#!/usr/bin/env python3
"""Render a daylight heatmap for a single date or a batch of dates.

Requires the [viz] optional dependencies:
    pip install -e ".[viz]"

Examples
--------
Single day, lower 48:
    .venv/Scripts/python viz/render_day.py --date 2026-06-08

Alaska, winter solstice:
    .venv/Scripts/python viz/render_day.py --date 2026-12-21 --region alaska

All three regions in one composite frame:
    .venv/Scripts/python viz/render_day.py --date 2026-06-08 --region all

Batch: all 365 days of 2026 (one PNG per day, named YYYYMMDD.png):
    .venv/Scripts/python viz/render_day.py --year 2026 --no-show

Date range for a specific region:
    .venv/Scripts/python viz/render_day.py --start 2026-06-01 --end 2026-08-31 --region alaska

Re-render frames that already exist:
    .venv/Scripts/python viz/render_day.py --year 2026 --overwrite --no-show

Color scale options (--scale):
    region      Fixed annual range for this region (default). Best for animation —
                frames are directly comparable. Lower 48: 8–16.5 h; Alaska: 0–24 h;
                Hawaii: 10.5–14 h.
    year        Fixed 0–24 h (full physical range). Works across all regions.
    day         Auto-scaled to each frame's actual data range. Maximum intra-frame
                contrast. WARNING: frames are NOT directly comparable — do not use
                for animation.
    reference   Fixes the colorbar to a reference day's actual data range (default:
                June 21). Animation-safe; maximum contrast on the reference day.
    percentile  Clips the top/bottom N % of the annual data distribution and uses
                those values as fixed vmin/vmax (default: 5 % each end, --clip-pct).
                Animation-safe; gives noticeably better WA-vs-TX contrast than
                'region' on most days without badly clipping any single frame.

    .venv/Scripts/python viz/render_day.py --date 2026-06-08 --scale day
    .venv/Scripts/python viz/render_day.py --year 2026 --scale year --no-show
    .venv/Scripts/python viz/render_day.py --date 2026-06-08 --vmin 10 --vmax 16
    .venv/Scripts/python viz/render_day.py --year 2026 --scale percentile --clip-pct 5
    .venv/Scripts/python viz/render_day.py --year 2026 --scale reference --ref-date 2026-06-21
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.shapereader as shpreader
import matplotlib.pyplot as plt
import numpy as np
import shapely.ops
from astral import LocationInfo
from astral.sun import sunset as _astral_sunset
from shapely.geometry import Point
from shapely.prepared import prep

from app.solar import _compute_day
from app.timezone import get_tzid

# ---------------------------------------------------------------------------
# Region definitions
# ---------------------------------------------------------------------------
# Each region has:
#   description   str      human-readable label
#   lat_range     (min, max) bounding-box for the compute grid
#   lon_range     (min, max) bounding-box for the compute grid
#   state_filter  callable(attrs dict) -> bool
#                          selects Natural Earth state records to include in
#                          the land mask
#   make_proj     callable() -> CRS  projection factory (called at render time)
#   extent        [w, e, s, n]  map extent in PlateCarree degrees
#   vmin/vmax     float   colorbar range (hours); span the full annual range
#                          for this region so animation frames share a fixed scale

_LOWER48_EXCLUDE = {
    "Alaska", "Hawaii",
    "Puerto Rico", "United States Virgin Islands",
    "Guam", "Commonwealth of the Northern Mariana Islands",
    "American Samoa",
}

REGIONS: dict[str, dict] = {
    "lower48": {
        "description": "Continental United States (lower 48)",
        "lat_range": (24.0, 50.0),
        "lon_range": (-125.0, -66.0),
        "state_filter": lambda a: (
            a["admin"] == "United States of America"
            and a["name"] not in _LOWER48_EXCLUDE
        ),
        "make_proj": lambda: ccrs.AlbersEqualArea(
            central_longitude=-96, standard_parallels=(29.5, 45.5)
        ),
        "extent": [-125, -66, 24, 50],
        # Full annual range across the lower 48 (Dec ~8h in Miami to Jun ~16h in Maine)
        "vmin": 8.0,
        "vmax": 16.5,
    },
    "alaska": {
        "description": "Alaska",
        # Far western Aleutians extend near 170 E; we clip the grid at -170 W.
        # The Natural Earth mask handles which points are actually land.
        "lat_range": (51.0, 72.0),
        "lon_range": (-170.0, -129.0),
        "state_filter": lambda a: (
            a["admin"] == "United States of America"
            and a["name"] == "Alaska"
        ),
        "make_proj": lambda: ccrs.AlbersEqualArea(
            central_longitude=-154, standard_parallels=(55, 65)
        ),
        "extent": [-170, -129, 51, 72],
        # Alaska sees polar night (0 h) in winter and polar day (24 h) in summer
        "vmin": 0.0,
        "vmax": 24.0,
    },
    "hawaii": {
        "description": "Hawaii",
        "lat_range": (18.5, 22.5),
        "lon_range": (-160.5, -154.5),
        "state_filter": lambda a: (
            a["admin"] == "United States of America"
            and a["name"] == "Hawaii"
        ),
        "make_proj": lambda: ccrs.AlbersEqualArea(
            central_longitude=-157.0, standard_parallels=(19.5, 22.0)
        ),
        "extent": [-160.5, -154.5, 18.5, 22.5],
        # Hawaii's annual range is narrow (tropical latitude)
        "vmin": 10.5,
        "vmax": 14.0,
    },
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a daily daylight heatmap (single frame or batch).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # --- Mode: exactly one of --date, --year, or --start is required ---
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Single date to render.",
    )
    mode.add_argument(
        "--year",
        type=int,
        metavar="YYYY",
        help="Render all days in a calendar year (batch mode).",
    )
    mode.add_argument(
        "--start",
        metavar="YYYY-MM-DD",
        help="Start date for a date range (batch mode; requires --end).",
    )

    # --end is paired with --start but not in the exclusive group
    parser.add_argument(
        "--end",
        metavar="YYYY-MM-DD",
        help="End date for a date range (requires --start).",
    )

    parser.add_argument(
        "--region",
        choices=list(REGIONS) + ["all"],
        default="lower48",
        help=(
            "Geographic region to render (default: lower48). "
            "'all' renders a composite frame with lower48, Alaska, and Hawaii."
        ),
    )
    parser.add_argument(
        "--step",
        type=float,
        default=0.25,
        metavar="DEG",
        help="Grid step in degrees (default: 0.25). Smaller = finer, slower.",
    )
    parser.add_argument(
        "--out",
        default="viz/frames/",
        metavar="PATH",
        help=(
            "Output path. If it is a directory (or ends with /), the filename "
            "is set to YYYYMMDD.png automatically (default: viz/frames/)."
        ),
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="Output image DPI (default: 150).",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Skip plt.show() — useful for batch/headless runs.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-render frames that already exist (batch mode only).",
    )

    # --- Color scale ---
    parser.add_argument(
        "--scale",
        choices=["region", "year", "day", "reference", "percentile"],
        default="region",
        help=(
            "Color scale mode (default: region). "
            "'region' uses a fixed annual range per region (animation-safe). "
            "'year' uses a fixed 0–24 h range (all regions comparable). "
            "'day' auto-scales each frame to its data — NOT animation-safe. "
            "'reference' fixes the colorbar to a reference day's actual data "
            "range (default: June 21) — animation-safe with maximum contrast "
            "on that day. "
            "'percentile' clips the top/bottom N%% of the annual distribution "
            "(see --clip-pct) for a tighter animation-safe scale with better "
            "within-day gradient than 'region'."
        ),
    )
    parser.add_argument(
        "--clip-pct",
        type=float,
        default=5.0,
        metavar="N",
        help=(
            "Percentage of annual data to clip at each end for --scale percentile "
            "(default: 5.0). Lower values → wider range, less clipping. "
            "Higher values → tighter range, more contrast but more clipping."
        ),
    )
    parser.add_argument(
        "--ref-date",
        metavar="YYYY-MM-DD",
        help=(
            "Reference date for --scale reference (default: June 21 of the "
            "relevant year). The colorbar range is derived from this day's "
            "actual data and held fixed across all frames."
        ),
    )
    parser.add_argument(
        "--vmin",
        type=float,
        metavar="H",
        help="Override colorbar minimum (hours). Overrides --scale.",
    )
    parser.add_argument(
        "--vmax",
        type=float,
        metavar="H",
        help="Override colorbar maximum (hours). Overrides --scale.",
    )

    return parser.parse_args(argv)


def resolve_output_path(out_arg: str, target_date: date) -> Path:
    """Return the resolved output Path.

    If *out_arg* looks like a directory (ends with / or \\ or has no suffix),
    the file is placed inside it named YYYYMMDD.png for lexicographic sorting.
    Otherwise the path is used as-is.
    """
    p = Path(out_arg)
    if out_arg.endswith(("/", "\\")) or p.suffix == "":
        p.mkdir(parents=True, exist_ok=True)
        return p / f"{target_date.strftime('%Y%m%d')}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Color-scale resolution
# ---------------------------------------------------------------------------

def _resolve_vmin_vmax(
    scale: str,
    region_key: str,
    grid: np.ndarray | None = None,
    vmin_arg: float | None = None,
    vmax_arg: float | None = None,
) -> tuple[float, float]:
    """Return (vmin, vmax) in hours for the pcolormesh colorbar.

    Priority:
      1. Explicit --vmin / --vmax override (both must be given).
      2. scale='year'   → 0–24 h (full physical range).
      3. scale='day'    → auto-scale to the actual data in *grid*.
      4. scale='region' → the fixed annual range stored in REGIONS.
    """
    if vmin_arg is not None and vmax_arg is not None:
        return float(vmin_arg), float(vmax_arg)

    if scale == "year":
        return 0.0, 24.0

    if scale in ("day", "reference"):
        if grid is not None:
            valid = grid[~np.isnan(grid)]
            if valid.size:
                lo = max(0.0, float(np.floor(valid.min() * 4) / 4))   # round down to ¼ h
                hi = min(24.0, float(np.ceil(valid.max() * 4) / 4))   # round up to ¼ h
                if hi > lo:
                    return lo, hi
        return 0.0, 24.0  # fallback if no valid data

    # "region" (default)
    cfg = REGIONS[region_key]
    return cfg["vmin"], cfg["vmax"]


def _default_ref_date(context_dates: list[date]) -> date:
    """Return June 21 of the year of the middle date in *context_dates*."""
    mid = context_dates[len(context_dates) // 2]
    return date(mid.year, 6, 21)


def _sample_annual_data(spec: "GridSpec", year: int) -> np.ndarray:
    """Sample the 21st of each month and return all valid daylight values.

    Used to estimate the annual data distribution for percentile-scale
    calculation.  Sampling 12 evenly-spaced dates gives a good approximation
    of the full-year distribution without computing all 365 frames.
    """
    sample_dates = [date(year, m, 21) for m in range(1, 13)]
    all_vals: list[np.ndarray] = []
    for d in sample_dates:
        grid = compute_grid_for_date(spec, d)
        valid = grid[~np.isnan(grid)]
        if valid.size:
            all_vals.append(valid)
    return np.concatenate(all_vals) if all_vals else np.array([])


def _percentile_vmin_vmax(all_vals: np.ndarray, clip_pct: float) -> tuple[float, float]:
    """Return (vmin, vmax) from percentile clipping of *all_vals*.

    Values are rounded to the nearest 0.25 h for clean colorbar ticks.
    """
    if all_vals.size == 0:
        return 0.0, 24.0
    lo = float(np.percentile(all_vals, clip_pct))
    hi = float(np.percentile(all_vals, 100.0 - clip_pct))
    lo = max(0.0, round(lo * 4) / 4)
    hi = min(24.0, round(hi * 4) / 4)
    if hi <= lo:
        return 0.0, 24.0
    return lo, hi


def _daylight_cmap_settings(
    vmin: float, vmax: float
) -> tuple[object, float, float, str]:
    """Return (cmap, effective_vmin, effective_vmax, colorbar_extend).

    The plasma colormap is extended with two special sentinel colours:
      • Black  (set_under)  — polar night, grid value = 0.0 h.
      • White  (set_over)   — polar day,   grid value = 24.0 h.

    To ensure sentinel values fall *outside* the colormap range:
      • When vmin < 0.25 h it is raised to 0.25 h so that exact 0.0 values
        render in black rather than mapping to the darkest plasma colour.
      • When vmax ≥ 24.0 h it is lowered to 23.75 h so that exact 24.0 values
        render in white rather than mapping to the brightest plasma colour.

    The returned *colorbar_extend* string ("neither", "min", "max", or "both")
    should be passed to plt.colorbar(extend=...) so that the black / white
    sentinel colours appear as triangular extensions on the colorbar.
    """
    cmap = plt.cm.plasma.copy()
    cmap.set_under("black")  # polar night
    cmap.set_over("white")   # polar day

    eff_vmin = 0.25 if vmin < 0.25 else vmin
    eff_vmax = 23.75 if vmax >= 24.0 else vmax

    under = eff_vmin > vmin   # vmin was bumped up  → under colour is reachable
    over  = eff_vmax < vmax   # vmax was pulled down → over  colour is reachable

    if under and over:
        extend = "both"
    elif under:
        extend = "min"
    elif over:
        extend = "max"
    else:
        extend = "neither"

    return cmap, eff_vmin, eff_vmax, extend


# ---------------------------------------------------------------------------
# Step 1: Build a prepared land mask for the region
# ---------------------------------------------------------------------------

def build_land_mask(region_key: str):
    """Return a shapely PreparedGeometry covering the region's land area.

    Uses Natural Earth 50 m admin_1_states_provinces; cached by cartopy.
    """
    cfg = REGIONS[region_key]
    print(f"Loading land mask for '{region_key}' ({cfg['description']}) ...")
    shpfile = shpreader.natural_earth(
        resolution="50m", category="cultural", name="admin_1_states_provinces"
    )
    reader = shpreader.Reader(shpfile)
    geometries = [
        rec.geometry
        for rec in reader.records()
        if cfg["state_filter"](rec.attributes)
    ]
    if not geometries:
        raise ValueError(
            f"No Natural Earth records matched the filter for region '{region_key}'."
        )
    print(f"  Loaded {len(geometries)} polygon(s)")
    return prep(shapely.ops.unary_union(geometries))


# ---------------------------------------------------------------------------
# Core per-point daylight computation (shared by grid functions below)
# ---------------------------------------------------------------------------

def _compute_point_daylight(
    location: LocationInfo,
    tz: ZoneInfo,
    target_date: date,
) -> float | None:
    """Return hours of daylight at one point, or None for no data.

    Handles polar day/night and the sunset-past-midnight edge case that
    affects high-latitude locations (e.g. interior Alaska) in summer.
    """
    day = _compute_day(location, target_date, tz)

    if day.polar_event == "polar_day":
        return 24.0
    if day.polar_event == "polar_night":
        return 0.0
    if day.day_length_sec is not None and day.day_length_sec > 0:
        return day.day_length_sec / 3600.0
    if day.day_length_sec == 0 and day.sunrise is not None:
        # Sunset-past-midnight edge case: for high-latitude locations in summer
        # the sun sets after midnight, so Astral returns yesterday's tail-end
        # sunset (< today's sunrise).  Ask for tomorrow's sunset and compute
        # the true day length from today's sunrise to it.
        try:
            tomorrow_ss = _astral_sunset(
                location.observer,
                date=target_date + timedelta(days=1),
                tzinfo=tz,
            )
            true_sec = int((tomorrow_ss - day.sunrise).total_seconds())
            return max(0.0, true_sec / 3600.0)
        except ValueError:
            return 24.0  # polar day on tomorrow — treat as 24 h
    return None


# ---------------------------------------------------------------------------
# GridSpec: pre-built land+timezone index for efficient batch rendering
# ---------------------------------------------------------------------------

@dataclass
class GridSpec:
    """Pre-computed land-point index for a region.

    Build once with build_grid_spec(), then reuse across many dates via
    compute_grid_for_date() — avoids rebuilding the shapefile mask and
    timezone cache for every frame in a batch run.
    """
    region_key: str
    step: float
    lats: np.ndarray
    lons: np.ndarray
    # Each entry: (row_idx, col_idx, LocationInfo, ZoneInfo)
    points: list = field(default_factory=list)


def build_grid_spec(region_key: str, step: float) -> GridSpec:
    """Build the land mask and timezone cache for a region once.

    Returns a GridSpec suitable for reuse across many dates in batch mode.
    Building the spec takes roughly as long as computing a single frame;
    every subsequent frame via compute_grid_for_date() skips the mask and
    timezone setup entirely.
    """
    cfg = REGIONS[region_key]
    lat_min, lat_max = cfg["lat_range"]
    lon_min, lon_max = cfg["lon_range"]

    lats = np.arange(lat_min, lat_max + step / 2, step)
    lons = np.arange(lon_min, lon_max + step / 2, step)
    total = len(lats) * len(lons)

    print(
        f"\nBuilding grid spec: '{region_key}'  "
        f"{len(lats)}\u00d7{len(lons)} = {total:,} candidate points  step={step}\u00b0"
    )
    mask = build_land_mask(region_key)

    tz_cache: dict[tuple, str | None] = {}
    points: list = []

    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            if not mask.contains(Point(lon, lat)):
                continue

            key = (round(lat * 2) / 2, round(lon * 2) / 2)
            if key not in tz_cache:
                try:
                    tz_cache[key] = get_tzid(lat, lon)
                except ValueError:
                    tz_cache[key] = None

            tzid = tz_cache[key]
            if tzid is None:
                continue

            points.append((
                i, j,
                LocationInfo(latitude=lat, longitude=lon, timezone=tzid),
                ZoneInfo(tzid),
            ))

        if (i + 1) % max(1, len(lats) // 5) == 0 or i == len(lats) - 1:
            pct = (i + 1) / len(lats) * 100
            print(f"  Row {i+1:4d}/{len(lats)} ({pct:.0f}%)  land pts so far: {len(points):,}")

    print(f"  Spec complete: {len(points):,} land points.")
    return GridSpec(region_key=region_key, step=step, lats=lats, lons=lons, points=points)


def compute_grid_for_date(spec: GridSpec, target_date: date) -> np.ndarray:
    """Compute a daylight grid for *target_date* using a pre-built GridSpec.

    Returns grid[i, j] = hours of daylight, or NaN for non-land points.
    Much faster than compute_daylight_grid() for repeated calls because the
    land mask and timezone cache are pre-built in the GridSpec.
    """
    grid = np.full((len(spec.lats), len(spec.lons)), np.nan)
    for i, j, location, tz in spec.points:
        val = _compute_point_daylight(location, tz, target_date)
        if val is not None:
            grid[i, j] = val
    return grid


# ---------------------------------------------------------------------------
# Step 2: Compute day-length grid (single-frame path, builds its own mask)
# ---------------------------------------------------------------------------

def compute_daylight_grid(
    region_key: str,
    target_date: date,
    step: float,
    land_mask,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (lats, lons, grid) for the region on target_date.

    *grid[i, j]* is hours of daylight, or NaN for non-land or no-data points.
    Polar day -> 24.0; polar night -> 0.0.

    For batch rendering prefer build_grid_spec() + compute_grid_for_date()
    which avoids rebuilding the mask and timezone cache each call.
    """
    cfg = REGIONS[region_key]
    lat_min, lat_max = cfg["lat_range"]
    lon_min, lon_max = cfg["lon_range"]

    lats = np.arange(lat_min, lat_max + step / 2, step)
    lons = np.arange(lon_min, lon_max + step / 2, step)
    grid = np.full((len(lats), len(lons)), np.nan)

    tz_cache: dict[tuple, str | None] = {}
    us_count = 0

    print(
        f"Computing {target_date} daylight on a {len(lats)}x{len(lons)} grid "
        f"(step={step}\u00b0) ..."
    )

    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            if not land_mask.contains(Point(lon, lat)):
                continue

            key = (round(lat * 2) / 2, round(lon * 2) / 2)
            if key not in tz_cache:
                try:
                    tz_cache[key] = get_tzid(lat, lon)
                except ValueError:
                    tz_cache[key] = None

            tzid = tz_cache[key]
            if tzid is None:
                continue

            location = LocationInfo(latitude=lat, longitude=lon, timezone=tzid)
            tz = ZoneInfo(tzid)
            val = _compute_point_daylight(location, tz, target_date)
            if val is not None:
                grid[i, j] = val
            us_count += 1

        if (i + 1) % max(1, len(lats) // 10) == 0 or i == len(lats) - 1:
            pct = (i + 1) / len(lats) * 100
            print(f"  Row {i+1:4d}/{len(lats)} ({pct:.0f}%)  land points: {us_count}")

    valid = grid[~np.isnan(grid)]
    if valid.size:
        print(f"\nLand points: {us_count}  |  range: {valid.min():.2f}h - {valid.max():.2f}h")
    else:
        print("\nWarning: no valid data points computed.")
    return lats, lons, grid


# ---------------------------------------------------------------------------
# Step 3: Render
# ---------------------------------------------------------------------------

def render_heatmap(
    region_key: str,
    target_date: date,
    lats: np.ndarray,
    lons: np.ndarray,
    grid: np.ndarray,
    out_path: Path,
    dpi: int = 150,
    show: bool = False,
    vmin: float | None = None,
    vmax: float | None = None,
    scale: str = "region",
    clip_pct: float | None = None,
) -> None:
    cfg = REGIONS[region_key]
    if vmin is None:
        vmin = cfg["vmin"]
    if vmax is None:
        vmax = cfg["vmax"]

    projection = cfg["make_proj"]()

    fig, ax = plt.subplots(figsize=(14, 9), subplot_kw={"projection": projection})
    ax.set_extent(cfg["extent"], crs=ccrs.PlateCarree())

    lons_2d, lats_2d = np.meshgrid(lons, lats)
    masked_grid = np.ma.masked_invalid(grid)

    # Polar sentinels: black = polar night (0 h), white = polar day (24 h)
    cmap, eff_vmin, eff_vmax, cbar_extend = _daylight_cmap_settings(vmin, vmax)

    mesh = ax.pcolormesh(
        lons_2d, lats_2d, masked_grid,
        transform=ccrs.PlateCarree(),
        cmap=cmap,
        vmin=eff_vmin,
        vmax=eff_vmax,
        shading="auto",
    )

    # Map features (drawn on top of the heatmap)
    ax.add_feature(cfeature.OCEAN, facecolor="#d0e8f0", zorder=0)
    ax.add_feature(cfeature.LAKES, facecolor="#d0e8f0", linewidth=0.3, zorder=1)
    ax.add_feature(cfeature.STATES, linewidth=0.4, edgecolor="#888888", zorder=2)
    ax.add_feature(cfeature.BORDERS, linewidth=0.9, edgecolor="#444444", zorder=3)
    ax.add_feature(cfeature.COASTLINE, linewidth=0.7, edgecolor="#444444", zorder=4)

    # Colorbar
    cbar = plt.colorbar(
        mesh, ax=ax, orientation="vertical",
        pad=0.02, fraction=0.025, aspect=35,
        extend=cbar_extend,
    )
    cbar.set_label("Hours of Daylight", fontsize=12)
    cbar.ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v:.1f}h")
    )

    date_str = f"{target_date.strftime('%B')} {target_date.day}, {target_date.year}"
    if scale == "day":
        scale_note = f"  |  auto-scale {vmin:.1f}\u2013{vmax:.1f} h"
    elif scale == "reference":
        scale_note = f"  |  ref-scale {vmin:.1f}\u2013{vmax:.1f} h"
    elif scale == "percentile":
        pct_str = f"{clip_pct:.0f}%" if clip_pct is not None else "N%"
        scale_note = f"  |  {pct_str}-clip {vmin:.1f}\u2013{vmax:.1f} h"
    else:
        scale_note = ""
    ax.set_title(
        f"Hours of Daylight  \u2014  {date_str}\n"
        f"{cfg['description']}  |  {cfg['lat_range'][0]}\u00b0\u2013"
        f"{cfg['lat_range'][1]}\u00b0N  |  {abs(cfg['lon_range'][1])}\u00b0\u2013"
        f"{abs(cfg['lon_range'][0])}\u00b0W  |  step={step_label(lats)}"
        f"{scale_note}  |  Astral/NREL SPA",
        fontsize=12,
        fontweight="bold",
        pad=16,
    )

    plt.tight_layout()
    plt.savefig(out_path, dpi=dpi, bbox_inches="tight")
    print(f"Saved: {out_path}")
    if show:
        plt.show()
    plt.close(fig)


def step_label(lats: np.ndarray) -> str:
    """Infer the step size from the lats array and format it for the title."""
    if len(lats) < 2:
        return "?"
    s = round(lats[1] - lats[0], 4)
    return f"{s}\u00b0"


# ---------------------------------------------------------------------------
# Composite: lower 48 + Alaska inset + Hawaii inset
# ---------------------------------------------------------------------------
# Panel positions in figure coordinates [left, bottom, width, height].
# Designed for a 16×10-inch figure.
_COMPOSITE_PANELS: dict[str, list[float]] = {
    "lower48": [0.01, 0.10, 0.79, 0.86],
    "alaska":  [0.01, 0.01, 0.27, 0.25],
    "hawaii":  [0.28, 0.01, 0.17, 0.10],
}
_COMPOSITE_CBAR: list[float] = [0.84, 0.18, 0.025, 0.60]


def _render_composite_from_grids(
    target_date: date,
    grids: dict[str, tuple],
    step: float,
    step_hi: float,
    out_path: Path,
    dpi: int = 150,
    show: bool = False,
    vmin: float = 0.0,
    vmax: float = 24.0,
    scale: str = "year",
    clip_pct: float | None = None,
) -> None:
    """Render a composite frame from pre-computed grids.

    *grids* maps region_key -> (lats, lons, grid).
    """

    fig = plt.figure(figsize=(16, 10), facecolor="white")
    mesh_ref = None
    axes: dict[str, object] = {}

    # Polar sentinels: black = polar night (0 h), white = polar day (24 h)
    cmap, eff_vmin, eff_vmax, cbar_extend = _daylight_cmap_settings(vmin, vmax)

    for region_key, (left, bot, w, h) in _COMPOSITE_PANELS.items():
        ax = fig.add_axes(
            [left, bot, w, h],
            projection=REGIONS[region_key]["make_proj"](),
        )
        axes[region_key] = ax

        lats, lons, grid = grids[region_key]
        lons_2d, lats_2d = np.meshgrid(lons, lats)
        masked = np.ma.masked_invalid(grid)

        mesh = ax.pcolormesh(
            lons_2d, lats_2d, masked,
            transform=ccrs.PlateCarree(),
            cmap=cmap,
            vmin=eff_vmin,
            vmax=eff_vmax,
            shading="auto",
        )
        if mesh_ref is None:
            mesh_ref = mesh

        ax.set_extent(REGIONS[region_key]["extent"], crs=ccrs.PlateCarree())
        ax.add_feature(cfeature.OCEAN, facecolor="#d0e8f0", zorder=0)
        ax.add_feature(cfeature.LAKES, facecolor="#d0e8f0", linewidth=0.3, zorder=1)
        ax.add_feature(cfeature.STATES, linewidth=0.4, edgecolor="#888888", zorder=2)
        ax.add_feature(cfeature.BORDERS, linewidth=0.9, edgecolor="#444444", zorder=3)
        ax.add_feature(cfeature.COASTLINE, linewidth=0.7, edgecolor="#444444", zorder=4)

    # Box borders around the insets
    for region_key in ("alaska", "hawaii"):
        l, b, w, h = _COMPOSITE_PANELS[region_key]
        rect = plt.Rectangle(
            (l - 0.002, b - 0.003), w + 0.004, h + 0.006,
            fill=False, edgecolor="#333333", linewidth=1.5,
            transform=fig.transFigure, figure=fig,
        )
        fig.add_artist(rect)

    axes["alaska"].set_title("Alaska", fontsize=9, pad=3, fontweight="bold")
    axes["hawaii"].set_title("Hawaii", fontsize=9, pad=3, fontweight="bold")

    ax_cb = fig.add_axes(_COMPOSITE_CBAR)
    cbar = fig.colorbar(mesh_ref, cax=ax_cb, extend=cbar_extend)
    cbar.set_label("Hours of Daylight", fontsize=12)
    cbar.ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{int(v)}h")
    )

    date_str = f"{target_date.strftime('%B')} {target_date.day}, {target_date.year}"
    if scale == "day":
        scale_note = f"  |  auto-scale {vmin:.1f}\u2013{vmax:.1f} h"
    elif scale == "reference":
        scale_note = f"  |  ref-scale {vmin:.1f}\u2013{vmax:.1f} h"
    elif scale == "percentile":
        pct_str = f"{clip_pct:.0f}%" if clip_pct is not None else "N%"
        scale_note = f"  |  {pct_str}-clip {vmin:.1f}\u2013{vmax:.1f} h"
    else:
        scale_note = ""
    fig.suptitle(
        f"Hours of Daylight  \u2014  {date_str}  |  United States  |  "
        f"step={step}\u00b0 / HI {step_hi}\u00b0{scale_note}  |  Astral/NREL SPA",
        fontsize=13,
        fontweight="bold",
        y=0.995,
    )

    plt.savefig(out_path, dpi=dpi, bbox_inches="tight")
    print(f"\nSaved: {out_path}")
    if show:
        plt.show()
    plt.close(fig)


def render_composite(
    target_date: date,
    step: float,
    out_path: Path,
    dpi: int = 150,
    show: bool = False,
    scale: str = "year",
    vmin_arg: float | None = None,
    vmax_arg: float | None = None,
    clip_pct: float | None = None,
) -> None:
    """Render lower 48, Alaska, and Hawaii in one composite frame.

    Uses a fixed 0–24 h color scale by default so all dates are comparable.
    Pass scale='day' for maximum contrast (frames won't be animation-comparable).
    """
    step_hi = min(step, 0.1)
    grids: dict[str, tuple] = {}
    for region_key, region_step in [
        ("lower48", step),
        ("alaska", step),
        ("hawaii", step_hi),
    ]:
        print(f"\n--- {REGIONS[region_key]['description']} (step={region_step}\u00b0) ---")
        mask = build_land_mask(region_key)
        lats, lons, grid = compute_daylight_grid(region_key, target_date, region_step, mask)
        grids[region_key] = (lats, lons, grid)

    # For day scale, compute vmin/vmax across all three grids combined
    all_grid = np.concatenate([g[~np.isnan(g)] for _, _, g in grids.values()])
    combined = all_grid if all_grid.size else None
    vmin, vmax = _resolve_vmin_vmax(
        scale, "lower48",
        grid=np.array(combined) if combined is not None else None,
        vmin_arg=vmin_arg, vmax_arg=vmax_arg,
    )
    _render_composite_from_grids(
        target_date, grids, step, step_hi, out_path, dpi, show,
        vmin=vmin, vmax=vmax, scale=scale, clip_pct=clip_pct,
    )


# ---------------------------------------------------------------------------
# Batch frame generation
# ---------------------------------------------------------------------------

def generate_frames(
    region: str,
    dates: list[date],
    step: float,
    out_dir: str,
    dpi: int,
    overwrite: bool,
    scale: str = "region",
    vmin_arg: float | None = None,
    vmax_arg: float | None = None,
    ref_date: date | None = None,
    clip_pct: float = 5.0,
) -> None:
    """Generate one PNG frame per date.

    Builds the land mask and timezone cache once per region (via GridSpec),
    then loops through dates — significantly faster than rebuilding the mask
    on every frame.

    Existing frames are skipped by default; pass overwrite=True to re-render.
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Determine which dates still need rendering
    to_render: list[date] = []
    skipped = 0
    for d in dates:
        frame_path = out_path / f"{d.strftime('%Y%m%d')}.png"
        if not overwrite and frame_path.exists():
            skipped += 1
        else:
            to_render.append(d)

    if skipped:
        print(f"Skipping {skipped} existing frame(s).  Use --overwrite to re-render.")
    if not to_render:
        print("All frames already exist. Nothing to render.")
        return

    print(
        f"\nGenerating {len(to_render)} frame(s)  "
        f"region={region!r}  step={step}\u00b0  out={out_path}"
    )

    # Build grid spec(s) once
    if region == "all":
        step_hi = min(step, 0.1)
        specs = {
            "lower48": build_grid_spec("lower48", step),
            "alaska":  build_grid_spec("alaska",  step),
            "hawaii":  build_grid_spec("hawaii",  step_hi),
        }
    else:
        step_hi = step  # unused for single region but keeps reference clear
        spec = build_grid_spec(region, step)

    # --- Pre-compute a fixed (vmin, vmax) for scales that don't change per frame ---
    # For 'reference': derive from the reference day's actual data (computed once).
    # For 'region'/'year': derive analytically (no grid needed).
    # For 'day': leave None — computed fresh each frame from that frame's grid.
    batch_vmin_arg = vmin_arg
    batch_vmax_arg = vmax_arg

    if scale == "reference" and (vmin_arg is None or vmax_arg is None):
        if ref_date is None:
            ref_date = _default_ref_date(dates)
        print(f"\nComputing reference scale from {ref_date} ...")
        if region == "all":
            ref_arrays = [compute_grid_for_date(s, ref_date) for s in specs.values()]
            ref_vals = np.concatenate([a[~np.isnan(a)] for a in ref_arrays])
            batch_vmin_arg, batch_vmax_arg = _resolve_vmin_vmax(
                "reference", "lower48", grid=ref_vals if ref_vals.size else None,
            )
        else:
            ref_grid = compute_grid_for_date(spec, ref_date)
            batch_vmin_arg, batch_vmax_arg = _resolve_vmin_vmax(
                "reference", region, grid=ref_grid,
            )
        print(f"  Reference scale: {batch_vmin_arg:.2f}\u2013{batch_vmax_arg:.2f} h")

    elif scale == "percentile" and (vmin_arg is None or vmax_arg is None):
        target_year = dates[len(dates) // 2].year
        print(
            f"\nSampling annual data for percentile scale "
            f"(year={target_year}, clip={clip_pct:.1f}%) ..."
        )
        if region == "all":
            all_vals_list = [_sample_annual_data(s, target_year) for s in specs.values()]
            all_vals = np.concatenate(all_vals_list) if all_vals_list else np.array([])
        else:
            all_vals = _sample_annual_data(spec, target_year)
        batch_vmin_arg, batch_vmax_arg = _percentile_vmin_vmax(all_vals, clip_pct)
        print(
            f"  Percentile scale ({clip_pct:.0f}%–{100-clip_pct:.0f}%): "
            f"{batch_vmin_arg:.2f}\u2013{batch_vmax_arg:.2f} h"
        )

    print(f"\nRendering frames ...")
    t0 = time.monotonic()

    for frame_idx, d in enumerate(to_render, 1):
        frame_path = out_path / f"{d.strftime('%Y%m%d')}.png"

        if region == "all":
            grids = {
                k: (s.lats, s.lons, compute_grid_for_date(s, d))
                for k, s in specs.items()
            }
            # For day scale, derive vmin/vmax from all three grids combined.
            # For all other scales, batch_vmin/vmax_arg is already set.
            all_vals = np.concatenate([g[~np.isnan(g)] for _, _, g in grids.values()])
            day_grid = all_vals if all_vals.size else None
            vmin, vmax = _resolve_vmin_vmax(
                scale, "lower48",
                grid=day_grid, vmin_arg=batch_vmin_arg, vmax_arg=batch_vmax_arg,
            )
            _render_composite_from_grids(
                d, grids, step, step_hi, frame_path, dpi, show=False,
                vmin=vmin, vmax=vmax, scale=scale, clip_pct=clip_pct,
            )
        else:
            grid = compute_grid_for_date(spec, d)
            vmin, vmax = _resolve_vmin_vmax(
                scale, region, grid=grid, vmin_arg=batch_vmin_arg, vmax_arg=batch_vmax_arg,
            )
            render_heatmap(
                region, d, spec.lats, spec.lons, grid,
                out_path=frame_path, dpi=dpi, show=False,
                vmin=vmin, vmax=vmax, scale=scale, clip_pct=clip_pct,
            )

        elapsed = time.monotonic() - t0
        avg_s = elapsed / frame_idx
        remaining_s = avg_s * (len(to_render) - frame_idx)
        if remaining_s >= 60:
            eta = f"{int(remaining_s // 60)}m {int(remaining_s % 60):02d}s"
        else:
            eta = f"{remaining_s:.0f}s"
        print(f"  [{frame_idx:4d}/{len(to_render)}] {d}  ETA {eta}")

    total_s = time.monotonic() - t0
    print(
        f"\nDone. {len(to_render)} frame(s) in {total_s:.0f}s "
        f"(avg {total_s / len(to_render):.1f}s/frame)"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv=None) -> None:
    args = parse_args(argv)

    # --- Resolve the date(s) for the requested mode ---
    if args.date is not None:
        # Single-frame mode
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"Error: invalid date '{args.date}'. Use YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)
        dates = None

    elif args.year is not None:
        # Year batch mode
        if not (1 <= args.year <= 9999):
            print(f"Error: invalid year '{args.year}'.", file=sys.stderr)
            sys.exit(1)
        start = date(args.year, 1, 1)
        end = date(args.year, 12, 31)
        dates = [start + timedelta(days=n) for n in range((end - start).days + 1)]
        target_date = None

    else:
        # Date-range batch mode (--start requires --end)
        if not args.end:
            print("Error: --start requires --end.", file=sys.stderr)
            sys.exit(1)
        try:
            start_date = date.fromisoformat(args.start)
            end_date = date.fromisoformat(args.end)
        except ValueError as exc:
            print(f"Error: invalid date: {exc}", file=sys.stderr)
            sys.exit(1)
        if end_date < start_date:
            print("Error: --end must be on or after --start.", file=sys.stderr)
            sys.exit(1)
        dates = [
            start_date + timedelta(days=n)
            for n in range((end_date - start_date).days + 1)
        ]
        target_date = None

    # --- Resolve --ref-date (used by --scale reference) ---
    ref_date: date | None = None
    if args.ref_date:
        try:
            ref_date = date.fromisoformat(args.ref_date)
        except ValueError:
            print(f"Error: invalid --ref-date '{args.ref_date}'. Use YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)

    # --- Dispatch to batch or single-frame path ---
    if dates is not None:
        # Batch: generate_frames handles reference scale pre-computation internally
        if ref_date is None and args.scale == "reference":
            ref_date = _default_ref_date(dates)
        generate_frames(
            region=args.region,
            dates=dates,
            step=args.step,
            out_dir=args.out,
            dpi=args.dpi,
            overwrite=args.overwrite,
            scale=args.scale,
            vmin_arg=args.vmin,
            vmax_arg=args.vmax,
            ref_date=ref_date,
            clip_pct=args.clip_pct,
        )
    elif args.region == "all":
        out_path = resolve_output_path(args.out, target_date)
        # Pre-compute vmin/vmax for scales that require it
        vmin_arg, vmax_arg = args.vmin, args.vmax
        step_hi = min(args.step, 0.1)

        if args.scale == "reference" and (vmin_arg is None or vmax_arg is None):
            if ref_date is None:
                ref_date = _default_ref_date([target_date])
            print(f"Computing reference scale from {ref_date} ...")
            ref_masks_grids = []
            for rk, rs in [("lower48", args.step), ("alaska", args.step), ("hawaii", step_hi)]:
                m = build_land_mask(rk)
                _, _, rg = compute_daylight_grid(rk, ref_date, rs, m)
                ref_masks_grids.append(rg)
            all_ref = np.concatenate([g[~np.isnan(g)] for g in ref_masks_grids])
            vmin_arg, vmax_arg = _resolve_vmin_vmax(
                "reference", "lower48", grid=all_ref if all_ref.size else None,
            )
            print(f"  Reference scale: {vmin_arg:.2f}\u2013{vmax_arg:.2f} h")

        elif args.scale == "percentile" and (vmin_arg is None or vmax_arg is None):
            print(
                f"Building GridSpecs for percentile scale "
                f"(clip={args.clip_pct:.1f}%) ..."
            )
            all_specs = {
                "lower48": build_grid_spec("lower48", args.step),
                "alaska":  build_grid_spec("alaska",  args.step),
                "hawaii":  build_grid_spec("hawaii",  step_hi),
            }
            all_vals_list = [
                _sample_annual_data(s, target_date.year) for s in all_specs.values()
            ]
            all_vals = np.concatenate(all_vals_list) if all_vals_list else np.array([])
            vmin_arg, vmax_arg = _percentile_vmin_vmax(all_vals, args.clip_pct)
            print(
                f"  Percentile scale ({args.clip_pct:.0f}%–{100-args.clip_pct:.0f}%): "
                f"{vmin_arg:.2f}\u2013{vmax_arg:.2f} h"
            )

        render_composite(
            target_date, args.step, out_path,
            dpi=args.dpi,
            show=not args.no_show,
            scale=args.scale,
            vmin_arg=vmin_arg,
            vmax_arg=vmax_arg,
            clip_pct=args.clip_pct,
        )
    else:
        out_path = resolve_output_path(args.out, target_date)
        vmin_arg, vmax_arg = args.vmin, args.vmax

        if args.scale == "percentile" and (vmin_arg is None or vmax_arg is None):
            # Build a GridSpec once; use it for both annual sampling and the target frame.
            print(
                f"\nBuilding GridSpec for percentile scale "
                f"(clip={args.clip_pct:.1f}%) ..."
            )
            spec = build_grid_spec(args.region, args.step)
            print(f"Sampling annual data (year={target_date.year}) ...")
            all_vals = _sample_annual_data(spec, target_date.year)
            vmin_arg, vmax_arg = _percentile_vmin_vmax(all_vals, args.clip_pct)
            print(
                f"  Percentile scale ({args.clip_pct:.0f}%–{100-args.clip_pct:.0f}%): "
                f"{vmin_arg:.2f}\u2013{vmax_arg:.2f} h"
            )
            lats, lons = spec.lats, spec.lons
            grid = compute_grid_for_date(spec, target_date)
        else:
            land_mask = build_land_mask(args.region)
            lats, lons, grid = compute_daylight_grid(
                args.region, target_date, args.step, land_mask
            )
            # For reference scale: compute the ref day's grid with the same mask
            if args.scale == "reference" and (vmin_arg is None or vmax_arg is None):
                if ref_date is None:
                    ref_date = _default_ref_date([target_date])
                print(f"Computing reference scale from {ref_date} ...")
                _, _, ref_grid = compute_daylight_grid(
                    args.region, ref_date, args.step, land_mask
                )
                vmin_arg, vmax_arg = _resolve_vmin_vmax(
                    "reference", args.region, grid=ref_grid
                )
                print(f"  Reference scale: {vmin_arg:.2f}\u2013{vmax_arg:.2f} h")

        vmin, vmax = _resolve_vmin_vmax(
            args.scale, args.region, grid=grid,
            vmin_arg=vmin_arg, vmax_arg=vmax_arg,
        )
        render_heatmap(
            args.region, target_date, lats, lons, grid,
            out_path=out_path,
            dpi=args.dpi,
            show=not args.no_show,
            vmin=vmin, vmax=vmax, scale=args.scale, clip_pct=args.clip_pct,
        )


if __name__ == "__main__":
    main()

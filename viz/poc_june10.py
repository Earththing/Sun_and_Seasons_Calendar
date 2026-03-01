#!/usr/bin/env python3
"""
POC: US lower-48 daylight heatmap for a single date.

Requires the [viz] optional dependencies:
    pip install -e ".[viz]"

Run from the project root:
    .venv/Scripts/python viz/poc_june10.py
"""

import os
import sys

# Allow imports from the project root (app.solar, app.timezone)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.shapereader as shpreader
import shapely.ops
from shapely.geometry import Point
from shapely.prepared import prep
from datetime import date
from zoneinfo import ZoneInfo

from astral import LocationInfo
from app.solar import _compute_day
from app.timezone import get_tzid

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TARGET_DATE = date(2026, 6, 10)

# Grid bounds (lower 48)
LAT_MIN, LAT_MAX = 24.0, 50.0
LON_MIN, LON_MAX = -125.0, -66.0
STEP = 0.5  # degrees  (~55 km N-S, ~45 km E-W in the US)

OUTPUT_PATH = "viz/poc_june10.png"

# States/territories to exclude from the lower-48 mask
EXCLUDE_NAMES = {
    "Alaska", "Hawaii",
    "Puerto Rico", "United States Virgin Islands",
    "Guam", "Commonwealth of the Northern Mariana Islands",
    "American Samoa",
}

# ---------------------------------------------------------------------------
# Step 1: Build a prepared shapely geometry for the lower 48
# ---------------------------------------------------------------------------

def build_us_geometry():
    """Load and union the lower-48 state polygons from Natural Earth 50 m data.

    Cartopy downloads and caches the shapefile on first use (~2 MB).
    Returns a shapely PreparedGeometry for fast point-in-polygon tests.
    """
    print("Loading US state boundaries (Natural Earth 50 m) ...")
    shpfile = shpreader.natural_earth(
        resolution="50m", category="cultural", name="admin_1_states_provinces"
    )
    reader = shpreader.Reader(shpfile)

    geometries = [
        rec.geometry
        for rec in reader.records()
        if rec.attributes["admin"] == "United States of America"
        and rec.attributes["name"] not in EXCLUDE_NAMES
    ]

    print(f"  Loaded {len(geometries)} state geometries")
    union = shapely.ops.unary_union(geometries)
    return prep(union)


# ---------------------------------------------------------------------------
# Step 2: Compute day length for every grid point inside the US
# ---------------------------------------------------------------------------

def compute_daylight_grid(us_prepared):
    """Return (lats, lons, grid) where grid[i,j] is hours of daylight on
    TARGET_DATE at that lat/lon, or NaN for non-US / no-data points.
    """
    lats = np.arange(LAT_MIN, LAT_MAX + STEP / 2, STEP)
    lons = np.arange(LON_MIN, LON_MAX + STEP / 2, STEP)
    grid = np.full((len(lats), len(lons)), np.nan)

    # Cache timezone lookups — adjacent grid points usually share a tzid
    tz_cache: dict[tuple[float, float], str | None] = {}

    total = len(lats) * len(lons)
    us_count = 0
    print(f"Grid: {len(lats)} lat x {len(lons)} lon = {total} points, step={STEP}°")
    print(f"Computing daylight for {TARGET_DATE} ...")

    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            if not us_prepared.contains(Point(lon, lat)):
                continue

            # Timezone (offline, cached)
            key = (round(lat, 1), round(lon, 1))
            if key not in tz_cache:
                try:
                    tz_cache[key] = get_tzid(lat, lon)
                except ValueError:
                    tz_cache[key] = None

            tzid = tz_cache[key]
            if tzid is None:
                continue

            location = LocationInfo(latitude=lat, longitude=lon, timezone=tzid)
            day = _compute_day(location, TARGET_DATE, ZoneInfo(tzid))

            if day.day_length_sec is not None:
                grid[i, j] = day.day_length_sec / 3600.0
            elif day.polar_event == "polar_day":
                grid[i, j] = 24.0  # sun never sets (unlikely in lower 48 in June)

            us_count += 1

        if (i + 1) % 10 == 0 or i == len(lats) - 1:
            pct = (i + 1) / len(lats) * 100
            print(f"  Row {i+1:3d}/{len(lats)} ({pct:.0f}%)  US points so far: {us_count}")

    valid = grid[~np.isnan(grid)]
    print(f"\nUS land points computed: {us_count}")
    print(f"Day length range: {valid.min():.2f}h – {valid.max():.2f}h")
    return lats, lons, grid


# ---------------------------------------------------------------------------
# Step 3: Render
# ---------------------------------------------------------------------------

def render_heatmap(lats, lons, grid):
    """Plot the daylight grid as a heatmap on an Albers Equal-Area US map."""
    projection = ccrs.AlbersEqualArea(
        central_longitude=-96,
        standard_parallels=(29.5, 45.5),
    )

    fig, ax = plt.subplots(figsize=(14, 9), subplot_kw={"projection": projection})
    ax.set_extent([-125, -66, 24, 50], crs=ccrs.PlateCarree())

    lons_2d, lats_2d = np.meshgrid(lons, lats)
    masked_grid = np.ma.masked_invalid(grid)

    # Auto-scale to the actual data range so the full gradient is visible
    vmin = float(masked_grid.min())
    vmax = float(masked_grid.max())

    mesh = ax.pcolormesh(
        lons_2d, lats_2d, masked_grid,
        transform=ccrs.PlateCarree(),
        cmap="plasma",
        vmin=vmin,
        vmax=vmax,
        shading="auto",
    )

    # Map features
    ax.add_feature(cfeature.OCEAN, facecolor="lightcyan", zorder=0)
    ax.add_feature(cfeature.LAKES, facecolor="lightcyan", linewidth=0.3, zorder=1)
    ax.add_feature(cfeature.STATES, linewidth=0.5, edgecolor="#888888", zorder=2)
    ax.add_feature(cfeature.BORDERS, linewidth=1.0, edgecolor="#444444", zorder=3)
    ax.add_feature(cfeature.COASTLINE, linewidth=0.8, edgecolor="#444444", zorder=4)

    # Colorbar
    cbar = plt.colorbar(
        mesh, ax=ax, orientation="vertical",
        pad=0.02, fraction=0.025, aspect=35,
    )
    cbar.set_label("Hours of Daylight", fontsize=12)
    cbar.ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1f}h"))

    ax.set_title(
        f"Hours of Daylight  \u2014  {TARGET_DATE.strftime('%B')} {TARGET_DATE.day}, {TARGET_DATE.year}\n"
        "United States (lower 48)  |  0.5° grid  |  computed with Astral/NREL SPA",
        fontsize=13,
        fontweight="bold",
        pad=16,
    )

    plt.tight_layout()
    plt.savefig(OUTPUT_PATH, dpi=150, bbox_inches="tight")
    print(f"\nSaved: {OUTPUT_PATH}")
    plt.show()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    us_prepared = build_us_geometry()
    lats, lons, grid = compute_daylight_grid(us_prepared)
    render_heatmap(lats, lons, grid)

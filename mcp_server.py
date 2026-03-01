"""Sun & Seasons MCP Server.

Exposes the Sun & Seasons compute modules as MCP tools so that Claude
(or any MCP client) can answer questions like:

  "When does the sun rise in Denver on the summer solstice?"
  "How many hours of daylight does Tromsø get in June?"
  "Generate a download link for my 2026 Tokyo sunrise calendar."

Usage — run as stdio server:
  python mcp_server.py

Configure in Claude Desktop (claude_desktop_config.json):
  {
    "mcpServers": {
      "sun-and-seasons": {
        "command": "python",
        "args": ["S:/source/Sun_and_Seasons_Calendar/mcp_server.py"]
      }
    }
  }

Or, if using the installed entry point (after `pip install -e .`):
  {
    "mcpServers": {
      "sun-and-seasons": {
        "command": "sun-and-seasons-mcp"
      }
    }
  }

All tools are pure-compute — no data is stored, no network calls except
geocode_address() which calls Nominatim/OpenStreetMap.
"""

import sys
import logging
from datetime import date as date_type

# MCP protocol writes JSON-RPC on stdout — never use print() here.
logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(message)s")

from mcp.server.fastmcp import FastMCP

from app.geocode import geocode_address
from app.timezone import get_tzid, get_dst_transitions
from app.solar import compute_year
from app.seasons import compute_seasons, SEASON_DISPLAY_NAMES
from app.ics_builder import DayLengthFormat

mcp = FastMCP(
    "sun-and-seasons",
    instructions=(
        "Tools for computing solar events (sunrise, sunset, day length), "
        "seasons (solstices, equinoxes), and DST transitions for any location "
        "and year. Use geocode_address to convert a place name to coordinates, "
        "then pass lat/lon to the other tools."
    ),
)


# ---------------------------------------------------------------------------
# Tool: geocode_address
# ---------------------------------------------------------------------------

@mcp.tool()
def geocode(address: str, top_n: int = 3) -> str:
    """Convert a place name or address to geographic coordinates.

    Returns up to top_n candidates with lat, lon, and a display name.
    Use the lat/lon from a chosen result with the other tools.

    Args:
        address: Place name or address, e.g. "Denver, CO" or "Tokyo, Japan"
        top_n:   Maximum number of candidates to return (1–5, default 3)
    """
    top_n = max(1, min(5, top_n))
    try:
        results = geocode_address(address, top_n=top_n)
    except ValueError as e:
        return f"No results found for {address!r}: {e}"
    except RuntimeError as e:
        return f"Geocoding service error: {e}"

    lines = [f"Found {len(results)} result(s) for {address!r}:\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"  {i}. {r.display_name}")
        lines.append(f"     lat={r.lat:.6f}  lon={r.lon:.6f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: get_timezone
# ---------------------------------------------------------------------------

@mcp.tool()
def get_timezone(lat: float, lon: float) -> str:
    """Return the IANA timezone ID for a lat/lon coordinate.

    Args:
        lat: Latitude  (-90 to 90)
        lon: Longitude (-180 to 180)
    """
    try:
        tzid = get_tzid(lat, lon)
        return f"Timezone: {tzid}"
    except ValueError as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Tool: get_solar_day
# ---------------------------------------------------------------------------

@mcp.tool()
def get_solar_day(lat: float, lon: float, date: str) -> str:
    """Get sunrise, solar noon, sunset, and day length for a single date.

    Args:
        lat:  Latitude  (-90 to 90)
        lon:  Longitude (-180 to 180)
        date: Date in YYYY-MM-DD format
    """
    try:
        target = date_type.fromisoformat(date)
    except ValueError:
        return f"Error: date must be YYYY-MM-DD, got {date!r}"

    try:
        tzid = get_tzid(lat, lon)
    except ValueError as e:
        return f"Error resolving timezone: {e}"

    days = compute_year(lat, lon, tzid, target.year)
    matches = [d for d in days if d.date == target]
    if not matches:
        return f"No data for {date}"

    d = matches[0]
    if d.polar_event:
        if d.polar_event == "polar_day":
            return f"{date} at ({lat}, {lon}): Polar Day — sun above horizon all day."
        else:
            return f"{date} at ({lat}, {lon}): Polar Night — sun below horizon all day."

    def fmt(dt):
        return dt.strftime("%H:%M %Z") if dt else "N/A"

    def fmt_dur(sec):
        if sec is None:
            return "unknown"
        h, rem = divmod(sec, 3600)
        m = rem // 60
        return f"{h}h {m:02d}m"

    lines = [
        f"Solar data for {date} at lat={lat}, lon={lon} ({tzid}):",
        f"  Sunrise:    {fmt(d.sunrise)}",
        f"  Solar noon: {fmt(d.solar_noon)}",
        f"  Sunset:     {fmt(d.sunset)}",
        f"  Day length: {fmt_dur(d.day_length_sec)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: get_solar_year
# ---------------------------------------------------------------------------

@mcp.tool()
def get_solar_year(lat: float, lon: float, year: int) -> str:
    """Get solar statistics and sample data for a full year at a location.

    Returns year statistics (avg/min/max day length, polar event counts)
    plus the solar times for the 21st of each month as a sample.

    Args:
        lat:  Latitude  (-90 to 90)
        lon:  Longitude (-180 to 180)
        year: Calendar year (1901–2099)
    """
    if not (1901 <= year <= 2099):
        return "Error: year must be between 1901 and 2099"

    try:
        tzid = get_tzid(lat, lon)
    except ValueError as e:
        return f"Error resolving timezone: {e}"

    days = compute_year(lat, lon, tzid, year)

    polar_day   = sum(1 for d in days if d.polar_event == "polar_day")
    polar_night = sum(1 for d in days if d.polar_event == "polar_night")
    normal      = [d for d in days if d.polar_event is None and d.day_length_sec]

    lines = [f"Solar year summary for lat={lat}, lon={lon}, {year} ({tzid}):"]

    if normal:
        avg = sum(d.day_length_sec for d in normal) // len(normal)
        shortest = min(normal, key=lambda d: d.day_length_sec)
        longest  = max(normal, key=lambda d: d.day_length_sec)

        def dur(s):
            h, r = divmod(s, 3600)
            return f"{h}h {r // 60:02d}m"

        lines += [
            f"  Normal days (sunrise & sunset): {len(normal)}",
            f"  Average day length: {dur(avg)}",
            f"  Shortest day: {shortest.date}  {dur(shortest.day_length_sec)}",
            f"  Longest day:  {longest.date}  {dur(longest.day_length_sec)}",
        ]
    if polar_day:
        lines.append(f"  Polar day (24h sun):   {polar_day} days")
    if polar_night:
        lines.append(f"  Polar night (no sun):  {polar_night} days")

    lines.append(f"\nSample solar times (21st of each month):")
    lines.append(f"  {'Date':<13} {'Sunrise':<10} {'Sunset':<10} Day length")
    lines.append(f"  {'-'*52}")
    for d in days:
        if d.date.day != 21:
            continue
        if d.polar_event:
            label = "Polar Day" if d.polar_event == "polar_day" else "Polar Night"
            lines.append(f"  {str(d.date):<13} {label}")
        else:
            sr = d.sunrise.strftime("%H:%M %Z") if d.sunrise else "  --  "
            ss = d.sunset.strftime("%H:%M %Z")  if d.sunset  else "  --  "
            h, rem = divmod(d.day_length_sec or 0, 3600)
            dl = f"{h}h {rem // 60:02d}m"
            lines.append(f"  {str(d.date):<13} {sr:<10} {ss:<10} {dl}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: get_seasons
# ---------------------------------------------------------------------------

@mcp.tool()
def get_seasons(lat: float, lon: float, year: int) -> str:
    """Get solstices and equinoxes for a year, in the location's local time.

    Args:
        lat:  Latitude  (-90 to 90)   — used only for timezone lookup
        lon:  Longitude (-180 to 180)
        year: Calendar year (1901–2099)
    """
    if not (1901 <= year <= 2099):
        return "Error: year must be between 1901 and 2099"

    try:
        tzid = get_tzid(lat, lon)
    except ValueError as e:
        return f"Error resolving timezone: {e}"

    seasons = compute_seasons(year, tzid)

    lines = [f"Solstices & Equinoxes for {year} ({tzid}):"]
    for s in seasons:
        name = SEASON_DISPLAY_NAMES[s.kind]
        local_str = s.local.strftime("%B %d at %H:%M %Z")
        utc_str   = s.utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(f"  {name}")
        lines.append(f"    Local: {local_str}")
        lines.append(f"    UTC:   {utc_str}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: get_dst_transitions
# ---------------------------------------------------------------------------

@mcp.tool()
def get_dst(lat: float, lon: float, year: int) -> str:
    """Get DST (daylight saving time) clock changes for a location and year.

    Returns the spring-forward and fall-back dates, or confirms the location
    does not observe DST.

    Args:
        lat:  Latitude  (-90 to 90)
        lon:  Longitude (-180 to 180)
        year: Calendar year (1901–2099)
    """
    if not (1901 <= year <= 2099):
        return "Error: year must be between 1901 and 2099"

    try:
        tzid = get_tzid(lat, lon)
    except ValueError as e:
        return f"Error resolving timezone: {e}"

    transitions = get_dst_transitions(tzid, year)

    if not transitions:
        return f"{tzid} does not observe DST in {year} — no clock changes."

    lines = [f"DST clock changes for {tzid} in {year}:"]
    for t in transitions:
        label = "Spring Forward (clocks +1h)" if t.kind == "dst_start" else "Fall Back (clocks -1h)"
        lines.append(f"  {t.local_date}  {label}  ({t.offset_before} → {t.offset_after})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: generate_ics_url
# ---------------------------------------------------------------------------

@mcp.tool()
def generate_ics_url(
    lat: float,
    lon: float,
    year: int,
    base_url: str = "http://localhost:8000",
    daylength: bool = False,
    fmt: str = "hm",
    display_name: str = "",
) -> str:
    """Generate the download URL for a Sun & Seasons ICS calendar file.

    The URL can be opened in a browser or shared. The Sun & Seasons web
    server must be running at base_url for the download to work.

    Args:
        lat:          Latitude  (-90 to 90)
        lon:          Longitude (-180 to 180)
        year:         Calendar year (1901–2099)
        base_url:     Base URL of the running Sun & Seasons server
                      (default: http://localhost:8000)
        daylength:    If True, generate the day-length calendar URL
        fmt:          Day-length format: hm, hm_label, colon, decimal, hms
                      (only used when daylength=True)
        display_name: Optional human-readable name embedded in the calendar
    """
    if not (1901 <= year <= 2099):
        return "Error: year must be between 1901 and 2099"

    valid_fmts = [f.value for f in DayLengthFormat]
    if fmt not in valid_fmts:
        return f"Error: fmt must be one of {valid_fmts}"

    base_url = base_url.rstrip("/")
    lat_s = f"{lat:.4f}"
    lon_s = f"{lon:.4f}"

    import urllib.parse
    dn_param = f"&display_name={urllib.parse.quote(display_name)}" if display_name else ""

    if daylength:
        url = f"{base_url}/calendar/{year}/{lat_s},{lon_s}-daylength.ics?download=true&fmt={fmt}{dn_param}"
        label = f"Day-length calendar ({fmt} format)"
    else:
        url = f"{base_url}/calendar/{year}/{lat_s},{lon_s}.ics?download=true{dn_param}"
        label = "Main calendar (sunrise, sunset, seasons, DST)"

    lines = [
        f"ICS download URL for {year} — {label}:",
        f"  {url}",
        f"",
        f"Open this URL in a browser to download the .ics file, then",
        f"import it into Google Calendar, Apple Calendar, or Outlook.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: render_daylight_frame  (requires [viz] optional dependencies)
# ---------------------------------------------------------------------------

@mcp.tool()
def render_daylight_frame(
    date: str,
    region: str = "lower48",
    step: float = 0.5,
    out_dir: str = "viz/frames/",
) -> str:
    """Render a daylight heatmap for a single date and save it as a PNG.

    Requires the [viz] optional dependencies:
        pip install -e ".[viz]"

    Returns the absolute path to the saved PNG file.  Rendering typically
    takes 15–90 seconds depending on region and step size.

    Args:
        date:    Date in YYYY-MM-DD format.
        region:  Geographic region — lower48, alaska, hawaii, or all
                 (default: lower48).  'all' renders a composite frame.
        step:    Grid resolution in degrees (default: 0.5 — balances quality
                 and speed; 0.25 is finer but ~4× slower).
        out_dir: Output directory.  The file is named YYYYMMDD.png for
                 lexicographic frame sorting (default: viz/frames/).
    """
    try:
        from viz.render_day import (
            REGIONS,
            build_land_mask,
            compute_daylight_grid,
            render_composite,
            render_heatmap,
            resolve_output_path,
        )
    except ImportError as exc:
        return (
            f"Error: viz dependencies not installed. "
            f"Run: pip install -e \".[viz]\"  ({exc})"
        )

    valid_regions = list(REGIONS) + ["all"]
    if region not in valid_regions:
        return f"Error: region must be one of {valid_regions}, got {region!r}"

    try:
        target = date_type.fromisoformat(date)
    except ValueError:
        return f"Error: date must be YYYY-MM-DD, got {date!r}"

    if not (0.01 <= step <= 2.0):
        return "Error: step must be between 0.01 and 2.0 degrees"

    out_path = resolve_output_path(out_dir, target)

    try:
        if region == "all":
            render_composite(target, step, out_path, dpi=150, show=False)
        else:
            mask = build_land_mask(region)
            lats, lons, grid = compute_daylight_grid(region, target, step, mask)
            render_heatmap(region, target, lats, lons, grid,
                           out_path=out_path, dpi=150, show=False)
    except Exception as exc:
        return f"Error rendering frame: {exc}"

    return f"Saved: {out_path.resolve()}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

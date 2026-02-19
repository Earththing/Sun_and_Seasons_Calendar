"""Sun & Seasons Calendar — command-line interface.

Usage:
  sun-and-seasons sun      <address> [--year Y] [--date YYYY-MM-DD]
  sun-and-seasons seasons  <address> [--year Y]
  sun-and-seasons ics      <address> [--year Y] [--out FILE] [--daylength] [--fmt FORMAT]
  sun-and-seasons preview  <address> [--year Y]

All subcommands geocode the address via Nominatim (no data stored).
Pass --lat/--lon instead of an address to skip geocoding.
"""

import argparse
import sys
from datetime import date, datetime

from .geocode import geocode_address, GeoResult
from .timezone import get_tzid, get_dst_transitions
from .solar import compute_year
from .seasons import compute_seasons, SEASON_DISPLAY_NAMES
from .ics_builder import build_ics, build_daylength_ics, DayLengthFormat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_time(dt) -> str:
    if dt is None:
        return "--:--"
    return dt.strftime("%H:%M %Z")


def _fmt_duration(seconds: int | None) -> str:
    if seconds is None:
        return "  --  "
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h {m:02d}m"


def _resolve_location(args) -> tuple[float, float, str, str]:
    """Return (lat, lon, display_name, tzid) from args."""
    if args.lat is not None and args.lon is not None:
        lat, lon = args.lat, args.lon
        display_name = f"{lat:.4f}, {lon:.4f}"
    else:
        address = " ".join(args.address)
        print(f"Geocoding: {address!r} ...", file=sys.stderr)
        results = geocode_address(address, top_n=1)
        loc = results[0]
        lat, lon = loc.lat, loc.lon
        display_name = loc.display_name
        print(f"Found: {display_name}  ({lat:.4f}, {lon:.4f})", file=sys.stderr)

    tzid = get_tzid(lat, lon)
    return lat, lon, display_name, tzid


def _current_year() -> int:
    return date.today().year


# ---------------------------------------------------------------------------
# Subcommand: sun
# ---------------------------------------------------------------------------

def cmd_sun(args):
    """Show sunrise, solar noon, sunset, and day length."""
    lat, lon, display_name, tzid = _resolve_location(args)
    year = args.year or _current_year()

    days = compute_year(lat, lon, tzid, year)

    if args.date:
        try:
            target = date.fromisoformat(args.date)
        except ValueError:
            print(f"Error: --date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
            sys.exit(1)
        days = [d for d in days if d.date == target]
        if not days:
            print(f"No data for {args.date} (year {year})", file=sys.stderr)
            sys.exit(1)

    print(f"\n{display_name}  |  {tzid}  |  {year}")
    print(f"{'Date':<13} {'Sunrise':<10} {'Noon':<10} {'Sunset':<10} {'Day length'}")
    print("-" * 58)
    for d in days:
        if d.polar_event:
            label = "Polar Day — sun above horizon all day" if d.polar_event == "polar_day" \
                    else "Polar Night — sun below horizon all day"
            print(f"{str(d.date):<13} {label}")
        else:
            print(
                f"{str(d.date):<13}"
                f" {_fmt_time(d.sunrise):<10}"
                f" {_fmt_time(d.solar_noon):<10}"
                f" {_fmt_time(d.sunset):<10}"
                f" {_fmt_duration(d.day_length_sec)}"
            )


# ---------------------------------------------------------------------------
# Subcommand: seasons
# ---------------------------------------------------------------------------

def cmd_seasons(args):
    """Show solstices and equinoxes for the year."""
    lat, lon, display_name, tzid = _resolve_location(args)
    year = args.year or _current_year()

    seasons = compute_seasons(year, tzid)
    dst = get_dst_transitions(tzid, year)

    print(f"\n{display_name}  |  {tzid}  |  {year}")
    print(f"\nSolstices & Equinoxes:")
    print("-" * 44)
    for s in seasons:
        name = SEASON_DISPLAY_NAMES[s.kind]
        local_str = s.local.strftime("%b %d  %H:%M %Z")
        utc_str = s.utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"  {local_str:<22} {name:<24} (UTC: {utc_str})")

    if dst:
        print(f"\nDST Clock Changes:")
        print("-" * 44)
        for t in dst:
            label = "Spring Forward" if t.kind == "dst_start" else "Fall Back    "
            print(f"  {str(t.local_date):<13} {label}  {t.offset_before} -> {t.offset_after}")
    else:
        print(f"\n  This location does not observe DST.")


# ---------------------------------------------------------------------------
# Subcommand: ics
# ---------------------------------------------------------------------------

def cmd_ics(args):
    """Generate an ICS calendar file."""
    lat, lon, display_name, tzid = _resolve_location(args)
    year = args.year or _current_year()

    days = compute_year(lat, lon, tzid, year)

    if args.daylength:
        try:
            fmt = DayLengthFormat(args.fmt)
        except ValueError:
            valid = ", ".join(f.value for f in DayLengthFormat)
            print(f"Error: --fmt must be one of: {valid}", file=sys.stderr)
            sys.exit(1)
        ics_bytes = build_daylength_ics(
            lat=lat, lon=lon, tzid=tzid, year=year,
            display_name=display_name[:80],
            days=days,
            fmt=fmt,
        )
        default_name = f"sun-and-seasons-{year}-daylength.ics"
    else:
        seasons = compute_seasons(year, tzid)
        dst = get_dst_transitions(tzid, year)
        ics_bytes = build_ics(
            lat=lat, lon=lon, tzid=tzid, year=year,
            display_name=display_name[:80],
            days=days, seasons=seasons, dst_transitions=dst,
        )
        default_name = f"sun-and-seasons-{year}.ics"

    out_path = args.out or default_name
    with open(out_path, "wb") as f:
        f.write(ics_bytes)

    event_count = ics_bytes.count(b"BEGIN:VEVENT")
    print(f"Saved {out_path}  ({event_count} events, {len(ics_bytes):,} bytes)")
    print(f"Import this file into Google Calendar, Apple Calendar, or Outlook.")


# ---------------------------------------------------------------------------
# Subcommand: preview
# ---------------------------------------------------------------------------

def cmd_preview(args):
    """Full summary: solar stats, seasons, DST, and year statistics."""
    lat, lon, display_name, tzid = _resolve_location(args)
    year = args.year or _current_year()

    print(f"\n{'='*60}")
    print(f"  Sun & Seasons Calendar")
    print(f"{'='*60}")
    print(f"\nLocation : {display_name}")
    print(f"Timezone : {tzid}")
    print(f"Year     : {year}")

    # DST
    dst = get_dst_transitions(tzid, year)
    if dst:
        print(f"\nDST Transitions:")
        for t in dst:
            label = "Spring Forward" if t.kind == "dst_start" else "Fall Back"
            print(f"  {t.local_date}  {label}  ({t.offset_before} -> {t.offset_after})")
    else:
        print(f"\nDST: this location does not observe DST")

    # Seasons
    print(f"\nSolstices & Equinoxes:")
    seasons = compute_seasons(year, tzid)
    for s in seasons:
        print(f"  {s.local.strftime('%b %d %H:%M %Z')}  --  {SEASON_DISPLAY_NAMES[s.kind]}")

    # Solar sample
    print(f"\nSolar Times (21st of selected months):")
    days = compute_year(lat, lon, tzid, year)
    print(f"  {'Date':<13} {'Sunrise':<10} {'Sunset':<10} {'Day length'}")
    print(f"  {'-'*50}")
    for d in days:
        if d.date.month in (1, 3, 6, 9, 12) and d.date.day == 21:
            if d.polar_event:
                label = d.polar_event.replace("_", " ").title()
                print(f"  {str(d.date):<13} -- {label}")
            else:
                print(
                    f"  {str(d.date):<13}"
                    f" {_fmt_time(d.sunrise):<10}"
                    f" {_fmt_time(d.sunset):<10}"
                    f" {_fmt_duration(d.day_length_sec)}"
                )

    # Stats
    polar_day   = sum(1 for d in days if d.polar_event == "polar_day")
    polar_night = sum(1 for d in days if d.polar_event == "polar_night")
    normal      = [d for d in days if d.polar_event is None and d.day_length_sec]
    avg = sum(d.day_length_sec for d in normal) // len(normal) if normal else 0

    print(f"\nYear Summary:")
    print(f"  Normal days (sunrise & sunset): {len(normal)}")
    if polar_day:
        print(f"  Polar day nights:               {polar_day}")
    if polar_night:
        print(f"  Polar nights:                   {polar_night}")
    print(f"  Average day length:             {_fmt_duration(avg)}")
    if normal:
        shortest = min(normal, key=lambda d: d.day_length_sec)
        longest  = max(normal, key=lambda d: d.day_length_sec)
        print(f"  Shortest day: {shortest.date}  {_fmt_duration(shortest.day_length_sec)}")
        print(f"  Longest day:  {longest.date}  {_fmt_duration(longest.day_length_sec)}")

    print(f"\n{'='*60}")


# ---------------------------------------------------------------------------
# Shared argument helpers
# ---------------------------------------------------------------------------

def _add_location_args(p):
    """Add address / lat+lon / year arguments to a subparser."""
    loc = p.add_mutually_exclusive_group(required=True)
    loc.add_argument(
        "address", nargs="*", metavar="ADDRESS",
        help='Location to look up, e.g. "Denver, CO" or "Sydney, Australia"',
    )
    p.add_argument("--lat", type=float, help="Latitude (skip geocoding)")
    p.add_argument("--lon", type=float, help="Longitude (skip geocoding)")
    p.add_argument("--year", type=int, metavar="YYYY",
                   help="Year (default: current year)")


def _add_location_args_v2(p):
    """Address as positional (default empty list) + optional --lat/--lon."""
    p.add_argument(
        "address", nargs="*", metavar="ADDRESS",
        help='Location, e.g. "Denver, CO"  (omit if using --lat/--lon)',
    )
    p.add_argument("--lat", type=float, help="Latitude (skip geocoding)")
    p.add_argument("--lon", type=float, help="Longitude (skip geocoding)")
    p.add_argument("--year", type=int, metavar="YYYY",
                   help="Year (default: current year)")


def _validate_location(args, parser):
    """Ensure either address words or --lat+--lon are provided."""
    if not args.address and (args.lat is None or args.lon is None):
        parser.error("Provide an address or both --lat and --lon")
    if args.address and (args.lat is not None or args.lon is not None):
        parser.error("Provide either an address or --lat/--lon, not both")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sun-and-seasons",
        description="Sun & Seasons Calendar — solar events for any location.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sun-and-seasons sun "Denver, CO"
  sun-and-seasons sun "Denver, CO" --date 2026-06-21
  sun-and-seasons sun --lat 34.052 --lon -118.243 --year 2026
  sun-and-seasons seasons "London, UK" --year 2026
  sun-and-seasons ics "Tokyo, Japan" --year 2026 --out tokyo-2026.ics
  sun-and-seasons ics "Tokyo, Japan" --daylength --fmt colon
  sun-and-seasons preview "Tromsø, Norway"
        """,
    )

    subs = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # --- sun ---
    p_sun = subs.add_parser("sun", help="Show sunrise, solar noon, and sunset times")
    _add_location_args_v2(p_sun)
    p_sun.add_argument("--date", metavar="YYYY-MM-DD",
                       help="Show a single date instead of the full year")
    p_sun.set_defaults(func=cmd_sun)

    # --- seasons ---
    p_seasons = subs.add_parser("seasons", help="Show solstices, equinoxes, and DST")
    _add_location_args_v2(p_seasons)
    p_seasons.set_defaults(func=cmd_seasons)

    # --- ics ---
    p_ics = subs.add_parser("ics", help="Generate and save an ICS calendar file")
    _add_location_args_v2(p_ics)
    p_ics.add_argument("--out", metavar="FILE",
                       help="Output filename (default: sun-and-seasons-YEAR.ics)")
    p_ics.add_argument("--daylength", action="store_true",
                       help="Generate day-length calendar instead of main calendar")
    p_ics.add_argument(
        "--fmt",
        default="hm",
        choices=[f.value for f in DayLengthFormat],
        metavar="FORMAT",
        help=f"Day-length title format (with --daylength): "
             f"{', '.join(f.value for f in DayLengthFormat)}  [default: hm]",
    )
    p_ics.set_defaults(func=cmd_ics)

    # --- preview ---
    p_preview = subs.add_parser("preview", help="Full summary: solar stats, seasons, DST")
    _add_location_args_v2(p_preview)
    p_preview.set_defaults(func=cmd_preview)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()
    _validate_location(args, parser)
    try:
        args.func(args)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

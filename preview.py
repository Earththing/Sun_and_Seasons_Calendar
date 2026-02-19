"""Quick preview script — run this to see the calendar in action.

Usage:
    .venv\Scripts\python preview.py
    .venv\Scripts\python preview.py --address "Chicago, IL" --year 2026
    .venv\Scripts\python preview.py --address "Sydney, Australia" --year 2026
    .venv\Scripts\python preview.py --save  (also writes output.ics)
"""

import argparse
from datetime import date

from app.geocode import geocode_address
from app.timezone import get_tzid, get_dst_transitions
from app.solar import compute_year
from app.seasons import compute_seasons, SEASON_DISPLAY_NAMES
from app.ics_builder import build_ics


def fmt_time(dt):
    if dt is None:
        return "N/A"
    return dt.strftime("%H:%M %Z")


def fmt_duration(seconds):
    if seconds is None:
        return "N/A"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def main():
    parser = argparse.ArgumentParser(description="Sun & Seasons Calendar preview")
    parser.add_argument("--address", default="Los Angeles, CA", help="Address to look up")
    parser.add_argument("--year", type=int, default=date.today().year, help="Year (default: current year)")
    parser.add_argument("--save", action="store_true", help="Save output.ics to disk")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Sun & Seasons Calendar Preview")
    print(f"{'='*60}")

    # 1. Geocode
    print(f"\n[Location] Geocoding: {args.address!r} ...")
    results = geocode_address(args.address, top_n=1)
    loc = results[0]
    print(f"   Found: {loc.display_name}")
    print(f"   Lat: {loc.lat:.4f}  Lon: {loc.lon:.4f}")

    # 2. Timezone
    print(f"\n[Timezone]")
    tzid = get_tzid(loc.lat, loc.lon)
    print(f"   IANA tzid: {tzid}")

    # 3. DST transitions
    dst = get_dst_transitions(tzid, args.year)
    if dst:
        print(f"\n[DST] Transitions for {args.year}:")
        for t in dst:
            label = "Spring Forward" if t.kind == "dst_start" else "Fall Back"
            print(f"   {t.local_date}  {label}  ({t.offset_before} -> {t.offset_after})")
    else:
        print(f"\n[DST] This location does not observe DST")

    # 4. Solstices & equinoxes
    print(f"\n[Seasons] Solstices & Equinoxes {args.year}:")
    seasons = compute_seasons(args.year, tzid)
    for s in seasons:
        print(f"   {s.local.strftime('%b %d %H:%M %Z')}  --  {SEASON_DISPLAY_NAMES[s.kind]}")

    # 5. Solar events — sample dates spread across the year
    print(f"\n[Solar] Sample dates for {args.year}:")
    days = compute_year(loc.lat, loc.lon, tzid, args.year)

    sample_months = [1, 3, 6, 9, 12]
    sample_day = 21
    print(f"   {'Date':<14} {'Sunrise':<12} {'Sunset':<12} {'Day length'}")
    print(f"   {'-'*52}")
    for d in days:
        if d.date.month in sample_months and d.date.day == sample_day:
            if d.polar_event:
                print(f"   {str(d.date):<14} -- {d.polar_event.replace('_', ' ').title()}")
            else:
                print(f"   {str(d.date):<14} {fmt_time(d.sunrise):<12} {fmt_time(d.sunset):<12} {fmt_duration(d.day_length_sec)}")

    # 6. Full stats
    polar_day_count   = sum(1 for d in days if d.polar_event == "polar_day")
    polar_night_count = sum(1 for d in days if d.polar_event == "polar_night")
    normal_count      = sum(1 for d in days if d.polar_event is None)
    avg_day_len = (
        sum(d.day_length_sec for d in days if d.day_length_sec) / normal_count
        if normal_count else 0
    )

    print(f"\n[Summary] Year {args.year}:")
    print(f"   Normal days (sunrise + sunset): {normal_count}")
    if polar_day_count:
        print(f"   Polar day:   {polar_day_count} days")
    if polar_night_count:
        print(f"   Polar night: {polar_night_count} days")
    print(f"   Average day length: {fmt_duration(int(avg_day_len))}")

    shortest = min((d for d in days if d.day_length_sec), key=lambda d: d.day_length_sec)
    longest  = max((d for d in days if d.day_length_sec), key=lambda d: d.day_length_sec)
    print(f"   Shortest day: {shortest.date}  {fmt_duration(shortest.day_length_sec)}")
    print(f"   Longest day:  {longest.date}  {fmt_duration(longest.day_length_sec)}")

    # 7. Optionally save ICS
    if args.save:
        print(f"\n[ICS] Generating calendar file ...")
        ics_bytes = build_ics(
            lat=loc.lat, lon=loc.lon, tzid=tzid, year=args.year,
            display_name=loc.display_name[:60],
            days=days, seasons=seasons, dst_transitions=dst,
        )
        out_path = "output.ics"
        with open(out_path, "wb") as f:
            f.write(ics_bytes)
        event_count = ics_bytes.count(b"BEGIN:VEVENT")
        print(f"   Saved {out_path}  ({event_count} events, {len(ics_bytes):,} bytes)")
        print(f"   --> Open output.ics in your calendar app to preview it!")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()

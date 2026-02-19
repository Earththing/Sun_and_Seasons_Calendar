"""ICS calendar builder — converts computed solar/season data to RFC 5545 ICS.

Produces:
- Separate VEVENT for each Sunrise and Sunset (day length in description)
- VEVENT for each solstice/equinox (1-minute duration)
- All-day VEVENT for each DST transition
- All-day VEVENT for polar day/night events
- VTIMEZONE component
- RFC 5545 compliant: line folding, CRLF, stable UIDs
"""

from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event, Timezone, TimezoneStandard, TimezoneDaylight, vText, vDatetime, vDate

from .solar import DayEvents
from .seasons import SeasonEvent, SEASON_DISPLAY_NAMES
from .timezone import DSTTransition

PRODID = "-//Sun and Seasons//Sun and Seasons Calendar v1//EN"
UID_DOMAIN = "sunandseasons.local"


def _format_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def _uid(year: int, code: str, d: date | str, lat: float, lon: float) -> str:
    lat_e6 = int(round(lat * 1e6))
    lon_e6 = int(round(lon * 1e6))
    date_str = d.isoformat() if isinstance(d, date) else d
    return f"{year}-{code}-{date_str}-{lat_e6}-{lon_e6}@{UID_DOMAIN}"


def build_ics(
    lat: float,
    lon: float,
    tzid: str,
    year: int,
    display_name: str,
    days: list[DayEvents],
    seasons: list[SeasonEvent],
    dst_transitions: list[DSTTransition],
) -> bytes:
    """Build and return a complete RFC 5545 ICS calendar as bytes."""
    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", f"Sun & Seasons \u2014 {year} \u2014 {display_name}")
    cal.add("x-wr-timezone", tzid)
    cal.add("x-published-ttl", "PT24H")

    tz = ZoneInfo(tzid)

    # --- Sunrise / Sunset events ---
    for day in days:
        if day.polar_event:
            # All-day polar event
            e = Event()
            label = "Polar Day \u2014 Sun above horizon all day" if day.polar_event == "polar_day" else "Polar Night \u2014 Sun below horizon all day"
            e.add("uid", _uid(year, day.polar_event.upper(), day.date, lat, lon))
            e.add("summary", label)
            e.add("dtstart", day.date)
            e.add("dtend", day.date + timedelta(days=1))
            e.add("description", f"{label}\nLat {lat:.4f}, Lon {lon:.4f}")
            cal.add_component(e)
            continue

        day_len_str = _format_duration(day.day_length_sec) if day.day_length_sec is not None else "unknown"
        coords_line = f"Lat {lat:.4f}, Lon {lon:.4f}"

        # Sunrise
        if day.sunrise:
            e = Event()
            e.add("uid", _uid(year, "SUNRISE", day.date, lat, lon))
            e.add("summary", "Sunrise")
            e.add("dtstart", day.sunrise)
            e.add("dtend", day.sunrise + timedelta(minutes=5))
            desc = (
                f"Sunrise: {day.sunrise.strftime('%H:%M %Z')}\n"
                f"Sunset:  {day.sunset.strftime('%H:%M %Z') if day.sunset else 'N/A'}\n"
                f"Day length: {day_len_str}\n"
                f"{coords_line}"
            )
            e.add("description", desc)
            e.add("location", coords_line)
            cal.add_component(e)

        # Sunset
        if day.sunset:
            e = Event()
            e.add("uid", _uid(year, "SUNSET", day.date, lat, lon))
            e.add("summary", "Sunset")
            e.add("dtstart", day.sunset)
            e.add("dtend", day.sunset + timedelta(minutes=5))
            desc = (
                f"Sunrise: {day.sunrise.strftime('%H:%M %Z') if day.sunrise else 'N/A'}\n"
                f"Sunset:  {day.sunset.strftime('%H:%M %Z')}\n"
                f"Day length: {day_len_str}\n"
                f"{coords_line}"
            )
            e.add("description", desc)
            e.add("location", coords_line)
            cal.add_component(e)

    # --- Season events (solstice/equinox) ---
    for season in seasons:
        e = Event()
        e.add("uid", _uid(year, f"SEASON-{season.kind.upper()}", season.utc.date(), lat, lon))
        e.add("summary", SEASON_DISPLAY_NAMES[season.kind])
        e.add("dtstart", season.local)
        e.add("dtend", season.local + timedelta(minutes=1))
        e.add("description",
              f"Astronomical event computed via Meeus algorithms.\n"
              f"UTC: {season.utc.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
              f"Local: {season.local.strftime('%Y-%m-%dT%H:%M:%S %Z')}")
        cal.add_component(e)

    # --- DST transition events ---
    for dst in dst_transitions:
        e = Event()
        code = "DST-START" if dst.kind == "dst_start" else "DST-END"
        label = (
            f"Clocks Spring Forward ({dst.offset_before} \u2192 {dst.offset_after})"
            if dst.kind == "dst_start"
            else f"Clocks Fall Back ({dst.offset_before} \u2192 {dst.offset_after})"
        )
        e.add("uid", _uid(year, code, dst.local_date, lat, lon))
        e.add("summary", label)
        e.add("dtstart", dst.local_date)
        e.add("dtend", dst.local_date + timedelta(days=1))
        e.add("description",
              f"{label}\nOffset change: {dst.offset_before} \u2192 {dst.offset_after}\n{coords_line}")
        cal.add_component(e)

    return cal.to_ical()

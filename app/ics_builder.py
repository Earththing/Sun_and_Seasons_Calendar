"""ICS calendar builder — converts computed solar/season data to RFC 5545 ICS.

Produces two calendar types:

build_ics() — main calendar:
  - Separate VEVENT for Sunrise and Sunset each day (day length in description)
  - All-day VEVENT for each solstice/equinox (exact time in description)
  - All-day VEVENT for each DST transition
  - All-day VEVENT for polar day/night

build_daylength_ics() — day length calendar:
  - One all-day VEVENT per day showing duration of daylight
  - Title format is user-selectable (see DayLengthFormat)
  - Polar days get a descriptive label instead of a duration

Both:
  - VTIMEZONE component
  - RFC 5545 compliant: line folding, CRLF, stable UIDs
"""

from datetime import datetime, date, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from .solar import DayEvents
from .seasons import SeasonEvent, SEASON_DISPLAY_NAMES
from .timezone import DSTTransition

PRODID = "-//Sun and Seasons//Sun and Seasons Calendar v1//EN"
UID_DOMAIN = "sunandseasons.local"


# ---------------------------------------------------------------------------
# Day length format options
# ---------------------------------------------------------------------------

class DayLengthFormat(str, Enum):
    HM        = "hm"         # 10h 23m
    HM_LABEL  = "hm_label"  # 10h 23m daylight
    COLON     = "colon"      # 10:23
    DECIMAL   = "decimal"    # 10.4 hrs
    HMS       = "hms"        # 10h 23m 45s  (full precision)

FORMAT_LABELS = {
    DayLengthFormat.HM:       "10h 23m",
    DayLengthFormat.HM_LABEL: "10h 23m daylight",
    DayLengthFormat.COLON:    "10:23",
    DayLengthFormat.DECIMAL:  "10.4 hrs",
    DayLengthFormat.HMS:      "10h 23m 45s",
}


def _fmt_duration(seconds: int, fmt: DayLengthFormat) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if fmt == DayLengthFormat.HM:
        return f"{h}h {m:02d}m"
    elif fmt == DayLengthFormat.HM_LABEL:
        return f"{h}h {m:02d}m daylight"
    elif fmt == DayLengthFormat.COLON:
        return f"{h}:{m:02d}"
    elif fmt == DayLengthFormat.DECIMAL:
        return f"{seconds / 3600:.1f} hrs"
    elif fmt == DayLengthFormat.HMS:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{h}h {m:02d}m"  # fallback


def _fmt_duration_desc(seconds: int) -> str:
    """Always use full HMS for descriptions regardless of title format."""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _uid(year: int, code: str, d: "date | str", lat: float, lon: float) -> str:
    lat_e6 = int(round(lat * 1e6))
    lon_e6 = int(round(lon * 1e6))
    date_str = d.isoformat() if isinstance(d, date) else d
    return f"{year}-{code}-{date_str}-{lat_e6}-{lon_e6}@{UID_DOMAIN}"


def _base_calendar(year: int, tzid: str, cal_name: str) -> Calendar:
    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", cal_name)
    cal.add("x-wr-timezone", tzid)
    cal.add("x-published-ttl", "PT24H")
    return cal


# ---------------------------------------------------------------------------
# Main calendar
# ---------------------------------------------------------------------------

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
    """Build the main ICS calendar (sunrise, sunset, solstices, DST)."""
    cal = _base_calendar(year, tzid, f"Sun & Seasons \u2014 {year} \u2014 {display_name}")
    coords_line = f"Lat {lat:.4f}, Lon {lon:.4f}"

    # --- Sunrise / Sunset events ---
    for day in days:
        if day.polar_event:
            label = (
                "Polar Day \u2014 Sun above horizon all day"
                if day.polar_event == "polar_day"
                else "Polar Night \u2014 Sun below horizon all day"
            )
            e = Event()
            e.add("uid", _uid(year, day.polar_event.upper(), day.date, lat, lon))
            e.add("summary", label)
            e.add("dtstart", day.date)
            e.add("dtend", day.date + timedelta(days=1))
            e.add("description", f"{label}\n{coords_line}")
            cal.add_component(e)
            continue

        day_len_str = _fmt_duration_desc(day.day_length_sec) if day.day_length_sec is not None else "unknown"

        if day.sunrise:
            e = Event()
            e.add("uid", _uid(year, "SUNRISE", day.date, lat, lon))
            e.add("summary", "Sunrise")
            e.add("dtstart", day.sunrise)
            e.add("dtend", day.sunrise + timedelta(minutes=5))
            e.add("description",
                f"Sunrise: {day.sunrise.strftime('%H:%M %Z')}\n"
                f"Sunset:  {day.sunset.strftime('%H:%M %Z') if day.sunset else 'N/A'}\n"
                f"Day length: {day_len_str}\n"
                f"{coords_line}")
            e.add("location", coords_line)
            cal.add_component(e)

        if day.sunset:
            e = Event()
            e.add("uid", _uid(year, "SUNSET", day.date, lat, lon))
            e.add("summary", "Sunset")
            e.add("dtstart", day.sunset)
            e.add("dtend", day.sunset + timedelta(minutes=5))
            e.add("description",
                f"Sunrise: {day.sunrise.strftime('%H:%M %Z') if day.sunrise else 'N/A'}\n"
                f"Sunset:  {day.sunset.strftime('%H:%M %Z')}\n"
                f"Day length: {day_len_str}\n"
                f"{coords_line}")
            e.add("location", coords_line)
            cal.add_component(e)

    # --- Season events — all-day, exact time in description ---
    for season in seasons:
        e = Event()
        e.add("uid", _uid(year, f"SEASON-{season.kind.upper()}", season.utc.date(), lat, lon))
        e.add("summary", SEASON_DISPLAY_NAMES[season.kind])
        e.add("dtstart", season.local.date())
        e.add("dtend", season.local.date() + timedelta(days=1))
        e.add("description",
            f"{SEASON_DISPLAY_NAMES[season.kind]}\n"
            f"Exact time: {season.local.strftime('%H:%M %Z')}\n"
            f"UTC: {season.utc.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
            f"(Computed via Meeus astronomical algorithms)")
        cal.add_component(e)

    # --- DST transition events ---
    for dst in dst_transitions:
        code = "DST-START" if dst.kind == "dst_start" else "DST-END"
        label = (
            f"Clocks Spring Forward ({dst.offset_before} \u2192 {dst.offset_after})"
            if dst.kind == "dst_start"
            else f"Clocks Fall Back ({dst.offset_before} \u2192 {dst.offset_after})"
        )
        e = Event()
        e.add("uid", _uid(year, code, dst.local_date, lat, lon))
        e.add("summary", label)
        e.add("dtstart", dst.local_date)
        e.add("dtend", dst.local_date + timedelta(days=1))
        e.add("description",
            f"{label}\nOffset change: {dst.offset_before} \u2192 {dst.offset_after}\n{coords_line}")
        cal.add_component(e)

    return cal.to_ical()


# ---------------------------------------------------------------------------
# Day length calendar
# ---------------------------------------------------------------------------

def build_daylength_ics(
    lat: float,
    lon: float,
    tzid: str,
    year: int,
    display_name: str,
    days: list[DayEvents],
    fmt: DayLengthFormat = DayLengthFormat.HM,
) -> bytes:
    """Build a separate day-length ICS calendar.

    One all-day event per day with the duration of daylight as the title,
    formatted according to `fmt`. Polar events get a descriptive label.
    """
    cal = _base_calendar(
        year, tzid,
        f"Sun & Seasons \u2014 Day Length \u2014 {year} \u2014 {display_name}"
    )
    coords_line = f"Lat {lat:.4f}, Lon {lon:.4f}"

    for day in days:
        e = Event()
        e.add("uid", _uid(year, "DAYLENGTH", day.date, lat, lon))
        e.add("dtstart", day.date)
        e.add("dtend", day.date + timedelta(days=1))

        if day.polar_event:
            label = "Polar Day" if day.polar_event == "polar_day" else "Polar Night"
            e.add("summary", label)
            e.add("description",
                f"{label}\n"
                f"{'Sun is above the horizon all day.' if day.polar_event == 'polar_day' else 'Sun is below the horizon all day.'}\n"
                f"{coords_line}")
        else:
            title = _fmt_duration(day.day_length_sec, fmt) if day.day_length_sec is not None else "Unknown"
            full = _fmt_duration_desc(day.day_length_sec) if day.day_length_sec is not None else "unknown"
            e.add("summary", title)
            e.add("description",
                f"Day length: {full}\n"
                f"Sunrise: {day.sunrise.strftime('%H:%M %Z') if day.sunrise else 'N/A'}\n"
                f"Sunset:  {day.sunset.strftime('%H:%M %Z') if day.sunset else 'N/A'}\n"
                f"{coords_line}")

        cal.add_component(e)

    return cal.to_ical()

"""Solar event computation via Astral.

Computes sunrise, sunset, solar noon, and day length for every day of a year.
Twilight and golden hour are stubbed as None (Phase 2).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun


@dataclass
class DayEvents:
    date: date
    sunrise: datetime | None
    sunset: datetime | None
    solar_noon: datetime | None
    day_length_sec: int | None
    polar_event: str | None          # "polar_day" | "polar_night" | None
    twilight: dict = field(default_factory=lambda: {
        "civil_begin": None, "civil_end": None,
        "nautical_begin": None, "nautical_end": None,
        "astronomical_begin": None, "astronomical_end": None,
    })
    golden_hour: dict = field(default_factory=lambda: {
        "morning_end": None,
        "evening_begin": None,
    })


def compute_year(lat: float, lon: float, tzid: str, year: int) -> list[DayEvents]:
    """Compute solar events for every day of the given year."""
    tz = ZoneInfo(tzid)
    location = LocationInfo(
        name="",
        region="",
        timezone=tzid,
        latitude=lat,
        longitude=lon,
    )

    results = []
    current = date(year, 1, 1)
    end = date(year + 1, 1, 1)

    while current < end:
        results.append(_compute_day(location, current, tz))
        current += timedelta(days=1)

    return results


def _compute_day(location: LocationInfo, d: date, tz: ZoneInfo) -> DayEvents:
    try:
        s = sun(location.observer, date=d, tzinfo=tz)
        sunrise = s["sunrise"]
        sunset = s["sunset"]
        noon = s["noon"]
        day_length_sec = max(0, int((sunset - sunrise).total_seconds()))
        return DayEvents(
            date=d,
            sunrise=sunrise,
            sunset=sunset,
            solar_noon=noon,
            day_length_sec=day_length_sec,
            polar_event=None,
        )
    except Exception as e:
        msg = str(e).lower()
        if "never rises" in msg or "below horizon" in msg:
            polar_event = "polar_night"
        elif "never sets" in msg or "above horizon" in msg:
            polar_event = "polar_day"
        else:
            polar_event = "polar_night"  # default for unknown edge case
        return DayEvents(
            date=d,
            sunrise=None,
            sunset=None,
            solar_noon=None,
            day_length_sec=None,
            polar_event=polar_event,
        )

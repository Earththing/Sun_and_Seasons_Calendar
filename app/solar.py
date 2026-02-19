"""Solar event computation via Astral.

Computes sunrise, sunset, solar noon, and day length for every day of a year.
Twilight and golden hour are stubbed as None (Phase 2).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sunrise as astral_sunrise, sunset as astral_sunset, noon as astral_noon


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


def _classify_polar(msg: str) -> str:
    """Return 'polar_day' or 'polar_night' from an Astral exception message.

    Astral raises ValueError with:
      polar day:   "Sun is always above the horizon on this day, at this location."
      polar night: "Sun is always below the horizon on this day, at this location."
    """
    msg_lower = msg.lower()
    if "always above" in msg_lower:
        return "polar_day"
    elif "always below" in msg_lower:
        return "polar_night"
    return "polar_night"  # safe default


def _compute_day(location: LocationInfo, d: date, tz: ZoneInfo) -> DayEvents:
    # Compute sunrise and sunset individually so we get the correct
    # "always above / always below" exception for each (the combined
    # sun() call may raise on twilight before reaching rise/set).
    try:
        sr = astral_sunrise(location.observer, date=d, tzinfo=tz)
    except ValueError as e:
        return DayEvents(
            date=d,
            sunrise=None, sunset=None, solar_noon=None,
            day_length_sec=None,
            polar_event=_classify_polar(str(e)),
        )

    try:
        ss = astral_sunset(location.observer, date=d, tzinfo=tz)
    except ValueError as e:
        return DayEvents(
            date=d,
            sunrise=None, sunset=None, solar_noon=None,
            day_length_sec=None,
            polar_event=_classify_polar(str(e)),
        )

    noon = astral_noon(location.observer, date=d, tzinfo=tz)
    day_length_sec = max(0, int((ss - sr).total_seconds()))

    return DayEvents(
        date=d,
        sunrise=sr,
        sunset=ss,
        solar_noon=noon,
        day_length_sec=day_length_sec,
        polar_event=None,
    )

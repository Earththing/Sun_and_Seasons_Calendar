"""Timezone resolution and DST transition detection.

Given (lat, lon), returns the IANA tzid and DST transition dates for a year.
Uses timezonefinder (offline) and zoneinfo (stdlib).
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from timezonefinder import TimezoneFinder

_tf = TimezoneFinder()


@dataclass
class DSTTransition:
    kind: str           # "dst_start" or "dst_end"
    local_date: date
    offset_before: str  # e.g. "-08:00"
    offset_after: str   # e.g. "-07:00"


def get_tzid(lat: float, lon: float) -> str:
    """Return IANA tzid for the given coordinates.

    Raises ValueError if no timezone found (e.g. open ocean far from land).
    """
    tzid = _tf.timezone_at(lat=lat, lng=lon)
    if tzid is None:
        raise ValueError(f"No timezone found for lat={lat}, lon={lon}")
    return tzid


def get_dst_transitions(tzid: str, year: int) -> list[DSTTransition]:
    """Return DST start and end transitions for the given IANA tzid and year.

    Returns an empty list for zones without DST (e.g. UTC, Arizona).
    """
    tz = ZoneInfo(tzid)
    transitions = []

    # Walk every day of the year and detect UTC offset changes
    prev_offset = None
    prev_date = None

    for month in range(1, 13):
        for day in range(1, 32):
            try:
                dt = datetime(year, month, day, 12, 0, 0, tzinfo=tz)
            except ValueError:
                continue

            offset = dt.utcoffset()
            if prev_offset is not None and offset != prev_offset:
                kind = "dst_start" if offset > prev_offset else "dst_end"
                transitions.append(
                    DSTTransition(
                        kind=kind,
                        local_date=date(year, month, day),
                        offset_before=_format_offset(prev_offset),
                        offset_after=_format_offset(offset),
                    )
                )
            prev_offset = offset
            prev_date = date(year, month, day)

    return transitions


def _format_offset(td) -> str:
    total = int(td.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    return f"{sign}{hours:02d}:{minutes:02d}"

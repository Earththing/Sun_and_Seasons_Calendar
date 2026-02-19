"""Solstice and equinox computation via Meeus (Astronomical Algorithms, Ch. 27).

Computes the four seasonal events for a given year, accurate to ~1 minute
for years 1951–2050. Returns UTC datetimes.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo


# ΔT approximation (TT - UT1) in seconds, good enough for 1900–2100.
# For higher accuracy, use a lookup table from IERS.
def _delta_t(year: int) -> float:
    t = (year - 2000) / 100.0
    if year < 2050:
        return 62.92 + 0.32217 * t + 0.005589 * t * t
    else:
        return -20 + 32 * ((year - 1820) / 100) ** 2 - 0.5628 * (2150 - year)


# Meeus Table 27.a — JDE0 mean values for equinoxes/solstices
# Keys: "march_equinox", "june_solstice", "september_equinox", "december_solstice"
_SEASON_INDEX = {
    "march_equinox": 0,
    "june_solstice": 1,
    "september_equinox": 2,
    "december_solstice": 3,
}

_PERIODIC_TERMS = [
    (485, 324.96, 1934.136),
    (203, 337.23, 32964.467),
    (199, 342.08, 20.186),
    (182, 27.85, 445267.112),
    (156, 73.14, 45036.886),
    (136, 171.52, 22518.443),
    (77, 222.54, 65928.934),
    (74, 296.72, 3034.906),
    (70, 243.58, 9037.513),
    (58, 119.81, 33718.147),
    (52, 297.17, 150.678),
    (50, 21.02, 2281.226),
    (45, 247.54, 29929.562),
    (44, 325.15, 31555.956),
    (29, 60.93, 4443.417),
    (18, 155.12, 67555.328),
    (17, 288.79, 4562.452),
    (16, 198.04, 62894.029),
    (14, 199.76, 31557.381),
    (12, 95.39, 14577.848),
    (10, 49.11, 31436.921),
    (10, 165.69, 28135.302),
    (10, 341.47, 183.119),
    (10, 297.84, 29447.967),
]


def _jde_for_season(year: int, season: str) -> float:
    """Return Julian Ephemeris Day for a seasonal event (Meeus Ch. 27)."""
    k = _SEASON_INDEX[season]
    y = year + k / 4.0  # approximate year fraction

    if year < 1000:
        y_norm = y / 1000.0
        jde0 = (
            1721139.2855
            + 365242.1376 * y_norm
            + 0.0679 * y_norm**2
            - 0.0027 * y_norm**3
            - 0.000047 * y_norm**4
        )
        # Per-season offsets for year < 1000 (Meeus Table 27.a)
        offsets = [
            (0, 0, 0, 0, 0),
            (365241.7169, -0.0152, -0.00799, 0.000107, 0),
            (365242.0986, -0.0167, 0.00257, -0.000023, 0),
            (365242.7931, 0.0169, -0.00223, -0.000052, 0),
        ]
        coeffs = offsets[k]
        jde0 = (
            1721325.7620 + coeffs[0] * y_norm
            if k > 0
            else 1721139.2855 + 365242.1376 * y_norm
        )
    # Use year >= 1000 formula (more common path)
    y_norm = (year - 2000) / 1000.0
    season_jde0 = [
        2451623.80984 + 365242.37404 * y_norm + 0.05169 * y_norm**2 - 0.00411 * y_norm**3 - 0.00057 * y_norm**4,
        2451716.56767 + 365241.62603 * y_norm + 0.00325 * y_norm**2 + 0.00888 * y_norm**3 - 0.00030 * y_norm**4,
        2451810.21715 + 365242.01767 * y_norm - 0.11575 * y_norm**2 + 0.00337 * y_norm**3 + 0.00078 * y_norm**4,
        2451900.05952 + 365242.74049 * y_norm - 0.06223 * y_norm**2 - 0.00823 * y_norm**3 + 0.00032 * y_norm**4,
    ]
    jde0 = season_jde0[k]

    t = (jde0 - 2451545.0) / 36525.0
    w = 35999.373 * t - 2.47
    delta_lambda = 1 + 0.0334 * math.cos(math.radians(w)) + 0.0007 * math.cos(math.radians(2 * w))

    s = sum(
        coeff * math.cos(math.radians(b + c * t))
        for coeff, b, c in _PERIODIC_TERMS
    )

    return jde0 + (0.00001 * s) / delta_lambda


def _jde_to_utc(jde: float, year: int) -> datetime:
    """Convert Julian Ephemeris Day (TT) to UTC datetime."""
    dt_seconds = _delta_t(year)
    # JDE is in TT; subtract ΔT to get UT
    jd_ut = jde - dt_seconds / 86400.0
    # Convert JD to calendar date (algorithm from Meeus Ch. 7)
    jd = jd_ut + 0.5
    z = int(jd)
    f = jd - z
    if z < 2299161:
        a = z
    else:
        alpha = int((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - alpha // 4
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)

    day_frac = b - d - int(30.6001 * e) + f
    day = int(day_frac)
    frac = day_frac - day

    month = e - 1 if e < 14 else e - 13
    year_out = c - 4716 if month > 2 else c - 4715

    total_seconds = int(frac * 86400)
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)

    return datetime(year_out, month, day, hours, minutes, seconds, tzinfo=timezone.utc)


@dataclass
class SeasonEvent:
    kind: str          # "march_equinox" | "june_solstice" | "september_equinox" | "december_solstice"
    utc: datetime
    local: datetime


_DISPLAY_NAMES = {
    "march_equinox": "March Equinox (Spring begins, Northern Hemisphere)",
    "june_solstice": "June Solstice (Summer begins, Northern Hemisphere)",
    "september_equinox": "September Equinox (Autumn begins, Northern Hemisphere)",
    "december_solstice": "December Solstice (Winter begins, Northern Hemisphere)",
}


def compute_seasons(year: int, tzid: str) -> list[SeasonEvent]:
    """Return the four seasonal events for the given year, in UTC and local time."""
    tz = ZoneInfo(tzid)
    events = []
    for kind in ("march_equinox", "june_solstice", "september_equinox", "december_solstice"):
        jde = _jde_for_season(year, kind)
        utc_dt = _jde_to_utc(jde, year)
        local_dt = utc_dt.astimezone(tz)
        events.append(SeasonEvent(kind=kind, utc=utc_dt, local=local_dt))
    return events


SEASON_DISPLAY_NAMES = _DISPLAY_NAMES

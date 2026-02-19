"""Tests for solar event computation (Astral wrapper).

Reference times from NOAA Solar Calculator and timeanddate.com.
Tolerance: ±3 minutes (Astral/SPA accuracy for sea-level default).
"""

from datetime import date, timezone
import pytest
from app.solar import compute_year, DayEvents


TOLERANCE_SECONDS = 3 * 60  # 3-minute window


def _hm(h, m):
    """Return total seconds from midnight for a given HH:MM."""
    return h * 3600 + m * 60


def _local_seconds(dt):
    """Return seconds from midnight in local time."""
    return dt.hour * 3600 + dt.minute * 60 + dt.second


def _get_day(days: list[DayEvents], month: int, day_num: int) -> DayEvents:
    return next(d for d in days if d.date.month == month and d.date.day == day_num)


class TestComputeYear:
    """Spot-check sunrise/sunset against NOAA for Los Angeles, 2026."""

    # lat/lon: downtown Los Angeles
    LAT = 34.052
    LON = -118.243
    TZID = "America/Los_Angeles"
    YEAR = 2026

    @pytest.fixture(scope="class")
    def la_days(self):
        return compute_year(self.LAT, self.LON, self.TZID, self.YEAR)

    def test_returns_365_days(self, la_days):
        assert len(la_days) == 365

    def test_all_dates_in_year(self, la_days):
        years = {d.date.year for d in la_days}
        assert years == {self.YEAR}

    # Jan 1 2026: sunrise ~07:00, sunset ~16:52 PST (NOAA)
    def test_jan1_sunrise(self, la_days):
        day = _get_day(la_days, 1, 1)
        assert day.sunrise is not None
        diff = abs(_local_seconds(day.sunrise) - _hm(7, 0))
        assert diff <= TOLERANCE_SECONDS, f"Jan 1 sunrise off by {diff}s"

    def test_jan1_sunset(self, la_days):
        day = _get_day(la_days, 1, 1)
        assert day.sunset is not None
        diff = abs(_local_seconds(day.sunset) - _hm(16, 52))
        assert diff <= TOLERANCE_SECONDS, f"Jan 1 sunset off by {diff}s"

    # Jun 21 2026 (summer solstice): sunrise ~05:42, sunset ~20:07 PDT
    def test_jun21_sunrise(self, la_days):
        day = _get_day(la_days, 6, 21)
        assert day.sunrise is not None
        diff = abs(_local_seconds(day.sunrise) - _hm(5, 42))
        assert diff <= TOLERANCE_SECONDS, f"Jun 21 sunrise off by {diff}s"

    def test_jun21_sunset(self, la_days):
        day = _get_day(la_days, 6, 21)
        assert day.sunset is not None
        diff = abs(_local_seconds(day.sunset) - _hm(20, 7))
        assert diff <= TOLERANCE_SECONDS, f"Jun 21 sunset off by {diff}s"

    # Dec 21 2026 (winter solstice): sunrise ~06:55, sunset ~16:48 PST
    def test_dec21_sunrise(self, la_days):
        day = _get_day(la_days, 12, 21)
        assert day.sunrise is not None
        diff = abs(_local_seconds(day.sunrise) - _hm(6, 55))
        assert diff <= TOLERANCE_SECONDS, f"Dec 21 sunrise off by {diff}s"

    def test_dec21_sunset(self, la_days):
        day = _get_day(la_days, 12, 21)
        assert day.sunset is not None
        diff = abs(_local_seconds(day.sunset) - _hm(16, 48))
        assert diff <= TOLERANCE_SECONDS, f"Dec 21 sunset off by {diff}s"

    def test_day_length_positive(self, la_days):
        for day in la_days:
            if day.polar_event is None:
                assert day.day_length_sec is not None
                assert day.day_length_sec > 0

    def test_sunrise_before_sunset(self, la_days):
        for day in la_days:
            if day.sunrise and day.sunset:
                assert day.sunrise < day.sunset

    def test_day_length_matches_rise_set(self, la_days):
        """day_length_sec should match sunset - sunrise within 1 second."""
        for day in la_days:
            if day.sunrise and day.sunset and day.day_length_sec is not None:
                computed = int((day.sunset - day.sunrise).total_seconds())
                assert abs(computed - day.day_length_sec) <= 1

    def test_no_polar_events_for_la(self, la_days):
        """LA never has polar day or night."""
        for day in la_days:
            assert day.polar_event is None


class TestPolarEdgeCases:
    """Verify polar day/night handling for Tromsø, Norway."""

    LAT = 69.649
    LON = 18.956
    TZID = "Europe/Oslo"
    YEAR = 2026

    @pytest.fixture(scope="class")
    def tromso_days(self):
        return compute_year(self.LAT, self.LON, self.TZID, self.YEAR)

    def test_has_polar_day_in_summer(self, tromso_days):
        # Tromsø has midnight sun roughly May 18 – July 26
        june_days = [d for d in tromso_days if d.date.month == 6]
        polar_day_count = sum(1 for d in june_days if d.polar_event == "polar_day")
        assert polar_day_count > 15, "Expected most of June to be polar day"

    def test_has_polar_night_in_winter(self, tromso_days):
        # Tromsø has polar night roughly Nov 26 – Jan 15
        dec_days = [d for d in tromso_days if d.date.month == 12]
        polar_night_count = sum(1 for d in dec_days if d.polar_event == "polar_night")
        assert polar_night_count > 15, "Expected most of December to be polar night"

    def test_polar_day_has_no_sunrise_sunset(self, tromso_days):
        for day in tromso_days:
            if day.polar_event == "polar_day":
                assert day.sunrise is None
                assert day.sunset is None

    def test_polar_night_has_no_sunrise_sunset(self, tromso_days):
        for day in tromso_days:
            if day.polar_event == "polar_night":
                assert day.sunrise is None
                assert day.sunset is None

    def test_stub_fields_present(self, tromso_days):
        """Twilight and golden_hour stubs should always be present."""
        for day in tromso_days:
            assert "civil_begin" in day.twilight
            assert "morning_end" in day.golden_hour

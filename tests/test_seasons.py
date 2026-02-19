"""Tests for solstice/equinox computation (Meeus Chapter 27).

Reference dates from the USNO / published astronomical almanacs.
Tolerance: ±2 minutes (our target), tested at ±5 minutes to be safe
against ΔT approximation error.
"""

from datetime import timezone, timedelta
import pytest
from app.seasons import compute_seasons


TOLERANCE_SECONDS = 5 * 60  # 5-minute window


def _utc(year, month, day, hour, minute, second=0):
    from datetime import datetime
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


# Published UTC instants (USNO / Astronomical Almanac)
KNOWN_EVENTS = {
    # 2024
    (2024, "march_equinox"):       _utc(2024,  3, 20, 3, 6),
    (2024, "june_solstice"):        _utc(2024,  6, 20, 20, 51),
    (2024, "september_equinox"):    _utc(2024,  9, 22, 12, 44),
    (2024, "december_solstice"):    _utc(2024, 12, 21, 9, 20),
    # 2025
    (2025, "march_equinox"):       _utc(2025,  3, 20, 9, 1),
    (2025, "june_solstice"):        _utc(2025,  6, 21, 2, 42),
    (2025, "september_equinox"):    _utc(2025,  9, 22, 18, 19),
    (2025, "december_solstice"):    _utc(2025, 12, 21, 15, 3),
    # 2026
    (2026, "march_equinox"):       _utc(2026,  3, 20, 14, 46),
    (2026, "june_solstice"):        _utc(2026,  6, 21, 8, 24),
    (2026, "september_equinox"):    _utc(2026,  9, 23, 0, 5),
    (2026, "december_solstice"):    _utc(2026, 12, 21, 20, 50),
}


class TestComputeSeasons:
    @pytest.mark.parametrize("year,kind", [
        (2024, "march_equinox"),
        (2024, "june_solstice"),
        (2024, "september_equinox"),
        (2024, "december_solstice"),
        (2025, "march_equinox"),
        (2025, "june_solstice"),
        (2025, "september_equinox"),
        (2025, "december_solstice"),
        (2026, "march_equinox"),
        (2026, "june_solstice"),
        (2026, "september_equinox"),
        (2026, "december_solstice"),
    ])
    def test_accuracy_within_tolerance(self, year, kind):
        seasons = compute_seasons(year, "UTC")
        event = next(s for s in seasons if s.kind == kind)
        expected = KNOWN_EVENTS[(year, kind)]
        diff = abs((event.utc - expected).total_seconds())
        assert diff <= TOLERANCE_SECONDS, (
            f"{year} {kind}: computed {event.utc}, expected {expected}, "
            f"diff={diff:.0f}s (tolerance={TOLERANCE_SECONDS}s)"
        )

    def test_returns_four_events(self):
        seasons = compute_seasons(2026, "UTC")
        assert len(seasons) == 4
        kinds = {s.kind for s in seasons}
        assert kinds == {"march_equinox", "june_solstice", "september_equinox", "december_solstice"}

    def test_local_time_matches_utc_offset(self):
        """Local time should equal UTC + tzid offset."""
        seasons = compute_seasons(2026, "America/Los_Angeles")
        for s in seasons:
            # local - utc should equal the UTC offset at that moment
            utc_offset = s.local.utcoffset()
            assert utc_offset is not None
            diff = (s.local.replace(tzinfo=None) - s.utc.replace(tzinfo=None))
            assert abs(diff.total_seconds() - utc_offset.total_seconds()) < 2

    def test_events_in_chronological_order(self):
        seasons = compute_seasons(2026, "UTC")
        utc_times = [s.utc for s in seasons]
        assert utc_times == sorted(utc_times)

    def test_year_1990(self):
        """Verify algorithm works outside the 2024-2026 test window."""
        seasons = compute_seasons(1990, "UTC")
        assert len(seasons) == 4
        # March equinox 1990 was March 20 at ~21:19 UTC
        march = next(s for s in seasons if s.kind == "march_equinox")
        expected = _utc(1990, 3, 20, 21, 19)
        diff = abs((march.utc - expected).total_seconds())
        assert diff <= TOLERANCE_SECONDS

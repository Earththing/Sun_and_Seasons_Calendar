"""Tests for timezone resolution and DST transition detection."""

import pytest
from app.timezone import get_tzid, get_dst_transitions


# --- tzid resolution ---

class TestGetTzid:
    def test_los_angeles(self):
        assert get_tzid(34.052, -118.243) == "America/Los_Angeles"

    def test_new_york(self):
        assert get_tzid(40.713, -74.006) == "America/New_York"

    def test_london(self):
        tzid = get_tzid(51.507, -0.128)
        assert tzid == "Europe/London"

    def test_sydney(self):
        tzid = get_tzid(-33.868, 151.209)
        assert tzid == "Australia/Sydney"

    def test_phoenix_arizona(self):
        # Arizona does not observe DST
        assert get_tzid(33.448, -112.074) == "America/Phoenix"

    def test_utc_zone(self):
        # Reykjavik is UTC year-round
        tzid = get_tzid(64.135, -21.895)
        assert tzid == "Atlantic/Reykjavik"

    def test_tokyo(self):
        assert get_tzid(35.689, 139.692) == "Asia/Tokyo"


# --- DST transitions ---

class TestGetDstTransitions:
    def test_la_2026_has_two_transitions(self):
        transitions = get_dst_transitions("America/Los_Angeles", 2026)
        assert len(transitions) == 2

    def test_la_2026_spring_forward(self):
        transitions = get_dst_transitions("America/Los_Angeles", 2026)
        start = next(t for t in transitions if t.kind == "dst_start")
        # 2026 DST starts second Sunday in March = March 8
        assert start.local_date.month == 3
        assert start.offset_before == "-08:00"
        assert start.offset_after == "-07:00"

    def test_la_2026_fall_back(self):
        transitions = get_dst_transitions("America/Los_Angeles", 2026)
        end = next(t for t in transitions if t.kind == "dst_end")
        # 2026 DST ends first Sunday in November = November 1
        assert end.local_date.month == 11
        assert end.offset_before == "-07:00"
        assert end.offset_after == "-08:00"

    def test_phoenix_no_dst(self):
        # Arizona does not observe DST
        transitions = get_dst_transitions("America/Phoenix", 2026)
        assert transitions == []

    def test_utc_no_dst(self):
        transitions = get_dst_transitions("UTC", 2026)
        assert transitions == []

    def test_tokyo_no_dst(self):
        transitions = get_dst_transitions("Asia/Tokyo", 2026)
        assert transitions == []

    def test_london_2026_has_dst(self):
        transitions = get_dst_transitions("Europe/London", 2026)
        assert len(transitions) == 2
        start = next(t for t in transitions if t.kind == "dst_start")
        assert start.offset_before == "+00:00"
        assert start.offset_after == "+01:00"

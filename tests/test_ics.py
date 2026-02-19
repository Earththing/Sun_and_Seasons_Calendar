"""Golden-file and structural tests for ICS rendering (RFC 5545)."""

from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import re

import pytest
from icalendar import Calendar

from app.solar import compute_year
from app.seasons import compute_seasons
from app.timezone import get_dst_transitions
from app.ics_builder import build_ics


# --- Shared fixture: generate a small but real ICS for LA 2026 ---

LAT = 34.052
LON = -118.243
TZID = "America/Los_Angeles"
YEAR = 2026


@pytest.fixture(scope="module")
def la_ics_bytes():
    days = compute_year(LAT, LON, TZID, YEAR)
    seasons = compute_seasons(YEAR, TZID)
    dst = get_dst_transitions(TZID, YEAR)
    return build_ics(
        lat=LAT, lon=LON, tzid=TZID, year=YEAR,
        display_name="Los Angeles, CA",
        days=days, seasons=seasons, dst_transitions=dst,
    )


@pytest.fixture(scope="module")
def la_ics_text(la_ics_bytes):
    return la_ics_bytes.decode("utf-8")


@pytest.fixture(scope="module")
def la_cal(la_ics_bytes):
    return Calendar.from_ical(la_ics_bytes)


# --- RFC 5545 structural tests ---

class TestRFC5545Structure:
    def test_begins_with_vcalendar(self, la_ics_text):
        assert la_ics_text.startswith("BEGIN:VCALENDAR")

    def test_ends_with_vcalendar(self, la_ics_text):
        assert la_ics_text.rstrip().endswith("END:VCALENDAR")

    def test_version_2(self, la_ics_text):
        assert "VERSION:2.0" in la_ics_text

    def test_prodid_present(self, la_ics_text):
        assert "PRODID:" in la_ics_text
        assert "Sun and Seasons" in la_ics_text

    def test_calscale_gregorian(self, la_ics_text):
        assert "CALSCALE:GREGORIAN" in la_ics_text

    def test_crlf_line_endings(self, la_ics_bytes):
        # RFC 5545 requires CRLF
        assert b"\r\n" in la_ics_bytes

    def test_no_bare_lf(self, la_ics_bytes):
        # No bare LF (i.e. every \n must be preceded by \r)
        lines = la_ics_bytes.split(b"\r\n")
        for line in lines:
            assert b"\n" not in line, f"Bare LF found in line: {line!r}"

    def test_line_length_max_75_octets(self, la_ics_bytes):
        # RFC 5545: lines must not exceed 75 octets (before CRLF)
        for line in la_ics_bytes.split(b"\r\n"):
            assert len(line) <= 75, f"Line too long ({len(line)} octets): {line!r}"

    def test_parseable_by_icalendar(self, la_cal):
        assert la_cal is not None

    def test_calname_present(self, la_ics_text):
        assert "X-WR-CALNAME" in la_ics_text
        assert "Sun & Seasons" in la_ics_text
        assert str(YEAR) in la_ics_text

    def test_timezone_hint_present(self, la_ics_text):
        assert "X-WR-TIMEZONE:America/Los_Angeles" in la_ics_text


# --- Event content tests ---

class TestEventContent:
    def _get_events(self, cal):
        from icalendar import Event
        return [c for c in cal.walk() if isinstance(c, Event)]

    def test_has_sunrise_events(self, la_cal):
        events = self._get_events(la_cal)
        summaries = [str(e.get("SUMMARY", "")) for e in events]
        assert any("Sunrise" in s for s in summaries)

    def test_has_sunset_events(self, la_cal):
        events = self._get_events(la_cal)
        summaries = [str(e.get("SUMMARY", "")) for e in events]
        assert any("Sunset" in s for s in summaries)

    def test_sunrise_and_sunset_are_separate_events(self, la_cal):
        """Each day must have both a Sunrise AND a Sunset event — not combined."""
        events = self._get_events(la_cal)
        sunrise_dates = {e.decoded("DTSTART").date() for e in events if "Sunrise" in str(e.get("SUMMARY", ""))}
        sunset_dates  = {e.decoded("DTSTART").date() for e in events if "Sunset"  in str(e.get("SUMMARY", ""))}
        # Both sets should be equal (same days have both)
        assert sunrise_dates == sunset_dates
        # And should cover most of the year (365 days, LA has no polar events)
        assert len(sunrise_dates) == 365

    def test_has_season_events(self, la_cal):
        events = self._get_events(la_cal)
        summaries = [str(e.get("SUMMARY", "")) for e in events]
        assert any("Solstice" in s or "Equinox" in s for s in summaries)
        solstice_equinox = [s for s in summaries if "Solstice" in s or "Equinox" in s]
        assert len(solstice_equinox) == 4

    def test_has_dst_events(self, la_cal):
        events = self._get_events(la_cal)
        summaries = [str(e.get("SUMMARY", "")) for e in events]
        assert any("Spring Forward" in s or "Fall Back" in s for s in summaries)

    def test_total_event_count(self, la_cal):
        events = self._get_events(la_cal)
        # 365 sunrise + 365 sunset + 4 seasons + 2 DST = 736
        assert len(events) == 736

    def test_all_events_have_uid(self, la_cal):
        events = self._get_events(la_cal)
        for e in events:
            assert e.get("UID") is not None, f"Missing UID on event: {e.get('SUMMARY')}"

    def test_uids_are_unique(self, la_cal):
        events = self._get_events(la_cal)
        uids = [str(e.get("UID")) for e in events]
        assert len(uids) == len(set(uids)), "Duplicate UIDs found"

    def test_uid_domain(self, la_cal):
        events = self._get_events(la_cal)
        for e in events:
            assert "@sunandseasons.local" in str(e.get("UID"))

    def test_sunrise_description_includes_day_length(self, la_cal):
        events = self._get_events(la_cal)
        sunrise_events = [e for e in events if "Sunrise" in str(e.get("SUMMARY", ""))]
        for e in sunrise_events[:5]:  # spot-check first 5
            desc = str(e.get("DESCRIPTION", ""))
            assert "Day length" in desc or "day_length" in desc.lower()

    def test_dst_events_are_all_day(self, la_cal):
        from icalendar import vDate, vDatetime
        events = self._get_events(la_cal)
        dst_events = [e for e in events if "Spring Forward" in str(e.get("SUMMARY", "")) or "Fall Back" in str(e.get("SUMMARY", ""))]
        assert len(dst_events) == 2
        for e in dst_events:
            dtstart = e.decoded("DTSTART")
            assert isinstance(dtstart, date) and not isinstance(dtstart, datetime), \
                f"DST event should be all-day, got {type(dtstart)}"


# --- UID stability test ---

class TestUIDStability:
    def test_regeneration_produces_same_uids(self):
        """Same inputs must produce identical UIDs (for calendar subscription updates)."""
        days = compute_year(LAT, LON, TZID, YEAR)
        seasons = compute_seasons(YEAR, TZID)
        dst = get_dst_transitions(TZID, YEAR)

        ics1 = build_ics(LAT, LON, TZID, YEAR, "Los Angeles", days, seasons, dst)
        ics2 = build_ics(LAT, LON, TZID, YEAR, "Los Angeles", days, seasons, dst)

        cal1 = Calendar.from_ical(ics1)
        cal2 = Calendar.from_ical(ics2)

        from icalendar import Event
        uids1 = sorted(str(e.get("UID")) for e in cal1.walk() if isinstance(e, Event))
        uids2 = sorted(str(e.get("UID")) for e in cal2.walk() if isinstance(e, Event))
        assert uids1 == uids2


# --- DST-free zone test ---

class TestNoDSTZone:
    def test_phoenix_no_dst_events(self):
        """Locations without DST should produce no DST events."""
        days = compute_year(33.448, -112.074, "America/Phoenix", YEAR)
        seasons = compute_seasons(YEAR, "America/Phoenix")
        dst = get_dst_transitions("America/Phoenix", YEAR)
        ics = build_ics(33.448, -112.074, "America/Phoenix", YEAR, "Phoenix, AZ", days, seasons, dst)
        cal = Calendar.from_ical(ics)
        from icalendar import Event
        events = [c for c in cal.walk() if isinstance(c, Event)]
        dst_events = [e for e in events if "Spring Forward" in str(e.get("SUMMARY", "")) or "Fall Back" in str(e.get("SUMMARY", ""))]
        assert len(dst_events) == 0

"""Golden-file and structural tests for ICS rendering (RFC 5545)."""

from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import re

import pytest
from icalendar import Calendar

from app.solar import compute_year
from app.seasons import compute_seasons
from app.timezone import get_dst_transitions
from app.ics_builder import build_ics, build_daylength_ics, DayLengthFormat


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

    def test_season_events_are_all_day(self, la_cal):
        """Solstice/equinox events must be all-day (not timed)."""
        events = self._get_events(la_cal)
        season_events = [
            e for e in events
            if "Solstice" in str(e.get("SUMMARY", "")) or "Equinox" in str(e.get("SUMMARY", ""))
        ]
        assert len(season_events) == 4
        for e in season_events:
            dtstart = e.decoded("DTSTART")
            assert isinstance(dtstart, date) and not isinstance(dtstart, datetime), \
                f"Season event should be all-day, got {type(dtstart)}: {e.get('SUMMARY')}"

    def test_season_description_includes_exact_time(self, la_cal):
        """Solstice/equinox descriptions must include the exact local time."""
        events = self._get_events(la_cal)
        season_events = [
            e for e in events
            if "Solstice" in str(e.get("SUMMARY", "")) or "Equinox" in str(e.get("SUMMARY", ""))
        ]
        for e in season_events:
            desc = str(e.get("DESCRIPTION", ""))
            assert "Exact time:" in desc, f"Missing exact time in description: {e.get('SUMMARY')}"

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


# --- Day length calendar tests ---

@pytest.fixture(scope="module")
def la_days():
    return compute_year(LAT, LON, TZID, YEAR)


class TestDayLengthICS:
    def _get_events(self, ics_bytes):
        from icalendar import Event
        cal = Calendar.from_ical(ics_bytes)
        return [c for c in cal.walk() if isinstance(c, Event)]

    def _build(self, fmt=DayLengthFormat.HM):
        days = compute_year(LAT, LON, TZID, YEAR)
        return build_daylength_ics(LAT, LON, TZID, YEAR, "Los Angeles, CA", days, fmt=fmt)

    def test_returns_365_events(self):
        events = self._get_events(self._build())
        assert len(events) == 365

    def test_all_events_are_all_day(self):
        events = self._get_events(self._build())
        for e in events:
            dtstart = e.decoded("DTSTART")
            assert isinstance(dtstart, date) and not isinstance(dtstart, datetime), \
                f"Day length event should be all-day, got {type(dtstart)}"

    def test_all_events_have_uid(self):
        events = self._get_events(self._build())
        for e in events:
            assert e.get("UID") is not None

    def test_uids_are_unique(self):
        events = self._get_events(self._build())
        uids = [str(e.get("UID")) for e in events]
        assert len(uids) == len(set(uids))

    def test_calname_includes_day_length(self):
        ics = self._build()
        assert b"Day Length" in ics

    def test_crlf_line_endings(self):
        assert b"\r\n" in self._build()

    def test_line_length_max_75_octets(self):
        for line in self._build().split(b"\r\n"):
            assert len(line) <= 75

    # --- Format tests ---

    def test_format_hm(self):
        events = self._get_events(self._build(DayLengthFormat.HM))
        summaries = [str(e.get("SUMMARY", "")) for e in events if e.get("SUMMARY")]
        # Should look like "10h 23m" — contains 'h' and 'm', no 'daylight'
        timed = [s for s in summaries if "h" in s and "m" in s]
        assert len(timed) > 300
        assert not any("daylight" in s for s in timed)

    def test_format_hm_label(self):
        events = self._get_events(self._build(DayLengthFormat.HM_LABEL))
        summaries = [str(e.get("SUMMARY", "")) for e in events]
        timed = [s for s in summaries if "daylight" in s]
        assert len(timed) > 300

    def test_format_colon(self):
        events = self._get_events(self._build(DayLengthFormat.COLON))
        summaries = [str(e.get("SUMMARY", "")) for e in events]
        # Colon format: "10:23" — contains ':' and no 'h'
        colon = [s for s in summaries if ":" in s and "h" not in s]
        assert len(colon) > 300

    def test_format_decimal(self):
        events = self._get_events(self._build(DayLengthFormat.DECIMAL))
        summaries = [str(e.get("SUMMARY", "")) for e in events]
        decimal = [s for s in summaries if "hrs" in s]
        assert len(decimal) > 300

    def test_format_hms(self):
        events = self._get_events(self._build(DayLengthFormat.HMS))
        summaries = [str(e.get("SUMMARY", "")) for e in events]
        # HMS includes seconds: "10h 23m 45s"
        hms = [s for s in summaries if "h" in s and "m" in s and "s" in s]
        assert len(hms) > 300

    def test_description_always_uses_full_hms(self):
        """Description should always show full HMS regardless of title format."""
        events = self._get_events(self._build(DayLengthFormat.COLON))
        timed = [e for e in events if ":" in str(e.get("SUMMARY", ""))]
        for e in timed[:5]:  # spot-check
            desc = str(e.get("DESCRIPTION", ""))
            assert "Day length:" in desc
            # Description should contain 'h' and 'm' and 's'
            assert "h" in desc and "m" in desc and "s" in desc

    def test_uid_stability_across_formats(self):
        """UIDs must be identical regardless of format (same day, same location)."""
        events_hm  = self._get_events(self._build(DayLengthFormat.HM))
        events_hms = self._get_events(self._build(DayLengthFormat.HMS))
        uids_hm  = sorted(str(e.get("UID")) for e in events_hm)
        uids_hms = sorted(str(e.get("UID")) for e in events_hms)
        assert uids_hm == uids_hms

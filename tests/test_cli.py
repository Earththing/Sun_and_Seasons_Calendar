"""Tests for the command-line interface (app/cli.py)."""

import os
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from app.cli import build_parser, main, _fmt_duration, _fmt_time
from app.geocode import GeoResult


# ---------------------------------------------------------------------------
# Shared mock: one-result geocode returning Los Angeles
# ---------------------------------------------------------------------------

LA = GeoResult(lat=34.052, lon=-118.243, display_name="Los Angeles, CA")

def _mock_geocode(address, top_n=1):
    return [LA]


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

class TestFmtHelpers:
    def test_fmt_duration_normal(self):
        assert _fmt_duration(3600) == "1h 00m"
        assert _fmt_duration(5400) == "1h 30m"
        assert _fmt_duration(36000 + 1380) == "10h 23m"

    def test_fmt_duration_none(self):
        result = _fmt_duration(None)
        assert "--" in result

    def test_fmt_time_none(self):
        assert _fmt_time(None) == "--:--"


# ---------------------------------------------------------------------------
# Parser structure
# ---------------------------------------------------------------------------

class TestParser:
    def test_sun_subcommand_exists(self):
        p = build_parser()
        args = p.parse_args(["sun", "Denver, CO"])
        assert args.command == "sun"

    def test_seasons_subcommand_exists(self):
        p = build_parser()
        args = p.parse_args(["seasons", "London, UK"])
        assert args.command == "seasons"

    def test_ics_subcommand_exists(self):
        p = build_parser()
        args = p.parse_args(["ics", "Tokyo, Japan"])
        assert args.command == "ics"

    def test_preview_subcommand_exists(self):
        p = build_parser()
        args = p.parse_args(["preview", "Sydney, Australia"])
        assert args.command == "preview"

    def test_sun_with_lat_lon(self):
        p = build_parser()
        args = p.parse_args(["sun", "--lat", "34.052", "--lon", "-118.243"])
        assert args.lat == 34.052
        assert args.lon == -118.243

    def test_sun_with_year(self):
        p = build_parser()
        args = p.parse_args(["sun", "Denver, CO", "--year", "2026"])
        assert args.year == 2026

    def test_sun_with_date(self):
        p = build_parser()
        args = p.parse_args(["sun", "Denver, CO", "--date", "2026-06-21"])
        assert args.date == "2026-06-21"

    def test_ics_daylength_flag(self):
        p = build_parser()
        args = p.parse_args(["ics", "Denver, CO", "--daylength"])
        assert args.daylength is True

    def test_ics_fmt_option(self):
        p = build_parser()
        args = p.parse_args(["ics", "Denver, CO", "--daylength", "--fmt", "colon"])
        assert args.fmt == "colon"

    def test_ics_out_option(self):
        p = build_parser()
        args = p.parse_args(["ics", "Denver, CO", "--out", "my.ics"])
        assert args.out == "my.ics"

    def test_no_subcommand_fails(self, capsys):
        p = build_parser()
        with pytest.raises(SystemExit):
            p.parse_args([])


# ---------------------------------------------------------------------------
# cmd_sun
# ---------------------------------------------------------------------------

class TestCmdSun:
    def test_sun_full_year_output(self, capsys):
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["sun", "Los Angeles, CA", "--year", "2026"])
            from app.cli import cmd_sun
            cmd_sun(args)
        out = capsys.readouterr().out
        assert "2026" in out
        assert "Sunrise" in out or "sunrise" in out.lower() or "06:" in out or "07:" in out

    def test_sun_single_date(self, capsys):
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["sun", "Los Angeles, CA", "--year", "2026", "--date", "2026-06-21"])
            from app.cli import cmd_sun
            cmd_sun(args)
        out = capsys.readouterr().out
        assert "2026-06-21" in out

    def test_sun_lat_lon_skips_geocode(self, capsys):
        p = build_parser()
        args = p.parse_args(["sun", "--lat", "34.052", "--lon", "-118.243",
                              "--year", "2026", "--date", "2026-01-01"])
        from app.cli import cmd_sun
        cmd_sun(args)
        out = capsys.readouterr().out
        assert "2026-01-01" in out

    def test_sun_bad_date_exits(self, capsys):
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["sun", "Los Angeles, CA", "--date", "not-a-date"])
            from app.cli import cmd_sun
            with pytest.raises(SystemExit):
                cmd_sun(args)

    def test_sun_output_has_365_rows(self, capsys):
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["sun", "Los Angeles, CA", "--year", "2026"])
            from app.cli import cmd_sun
            cmd_sun(args)
        out = capsys.readouterr().out
        # Count date lines (YYYY-MM-DD pattern)
        import re
        date_lines = re.findall(r"\d{4}-\d{2}-\d{2}", out)
        assert len(date_lines) == 365


# ---------------------------------------------------------------------------
# cmd_seasons
# ---------------------------------------------------------------------------

class TestCmdSeasons:
    def test_seasons_shows_four_events(self, capsys):
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["seasons", "Los Angeles, CA", "--year", "2026"])
            from app.cli import cmd_seasons
            cmd_seasons(args)
        out = capsys.readouterr().out
        assert "Solstice" in out or "Equinox" in out
        # Count season lines by the UTC timestamp — one per event
        utc_lines = [ln for ln in out.splitlines() if "UTC:" in ln]
        assert len(utc_lines) == 4

    def test_seasons_shows_dst_for_la(self, capsys):
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["seasons", "Los Angeles, CA", "--year", "2026"])
            from app.cli import cmd_seasons
            cmd_seasons(args)
        out = capsys.readouterr().out
        assert "Spring Forward" in out or "Fall Back" in out

    def test_seasons_no_dst_for_phoenix(self, capsys):
        phoenix = GeoResult(lat=33.448, lon=-112.074, display_name="Phoenix, AZ")
        with patch("app.cli.geocode_address", return_value=[phoenix]):
            p = build_parser()
            args = p.parse_args(["seasons", "Phoenix, AZ", "--year", "2026"])
            from app.cli import cmd_seasons
            cmd_seasons(args)
        out = capsys.readouterr().out
        assert "does not observe DST" in out


# ---------------------------------------------------------------------------
# cmd_ics
# ---------------------------------------------------------------------------

class TestCmdIcs:
    def test_ics_creates_file(self, tmp_path, capsys):
        out_file = str(tmp_path / "test.ics")
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["ics", "Los Angeles, CA", "--year", "2026",
                                  "--out", out_file])
            from app.cli import cmd_ics
            cmd_ics(args)
        assert Path(out_file).exists()
        content = Path(out_file).read_bytes()
        assert content.startswith(b"BEGIN:VCALENDAR")

    def test_ics_file_is_valid_ics(self, tmp_path):
        out_file = str(tmp_path / "test.ics")
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["ics", "Los Angeles, CA", "--year", "2026",
                                  "--out", out_file])
            from app.cli import cmd_ics
            cmd_ics(args)
        from icalendar import Calendar
        cal = Calendar.from_ical(Path(out_file).read_bytes())
        assert cal is not None

    def test_ics_daylength_creates_file(self, tmp_path, capsys):
        out_file = str(tmp_path / "daylength.ics")
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["ics", "Los Angeles, CA", "--year", "2026",
                                  "--daylength", "--out", out_file])
            from app.cli import cmd_ics
            cmd_ics(args)
        content = Path(out_file).read_bytes()
        assert b"Day Length" in content

    def test_ics_daylength_colon_format(self, tmp_path):
        out_file = str(tmp_path / "colon.ics")
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["ics", "Los Angeles, CA", "--year", "2026",
                                  "--daylength", "--fmt", "colon", "--out", out_file])
            from app.cli import cmd_ics
            cmd_ics(args)
        assert Path(out_file).exists()

    def test_ics_invalid_fmt_exits(self, tmp_path):
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["ics", "Los Angeles, CA", "--daylength"])
            args.fmt = "bad_format"
            args.out = str(tmp_path / "x.ics")
            from app.cli import cmd_ics
            with pytest.raises(SystemExit):
                cmd_ics(args)

    def test_ics_default_filename_contains_year(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["ics", "Los Angeles, CA", "--year", "2026"])
            from app.cli import cmd_ics
            cmd_ics(args)
        out = capsys.readouterr().out
        assert "2026" in out
        # Default file should have been created
        ics_files = list(tmp_path.glob("*.ics"))
        assert len(ics_files) == 1


# ---------------------------------------------------------------------------
# cmd_preview
# ---------------------------------------------------------------------------

class TestCmdPreview:
    def test_preview_output_has_sections(self, capsys):
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["preview", "Los Angeles, CA", "--year", "2026"])
            from app.cli import cmd_preview
            cmd_preview(args)
        out = capsys.readouterr().out
        assert "Location" in out
        assert "Timezone" in out
        assert "Solstice" in out or "Equinox" in out
        assert "Shortest day" in out
        assert "Longest day" in out

    def test_preview_shows_dst(self, capsys):
        with patch("app.cli.geocode_address", side_effect=_mock_geocode):
            p = build_parser()
            args = p.parse_args(["preview", "Los Angeles, CA", "--year", "2026"])
            from app.cli import cmd_preview
            cmd_preview(args)
        out = capsys.readouterr().out
        assert "Spring Forward" in out or "Fall Back" in out


# ---------------------------------------------------------------------------
# MCP server tool functions
# ---------------------------------------------------------------------------

class TestMCPTools:
    """Test the MCP tool functions directly (not via MCP protocol)."""

    def test_geocode_returns_results(self):
        with patch("mcp_server.geocode_address", side_effect=_mock_geocode):
            import mcp_server
            result = mcp_server.geocode("Los Angeles, CA")
        assert "Los Angeles" in result
        assert "34." in result

    def test_geocode_not_found(self):
        with patch("mcp_server.geocode_address",
                   side_effect=ValueError("No results")):
            import mcp_server
            result = mcp_server.geocode("xyzzy_fake_place")
        assert "No results" in result

    def test_get_timezone_returns_tzid(self):
        import mcp_server
        result = mcp_server.get_timezone(34.052, -118.243)
        assert "America/Los_Angeles" in result

    def test_get_solar_day_returns_sunrise(self):
        import mcp_server
        result = mcp_server.get_solar_day(34.052, -118.243, "2026-06-21")
        assert "Sunrise" in result
        assert "2026-06-21" in result

    def test_get_solar_day_bad_date(self):
        import mcp_server
        result = mcp_server.get_solar_day(34.052, -118.243, "not-a-date")
        assert "Error" in result

    def test_get_solar_year_returns_stats(self):
        import mcp_server
        result = mcp_server.get_solar_year(34.052, -118.243, 2026)
        assert "Shortest day" in result
        assert "Longest day" in result
        assert "Average" in result

    def test_get_solar_year_invalid(self):
        import mcp_server
        result = mcp_server.get_solar_year(34.052, -118.243, 3000)
        assert "Error" in result

    def test_get_seasons_returns_four(self):
        import mcp_server
        result = mcp_server.get_seasons(34.052, -118.243, 2026)
        # Count "Local:" lines — one per season event
        local_lines = [ln for ln in result.splitlines() if "Local:" in ln]
        assert len(local_lines) == 4

    def test_get_dst_la_has_transitions(self):
        import mcp_server
        result = mcp_server.get_dst(34.052, -118.243, 2026)
        assert "Spring Forward" in result
        assert "Fall Back" in result

    def test_get_dst_phoenix_no_dst(self):
        import mcp_server
        result = mcp_server.get_dst(33.448, -112.074, 2026)
        assert "does not observe DST" in result

    def test_generate_ics_url_main(self):
        import mcp_server
        result = mcp_server.generate_ics_url(34.052, -118.243, 2026)
        assert "/calendar/2026/" in result
        assert ".ics" in result
        assert "daylength" not in result

    def test_generate_ics_url_daylength(self):
        import mcp_server
        result = mcp_server.generate_ics_url(34.052, -118.243, 2026, daylength=True, fmt="colon")
        assert "daylength" in result
        assert "fmt=colon" in result

    def test_generate_ics_url_invalid_fmt(self):
        import mcp_server
        result = mcp_server.generate_ics_url(34.052, -118.243, 2026, daylength=True, fmt="bad")
        assert "Error" in result

    def test_generate_ics_url_display_name(self):
        import mcp_server
        result = mcp_server.generate_ics_url(
            34.052, -118.243, 2026, display_name="My Home"
        )
        assert "My%20Home" in result or "My+Home" in result or "My Home" in result

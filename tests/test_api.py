"""Tests for FastAPI routes (async test client, no real network calls)."""

from unittest.mock import patch, MagicMock
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.geocode import GeoResult


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_geocode_la():
    """Mock geocode_address returning a single Los Angeles result."""
    with patch("app.main.geocode_address") as m:
        m.return_value = [GeoResult(lat=34.052, lon=-118.243, display_name="Los Angeles, CA")]
        yield m


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

class TestIndex:
    async def test_returns_200(self, client):
        r = await client.get("/")
        assert r.status_code == 200

    async def test_returns_html(self, client):
        r = await client.get("/")
        assert "text/html" in r.headers["content-type"]


# ---------------------------------------------------------------------------
# GET /help
# ---------------------------------------------------------------------------

class TestHelp:
    async def test_returns_200(self, client):
        r = await client.get("/help")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /geocode
# ---------------------------------------------------------------------------

class TestGeocode:
    async def test_returns_candidates(self, client, mock_geocode_la):
        r = await client.post("/geocode", json={"address": "Los Angeles, CA"})
        assert r.status_code == 200
        data = r.json()
        assert "candidates" in data
        assert len(data["candidates"]) == 1
        assert data["candidates"][0]["lat"] == pytest.approx(34.052)
        assert data["candidates"][0]["display_name"] == "Los Angeles, CA"

    async def test_empty_address_returns_400(self, client):
        r = await client.post("/geocode", json={"address": "   "})
        assert r.status_code == 400

    async def test_not_found_returns_404(self, client):
        with patch("app.main.geocode_address", side_effect=ValueError("No results")):
            r = await client.post("/geocode", json={"address": "xyzzy_fake_place"})
        assert r.status_code == 404

    async def test_service_error_returns_503(self, client):
        with patch("app.main.geocode_address", side_effect=RuntimeError("timeout")):
            r = await client.post("/geocode", json={"address": "London"})
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/v1/tzid
# ---------------------------------------------------------------------------

class TestTzid:
    async def test_la_returns_correct_tzid(self, client):
        r = await client.get("/api/v1/tzid?lat=34.052&lon=-118.243")
        assert r.status_code == 200
        assert r.json()["tzid"] == "America/Los_Angeles"

    async def test_invalid_lat_returns_422(self, client):
        r = await client.get("/api/v1/tzid?lat=999&lon=0")
        assert r.status_code == 422

    async def test_missing_params_returns_422(self, client):
        r = await client.get("/api/v1/tzid")
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/sun
# ---------------------------------------------------------------------------

class TestSunAPI:
    async def test_returns_365_days(self, client):
        r = await client.get("/api/v1/sun?lat=34.052&lon=-118.243&year=2026")
        assert r.status_code == 200
        data = r.json()
        assert data["meta"]["year"] == 2026
        assert data["meta"]["tzid"] == "America/Los_Angeles"
        assert len(data["days"]) == 365

    async def test_days_have_required_fields(self, client):
        r = await client.get("/api/v1/sun?lat=34.052&lon=-118.243&year=2026")
        day = r.json()["days"][0]
        assert "date" in day
        assert "sunrise" in day
        assert "sunset" in day
        assert "day_length_sec" in day
        assert "polar_event" in day

    async def test_returns_four_seasons(self, client):
        r = await client.get("/api/v1/sun?lat=34.052&lon=-118.243&year=2026")
        seasons = r.json()["events"]["seasons"]
        assert len(seasons) == 4

    async def test_returns_two_dst_events_for_la(self, client):
        r = await client.get("/api/v1/sun?lat=34.052&lon=-118.243&year=2026")
        dst = r.json()["events"]["dst"]
        assert len(dst) == 2

    async def test_no_dst_events_for_phoenix(self, client):
        r = await client.get("/api/v1/sun?lat=33.448&lon=-112.074&year=2026")
        dst = r.json()["events"]["dst"]
        assert len(dst) == 0

    async def test_year_out_of_range_returns_422(self, client):
        r = await client.get("/api/v1/sun?lat=34.052&lon=-118.243&year=3000")
        assert r.status_code == 422

    async def test_defaults_to_current_year(self, client):
        from datetime import date
        r = await client.get("/api/v1/sun?lat=34.052&lon=-118.243")
        assert r.status_code == 200
        assert r.json()["meta"]["year"] == date.today().year


# ---------------------------------------------------------------------------
# GET /calendar/{year}/{coords}.ics
# ---------------------------------------------------------------------------

class TestCalendarICS:
    async def test_returns_200_and_ics_content_type(self, client):
        r = await client.get("/calendar/2026/34.052,-118.243.ics")
        assert r.status_code == 200
        assert "text/calendar" in r.headers["content-type"]

    async def test_ics_begins_with_vcalendar(self, client):
        r = await client.get("/calendar/2026/34.052,-118.243.ics")
        assert r.content.startswith(b"BEGIN:VCALENDAR")

    async def test_download_flag_sets_attachment(self, client):
        r = await client.get("/calendar/2026/34.052,-118.243.ics?download=true")
        assert "attachment" in r.headers["content-disposition"]

    async def test_inline_without_download_flag(self, client):
        r = await client.get("/calendar/2026/34.052,-118.243.ics")
        assert "inline" in r.headers["content-disposition"]

    async def test_custom_display_name_in_calname(self, client):
        r = await client.get("/calendar/2026/34.052,-118.243.ics?display_name=My+Home")
        assert b"My Home" in r.content

    async def test_invalid_coords_returns_400(self, client):
        r = await client.get("/calendar/2026/not-a-coord.ics")
        assert r.status_code == 400

    async def test_out_of_range_year_returns_400(self, client):
        r = await client.get("/calendar/1800/34.052,-118.243.ics")
        assert r.status_code == 400

    async def test_out_of_range_lat_returns_400(self, client):
        r = await client.get("/calendar/2026/999.0,-118.243.ics")
        assert r.status_code == 400

    async def test_cache_control_header(self, client):
        r = await client.get("/calendar/2026/34.052,-118.243.ics")
        assert "max-age" in r.headers.get("cache-control", "")

    async def test_negative_lon_in_coords(self, client):
        # Negative longitudes (e.g. Americas) must parse correctly
        r = await client.get("/calendar/2026/34.052,-118.243.ics")
        assert r.status_code == 200

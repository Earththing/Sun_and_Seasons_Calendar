"""Tests for geocoding module.

Unit tests use mocked Nominatim responses (no network).
The live smoke test is marked so it can be skipped in CI with:
    pytest -m "not live"
"""

from unittest.mock import MagicMock, patch
import pytest

from app.geocode import geocode_address, GeoResult


def _mock_location(lat, lon, address):
    loc = MagicMock()
    loc.latitude = lat
    loc.longitude = lon
    loc.address = address
    return loc


class TestGeocodeAddress:
    """Unit tests — fully mocked, no network calls."""

    def test_returns_geo_result_list(self):
        mock_loc = _mock_location(34.052, -118.243, "Los Angeles, CA, USA")
        with patch("app.geocode.Nominatim") as MockNominatim:
            MockNominatim.return_value.geocode.return_value = [mock_loc]
            results = geocode_address("Los Angeles, CA")
        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], GeoResult)

    def test_result_fields(self):
        mock_loc = _mock_location(34.052, -118.243, "Los Angeles, CA, USA")
        with patch("app.geocode.Nominatim") as MockNominatim:
            MockNominatim.return_value.geocode.return_value = [mock_loc]
            results = geocode_address("Los Angeles, CA")
        r = results[0]
        assert r.lat == 34.052
        assert r.lon == -118.243
        assert r.display_name == "Los Angeles, CA, USA"

    def test_respects_top_n(self):
        mock_locs = [
            _mock_location(34.052, -118.243, "Los Angeles, CA"),
            _mock_location(34.055, -118.250, "Los Angeles, CA (alt)"),
            _mock_location(34.060, -118.260, "Los Angeles, CA (alt 2)"),
        ]
        with patch("app.geocode.Nominatim") as MockNominatim:
            MockNominatim.return_value.geocode.return_value = mock_locs
            results = geocode_address("Los Angeles", top_n=3)
        assert len(results) == 3
        # Verify top_n was passed to geocode
        MockNominatim.return_value.geocode.assert_called_once_with(
            "Los Angeles", exactly_one=False, limit=3
        )

    def test_raises_value_error_on_no_results(self):
        with patch("app.geocode.Nominatim") as MockNominatim:
            MockNominatim.return_value.geocode.return_value = None
            with pytest.raises(ValueError, match="No results found"):
                geocode_address("xyzzy not a real place 99999")

    def test_raises_runtime_error_on_service_error(self):
        from geopy.exc import GeocoderServiceError
        with patch("app.geocode.Nominatim") as MockNominatim:
            MockNominatim.return_value.geocode.side_effect = GeocoderServiceError("timeout")
            with pytest.raises(RuntimeError, match="Geocoding service error"):
                geocode_address("London")

    def test_user_agent_set(self):
        mock_loc = _mock_location(51.507, -0.128, "London, UK")
        with patch("app.geocode.Nominatim") as MockNominatim:
            MockNominatim.return_value.geocode.return_value = [mock_loc]
            geocode_address("London")
        MockNominatim.assert_called_once_with(user_agent="sun-and-seasons-calendar/0.1")

    def test_multiple_candidates_returned(self):
        mock_locs = [
            _mock_location(51.507, -0.128, "London, Greater London, England, UK"),
            _mock_location(42.983, -81.233, "London, Ontario, Canada"),
        ]
        with patch("app.geocode.Nominatim") as MockNominatim:
            MockNominatim.return_value.geocode.return_value = mock_locs
            results = geocode_address("London", top_n=5)
        assert len(results) == 2
        assert results[0].display_name == "London, Greater London, England, UK"
        assert results[1].display_name == "London, Ontario, Canada"


@pytest.mark.live
class TestGeocodeAddressLive:
    """Live network tests — skipped by default in CI (pytest -m 'not live')."""

    def test_los_angeles_returns_result(self):
        results = geocode_address("Los Angeles, CA", top_n=1)
        assert len(results) >= 1
        assert abs(results[0].lat - 34.05) < 0.1
        assert abs(results[0].lon - (-118.24)) < 0.1

    def test_ambiguous_returns_multiple(self):
        results = geocode_address("Springfield", top_n=5)
        assert len(results) >= 2  # many Springfields in the US

    def test_no_result_raises(self):
        with pytest.raises(ValueError):
            geocode_address("xyzzy_not_a_real_place_123456789")

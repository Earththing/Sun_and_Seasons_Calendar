"""Geocoding: address string → (lat, lon, display_name) via Nominatim/OSM.

The address string is used only for this lookup and is never stored.
"""

from dataclasses import dataclass

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderServiceError


@dataclass
class GeoResult:
    lat: float
    lon: float
    display_name: str


def geocode_address(address: str, top_n: int = 5) -> list[GeoResult]:
    """Return up to top_n geocoding candidates for the given address string.

    Raises ValueError if no results found.
    Raises RuntimeError on geocoder service errors.
    """
    geolocator = Nominatim(user_agent="sun-and-seasons-calendar/0.1")
    try:
        locations = geolocator.geocode(address, exactly_one=False, limit=top_n)
    except GeocoderServiceError as e:
        raise RuntimeError(f"Geocoding service error: {e}") from e

    if not locations:
        raise ValueError(f"No results found for address: {address!r}")

    return [
        GeoResult(lat=loc.latitude, lon=loc.longitude, display_name=loc.address)
        for loc in locations
    ]

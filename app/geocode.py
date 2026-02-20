"""Geocoding: address string → (lat, lon, display_name) via Nominatim/OSM.

The address string is used only for this lookup and is never stored.
"""

import logging
from dataclasses import dataclass

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderServiceError, GeocoderTimedOut

logger = logging.getLogger(__name__)

# Nominatim usage policy: identify your app and provide contact info.
# https://operations.osmfoundation.org/policies/nominatim/
_USER_AGENT = "sun-and-seasons-calendar/0.1 (https://github.com/earththing/sun-and-seasons)"

# Seconds to wait for a Nominatim response before giving up.
_GEOCODE_TIMEOUT = 8


@dataclass
class GeoResult:
    lat: float
    lon: float
    display_name: str


def geocode_address(address: str, top_n: int = 5) -> list[GeoResult]:
    """Return up to top_n geocoding candidates for the given address string.

    Raises ValueError if no results found.
    Raises RuntimeError on geocoder service errors or timeouts.
    """
    geolocator = Nominatim(user_agent=_USER_AGENT)
    try:
        locations = geolocator.geocode(
            address, exactly_one=False, limit=top_n, timeout=_GEOCODE_TIMEOUT
        )
    except GeocoderTimedOut as e:
        logger.warning("Nominatim timeout for address %r: %s", address, e)
        raise RuntimeError("Geocoding service timed out — please try again.") from e
    except GeocoderServiceError as e:
        logger.warning("Nominatim service error for address %r: %s", address, e)
        raise RuntimeError(f"Geocoding service error: {e}") from e

    if not locations:
        raise ValueError(f"No results found for address: {address!r}")

    return [
        GeoResult(lat=loc.latitude, lon=loc.longitude, display_name=loc.address)
        for loc in locations
    ]

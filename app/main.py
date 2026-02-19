"""Sun & Seasons Calendar — FastAPI application."""

from datetime import date
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .geocode import geocode_address
from .timezone import get_tzid, get_dst_transitions
from .solar import compute_year
from .seasons import compute_seasons
from .ics_builder import build_ics

app = FastAPI(
    title="Sun & Seasons Calendar",
    description="Generate ICS calendars with sunrise, sunset, solstices, and DST events.",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

YEAR_MIN = 1901
YEAR_MAX = 2099


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class GeocodeRequest(BaseModel):
    address: str


class GeocodeCandidate(BaseModel):
    lat: float
    lon: float
    display_name: str


class GeocodeResponse(BaseModel):
    candidates: list[GeocodeCandidate]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/help", response_class=HTMLResponse)
async def help_page(request: Request):
    return templates.TemplateResponse(request, "help.html")


@app.post("/geocode", response_model=GeocodeResponse)
async def geocode(body: GeocodeRequest):
    """Geocode an address string to lat/lon candidates via Nominatim.

    The address string is used only for this lookup and is not stored.
    Returns up to 5 candidates for the user to confirm.
    """
    if not body.address.strip():
        raise HTTPException(status_code=400, detail="Address must not be empty.")
    try:
        results = geocode_address(body.address, top_n=5)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return GeocodeResponse(
        candidates=[
            GeocodeCandidate(lat=r.lat, lon=r.lon, display_name=r.display_name)
            for r in results
        ]
    )


@app.get("/api/v1/tzid")
async def api_tzid(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
):
    """Return the IANA timezone ID for a lat/lon coordinate."""
    try:
        tzid = get_tzid(lat, lon)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"tzid": tzid}


@app.get("/api/v1/sun")
async def api_sun(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    year: Annotated[int, Query(ge=YEAR_MIN, le=YEAR_MAX)] = None,
    tzid: str = None,
):
    """Return JSON solar events (sunrise, sunset, day length) for a full year."""
    if year is None:
        year = date.today().year
    if tzid is None:
        try:
            tzid = get_tzid(lat, lon)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    days = compute_year(lat, lon, tzid, year)
    seasons = compute_seasons(year, tzid)
    dst = get_dst_transitions(tzid, year)

    return {
        "meta": {"lat": lat, "lon": lon, "tzid": tzid, "year": year},
        "days": [
            {
                "date": d.date.isoformat(),
                "sunrise": d.sunrise.isoformat() if d.sunrise else None,
                "sunset": d.sunset.isoformat() if d.sunset else None,
                "solar_noon": d.solar_noon.isoformat() if d.solar_noon else None,
                "day_length_sec": d.day_length_sec,
                "polar_event": d.polar_event,
            }
            for d in days
        ],
        "events": {
            "seasons": [
                {
                    "kind": s.kind,
                    "utc": s.utc.isoformat(),
                    "local": s.local.isoformat(),
                }
                for s in seasons
            ],
            "dst": [
                {
                    "kind": t.kind,
                    "local_date": t.local_date.isoformat(),
                    "offset_before": t.offset_before,
                    "offset_after": t.offset_after,
                }
                for t in dst
            ],
        },
    }


@app.get("/calendar/{year}/{coords}.ics")
async def calendar_ics(
    year: int,
    coords: str,
    tzid: str = None,
    display_name: str = None,
    download: bool = False,
):
    """Generate and return an ICS calendar file.

    Path: /calendar/2026/34.052,-118.243.ics
    Query params:
      - tzid: IANA timezone (auto-detected if omitted)
      - display_name: human-readable label for the calendar name
      - download: if true, serve as attachment (triggers browser download)
    """
    if year < YEAR_MIN or year > YEAR_MAX:
        raise HTTPException(status_code=400, detail=f"Year must be between {YEAR_MIN} and {YEAR_MAX}.")

    # Parse "lat,lon" from path segment
    try:
        lat_str, lon_str = coords.split(",", 1)
        lat = float(lat_str)
        lon = float(lon_str)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail="Coordinates must be formatted as 'lat,lon' e.g. 34.052,-118.243",
        )

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Coordinates out of range.")

    if tzid is None:
        try:
            tzid = get_tzid(lat, lon)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    if display_name is None:
        display_name = f"{lat:.4f}, {lon:.4f}"

    days = compute_year(lat, lon, tzid, year)
    seasons = compute_seasons(year, tzid)
    dst = get_dst_transitions(tzid, year)

    ics_bytes = build_ics(
        lat=lat, lon=lon, tzid=tzid, year=year,
        display_name=display_name[:80],
        days=days, seasons=seasons, dst_transitions=dst,
    )

    disposition = "attachment" if download else "inline"
    filename = f"sun-and-seasons-{year}-{lat:.4f},{lon:.4f}.ics"

    return Response(
        content=ics_bytes,
        media_type="text/calendar",
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "public, max-age=86400",
        },
    )

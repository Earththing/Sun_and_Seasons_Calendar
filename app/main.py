"""Sun & Seasons Calendar — FastAPI application."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(
    title="Sun & Seasons Calendar",
    description="Generate ICS calendars with sunrise, sunset, solstices, and DST events.",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# Routes will be added here as modules are built:
#   POST /geocode
#   GET  /api/v1/tzid
#   GET  /api/v1/sun
#   GET  /calendar/{year}/{coords}.ics
#   GET  /help
#   GET  /  (UI)

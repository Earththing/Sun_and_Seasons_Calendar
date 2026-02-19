# Sun & Seasons Calendar

A location-aware calendar generator that produces ICS files (and eventually subscription feeds) containing:

- **Sunrise & Sunset** times (separate events, with day length)
- **Solstices & Equinoxes** (astronomical, via Meeus algorithms)
- **DST transitions** for the location's time zone

## Quick start (local)

```bash
# Install dependencies (requires Python 3.12+)
uv sync

# Run the development server
uv run uvicorn app.main:app --reload

# Open in browser
# http://localhost:8000
```

## Development

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check .
```

## Project status

MVP in development. See [Sun-Seasons-Calendar-Project-Plan.md](Sun-Seasons-Calendar-Project-Plan.md) for full plan.

## Attributions

- Solar computation: [Astral](https://sffjunkie.github.io/astral/) (Apache-2.0)
- Time zone lookup: [timezonefinder](https://github.com/jannikmi/timezonefinder) (MIT)
- Geocoding: [Nominatim / OpenStreetMap](https://nominatim.org/) contributors (ODbL)
- ICS generation: [icalendar](https://icalendar.readthedocs.io/) (BSD)

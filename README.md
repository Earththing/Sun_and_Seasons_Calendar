# Sun & Seasons Calendar

Generate a personal ICS calendar of **sunrise, sunset, solstices, equinoxes, and DST clock changes** for any location in the world.

Three ways to use it:

| Interface | Best for |
|-----------|----------|
| **Web app** | Picking a location, previewing data, and downloading a calendar file |
| **CLI** | Scripting, automation, quick terminal lookups |
| **MCP server** | Asking Claude questions like *"when does the sun rise in Denver this summer?"* |

---

## Table of Contents

1. [Features](#features)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Web App](#web-app)
5. [Importing Your Calendar](#importing-your-calendar)
6. [Command-Line Interface](#command-line-interface)
7. [MCP Server (Claude Integration)](#mcp-server-claude-integration)
8. [JSON API](#json-api)
9. [Development](#development)
10. [Accuracy & Attributions](#accuracy--attributions)

---

## Features

- **Sunrise & Sunset** — separate timed events for each day of the year, with day length in the description
- **Solstices & Equinoxes** — all-day events with the exact astronomical moment in the description; computed via Meeus astronomical algorithms (accurate to ~1 minute)
- **DST clock changes** — Spring Forward / Fall Back all-day events; omitted automatically for locations that don't observe DST
- **Day Length Calendar** — optional separate calendar with one all-day event per day showing hours of daylight; five title formats to choose from
- **Polar regions** — Polar Day / Polar Night all-day events for high-latitude locations (e.g. Tromsø)
- **Stable UIDs** — same inputs always produce the same event UIDs, so calendar subscription clients update in place
- **RFC 5545 compliant** — CRLF line endings, 75-octet line folding, VTIMEZONE component

---

## Requirements

- Python **3.11** or later
- Internet connection for geocoding (Nominatim/OpenStreetMap) — coordinates are not stored

---

## Installation

```bash
git clone https://github.com/youruser/sun-and-seasons-calendar.git
cd sun-and-seasons-calendar

python -m venv .venv

# Windows
.venv\Scripts\pip install -e ".[dev]"

# macOS / Linux
.venv/bin/pip install -e ".[dev]"
```

This installs all dependencies and registers two command-line entry points:
- `sun-and-seasons` — the CLI
- `sun-and-seasons-mcp` — the MCP stdio server

---

## Web App

Start the server:

```bash
# Windows
.venv\Scripts\uvicorn app.main:app --reload

# macOS / Linux
.venv/bin/uvicorn app.main:app --reload
```

Open **http://localhost:8000** in your browser.

### Steps

1. **Enter a location** — type any city, address, or region. The address is used only to look up coordinates and is never stored.
2. **Select a year** — defaults to the current year; supports 1901–2099.
3. **Download your calendar:**
   - **Main Calendar** — sunrise, sunset, solstices & equinoxes, and DST clock changes
   - **Day Length Calendar** *(optional)* — one all-day event per day with the duration of daylight; choose from five title formats

### Preview

Click **Show preview** to see a sample of the solar data, solstice/equinox times, and DST transitions before downloading.

---

## Importing Your Calendar

### Google Calendar

1. Open [calendar.google.com](https://calendar.google.com).
2. In the left sidebar, click **+** next to *Other calendars* → **Create new calendar**. Name it something like *Sun & Seasons 2026*.
   > **Important:** Create the new calendar *before* importing — the destination picker only appears when you have more than one calendar.
3. Go to **Settings** (gear icon) → **Import & export** → **Import**.
4. Choose your `.ics` file and select the calendar you just created.

**To remove:** In Settings, find the calendar under *Settings for my calendars* and click **Delete calendar**. All events disappear at once.

### Apple Calendar (macOS / iOS)

1. **macOS:** Double-click the `.ics` file. When prompted, choose **New Calendar** rather than adding to an existing one.
2. **iOS:** Open the file from Files or Mail, then tap **Add All**.

**To remove:** Right-click (or long-press) the calendar in the sidebar and choose **Delete Calendar**.

### Outlook (Desktop)

1. Go to **File → Open & Export → Import/Export**.
2. Choose **Import an iCalendar (.ics) or vCalendar file** and select your file.
3. When asked, choose **Import** (not Open). Create a dedicated calendar folder first if you want easy removal later.

### Outlook on the Web

1. Open [outlook.live.com](https://outlook.live.com), click the calendar icon.
2. Click **Add calendar → Upload from file**.
3. Select your `.ics` file and choose a destination calendar (create a new one first for easy removal).

### A Note on Removal

The `.ics` file is a **one-time import**, not a live subscription. The easiest way to remove all events later is to delete the entire dedicated calendar you imported into. If you imported into your main calendar you would need to delete each event individually — so creating a dedicated calendar (e.g. *"Sun & Seasons 2026"*) is strongly recommended.

### Event Reference

| Event | Type | Details |
|-------|------|---------|
| Sunrise | Timed (5 min) | Local time; sunrise, sunset, and day length in description |
| Sunset | Timed (5 min) | Local time; sunrise, sunset, and day length in description |
| March / June / September / December Solstice or Equinox | All-day | Exact astronomical moment in description (UTC and local) |
| DST Spring Forward | All-day | Only for locations that observe DST |
| DST Fall Back | All-day | Only for locations that observe DST |
| Polar Day | All-day | High-latitude only — sun above horizon all day |
| Polar Night | All-day | High-latitude only — sun below horizon all day |
| Day length *(optional calendar)* | All-day | Duration of daylight in your chosen format |

---

## Command-Line Interface

After installation, activate the virtual environment and use the `sun-and-seasons` command.

```bash
# Activate the venv first:
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
```

### `sun` — Sunrise, solar noon, and sunset

```bash
# Full year for a location
sun-and-seasons sun "Denver, CO"
sun-and-seasons sun "Denver, CO" --year 2026

# Single date
sun-and-seasons sun "Denver, CO" --date 2026-06-21

# Skip geocoding — use coordinates directly
sun-and-seasons sun --lat 34.052 --lon -118.243 --year 2026
```

Sample output:
```
Denver, CO, USA  |  America/Denver  |  2026
Date          Sunrise    Noon       Sunset     Day length
----------------------------------------------------------
2026-01-01    7:22 MST   12:13 MST  17:06 MST  9h 44m
2026-06-21    5:31 MDT   12:55 MDT  20:19 MDT  14h 48m
...
```

### `seasons` — Solstices, equinoxes, and DST

```bash
sun-and-seasons seasons "London, UK" --year 2026
sun-and-seasons seasons "Phoenix, AZ"   # shows "does not observe DST"
```

### `ics` — Generate and save an ICS file

```bash
# Main calendar (sunrise, sunset, seasons, DST)
sun-and-seasons ics "Tokyo, Japan" --year 2026
sun-and-seasons ics "Tokyo, Japan" --year 2026 --out tokyo-2026.ics

# Day length calendar
sun-and-seasons ics "Tokyo, Japan" --year 2026 --daylength
sun-and-seasons ics "Tokyo, Japan" --year 2026 --daylength --fmt colon --out tokyo-daylen.ics
```

Day length format options for `--fmt`:

| Value | Example |
|-------|---------|
| `hm` *(default)* | `10h 23m` |
| `hm_label` | `10h 23m daylight` |
| `colon` | `10:23` |
| `decimal` | `10.4 hrs` |
| `hms` | `10h 23m 45s` |

### `preview` — Full summary

```bash
sun-and-seasons preview "Tromsø, Norway"
sun-and-seasons preview "Sydney, Australia" --year 2026
```

Shows location, timezone, DST transitions, solstices/equinoxes, solar times for sample dates across the year, and year statistics (shortest/longest day, average day length, polar event counts).

### Common Options

All subcommands accept:

| Option | Description |
|--------|-------------|
| `ADDRESS` | Place name or address, e.g. `"Denver, CO"` or `"Sydney, Australia"` |
| `--lat FLOAT` | Latitude — use with `--lon` to skip geocoding |
| `--lon FLOAT` | Longitude — use with `--lat` to skip geocoding |
| `--year YYYY` | Calendar year (default: current year, range: 1901–2099) |

---

## MCP Server (Claude Integration)

The MCP server exposes the Sun & Seasons compute modules as tools that Claude can call directly. Once configured in Claude Desktop, you can ask questions like:

- *"When does the sun rise in Denver on the summer solstice 2026?"*
- *"How many hours of daylight does Tromsø get in June?"*
- *"Does Phoenix observe daylight saving time?"*
- *"Generate a download link for my 2026 Tokyo sunrise calendar."*

### Setup

Edit your Claude Desktop config file:

| Platform | Location |
|----------|----------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

#### Option A — Run directly with Python (recommended for local development)

```json
{
  "mcpServers": {
    "sun-and-seasons": {
      "command": "C:/path/to/sun-and-seasons-calendar/.venv/Scripts/python.exe",
      "args": ["C:/path/to/sun-and-seasons-calendar/mcp_server.py"]
    }
  }
}
```

Replace the paths with the actual location of your project directory.

**Windows note:** Use forward slashes (`/`) or escaped backslashes (`\\`) in the JSON.

#### Option B — Use the installed entry point

```json
{
  "mcpServers": {
    "sun-and-seasons": {
      "command": "C:/path/to/sun-and-seasons-calendar/.venv/Scripts/sun-and-seasons-mcp.exe"
    }
  }
}
```

After editing the config, **fully quit and reopen Claude Desktop** (closing the window is not enough).

### Available Tools

| Tool | What it does |
|------|-------------|
| `geocode` | Convert a place name or address to lat/lon candidates |
| `get_timezone` | Return the IANA timezone ID for a lat/lon coordinate |
| `get_solar_day` | Sunrise, solar noon, sunset, and day length for a single date |
| `get_solar_year` | Full-year statistics and monthly sample table |
| `get_seasons` | Solstices and equinoxes with local and UTC times |
| `get_dst` | DST clock-change dates, or confirmation that a location doesn't use DST |
| `generate_ics_url` | Build the ICS download URL for the running web server |

All tools are read-only and pure-compute. The only network call is `geocode`, which queries Nominatim/OpenStreetMap. No data is stored.

### Running the server manually (for testing)

```bash
# Windows
.venv\Scripts\python mcp_server.py

# macOS / Linux
.venv/bin/python mcp_server.py
```

The server speaks the MCP stdio protocol on stdout/stdin. Use `Ctrl+C` to stop it.

---

## JSON API

The web server exposes a JSON API for building other tools on top of the compute modules.

### `GET /api/v1/tzid`

Return the IANA timezone ID for a coordinate.

```
GET /api/v1/tzid?lat=34.052&lon=-118.243
→ {"tzid": "America/Los_Angeles"}
```

### `GET /api/v1/sun`

Full year of solar data as JSON.

```
GET /api/v1/sun?lat=34.052&lon=-118.243&year=2026
```

Response shape:
```json
{
  "meta": {"lat": 34.052, "lon": -118.243, "tzid": "America/Los_Angeles", "year": 2026},
  "days": [
    {
      "date": "2026-01-01",
      "sunrise": "2026-01-01T07:00:00-08:00",
      "sunset":  "2026-01-01T17:00:00-08:00",
      "solar_noon": "...",
      "day_length_sec": 36000,
      "polar_event": null
    }
  ],
  "events": {
    "seasons": [{"kind": "march_equinox", "utc": "...", "local": "..."}],
    "dst":     [{"kind": "dst_start", "local_date": "2026-03-08", "offset_before": "-08:00", "offset_after": "-07:00"}]
  }
}
```

### `POST /geocode`

```
POST /geocode
Content-Type: application/json
{"address": "Denver, CO"}

→ {"candidates": [{"lat": 39.7392, "lon": -104.9847, "display_name": "Denver, CO, USA"}]}
```

### `GET /calendar/{year}/{lat},{lon}.ics`

Download the main ICS calendar.

```
GET /calendar/2026/34.052,-118.243.ics?download=true&display_name=Los+Angeles
```

### `GET /calendar/{year}/{lat},{lon}-daylength.ics`

Download the day length ICS calendar.

```
GET /calendar/2026/34.052,-118.243-daylength.ics?download=true&fmt=colon
```

Query parameters: `fmt` (hm, hm_label, colon, decimal, hms), `display_name`, `download`, `tzid`

---

## Development

### Running tests

```bash
# All tests (excluding live network calls — fast, no internet required)
.venv\Scripts\python -m pytest tests/ -v -m "not live"

# Include live geocoding tests (requires internet)
.venv\Scripts\python -m pytest tests/ -v
```

181 tests covering: solar computation, season algorithms (validated against USNO published tables for 2024–2026), timezone/DST detection, ICS RFC 5545 compliance, FastAPI routes, CLI subcommands, and MCP tool functions.

### Project structure

```
app/
  cli.py          CLI — sun-and-seasons entry point
  geocode.py      Address -> lat/lon via Nominatim/OSM
  ics_builder.py  RFC 5545 ICS calendar builder
  main.py         FastAPI web application and routes
  seasons.py      Solstice/equinox computation (Meeus Ch. 27 + delta-T)
  solar.py        Sunrise/sunset/day-length computation (Astral/NREL SPA)
  timezone.py     IANA tzid lookup and DST transition detection
mcp_server.py     MCP stdio server — sun-and-seasons-mcp entry point
preview.py        Legacy command-line preview script
static/           CSS
templates/        Jinja2 HTML templates (index.html, help.html)
tests/            pytest test suite (181 tests)
```

### Linting

```bash
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format .
```

---

## Accuracy & Attributions

| Data | Source | Accuracy |
|------|--------|----------|
| Sunrise / Sunset | [Astral](https://github.com/sffjunkie/astral) — NREL SPA algorithm | ~1 minute |
| Solstices / Equinoxes | Meeus *Astronomical Algorithms* Ch. 27 + ΔT correction | ~1 minute (1951–2050) |
| DST transitions | Python `zoneinfo` (IANA tz database) | Exact |
| Timezone lookup | [timezonefinder](https://github.com/jannikmi/timezonefinder) (offline) | Exact for populated areas |
| Geocoding | [Nominatim / OpenStreetMap](https://nominatim.openstreetmap.org/) | Dependent on OSM data quality |

Address lookups use the user agent `sun-and-seasons-calendar/0.1`. The address string is used only to resolve coordinates and is never stored or logged by this application. See [Nominatim's usage policy](https://operations.osmfoundation.org/policies/nominatim/) for their terms.

### Libraries

- [Astral](https://sffjunkie.github.io/astral/) — Apache-2.0
- [icalendar](https://icalendar.readthedocs.io/) — BSD
- [timezonefinder](https://github.com/jannikmi/timezonefinder) — MIT
- [geopy](https://geopy.readthedocs.io/) — MIT
- [FastAPI](https://fastapi.tiangolo.com/) — MIT
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — MIT

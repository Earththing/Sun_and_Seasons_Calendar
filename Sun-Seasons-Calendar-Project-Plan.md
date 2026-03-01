# Project Plan — Location‑Aware "Sun & Seasons" Calendar (ICS feed + download)

## Executive summary

Build a small web app and service that, given a user's location and year, generates a calendar of astronomical/civil events—**sunrise, sunset, day length, solstices & equinoxes, season starts, and DST transitions**—and exposes them as a **downloadable ICS file** for one‑time import.

> **Scope decision**: Hosted subscription feeds (webcal/Google/Outlook) are out of scope. The project focuses on local-first download-only ICS, a JSON API, an MCP server for LLM integration, and a visualization subsystem. No hosting infrastructure required.

Imported files are static; users should import them into a **separate calendar** that can be deleted to remove everything at once.

---

## Target users & value

- Everyday users who want local sunrise/sunset and season markers on their personal calendar.
- Photographers, outdoor athletes, educators, and teams planning around daylight.
- Value: single‑click subscribe, accurate time zone & DST handling, and easy remove/hide UX.

---

## Primary deliverables

- **Web UI (responsive)**: Address input → Options → Preview → **Download .ics**
- **ICS download endpoint**: `GET /calendar/{year}/{lat},{lon}.ics?tzid=…&opts=…`
- **JSON API**: `GET /api/v1/sun?lat=…&lon=…&year=…` → JSON (useful for developers and internal use)
- **MCP server**: exposes all solar/calendar tools to Claude and other LLM clients
- **Visualization subsystem** (optional): daylight heatmaps, year-long animations
- **Docs/help**: how to import, manage, and delete calendar files in Google/Apple/Outlook

---

## Functional requirements (what it must do)

1. **Input**
    - Location: user enters a street address or city/region; the backend geocodes it to lat/lon using a free geocoding API (e.g., Nominatim/OpenStreetMap). **Coordinates are not stored beyond the request.**
    - Elevation: default to sea level (0 m) for SPA; do not ask the user unless they opt in to advanced mode.
    - Year: default current year; allow any year in [1901..2099].
    - Options: include twilight levels (civil/nautical/astronomical), golden hour, event naming style, 12/24‑hour clock.
2. **Compute** (per day or key dates)
    - Sunrise, sunset, solar noon; optionally twilights, golden hour; **day length**.
    - **Solstices & equinoxes** (UT/TT conversion via Meeus algorithms).
    - **Season starts** (astronomical: equinox/solstice moments; optionally meteorological seasons).
    - **DST start/end** for the location's IANA time zone.
3. **Output**
    - **Separate events for Sunrise and Sunset** (not a single spanning event). Day length in both descriptions.
    - Hosted ICS feed (subscribe) and downloadable ICS (import).
    - Each event: start/end, summary, description with solar metrics, location line with coordinates.
    - **VTIMEZONE** block. **ICS 2.0 (RFC 5545).**
    - **JSON API** alongside ICS for developer access.
4. **Privacy**
    - Address is geocoded to lat/lon server-side; only the rounded coordinates (≈10 km grid) are used for any logging/analytics. The address string is never logged or stored.
5. **Removal/hide UX**
    - Subscribed: show "Unsubscribe / Hide" instructions.
    - Downloaded import: recommend importing into a **separate calendar** so users can delete it to remove all events.

---

## Non‑functional requirements

- **Accuracy**:
    - Solar times via **Astral** (Python, Apache-2.0) — wraps NREL SPA; accurate to ~±1 min for rise/set.
    - Equinox/solstice via **Meeus Chapter 27** algorithms with ΔT handling.
    - Time zones via **IANA tzdb**; no hardcoded DST rules.
- **Performance**: server-side memoization and CDN caching per `{year, lat, lon, options}` tuple.
- **Portability**: ICS validated against RFC 5545; tested on Google/Apple/Outlook.
- **Privacy**: address is never stored; coordinates rounded for analytics only.
- **Local-first**: runs on a home computer (localhost) from day one; deployment to hosting is a later phase.

---

## Tech stack (decided)

| Layer | Choice | Rationale |
|---|---|---|
| Language | **Python 3.12+** | Best library support (Astral, timezonefinder, icalendar); familiar |
| Web framework | **FastAPI** | Async, automatic OpenAPI docs, fast enough for this workload |
| Solar compute | **Astral** (Python) | Apache-2.0; wraps SPA/NREL; handles twilight, golden hour |
| Equinox/solstice | **Meeus** (custom impl or `ephem`) | Accuracy within ~1 min for 1901–2099 |
| Timezone lookup | **timezonefinder** | Offline lat/lon → IANA tzid; no API key needed |
| IANA tzdb | **pytz** or **zoneinfo** (stdlib 3.9+) | DST transitions for any year |
| Geocoding | **Nominatim (OSM)** via `geopy` | Free, no API key for low-volume use |
| ICS rendering | **icalendar** (Python) | RFC 5545 compliant; handles line folding, CRLF, VTIMEZONE |
| Frontend | **Plain HTML/CSS/JS** (MVP) | No framework needed for a form + results page |
| Dev tooling | **uv** (package manager), **pytest**, **ruff** | Fast, modern Python tooling |
| **MCP server** | **FastMCP** | Exposes all API tools to Claude and other LLM clients |
| **Visualization** *(optional)* | **matplotlib + cartopy + numpy + shapely** | Daylight heatmap frames and year-long animations |
| **Video assembly** *(optional)* | **ffmpeg** (via `viz/make_video.py`) | Assembles frame PNGs into MP4 animation via concat demuxer |

---

## Identity & ICS metadata

- **PRODID**: `-//Sun and Seasons//Sun and Seasons Calendar v1//EN`
- **UID format**: `{year}-{eventcode}-{date}-{latE6}-{lonE6}@sunandseasons.local` (use a real domain once hosted)
- **X-WR-CALNAME**: `Sun & Seasons — {year} — {nearest place or lat,lon}`
- **X-WR-TIMEZONE**: IANA tzid

> **Note on the domain in UIDs**: Calendar clients use UIDs to match and update events in subscribed feeds. The `@...` suffix just needs to be globally unique — `@sunandseasons.local` is fine for local use. Once you have a real domain, update it (and keep it stable afterward).

---

## Core domain logic & algorithms

### 1) Geocoding (address → lat/lon)

- User types an address string → backend calls Nominatim → returns lat, lon, display name.
- Address string is discarded after geocoding. Only lat/lon is passed downstream.
- Edge cases: ambiguous address → return top N candidates for user to pick; no result → prompt user to try again.

### 2) Time zone + DST (IANA tzdb)

- Resolve `tzid` from lat/lon via **timezonefinder** (offline, no API needed).
- Use **zoneinfo** to compute local offsets and **DST transitions for the given year**.
- Provide DST start/end as all-day events.

### 3) Solar events (sunrise/sunset/day length)

- Use **Astral** for sunrise, sunset, solar noon, and optional twilights/golden hour.
- **Elevation**: default 0 m; standard atmosphere pressure/temperature defaults.
- **Day length** = `sunset − sunrise` (clip to [0, 24 h]; polar day/night → special all-day label event).
- Edge cases: no sunrise/sunset at high latitudes → all-day event: "Polar Day — sun above horizon all day."

### 4) Solstices & equinoxes / Season start

- **Meeus Chapter 27**: compute TT instants → convert to UTC using ΔT → convert to local time.
- Accuracy ≲ 1 minute for 1951–2050. Publish as instantaneous events (1-minute duration for calendar visibility).
- Meteorological seasons (Mar–May, Jun–Aug, etc.) as an opt-in option, Phase 2.

---

## Calendar publishing strategy

**Download-only** — no hosted subscription feed.

- ICS files are generated on demand and downloaded by the user.
- Clear note in the UI: imports are **static** and won't auto-update.
- Prompt users to *create a new calendar first* before importing, so they can delete it later to remove all events in one step.
- No hosting infrastructure, domain, or CDN required.

---

## ICS content & formatting (RFC 5545)

- One VCALENDAR per file; `VERSION:2.0`, `PRODID`, `CALSCALE:GREGORIAN`.
- Include VTIMEZONE matching tzid.
- **Separate VEVENT for Sunrise and Sunset** each day (not a single spanning event).
- Day length in DESCRIPTION of both events.
- DST transitions: all-day events with offset change in description.
- Solstice/Equinox: 1-minute duration timed events.
- `X-ALT-DESC;FMTTYPE=text/html` for HTML table body (optional rich view).
- Line folding at 75 octets; CRLF line endings. Validate with icalendar parser in CI.

### UID design

```
{year}-SUNRISE-{date}-{latE6}-{lonE6}@sunandseasons.local
{year}-SUNSET-{date}-{latE6}-{lonE6}@sunandseasons.local
{year}-SOLSTICE-JUNE-{latE6}-{lonE6}@sunandseasons.local
```

UIDs must be stable across regenerations so subscribed calendars update in place.

---

## System architecture

```
[Browser]
    │  address + year + options
    ▼
[FastAPI app — app/main.py]
    ├── GET /                        → HTML form (address, year, options)
    ├── POST /geocode                → Nominatim → {lat, lon, display_name}
    ├── GET /api/v1/sun              → JSON solar events
    ├── GET /api/v1/tzid             → IANA tzid for lat/lon
    ├── GET /calendar/{year}/{lat},{lon}.ics  → ICS feed or download
    └── GET /help                   → calendar client instructions

[MCP server — mcp_server.py]           ← LLM clients (Claude, etc.)
    ├── get_solar_day(lat,lon,date)  → sunrise/sunset/day_length JSON
    ├── get_solar_year(lat,lon,year) → year stats + monthly samples
    ├── get_seasons(lat,lon,year)    → solstice/equinox local times
    ├── get_dst(lat,lon,year)        → DST transitions
    ├── get_timezone(lat,lon)        → IANA tzid
    ├── geocode(address)             → lat/lon candidates
    ├── generate_ics_url(...)        → ICS calendar download URL
    └── render_daylight_frame(...)   → PNG heatmap (requires [viz])

[Compute layer — pure Python, no HTTP]
    ├── geocode.py        address → (lat, lon)
    ├── timezone.py       (lat, lon) → tzid, DST transitions
    ├── solar.py          Astral wrapper → daily events JSON
    ├── seasons.py        Meeus → equinox/solstice UTC + local
    └── ics_builder.py    JSON → RFC 5545 ICS text

[Visualization layer — viz/ — optional [viz] extras]
    ├── render_day.py     daylight heatmap (single frame or batch)
    │   ├── GridSpec      pre-built land mask + tz cache for batch speed
    │   ├── 5 scale modes region / year / day / reference / percentile
    │   └── polar sentinels: black=polar night, white=polar day
    └── make_video.py     ffmpeg automation: frames → MP4
```

**Storage**: None. All computation is on-demand. No database required for MVP.

---

## Data model (internal JSON)

```json
{
  "meta": {
    "lat": 34.091, "lon": -117.889,
    "tzid": "America/Los_Angeles", "year": 2026,
    "display_name": "Upland, CA"
  },
  "days": [
    {
      "date": "2026-01-01",
      "sunrise": "2026-01-01T07:00:11-08:00",
      "sunset":  "2026-01-01T16:52:33-08:00",
      "solar_noon": "2026-01-01T11:56:22-08:00",
      "day_length_sec": 35542,
      "twilight": {
        "civil_begin": null, "civil_end": null,
        "nautical_begin": null, "nautical_end": null,
        "astronomical_begin": null, "astronomical_end": null
      },
      "golden_hour": { "morning_end": null, "evening_begin": null },
      "polar_event": null
    }
  ],
  "events": {
    "seasons": [
      { "kind": "march_equinox",      "utc": "2026-03-20T21:45:50Z", "local": "2026-03-20T14:45:50-07:00" },
      { "kind": "june_solstice",       "utc": "2026-06-21T15:24:23Z", "local": "2026-06-21T08:24:23-07:00" },
      { "kind": "september_equinox",   "utc": "…", "local": "…" },
      { "kind": "december_solstice",   "utc": "…", "local": "…" }
    ],
    "dst": [
      { "kind": "dst_start", "local_date": "2026-03-08", "offset_change": "-08:00 → -07:00" },
      { "kind": "dst_end",   "local_date": "2026-11-01", "offset_change": "-07:00 → -08:00" }
    ]
  }
}
```

Twilight and golden_hour fields are `null` unless those options are enabled — stubbed from day one so the schema doesn't need versioning later.

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | HTML UI |
| POST | `/geocode` | Address → `{lat, lon, display_name}` |
| GET | `/api/v1/tzid?lat=&lon=` | → IANA tzid |
| GET | `/api/v1/sun?lat=&lon=&year=&tzid=&opts=` | → JSON daily solar events |
| GET | `/calendar/{year}/{lat},{lon}.ics` | ICS feed (subscribe) |
| GET | `/calendar/{year}/{lat},{lon}.ics?download=1` | ICS download |
| GET | `/help` | Calendar client instructions |

---

## Rate limiting / abuse (pragmatic)

For local use: slowapi rate limiting is in place as a courtesy guard.
Year range is bounded to [1901..2099] server-side to prevent unbounded compute. No hosting infrastructure is planned, so CDN caching is not a concern.

---

## Project structure

```
Sun_and_Seasons_Calendar/
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI app, routes
│   ├── geocode.py        # address → lat/lon via Nominatim
│   ├── timezone.py       # lat/lon → tzid, DST transitions
│   ├── solar.py          # Astral wrapper, daily events
│   ├── seasons.py        # Meeus equinox/solstice
│   └── ics_builder.py    # JSON → RFC 5545 ICS
├── templates/
│   ├── index.html
│   └── help.html
├── static/
│   └── style.css
├── tests/
│   ├── test_solar.py
│   ├── test_seasons.py
│   ├── test_ics.py
│   ├── test_timezone.py
│   └── test_viz.py       # visualization tests (requires [viz] extras)
├── viz/
│   ├── render_day.py     # daylight heatmap renderer (single frame or batch)
│   ├── make_video.py     # ffmpeg automation: frames → MP4
│   └── poc_june8.py      # original proof-of-concept (kept for reference)
├── mcp_server.py         # FastMCP server exposing all tools to LLM clients
├── Sun-Seasons-Calendar-Project-Plan.md
├── pyproject.toml        # uv / pip dependencies (core + [viz] optional extras)
├── .gitignore
└── README.md
```

---

## Resolved decisions

| # | Decision | Choice |
|---|---|---|
| 1 | SPA vs library | **Astral** (don't implement SPA from scratch for MVP) |
| 2 | Twilight in MVP? | Deferred to Phase 3 (MVP: sunrise/sunset/day length only) |
| 3 | One event vs two per day | **Two separate events** (Sunrise + Sunset) |
| 4 | Meteorological seasons | Deferred to Phase 3 |
| 5 | JSON API | **Yes** — minimal extra cost, useful for devs |
| 6 | Location input | **Address field** → geocode to lat/lon; address not stored |
| 7 | Rate limiting | **slowapi** in production; CDN caching recommended for hosting |
| 8 | LLM integration | **FastMCP server** exposing all solar/calendar tools |
| 9 | Visualization | **Optional `[viz]` extras** — matplotlib/cartopy heatmaps + ffmpeg video |
| 10 | Viz color scale | **5 modes**: region, year, day, reference, percentile (with `--clip-pct`) |
| 11 | Polar day/night in viz | **Sentinels**: black = 0 h (polar night), white = 24 h (polar day) |

---

## Roadmap (phased)

**MVP ✅ COMPLETE**

- ✅ Address input → geocode → tzid → Astral sunrise/sunset/day length
- ✅ Meeus equinox/solstice events
- ✅ DST start/end events from tzdb
- ✅ ICS download (RFC 5545, VTIMEZONE, stable UIDs)
- ✅ JSON API endpoint
- ✅ Minimal HTML UI
- ✅ pytest suite (186 core tests covering solar, seasons, ICS, timezone, FastAPI routes)

**Phase 2 ✅ COMPLETE**

- ✅ Polar day/night edge case handling (24 h / 0 h sentinel values)
- ✅ Rate limiting (slowapi), request-level logging, geocode timeouts
- ✅ MCP server (`mcp_server.py`) — exposes all tools to Claude and other LLM clients via FastMCP
- ✅ `sun-and-seasons` CLI subcommand (pyproject entry point)
- ✅ Comprehensive README with install, usage, API, and MCP docs
- ~~ICS subscription feed (hosted)~~ — **removed from scope** (download-only is sufficient)
- ⏳ Twilight options (civil/nautical/astronomical) — deferred to Phase 3
- ⏳ Meteorological seasons toggle — deferred to Phase 3
- ⏳ UI polish, accessibility

**Visualization subsystem ✅ COMPLETE** *(optional extras, `pip install -e ".[viz]"`)*

- ✅ `viz/render_day.py` — daylight heatmap renderer
  - Single frame or batch (full year / date range) with `GridSpec` for fast repeated rendering
  - Five color scale modes: `region`, `year`, `day`, `reference`, `percentile`
  - `--clip-pct N` for tunable percentile clipping (better within-day north-south gradient)
  - Polar sentinels: **black** = polar night (0 h), **white** = polar day (24 h)
  - Colorbar `extend` arrows show sentinel colours automatically
  - All three regions: lower 48, Alaska, Hawaii; `--region all` composite frame
  - ETA progress reporting for batch runs; `--overwrite` to re-render existing frames
- ✅ `viz/make_video.py` — ffmpeg automation
  - concat demuxer (Windows-safe); even-pixel-dimension fix for H.264/H.265
  - Year / date-range filtering; auto output naming; FPS, CRF, codec options
- ✅ `render_daylight_frame` MCP tool (lazy import, graceful error if [viz] absent)
- ✅ 123 visualization tests (region definitions, argparse, color scale logic, GridSpec, percentile helpers, polar-sentinel settings, integration)

**Phase 3**

- Golden hour events
- Twilight options (civil/nautical/astronomical)
- Meteorological seasons toggle
- Printable/monthly preview
- Shareable preset URLs
- Multi-year ICS files
- i18n / language options
- API documentation page
- Telemetry (privacy-preserving, optional)

---

## Testing & validation

**Current status: 309 tests, all passing.**

- **Unit tests**: Astral outputs vs NREL reference points; Meeus dates vs USNO published tables (2024–2026, ±2 min tolerance); ICS rendering (line folding, CRLF, VTIMEZONE, UID stability, separate Sunrise/Sunset events).
- **API tests**: FastAPI route tests via `TestClient`; rate limiting, geocode timeout handling, error responses.
- **MCP tests**: all tool functions covered including edge cases.
- **Visualization tests** (123, requires `[viz]` extras): region definitions, argparse (all 5 scale modes, batch args), color scale resolution, GridSpec, percentile helpers (`_percentile_vmin_vmax`, `_sample_annual_data`), polar-sentinel colormap settings (`_daylight_cmap_settings`), output path resolution, integration tests (compute grid, verify physical properties).
- **Integration** (manual): rendered lower 48 heatmap frames at step=0.1°, assembled into MP4 via `make_video.py`.
- **Client integration** (Phase 3): Google Calendar subscribe/unsubscribe/hide; Apple Calendar; Outlook web.

---

## Security & privacy

- No login required; all computation is anonymous.
- Address string is never logged, stored, or forwarded — only geocoded to lat/lon.
- Analytics (Phase 3): store only rounded coordinates (~10 km grid).
- Abuse: year range bounded [1901..2099]; CDN caching reduces compute load.

---

## Licensing & attributions

- **Astral** — Apache-2.0.
- **timezonefinder** — MIT.
- **icalendar (Python)** — BSD.
- **Nominatim/OSM** — ODbL; must credit OpenStreetMap contributors.
- **IANA tzdb** — BCP 175, permissive.
- Standards: RFC 5545 (iCalendar), RFC 5546 (iTIP, referenced for CANCEL caveat).

---

## Open questions

1. Should the UI show a map pin after geocoding so the user can confirm the right location was found?
2. Should we support address input in languages other than English from day one, or defer to Phase 3?
3. Should the Nominatim user-agent URL be updated once the project has a public GitHub URL?

---

## References

- **iCalendar (RFC 5545)** — syntax, components, time zones.
- **iTIP (RFC 5546)** — scheduling semantics.
- **IANA Time Zone Database** — DST rules.
- **NREL SPA** — authoritative solar position algorithm (wrapped by Astral).
- **Astral (Python)** — sun/moon/twilight library (Apache-2.0).
- **Meeus: Astronomical Algorithms** — equinox/solstice & ΔT.
- **Nominatim/OpenStreetMap** — geocoding (free, attribution required).
- **Google Help** — delete/unsubscribe/hide calendars.
- **webcal scheme** — subscription UX and Outlook caveats.

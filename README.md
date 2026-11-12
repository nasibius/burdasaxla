# BurdaSaxla — harada saxlamaq olar?

A map that applies Azerbaijan's road-traffic stopping rules to **each side of every street** in
the 28 May area of Baku. It also recommends where a driver can legally drop off or pick up a passenger.

* **Red (PROHIBITED):** a *verified* rule of the Law “On Road Traffic” (517-IQ) forbids **stopping (dayanma, Art. 1.29)**
  here for the selected vehicle class. A pick-up/drop-off legally *is* stopping.
* **Green (ALLOWED):** the curb was **checked on site** (a reviewed survey observation, or an official AYNA zone) and
  no prohibition or open question applies.
* **Yellow (UNVERIFIED):** incomplete, unverified or conflicting information. **Missing sign data never means
  stopping is legal.** Until a real field survey is entered, the map has no green curbs at all.

Legal decisions are made by a **deterministic rule engine** (Python + Shapely). No AI is involved. Every rule cites
its article, quotes the official text from e-qanun.az and states how certain it is. See
**[docs/LEGAL_VERIFICATION.md](docs/LEGAL_VERIFICATION.md)**.

---

## Quick start

Requirements: Python 3.11+ and Node 18+.

```bash
# 1. Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                         # 66 tests
.venv/bin/uvicorn app.main:app --port 8000 --reload   # http://localhost:8000/docs
```

```bash
# 2. Frontend (dev, hot reload, proxies /api -> :8000)
cd frontend
npm install
npm run dev                                           # http://localhost:5173
```

Production uses one port: run `npm run build` in `frontend/`. The FastAPI app then serves `frontend/dist` at
http://localhost:8000.

* Admin panel: open `#admin` (button at top right). Default token: `burdasaxla-admin`. Override it with
  `BURDASAXLA_ADMIN_TOKEN`.
* Refresh the OSM data: `python3 backend/scripts/fetch_osm.py [south west north east]`. The fetcher tries the
  Overpass API first, then falls back to the main OSM API (`/api/0.6/map`).
* Basemap: Esri Canvas tiles by default (no key needed). To use CARTO or MapTiler with your own key, set
  `VITE_TILE_DARK` / `VITE_TILE_LIGHT` (and optionally `VITE_TILE_LABELS_*`).

## Hosting

There are two ways to run it:

| | Static demo (GitHub Pages) | Full app (API) |
|---|---|---|
| URL | https://nasibius.github.io/burdasaxla/ | your own host (Render, Docker, VM) |
| Map, reasons, search, drop-off / pick-up / driver recommendations | ✅ | ✅ |
| Admin panel, validation queue, conflict detection | — (read-only) | ✅ |
| Deploy | automatic on every push to `main` (`.github/workflows/pages.yml`) | `docker build` / Render blueprint |

**How the static demo works.** On deploy, the Python rule engine runs in CI (`backend/scripts/export_static.py`).
It writes every curb status and reason, plus compact road and walk graphs, to JSON. Legal decisions therefore still come
from Python. In the browser, `frontend/src/static/engine.ts` runs the routing and ranking part of the recommender. It is a
line-by-line port of `dropoff.py`. It is checked against the API on 80 random queries (40 trips × both vehicle
classes): the top recommendation, the door status and the driver-mode top pick were identical in 80/80.

**Running the full app with the API:**

```bash
docker build -t burdasaxla .
docker run -p 8000:8000 -e BURDASAXLA_ADMIN_TOKEN=change-me -v burdasaxla-data:/data burdasaxla
```

On Render: *New → Blueprint →* pick this repo. `render.yaml` creates a free web service and generates a random admin
token, which you can see in the service's Environment tab. The free plan has no persistent disk, so curated features
are reset whenever the service restarts. Attach a disk at `/data` to keep them.

| Env var | Default | Purpose |
|---|---|---|
| `BURDASAXLA_ADMIN_TOKEN` | `burdasaxla-admin` (logged as a warning) | Admin API token |
| `BURDASAXLA_DB` | `backend/data/burdasaxla.sqlite3` | SQLite file for curated features |
| `BURDASAXLA_OSM` | `backend/data/osm_raw.json` | OSM snapshot |
| `BURDASAXLA_DEFAULT_VEHICLE` | `taxi` | Vehicle class for the default map status |
| `MAPILLARY_TOKEN` | unset | Enables the Mapillary importer |
| `BURDASAXLA_DEMO_SURVEY` | unset | `1` adds one in-memory **SIMULATED EXAMPLE** survey area (never stored) so the map shows green. Every such curb is labelled SIMULATED in the map, cards, drawer and legend, is never `legally_confirmed`, and is ignored by AYNA planning. Enabled on the public demo (Pages + Render); turn off for real use. |
| `VITE_STATIC`, `VITE_BASE` | unset, `/` | Build the static variant / set its public path |

## Quality checks

* `backend`: `ruff check app tests scripts` and `pytest -q` (66 tests: verified rules, 3.27 vs 3.28, 1.4 vs 1.10, side/direction, exceptions,
  conflicts, unverified observations, recommender trust, evidence workflow, importers, security, concurrency). Both run in CI (`.github/workflows/ci.yml`) along with the frontend type-check and build.
* Inputs are validated. Out-of-range coordinates get a 422. A destination outside the area gets `outside_area`. A driver
  outside the area or off the road network gets a `warnings` entry instead of a silently missing car route.
* Admin geometry is checked for type, validity and being inside the modelled area *before* it is stored. A bad row that
  was stored earlier is skipped during a rebuild and reported in `feature_errors`, so it can't take the map down.
* Static file serving is confined to `frontend/dist` (blocks path traversal). Unknown `/api/*` paths return a JSON
  404. The admin token is compared in constant time.

## Features

| Mode | What it does |
|---|---|
| **Düşür** (drop-off) | Finds the best legal spot for a destination (up to 3). For each one you get the car route, the walk route, the walk distance and whether the passenger must cross the street. |
| **Götür** (pick-up) | The same, starting from the passenger's location. |
| **Sürücü** (driver) | The driver's own recommendation: the nearest legal places to stop from the current position, ranked by **driving time in the legal direction of travel**. |
| **Qapının qarşısı** | Shows the status of the curb directly in front of the destination, with the reason (e.g. "Bus stop, 15 m"). |
| **Segment drawer** | Click any curb to see its status, each rule with its legal reference, the source object (links to OSM), the rule version, whether the geometry is approximate, the data sources and the verification date. |
| **Admin** | Add 3.27/3.28 signs, 1.4/1.10 yellow markings, bus lanes, AYNA zones and survey areas. Each new item gets an impact preview and **conflict detection** (e.g. "a verified green curb would turn red"). Items go through a pending → approve/reject queue, with an audit log. Approving one recomputes the map. |

AZ/EN, dark/light theme, mobile bottom-sheet layout, draggable destination and car markers.

## Architecture

```
backend/
  scripts/fetch_osm.py   Data collection (Overpass → OSM API fallback) → data/osm_raw.json
  app/rules.py           Versioned legal rule catalog (distances are configuration, not code)
  app/citymodel.py       OSM parse → metric CRS (UTM 39N) → ways, curbs, rule engine, segmentation, graphs, search
  app/dropoff.py         Recommender: candidates → legal filter → direction-aware reachability → walk → safety → rank
  app/store.py           SQLite: curated features, validation status, audit log
  app/main.py            FastAPI endpoints (+ serves the built frontend)
frontend/                React 18 + TypeScript + Vite + Leaflet (canvas renderer)
```

### How curbs are modelled
Each drivable OSM way is normalised so that one-way roads point with traffic. Its two curbs (left/right) are modelled
separately. Every rule produces an interval, in metres along the way, on a specific side. Each curb is cut at every
interval boundary, which gives the **curb segments**. Every segment stores its id, way, side, compass side, direction
of travel, reasons (rule id + version + legal reference + source object), notes, coverage, sources, last-verified
date and confidence.

### Rules implemented

The rules were checked on 2026-11-12 against the official consolidated text (e-qanun.az framework 3423, including
amendment 471-VIIQD of 14.07.2026). The full table with quotes, exceptions and v1 → v2 fixes is in
[docs/LEGAL_VERIFICATION.md](docs/LEGAL_VERIFICATION.md), and the app's **Qaydalar / Rules** button shows the same
catalog. Summary:

| Effect | Rules |
|---|---|
| **RED** (verified prohibition of stopping) | crossing ±5 m (52.IV.4), intersection +5 m from the crossed edge (52.IV.6), 15 m from a bus stop (52.IV.7), bus lane with solid line (48.IV), tunnel, bridge with < 3 lanes, under bridges (52.IV.2), level crossing, motorway, roundabout, blocking a driveway (52.IV.8), bike lane (52.IV.10-1), taxi stand for non-taxis (52.IV.10-2), sign 3.27 zone, 1.4 line **paired with 3.27**, reviewed field observations of other 52.IV clauses |
| **YELLOW** (can't be decided from the data) | not surveyed, bus lane with unknown line type (dashed lines allow drop-off), bridge with unknown lane count, possible T-junction exception, 1.4 line without a 3.27 sign, traffic-signal visibility (no distance in law), unreviewed observations, conflicting sources |
| **info** (doesn't restrict stopping) | 3.28 and 1.10 (restrict *durma*, not *dayanma*), dashed bus lane, left side of one-way roads, single row, official AYNA zone |

Vehicle classes: `taxi` (default) and `private`. They differ only where the law gives exemptions, currently taxi stands.

### Recommendation algorithm
1. **Candidates:** VERIFIED segments at least 7 m long. The spot on each segment is the point closest to the destination,
   kept 3.5 m inside the segment ends.
2. **Legal filter:** only VERIFIED segments are used. Gray and red are never recommended.
3. **Vehicle accessibility:** one multi-source Dijkstra run from the driver over a directed road graph (`oneway` is
   respected). A spot counts only if the car can reach it **travelling in the curb's legal direction**.
4. **Pedestrian routing:** Dijkstra from the destination over the walk graph (footways and streets).
5. **Safety:** if the destination is on the other side of the same street, the passenger must cross. A zebra within
   120 m adds a small penalty; no zebra adds a large one and a warning.
6. **Ranking:** walk metres + crossing penalty + 1.2 × driving seconds, with a bonus for official AYNA zones. Results
   are spread out (at least 35 m apart) and capped at 3.
7. If nothing qualifies, the response says so explicitly (`message: "no_verified_spot"`).

## API (see `/docs`)

| Endpoint | Purpose |
|---|---|
| `GET /api/meta` | Area, OSM snapshot time, ruleset version, stats |
| `GET /api/map/segments[?status=]` | GeoJSON curb segments |
| `GET /api/segments/{id}` | Full reasons, sources, data quality |
| `GET /api/map/context` | Crossings, bus stops, signals |
| `GET /api/search?q=` | Local POI/street search (diacritic-insensitive: `kuc` finds `küçə`) |
| `POST /api/dropoff/recommendations` | `{destination:[lon,lat], origin?, mode, max_walk_m}` |
| `POST /api/driver/nearest-stops` | `{origin:[lon,lat], radius_m?}` |
| `GET /api/official-zones`, `GET /api/features` | Verified curated data |
| `GET /api/validation/tasks` 🔒 | Pending items with impact + conflicts |
| `POST /api/admin/features` 🔒, `POST /api/admin/preview` 🔒 | Add / preview a feature |
| `POST /api/validation/approve` 🔒 | `{id, decision: verified\|rejected, geometry?}` |
| `DELETE /api/admin/features/{id}` 🔒, `GET /api/admin/audit` 🔒 | |

🔒 = requires the `X-Admin-Token` header.

## Data sources & honesty notes

| Source | What it gives | Coverage in 28 May (2026-11-12) |
|---|---|---|
| OpenStreetMap (ODbL) | roads, crossings, stops, signals, bus/bike lanes | 93 km of curb, 396 crossings, 50 bus stops/platforms, 56 signals, 6.9 km bike lanes. **0 traffic_sign tags, 0 stopping-restriction tags.** |
| Official / AYNA (ayna.gov.az) | taxi stands, pick-up zones | **No machine-readable dataset found.** Enter zones by hand with their source URL. |
| Mapillary | detected signs, positions computed from several images | Importer ready (`MAPILLARY_TOKEN`). Coverage **not measured**: no token was available. |
| Field survey / geotagged photos | signs, markings, survey areas | **0 so far.** Entered in Admin or by GeoJSON import. |

* **Nothing is fabricated.** The v1 demo “survey rectangle” has been retired (marked rejected with a note), so
  green only comes from real reviewed observations. Synthetic data exists only in `backend/tests/fixtures.py`, is
  labelled as such, and is never written to the app database.
* **Camera position ≠ sign position.** EXIF GPS is stored as the *camera* position. The reviewer places the sign
  where it stands, and approval is refused if a sign sits exactly at the camera position. Mapillary signs use
  Mapillary's computed position, not a camera location.
* **Every observation is traceable:** observer, date, source, and a photo / URL / reference are required before it
  can be verified. Automated sources (OSM, Mapillary, AI) always enter as *pending*. Editing a verified item sends it
  back to review. Everything is written to the audit log.
* **Approximations:** curb lines are offsets of the road centreline, road widths are estimated, and crossing width is
  estimated. Such rules are flagged in the UI.

## Validation workflow (Admin, `#admin`)

1. Add a sign (click where it **stands**), draw a marking / bus lane / taxi stand / other prohibition, or draw a survey area.
2. Set the road **side** (auto-detected, can be overridden), the zone (to the next intersection, a 7.2.2 length, or a
   repeated sign with 7.2.3), the line type for bus lanes, or the legal clause for other prohibitions.
3. Record the source (field survey, street photo, AYNA, Mapillary, AI), observer, date, and a URL or reference. Upload photos.
4. The review queue shows the photos, the camera-vs-sign position, the impact on curbs, conflicts, and **what is
   still missing** before the item can be verified. Approve, or reject with a reason.
5. Imports (OSM tags, Mapillary, GeoJSON) all land in the same queue.

## Status vs. the technical specification

| Spec item | Status |
|---|---|
| OSM integration, curb segmentation, rule engine, three statuses, legal explanation (templates + official quotes) | ✅ |
| Laws verified against the official text, with a verification level per rule | ✅ [docs/LEGAL_VERIFICATION.md](docs/LEGAL_VERIFICATION.md) |
| Smart drop-off: legal filter, direction-aware car route, walk route, crossing safety, ranking, top 3, "no spot" | ✅ confirmed (green) and *unverified* (yellow) spots are returned separately, each with status, reasons, sources and confidence |
| Driver "where can I stop" mode | ✅ |
| Import pipeline: OSM, Mapillary, GeoJSON, geotagged photos (EXIF) | ✅ (Mapillary needs a token) |
| Admin: add/edit/move, side, zone, photo evidence, sources, pending/verified/rejected, AI review, audit | ✅ |
| PostgreSQL/PostGIS | ⏳ **Not used.** The app has always run on SQLite + in-memory Shapely, and still does. Moving to PostGIS is a storage swap (the table layout maps onto the spec's tables). |
| AI Vision sign detection, LLM extraction of AYNA notices | ⏳ not built. Their output plugs into the same pending queue (`source=ai_vision`). |
| Time-dependent restrictions | ⏳ plate text is recorded but not evaluated |

## AYNA planning and passenger activity

Open **AYNA Planning** (`#authority`) for a separate authority journey. The present
OSM-only snapshot supports **curb survey tasks**, not proven infrastructure gaps or
approved new zones. Coverage remains `INVENTORY_UNKNOWN`; scores and network benefit
are withheld. Cards, CSV/GeoJSON and printable reports share the selected status filter.

A separate **Passenger activity** table accepts sourced aggregate boarding and
alighting counts through the authenticated backend. No passenger observations are
bundled. The empty table means **not measured**, not zero demand. Records retain their
source, period, license and collection method; overlapping sources are not summed.

See [audit](docs/feature_audit.md), [delivery and reproducible tests](docs/delivery.md)
and [authority API / data contract](docs/authority_api.md). Existing law, sign and marking
work is unchanged. AYNA is a possible stakeholder; no partnership is asserted.

### Persistent backend storage

Admin writes require the full backend deployment. On Render, use the Docker service
from `render.yaml`. Its default free plan is an ephemeral demonstration: data can be
lost when the instance restarts. For saved operational records, choose a service plan
that supports persistent disks, attach a disk at `/data`, and keep
`BURDASAXLA_DB=/data/burdasaxla.sqlite3`. Review Render's displayed plan/disk costs
before creating a paid service. The generated `BURDASAXLA_ADMIN_TOKEN` is the admin
password; retrieve it privately from the service's Environment settings.

Open the resulting service URL with `/#admin` to use the editor. The same service
serves both the UI and API; GitHub Pages continues to show its read-only snapshot.
Photos now default to the `evidence` directory beside the SQLite database, so both
observations and their evidence live on the persistent disk. Override with
`BURDASAXLA_EVIDENCE_DIR` only when an existing deployment uses another mounted
location. Migrate old photos into the configured directory before switching an
existing deployment; SQLite records refer to their stored filenames.

The GitHub Pages **Admin** button opens the full backend at
https://burdasaxla.onrender.com/#admin. The Pages workflow supplies
`VITE_ADMIN_URL`; direct `#admin` bookmarks also show a link to that login.
Admin credentials are never included in the static build. Backend builds keep their
local admin navigation. Retrieve the admin token privately in Render's service
Environment settings (`BURDASAXLA_ADMIN_TOKEN`).

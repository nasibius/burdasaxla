# BurdaSaxla — harada saxlamaq olar?

A map that applies Azerbaijan's road-traffic stopping rules to **each side of every street** in
the 28 May area of Baku. It also recommends where a driver can legally drop off or pick up a passenger.

* **Red (PROHIBITED):** a known rule forbids stopping here (crossing, intersection, bus stop, bus lane, bridge, sign 3.27, marking 1.4…).
* **Green (VERIFIED):** no prohibition, **and** the curb is covered by a verified survey area or an official AYNA zone.
* **Gray (UNKNOWN):** no known prohibition, but not verified. *No prohibition found never means green on its own.*

Legal decisions are made by a **deterministic rule engine** (Python + Shapely). No AI is involved.

**Live demo:** https://nasibius.github.io/burdasaxla/ (static build, see [Hosting](#hosting)).

---

## Quick start

Requirements: Python 3.11+ and Node 18+.

```bash
# 1. Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                         # 30 tests
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
line-by-line port of `dropoff.py` and is checked against the API on 40 random trips: the top drop-off pick matches
40/40 and walking distance is within 2 m. Driver mode matches 37/40; the three differences are equal-time ties at
OSM way splits.

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
| `BURDASAXLA_NO_DEMO_SEED` | unset | `1` = don't create the demo survey area |
| `VITE_STATIC`, `VITE_BASE` | unset, `/` | Build the static variant / set its public path |

## Quality checks

* `backend`: `ruff check app tests scripts` and `pytest -q` (30 tests: rule geometry, recommender, API, security
  and regression cases). Both run in CI (`.github/workflows/ci.yml`) along with the frontend type-check and build.
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

### Rules implemented (`app/rules.py`)

| Rule | Effect | Geometry |
|---|---|---|
| Pedestrian crossing | prohibit | on the crossing + **5 m before it in the direction of travel** (so the two sides differ) |
| Intersection | prohibit | ± (half-width of the crossed road + 5 m); yard/driveway exits are excluded (adjacent territory) |
| Bus stop | prohibit | ±15 m around the stop sign/platform, **only on the stop's side** (rail/metro platforms excluded) |
| Bus lane | prohibit | OSM `lanes:bus`, `bus:lanes`, `psv:lanes`, `busway:*`, or added by an admin |
| Bridge / tunnel, under bridge | prohibit | whole way / footprint of the overpass |
| Motorway, roundabout, level crossing | prohibit | whole way / ±10 m |
| Traffic signal | prohibit | 10 m before the signal (approximation of the "do not hide the signal" rule) |
| Sign 3.27 | prohibit | from the sign to the next intersection, on that side, continuing across OSM way splits |
| Marking 1.4 (solid yellow) | prohibit | the drawn extent |
| OSM `parking:*=no_stopping` | prohibit | that side |
| Sign 3.28, marking 1.10, OSM `no_parking` | **info** | parking is banned, but a short stop is allowed, so these do *not* turn a curb red |
| Left curb of a one-way road | info | allowed in built-up areas |

**Legal review needed:** all distances are configured from Art. 52 of the Law "On Road Traffic" as we understand it.
The legal/product owner must check every entry against the text currently in force. Change the parameters in
`rules.py` and bump `version` (and `RULESET_VERSION`) so results stay auditable.

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

* **OpenStreetMap** (ODbL): about 93 km of curb in a 1.8 × 1.6 km bbox around the 28 May metro. The data includes
  51 bus stops/platforms, about 400 crossings, 56 signals and 64 ways tagged with bus lanes.
* **Demo survey area:** on first run the app adds one survey polygon covering the middle 70 % of the area,
  labelled `demo_seed`. This is what makes curbs green. It stands in for the field survey the team must actually do.
  Delete it in Admin and draw real surveyed areas.
* **AYNA zones:** none are pre-loaded, to avoid inventing official data. Add them in Admin with the source URL.
* **Approximations:** curb lines are drawn by offsetting the road centreline, and widths are estimated from
  `width`/`lanes` tags or the road type. Rules marked *approximate* are flagged in the UI.
* **Not covered:** yellow lines and most signs are not in OSM. They must come from a field survey, street imagery
  or AI Vision, then go through the validation queue.

## Status vs. the technical specification

| Spec item | Status |
|---|---|
| OSM integration, curb segmentation, rule engine, red/green/gray, legal explanation (templates) | ✅ |
| Smart drop-off: candidates, legal filter, direction-aware car route, walk route, crossing safety, ranking, top 3, "no spot" | ✅ |
| Driver "where can I stop" mode | ✅ (extra) |
| Data quality: source, timestamps, rule version, conflict detection, validation queue, audit log | ✅ |
| Admin panel (add / approve / reject / delete; map-matched to way + side) | ✅ |
| PostgreSQL/PostGIS | ⏳ in-memory Shapely + SQLite for the MVP. The schema maps 1:1 onto the spec's tables, so moving to PostGIS is a storage swap. |
| Valhalla/GraphHopper | ⏳ own Dijkstra on OSM graphs. This is enough for one district. |
| AI Vision (sign detection), LLM extraction of AYNA notices | ⏳ not built. Their output plugs into `POST /api/admin/features` with `source=ai_vision` and `status=pending`, so a human always confirms it. |
| Time-dependent restrictions (sign plates) | ⏳ `time` is accepted by the API but not yet evaluated |

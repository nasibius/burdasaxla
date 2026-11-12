# AYNA Planning (B2G) — method, data coverage and delivery status

**Purpose.** The driver map answers *"where may I stop today?"*. The AYNA Planning view answers a different question:
*"where should new official pick-up/drop-off zones be investigated?"*. Its outputs are **investigation proposals and
field-survey tasks, never legal permissions**. They never appear in driver recommendations. Only a separately
validated official-zone import (`official_zone` observations reviewed in Admin) changes the supply inventory.

AYNA is a *target stakeholder*. No partnership, contract or mandatory integration is assumed.

Open it at `#planning` (toolbar: **Sürücü / AYNA Planlama / Admin**).

## Data inputs and coverage (28 May pilot, snapshot 2026-11-12)

| Input | Source | Status in the pilot |
|---|---|---|
| Road + pedestrian network | OSM snapshot 2026-11-12 16:37 UTC | 93 km of curb; pedestrian graph from footways and streets |
| **Officially designated zones** (supply) | `official_zone` observations, verified with a source URL | **0.** AYNA publishes no machine-readable list (checked 2026-11-12) |
| Field-verified suitable curbs | reviewed survey areas (legal stream) | **0** |
| Inventory completeness | `planning_areas.inventory_status`, set by a planner *with a source URL* | **unknown** |
| Access nodes (where people go) | OSM POIs, stations, entrances | 1,081 nodes, all labelled **`is_proxy: true`**. They are *not* demand |
| Measured demand | `passenger_activity` table (verified counts only) | **0 rows → "not measured"** |
| Synthetic examples | — | **none in the app or the live site.** Synthetic fixtures exist only in `backend/tests/` |

**Result on real data:** 0 SERVED · 0 POTENTIAL_COVERAGE_GAP · **1,077 INVENTORY_UNKNOWN** · 4 NETWORK_UNRELIABLE ·
**128 field-survey tasks** · **0 candidate sites**. Because the inventory is incomplete, no shortage is claimed. The
dashboard shows the honest fallback ("Areas requiring field verification").

## Method (`backend/app/planning.py`, algorithm `b2g-planning-1.0`)

1. **Supply:** verified *officially designated* zones. Field-verified legal curbs are counted separately, as
   "observed suitable". They are the natural candidates for designation, not existing official supply.
2. **Coverage per access node:** one multi-source Dijkstra on the pedestrian network from all supply points. Each node
   is snapped to the network (max 60 m); nodes on small isolated pieces of the network are `NETWORK_UNRELIABLE`.
   - `SERVED`: an official zone is within the threshold (default **300 m, a planning assumption, not a legal distance**).
   - `POTENTIAL_COVERAGE_GAP`: beyond the threshold **and** the inventory has been declared complete with a source.
   - `INVENTORY_UNKNOWN`: beyond the threshold while the inventory is incomplete. **Never merged with a gap.**
3. **Survey tasks:** 150 m grid cells with unserved nodes, ranked by:

   | Factor | Weight |
   |---|---|
   | destination density (proxy) | 35 % |
   | measured activity | 25 % |
   | transit hub | 15 % |
   | unverified curb share | 15 % |
   | no verified supply | 10 % |

   Unavailable factors are reported as `unknown` and **excluded, with the weights renormalised**. They are never
   scored as 0 or 1. Each task lists the curb pieces to survey and the missing evidence.
4. **Candidates (only for supported gaps):** curb segments within 1.5× the threshold on the walking network.
   - Curbs with a statutory prohibition (legal stream), existing official zones, and pieces < 12 m are excluded.
   - `SCREENED_FOR_FURTHER_STUDY` = a surveyed legal curb, scored with illustrative weights:

     | Factor | Weight |
     |---|---|
     | walking-access improvement | 35 % |
     | known feasibility | 25 % |
     | pedestrian connectivity | 20 % |
     | curb practicality | 10 % |
     | evidence completeness | 10 % |

   - `DATA_COLLECTION_NEEDED` = an unsurveyed curb, with **no numeric score**.
   - At most 2 per cluster, ≥ 60 m apart. A cluster with no defensible site is flagged on its survey task instead of
     getting a forced pin.
5. **Reviews:** `needs_survey / shortlist / more_data / reject` (reject needs a reason). They are stored against
   stable ids (cell or curb segment), so recomputing never erases a decision. There is no "approved" action.
6. **Runs:** `recommendation_runs` stores parameters, source versions and summary counts for reproducibility.

## Passenger boarding/alighting table (`passenger_activity`)

This is the separate table you asked for: **places where many passengers get in or out**.

- **What a row holds:** place, point, counting period, **pickups (getting in)**, **dropoffs (getting out)**, vehicle
  scope, method (`field_count` / `operator_aggregate` / `official_statistic`), source, URL or reference, observer.
- **Workflow:** rows enter as *pending* and need a source before verification. Admin can enter them by form or CSV import.
- **Output:** only verified rows are public, ranked busiest first (passengers per hour). Counts below 5 are shown as
  "<5" for privacy.
- **Use in planning:** verified rows feed the *measured activity* factor and show as a map layer. With no rows the UI
  says **"not measured"**. No heatmap or count is ever derived from POIs.
- CSV columns: `place_name,lon,lat,period_start,period_end,pickups,dropoffs,method,source[,source_url,source_ref,vehicle_scope,note]`.

## API (backend)

| Method | Endpoint | |
|---|---|---|
| GET | `/api/authority/overview?threshold_m=` | summary, provenance, limitations, supply, recent runs |
| GET | `/api/authority/coverage?threshold_m=` | per-node state, distance, reason |
| GET | `/api/authority/candidates?kind=all\|survey\|candidate&review=` | ranked items with review state |
| GET | `/api/authority/candidates/{id}` | one item with factor breakdown and review history |
| POST 🔒 | `/api/authority/recommendations/run` | recompute and record a run |
| POST 🔒 | `/api/authority/candidates/{id}/review` | planner decision (never an approval) |
| POST 🔒 | `/api/authority/inventory` | declare inventory `complete` (source URL required) or `unknown` |
| GET | `/api/authority/export?format=csv\|geojson&kind=&review=` | export with limitations |
| GET | `/api/activity` | verified, aggregated passenger counts |
| GET/POST 🔒 | `/api/admin/activity`, `/api/admin/activity/{id}/review`, `/api/admin/activity/import` | count entry, review, CSV |

Real example (top survey task, live data, abridged):

```json
{
 "id": "survey-2683-29803",
 "type": "survey_task",
 "rank": 1,
 "priority_score": 80.5,
 "factors": {
  "access_proxy": 0.95,
  "measured_activity": null,
  "transit_hub": 1.0,
  "unverified_curb_share": 0.141,
  "no_verified_supply": 1.0
 },
 "factors_missing": [
  "measured_activity"
 ],
 "access_nodes": 19,
 "access_nodes_are_proxy": true,
 "transit_hubs": [
  "28 May D",
  "28 May C"
 ],
 "coverage_states": {
  "INVENTORY_UNKNOWN": 19,
  "POTENTIAL_COVERAGE_GAP": 0,
  "SERVED": 0
 },
 "measured_activity": "not_measured",
 "curb_m": {
  "total": 206,
  "unverified": 29,
  "prohibited": 177,
  "allowed": 0
 },
 "missing_evidence": [
  "Complete, sourced inventory of officially designated pick-up/drop-off zones (AYNA)",
  "Field survey of signs (3.27/3.28) and markings (1.4/1.10) on nearby curbs",
  "Measured pick-up/drop-off counts (passenger_activity) — demand is not inferred from POIs"
 ],
 "officially_approved": false,
 "review": null,
 "curb_segments_to_survey": [
  {
   "segment_id": "w304967884-r-312",
   "street": "Dilarə Əliyeva küçəsi",
   "compass": "S",
   "length_m": 12.87,
   "cautions": [
    "NOT_SURVEYED"
   ]
  }
 ]
}
```

**Static site (GitHub Pages):** `scripts/export_static.py` runs the same engine at build time and writes
`planning.json` and `activity.json`. The site is read-only: review controls are replaced by a "Read-only demonstration"
note, and the threshold is fixed at 300 m. Exports (CSV, GeoJSON, printable report) are built in the browser from the
visible, filtered items, with the same columns as the API export. The build commit and time are shown in the panel footer.

## P0 checklist

| Item | Status | Evidence |
|---|---|---|
| Audit current repo and live site | DONE | `docs/feature_audit.md` |
| AYNA Planning navigation, layers, labels, purpose text | DONE | `frontend/src/planning/*`, `#planning` |
| Coverage states SERVED / GAP / INVENTORY_UNKNOWN / NETWORK_UNRELIABLE | DONE | `planning.py`; `test_planning.py` B2G-01/02/03 |
| Candidates only when supported; survey tasks otherwise | DONE | B2G-04/04b/05; real data → 0 candidates, 128 tasks |
| Ranked cards with reasons, provenance, missing evidence | DONE | panel and drawer screenshots |
| Review statuses; read-only on static | DONE (backend) / DONE (static read-only) | `test_authority_api.py`; drawer shows a read-only note on Pages |
| Export CSV, GeoJSON and printable report | DONE | API export tests; client export; print view |
| Proposals kept out of driver recommendations | DONE | B2G-06 (engine and API) |
| Static site shows dataset revision and works without backend | DONE | footer build commit and time; `planning.json` |
| Regression of driver flows | DONE | 66 previous tests still pass; UI smoke test (driver search → 0 confirmed / 3 unverified) |
| demo_seed cannot masquerade as verified data | DONE | live `features.json` = `[]`; store migration retires demo_seed |
| Separate passenger in/out table | DONE | `passenger_activity`, `/api/activity`, "Sərnişin axını" tab |

## Acceptance tests (`backend/tests/test_planning.py`, `test_authority_api.py`)

| Test | Status |
|---|---|
| B2G-01 to B2G-07 | ✅ automated |
| B2G-08 (static read-only) | ✅ UI: static mode hides write controls, no "saved" message possible |
| B2G-09 (export matches filter + limitations) | ✅ automated |
| B2G-10 (demand not measured) | ✅ automated |
| B2G-11 (synthetic labelling) | ✅ by construction: no synthetic data ships |
| B2G-12 (Pages base path + reload) | ✅ checked on the live URL after deploy |
| CORE-01 to CORE-04 | ✅ covered by the existing driver tests and the UI smoke test |

## Blockers

- **No official zone inventory** (AYNA publishes none in machine-readable form), so coverage can't be established and
  no candidate sites are generated.
- **No measured demand data**, so demand is "not measured".
- **No field survey yet**, so no SCREENED candidates are possible.
- **Persistence and access:** reviews persist only on a backend deployment. Authority access uses the admin token
  (no per-user accounts yet, P1).
- **Curb geometry** is estimated from road centrelines.

## 60–90 second demo script (only what is implemented)

1. **Driver:** search "Nizami kino mərkəzi". The app shows 0 confirmed spots (honest), 3 *unverified* options and the
   door warning (bus stop, Art. 52.IV.7). Open one to show the car and walking routes.
2. **Switch to AYNA Planlama:** "the authority's question is different".
3. Point at the inventory banner: *coverage cannot be established*. Show the survey-priority list: #1 is around the
   28 May bus station (transit hub, 19 destinations). Demand is explicitly not measured.
4. Open task #1: why, factors (measured activity = unknown, excluded), curb pieces to survey, "not a legal permission".
5. Export CSV or print the report. Close: *"With AYNA's official list and a field survey, the same pipeline produces
   ranked candidate sites, and nothing is invented before then."*

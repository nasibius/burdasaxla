# Feature audit — 12 November 2026

Baseline: `9f2396da0cfc1ed123a539279575ad478f81a959`. Read-only inspection before implementation.
Live: https://nasibius.github.io/burdasaxla/ ; `/static-data/meta.json` reports build
2026-11-12T18:38:19Z and OSM 2026-11-12T16:37:27Z, ruleset 2026.11-law517IQ-v2.
Live assets: index-CmXKsbnA.js / index-DIfSz5NL.css. Exact deployed Git SHA is
NOT VERIFIED: the old export does not embed it. The timestamp is consistent with
the baseline but is not proof of deployed commit identity.

| Area | Baseline status | Evidence / static vs backend |
|---|---|---|
| Road/curb restrictions | IMPLEMENTED | `backend/app/citymodel.py`, `rules.py`; live 3,702 segments; legal correctness outside this task |
| Destination search / up to three results | IMPLEMENTED | `dropoff.py`, `frontend/src/static/engine.ts`, `Panel.tsx`; UI regression pending |
| Vehicle / walking routes | PARTIAL | Directed vehicle graph and pedestrian Dijkstra exist in both engines; connector/crossing assumptions are not field-validated |
| Explanations / sources | IMPLEMENTED | `SegmentDrawer.tsx`, static segment-details and rules JSON |
| Sign/data administration | IMPLEMENTED | `AdminPanel.tsx`, `/api/admin/*`; backend writes, static read-only; do not duplicate |
| Authority dashboard | MISSING | No authority component or routes at baseline |
| Candidate generation | MISSING | Driver recommendation engine is not a planning engine |
| Coverage analysis | MISSING | No inventory completeness declaration or coverage states |
| Authority review workflow | MISSING | Existing validation concerns observations, not future proposals |
| Authority reports | MISSING | No candidate CSV/GeoJSON/print export |
| Official zone inventory | BLOCKED | Live features.json is []; no verified official or observed inventory supplied |
| Measured passenger activity | MISSING | No table/source; user requests a separate aggregate boarding/alighting table |
| Synthetic coverage | IMPLEMENTED | `Store._migrate` retires demo_seed; live verified observations=0, ALLOWED=0, features=[] |
| Static deployment | PARTIAL | `.github/workflows/pages.yml` exports Python decisions; missing Git SHA and planning snapshot |
| Database | IMPLEMENTED | SQLite `Store`; no migration to PostGIS needed |
| Tests / readiness | NOT VERIFIED | Existing pytest and CI; run and report independently during delivery |

## Implementation boundary

Preserve legal engine, sign ingestion and admin editor. Reuse curb geometry as
**approximate survey targets**, not certified sites. Current inventory is unknown;
current pedestrian access quality is not independently validated. No shortage,
demand, network coverage percentage or numerical site score is supportable.
Provide the expressly permitted survey-board fallback and preserve the four-state
coverage contract for evidence-qualified network inputs. A shortlist cannot alter
verified supply. Passenger data must be explicitly sourced aggregate observations,
with publication permission, never POI-derived counts or individual trajectories.

Post-change acceptance evidence and limitations: see `delivery.md`.

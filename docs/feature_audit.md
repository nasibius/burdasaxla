# Feature audit — before the B2G planning work

Audited 2026-11-12 against commit `9f2396d` (main) and the live static site
<https://nasibius.github.io/burdasaxla/> (snapshot `built_at 2026-11-12T18:38:19Z`, OSM snapshot `2026-11-12T16:37:27Z`,
ruleset `2026.11-law517IQ-v2`).

Statuses: `IMPLEMENTED`, `PARTIAL`, `MISSING`, `BLOCKED`, `NOT VERIFIED`.
"Live" = works on GitHub Pages (static, read-only). "Backend" = needs the FastAPI server.

| Area | Status | Where | Live | Backend | Evidence / note |
|---|---|---|---|---|---|
| Road network, curb-side segmentation, road-derived restrictions | IMPLEMENTED | `backend/app/citymodel.py` | ✅ (precomputed) | ✅ | 33 engine tests. Legal correctness is owned by the legal stream (`docs/LEGAL_VERIFICATION.md`). |
| Destination search, up to 3 suggestions | IMPLEMENTED | `dropoff.py`, `frontend/src/static/engine.ts`, `Panel.tsx` | ✅ | ✅ | Parity 80/80 (TS vs Python). |
| Confirmed vs unverified suggestions separated | IMPLEMENTED | `dropoff.py` (`results` / `unverified_candidates`) | ✅ | ✅ | `tests/test_recommend.py`. Unverified ones are a separate, labelled list, never "confirmed". |
| "No verified spot" empty state | IMPLEMENTED | `Panel.tsx` | ✅ | ✅ | Shows "Yaxınlıqda təsdiqlənmiş nöqtə yoxdur" + reason. |
| Vehicle approach (one-way, direction of travel) | IMPLEMENTED | `dropoff.py::_arrival` | ✅ | ✅ | Directed graph; curb reachable only in its legal travel direction. |
| Pedestrian route on the walk network | IMPLEMENTED | `dropoff.py::_walk_to/_walk_path` | ✅ | ✅ | Network Dijkstra over OSM footways and streets; the first/last metres to the snapped edge are straight-line access legs. |
| Route unavailable handling | PARTIAL | `Panel.tsx` | ✅ | ✅ | Car metric shows "—" when there is no driver position. Unreachable candidates are dropped, not invented. No dedicated "route unavailable" text yet → added in this stream. |
| Restriction explanation and sources per recommendation | IMPLEMENTED | `dropoff.evidence()`, `SegmentDrawer.tsx` | ✅ | ✅ | Status, reasons, cautions, sources, confidence on every result. |
| Admin: signs/markings/evidence/review | IMPLEMENTED | `AdminPanel.tsx`, `main.py` | read-only notice | ✅ | Owned by the legal/data stream. Not duplicated here. |
| **AYNA planning dashboard** | IMPLEMENTED (this stream) | `frontend/src/planning/`, `#planning` | ✅ read-only | ✅ | — |
| **New-zone candidate generation** | IMPLEMENTED; BLOCKED on data | `planning.py::_candidates` | ✅ | ✅ | 0 candidates on real data: the inventory is unknown |
| **Coverage / shortage analysis with an unknown state** | IMPLEMENTED | `planning.py::coverage` | ✅ | ✅ | 1,077 INVENTORY_UNKNOWN, 4 NETWORK_UNRELIABLE |
| **Authority review workflow** | IMPLEMENTED | `/api/authority/candidates/{id}/review` | read-only | ✅ persisted | — |
| **Authority export (CSV / GeoJSON / printable)** | IMPLEMENTED | `/api/authority/export`, `planning/export.ts`, `PrintReport.tsx` | ✅ | ✅ | — |
| **Passenger boarding/alighting activity table** | IMPLEMENTED; empty | `passenger_activity`, `/api/activity` | ✅ read-only | ✅ | 0 measured rows → "not measured" |
| Official designated zone inventory | PARTIAL | `official_zone` feature kind | — | ✅ | The data model exists; **0 zones recorded**. AYNA publishes no machine-readable dataset (checked 2026-11-12). Inventory completeness is **unknown**. |
| Measured taxi-demand dataset | BLOCKED | — | — | — | No source available. Not invented. |
| `demo_seed` synthetic coverage | IMPLEMENTED (removed) | `store.py::_migrate` | ✅ none in live data | ✅ | Live `features.json` is `[]`; live stats show 0 km green. The migration retires any demo_seed row. |
| Live deploy, base path, freshness | IMPLEMENTED | `.github/workflows/pages.yml` | ✅ | — | Builds from `main` on every push; served under `/burdasaxla/`. The visible build timestamp/commit was missing → added in this stream. |
| Database | IMPLEMENTED (SQLite) | `store.py` | — | ✅ | **SQLite + in-memory Shapely, not PostGIS.** Kept for the MVP (GAP-12). |
| Tests / CI | IMPLEMENTED | `backend/tests`, `.github/workflows/ci.yml` | — | — | 66 backend tests, ruff, tsc, build on every push. |

## B2G stream — results after implementation

See the P0 checklist in [`docs/B2G_PLANNING.md`](B2G_PLANNING.md#p0-checklist) for DONE / PARTIAL / BLOCKED with evidence.

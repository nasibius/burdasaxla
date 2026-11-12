# Delivery: authority survey workflow and passenger activity

## Scope and evidence

Baseline audit: [feature_audit.md](feature_audit.md). Implementation extends React/Vite,
FastAPI and the existing SQLite database. It does not change `rules.py`, `citymodel.py`,
`dropoff.py`, the static driver engine or sign/marking administration. No new database
platform or duplicated legal/data workflow.

The current data support **a reproducible survey board**, the brief's honest fallback.
They do not support actual shortage claims or scored new-zone proposals. Counts from the
checked real OSM snapshot (2026-11-12T16:37:27Z), clean local source DB:

| Category | Count / finding |
|---|---|
| Verified official location records | 0 supplied; inventory completeness unknown |
| Field-observed usable curb segments | 0 |
| Synthetic examples in shipped data | 0 |
| Screened infrastructure investigation sites | 0; feasibility evidence missing |
| Approximate curb survey tasks | 24; DATA_COLLECTION_NEEDED |
| Geographic access proxies | 710; all INVENTORY_UNKNOWN, not proven gaps |
| Measured passenger activity rows | 0; not measured |
| Coverage percentage / numeric scores / network benefit | Withheld, not zero |

The 3,702 existing curb segments are unchanged. 3,678 are omitted from the 24-task
survey batch, with per-segment reasons (restriction, short geometry, boundary, spacing,
batch limit). A batch limit is not a claim that remaining sites are unsuitable.

## P0 delivery status

| Checklist item | Result / evidence |
|---|---|
| Audit repository and live data | DONE; baseline source hash, live timestamps and asset names recorded; old deployment's exact Git SHA cannot be established from its payload |
| Authority navigation / layers / explanations | DONE; `#authority`, pilot polygon, existing inventory layer, gray survey geometry, selected purple geometry, current restrictions toggle |
| Honest coverage states | DONE for contract and synthetic tests; production adapter returns INVENTORY_UNKNOWN until independently validated inventory/network inputs exist |
| Supported candidates or genuine survey tasks | DONE via survey fallback; actual scored infrastructure candidate generation BLOCKED on evidence |
| Cards, provenance and missing evidence | DONE; no numeric score/rank; explicit deterministic survey order |
| Human review | DONE; four statuses, authenticated SQLite persistence and audit; static is read-only; individual reviewer accounts are P1 |
| CSV/GeoJSON and printable report | DONE; same status filter; source/version/limitations included; candidate PDF verified as one A4 page |
| Separation from driver destinations | DONE; separate tables/module; no legal feature writes; regression asserts driver output unchanged |
| GitHub Pages data revision and backend independence | DONE in local Pages-style build and CI workflow; deployment requires merging the PR; no claim of an already updated live site |
| Driver regression | DONE for existing automated graph/filter tests and browser search/no-verified-result flow; real safe crossings and field route suitability remain NOT VERIFIED |
| Synthetic data exclusion | DONE; baseline migration already retired demo_seed; planning additionally excludes it; no fabricated demo supply or demand added |
| Passenger boarding/alighting table (additional request) | DONE; separate SQLite table, authenticated aggregate JSON import, source-period records, sorting/filtering/export and explicit empty state |

## Acceptance mapping

- B2G-01–05: `backend/tests/test_planning.py`: inventory/freshness/network gates,
  metric shortest paths, unavailable attachments, missing evidence, hard exclusions,
  and no forced candidate. SERVED/GAP cases use explicitly synthetic validated graphs;
  they are not production findings.
- B2G-06–07: driver-output separation and persistent authenticated reviews, including
  stale-run rejection and no official-approval action.
- B2G-08–10, B2G-12: `frontend/tests/smoke.py`: read-only control state, export parity,
  absent measured activity, direct hash reload at `/burdasaxla/`, mobile and AZ navigation.
- B2G-11: no synthetic production records exist. Unit/UI fixtures are confined to test
  execution; the backend UI test names its throwaway activity `SIMULATED EXAMPLE`.
- CORE-01/03: driver browser smoke shows no confirmed spot and separate unverified
  observations. Existing segment drawer remains the detailed source/freshness view.
- CORE-02: existing routing/no-route/one-way unit regressions pass. Real pedestrian
  barriers/attachments remain unvalidated; authority distances are withheld.
- CORE-04: one export uses the same model timestamp and run ID in `meta.json` and
  `planning.json`, with Git revision, raw-network checksum and inventory digest.

## Files changed

| File | Purpose |
|---|---|
| `backend/app/planning.py` | Four-state coverage contract, survey selection, provenance and export |
| `backend/app/planning_store.py` | Separate run/review/passenger tables in SQLite |
| `backend/app/planning_api.py` | Public reads and validated authenticated mutations |
| `backend/app/main.py` | Register authority router before catch-all |
| `backend/scripts/export_static.py` | Export shared planning snapshot and source revision |
| `backend/tests/test_planning.py` | B2G, persistence, isolation, export and passenger-data tests |
| `frontend/src/planning.ts` | Typed contracts, fetch/import/review and download helpers |
| `frontend/src/components/AuthorityPanel.tsx` | Planning map/cards/detail/review/report plus separate activity table |
| `frontend/src/components/authority.css` | Responsive layout and printable single-candidate report |
| `frontend/src/App.tsx` | Driver/authority navigation; separate map rendering |
| `frontend/tests/smoke.py` | Static driver/authority browser acceptance and screenshots/PDF |
| `frontend/tests/backend_smoke.py` | Local-only review and aggregate-import UI persistence test |
| `.github/workflows/ci.yml` | Pages-base-path browser test job and evidence artifact |
| `.gitignore` | Ignore local Python environment |
| `README.md`, `docs/*.md` | Audit, contracts, sample report, pilot protocol and delivery instructions |

## Reproduce validation

From repository root (Python 3.12 / Node 22 used):

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt ruff playwright==1.65.1
.venv/bin/playwright install chromium
.venv/bin/ruff check backend/app backend/tests backend/scripts
(cd backend && ../.venv/bin/pytest -q)
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/python backend/scripts/export_static.py
VITE_STATIC=1 VITE_BASE=/burdasaxla/ npm run build --prefix frontend
VITE_BASE=/burdasaxla/ npm run preview --prefix frontend -- --host 127.0.0.1 --port 4173
# In another terminal:
.venv/bin/python frontend/tests/smoke.py http://127.0.0.1:4173/burdasaxla/ work/ui-evidence
```

Results recorded locally: **78 pytest tests pass**, Ruff passes, backend/frontend
production build passes, static browser smoke passes. The smoke produces desktop driver,
planning, passenger-table and mobile screenshots, plus `sample-candidate-report.pdf`
(one A4 page). These are also uploaded as the `ui-evidence` CI artifact. CI results
should be read from the PR rather than inferred from local checks.

Local tested URLs:
- `http://127.0.0.1:4173/burdasaxla/` — static driver
- `http://127.0.0.1:4173/burdasaxla/#authority` — static planning (reload tested)
- `http://127.0.0.1:5173/#authority` — Vite/backend mode
- `http://127.0.0.1:8000/api/authority/overview` — backend snapshot

To repeat the local backend UI write test, use a **fresh throwaway database**, run
uvicorn with a unique test-only `BURDASAXLA_ADMIN_TOKEN`, and start `npm run dev` in
`frontend`. Set the same token as `SMOKE_ADMIN_TOKEN` for
`.venv/bin/python frontend/tests/backend_smoke.py`. The script only targets localhost. This backend browser test also passed locally.
It verifies review persistence and a labelled synthetic aggregate import after reload.
Never point the static exporter at that test DB.

Manual report steps: open `#authority`, select a survey card, inspect its evidence,
then **Print candidate**. Change the review-status filter and use CSV/GeoJSON or
**Print list** to report the visible set. Open **Passenger activity** for the separate
boarding/alighting table. Backend-only JSON import format is in [authority_api.md](authority_api.md).

## Deployment and blockers

The existing Pages workflow builds and deploys automatically **after merge to main**.
The intended deployed route is https://nasibius.github.io/burdasaxla/#authority .
A draft PR does not deploy it. Check the new static `meta.json` Git revision against
that merge commit after deployment. CI's clean DB intentionally contains no local
private activity or reviewer notes. For full backend hosting, build without VITE_STATIC,
set a nondefault admin token and use persistent SQLite storage.

Still blocked by real evidence: complete fresh official inventory, field-measured curb
geometry, validated pedestrian/crossing attachments, measured passenger activity,
engineering/legal feasibility. No suitability score, walking coverage percentage,
new official approval, AYNA partnership, or measured benefit is claimed. Current
supply imports remain the existing curated-feature workflow; planner shortlists
cannot alter it. PostGIS, personal accounts, scheduled approved-data publication,
and generalized evidence-qualified candidate scoring remain future work.

# Authority API and passenger activity contract

All endpoints are under `/api/authority`. Read routes are public. Writes require
`X-Admin-Token` matching a **nondefault** `BURDASAXLA_ADMIN_TOKEN`. This is the existing
shared admin credential, not a new account system. Configure a unique secret and
persistent `BURDASAXLA_DB` for backend hosting; never put a token into a Pages build.
Review notes and the credential-holder label are omitted from public snapshots.
The authenticated `/reviews` endpoint retains the full audit history. Token input in
the planning UI stays in memory only.

| Method/path | Contract |
|---|---|
| GET `/overview?area_id=28-may&threshold_m=450` | Full snapshot, source versions, coverage, candidates, activity |
| GET `/candidates?status=needs_survey` | Filtered tasks; optional status |
| GET `/candidates/{id}` | Current candidate, evidence and public review history |
| GET `/coverage?threshold_m=450` | Four-state coverage records |
| POST `/recommendations/run?threshold_m=450` | Persist deterministic current run; no legal-store writes |
| POST `/candidates/{id}/review?threshold_m=450` | `{action, reason, run_id}`; stale run gives 409 |
| GET `/reviews` | Authenticated full review history, including retired candidate IDs |
| GET `/export?format=csv&status=needs_survey` | CSV or GeoJSON; same filters as candidates |
| GET `/passenger-activity` | Publication-permitted aggregates only |
| POST `/passenger-activity` | `{records: [...]}`; transactional import, maximum 500 rows |

Review actions: `needs_survey`, `shortlist`, `reject`, `more_data_needed`. There is no
approval operation. Decisions remain keyed to stable curb segment IDs across reruns;
if upstream segmentation changes IDs, old decisions remain in the audit endpoint
but are **not** silently copied onto a different geometry. Reconciliation requires
human review. Individual reviewer accounts and compare-and-swap review editing are P1.

## Passenger activity input (schema illustration, NOT measured data)

```json
{
  "records": [{
    "location_id": "REPLACE_WITH_SOURCE_LOCATION_ID",
    "name": "REPLACE_WITH_OBSERVED_PLACE",
    "longitude": 49.85,
    "latitude": 40.38,
    "period_start": "2026-11-01T00:00:00+04:00",
    "period_end": "2026-11-02T00:00:00+04:00",
    "pickups": 0,
    "dropoffs": 0,
    "source_ref": "REPLACE_WITH_OBSERVATION_REFERENCE",
    "source_url": "https://example.org/REPLACE_WITH_REAL_SOURCE",
    "license": "REPLACE_WITH_PERMISSION_OR_LICENSE",
    "collection_method": "REPLACE_WITH_COUNTING_METHOD_AND_SAMPLE_SCOPE",
    "publication_permitted": false
  }]
}
```

Do not import this illustration as evidence. `pickups` and `dropoffs` are **passenger
movements**, not trip counts, unique passengers or population estimates. Counts must
be nonnegative integers. A passenger observed boarding and later alighting represents
two movements. No rider IDs, device IDs or trajectories are accepted. Places must be
inside the pilot; periods need explicit timezones, must be historical and span 1–366
days. Times are normalized to UTC. The UI reports `(pickups + dropoffs) / observed hours`
for comparison, not an extrapolated prediction. Different periods, collection methods
and operator samples still have bias; do not combine them as citywide demand.

Public export requires explicit publication permission and at least ten movements
for nonzero cells. This minimal suppression rule is not a complete privacy guarantee;
data owners must assess licensing, aggregation and disclosure risks before publication.
Private rows stay in SQLite and are excluded from API reads and Pages. Reimporting an
exact `(location_id, period_start, period_end, source_ref)` replaces that observation;
overlapping windows from the same location/source are rejected atomically. Different
sources remain separate rows and are never summed. Editing the source reference does
not establish independence. Aggregate corrections retain import timestamps; a full
versioned passenger-record audit is P1.

## Coverage adapter boundary

`app.planning.assess_coverage` accepts a **validated** metric pedestrian graph, eligible
zones attached to graph nodes, and access points with validated attachments. It uses
Dijkstra shortest paths, not circles or Euclidean distances. Inventory completeness
and freshness must both be established before served/gap claims. Unknown endpoint
connections or network quality yield `NETWORK_UNRELIABLE`. Incomplete inventory yields
`INVENTORY_UNKNOWN`, including when the table has no entries.

The current OSM adapter intentionally supplies neither completeness nor validated
access. It therefore exports 710 geographic access proxies with unknown inventory,
not 710 proven gaps. No production configuration flag can manufacture the missing
survey evidence. Integrating an independently QA-reviewed inventory/network dataset
is a future task. Current task selection is **survey sampling**, not new-zone scoring.

## Static contract and reproducibility

`backend/scripts/export_static.py` calls the same `build_snapshot` as the backend.
`planning.json` includes source timestamps, a raw network checksum, inventory digest,
Git revision, algorithm version and scenario parameters. A dirty local build is labeled
`-dirty`. `meta.json` links the planning run. The deterministic run ID excludes wall-clock
build time and review actions; review history is appended separately. Backend hosts can
set `BURDASAXLA_CODE_REVISION` to their deployed Git SHA (otherwise explicitly unknown).
Passenger aggregates have their own content version and are not inputs to site scores.

GitHub CI starts from an empty SQLite database unless a separately authorized, validated
inventory is supplied. Local private reviews/aggregates do not automatically travel to
GitHub Pages. To publish authorized aggregate data, run the exporter against the approved
source database and deploy its output through a reviewed workflow; never commit the DB.

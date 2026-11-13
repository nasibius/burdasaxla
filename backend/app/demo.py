"""SIMULATED EXAMPLE survey coverage for demonstrations.

Enabled only with BURDASAXLA_DEMO_SURVEY=1. It adds one in-memory survey area (never written to the
database) so the map can show what GREEN looks like once a real field survey exists. Everything it
touches is labelled `simulated` / `is_synthetic_example`:
  * curbs it turns green carry `simulated: true` and confidence `simulated_example`;
  * recommendations on them are never `legally_confirmed`;
  * the authority planning engine ignores it (it is not supply and not an observed survey).
Statutory prohibitions (crossings, bus stops, bike lanes...) and cautions still apply on top of it.
"""
import os

DEMO_FEATURE_ID = -1
DEMO_SOURCE = "simulated_example"


def enabled() -> bool:
    return os.environ.get("BURDASAXLA_DEMO_SURVEY") == "1"


def demo_survey(bbox, share=0.85):
    s, w, n, e = bbox
    ds, dw = (n - s) * (1 - share) / 2, (e - w) * (1 - share) / 2
    ring = [[w + dw, s + ds], [e - dw, s + ds], [e - dw, n - ds], [w + dw, n - ds], [w + dw, s + ds]]
    return {"id": DEMO_FEATURE_ID, "kind": "survey_area", "status": "verified", "source": DEMO_SOURCE,
            "is_synthetic_example": True, "geometry": {"type": "Polygon", "coordinates": [ring]},
            "props": {"label": "SIMULATED EXAMPLE"}, "observer": "simulation", "observed_at": None,
            "verified_at": None, "note": "SIMULATED EXAMPLE — not a real field survey. Demonstration only."}


def with_demo(features, bbox):
    return [*features, demo_survey(bbox)] if enabled() else list(features)


# --- SIMULATED EXAMPLE passenger activity (boarding/alighting table) -------------------------------
ACTIVITY_KINDS = {"platform": 9, "station": 9, "mall": 7, "hotel": 5, "university": 6, "supermarket": 4,
                  "bank": 3, "government": 3, "hospital": 5, "theatre": 4, "museum": 3}
PERIOD = ("2026-11-02T00:00:00Z", "2026-11-09T00:00:00Z")  # one example week (168 h)


def demo_activity(model, limit=12):
    """Invented weekly boarding/alighting counts at real OSM places. Never stored; every row is labelled."""
    import hashlib

    if not enabled():
        return []
    picks = sorted((it for it in model.search_items if it.get("kind") in ACTIVITY_KINDS),
                   key=lambda it: (-ACTIVITY_KINDS[it["kind"]], hashlib.sha1(it["name"].encode()).hexdigest()))
    rows, names, per_kind = [], set(), {}
    for it in picks:
        cap = 4 if it["kind"] in ("platform", "station") else 2
        if it["name"] in names or per_kind.get(it["kind"], 0) >= cap:
            continue
        names.add(it["name"])
        per_kind[it["kind"]] = per_kind.get(it["kind"], 0) + 1
        h = int(hashlib.sha1(it["name"].encode()).hexdigest(), 16)
        weight = ACTIVITY_KINDS[it["kind"]]
        pickups = 150 * weight + h % 120
        dropoffs = 150 * weight + (h // 997) % 120
        rows.append({
            "id": -(len(rows) + 1), "location_id": f"sim-{h % 10**8:08d}", "name": it["name"],
            "pickups": pickups, "dropoffs": dropoffs, "period_start": PERIOD[0], "period_end": PERIOD[1],
            "passengers_per_hour": round((pickups + dropoffs) / 168, 3), "unit": "passenger movements",
            "source_ref": "SIMULATED EXAMPLE",
            "source_url": f"https://www.openstreetmap.org/#map=19/{it['lat']:.5f}/{it['lon']:.5f}",
            "license": "Simulated demo data — not real counts", "collection_method": "Simulated example (demo mode)",
            "longitude": it["lon"], "latitude": it["lat"], "publication_permitted": True, "is_synthetic_example": True,
        })
        if len(rows) == limit:
            break
    return sorted(rows, key=lambda r: (-r["passengers_per_hour"], r["location_id"]))

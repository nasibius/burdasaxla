"""Export a precomputed, read-only snapshot for static hosting (e.g. GitHub Pages).

The legal decisions are still made by the Python rule engine; this script just
writes its output (curb segments with reasons) plus the compact road/walk graphs
the in-browser recommender needs.

Usage:  python scripts/export_static.py [out_dir]
Default out_dir: ../frontend/public/static-data
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config as C  # noqa: E402
from app.citymodel import CityModel, load_raw  # noqa: E402
from app.planning import Planner, attach_reviews  # noqa: E402
from app.rules import ruleset  # noqa: E402
from app.store import Store  # noqa: E402

ROUND = 7


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else C.BASE_DIR.parent / "frontend" / "public" / "static-data"
    out.mkdir(parents=True, exist_ok=True)
    raw = load_raw()
    # Only real, reviewed observations from the database. Nothing is added for the demo:
    # without verified surveys the static map is RED/YELLOW only, exactly like the API.
    features = Store().list() if C.DB_PATH.exists() else []
    m = CityModel(raw, [f for f in features if f["status"] in ("verified", "pending")])

    s, w, n, e = m.bbox
    meta = {"area": "28 May, Bakı", "bbox": m.bbox, "center": [(w + e) / 2, (s + n) / 2],
            "osm_timestamp": m.osm_timestamp, "built_at": m.built_at, "build_ms": 0,
            "ruleset": ruleset()["version"], "law": ruleset()["law"], "stats": m.stats(), "mode": "static",
            "vehicle": C.DEFAULT_VEHICLE, "vehicles": ["taxi", "private"],
            "stats_by_vehicle": {v: m.stats(v) for v in ("taxi", "private")}}

    # --- compact graph for the browser recommender ---------------------------
    node_ids = sorted({n for w_ in m.drive_ways.values() for n in w_.nodes} | set(m.walk_adj))
    idx = {nid: i for i, nid in enumerate(node_ids)}
    coords = [[round(m.nodes[nid]["lon"], ROUND), round(m.nodes[nid]["lat"], ROUND)] for nid in node_ids]

    ways = []
    way_idx = {}
    for w_ in m.drive_ways.values():
        way_idx[w_.id] = len(ways)
        ways.append({"id": w_.id, "n": [idx[x] for x in w_.nodes], "w": round(w_.width, 2), "o": int(w_.oneway),
                     "sp": round(w_.speed(), 3), "nm": w_.name, "c": int(w_.id in m.ways)})

    walk = []
    seen = set()
    for a, nbrs in m.walk_adj.items():
        for b, _ in nbrs:
            key = (min(a, b), max(a, b))
            if key not in seen:
                seen.add(key)
                walk.append([idx[a], idx[b]])

    segs = []
    status_code = {"PROHIBITED": "P", "ALLOWED": "A", "UNVERIFIED": "U"}
    for sg in m.segments.values():
        sv = sg["status_by_vehicle"]
        segs.append([sg["id"], way_idx[sg["way_id"]], sg["side"][0], round(sg["start_m"], 2), round(sg["end_m"], 2),
                     status_code[sv["taxi"]] + status_code[sv["private"]], int(sg["official"]),
                     [r["rule"] for r in sg["notes"]], sg["confidence"],
                     sorted({r["rule"] for r in sg["reasons"]}), sorted({r["rule"] for r in sg["cautions"]})])

    engine = {"nodes": coords, "ways": ways, "walk": walk, "segments": segs,
              "crossings": sorted(idx[x] for x in m.crossing_nodes if x in idx),
              "intersections": sorted(idx[x] for x in m.intersections if x in idx)}

    details = {k: {kk: vv for kk, vv in v.items() if kk != "coords"} for k, v in m.segments.items()}
    search = [{**it, "_n": it["_n"]} for it in m.search_items]
    keep = ("id", "kind", "status", "geometry", "props", "source", "source_url", "source_ref", "observed_at",
            "verified_at", "note")
    public_features = [{k: f.get(k) for k in keep} for f in features if f["status"] == "verified"]

    # B2G planning snapshot: same engine as /api/authority/*, read-only on the static site
    store = Store() if C.DB_PATH.exists() else None
    area = (store.get_area("28-may-pilot") if store else None) or {"id": "28-may-pilot", "name": "28 May pilot (Bakı)",
                                                                   "inventory_status": "unknown"}
    activity = store.list_activity(status="verified") if store else []
    plan = attach_reviews(Planner(m, activity, area).run(), store.reviews() if store else [])
    plan["area"]["name"] = area.get("name", "28 May pilot (Bakı)")
    plan["area"]["polygon"] = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
    from app.main import LIMITATIONS  # noqa: E402 - single source of the limitations text
    plan["limitations"] = LIMITATIONS
    plan["read_only"] = True
    act_rows = []
    for a in activity:
        rate = Planner.activity_rate(a)
        small = a["pickups"] + a["dropoffs"] < 5
        act_rows.append({"id": a["id"], "place_name": a["place_name"], "geometry": a["geometry"],
                         "period_start": a["period_start"], "period_end": a["period_end"],
                         "pickups": a["pickups"] if a["pickups"] >= 5 else "<5",
                         "dropoffs": a["dropoffs"] if a["dropoffs"] >= 5 else "<5",
                         "per_hour": None if small or rate is None else round(rate, 1), "vehicle_scope": a["vehicle_scope"],
                         "method": a["method"], "source": a["source"], "source_url": a["source_url"],
                         "verified_at": a["verified_at"], "measured": True})
    act_rows.sort(key=lambda x: -(x["per_hour"] or 0))

    files = {
        "meta.json": meta, "segments.json": m.segments_geojson(), "segment-details.json": details,
        "context.json": m.context_layers(), "features.json": public_features, "search.json": search,
        "engine.json": engine, "rules.json": ruleset(), "planning.json": plan,
        "activity.json": {"rows": act_rows, "measured": bool(act_rows), "suppression_threshold": 5},
    }
    for name, data in files.items():
        (out / name).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        print(f"{name:24s} {(out / name).stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()

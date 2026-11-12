"""Export a precomputed, read-only snapshot for static hosting (e.g. GitHub Pages).

The legal decisions are still made by the Python rule engine; this script just
writes its output (curb segments with reasons) plus the compact road/walk graphs
the in-browser recommender needs.

Usage:  python scripts/export_static.py [out_dir]
Default out_dir: ../frontend/public/static-data
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config as C  # noqa: E402
from app.citymodel import CityModel, load_raw  # noqa: E402
from app.demo import enabled as demo_enabled  # noqa: E402
from app.demo import with_demo  # noqa: E402
from app.planning import build_snapshot  # noqa: E402
from app.planning_store import PlanningStore  # noqa: E402
from app.rules import ruleset  # noqa: E402
from app.store import Store  # noqa: E402

ROUND = 7


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else C.BASE_DIR.parent / "frontend" / "public" / "static-data"
    out.mkdir(parents=True, exist_ok=True)
    raw = load_raw()
    # Only real, reviewed observations from the database. With BURDASAXLA_DEMO_SURVEY=1 one in-memory
    # SIMULATED EXAMPLE survey area is added (app/demo.py); its green is labelled `simulated` everywhere.
    features = Store().list() if C.DB_PATH.exists() else []
    m = CityModel(raw, with_demo([f for f in features if f["status"] in ("verified", "pending")], raw["bbox"]))

    revision = os.environ.get("GITHUB_SHA") or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=C.BASE_DIR.parent, text=True).strip()
    if not os.environ.get("GITHUB_SHA") and subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=C.BASE_DIR.parent, text=True).strip():
        revision += "-dirty"
    planning_store = PlanningStore(C.DB_PATH)
    planning = build_snapshot(m, features, passenger_activity=planning_store.activity(),
                              reviews=planning_store.reviews(public=True), code_revision=revision)
    s, w, n, e = m.bbox
    meta = {"area": "28 May, Bakı", "bbox": m.bbox, "center": [(w + e) / 2, (s + n) / 2],
            "osm_timestamp": m.osm_timestamp, "built_at": m.built_at, "build_ms": 0,
            "code_revision": revision, "planning_run_id": planning["run_id"],
            "ruleset": ruleset()["version"], "law": ruleset()["law"], "stats": m.stats(), "mode": "static",
            "demo_survey": demo_enabled(),
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

    files = {
        "meta.json": meta, "segments.json": m.segments_geojson(), "segment-details.json": details,
        "context.json": m.context_layers(), "features.json": public_features, "search.json": search,
        "engine.json": engine, "rules.json": ruleset(), "planning.json": planning,
    }
    for name, data in files.items():
        (out / name).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        print(f"{name:24s} {(out / name).stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()

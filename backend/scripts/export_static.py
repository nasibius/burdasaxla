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
from app.rules import ruleset  # noqa: E402
from app.store import Store  # noqa: E402

ROUND = 7


def demo_survey(bbox):
    s, w, n, e = bbox
    ds, dw = (n - s) * 0.15, (e - w) * 0.15
    return {"id": 1, "kind": "survey_area", "status": "verified", "source": "demo_seed",
            "note": "DEMO: treated as surveyed for the hackathon demo. Replace with real field-survey areas.",
            "verified_at": None, "created_at": None, "props": {"label": "Demo survey area"},
            "geometry": {"type": "Polygon", "coordinates": [[[w + dw, s + ds], [e - dw, s + ds], [e - dw, n - ds],
                                                             [w + dw, n - ds], [w + dw, s + ds]]]}}


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else C.BASE_DIR.parent / "frontend" / "public" / "static-data"
    out.mkdir(parents=True, exist_ok=True)
    raw = load_raw()
    features = Store().list(status="verified") if C.DB_PATH.exists() else []
    if not any(f["kind"] == "survey_area" for f in features):
        features.append(demo_survey(raw["bbox"]))
    m = CityModel(raw, features)

    s, w, n, e = m.bbox
    meta = {"area": "28 May, Bakı", "bbox": m.bbox, "center": [(w + e) / 2, (s + n) / 2],
            "osm_timestamp": m.osm_timestamp, "built_at": m.built_at, "build_ms": 0,
            "ruleset": ruleset()["version"], "stats": m.stats(), "mode": "static"}

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
    for sg in m.segments.values():
        segs.append([sg["id"], way_idx[sg["way_id"]], sg["side"][0], round(sg["start_m"], 2), round(sg["end_m"], 2),
                     sg["status"][0], int(sg["official"]), [r["rule"] for r in sg["notes"]], sg["confidence"],
                     sorted({r["rule"] for r in sg["reasons"]})])

    engine = {"nodes": coords, "ways": ways, "walk": walk, "segments": segs,
              "crossings": sorted(idx[x] for x in m.crossing_nodes if x in idx),
              "intersections": sorted(idx[x] for x in m.intersections if x in idx)}

    details = {k: {kk: vv for kk, vv in v.items() if kk != "coords"} for k, v in m.segments.items()}
    search = [{**it, "_n": it["_n"]} for it in m.search_items]
    public_features = [f for f in features if f["status"] == "verified"]

    files = {
        "meta.json": meta, "segments.json": m.segments_geojson(), "segment-details.json": details,
        "context.json": m.context_layers(), "features.json": public_features, "search.json": search,
        "engine.json": engine,
    }
    for name, data in files.items():
        (out / name).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        print(f"{name:24s} {(out / name).stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()

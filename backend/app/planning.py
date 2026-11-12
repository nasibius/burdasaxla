"""Conservative authority planning. Proposals never write to the legal supply store."""
import csv
import hashlib
import io
import json
from collections import Counter
from datetime import datetime, timezone

from shapely.geometry import LineString, box, mapping, shape

from .citymodel import to_m_point
from .dropoff import dijkstra

VERSION = "planning-survey-v1"
AREA_ID = "28-may"
LIMITATIONS = [
    "Investigation only; not an authorized pickup/drop-off location or legal permission.",
    "Verified supply inventory incomplete — coverage cannot be established.",
    "OSM curb offsets are approximate; pedestrian connections and physical feasibility require field assessment.",
    "POIs are geographic proxies, not measured taxi demand. AYNA is a potential stakeholder, not a partner.",
]
METHODOLOGY = (
    "Survey targets: unverified curb segments at least 7 m long, inside the pilot, excluding current prohibited "
    "segments. Stable segment-ID order, minimum 150 m between target midpoints, maximum 24 targets. "
    "Spacing is a survey sampling policy, not walking distance or a suitability ranking. No numeric score. "
    "Coverage requires a fresh complete inventory and validated pedestrian network attachments."
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def assess_coverage(nodes, zones, graph, *, inventory_complete, inventory_fresh, network_reliable, threshold_m=450):
    """Distances only on a validated metric walk graph; never snap through unknown barriers.

    Adapter contract: node/zone graph_node and access_verified certify the attachment;
    zones also need eligible=True. Incomplete inventory takes precedence over network uncertainty.
    """
    if not 50 <= threshold_m <= 1500:
        raise ValueError("threshold_m must be 50–1500")
    eligible = [z for z in zones if z.get("eligible")]
    attachments_ok = all(z.get("access_verified") and z.get("graph_node") in graph for z in eligible)
    distances = {}
    if inventory_complete and inventory_fresh and network_reliable and attachments_ok:
        distances, _ = dijkstra(graph, {z["graph_node"]: 0 for z in eligible})
    out = []
    for node in nodes:
        distance = None
        if not inventory_complete or not inventory_fresh:
            state, reason = "INVENTORY_UNKNOWN", "Existing verified supply inventory incomplete or stale"
        elif not (network_reliable and attachments_ok and node.get("access_verified")
                  and node.get("graph_node") in graph):
            state, reason = "NETWORK_UNRELIABLE", "Pedestrian network or endpoint access not validated"
        else:
            distance = distances.get(node["graph_node"])
            state = "SERVED" if distance is not None and distance <= threshold_m else "POTENTIAL_COVERAGE_GAP"
            reason = ("Validated network shortest path" if distance is not None
                      else "No reachable eligible zone in validated graph")
        out.append({**node, "state": state, "distance_m": distance, "threshold_m": threshold_m, "reason": reason})
    return out


def candidate_class(*, hard_exclusions, missing_evidence):
    if hard_exclusions:
        return "EXCLUDED"
    return "DATA_COLLECTION_NEEDED" if missing_evidence else "SCREENED_FOR_FURTHER_STUDY"


def build_snapshot(model, features, *, passenger_activity=None, reviews=None, threshold_m=450, code_revision="unknown"):
    """Same function for API and Pages. Current adapter deliberately cannot certify inventory/network."""
    features = [f for f in features if f.get("source") != "demo_seed" and not f.get("is_synthetic_example")]
    features = sorted(({k: v for k, v in f.items() if k != "evidence"} for f in features), key=lambda f: f["id"])
    verified = [f for f in features if f.get("status") == "verified"]
    official = [f for f in verified if f.get("kind") == "official_zone"]
    observed = [s for s in model.segments.values() if s["status"] == "ALLOWED" and not s["official"]]
    inventory_version = digest(verified)
    sources = {"osm": model.osm_timestamp, "verified_inventory": inventory_version,
               "code_revision": code_revision, "network_checksum": digest(model.raw), "observations": digest(features),
               "ruleset": next(iter(model.segments.values()), {}).get("ruleset_version")}
    parameters = {"threshold_m": threshold_m, "spacing_m": 150, "max_targets": 24, "min_length_m": 7}
    run_id = digest({"sources": sources, "parameters": parameters, "algorithm": VERSION})
    south, west, north, east = model.bbox
    boundary = box(west, south, east, north)
    access = []
    # Use source-identifiable OSM nodes, not building centroids disguised as entrances.
    for nid, n in sorted(model.nodes.items()):
        tags = n.get("tags", {})
        if not any(k in tags for k in ("entrance", "amenity", "public_transport", "railway")):
            continue
        geom = {"type": "Point", "coordinates": [n["lon"], n["lat"]]}
        if not boundary.covers(shape(geom)):
            continue
        access.append({"id": f"node/{nid}", "name": tags.get("name", f"OSM {nid}"), "geometry": geom,
                       "is_proxy": True, "source_url": f"https://www.openstreetmap.org/node/{nid}",
                       "access_verified": False, "graph_node": nid if nid in model.walk_adj else None})
    coverage = assess_coverage(access, [], model.walk_adj, inventory_complete=False, inventory_fresh=False,
                               network_reliable=False, threshold_m=threshold_m)
    candidates, excluded, points = [], [], []
    reviews = reviews or []
    review_by_id = {}
    for review in reviews:
        review_by_id.setdefault(review["candidate_id"], []).append(review)
    for seg in sorted(model.segments.values(), key=lambda s: s["id"]):
        reason = None
        if seg["status"] == "PROHIBITED":
            reason = "Current restriction: " + ", ".join(r["rule"] for r in seg["reasons"])
        elif seg["length_m"] < 7:
            reason = "Insufficient approximate segment length"
        elif not boundary.covers(LineString(seg["coords"])):
            reason = "Outside pilot boundary"
        elif seg["status"] == "ALLOWED":
            reason = "Existing verified curb; not a new survey target"
        if reason:
            excluded.append({"segment_id": seg["id"], "reason": reason})
            continue
        mid = LineString(seg["coords"]).interpolate(0.5, normalized=True)
        metric = to_m_point(mid.x, mid.y)
        if any(metric.distance(p) < parameters["spacing_m"] for p in points):
            excluded.append({"segment_id": seg["id"], "reason": "Survey spacing policy"})
            continue
        if len(candidates) >= parameters["max_targets"]:
            excluded.append({"segment_id": seg["id"], "reason": "Survey batch limit; not a suitability exclusion"})
            continue
        points.append(metric)
        cid = "survey-" + seg["id"]
        missing = ["Complete fresh existing-zone inventory", "Field-measured curb geometry and clearances",
                   "Validated pedestrian access and crossings", "Vehicle approach feasibility",
                   "Official engineering/legal assessment", "Curb ramps and sidewalk width"]
        history = review_by_id.get(cid, [])
        candidates.append({
            "candidate_id": cid, "curb_segment_id": seg["id"], "planning_area_id": AREA_ID,
            "name": seg["name"] or seg["osm_ref"], "road_side": seg["side"], "length_m": seg["length_m"],
            "geometry": {"type": "LineString", "coordinates": seg["coords"]},
            "candidate_class": candidate_class(hard_exclusions=[], missing_evidence=missing),
            "purpose": "Survey pickup/drop-off feasibility; use allocation undecided",
            "current_legal_status": "UNKNOWN", "officially_approved": False,
            "coverage_finding": "INVENTORY_UNKNOWN", "measured_taxi_demand_available": False,
            "walk_distance_to_verified_zone_m": None, "pedestrian_access_path": None,
            "potential_accessibility_benefit": None, "score": None, "rank": None,
            "display_order": len(candidates) + 1, "evidence_strength": "GEOMETRY_ONLY",
            "reasons": ["Mapped curb with incomplete field evidence; a reproducible inventory survey target"],
            "missing_evidence": missing, "constraints": [r["rule"] for r in seg["cautions"]],
            "factors": {k: None for k in ("network_improvement", "safety", "pedestrian_access", "vehicle_access")},
            "source_url": f"https://www.openstreetmap.org/{seg['osm_ref']}", "source_snapshot": sources,
            "last_verified": seg["last_verified"], "is_synthetic_example": False,
            "run_id": run_id, "algorithm_version": VERSION,
            "review_status": history[-1]["action"] if history else "needs_survey",
            "review_history": history, "limitations": LIMITATIONS, "methodology": METHODOLOGY,
        })
    activity = passenger_activity or []
    return {
        "area": {"id": AREA_ID, "name": "28 May, Bakı", "geometry": mapping(boundary)},
        "run_id": run_id, "algorithm_version": VERSION, "generated_at": model.built_at,
        "source_versions": sources, "parameters": parameters, "limitations": LIMITATIONS, "methodology": METHODOLOGY,
        "inventory_state": "INVENTORY_UNKNOWN", "network_state": "NETWORK_UNRELIABLE",
        "summary": {"verified_official_locations": len(official), "observed_usable_curb_segments": len(observed),
                    "synthetic_examples": 0, "investigation_sites": 0, "survey_tasks": len(candidates),
                    "analyzed_nodes": len(coverage), "coverage_share": None,
                    "coverage_counts": dict(Counter(n["state"] for n in coverage)), "excluded_segments": len(excluded)},
        "verified_locations": [{k: f.get(k) for k in ("id", "geometry", "source_url", "verified_at", "source")}
                               for f in official],
        "coverage": coverage, "candidates": candidates, "exclusions": excluded,
        "passenger_activity": activity, "measured_passenger_activity_available": bool(activity),
        "passenger_activity_version": digest(activity),
        "empty_reason": None if candidates else "No defensible candidate found. Request an area inventory survey.",
    }


def filtered_candidates(snapshot, status=None):
    return [c for c in snapshot["candidates"] if not status or c["review_status"] == status]


def export_candidates(snapshot, fmt, status=None):
    candidates = filtered_candidates(snapshot, status)
    if fmt == "geojson":
        return json.dumps({"type": "FeatureCollection", "run_id": snapshot["run_id"],
                           "limitations": snapshot["limitations"], "methodology": snapshot["methodology"],
                           "features": [{"type": "Feature", "geometry": c["geometry"],
                                         "properties": {k: v for k, v in c.items() if k != "geometry"}}
                                        for c in candidates]}, ensure_ascii=False)
    columns = ["candidate_id", "name", "road_side", "candidate_class", "review_status", "coverage_finding", "score",
               "rank", "officially_approved", "current_legal_status", "length_m", "evidence_strength", "last_verified",
               "walk_distance_to_verified_zone_m", "measured_taxi_demand_available", "geometry", "source_snapshot",
               "source_url", "missing_evidence", "constraints", "limitations",
               "methodology", "is_synthetic_example", "run_id"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns)
    writer.writeheader()
    for candidate in candidates:
        row = {}
        for key in columns:
            value = candidate.get(key)
            value = (json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, bool))
                     else str(value) if value is not None else "")
            # Spreadsheet formula injection guard, including leading control/whitespace.
            row[key] = "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
        writer.writerow(row)
    return out.getvalue()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

"""B2G planning engine: coverage of verified pick-up/drop-off supply, survey priorities and
new-zone investigation candidates for transport authorities (e.g. AYNA).

This is a different question from the driver recommender:
  driver:    "where may I stop *today*?"                      -> legal, verified curbs only
  authority: "where should *new* official zones be studied?"   -> proposals, never legal permissions

Honesty rules implemented here (see docs/B2G_PLANNING.md):
  * Access nodes are POIs / stations from OSM and are always labelled `is_proxy = True`.
    They are NOT taxi demand. Measured demand comes only from the `passenger_activity` table.
  * Coverage states per node: SERVED, POTENTIAL_COVERAGE_GAP, INVENTORY_UNKNOWN, NETWORK_UNRELIABLE.
    A gap can only be concluded when the verified-zone inventory of the area is declared complete
    (with a source). Otherwise every unserved node is INVENTORY_UNKNOWN.
  * Candidates are produced only for supported gaps. Missing critical evidence -> DATA_COLLECTION_NEEDED
    with no numeric score. No defensible site -> a survey task instead of a forced pin.
  * Every factor that cannot be computed is reported as `unknown` and excluded from the score
    (weights renormalised over available factors), never scored as 0 or 1.
"""
from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import datetime, timezone

from shapely.geometry import Point

from . import config as C
from .citymodel import ALLOWED, PROHIBITED, UNVERIFIED, CityModel, to_ll_coords, to_m_point
from .dropoff import dijkstra

ALGORITHM_VERSION = "b2g-planning-1.0"
DEFAULT_THRESHOLD_M = 300          # planning scenario assumption, NOT a legal distance
CELL_M = 150                       # survey-task grid size
SNAP_MAX_M = 60                    # access node must be this close to the walk network
MIN_COMPONENT_NODES = 50           # smaller walk-graph islands are treated as unreliable
CANDIDATE_MIN_LEN_M = 12           # shorter curb pieces cannot hold a loading zone
CANDIDATE_SPACING_M = 60
MAX_CANDIDATES_PER_CLUSTER = 2

SURVEY_WEIGHTS = {"access_proxy": 0.35, "measured_activity": 0.25, "transit_hub": 0.15,
                  "unverified_curb_share": 0.15, "no_verified_supply": 0.10}
CANDIDATE_WEIGHTS = {"walk_access_improvement": 0.35, "known_feasibility": 0.25, "pedestrian_connectivity": 0.20,
                     "vehicle_curb_practicality": 0.10, "evidence_completeness": 0.10}

PROXY_KEYS = ("amenity", "shop", "tourism", "office", "leisure", "healthcare")
TRANSIT = {("railway", "station"), ("public_transport", "station"), ("amenity", "bus_station"),
           ("station", "subway"), ("railway", "subway_entrance")}


def _stable_id(prefix, *parts):
    h = hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8]
    return f"{prefix}-{h}"


def _weighted(factors: dict, weights: dict):
    """Weighted score over AVAILABLE factors only; returns (score 0..100 or None, used, missing)."""
    used = {k: v for k, v in factors.items() if v is not None}
    missing = sorted(k for k, v in factors.items() if v is None)
    total_w = sum(weights[k] for k in used)
    if not used or total_w == 0:
        return None, used, missing
    score = 100 * sum(weights[k] * used[k] for k in used) / total_w
    return round(score, 1), used, missing


class Planner:
    def __init__(self, model: CityModel, activity: list[dict] | None = None, area: dict | None = None):
        self.m = model
        self.area = area or {"id": "28-may-pilot", "inventory_status": "unknown"}
        self.activity = [a for a in (activity or []) if a.get("status") == "verified"]
        self._components()
        self.nodes = self._access_nodes()

    # ---------------------------------------------------------------- inputs
    def _components(self):
        comp, sizes, cid = {}, {}, 0
        for start in self.m.walk_adj:
            if start in comp:
                continue
            stack, n = [start], 0
            comp[start] = cid
            while stack:
                u = stack.pop()
                n += 1
                for v, _ in self.m.walk_adj[u]:
                    if v not in comp:
                        comp[v] = cid
                        stack.append(v)
            sizes[cid] = n
            cid += 1
        self.comp, self.comp_size = comp, sizes
        self.main_comp = max(sizes, key=sizes.get) if sizes else None

    def _reliable(self, walk_node):
        """On the main pedestrian network, or on a piece big enough not to be a mapping fragment."""
        c = self.comp.get(walk_node)
        return c is not None and (c == self.main_comp or self.comp_size[c] >= MIN_COMPONENT_NODES)

    def _access_nodes(self):
        """Geographic PROXIES for where people go: named POIs, stations, entrances. Never demand."""
        s_, w_, n_, e_ = self.m.bbox
        out, seen = [], set()
        for el in self.m.raw["elements"]:
            t = el.get("tags") or {}
            kind = next((f"{k}={t[k]}" for k in PROXY_KEYS if k in t), None)
            transit = any(t.get(k) == v for k, v in TRANSIT)
            if t.get("entrance") and t.get("entrance") != "no":
                kind = kind or f"entrance={t['entrance']}"
            if transit:
                kind = next((f"{k}={v}" for k, v in TRANSIT if t.get(k) == v), kind)
            if not kind:
                continue
            if el["type"] == "node":
                lon, lat = el["lon"], el["lat"]
            elif el["type"] == "way":
                pts = [self.m.nodes[n] for n in el.get("nodes", []) if n in self.m.nodes]
                if not pts:
                    continue
                lon, lat = sum(p["lon"] for p in pts) / len(pts), sum(p["lat"] for p in pts) / len(pts)
            else:
                continue
            if not (s_ <= lat <= n_ and w_ <= lon <= e_):
                continue
            key = (round(lon, 4), round(lat, 4), t.get("name"))
            if key in seen:
                continue
            seen.add(key)
            out.append({"id": f"{el['type']}/{el['id']}", "lon": lon, "lat": lat, "pt": to_m_point(lon, lat),
                        "kind": kind, "name": t.get("name:az") or t.get("name") or "", "transit_hub": transit,
                        "is_proxy": True, "source": "osm"})
        return out

    def _curb_supply(self):
        out = []
        for seg in self.m.segments.values():
            if seg["status_by_vehicle"]["taxi"] != ALLOWED or seg["length_m"] < C.MIN_STOP_LENGTH_M:
                continue
            w = self.m.ways[seg["way_id"]]
            pos = (seg["start_m"] + seg["end_m"]) / 2
            pt = w.curb_point(pos, seg["side"])
            out.append({"segment_id": seg["id"], "type": "official_designated" if seg["official"] else "field_verified_suitable",
                        "way": w, "pos": pos, "point": to_ll_coords([(pt.x, pt.y)])[0], "street": seg["name"],
                        "side": seg["side"], "verified_at": seg["last_verified"], "sources": seg["coverage"]})
        return out

    def supply(self):
        """Existing OFFICIALLY DESIGNATED pick-up/drop-off zones (verified). This is what authority coverage is
        measured against: the question is where *new official* zones are needed."""
        return [s for s in self._curb_supply() if s["type"] == "official_designated"]

    def observed_suitable(self):
        """Curbs verified on site as legal for stopping but not officially designated. They are not counted as
        official supply; they are the natural SCREENED_FOR_FURTHER_STUDY candidates."""
        return [s for s in self._curb_supply() if s["type"] == "field_verified_suitable"]

    # -------------------------------------------------------------- coverage
    def _snap(self, pt: Point):
        idx, dist = self.m.walk_edge_tree.query_nearest(pt, max_distance=SNAP_MAX_M, return_distance=True)
        if len(idx) == 0:
            return None
        j = int(idx[0])
        a, b, L, _ = self.m.walk_edge_meta[j]
        t = self.m.walk_edge_geoms[j].project(pt)
        acc = float(dist[0])
        return {a: acc + t, b: acc + (L - t)}

    def _supply_distances(self, supply):
        sources = {}
        for s in supply:
            w, pos = s["way"], s["pos"]
            i = w.edge_index(pos)
            for node, d in ((w.nodes[i], pos - w.cum[i]), (w.nodes[i + 1], w.cum[i + 1] - pos)):
                if node in self.m.walk_adj:
                    d += w.width / 2
                    if d < sources.get(node, (math.inf,))[0]:
                        sources[node] = (d, s)
        if not sources:
            return {}, {}
        dist, prev = dijkstra(self.m.walk_adj, {n: d for n, (d, _) in sources.items()})
        # remember which supply each node is closest to (follow prev to a source)
        owner = {}
        for n in dist:
            cur = n
            while cur in prev and cur not in sources:
                cur = prev[cur]
            owner[n] = sources.get(cur, (None, None))[1]
        return dist, owner

    def coverage(self, threshold_m=DEFAULT_THRESHOLD_M):
        supply = self.supply()
        dist, owner = self._supply_distances(supply)
        complete = self.area.get("inventory_status") == "complete"
        out = []
        for n in self.nodes:
            snap = self._snap(n["pt"])
            rec = {k: n[k] for k in ("id", "lon", "lat", "kind", "name", "transit_hub", "is_proxy", "source")}
            if not snap or not any(self._reliable(x) for x in snap):
                rec.update(state="NETWORK_UNRELIABLE", distance_m=None,
                           reason="Not connected to the mapped pedestrian network (or only to a small isolated piece).")
            else:
                best, via = math.inf, None
                for node, d0 in snap.items():
                    if node in dist and dist[node] + d0 < best:
                        best, via = dist[node] + d0, owner.get(node)
                if best <= threshold_m:
                    rec.update(state="SERVED", distance_m=round(best), nearest_supply=via["segment_id"] if via else None,
                               nearest_supply_type=via["type"] if via else None,
                               reason=f"Verified pick-up/drop-off curb {round(best)} m away on the walking network.")
                elif complete:
                    rec.update(state="POTENTIAL_COVERAGE_GAP", distance_m=round(best) if best < math.inf else None,
                               reason=("No verified zone within the threshold on the walking network; the area's "
                                       "verified-zone inventory is declared complete."))
                else:
                    rec.update(state="INVENTORY_UNKNOWN", distance_m=round(best) if best < math.inf else None,
                               reason=("No verified zone found within the threshold, but the verified-zone inventory "
                                       "is incomplete — a shortage cannot be concluded."))
            rec["threshold_m"] = threshold_m
            out.append(rec)
        return out, supply

    # ------------------------------------------------------------- activity
    @staticmethod
    def activity_rate(a):
        try:
            t0 = datetime.fromisoformat(a["period_start"])
            t1 = datetime.fromisoformat(a["period_end"])
            hours = max((t1 - t0).total_seconds() / 3600, 1 / 60)
        except (ValueError, TypeError):
            return None
        return (a["pickups"] + a["dropoffs"]) / hours

    # ----------------------------------------------------------- clustering
    def _cell(self, pt):
        return int(pt.x // CELL_M), int(pt.y // CELL_M)

    def _cell_polygon(self, cx, cy):
        x0, y0 = cx * CELL_M, cy * CELL_M
        ring = [(x0, y0), (x0 + CELL_M, y0), (x0 + CELL_M, y0 + CELL_M), (x0, y0 + CELL_M), (x0, y0)]
        return {"type": "Polygon", "coordinates": [to_ll_coords(ring)]}

    def run(self, threshold_m=DEFAULT_THRESHOLD_M):
        cov, supply = self.coverage(threshold_m)
        by_cell = defaultdict(list)
        for rec, n in zip(cov, self.nodes, strict=True):
            by_cell[self._cell(n["pt"])].append(rec)
        seg_by_cell = defaultdict(list)
        for seg in self.m.segments.values():
            w = self.m.ways[seg["way_id"]]
            p = w.curb_point((seg["start_m"] + seg["end_m"]) / 2, seg["side"])
            seg_by_cell[self._cell(p)].append(seg)
        act_by_cell = defaultdict(list)
        for a in self.activity:
            act_by_cell[self._cell(to_m_point(*a["geometry"]["coordinates"]))].append(a)
        any_activity = bool(self.activity)
        max_rate = max((self.activity_rate(a) or 0 for a in self.activity), default=0)

        tasks, candidates, gap_cells = [], [], []
        for (cx, cy), recs in sorted(by_cell.items()):
            states = defaultdict(int)
            for r in recs:
                states[r["state"]] += 1
            if states["POTENTIAL_COVERAGE_GAP"]:
                gap_cells.append(((cx, cy), recs))
            if states["SERVED"] == len(recs):
                continue  # fully served cells need no task
            segs = seg_by_cell.get((cx, cy), [])
            curb_total = sum(s["length_m"] for s in segs)
            curb_unv = sum(s["length_m"] for s in segs if s["status"] == UNVERIFIED)
            rates = [self.activity_rate(a) for a in act_by_cell.get((cx, cy), [])]
            factors = {
                "access_proxy": min(1.0, len(recs) / 20),
                "measured_activity": (min(1.0, sum(r or 0 for r in rates) / max_rate) if max_rate else 0.0)
                if any_activity else None,
                "transit_hub": 1.0 if any(r["transit_hub"] for r in recs) else 0.0,
                "unverified_curb_share": round(curb_unv / curb_total, 3) if curb_total else None,
                "no_verified_supply": 0.0 if states["SERVED"] else 1.0,
            }
            score, used, missing = _weighted(factors, SURVEY_WEIGHTS)
            to_survey = sorted((s for s in segs if s["status"] == UNVERIFIED and s["length_m"] >= CANDIDATE_MIN_LEN_M),
                               key=lambda s: -s["length_m"])[:5]
            kinds = defaultdict(int)
            for r in recs:
                kinds[r["kind"]] += 1
            tid = f"survey-{cx}-{cy}"
            tasks.append({
                "id": tid, "type": "survey_task", "cell": [cx, cy], "geometry": self._cell_polygon(cx, cy),
                "centroid": to_ll_coords([((cx + 0.5) * CELL_M, (cy + 0.5) * CELL_M)])[0],
                "priority_score": score, "factors": factors, "factors_missing": missing,
                "access_nodes": len(recs), "access_nodes_are_proxy": True,
                "access_kinds": dict(sorted(kinds.items(), key=lambda x: -x[1])[:6]),
                "transit_hubs": [r["name"] or r["kind"] for r in recs if r["transit_hub"]][:4],
                "coverage_states": dict(states),
                "measured_activity": {"rows": len(rates), "per_hour": round(sum(r or 0 for r in rates), 1)} if rates
                else ("not_measured" if not any_activity else {"rows": 0, "per_hour": 0}),
                "curb_m": {"total": round(curb_total), "unverified": round(curb_unv),
                           "prohibited": round(sum(s["length_m"] for s in segs if s["status"] == PROHIBITED)),
                           "allowed": round(sum(s["length_m"] for s in segs if s["status"] == ALLOWED))},
                "curb_segments_to_survey": [{"segment_id": s["id"], "street": s["name"], "compass": s["compass"],
                                             "length_m": s["length_m"], "cautions": [c["rule"] for c in s["cautions"]]}
                                            for s in to_survey],
                "missing_evidence": self._task_missing(states),
                "why": self._task_why(states, recs, factors),
                "officially_approved": False,
            })
        tasks.sort(key=lambda t: (-(t["priority_score"] or -1), t["id"]))
        for i, t in enumerate(tasks, 1):
            t["rank"] = i

        if gap_cells:
            candidates, no_candidate = self._candidates(gap_cells, threshold_m)
            for cell_id in no_candidate:
                for t in tasks:
                    if t["id"] == cell_id:
                        t["no_defensible_candidate"] = True

        observed = self.observed_suitable()
        summary = {
            "verified_supply_locations": len(supply),
            "verified_supply_by_type": {"official_designated": len(supply), "field_verified_suitable": len(observed)},
            "access_nodes": len(cov),
            "coverage_states": {s: sum(r["state"] == s for r in cov) for s in
                                ("SERVED", "POTENTIAL_COVERAGE_GAP", "INVENTORY_UNKNOWN", "NETWORK_UNRELIABLE")},
            "survey_tasks": len(tasks),
            "candidates": {k: sum(c["candidate_class"] == k for c in candidates)
                           for k in ("SCREENED_FOR_FURTHER_STUDY", "DATA_COLLECTION_NEEDED")},
            "measured_activity_rows": len(self.activity),
        }
        reliable = [r for r in cov if r["state"] != "NETWORK_UNRELIABLE"]
        summary["served_share"] = (round(summary["coverage_states"]["SERVED"] / len(reliable), 3)
                                   if reliable and self.area.get("inventory_status") == "complete" else None)
        return {
            "algorithm_version": ALGORITHM_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "parameters": {"threshold_m": threshold_m, "cell_m": CELL_M, "snap_max_m": SNAP_MAX_M,
                           "survey_weights": SURVEY_WEIGHTS, "candidate_weights": CANDIDATE_WEIGHTS,
                           "candidate_min_len_m": CANDIDATE_MIN_LEN_M},
            "area": {k: self.area.get(k) for k in ("id", "name", "inventory_status", "inventory_source_url",
                                                    "inventory_declared_by", "inventory_declared_at", "inventory_note")},
            "source_versions": {"osm_snapshot": self.m.osm_timestamp, "model_built_at": self.m.built_at,
                                "ruleset": self.m.segments and next(iter(self.m.segments.values()))["ruleset_version"],
                                "verified_observations": sum(f["status"] == "verified" for f in self.m.features),
                                "measured_activity_rows": len(self.activity)},
            "inventory_complete": self.area.get("inventory_status") == "complete",
            "demand_measured": bool(self.activity),
            "summary": summary,
            "supply": [{k: s[k] for k in ("segment_id", "type", "point", "street", "side", "verified_at")} for s in supply],
            "observed_suitable": [{k: s[k] for k in ("segment_id", "type", "point", "street", "side", "verified_at")}
                                  for s in observed],
            "coverage": cov,
            "survey_tasks": tasks,
            "candidates": candidates,
        }

    @staticmethod
    def _task_missing(states):
        out = []
        if states["INVENTORY_UNKNOWN"]:
            out.append("Complete, sourced inventory of officially designated pick-up/drop-off zones (AYNA)")
            out.append("Field survey of signs (3.27/3.28) and markings (1.4/1.10) on nearby curbs")
        if states["NETWORK_UNRELIABLE"]:
            out.append("Pedestrian network connectivity (footways, crossings, entrances)")
        out.append("Measured pick-up/drop-off counts (passenger_activity) — demand is not inferred from POIs")
        return out

    @staticmethod
    def _task_why(states, recs, factors):
        parts = [f"{len(recs)} mapped destinations (OSM proxies, not demand)"]
        if factors["transit_hub"]:
            parts.append("includes a transit hub")
        if states["INVENTORY_UNKNOWN"]:
            parts.append(f"{states['INVENTORY_UNKNOWN']} have no verified zone within the threshold, "
                         "but the inventory is incomplete")
        if states["POTENTIAL_COVERAGE_GAP"]:
            parts.append(f"{states['POTENTIAL_COVERAGE_GAP']} potential coverage gaps")
        if states["NETWORK_UNRELIABLE"]:
            parts.append(f"{states['NETWORK_UNRELIABLE']} poorly connected to the walking network")
        return "; ".join(parts) + "."

    # ------------------------------------------------------------ candidates
    def _candidates(self, gap_cells, threshold_m):
        """Investigation sites for supported gaps only. Proposals, never legal stops."""
        out, no_candidate = [], []
        for (cx, cy), recs in gap_cells:
            gap = [r for r in recs if r["state"] == "POTENTIAL_COVERAGE_GAP"]
            sources = {}
            for r in gap:
                for node, d in (self._snap(to_m_point(r["lon"], r["lat"])) or {}).items():
                    sources[node] = min(sources.get(node, math.inf), d)
            if not sources:
                no_candidate.append(f"survey-{cx}-{cy}")
                continue
            reach = threshold_m * 1.5
            dist, _ = dijkstra(self.m.walk_adj, sources, cutoff=reach)
            current = [r["distance_m"] if r["distance_m"] is not None else 2 * threshold_m for r in gap]
            cur_avg = sum(min(c, 2 * threshold_m) for c in current) / len(current)
            options, exclusions = [], defaultdict(int)
            for seg in self.m.segments.values():
                w = self.m.ways[seg["way_id"]]
                pos = (seg["start_m"] + seg["end_m"]) / 2
                i = w.edge_index(pos)
                d = min(dist.get(w.nodes[i], math.inf) + abs(pos - w.cum[i]),
                        dist.get(w.nodes[i + 1], math.inf) + abs(w.cum[i + 1] - pos))
                if d > reach:
                    continue
                if seg["official"]:
                    continue  # already an official zone
                if any(st == PROHIBITED for st in seg["status_by_vehicle"].values()):
                    exclusions["statutory prohibition"] += 1
                    continue
                if seg["length_m"] < CANDIDATE_MIN_LEN_M:
                    exclusions["curb piece too short"] += 1
                    continue
                pt = w.curb_point(pos, seg["side"])
                straight = min(pt.distance(to_m_point(r["lon"], r["lat"])) for r in gap) or 1
                cautions = [c["rule"] for c in seg["cautions"]]
                screened = seg["status"] == ALLOWED
                factors = {
                    "walk_access_improvement": max(0.0, min(1.0, (cur_avg - d) / threshold_m)),
                    "known_feasibility": 1.0 if screened else None,
                    "pedestrian_connectivity": max(0.0, min(1.0, straight / max(d, 1))),
                    "vehicle_curb_practicality": min(1.0, seg["length_m"] / 30),
                    "evidence_completeness": 1.0 if seg["last_verified"] else None,
                }
                score, _, missing = _weighted(factors, CANDIDATE_WEIGHTS) if screened else (None, None, None)
                options.append({
                    "id": _stable_id("cand", seg["id"]), "type": "candidate", "segment_id": seg["id"],
                    "candidate_class": "SCREENED_FOR_FURTHER_STUDY" if screened else "DATA_COLLECTION_NEEDED",
                    "geometry": {"type": "LineString", "coordinates": seg["coords"]}, "point": to_ll_coords([(pt.x, pt.y)])[0],
                    "street": seg["name"], "road_side": seg["side"], "compass": seg["compass"],
                    "length_m": seg["length_m"], "current_legal_status": seg["status"], "officially_approved": False,
                    "coverage_finding": "POTENTIAL_COVERAGE_GAP", "measured_taxi_demand_available": bool(self.activity),
                    "walk_distance_to_gap_m": round(d), "current_avg_walk_to_verified_m": round(cur_avg),
                    "factors": factors, "factors_missing": missing if screened else sorted(
                        k for k, v in factors.items() if v is None),
                    "score": score, "cluster": f"survey-{cx}-{cy}",
                    "missing_evidence": [] if screened else ["Field survey of this curb"] + cautions,
                    "why": (f"Serves {len(gap)} destinations in a potential coverage gap; {round(d)} m walk vs "
                            f"{round(cur_avg)} m to the nearest verified zone today."),
                    "requires": ["Official field / traffic-engineering / legal assessment",
                                 "Possible new signs (5.14 or designated stop) — not legally permitted today"],
                    "exclusions_in_cluster": None,
                })
            options.sort(key=lambda o: (o["candidate_class"] != "SCREENED_FOR_FURTHER_STUDY",
                                        -(o["score"] or 0), o["walk_distance_to_gap_m"]))
            chosen = []
            for o in options:
                p = to_m_point(*o["point"])
                if all(p.distance(to_m_point(*c["point"])) >= CANDIDATE_SPACING_M for c in chosen):
                    o["exclusions_in_cluster"] = dict(exclusions)
                    chosen.append(o)
                if len(chosen) == MAX_CANDIDATES_PER_CLUSTER:
                    break
            if not chosen:
                no_candidate.append(f"survey-{cx}-{cy}")
            out += chosen
        screened = sorted((c for c in out if c["score"] is not None), key=lambda c: -c["score"])
        for i, c in enumerate(screened, 1):
            c["rank"] = i
        for c in out:
            c.setdefault("rank", None)
        return out, no_candidate


def attach_reviews(result: dict, reviews: list[dict]):
    """Latest planner review per stable target id + history (recomputing never erases decisions)."""
    by_target = defaultdict(list)
    for r in reviews:
        by_target[r["target_id"]].append(r)
    for item in result["survey_tasks"] + result["candidates"]:
        hist = by_target.get(item["id"], [])
        item["review"] = hist[0] if hist else None
        item["review_history"] = hist
    return result


__all__ = ["Planner", "attach_reviews", "ALGORITHM_VERSION", "DEFAULT_THRESHOLD_M"]

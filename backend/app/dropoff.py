"""Smart drop-off / pickup recommendation and driver "where can I stop" search.

Order of operations follows the spec: candidate generation -> legal filter
(VERIFIED only) -> vehicle accessibility (correct direction of travel) ->
pedestrian routing -> safety checks -> ranking -> at most 3 alternatives.
Everything is deterministic shortest-path maths; no AI.
"""
from __future__ import annotations

import heapq
import math
from itertools import pairwise

from shapely.geometry import Point

from . import config as C
from .citymodel import PROHIBITED, UNKNOWN, VERIFIED, CityModel, to_ll_coords, to_m_point

WALK_SPEED = 1.3  # m/s
SAFE_CROSSING_SEARCH_M = 120
UNSAFE_CROSSING_PENALTY_M = 400
OFFICIAL_BONUS_M = 40


def dijkstra(adj, sources: dict, cutoff=math.inf, weight_index=1):
    """Multi-source Dijkstra. sources: node -> initial cost."""
    dist, prev = {}, {}
    pq = [(c, n) for n, c in sources.items()]
    heapq.heapify(pq)
    best = dict(sources)
    while pq:
        d, u = heapq.heappop(pq)
        if u in dist:
            continue
        dist[u] = d
        if d > cutoff:
            break
        for e in adj.get(u, ()):
            v, w = e[0], e[weight_index]
            nd = d + w
            if nd < best.get(v, math.inf):
                best[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev


def path_to(prev, node, sources=None):
    """Node sequence from the source tree root to `node`."""
    out = [node]
    while out[-1] in prev:
        out.append(prev[out[-1]])
    return out[::-1]


class Recommender:
    def __init__(self, model: CityModel):
        self.m = model

    # ---------------------------------------------------------------- snaps
    def _snap_drive(self, pt: Point):
        idx, dist = self.m.drive_edge_tree.query_nearest(pt, max_distance=150, return_distance=True)
        if len(idx) == 0:
            return None
        j = int(idx[0])
        way_id, i = self.m.drive_edge_meta[j]
        w = self.m.drive_ways[way_id]
        a, b = w.nodes[i], w.nodes[i + 1]
        seg = self.m.drive_edge_geoms[j]
        t = seg.project(pt)
        L = seg.length
        sp = w.speed()
        sources = {}
        if (a, b) in self.m.drive_edges:
            sources[b] = (L - t) / sp
        if (b, a) in self.m.drive_edges:
            sources[a] = min(sources.get(a, math.inf), t / sp)
        snapped = seg.interpolate(t)
        return {"sources": sources, "snapped": snapped, "dist": float(dist[0]), "way": w, "edge_idx": i, "t": t, "L": L}

    def _snap_walk(self, pt: Point):
        idx, dist = self.m.walk_edge_tree.query_nearest(pt, max_distance=250, return_distance=True)
        if len(idx) == 0:
            return None
        j = int(idx[0])
        a, b, L, _ = self.m.walk_edge_meta[j]
        seg = self.m.walk_edge_geoms[j]
        t = seg.project(pt)
        access = float(dist[0])
        return {"sources": {a: access + t, b: access + (L - t)}, "snapped": seg.interpolate(t), "access": access}

    # ------------------------------------------------------------ candidates
    def _candidates(self, center: Point, radius: float, prefer="nearest_to_center"):
        out = []
        for seg in self.m.segments.values():
            if seg["status"] != VERIFIED or seg["length_m"] < C.MIN_STOP_LENGTH_M:
                continue
            w = self.m.ways[seg["way_id"]]
            a, b = seg["start_m"] + 3.5, seg["end_m"] - 3.5
            if prefer == "nearest_to_center":
                pos = min(max(w.line.project(center), a), b)
            else:  # first legal spot in direction of travel
                pos = a if seg["travel"] == "fwd" else b
            cp = w.curb_point(pos, seg["side"])
            d = cp.distance(center)
            if d <= radius:
                out.append({"seg": seg, "way": w, "pos": pos, "pt": cp, "air": d})
        return out

    def _arrival(self, cand, ddist, snap=None):
        """Driving cost to reach the candidate travelling in the legal direction."""
        w, pos, seg = cand["way"], cand["pos"], cand["seg"]
        i = w.edge_index(pos)
        sp = w.speed()
        if seg["travel"] == "fwd":
            a, b, along = w.nodes[i], w.nodes[i + 1], pos - w.cum[i]
        else:
            a, b, along = w.nodes[i + 1], w.nodes[i], w.cum[i + 1] - pos
        if (a, b) not in self.m.drive_edges:
            return None
        # Driver is already on this edge, behind the spot: drive straight to it.
        if snap and snap["way"].id == w.id and snap["edge_idx"] == i:
            t_from_a = snap["t"] if seg["travel"] == "fwd" else snap["L"] - snap["t"]
            if t_from_a <= along + 0.5:
                return {"node": None, "direct": True, "seconds": max(0.0, along - t_from_a) / sp}
        if a not in ddist:
            return None
        return {"node": a, "seconds": ddist[a] + along / sp}

    def _drive_path(self, cand, arr, prev, snap, origin_pt):
        coords = [(origin_pt.x, origin_pt.y), (snap["snapped"].x, snap["snapped"].y)]
        if not arr.get("direct"):
            coords += [self.m.xy[n] for n in path_to(prev, arr["node"])]
        w = cand["way"]
        end_center = w.line.interpolate(cand["pos"])
        coords.append((end_center.x, end_center.y))
        coords.append((cand["pt"].x, cand["pt"].y))
        metres = sum(math.dist(p, q) for p, q in pairwise(coords[1:]))
        return to_ll_coords(coords), metres

    def _walk_to(self, cand, wdist):
        w, pos = cand["way"], cand["pos"]
        i = w.edge_index(pos)
        na, nb = w.nodes[i], w.nodes[i + 1]
        opts = []
        if na in wdist:
            opts.append((wdist[na] + (pos - w.cum[i]), na))
        if nb in wdist:
            opts.append((wdist[nb] + (w.cum[i + 1] - pos), nb))
        if not opts:
            return None, None
        d, node = min(opts)
        return d + w.width / 2, node

    def _walk_path(self, cand, node, wprev, wsnap, dest_pt):
        nodes = path_to(wprev, node, wsnap["sources"])[::-1]  # candidate side -> destination
        w = cand["way"]
        center = w.line.interpolate(cand["pos"])
        coords = [(cand["pt"].x, cand["pt"].y), (center.x, center.y)]
        coords += [self.m.xy[n] for n in nodes]
        coords += [(wsnap["snapped"].x, wsnap["snapped"].y), (dest_pt.x, dest_pt.y)]
        return to_ll_coords(coords)

    def _crossing_check(self, cand, dest_pt):
        """Does the passenger have to cross the street the car stops on?"""
        w, seg = cand["way"], cand["seg"]
        dw, dd = self.m.nearest_curb_way(dest_pt, 45)
        if dw is None or (dw.id != w.id and (not w.name or dw.name != w.name)):
            return {"must_cross": False}
        dest_side = dw.side_of(dest_pt)
        same_side = dest_side == seg["side"] if dw.id == w.id else None
        if same_side is None:
            # parallel carriageway of a dual road with the same name: always a crossing
            same_side = False
        if same_side:
            return {"must_cross": False}
        positions = sorted(p for n, ps in w.node_pos.items() if n in self.m.crossing_nodes for p in ps)
        if positions:
            near = min(positions, key=lambda p: abs(p - cand["pos"]))
            if abs(near - cand["pos"]) <= SAFE_CROSSING_SEARCH_M:
                return {"must_cross": True, "safe_crossing": True, "crossing_distance_m": round(abs(near - cand["pos"])),
                        "penalty_m": abs(near - cand["pos"]) * 0.5 + 20}
        return {"must_cross": True, "safe_crossing": False, "penalty_m": UNSAFE_CROSSING_PENALTY_M}

    def _diverse(self, ranked, k=3, min_sep=35):
        chosen = []
        for c in ranked:
            if all(c["pt"].distance(o["pt"]) >= min_sep for o in chosen):
                chosen.append(c)
            if len(chosen) == k:
                break
        return chosen

    def _curb_at_door(self, dest_pt):
        w, d = self.m.nearest_curb_way(dest_pt, 60)
        if not w:
            return None
        side = w.side_of(dest_pt)
        pos = w.line.project(dest_pt)
        for seg in self.m.segments_by_way.get((w.id, side), []):
            if seg["start_m"] <= pos <= seg["end_m"]:
                return {"segment_id": seg["id"], "status": seg["status"], "name": seg["name"], "side": side,
                        "compass": seg["compass"],
                        "reasons": [{"rule": r["rule"], "legal_ref": r["legal_ref"], "source_ref": r["source_ref"],
                                     "detail": r["detail"]} for r in seg["reasons"]],
                        "distance_m": round(d)}
        return None

    # ------------------------------------------------------------- public
    def recommend(self, dest_lonlat, origin_lonlat=None, mode="dropoff", max_walk_m=450, k=3):
        dest = to_m_point(*dest_lonlat)
        origin = to_m_point(*origin_lonlat) if origin_lonlat else None
        cands = self._candidates(dest, max_walk_m)
        considered = len(cands)

        wsnap = self._snap_walk(dest)
        if not wsnap:
            return self._empty("destination_outside_network", dest)
        wdist, wprev = dijkstra(self.m.walk_adj, wsnap["sources"], cutoff=max_walk_m * 1.6)

        dsnap = ddist = dprev = None
        warnings = []
        if origin is not None:
            dsnap = self._snap_drive(origin)
            if dsnap and dsnap["sources"]:
                ddist, dprev = dijkstra(self.m.drive_adj, dsnap["sources"])
            else:
                warnings.append("origin_outside_network")

        scored, unreachable = [], 0
        for c in cands:
            walk_m, wnode = self._walk_to(c, wdist)
            if walk_m is None or walk_m > max_walk_m * 1.25:
                continue
            arr = None
            if ddist is not None:
                arr = self._arrival(c, ddist, dsnap)
                if arr is None:
                    unreachable += 1
                    continue
            cross = self._crossing_check(c, dest)
            score = walk_m + cross.get("penalty_m", 0)
            if arr:
                score += arr["seconds"] * 1.2
            if c["seg"]["official"]:
                score -= OFFICIAL_BONUS_M
            c.update(walk_m=walk_m, wnode=wnode, arr=arr, cross=cross, score=score)
            scored.append(c)
        scored.sort(key=lambda c: c["score"])
        best = self._diverse(scored, k)

        results = []
        for rank, c in enumerate(best, 1):
            seg = c["seg"]
            lon, lat = to_ll_coords([(c["pt"].x, c["pt"].y)])[0]
            item = {
                "rank": rank,
                "point": [lon, lat],
                "segment_id": seg["id"],
                "street": seg["name"],
                "side": seg["side"],
                "compass": c["way"].compass(c["pos"], seg["side"]),
                "status": seg["status"],
                "official": seg["official"],
                "confidence": seg["confidence"],
                "walk_m": round(c["walk_m"]),
                "walk_min": round(c["walk_m"] / WALK_SPEED / 60, 1),
                "walk_route": self._walk_path(c, c["wnode"], wprev, wsnap, dest),
                "crossing": c["cross"],
                "score": round(c["score"], 1),
                "notes": [n["rule"] for n in seg["notes"]],
                "approach": "with_way" if seg["travel"] == "fwd" else "against_way",
            }
            if c["arr"]:
                coords, metres = self._drive_path(c, c["arr"], dprev, dsnap, origin)
                item.update(drive_route=coords, drive_m=round(metres), drive_min=round(c["arr"]["seconds"] / 60, 1))
            results.append(item)

        return {
            "mode": mode,
            "destination": dest_lonlat,
            "origin": origin_lonlat,
            "results": results,
            "curb_at_door": self._curb_at_door(dest),
            "diagnostics": {"candidates_in_radius": considered, "unreachable_by_car": unreachable,
                            "ranked": len(scored), "max_walk_m": max_walk_m},
            "message": None if results else "no_verified_spot",
            "warnings": warnings,
        }

    def nearest_stops(self, origin_lonlat, radius_m=1200, k=3):
        """Driver mode: closest legal stops reachable from the driver's position."""
        origin = to_m_point(*origin_lonlat)
        dsnap = self._snap_drive(origin)
        if not dsnap or not dsnap["sources"]:
            return {"origin": origin_lonlat, "results": [], "message": "origin_outside_network"}
        ddist, dprev = dijkstra(self.m.drive_adj, dsnap["sources"])
        cands = self._candidates(origin, radius_m, prefer="first_in_travel")
        scored = []
        for c in cands:
            arr = self._arrival(c, ddist, dsnap)
            if arr is None:
                continue
            c["arr"] = arr
            c["score"] = arr["seconds"] - (OFFICIAL_BONUS_M / 8 if c["seg"]["official"] else 0)
            scored.append(c)
        scored.sort(key=lambda c: c["score"])
        results = []
        for rank, c in enumerate(self._diverse(scored, k, 50), 1):
            seg = c["seg"]
            coords, metres = self._drive_path(c, c["arr"], dprev, dsnap, origin)
            results.append({
                "rank": rank, "point": to_ll_coords([(c["pt"].x, c["pt"].y)])[0], "segment_id": seg["id"],
                "street": seg["name"], "side": seg["side"], "compass": c["way"].compass(c["pos"], seg["side"]),
                "status": seg["status"], "official": seg["official"],
                "confidence": seg["confidence"], "drive_route": coords, "drive_m": round(metres),
                "drive_min": round(c["arr"]["seconds"] / 60, 1), "length_m": seg["length_m"],
                "notes": [n["rule"] for n in seg["notes"]],
            })
        return {"origin": origin_lonlat, "results": results,
                "message": None if results else "no_verified_spot"}

    def _empty(self, msg, dest):
        return {"results": [], "message": msg, "curb_at_door": self._curb_at_door(dest), "diagnostics": {}}


__all__ = ["Recommender", "PROHIBITED", "UNKNOWN", "VERIFIED"]

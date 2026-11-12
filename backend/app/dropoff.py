"""Smart drop-off / pickup recommendation and driver "where can I stop" search.

Order of operations follows the spec: candidate generation -> legal filter
(GREEN = confirmed; YELLOW = separately labelled, never "confirmed") -> vehicle accessibility (correct direction of travel) ->
pedestrian routing -> safety checks -> ranking -> at most 3 alternatives.
Everything is deterministic shortest-path maths; no AI.
"""
from __future__ import annotations

import heapq
import math
from itertools import pairwise

from shapely.geometry import Point

from . import config as C
from .citymodel import ALLOWED, PROHIBITED, UNVERIFIED, CityModel, to_ll_coords, to_m_point

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
    def _candidates(self, center: Point, radius: float, vehicle: str, status: str, prefer="nearest_to_center"):
        out = []
        for seg in self.m.segments.values():
            if seg["status_by_vehicle"][vehicle] != status or seg["length_m"] < C.MIN_STOP_LENGTH_M:
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

    def _curb_at_door(self, dest_pt, vehicle):
        w, d = self.m.nearest_curb_way(dest_pt, 60)
        if not w:
            return None
        side = w.side_of(dest_pt)
        pos = w.line.project(dest_pt)
        for seg in self.m.segments_by_way.get((w.id, side), []):
            if seg["start_m"] <= pos <= seg["end_m"]:
                return {"segment_id": seg["id"], "name": seg["name"], "side": side, "compass": seg["compass"],
                        "distance_m": round(d), **evidence(seg, vehicle)}
        return None

    def _score_dropoff(self, cands, dest, wdist, max_walk_m, ddist, dsnap):
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
            # unverified candidates: each specific caution (beyond "not surveyed") pushes it down
            score += 60 * sum(r["rule"] != "NOT_SURVEYED" for r in c["seg"]["cautions"])
            c.update(walk_m=walk_m, wnode=wnode, arr=arr, cross=cross, score=score)
            scored.append(c)
        scored.sort(key=lambda c: c["score"])
        return scored, unreachable

    def _item(self, rank, c, vehicle, extra):
        seg = c["seg"]
        return {"rank": rank, "point": to_ll_coords([(c["pt"].x, c["pt"].y)])[0], "segment_id": seg["id"],
                "street": seg["name"], "side": seg["side"], "compass": c["way"].compass(c["pos"], seg["side"]),
                "official": seg["official"], "length_m": seg["length_m"],
                "approach": "with_way" if seg["travel"] == "fwd" else "against_way",
                **evidence(seg, vehicle), **extra}

    # ------------------------------------------------------------- public
    def recommend(self, dest_lonlat, origin_lonlat=None, mode="dropoff", max_walk_m=450, k=3, vehicle=None):
        """Confirmed spots come only from GREEN curbs. YELLOW curbs (no known prohibition, but not verified)
        are returned separately as `unverified_candidates` and are never presented as legally confirmed."""
        vehicle = vehicle or C.DEFAULT_VEHICLE
        dest = to_m_point(*dest_lonlat)
        origin = to_m_point(*origin_lonlat) if origin_lonlat else None
        green = self._candidates(dest, max_walk_m, vehicle, ALLOWED)
        yellow = self._candidates(dest, max_walk_m, vehicle, UNVERIFIED)

        wsnap = self._snap_walk(dest)
        if not wsnap:
            return self._empty("destination_outside_network", dest, vehicle)
        wdist, wprev = dijkstra(self.m.walk_adj, wsnap["sources"], cutoff=max_walk_m * 1.6)

        dsnap = ddist = dprev = None
        warnings = []
        if origin is not None:
            dsnap = self._snap_drive(origin)
            if dsnap and dsnap["sources"]:
                ddist, dprev = dijkstra(self.m.drive_adj, dsnap["sources"])
            else:
                warnings.append("origin_outside_network")

        def build(scored, kk, avoid=()):
            out = []
            chosen = self._diverse([c for c in scored if all(c["pt"].distance(o["pt"]) >= 35 for o in avoid)], kk)
            for rank, c in enumerate(chosen, 1):
                extra = {"walk_m": round(c["walk_m"]), "walk_min": round(c["walk_m"] / WALK_SPEED / 60, 1),
                         "walk_route": self._walk_path(c, c["wnode"], wprev, wsnap, dest), "crossing": c["cross"],
                         "score": round(c["score"], 1)}
                if c["arr"]:
                    coords, metres = self._drive_path(c, c["arr"], dprev, dsnap, origin)
                    extra.update(drive_route=coords, drive_m=round(metres), drive_min=round(c["arr"]["seconds"] / 60, 1))
                out.append(self._item(rank, c, vehicle, extra))
            return out, chosen

        g_scored, g_unreach = self._score_dropoff(green, dest, wdist, max_walk_m, ddist, dsnap)
        y_scored, y_unreach = self._score_dropoff(yellow, dest, wdist, max_walk_m, ddist, dsnap)
        results, chosen = build(g_scored, k)
        unverified, _ = build(y_scored, k, chosen)
        return {
            "mode": mode, "vehicle": vehicle, "destination": dest_lonlat, "origin": origin_lonlat,
            "results": results,
            "unverified_candidates": unverified,
            "curb_at_door": self._curb_at_door(dest, vehicle),
            "diagnostics": {"confirmed_candidates": len(green), "unverified_candidates": len(yellow),
                            "candidates_in_radius": len(green), "ranked": len(g_scored),
                            "unreachable_by_car": g_unreach + y_unreach, "max_walk_m": max_walk_m},
            "message": None if results else "no_verified_spot",
            "warnings": warnings,
        }

    def nearest_stops(self, origin_lonlat, radius_m=1200, k=3, vehicle=None):
        """Driver mode: closest confirmed (GREEN) stops reachable from the driver's position, plus
        separately labelled unverified (YELLOW) options."""
        vehicle = vehicle or C.DEFAULT_VEHICLE
        origin = to_m_point(*origin_lonlat)
        dsnap = self._snap_drive(origin)
        if not dsnap or not dsnap["sources"]:
            return {"origin": origin_lonlat, "results": [], "unverified_candidates": [], "message": "origin_outside_network"}
        ddist, dprev = dijkstra(self.m.drive_adj, dsnap["sources"])

        def rank(status, avoid=()):
            scored = []
            for c in self._candidates(origin, radius_m, vehicle, status, prefer="first_in_travel"):
                arr = self._arrival(c, ddist, dsnap)
                if arr is None or any(c["pt"].distance(o["pt"]) < 50 for o in avoid):
                    continue
                c["arr"] = arr
                c["score"] = arr["seconds"] - (OFFICIAL_BONUS_M / 8 if c["seg"]["official"] else 0) \
                    + 8 * sum(r["rule"] != "NOT_SURVEYED" for r in c["seg"]["cautions"])
                scored.append(c)
            scored.sort(key=lambda c: c["score"])
            chosen = self._diverse(scored, k, 50)
            items = []
            for i, c in enumerate(chosen, 1):
                coords, metres = self._drive_path(c, c["arr"], dprev, dsnap, origin)
                items.append(self._item(i, c, vehicle, {"drive_route": coords, "drive_m": round(metres),
                                                        "drive_min": round(c["arr"]["seconds"] / 60, 1)}))
            return items, chosen

        results, chosen = rank(ALLOWED)
        unverified, _ = rank(UNVERIFIED, chosen)
        return {"origin": origin_lonlat, "vehicle": vehicle, "results": results, "unverified_candidates": unverified,
                "message": None if results else "no_verified_spot"}

    def _empty(self, msg, dest, vehicle):
        return {"results": [], "unverified_candidates": [], "message": msg,
                "curb_at_door": self._curb_at_door(dest, vehicle), "diagnostics": {}}


def evidence(seg, vehicle):
    """Status + the legal basis and provenance behind it, attached to every recommendation."""
    def brief(r):
        return {"rule": r["rule"], "effect": r["effect"], "legal_ref": r["legal_ref"], "verification": r["verification"],
                "source": r["source"], "source_ref": r["source_ref"], "exempt": r.get("exempt", [])}
    status = seg["status_by_vehicle"][vehicle]
    applicable = [r for r in seg["reasons"] if vehicle not in r.get("exempt", [])]
    return {
        "status": status,
        "legally_confirmed": status == ALLOWED,
        "reasons": [brief(r) for r in applicable],
        "cautions": [brief(r) for r in seg["cautions"]],
        "notes": [n["rule"] for n in seg["notes"]],
        "note_details": [brief(n) for n in seg["notes"]],
        "sources": seg["sources"],
        "coverage": seg["coverage"],
        "last_verified": seg["last_verified"],
        "confidence": seg["confidence"] if status == seg["status"] else
        ("verified_observation" if status == ALLOWED else "rule_verified_text" if status == PROHIBITED
         else "insufficient_or_conflicting_data"),
    }


__all__ = ["Recommender", "evidence", "PROHIBITED", "ALLOWED", "UNVERIFIED"]

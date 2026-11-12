"""City model: OSM -> road graph -> curb segments -> legal status.

Pipeline (all deterministic, no AI):
  1. Parse raw OSM (Overpass JSON) and project to a metric CRS.
  2. Build drivable ways; each way has two curbs ("right"/"left" relative to
     the way's digitised direction, normalised so oneway roads point with traffic).
  3. Rule engine: for every way-side collect prohibition intervals in linear
     metres along the way (crossings, intersections, bus stops, bus lanes,
     bridges, signs, markings...). Each interval keeps its rule id + source.
  4. Split each curb at every interval / coverage boundary -> curb segments.
     RED (PROHIBITED): a verified rule forbids stopping (dayanma) for the vehicle class.
     GREEN (ALLOWED): no prohibition, no caution, AND the curb is covered by a reviewed
       field survey or an official zone.
     YELLOW (UNVERIFIED): anything else — incomplete, unverified or conflicting data.
     Missing sign data never produces GREEN.
  5. Build directed drive graph and undirected walk graph for routing.
"""
from __future__ import annotations

import json
import math
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import pairwise

from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import substring

from . import config as C
from .rules import RULES, RULESET_VERSION, VEHICLE_CLASSES

TO_M = Transformer.from_crs("EPSG:4326", C.METRIC_CRS, always_xy=True)
TO_LL = Transformer.from_crs(C.METRIC_CRS, "EPSG:4326", always_xy=True)

PROHIBITED, ALLOWED, UNVERIFIED = "PROHIBITED", "ALLOWED", "UNVERIFIED"  # RED, GREEN, YELLOW
SIDES = ("right", "left")


def to_ll_coords(coords):
    xs, ys = zip(*coords, strict=True)
    lons, lats = TO_LL.transform(xs, ys)
    return [[round(lo, 7), round(la, 7)] for lo, la in zip(lons, lats, strict=True)]


def to_m_point(lon, lat):
    x, y = TO_M.transform(lon, lat)
    return Point(x, y)


def _num(v):
    try:
        return float(str(v).split(";")[0].replace(",", ".").replace("m", "").strip())
    except (TypeError, ValueError):
        return None


def norm_text(s: str) -> str:
    table = str.maketrans("əıöüşçğİƏÖÜŞÇĞ", "eiouscgieouscg")
    return (s or "").translate(table).lower().strip()


def is_bus_platform(t: dict) -> bool:
    """Bus/trolleybus platforms count for the 15 m rule; rail, metro and tram platforms do not."""
    if t.get("bus") == "yes" or t.get("trolleybus") == "yes" or t.get("highway") in ("bus_stop", "platform"):
        return True
    if t.get("railway") or any(t.get(k) == "yes" for k in ("train", "subway", "tram", "light_rail", "monorail")):
        return False
    return True


def flip(side: str) -> str:
    return "left" if side == "right" else "right"


PROHIBITING_KINDS = {"sign_3_27", "marking_1_4", "taxi_stand", "observed_prohibition"}


def feature_prohibits(f) -> bool:
    """Would this observation (once verified) restrict stopping? Used to flag pending observations."""
    if f["kind"] == "bus_lane":
        return (f.get("props") or {}).get("line_type") != "dashed"
    return f["kind"] in PROHIBITING_KINDS


@dataclass
class Way:
    id: int
    tags: dict
    nodes: list
    line: LineString
    cum: list
    highway: str
    oneway: bool
    width: float
    name: str
    node_pos: dict = field(default_factory=dict)

    @property
    def length(self):
        return self.cum[-1]

    def travel(self, side):
        """Direction of traffic along the curb: 'fwd' = digitised direction."""
        return "fwd" if (side == "right" or self.oneway) else "bwd"

    def speed(self):
        return C.SPEED_KMH.get(self.highway.replace("_link", ""), 20) / 3.6

    def edge_index(self, pos):
        i = bisect_right(self.cum, pos) - 1
        return max(0, min(i, len(self.cum) - 2))

    def side_of(self, pt: Point) -> str:
        pos = self.line.project(pt)
        a = self.line.interpolate(max(0.0, pos - 1.0))
        b = self.line.interpolate(min(self.length, pos + 1.0))
        cross = (b.x - a.x) * (pt.y - a.y) - (b.y - a.y) * (pt.x - a.x)
        return "left" if cross > 0 else "right"

    def compass(self, pos, side):
        """Which side of the street the curb is on, as an 8-point compass label."""
        a = self.line.interpolate(max(0.0, pos - 2.0))
        b = self.line.interpolate(min(self.length, pos + 2.0))
        dx, dy = b.x - a.x, b.y - a.y
        nx, ny = (-dy, dx) if side == "left" else (dy, -dx)
        ang = (math.degrees(math.atan2(nx, ny)) + 360) % 360  # 0 = north, clockwise
        return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((ang + 22.5) // 45) % 8]

    def curb_point(self, pos, side):
        pos = max(0.0, min(self.length, pos))
        p = self.line.interpolate(pos)
        a = self.line.interpolate(max(0.0, pos - 1.0))
        b = self.line.interpolate(min(self.length, pos + 1.0))
        dx, dy = b.x - a.x, b.y - a.y
        n = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n, dx / n  # left normal
        off = self.width / 2.0 * (1 if side == "left" else -1)
        return Point(p.x + nx * off, p.y + ny * off)


@dataclass
class Interval:
    start: float
    end: float
    rule: str
    source: str
    source_ref: str
    detail: dict = field(default_factory=dict)

    def covers(self, m):
        return self.start <= m < self.end


class CityModel:
    def __init__(self, raw: dict, features: list[dict]):
        self.raw = raw
        self.features = features
        self.osm_timestamp = (raw.get("osm3s") or {}).get("timestamp_osm_base")
        self.built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.bbox = raw.get("bbox")
        self._parse()
        self._build_ways()
        self._build_graphs()
        self._collect_points()
        self._apply_rules()
        self._segment()
        self._build_search()

    # ------------------------------------------------------------------ parse
    def _parse(self):
        self.nodes, self.raw_ways = {}, []
        for el in self.raw["elements"]:
            if el["type"] == "node":
                self.nodes[el["id"]] = el
            elif el["type"] == "way":
                self.raw_ways.append(el)
        ids = list(self.nodes)
        xs, ys = TO_M.transform([self.nodes[i]["lon"] for i in ids], [self.nodes[i]["lat"] for i in ids])
        self.xy = {i: (x, y) for i, x, y in zip(ids, xs, ys, strict=True)}

    def _way_ok_for_drive(self, t):
        hw = t.get("highway")
        if hw not in C.DRIVE_HIGHWAYS or t.get("area") == "yes":
            return False
        if t.get("access") in ("private", "no") or t.get("motor_vehicle") in ("no", "private"):
            return False
        if hw == "service" and t.get("service") in C.EXCLUDED_SERVICE:
            return False
        return True

    def _width(self, t, oneway):
        w = _num(t.get("width"))
        if w and 2 < w < 60:
            return w
        lanes = _num(t.get("lanes"))
        if lanes and 0 < lanes < 12:
            return lanes * C.LANE_WIDTH
        base = C.DEFAULT_WIDTH.get(t.get("highway", "").replace("_link", ""), 7)
        if t.get("highway", "").endswith("_link"):
            base = 6
        return base * (0.6 if oneway else 1.0)

    def _build_ways(self):
        self.ways: dict[int, Way] = {}
        self.drive_ways: dict[int, Way] = {}
        for el in self.raw_ways:
            t = el.get("tags", {})
            if not self._way_ok_for_drive(t):
                continue
            nds = [n for n in el["nodes"] if n in self.xy]
            if len(nds) < 2:
                continue
            ow = t.get("oneway")
            oneway = ow in ("yes", "true", "1", "-1") or t.get("junction") in ("roundabout", "circular") \
                or t.get("highway") in ("motorway",)
            if ow == "-1":
                nds = nds[::-1]
            coords = [self.xy[n] for n in nds]
            line = LineString(coords)
            if line.length < 1:
                continue
            cum = [0.0]
            for a, b in pairwise(coords):
                cum.append(cum[-1] + math.dist(a, b))
            w = Way(el["id"], t, nds, line, cum, t["highway"], oneway, self._width(t, oneway),
                    t.get("name:az") or t.get("name") or t.get("name:en") or "")
            for i, n in enumerate(nds):
                w.node_pos.setdefault(n, []).append(cum[i])
            self.drive_ways[w.id] = w
            if t["highway"] in C.CURB_HIGHWAYS:
                self.ways[w.id] = w
        self.curb_list = list(self.ways.values())
        self.curb_tree = STRtree([w.line for w in self.curb_list])

        # Intersections: node degree >= 3 in the undirected graph of public roads.
        # Service roads (yards, parking exits) are "adjacent territories", not intersections.
        nbrs = defaultdict(set)
        for w in self.ways.values():
            for a, b in pairwise(w.nodes):
                nbrs[a].add(b)
                nbrs[b].add(a)
        self.intersections = {n for n, s in nbrs.items() if len(s) >= 3}
        self.curb_nbrs = nbrs
        # Nodes where a service road (yard / parking / driveway) meets a public road, not an intersection.
        self.driveway_nodes = defaultdict(list)
        curb_nodes = set(nbrs)
        for el in self.raw_ways:
            t = el.get("tags", {})
            if t.get("highway") != "service" or t.get("area") == "yes":
                continue
            nds = [n for n in el["nodes"] if n in self.xy]
            if len(nds) < 2:
                continue
            sw = self.drive_ways.get(el["id"])
            width = sw.width if sw else C.DEFAULT_WIDTH["service"] * 0.6
            ref = type("SW", (), {"id": el["id"], "nodes": nds, "width": width})
            for end in (nds[0], nds[-1]):
                if end in curb_nodes and end not in self.intersections:
                    self.driveway_nodes[end].append(ref)
        self.node_ways = defaultdict(set)
        for w in self.drive_ways.values():
            for n in w.nodes:
                self.node_ways[n].add(w.id)

    def nearest_curb_way(self, pt: Point, max_dist=40.0):
        idx, dist = self.curb_tree.query_nearest(pt, max_distance=max_dist, return_distance=True)
        if len(idx) == 0:
            return None, None
        j = int(idx[0])
        return self.curb_list[j], float(dist[0])

    # ----------------------------------------------------------------- graphs
    def _build_graphs(self):
        # Directed drive graph: node -> [(nbr, seconds, metres, way_id)]
        self.drive_adj = defaultdict(list)
        self.drive_edges = set()
        edge_geoms, self.drive_edge_meta = [], []
        for w in self.drive_ways.values():
            sp = w.speed()
            for i, (a, b) in enumerate(pairwise(w.nodes)):
                L = w.cum[i + 1] - w.cum[i]
                self.drive_adj[a].append((b, L / sp, L, w.id))
                self.drive_edges.add((a, b))
                if not w.oneway:
                    self.drive_adj[b].append((a, L / sp, L, w.id))
                    self.drive_edges.add((b, a))
                edge_geoms.append(LineString([self.xy[a], self.xy[b]]))
                self.drive_edge_meta.append((w.id, i))
        self.drive_edge_tree = STRtree(edge_geoms)
        self.drive_edge_geoms = edge_geoms

        # Undirected walk graph over every walkable highway
        self.walk_adj = defaultdict(list)
        wgeoms, self.walk_edge_meta = [], []
        for el in self.raw_ways:
            t = el.get("tags", {})
            hw = t.get("highway")
            if not hw or hw in C.NO_WALK_HIGHWAYS or t.get("foot") in ("no", "private") or t.get("area") == "yes":
                continue
            if t.get("access") in ("private", "no") and t.get("foot") not in ("yes", "designated"):
                continue
            nds = [n for n in el["nodes"] if n in self.xy]
            for a, b in pairwise(nds):
                L = math.dist(self.xy[a], self.xy[b])
                self.walk_adj[a].append((b, L))
                self.walk_adj[b].append((a, L))
                wgeoms.append(LineString([self.xy[a], self.xy[b]]))
                self.walk_edge_meta.append((a, b, L, hw))
        self.walk_edge_tree = STRtree(wgeoms)
        self.walk_edge_geoms = wgeoms

    # ---------------------------------------------------------- point objects
    def _collect_points(self):
        self.crossing_nodes, self.signal_nodes, self.level_crossings = set(), set(), set()
        footway_crossing_nodes = set()
        for el in self.raw_ways:
            t = el.get("tags", {})
            if t.get("footway") == "crossing" or t.get("path") == "crossing" or t.get("cycleway") == "crossing":
                footway_crossing_nodes.update(el["nodes"])
        road_nodes = set(self.node_ways)
        for nid, el in self.nodes.items():
            t = el.get("tags", {})
            if (t.get("highway") == "crossing" or ("crossing" in t and t.get("crossing") != "no")) and nid in road_nodes:
                self.crossing_nodes.add(nid)
            if t.get("highway") == "traffic_signals" and nid in road_nodes:
                self.signal_nodes.add(nid)
            if t.get("railway") == "level_crossing" and nid in road_nodes:
                self.level_crossings.add(nid)
        self.crossing_nodes |= (footway_crossing_nodes & road_nodes)

        # Bus stops: sign/platform positions beside the road (side matters).
        self.bus_stops = []
        for nid, el in self.nodes.items():
            t = el.get("tags", {})
            if t.get("highway") == "bus_stop" or (t.get("public_transport") == "platform" and is_bus_platform(t)):
                self.bus_stops.append({"ref": f"node/{nid}", "pt": Point(self.xy[nid]), "pts": [Point(self.xy[nid])],
                                       "on_road": nid in road_nodes,
                                       "name": t.get("name:az") or t.get("name") or "", "lonlat": [el["lon"], el["lat"]]})
        for el in self.raw_ways:
            t = el.get("tags", {})
            if (t.get("public_transport") == "platform" or t.get("highway") == "platform") and is_bus_platform(t):
                nds = [n for n in el["nodes"] if n in self.xy]
                if len(nds) >= 2:
                    c = LineString([self.xy[n] for n in nds]).centroid
                    lon, lat = TO_LL.transform(c.x, c.y)
                    self.bus_stops.append({"ref": f"way/{el['id']}", "pt": c, "pts": [Point(self.xy[n]) for n in nds],
                                           "on_road": False,
                                           "name": t.get("name") or "", "lonlat": [lon, lat]})

    # ------------------------------------------------------------ rule engine
    def _lanes_in_direction(self, w: Way, side: str):
        """Lane count for the traffic that uses this curb, or None if unknown."""
        t = w.tags
        if w.oneway:
            n = _num(t.get("lanes"))
            return int(n) if n else None
        key = "lanes:forward" if w.travel(side) == "fwd" else "lanes:backward"
        n = _num(t.get(key))
        if n:
            return int(n)
        total = _num(t.get("lanes"))
        if total and int(total) % 2 == 0:
            return int(total) // 2
        return None

    def _t_junction_branch(self, w: Way, k: int, nid: int):
        """If `nid` is a T-junction where w is the through road, return the side of w the branch is on."""
        nbrs = self.curb_nbrs.get(nid, set())
        if len(nbrs) != 3:
            return None
        own = {w.nodes[k - 1]} if k > 0 else set()
        if k < len(w.nodes) - 1:
            own.add(w.nodes[k + 1])
        if len(own) == 1 and w.name:
            # w ends here: the through road may continue on another way with the same name
            for oid in self.node_ways[nid]:
                o = self.ways.get(oid)
                if o is None or o.id == w.id or o.name != w.name:
                    continue
                for j, n in enumerate(o.nodes):
                    if n == nid:
                        own |= {o.nodes[x] for x in (j - 1, j + 1) if 0 <= x < len(o.nodes)}
        branch = nbrs - own
        if len(own) != 2 or len(branch) != 1:
            return None
        return w.side_of(Point(self.xy[next(iter(branch))]))

    def _apply_rules(self):
        iv = defaultdict(list)                 # (way_id, side) -> [Interval]
        self.coverage = defaultdict(list)      # (way_id, side) -> [(start, end, feature)]
        self.official = defaultdict(list)
        self.feature_matches = {}              # feature id -> [(way_id, side, start, end)]
        self.feature_errors = {}

        def add(w, side, a, b, rule, source, ref, **detail):
            a, b = max(0.0, a), min(w.length, b)
            if b - a > 0.05:
                iv[(w.id, side)].append(Interval(a, b, rule, source, ref, detail))

        P = {k: r.params for k, r in RULES.items()}
        for w in self.ways.values():
            t, ref = w.tags, f"way/{w.id}"
            whole = []
            if w.highway in ("motorway", "motorway_link"):
                whole.append("MOTORWAY")
            if t.get("junction") in ("roundabout", "circular"):
                whole.append("ROUNDABOUT")
            tunnel = t.get("tunnel", "no")
            if tunnel not in ("no", "culvert"):
                whole.append("TUNNEL_PASSAGE" if tunnel == "building_passage" else "TUNNEL")
            for side in SIDES:
                for rule in whole:
                    add(w, side, 0, w.length, rule, "osm", ref)
                if t.get("bridge", "no") != "no":
                    lanes = self._lanes_in_direction(w, side)
                    if lanes is None:
                        add(w, side, 0, w.length, "BRIDGE_LANES_UNKNOWN", "osm", ref)
                    elif lanes < P["BRIDGE"]["min_lanes_allowed"]:
                        add(w, side, 0, w.length, "BRIDGE", "osm", ref, lanes_in_direction=lanes)
                if w.oneway and side == "left":
                    add(w, side, 0, w.length, "ONE_WAY_LEFT_SIDE", "osm", ref)

            for k, nid in enumerate(w.nodes):
                pos = w.cum[k]
                nref = f"node/{nid}"
                if nid in self.crossing_nodes:
                    half = P["PEDESTRIAN_CROSSING"]["crossing_half_width_m"] + P["PEDESTRIAN_CROSSING"]["buffer_m"]
                    for side in SIDES:
                        add(w, side, pos - half, pos + half, "PEDESTRIAN_CROSSING", "osm", nref)
                if nid in self.intersections:
                    others = [self.drive_ways[o] for o in self.node_ways[nid] if o != w.id and o in self.ways]
                    half_other = max([o.width / 2 for o in others], default=w.width / 2)
                    r = half_other + P["INTERSECTION"]["edge_buffer_m"]
                    branch_side = self._t_junction_branch(w, k, nid)
                    for side in SIDES:
                        if branch_side is not None and side != branch_side:
                            # 52.IV.6 exception may apply opposite the side road (needs 1.1–1.4 line or divider)
                            add(w, side, pos - r, pos + r, "T_JUNCTION_EXCEPTION", "osm", nref,
                                crossed_half_width_m=round(half_other, 1))
                        else:
                            add(w, side, pos - r, pos + r, "INTERSECTION", "osm", nref,
                                crossed_half_width_m=round(half_other, 1))
                elif nid in self.driveway_nodes:
                    for sw in self.driveway_nodes[nid]:
                        other = next((n for n in sw.nodes if n != nid), None)
                        if other is None:
                            continue
                        side = w.side_of(Point(self.xy[other]))
                        half = sw.width / 2 + P["DRIVEWAY_BLOCKING"]["extra_m"]
                        add(w, side, pos - half, pos + half, "DRIVEWAY_BLOCKING", "osm", nref, service_way=f"way/{sw.id}")
                if nid in self.signal_nodes and nid not in self.crossing_nodes:
                    before = P["TRAFFIC_SIGNAL"]["before_m"]
                    for side in SIDES:
                        if w.travel(side) == "fwd":
                            add(w, side, pos - before, pos + 0.5, "TRAFFIC_SIGNAL", "osm", nref)
                        else:
                            add(w, side, pos - 0.5, pos + before, "TRAFFIC_SIGNAL", "osm", nref)
                if nid in self.level_crossings:
                    r = P["LEVEL_CROSSING"]["half_extent_m"]
                    for side in SIDES:
                        add(w, side, pos - r, pos + r, "LEVEL_CROSSING", "osm", nref)

            for side, rules in self._osm_way_tags(w).items():
                for rule in rules:
                    add(w, side, 0, w.length, rule, "osm", ref)

        # Under bridges / overpasses
        for bid, bl, bw, bnodes in self._bridge_lines():
            for j in self.curb_tree.query(bl, predicate="intersects"):
                w = self.curb_list[int(j)]
                if w.id == bid or set(w.nodes) & bnodes or w.tags.get("bridge", "no") != "no":
                    continue
                inter = w.line.intersection(bl)
                for p in getattr(inter, "geoms", [inter]):
                    if p.is_empty or p.geom_type != "Point":
                        continue
                    pos = w.line.project(p)
                    for side in SIDES:
                        add(w, side, pos - bw / 2 - 2, pos + bw / 2 + 2, "UNDER_BRIDGE", "osm", f"way/{bid}")

        # Bus stops: 15 m from the stop sign or from the ends of the platform, on the stop's side
        r = P["BUS_STOP"]["radius_m"]
        for bs in self.bus_stops:
            w, d = self.nearest_curb_way(bs["pt"], 35)
            if w is None:
                continue
            positions = [w.line.project(p) for p in bs["pts"]]
            lo, hi = min(positions), max(positions)
            sides = SIDES if (bs["on_road"] or d < 1.0) else (w.side_of(bs["pt"]),)
            for side in sides:  # overlapping sign + platform zones simply union
                add(w, side, lo - r, hi + r, "BUS_STOP", "osm", bs["ref"], name=bs["name"],
                    measured_from="platform" if len(bs["pts"]) > 1 else "stop_node")
            bs["way_id"], bs["pos"] = w.id, (lo + hi) / 2

        # Curated observations
        verified = [f for f in self.features if f["status"] == "verified"]
        pending = [f for f in self.features if f["status"] == "pending"]
        self._apply_verified_features(verified, add)
        for f in pending:
            if not feature_prohibits(f):
                continue
            try:
                for w, side, a, b in self.match_feature(f):
                    add(w, side, a, b, "PENDING_OBSERVATION", f["source"], f"feature/{f['id']}",
                        feature_id=f["id"], kind=f["kind"])
            except Exception as exc:  # noqa: BLE001
                self.feature_errors[f["id"]] = str(exc)
        self.intervals = iv

    def _bridge_lines(self):
        out = []
        for el in self.raw_ways:
            t = el.get("tags", {})
            if t.get("bridge", "no") != "no" and (t.get("highway") in C.DRIVE_HIGHWAYS or t.get("railway")):
                nds = [n for n in el["nodes"] if n in self.xy]
                if len(nds) >= 2:
                    bw = self._width(t, t.get("oneway") == "yes") if t.get("highway") else 6
                    out.append((el["id"], LineString([self.xy[n] for n in nds]), bw, set(nds)))
        return out

    def _apply_verified_features(self, features, add):
        """Apply reviewed observations, including the 3.27 + 1.4 / 3.28 + 1.10 pairing of Art. 64.VIII.3."""
        placed = {}
        for f in features:
            try:
                placed[f["id"]] = (f, self.match_feature(f))
            except Exception as exc:  # noqa: BLE001 - one bad row must not take the map down
                self.feature_errors[f["id"]] = str(exc)

        def sign_points(kind):
            out = []
            for f, matches in placed.values():
                if f["kind"] == kind and matches:
                    w, side, a, b = matches[0]
                    # sign position = start of its zone in the direction of traffic
                    out.append((f, w.id, side, a if w.travel(side) == "fwd" else b))
            return out

        signs = {"sign_3_27": sign_points("sign_3_27"), "sign_3_28": sign_points("sign_3_28")}
        paired_signs = set()
        pair_of = {"marking_1_4": ("sign_3_27", "MARKING_1_4", "MARKING_1_4_UNPAIRED"),
                   "marking_1_10": ("sign_3_28", "MARKING_1_10", "MARKING_1_10")}
        tol = 20.0
        for f, matches in placed.values():
            kind, ref = f["kind"], f"feature/{f['id']}"
            self.feature_matches[f["id"]] = [(w.id, s, a, b) for w, s, a, b in matches]
            meta = {"feature_id": f["id"], "verified_at": f.get("verified_at"), "kind": kind}
            if kind in pair_of:
                sign_kind, ok_rule, unpaired_rule = pair_of[kind]
                for w, side, a, b in matches:
                    partner = next((s for s in signs[sign_kind]
                                    if s[1] == w.id and s[2] == side and a - tol <= s[3] <= b + tol), None)
                    if partner:
                        paired_signs.add(partner[0]["id"])
                        add(w, side, a, b, ok_rule, f["source"], ref, paired_sign=partner[0]["id"], **meta)
                        # 64.VIII.3: with a paired line the sign's zone is the line's length
                        add(w, side, a, b, "SIGN_3_27" if sign_kind == "sign_3_27" else "SIGN_3_28",
                            partner[0]["source"], f"feature/{partner[0]['id']}", zone="paired_marking",
                            feature_id=partner[0]["id"], verified_at=partner[0].get("verified_at"), kind=sign_kind)
                    else:
                        add(w, side, a, b, unpaired_rule, f["source"], ref, **meta)
        for f, matches in placed.values():
            kind, ref = f["kind"], f"feature/{f['id']}"
            meta = {"feature_id": f["id"], "verified_at": f.get("verified_at"), "kind": kind}
            props = f.get("props") or {}
            for w, side, a, b in matches:
                a, b = max(0.0, a), min(w.length, b)
                if b - a < 0.05:
                    continue
                if kind == "survey_area":
                    self.coverage[(w.id, side)].append((a, b, f))
                elif kind == "official_zone":
                    self.official[(w.id, side)].append((a, b, f))
                    add(w, side, a, b, "OFFICIAL_ZONE", f["source"], ref, **meta)
                elif kind in ("sign_3_27", "sign_3_28") and f["id"] not in paired_signs:
                    add(w, side, a, b, "SIGN_3_27" if kind == "sign_3_27" else "SIGN_3_28", f["source"], ref,
                        zone=props.get("zone_mode", "to_next_intersection"), plate=props.get("plate"), **meta)
                elif kind == "bus_lane":
                    rule = {"solid": "BUS_LANE_SOLID", "dashed": "BUS_LANE_DASHED"}.get(props.get("line_type"),
                                                                                       "BUS_LANE_UNKNOWN_LINE")
                    add(w, side, a, b, rule, f["source"], ref, line_type=props.get("line_type", "unknown"), **meta)
                elif kind == "taxi_stand":
                    add(w, side, a, b, "TAXI_STAND", f["source"], ref, **meta)
                elif kind == "observed_prohibition":
                    add(w, side, a, b, "OBSERVED_PROHIBITION", f["source"], ref, clause=props.get("clause"), **meta)

    def _osm_way_tags(self, w: Way):
        """Bus lanes, bike lanes and stopping restrictions encoded on the way itself."""
        t, out = w.tags, defaultdict(set)

        def lane_last(v, rightmost=True):
            parts = (v or "").split("|")
            if parts == [""]:
                return False
            return (parts[-1] if rightmost else parts[0]) in ("designated", "yes", "lane")

        bus = defaultdict(bool)
        for side in SIDES:
            bw = t.get(f"busway:{side}") or t.get("busway:both") or (t.get("busway") if side == "right" or not w.oneway else None)
            if bw in ("lane", "share_busway"):
                bus[side] = True
        for key in ("bus:lanes", "psv:lanes"):
            if w.oneway:
                bus["right"] |= lane_last(t.get(key), True)
                bus["left"] |= lane_last(t.get(key), False)
            else:
                bus["right"] |= lane_last(t.get(f"{key}:forward"), True)
                bus["left"] |= lane_last(t.get(f"{key}:backward"), True)

        def n_bus(key):
            v = _num(t.get(key))
            return int(v) if v else 0
        if w.oneway:
            bus["right"] |= bool(n_bus("lanes:bus") or n_bus("lanes:psv"))
        else:
            bus["right"] |= bool(n_bus("lanes:bus:forward") or n_bus("lanes:psv:forward"))
            bus["left"] |= bool(n_bus("lanes:bus:backward") or n_bus("lanes:psv:backward"))
            if n_bus("lanes:bus") >= 1 and not any(k.startswith(("lanes:bus:", "bus:lanes")) for k in t):
                bus["right"] = bus["left"] = True  # direction not given: both curbs
        for side in SIDES:
            if bus[side]:
                # 48.IV: legality of a drop-off depends on the separating line (dashed/solid), unknown in OSM
                out[side].add("BUS_LANE_UNKNOWN_LINE")
            cyc = t.get(f"cycleway:{side}") or t.get("cycleway:both") or \
                (t.get("cycleway") if side == "right" or not w.oneway else None)
            if cyc == "lane":
                out[side].add("BIKE_LANE")
            vals = {t.get(f"parking:{side}:restriction"), t.get("parking:both:restriction"),
                    t.get(f"parking:lane:{side}"), t.get("parking:lane:both"),
                    t.get(f"parking:condition:{side}"), t.get("parking:condition:both")}
            if "no_stopping" in vals:
                out[side].add("OSM_NO_STOPPING")
            elif vals & {"no_parking", "no_standing"}:
                out[side].add("OSM_NO_PARKING")
        return out

    def match_feature(self, f):
        """Map-match a curated feature to (way, side, start, end) tuples."""
        g = f["geometry"]
        kind = f["kind"]
        props = f.get("props") or {}
        if g["type"] == "Point":
            pt = to_m_point(*g["coordinates"])
            w, _ = self.nearest_curb_way(pt, 30)
            if not w:
                return []
            side = props.get("side") if props.get("side") in SIDES else w.side_of(pt)
            pos = w.line.project(pt)
            if kind in ("sign_3_27", "sign_3_28"):
                mode = props.get("zone_mode", "to_next_intersection")
                if mode == "to_point" and props.get("zone_end"):
                    end = w.line.project(to_m_point(*props["zone_end"]))
                    return [(w, side, min(pos, end), max(pos, end))]
                length = props.get("zone_length_m") if mode == "length" else None
                return self._sign_zone(w, side, pos, length)
            half = float(props.get("half_length_m", 10))
            return [(w, side, pos - half, pos + half)]
        if g["type"] == "LineString":
            pts = [to_m_point(*c) for c in g["coordinates"]]
            w, _ = self.nearest_curb_way(pts[0], 30)
            if not w:
                return []
            mid = LineString([(p.x, p.y) for p in pts]).interpolate(0.5, normalized=True)
            side = props.get("side") if props.get("side") in SIDES else w.side_of(mid)
            ps = [w.line.project(p) for p in pts]
            return [(w, side, min(ps), max(ps))]
        if g["type"] in ("Polygon", "MultiPolygon"):
            ll = shape(g)
            polys = getattr(ll, "geoms", [ll])
            out = []
            for poly in polys:
                mp = Polygon(TO_M.itransform(poly.exterior.coords))
                for j in self.curb_tree.query(mp, predicate="intersects"):
                    w = self.curb_list[int(j)]
                    inter = w.line.intersection(mp)
                    for part in getattr(inter, "geoms", [inter]):
                        if part.is_empty or part.geom_type != "LineString":
                            continue
                        a = w.line.project(Point(part.coords[0]))
                        b = w.line.project(Point(part.coords[-1]))
                        for side in SIDES:
                            out.append((w, side, min(a, b), max(a, b)))
            return out
        return []

    def _sign_zone(self, w, side, pos, zone_len=None, max_len=1000.0):
        """Sign zone in the direction of traffic, up to the next intersection (Art. 64.VI).

        OSM often splits one street into several ways without an intersection, and
        driveway exits do not end a zone (64.VI); the zone then continues onto the
        next way, keeping the same physical curb.
        """
        out = []
        remaining = float(zone_len) if zone_len else max_len
        forward = w.travel(side) == "fwd"
        for _ in range(12):
            inter = sorted(p for n, ps in w.node_pos.items() if n in self.intersections for p in ps)
            if forward:
                stop = next((p for p in inter if p > pos + 1), None)
                end = min(stop if stop is not None else w.length, pos + remaining)
                out.append((w, side, pos, end))
                remaining -= end - pos
                node = w.nodes[-1]
            else:
                stop = next((p for p in reversed(inter) if p < pos - 1), None)
                start = max(stop if stop is not None else 0.0, pos - remaining)
                out.append((w, side, start, pos))
                remaining -= pos - start
                node = w.nodes[0]
            if stop is not None or remaining <= 0.5 or node in self.intersections:
                break
            side_rel = side if forward else flip(side)  # curb side relative to the movement
            nxt = [self.ways[i] for i in self.node_ways[node] if i != w.id and i in self.ways]
            if len(nxt) != 1:
                break
            w2 = nxt[0]
            if w2.nodes[0] == node:
                fwd2, pos2 = True, 0.0
            elif w2.nodes[-1] == node:
                fwd2, pos2 = False, w2.length
            else:
                break
            side2 = side_rel if fwd2 else flip(side_rel)
            if (w2.travel(side2) == "fwd") != fwd2:  # traffic on that curb flows the other way
                break
            w, side, pos, forward = w2, side2, pos2, fwd2
        return out

    # -------------------------------------------------------- segmentation
    @staticmethod
    def _status_for(vehicle, prohib, cautions, covered):
        if any(vehicle not in RULES[i.rule].exempt for i in prohib):
            return PROHIBITED
        if cautions or not covered:
            return UNVERIFIED
        return ALLOWED

    def _segment(self):
        self.segments = {}
        self.segments_by_way = defaultdict(list)
        for w in self.ways.values():
            for side in SIDES:
                ivs = self.intervals.get((w.id, side), [])
                cov = self.coverage.get((w.id, side), [])
                off = self.official.get((w.id, side), [])
                cuts = {0.0, w.length}
                for i in ivs:
                    cuts.update((i.start, i.end))
                for a, b, _ in cov + off:
                    cuts.update((a, b))
                cuts = sorted(c for c in cuts if 0 <= c <= w.length)
                pieces = []
                for a, b in pairwise(cuts):
                    if b - a < 0.3:
                        continue
                    m = (a + b) / 2
                    active = [i for i in ivs if i.covers(m)]
                    # A reviewed bus-lane observation (line type known) supersedes the OSM "unknown line" caution.
                    if any(i.rule in ("BUS_LANE_SOLID", "BUS_LANE_DASHED") for i in active):
                        active = [i for i in active if not (i.rule == "BUS_LANE_UNKNOWN_LINE" and i.source == "osm")]
                    prohib = [i for i in active if RULES[i.rule].effect == "prohibit"]
                    cautions = [i for i in active if RULES[i.rule].effect == "caution"]
                    info = [i for i in active if RULES[i.rule].effect == "info"]
                    covered = [f for s, e, f in cov if s <= m < e]
                    official = [f for s, e, f in off if s <= m < e]
                    if official and prohib:
                        cautions.append(Interval(a, b, "SOURCE_CONFLICT", "engine", "conflict",
                                                 {"official_zone": [f["id"] for f in official],
                                                  "prohibitions": sorted({i.rule for i in prohib})}))
                    if not covered and not official:
                        cautions.append(Interval(a, b, "NOT_SURVEYED", "engine", "coverage", {}))
                    by_vehicle = {v: self._status_for(v, prohib, cautions, covered or official) for v in VEHICLE_CLASSES}
                    key = (tuple(by_vehicle.items()), tuple(sorted({(i.rule, i.source_ref) for i in active + cautions})),
                           tuple(sorted(f["id"] for f in covered + official)))
                    if pieces and pieces[-1]["key"] == key and abs(pieces[-1]["end"] - a) < 0.31:
                        pieces[-1]["end"] = b
                    else:
                        pieces.append({"key": key, "start": a, "end": b, "by_vehicle": by_vehicle, "prohib": prohib,
                                       "cautions": cautions, "info": info, "covered": covered, "official": official})
                for p in pieces:
                    seg = self._make_segment(w, side, p)
                    self.segments[seg["id"]] = seg
                    self.segments_by_way[(w.id, side)].append(seg)

    def _reason(self, i: Interval):
        r = RULES[i.rule]
        return {"rule": r.id, "rule_version": r.version, "effect": r.effect, "legal_ref": r.legal_ref,
                "article": r.article, "verification": r.verification, "applies_to": r.applies_to,
                "exempt": list(r.exempt), "params": r.params, "source": i.source,
                "source_ref": i.source_ref, "detail": i.detail}

    def _make_segment(self, w, side, p):
        a, b = p["start"], p["end"]
        center = substring(w.line, a, b)
        off = w.width / 2 * (1 if side == "left" else -1)
        try:
            curb = center.offset_curve(off) if center.length > 0.5 else center
            if curb.is_empty or curb.geom_type != "LineString":
                curb = center
        except Exception:  # noqa: BLE001 - degenerate geometry, fall back
            curb = center

        def uniq(items):
            return list({(r["rule"], r["source_ref"]): r for r in (self._reason(i) for i in items)}.values())

        reasons, cautions, notes = uniq(p["prohib"]), uniq(p["cautions"]), uniq(p["info"])
        status = p["by_vehicle"][C.DEFAULT_VEHICLE]
        feats = p["covered"] + p["official"]
        verified_dates = [f.get("verified_at") for f in feats if f.get("verified_at")]
        verified_dates += [i.detail.get("verified_at") for i in p["prohib"] + p["info"] if i.detail.get("verified_at")]
        sources = sorted({r["source"] for r in reasons + cautions + notes if r["source"] != "engine"} |
                         {f["source"] for f in feats} | {"osm"})
        if status == ALLOWED:
            confidence = "verified_observation"
        elif status == PROHIBITED:
            levels = {r["verification"] for r in reasons}
            confidence = "rule_verified_text" if levels <= {"verified_text"} else "rule_interpretation"
        else:
            confidence = "insufficient_or_conflicting_data"
        return {
            "id": f"w{w.id}-{side[0]}-{int(round(a * 10))}",
            "way_id": w.id, "side": side, "travel": w.travel(side), "compass": w.compass((a + b) / 2, side),
            "name": w.name, "highway": w.highway, "oneway": w.oneway,
            "start_m": round(a, 2), "end_m": round(b, 2), "length_m": round(b - a, 2),
            "status": status,
            "status_by_vehicle": p["by_vehicle"],
            "reasons": reasons,
            "cautions": cautions,
            "notes": notes,
            "coverage": [{"feature_id": f["id"], "kind": f["kind"], "source": f["source"],
                          "note": f.get("note"), "verified_at": f.get("verified_at")} for f in feats],
            "official": bool(p["official"]),
            "sources": sources,
            "osm_ref": f"way/{w.id}",
            "osm_timestamp": self.osm_timestamp,
            "last_verified": max(verified_dates) if verified_dates else None,
            "confidence": confidence,
            "geometry_quality": "estimated_curb_offset",
            "ruleset_version": RULESET_VERSION,
            "coords": to_ll_coords(list(curb.coords)),
        }

    # ------------------------------------------------------------- search
    def _build_search(self):
        items, seen = [], set()
        s_, w_, n_, e_ = self.bbox or (-90, -180, 90, 180)

        def inside(nd):
            return s_ <= nd["lat"] <= n_ and w_ <= nd["lon"] <= e_

        for el in self.raw["elements"]:
            t = el.get("tags") or {}
            name = t.get("name:az") or t.get("name") or t.get("name:en")
            if not name:
                continue
            if el["type"] == "node":
                if not inside(el):
                    continue
                lon, lat = el["lon"], el["lat"]
            elif el["type"] == "way":
                pts = [self.nodes[n] for n in el["nodes"] if n in self.nodes and inside(self.nodes[n])]
                if not pts:
                    continue
                if "highway" in t:
                    mid = pts[len(pts) // 2]
                    lon, lat = mid["lon"], mid["lat"]
                else:
                    lon = sum(p["lon"] for p in pts) / len(pts)
                    lat = sum(p["lat"] for p in pts) / len(pts)
            else:
                continue
            if "highway" in t and t["highway"] in ("crossing", "traffic_signals"):
                continue
            kind = ("street" if "highway" in t and el["type"] == "way" else
                    t.get("amenity") or t.get("shop") or t.get("tourism") or t.get("office") or
                    t.get("leisure") or t.get("public_transport") or t.get("railway") or t.get("highway") or "place")
            key = (norm_text(name), kind if kind == "street" else round(lat, 4))
            if key in seen:
                continue
            seen.add(key)
            names = {v for k, v in t.items() if k == "name" or k.startswith("name:") or k in ("alt_name", "old_name")}
            items.append({"name": name, "kind": kind, "lat": lat, "lon": lon,
                          "alt": sorted(n for n in names if n != name)[:3],
                          "_n": " ".join(norm_text(n) for n in names)})
        self.search_items = items

    def search(self, q, limit=8):
        nq = norm_text(q)
        if len(nq) < 2:
            return []
        scored = []
        for it in self.search_items:
            n = it["_n"]
            if n.startswith(nq) or norm_text(it["name"]).startswith(nq):
                s = 0
            elif f" {nq}" in f" {n}":
                s = 1
            elif nq in n:
                s = 2
            elif all(tok in n for tok in nq.split()):
                s = 3
            else:
                continue
            scored.append((s, it["kind"] == "street", len(it["name"]), it))
        scored.sort(key=lambda x: x[:3])
        return [{k: v for k, v in it.items() if k != "_n"} for *_, it in scored[:limit]]

    # ------------------------------------------------------------- outputs
    def stats(self, vehicle=None):
        vehicle = vehicle or C.DEFAULT_VEHICLE
        out = {s: {"count": 0, "length_m": 0.0} for s in (PROHIBITED, ALLOWED, UNVERIFIED)}
        by_rule, cautions = defaultdict(float), defaultdict(float)
        for s in self.segments.values():
            st = s["status_by_vehicle"][vehicle]
            out[st]["count"] += 1
            out[st]["length_m"] += s["length_m"]
            for r in s["reasons"]:
                by_rule[r["rule"]] += s["length_m"]
            if st == UNVERIFIED:
                for r in s["cautions"]:
                    cautions[r["rule"]] += s["length_m"]
        for v in out.values():
            v["length_m"] = round(v["length_m"])

        def top(d):
            return {k: round(v) for k, v in sorted(d.items(), key=lambda x: -x[1])}
        verified = [f for f in self.features if f["status"] == "verified"]
        return {"vehicle": vehicle, "by_status": out, "prohibited_length_by_rule": top(by_rule),
                "unverified_length_by_reason": top(cautions),
                "observations": {"verified": len(verified),
                                 "pending": sum(f["status"] == "pending" for f in self.features),
                                 "verified_by_kind": dict(sorted(defaultdict(int, {
                                     k: sum(f["kind"] == k for f in verified) for k in {f["kind"] for f in verified}
                                 }).items()))},
                "ways": len(self.ways), "crossings": len(self.crossing_nodes), "bus_stops": len(self.bus_stops),
                "intersections": len(self.intersections), "signals": len(self.signal_nodes)}

    def segments_geojson(self, status=None, vehicle=None):
        vehicle = vehicle or C.DEFAULT_VEHICLE
        feats = []
        for seg in self.segments.values():
            st = seg["status_by_vehicle"][vehicle]
            if status and st != status:
                continue
            feats.append({"type": "Feature", "id": seg["id"],
                          "geometry": {"type": "LineString", "coordinates": seg["coords"]},
                          "properties": {"id": seg["id"], "status": st, "by_vehicle": seg["status_by_vehicle"],
                                         "name": seg["name"], "side": seg["side"], "compass": seg["compass"],
                                         "length_m": seg["length_m"],
                                         "rules": sorted({r["rule"] for r in seg["reasons"]}),
                                         "cautions": sorted({r["rule"] for r in seg["cautions"]}),
                                         "official": seg["official"], "highway": seg["highway"]}})
        return {"type": "FeatureCollection", "features": feats}

    def context_layers(self):
        def node_pt(n):
            el = self.nodes[n]
            return [el["lon"], el["lat"]]
        return {
            "crossings": [{"ref": f"node/{n}", "coord": node_pt(n)} for n in self.crossing_nodes],
            "bus_stops": [{"ref": b["ref"], "coord": b["lonlat"], "name": b["name"]} for b in self.bus_stops],
            "signals": [{"ref": f"node/{n}", "coord": node_pt(n)} for n in self.signal_nodes],
        }


def load_raw(path=C.OSM_RAW):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)

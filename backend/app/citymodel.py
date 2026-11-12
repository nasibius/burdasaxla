"""City model: OSM -> road graph -> curb segments -> legal status.

Pipeline (all deterministic, no AI):
  1. Parse raw OSM (Overpass JSON) and project to a metric CRS.
  2. Build drivable ways; each way has two curbs ("right"/"left" relative to
     the way's digitised direction, normalised so oneway roads point with traffic).
  3. Rule engine: for every way-side collect prohibition intervals in linear
     metres along the way (crossings, intersections, bus stops, bus lanes,
     bridges, signs, markings...). Each interval keeps its rule id + source.
  4. Split each curb at every interval / coverage boundary -> curb segments.
     PROHIBITED if any prohibition applies; VERIFIED only if no prohibition AND
     the curb is covered by a verified survey area or an official zone;
     otherwise UNKNOWN. "No prohibition found" is never green on its own.
  5. Build directed drive graph and undirected walk graph for routing.
"""
from __future__ import annotations

import json
import math
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import substring

from . import config as C
from .rules import RULES, RULESET_VERSION

TO_M = Transformer.from_crs("EPSG:4326", C.METRIC_CRS, always_xy=True)
TO_LL = Transformer.from_crs(C.METRIC_CRS, "EPSG:4326", always_xy=True)

PROHIBITED, VERIFIED, UNKNOWN = "PROHIBITED", "VERIFIED", "UNKNOWN"
SIDES = ("right", "left")


def to_ll_coords(coords):
    xs, ys = zip(*coords)
    lons, lats = TO_LL.transform(xs, ys)
    return [[round(lo, 7), round(la, 7)] for lo, la in zip(lons, lats)]


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
        self.xy = {i: (x, y) for i, x, y in zip(ids, xs, ys)}

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
            for a, b in zip(coords, coords[1:]):
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
            for a, b in zip(w.nodes, w.nodes[1:]):
                nbrs[a].add(b)
                nbrs[b].add(a)
        self.intersections = {n for n, s in nbrs.items() if len(s) >= 3}
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
            for i, (a, b) in enumerate(zip(w.nodes, w.nodes[1:])):
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
            for a, b in zip(nds, nds[1:]):
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
            if t.get("highway") == "bus_stop" or (t.get("public_transport") == "platform" and
                                                  (t.get("bus") == "yes" or t.get("highway") == "bus_stop" or "bus" not in t)):
                self.bus_stops.append({"ref": f"node/{nid}", "pt": Point(self.xy[nid]), "on_road": nid in road_nodes,
                                       "name": t.get("name:az") or t.get("name") or "", "lonlat": [el["lon"], el["lat"]]})
        for el in self.raw_ways:
            t = el.get("tags", {})
            if t.get("public_transport") == "platform" or t.get("highway") == "platform":
                nds = [n for n in el["nodes"] if n in self.xy]
                if len(nds) >= 2:
                    c = LineString([self.xy[n] for n in nds]).centroid
                    lon, lat = TO_LL.transform(c.x, c.y)
                    self.bus_stops.append({"ref": f"way/{el['id']}", "pt": c, "on_road": False,
                                           "name": t.get("name") or "", "lonlat": [lon, lat]})

    # ------------------------------------------------------------ rule engine
    def _apply_rules(self):
        iv = defaultdict(list)          # (way_id, side) -> [Interval]
        self.coverage = defaultdict(list)   # (way_id, side) -> [(start, end, feature)]
        self.official = defaultdict(list)
        self.feature_matches = {}       # feature id -> [(way_id, side, start, end)]

        def add(w, side, a, b, rule, source, ref, **detail):
            a, b = max(0.0, a), min(w.length, b)
            if b - a > 0.05:
                iv[(w.id, side)].append(Interval(a, b, rule, source, ref, detail))

        def around_before(w, side, pos, before, half, rule, ref, **detail):
            if w.travel(side) == "fwd":
                add(w, side, pos - half - before, pos + half, rule, "osm", ref, **detail)
            else:
                add(w, side, pos - half, pos + half + before, rule, "osm", ref, **detail)

        P = {k: r.params for k, r in RULES.items()}
        for w in self.ways.values():
            t = w.tags
            whole = None
            if w.highway in ("motorway", "motorway_link"):
                whole = ("MOTORWAY", f"way/{w.id}")
            elif t.get("junction") in ("roundabout", "circular"):
                whole = ("ROUNDABOUT", f"way/{w.id}")
            elif t.get("bridge", "no") not in ("no",) or t.get("tunnel", "no") not in ("no", "culvert"):
                whole = ("BRIDGE_TUNNEL", f"way/{w.id}")
            for side in SIDES:
                if whole:
                    add(w, side, 0, w.length, whole[0], "osm", whole[1])
                if w.oneway and side == "left":
                    add(w, side, 0, w.length, "ONE_WAY_LEFT_SIDE", "osm", f"way/{w.id}")

            for nid, positions in w.node_pos.items():
                for pos in positions:
                    if nid in self.crossing_nodes:
                        for side in SIDES:
                            around_before(w, side, pos, P["PEDESTRIAN_CROSSING"]["before_m"],
                                          P["PEDESTRIAN_CROSSING"]["crossing_half_width_m"],
                                          "PEDESTRIAN_CROSSING", f"node/{nid}")
                    if nid in self.intersections:
                        others = [self.drive_ways[o] for o in self.node_ways[nid] if o != w.id]
                        half_other = max([o.width / 2 for o in others], default=w.width / 2)
                        r = half_other + P["INTERSECTION"]["edge_buffer_m"]
                        for side in SIDES:
                            add(w, side, pos - r, pos + r, "INTERSECTION", "osm", f"node/{nid}",
                                crossed_half_width_m=round(half_other, 1))
                    if nid in self.signal_nodes and nid not in self.crossing_nodes:
                        for side in SIDES:
                            around_before(w, side, pos, P["TRAFFIC_SIGNAL"]["before_m"], 0.5,
                                          "TRAFFIC_SIGNAL", f"node/{nid}")
                    if nid in self.level_crossings:
                        r = P["LEVEL_CROSSING"]["radius_m"]
                        for side in SIDES:
                            add(w, side, pos - r, pos + r, "LEVEL_CROSSING", "osm", f"node/{nid}")

            # OSM bus lanes & parking restrictions
            for side, (rule, ref) in self._osm_lane_tags(w).items():
                for r_ in rule:
                    add(w, side, 0, w.length, r_, "osm", ref)

        # Under bridges / overpasses
        bridge_lines = []
        for el in self.raw_ways:
            t = el.get("tags", {})
            if t.get("bridge", "no") != "no" and (t.get("highway") in C.DRIVE_HIGHWAYS or t.get("railway")):
                nds = [n for n in el["nodes"] if n in self.xy]
                if len(nds) >= 2:
                    bw = self._width(t, t.get("oneway") == "yes") if t.get("highway") else 6
                    bridge_lines.append((el["id"], LineString([self.xy[n] for n in nds]), bw, set(nds)))
        for bid, bl, bw, bnodes in bridge_lines:
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

        # Bus stops (side-specific)
        r = P["BUS_STOP"]["radius_m"]
        seen = []
        for bs in self.bus_stops:
            w, d = self.nearest_curb_way(bs["pt"], 35)
            if w is None:
                continue
            pos = w.line.project(bs["pt"])
            sides = SIDES if (bs["on_road"] or d < 1.0) else (w.side_of(bs["pt"]),)
            for side in sides:
                if any(s[0] == w.id and s[1] == side and abs(s[2] - pos) < 20 for s in seen):
                    continue
                seen.append((w.id, side, pos))
                add(w, side, pos - r, pos + r, "BUS_STOP", "osm", bs["ref"], name=bs["name"])
            bs["way_id"], bs["pos"] = w.id, pos

        # Curated features (verified only)
        for f in self.features:
            if f["status"] != "verified":
                continue
            self._apply_feature(f, add)

        self.intervals = iv

    def _osm_lane_tags(self, w: Way):
        """Bus lanes and stopping restrictions encoded on the way itself."""
        t, out = w.tags, defaultdict(list)
        res = {}
        ref = f"way/{w.id}"

        def lane_last(v, rightmost=True):
            parts = (v or "").split("|")
            if not parts or parts == [""]:
                return False
            p = parts[-1] if rightmost else parts[0]
            return p in ("designated", "yes", "lane")

        # busway scheme
        for side in SIDES:
            bw = t.get(f"busway:{side}") or t.get("busway:both") or (t.get("busway") if side == "right" or not w.oneway else None)
            if bw in ("lane", "share_busway"):
                out[side].append("BUS_LANE")
        # bus:lanes / psv:lanes scheme
        for key in ("bus:lanes", "psv:lanes"):
            if w.oneway:
                if lane_last(t.get(key), True):
                    out["right"].append("BUS_LANE")
                if lane_last(t.get(key), False):
                    out["left"].append("BUS_LANE")
            else:
                if lane_last(t.get(f"{key}:forward"), True):
                    out["right"].append("BUS_LANE")
                if lane_last(t.get(f"{key}:backward"), True):
                    out["left"].append("BUS_LANE")
        # lanes:bus=<count> scheme (rightmost lane is the bus lane in Baku practice)
        def n_bus(key):
            v = _num(t.get(key))
            return int(v) if v else 0
        if w.oneway:
            if n_bus("lanes:bus") or n_bus("lanes:psv"):
                out["right"].append("BUS_LANE")
        else:
            if n_bus("lanes:bus:forward") or n_bus("lanes:psv:forward"):
                out["right"].append("BUS_LANE")
            if n_bus("lanes:bus:backward") or n_bus("lanes:psv:backward"):
                out["left"].append("BUS_LANE")
            if n_bus("lanes:bus") >= 1 and not any(k.startswith(("lanes:bus:", "bus:lanes")) for k in t):
                # direction not specified: conservatively assume both curbs
                out["right"].append("BUS_LANE")
                out["left"].append("BUS_LANE")
        # parking restrictions (new + legacy schemes)
        for side in SIDES:
            vals = {t.get(f"parking:{side}:restriction"), t.get("parking:both:restriction"),
                    t.get(f"parking:lane:{side}"), t.get("parking:lane:both"),
                    t.get(f"parking:condition:{side}"), t.get("parking:condition:both")}
            if "no_stopping" in vals:
                out[side].append("OSM_NO_STOPPING")
            elif vals & {"no_parking", "no_standing"}:
                out[side].append("OSM_NO_PARKING")
        for side, rules in out.items():
            res[side] = (sorted(set(rules)), ref)
        return res

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
            side = props.get("side") or w.side_of(pt)
            pos = w.line.project(pt)
            if kind in ("sign_3_27", "sign_3_28"):
                zl = props.get("zone_length_m")
                inter = sorted(p for n, ps in w.node_pos.items() if n in self.intersections for p in ps)
                if w.travel(side) == "fwd":
                    end = pos + zl if zl else next((p for p in inter if p > pos + 1), w.length)
                    return [(w, side, pos, end)]
                start = pos - zl if zl else next((p for p in reversed(inter) if p < pos - 1), 0.0)
                return [(w, side, start, pos)]
            half = float(props.get("half_length_m", 10))
            return [(w, side, pos - half, pos + half)]
        if g["type"] == "LineString":
            pts = [to_m_point(*c) for c in g["coordinates"]]
            w, _ = self.nearest_curb_way(pts[0], 30)
            if not w:
                return []
            mid = LineString([(p.x, p.y) for p in pts]).interpolate(0.5, normalized=True)
            side = props.get("side") or w.side_of(mid)
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

    def _apply_feature(self, f, add):
        matches = self.match_feature(f)
        self.feature_matches[f["id"]] = [(w.id, s, a, b) for w, s, a, b in matches]
        kind, ref = f["kind"], f"feature/{f['id']}"
        rule = {"sign_3_27": "SIGN_3_27", "sign_3_28": "SIGN_3_28", "marking_1_4": "MARKING_1_4",
                "marking_1_10": "MARKING_1_10", "bus_lane": "BUS_LANE", "official_zone": "OFFICIAL_ZONE"}.get(kind)
        for w, side, a, b in matches:
            a, b = max(0.0, a), min(w.length, b)
            if b - a < 0.05:
                continue
            if kind == "survey_area":
                self.coverage[(w.id, side)].append((a, b, f))
                continue
            if kind == "official_zone":
                self.official[(w.id, side)].append((a, b, f))
            add(w, side, a, b, rule, f["source"], ref, feature_id=f["id"], verified_at=f.get("verified_at"))

    # -------------------------------------------------------- segmentation
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
                for a, b in zip(cuts, cuts[1:]):
                    if b - a < 0.3:
                        continue
                    m = (a + b) / 2
                    active = [i for i in ivs if i.covers(m)]
                    prohib = [i for i in active if RULES[i.rule].effect == "prohibit"]
                    info = [i for i in active if RULES[i.rule].effect == "info"]
                    covered = [f for s, e, f in cov if s <= m < e]
                    official = [f for s, e, f in off if s <= m < e]
                    if prohib:
                        status = PROHIBITED
                    elif covered or official:
                        status = VERIFIED
                    else:
                        status = UNKNOWN
                    key = (status, tuple(sorted({(i.rule, i.source_ref) for i in active})),
                           tuple(sorted(f["id"] for f in covered + official)))
                    if pieces and pieces[-1]["key"] == key and abs(pieces[-1]["end"] - a) < 0.31:
                        pieces[-1]["end"] = b
                    else:
                        pieces.append({"key": key, "start": a, "end": b, "status": status,
                                       "prohib": prohib, "info": info, "covered": covered, "official": official})
                for p in pieces:
                    seg = self._make_segment(w, side, p)
                    self.segments[seg["id"]] = seg
                    self.segments_by_way[(w.id, side)].append(seg)

    def _reason(self, i: Interval):
        r = RULES[i.rule]
        return {"rule": r.id, "rule_version": r.version, "effect": r.effect, "legal_ref": r.legal_ref,
                "params": r.params, "approximation": r.approximation, "source": i.source,
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
        reasons = [self._reason(i) for i in p["prohib"]]
        # dedupe identical reasons (same rule + same source object)
        uniq = {(r["rule"], r["source_ref"]): r for r in reasons}
        notes = {(r["rule"], r["source_ref"]): r for r in (self._reason(i) for i in p["info"])}
        verified_dates = [f.get("verified_at") for f in p["covered"] + p["official"] if f.get("verified_at")]
        verified_dates += [i.detail.get("verified_at") for i in p["prohib"] + p["info"] if i.detail.get("verified_at")]
        sources = sorted({r["source"] for r in list(uniq.values()) + list(notes.values())} |
                         {f["source"] for f in p["covered"] + p["official"]} | {"osm"})
        if p["status"] == VERIFIED:
            confidence = "verified"
        elif any(r["approximation"] for r in uniq.values()):
            confidence = "estimated"
        else:
            confidence = "rule_derived" if uniq else "insufficient_data"
        return {
            "id": f"w{w.id}-{side[0]}-{int(round(a * 10))}",
            "way_id": w.id, "side": side, "travel": w.travel(side), "compass": w.compass((a + b) / 2, side),
            "name": w.name, "highway": w.highway, "oneway": w.oneway,
            "start_m": round(a, 2), "end_m": round(b, 2), "length_m": round(b - a, 2),
            "status": p["status"],
            "reasons": list(uniq.values()),
            "notes": list(notes.values()),
            "coverage": [{"feature_id": f["id"], "kind": f["kind"], "source": f["source"],
                          "note": f.get("note"), "verified_at": f.get("verified_at")} for f in p["covered"] + p["official"]],
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
    def stats(self):
        out = {s: {"count": 0, "length_m": 0.0} for s in (PROHIBITED, VERIFIED, UNKNOWN)}
        by_rule = defaultdict(float)
        for s in self.segments.values():
            out[s["status"]]["count"] += 1
            out[s["status"]]["length_m"] += s["length_m"]
            for r in s["reasons"]:
                by_rule[r["rule"]] += s["length_m"]
        for v in out.values():
            v["length_m"] = round(v["length_m"])
        return {"by_status": out, "prohibited_length_by_rule": {k: round(v) for k, v in
                                                                 sorted(by_rule.items(), key=lambda x: -x[1])},
                "ways": len(self.ways), "crossings": len(self.crossing_nodes), "bus_stops": len(self.bus_stops),
                "intersections": len(self.intersections), "signals": len(self.signal_nodes)}

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

/**
 * In-browser port of backend/app/dropoff.py for static hosting.
 *
 * Legal statuses are NOT computed here: they come precomputed from the Python
 * rule engine (scripts/export_static.py). This module only does the routing,
 * ranking and geometry the recommender needs, mirroring the Python version.
 */
import type { DoorInfo, LngLat, Recommendation, RecResponse } from "../types";

export interface EngineData {
  nodes: LngLat[];
  ways: { id: number; n: number[]; w: number; o: 0 | 1; sp: number; nm: string; c: 0 | 1 }[];
  walk: [number, number][];
  /** [id, wayIdx, side, start, end, status codes "<taxi><private>" (P/A/U), official, notes, confidence, prohibitions, cautions] */
  segments: [string, number, "r" | "l", number, number, string, 0 | 1, string[], string, string[], string[]][];
  crossings: number[];
  intersections: number[];
}

type XY = [number, number];
type Side = "right" | "left";
const STATUS = { P: "PROHIBITED", A: "ALLOWED", U: "UNVERIFIED" } as const;
type Code = keyof typeof STATUS;
export type VehicleClass = "taxi" | "private";

const MIN_STOP_LENGTH_M = 7;
const WALK_SPEED = 1.3;
const SAFE_CROSSING_SEARCH_M = 120;
const UNSAFE_CROSSING_PENALTY_M = 400;
const OFFICIAL_BONUS_M = 40;

// ------------------------------------------------------------------ geometry
const dist = (a: XY, b: XY) => Math.hypot(a[0] - b[0], a[1] - b[1]);

function projectOnSeg(p: XY, a: XY, b: XY) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const L2 = dx * dx + dy * dy || 1e-9;
  const u = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2));
  const q: XY = [a[0] + u * dx, a[1] + u * dy];
  return { t: u * Math.sqrt(L2), d: dist(p, q), q };
}

class Heap {
  private h: [number, number][] = [];
  push(x: [number, number]) {
    const h = this.h; h.push(x);
    let i = h.length - 1;
    while (i > 0) { const p = (i - 1) >> 1; if (h[p][0] <= h[i][0]) break; [h[p], h[i]] = [h[i], h[p]]; i = p; }
  }
  pop() {
    const h = this.h; const top = h[0]; const last = h.pop()!;
    if (h.length) {
      h[0] = last; let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1; let m = i;
        if (l < h.length && h[l][0] < h[m][0]) m = l;
        if (r < h.length && h[r][0] < h[m][0]) m = r;
        if (m === i) break; [h[m], h[i]] = [h[i], h[m]]; i = m;
      }
    }
    return top;
  }
  get size() { return this.h.length; }
}

type Adj = Map<number, [number, number][]>; // node -> [nbr, weight]

function dijkstra(adj: Adj, sources: Map<number, number>, cutoff = Infinity) {
  const d = new Map<number, number>(), prev = new Map<number, number>(), best = new Map(sources);
  const pq = new Heap();
  sources.forEach((c, n) => pq.push([c, n]));
  while (pq.size) {
    const [c, u] = pq.pop();
    if (d.has(u)) continue;
    d.set(u, c);
    if (c > cutoff) break;
    for (const [v, w] of adj.get(u) ?? []) {
      const nc = c + w;
      if (nc < (best.get(v) ?? Infinity)) { best.set(v, nc); prev.set(v, u); pq.push([nc, v]); }
    }
  }
  return { d, prev };
}

function pathTo(prev: Map<number, number>, node: number) {
  const out = [node];
  while (prev.has(out[out.length - 1])) out.push(prev.get(out[out.length - 1])!);
  return out.reverse();
}

/** Uniform grid over edges for nearest-edge queries. */
class EdgeGrid<T> {
  private cells = new Map<string, number[]>();
  constructor(private edges: { a: XY; b: XY; data: T }[], private size = 60) {
    edges.forEach((e, i) => {
      const [x0, x1] = [Math.min(e.a[0], e.b[0]), Math.max(e.a[0], e.b[0])];
      const [y0, y1] = [Math.min(e.a[1], e.b[1]), Math.max(e.a[1], e.b[1])];
      for (let cx = Math.floor(x0 / size); cx <= Math.floor(x1 / size); cx++)
        for (let cy = Math.floor(y0 / size); cy <= Math.floor(y1 / size); cy++) {
          const k = `${cx},${cy}`;
          (this.cells.get(k) ?? this.cells.set(k, []).get(k)!).push(i);
        }
    });
  }
  nearest(p: XY, maxDist: number, filter?: (d: T) => boolean) {
    let best: { e: { a: XY; b: XY; data: T }; t: number; d: number; q: XY } | null = null;
    const r = Math.ceil(maxDist / this.size);
    const cx = Math.floor(p[0] / this.size), cy = Math.floor(p[1] / this.size);
    const seen = new Set<number>();
    for (let i = cx - r; i <= cx + r; i++)
      for (let j = cy - r; j <= cy + r; j++)
        for (const k of this.cells.get(`${i},${j}`) ?? []) {
          if (seen.has(k)) continue; seen.add(k);
          const e = this.edges[k];
          if (filter && !filter(e.data)) continue;
          const pr = projectOnSeg(p, e.a, e.b);
          if (pr.d <= maxDist && (!best || pr.d < best.d)) best = { e, ...pr };
        }
    return best;
  }
}

// ---------------------------------------------------------------------- ways
class Way {
  cum: number[] = [0];
  constructor(public i: number, public id: number, public nodes: number[], public pts: XY[], public width: number,
    public oneway: boolean, public speed: number, public name: string, public curb: boolean) {
    for (let k = 1; k < pts.length; k++) this.cum.push(this.cum[k - 1] + dist(pts[k - 1], pts[k]));
  }
  get length() { return this.cum[this.cum.length - 1]; }
  travel(side: Side) { return side === "right" || this.oneway ? "fwd" : "bwd"; }
  edgeIndex(pos: number) {
    let i = 0;
    while (i < this.cum.length - 2 && this.cum[i + 1] <= pos) i++;
    return i;
  }
  at(pos: number): XY {
    pos = Math.max(0, Math.min(this.length, pos));
    const i = this.edgeIndex(pos);
    const L = this.cum[i + 1] - this.cum[i] || 1e-9, u = (pos - this.cum[i]) / L;
    const a = this.pts[i], b = this.pts[i + 1];
    return [a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1])];
  }
  project(p: XY) {
    let best = { pos: 0, d: Infinity };
    for (let i = 0; i < this.pts.length - 1; i++) {
      const pr = projectOnSeg(p, this.pts[i], this.pts[i + 1]);
      if (pr.d < best.d) best = { pos: this.cum[i] + pr.t, d: pr.d };
    }
    return best;
  }
  private tangent(pos: number) {
    const a = this.at(pos - 1), b = this.at(pos + 1);
    const n = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    return [(b[0] - a[0]) / n, (b[1] - a[1]) / n] as XY;
  }
  sideOf(p: XY): Side {
    const pos = this.project(p).pos;
    const a = this.at(pos - 1), b = this.at(pos + 1);
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) > 0 ? "left" : "right";
  }
  curbPoint(pos: number, side: Side): XY {
    const p = this.at(pos), [tx, ty] = this.tangent(pos);
    const off = (this.width / 2) * (side === "left" ? 1 : -1);
    return [p[0] - ty * off, p[1] + tx * off];
  }
  compass(pos: number, side: Side) {
    const [tx, ty] = this.tangent(pos);
    const [nx, ny] = side === "left" ? [-ty, tx] : [ty, -tx];
    const ang = ((Math.atan2(nx, ny) * 180) / Math.PI + 360) % 360;
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.floor((ang + 22.5) / 45) % 8];
  }
}

interface Seg {
  id: string; way: Way; side: Side; start: number; end: number; status: Record<VehicleClass, Code>;
  official: boolean; notes: string[]; confidence: string; rules: string[]; cautions: string[];
}

// -------------------------------------------------------------------- engine
export class StaticEngine {
  private lon0: number; private lat0: number; private kx: number; private ky = 110574;
  private xy: XY[];
  private ways: Way[];
  private driveAdj: Adj = new Map();
  private walkAdj: Adj = new Map();
  private driveEdges = new Set<number>();
  private driveGrid: EdgeGrid<{ way: Way; i: number }>;
  private walkGrid: EdgeGrid<{ a: number; b: number }>;
  private segs: Seg[];
  private segsByWaySide = new Map<string, Seg[]>();
  private crossings: Set<number>;
  private N: number;

  constructor(data: EngineData, center: LngLat) {
    [this.lon0, this.lat0] = center;
    this.kx = 111320 * Math.cos((this.lat0 * Math.PI) / 180);
    this.xy = data.nodes.map((c) => this.toXY(c));
    this.N = this.xy.length;
    this.ways = data.ways.map((w, i) => new Way(i, w.id, w.n, w.n.map((n) => this.xy[n]), w.w, !!w.o, w.sp, w.nm, !!w.c));
    const driveEdgeList: { a: XY; b: XY; data: { way: Way; i: number } }[] = [];
    for (const w of this.ways) {
      for (let i = 0; i < w.nodes.length - 1; i++) {
        const a = w.nodes[i], b = w.nodes[i + 1], L = w.cum[i + 1] - w.cum[i];
        this.addEdge(this.driveAdj, a, b, L / w.speed); this.driveEdges.add(a * this.N + b);
        if (!w.oneway) { this.addEdge(this.driveAdj, b, a, L / w.speed); this.driveEdges.add(b * this.N + a); }
        driveEdgeList.push({ a: w.pts[i], b: w.pts[i + 1], data: { way: w, i } });
      }
    }
    this.driveGrid = new EdgeGrid(driveEdgeList);
    this.walkGrid = new EdgeGrid(data.walk.map(([a, b]) => {
      const L = dist(this.xy[a], this.xy[b]);
      this.addEdge(this.walkAdj, a, b, L); this.addEdge(this.walkAdj, b, a, L);
      return { a: this.xy[a], b: this.xy[b], data: { a, b } };
    }));
    this.segs = data.segments.map(([id, wi, s, start, end, st, off, notes, conf, rules, cautions]) => ({
      id, way: this.ways[wi], side: s === "r" ? "right" : "left", start, end,
      status: { taxi: st[0] as Code, private: st[1] as Code }, official: !!off, notes, confidence: conf, rules, cautions,
    }));
    for (const s of this.segs) {
      const k = `${s.way.i}:${s.side}`;
      (this.segsByWaySide.get(k) ?? this.segsByWaySide.set(k, []).get(k)!).push(s);
    }
    this.crossings = new Set(data.crossings);
  }

  private addEdge(adj: Adj, a: number, b: number, w: number) {
    (adj.get(a) ?? adj.set(a, []).get(a)!).push([b, w]);
  }
  private toXY([lon, lat]: LngLat): XY { return [(lon - this.lon0) * this.kx, (lat - this.lat0) * this.ky]; }
  private toLL([x, y]: XY): LngLat { return [+(x / this.kx + this.lon0).toFixed(7), +(y / this.ky + this.lat0).toFixed(7)]; }

  private nearestCurbWay(p: XY, maxDist: number) {
    const hit = this.driveGrid.nearest(p, maxDist, (d) => d.way.curb);
    return hit ? { way: hit.e.data.way, d: hit.d } : null;
  }

  private snapDrive(p: XY) {
    const hit = this.driveGrid.nearest(p, 150);
    if (!hit) return null;
    const { way: w, i } = hit.e.data;
    const a = w.nodes[i], b = w.nodes[i + 1], L = w.cum[i + 1] - w.cum[i];
    const sources = new Map<number, number>();
    if (this.driveEdges.has(a * this.N + b)) sources.set(b, (L - hit.t) / w.speed);
    if (this.driveEdges.has(b * this.N + a)) sources.set(a, Math.min(sources.get(a) ?? Infinity, hit.t / w.speed));
    return { sources, snapped: hit.q, way: w, edgeIdx: i, t: hit.t, L };
  }

  private snapWalk(p: XY) {
    const hit = this.walkGrid.nearest(p, 250);
    if (!hit) return null;
    const { a, b } = hit.e.data, L = dist(this.xy[a], this.xy[b]);
    return { sources: new Map([[a, hit.d + hit.t], [b, hit.d + (L - hit.t)]]), snapped: hit.q };
  }

  private candidates(center: XY, radius: number, prefer: "nearest" | "first", vehicle: VehicleClass, status: Code) {
    const out: { seg: Seg; way: Way; pos: number; pt: XY }[] = [];
    for (const seg of this.segs) {
      if (seg.status[vehicle] !== status || seg.end - seg.start < MIN_STOP_LENGTH_M) continue;
      const w = seg.way, a = seg.start + 3.5, b = seg.end - 3.5;
      const pos = prefer === "nearest" ? Math.min(Math.max(w.project(center).pos, a), b)
        : w.travel(seg.side) === "fwd" ? a : b;
      const pt = w.curbPoint(pos, seg.side);
      if (dist(pt, center) <= radius) out.push({ seg, way: w, pos, pt });
    }
    return out;
  }

  private arrival(c: { seg: Seg; way: Way; pos: number }, dd: Map<number, number>, snap: ReturnType<StaticEngine["snapDrive"]>) {
    const w = c.way, i = w.edgeIndex(c.pos), fwd = w.travel(c.seg.side) === "fwd";
    const [a, b, along] = fwd ? [w.nodes[i], w.nodes[i + 1], c.pos - w.cum[i]] : [w.nodes[i + 1], w.nodes[i], w.cum[i + 1] - c.pos];
    if (!this.driveEdges.has(a * this.N + b)) return null;
    if (snap && snap.way === w && snap.edgeIdx === i) {
      const tFromA = fwd ? snap.t : snap.L - snap.t;
      if (tFromA <= along + 0.5) return { node: -1, direct: true, seconds: Math.max(0, along - tFromA) / w.speed };
    }
    if (!dd.has(a)) return null;
    return { node: a, direct: false, seconds: dd.get(a)! + along / w.speed };
  }

  private drivePath(c: { way: Way; pos: number; pt: XY }, arr: { node: number; direct: boolean },
    prev: Map<number, number>, snap: NonNullable<ReturnType<StaticEngine["snapDrive"]>>, origin: XY) {
    const coords: XY[] = [origin, snap.snapped];
    if (!arr.direct) coords.push(...pathTo(prev, arr.node).map((n) => this.xy[n]));
    coords.push(c.way.at(c.pos), c.pt);
    let metres = 0;
    for (let k = 2; k < coords.length; k++) metres += dist(coords[k - 1], coords[k]);
    return { coords: coords.map((p) => this.toLL(p)), metres };
  }

  private walkTo(c: { way: Way; pos: number }, wd: Map<number, number>) {
    const w = c.way, i = w.edgeIndex(c.pos), na = w.nodes[i], nb = w.nodes[i + 1];
    const opts: [number, number][] = [];
    if (wd.has(na)) opts.push([wd.get(na)! + (c.pos - w.cum[i]), na]);
    if (wd.has(nb)) opts.push([wd.get(nb)! + (w.cum[i + 1] - c.pos), nb]);
    if (!opts.length) return null;
    opts.sort((x, y) => x[0] - y[0]);
    return { m: opts[0][0] + w.width / 2, node: opts[0][1] };
  }

  private crossingCheck(c: { seg: Seg; way: Way; pos: number }, dest: XY) {
    const w = c.way, near = this.nearestCurbWay(dest, 45);
    if (!near || (near.way !== w && (!w.name || near.way.name !== w.name))) return { must_cross: false };
    const sameSide = near.way === w ? near.way.sideOf(dest) === c.seg.side : false;
    if (sameSide) return { must_cross: false };
    let best = Infinity;
    w.nodes.forEach((n, k) => { if (this.crossings.has(n)) best = Math.min(best, Math.abs(w.cum[k] - c.pos)); });
    if (best <= SAFE_CROSSING_SEARCH_M)
      return { must_cross: true, safe_crossing: true, crossing_distance_m: Math.round(best), penalty_m: best * 0.5 + 20 };
    return { must_cross: true, safe_crossing: false, penalty_m: UNSAFE_CROSSING_PENALTY_M };
  }

  private diverse<T extends { pt: XY }>(ranked: T[], k = 3, minSep = 35) {
    const chosen: T[] = [];
    for (const c of ranked) {
      if (chosen.every((o) => dist(o.pt, c.pt) >= minSep)) chosen.push(c);
      if (chosen.length === k) break;
    }
    return chosen;
  }

  private evidence(seg: Seg, vehicle: VehicleClass) {
    const status = STATUS[seg.status[vehicle]];
    return {
      status, legally_confirmed: status === "ALLOWED",
      reasons: seg.rules.map((rule) => ({ rule })), cautions: seg.cautions.map((rule) => ({ rule })),
      notes: seg.notes, sources: ["osm"], confidence: seg.confidence,
    };
  }

  curbAtDoor(destLL: LngLat, vehicle: VehicleClass = "taxi"): DoorInfo | null {
    const dest = this.toXY(destLL), near = this.nearestCurbWay(dest, 60);
    if (!near) return null;
    const w = near.way, side = w.sideOf(dest), pos = w.project(dest).pos;
    const seg = (this.segsByWaySide.get(`${w.i}:${side}`) ?? []).find((s) => s.start <= pos && pos <= s.end);
    if (!seg) return null;
    return { segment_id: seg.id, name: w.name, side, distance_m: Math.round(near.d), ...this.evidence(seg, vehicle) } as DoorInfo;
  }

  recommend(destLL: LngLat, originLL: LngLat | null, maxWalk = 450, vehicle: VehicleClass = "taxi"): RecResponse {
    const dest = this.toXY(destLL), origin = originLL ? this.toXY(originLL) : null;
    const ws = this.snapWalk(dest);
    if (!ws) return { results: [], unverified_candidates: [], message: "destination_outside_network", curb_at_door: this.curbAtDoor(destLL, vehicle) };
    const { d: wd, prev: wprev } = dijkstra(this.walkAdj, ws.sources, maxWalk * 1.6);
    const warnings: string[] = [];
    let ds: ReturnType<StaticEngine["snapDrive"]> = null, dd: Map<number, number> | null = null, dprev = new Map<number, number>();
    if (origin) {
      ds = this.snapDrive(origin);
      if (ds && ds.sources.size) ({ d: dd, prev: dprev } = dijkstra(this.driveAdj, ds.sources));
      else warnings.push("origin_outside_network");
    }
    let unreachable = 0;
    const score = (cands: ReturnType<StaticEngine["candidates"]>) => {
      const scored = [];
      for (const c of cands) {
        const walk = this.walkTo(c, wd);
        if (!walk || walk.m > maxWalk * 1.25) continue;
        let arr = null;
        if (dd) { arr = this.arrival(c, dd, ds); if (!arr) { unreachable++; continue; } }
        const cross = this.crossingCheck(c, dest);
        let sc = walk.m + ((cross as any).penalty_m ?? 0);
        if (arr) sc += arr.seconds * 1.2;
        if (c.seg.official) sc -= OFFICIAL_BONUS_M;
        sc += 60 * c.seg.cautions.filter((r) => r !== "NOT_SURVEYED").length;
        scored.push({ ...c, walk, arr, cross, score: sc });
      }
      return scored.sort((a, b) => a.score - b.score);
    };
    const build = (scored: ReturnType<typeof score>, avoid: { pt: XY }[] = []) => {
      const chosen = this.diverse(scored.filter((c) => avoid.every((o) => dist(o.pt, c.pt) >= 35)));
      const items: Recommendation[] = chosen.map((c, k) => {
        const nodes = pathTo(wprev, c.walk.node).reverse();
        const walkCoords: XY[] = [c.pt, c.way.at(c.pos), ...nodes.map((n) => this.xy[n]), ws.snapped, dest];
        const { penalty_m: _p, ...crossing } = c.cross as any;
        const item = {
          rank: k + 1, point: this.toLL(c.pt), segment_id: c.seg.id, street: c.way.name, side: c.seg.side,
          compass: c.way.compass(c.pos, c.seg.side), official: c.seg.official, length_m: +(c.seg.end - c.seg.start).toFixed(2),
          walk_m: Math.round(c.walk.m), walk_min: +(c.walk.m / WALK_SPEED / 60).toFixed(1),
          walk_route: walkCoords.map((p) => this.toLL(p)), crossing, score: +c.score.toFixed(1),
          ...this.evidence(c.seg, vehicle),
        } as Recommendation;
        if (c.arr && ds) {
          const dp = this.drivePath(c, c.arr, dprev, ds, origin!);
          Object.assign(item, { drive_route: dp.coords, drive_m: Math.round(dp.metres), drive_min: +(c.arr.seconds / 60).toFixed(1) });
        }
        return item;
      });
      return { items, chosen };
    };
    const green = this.candidates(dest, maxWalk, "nearest", vehicle, "A");
    const yellow = this.candidates(dest, maxWalk, "nearest", vehicle, "U");
    const g = build(score(green));
    const y = build(score(yellow), g.chosen);
    return {
      results: g.items, unverified_candidates: y.items, curb_at_door: this.curbAtDoor(destLL, vehicle),
      message: g.items.length ? null : "no_verified_spot", warnings,
      diagnostics: { candidates_in_radius: green.length, unreachable_by_car: unreachable, ranked: g.items.length, max_walk_m: maxWalk },
    };
  }

  nearestStops(originLL: LngLat, radius = 1200, vehicle: VehicleClass = "taxi"): RecResponse {
    const origin = this.toXY(originLL), ds = this.snapDrive(origin);
    if (!ds || !ds.sources.size) return { results: [], unverified_candidates: [], message: "origin_outside_network" };
    const { d: dd, prev } = dijkstra(this.driveAdj, ds.sources);
    const rank = (status: Code, avoid: { pt: XY }[] = []) => {
      const scored = [];
      for (const c of this.candidates(origin, radius, "first", vehicle, status)) {
        const arr = this.arrival(c, dd, ds);
        if (!arr || avoid.some((o) => dist(o.pt, c.pt) < 50)) continue;
        scored.push({ ...c, arr, score: arr.seconds - (c.seg.official ? OFFICIAL_BONUS_M / 8 : 0)
          + 8 * c.seg.cautions.filter((r) => r !== "NOT_SURVEYED").length });
      }
      scored.sort((a, b) => a.score - b.score);
      const chosen = this.diverse(scored, 3, 50);
      const items: Recommendation[] = chosen.map((c, k) => {
        const dp = this.drivePath(c, c.arr, prev, ds, origin);
        return {
          rank: k + 1, point: this.toLL(c.pt), segment_id: c.seg.id, street: c.way.name, side: c.seg.side,
          compass: c.way.compass(c.pos, c.seg.side), official: c.seg.official,
          drive_route: dp.coords, drive_m: Math.round(dp.metres), drive_min: +(c.arr.seconds / 60).toFixed(1),
          length_m: +(c.seg.end - c.seg.start).toFixed(2), ...this.evidence(c.seg, vehicle),
        } as Recommendation;
      });
      return { items, chosen };
    };
    const g = rank("A");
    const y = rank("U", g.chosen);
    return { results: g.items, unverified_candidates: y.items, message: g.items.length ? null : "no_verified_spot" };
  }
}

// ------------------------------------------------------------------- search
const TR: Record<string, string> = { ə: "e", ı: "i", ö: "o", ü: "u", ş: "s", ç: "c", ğ: "g", İ: "i", Ə: "e", Ö: "o", Ü: "u", Ş: "s", Ç: "c", Ğ: "g" };
export const normText = (s: string) => (s || "").replace(/[əıöüşçğİƏÖÜŞÇĞ]/g, (ch) => TR[ch]).toLowerCase().trim();

export function searchItems<T extends { name: string; kind: string; _n: string }>(items: T[], q: string, limit = 8) {
  const nq = normText(q);
  if (nq.length < 2) return [];
  const scored: [number, number, number, T][] = [];
  for (const it of items) {
    const n = it._n;
    let s: number;
    if (n.startsWith(nq) || normText(it.name).startsWith(nq)) s = 0;
    else if (` ${n}`.includes(` ${nq}`)) s = 1;
    else if (n.includes(nq)) s = 2;
    else if (nq.split(/\s+/).every((tok) => n.includes(tok))) s = 3;
    else continue;
    scored.push([s, it.kind === "street" ? 1 : 0, it.name.length, it]);
  }
  scored.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
  return scored.slice(0, limit).map(([, , , it]) => { const { _n, ...rest } = it; return rest; });
}

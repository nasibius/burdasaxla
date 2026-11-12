"""Unmet-demand recommendations: "many drivers ask for this area, but there is nowhere legal to stop".

Real demand: every drop-off/pick-up search on the live API is logged as an AGGREGATE grid cell
(~100 m) with whether a legally confirmed stopping place was found. No driver position, no exact
destination, no IP, no user id is stored.

An area becomes a "build a new stopping place here" recommendation when it has at least
`min_unmet` unmet requests and no legally confirmed (non-simulated) stopping place within
`legal_radius_m`. Each recommendation suggests the nearest curb that is NOT statutorily
prohibited, as a site for the authority to survey. It is a planning signal, not legal approval.

Demo mode (BURDASAXLA_DEMO_SURVEY=1) adds SIMULATED EXAMPLE hotspots (invented request counts
at real OSM places) so the static demo is not empty; every one carries is_synthetic_example=True.
"""
import hashlib
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import demo

CELL_LAT = 0.0009   # ~100 m
CELL_LON = 0.0012   # ~100 m at 40.4 N
MIN_UNMET = 5
LEGAL_RADIUS_M = 150
SITE_RADIUS_M = 200
MIN_SITE_LENGTH_M = 12
BUSY_KINDS = ("hotel", "supermarket", "bank", "platform", "government", "school", "post_office",
              "mall", "hospital", "clinic", "university", "station", "theatre", "museum")

SCHEMA = """
CREATE TABLE IF NOT EXISTS demand_requests (
    id INTEGER PRIMARY KEY, cell TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
    mode TEXT NOT NULL, vehicle TEXT NOT NULL, served INTEGER NOT NULL, hour TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS demand_cell ON demand_requests(cell);
"""


def cell_of(lon, lat):
    i, j = math.floor(lat / CELL_LAT), math.floor(lon / CELL_LON)
    return f"{i}:{j}", (j + 0.5) * CELL_LON, (i + 0.5) * CELL_LAT


def _m(a, b):
    """Approximate metres between two (lon, lat) points (fine at city scale)."""
    kx = 111_320 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * 110_574)


def _dist_to_line(p, coords):
    kx = 111_320 * math.cos(math.radians(p[1]))
    px, py = 0.0, 0.0
    pts = [((c[0] - p[0]) * kx, (c[1] - p[1]) * 110_574) for c in coords]
    best = math.inf
    for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
        best = min(best, math.hypot(ax + t * dx - px, ay + t * dy - py))
    return best


class DemandStore:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def log(self, destination, mode, vehicle, served):
        cell, lon, lat = cell_of(*destination)
        hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00Z")
        with self.connect() as conn:
            conn.execute("INSERT INTO demand_requests(cell,lat,lon,mode,vehicle,served,hour) VALUES (?,?,?,?,?,?,?)",
                         (cell, lat, lon, mode, vehicle, int(bool(served)), hour))

    def cells(self):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT cell, lat, lon, COUNT(*) AS requests, SUM(1 - served) AS unmet, "
                "MIN(hour) AS first_seen, MAX(hour) AS last_seen FROM demand_requests GROUP BY cell")]


def served(result):
    """A request is served only by a legally confirmed spot (simulated demo green never counts)."""
    return any(r.get("legally_confirmed") for r in result.get("results", []))


def simulated_cells(model):
    """SIMULATED EXAMPLE demand at real OSM places, deterministic, clearly labelled."""
    picks = sorted((it for it in model.search_items if it.get("kind") in BUSY_KINDS),
                   key=lambda it: hashlib.sha1(it["name"].encode()).hexdigest())
    out, seen = [], set()
    for it in picks:
        cell, lon, lat = cell_of(it["lon"], it["lat"])
        if cell in seen:
            continue
        seen.add(cell)
        h = int(hashlib.sha1(it["name"].encode()).hexdigest(), 16)
        req = 25 + h % 90
        out.append({"cell": cell, "lat": lat, "lon": lon, "requests": req, "unmet": req - h % 7,
                    "first_seen": None, "last_seen": None, "is_synthetic_example": True})
        if len(out) == 10:
            break
    return out


def _place_name(model, pt, radius=150):
    best = None
    for it in model.search_items:
        if it.get("kind") == "street":
            continue
        d = _m(pt, (it["lon"], it["lat"]))
        if d <= radius and (best is None or d < best[0]):
            best = (d, it["name"])
    return best[1] if best else None


def hotspots(model, cells, vehicle="taxi", min_unmet=MIN_UNMET, legal_radius_m=LEGAL_RADIUS_M):
    legal = [s for s in model.segments.values()
             if (s["status_by_vehicle"][vehicle] == "ALLOWED" and not s.get("simulated")) or s["official"]]
    usable = [s for s in model.segments.values()
              if s["status_by_vehicle"][vehicle] != "PROHIBITED" and s["length_m"] >= MIN_SITE_LENGTH_M]
    out = []
    for c in cells:
        if (c["unmet"] or 0) < min_unmet:
            continue
        pt = (c["lon"], c["lat"])
        nearest_legal = min((_dist_to_line(pt, s["coords"]) for s in legal), default=None)
        if nearest_legal is not None and nearest_legal <= legal_radius_m:
            continue
        site = min(((_dist_to_line(pt, s["coords"]), s) for s in usable), key=lambda x: x[0], default=None)
        suggestion = None
        if site and site[0] <= SITE_RADIUS_M:
            d, s = site
            suggestion = {"segment_id": s["id"], "name": s["name"], "side": s["side"], "compass": s.get("compass"),
                          "length_m": round(s["length_m"], 1), "distance_m": round(d),
                          "current_status": s["status_by_vehicle"][vehicle], "simulated_green": bool(s.get("simulated")),
                          "cautions": sorted({r["rule"] for r in s["cautions"]}), "geometry": s["coords"]}
        sim = bool(c.get("is_synthetic_example"))
        out.append({
            "id": ("sim-" if sim else "") + c["cell"], "center": [round(c["lon"], 6), round(c["lat"], 6)],
            "place": _place_name(model, pt), "requests": c["requests"], "unmet": c["unmet"],
            "unmet_share": round(c["unmet"] / c["requests"], 2) if c["requests"] else None,
            "nearest_legal_m": None if nearest_legal is None else round(nearest_legal),
            "first_seen": c.get("first_seen"), "last_seen": c.get("last_seen"),
            "suggested_site": suggestion, "is_synthetic_example": sim,
            "recommendation": "build_new_stopping_place" if suggestion else "no_usable_curb_nearby",
        })
    out.sort(key=lambda h: (-h["unmet"], h["id"]))
    return out


def report(model, store=None, vehicle="taxi", min_unmet=MIN_UNMET):
    real = store.cells() if store else []
    cells = real + (simulated_cells(model) if demo.enabled() else [])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "vehicle": vehicle, "min_unmet": min_unmet, "legal_radius_m": LEGAL_RADIUS_M, "site_radius_m": SITE_RADIUS_M,
        "logged_requests": sum(c["requests"] for c in real), "logged_cells": len(real),
        "demo": demo.enabled(),
        "hotspots": hotspots(model, cells, vehicle, min_unmet),
        "method": ("Requests are logged per ~100 m cell by the live API (no driver position or identity). "
                   f"A hotspot has at least {min_unmet} requests without a legally confirmed spot and no confirmed "
                   f"legal stopping place within {LEGAL_RADIUS_M} m. The suggested site is the nearest curb within "
                   f"{SITE_RADIUS_M} m that is not prohibited by statute; it still needs a field survey and an official "
                   "decision. Simulated demo green never counts as legal supply."),
    }

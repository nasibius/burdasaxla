"""SYNTHETIC TEST FIXTURES — NOT REAL-WORLD OBSERVATIONS.

Small invented street networks placed near 28 May only so the projection maths is realistic.
None of these streets, signs, markings or surveys exist; they are never written to the app's
database or shown on the map. Every synthetic observation uses source="synthetic_test".

Coordinates are metres (x east, y north) from an origin at 40.38 N, 49.85 E.
"""
import math

LAT0, LON0 = 40.38, 49.85
M_LAT = 1 / 111_320
M_LON = 1 / (111_320 * math.cos(math.radians(LAT0)))
SYNTHETIC = "synthetic_test"
_next_id = [1000]


def ll(x, y):
    return LON0 + x * M_LON, LAT0 + y * M_LAT


def node(i, x, y, **tags):
    lon, lat = ll(x, y)
    return {"type": "node", "id": i, "lon": lon, "lat": lat, "tags": tags}


def way(i, nodes, **tags):
    return {"type": "way", "id": i, "nodes": nodes, "tags": tags}


def raw(elements):
    s, w = ll(-300, -300)[1], ll(-300, -300)[0]
    n, e = ll(700, 400)[1], ll(700, 400)[0]
    return {"elements": elements, "bbox": [s, w, n, e], "osm3s": {"timestamp_osm_base": "synthetic"}}


def main_street(**extra_way101_tags):
    """    Way 101 "Synthetic street" residential two-way  A(0,0)-B(100,0)-C(200,0)-D(300,0)
           B = zebra crossing, C = 4-way intersection with way 102.
    Way 102 tertiary oneway northbound E(200,-100)-C-F(200,100)
    Way 103 residential bridge D(300,0)-G(400,0)  (no lanes tag)
    Bus stop sign at (60,-8): south side = RIGHT side of way 101.
    """
    return raw([
        node(1, 0, 0), node(2, 100, 0, highway="crossing"), node(3, 200, 0), node(4, 300, 0),
        node(5, 200, -100), node(6, 200, 100), node(7, 400, 0),
        node(8, 60, -8, highway="bus_stop", name="Synthetic stop"),
        way(101, [1, 2, 3, 4], highway="residential", name="Synthetic street", **extra_way101_tags),
        way(102, [5, 3, 6], highway="tertiary", oneway="yes", name="Synthetic one-way"),
        way(103, [4, 7], highway="residential", bridge="yes", name="Synthetic bridge"),
    ])


def obs(kind, geometry, status="verified", **props):
    _next_id[0] += 1
    return {"id": _next_id[0], "kind": kind, "status": status, "source": SYNTHETIC, "verified_at": "2026-11-12",
            "geometry": geometry, "props": props, "note": "synthetic", "observer": "pytest"}


def point(x, y):
    lon, lat = ll(x, y)
    return {"type": "Point", "coordinates": [lon, lat]}


def line(*pts):
    return {"type": "LineString", "coordinates": [list(ll(x, y)) for x, y in pts]}


def polygon(x0, y0, x1, y1):
    (w, s), (e, n) = ll(x0, y0), ll(x1, y1)
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def survey(x0=-150, y0=-150, x1=550, y1=150, **kw):
    return obs("survey_area", polygon(x0, y0, x1, y1), **kw)


def seg_at(m, way_id, side, pos):
    for seg in m.segments_by_way[(way_id, side)]:
        if seg["start_m"] <= pos < seg["end_m"]:
            return seg
    raise AssertionError(f"no segment at {pos}")


def rules_at(m, way_id, side, pos, field="reasons"):
    return {r["rule"] for r in seg_at(m, way_id, side, pos)[field]}

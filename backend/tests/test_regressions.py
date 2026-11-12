"""Regression tests for bugs found in the QA pass."""
from app.citymodel import CityModel
from app.dropoff import Recommender
from tests.test_engine import build_raw, ll, node, rules_at, status_at, survey


def split_street_raw(reverse_second=False):
    """Street split into two OSM ways at P1 (not an intersection); real intersection at P2."""
    els = [node(1, 0, 50), node(2, 100, 50), node(3, 250, 50), node(4, 250, 0), node(5, 250, 100)]
    second = [3, 2] if reverse_second else [2, 3]
    els += [
        {"type": "way", "id": 301, "nodes": [1, 2], "tags": {"highway": "residential", "name": "Split"}},
        {"type": "way", "id": 302, "nodes": second, "tags": {"highway": "residential", "name": "Split"}},
        {"type": "way", "id": 303, "nodes": [4, 3, 5], "tags": {"highway": "residential", "name": "Cross"}},
    ]
    s, w = ll(-200, -200)[1], ll(-200, -200)[0]
    n, e = ll(600, 300)[1], ll(600, 300)[0]
    return {"elements": els, "bbox": [s, w, n, e]}


def sign_327(x, y):
    lon, lat = ll(x, y)
    return {"id": 9, "kind": "sign_3_27", "status": "verified", "source": "test", "verified_at": "2026-11-12",
            "geometry": {"type": "Point", "coordinates": [lon, lat]}, "props": {}}


def test_sign_zone_continues_across_way_split():
    m = CityModel(split_street_raw(), [survey(), sign_327(20, 45)])  # south curb = right side
    assert "SIGN_3_27" in rules_at(m, 301, "right", 60)
    assert "SIGN_3_27" in rules_at(m, 302, "right", 80)  # continued past the split
    assert status_at(m, 301, "left", 60)["status"] == "VERIFIED"  # other side untouched


def test_sign_zone_continues_onto_reversed_way():
    m = CityModel(split_street_raw(reverse_second=True), [survey(), sign_327(20, 45)])
    w = m.ways[302]
    pos_mid = w.length - 70  # 70 m east of P1, measured on the reversed way
    assert "SIGN_3_27" in rules_at(m, 302, "left", pos_mid)  # same physical (south) curb
    assert status_at(m, 302, "right", pos_mid)["status"] == "VERIFIED"


def test_rail_platform_is_not_a_bus_stop():
    raw = build_raw()
    raw["elements"].append(node(50, 160, 10, public_transport="platform", railway="platform", name="Rail"))
    m = CityModel(raw, [survey()])
    assert not any(b["name"] == "Rail" for b in m.bus_stops)


def test_bad_feature_does_not_break_build():
    bad = {"id": 77, "kind": "survey_area", "status": "verified", "source": "test",
           "geometry": {"type": "Polygon", "coordinates": []}, "props": {}}
    m = CityModel(build_raw(), [survey(), bad])
    assert 77 in m.feature_errors and m.segments


def test_driver_on_same_edge_goes_straight():
    m = CityModel(build_raw(), [survey()])
    rec = Recommender(m)
    # driver heading east on way 101 at x=5, south (right) curb is legal from ~0..45 m
    out = rec.recommend(list(ll(30, -25)), list(ll(5, -1)))
    top = out["results"][0]
    assert top["drive_m"] < 60, top["drive_m"]

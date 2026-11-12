"""Rule-engine and recommender tests on a tiny synthetic street network.

Layout (metres, x east / y north), origin near 28 May:
    Way 1  "Test küçəsi" residential, two-way  A(0,0)-B(100,0)-C(200,0)-D(300,0)
           B is a zebra crossing, C an intersection.
    Way 2  tertiary, oneway northbound         E(200,-100)-C(200,0)-F(200,100)
    Way 3  residential bridge                  D(300,0)-G(400,0)
    Bus stop sign at (60,-8)  -> south side = RIGHT side of way 1.
"""
import math

import pytest

from app.citymodel import PROHIBITED, UNKNOWN, VERIFIED, CityModel
from app.dropoff import Recommender

LAT0, LON0 = 40.38, 49.85
M_LAT = 1 / 111_320
M_LON = 1 / (111_320 * math.cos(math.radians(LAT0)))


def ll(x, y):
    return LON0 + x * M_LON, LAT0 + y * M_LAT


def node(i, x, y, **tags):
    lon, lat = ll(x, y)
    return {"type": "node", "id": i, "lon": lon, "lat": lat, "tags": tags}


def build_raw():
    els = [
        node(1, 0, 0), node(2, 100, 0, highway="crossing"), node(3, 200, 0), node(4, 300, 0),
        node(5, 200, -100), node(6, 200, 100), node(7, 400, 0),
        node(8, 60, -8, highway="bus_stop", name="Test dayanacağı"),
        {"type": "way", "id": 101, "nodes": [1, 2, 3, 4], "tags": {"highway": "residential", "name": "Test küçəsi"}},
        {"type": "way", "id": 102, "nodes": [5, 3, 6], "tags": {"highway": "tertiary", "oneway": "yes", "name": "Bir"}},
        {"type": "way", "id": 103, "nodes": [4, 7], "tags": {"highway": "residential", "bridge": "yes"}},
    ]
    s, w = ll(-200, -200)[1], ll(-200, -200)[0]
    n, e = ll(600, 300)[1], ll(600, 300)[0]
    return {"elements": els, "bbox": [s, w, n, e], "osm3s": {"timestamp_osm_base": "test"}}


def survey(fid=1):
    (w, s), (e, n) = ll(-100, -150), ll(500, 150)
    return {"id": fid, "kind": "survey_area", "status": "verified", "source": "test", "verified_at": "2026-11-12",
            "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}, "props": {}}


def status_at(m, way_id, side, pos):
    for seg in m.segments_by_way[(way_id, side)]:
        if seg["start_m"] <= pos < seg["end_m"]:
            return seg
    raise AssertionError(f"no segment at {pos}")


def rules_at(m, way_id, side, pos):
    return {r["rule"] for r in status_at(m, way_id, side, pos)["reasons"]}


@pytest.fixture
def model():
    return CityModel(build_raw(), [survey()])


def test_no_prohibition_without_survey_is_unknown_not_green():
    m = CityModel(build_raw(), [])
    assert status_at(m, 101, "right", 20)["status"] == UNKNOWN


def test_clear_curb_inside_survey_is_verified(model):
    assert status_at(model, 101, "right", 20)["status"] == VERIFIED


def test_crossing_applies_5m_before_in_travel_direction(model):
    # right side travels east: zone [93, 102]
    assert "PEDESTRIAN_CROSSING" in rules_at(model, 101, "right", 94)
    assert status_at(model, 101, "right", 104)["status"] == VERIFIED
    # left side travels west: zone [98, 107]
    assert "PEDESTRIAN_CROSSING" in rules_at(model, 101, "left", 106)
    assert status_at(model, 101, "left", 94)["status"] == VERIFIED


def test_bus_stop_only_on_its_side(model):
    assert "BUS_STOP" in rules_at(model, 101, "right", 60)
    assert status_at(model, 101, "left", 60)["status"] == VERIFIED
    assert status_at(model, 101, "right", 80)["status"] == VERIFIED  # 15 m radius ends at 75


def test_intersection_buffer_uses_crossed_road_width(model):
    # tertiary oneway width 6 -> half 3 + 5 = 8
    assert "INTERSECTION" in rules_at(model, 101, "right", 193)
    assert status_at(model, 101, "right", 190)["status"] == VERIFIED


def test_bridge_whole_way(model):
    assert status_at(model, 103, "left", 50)["status"] == PROHIBITED
    assert "BRIDGE_TUNNEL" in rules_at(model, 103, "right", 10)


def test_oneway_left_side_allowed_with_note(model):
    seg = status_at(model, 102, "left", 30)
    assert seg["status"] == VERIFIED
    assert any(n["rule"] == "ONE_WAY_LEFT_SIDE" for n in seg["notes"])
    assert seg["travel"] == "fwd"


def _sign(kind, fid=2):
    lon, lat = ll(20, -5)
    return {"id": fid, "kind": kind, "status": "verified", "source": "test", "verified_at": "2026-11-12",
            "geometry": {"type": "Point", "coordinates": [lon, lat]}, "props": {}}


def test_327_and_328_differ():
    m27 = CityModel(build_raw(), [survey(), _sign("sign_3_27")])
    m28 = CityModel(build_raw(), [survey(), _sign("sign_3_28")])
    s27, s28 = status_at(m27, 101, "right", 40), status_at(m28, 101, "right", 40)
    assert s27["status"] == PROHIBITED and "SIGN_3_27" in {r["rule"] for r in s27["reasons"]}
    assert s28["status"] == VERIFIED and any(n["rule"] == "SIGN_3_28" for n in s28["notes"])
    # 3.27 zone runs to the next intersection (C at 200 m) on its side only
    assert "SIGN_3_27" in rules_at(m27, 101, "right", 150)
    assert status_at(m27, 101, "left", 40)["status"] == VERIFIED
    assert status_at(m27, 101, "right", 10)["status"] == VERIFIED  # before the sign


def test_pending_feature_is_ignored():
    f = _sign("sign_3_27")
    f["status"] = "pending"
    m = CityModel(build_raw(), [survey(), f])
    assert status_at(m, 101, "right", 40)["status"] == VERIFIED


def test_recommendation_prefers_same_side_and_is_reachable(model):
    rec = Recommender(model)
    dest = list(ll(30, -25))
    origin = list(ll(280, 5))
    out = rec.recommend(dest, origin)
    assert out["results"], out
    top = out["results"][0]
    assert top["status"] == VERIFIED
    assert top["side"] == "right"  # destination is south = right side, no street crossing
    assert top["drive_route"] and top["walk_route"]
    assert len(out["results"]) <= 3
    for r in out["results"]:
        assert model.segments[r["segment_id"]]["status"] == VERIFIED


def test_no_spot_reported():
    m = CityModel(build_raw(), [])  # nothing verified
    out = Recommender(m).recommend(list(ll(30, -25)), None)
    assert out["results"] == [] and out["message"] == "no_verified_spot"


def test_driver_nearest_respects_oneway(model):
    rec = Recommender(model)
    out = rec.nearest_stops(list(ll(200, -60)))  # on oneway northbound
    assert out["results"]
    for r in out["results"]:
        assert model.segments[r["segment_id"]]["status"] == VERIFIED

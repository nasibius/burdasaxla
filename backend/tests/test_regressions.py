"""Regression tests for bugs found in QA passes. SYNTHETIC fixtures only (tests/fixtures.py)."""
from app.citymodel import ALLOWED, CityModel
from app.dropoff import Recommender
from tests.fixtures import ll, main_street, node, obs, point, raw, rules_at, seg_at, survey, way


def split_street_raw(reverse_second=False):
    """Street split into two OSM ways at P1 (not an intersection); real intersection at P2."""
    second = [3, 2] if reverse_second else [2, 3]
    return raw([node(1, 0, 50), node(2, 100, 50), node(3, 250, 50), node(4, 250, 0), node(5, 250, 100),
                way(301, [1, 2], highway="residential", name="Split"),
                way(302, second, highway="residential", name="Split"),
                way(303, [4, 3, 5], highway="residential", name="Cross")])


def test_sign_zone_continues_across_way_split():
    m = CityModel(split_street_raw(), [survey(-50, 0, 400, 120), obs("sign_3_27", point(20, 45))])
    assert "SIGN_3_27" in rules_at(m, 301, "right", 60)
    assert "SIGN_3_27" in rules_at(m, 302, "right", 80)
    assert seg_at(m, 301, "left", 60)["status"] == ALLOWED


def test_sign_zone_continues_onto_reversed_way():
    m = CityModel(split_street_raw(reverse_second=True), [survey(-50, 0, 400, 120), obs("sign_3_27", point(20, 45))])
    pos_mid = m.ways[302].length - 70
    assert "SIGN_3_27" in rules_at(m, 302, "left", pos_mid)
    assert seg_at(m, 302, "right", pos_mid)["status"] == ALLOWED


def test_driver_on_same_edge_goes_straight():
    m = CityModel(main_street(), [survey()])
    out = Recommender(m).recommend(list(ll(30, -25)), list(ll(5, -1)))
    assert out["results"][0]["drive_m"] < 60

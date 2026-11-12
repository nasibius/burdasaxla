"""Recommendation trust rules. SYNTHETIC fixtures only (tests/fixtures.py)."""
from app.citymodel import ALLOWED, UNVERIFIED, CityModel
from app.dropoff import Recommender
from tests.fixtures import line, ll, main_street, obs, survey

DEST, ORIGIN = list(ll(30, -25)), list(ll(280, 5))


def test_confirmed_results_are_green_and_carry_evidence():
    m = CityModel(main_street(), [survey()])
    out = Recommender(m).recommend(DEST, ORIGIN)
    assert 1 <= len(out["results"]) <= 3
    for r in out["results"]:
        assert r["status"] == ALLOWED and r["legally_confirmed"] is True
        assert m.segments[r["segment_id"]]["status"] == ALLOWED
        assert r["sources"] and r["confidence"] == "verified_observation"
        assert r["coverage"] and r["coverage"][0]["kind"] == "survey_area"
        assert isinstance(r["reasons"], list) and isinstance(r["cautions"], list)


def test_without_survey_nothing_is_confirmed():
    m = CityModel(main_street(), [])
    out = Recommender(m).recommend(DEST, ORIGIN)
    assert out["results"] == [] and out["message"] == "no_verified_spot"
    assert out["unverified_candidates"], "yellow options are offered separately"
    for r in out["unverified_candidates"]:
        assert r["status"] == UNVERIFIED and r["legally_confirmed"] is False
        assert "NOT_SURVEYED" in {c["rule"] for c in r["cautions"]}


def test_prohibited_curbs_never_recommended():
    m = CityModel(main_street(), [])
    out = Recommender(m).recommend(DEST, ORIGIN)
    for r in out["results"] + out["unverified_candidates"]:
        assert m.segments[r["segment_id"]]["status_by_vehicle"]["taxi"] != "PROHIBITED"


def test_taxi_stand_eligible_for_taxi_but_never_for_private():
    m = CityModel(main_street(), [survey(), obs("taxi_stand", line((10, -5), (40, -5)))])
    rec = Recommender(m)
    stand = {s for s, seg in m.segments.items() if seg["status_by_vehicle"] == {"taxi": ALLOWED, "private": "PROHIBITED"}}
    assert stand
    center = m.ways[101].curb_point(25, "right")
    taxi_ids = {c["seg"]["id"] for c in rec._candidates(center, 50, "taxi", ALLOWED)}
    private_ids = {c["seg"]["id"] for st in (ALLOWED, UNVERIFIED) for c in rec._candidates(center, 50, "private", st)}
    assert stand & taxi_ids and not stand & private_ids
    private = rec.recommend(DEST, ORIGIN, vehicle="private")
    assert not any(r["segment_id"] in stand for r in private["results"] + private["unverified_candidates"])


def test_door_status_reports_reason_and_legal_ref():
    m = CityModel(main_street(), [survey()])
    out = Recommender(m).recommend(list(ll(60, -20)), None)   # in front of the synthetic bus stop
    door = out["curb_at_door"]
    assert door["status"] == "PROHIBITED"
    assert door["reasons"][0]["rule"] == "BUS_STOP" and "52.IV.7" in door["reasons"][0]["legal_ref"]


def test_driver_mode_separates_confirmed_and_unverified():
    m = CityModel(main_street(), [survey(-150, -150, 150, 150)])
    out = Recommender(m).nearest_stops(list(ll(200, -60)))
    assert all(r["status"] == ALLOWED for r in out["results"])
    assert all(r["status"] == UNVERIFIED for r in out["unverified_candidates"])

"""B2G planning acceptance tests (brief §9). SYNTHETIC fixtures only — see tests/fixtures.py.

Synthetic layout: main_street() plus invented destinations ("SYNTH ..." names) south and north of it.
"""
from app.citymodel import CityModel
from app.dropoff import Recommender
from app.planning import Planner, attach_reviews
from tests.fixtures import line, main_street, node, obs, survey


def synth_raw():
    r = main_street()
    r["elements"] += [
        node(500, 30, -30, amenity="cafe", name="SYNTH cafe west"),
        node(501, 60, -30, amenity="pharmacy", name="SYNTH pharmacy"),
        node(502, 270, -30, shop="bakery", name="SYNTH bakery east"),
        node(503, 120, 40, amenity="bus_station", name="SYNTH station"),
    ]
    # a sidewalk spur so the destinations connect to the walk network
    r["elements"] += [node(510, 30, -10), node(511, 60, -10), node(512, 270, -10), node(513, 120, 20),
                      {"type": "way", "id": 900, "nodes": [1, 510], "tags": {"highway": "footway"}},
                      {"type": "way", "id": 901, "nodes": [510, 511], "tags": {"highway": "footway"}},
                      {"type": "way", "id": 902, "nodes": [4, 512], "tags": {"highway": "footway"}},
                      {"type": "way", "id": 903, "nodes": [2, 513], "tags": {"highway": "footway"}}]
    return r


AREA_UNKNOWN = {"id": "synthetic-area", "inventory_status": "unknown"}
AREA_COMPLETE = {"id": "synthetic-area", "inventory_status": "complete", "inventory_source_url": "https://example.org/synthetic"}
WEST_ZONE = obs("official_zone", line((5, -5), (40, -5)))   # official zone at the west end, south curb


def states(result):
    return {r["name"]: r["state"] for r in result["coverage"]}


def test_b2g_01_no_inventory_means_unknown_not_underserved():
    r = Planner(CityModel(synth_raw(), []), area=AREA_UNKNOWN).run(300)
    assert r["summary"]["coverage_states"]["POTENTIAL_COVERAGE_GAP"] == 0
    assert r["summary"]["coverage_states"]["INVENTORY_UNKNOWN"] >= 3
    assert r["candidates"] == [] and r["survey_tasks"]
    assert r["summary"]["served_share"] is None


def test_b2g_02_reachable_official_zone_is_served_even_with_incomplete_inventory():
    r = Planner(CityModel(synth_raw(), [WEST_ZONE]), area=AREA_UNKNOWN).run(300)
    s = states(r)
    assert s["SYNTH cafe west"] == "SERVED"
    assert next(x for x in r["coverage"] if x["name"] == "SYNTH cafe west")["distance_m"] <= 300


def test_b2g_03_gap_only_when_inventory_complete():
    m = CityModel(synth_raw(), [WEST_ZONE])
    unknown = states(Planner(m, area=AREA_UNKNOWN).run(150))
    complete = Planner(m, area=AREA_COMPLETE).run(150)
    assert unknown["SYNTH bakery east"] == "INVENTORY_UNKNOWN"
    assert states(complete)["SYNTH bakery east"] == "POTENTIAL_COVERAGE_GAP"
    rec = next(x for x in complete["coverage"] if x["name"] == "SYNTH bakery east")
    assert rec["distance_m"] > 150


def test_b2g_04_unsurveyed_candidate_is_data_collection_needed_without_score():
    r = Planner(CityModel(synth_raw(), [WEST_ZONE]), area=AREA_COMPLETE).run(150)
    assert r["candidates"]
    for c in r["candidates"]:
        if c["current_legal_status"] == "UNVERIFIED":
            assert c["candidate_class"] == "DATA_COLLECTION_NEEDED" and c["score"] is None and c["rank"] is None
            assert c["officially_approved"] is False


def test_b2g_04b_surveyed_curb_can_be_screened_with_score():
    m = CityModel(synth_raw(), [WEST_ZONE, survey()])
    r = Planner(m, area=AREA_COMPLETE).run(150)
    screened = [c for c in r["candidates"] if c["candidate_class"] == "SCREENED_FOR_FURTHER_STUDY"]
    assert screened and all(c["score"] is not None and c["rank"] for c in screened)


def test_b2g_05_prohibited_curbs_are_never_candidates():
    r = Planner(CityModel(synth_raw(), [WEST_ZONE, survey()]), area=AREA_COMPLETE).run(150)
    assert all(c["current_legal_status"] != "PROHIBITED" for c in r["candidates"])
    assert any(c["exclusions_in_cluster"].get("statutory prohibition") for c in r["candidates"])


def test_b2g_06_candidates_never_become_driver_recommendations():
    m = CityModel(synth_raw(), [WEST_ZONE])
    r = Planner(m, area=AREA_COMPLETE).run(150)
    cand_segments = {c["segment_id"] for c in r["candidates"] if c["candidate_class"] == "DATA_COLLECTION_NEEDED"}
    from tests.fixtures import ll
    out = Recommender(m).recommend(list(ll(270, -30)), None)
    assert not cand_segments & {x["segment_id"] for x in out["results"]}


def test_b2g_07_reviews_survive_recompute():
    m = CityModel(synth_raw(), [])
    r1 = Planner(m, area=AREA_UNKNOWN).run(300)
    tid = r1["survey_tasks"][0]["id"]
    review = [{"target_id": tid, "action": "reject", "reason": "synthetic", "reviewer": "pytest", "reviewed_at": "x"}]
    r2 = attach_reviews(Planner(m, area=AREA_UNKNOWN).run(300), review)
    assert next(t for t in r2["survey_tasks"] if t["id"] == tid)["review"]["action"] == "reject"


def test_b2g_10_demand_not_measured_is_explicit():
    r = Planner(CityModel(synth_raw(), []), area=AREA_UNKNOWN).run(300)
    assert r["demand_measured"] is False
    assert all(t["measured_activity"] == "not_measured" for t in r["survey_tasks"])
    assert all("measured_activity" in t["factors_missing"] for t in r["survey_tasks"])
    assert all(t["access_nodes_are_proxy"] for t in r["survey_tasks"])


def test_measured_activity_raises_survey_priority():
    from tests.fixtures import ll
    m = CityModel(synth_raw(), [])
    lon, lat = ll(270, -30)
    act = [{"status": "verified", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "pickups": 40,
            "dropoffs": 60, "period_start": "2026-11-10T08:00:00", "period_end": "2026-11-10T10:00:00"}]
    r = Planner(m, act, area=AREA_UNKNOWN).run(300)
    east = next(t for t in r["survey_tasks"] if any("bakery" in k for k in t["access_kinds"]))
    assert east["measured_activity"]["per_hour"] == 50.0
    assert east["factors"]["measured_activity"] == 1.0 and r["demand_measured"] is True


def test_unavailable_factor_is_not_scored_as_zero():
    from app.planning import _weighted
    score, used, missing = _weighted({"a": 1.0, "b": None}, {"a": 0.5, "b": 0.5})
    assert score == 100.0 and missing == ["b"]


def test_network_unreliable_destination():
    r = synth_raw()
    r["elements"].append(node(599, 600, 300, amenity="cafe", name="SYNTH island"))  # far from any path
    res = Planner(CityModel(r, []), area=AREA_UNKNOWN).run(300)
    assert states(res)["SYNTH island"] == "NETWORK_UNRELIABLE"

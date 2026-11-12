"""Rule engine tests (Law 517-IQ, verified text). Uses SYNTHETIC fixtures only — see tests/fixtures.py."""
from app.citymodel import ALLOWED, PROHIBITED, UNVERIFIED, CityModel
from tests.fixtures import line, main_street, node, obs, point, raw, rules_at, seg_at, survey, way


def model(features=(), **way_tags):
    return CityModel(main_street(**way_tags), [survey(), *features])


# ----------------------------------------------------------- 3-state model
def test_missing_sign_data_is_yellow_not_green():
    m = CityModel(main_street(), [])  # no survey, no signs
    seg = seg_at(m, 101, "right", 20)
    assert seg["status"] == UNVERIFIED
    assert "NOT_SURVEYED" in {r["rule"] for r in seg["cautions"]}


def test_surveyed_clear_curb_is_green():
    seg = seg_at(model(), 101, "right", 20)
    assert seg["status"] == ALLOWED and seg["confidence"] == "verified_observation"


def test_unverified_survey_does_not_make_green():
    m = CityModel(main_street(), [survey(status="pending")])
    assert seg_at(m, 101, "right", 20)["status"] == UNVERIFIED


# ---------------------------------------------- 52.IV.4 pedestrian crossings
def test_crossing_is_5m_on_both_sides_of_the_crossing():
    m = model()
    # crossing node at 100 m, ±2 m crossing + 5 m => [93, 107] on BOTH curbs (v1 bug: only 'before')
    for side in ("right", "left"):
        for pos in (94, 100, 106):
            assert "PEDESTRIAN_CROSSING" in rules_at(m, 101, side, pos), (side, pos)
        assert seg_at(m, 101, side, 91)["status"] == ALLOWED
        assert seg_at(m, 101, side, 109)["status"] == ALLOWED


# ----------------------------------------------- 52.IV.7 bus stops (side)
def test_bus_stop_15m_only_on_its_side():
    m = model()
    assert "BUS_STOP" in rules_at(m, 101, "right", 60)
    assert "BUS_STOP" in rules_at(m, 101, "right", 74)
    assert seg_at(m, 101, "right", 77)["status"] == ALLOWED
    assert seg_at(m, 101, "left", 60)["status"] == ALLOWED


def test_bus_platform_measured_from_its_ends():
    r = main_street()
    r["elements"] += [node(60, 30, -8), node(61, 70, -8),
                      way(600, [60, 61], public_transport="platform", bus="yes", name="Long platform")]
    m = CityModel(r, [survey()])
    assert "BUS_STOP" in rules_at(m, 101, "right", 16)   # 30 - 15 + 1
    assert "BUS_STOP" in rules_at(m, 101, "right", 84)   # 70 + 15 - 1


def test_rail_platform_is_not_a_bus_stop():
    r = main_street()
    r["elements"].append(node(50, 160, 10, public_transport="platform", railway="platform", name="Rail"))
    m = CityModel(r, [survey()])
    assert not any(b["name"] == "Rail" for b in m.bus_stops)


# ------------------------------------------------- 52.IV.6 intersections
def test_intersection_uses_crossed_road_edge_plus_5m():
    m = model()
    # tertiary oneway width 6 -> half 3 + 5 = 8 => [192, 208]
    assert "INTERSECTION" in rules_at(m, 101, "right", 193)
    assert seg_at(m, 101, "right", 190)["status"] == ALLOWED


def test_t_junction_opposite_side_is_caution_not_red():
    # through road H-J-K east, branch J -> L northwards (left side of the through road)
    r = raw([node(11, 0, 0), node(12, 100, 0), node(13, 200, 0), node(14, 100, 100),
             way(201, [11, 12, 13], highway="residential", name="Through"),
             way(202, [12, 14], highway="residential", name="Branch")])
    m = CityModel(r, [survey()])
    assert "INTERSECTION" in rules_at(m, 201, "left", 100)                       # branch side: red
    opposite = seg_at(m, 201, "right", 100)
    assert opposite["status"] == UNVERIFIED                                      # exception possible
    assert "T_JUNCTION_EXCEPTION" in {c["rule"] for c in opposite["cautions"]}


def test_driveway_mouth_blocked_only_on_its_side():
    r = main_street()
    r["elements"] += [node(71, 150, 0), node(72, 150, 40), way(701, [71, 72], highway="service")]
    for e in r["elements"]:
        if e.get("id") == 101:
            e["nodes"] = [1, 2, 71, 3, 4]       # driveway attaches to the street at x=150
    m = CityModel(r, [survey()])
    assert "DRIVEWAY_BLOCKING" in rules_at(m, 101, "left", 150)   # driveway goes north = left side
    assert seg_at(m, 101, "right", 150)["status"] == ALLOWED
    assert 71 not in m.intersections                               # not an intersection (Art. 64.VI)


# ------------------------------------------------ 52.IV.2 bridges/tunnels
def test_bridge_without_lane_count_is_caution():
    seg = seg_at(model(), 103, "right", 50)
    assert seg["status"] == UNVERIFIED and "BRIDGE_LANES_UNKNOWN" in {c["rule"] for c in seg["cautions"]}


def test_bridge_fewer_than_3_lanes_is_red_3_or_more_is_not():
    for lanes, expected in (("2", PROHIBITED), ("6", ALLOWED)):
        r = main_street()
        for e in r["elements"]:
            if e.get("id") == 103:
                e["tags"]["lanes"] = lanes
        m = CityModel(r, [survey()])
        assert seg_at(m, 103, "right", 50)["status"] == expected, lanes


def test_tunnel_is_red():
    r = main_street()
    for e in r["elements"]:
        if e.get("id") == 103:
            e["tags"] = {"highway": "residential", "tunnel": "yes"}
    assert "TUNNEL" in rules_at(CityModel(r, [survey()]), 103, "left", 50)


# ------------------------------------------- signs: 3.27 vs 3.28 (dayanma vs durma)
def test_327_red_and_328_not_red():
    m27 = model([obs("sign_3_27", point(20, -5))])
    m28 = model([obs("sign_3_28", point(20, -5))])
    s27, s28 = seg_at(m27, 101, "right", 40), seg_at(m28, 101, "right", 40)
    assert s27["status"] == PROHIBITED and "SIGN_3_27" in {r["rule"] for r in s27["reasons"]}
    assert s28["status"] == ALLOWED and "SIGN_3_28" in {n["rule"] for n in s28["notes"]}
    assert any(n["applies_to"] == "durma" for n in s28["notes"])


def test_327_zone_side_and_direction_specific():
    m = model([obs("sign_3_27", point(20, -5))])          # south curb = right, traffic eastbound
    assert "SIGN_3_27" in rules_at(m, 101, "right", 150)   # continues to next intersection (C at 200)
    assert seg_at(m, 101, "right", 10)["status"] == ALLOWED  # before the sign
    assert seg_at(m, 101, "left", 40)["status"] == ALLOWED   # other side untouched (64.IX)


def test_327_on_left_curb_runs_westward():
    m = model([obs("sign_3_27", point(150, 5))])            # north curb = left, traffic westbound
    assert "SIGN_3_27" in rules_at(m, 101, "left", 120)
    assert seg_at(m, 101, "left", 170)["status"] == ALLOWED  # 'behind' the sign for westbound traffic


def test_327_explicit_zone_length_plate():
    m = model([obs("sign_3_27", point(20, -5), zone_mode="length", zone_length_m=30)])
    assert "SIGN_3_27" in rules_at(m, 101, "right", 45)      # zone [20, 50]
    assert seg_at(m, 101, "right", 85)["status"] == ALLOWED  # (45–75 is the synthetic bus stop)


# ------------------------------------------- markings: 1.4 vs 1.10
def test_1_4_alone_is_yellow_not_red():
    m = model([obs("marking_1_4", line((20, -5), (60, -5)))])
    seg = seg_at(m, 101, "right", 40)
    assert seg["status"] == UNVERIFIED and "MARKING_1_4_UNPAIRED" in {c["rule"] for c in seg["cautions"]}


def test_1_4_with_327_is_red_and_zone_is_line_length():
    m = model([obs("sign_3_27", point(20, -5)), obs("marking_1_4", line((20, -5), (60, -5)))])
    assert {"MARKING_1_4", "SIGN_3_27"} <= rules_at(m, 101, "right", 40)
    # 64.VIII.3: with a paired line the zone is the line's length, not "to the next intersection"
    assert seg_at(m, 101, "right", 80)["status"] == ALLOWED


def test_1_10_never_prohibits_stopping():
    for feats in ([obs("marking_1_10", line((20, -5), (60, -5)))],
                  [obs("sign_3_28", point(20, -5)), obs("marking_1_10", line((20, -5), (60, -5)))]):
        assert seg_at(model(feats), 101, "right", 40)["status"] == ALLOWED


# ------------------------------------------- bus lanes (48.IV), bike lanes, taxi stands
def test_osm_bus_lane_unknown_line_is_caution():
    m = model(**{"lanes:bus:forward": "1"})
    seg = seg_at(m, 101, "right", 30)
    assert seg["status"] == UNVERIFIED and "BUS_LANE_UNKNOWN_LINE" in {c["rule"] for c in seg["cautions"]}
    assert seg_at(m, 101, "left", 30)["status"] == ALLOWED


def test_bus_lane_dashed_allows_dropoff_solid_prohibits():
    tags = {"lanes:bus:forward": "1"}
    dashed = model([obs("bus_lane", line((0, -5), (90, -5)), line_type="dashed")], **tags)
    solid = model([obs("bus_lane", line((0, -5), (90, -5)), line_type="solid")], **tags)
    assert seg_at(dashed, 101, "right", 30)["status"] == ALLOWED
    assert seg_at(solid, 101, "right", 30)["status"] == PROHIBITED


def test_bike_lane_is_red():
    assert "BIKE_LANE" in rules_at(model(**{"cycleway:right": "lane"}), 101, "right", 30)


def test_taxi_stand_depends_on_vehicle():
    m = model([obs("taxi_stand", line((10, -5), (40, -5)))])
    seg = seg_at(m, 101, "right", 25)
    assert seg["status_by_vehicle"] == {"taxi": ALLOWED, "private": PROHIBITED}


# ------------------------------------------- caution-only rules, unverified data, conflicts
def test_traffic_signal_distance_is_caution():
    r = main_street()
    for e in r["elements"]:
        if e.get("id") == 4:
            e["tags"] = {"highway": "traffic_signals"}
    m = CityModel(r, [survey()])
    seg = seg_at(m, 101, "right", 295)
    assert seg["status"] == UNVERIFIED and "TRAFFIC_SIGNAL" in {c["rule"] for c in seg["cautions"]}


def test_pending_observation_turns_curb_yellow_not_red():
    m = model([obs("sign_3_27", point(20, -5), status="pending")])
    seg = seg_at(m, 101, "right", 40)
    assert seg["status"] == UNVERIFIED and "PENDING_OBSERVATION" in {c["rule"] for c in seg["cautions"]}


def test_rejected_observation_has_no_effect():
    m = model([obs("sign_3_27", point(20, -5), status="rejected")])
    assert seg_at(m, 101, "right", 40)["status"] == ALLOWED


def test_official_zone_on_prohibited_curb_is_flagged_but_stays_red():
    m = CityModel(main_street(), [obs("official_zone", line((95, -5), (105, -5)))])
    seg = seg_at(m, 101, "right", 100)   # on the zebra crossing (52.IV.4)
    assert seg["status"] == PROHIBITED and "SOURCE_CONFLICT" in {c["rule"] for c in seg["cautions"]}


def test_conflicting_pending_report_on_green_curb_is_yellow():
    m = model([obs("sign_3_27", point(20, -5), status="pending")])
    assert seg_at(m, 101, "right", 30)["status"] == UNVERIFIED


def test_every_reason_carries_its_legal_basis():
    m = model([obs("sign_3_27", point(20, -5))])
    for seg in m.segments.values():
        for r in seg["reasons"] + seg["cautions"]:
            assert r["verification"] in ("verified_text", "interpretation", "heuristic")
            if r["effect"] == "prohibit":
                assert r["legal_ref"].startswith("Yol hərəkəti haqqında Qanun (517-IQ), m.")


def test_bad_feature_does_not_break_build():
    bad = obs("survey_area", {"type": "Polygon", "coordinates": []})
    m = CityModel(main_street(), [survey(), bad])
    assert bad["id"] in m.feature_errors and m.segments


def test_oneway_left_side_allowed_with_note():
    seg = seg_at(model(), 102, "left", 30)
    assert seg["status"] == ALLOWED and any(n["rule"] == "ONE_WAY_LEFT_SIDE" for n in seg["notes"])


def test_synthetic_sources_are_labelled():
    m = model([obs("sign_3_27", point(20, -5))])
    assert "synthetic_test" in seg_at(m, 101, "right", 40)["sources"]


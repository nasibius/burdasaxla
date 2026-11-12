"""Importer unit tests (no network). Payloads are SYNTHETIC and shaped like the real APIs."""
from app.citymodel import CityModel
from app.ingest import geojson_candidates, mapillary_candidates, osm_candidates
from tests.fixtures import ll, main_street, node


def test_osm_sign_tags_parsed_and_side_from_direction():
    r = main_street()
    r["elements"] += [node(91, 150, -6, traffic_sign="AZ:3.27"),
                      node(92, 170, 6, traffic_sign="RU:3.28;RU:7.2.2[50]"),
                      node(93, 120, 6, traffic_sign="AZ:5.19.1")]               # not a stopping sign
    for e in r["elements"]:
        if e.get("id") == 4:  # sign mapped ON the road with a direction
            e["tags"] = {"traffic_sign": "3.27", "direction": "backward"}
    c = {x["source_ref"]: x for x in osm_candidates(CityModel(r, []))}
    assert c["node/91"]["kind"] == "sign_3_27" and c["node/92"]["kind"] == "sign_3_28"
    assert "node/93" not in c
    assert c["node/4"]["props"]["side"] == "left"       # backward traffic on a two-way road uses the left curb
    assert all(x["source"] == "osm" and x["source_url"].startswith("https://www.openstreetmap.org/") for x in c.values())


def test_osm_without_signs_yields_nothing():
    assert osm_candidates(CityModel(main_street(), [])) == []


def test_mapillary_mapping_uses_feature_position_not_camera():
    lon, lat = ll(20, -5)
    payload = [
        {"id": "111", "object_value": "regulatory--no-stopping--g1", "object_type": "trafficsign",
         "geometry": {"type": "Point", "coordinates": [lon, lat]}, "aligned_direction": 87.0,
         "images": {"data": [{"id": "img1"}, {"id": "img2"}]}},
        {"id": "222", "object_value": "regulatory--no-parking--g2", "geometry": {"type": "Point", "coordinates": [lon, lat]}},
        {"id": "333", "object_value": "warning--pedestrians-crossing--g1", "geometry": {"type": "Point", "coordinates": [lon, lat]}},
    ]
    c = {x["source_ref"]: x for x in mapillary_candidates(payload)}
    assert c["111"]["kind"] == "sign_3_27" and c["222"]["kind"] == "sign_3_28" and "333" not in c
    assert c["111"]["geometry"]["coordinates"] == [lon, lat]
    assert c["111"]["props"]["position_method"] == "mapillary_triangulated"
    assert c["111"]["props"]["image_ids"] == ["img1", "img2"]


def test_geojson_requires_kind_and_source():
    fc = {"features": [
        {"geometry": {"type": "Point", "coordinates": [49.85, 40.38]}, "properties": {"kind": "sign_3_27",
                                                                                  "photo_url": "https://x/1.jpg"}},
        {"geometry": {"type": "Point", "coordinates": [49.85, 40.38]}, "properties": {"kind": "bogus"}},
        {"geometry": {"type": "Point", "coordinates": [49.85, 40.38]}, "properties": {"kind": "sign_3_28"}},
    ]}
    ok, errors = geojson_candidates(fc)
    assert len(ok) == 1 and len(errors) == 2

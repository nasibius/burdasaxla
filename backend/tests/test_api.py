"""HTTP API tests against the synthetic network (isolated temp DB + OSM file)."""
import importlib
import json
import os

import pytest

from tests.test_engine import build_raw, ll


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("bs")
    (d / "osm.json").write_text(json.dumps(build_raw()))
    os.environ["BURDASAXLA_OSM"] = str(d / "osm.json")
    os.environ["BURDASAXLA_DB"] = str(d / "db.sqlite3")
    from app import citymodel, config, main, store  # noqa: F401
    for m in (config, store, citymodel, main):
        importlib.reload(m)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c


H = {"x-admin-token": "burdasaxla-admin"}


def test_meta_and_segments(client):
    m = client.get("/api/meta").json()
    assert m["stats"]["by_status"]["VERIFIED"]["count"] > 0  # demo survey seeded
    fc = client.get("/api/map/segments").json()
    assert fc["type"] == "FeatureCollection" and fc["features"]
    seg_id = fc["features"][0]["id"]
    seg = client.get(f"/api/segments/{seg_id}").json()
    assert {"reasons", "sources", "ruleset_version", "compass"} <= seg.keys()


def test_search(client):
    r = client.get("/api/search", params={"q": "test kuc"}).json()  # diacritic-insensitive
    assert any("Test" in i["name"] for i in r)


def test_recommendations_and_driver(client):
    r = client.post("/api/dropoff/recommendations",
                    json={"destination": list(ll(30, -25)), "origin": list(ll(280, 5))}).json()
    assert 1 <= len(r["results"]) <= 3
    d = client.post("/api/driver/nearest-stops", json={"origin": list(ll(280, 5))}).json()
    assert d["results"]


def test_admin_requires_token(client):
    assert client.get("/api/validation/tasks").status_code == 401
    assert client.post("/api/admin/features", json={}).status_code in (401, 422)


def test_validation_flow(client):
    lon, lat = ll(20, -5)
    f = client.post("/api/admin/features", headers=H, json={
        "kind": "sign_3_27", "geometry": {"type": "Point", "coordinates": [lon, lat]}}).json()
    assert f["status"] == "pending" and f["impact"]["conflicts"]
    assert [t["id"] for t in client.get("/api/validation/tasks", headers=H).json()] == [f["id"]]
    client.post("/api/validation/approve", headers=H, json={"id": f["id"], "decision": "verified"})
    fc = client.get("/api/map/segments").json()["features"]
    assert any("SIGN_3_27" in x["properties"]["rules"] for x in fc)
    client.delete(f"/api/admin/features/{f['id']}", headers=H)
    fc = client.get("/api/map/segments").json()["features"]
    assert not any("SIGN_3_27" in x["properties"]["rules"] for x in fc)


def test_bad_geometry_rejected(client):
    r = client.post("/api/admin/features", headers=H, json={
        "kind": "marking_1_4", "geometry": {"type": "Point", "coordinates": [49.85, 40.38]}})
    assert r.status_code == 400


def test_unknown_api_is_404(client):
    assert client.get("/api/does-not-exist").status_code == 404


def test_invalid_coordinates_rejected(client):
    r = client.post("/api/dropoff/recommendations", json={"destination": [200, 95]})
    assert r.status_code == 422


def test_destination_outside_area(client):
    r = client.post("/api/dropoff/recommendations", json={"destination": [0, 0]}).json()
    assert r["message"] == "outside_area" and r["results"] == []


def test_origin_outside_area_is_reported(client):
    r = client.post("/api/dropoff/recommendations",
                    json={"destination": list(ll(30, -25)), "origin": [0, 0]}).json()
    assert "origin_outside_area" in r["warnings"]


def test_malformed_geometry_is_rejected_and_not_stored(client):
    before = len(client.get("/api/admin/features", headers=H).json())
    for geom in ({"type": "Polygon", "coordinates": []},
                 {"type": "LineString", "coordinates": [[49.85]]},
                 {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}):  # outside area
        kind = "survey_area" if geom["type"] == "Polygon" else "marking_1_4"
        r = client.post("/api/admin/features", headers=H, json={"kind": kind, "geometry": geom})
        assert r.status_code == 400, (geom, r.text)
    assert len(client.get("/api/admin/features", headers=H).json()) == before


def test_unknown_kind_and_bad_url_rejected(client):
    lon, lat = ll(20, -5)
    g = {"type": "Point", "coordinates": [lon, lat]}
    assert client.post("/api/admin/features", headers=H, json={"kind": "nope", "geometry": g}).status_code == 422
    assert client.post("/api/admin/features", headers=H,
                       json={"kind": "sign_3_27", "geometry": g, "source_url": "javascript:alert(1)"}).status_code == 422


def test_wrong_token_rejected(client):
    assert client.get("/api/validation/tasks", headers={"x-admin-token": "wrong"}).status_code == 401

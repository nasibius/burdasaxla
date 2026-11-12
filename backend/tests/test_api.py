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
    from app import config, store, citymodel, main  # noqa: F401
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

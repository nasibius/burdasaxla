"""Authority (B2G) and passenger-activity API tests. Isolated temp DB/OSM, SYNTHETIC fixtures only."""
import csv
import importlib
import io
import json
import os

import pytest

from tests.fixtures import ll
from tests.test_planning import synth_raw

H = {"x-admin-token": "burdasaxla-admin"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("b2g")
    (d / "osm.json").write_text(json.dumps(synth_raw()))
    os.environ["BURDASAXLA_OSM"] = str(d / "osm.json")
    os.environ["BURDASAXLA_DB"] = str(d / "db.sqlite3")
    from app import citymodel, config, main, store  # noqa: F401
    for m in (config, store, citymodel, main):
        importlib.reload(m)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c


def test_overview_is_honest_without_inventory(client):
    o = client.get("/api/authority/overview").json()
    assert o["inventory_complete"] is False and o["demand_measured"] is False
    assert o["summary"]["coverage_states"]["POTENTIAL_COVERAGE_GAP"] == 0
    assert o["summary"]["served_share"] is None
    assert any("NOT legal" in x for x in o["limitations"])


def test_review_requires_admin_and_reject_reason(client):
    item = client.get("/api/authority/candidates", params={"kind": "survey"}).json()["items"][0]
    url = f"/api/authority/candidates/{item['id']}/review"
    assert client.post(url, json={"action": "shortlist", "reviewer": "pytest"}).status_code == 401
    assert client.post(url, headers=H, json={"action": "reject", "reviewer": "pytest"}).status_code == 400
    r = client.post(url, headers=H, json={"action": "needs_survey", "reviewer": "pytest", "reason": "synthetic"}).json()
    assert r["item"]["review"]["action"] == "needs_survey" and "does not create or approve" in r["note"]
    # recompute (new run) keeps the decision
    client.post("/api/authority/recommendations/run", headers=H)
    again = client.get(f"/api/authority/candidates/{item['id']}").json()
    assert again["review"]["action"] == "needs_survey"
    filtered = client.get("/api/authority/candidates", params={"review": "needs_survey"}).json()["items"]
    assert [i["id"] for i in filtered] == [item["id"]]


def test_inventory_complete_needs_source(client):
    assert client.post("/api/authority/inventory", headers=H,
                       json={"status": "complete", "declared_by": "pytest"}).status_code == 400


def test_export_matches_filters_and_has_limitations(client):
    text = client.get("/api/authority/export", params={"format": "csv", "review": "needs_survey"}).text
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 1 and rows[0]["review_action"] == "needs_survey"
    assert rows[0]["officially_approved"] == "False" and rows[0]["is_synthetic_example"] == "False"
    assert "NOT legal" in rows[0]["limitations"]
    gj = client.get("/api/authority/export", params={"format": "geojson"}).json()
    assert gj["metadata"]["limitations"] and gj["features"][0]["geometry"]["type"] == "Polygon"


def test_gap_and_candidates_after_sourced_inventory_declaration(client):
    a, b = ll(5, -5), ll(40, -5)
    z = client.post("/api/admin/features", headers=H, json={
        "kind": "official_zone", "geometry": {"type": "LineString", "coordinates": [a, b]},
        "observer": "pytest", "source": "ayna_official", "source_url": "https://example.org/synthetic-zone"}).json()
    assert client.post("/api/validation/approve", headers=H, json={"id": z["id"]}).status_code == 200
    client.post("/api/authority/inventory", headers=H, json={
        "status": "complete", "declared_by": "pytest", "source_url": "https://example.org/synthetic-list"})
    o = client.get("/api/authority/overview", params={"threshold_m": 150}).json()
    assert o["inventory_complete"] and o["summary"]["coverage_states"]["POTENTIAL_COVERAGE_GAP"] >= 1
    cands = client.get("/api/authority/candidates", params={"kind": "candidate", "threshold_m": 150}).json()["items"]
    assert cands and all(not c["officially_approved"] for c in cands)
    # the driver API never offers DATA_COLLECTION_NEEDED candidates as confirmed spots
    rec = client.post("/api/dropoff/recommendations", json={"destination": list(ll(270, -30))}).json()
    dcn = {c["segment_id"] for c in cands if c["candidate_class"] == "DATA_COLLECTION_NEEDED"}
    assert not dcn & {r["segment_id"] for r in rec["results"]}
    client.post("/api/authority/inventory", headers=H, json={"status": "unknown", "declared_by": "pytest"})


# ------------------------------------------------------------ passenger activity table
def activity(**kw):
    lon, lat = ll(270, -30)
    body = {"place_name": "SYNTH bakery entrance", "point": [lon, lat], "period_start": "2026-11-10T08:00:00",
            "period_end": "2026-11-10T10:00:00", "pickups": 40, "dropoffs": 60, "method": "field_count",
            "source": "synthetic test", "observer": "pytest"}
    return {**body, **kw}


def test_activity_pending_until_verified_with_source(client):
    a = client.post("/api/admin/activity", headers=H, json=activity()).json()
    assert a["status"] == "pending" and client.get("/api/activity").json()["rows"] == []
    r = client.post(f"/api/admin/activity/{a['id']}/review", headers=H, json={"decision": "verified", "reviewer": "pytest"})
    assert r.status_code == 400  # no source URL / reference
    b = client.post("/api/admin/activity", headers=H, json=activity(source_ref="synthetic-sheet-1")).json()
    assert client.post(f"/api/admin/activity/{b['id']}/review", headers=H,
                       json={"decision": "verified", "reviewer": "pytest"}).status_code == 200
    pub = client.get("/api/activity").json()
    assert pub["measured"] and pub["rows"][0]["per_hour"] == 50.0
    o = client.get("/api/authority/overview").json()
    assert o["demand_measured"] is True and o["summary"]["measured_activity_rows"] == 1


def test_activity_small_counts_suppressed_and_validation(client):
    c = client.post("/api/admin/activity", headers=H, json=activity(pickups=2, dropoffs=1, source_ref="s2")).json()
    client.post(f"/api/admin/activity/{c['id']}/review", headers=H, json={"decision": "verified", "reviewer": "pytest"})
    row = next(r for r in client.get("/api/activity").json()["rows"] if r["id"] == c["id"])
    assert row["pickups"] == "<5" and row["per_hour"] is None
    bad = activity(period_end="2026-11-10T07:00:00")
    assert client.post("/api/admin/activity", headers=H, json=bad).status_code == 400
    assert client.post("/api/admin/activity", headers=H, json=activity(point=[0, 0])).status_code == 400
    assert client.post("/api/admin/activity", headers=H, json=activity(pickups=-1)).status_code == 422


def test_activity_csv_import(client):
    lon, lat = ll(30, -30)
    text = ("place_name,lon,lat,period_start,period_end,pickups,dropoffs,method,source,source_ref\n"
            f"SYNTH cafe,{lon},{lat},2026-11-11T08:00,2026-11-11T09:00,12,30,field_count,synthetic,sheet-9\n"
            f"Broken,{lon},{lat},2026-11-11T08:00,2026-11-11T07:00,1,1,field_count,synthetic,\n")
    r = client.post("/api/admin/activity/import", headers=H, json={"csv_text": text, "observer": "pytest"}).json()
    assert r["created"] == 1 and len(r["errors"]) == 1

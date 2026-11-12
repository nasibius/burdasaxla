"""HTTP API + validation workflow tests. Isolated temp DB/OSM; SYNTHETIC fixtures only (tests/fixtures.py)."""
import importlib
import io
import json
import os
import sqlite3

import pytest
from PIL import Image

from tests.fixtures import ll, main_street, node

H = {"x-admin-token": "burdasaxla-admin"}
WHO = {"observer": "pytest"}


def jpeg_with_gps(lon, lat, heading=90.0) -> bytes:
    """Synthetic photo whose EXIF says it was taken at (lon, lat)."""
    def dms(v):
        d = int(v)
        m = int((v - d) * 60)
        return (float(d), float(m), round(((v - d) * 60 - m) * 60, 4))
    img, ex = Image.new("RGB", (64, 48), (200, 40, 40)), Image.Exif()
    ex.get_ifd(0x8825).update({1: "N", 2: dms(lat), 3: "E", 4: dms(lon), 16: "T", 17: heading})
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=ex)
    return buf.getvalue()


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("bs")
    r = main_street()
    r["elements"].append(node(90, 150, -6, traffic_sign="AZ:3.27", name="synthetic OSM sign"))
    (d / "osm.json").write_text(json.dumps(r))
    os.environ["BURDASAXLA_OSM"] = str(d / "osm.json")
    os.environ["BURDASAXLA_DB"] = str(d / "db.sqlite3")
    from app import citymodel, config, main, store  # noqa: F401
    for m in (config, store, citymodel, main):
        importlib.reload(m)
    main.EVIDENCE_DIR = d / "evidence"
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c


def add(client, **body):
    return client.post("/api/admin/features", headers=H, json={**WHO, **body})


def segs(client, vehicle="taxi"):
    return client.get("/api/map/segments", params={"vehicle": vehicle}).json()["features"]


# ------------------------------------------------------------- public
def test_meta_has_law_and_no_green_without_survey(client):
    m = client.get("/api/meta").json()
    assert m["law"]["url"] == "https://e-qanun.az/framework/3423"
    assert m["stats"]["by_status"]["ALLOWED"]["count"] == 0          # nothing surveyed -> nothing green
    assert m["stats"]["by_status"]["UNVERIFIED"]["count"] > 0


def test_rules_catalog_has_quotes_and_levels(client):
    rules = {r["id"]: r for r in client.get("/api/rules").json()["rules"]}
    assert rules["PEDESTRIAN_CROSSING"]["article"] == "52.IV.4" and "5 metrdən az" in rules["PEDESTRIAN_CROSSING"]["quote"]
    assert rules["SIGN_3_28"]["applies_to"] == "durma" and rules["SIGN_3_28"]["effect"] == "info"
    assert rules["TRAFFIC_SIGNAL"]["verification"] == "heuristic" and rules["TRAFFIC_SIGNAL"]["effect"] == "caution"


def test_segment_detail_and_search(client):
    f = segs(client)[0]
    seg = client.get(f"/api/segments/{f['id']}").json()
    assert {"reasons", "cautions", "notes", "status_by_vehicle", "sources", "ruleset_version"} <= seg.keys()
    assert any("Synthetic" in i["name"] for i in client.get("/api/search", params={"q": "synth"}).json())


def test_recommendations_without_survey(client):
    r = client.post("/api/dropoff/recommendations",
                    json={"destination": list(ll(30, -25)), "origin": list(ll(280, 5))}).json()
    assert r["results"] == [] and r["message"] == "no_verified_spot"
    assert r["unverified_candidates"] and all(not c["legally_confirmed"] for c in r["unverified_candidates"])


def test_input_validation(client):
    assert client.post("/api/dropoff/recommendations", json={"destination": [200, 95]}).status_code == 422
    assert client.post("/api/dropoff/recommendations", json={"destination": [0, 0]}).json()["message"] == "outside_area"
    r = client.post("/api/dropoff/recommendations", json={"destination": list(ll(30, -25)), "origin": [0, 0]}).json()
    assert "origin_outside_area" in r["warnings"]
    assert client.get("/api/does-not-exist").status_code == 404


# ------------------------------------------------------------- admin
def test_admin_requires_token(client):
    assert client.get("/api/validation/tasks").status_code == 401
    assert client.get("/api/validation/tasks", headers={"x-admin-token": "wrong"}).status_code == 401


def test_observer_is_required(client):
    lon, lat = ll(20, -5)
    r = client.post("/api/admin/features", headers=H, json={"kind": "sign_3_27",
                                                            "geometry": {"type": "Point", "coordinates": [lon, lat]}})
    assert r.status_code == 422


def test_cannot_verify_without_traceable_evidence(client):
    lon, lat = ll(20, -5)
    r = add(client, kind="sign_3_27", geometry={"type": "Point", "coordinates": [lon, lat]}, status="verified")
    assert r.status_code == 400 and "traceable" in r.text


def test_ai_detections_always_enter_as_pending(client):
    lon, lat = ll(250, -5)
    r = add(client, kind="sign_3_27", geometry={"type": "Point", "coordinates": [lon, lat]}, source="ai_vision",
            source_ref="synthetic-detection-1", status="verified", confidence=0.91).json()
    assert r["status"] == "pending"
    client.delete(f"/api/admin/features/{r['id']}", headers=H)


def test_full_review_cycle_with_photo_evidence(client):
    sign_lon, sign_lat = ll(20, -5)
    f = add(client, kind="sign_3_27", geometry={"type": "Point", "coordinates": [sign_lon, sign_lat]},
            source="street_photo", observed_at="2026-11-10", note="synthetic").json()
    assert f["status"] == "pending" and f["problems"]
    # pending prohibition -> affected curb is YELLOW with PENDING_OBSERVATION
    seg = client.get(f"/api/segments/{f['impact']['affected_segments'][0]['id']}").json()
    assert "PENDING_OBSERVATION" in {c["rule"] for c in seg["cautions"]}
    # approval without evidence is refused
    assert client.post("/api/validation/approve", headers=H, json={"id": f["id"]}).status_code == 400
    # photo taken 12 m away (camera position != sign position)
    cam_lon, cam_lat = ll(8, -12)
    up = client.post(f"/api/admin/features/{f['id']}/evidence", headers=H,
                     files={"file": ("sign.jpg", jpeg_with_gps(cam_lon, cam_lat), "image/jpeg")}).json()
    assert abs(up["camera"]["lon"] - cam_lon) < 1e-5 and up["camera"]["heading"] == 90.0
    ev_id = up["evidence"]["id"]
    assert client.get(f"/api/evidence/{ev_id}").status_code == 403            # pending: admin only
    assert client.get(f"/api/evidence/{ev_id}", params={"token": "burdasaxla-admin"}).status_code == 200
    ok = client.post("/api/validation/approve", headers=H, json={"id": f["id"], "review_note": "photo checked"})
    assert ok.status_code == 200, ok.text
    assert client.get(f"/api/evidence/{ev_id}").status_code == 200            # verified: public
    assert any("SIGN_3_27" in s["properties"]["rules"] for s in segs(client))
    # editing a verified observation reopens review and removes its effect until re-approved
    moved = client.patch(f"/api/admin/features/{f['id']}", headers=H,
                         json={"note": "corrected"}).json()
    assert moved["status"] == "pending"
    assert not any("SIGN_3_27" in s["properties"]["rules"] for s in segs(client))
    audit = client.get(f"/api/admin/features/{f['id']}", headers=H).json()["audit"]
    assert {"create", "evidence_add", "set_status:verified", "edit"} <= {a["action"] for a in audit}
    client.delete(f"/api/admin/features/{f['id']}", headers=H)


def test_sign_at_camera_position_is_refused(client):
    lon, lat = ll(240, -5)
    f = add(client, kind="sign_3_27", geometry={"type": "Point", "coordinates": [lon, lat]},
            source="street_photo").json()
    client.post(f"/api/admin/features/{f['id']}/evidence", headers=H,
                files={"file": ("p.jpg", jpeg_with_gps(lon, lat), "image/jpeg")})
    r = client.post("/api/validation/approve", headers=H, json={"id": f["id"]})
    assert r.status_code == 400 and "camera" in r.text
    client.delete(f"/api/admin/features/{f['id']}", headers=H)


def test_rejection_needs_a_note(client):
    lon, lat = ll(240, 5)
    f = add(client, kind="sign_3_28", geometry={"type": "Point", "coordinates": [lon, lat]},
            source_url="https://example.org/synthetic").json()
    assert client.post("/api/validation/approve", headers=H, json={"id": f["id"], "decision": "rejected"}).status_code == 400
    assert client.post("/api/validation/approve", headers=H,
                       json={"id": f["id"], "decision": "rejected", "review_note": "not a 3.28"}).status_code == 200


def test_observed_prohibition_needs_clause(client):
    a, b = ll(120, -5), ll(180, -5)
    f = add(client, kind="observed_prohibition", geometry={"type": "LineString", "coordinates": [a, b]},
            source_url="https://example.org/synthetic", props={}).json()
    r = client.post("/api/validation/approve", headers=H, json={"id": f["id"]})
    assert r.status_code == 400 and "clause" in r.text
    client.delete(f"/api/admin/features/{f['id']}", headers=H)


def test_malformed_input_is_rejected_and_not_stored(client):
    before = len(client.get("/api/admin/features", headers=H).json())
    for kind, geom, props in (("survey_area", {"type": "Polygon", "coordinates": []}, {}),
                              ("marking_1_4", {"type": "LineString", "coordinates": [[49.85]]}, {}),
                              ("marking_1_4", {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, {}),
                              ("bus_lane", {"type": "LineString", "coordinates": [ll(0, -5), ll(50, -5)]},
                               {"line_type": "zigzag"})):
        assert add(client, kind=kind, geometry=geom, props=props).status_code == 400
    assert add(client, kind="nope", geometry={"type": "Point", "coordinates": ll(1, 1)}).status_code == 422
    assert add(client, kind="sign_3_27", geometry={"type": "Point", "coordinates": ll(1, 1)},
               source_url="javascript:alert(1)").status_code == 422
    assert len(client.get("/api/admin/features", headers=H).json()) == before


# ------------------------------------------------------------- importers
def test_osm_import_creates_pending_and_dedupes(client):
    r1 = client.post("/api/admin/import/osm", headers=H, json={"observer": "pytest"}).json()
    assert r1["found"] == 1 and r1["created"] == 1
    r2 = client.post("/api/admin/import/osm", headers=H, json={"observer": "pytest"}).json()
    assert r2["created"] == 0 and r2["skipped_duplicates"] == 1
    f = client.get(f"/api/admin/features/{r1['ids'][0]}", headers=H).json()
    assert f["status"] == "pending" and f["source"] == "osm" and f["source_ref"] == "node/90"


def test_geojson_import(client):
    a, b = ll(210, 5), ll(260, 5)
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [a, b]},
         "properties": {"kind": "marking_1_4", "source_ref": "synthetic-photo-7", "observed_at": "2026-11-11"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": ll(5, 5)},
         "properties": {"kind": "sign_3_27"}},                                   # no source -> refused
    ]}
    r = client.post("/api/admin/import/geojson", headers=H, json={"observer": "pytest", "collection": fc}).json()
    assert r["created"] == 1 and len(r["errors"]) == 1


def test_mapillary_without_token_is_explicit(client):
    os.environ.pop("MAPILLARY_TOKEN", None)
    r = client.post("/api/admin/import/mapillary", headers=H, json={"observer": "pytest"})
    assert r.status_code == 400 and "MAPILLARY_TOKEN" in r.text


def test_sources_report(client):
    r = client.get("/api/sources").json()
    assert r["osm"]["traffic_sign_candidates"] == 1
    assert "ayna" in r["official_ayna_dataset"]


def test_demo_seed_is_retired_on_migration(tmp_path):
    db = tmp_path / "legacy.sqlite3"
    con = sqlite3.connect(db)
    con.executescript("""CREATE TABLE features (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', geometry TEXT NOT NULL, props TEXT NOT NULL DEFAULT '{}',
        source TEXT NOT NULL, source_url TEXT, note TEXT, created_at TEXT NOT NULL, verified_at TEXT, verified_by TEXT);
        INSERT INTO features(kind,status,geometry,source,created_at) VALUES
        ('survey_area','verified','{"type":"Polygon","coordinates":[]}','demo_seed','2026-11-12');""")
    con.commit()
    con.close()
    from app.store import Store
    row = Store(db).get(1)
    assert row["status"] == "rejected" and "not a real field survey" in row["review_note"]


def test_store_is_thread_safe(tmp_path):
    """Regression: parallel requests (admin page loads 3 endpoints at once) crashed the shared SQLite connection."""
    from concurrent.futures import ThreadPoolExecutor

    from app.store import Store
    st = Store(tmp_path / "t.sqlite3")
    lon, lat = ll(20, -5)
    ids = [st.add("sign_3_28", {"type": "Point", "coordinates": [lon, lat]}, "synthetic_test", observer="pytest")["id"]
           for _ in range(5)]

    def work(i):
        st.list()
        st.get(ids[i % 5])
        st.add_evidence(ids[i % 5], f"f{i}.jpg", "x.jpg", "image/jpeg", f"{i:064d}", 1)
        return len(st.evidence_for(ids[i % 5]))

    with ThreadPoolExecutor(16) as pool:
        assert all(n >= 1 for n in pool.map(work, range(200)))


def test_recommendation_requests_feed_aggregate_demand(client):
    before = client.get("/api/authority/demand").json()["logged_requests"]
    for _ in range(2):
        client.post("/api/dropoff/recommendations", json={"destination": list(ll(150, 10)), "origin": list(ll(10, 5))})
    rep = client.get("/api/authority/demand", params={"min_unmet": 1}).json()
    assert rep["logged_requests"] == before + 2 and "hotspots" in rep

"""B2G acceptance tests. ALL records are SYNTHETIC TEST FIXTURES, never deployed."""
import csv
import io
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from app.citymodel import CityModel
from app.dropoff import Recommender
from app.planning import assess_coverage, build_snapshot, candidate_class, export_candidates
from app.planning_api import router_for
from app.planning_store import PlanningStore
from app.store import Store
from tests.fixtures import ll, main_street


@pytest.mark.parametrize(('complete', 'fresh', 'network', 'distance', 'expected'), [
    (False, True, True, 100, 'INVENTORY_UNKNOWN'),
    (True, False, True, 100, 'INVENTORY_UNKNOWN'),
    (True, True, False, 100, 'NETWORK_UNRELIABLE'),
    (True, True, True, 100, 'SERVED'),
    (True, True, True, 600, 'POTENTIAL_COVERAGE_GAP'),
])
def test_coverage_states(complete, fresh, network, distance, expected):
    graph = {1: [(2, distance)], 2: [(1, distance)]}
    result = assess_coverage([{'id': 'SYNTHETIC', 'graph_node': 1, 'access_verified': True}],
                             [{'graph_node': 2, 'access_verified': True, 'eligible': True}], graph,
                             inventory_complete=complete, inventory_fresh=fresh, network_reliable=network)[0]
    assert result['state'] == expected
    assert result['distance_m'] == (distance if expected in ('SERVED', 'POTENTIAL_COVERAGE_GAP') else None)


def test_network_distance_disconnection_and_unknown_attachments():
    graph = {1: [(2, 300)], 2: [(1, 300), (3, 300)], 3: [(2, 300)], 4: []}
    nodes = [{'id': 'SYNTHETIC', 'graph_node': i, 'access_verified': i != 2} for i in (1, 2, 4)]
    result = assess_coverage(nodes, [{'graph_node': 3, 'access_verified': True, 'eligible': True}], graph,
                             inventory_complete=True, inventory_fresh=True, network_reliable=True)
    assert result[0]['distance_m'] == 600 and result[0]['state'] == 'POTENTIAL_COVERAGE_GAP'
    assert result[1]['state'] == 'NETWORK_UNRELIABLE'
    assert result[2]['distance_m'] is None and result[2]['state'] == 'POTENTIAL_COVERAGE_GAP'
    out = assess_coverage(nodes, [{'graph_node': 3, 'eligible': True}], graph,
                          inventory_complete=True, inventory_fresh=True, network_reliable=True)
    assert all(r['state'] == 'NETWORK_UNRELIABLE' for r in out)


def test_classification_and_no_forced_candidate():
    assert candidate_class(hard_exclusions=['barrier'], missing_evidence=[]) == 'EXCLUDED'
    assert candidate_class(hard_exclusions=[], missing_evidence=['crossing']) == 'DATA_COLLECTION_NEEDED'
    assert candidate_class(hard_exclusions=[], missing_evidence=[]) == 'SCREENED_FOR_FURTHER_STUDY'
    model = CityModel(main_street(), [])
    for seg in model.segments.values():
        seg['status'] = 'PROHIBITED'
    result = build_snapshot(model, [])
    assert not result['candidates'] and 'No defensible candidate' in result['empty_reason']


def test_snapshot_separation_reproducibility_and_exports():
    model = CityModel(main_street(), [])
    before = Recommender(model).recommend(ll(150, 10))
    result = build_snapshot(model, [])
    assert result == build_snapshot(model, [])
    assert result['summary']['coverage_share'] is None
    assert not result['measured_passenger_activity_available']
    assert result['candidates']
    assert all(c['score'] is None and not c['officially_approved'] and c['rank'] is None for c in result['candidates'])
    assert Recommender(model).recommend(ll(150, 10)) == before and not before['results']
    result['candidates'][0]['review_status'] = 'reject'
    result['candidates'][0]['name'] = '=HYPERLINK("test")'
    records = list(csv.DictReader(io.StringIO(export_candidates(result, 'csv', 'reject'))))
    geo = json.loads(export_candidates(result, 'geojson', 'reject'))
    assert len(records) == len(geo['features']) == 1
    assert records[0]['name'].startswith("'=")
    assert records[0]['limitations'] and geo['features'][0]['properties']['source_snapshot']
    assert json.loads(records[0]['geometry']) == geo['features'][0]['geometry']


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, 'ADMIN_TOKEN', 'synthetic-test-token')
    model = CityModel(main_street(), [])
    st = Store(tmp_path / 'test.sqlite3')

    def auth(x_admin_token: str = Header(default='')):
        if x_admin_token != 'synthetic-test-token':
            raise HTTPException(401, 'Token required')

    app = FastAPI()
    app.include_router(router_for(SimpleNamespace(store=st), lambda: model, auth))
    with TestClient(app) as c:
        yield c


HEADERS = {'x-admin-token': 'synthetic-test-token'}


def test_review_persistence_auth_and_conflicts(client):
    data = client.get('/api/authority/overview').json()
    candidate = data['candidates'][0]
    path = f"/api/authority/candidates/{candidate['candidate_id']}/review"
    body = {'action': 'reject', 'reason': 'SYNTHETIC field obstruction', 'run_id': data['run_id']}
    assert client.post(path, json=body).status_code == 401
    assert client.post(path, headers=HEADERS, json={**body, 'action': 'APPROVED_OFFICIAL'}).status_code == 422
    assert client.post(path, headers=HEADERS, json={**body, 'reason': '   '}).status_code == 422
    assert client.post(path, headers=HEADERS, json={**body, 'run_id': 'x' * 16}).status_code == 409
    assert client.post(path, headers=HEADERS, json=body).status_code == 200
    recomputed = client.post('/api/authority/recommendations/run', headers=HEADERS).json()
    assert recomputed['candidates'][0]['review_status'] == 'reject'
    public = client.get('/api/authority/candidates').json()[0]
    assert 'reason' not in public['review_history'][0] and 'actor' not in public['review_history'][0]
    assert client.get('/api/authority/reviews', headers=HEADERS).json()[0]['reason'] == body['reason']
    assert len(client.get('/api/authority/export?format=geojson&status=reject').json()['features']) == 1
    assert client.get('/api/authority/overview?area_id=all-baku').status_code == 404
    assert client.get('/api/authority/overview?threshold_m=0').status_code == 422


def activity_record():
    lon, lat = ll(100, 5)
    return {'location_id': 'SYNTHETIC-TEST', 'name': 'SYNTHETIC TEST ONLY', 'longitude': lon, 'latitude': lat,
            'period_start': '2020-01-01T00:00:00Z', 'period_end': '2020-01-02T00:00:00Z',
            'pickups': 120, 'dropoffs': 240, 'source_ref': 'SYNTHETIC fixture', 'source_url': 'https://example.org/test',
            'license': 'SYNTHETIC test only', 'collection_method': 'SYNTHETIC counts', 'publication_permitted': True}


def test_activity_validation_privacy_idempotence_and_rate(client):
    path = '/api/authority/passenger-activity'
    record = activity_record()
    assert client.post(path, json={'records': [record]}).status_code == 401
    for invalid in ({'rider_id': 'not allowed'}, {'pickups': -1}, {'longitude': 0}, {'pickups': 1, 'dropoffs': 1},
                    {'period_end': '2020-01-01T01:00:00Z'}, {'period_start': '2020-01-01'},
                    {'period_end': '2099-01-01T00:00:00Z'}, {'pickups': 1.5}):
        assert client.post(path, headers=HEADERS, json={'records': [{**record, **invalid}]}).status_code == 422
    for _ in range(2):
        assert client.post(path, headers=HEADERS, json={'records': [record]}).status_code == 200
    rows = client.get(path).json()['records']
    assert len(rows) == 1 and rows[0]['passengers_per_hour'] == 15
    overlap = {**record, 'period_end': '2020-01-03T00:00:00Z'}
    assert client.post(path, headers=HEADERS, json={'records': [overlap]}).status_code == 409
    private = {**record, 'location_id': 'PRIVATE-TEST', 'publication_permitted': False}
    assert client.post(path, headers=HEADERS, json={'records': [private]}).status_code == 200
    assert len(client.get(path).json()['records']) == 1
    assert len(client.get('/api/authority/overview').json()['passenger_activity']) == 1


def test_sqlite_reviews_survive_new_connection(tmp_path):
    path = tmp_path / 'test.sqlite3'
    st = PlanningStore(path)
    st.review('SYNTHETIC', 'test-run', 'needs_survey', 'SYNTHETIC reason')
    assert PlanningStore(path).reviews()[0]['reason'] == 'SYNTHETIC reason'


def test_source_fingerprints_track_pending_inputs_and_ignore_evidence_attachment_shape():
    model = CityModel(main_street(), [])
    source = {'id': 1, 'status': 'pending', 'source': 'field_survey', 'source_ref': 'SYNTHETIC'}
    baseline = build_snapshot(model, [source])
    assert baseline['run_id'] == build_snapshot(model, [{**source, 'evidence': []}])['run_id']
    assert baseline['run_id'] != build_snapshot(model, [{**source, 'source_ref': 'SYNTHETIC changed'}])['run_id']
    rows = list(csv.DictReader(io.StringIO(export_candidates(baseline, 'csv'))))
    assert rows[0]['officially_approved'] == 'false'
    assert rows[0]['is_synthetic_example'] == 'false'

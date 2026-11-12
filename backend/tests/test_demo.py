"""Demo (SIMULATED EXAMPLE) survey coverage must be labelled, opt-in and never count as evidence."""
from app import demo
from app.citymodel import CityModel
from app.dropoff import Recommender
from app.planning import build_snapshot
from tests.fixtures import ll, main_street


def test_demo_off_by_default(monkeypatch):
    monkeypatch.delenv("BURDASAXLA_DEMO_SURVEY", raising=False)
    raw = main_street()
    assert demo.with_demo([], raw["bbox"]) == []


def test_demo_green_is_labelled_and_never_legally_confirmed(monkeypatch):
    monkeypatch.setenv("BURDASAXLA_DEMO_SURVEY", "1")
    raw = main_street()
    feats = demo.with_demo([], raw["bbox"])
    assert len(feats) == 1 and feats[0]["is_synthetic_example"] and feats[0]["source"] == "simulated_example"
    model = CityModel(raw, feats)
    green = [s for s in model.segments.values() if s["status"] == "ALLOWED"]
    assert green, "demo coverage should produce some green curb"
    assert all(s["simulated"] and s["confidence"] == "simulated_example" for s in green)
    # Statutory prohibitions still apply (the zebra crossing at x=100 stays red).
    assert any(s["status"] == "PROHIBITED" for s in model.segments.values())
    gj = model.segments_geojson()["features"]
    assert all(f["properties"]["simulated"] for f in gj if f["properties"]["status"] == "ALLOWED")
    rec = Recommender(model).recommend(ll(150, 10))
    assert rec["results"]
    assert all(r["simulated"] and not r["legally_confirmed"] for r in rec["results"])


def test_planning_ignores_simulated_green(monkeypatch):
    raw = main_street()
    monkeypatch.delenv("BURDASAXLA_DEMO_SURVEY", raising=False)
    plain = build_snapshot(CityModel(raw, []), [])
    monkeypatch.setenv("BURDASAXLA_DEMO_SURVEY", "1")
    demo_model = CityModel(raw, demo.with_demo([], raw["bbox"]))
    snap = build_snapshot(demo_model, [])
    assert snap["summary"]["observed_usable_curb_segments"] == 0
    assert len(snap["candidates"]) == len(plain["candidates"])

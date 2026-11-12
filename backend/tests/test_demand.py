"""Unmet-demand recommendations: aggregate logging, thresholds, legal-supply rules, labelled demo data."""
import sqlite3

from app import demand, demo
from app.citymodel import CityModel
from tests.fixtures import ll, main_street, obs, polygon


def test_store_is_aggregate_only(tmp_path):
    st = demand.DemandStore(tmp_path / "d.sqlite")
    for _ in range(3):
        st.log(ll(150, 10), "dropoff", "taxi", served=False)
    st.log(ll(150, 12), "pickup", "taxi", served=True)          # same ~100 m cell
    cols = [r[1] for r in sqlite3.connect(tmp_path / "d.sqlite").execute("PRAGMA table_info(demand_requests)")]
    assert not {"origin", "ip", "user", "destination"} & set(cols)
    [cell] = st.cells()
    assert cell["requests"] == 4 and cell["unmet"] == 3


def test_hotspot_needs_unmet_threshold_and_no_legal_supply(tmp_path, monkeypatch):
    monkeypatch.delenv("BURDASAXLA_DEMO_SURVEY", raising=False)
    st = demand.DemandStore(tmp_path / "d.sqlite")
    for _ in range(6):
        st.log(ll(150, 10), "dropoff", "taxi", served=False)
    model = CityModel(main_street(), [])
    assert demand.report(model, st, min_unmet=7)["hotspots"] == []
    [h] = demand.report(model, st, min_unmet=5)["hotspots"]
    assert h["unmet"] == 6 and not h["is_synthetic_example"] and h["nearest_legal_m"] is None
    site = h["suggested_site"]
    assert h["recommendation"] == "build_new_stopping_place" and site["current_status"] != "PROHIBITED"
    # A verified real survey makes the area legally served -> no longer a "build here" hotspot.
    surveyed = CityModel(main_street(), [obs("survey_area", polygon(-50, -60, 350, 60))])
    assert demand.report(surveyed, st, min_unmet=5)["hotspots"] == []


def test_simulated_green_is_not_supply_and_demo_hotspots_are_labelled(tmp_path, monkeypatch):
    monkeypatch.setenv("BURDASAXLA_DEMO_SURVEY", "1")
    raw = main_street()
    model = CityModel(raw, demo.with_demo([], raw["bbox"]))
    st = demand.DemandStore(tmp_path / "d.sqlite")
    for _ in range(6):
        st.log(ll(150, 10), "dropoff", "taxi", served=False)
    rep = demand.report(model, st, min_unmet=5)
    real = [h for h in rep["hotspots"] if not h["is_synthetic_example"]]
    assert len(real) == 1 and real[0]["nearest_legal_m"] is None     # simulated green does not count
    assert rep["demo"] and all(h["id"].startswith("sim-") for h in rep["hotspots"] if h["is_synthetic_example"])
    assert demand.served({"results": [{"legally_confirmed": False, "simulated": True}]}) is False

"""SIMULATED EXAMPLE survey coverage for demonstrations.

Enabled only with BURDASAXLA_DEMO_SURVEY=1. It adds one in-memory survey area (never written to the
database) so the map can show what GREEN looks like once a real field survey exists. Everything it
touches is labelled `simulated` / `is_synthetic_example`:
  * curbs it turns green carry `simulated: true` and confidence `simulated_example`;
  * recommendations on them are never `legally_confirmed`;
  * the authority planning engine ignores it (it is not supply and not an observed survey).
Statutory prohibitions (crossings, bus stops, bike lanes...) and cautions still apply on top of it.
"""
import os

DEMO_FEATURE_ID = -1
DEMO_SOURCE = "simulated_example"


def enabled() -> bool:
    return os.environ.get("BURDASAXLA_DEMO_SURVEY") == "1"


def demo_survey(bbox, share=0.85):
    s, w, n, e = bbox
    ds, dw = (n - s) * (1 - share) / 2, (e - w) * (1 - share) / 2
    ring = [[w + dw, s + ds], [e - dw, s + ds], [e - dw, n - ds], [w + dw, n - ds], [w + dw, s + ds]]
    return {"id": DEMO_FEATURE_ID, "kind": "survey_area", "status": "verified", "source": DEMO_SOURCE,
            "is_synthetic_example": True, "geometry": {"type": "Polygon", "coordinates": [ring]},
            "props": {"label": "SIMULATED EXAMPLE"}, "observer": "simulation", "observed_at": None,
            "verified_at": None, "note": "SIMULATED EXAMPLE — not a real field survey. Demonstration only."}


def with_demo(features, bbox):
    return [*features, demo_survey(bbox)] if enabled() else list(features)

"""BurdaSaxla HTTP API (FastAPI)."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from contextlib import asynccontextmanager

from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config as C
from .citymodel import CityModel, load_raw
from .dropoff import Recommender
from .rules import RULES, ruleset
from .store import FEATURE_KINDS, Store



class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.store = Store()
        self.raw = None
        self.model: Optional[CityModel] = None
        self.rec: Optional[Recommender] = None
        self.build_ms = None

    def ensure_seed(self):
        """First run only: a clearly-labelled demo survey area so the demo shows green curbs.
        Replace it with real field-survey polygons before any real-world use."""
        if self.store.list(kind="survey_area"):
            return
        s, w, n, e = self.raw["bbox"]
        # inner 70% of the bbox
        ds, dw = (n - s) * 0.15, (e - w) * 0.15
        poly = {"type": "Polygon", "coordinates": [[[w + dw, s + ds], [e - dw, s + ds], [e - dw, n - ds],
                                                    [w + dw, n - ds], [w + dw, s + ds]]]}
        self.store.add("survey_area", poly, source="demo_seed", status="verified",
                       note="DEMO: treated as surveyed for the hackathon demo. Replace with real field-survey areas.",
                       props={"label": "Demo survey area"})

    def rebuild(self):
        with self.lock:
            t0 = time.perf_counter()
            if self.raw is None:
                self.raw = load_raw()
                self.ensure_seed()
            model = CityModel(self.raw, self.store.list())
            self.model, self.rec = model, Recommender(model)
            self.build_ms = round((time.perf_counter() - t0) * 1000)


S = State()


@asynccontextmanager
async def lifespan(_app):
    S.rebuild()
    yield


app = FastAPI(title="BurdaSaxla API", version="0.1.0", lifespan=lifespan,
              description="Legal curbside stopping map for Baku — deterministic rule engine + drop-off recommender.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)


def model() -> CityModel:
    if S.model is None:
        raise HTTPException(503, "City model not built yet")
    return S.model


def admin(x_admin_token: str = Header(default="")):
    if x_admin_token != C.ADMIN_TOKEN:
        raise HTTPException(401, "Admin token required")
    return True


# ---------------------------------------------------------------- public API
@app.get("/api/health")
def health():
    return {"ok": S.model is not None, "build_ms": S.build_ms}


@app.get("/api/meta")
def meta():
    m = model()
    s, w, n, e = m.bbox
    return {"area": "28 May, Bakı", "bbox": m.bbox, "center": [(w + e) / 2, (s + n) / 2],
            "osm_timestamp": m.osm_timestamp, "built_at": m.built_at, "build_ms": S.build_ms,
            "ruleset": ruleset()["version"], "stats": m.stats()}


@app.get("/api/rules")
def rules():
    return ruleset()


@app.get("/api/map/segments")
def map_segments(status: Optional[str] = None):
    m = model()
    feats = []
    for seg in m.segments.values():
        if status and seg["status"] != status:
            continue
        feats.append({"type": "Feature", "id": seg["id"],
                      "geometry": {"type": "LineString", "coordinates": seg["coords"]},
                      "properties": {"id": seg["id"], "status": seg["status"], "name": seg["name"],
                                     "side": seg["side"], "compass": seg["compass"], "length_m": seg["length_m"],
                                     "rules": sorted({r["rule"] for r in seg["reasons"]}),
                                     "official": seg["official"], "highway": seg["highway"]}})
    return {"type": "FeatureCollection", "features": feats}


@app.get("/api/map/context")
def map_context():
    return model().context_layers()


@app.get("/api/segments/{seg_id}")
def segment(seg_id: str):
    seg = model().segments.get(seg_id)
    if not seg:
        raise HTTPException(404, "segment not found")
    return seg


@app.get("/api/search")
def search(q: str = Query(..., min_length=1), limit: int = 8):
    return model().search(q, limit)


class RecRequest(BaseModel):
    destination: list[float] = Field(..., min_length=2, max_length=2, description="[lon, lat]")
    origin: Optional[list[float]] = Field(None, min_length=2, max_length=2)
    mode: Literal["dropoff", "pickup"] = "dropoff"
    max_walk_m: int = Field(450, ge=50, le=1500)
    time: Optional[str] = None  # reserved for time-dependent restrictions


@app.post("/api/dropoff/recommendations")
def recommendations(req: RecRequest):
    model()
    return S.rec.recommend(req.destination, req.origin, req.mode, req.max_walk_m)


class DriverRequest(BaseModel):
    origin: list[float] = Field(..., min_length=2, max_length=2)
    radius_m: int = Field(1200, ge=100, le=3000)


@app.post("/api/driver/nearest-stops")
def driver_nearest(req: DriverRequest):
    model()
    return S.rec.nearest_stops(req.origin, req.radius_m)


@app.get("/api/official-zones")
def official_zones():
    return S.store.list(status="verified", kind="official_zone")


@app.get("/api/features")
def public_features():
    """Verified curated features (signs, markings, survey areas) for map display."""
    return S.store.list(status="verified")


# ----------------------------------------------------------------- admin API
class FeatureIn(BaseModel):
    kind: str
    geometry: dict
    source: str = "field_survey"
    source_url: Optional[str] = None
    note: Optional[str] = None
    props: dict = Field(default_factory=dict)
    status: Literal["pending", "verified"] = "pending"


def _impact(f):
    """Which segments a feature would touch, and whether it contradicts current data."""
    m = model()
    matches = m.match_feature(f)
    rule = {"sign_3_27": "SIGN_3_27", "marking_1_4": "MARKING_1_4", "bus_lane": "BUS_LANE"}.get(f["kind"])
    prohibits = rule is not None and RULES[rule].effect == "prohibit"
    affected, conflicts = [], []
    for w, side, a, b in matches:
        for seg in m.segments_by_way.get((w.id, side), []):
            if seg["end_m"] > a and seg["start_m"] < b:
                affected.append({"id": seg["id"], "status": seg["status"], "name": seg["name"], "side": side})
                if prohibits and seg["status"] == "VERIFIED":
                    conflicts.append({"segment_id": seg["id"], "type": "verified_green_would_become_red"})
                if f["kind"] == "official_zone" and seg["status"] == "PROHIBITED":
                    conflicts.append({"segment_id": seg["id"], "type": "official_zone_on_prohibited_curb",
                                      "rules": [r["rule"] for r in seg["reasons"]]})
    return {"matched": [{"way_id": w.id, "side": s, "start_m": round(a, 1), "end_m": round(b, 1), "street": w.name}
                        for w, s, a, b in matches],
            "affected_segments": affected[:200], "conflicts": conflicts}


@app.get("/api/validation/tasks", dependencies=[Depends(admin)])
def validation_tasks():
    return [{**f, "impact": _impact(f)} for f in S.store.list(status="pending")]


@app.post("/api/admin/preview", dependencies=[Depends(admin)])
def preview(f: FeatureIn):
    return _impact({**f.model_dump(), "id": -1})


@app.get("/api/admin/features", dependencies=[Depends(admin)])
def admin_features(status: Optional[str] = None, kind: Optional[str] = None):
    return S.store.list(status=status, kind=kind)


@app.post("/api/admin/features", dependencies=[Depends(admin)])
def add_feature(f: FeatureIn):
    if f.kind not in FEATURE_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(FEATURE_KINDS)}")
    expected = {"point": "Point", "line": "LineString", "polygon": "Polygon"}[FEATURE_KINDS[f.kind]]
    if f.geometry.get("type") != expected:
        raise HTTPException(400, f"{f.kind} needs {expected} geometry")
    row = S.store.add(f.kind, f.geometry, f.source, f.props, f.status, f.source_url, f.note)
    if f.status == "verified":
        S.rebuild()
    return {**row, "impact": _impact(row)}


class Decision(BaseModel):
    id: int
    decision: Literal["verified", "rejected"] = "verified"
    reviewer: str = "admin"
    geometry: Optional[dict] = None  # optional corrected geometry


@app.post("/api/validation/approve", dependencies=[Depends(admin)])
def approve(d: Decision):
    if not S.store.get(d.id):
        raise HTTPException(404, "feature not found")
    if d.geometry:
        S.store.update_geometry(d.id, d.geometry)
    row = S.store.set_status(d.id, d.decision, d.reviewer)
    S.rebuild()
    return {"feature": row, "stats": model().stats()}


@app.delete("/api/admin/features/{fid}", dependencies=[Depends(admin)])
def delete_feature(fid: int):
    S.store.delete(fid)
    S.rebuild()
    return {"ok": True}


@app.get("/api/admin/audit", dependencies=[Depends(admin)])
def audit():
    return S.store.audit()


@app.post("/api/admin/rebuild", dependencies=[Depends(admin)])
def rebuild():
    S.rebuild()
    return {"build_ms": S.build_ms, "stats": model().stats()}


# ------------------------------------------------- serve built frontend (prod)
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")

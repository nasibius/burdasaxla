"""BurdaSaxla HTTP API (FastAPI)."""
from __future__ import annotations

import hmac
import logging
import math
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AfterValidator, BaseModel, Field
from shapely.geometry import box, shape

from . import config as C
from .citymodel import CityModel, load_raw
from .dropoff import Recommender
from .rules import RULES, ruleset
from .store import FEATURE_KINDS, Store

log = logging.getLogger("burdasaxla")

AREA_MARGIN_DEG = 0.01  # ~1 km around the modelled bbox is still accepted


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.store = Store()
        self.raw = None
        self.model: CityModel | None = None
        self.rec: Recommender | None = None
        self.build_ms = None

    def ensure_seed(self):
        """First run only: a clearly-labelled demo survey area so the demo shows green curbs.
        Replace it with real field-survey polygons before any real-world use."""
        if self.store.list(kind="survey_area") or C.NO_DEMO_SEED:
            return
        s, w, n, e = self.raw["bbox"]
        ds, dw = (n - s) * 0.15, (e - w) * 0.15  # inner 70% of the bbox
        poly = {"type": "Polygon", "coordinates": [[[w + dw, s + ds], [e - dw, s + ds], [e - dw, n - ds],
                                                    [w + dw, n - ds], [w + dw, s + ds]]]}
        self.store.add("survey_area", poly, source="demo_seed", status="verified",
                       note="DEMO: treated as surveyed for the hackathon demo. Replace with real field-survey areas.",
                       props={"label": "Demo survey area"})

    def rebuild(self):
        """Rebuild the city model. On failure the previous model keeps serving."""
        with self.lock:
            t0 = time.perf_counter()
            if self.raw is None:
                self.raw = load_raw()
                self.ensure_seed()
            model = CityModel(self.raw, self.store.list())
            self.model, self.rec = model, Recommender(model)
            self.build_ms = round((time.perf_counter() - t0) * 1000)
            if model.feature_errors:
                log.warning("features skipped during build: %s", model.feature_errors)

    def area(self):
        s, w, n, e = self.raw["bbox"]
        return box(w - AREA_MARGIN_DEG, s - AREA_MARGIN_DEG, e + AREA_MARGIN_DEG, n + AREA_MARGIN_DEG)


S = State()


@asynccontextmanager
async def lifespan(_app):
    if C.ADMIN_TOKEN == C.DEFAULT_ADMIN_TOKEN:
        log.warning("Using the default admin token. Set BURDASAXLA_ADMIN_TOKEN before exposing the API.")
    S.rebuild()
    yield


app = FastAPI(title="BurdaSaxla API", version="0.2.0", lifespan=lifespan,
              description="Legal curbside stopping map for Baku — deterministic rule engine + drop-off recommender.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["content-type", "x-admin-token"])
app.add_middleware(GZipMiddleware, minimum_size=1000)


def model() -> CityModel:
    if S.model is None:
        raise HTTPException(503, "City model not built yet")
    return S.model


def admin(x_admin_token: str = Header(default="")):
    if not hmac.compare_digest(x_admin_token.encode(), C.ADMIN_TOKEN.encode()):
        raise HTTPException(401, "Admin token required")
    return True


# ------------------------------------------------------------- validation
def _check_lonlat(v: list[float]) -> list[float]:
    lon, lat = v
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("expected [lon, lat] in WGS84 degrees")
    return v


LonLat = Annotated[list[float], Field(min_length=2, max_length=2, description="[lon, lat]"),
                   AfterValidator(_check_lonlat)]


def in_area(c) -> bool:
    from shapely.geometry import Point
    return S.area().contains(Point(c))


GEOM_FOR_KIND = {"point": "Point", "line": "LineString", "polygon": "Polygon"}


def validate_geometry(kind: str, geom: dict):
    expected = GEOM_FOR_KIND[FEATURE_KINDS[kind]]
    if not isinstance(geom, dict) or geom.get("type") != expected:
        raise HTTPException(400, f"{kind} needs a {expected} geometry")
    try:
        g = shape(geom)
    except Exception as exc:  # noqa: BLE001 - malformed coordinates
        raise HTTPException(400, f"invalid geometry: {exc}") from exc
    if g.is_empty or not g.is_valid:
        raise HTTPException(400, "geometry is empty or self-intersecting")
    if expected == "LineString" and g.length == 0:
        raise HTTPException(400, "line needs two distinct points")
    if not S.area().contains(g):
        raise HTTPException(400, "geometry is outside the modelled area")


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
            "ruleset": ruleset()["version"], "stats": m.stats(), "mode": "api"}


@app.get("/api/rules")
def rules():
    return ruleset()


@app.get("/api/map/segments")
def map_segments(status: Literal["PROHIBITED", "VERIFIED", "UNKNOWN"] | None = None):
    return model().segments_geojson(status)


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
def search(q: str = Query(..., min_length=1, max_length=100), limit: int = Query(8, ge=1, le=25)):
    return model().search(q, limit)


class RecRequest(BaseModel):
    destination: LonLat
    origin: LonLat | None = None
    mode: Literal["dropoff", "pickup"] = "dropoff"
    max_walk_m: int = Field(450, ge=50, le=1500)
    time: str | None = Field(None, max_length=40)  # reserved for time-dependent restrictions


@app.post("/api/dropoff/recommendations")
def recommendations(req: RecRequest):
    model()
    if not in_area(req.destination):
        return {"results": [], "message": "outside_area", "curb_at_door": None, "diagnostics": {}, "warnings": []}
    origin = req.origin if req.origin and in_area(req.origin) else None
    out = S.rec.recommend(req.destination, origin, req.mode, req.max_walk_m)
    if req.origin and origin is None:
        out.setdefault("warnings", []).append("origin_outside_area")
    return out


class DriverRequest(BaseModel):
    origin: LonLat
    radius_m: int = Field(1200, ge=100, le=3000)


@app.post("/api/driver/nearest-stops")
def driver_nearest(req: DriverRequest):
    model()
    if not in_area(req.origin):
        return {"origin": req.origin, "results": [], "message": "outside_area"}
    return S.rec.nearest_stops(req.origin, req.radius_m)


@app.get("/api/official-zones")
def official_zones():
    return S.store.list(status="verified", kind="official_zone")


@app.get("/api/features")
def public_features():
    """Verified curated features (signs, markings, survey areas) for map display."""
    return S.store.list(status="verified")


# ----------------------------------------------------------------- admin API
Source = Literal["field_survey", "ayna_official", "street_imagery", "ai_vision", "osm", "demo_seed"]


class FeatureIn(BaseModel):
    kind: Literal[tuple(FEATURE_KINDS)]  # type: ignore[valid-type]
    geometry: dict
    source: Source = "field_survey"
    source_url: str | None = Field(None, max_length=500, pattern=r"^https?://")
    note: str | None = Field(None, max_length=1000)
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
    if not matches and f["kind"] != "survey_area":
        conflicts.append({"segment_id": None, "type": "no_road_nearby"})
    return {"matched": [{"way_id": w.id, "side": s, "start_m": round(a, 1), "end_m": round(b, 1), "street": w.name}
                        for w, s, a, b in matches],
            "affected_segments": affected[:200], "conflicts": conflicts}


def _safe_impact(f):
    try:
        return _impact(f)
    except Exception:  # noqa: BLE001 - a broken legacy row must not break the queue
        log.exception("impact failed for feature %s", f.get("id"))
        return {"matched": [], "affected_segments": [], "conflicts": [{"segment_id": None, "type": "invalid_geometry"}]}


@app.get("/api/validation/tasks", dependencies=[Depends(admin)])
def validation_tasks():
    return [{**f, "impact": _safe_impact(f)} for f in S.store.list(status="pending")]


@app.post("/api/admin/preview", dependencies=[Depends(admin)])
def preview(f: FeatureIn):
    validate_geometry(f.kind, f.geometry)
    return _impact({**f.model_dump(), "id": -1})


@app.get("/api/admin/features", dependencies=[Depends(admin)])
def admin_features(status: Literal["pending", "verified", "rejected"] | None = None, kind: str | None = None):
    return S.store.list(status=status, kind=kind)


@app.post("/api/admin/features", dependencies=[Depends(admin)])
def add_feature(f: FeatureIn):
    validate_geometry(f.kind, f.geometry)
    row = S.store.add(f.kind, f.geometry, f.source, f.props, f.status, f.source_url, f.note)
    if f.status == "verified":
        S.rebuild()
    return {**row, "impact": _safe_impact(row)}


class Decision(BaseModel):
    id: int
    decision: Literal["verified", "rejected"] = "verified"
    reviewer: str = Field("admin", max_length=80)
    geometry: dict | None = None  # optional corrected geometry


@app.post("/api/validation/approve", dependencies=[Depends(admin)])
def approve(d: Decision):
    row = S.store.get(d.id)
    if not row:
        raise HTTPException(404, "feature not found")
    if d.geometry:
        validate_geometry(row["kind"], d.geometry)
        S.store.update_geometry(d.id, d.geometry)
    elif d.decision == "verified":
        validate_geometry(row["kind"], row["geometry"])
    row = S.store.set_status(d.id, d.decision, d.reviewer)
    S.rebuild()
    return {"feature": row, "stats": model().stats()}


@app.delete("/api/admin/features/{fid}", dependencies=[Depends(admin)])
def delete_feature(fid: int):
    if not S.store.get(fid):
        raise HTTPException(404, "feature not found")
    S.store.delete(fid)
    S.rebuild()
    return {"ok": True}


@app.get("/api/admin/audit", dependencies=[Depends(admin)])
def audit():
    return S.store.audit()


@app.post("/api/admin/rebuild", dependencies=[Depends(admin)])
def rebuild():
    S.rebuild()
    return {"build_ms": S.build_ms, "stats": model().stats(), "feature_errors": model().feature_errors}


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "DELETE"], include_in_schema=False)
def api_not_found(rest: str):
    raise HTTPException(404, "unknown API endpoint")


# ------------------------------------------------- serve built frontend (prod)
DIST = (Path(__file__).resolve().parents[2] / "frontend" / "dist").resolve()
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = (DIST / path).resolve()
        # only serve files that really live inside dist/ (blocks ../ traversal)
        if path and f.is_file() and f.is_relative_to(DIST):
            return FileResponse(f)
        return FileResponse(DIST / "index.html")

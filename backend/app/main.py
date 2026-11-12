"""BurdaSaxla HTTP API (FastAPI)."""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import logging
import math
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import AfterValidator, BaseModel, Field, ValidationError
from shapely.geometry import Point, box, shape

from . import config as C
from . import ingest, planning
from .citymodel import CityModel, feature_prohibits, load_raw
from .dropoff import Recommender
from .rules import RULES, VEHICLE_CLASSES, ruleset
from .store import AUTOMATED_SOURCES, FEATURE_KINDS, Store

log = logging.getLogger("burdasaxla")

AREA_MARGIN_DEG = 0.01  # ~1 km around the modelled bbox is still accepted
EVIDENCE_DIR = C.DATA_DIR / "evidence"
MAX_PHOTO_BYTES = 15 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
OBSERVED_CLAUSES = {"52.IV.1", "52.IV.3", "52.IV.5", "52.IV.8", "52.IV.9", "52.IV.11"}


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.store = Store()
        self.raw = None
        self.model: CityModel | None = None
        self.rec: Recommender | None = None
        self.build_ms = None

    def rebuild(self):
        """Rebuild the city model. On failure the previous model keeps serving."""
        with self.lock:
            t0 = time.perf_counter()
            if self.raw is None:
                self.raw = load_raw()
            model = CityModel(self.raw, self.store.list(with_evidence=False))
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
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    S.rebuild()
    yield


app = FastAPI(title="BurdaSaxla API", version="0.3.0", lifespan=lifespan,
              description="Legal curbside stopping map for Baku — deterministic rule engine (Law 517-IQ) + "
                          "drop-off recommender + evidence-based validation workflow.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "PATCH", "DELETE"],
                   allow_headers=["content-type", "x-admin-token"])
app.add_middleware(GZipMiddleware, minimum_size=1000)


def model() -> CityModel:
    if S.model is None:
        raise HTTPException(503, "City model not built yet")
    return S.model


def is_admin(token: str) -> bool:
    return hmac.compare_digest((token or "").encode(), C.ADMIN_TOKEN.encode())


def admin(x_admin_token: str = Header(default="")):
    if not is_admin(x_admin_token):
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
Vehicle = Literal["taxi", "private"]


def in_area(c) -> bool:
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


def validate_props(kind: str, props: dict):
    side = props.get("side")
    if side not in (None, "left", "right"):
        raise HTTPException(400, "props.side must be 'left', 'right' or omitted (auto from position)")
    if kind in ("sign_3_27", "sign_3_28"):
        mode = props.get("zone_mode", "to_next_intersection")
        if mode not in ("to_next_intersection", "length", "to_point"):
            raise HTTPException(400, "props.zone_mode must be to_next_intersection, length or to_point")
        if mode == "length":
            zl = props.get("zone_length_m")
            if not isinstance(zl, (int, float)) or not 1 <= zl <= 1000:
                raise HTTPException(400, "props.zone_length_m (plate 7.2.2) must be 1–1000 m")
        if mode == "to_point":
            try:
                _check_lonlat(props.get("zone_end") or [])
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, "props.zone_end (repeated sign with plate 7.2.3) must be [lon, lat]") from exc
    if kind == "bus_lane" and props.get("line_type", "unknown") not in ("solid", "dashed", "unknown"):
        raise HTTPException(400, "props.line_type must be solid, dashed or unknown")
    if len(str(props.get("plate") or "")) > 200:
        raise HTTPException(400, "props.plate too long")


def traceable(row: dict) -> bool:
    return bool(row.get("source_url") or row.get("source_ref") or row.get("evidence"))


def verification_problems(row: dict) -> list[str]:
    """Why a feature cannot be marked verified yet (empty list = OK)."""
    problems = []
    if not traceable(row):
        problems.append("No traceable evidence: attach a photo, or record a source URL / reference.")
    if not row.get("observer"):
        problems.append("Observer (who saw it) is missing.")
    if row["kind"] == "observed_prohibition" and (row.get("props") or {}).get("clause") not in OBSERVED_CLAUSES:
        problems.append(f"Observed prohibition needs its legal clause, one of {sorted(OBSERVED_CLAUSES)}.")
    if row["kind"] == "survey_area" and not (row.get("note") and row.get("observed_at")):
        problems.append("Survey area needs a note describing what was checked and the survey date.")
    if ingest.sign_at_camera_position(row, row.get("evidence") or []):
        problems.append("Sign position equals the photo's camera GPS position. Place the sign where it stands.")
    try:
        validate_geometry(row["kind"], row["geometry"])
    except HTTPException as exc:
        problems.append(str(exc.detail))
    return problems


# ---------------------------------------------------------------- public API
@app.get("/api/health")
def health():
    return {"ok": S.model is not None, "build_ms": S.build_ms}


@app.get("/api/meta")
def meta(vehicle: Vehicle = C.DEFAULT_VEHICLE):
    m = model()
    s, w, n, e = m.bbox
    return {"area": "28 May, Bakı", "bbox": m.bbox, "center": [(w + e) / 2, (s + n) / 2],
            "osm_timestamp": m.osm_timestamp, "built_at": m.built_at, "build_ms": S.build_ms,
            "ruleset": ruleset()["version"], "law": ruleset()["law"], "stats": m.stats(vehicle), "mode": "api",
            "vehicle": vehicle, "vehicles": list(VEHICLE_CLASSES)}


@app.get("/api/rules")
def rules():
    """Legal rule catalog: article, official quote, verification level, effect."""
    return ruleset()


@app.get("/api/map/segments")
def map_segments(status: Literal["PROHIBITED", "ALLOWED", "UNVERIFIED"] | None = None,
                 vehicle: Vehicle = C.DEFAULT_VEHICLE):
    return model().segments_geojson(status, vehicle)


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
    vehicle: Vehicle = C.DEFAULT_VEHICLE
    max_walk_m: int = Field(450, ge=50, le=1500)
    time: str | None = Field(None, max_length=40)  # reserved for time-dependent restrictions


@app.post("/api/dropoff/recommendations")
def recommendations(req: RecRequest):
    model()
    if not in_area(req.destination):
        return {"results": [], "unverified_candidates": [], "message": "outside_area", "curb_at_door": None,
                "diagnostics": {}, "warnings": []}
    origin = req.origin if req.origin and in_area(req.origin) else None
    out = S.rec.recommend(req.destination, origin, req.mode, req.max_walk_m, vehicle=req.vehicle)
    if req.origin and origin is None:
        out.setdefault("warnings", []).append("origin_outside_area")
    return out


class DriverRequest(BaseModel):
    origin: LonLat
    radius_m: int = Field(1200, ge=100, le=3000)
    vehicle: Vehicle = C.DEFAULT_VEHICLE


@app.post("/api/driver/nearest-stops")
def driver_nearest(req: DriverRequest):
    model()
    if not in_area(req.origin):
        return {"origin": req.origin, "results": [], "unverified_candidates": [], "message": "outside_area"}
    return S.rec.nearest_stops(req.origin, req.radius_m, vehicle=req.vehicle)


def _public(f):
    """Public view of a verified feature (no internal review notes)."""
    keep = ("id", "kind", "status", "geometry", "props", "source", "source_url", "source_ref", "observed_at",
            "verified_at", "evidence", "note")
    return {k: f.get(k) for k in keep}


@app.get("/api/features")
def public_features():
    """Verified curated observations for map display."""
    return [_public(f) for f in S.store.list(status="verified")]


@app.get("/api/official-zones")
def official_zones():
    return [_public(f) for f in S.store.list(status="verified", kind="official_zone")]


@app.get("/api/evidence/{eid}")
def evidence_file(eid: int, token: str = ""):
    """Photo evidence. Public only for verified observations; otherwise admins (token query param for <img>)."""
    ev = S.store.get_evidence(eid)
    if not ev:
        raise HTTPException(404, "evidence not found")
    f = S.store.get(ev["feature_id"])
    if not (f and f["status"] == "verified") and not is_admin(token):
        raise HTTPException(403, "evidence of unreviewed observations is admin-only")
    path = (EVIDENCE_DIR / ev["filename"]).resolve()
    if not path.is_relative_to(EVIDENCE_DIR.resolve()) or not path.is_file():
        raise HTTPException(404, "file missing")
    return FileResponse(path, media_type=ev["content_type"])


@app.get("/api/sources")
def data_sources():
    """What the map is built from, and how much of it is verified."""
    m = model()
    rows = S.store.list(with_evidence=False)
    by = {}
    for f in rows:
        key = (f["source"], f["kind"], f["status"])
        by[key] = by.get(key, 0) + 1
    surveyed_m = sum(b - a for spans in m.coverage.values() for a, b, _ in spans)
    total_m = sum(w.length * 2 for w in m.ways.values())
    return {
        "osm": {"snapshot": m.osm_timestamp, "ways": len(m.ways), "crossings": len(m.crossing_nodes),
                "bus_stops": len(m.bus_stops), "signals": len(m.signal_nodes),
                "traffic_sign_candidates": len(ingest.osm_candidates(m))},
        "observations": [{"source": s, "kind": k, "status": st, "count": c} for (s, k, st), c in sorted(by.items())],
        "survey_coverage": {"curb_m_verified": round(surveyed_m), "curb_m_total": round(total_m),
                            "share": round(surveyed_m / total_m, 4) if total_m else 0},
        "law": ruleset()["law"],
        "official_ayna_dataset": "none found on ayna.gov.az (checked 2026-11-12); zones are entered manually with URL",
        "mapillary": {"configured": bool(os.environ.get("MAPILLARY_TOKEN"))},
    }


# ----------------------------------------------------------------- admin API
EntrySource = Literal["field_survey", "street_photo", "mapillary", "ai_vision", "osm", "ayna_official", "other_official"]


class FeatureIn(BaseModel):
    kind: Literal[tuple(FEATURE_KINDS)]  # type: ignore[valid-type]
    geometry: dict
    source: EntrySource = "field_survey"
    source_url: str | None = Field(None, max_length=500, pattern=r"^https?://")
    source_ref: str | None = Field(None, max_length=200)
    observer: str = Field(..., min_length=2, max_length=80)
    observed_at: date | None = None
    note: str | None = Field(None, max_length=1000)
    props: dict = Field(default_factory=dict)
    status: Literal["pending", "verified"] = "pending"
    confidence: float | None = Field(None, ge=0, le=1)


class FeaturePatch(BaseModel):
    geometry: dict | None = None
    props: dict | None = None
    source_url: str | None = Field(None, max_length=500, pattern=r"^https?://")
    source_ref: str | None = Field(None, max_length=200)
    observer: str | None = Field(None, min_length=2, max_length=80)
    observed_at: date | None = None
    note: str | None = Field(None, max_length=1000)


def _impact(f):
    """Which segments a feature would touch, and whether it contradicts current data."""
    m = model()
    matches = m.match_feature(f)
    prohibits = feature_prohibits(f)
    affected, conflicts = [], []
    for w, side, a, b in matches:
        for seg in m.segments_by_way.get((w.id, side), []):
            if seg["end_m"] > a and seg["start_m"] < b:
                affected.append({"id": seg["id"], "status": seg["status"], "name": seg["name"], "side": side})
                if prohibits and seg["status"] == "ALLOWED":
                    conflicts.append({"segment_id": seg["id"], "type": "verified_green_would_become_red"})
                if f["kind"] == "official_zone" and seg["status"] == "PROHIBITED":
                    conflicts.append({"segment_id": seg["id"], "type": "official_zone_on_prohibited_curb",
                                      "rules": [r["rule"] for r in seg["reasons"]]})
                if f["kind"] == "sign_3_28" and any(r["rule"] == "SIGN_3_27" for r in seg["reasons"]):
                    conflicts.append({"segment_id": seg["id"], "type": "both_3_27_and_3_28"})
    if not matches and f["kind"] != "survey_area":
        conflicts.append({"segment_id": None, "type": "no_road_nearby"})
    return {"matched": [{"way_id": w.id, "side": s, "start_m": round(a, 1), "end_m": round(b, 1), "street": w.name,
                         "compass": w.compass((a + b) / 2, s), "travel": w.travel(s)} for w, s, a, b in matches],
            "affected_segments": affected[:200], "conflicts": conflicts}


def _safe_impact(f):
    try:
        return _impact(f)
    except Exception:  # noqa: BLE001 - a broken legacy row must not break the queue
        log.exception("impact failed for feature %s", f.get("id"))
        return {"matched": [], "affected_segments": [], "conflicts": [{"segment_id": None, "type": "invalid_geometry"}]}


def _with_review(f):
    return {**f, "impact": _safe_impact(f), "problems": verification_problems(f)}


@app.get("/api/validation/tasks", dependencies=[Depends(admin)])
def validation_tasks():
    return [_with_review(f) for f in S.store.list(status="pending")]


@app.post("/api/admin/preview", dependencies=[Depends(admin)])
def preview(f: FeatureIn):
    validate_geometry(f.kind, f.geometry)
    validate_props(f.kind, f.props)
    return _impact({**f.model_dump(), "id": -1})


@app.get("/api/admin/features", dependencies=[Depends(admin)])
def admin_features(status: Literal["pending", "verified", "rejected"] | None = None, kind: str | None = None):
    return S.store.list(status=status, kind=kind)


@app.get("/api/admin/features/{fid}", dependencies=[Depends(admin)])
def admin_feature(fid: int):
    f = S.store.get(fid)
    if not f:
        raise HTTPException(404, "feature not found")
    return {**_with_review(f), "audit": S.store.audit(feature_id=fid)}


@app.post("/api/admin/features", dependencies=[Depends(admin)])
def add_feature(f: FeatureIn):
    validate_geometry(f.kind, f.geometry)
    validate_props(f.kind, f.props)
    status = f.status
    if f.source in AUTOMATED_SOURCES:
        status = "pending"  # automated detections always go through human review
    row = {**f.model_dump(), "status": status, "evidence": [],
           "observed_at": f.observed_at.isoformat() if f.observed_at else None}
    if status == "verified":
        problems = verification_problems(row)
        if problems:
            raise HTTPException(400, " ".join(problems))
    row = S.store.add(f.kind, f.geometry, f.source, f.props, status, f.source_url, f.note, source_ref=f.source_ref,
                      observer=f.observer, observed_at=row["observed_at"], confidence=f.confidence)
    S.rebuild()
    return _with_review(row)


@app.patch("/api/admin/features/{fid}", dependencies=[Depends(admin)])
def edit_feature(fid: int, patch: FeaturePatch, x_admin_user: str = Header(default="admin")):
    row = S.store.get(fid)
    if not row:
        raise HTTPException(404, "feature not found")
    fields = patch.model_dump(exclude_unset=True)
    if "geometry" in fields:
        validate_geometry(row["kind"], fields["geometry"])
    if "props" in fields:
        validate_props(row["kind"], fields["props"])
    if "observed_at" in fields and fields["observed_at"]:
        fields["observed_at"] = fields["observed_at"].isoformat()
    row = S.store.update(fid, by=x_admin_user[:80], **fields)
    S.rebuild()
    return _with_review(row)


@app.post("/api/admin/features/{fid}/evidence", dependencies=[Depends(admin)])
async def upload_evidence(fid: int, file: UploadFile = File(...)):
    row = S.store.get(fid)
    if not row:
        raise HTTPException(404, "feature not found")
    if file.content_type not in PHOTO_TYPES:
        raise HTTPException(400, f"photo must be one of {sorted(PHOTO_TYPES)}")
    data = await file.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "photo larger than 15 MB")
    sha = hashlib.sha256(data).hexdigest()
    name = f"{sha}{PHOTO_TYPES[file.content_type]}"
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / name).write_bytes(data)
    meta = ingest.photo_metadata(data)
    ev = S.store.add_evidence(fid, name, (file.filename or "")[:200], file.content_type, sha, len(data),
                              meta["camera"], meta["taken_at"], meta["exif"])
    return {"evidence": ev, "camera": meta["camera"], "taken_at": meta["taken_at"],
            "note": "Camera position is where the photo was taken. Place the sign where it actually stands."}


class Decision(BaseModel):
    id: int
    decision: Literal["verified", "rejected"] = "verified"
    reviewer: str = Field("admin", max_length=80)
    review_note: str | None = Field(None, max_length=1000)
    geometry: dict | None = None  # optional corrected geometry


@app.post("/api/validation/approve", dependencies=[Depends(admin)])
def approve(d: Decision):
    row = S.store.get(d.id)
    if not row:
        raise HTTPException(404, "feature not found")
    if d.geometry:
        validate_geometry(row["kind"], d.geometry)
        S.store.update(d.id, by=d.reviewer, geometry=d.geometry)
        row = S.store.get(d.id)
    if d.decision == "verified":
        problems = verification_problems(row)
        if problems:
            raise HTTPException(400, " ".join(problems))
    elif not d.review_note:
        raise HTTPException(400, "A rejection needs a review note (why it was rejected).")
    row = S.store.set_status(d.id, d.decision, d.reviewer, d.review_note)
    S.rebuild()
    return {"feature": row, "stats": model().stats()}


@app.delete("/api/admin/features/{fid}", dependencies=[Depends(admin)])
def delete_feature(fid: int):
    if not S.store.get(fid):
        raise HTTPException(404, "feature not found")
    S.store.delete(fid)
    S.rebuild()
    return {"ok": True}


class ImportRequest(BaseModel):
    observer: str = Field("importer", min_length=2, max_length=80)


@app.post("/api/admin/import/osm", dependencies=[Depends(admin)])
def import_osm(req: ImportRequest):
    candidates = ingest.osm_candidates(model())
    result = ingest.enqueue(S.store, candidates, req.observer)
    S.rebuild()
    return {"source": "osm", "found": len(candidates), **result}


@app.post("/api/admin/import/mapillary", dependencies=[Depends(admin)])
def import_mapillary(req: ImportRequest):
    token = os.environ.get("MAPILLARY_TOKEN")
    if not token:
        raise HTTPException(400, "MAPILLARY_TOKEN is not configured on the server.")
    try:
        raw = ingest.fetch_mapillary(token, model().bbox)
    except Exception as exc:  # noqa: BLE001 - surface upstream failure
        raise HTTPException(502, f"Mapillary request failed: {exc}") from exc
    candidates = ingest.mapillary_candidates(raw)
    result = ingest.enqueue(S.store, candidates, req.observer)
    S.rebuild()
    return {"source": "mapillary", "map_features_in_area": len(raw), "found": len(candidates), **result}


class GeoJSONImport(BaseModel):
    observer: str = Field(..., min_length=2, max_length=80)
    source: EntrySource = "field_survey"
    collection: dict


@app.post("/api/admin/import/geojson", dependencies=[Depends(admin)])
def import_geojson(req: GeoJSONImport):
    candidates, errors = ingest.geojson_candidates(req.collection, req.source)
    valid = []
    for i, c in enumerate(candidates):
        try:
            validate_geometry(c["kind"], c["geometry"])
            validate_props(c["kind"], c["props"])
            valid.append(c)
        except HTTPException as exc:
            errors.append(f"feature {i}: {exc.detail}")
    result = ingest.enqueue(S.store, valid, req.observer)
    S.rebuild()
    return {"source": req.source, "found": len(candidates), "errors": errors, **result}


@app.get("/api/admin/audit", dependencies=[Depends(admin)])
def audit(feature_id: int | None = None):
    return S.store.audit(feature_id=feature_id)


@app.post("/api/admin/rebuild", dependencies=[Depends(admin)])
def rebuild():
    S.rebuild()
    return {"build_ms": S.build_ms, "stats": model().stats(), "feature_errors": model().feature_errors}


# ------------------------------------------------------------ B2G / AYNA planning
AREA_ID = "28-may-pilot"
REVIEW_ACTIONS = ("needs_survey", "shortlist", "reject", "more_data")
LIMITATIONS = [
    "Proposals are investigation sites for an authority, NOT legal pick-up/drop-off permissions.",
    "Access nodes are OpenStreetMap places (proxies for where people go); they are not measured taxi demand.",
    "A coverage gap is only concluded when the verified-zone inventory is declared complete with a source; "
    "otherwise the finding is INVENTORY_UNKNOWN.",
    "Walking distances are shortest paths on the mapped pedestrian network; access legs to the network are straight lines.",
    "The walking threshold is a planning scenario assumption, not a legal distance.",
    "Scores use illustrative weights; unavailable factors are excluded, not scored as zero.",
]


def planning_area():
    s, w, n, e = S.raw["bbox"]
    poly = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
    return S.store.ensure_area(AREA_ID, "28 May pilot (Bakı)", poly)


_plan_cache: dict = {}


def plan(threshold_m: int = planning.DEFAULT_THRESHOLD_M, record_run=False):
    model()
    area = planning_area()
    activity = S.store.list_activity(status="verified")
    key = (S.model.built_at, threshold_m, area["inventory_status"], area["inventory_declared_at"],
           tuple((a["id"], a["verified_at"]) for a in activity))
    if key not in _plan_cache or record_run:
        _plan_cache.clear()
        result = planning.Planner(S.model, activity, area).run(threshold_m)
        result["area"]["polygon"] = area["polygon"]
        result["area"]["name"] = area["name"]
        result["limitations"] = LIMITATIONS
        if record_run:
            result["run_id"] = S.store.add_run(AREA_ID, result["algorithm_version"], result["source_versions"],
                                               result["parameters"], result["summary"])
        _plan_cache[key] = result
    return planning.attach_reviews(_plan_cache[key], S.store.reviews())


Threshold = Query(planning.DEFAULT_THRESHOLD_M, ge=100, le=1000, description="Walking threshold (planning assumption)")


@app.get("/api/authority/overview")
def authority_overview(threshold_m: int = Threshold):
    r = plan(threshold_m)
    return {k: r[k] for k in ("algorithm_version", "generated_at", "parameters", "area", "source_versions",
                              "inventory_complete", "demand_measured", "summary", "limitations")} | {
        "supply": r["supply"], "observed_suitable": r["observed_suitable"], "runs": S.store.runs(5)}


@app.get("/api/authority/coverage")
def authority_coverage(threshold_m: int = Threshold):
    r = plan(threshold_m)
    return {"threshold_m": threshold_m, "inventory_complete": r["inventory_complete"], "nodes": r["coverage"]}


def _items(r, kind, review):
    items = (r["survey_tasks"] if kind in ("all", "survey") else []) + (r["candidates"] if kind in ("all", "candidate") else [])
    if review == "unreviewed":
        items = [i for i in items if not i.get("review")]
    elif review:
        items = [i for i in items if i.get("review") and i["review"]["action"] == review]
    return items


@app.get("/api/authority/candidates")
def authority_candidates(threshold_m: int = Threshold, kind: Literal["all", "survey", "candidate"] = "all",
                         review: str | None = None):
    r = plan(threshold_m)
    return {"inventory_complete": r["inventory_complete"], "demand_measured": r["demand_measured"],
            "items": _items(r, kind, review)}


@app.get("/api/authority/candidates/{item_id}")
def authority_candidate(item_id: str, threshold_m: int = Threshold):
    r = plan(threshold_m)
    for i in r["survey_tasks"] + r["candidates"]:
        if i["id"] == item_id:
            return i
    raise HTTPException(404, "planning item not found")


@app.post("/api/authority/recommendations/run", dependencies=[Depends(admin)])
def authority_run(threshold_m: int = Threshold):
    r = plan(threshold_m, record_run=True)
    return {"run_id": r["run_id"], "summary": r["summary"], "generated_at": r["generated_at"]}


class ReviewIn(BaseModel):
    action: Literal[REVIEW_ACTIONS]  # type: ignore[valid-type]
    reason: str | None = Field(None, max_length=1000)
    reviewer: str = Field(..., min_length=2, max_length=80)


@app.post("/api/authority/candidates/{item_id}/review", dependencies=[Depends(admin)])
def authority_review(item_id: str, body: ReviewIn, threshold_m: int = Threshold):
    r = plan(threshold_m)
    item = next((i for i in r["survey_tasks"] + r["candidates"] if i["id"] == item_id), None)
    if not item:
        raise HTTPException(404, "planning item not found")
    if body.action == "reject" and not body.reason:
        raise HTTPException(400, "Rejecting needs a reason.")
    S.store.add_review(item_id, item["type"], body.action, body.reviewer, body.reason, (S.store.runs(1) or [{}])[0].get("id"))
    return {"ok": True, "item": authority_candidate(item_id, threshold_m),
            "note": "Planning review recorded. This does not create or approve a legal stop."}


class InventoryIn(BaseModel):
    status: Literal["unknown", "complete"]
    source_url: str | None = Field(None, max_length=500, pattern=r"^https?://")
    declared_by: str = Field(..., min_length=2, max_length=80)
    note: str | None = Field(None, max_length=1000)


@app.post("/api/authority/inventory", dependencies=[Depends(admin)])
def authority_inventory(body: InventoryIn):
    """Declare whether the area's verified-zone inventory is complete. 'complete' needs an official source."""
    if body.status == "complete" and not body.source_url:
        raise HTTPException(400, "Declaring the inventory complete needs a source URL (e.g. the official AYNA list).")
    planning_area()
    return S.store.set_inventory_status(AREA_ID, body.status, body.declared_by, body.source_url, body.note)


def _export_rows(items, r):
    for i in items:
        rev = i.get("review") or {}
        lon, lat = i.get("centroid") or i.get("point")
        yield {
            "id": i["id"], "type": i["type"], "rank": i.get("rank"),
            "class": i.get("candidate_class") or "SURVEY_TASK",
            "score": i.get("score") if i["type"] == "candidate" else i.get("priority_score"),
            "street": i.get("street", ""), "road_side": i.get("road_side", ""), "lon": round(lon, 6), "lat": round(lat, 6),
            "why": i.get("why", ""), "missing_evidence": " | ".join(i.get("missing_evidence") or []),
            "factors_missing": " | ".join(i.get("factors_missing") or []),
            "coverage_states": json.dumps(i.get("coverage_states") or {}),
            "access_nodes_are_proxy": i.get("access_nodes_are_proxy", ""),
            "demand_measured": r["demand_measured"], "officially_approved": False, "current_legal_status":
                i.get("current_legal_status", ""), "review_action": rev.get("action", ""),
            "review_reason": rev.get("reason", ""), "reviewer": rev.get("reviewer", ""),
            "threshold_m": r["parameters"]["threshold_m"], "algorithm_version": r["algorithm_version"],
            "osm_snapshot": r["source_versions"]["osm_snapshot"], "generated_at": r["generated_at"],
            "is_synthetic_example": False,
        }


@app.get("/api/authority/export")
def authority_export(format: Literal["csv", "geojson"] = "csv", threshold_m: int = Threshold,
                     kind: Literal["all", "survey", "candidate"] = "all", review: str | None = None):
    r = plan(threshold_m)
    items = _items(r, kind, review)
    if format == "geojson":
        feats = [{"type": "Feature", "geometry": i["geometry"], "properties": row}
                 for i, row in zip(items, _export_rows(items, r), strict=True)]
        return JSONResponse({"type": "FeatureCollection", "features": feats,
                             "metadata": {"limitations": LIMITATIONS, "area": r["area"]["name"],
                                          "inventory_complete": r["inventory_complete"],
                                          "source_versions": r["source_versions"], "parameters": r["parameters"]}},
                            headers={"content-disposition": "attachment; filename=burdasaxla-planning.geojson"})
    buf = io.StringIO()
    rows = list(_export_rows(items, r))
    fields = list(rows[0].keys()) if rows else ["id"]
    wr = csv.DictWriter(buf, fieldnames=fields + ["limitations"])
    wr.writeheader()
    for row in rows:
        wr.writerow({**row, "limitations": " ".join(LIMITATIONS)})
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"content-disposition": "attachment; filename=burdasaxla-planning.csv"})


# ------------------------------------------------- measured passenger activity table
ACTIVITY_PUBLIC_MIN = 5   # small counts are suppressed in public output


class ActivityIn(BaseModel):
    place_name: str = Field(..., min_length=2, max_length=160)
    point: LonLat
    period_start: datetime
    period_end: datetime
    pickups: int = Field(..., ge=0, le=100_000, description="passengers getting IN")
    dropoffs: int = Field(..., ge=0, le=100_000, description="passengers getting OUT")
    vehicle_scope: Literal["taxi", "all_cars", "other"] = "taxi"
    method: Literal["field_count", "operator_aggregate", "official_statistic"]
    source: str = Field(..., min_length=2, max_length=120)
    source_url: str | None = Field(None, max_length=500, pattern=r"^https?://")
    source_ref: str | None = Field(None, max_length=200)
    observer: str = Field(..., min_length=2, max_length=80)
    note: str | None = Field(None, max_length=1000)


def _check_activity(a: ActivityIn):
    if a.period_end <= a.period_start:
        raise HTTPException(400, "period_end must be after period_start")
    if (a.period_end - a.period_start).days > 366:
        raise HTTPException(400, "counting period longer than a year")
    if not in_area(a.point):
        raise HTTPException(400, "point is outside the modelled area")


def _public_activity(a):
    def sup(n):
        return n if n >= ACTIVITY_PUBLIC_MIN else f"<{ACTIVITY_PUBLIC_MIN}"
    rate = planning.Planner.activity_rate(a)
    return {"id": a["id"], "place_name": a["place_name"], "geometry": a["geometry"], "period_start": a["period_start"],
            "period_end": a["period_end"], "pickups": sup(a["pickups"]), "dropoffs": sup(a["dropoffs"]),
            "per_hour": round(rate, 1) if rate is not None and a["pickups"] + a["dropoffs"] >= ACTIVITY_PUBLIC_MIN else None,
            "vehicle_scope": a["vehicle_scope"], "method": a["method"], "source": a["source"],
            "source_url": a["source_url"], "verified_at": a["verified_at"], "measured": True}


@app.get("/api/activity")
def activity_public():
    """Verified, aggregated boarding/alighting counts, busiest first. Empty = not measured (nothing is estimated)."""
    rows = [_public_activity(a) for a in S.store.list_activity(status="verified")]
    rows.sort(key=lambda x: -(x["per_hour"] or 0))
    return {"rows": rows, "measured": bool(rows), "suppression_threshold": ACTIVITY_PUBLIC_MIN}


@app.get("/api/admin/activity", dependencies=[Depends(admin)])
def activity_admin():
    return S.store.list_activity()


@app.post("/api/admin/activity", dependencies=[Depends(admin)])
def activity_add(a: ActivityIn):
    _check_activity(a)
    return S.store.add_activity(geometry={"type": "Point", "coordinates": a.point}, place_name=a.place_name,
                                period_start=a.period_start.isoformat(), period_end=a.period_end.isoformat(),
                                pickups=a.pickups, dropoffs=a.dropoffs, vehicle_scope=a.vehicle_scope, method=a.method,
                                source=a.source, source_url=a.source_url, source_ref=a.source_ref, observer=a.observer,
                                note=a.note)


class ActivityDecision(BaseModel):
    decision: Literal["verified", "rejected"]
    reviewer: str = Field(..., min_length=2, max_length=80)
    review_note: str | None = Field(None, max_length=1000)


@app.post("/api/admin/activity/{aid}/review", dependencies=[Depends(admin)])
def activity_review(aid: int, d: ActivityDecision):
    a = S.store.get_activity(aid)
    if not a:
        raise HTTPException(404, "activity row not found")
    if d.decision == "verified" and not (a["source_url"] or a["source_ref"]):
        raise HTTPException(400, "A count can only be verified with a source URL or reference (count sheet, dataset id).")
    if d.decision == "rejected" and not d.review_note:
        raise HTTPException(400, "A rejection needs a review note.")
    return S.store.set_activity_status(aid, d.decision, d.reviewer, d.review_note)


@app.delete("/api/admin/activity/{aid}", dependencies=[Depends(admin)])
def activity_delete(aid: int):
    S.store.delete_activity(aid)
    return {"ok": True}


class ActivityCSV(BaseModel):
    csv_text: str = Field(..., max_length=2_000_000)
    observer: str = Field(..., min_length=2, max_length=80)


@app.post("/api/admin/activity/import", dependencies=[Depends(admin)])
def activity_import(body: ActivityCSV):
    """CSV columns: place_name,lon,lat,period_start,period_end,pickups,dropoffs,method,source[,source_url,source_ref,
    vehicle_scope,note]. Every row enters as pending."""
    created, errors = [], []
    for n, row in enumerate(csv.DictReader(io.StringIO(body.csv_text)), start=2):
        try:
            a = ActivityIn(place_name=row["place_name"], point=[float(row["lon"]), float(row["lat"])],
                           period_start=row["period_start"], period_end=row["period_end"], pickups=int(row["pickups"]),
                           dropoffs=int(row["dropoffs"]), method=row["method"], source=row["source"],
                           source_url=row.get("source_url") or None, source_ref=row.get("source_ref") or None,
                           vehicle_scope=row.get("vehicle_scope") or "taxi", observer=body.observer, note=row.get("note") or None)
            _check_activity(a)
            created.append(activity_add(a)["id"])
        except (KeyError, ValueError, ValidationError) as exc:
            errors.append(f"line {n}: {exc}".splitlines()[0][:200])
        except HTTPException as exc:
            errors.append(f"line {n}: {exc.detail}")
    return {"created": len(created), "ids": created, "errors": errors}


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PATCH", "DELETE"], include_in_schema=False)
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


__all__ = ["app", "RULES"]

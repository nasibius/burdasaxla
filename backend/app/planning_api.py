"""Authority endpoints; public read-only snapshots and authenticated append-only reviews."""
import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shapely.geometry import Point, box

from . import config as C
from .planning import AREA_ID, build_snapshot, export_candidates, filtered_candidates
from .planning_store import PlanningStore

ReviewStatus = Literal["needs_survey", "shortlist", "reject", "more_data_needed"]


class ReviewIn(BaseModel):
    action: ReviewStatus
    reason: str = Field(min_length=3, max_length=1000)
    run_id: str = Field(min_length=16, max_length=16)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, v):
        if len(v.strip()) < 3:
            raise ValueError("Please explain the decision")
        return v.strip()


class ActivityIn(BaseModel):
    """Aggregate passenger observations only; no identifiers or trajectories accepted."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    location_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=150)
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    period_start: datetime
    period_end: datetime
    pickups: int = Field(ge=0, le=10000000, strict=True)
    dropoffs: int = Field(ge=0, le=10000000, strict=True)
    source_ref: str = Field(min_length=3, max_length=200)
    source_url: str = Field(pattern=r"^https?://", max_length=500)
    license: str = Field(min_length=3, max_length=300)
    collection_method: str = Field(min_length=3, max_length=300)
    publication_permitted: bool = False

    @model_validator(mode="after")
    def period(self):
        if not self.period_start.tzinfo or not self.period_end.tzinfo:
            raise ValueError("Observation periods need an explicit timezone")
        self.period_start = self.period_start.astimezone(timezone.utc)
        self.period_end = self.period_end.astimezone(timezone.utc)
        hours = (self.period_end - self.period_start).total_seconds() / 3600
        if hours < 24 or hours > 24 * 366:
            raise ValueError("Use aggregated observation windows of 1–366 days")
        if self.period_end > datetime.now(timezone.utc):
            raise ValueError("Observed activity cannot be in the future")
        if self.publication_permitted and 0 < self.pickups + self.dropoffs < 10:
            raise ValueError("Public cells require at least 10 observed passenger movements; keep smaller cells private")
        return self

    def record(self):
        hours = (self.period_end - self.period_start).total_seconds() / 3600
        return {**self.model_dump(mode="json"), "passengers_per_hour": round((self.pickups + self.dropoffs) / hours, 3),
                "unit": "passenger movements", "is_synthetic_example": False}


class ActivityBatch(BaseModel):
    records: list[ActivityIn] = Field(min_length=1, max_length=500)


def router_for(state, get_model, authenticate):
    router = APIRouter(prefix="/api/authority", tags=["authority"])

    def store():
        return PlanningStore(state.store.path)

    def write_access(_auth=Depends(authenticate)):
        if C.ADMIN_TOKEN == C.DEFAULT_ADMIN_TOKEN:
            raise HTTPException(503, "Configure BURDASAXLA_ADMIN_TOKEN before enabling authority writes")

    def snapshot(area_id: str = AREA_ID, threshold_m: int = 450):
        if area_id != AREA_ID:
            raise HTTPException(404, "Only the 28 May pilot is available")
        st = store()
        city = get_model()
        return build_snapshot(city, city.features,
                              passenger_activity=st.activity(), reviews=st.reviews(public=True), threshold_m=threshold_m,
                              code_revision=os.environ.get("BURDASAXLA_CODE_REVISION", "unknown"))

    @router.get("/overview")
    def overview(area_id: str = AREA_ID, threshold_m: int = Query(450, ge=50, le=1500)):
        return snapshot(area_id, threshold_m)

    @router.get("/candidates")
    def candidates(area_id: str = AREA_ID, status: ReviewStatus | None = None):
        return filtered_candidates(snapshot(area_id), status)

    @router.get("/candidates/{candidate_id}")
    def candidate(candidate_id: str):
        found = next((c for c in snapshot()["candidates"] if c["candidate_id"] == candidate_id), None)
        if not found:
            raise HTTPException(404, "Candidate not found in current snapshot")
        return found

    @router.get("/coverage")
    def coverage(area_id: str = AREA_ID, threshold_m: int = Query(450, ge=50, le=1500)):
        return snapshot(area_id, threshold_m)["coverage"]

    @router.post("/recommendations/run", dependencies=[Depends(write_access)])
    def run(threshold_m: int = Query(450, ge=50, le=1500)):
        result = snapshot(threshold_m=threshold_m)
        store().save_run(result)
        return result

    @router.post("/candidates/{candidate_id}/review", dependencies=[Depends(write_access)])
    def review(candidate_id: str, body: ReviewIn, threshold_m: int = Query(450, ge=50, le=1500)):
        current = snapshot(threshold_m=threshold_m)
        if body.run_id != current["run_id"]:
            raise HTTPException(409, "Snapshot changed; reload before reviewing")
        if not any(c["candidate_id"] == candidate_id for c in current["candidates"]):
            raise HTTPException(404, "Candidate not found")
        st = store()
        st.save_run(current)
        return st.review(candidate_id, current["run_id"], body.action, body.reason)

    @router.get("/reviews", dependencies=[Depends(write_access)])
    def reviews():
        return store().reviews()

    @router.get("/export")
    def export(format: Literal["csv", "geojson"] = "csv", status: ReviewStatus | None = None,
               area_id: str = AREA_ID, threshold_m: int = Query(450, ge=50, le=1500)):
        return Response(export_candidates(snapshot(area_id, threshold_m), format, status),
                        media_type="text/csv" if format == "csv" else "application/geo+json",
                        headers={"Content-Disposition": f'attachment; filename="authority.{format}"'})

    @router.get("/passenger-activity")
    def activity():
        return {"records": store().activity(), "unit": "passenger movements",
                "limitation": "Observed source/period samples, not citywide taxi demand. Overlapping sources are not summed."}

    @router.post("/passenger-activity", dependencies=[Depends(write_access)])
    def import_activity(body: ActivityBatch):
        south, west, north, east = get_model().bbox
        if any(not box(west, south, east, north).covers(Point(r.longitude, r.latitude)) for r in body.records):
            raise HTTPException(422, "Activity location outside pilot")
        try:
            count = store().import_activity([r.record() for r in body.records])
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"imported": count, "records": store().activity()}

    return router

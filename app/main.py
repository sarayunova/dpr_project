"""API routes -- contract in docs/08_api_specification.md.

Response shapes match that spec exactly; if you need to change one,
update the doc in the same change (per CLAUDE.md) rather than letting
the dashboard's contract drift silently.
"""

from __future__ import annotations

import io
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import (
    SESSION_COOKIE,
    authenticate,
    cookie_secure,
    create_session,
    delete_session,
    get_current_user,
    session_lifetime,
)
from app.database import get_db
from app.ingest import extract_text_from_pdf, ingest_dpr_text
from app.jobs import (
    enqueue_pdf,
    notify_worker,
    queue_failed_repair_checks,
    start_worker,
    stop_worker,
    worker_enabled,
)
from app.models import (
    DailyEntry,
    IngestJob,
    PhaseSnapshot,
    RepairEvent,
    SourceDocument,
    User,
    Well,
)
from app.storage import save_source_document, source_document_path



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Background ingestion worker (app/jobs.py). Not started under
    # TestClient unless used as a context manager -- tests drive the queue
    # with app.jobs.run_pending_jobs() instead.
    if worker_enabled():
        start_worker()
    yield
    if worker_enabled():
        stop_worker()


app = FastAPI(title="Drilling DPR Monitor", lifespan=lifespan)

# Every /api route except the auth ones below requires a logged-in user
# (docs/07_non_functional_requirements.md). /health and the static
# dashboard shell stay public -- neither exposes any well data.
LOGIN_REQUIRED = [Depends(get_current_user)]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    user = authenticate(db, body.email, body.password)
    if user is None:
        # Same message for unknown email and wrong password.
        raise HTTPException(status_code=401, detail="invalid email or password")
    response.set_cookie(
        SESSION_COOKIE,
        create_session(db, user),
        max_age=int(session_lifetime().total_seconds()),
        httponly=True,
        samesite="strict",
        secure=cookie_secure(),
    )
    return {"email": user.email}


@app.post("/api/auth/logout")
def logout(
    response: Response,
    dpr_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    if dpr_session:
        delete_session(db, dpr_session)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"email": user.email}


@app.post("/api/ingest", dependencies=LOGIN_REQUIRED)
async def ingest(
    files: list[UploadFile] = File(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    ingested = []
    errors = []

    for file in files:
        try:
            data = await file.read()
            text = extract_text_from_pdf(io.BytesIO(data))
            # Stored only once text extraction succeeds, so a non-PDF
            # upload never gets kept as a "system of record" document.
            document = save_source_document(db, file.filename, data)
            result = ingest_dpr_text(
                text, db, source_filename=file.filename, source_document=document
            )
            db.commit()
            ingested.append(result)
        except Exception as exc:
            db.rollback()
            errors.append({"filename": file.filename, "error": str(exc)})

    return {"ingested": ingested, "errors": errors}


@app.post("/api/ingest-jobs", dependencies=LOGIN_REQUIRED)
async def queue_ingest(
    files: list[UploadFile] = File(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Store and queue each PDF, returning immediately -- the dashboard's
    upload path. Processing happens in app/jobs.py's worker."""
    queued = []
    errors = []

    for file in files:
        try:
            job = enqueue_pdf(db, file.filename, await file.read())
            db.commit()
            queued.append({"job_id": job.id, "filename": file.filename})
        except Exception as exc:
            db.rollback()
            errors.append({"filename": file.filename, "error": str(exc)})

    notify_worker()
    return {"queued": queued, "errors": errors}


@app.get("/api/ingest-jobs", dependencies=LOGIN_REQUIRED)
def list_ingest_jobs(
    limit: int = Query(default=100, ge=1, le=1000), db: Session = Depends(get_db)
) -> dict[str, Any]:
    counts = dict.fromkeys(("queued", "running", "done", "failed"), 0)
    for status, count in (
        db.query(IngestJob.status, func.count()).group_by(IngestJob.status).all()
    ):
        counts[status] = count
    jobs = db.query(IngestJob).order_by(IngestJob.id.desc()).limit(limit).all()
    return {"counts": counts, "jobs": [_job_dict(job) for job in jobs]}


@app.get("/api/ingest-jobs/{job_id}", dependencies=LOGIN_REQUIRED)
def get_ingest_job(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = db.get(IngestJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="ingest job not found")
    return _job_dict(job)


@app.get("/api/wells", dependencies=LOGIN_REQUIRED)
def list_wells(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    wells = db.query(Well).order_by(Well.well_name).all()
    return [_well_summary(well, _latest_entry(db, well.id)) for well in wells]


@app.get("/api/wells/{well_id}", dependencies=LOGIN_REQUIRED)
def get_well(well_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    well = db.get(Well, well_id)
    if well is None:
        raise HTTPException(status_code=404, detail="well not found")

    entries = (
        db.query(DailyEntry)
        .filter_by(well_id=well_id)
        .order_by(DailyEntry.report_date)
        .all()
    )

    return {
        "well": {
            "id": well.id,
            "well_name": well.well_name,
            "location_code": well.location_code,
            "asset_name": well.asset_name,
            "category": well.category,
            "target_depth": well.target_depth,
        },
        "timeline": [_timeline_entry(entry) for entry in entries],
    }


@app.get("/api/wells/{well_id}/variance", dependencies=LOGIN_REQUIRED)
def get_well_variance(well_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    well = db.get(Well, well_id)
    if well is None:
        raise HTTPException(status_code=404, detail="well not found")

    entry = _latest_entry(db, well_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="no reports ingested for this well yet")

    return {
        "report_date": entry.report_date,
        "days_variance_pct": _variance_pct(entry.tot_days_actual, entry.tot_days_planned),
        "cost_variance_pct": _variance_pct(entry.cost_actual_inr, entry.cost_planned_inr),
        "phases": [_phase_variance(phase) for phase in entry.phases],
    }


@app.get("/api/repairs/unreviewed", dependencies=LOGIN_REQUIRED)
def list_unreviewed_repairs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (
        db.query(RepairEvent, DailyEntry, Well)
        .join(DailyEntry, RepairEvent.daily_entry_id == DailyEntry.id)
        .join(Well, DailyEntry.well_id == Well.id)
        .filter(RepairEvent.reviewed.is_(False))
        .order_by(DailyEntry.report_date.desc())
        .all()
    )
    return [
        {
            "repair_id": event.id,
            "well_name": well.well_name,
            "report_date": entry.report_date,
            "equipment_or_system": event.equipment_or_system,
            "snippet": event.snippet,
            "confidence": event.confidence,
        }
        for event, entry, well in rows
    ]


class ReviewRequest(BaseModel):
    # Defaults to "confirmed" so a bodyless POST (the original v1 contract)
    # keeps working -- see docs/08_api_specification.md for why this field
    # was added (Phase 7: track LLM precision over time, not just whether
    # a human looked at the flag).
    outcome: Literal["confirmed", "false_positive"] = "confirmed"


@app.get("/api/repairs/reviewed", dependencies=LOGIN_REQUIRED)
def list_reviewed_repairs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (
        db.query(RepairEvent, DailyEntry, Well)
        .join(DailyEntry, RepairEvent.daily_entry_id == DailyEntry.id)
        .join(Well, DailyEntry.well_id == Well.id)
        .filter(RepairEvent.reviewed.is_(True))
        .order_by(DailyEntry.report_date.desc())
        .all()
    )
    return [
        {
            "repair_id": event.id,
            "well_name": well.well_name,
            "report_date": entry.report_date,
            "equipment_or_system": event.equipment_or_system,
            "snippet": event.snippet,
            "confidence": event.confidence,
            "outcome": event.outcome,
        }
        for event, entry, well in rows
    ]


@app.get("/api/repairs/check-status", dependencies=LOGIN_REQUIRED)
def repair_check_status(db: Session = Depends(get_db)) -> dict[str, int]:
    """How many daily reports have NOT been checked for repair events
    because the local LLM failed ("failed"), or are waiting for a re-run
    ("queued") -- the dashboard's warning banner."""
    counts = dict(
        db.query(DailyEntry.repair_check_status, func.count())
        .filter(DailyEntry.repair_check_status.in_(["failed", "queued"]))
        .group_by(DailyEntry.repair_check_status)
        .all()
    )
    return {"failed": counts.get("failed", 0), "queued": counts.get("queued", 0)}


@app.post("/api/repairs/recheck", dependencies=LOGIN_REQUIRED)
def recheck_failed_repairs(db: Session = Depends(get_db)) -> dict[str, int]:
    """Queue every failed check for a re-run by the background worker."""
    queued = queue_failed_repair_checks(db)
    db.commit()
    notify_worker()
    return {"queued": queued}


@app.post("/api/repairs/{repair_id}/review", dependencies=LOGIN_REQUIRED)
def review_repair(
    repair_id: int, body: ReviewRequest = ReviewRequest(), db: Session = Depends(get_db)
) -> dict[str, bool]:
    event = db.get(RepairEvent, repair_id)
    if event is None:
        raise HTTPException(status_code=404, detail="repair event not found")
    event.reviewed = True
    event.outcome = body.outcome
    db.commit()
    return {"ok": True}


@app.get("/api/documents/{document_id}", dependencies=LOGIN_REQUIRED)
def download_source_document(document_id: int, db: Session = Depends(get_db)) -> FileResponse:
    document = db.get(SourceDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    path = source_document_path(document)
    if not path.exists():
        raise HTTPException(status_code=404, detail="document file missing from storage")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document.original_filename or f"{document.sha256}.pdf",
        content_disposition_type="inline",  # open in the browser's PDF viewer
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _job_dict(job: IngestJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "filename": job.filename,
        "status": job.status,
        "wells_done": job.wells_done,
        "wells_total": job.wells_total,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def _latest_entry(db: Session, well_id: int) -> DailyEntry | None:
    return (
        db.query(DailyEntry)
        .filter_by(well_id=well_id)
        .order_by(DailyEntry.report_date.desc())
        .first()
    )


def _well_summary(well: Well, entry: DailyEntry | None) -> dict[str, Any]:
    return {
        "id": well.id,
        "well_name": well.well_name,
        "location_code": well.location_code,
        "asset_name": well.asset_name,
        "category": well.category,
        "target_depth": well.target_depth,
        "latest_report_date": entry.report_date if entry else None,
        "present_depth": entry.present_depth if entry else None,
        "tot_days_planned": entry.tot_days_planned if entry else None,
        "tot_days_actual": entry.tot_days_actual if entry else None,
        "cost_planned_inr": entry.cost_planned_inr if entry else None,
        "cost_actual_inr": entry.cost_actual_inr if entry else None,
        "status_text": entry.status_text if entry else None,
    }


def _timeline_entry(entry: DailyEntry) -> dict[str, Any]:
    return {
        "report_date": entry.report_date,
        "source_document_id": entry.source_document_id,
        "mode": entry.mode,
        "present_depth": entry.present_depth,
        "day_meterage": entry.day_meterage,
        "tot_days_planned": entry.tot_days_planned,
        "tot_days_actual": entry.tot_days_actual,
        "cost_planned_inr": entry.cost_planned_inr,
        "cost_actual_inr": entry.cost_actual_inr,
        "status_text": entry.status_text,
        "oper_narrative": entry.oper_narrative,
        "repair_check_status": entry.repair_check_status,
        "phases": [_phase_dict(phase) for phase in entry.phases],
        "repair_events": [_repair_event_dict(event) for event in entry.repair_events],
    }


def _phase_dict(phase: PhaseSnapshot) -> dict[str, Any]:
    return {
        "phase_no": phase.phase_no,
        "casing_size": phase.casing_size,
        "depth_planned": phase.depth_planned,
        "depth_actual": phase.depth_actual,
        "days_planned": phase.days_planned,
        "days_actual": phase.days_actual,
    }


def _repair_event_dict(event: RepairEvent) -> dict[str, Any]:
    return {
        "equipment_or_system": event.equipment_or_system,
        "snippet": event.snippet,
        "confidence": event.confidence,
        "reviewed": event.reviewed,
        "outcome": event.outcome,
    }


def _phase_variance(phase: PhaseSnapshot) -> dict[str, Any]:
    return {
        "phase_no": phase.phase_no,
        "casing_size": phase.casing_size,
        "days_variance_pct": _variance_pct(phase.days_actual, phase.days_planned),
        "depth_planned": phase.depth_planned,
        "depth_actual": phase.depth_actual,
    }


def _variance_pct(actual: float | None, planned: float | None) -> float | None:
    """(actual - planned) / planned * 100 -- None if either side is
    missing or planned is zero (can't compute a meaningful percentage)."""
    if actual is None or planned is None or planned == 0:
        return None
    return (actual - planned) / planned * 100


# Mounted last so it never shadows the /api/* and /health routes above --
# StaticFiles(html=True) serves static/index.html for "/" and any other
# unmatched path, which is what the dashboard's client-side #hash routing
# expects.
app.mount("/", StaticFiles(directory="static", html=True), name="static")

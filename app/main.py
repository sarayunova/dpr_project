"""API routes -- contract in docs/08_api_specification.md.

Response shapes match that spec exactly; if you need to change one,
update the doc in the same change (per CLAUDE.md) rather than letting
the dashboard's contract drift silently.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.ingest import extract_text_from_pdf, ingest_dpr_text
from app.models import DailyEntry, PhaseSnapshot, RepairEvent, Well

app = FastAPI(title="Drilling DPR Monitor")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/ingest")
async def ingest(
    files: list[UploadFile] = File(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    ingested = []
    errors = []

    for file in files:
        try:
            text = extract_text_from_pdf(file.file)
            result = ingest_dpr_text(text, db, source_filename=file.filename)
            db.commit()
            ingested.append(result)
        except Exception as exc:
            db.rollback()
            errors.append({"filename": file.filename, "error": str(exc)})

    return {"ingested": ingested, "errors": errors}


@app.get("/api/wells")
def list_wells(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    wells = db.query(Well).order_by(Well.well_name).all()
    return [_well_summary(well, _latest_entry(db, well.id)) for well in wells]


@app.get("/api/wells/{well_id}")
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


@app.get("/api/wells/{well_id}/variance")
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


@app.get("/api/repairs/unreviewed")
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


@app.get("/api/repairs/reviewed")
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


@app.post("/api/repairs/{repair_id}/review")
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


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


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
        "mode": entry.mode,
        "present_depth": entry.present_depth,
        "day_meterage": entry.day_meterage,
        "tot_days_planned": entry.tot_days_planned,
        "tot_days_actual": entry.tot_days_actual,
        "cost_planned_inr": entry.cost_planned_inr,
        "cost_actual_inr": entry.cost_actual_inr,
        "status_text": entry.status_text,
        "oper_narrative": entry.oper_narrative,
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

"""PDF -> text -> parse -> DB write path.

Repair/troubleshooting extraction calls the local LLM (app/llm_client.py)
once per well's narrative; a failure there is caught here and recorded
on the entry (`repair_check_status = "failed"`), not raised, so one
well's LLM issue never blocks the rest of the file's wells from being
ingested -- and is never mistaken for "no repairs found". Transaction control is the caller's
responsibility: this module adds/flushes but never commits or rolls
back, so a batch caller (Phase 5's `POST /api/ingest`) can commit or
roll back one file's work without affecting others in the same request.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import IO, Any, Callable

import pdfplumber
from sqlalchemy.orm import Session

from app.llm_client import RepairExtractionError, extract_repair_events
from app.models import DailyEntry, PhaseSnapshot, RepairEvent, SourceDocument, Well
from app.parser import ParsedReport, ParsedWell, parse_dpr_text

logger = logging.getLogger(__name__)


def extract_text_from_pdf(source: str | Path | IO[bytes]) -> str:
    """Concatenate every page's extracted text, in page order.

    `source` is a path (local files, e.g. tests) or a binary file-like
    object (e.g. `UploadFile.file` from Phase 5's `POST /api/ingest`) --
    pdfplumber accepts either.

    `x_tolerance=2` (pdfplumber's default is 3) -- found in Phase 9
    against the real sample_dpr_assam_ro_day2.pdf: the default merged
    adjacent words in the banner line with no space between them
    ("COMPANY :AssamAsset+ RO"), which corrupted the extracted
    asset_name, not just cosmetics. Verified against all four real/
    synthesized sample PDFs with no regressions.
    """
    with pdfplumber.open(source) as pdf:
        return "\n".join(page.extract_text(x_tolerance=2) or "" for page in pdf.pages)


def ingest_dpr_pdf(path: str | Path, db: Session) -> dict[str, Any]:
    text = extract_text_from_pdf(path)
    return ingest_dpr_text(text, db, source_filename=Path(path).name)


def ingest_dpr_text(
    text: str,
    db: Session,
    source_filename: str | None = None,
    source_document: SourceDocument | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """`on_progress(wells_done, wells_total)`, if given, is called once
    before the first well and after each well -- the background job
    queue (app/jobs.py) uses it to show per-file progress, since the LLM
    call makes each well take seconds on CPU."""
    report = parse_dpr_text(text)
    if on_progress:
        on_progress(0, len(report.wells))

    repair_events_created = 0
    repair_checks_failed = 0
    for done, parsed_well in enumerate(report.wells, start=1):
        well = _upsert_well(db, report, parsed_well)
        entry = _upsert_daily_entry(db, well, report, parsed_well, source_filename)
        entry.source_document_id = source_document.id if source_document else None
        created = run_repair_check(db, entry)
        if created is None:
            repair_checks_failed += 1
        else:
            repair_events_created += created
        if on_progress:
            on_progress(done, len(report.wells))

    db.flush()

    return {
        "filename": source_filename,
        "asset_name": report.asset_name,
        "report_date": report.report_date,
        "wells_ingested": len(report.wells),
        "repair_events_created": repair_events_created,
        # Wells whose narrative could NOT be checked (LLM unreachable) --
        # their 0 events are unverified, not "none found".
        "repair_checks_failed": repair_checks_failed,
    }


def _upsert_well(db: Session, report: ParsedReport, parsed_well: ParsedWell) -> Well:
    well = db.query(Well).filter_by(well_name=parsed_well.well_name).one_or_none()
    if well is None:
        well = Well(well_name=parsed_well.well_name)
        db.add(well)

    # Well-level attributes reflect the most recently ingested report.
    well.location_code = parsed_well.location_code
    well.asset_name = report.asset_name
    well.category = parsed_well.category
    well.well_type = parsed_well.well_type
    well.target_depth = parsed_well.target_depth

    db.flush()
    return well


def _upsert_daily_entry(
    db: Session,
    well: Well,
    report: ParsedReport,
    parsed_well: ParsedWell,
    source_filename: str | None,
) -> DailyEntry:
    entry = (
        db.query(DailyEntry)
        .filter_by(well_id=well.id, report_date=report.report_date)
        .one_or_none()
    )
    if entry is None:
        entry = DailyEntry(well_id=well.id, report_date=report.report_date)
        db.add(entry)
    else:
        entry.phases.clear()  # replace, don't append — re-ingestion overwrites
        entry.repair_events.clear()  # regenerated fresh from the (possibly
        # corrected) narrative below — note this resets any human review
        # status a prior ingest's events had; acceptable for now, revisit
        # if Phase 7's review queue makes that loss noticeable.

    entry.source_filename = source_filename
    entry.mode = parsed_well.mode
    entry.present_depth = parsed_well.present_depth
    entry.day_meterage = parsed_well.day_meterage
    entry.rb_start = parsed_well.rb_start
    entry.dr_start = parsed_well.dr_start
    entry.pt_start = parsed_well.pt_start
    entry.rb_days_planned = parsed_well.rb_days_planned
    entry.rb_days_actual = parsed_well.rb_days_actual
    entry.dr_days_planned = parsed_well.dr_days_planned
    entry.dr_days_actual = parsed_well.dr_days_actual
    entry.pt_days_planned = parsed_well.pt_days_planned
    entry.pt_days_actual = parsed_well.pt_days_actual
    entry.tot_days_planned = parsed_well.tot_days_planned
    entry.tot_days_actual = parsed_well.tot_days_actual
    entry.mud_weight = parsed_well.mud_weight
    entry.mud_viscosity = parsed_well.mud_viscosity
    entry.litho = parsed_well.litho
    entry.cost_planned_inr = parsed_well.cost_planned_inr
    entry.cost_actual_inr = parsed_well.cost_actual_inr
    entry.status_text = parsed_well.status_text
    entry.oper_narrative = parsed_well.oper_narrative

    db.flush()

    for phase in parsed_well.phases:
        db.add(
            PhaseSnapshot(
                daily_entry_id=entry.id,
                phase_no=phase.phase_no,
                casing_size=phase.casing_size,
                depth_planned=phase.depth_planned,
                depth_actual=phase.depth_actual,
                days_planned=phase.days_planned,
                days_actual=phase.days_actual,
                hole_top=phase.hole_top,
            )
        )

    db.flush()
    return entry


def run_repair_check(db: Session, entry: DailyEntry) -> int | None:
    """Run the LLM repair/troubleshooting check on one entry's narrative
    and record whether it ran (`entry.repair_check_status`).

    Returns the number of RepairEvent rows created, or None if the check
    failed. Never raises for an LLM failure -- one well's failed call must
    not block the rest of the file. Also used to re-run failed checks
    (app/jobs.py).
    """
    try:
        events = extract_repair_events(entry.oper_narrative)
    except Exception as exc:
        # RepairExtractionError is the expected case (Ollama down, timeout,
        # bad response); anything else is caught too, as a second line of
        # defense, and recorded the same way.
        logger.warning(
            "repair/troubleshooting check did not run for well_id=%s, report_date=%s: %s",
            entry.well_id,
            entry.report_date,
            exc,
            exc_info=not isinstance(exc, RepairExtractionError),
        )
        entry.repair_check_status = "failed"
        db.flush()
        return None

    for event in events:
        db.add(
            RepairEvent(
                daily_entry_id=entry.id,
                equipment_or_system=event["equipment_or_system"],
                snippet=event["snippet"],
                confidence=event["confidence"],
                reviewed=False,
            )
        )
    entry.repair_check_status = "ok"
    db.flush()
    return len(events)

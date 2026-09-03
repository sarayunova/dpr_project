"""Ingestion pipeline tests: PDF -> text -> parse -> DB rows.

Requires a running Postgres reachable via DATABASE_URL — see
tests/test_models.py for why, and how to start one
(`docker compose up -d db`). Skipped automatically otherwise.

The LLM boundary (app.ingest.extract_repair_events) is mocked in every
test here, per CLAUDE.md: these tests exercise the ingestion wiring, not
the real model — see tests/test_llm_client.py for that boundary's own
unit tests, and scripts/run_repair_eval.py for the real-model eval run.
"""

import os
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ingest import ingest_dpr_pdf, ingest_dpr_text
from app.models import DailyEntry, PhaseSnapshot, RepairEvent, Well

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://dpr_monitor:dpr_monitor@localhost:5432/dpr_monitor",
)
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "docs" / "03_sample_documents"

try:
    _engine = create_engine(DATABASE_URL)
    with _engine.connect():
        _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _DB_AVAILABLE,
    reason=f"no Postgres reachable at {DATABASE_URL} — start it with `docker compose up -d db`",
)

Session = sessionmaker(bind=_engine) if _DB_AVAILABLE else None

TEST_WELL_NAMES = [
    "NG-2000-4",
    "NG-2000-6",
    "ARMCUE-1",
    "E-1400-13",
    # test_reingesting_updates_changed_values ingests the full 13-well
    # sample_dpr_assam_ro_day2.txt, which brings in these 9 as well.
    "E-1400-4",
    "E-1400-6",
    "E-3000-1",
    "EV-2000-3",
    "EV-2000-4",
    "EV-2000-5",
    "M-4900",
    "M-6100-1",
    "NG-1500-6",
]


@pytest.fixture
def db():
    session = Session()
    try:
        yield session
    finally:
        # Ingestion commits internally in these tests via explicit
        # db.commit() calls below, so clean up by name instead of relying
        # on rollback (which only undoes uncommitted work). Deleting each
        # Well object (rather than a bulk DELETE) lets the ORM cascade
        # into DailyEntry/PhaseSnapshot per the models' cascade config.
        wells = session.query(Well).filter(Well.well_name.in_(TEST_WELL_NAMES)).all()
        for well in wells:
            session.delete(well)
        session.commit()
        session.close()


@pytest.fixture(autouse=True)
def no_real_llm_calls():
    """Every test in this file mocks the LLM boundary to `[]` by default
    (no repair events) so results are deterministic and no test depends
    on Ollama being reachable. Individual tests override this via
    `with patch(...)` when they need to verify RepairEvent creation."""
    with patch("app.ingest.extract_repair_events", return_value=[]):
        yield


def _well(db, well_name):
    return db.query(Well).filter_by(well_name=well_name).one()


def test_ingest_pdf_produces_acceptance_criteria_rows(db):
    result = ingest_dpr_pdf(SAMPLES_DIR / "sample_dpr.pdf", db)
    db.commit()

    assert result["wells_ingested"] == 4
    assert result["asset_name"] == "Assam Asset + RO"
    assert result["report_date"] == date(2026, 4, 2)
    assert result["repair_events_created"] == 0  # mocked to return no events

    ng_2000_4 = _well(db, "NG-2000-4")
    entry = db.query(DailyEntry).filter_by(well_id=ng_2000_4.id).one()
    assert entry.tot_days_planned == 190
    assert entry.tot_days_actual == 155
    assert entry.cost_planned_inr == 886323863.0
    assert entry.cost_actual_inr == 960346238.0

    phases = (
        db.query(PhaseSnapshot)
        .filter_by(daily_entry_id=entry.id)
        .order_by(PhaseSnapshot.phase_no)
        .all()
    )
    assert len(phases) == 4
    assert phases[1].casing_size == '13 3/8"'
    assert phases[1].depth_planned == 2400.0
    assert phases[1].depth_actual == 2404.0

    armcue_1 = _well(db, "ARMCUE-1")
    armcue_entry = db.query(DailyEntry).filter_by(well_id=armcue_1.id).one()
    assert armcue_entry.cost_planned_inr is None
    assert armcue_entry.cost_actual_inr == 378925607.0

    e_1400_13 = _well(db, "E-1400-13")
    e_entry = db.query(DailyEntry).filter_by(well_id=e_1400_13.id).one()
    assert len(e_entry.phases) == 3
    assert e_entry.cost_planned_inr is None
    assert e_entry.cost_actual_inr == 373789219.0


def test_reingesting_same_file_does_not_duplicate(db):
    ingest_dpr_pdf(SAMPLES_DIR / "sample_dpr.pdf", db)
    db.commit()
    ingest_dpr_pdf(SAMPLES_DIR / "sample_dpr.pdf", db)
    db.commit()

    wells = db.query(Well).filter(Well.well_name.in_(TEST_WELL_NAMES)).all()
    assert len(wells) == 4  # not 8

    ng_2000_4 = _well(db, "NG-2000-4")
    entries = db.query(DailyEntry).filter_by(well_id=ng_2000_4.id).all()
    assert len(entries) == 1  # same (well, report_date) — replaced, not duplicated
    assert len(entries[0].phases) == 4  # phase rows replaced, not doubled to 8


def test_reingesting_updates_changed_values(db):
    ingest_dpr_text(
        (SAMPLES_DIR / "sample_dpr.txt").read_text(encoding="utf-8"), db, "v1.txt"
    )
    db.commit()

    # Same well/report_date, but a different actual-days figure — as if a
    # corrected report were re-uploaded.
    day2_text = (SAMPLES_DIR / "sample_dpr_assam_ro_day2.txt").read_text(encoding="utf-8")
    edited = day2_text.replace(
        "06:00 Hrs of 02.04.2026 to 06:00 Hrs of 03.04.2026",
        "06:00 Hrs of 01.04.2026 to 06:00 Hrs of 02.04.2026",
    )
    ingest_dpr_text(edited, db, "v2-corrected.txt")
    db.commit()

    ng_2000_4 = _well(db, "NG-2000-4")
    entries = db.query(DailyEntry).filter_by(well_id=ng_2000_4.id).all()
    assert len(entries) == 1
    assert entries[0].present_depth == 3616.0  # day 2's value, not day 1's 3612.0
    assert entries[0].source_filename == "v2-corrected.txt"


def test_two_different_report_dates_accumulate_not_replace(db):
    # Unlike the same-date "correction" case above, ingesting day 1 and
    # the *real* (unedited) day 2 must produce two separate DailyEntry
    # rows for the same well, per docs/10_acceptance_criteria.md
    # "Multi-day timeline".
    ingest_dpr_text(
        (SAMPLES_DIR / "sample_dpr.txt").read_text(encoding="utf-8"), db, "day1.txt"
    )
    db.commit()
    ingest_dpr_text(
        (SAMPLES_DIR / "sample_dpr_assam_ro_day2.txt").read_text(encoding="utf-8"),
        db,
        "day2.txt",
    )
    db.commit()

    ng_2000_4 = _well(db, "NG-2000-4")
    entries = (
        db.query(DailyEntry)
        .filter_by(well_id=ng_2000_4.id)
        .order_by(DailyEntry.report_date)
        .all()
    )
    assert [e.report_date for e in entries] == [date(2026, 4, 2), date(2026, 4, 3)]
    assert entries[0].present_depth == 3612.0
    assert entries[1].present_depth == 3616.0


def test_well_matched_and_created_by_well_name(db):
    original_four = ["NG-2000-4", "NG-2000-6", "ARMCUE-1", "E-1400-13"]
    ingest_dpr_pdf(SAMPLES_DIR / "sample_dpr.pdf", db)
    db.commit()
    wells = db.query(Well).filter(Well.well_name.in_(original_four)).all()
    assert {w.well_name for w in wells} == set(original_four)
    assert all(w.asset_name == "Assam Asset + RO" for w in wells)


def test_llm_flagged_events_become_repair_event_rows_unreviewed(db):
    fake_events = [
        {
            "equipment_or_system": "DW drum encoder",
            "snippet": "ENCODER#2 REPLACED",
            "confidence": "high",
        }
    ]
    with patch("app.ingest.extract_repair_events", return_value=fake_events):
        result = ingest_dpr_pdf(SAMPLES_DIR / "sample_dpr.pdf", db)
    db.commit()

    # One fake event per well (4 wells) from the mock above.
    assert result["repair_events_created"] == 4

    ng_2000_4 = _well(db, "NG-2000-4")
    entry = db.query(DailyEntry).filter_by(well_id=ng_2000_4.id).one()
    events = db.query(RepairEvent).filter_by(daily_entry_id=entry.id).all()
    assert len(events) == 1
    assert events[0].equipment_or_system == "DW drum encoder"
    assert events[0].reviewed is False  # never surfaced as confirmed by default


def test_llm_failure_does_not_block_ingestion(db):
    # extract_repair_events itself never raises (see test_llm_client.py),
    # but ingest.py's own try/except around it is a second line of
    # defense — confirm ingestion still completes if it somehow did.
    with patch("app.ingest.extract_repair_events", side_effect=RuntimeError("boom")):
        result = ingest_dpr_pdf(SAMPLES_DIR / "sample_dpr.pdf", db)
    db.commit()

    assert result["wells_ingested"] == 4
    assert result["repair_events_created"] == 0
    # DailyEntry rows still got created despite every well's LLM call failing.
    ng_2000_4 = _well(db, "NG-2000-4")
    entry = db.query(DailyEntry).filter_by(well_id=ng_2000_4.id).one()
    assert entry.tot_days_actual == 155


def test_reingestion_replaces_repair_events_not_appends(db):
    stale_event = [
        {"equipment_or_system": "old sensor", "snippet": "old snippet", "confidence": "low"}
    ]
    with patch("app.ingest.extract_repair_events", return_value=stale_event):
        ingest_dpr_pdf(SAMPLES_DIR / "sample_dpr.pdf", db)
    db.commit()

    fresh_event = [
        {"equipment_or_system": "DW drum encoder", "snippet": "fresh snippet", "confidence": "high"}
    ]
    with patch("app.ingest.extract_repair_events", return_value=fresh_event):
        ingest_dpr_pdf(SAMPLES_DIR / "sample_dpr.pdf", db)
    db.commit()

    ng_2000_4 = _well(db, "NG-2000-4")
    entry = db.query(DailyEntry).filter_by(well_id=ng_2000_4.id).one()
    events = db.query(RepairEvent).filter_by(daily_entry_id=entry.id).all()
    assert len(events) == 1  # not 2 — replaced, not appended
    assert events[0].equipment_or_system == "DW drum encoder"

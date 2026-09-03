"""Round-trip (write then read) tests for every entity in app/models.py.

Requires a running Postgres reachable via DATABASE_URL — matching how the
app actually runs (see docs/05_architecture.md: Postgres from the start,
not SQLite). Skipped automatically if no database is reachable, the same
pattern CLAUDE.md prescribes for Ollama-dependent tests: don't require an
external service to be present for the rest of the suite to run.

To run these locally: `docker compose up -d db`, then
`alembic upgrade head`, then `pytest tests/test_models.py`.
"""

import os
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import DailyEntry, PhaseSnapshot, Proposal, RepairEvent, Well

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://dpr_monitor:dpr_monitor@localhost:5432/dpr_monitor",
)

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


@pytest.fixture
def db():
    session = Session()
    try:
        yield session
        session.rollback()  # never persist test data
    finally:
        session.close()


def test_well_round_trip(db):
    well = Well(
        well_name="TEST-WELL-1",
        location_code="TSTL",
        asset_name="Test Asset",
        category="ON LAND EXPLORATORY WELLS",
        well_type="DI",
        target_depth=4000.0,
    )
    db.add(well)
    db.flush()

    fetched = db.get(Well, well.id)
    assert fetched.well_name == "TEST-WELL-1"
    assert fetched.asset_name == "Test Asset"
    assert fetched.target_depth == 4000.0


def test_proposal_round_trip(db):
    well = Well(well_name="TEST-WELL-2", asset_name="Test Asset")
    db.add(well)
    db.flush()

    proposal = Proposal(
        well_id=well.id,
        proposed_date=date(2025, 1, 1),
        approved_date=date(2025, 2, 1),
        approving_authority="Test Authority",
        afe_number="AFE-123",
        gto_reference="GTO-456",
        planned_total_days=150,
        planned_total_cost_inr=500_000_000.0,
    )
    db.add(proposal)
    db.flush()

    fetched = db.get(Proposal, proposal.id)
    assert fetched.well_id == well.id
    assert fetched.afe_number == "AFE-123"
    assert fetched.planned_total_days == 150
    assert well.proposal.id == proposal.id  # relationship works both ways


def test_daily_entry_round_trip(db):
    well = Well(well_name="TEST-WELL-3", asset_name="Test Asset")
    db.add(well)
    db.flush()

    entry = DailyEntry(
        well_id=well.id,
        report_date=date(2026, 4, 2),
        source_filename="test.pdf",
        mode="D",
        present_depth=3616.0,
        tot_days_planned=190,
        tot_days_actual=156,
        cost_planned_inr=886323863.0,
        cost_actual_inr=960346238.0,
        oper_narrative="TEST NARRATIVE",
    )
    db.add(entry)
    db.flush()

    fetched = db.get(DailyEntry, entry.id)
    assert fetched.well_id == well.id
    assert fetched.report_date == date(2026, 4, 2)
    assert fetched.tot_days_actual == 156
    assert fetched.ingested_at is not None  # server_default populated it


def test_daily_entry_unique_on_well_and_report_date(db):
    well = Well(well_name="TEST-WELL-4", asset_name="Test Asset")
    db.add(well)
    db.flush()

    db.add(DailyEntry(well_id=well.id, report_date=date(2026, 4, 2)))
    db.flush()
    db.add(DailyEntry(well_id=well.id, report_date=date(2026, 4, 2)))
    with pytest.raises(Exception):
        db.flush()


def test_phase_snapshot_round_trip(db):
    well = Well(well_name="TEST-WELL-5", asset_name="Test Asset")
    db.add(well)
    db.flush()
    entry = DailyEntry(well_id=well.id, report_date=date(2026, 4, 2))
    db.add(entry)
    db.flush()

    phase = PhaseSnapshot(
        daily_entry_id=entry.id,
        phase_no=2,
        casing_size='13 3/8"',
        depth_planned=2400.0,
        depth_actual=2404.0,
        days_planned=34,
        days_actual=53,
    )
    db.add(phase)
    db.flush()

    fetched = db.get(PhaseSnapshot, phase.id)
    assert fetched.casing_size == '13 3/8"'
    assert fetched.depth_actual == 2404.0
    assert entry.phases[0].id == phase.id


def test_repair_event_round_trip_defaults_unreviewed(db):
    well = Well(well_name="TEST-WELL-6", asset_name="Test Asset")
    db.add(well)
    db.flush()
    entry = DailyEntry(well_id=well.id, report_date=date(2026, 4, 2))
    db.add(entry)
    db.flush()

    event = RepairEvent(
        daily_entry_id=entry.id,
        equipment_or_system="DW drum encoder",
        snippet="ENCOUNTERED DW DRUM ENCODER FAULT...ENCODER#2 REPLACED",
        confidence="high",
    )
    db.add(event)
    db.flush()

    fetched = db.get(RepairEvent, event.id)
    assert fetched.equipment_or_system == "DW drum encoder"
    assert fetched.reviewed is False  # never surfaced as confirmed by default
    assert entry.repair_events[0].id == event.id

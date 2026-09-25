"""ORM models — entity contract per docs/04_data_model.md.

Field-for-field match with that document. Two design rules called out
there and preserved here:

1. Deterministic fields (DailyEntry, PhaseSnapshot) never touch the LLM;
   only RepairEvent and Proposal extraction do.
2. The DPR's own "Planned" columns and the Proposal's originally
   approved figures are kept as separate fields on purpose — a
   three-way comparison (originally approved vs. current plan vs.
   actual) is intended, not just plan-vs-actual.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Well(Base):
    __tablename__ = "wells"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    well_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    location_code: Mapped[str | None] = mapped_column(String)
    asset_name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str | None] = mapped_column(String)
    well_type: Mapped[str | None] = mapped_column(String)
    target_depth: Mapped[float | None] = mapped_column(Float)

    proposal: Mapped["Proposal | None"] = relationship(
        back_populates="well", uselist=False, cascade="all, delete-orphan"
    )
    daily_entries: Mapped[list["DailyEntry"]] = relationship(
        back_populates="well", cascade="all, delete-orphan"
    )


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    well_id: Mapped[int] = mapped_column(
        ForeignKey("wells.id"), unique=True, nullable=False
    )
    proposed_date: Mapped[date | None] = mapped_column(Date)
    approved_date: Mapped[date | None] = mapped_column(Date)
    approving_authority: Mapped[str | None] = mapped_column(String)
    afe_number: Mapped[str | None] = mapped_column(String)
    gto_reference: Mapped[str | None] = mapped_column(String)
    formation_tops: Mapped[str | None] = mapped_column(Text)
    mud_program: Mapped[str | None] = mapped_column(Text)
    casing_program: Mapped[str | None] = mapped_column(Text)
    objective: Mapped[str | None] = mapped_column(Text)
    planned_total_days: Mapped[int | None] = mapped_column(Integer)
    planned_total_cost_inr: Mapped[float | None] = mapped_column(Float)
    raw_extracted_json: Mapped[str | None] = mapped_column(Text)

    well: Mapped["Well"] = relationship(back_populates="proposal")


class DailyEntry(Base):
    __tablename__ = "daily_entries"
    __table_args__ = (UniqueConstraint("well_id", "report_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    well_id: Mapped[int] = mapped_column(ForeignKey("wells.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_filename: Mapped[str | None] = mapped_column(String)
    # Null for text-only ingestion (tests, scripts) -- set whenever an
    # actual PDF upload produced this row.
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id")
    )
    mode: Mapped[str | None] = mapped_column(String)
    present_depth: Mapped[float | None] = mapped_column(Float)
    day_meterage: Mapped[float | None] = mapped_column(Float)
    rb_start: Mapped[date | None] = mapped_column(Date)
    dr_start: Mapped[date | None] = mapped_column(Date)
    pt_start: Mapped[date | None] = mapped_column(Date)
    rb_days_planned: Mapped[int | None] = mapped_column(Integer)
    rb_days_actual: Mapped[int | None] = mapped_column(Integer)
    dr_days_planned: Mapped[int | None] = mapped_column(Integer)
    dr_days_actual: Mapped[int | None] = mapped_column(Integer)
    pt_days_planned: Mapped[int | None] = mapped_column(Integer)
    pt_days_actual: Mapped[int | None] = mapped_column(Integer)
    tot_days_planned: Mapped[int | None] = mapped_column(Integer)
    tot_days_actual: Mapped[int | None] = mapped_column(Integer)
    mud_weight: Mapped[float | None] = mapped_column(Float)
    mud_viscosity: Mapped[float | None] = mapped_column(Float)
    litho: Mapped[str | None] = mapped_column(Text)
    cost_planned_inr: Mapped[float | None] = mapped_column(Float)
    cost_actual_inr: Mapped[float | None] = mapped_column(Float)
    status_text: Mapped[str | None] = mapped_column(Text)
    oper_narrative: Mapped[str | None] = mapped_column(Text)
    # Whether the LLM repair/troubleshooting check actually ran on
    # oper_narrative: "ok" (ran -- zero events then genuinely means none
    # found), "failed" (local LLM unreachable/errored -- zero events means
    # NOT checked), "queued" (re-run requested, see app/jobs.py). Null for
    # rows ingested before this was tracked (unknown).
    repair_check_status: Mapped[str | None] = mapped_column(String, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    well: Mapped["Well"] = relationship(back_populates="daily_entries")
    phases: Mapped[list["PhaseSnapshot"]] = relationship(
        back_populates="daily_entry", cascade="all, delete-orphan"
    )
    repair_events: Mapped[list["RepairEvent"]] = relationship(
        back_populates="daily_entry", cascade="all, delete-orphan"
    )


class SourceDocument(Base):
    """One row per distinct uploaded PDF (by content hash) -- the file
    itself lives on disk, see app/storage.py. Added in Phase 10."""

    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    original_filename: Mapped[str | None] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    stored_path: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class IngestJob(Base):
    """One queued DPR PDF, processed in the background by app/jobs.py so
    large batch uploads don't run inside a single HTTP request (~12s of
    CPU LLM time per well). Added after Phase 10; see
    docs/08_api_specification.md §Ingest jobs."""

    __tablename__ = "ingest_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )
    filename: Mapped[str | None] = mapped_column(String)
    # queued -> running -> done | failed
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)
    wells_total: Mapped[int | None] = mapped_column(Integer)
    wells_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Same shape as one POST /api/ingest "ingested" item, once done.
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    source_document: Mapped["SourceDocument"] = relationship()


class User(Base):
    """Email + password login, single role -- see app/auth.py. Added in
    Phase 10 per docs/07_non_functional_requirements.md."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)  # lowercased
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    # Deactivate rather than delete, so a departed user's account can't
    # log in but the row (and anything later attributed to it) remains.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    user: Mapped["User"] = relationship(back_populates="sessions")


class PhaseSnapshot(Base):
    __tablename__ = "phase_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    daily_entry_id: Mapped[int] = mapped_column(
        ForeignKey("daily_entries.id"), nullable=False
    )
    phase_no: Mapped[int] = mapped_column(Integer, nullable=False)
    casing_size: Mapped[str | None] = mapped_column(String)
    depth_planned: Mapped[float | None] = mapped_column(Float)
    depth_actual: Mapped[float | None] = mapped_column(Float)
    days_planned: Mapped[int | None] = mapped_column(Integer)
    days_actual: Mapped[int | None] = mapped_column(Integer)
    hole_top: Mapped[str | None] = mapped_column(String)

    daily_entry: Mapped["DailyEntry"] = relationship(back_populates="phases")


class RepairEvent(Base):
    __tablename__ = "repair_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    daily_entry_id: Mapped[int] = mapped_column(
        ForeignKey("daily_entries.id"), nullable=False
    )
    equipment_or_system: Mapped[str | None] = mapped_column(String)
    snippet: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(String)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # "confirmed" or "false_positive", set together with reviewed=True by
    # POST /api/repairs/{id}/review -- null until reviewed. Kept distinct
    # from `reviewed` (per docs/09_ui_wireframes.md Screen 3's recommendation)
    # so the LLM's real precision is measurable over time, not just a
    # binary "someone looked at it" flag.
    outcome: Mapped[str | None] = mapped_column(String)

    daily_entry: Mapped["DailyEntry"] = relationship(back_populates="repair_events")

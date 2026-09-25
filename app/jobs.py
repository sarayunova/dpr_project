"""Background ingestion queue.

docs/07_non_functional_requirements.md treats batch uploads of
backlogged PDFs as a normal, recurring case -- but each well's narrative
takes ~12s through the local LLM on CPU, so ingesting a backlog inside
one HTTP request (`POST /api/ingest`) can run for hours. Instead,
`POST /api/ingest-jobs` stores each PDF and queues it here; a single
worker thread in the app process works through the queue.

Deliberately no extra infrastructure (Redis, Celery, ...): the queue is
the `ingest_jobs` table in the Postgres we already run, so queued jobs
survive a restart and are backed up with everything else.

One worker, one file at a time, on purpose: the LLM is CPU-bound, so
running files in parallel wouldn't finish a backlog any sooner.

A job interrupted by a crash or restart is put back in the queue on
startup and re-run from scratch. That's safe because ingestion replaces
rather than duplicates per (well, report_date) -- see CLAUDE.md.
"""

from __future__ import annotations

import io
import logging
import os
import threading
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.ingest import extract_text_from_pdf, ingest_dpr_text, run_repair_check
from app.models import DailyEntry, IngestJob
from app.storage import save_source_document, source_document_path

logger = logging.getLogger(__name__)

POLL_SECONDS = 5.0


def enqueue_pdf(db: Session, filename: str | None, data: bytes) -> IngestJob:
    """Store the PDF and queue it -- flushed, not committed (the caller
    commits, then calls notify_worker()).

    Only a cheap header check happens here, not full text extraction, so
    uploading hundreds of files stays fast. A file with a PDF header that
    still can't be read fails later, as that job's error.
    """
    if not data.startswith(b"%PDF-"):
        raise ValueError("not a PDF file")
    document = save_source_document(db, filename, data)
    job = IngestJob(source_document_id=document.id, filename=filename, status="queued")
    db.add(job)
    db.flush()
    return job


def recover_interrupted_jobs() -> int:
    """Put jobs left 'running' by a crash/restart back in the queue.
    Assumes a single app process -- see the module docstring."""
    with SessionLocal() as db:
        count = (
            db.query(IngestJob)
            .filter_by(status="running")
            .update({"status": "queued", "wells_done": 0, "started_at": None})
        )
        db.commit()
    if count:
        logger.warning("re-queued %d ingest job(s) interrupted by a restart", count)
    return count


def run_pending_jobs(should_stop: Callable[[], bool] = lambda: False) -> int:
    """Process queued jobs until none are left (or `should_stop()`);
    returns how many ran. The worker thread calls this; tests call it
    directly."""
    processed = 0
    while not should_stop() and (job_id := _claim_next_job()) is not None:
        _process_job(job_id)
        processed += 1
    return processed


def _claim_next_job() -> int | None:
    with SessionLocal() as db:
        # SKIP LOCKED: harmless with one worker, and keeps two workers
        # from ever grabbing the same job if that ever changes.
        job = db.scalars(
            select(IngestJob)
            .filter_by(status="queued")
            .order_by(IngestJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if job is None:
            return None
        job.status = "running"
        job.started_at = datetime.utcnow()
        job.wells_done = 0
        db.commit()
        return job.id


def _process_job(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(IngestJob, job_id)
        try:
            data = source_document_path(job.source_document).read_bytes()
            text = extract_text_from_pdf(io.BytesIO(data))
            result = ingest_dpr_text(
                text,
                db,
                source_filename=job.filename,
                source_document=job.source_document,
                on_progress=lambda done, total: _record_progress(job_id, done, total),
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("ingest job %s failed", job_id, exc_info=True)
            _finish(job_id, status="failed", error=str(exc) or type(exc).__name__)
            return
    _finish(job_id, status="done", result=_json_safe(result))


def _record_progress(job_id: int, done: int, total: int) -> None:
    # Own short transaction, so progress is visible while the ingest
    # transaction itself is still open.
    with SessionLocal() as db:
        db.query(IngestJob).filter_by(id=job_id).update(
            {"wells_done": done, "wells_total": total}
        )
        db.commit()


def _finish(job_id: int, status: str, result: dict | None = None, error: str | None = None) -> None:
    with SessionLocal() as db:
        job = db.get(IngestJob, job_id)
        job.status = status
        job.result = result
        job.error = error
        job.finished_at = datetime.utcnow()
        db.commit()


def _json_safe(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in result.items()
    }


# ---------------------------------------------------------------------------
# Re-running failed repair/troubleshooting checks
# ---------------------------------------------------------------------------


def queue_failed_repair_checks(db: Session) -> int:
    """Mark every entry whose LLM check failed for re-run; returns how
    many. Flushed, not committed -- the caller commits, then calls
    notify_worker()."""
    return (
        db.query(DailyEntry)
        .filter_by(repair_check_status="failed")
        .update({"repair_check_status": "queued"})
    )


def run_next_repair_check() -> bool:
    """Re-run one queued check; returns False if none were queued.

    The whole re-check is one transaction holding the entry's row lock,
    so a crash mid-call just rolls back and leaves it queued -- no
    separate "running" state or startup recovery needed. If the LLM is
    still unreachable the entry goes back to "failed" (not retried in a
    loop); the user re-queues it once the LLM is back.
    """
    with SessionLocal() as db:
        entry = db.scalars(
            select(DailyEntry)
            .filter_by(repair_check_status="queued")
            .order_by(DailyEntry.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if entry is None:
            return False
        run_repair_check(db, entry)
        db.commit()
        return True


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None


def worker_enabled() -> bool:
    # INGEST_WORKER=false lets a process serve the API without consuming
    # the queue (e.g. a second replica on the future shared server).
    return os.environ.get("INGEST_WORKER", "true").lower() not in ("0", "false", "no")


def notify_worker() -> None:
    """Start on newly queued work now rather than at the next poll."""
    _wake.set()


def start_worker() -> None:
    global _thread
    recover_interrupted_jobs()
    _stop.clear()
    _thread = threading.Thread(target=_worker_loop, name="ingest-worker", daemon=True)
    _thread.start()


def stop_worker(timeout: float = 5.0) -> None:
    _stop.set()
    _wake.set()
    if _thread is not None:
        # A job mid-LLM-call may not stop in time; it's re-queued on the
        # next startup.
        _thread.join(timeout)


def _worker_loop() -> None:
    while not _stop.is_set():
        try:
            # New uploads first; then one re-check at a time, so a long
            # re-check backlog never holds up a freshly uploaded file.
            worked = run_pending_jobs(should_stop=_stop.is_set) > 0
            worked = run_next_repair_check() or worked
        except Exception:
            # e.g. the database briefly unreachable -- log and keep going,
            # the thread must never die silently.
            logger.exception("ingest worker loop error")
            worked = False
        if not worked:
            _wake.wait(POLL_SECONDS)
            _wake.clear()

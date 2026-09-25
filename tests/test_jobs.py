"""Background ingestion queue -- app/jobs.py, `/api/ingest-jobs`.

Requires Postgres (skipped otherwise, like tests/test_api.py). The LLM
boundary is mocked, per CLAUDE.md. Most tests drive the queue
synchronously with run_pending_jobs(); one runs the real worker thread.
"""

import io
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import jobs
from app.auth import get_current_user
from app.main import app
from app.llm_client import RepairExtractionError
from app.models import DailyEntry, IngestJob, SourceDocument, Well

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

# sample_dpr.pdf (4 wells) and sample_dpr_assam_ro_day2.pdf (13 wells,
# a superset of the first 4).
TEST_WELL_NAMES = [
    "NG-2000-4", "NG-2000-6", "ARMCUE-1", "E-1400-13", "E-1400-4", "E-1400-6",
    "E-3000-1", "EV-2000-3", "EV-2000-4", "EV-2000-5", "M-4900", "M-6100-1",
    "NG-1500-6",
]


@pytest.fixture(autouse=True)
def no_real_llm_calls():
    with patch("app.ingest.extract_repair_events", return_value=[]):
        yield


@pytest.fixture(autouse=True)
def isolated_db_state(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    session = Session()
    existing_jobs = [j.id for j in session.query(IngestJob.id)]
    existing_docs = [d.id for d in session.query(SourceDocument.id)]
    # Jobs left queued by anything else would be picked up by our
    # run_pending_jobs() calls -- refuse to run rather than touch them.
    assert session.query(IngestJob).filter(IngestJob.status.in_(["queued", "running"])).count() == 0
    assert session.query(DailyEntry).filter_by(repair_check_status="queued").count() == 0
    try:
        yield
    finally:
        session.query(IngestJob).filter(IngestJob.id.not_in(existing_jobs)).delete(
            synchronize_session=False
        )
        for well in session.query(Well).filter(Well.well_name.in_(TEST_WELL_NAMES)):
            session.delete(well)
        session.flush()
        session.query(SourceDocument).filter(SourceDocument.id.not_in(existing_docs)).delete(
            synchronize_session=False
        )
        session.commit()
        session.close()


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: None
    try:
        yield TestClient(app)  # not a context manager: no worker thread
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _queue(client, *filenames):
    handles = [open(SAMPLES_DIR / name, "rb") for name in filenames]
    try:
        return client.post(
            "/api/ingest-jobs",
            files=[("files", (name, h, "application/pdf")) for name, h in zip(filenames, handles)],
        )
    finally:
        for h in handles:
            h.close()


def test_real_worker_thread_picks_up_uploads():
    app.dependency_overrides[get_current_user] = lambda: None
    try:
        with TestClient(app) as client:  # runs lifespan -> starts the worker
            job_id = _queue(client, "sample_dpr.pdf").json()["queued"][0]["job_id"]
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                status = client.get(f"/api/ingest-jobs/{job_id}").json()["status"]
                if status in ("done", "failed"):
                    break
                time.sleep(0.2)
        assert status == "done"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_upload_returns_queued_without_ingesting(client):
    body = _queue(client, "sample_dpr.pdf").json()
    assert body["errors"] == []
    assert [q["filename"] for q in body["queued"]] == ["sample_dpr.pdf"]

    job = client.get(f"/api/ingest-jobs/{body['queued'][0]['job_id']}").json()
    assert job["status"] == "queued"
    assert job["result"] is None

    session = Session()
    try:
        assert session.query(Well).filter_by(well_name="NG-2000-4").count() == 0
    finally:
        session.close()


def test_worker_processes_job_to_same_result_as_sync_ingest(client):
    job_id = _queue(client, "sample_dpr.pdf").json()["queued"][0]["job_id"]
    assert jobs.run_pending_jobs() == 1

    job = client.get(f"/api/ingest-jobs/{job_id}").json()
    assert job["status"] == "done"
    assert job["error"] is None
    assert job["wells_done"] == job["wells_total"] == 4
    assert job["started_at"] and job["finished_at"]
    # Same shape and values as a POST /api/ingest "ingested" item.
    assert job["result"] == {
        "filename": "sample_dpr.pdf",
        "asset_name": "Assam Asset + RO",
        "report_date": "2026-04-02",
        "wells_ingested": 4,
        "repair_events_created": 0,
        "repair_checks_failed": 0,
    }

    session = Session()
    try:
        entry = (
            session.query(DailyEntry).join(Well).filter(Well.well_name == "NG-2000-4").one()
        )
        assert entry.source_document_id is not None
        assert entry.tot_days_actual == 155
    finally:
        session.close()


def test_progress_visible_while_job_runs(client):
    job_id = _queue(client, "sample_dpr_assam_ro_day2.pdf").json()["queued"][0]["job_id"]
    seen = []

    def spy(narrative):
        # Called once per well, mid-transaction -- read progress from a
        # separate session, as the dashboard would.
        s = Session()
        try:
            job = s.get(IngestJob, job_id)
            seen.append((job.status, job.wells_done, job.wells_total))
        finally:
            s.close()
        return []

    with patch("app.ingest.extract_repair_events", side_effect=spy):
        jobs.run_pending_jobs()

    assert len(seen) == 13
    assert all(status == "running" and total == 13 for status, _, total in seen)
    assert [done for _, done, _ in seen] == list(range(13))  # 0..12 before each well


def test_non_pdf_rejected_at_upload_and_not_stored(client, tmp_path):
    response = client.post(
        "/api/ingest-jobs",
        files=[("files", ("notes.txt", io.BytesIO(b"hello"), "text/plain"))],
    )
    body = response.json()
    assert body["queued"] == []
    assert body["errors"] == [{"filename": "notes.txt", "error": "not a PDF file"}]
    assert not (tmp_path / "uploads").exists() or not list((tmp_path / "uploads").rglob("*"))


def test_unreadable_pdf_fails_its_job_without_blocking_others(client):
    bad = b"%PDF-1.4\nthis is not really a pdf"
    with open(SAMPLES_DIR / "sample_dpr.pdf", "rb") as good:
        body = client.post(
            "/api/ingest-jobs",
            files=[
                ("files", ("broken.pdf", io.BytesIO(bad), "application/pdf")),
                ("files", ("sample_dpr.pdf", good, "application/pdf")),
            ],
        ).json()
    broken_id, good_id = (q["job_id"] for q in body["queued"])

    assert jobs.run_pending_jobs() == 2

    broken = client.get(f"/api/ingest-jobs/{broken_id}").json()
    assert broken["status"] == "failed"
    assert broken["error"]
    assert client.get(f"/api/ingest-jobs/{good_id}").json()["status"] == "done"


def test_jobs_run_in_upload_order_and_counts_reported(client):
    body = _queue(client, "sample_dpr.pdf", "sample_dpr_assam_ro_day2.pdf").json()
    first_id, second_id = (q["job_id"] for q in body["queued"])
    jobs.run_pending_jobs()

    listing = client.get("/api/ingest-jobs").json()
    assert listing["counts"]["queued"] == listing["counts"]["running"] == 0
    assert listing["counts"]["done"] >= 2
    ours = {j["job_id"]: j for j in listing["jobs"] if j["job_id"] in (first_id, second_id)}
    assert ours[first_id]["finished_at"] <= ours[second_id]["started_at"]


def test_job_interrupted_by_restart_is_requeued_and_rerun(client):
    job_id = _queue(client, "sample_dpr.pdf").json()["queued"][0]["job_id"]
    session = Session()
    try:
        session.query(IngestJob).filter_by(id=job_id).update(
            {"status": "running", "wells_done": 2}
        )
        session.commit()
    finally:
        session.close()

    assert jobs.recover_interrupted_jobs() == 1
    assert client.get(f"/api/ingest-jobs/{job_id}").json()["status"] == "queued"

    jobs.run_pending_jobs()
    assert client.get(f"/api/ingest-jobs/{job_id}").json()["status"] == "done"


def test_unknown_job_404(client):
    assert client.get("/api/ingest-jobs/999999999").status_code == 404



# ---------------------------------------------------------------------------
# LLM-unreachable warning + re-running failed repair checks
# ---------------------------------------------------------------------------

LLM_DOWN = RepairExtractionError("local LLM call failed: connection refused")


def _ingest_with_llm_down(client, filename="sample_dpr.pdf"):
    _queue(client, filename)
    with patch("app.ingest.extract_repair_events", side_effect=LLM_DOWN):
        jobs.run_pending_jobs()


def _check_status(client):
    return client.get("/api/repairs/check-status").json()


def _ng_2000_4_latest_day(client):
    well_id = next(
        w["id"] for w in client.get("/api/wells").json() if w["well_name"] == "NG-2000-4"
    )
    return client.get(f"/api/wells/{well_id}").json()["timeline"][-1]


def test_job_result_reports_failed_checks_and_status_endpoint_counts_them(client):
    before = _check_status(client)["failed"]
    _ingest_with_llm_down(client)

    job = client.get("/api/ingest-jobs").json()["jobs"][0]
    assert job["status"] == "done"  # the well data itself still got in
    assert job["result"]["repair_checks_failed"] == 4
    assert _check_status(client)["failed"] == before + 4


def test_timeline_exposes_repair_check_status(client):
    _ingest_with_llm_down(client)
    day = _ng_2000_4_latest_day(client)
    assert day["repair_check_status"] == "failed"
    assert day["repair_events"] == []


def test_recheck_reruns_failed_checks_once_llm_is_back(client):
    _ingest_with_llm_down(client)
    failed = _check_status(client)["failed"]

    assert client.post("/api/repairs/recheck").json() == {"queued": failed}
    assert _check_status(client) == {"failed": 0, "queued": failed}

    event = [{"equipment_or_system": "DW", "snippet": "RECTIFIED OIL LEAKAGE", "confidence": "high"}]
    with patch("app.ingest.extract_repair_events", return_value=event):
        while jobs.run_next_repair_check():
            pass

    assert _check_status(client) == {"failed": 0, "queued": 0}
    day = _ng_2000_4_latest_day(client)
    assert day["repair_check_status"] == "ok"
    assert [e["snippet"] for e in day["repair_events"]] == ["RECTIFIED OIL LEAKAGE"]
    assert day["repair_events"][0]["reviewed"] is False


def test_recheck_while_llm_still_down_goes_back_to_failed_without_looping(client):
    _ingest_with_llm_down(client)
    failed = _check_status(client)["failed"]
    client.post("/api/repairs/recheck")

    calls = []

    def still_down(narrative):
        calls.append(narrative)
        raise LLM_DOWN

    with patch("app.ingest.extract_repair_events", side_effect=still_down):
        while jobs.run_next_repair_check():
            pass

    assert len(calls) == failed  # each tried exactly once, not retried forever
    assert _check_status(client) == {"failed": failed, "queued": 0}

"""API endpoint tests -- docs/08_api_specification.md contract.

Requires a running Postgres reachable via DATABASE_URL (see
tests/test_models.py). The LLM boundary is mocked, per CLAUDE.md, except
where a test explicitly needs a fake repair event.
"""

import os
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models import DailyEntry, SourceDocument, Well

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
    # test_well_detail_timeline_includes_both_days_once_both_ingested
    # (Phase 9) also ingests the full 13-well sample_dpr_assam_ro_day2.pdf.
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


@pytest.fixture(autouse=True)
def no_real_llm_calls():
    with patch("app.ingest.extract_repair_events", return_value=[]):
        yield


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    """Keep uploaded PDFs (app/storage.py) out of the real data/uploads."""
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    return tmp_path / "uploads"


@pytest.fixture
def client():
    session = Session()
    existing_document_ids = [d.id for d in session.query(SourceDocument.id)]

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    # Login itself is covered in tests/test_auth.py; here every request
    # is treated as coming from a logged-in user.
    app.dependency_overrides[get_current_user] = lambda: None
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        wells = session.query(Well).filter(Well.well_name.in_(TEST_WELL_NAMES)).all()
        for well in wells:
            session.delete(well)
        session.flush()
        session.query(SourceDocument).filter(
            SourceDocument.id.not_in(existing_document_ids)
        ).delete(synchronize_session=False)
        session.commit()
        session.close()


def _upload_sample(client, filename="sample_dpr.pdf"):
    with open(SAMPLES_DIR / filename, "rb") as f:
        return client.post(
            "/api/ingest", files=[("files", (filename, f, "application/pdf"))]
        )


def test_ingest_endpoint_shape(client):
    response = _upload_sample(client)
    assert response.status_code == 200
    body = response.json()

    assert body["errors"] == []
    assert len(body["ingested"]) == 1
    result = body["ingested"][0]
    assert result["filename"] == "sample_dpr.pdf"
    assert result["asset_name"] == "Assam Asset + RO"
    assert result["report_date"] == "2026-04-02"
    assert result["wells_ingested"] == 4
    assert result["repair_events_created"] == 0


def test_ingest_endpoint_reports_per_file_errors(client):
    import io

    response = client.post(
        "/api/ingest",
        files=[("files", ("corrupt.pdf", io.BytesIO(b"not a real pdf"), "application/pdf"))],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ingested"] == []
    assert len(body["errors"]) == 1
    assert body["errors"][0]["filename"] == "corrupt.pdf"
    assert "error" in body["errors"][0]


def test_ingest_endpoint_partial_success_across_multiple_files(client):
    import io

    with open(SAMPLES_DIR / "sample_dpr.pdf", "rb") as good_file:
        response = client.post(
            "/api/ingest",
            files=[
                ("files", ("sample_dpr.pdf", good_file, "application/pdf")),
                ("files", ("corrupt.pdf", io.BytesIO(b"garbage"), "application/pdf")),
            ],
        )
    body = response.json()
    assert len(body["ingested"]) == 1
    assert len(body["errors"]) == 1


def test_reingest_via_api_replaces_not_duplicates(client):
    _upload_sample(client)
    _upload_sample(client)

    wells = client.get("/api/wells").json()
    test_wells = [w for w in wells if w["well_name"] in TEST_WELL_NAMES]
    assert len(test_wells) == 4  # not 8


def test_list_wells_shape_and_values(client):
    _upload_sample(client)

    wells = client.get("/api/wells").json()
    ng_2000_4 = next(w for w in wells if w["well_name"] == "NG-2000-4")

    assert ng_2000_4["asset_name"] == "Assam Asset + RO"
    assert ng_2000_4["category"] == "ON LAND EXPLORATORY WELLS"
    assert ng_2000_4["target_depth"] == 4394.0
    assert ng_2000_4["latest_report_date"] == "2026-04-02"
    assert ng_2000_4["present_depth"] == 3612.0
    assert ng_2000_4["tot_days_planned"] == 190
    assert ng_2000_4["tot_days_actual"] == 155
    assert ng_2000_4["cost_planned_inr"] == 886323863.0
    assert ng_2000_4["cost_actual_inr"] == 960346238.0


def test_get_well_detail_timeline_and_phases(client):
    _upload_sample(client)
    wells = client.get("/api/wells").json()
    well_id = next(w for w in wells if w["well_name"] == "NG-2000-4")["id"]

    detail = client.get(f"/api/wells/{well_id}").json()
    assert detail["well"]["well_name"] == "NG-2000-4"
    assert len(detail["timeline"]) == 1

    day = detail["timeline"][0]
    assert day["report_date"] == "2026-04-02"
    assert day["mode"] == "D"
    assert len(day["phases"]) == 4
    assert day["phases"][1] == {
        "phase_no": 2,
        "casing_size": '13 3/8"',
        "depth_planned": 2400.0,
        "depth_actual": 2404.0,
        "days_planned": 34,
        "days_actual": 53,
    }
    assert day["repair_events"] == []  # LLM mocked to return none


def test_get_well_detail_404_for_unknown_well(client):
    response = client.get("/api/wells/999999999")
    assert response.status_code == 404


def test_well_detail_timeline_includes_both_days_once_both_ingested(client):
    # Phase 9: closes the last unchecked item under
    # docs/10_acceptance_criteria.md's "Multi-day timeline" section --
    # the DB-level accumulation was already proven in
    # tests/test_ingest.py; this proves the API surfaces both days too.
    _upload_sample(client)  # day 1 (02.04.2026), 4 wells
    with open(SAMPLES_DIR / "sample_dpr_assam_ro_day2.pdf", "rb") as day2_file:
        response = client.post(
            "/api/ingest",
            files=[("files", ("sample_dpr_assam_ro_day2.pdf", day2_file, "application/pdf"))],
        )
    assert response.json()["errors"] == []

    wells = client.get("/api/wells").json()
    well_id = next(w for w in wells if w["well_name"] == "NG-2000-4")["id"]

    timeline = client.get(f"/api/wells/{well_id}").json()["timeline"]
    assert [day["report_date"] for day in timeline] == ["2026-04-02", "2026-04-03"]
    assert timeline[0]["present_depth"] == 3612.0
    assert timeline[1]["present_depth"] == 3616.0
    assert timeline[0]["tot_days_actual"] == 155
    assert timeline[1]["tot_days_actual"] == 156


def test_get_well_variance_matches_spec_worked_example(client):
    _upload_sample(client)
    wells = client.get("/api/wells").json()
    well_id = next(w for w in wells if w["well_name"] == "NG-2000-4")["id"]

    variance = client.get(f"/api/wells/{well_id}/variance").json()
    assert variance["report_date"] == "2026-04-02"
    # (155 - 190) / 190 * 100 -- matches the -18.4 worked example in
    # docs/08_api_specification.md almost exactly.
    assert variance["days_variance_pct"] == pytest.approx(-18.42, abs=0.01)

    phase1 = variance["phases"][0]
    # This phase's numbers are the exact worked example from the spec:
    # days_variance_pct 50.0, depth_planned 450.0, depth_actual 453.0.
    assert phase1["phase_no"] == 1
    assert phase1["casing_size"] == '20"'
    assert phase1["days_variance_pct"] == 50.0
    assert phase1["depth_planned"] == 450.0
    assert phase1["depth_actual"] == 453.0


def test_get_well_variance_404_for_unknown_well(client):
    response = client.get("/api/wells/999999999/variance")
    assert response.status_code == 404


def test_repairs_unreviewed_and_review_endpoint(client):
    fake_event = [
        {"equipment_or_system": "DW drum encoder", "snippet": "fixed it", "confidence": "high"}
    ]
    with patch("app.ingest.extract_repair_events", return_value=fake_event):
        _upload_sample(client)

    unreviewed = client.get("/api/repairs/unreviewed").json()
    ours = [e for e in unreviewed if e["well_name"] in TEST_WELL_NAMES]
    assert len(ours) == 4  # one fake event per well (4 wells)
    assert ours[0]["equipment_or_system"] == "DW drum encoder"

    repair_id = ours[0]["repair_id"]
    review_response = client.post(f"/api/repairs/{repair_id}/review")
    assert review_response.status_code == 200
    assert review_response.json() == {"ok": True}

    unreviewed_after = client.get("/api/repairs/unreviewed").json()
    assert repair_id not in [e["repair_id"] for e in unreviewed_after]


def test_review_unknown_repair_404(client):
    response = client.post("/api/repairs/999999999/review")
    assert response.status_code == 404


def test_bodyless_review_defaults_to_confirmed(client):
    fake_event = [
        {"equipment_or_system": "DW drum", "snippet": "fixed it", "confidence": "high"}
    ]
    with patch("app.ingest.extract_repair_events", return_value=fake_event):
        _upload_sample(client)
    repair_id = next(
        e for e in client.get("/api/repairs/unreviewed").json()
        if e["well_name"] in TEST_WELL_NAMES
    )["repair_id"]

    response = client.post(f"/api/repairs/{repair_id}/review")
    assert response.status_code == 200

    reviewed = client.get("/api/repairs/reviewed").json()
    ours = next(e for e in reviewed if e["repair_id"] == repair_id)
    assert ours["outcome"] == "confirmed"


def test_review_with_explicit_false_positive_outcome(client):
    fake_event = [
        {"equipment_or_system": "DW drum", "snippet": "fixed it", "confidence": "high"}
    ]
    with patch("app.ingest.extract_repair_events", return_value=fake_event):
        _upload_sample(client)
    repair_id = next(
        e for e in client.get("/api/repairs/unreviewed").json()
        if e["well_name"] in TEST_WELL_NAMES
    )["repair_id"]

    response = client.post(
        f"/api/repairs/{repair_id}/review", json={"outcome": "false_positive"}
    )
    assert response.status_code == 200

    reviewed = client.get("/api/repairs/reviewed").json()
    ours = next(e for e in reviewed if e["repair_id"] == repair_id)
    assert ours["outcome"] == "false_positive"

    # Queryable via the well-detail timeline too, not just the reviewed list.
    well_id = next(
        w for w in client.get("/api/wells").json() if w["well_name"] == "NG-2000-4"
    )["id"]
    timeline_event = client.get(f"/api/wells/{well_id}").json()["timeline"][0]["repair_events"][0]
    assert timeline_event["reviewed"] is True
    assert timeline_event["outcome"] == "false_positive"


def test_review_rejects_invalid_outcome(client):
    fake_event = [
        {"equipment_or_system": "DW drum", "snippet": "fixed it", "confidence": "high"}
    ]
    with patch("app.ingest.extract_repair_events", return_value=fake_event):
        _upload_sample(client)
    repair_id = next(
        e for e in client.get("/api/repairs/unreviewed").json()
        if e["well_name"] in TEST_WELL_NAMES
    )["repair_id"]

    response = client.post(f"/api/repairs/{repair_id}/review", json={"outcome": "bogus"})
    assert response.status_code == 422


def test_reviewed_events_excluded_from_unreviewed_list(client):
    fake_event = [
        {"equipment_or_system": "DW drum", "snippet": "fixed it", "confidence": "high"}
    ]
    with patch("app.ingest.extract_repair_events", return_value=fake_event):
        _upload_sample(client)
    repair_id = next(
        e for e in client.get("/api/repairs/unreviewed").json()
        if e["well_name"] in TEST_WELL_NAMES
    )["repair_id"]

    client.post(f"/api/repairs/{repair_id}/review", json={"outcome": "confirmed"})

    unreviewed = client.get("/api/repairs/unreviewed").json()
    assert repair_id not in [e["repair_id"] for e in unreviewed]
    reviewed = client.get("/api/repairs/reviewed").json()
    assert repair_id in [e["repair_id"] for e in reviewed]


# ---------------------------------------------------------------------------
# Phase 10: original PDFs preserved as the system of record
# ---------------------------------------------------------------------------


def test_uploaded_pdf_is_preserved_byte_for_byte(client, upload_dir):
    original = (SAMPLES_DIR / "sample_dpr.pdf").read_bytes()
    _upload_sample(client)

    stored = list(upload_dir.rglob("*.pdf"))
    assert len(stored) == 1
    assert stored[0].read_bytes() == original


def test_timeline_links_to_downloadable_source_pdf(client):
    _upload_sample(client)
    well_id = next(
        w["id"] for w in client.get("/api/wells").json() if w["well_name"] == "NG-2000-4"
    )
    entry = client.get(f"/api/wells/{well_id}").json()["timeline"][0]
    assert entry["source_document_id"] is not None

    response = client.get(f"/api/documents/{entry['source_document_id']}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == (SAMPLES_DIR / "sample_dpr.pdf").read_bytes()


def test_reuploading_same_pdf_reuses_one_stored_copy(client, upload_dir):
    _upload_sample(client)
    _upload_sample(client)

    assert len(list(upload_dir.rglob("*.pdf"))) == 1
    session = Session()
    try:
        sha_rows = (
            session.query(SourceDocument)
            .filter_by(original_filename="sample_dpr.pdf")
            .count()
        )
    finally:
        session.close()
    assert sha_rows == 1


def test_unparseable_upload_is_not_stored(client, upload_dir):
    import io

    client.post(
        "/api/ingest",
        files=[("files", ("corrupt.pdf", io.BytesIO(b"not a real pdf"), "application/pdf"))],
    )
    assert list(upload_dir.rglob("*.pdf")) == []


def test_download_unknown_document_404(client):
    assert client.get("/api/documents/999999999").status_code == 404

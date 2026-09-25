# API Specification — Drilling DPR Monitor

REST API contract. This has been implemented once already and is
provided here as a starting contract — Claude Code may adjust the
implementation but should confirm any contract changes explicitly
rather than silently drifting from this spec, since the dashboard
depends on it.

## Authentication (added in Phase 10)

Email + password, single role (`07_non_functional_requirements.md`).
**Every `/api/*` endpoint below requires a logged-in session and returns
`401 {"detail": "not authenticated"}` without one** — except
`POST /api/auth/login` and `POST /api/auth/logout`. `/health` and the
static dashboard shell stay public (neither exposes well data).

The session is an `HttpOnly`, `SameSite=Strict` cookie named
`dpr_session`, valid for `SESSION_HOURS` (default 12). There is no
sign-up or password-reset endpoint (no outbound SMTP); accounts are
managed from the command line with `python -m app.users` (see the
project README).

### POST /api/auth/login

**Request body**
```json
{ "email": "someone@ongc.co.in", "password": "..." }
```
Email is matched case-insensitively.

**Response** — `200` with the session cookie set:
```json
{ "email": "someone@ongc.co.in" }
```
`401 {"detail": "invalid email or password"}` for a wrong password, an
unknown email, or a deactivated account — deliberately indistinguishable.

### POST /api/auth/logout

Deletes the session server-side (the old cookie can't be replayed) and
clears the cookie. Always returns `{ "ok": true }`.

### GET /api/auth/me

**Response**
```json
{ "email": "someone@ongc.co.in" }
```

## POST /api/ingest

Upload one or more DPR PDFs in a single request (multipart form,
repeated `files` field) — supports uploading multiple assets' reports
at once.

**Response**
```json
{
  "ingested": [
    {
      "filename": "assam_20260402.pdf",
      "asset_name": "Assam Asset + RO",
      "report_date": "2026-04-02",
      "wells_ingested": 11,
      "repair_events_created": 3
    }
  ],
  "errors": [
    { "filename": "corrupt.pdf", "error": "Could not find report date -- unexpected format" }
  ]
}
```

Re-uploading a file covering a (well, report_date) pair already in the
database **replaces** that entry rather than duplicating it.

**Phase 10:** every file that parses is also stored byte-for-byte as the
system of record (`07_non_functional_requirements.md`), content-addressed
by SHA-256 — re-uploading identical bytes reuses the stored copy. Files
that fail PDF text extraction are not stored. See
`GET /api/documents/{document_id}`.

## GET /api/wells

List every well with its latest known snapshot.

**Response** (array)
```json
{
  "id": 1,
  "well_name": "NG-2000-4",
  "location_code": "HPAA",
  "asset_name": "Assam Asset + RO",
  "category": "ON LAND EXPLORATORY WELLS",
  "target_depth": 4394.0,
  "latest_report_date": "2026-04-02",
  "present_depth": 3612.0,
  "tot_days_planned": 190,
  "tot_days_actual": 155,
  "cost_planned_inr": 886323863.0,
  "cost_actual_inr": 960346238.0,
  "status_text": "LOC#NA (NOT AVAILABLE)"
}
```

## GET /api/wells/{well_id}

Full well detail plus its complete daily timeline.

**Response**
```json
{
  "well": { "id": 1, "well_name": "NG-2000-4", "...": "..." },
  "timeline": [
    {
      "report_date": "2026-04-02",
      "source_document_id": 3,
      "mode": "D",
      "present_depth": 3612.0,
      "day_meterage": null,
      "tot_days_planned": 190,
      "tot_days_actual": 155,
      "cost_planned_inr": 886323863.0,
      "cost_actual_inr": 960346238.0,
      "status_text": "LOC#NA (NOT AVAILABLE)",
      "oper_narrative": "RECTIFIED OIL LEAKAGE FROM DW. ...",
      "phases": [
        { "phase_no": 1, "casing_size": "20\"", "depth_planned": 450.0,
          "depth_actual": 453.0, "days_planned": 8, "days_actual": 12 }
      ],
      "repair_events": [
        { "equipment_or_system": "DW (drawworks)",
          "snippet": "RECTIFIED OIL LEAKAGE FROM DW",
          "confidence": "high", "reviewed": false, "outcome": null }
      ]
    }
  ]
}
```

`source_document_id` (added in Phase 10) is the stored original PDF this
day's entry came from — `null` for entries ingested before Phase 10 or
from text rather than a PDF upload.

## GET /api/wells/{well_id}/variance

Latest planned-vs-actual variance, well-level and per-phase.

**Response**
```json
{
  "report_date": "2026-04-02",
  "days_variance_pct": -18.4,
  "cost_variance_pct": 8.4,
  "phases": [
    { "phase_no": 1, "casing_size": "20\"", "days_variance_pct": 50.0,
      "depth_planned": 450.0, "depth_actual": 453.0 }
  ]
}
```
Variance % = `(actual - planned) / planned * 100`. Negative = ahead of
plan (fewer days than planned so far); positive = behind/over plan.

## GET /api/repairs/unreviewed

All repair/troubleshooting events not yet confirmed/dismissed by a
human, most recent first.

**Response** (array)
```json
{
  "repair_id": 7,
  "well_name": "EV-2000-4",
  "report_date": "2026-04-03",
  "equipment_or_system": "DW drum encoder",
  "snippet": "REPLACED D/WORKSENCODER BY FMP(E), TESTED OK",
  "confidence": "high"
}
```
(Example corrected 2026-09-04 — the previous example's exact quote
never appeared in any real sample; see the note in
`06_llm_prompts_and_eval.md`'s evaluation-set verification section.)

## GET /api/repairs/reviewed

**Added in Phase 7.** All repair/troubleshooting events a human has
already acted on, most recent first — lets the confirmed-vs-false-positive
split (see below) be queried/measured over time, not just eyeballed.

**Response** (array)
```json
{
  "repair_id": 4,
  "well_name": "NG-2000-4",
  "report_date": "2026-04-02",
  "equipment_or_system": "DW drum",
  "snippet": "RECTIFIED OIL LEAKAGE FROM DW",
  "confidence": "high",
  "outcome": "confirmed"
}
```

## POST /api/repairs/{repair_id}/review

Marks one repair event as reviewed, recording whether it was a real
issue or a false positive — this is how `docs/09_ui_wireframes.md`
Screen 3's "keep the confirmed vs. false-positive distinction"
recommendation is implemented (added in Phase 7; superseded the original
v1 contract, which had no body).

**Request body** (optional — a bodyless POST still works and defaults
to `"confirmed"`, preserving the original v1 behavior)
```json
{ "outcome": "confirmed" }
```
`outcome` must be `"confirmed"` or `"false_positive"`.

**Response**
```json
{ "ok": true }
```

## GET /api/documents/{document_id}

**Added in Phase 10.** Returns the original uploaded PDF
(`application/pdf`, `Content-Disposition: inline` with the original
filename). `404` if the id is unknown or the file is missing from
storage.

## Endpoints planned but not yet implemented

- `POST /api/ingest-proposal` — one-time proposal/AFE ingestion per
  well. Blocked on having a real sample document to build extraction
  against (see `02_data_dictionary.md` §B).

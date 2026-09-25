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
      "repair_events_created": 3,
      "repair_checks_failed": 0
    }
  ],
  "errors": [
    { "filename": "corrupt.pdf", "error": "Could not find report date -- unexpected format" }
  ]
}
```

Re-uploading a file covering a (well, report_date) pair already in the
database **replaces** that entry rather than duplicating it.

`repair_checks_failed` (added 2026-09-25) counts wells whose narrative
could **not** be checked for repair/troubleshooting events because the
local LLM was unreachable or errored — those wells' zero events are
unverified, not "none found". See `GET /api/repairs/check-status`.

**Phase 10:** every file that parses is also stored byte-for-byte as the
system of record (`07_non_functional_requirements.md`), content-addressed
by SHA-256 — re-uploading identical bytes reuses the stored copy. Files
that fail PDF text extraction are not stored. See
`GET /api/documents/{document_id}`.

## Ingest jobs — background queue (added 2026-09-25)

`POST /api/ingest` above ingests inside the request, which is fine for a
file or two but not for backlog uploads (`07_non_functional_requirements.md`
makes those a normal, recurring case): each well's narrative takes ~12s
through the local LLM on CPU, so a large batch could run for hours in one
request. The dashboard now uploads through this queue instead;
`POST /api/ingest` is unchanged and still available (scripts, tests).

Jobs are rows in Postgres, processed one at a time, oldest first, by a
worker thread in the app process (`app/jobs.py`). They survive a restart:
a job interrupted mid-run is re-queued and re-run from the start on the
next startup, which is safe because ingestion replaces rather than
duplicates. `INGEST_WORKER=false` runs the API without consuming the
queue.

### POST /api/ingest-jobs

Same multipart request as `POST /api/ingest` (repeated `files` field).
Returns as soon as the files are stored and queued.

**Response**
```json
{
  "queued": [ { "job_id": 12, "filename": "assam_20260402.pdf" } ],
  "errors": [ { "filename": "notes.txt", "error": "not a PDF file" } ]
}
```
Only a cheap check happens at upload (the file must start with the PDF
header `%PDF-`) so large batches upload quickly; a file that passes it
but can't actually be read fails later, as that job's `error`. Every
queued file is stored as the system of record first (see
`GET /api/documents/{document_id}`).

### GET /api/ingest-jobs?limit=100

Queue totals plus the most recent `limit` jobs (1–1000, default 100),
newest first.

**Response**
```json
{
  "counts": { "queued": 40, "running": 1, "done": 212, "failed": 1 },
  "jobs": [
    {
      "job_id": 12,
      "filename": "assam_20260402.pdf",
      "status": "running",
      "wells_done": 7,
      "wells_total": 13,
      "result": null,
      "error": null,
      "created_at": "2026-09-25T06:35:41",
      "started_at": "2026-09-25T06:36:02",
      "finished_at": null
    }
  ]
}
```
`status` is `queued` → `running` → `done` | `failed`. `wells_total` is
`null` until the PDF has been parsed. `result`, once `done`, has exactly
the shape of one `POST /api/ingest` `ingested` item. Timestamps are UTC.

### GET /api/ingest-jobs/{job_id}

One job, same shape as a `jobs` item above. `404` if unknown.

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
      "repair_check_status": "ok",
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

`repair_check_status` (added 2026-09-25): `"ok"` — the LLM check ran
(an empty `repair_events` genuinely means none found); `"failed"` — the
local LLM was unreachable/errored, so the narrative has **not** been
checked; `"queued"` — a re-run is pending; `null` — ingested before this
was tracked (unknown).

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

## GET /api/repairs/check-status

**Added 2026-09-25.** How many daily reports have not been checked for
repair/troubleshooting events because the local LLM failed, and how many
are queued for a re-run — drives the dashboard's warning banner.

**Response**
```json
{ "failed": 4, "queued": 0 }
```

## POST /api/repairs/recheck

**Added 2026-09-25.** Queues every `"failed"` check for a re-run by the
background worker (after any pending uploads, one report at a time). A
re-run that fails again goes back to `"failed"` — it is not retried in a
loop; call this again once the LLM is reachable. Events it creates are
`reviewed = false`, like any other.

**Response**
```json
{ "queued": 4 }
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

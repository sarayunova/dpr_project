# Acceptance Criteria — Drilling DPR Monitor v1

Define pass/fail tests against the real samples in
`03_sample_documents/` (see that folder's `README.md` for the full list
and what each one exercises), so "done" is objective rather than a
judgment call. Below are starter criteria derived from those samples —
verify these against your own copy of the build, and add more once a
real proposal document is available.

## Parsing correctness (against `sample_dpr.txt`)

Verified by `tests/test_parser.py` (Phase 1); the last item additionally
by `tests/test_ingest.py` (Phase 3).

- [x] Ingesting this file creates exactly 4 wells: `NG-2000-4`,
      `NG-2000-6`, `ARMCUE-1`, `E-1400-13`.
- [x] `NG-2000-4`'s total days planned/actual are exactly `190` / `155`.
- [x] `NG-2000-4`'s cost planned/actual are exactly `886323863.0` /
      `960346238.0`.
- [x] `NG-2000-4` has exactly 4 phase rows, with phase 2's casing size
      parsed as `13 3/8"` (not corrupted by the fraction's `/`) and
      depth planned/actual `2400.0` / `2404.0`.
- [x] `ARMCUE-1`'s cost **planned** value is `null`/`None` (source field
      is blank) while cost **actual** is `378925607.0` — blank-planned
      values must not be coerced to zero or dropped.
- [x] `E-1400-13`, whose block spans a page break with a repeated SAP
      page banner in the middle of it, still parses into one well with
      3 phases and both cost fields correctly matched from the
      *second* half of the block (after the banner).
- [x] Re-uploading the same file a second time does not create
      duplicate DailyEntry rows for these wells/date — it replaces them.

## Repair/troubleshooting extraction (against real narratives)

Verified against the real local LLM (`qwen2.5:1.5b-instruct` — see
`06_llm_prompts_and_eval.md`'s "Acceptance threshold" for why this model
size, not yet the recommended production one) via
`app.llm_client.extract_repair_events` directly, and the DB-level
wiring (event creation, `reviewed=false`, replace-on-reingest) via
`tests/test_ingest.py` with the LLM boundary mocked.

- [x] `EV-2000-4`'s narrative in `sample_dpr_assam_ro_day2.txt`
      (`REPLACED B/OFF TONG DAMAGED JERK LINE WITH NEW ONE. REPLACED
      D/WORKSENCODER BY FMP(E), TESTED OK.`) produces at least one
      repair event referencing the encoder — confirmed:
      `{"equipment_or_system": "DW drum encoder", "snippet": "REPLACED
      D/WORKSENCODER BY FMP(E), TESTED OK", "confidence": "high"}`.
      **Correction (2026-09-03)**: this item previously named
      `NG-2000-6` with an `ENCOUNTERED DW DRUM ENCODER FAULT...` quote
      that does not actually appear anywhere in `sample_dpr.txt` — that
      exact narrative never existed in this well's real text. Fixed to
      cite the real source, found while building out the evaluation set
      in `06_llm_prompts_and_eval.md`.
- [x] `E-1400-13`'s narrative (rig-dragging, pulley-fitting, material
      shifting — no fault language) produces **zero** repair events —
      confirmed against the real model.
- [x] Every repair event defaults to `reviewed = false` until a human
      confirms it via the review endpoint — `tests/test_ingest.py::
      test_llm_flagged_events_become_repair_event_rows_unreviewed`.

Done: the evaluation set in `06_llm_prompts_and_eval.md` now has 21 rows
(18 machine-verifiable, in `eval/repair_extraction_eval.json`), and
`scripts/run_repair_eval.py` tracks precision/recall against it. Run
against the actual production-recommended model (`qwen2.5:7b-instruct`):
**1.00 recall / 0.83 precision (94% accuracy, zero false negatives)** —
its one false positive is the exact narrative this eval set had already
flagged in advance as the most likely case for reasonable disagreement,
not a wiring bug. See the doc's "Acceptance threshold" section for the
full comparison against the smaller model used earlier, and the
performance caveat about per-narrative latency at full well-count scale.

## API contract

- [x] Every endpoint in `08_api_specification.md` returns the documented
      shape for the sample data above — `tests/test_api.py` (11 tests),
      plus a live `uvicorn` smoke test hitting every endpoint with real
      `curl` requests. The variance endpoint's numbers were checked
      against the spec's own worked examples and matched exactly
      (`NG-2000-4`: -18.42% days variance vs. the spec's -18.4 example;
      phase 1: 50.0% days variance, `depth_planned`/`depth_actual`
      450.0/453.0 — an exact match to the spec's phase example).

## Dashboard

Verified manually in a real browser (Phase 6) against the live app —
Postgres + Ollama (`qwen2.5:7b-instruct`) running, `uvicorn` serving
`static/index.html` at `/`.

- [x] Uploading `sample_dpr.pdf` (the equivalent test PDF built from
      `sample_dpr.txt`, since no original exists) through the UI
      populates the wells table correctly, with color-coded
      planned/actual pills matching the values from `GET /api/wells`
      exactly (e.g. `NG-2000-4`: `190 / 155 (-18.4%)` days in green,
      `886,323,863 / 960,346,238 (+8.4%)` cost in red).
- [x] Clicking into a well shows its variance and timeline matching the
      API response — `NG-2000-4`'s variance summary (`-18.4%` /
      `+8.4%`) and phase table (phase 1: `+50.0%`, `450 / 453`) matched
      `08_api_specification.md`'s own worked examples exactly. The
      narrative, and a real LLM-flagged repair event with its
      **"pending review" pill** (per `05_architecture.md`'s
      human-in-the-loop requirement), rendered correctly inline.

## Repair/troubleshooting review queue (Screen 3, Phase 7)

Verified both automatically (`tests/test_api.py`, mocked LLM) and
manually in a real browser against the live app with a real model
(`qwen2.5:7b-instruct`).

- [x] A repair event flagged during ingestion can be reviewed
      end-to-end through the UI: `docs/09_ui_wireframes.md` Screen 3's
      list (well name, date, equipment, snippet, confidence) rendered
      correctly for all 3 real events from a live ingest, each with
      working Confirm and Dismiss buttons.
- [x] The confirmed-vs-false-positive distinction (recommended in
      `09_ui_wireframes.md`, implemented as `RepairEvent.outcome`) is
      queryable afterward: confirmed via `GET /api/repairs/reviewed`
      returning the correct `outcome` per event, via the well-detail
      timeline showing the same event with a "confirmed" or "dismissed
      (false positive)" pill instead of "pending review", and via
      automated tests asserting both.
- [x] A bodyless `POST /api/repairs/{id}/review` still works and
      defaults to `"confirmed"`, preserving the pre-Phase-7 contract;
      an invalid `outcome` value is rejected with `422`.

## Multi-day timeline (against `sample_dpr.txt` + `sample_dpr_assam_ro_day2.txt`)

`sample_dpr_assam_ro_day2.txt` is the same "Assam Asset + RO" asset, the
day immediately after `sample_dpr.txt` (02.04.2026–03.04.2026 vs.
01.04.2026–02.04.2026), so ingesting both in order (day 1, then day 2)
exercises accumulation across two `DailyEntry` rows for the same well
rather than an overwrite of one row.

- [x] Ingesting both files creates **two** `DailyEntry` rows for
      `NG-2000-4` (`report_date` 02.04.2026 and 03.04.2026), not one —
      unlike re-ingesting the *same* file twice (which must replace, per
      the Parsing correctness section above), ingesting two *different*
      report dates for the same well must accumulate.
- [x] `NG-2000-4`'s present depth increases from `3612.0` (day 1) to
      `3616.0` (day 2), consistent with that day's `Day Mtr:4`.
- [x] `NG-2000-4`'s total days actual increases from `155` (day 1) to
      `156` (day 2); total days planned stays `190` on both days.
- [x] `NG-2000-4`'s cost planned/actual are **unchanged** between day 1
      and day 2 (`886323863.0` / `960346238.0` both days) — cost figures
      can legitimately stay flat for a day even while depth/days move;
      don't treat an unchanged value as a parsing error.
- [x] The well-detail timeline (`GET /api/wells/{id}`, per
      `08_api_specification.md`) returns both days' entries in the
      timeline array once both files are ingested —
      `tests/test_api.py::test_well_detail_timeline_includes_both_days_once_both_ingested`
      (Phase 9), using the real PDFs end to end through the API, not
      just the hand-transcribed text.

All five items above are now verified at every layer: parser output
(Phase 1, `tests/test_parser.py`), the DB (Phase 3,
`tests/test_ingest.py`), and the API (Phase 9, `tests/test_api.py`).

## Multi-asset parsing (against `sample_dpr_assam_arakan.txt` and `sample_dpr_tripura.txt`)

Verified at the parser level by `tests/test_parser.py` (Phase 1), and at
the full DB-ingestion level by `tests/test_ingest.py`
(`test_ingest_assam_arakan_different_asset_and_zero_phase_well`,
`test_ingest_tripura_workover_category_and_missing_phase_number`, Phase
9) — Phase 1 only proved these formats *parse*; Phase 9 proves the full
pipeline (well upsert, `DailyEntry`, `PhaseSnapshot`) holds up on them
too, and this is also where a real pdfplumber word-merging bug was
caught (see `02_data_dictionary.md` §A.4) — Phase 1's tests used
hand-transcribed text and couldn't have found it.

- [x] `sample_dpr_assam_arakan.txt` ingests 3 wells (`E-760-10`,
      `E-1400-24`, `E-760-9U`) under asset name `Assam & Assam Arakan
      Basin, Jorhat`, distinct from `Assam Asset + RO`.
- [x] `E-760-10` (sequence number `0`, `MODE:O`) ingests with **zero**
      `PhaseSnapshot` rows and every date/depth/day/cost field `null` —
      the parser must not error or skip the well just because its phase
      table has a header but no data rows, and must not assume every
      well's sequence number starts at 1.
- [x] `sample_dpr_tripura.txt` ingests 6 wells under asset name `Tripura
      Asset` (`E-1400-M1`, `NG-2000-1`, `NG-2000-2`, `NG-2000-3`,
      `E-1400-14`, `E-1400-M2`), including one (`E-1400-M2`) categorized
      `WORKOVER WELLS` — a third category value alongside `ON LAND
      EXPLORATORY WELLS` / `ON LAND DEVELOPMENT WELLS`.
- [x] `E-1400-M2`'s `WO P/A` value, which wraps onto its own line in the
      source text (`TOT.P/A:20/157 WO\nP/A:45/40/`), still parses as
      planned `45` / actual `40` — not dropped or misattributed to
      another field.
- [x] `NG-2000-3` (Tripura sample) has exactly 4 phase rows despite its
      first row's phase-number token being absent from the source text —
      the parser must infer phase 1 by row position, not by a leading
      number.
- [x] Ingesting the **real** `sample_dpr_assam_ro_day2.pdf` (not the
      hand-transcribed `.txt`) end to end produces `asset_name` `Assam
      Asset + RO`, uncorrupted, and all 13 wells —
      `tests/test_ingest.py::test_ingest_real_pdf_extraction_does_not_merge_words_in_banner`.
      Regression test for the pdfplumber word-merging bug found in
      Phase 9; see `02_data_dictionary.md` §A.4.

## Non-functional hardening (Phase 10)

Derived from `07_non_functional_requirements.md`. Automated in
`tests/test_auth.py` and `tests/test_api.py` unless marked manual.

**Authentication (email + password, single role)**
- [x] Every `/api/*` route except login/logout returns `401` without a
      session — enumerated from the app's route table, so a new endpoint
      added without the login guard fails the test automatically.
- [x] `/health` and the dashboard shell stay reachable logged-out.
- [x] Correct login sets an `HttpOnly`, `SameSite=Strict` session cookie
      and grants access; email matching is case-insensitive.
- [x] Wrong password and unknown email return identical `401` responses.
- [x] Passwords stored salted-hashed (scrypt), never plaintext; session
      tokens stored only as a SHA-256 hash.
- [x] Logout invalidates the session server-side (replaying the old
      cookie fails); expired sessions are rejected.
- [x] Deactivating a user or changing their password (CLI) ends their
      existing sessions immediately.
- [x] Manual (browser): logged-out dashboard shows only the sign-in form;
      wrong password shows an error; correct login loads the dashboard;
      log out returns to the sign-in form.

**Original PDFs preserved as system of record**
- [x] An uploaded PDF is stored byte-for-byte on disk and linked from
      each `DailyEntry` it produced (`source_document_id`).
- [x] `GET /api/documents/{id}` returns the identical bytes as
      `application/pdf`; the dashboard timeline links to it.
- [x] Re-uploading identical bytes keeps one stored copy and one row.
- [x] A file that isn't a readable PDF is not stored.

**Deployment, restart survival, backups** (manual, verified 2026-09-25
against the full `docker compose up --build` stack)
- [x] App container waits for a healthy database, applies migrations on
      start, and serves `/health`.
- [x] Killing the app's process inside the container: Docker restarts
      it automatically (`RestartCount` 1, `/health` OK).
- [x] Full flow in Docker: create user via `python -m app.users` →
      login → upload → PDF appears under `UPLOAD_HOST_DIR` on the host.
- [x] The `backup` service writes a `pg_dump` and mirrors the uploaded
      PDF; restoring that dump into a scratch database with `pg_restore`
      reproduces wells, daily entries, users, and source documents.
- [ ] Survives a real machine reboot — **requires Docker Desktop's
      "Start Docker Desktop when you sign in" setting, which is currently
      off on the dev machine**; and Docker Desktop only starts on user
      sign-in, not at boot. Re-check on the actual deployment machine.

## Background ingestion queue (added 2026-09-25)

Automated in `tests/test_jobs.py`; LLM mocked.
- [x] `POST /api/ingest-jobs` returns with the files stored and queued,
      before any wells are ingested.
- [x] The worker produces the same result as synchronous ingestion
      (identical `result` shape and values; `DailyEntry` linked to its
      `SourceDocument`).
- [x] Per-well progress (`wells_done` / `wells_total`) is visible from a
      separate session while the job is still running.
- [x] A non-PDF is rejected at upload and not stored; a PDF-headed but
      unreadable file fails only its own job, and later jobs still run.
- [x] Jobs run oldest first; `GET /api/ingest-jobs` counts are correct.
- [x] A job left `running` by a restart is re-queued on startup and then
      completes.
- [x] The real worker thread (started by the app's startup hook) picks up
      an upload and finishes it without any manual trigger.
- [x] Queue routes require login (covered by the route-enumerating auth
      test).
- [x] Manual (browser, 2026-09-25): uploading all four sample PDFs plus a
      non-PDF returned immediately; the non-PDF showed "not a PDF file";
      the queue list showed queued → running with "2 / 4 wells" progress →
      done with each file's result; the wells table refreshed by itself
      when jobs finished (26 wells across 3 assets).

## LLM-unreachable warning and re-check (added 2026-09-25)

Automated in `tests/test_llm_client.py`, `tests/test_ingest.py`,
`tests/test_jobs.py`; LLM mocked.
- [x] A failed LLM call (connection error, HTTP error, invalid JSON,
      unusable shape) raises `RepairExtractionError` — never `[]`.
- [x] Ingestion with the LLM down still stores every well's data, marks
      each entry `repair_check_status = "failed"`, and reports
      `repair_checks_failed` in the ingest/job result.
- [x] A check that ran and found nothing is `"ok"` — distinguishable from
      one that failed. A partial failure is counted per well.
- [x] Re-ingesting once the LLM is back resets the status to `"ok"`.
- [x] `GET /api/repairs/check-status` counts failed/queued reports;
      `GET /api/wells/{id}` exposes `repair_check_status` per day.
- [x] `POST /api/repairs/recheck` queues failed checks; the worker re-runs
      them, creating `reviewed = false` events and setting `"ok"`.
- [x] A re-check while the LLM is still down tries each report exactly
      once and returns it to `"failed"` — no retry loop.
- [x] Manual (browser, 2026-09-25, stand-in model server): with the model
      down, uploading `sample_dpr.pdf` showed the warning banner ("did
      not run for 4 daily report(s)"), the job as `done*` with the
      warning, and "repair check not run" on NG-2000-4's day (a narrative
      containing "RECTIFIED OIL LEAKAGE FROM DW"). After starting the
      model and clicking Re-run checks, the banner cleared, all 4 reports
      became `ok`, and the flagged events appeared in the review queue.

## Not yet defined (fill in once available)

- [ ] Proposal ingestion correctness — blocked on a real sample.
- [ ] Performance criteria — see `07_non_functional_requirements.md`.

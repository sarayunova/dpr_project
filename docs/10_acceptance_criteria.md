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

## Not yet defined (fill in once available)

- [ ] Proposal ingestion correctness — blocked on a real sample.
- [ ] Performance criteria — see `07_non_functional_requirements.md`.

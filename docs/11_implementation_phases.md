# Implementation Phases — Drilling DPR Monitor

Each phase is scoped to be independently buildable, testable, and
reviewable — don't let Claude Code jump ahead to a later phase's work
even if it seems easy to combine. Confirm each phase's exit criteria
before starting the next one. Phases map to the acceptance checks in
`10_acceptance_criteria.md` where possible; add new checks there as
each phase completes if the current list doesn't already cover it.

## Phase 0 — Project scaffolding

**Goal**: an empty-but-runnable skeleton, nothing functional yet.

- Repo structure per `CLAUDE.md`'s target layout.
- `requirements.txt` / dependency manifest.
- `README.md` (project-facing, distinct from `docs/00_README.md`)
  with setup steps: install Ollama + pull a model, install deps, run.
- Empty FastAPI app that starts and serves a health-check route.
- Git initialized, `.gitignore` covering the local SQLite file, `venv/`,
  `__pycache__/`.

**Exit criteria**: `uvicorn app.main:app --reload` starts with no
errors; a `GET /health` (or equivalent) returns 200.

## Phase 1 — Deterministic DPR parser

**Goal**: `app/parser.py` turns raw DPR text into structured Python
objects, with no database or LLM involved yet.

- Implement parsing per `02_data_dictionary.md` §A.
- Handle the specific hazards it documents: page-break banners, the two
  separator-line lengths, casing-fraction disambiguation, blank fields.
- Unit tests against `03_sample_documents/sample_dpr.txt` asserting the
  exact values listed in `10_acceptance_criteria.md` (well count, each
  well's day/cost figures, phase table correctness, the page-break case
  for `E-1400-13`).

**Exit criteria**: all parser-related checkboxes in
`10_acceptance_criteria.md` §"Parsing correctness" pass as automated
tests, not manual spot checks.

## Phase 2 — Data model & database

**Goal**: the schema in `04_data_model.md` exists and is migratable.

- Implement `Well`, `Proposal`, `DailyEntry`, `PhaseSnapshot`,
  `RepairEvent` per the entity contract (ORM of your choice).
- A way to initialize/reset the database for local dev.
- No ingestion logic yet — just confirm the schema by writing and
  reading a hand-built row of each entity in a test.

**Exit criteria**: schema matches `04_data_model.md` field-for-field;
round-trip test (write then read) passes for every entity.

## Phase 3 — Ingestion pipeline (no LLM yet)

**Goal**: a DPR PDF goes in, `DailyEntry` + `PhaseSnapshot` rows come
out. Repair/troubleshooting extraction is stubbed (empty list) — LLM
integration is Phase 4, kept separate so parsing/DB bugs aren't
tangled up with LLM-related ones.

- PDF → text extraction (pdfplumber per `05_architecture.md`).
- Wire Phase 1's parser output into Phase 2's models via an
  upsert-by-(well, report_date) write path — replace, don't duplicate,
  per the re-ingestion rule in `CLAUDE.md`.
- Well matching/creation by `well_name`.

**Exit criteria**: ingesting `sample_dpr.txt` (as an actual PDF — build
or obtain one from it if only text exists) produces the exact
`DailyEntry`/`PhaseSnapshot` rows checked in `10_acceptance_criteria.md`,
including the page-break well and the blank-planned-cost well.
Re-running ingestion on the same file doesn't duplicate rows.

## Phase 4 — Local LLM: repair/troubleshooting extraction

**Goal**: `app/llm_client.py` calls a local Ollama instance and Phase
3's stub is replaced with real extraction.

- Implement the prompt from `06_llm_prompts_and_eval.md` Prompt 1
  exactly, with `temperature: 0.0` and JSON-mode output.
- Wire it into ingestion: every `DailyEntry`'s `oper_narrative` gets
  passed through, results become `RepairEvent` rows with
  `reviewed = false`.
- Handle LLM call failures gracefully (don't crash ingestion of other
  wells if one narrative's LLM call errors — log and continue, matching
  the pattern already sketched in `ingest.py`).
- Build out the evaluation set in `06_llm_prompts_and_eval.md` past its
  current 5 rows (this is manual/human work, not something Claude Code
  can do alone — flag it back to the user if the set is still small
  when this phase starts).

**Exit criteria**: the repair-extraction checkboxes in
`10_acceptance_criteria.md` pass; a documented precision/recall check
against the evaluation set exists, even if informal.

## Phase 5 — API layer

**Goal**: every endpoint in `08_api_specification.md` implemented and
tested against Phase 3/4's data.

- `POST /api/ingest`, `GET /api/wells`, `GET /api/wells/{id}`,
  `GET /api/wells/{id}/variance`, `GET /api/repairs/unreviewed`,
  `POST /api/repairs/{id}/review`.
- Response shapes match the spec exactly — this is the dashboard's
  contract, don't let it drift silently.
- Automated tests hitting each endpoint with `sample_dpr.txt` ingested,
  asserting on response shape and values.

**Exit criteria**: `10_acceptance_criteria.md` §"API contract" passes.

## Phase 6 — Dashboard: wells overview + well detail

**Goal**: the two core screens from `09_ui_wireframes.md` (Screens 1
and 2), backed by Phase 5's API.

- Upload UI (multi-file), wells table with variance color-coding, well
  detail page with timeline, phase variance, and narrative display.
- Doesn't need to be the final visual design — functional and correct
  first, polish later if wanted.

**Exit criteria**: `10_acceptance_criteria.md` §"Dashboard" passes
manually (upload the sample, verify what renders matches the API
response).

## Phase 7 — Repair/troubleshooting review queue UI

**Goal**: Screen 3 from `09_ui_wireframes.md` — a usable review
interface for the API built in Phase 5.

- List unreviewed events, allow confirm/dismiss.
- Decide and implement the confirmed-vs-false-positive distinction
  flagged as recommended in `09_ui_wireframes.md`, so precision can be
  measured over time, not just a binary "reviewed" flag.

**Exit criteria**: a repair event flagged in Phase 4 can be reviewed
end-to-end through the UI, and the distinction (confirmed vs.
dismissed) is queryable afterward.

## Phase 8 — Proposal/AFE ingestion (blocked)

**Do not start this phase until a real proposal/AFE PDF sample has
been provided and added to `03_sample_documents/`.** Everything in
`02_data_dictionary.md` §B and `06_llm_prompts_and_eval.md` Prompt 2 is
speculative until then.

- Once a real sample exists: repeat the Phase 1 process for this
  document type — analyze the real layout, determine what's regular
  enough to parse deterministically vs. what genuinely needs the LLM,
  update the two docs above from real data the same way the DPR docs
  were built.
- Implement `POST /api/ingest-proposal` and wire `Proposal` rows to
  their `Well`.
- Surface proposal data (proposed/approved dates, GTO details) on the
  well detail screen.

**Exit criteria**: define once the real sample is in hand — don't
pre-write acceptance checks against a guessed format.

## Phase 9 — Multi-asset / multi-format hardening

**Goal**: confirm the system holds up beyond the single sample it was
built against.

- Ingest a second day's DPR for the same wells — verify the timeline
  accumulates correctly and variance figures update as expected.
- If a second asset or region uses a differently-formatted DPR, add it
  as a new sample and extend the parser per the convention in
  `CLAUDE.md`'s "Working conventions" section — new sample and data
  dictionary entry before new parsing code.

**Exit criteria**: `10_acceptance_criteria.md` §"Not yet defined" items
around multi-day timeline correctness are filled in and passing.

## Phase 10 — Non-functional hardening

**Goal**: address whatever `07_non_functional_requirements.md` ends up
specifying, once its `[ ]` sections are filled in.

- Likely candidates depending on answers there: switch SQLite →
  Postgres, add authentication, containerize for deployment, add
  backup/retention handling.

**Exit criteria**: defined by the completed NFR doc — don't guess ahead
of it.

**Status (2026-09-25)**: implemented — email + password auth, original-PDF
preservation, scheduled backups, restart/migration-on-start. Checks in
`10_acceptance_criteria.md` §"Non-functional hardening (Phase 10)".
Still open: the real-reboot check on the deployment machine, the
backup-mechanism confirmation, and the performance items below, which
need a decision rather than code:
- Batch backlog uploads run synchronously in one HTTP request (~12s per
  well narrative through the LLM on CPU), so a large backlog upload can
  run for a very long time in a single request. A background job queue
  would fix this but is an architecture change — confirm before building.
- At 30 wells/asset the per-file LLM time approaches ~6 minutes, over the
  5-minute budget (see `06_llm_prompts_and_eval.md`) — needs a hardware
  benchmark / model-size decision.

## Sequencing notes

- Phases 0-7 can proceed with what's already documented; Phase 8 is
  explicitly blocked on new input from the user.
- Don't parallelize Phase 4 (LLM) with Phase 1-3 (deterministic
  parsing/DB) — keeping them separate is what made the original
  prototype's bugs easy to isolate (a parsing bug and an LLM-prompt
  issue look very different when they're not tangled in the same
  commit).
- After each phase, update `10_acceptance_criteria.md` with any new
  checks discovered during that phase's work, so the file stays a
  living test spec rather than going stale.

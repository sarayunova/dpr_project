# CLAUDE.md — Drilling DPR Monitor

Read `docs/00_README.md` and every file in `docs/` before writing any
code. This file is operating guidance for working in this repo;
`docs/` is the source of truth for requirements, data model, and API
contract. If anything here conflicts with `docs/`, treat `docs/` as
authoritative and flag the conflict rather than silently picking one.

## What this project is

A local, privacy-preserving web app that ingests ONGC-style Drilling
Progress Report (DPR) PDFs and proposal/AFE PDFs, tracks each well's
progress phase-by-phase against its approved baseline, and logs
repair/troubleshooting time from the daily narrative — using a
locally-installed LLM, not a cloud API.

## Non-negotiable constraints

- **No well, cost, or operational data may be sent to any third-party
  API or cloud service.** All LLM inference happens through a locally
  running model (Ollama or equivalent). Do not add analytics SDKs,
  cloud logging, telemetry, or any library that phones home by default.
  If a package you want to use does this, either configure it off
  explicitly or don't use it.
- **Deterministic data stays deterministic.** Fields that are regular
  and label-delimited in the source PDFs (dates, planned/actual day and
  cost figures, the phase table) are parsed with regex/tokenization —
  never routed through the LLM "for robustness." The LLM is reserved
  for genuine judgement tasks (see `docs/06_llm_prompts_and_eval.md`
  for why this line is drawn where it is, and what happened when NPT
  categorization was tried as an LLM task instead of the narrower
  repair/troubleshooting detection that replaced it).
- **Re-ingestion replaces, never duplicates.** Uploading a DPR for a
  (well, report_date) pair already in the database overwrites the
  existing row.

## Project structure (target — adjust if you have a reason, but state it)

```
app/
  parser.py        # deterministic DPR text -> structured data (regex/tokenization, no LLM)
  llm_client.py     # all Ollama calls: repair/troubleshooting extraction, proposal extraction
  ingest.py         # orchestrates PDF -> text -> parse -> LLM -> DB write
  models.py         # ORM models -- see docs/04_data_model.md for the entity contract
  database.py       # DB session/engine setup
  main.py           # API routes -- see docs/08_api_specification.md for the contract
static/
  index.html        # dashboard (or replace with a proper frontend build if scope grows)
docs/               # requirements, data dictionary, architecture, prompts, API spec (read first)
tests/              # see Testing below
```

## Key parsing gotchas (verified against a real sample — see `docs/03_sample_documents/sample_dpr.txt`)

- Casing-size tokens like `3/8"` contain a `/` and look like a
  Planned/Actual pair. Disambiguate with a strict pattern
  (`^[\d,]*/[\d,]*$`) that the casing fraction fails due to its
  trailing `"`.
- A well's block can span a PDF page break, with the full page banner
  (company name, report title, date range, separator line) re-printed
  mid-block. Strip these banners without treating the separator line
  that follows them as end-of-block.
- Two different separator line lengths exist: short (~30 underscores,
  appears before the phase table, mid-block) vs. long (~90 underscores,
  true end-of-block). Don't conflate them.
- Blank fields are common and meaningful (e.g. blank planned cost until
  AFE finalized) — never coerce blank to zero.

Full field-by-field mapping: `docs/02_data_dictionary.md`.

## Testing

- Test the parser against `docs/03_sample_documents/sample_dpr.txt`
  first — it's real data with the page-break and blank-field cases
  already present. Acceptance checks are enumerated in
  `docs/10_acceptance_criteria.md`; treat that file as the test spec,
  and write actual automated tests (pytest) that assert those exact
  values rather than only eyeballing output.
- For the LLM-based repair/troubleshooting extraction, build the
  evaluation set described in `docs/06_llm_prompts_and_eval.md` before
  trusting model output. Every LLM-extracted event ships with
  `reviewed = false` — never surface it in a dashboard or report as
  confirmed fact without that flag being visible.
- Do not write tests that call a real Ollama instance in CI unless CI
  has one available; mock the LLM client boundary (`llm_client.py`) for
  parser/API tests, and keep a small separate suite that exercises the
  real model when run locally.

## Open items to resolve before extending scope

1. Proposal/AFE ingestion is speculative — the prompt in
   `docs/06_llm_prompts_and_eval.md` §Prompt 2 has not been validated
   against a real document. Do not build a polished proposal-ingestion
   UI or assume its field list is final until a real sample has been
   analyzed the same way the DPR was.
2. Non-functional requirements (`docs/07_non_functional_requirements.md`)
   and UI preferences (`docs/09_ui_wireframes.md`) have unresolved
   `[ ]` sections. Ask rather than assume for anything that changes
   architecture (SQLite vs. Postgres, auth requirements, deployment
   target) — these are expensive to reverse later.

## Working conventions

- **Work one phase at a time, per `docs/11_implementation_phases.md`.**
  Confirm a phase's exit criteria are met before starting the next one
  — don't combine phases into one large change even if it seems
  efficient. Phase 4 (LLM integration) is deliberately kept separate
  from Phases 1-3 (deterministic parsing/DB) so bugs in one aren't
  tangled with the other.
- Prefer small, verifiable commits: parser changes should come with a
  test run against the real sample showing before/after output, not
  just a description of the change.
- When extending the parser to a new asset's DPR format, add the new
  sample to `docs/03_sample_documents/` and a corresponding section to
  `docs/02_data_dictionary.md` before writing the extraction code for
  it — the DPR parser here was built from real data, not a spec, and
  the next format should be too.
- Keep `docs/08_api_specification.md` in sync with the actual API. If
  you change a response shape, update the doc in the same change.
- Phase 8 (proposal/AFE ingestion) is blocked until a real sample
  document is provided — do not build ahead of it from the speculative
  field list in `docs/02_data_dictionary.md` §B.

# Drilling DPR Monitor

Local, privacy-preserving tracker for ONGC-style Drilling Progress
Reports. See `docs/` for the full requirements, data model, and API
contract — start with `docs/00_README.md`.

## Prerequisites

- Python 3.12+
- [Ollama](https://ollama.com), running locally, with a model pulled.
  Hardware here is CPU-only, so favor a smaller instruction-following
  model — e.g.:

  ```
  ollama pull qwen2.5:7b-instruct
  ```

  `OLLAMA_MODEL` (default `qwen2.5:7b-instruct`) and `OLLAMA_HOST`
  (default `http://localhost:11434`) are both overridable — see
  `.env.example`.

- Docker + Docker Compose (for Postgres, and for running the app as a
  container per `docs/05_architecture.md`).

## Local development (no Docker)

```
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Visit `http://127.0.0.1:8000/health` — should return `{"status": "ok"}`.

Run tests:

```
pytest
```

To run the database-backed tests and the app itself locally (without
the full Docker Compose stack), start just Postgres and apply migrations:

```
docker compose up -d db
alembic upgrade head
pytest
```

`DATABASE_URL` defaults to `postgresql+psycopg://dpr_monitor:dpr_monitor@localhost:5432/dpr_monitor`
(matching `.env.example`); override it if your local Postgres differs.
Model round-trip tests (`tests/test_models.py`) skip automatically if no
database is reachable, so `pytest` still runs fine without Postgres —
useful when iterating on the parser alone.

Schema changes go through Alembic, not `Base.metadata.create_all()`:

```
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

## Evaluating the repair/troubleshooting LLM

`tests/test_llm_client.py` and `tests/test_ingest.py` mock the LLM
boundary, per CLAUDE.md — they don't need Ollama running. To check the
real model against the labeled examples in
`eval/repair_extraction_eval.json` (see
`docs/06_llm_prompts_and_eval.md`):

```
ollama pull qwen2.5:7b-instruct   # or whatever OLLAMA_MODEL is set to
python scripts/run_repair_eval.py
```

Prints per-row pass/fail plus precision/recall/accuracy. This is a
wiring/regression sanity check, not a production quality gate — every
flagged event still ships with `reviewed = false` and needs human
confirmation regardless of these numbers.

## Running via Docker Compose

```
copy .env.example .env
# edit .env, set a real POSTGRES_PASSWORD
docker compose up --build
```

This starts the app (port 8000) and a Postgres 16 database. Ollama is
expected to already be running on the host machine — it is not
containerized here, since a locally-installed model is the whole point
of the no-cloud-data constraint (see `docs/05_architecture.md`).

## Project layout

```
app/            deterministic parser, LLM client, ingestion, models, API routes
static/         dashboard frontend
docs/           requirements, data model, architecture, API spec (read first)
tests/          automated tests
eval/           labeled examples for the repair-extraction LLM prompt
scripts/        one-off tools (real-model eval runner)
```

## Status

Phases 0-7 and 9 complete: scaffolding, the deterministic DPR parser
(`app/parser.py`), the data model/database (`app/models.py`,
`app/database.py`, Alembic migrations), the ingestion pipeline
(`app/ingest.py`), local LLM repair/troubleshooting extraction
(`app/llm_client.py`), the full REST API (`app/main.py`, 7 endpoints —
the original 6 in `docs/08_api_specification.md` plus
`GET /api/repairs/reviewed` added in Phase 7), the full dashboard
(`static/index.html` — wells overview, well detail, and the
repair/troubleshooting review queue with a confirmed-vs-false-positive
distinction, no external dependencies), and multi-asset/multi-format
hardening (Phase 9) — 61/61 tests passing against a real Postgres
instance, plus manual browser walkthroughs of the live dashboard. A
real bug was caught during Phase 9 by testing the *actual* sample PDFs
end to end (not just hand-transcribed text): pdfplumber's default word
tolerance merged adjacent words in one PDF's banner, corrupting
`asset_name` — fixed and regression-tested, see
`docs/02_data_dictionary.md` §A.4. Real-model eval against the
production-recommended `qwen2.5:7b-instruct`: 100% recall / 83%
precision / 94% accuracy on the 18-row labeled set — see
`docs/06_llm_prompts_and_eval.md` for the full comparison against a
smaller model and a performance caveat at full well-count scale.

Remaining v1 scope: **Phase 8 (proposal/AFE ingestion) is blocked** on
a real sample document (see `02_data_dictionary.md` §B) — nothing to
build there yet. Phase 10 (non-functional hardening, now that
`07_non_functional_requirements.md` is filled in) is open. See
`docs/11_implementation_phases.md` for the full phase-by-phase build
plan.

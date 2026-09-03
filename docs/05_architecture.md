# Technical Architecture — Drilling DPR Monitor

## Hard constraint

**All processing must happen on infrastructure the organization
controls — no well, cost, or operational data may be sent to a
third-party API.** This is why the LLM is a locally-installed model
(via Ollama or equivalent), not a cloud API. This constraint should be
treated as non-negotiable when choosing any library, service, or
default configuration — e.g. no analytics SDKs, no cloud logging
services, no "helpfully" phoning home.

This is confirmed to be a **formal policy** (see
`07_non_functional_requirements.md`) — exact policy citation still to be
added once available.

## Pipeline

```
Proposal/AFE PDF (once, per well)      Daily DPR PDF (daily, per asset, many wells)
            │                                       │
            ▼                                       ▼
   PDF text extraction                     PDF text extraction
   (pdfplumber; OCR fallback                (pdfplumber; regular text-based
   only if a proposal PDF turns             layout confirmed from real
   out to be a scanned image)               sample — OCR fallback only if
            │                               a future asset's export is scanned)
            ▼                                       │
   Local LLM structured extraction                  ▼
   (proposal fields vary more in           Deterministic regex/tokenization
   layout than the DPR, so this            parser (no LLM — see
   whole document goes to the LLM)         02_data_dictionary.md and
            │                              04_data_model.md for exact fields)
            │                                       │
            │                                       ├──► DailyEntry, PhaseSnapshot
            │                                       │    rows written directly
            │                                       │
            │                                       └──► OPER narrative text
            │                                            goes to local LLM for
            │                                            repair/troubleshooting
            │                                            event extraction
            ▼                                                    │
       Proposal row                                     RepairEvent rows
            │                                                    │
            └──────────────────┬─────────────────────────────────┘
                                ▼
                            Database
                                │
                                ▼
                    Variance / comparison logic
                    (planned vs. actual, well- and
                    phase-level, day and cost)
                                │
                                ▼
                          REST API
                                │
                                ▼
                       Web dashboard
                    (well list, well timeline,
                    variance view, repair-event
                    review queue)
```

## Human-in-the-loop review

LLM-extracted data (repair/troubleshooting events, and eventually
proposal fields) is written to the database as-is but flagged
`reviewed = false`. A drilling engineer confirms or dismisses each flag
via the review queue. **Do not treat unreviewed LLM output as
ground truth in any downstream reporting or alerting** without labeling
it as such (e.g. show a "pending review" indicator in the dashboard).

## Recommended stack

(The PDF extraction, LLM runtime, and frontend choices below come from
the tested prototype. The database, auth, and deployment choices have
since been finalized against `07_non_functional_requirements.md` and
supersede what the prototype originally used.)

- **Backend**: Python + FastAPI
- **Database**: **PostgreSQL**, from the start (not SQLite) — chosen
  because the deployment model below has a confirmed future
  shared-server rollout, the scale ceiling is ~900 wells over 5 years,
  and auth requires a real multi-user-capable store; starting on
  Postgres avoids a later migration/cutover event.
- **Auth**: **email + password** login, single role, no RBAC in v1 —
  passwords hashed and stored locally, no outbound SMTP dependency.
- **PDF text extraction**: `pdfplumber` (confirmed to work directly on
  the real DPR sample — it's text-based, not scanned)
- **Local LLM runtime**: Ollama, called via its local HTTP API
  (`http://localhost:11434`)
- **LLM model**: hardware is **CPU-only** (no GPU) — favor a smaller
  instruction-following model (the 7-8B end of the Qwen2.5 range, or
  similar) over a 14B model to keep the 5-minute end-to-end ingest
  budget from `07_non_functional_requirements.md`; benchmark on real
  hardware and real narratives before committing to a specific size.
- **Frontend**: a lightweight dashboard (a working single-page HTML+JS
  version already exists; a React app is a reasonable v2 upgrade if the
  UI needs to grow)
- **File storage**: original uploaded PDFs (both DPR and, once
  available, proposal/AFE) are preserved on disk as the system of
  record, separate from the parsed database rows, per
  `07_non_functional_requirements.md`.

## Deployment model

- **Topology**: single machine for the initial rollout, with a planned
  migration to a shared server later — the deployment approach below is
  chosen to make that move a non-event.
- **Service model**: runs as a **Docker container**, so it survives an
  unattended machine restart and the same container image moves to the
  future shared server regardless of its OS.
- **Backups**: required. Default approach (to be confirmed): a
  scheduled `pg_dump` job writing to a backup location.

## Non-functional constraints to carry into implementation

See `07_non_functional_requirements.md` (now filled in) for the full
detail on performance targets, data volume, retention, and backups —
notably the 5-minute end-to-end ingest budget and 5-minute dashboard
load budget, both against CPU-only hardware.

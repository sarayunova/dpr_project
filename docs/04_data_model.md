# Data Model — Drilling DPR Monitor

This describes the entities and relationships independent of any
specific ORM/language, so it can be implemented in whatever stack is
chosen. A working SQLAlchemy implementation of this model already
exists and has been tested against real data — treat this document as
the contract; implementation is free to differ mechanically (e.g.
different ORM, different DB engine) as long as the entities and
relationships below are preserved.

## Entities

### Well
One row per physical well. Identified by `well_name` (must match the
DPR's well identifier exactly, e.g. `NG-2000-4`) — this is the join key
across every daily report a well ever appears in.

| Field | Type | Notes |
|---|---|---|
| id | PK | |
| well_name | string, unique | Primary matching key |
| location_code | string | e.g. `HPAA` |
| asset_name | string | e.g. `Assam Asset + RO` |
| category | string | e.g. `ON LAND EXPLORATORY WELLS` |
| well_type | string | e.g. `DI` |
| target_depth | float | metres |

Relationships: one Well → one Proposal (optional, added once
available); one Well → many DailyEntry (one per day ingested).

### Proposal
One row per well, added once from the proposal/AFE document.

| Field | Type | Notes |
|---|---|---|
| id | PK | |
| well_id | FK → Well, unique | |
| proposed_date | date | |
| approved_date | date | |
| approving_authority | string | |
| afe_number | string | |
| gto_reference | string | |
| formation_tops | text | |
| mud_program | text | |
| casing_program | text | |
| objective | text | |
| planned_total_days | int | Cross-check against DPR's planned TOT days once both exist |
| planned_total_cost_inr | float | Cross-check against DPR's planned cost |
| raw_extracted_json | text | Full LLM extraction output, kept for audit/debugging |

### DailyEntry
One row per well, per report date — the core fact table. Unique on
(well_id, report_date); re-ingesting the same well/date replaces the
existing row rather than duplicating.

| Field | Type | Notes |
|---|---|---|
| id | PK | |
| well_id | FK → Well | |
| report_date | date | End of the report's 24h window |
| source_filename | string | For traceability |
| source_document_id | FK → SourceDocument, nullable | The stored original PDF (Phase 10); null for text-only ingestion |
| mode | string | D/R/P/O/etc. |
| present_depth | float | |
| day_meterage | float | |
| rb_start, dr_start, pt_start | date | |
| rb/dr/pt/tot_days_planned, rb/dr/pt/tot_days_actual | int | Cumulative, as of report_date |
| mud_weight, mud_viscosity | float | |
| litho | string | |
| cost_planned_inr, cost_actual_inr | float | Cumulative |
| status_text | string | |
| oper_narrative | text | Free-text daily activity description |
| ingested_at | datetime | |

Relationships: one DailyEntry → many PhaseSnapshot; one DailyEntry →
many RepairEvent.

### PhaseSnapshot
One row per casing phase, per DailyEntry (typically 3–4 rows per well
per day, matching the DPR's phase table).

| Field | Type | Notes |
|---|---|---|
| id | PK | |
| daily_entry_id | FK → DailyEntry | |
| phase_no | int | |
| casing_size | string | e.g. `13 3/8"` |
| depth_planned, depth_actual | float | |
| days_planned, days_actual | int | Primary phase-level variance figure |
| hole_top | string | Rarely populated in samples seen |

### RepairEvent
Zero or more per DailyEntry — LLM-flagged repair/troubleshooting
mentions in that day's OPER narrative. **Occurrence-level, not
duration-based** — the source report has no hours field (see
`02_data_dictionary.md` §A.5).

| Field | Type | Notes |
|---|---|---|
| id | PK | |
| daily_entry_id | FK → DailyEntry | |
| equipment_or_system | string | e.g. `DW drum encoder` |
| snippet | text | Exact triggering phrase from the narrative |
| confidence | string | low / medium / high, LLM self-assessed |
| reviewed | boolean | Human has confirmed/dismissed |

### SourceDocument (Phase 10)
One row per distinct uploaded PDF — the original file is the system of
record (`07_non_functional_requirements.md`) and lives on disk at
`UPLOAD_DIR/<sha256[:2]>/<sha256>.pdf`; this row indexes it. Never
deleted or overwritten by the app.

| Field | Type | Notes |
|---|---|---|
| id | PK | |
| original_filename | string | Name at first upload |
| sha256 | string(64), unique | Content hash — identical re-uploads reuse the row |
| stored_path | string | Relative to `UPLOAD_DIR`, so the directory can move |
| size_bytes | int | |
| uploaded_at | datetime | |

### User (Phase 10)
Email + password login, single role, no RBAC.

| Field | Type | Notes |
|---|---|---|
| id | PK | |
| email | string, unique | Stored lowercased |
| password_hash | string | scrypt, salted, parameters stored in the hash |
| is_active | boolean | Deactivate instead of delete |
| created_at | datetime | |

### UserSession (Phase 10)

| Field | Type | Notes |
|---|---|---|
| id | PK | |
| token_hash | string(64), unique | SHA-256 of the cookie token — the raw token is never stored |
| user_id | FK → User | |
| created_at, expires_at | datetime | |

## Entity-relationship summary

```
Well 1───1 Proposal
Well 1───N DailyEntry
DailyEntry 1───N PhaseSnapshot
DailyEntry 1───N RepairEvent
SourceDocument 1───N DailyEntry   (one PDF covers many wells)
User 1───N UserSession
```

## Design decisions worth preserving

1. **Deterministic fields never go through the LLM.** Everything in
   DailyEntry/PhaseSnapshot comes from regex/tokenization of the DPR
   text, not LLM extraction — it's reproducible and doesn't need
   re-verification once the parser is tested. Only `RepairEvent`
   extraction and (pending) `Proposal` extraction use the LLM, because
   those genuinely require judgement or handle less regular documents.
2. **Baseline lives in two places, both worth keeping**: the DPR's own
   "Planned" columns (which may drift/get re-baselined over time as
   operations proceed) and the Proposal's original approved figures
   (fixed at approval time). Don't collapse these into one field —
   comparing "current plan" vs. "originally approved plan" vs. "actual"
   is a three-way comparison worth supporting, not just plan-vs-actual.
3. **Re-ingestion replaces, not appends**, per (well_id, report_date).
   Corrections to a previously-uploaded report should overwrite cleanly.

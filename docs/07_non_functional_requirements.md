# Non-Functional Requirements — Drilling DPR Monitor

These decisions materially affect the architecture (database engine,
auth, deployment model) — see `05_architecture.md` for how each answer
below was translated into a concrete stack decision.

## Data privacy / security

- "No data leaves the organization's infrastructure" **is a formal
  policy**. [ Exact policy name/number not yet cited — add the citation
  here once available. ]
- Encryption at rest for the database: **not required**.
- Audit logging of who uploaded/edited what: **not required**.
- Retention policy: **indefinite** — historical DPR data must remain
  queryable indefinitely, no automatic archiving/deletion.

## Scale / volume

- Number of assets expected to use this system: **up to 30**.
- Wells per asset: **30 maximum**.
- Expected total history: **5 years** of accumulating daily reports.
  At the ceiling (30 assets × 30 wells), this is up to ~900 wells;
  daily entries accumulate per well only while it's actively reporting,
  not for its full lifetime every day, so actual row counts will be
  well below "900 wells × 5 years × 365 days" — but the schema and
  database choice should comfortably handle that order of magnitude
  without special-case archiving.
- Upload frequency: **daily**, per asset. **Batch upload of backlogged
  historical PDFs will also happen at initial rollout**, and batch
  uploads may recur afterward (not a one-time-only event at launch) —
  the ingest pipeline and `POST /api/ingest` should treat "many files at
  once" as a normal, recurring case, not a special migration path.

## Performance

- Acceptable hardware: **CPU-only** — no GPU available. LLM model choice
  and latency expectations must be set accordingly (see
  `05_architecture.md` and `06_llm_prompts_and_eval.md` — favor a
  smaller/quantized model, e.g. the 7-8B end of the recommended range,
  and benchmark early).
- Acceptable end-to-end ingest time per DPR PDF (including the LLM
  call): **5 minutes**.
- Acceptable dashboard load time (wells list / a well's full timeline):
  **5 minutes**.

## Availability / deployment

- Topology: **single machine now**, with a **planned migration to a
  shared server** in a later rollout phase — not single-machine-only for
  the life of the project.
- Must **survive an unattended machine restart** — the app runs as a
  managed service, not something started manually each session.
- Backups: **required**. [ Exact mechanism not yet specified by the
  user; default assumption until confirmed otherwise: a scheduled
  `pg_dump` job writing to a backup location, consistent with the
  Postgres decision below. ]

## Access control

- **Authentication is required for v1** — users are identified by
  **email**, via **email + password** login (standard form, passwords
  hashed and stored locally; no outbound SMTP dependency).
- **No multiple roles** — a single role for all authenticated users, no
  RBAC needed for v1. (This narrows the PRD §4 draft split between
  "drilling engineer" and "asset manager" to a v2-or-never item; v1
  does not need to enforce different permissions per user.)

## Compliance / regulatory

- No oil & gas industry-specific regulatory requirements touching data
  handling, retention, or reporting format.
- Original source PDFs **must be preserved** as a system of record,
  separate from the extracted database rows (e.g. store the uploaded
  file itself, not just its parsed content).

## Resulting architecture decisions

Derived directly from the answers above (see `05_architecture.md` for
the full stack write-up):

- **Database: PostgreSQL from the start** (not SQLite) — chosen given
  the confirmed future shared-server rollout, the ~900-well/5-year
  scale ceiling, and the auth requirement, to avoid a later
  migration/cutover event.
- **Auth: email + password**, single role, no RBAC.
- **Deployment: Docker container**, run as a managed/restarting service
  — portable from the current single machine to the future shared
  server regardless of its OS.

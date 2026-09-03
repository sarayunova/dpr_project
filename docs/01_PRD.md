# Product Requirements Document — Drilling DPR Monitor

## 1. Problem statement

Daily Drilling Progress Reports (DPRs) are currently downloaded as PDFs
from SAP, one per asset per day, covering every well on that asset. There
is no system that automatically tracks a well's progress against its
originally approved baseline (proposal/AFE), across phases and
sub-phases, over the life of the well. Tracking today is manual /
ad hoc.

[ Add: who does this manually today, how long it takes, what mistakes or
delays result from the current process. ]

## 2. Goals

- Ingest daily DPR PDFs automatically and extract structured data using
  a **locally-installed LLM** — no well or cost data leaves the
  organization's own infrastructure. This is a hard requirement, not a
  preference. [ Confirm: is this an internal policy, a regulatory
  requirement, or both? Note it here so Claude Code treats it as
  non-negotiable rather than optimizable-away. ]
- Maintain a running record of what happened on each well, each day.
- Ingest each well's proposal/AFE file once, capturing: when it was
  proposed, when it was approved, and full well design details per GTO
  (Government Technical Order / internal well-design reference).
- Track progress phase-wise and sub-phase-wise against the approved
  baseline, so variance (days, cost) is visible at any point in a well's
  life, not just at the end.
- Record repair/troubleshooting time (see `06_llm_prompts_and_eval.md`
  for why this replaced generic "NPT categorization") and cost.
- Support multiple assets — the same instance should handle DPR uploads
  from more than one asset, not just Assam Asset + RO.

## 3. Non-goals (v1)

- Hourly-level NPT/downtime tracking (the source DPR format doesn't
  provide hours — see `02_data_dictionary.md`).
- Multi-tenant access control / SSO. [ Confirm this is acceptable for v1
  — single machine or trusted LAN only. ]
- Itemized cost breakdown by AFE line item (the DPR gives one aggregate
  cost per well, not a breakdown) — unless SAP can export this
  separately; note if it can.
- [ Add any other explicit exclusions you want Claude Code to NOT build
  by default. ]

## 4. Users / roles

[ Fill in. Starting point based on our discussion: ]

- **Drilling engineer** — uploads daily DPRs, reviews/corrects LLM
  extractions, reviews repair/troubleshooting flags.
- **Asset manager / management** — views dashboards, variance reports,
  does not upload or correct data.
- [ Add other roles, and note if role-based permissions matter for v1
  or can wait. ]

## 5. Core features (v1 scope)

1. Multi-file DPR upload (multiple assets/wells per upload).
2. Deterministic extraction of DPR fields (see data dictionary) — no
   LLM needed for this part, it's regular enough for regex/parsing.
3. LLM-based extraction of repair/troubleshooting events from the daily
   narrative text.
4. One-time proposal/AFE ingestion per well (LLM-based, since this
   document type is less structurally regular than the DPR).
5. Well timeline view: every day ingested, with narrative, phase
   snapshot, and any repair events.
6. Variance dashboard: planned vs. actual days and cost, well-level and
   phase-level.
7. Review queue for LLM-flagged repair/troubleshooting events (human
   confirms or dismisses).

## 6. Later / v2 candidates

[ Add anything raised in brainstorming that you want recorded but not
built yet — e.g. role-based auth, cost-by-line-item, hourly NPT if a
better source report becomes available, notifications/alerts on
variance thresholds, multi-user concurrent editing. ]

## 7. Success criteria

[ Fill in — e.g. "engineer can find any well's current day/cost variance
without opening SAP," "time to compile a weekly variance report drops
from X hours to Y minutes." ]

# UI Notes / Wireframes — Drilling DPR Monitor

A minimal working single-page dashboard already exists (plain HTML/JS)
covering the three screens below. Treat these descriptions as the
functional baseline; replace the rough layout notes with your own
sketches/preferences before Claude Code builds a more polished version.

## Screen 1: Upload + Wells overview

- File upload control, accepts multiple PDFs at once, one "Ingest"
  action.
- After ingest, shows a per-file result line (wells ingested, repair
  events created) or an error line if a file failed to parse.
- Table of all wells: name, location code, asset, category, latest
  report date, days (planned/actual, color-coded over/under), cost
  (planned/actual, color-coded), status text.
- Clicking a row opens Screen 2 for that well.

[ Add/replace: do you want filtering (by asset, by category, by status)
or sorting on this table? Any columns missing that matter to you? ]

## Screen 2: Well detail

- Well identity header (name, location code, asset).
- Variance summary: total days variance %, total cost variance %.
- Per-phase variance table: phase no, casing size, planned/actual
  depth, days variance %.
- Full daily timeline (most recent first or oldest first — [confirm
  preference]): one row per day ingested, with mode, depth, days P/A,
  cost P/A, and any repair/troubleshooting events for that day shown
  inline with the triggering snippet.
- Each day's OPER narrative shown in full underneath its row.

[ Add: do you want a chart (e.g. actual vs. planned depth-over-time, or
cost burn-down) here, or is the table sufficient for v1? ]

## Screen 3: Repair/troubleshooting review queue (API exists, no UI yet)

- List of all unreviewed repair events: well name, date, equipment/
  system, snippet, confidence.
- A way to confirm or dismiss each one (calls
  `POST /api/repairs/{id}/review`).

[ Add: should dismissing an event just mark it reviewed, or should
there be a "false positive" vs. "confirmed" distinction kept in the
data, so you can later measure the LLM's real precision? Recommended:
keep the distinction — it's cheap to add now and valuable for tuning
the prompt later. ]

## Not yet designed

- Proposal/AFE entry or upload screen (blocked on having a real sample
  document — see `02_data_dictionary.md` §B).
- Any cross-well/asset-level rollup view (e.g. "all wells behind
  schedule across all assets").

[ Add sketches, a Figma link, or plain descriptions for any of the
above before Claude Code builds them, so it isn't guessing at layout. ]

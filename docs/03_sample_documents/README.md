# Sample documents

DPR samples — all four cover the same source format (SAP export, ONGC
"DRILLING PROGRESS REPORT" layout) but differ in asset, well mix, and
which edge cases they exercise. Each `.txt` is the plain pdfplumber-style
text extraction of its matching `.pdf`, kept side by side so PDF-to-text
extraction itself can also be tested, not just parsing of already-extracted
text.

- `sample_dpr.txt` / `sample_dpr.pdf` — "Assam Asset + RO",
  **01.04.2026–02.04.2026**, 4 wells (`NG-2000-4`, `NG-2000-6`,
  `ARMCUE-1`, `E-1400-13`). The original sample used to build and
  validate the parsing logic in `02_data_dictionary.md` §A. Demonstrates
  the mid-block page-break banner hazard on `E-1400-13`. **No original
  PDF was ever supplied for this one** — `sample_dpr.pdf` is a
  synthesized reconstruction (monospace text laid out line-for-line via
  `fpdf2`, built for Phase 3's exit criteria which needs an actual PDF to
  ingest), not a real ONGC export. Confirmed to round-trip through
  `pdfplumber` back to text the parser handles identically to
  `sample_dpr.txt` — but treat the three real PDFs below as the more
  faithful test of actual PDF-extraction quirks.

- `sample_dpr_assam_ro_day2.txt` / `sample_dpr_assam_ro_day2.pdf` —
  **same asset** ("Assam Asset + RO"), **the very next day**
  (02.04.2026–03.04.2026), full 5-page / 13-well report (2 under `ON LAND
  EXPLORATORY WELLS` + 11 under `ON LAND DEVELOPMENT WELLS` — sequence
  numbers reset per category, so the highest sequence number seen,
  `11.NG-1500-6`, is not the well count). Includes the
  four wells from `sample_dpr.txt` one day later plus 7 more wells not
  seen before. **This is the second day's report needed to test
  multi-day timeline accumulation** — see the acceptance criteria
  addition below. Also demonstrates the same mid-block banner hazard
  (`E-1400-13` again) and shows several fields populated for the first
  time: `Obj No/Name` / `Obj days` / `Obj interval`, and `NL-1` holding
  an actual location code (e.g. `RSFB`, `LPEZ`, `CMAJ`) instead of always
  being `LOC-NOT AVBL.`.

- `sample_dpr_assam_arakan.txt` / `sample_dpr_assam_arakan.pdf` — a
  **different asset**, "Assam & Assam Arakan Basin, Jorhat"
  (02.04.2026–03.04.2026), 3 wells. Same overall DPR format, but
  introduces a well entry (`0.E-760-10`, sequence number **0**, not 1)
  for a rig that has been released/is in transit between wells: `MODE:O`,
  every date/depth/day/cost field blank, no phase table rows at all (the
  phase table header line has no rows under it), and a narrative
  describing rig transfer/dismantling rather than well progress. This is
  a fifth "mode" value beyond the D/R/P inferred so far, and the first
  observed case of a well block with zero phase rows.

- `sample_dpr_tripura.txt` / `sample_dpr_tripura.pdf` — a **third,
  unrelated asset**, "Tripura Asset" (14.04.2026–15.04.2026), 6 wells.
  Introduces a third well-category section, `WORKOVER WELLS` (alongside
  the existing `ON LAND EXPLORATORY WELLS` / `ON LAND DEVELOPMENT WELLS`),
  a well `Type` value other than `DI` (`VE`), a `MODE:W` (workover), a
  casing size with no fraction (`7"`, vs. the fractional `9 5/8"` /
  `13 3/8"` / `5 1/2"` seen elsewhere), a phase-table row whose leading
  phase number is missing entirely (well `2.NG-2000-3`, phase 1 row —
  parser must not assume the first token is always a phase number), and
  the **first populated "WELLS COMPLETED" footer** (`ONLAND DEV :
  1.ROKDB(12.04.26),`), which the existing samples only show empty. Also
  shows the one irregular field-wrap seen so far: well `1.E-1400-M2`'s
  `WO P/A` value wraps onto its own line (`WO\nP/A:45/40/`) instead of
  staying inline like every other well's `WO P/A://`.

Still needed:

- **[Action needed] A real proposal/AFE PDF.** Still not analyzed — see
  the open item in `02_data_dictionary.md` Section B. None of the four
  DPR samples above are a substitute for this; Phase 8
  (`11_implementation_phases.md`) remains blocked until one is supplied.

Tell Claude Code to read every file in this folder before writing or
extending any parsing code.

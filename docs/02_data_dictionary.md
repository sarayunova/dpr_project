# Data Dictionary — Source Documents

## A. Daily Progress Report (DPR) PDF

Source: SAP export, one PDF per asset per day. Covers every well on that
asset in a single file. Verified against four real ONGC DPR samples (see
`03_sample_documents/README.md` for the full list): "Assam Asset + RO"
(01.04.2026–02.04.2026, 4 wells, and 02.04.2026–03.04.2026, the full
13-well/5-page report — the same asset two consecutive days apart), "Assam
& Assam Arakan Basin, Jorhat" (02.04.2026–03.04.2026, 3 wells), and
"Tripura Asset" (14.04.2026–15.04.2026, 6 wells). All four share the same
overall layout — everything below applies across assets — but each
exercises different edge cases, called out inline.

### A.1 Report-level fields (appear once per PDF)

| Field | Example | Notes |
|---|---|---|
| Company / asset name | `Assam Asset + RO` | From `COMPANY :` line, repeated on every page |
| Report period | `06:00 Hrs of 01.04.2026 to 06:00 Hrs of 02.04.2026` | Defines the "as of" date for every well entry in this file — use the *end* of the window as `report_date` |
| Well category headers | `ON LAND EXPLORATORY WELLS`, `ON LAND DEVELOPMENT WELLS`, `WORKOVER WELLS` | Wells are grouped under these; category is a per-well attribute. `WORKOVER WELLS` confirmed as a third category value in the Tripura sample — don't assume only the original two exist. |
| MOU plan footer | `MOU PLAN: MONTH MTR:5,235 QTR MTR:21,965 YEAR MTR:106,162` / `ACTUAL DAY MTR:149 MONTH MTR:149 QTR MTR:149 YEAR MTR:149` | Asset-level (not well-level) meterage plan vs actual. Not currently ingested by the prototype — candidate for v2 if asset-level meterage tracking is wanted. |
| Wells-completed footer | `-----------WELLS COMPLETED ----------------` followed by, per category, a line like `ONLAND DEV :` then `1.ROKDB(12.04.26),` | Lists wells that finished (moved off the active list) during the report period, grouped by category, with a completion date in parentheses. Empty in the original samples (just the header line, no names) but populated in the Tripura sample — confirms this section can have real content and its per-category/per-well structure. Not currently ingested — candidate for detecting well completion events, complementary to but distinct from a well simply stopping to appear in subsequent reports. |

### A.2 Per-well header fields (one block per well)

| Field | Example raw text | Parsed meaning |
|---|---|---|
| Sequence no. + well name | `1.NG-2000-4` | Well identifier — used as the primary key for matching a well across days |
| Location code | `HPAA` | Short site/location code |
| Type | `Type: DI/` | Well type code — `DI` seen for exploratory/development wells, `VE` seen for a workover well in the Tripura sample. **Confirm the full type taxonomy with your drilling team** — only two values observed so far. |
| Mode | `MODE:D /` | Current activity mode. Five values now observed: **D**=Drilling, **R**=Reaming/Rig-move(?), **P**=Production testing(?), **O**=Other — confirmed in the Assam & Assam Arakan sample on a well (`0.E-760-10`) whose rig had been released and was in transit to another basin, so likely means "inactive/rig not currently on this well" rather than "old" — and **W**=Workover, confirmed on the Tripura sample's `WORKOVER WELLS` entry. **Still confirm the full mode code list with your ops team** — inferred from samples, not officially documented here. |
| WD | `/WD:` | Water depth — blank for onland wells; relevant for offshore assets if this system is extended there |
| Target depth | `T.Depth:4,394` | Planned total depth, metres |
| Present depth | `Pr.Depth:3,612` | Actual depth reached as of report date |
| Day meterage | `Day Mtr:` | Metres drilled in the last 24h (often blank if not drilling that day) |
| RB Start | `RB Start: 09.09.2025` | Rig-building start date |
| DR Start | `DR.Start:15.12.2025` | Drilling start date |
| PT Start | `PT.Start:` | Production-testing start date (blank if not yet reached) |
| WO Start | `WO.Start:` | Workover start date, if applicable. In every well seen across all four samples (15 wells), this value is blank and the label is immediately followed by `CRep/OutCyl:` with no date in between — see next row. |
| CRep/OutCyl (Planned/Actual) | `WO.Start:CRep/OutCyl:29/29` | A Planned/Actual numeric pair attached directly to the `WO.Start:` label with no separator, e.g. `CRep/OutCyl:/13` (planned blank, actual 13) or `CRep/OutCyl:29/29`. **Not documented in the original analysis** — missed because it was always blank (`CRep/OutCyl:/`) in the single original well sample. Meaning unconfirmed (possibly "Cycles Repair / Out-of-Cycle" — a rig-cycle count?); **confirm with your ops team**. Not part of the current `DailyEntry` entity in `04_data_model.md` — parse it for completeness/traceability, but it doesn't need to be persisted until confirmed useful. |
| Days RB P/A | `Days RB.P/A:25/47` | Rig-building days, Planned/Actual (cumulative) |
| DR P/A | `DR.P/A:145/108` | Drilling days, Planned/Actual |
| PT P/A | `PT.P/A:20/` | Production-testing days, Planned/Actual |
| TOT P/A | `TOT.P/A:190/155` | Total days, Planned/Actual — **this is the primary day-variance figure** |
| WO P/A | `WO P/A://` | Workover days, Planned/Actual |
| LA no / A.Kick | `LA no/A.Kick:/` | Location approval number / kick indicator — usually blank in samples seen; confirm meaning and whether it's ever populated |
| Mud weight / viscosity | `Mw wt/visc:11.20/046` | Current mud properties |
| Lot | `Lot:3,616/11.35` | Leak-off test depth / value pair (confirm exact definition with mud engineer) |
| Litho | `Litho:CLAYSTONE AND SANDSTONE` | Lithology encountered, free text |
| Obj No/Name, Obj days, Obj interval | blank in most samples; populated e.g. `Obj No/Name:1 /Obj-1 Obj days:15 Obj interval:2585- 2588` | Production-testing objective details — populated when PT phase is active. Now confirmed from real data (Assam+RO day 2 and Tripura samples): `Obj interval` is two depths separated by `- ` (dash then space, no space before the dash) — a distinct pattern from the Depth (P/A) phase-table columns' `/`-separated pair, so don't reuse the same split logic for both. |
| Cost (Planned/Actual) | `Cost in INR(Planned/Actual):886,323,863.00 /960,346,238.00` | **Primary cost-variance figure**, cumulative INR. Either side may be blank (e.g. planned cost blank until AFE finalized) |
| NL-1 / Status / Cluster | `NL-1: LOC-NOT AVBL. Status: LOC#NA (NOT AVAILABLE) Cluster: N` | Location/rig status text and cluster flag. `NL-1` is not always the literal string `LOC-NOT AVBL.` as the original sample suggested — the Assam+RO day-2 and Tripura samples show it holding real location codes (`RSFB`, `LPEZ`, `CMAJ`, `LPES`, `CHDW`, `KHDD_AGT`, `KUDH`, `SNAA_AGT`, `ADEN`, `ROKAC`) and even a parenthetical note (`PT (PT ACT)`). Treat it as free text, not a fixed sentinel value. `Status` similarly takes several values beyond `LOC#NA (NOT AVAILABLE)`: `CIVIL WORK IN PROGRESS`, `LOCATION RFD (READY FOR DRILLING)`, `LAQ IN PROGRESS`, `LAQ COMPLETED` — treat as free text, not an enum, unless a fixed list is confirmed with ops. |
| OPER narrative | `OPER:RECTIFIED OIL LEAKAGE FROM DW. CLEARED CMT...` | Free-text description of the day's activity — **only source of repair/troubleshooting signal**; see `06_llm_prompts_and_eval.md` |

### A.3 Phase table (repeats per well, 3–4 rows typically = one per casing string)

| Column | Example | Notes |
|---|---|---|
| Phase no | `1`, `2`, `3`, `4` | Sequential phase number, corresponds to a casing string. **Can be missing from the row entirely** — the Tripura sample's `2.NG-2000-3` well has a phase-1 row with no leading number token at all (`   20" 390/377 9/12` vs. the normal `2 13 3/8" 2,000/1,947 29/24`). Don't assume the first token on a phase row is always a phase number; a row may need to be inferred as "phase 1" by its position within the block instead. Some wells also have **zero phase rows** at all — the Assam & Assam Arakan sample's `0.E-760-10` (a rig in transit, `MODE:O`) has the `Phase no / Csg Size / ...` header line immediately followed by the `OPER:` narrative, with no data rows in between. |
| Casing size | `20"`, `13 3/8"`, `9 5/8"`, `5 1/2"`, `7"` | **Parsing hazard**: a fractional size like `13 3/8"` contains a `/` and looks like a Planned/Actual pair — must be disambiguated from the true P/A columns (see parsing note below). Casing sizes are **not always fractional** — the Tripura sample shows a plain `7"` (no `/` at all) as a valid casing size too, so the parser can't assume every casing-size token needs fraction-disambiguation logic to begin with. |
| Depth (P/A) | `2,400/2,404` | Planned/actual depth for this phase, metres |
| Days (P/A) | `34/53` | Planned/actual days for this phase — **primary phase-level variance figure** |
| H.top | usually blank in samples | Hole-top depth — rarely populated in samples seen; confirm when this field is used |

**Parsing note (important for whoever implements/extends this):** a
casing-size token like `3/8"` contains a slash and superficially looks
like a Planned/Actual pair. A working parser disambiguates by requiring
true P/A tokens to match `^[\d,]*/[\d,]*$` (digits/commas only) — the
casing fraction fails this because of the trailing `"` — see the
existing `parser.py` for the tested implementation.

### A.4 Known structural hazards in the raw PDF text

- **Multi-page well blocks.** A well's entry can be split across a page
  break, with SAP re-printing the full page banner (company name, report
  title, date range, separator line) in the middle of the block. Any
  parser must strip these repeated banners without treating the
  separator line that follows them as an end-of-block marker.
- **Two different separator line lengths.** A short separator
  (~30 underscores) appears *inside* a well block, between the header
  fields and the phase table. A long separator (~90 underscores) marks
  the *actual* end of a well block. Treating both the same way breaks
  parsing.
- **Blank fields are common**, not exceptional — e.g. planned cost blank
  until AFE finalized, PT Start blank until that phase begins, Day Mtr
  blank on non-drilling days. Don't assume required-ness.
- **A field's value can wrap onto its own line.** The Tripura sample's
  workover well `1.E-1400-M2` has its `WO P/A` value wrap past the line
  break: `...TOT.P/A:20/157 WO\nP/A:45/40/` (the label `WO` ends one
  line, `P/A:45/40/` starts the next) instead of staying inline like
  every other well's `WO P/A://`. A parser that assumes `WO P/A:<val>`
  always appears as one contiguous token will silently drop this value or
  misparse the following line — join wrapped lines before field-splitting,
  or match across the wrap explicitly.
- **The page banner's position in the extracted text stream is not
  reliably "top of page."** In the existing `sample_dpr.txt` the banner
  for page 1 appears first, as expected. In the Assam & Assam Arakan
  sample (a single-page PDF), the plain-text extraction places that same
  page's banner **after** all of the page's well content, immediately
  before the following page's would-be content (which doesn't exist here,
  since the PDF only had one page) — i.e. the banner reads like it
  belongs to a page that never comes. This is consistent with the
  already-documented mid-block banner behavior (A.4, first bullet) but
  confirms banners should be located by matching their content pattern
  (`OIL AND NATURAL GAS CORPORATION LTD.` / `COMPANY :` / `DRILLING
  PROGRESS REPORT` / date-range line), never by assuming a fixed position
  such as "first N lines of the file" or "immediately after a page
  break."
- **pdfplumber's default word-spacing tolerance can merge adjacent words
  in the banner with no inserted space.** Found in Phase 9 against the
  real `sample_dpr_assam_ro_day2.pdf` (not the hand-transcribed `.txt` —
  this is a PDF-extraction-layer issue, invisible to any test using
  already-extracted text): `page.extract_text()`'s default
  `x_tolerance=3` produced `COMPANY :AssamAsset+ RO` instead of
  `COMPANY : Assam Asset + RO`, which both broke the banner regex *and*
  would have corrupted `asset_name` even if it hadn't. Fixed by calling
  `extract_text(x_tolerance=2)` in `app/ingest.py`'s
  `extract_text_from_pdf` — verified against all four sample PDFs with
  no regressions. Only the banner line was affected in the samples
  checked (well-data lines extracted correctly at the default
  tolerance), but this is worth re-checking if a future asset's PDF
  shows the same symptom elsewhere.

### A.5 What this document does NOT contain

- No explicit NPT/downtime **hours** field — only inferable qualitatively
  from the OPER narrative (see repair/troubleshooting approach).
- No cost breakdown by AFE line item — one aggregate cost figure per
  well only.
- No personnel, equipment-on-site, or hourly operations log.

**Multi-asset check (2026-09-03): done for onland assets.** Three
additional real samples now confirm "Assam Asset + RO" (a second day),
"Assam & Assam Arakan Basin, Jorhat", and "Tripura Asset" all share this
same overall DPR layout — see `03_sample_documents/README.md` for the
full list and what each one exercises. No offshore or differently
SAP-configured sample has been supplied yet; if one surfaces, add it and
a corresponding note here the same way, before assuming the parser
generalizes to it too.

---

## B. Proposal / AFE / GTO document

**Status: not yet analyzed against a real sample.** Everything below is
a *target* field list based on stated requirements, not verified
extraction logic. Provide a real (redacted if necessary) sample before
implementation, and update this section the same way Section A was
built — from an actual document, not assumption.

| Target field | Notes |
|---|---|
| Well name | Must match the DPR's well-name key exactly for joining |
| Proposed date | Date the well/plan was proposed |
| Approved date | Date of approval |
| Approving authority | Who/what body approved it |
| AFE number | Authority for Expenditure reference number |
| GTO reference | Government Technical Order reference — [confirm exact document/field name with your team] |
| Well design details per GTO | [Specify: formation tops, casing program, mud program, directional plan, target reservoir — whatever GTO actually enumerates] |
| Planned total days | Baseline day count — cross-check against DPR's "Planned" days for consistency once both sources exist |
| Planned total cost (INR) | Baseline AFE cost — cross-check against DPR's "Planned" cost |
| Planned phase/sub-phase breakdown | If the proposal breaks planned days/cost down by phase (it may be more granular than the DPR's 3-4 casing phases) |

[ **Action needed**: upload a real sample proposal/AFE PDF; Claude Code
should re-run the same real-document analysis process used for the DPR
before writing any extraction code for this document type. ]

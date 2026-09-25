# LLM Prompts & Evaluation — Drilling DPR Monitor

## Why the LLM's job is narrow and specific

Early design considered a broad "NPT (non-productive time) categorization"
task (mechanical / weather / waiting-on-materials / etc.). This was
dropped in favor of a narrower, more reliable ask: **is this narrative
describing repairing or troubleshooting equipment, as opposed to
forward well-progressing work?** This is both more useful (it's the
actual thing worth tracking against cost/schedule) and more reliable
for a local LLM to judge consistently, since the source report gives no
formal NPT taxonomy to classify against — asking the model to invent
categories from thin air produces less consistent results than asking
it to detect one well-defined pattern.

**General principle for extending this system**: give the LLM narrow,
well-defined judgement tasks (classification, flagging) rather than
broad interpretive ones, and keep everything that's actually regular
and rule-based (dates, numbers, table structure) out of the LLM
entirely — see the deterministic parser in `04_data_model.md`.

## Prompt 1: Repair/troubleshooting event extraction

**Input**: one day's OPER narrative text for one well.
**Output**: JSON array, one object per detected event.

```
SYSTEM PROMPT:

You are reviewing a daily drilling operations narrative (OPER text)
from an oil & gas drilling progress report. Identify any part of the
text that describes REPAIRING or TROUBLESHOOTING equipment, tools, or
instrumentation -- time spent fixing, diagnosing, or rectifying a fault
-- as opposed to forward well-progressing work (drilling, tripping
pipe, running/cementing casing, logging, testing as planned).

Only flag genuine repair/troubleshooting language (e.g. "rectified
leakage", "changed faulty gauge", "encoder fault ... replaced",
"arrested leakage from riser"). Do NOT flag routine planned
maintenance-adjacent activity described without a fault (e.g. "greased
elevator" alone, scheduled preventive maintenance with no problem
stated) unless it's clearly reactive to a problem in the same sentence.

Return ONLY a JSON array (no other text, no markdown fences). Each item:
{"equipment_or_system": "<short name of what was being repaired/troubleshot, e.g. 'DW drum encoder'>",
 "snippet": "<the exact phrase from the text describing the repair/troubleshooting>",
 "confidence": "<low|medium|high>"}

If there is no repair/troubleshooting language, return an empty array: []
```

Called with `temperature: 0.0` and Ollama's `format: json` mode to
minimize output variance.

### Evaluation set (starter — expand with real narratives before trusting this in production)

Build a spreadsheet/JSON file with columns: `narrative_text`,
`expected_should_flag` (yes/no), `expected_equipment` (if yes),
`notes`. Below are examples drawn from the real sample already
analyzed — use these as the first rows, then add 15-20 more pulled from
your own historical DPRs, covering:

- Clear repair language (should flag)
- Routine planned maintenance with no fault (should NOT flag)
- Ambiguous cases (e.g. preventive maintenance mentioned alongside an
  actual fault in the same sentence) — decide the correct answer
  explicitly and record why, since these are exactly where model
  behavior drifts

| Narrative (excerpt) | Should flag? | Expected equipment | Notes |
|---|---|---|---|
| "RECTIFIED OIL LEAKAGE FROM DW. CLEARED CMT... C/O PREVENTIVE MAINTENANCE OF CATWALK. GREASED TDS ELEVATOR." | Yes (for the leakage part only) | DW (drawworks) | Preventive maintenance mentioned in the *same* narrative should NOT itself be flagged — tests whether the model correctly separates the two |
| "ENCOUNTERED DW DRUM ENCODER FAULT. DW O/O/O. ENCODER#2 REPLACED BY FMP(E). TESTED, OK." | Yes | DW drum encoder | Clear fault + replacement |
| "TDS RIGHT BLOWER MOTOR RE-WINDING AT BASE IIP." | Yes (medium confidence) | TDS blower motor | Rewinding implies prior fault, but phrasing is terser — good test of confidence calibration |
| "M/A FOR RIG DRAGGING TO NEW POINT. FITTED DRAGGING PULLEYS. C/OUT TUBULAR SHIFTING & TRANSPORTATION." | No | — | Routine rig-move activity, no fault language |
| "OBSD PCT GOT STUCK DURING OPERATION AT MOUSE HOLE, RECTIFIED SAME." | Yes | PCT (power catwalk tool?) | Confirm equipment abbreviation with ops team before relying on the model's expansion of acronyms |

**Verification note (2026-09-03)**: checked each row above against the
real text now in `03_sample_documents/`. Rows 1 and 4 match real
narratives exactly (well `NG-2000-4` and `E-1400-13` in `sample_dpr.txt`
respectively, both unattributed in the table above). **Rows 2 and 5 do
not appear anywhere in any of the four real samples** — despite this
table's heading, they were not drawn from text that's actually in this
repo (possibly illustrative, or from source material outside
`03_sample_documents/`). One related bug this surfaced: elsewhere,
`10_acceptance_criteria.md` had attributed row 2's exact wording to
`NG-2000-6` — that well's real narrative is entirely different (see the
correction noted there). Row 2's *concept* (encoder fault + replacement)
does have a real counterpart — see row 6 below, which cites the actual
matching text. Row 5 remains unverified against real data; keep it, but
don't treat it as confirmed until a real PCT-stuck narrative turns up.

**The 15 rows below (2026-09-03) are a draft expansion pulled from the
real narratives across all four DPR samples now in
`03_sample_documents/`** (the three added after the original 5-row table
was written — see that folder's `README.md`). Every `should_flag` /
`expected_equipment` judgment here is **Claude Code's read of the text,
not a human/ops-team confirmation** — per `11_implementation_phases.md`
Phase 4, expanding this set is manual/human work; treat this as a
starting draft to correct, not a validated ground truth. In particular:
confirm the "hole hang-up ≠ equipment fault" distinction (rows 6-7) and
the "TDS" acronym (rows 3, 15) with your ops team, and revisit row 14
once real outcomes for that kind of narrative exist.

| # | Narrative (excerpt) | Should flag? | Expected equipment | Notes / source |
|---|---|---|---|---|
| 6 | "REPLACED B/OFF TONG DAMAGED JERK LINE WITH NEW ONE. REPLACED D/WORKSENCODER BY FMP(E), TESTED OK." | Yes | tong jerk line; drawworks encoder | Two distinct repairs in one narrative — tests multi-event detection. `sample_dpr_assam_ro_day2.txt`, well EV-2000-4 |
| 7 | "RE-WINDING OF TDS RIGHT BLOWER MOTOR AT BASE. RECEIVED TDS BLOWER MOTOR @ 19:30 HRS. FITTED SAME. TESTED TDS MOTOR BLOWER, CHECKED ALL FUNCTIONS FOUND OK." | Yes (high confidence) | TDS blower motor | A more complete repair-cycle than row 3 (received/fitted/tested) — same equipment class, different asset/day; use to check the model doesn't under-weight confidence just because the fault itself isn't restated. `sample_dpr_assam_ro_day2.txt`, well EV-2000-5 |
| 8 | "ARRESTED LEAKAGE OF TDS." | Yes (high confidence) | TDS (top drive system) | Near-exact match to the system prompt's own worked example ("arrested leakage from riser") — should be an easy case; if the model misses this, something is wrong with the prompt/wiring, not just calibration. `sample_dpr_tripura.txt`, well NG-2000-2 |
| 9 | "FUNCTION TESTED BOP, FOUND OK." (full context: BOP joints tightened as part of routine rig-up, then function-tested) | No | — | Routine test that *passes* — no fault stated. `sample_dpr_assam_ro_day2.txt`, well E-3000-1 |
| 10 | "CONTD SURFACE CIRC FOR CLEARING DEBRIS...TESTED MWD TOOL, OK." | No | — | Same "tested, OK" pattern as row 9, different equipment (MWD tool) — reinforces that a passing test is never a flag regardless of what's being tested. `sample_dpr_assam_ro_day2.txt`, well M-6100-1 |
| 11 | "TESTED MWD TOOL WITH BOTH PUMP, F/OK." | No | — | Third instance of the same pattern, different asset — checks the model generalizes past specific equipment nouns. `sample_dpr_assam_arakan.txt`, well E-760-9U |
| 12 | "TESTED PCE @ 8000 PSI F/OK...TESTED W/H @ 3600 PSI, OK" | No | — | Multiple pressure tests in sequence, all passing. `sample_dpr_tripura.txt`, well E-1400-M2 |
| 13 | "LOADED & DESPATCHED 04 TRAILERS FROM BREI TO KHEK. REMOVED REMAINING DRESSER COUPLING. R/DN IRD..." | No | — | Routine rig-move/dismantling — same category as the original row 4 but a different asset, to check the model isn't keying off asset-specific phrasing. `sample_dpr_assam_arakan.txt`, well E-1400-24 |
| 14 | "CONT. RIG DISMANTLING. L/DN DOGHOUSE AND ITS UNDER STRUCTURE. DISMANTLED IRD UNDERSTRUCTURE..." | No | — | Second rig-dismantling reinforcement, third asset. `sample_dpr_tripura.txt`, well E-1400-14 |
| 15 | "OBSD H/UP. CLEARED WITH PUMPS." (repeated 3x in the same narrative, at different depths) | No | — | **Ambiguous — explicit reasoning**: "H/UP" (hang-up) is drillstring resistance while tripping in/out of the hole, a normal drilling hazard cleared by standard procedure (pumping) — not an equipment fault. Do not let the model conflate "cleared a problem" in general with "repaired/troubleshot equipment" specifically. `sample_dpr_assam_ro_day2.txt`, well NG-2000-6 |
| 16 | "OBSD H/UP @ 1374-1378M, 1530-1534M,...CLEARED BY RECIPROCATION MULTIPLE TIMES." | No | — | Same hang-up-is-not-equipment-fault case as row 15, different clearing method (reciprocation vs. pumping) and different well — two examples guard against the model latching onto one specific verb. `sample_dpr_assam_ro_day2.txt`, well NG-1500-6 |
| 17 | "TUBING GETTING STUCK IN THE TBG SPINNER FREQUENTLY. JOINTS WERE TOO TIGHT." | No (borderline) | — | **Ambiguous — explicit reasoning**: describes an operational problem but states no diagnostic or corrective action ("rectified", "adjusted", "replaced") — the system prompt asks for *time spent fixing*, not problem-mentions alone. Flagged here as the boundary case most likely to cause disagreement; revisit if real outcomes later show this kind of narrative should count. `sample_dpr_tripura.txt`, well NG-2000-3 |
| 18 | "N/DN PBOP, N/UP XMAS TREE, TESTED @6000PSI, OK...WAITING FOR DAYLIGHT FOR STIM PERF. JOB IIP." | No | — | Routine completion-ops sequence, nothing reactive. `sample_dpr_tripura.txt`, well E-1400-M1 |
| 19 | "WKO THRU TUBING TO FLARE TIP VIA 8MM BEAN...SUBDUE WELL WITH 12.5 PPG MUD. CCM 01 CYCLE. WUO. OBSD MINOR FLUID RETURNS; CONTINUING CCM IIP." | No | — | Routine well-kill/workover circulation — "minor fluid returns" is monitored, not a stated fault being fixed. `sample_dpr_tripura.txt`, well NG-2000-1 |
| 20 | "D/DN FROM 3337M TO 3340M.M/A FOR PIT...P/O (55) STDS 5” DP UPTO 1757M...POOH. B/OFF & L/DN 8.5” TCR BIT. MA FOR CBL-VDL LOGGING, R/UP LOGGING TOOLS...IIP." | No | — | Routine logging prep, no fault language — from a well already central to the Phase 1/3 acceptance criteria, whose narrative hadn't been used in this eval set yet. **Source correction (2026-09-04)**: originally mislabeled as `sample_dpr.txt`; this is actually `ARMCUE-1`'s narrative from **`sample_dpr_assam_ro_day2.txt`** (day 2, not day 1) — found while cross-checking a live production-model run against row 21 below, whose flag surfaced the mix-up. |
| 21 | "R/I (30) SGLS 5” DP TILL 1929M. RECTIFIED PR GAUGE PROBLEM BY INSTRUMENTATION CREW. CHANGED ANALOG PR GAUGE ON H-MANIFOLD. PR TESTED SURFACE LINES. C/O GEL BREAK. RIH UPTO BTTM. CCM. CLEARED CMT. D/DN F/F UPTO 3337M. FURTHER C&C PRIOR TO PIT IIP." | Yes (high confidence) | PR (pressure) gauge | `ARMCUE-1`'s *actual* `sample_dpr.txt` (day 1) narrative — clear fault ("RECTIFIED...PROBLEM") plus a stated corrective action ("CHANGED ANALOG PR GAUGE"). Confirmed live: `qwen2.5:7b-instruct` correctly flagged this with `equipment_or_system: "PR gauge"`, `confidence: "high"` during Phase 6 browser testing. |

This brings the set to 21 rows (5 original + 16 draft above), clearing
the "at least 15-20" bar — but the count clearing the bar doesn't by
itself mean the *judgments* are validated; see the caveat above the
table. `eval/repair_extraction_eval.json` carries the 18 of these 21
rows that map to real, verified sample text (excluding rows 2 and 5),
for use with `scripts/run_repair_eval.py`.

### Acceptance threshold

[ **Fill in**: what false-positive/false-negative rate is acceptable
before this goes into production without mandatory human review of
every flag? Given there's no ground-truth hours to check against, err
toward treating every LLM flag as "needs human confirmation" indefinitely
unless/until a much larger evaluation set says otherwise. ]

**First real run (2026-09-03, Phase 4)** — `scripts/run_repair_eval.py`
against the 17 machine-verifiable rows in
`eval/repair_extraction_eval.json` (rows 1, 4, 6-20 from the tables
above — rows 2 and 5 are excluded since they don't correspond to real
sample text, per the verification note above):

| Model | Rows | TP | FP | TN | FN | Precision | Recall | Accuracy | Avg time/narrative |
|---|---|---|---|---|---|---|---|---|---|
| `qwen2.5:1.5b-instruct` | 17 | 3 | 0 | 13 | 1 | 1.00 | 0.75 | 0.94 | ~4.2s |

Notable: **zero false positives**, including on all three deliberately
ambiguous rows (15, 16, 17 — the hole-hang-up and stuck-tubing borderline
cases) — the model correctly did not flag any of them, matching the
judgment recorded in this doc. The one miss (row 7, EV-2000-5's blower
motor rewinding) is the same narrative the original 5-row table's row 3
flagged as "terser phrasing, good test of confidence calibration" — this
result is consistent with that expectation, not a surprise.

This also caught a real bug worth knowing about regardless of model
size: smaller models sometimes return a bare JSON object instead of the
requested array (`{}` for no events, or a single event unwrapped) —
`app/llm_client.py` now recovers both cases rather than silently
discarding a real event.

**Second real run (2026-09-04, Phase 6)** — the production-recommended
model finished pulling during Phase 6's browser testing, on the
corrected 18-row set (the run above also surfaced a real eval-set bug:
row 20 had been mislabeled as `sample_dpr.txt` when its text is actually
`sample_dpr_assam_ro_day2.txt`'s ARMCUE-1 narrative — fixed, and
`sample_dpr.txt`'s own ARMCUE-1 narrative, a genuine repair case, added
as row 21):

| Model | Rows | TP | FP | TN | FN | Precision | Recall | Accuracy | Avg time/narrative |
|---|---|---|---|---|---|---|---|---|---|
| `qwen2.5:1.5b-instruct` | 17 | 3 | 0 | 13 | 1 | 1.00 | 0.75 | 0.94 | ~4.2s |
| `qwen2.5:7b-instruct` | 18 | 5 | 1 | 12 | 0 | 0.83 | **1.00** | 0.94 | ~12.3s |

The production model caught every genuine repair narrative, including
both new ones (row 7's blower motor and row 21's PR gauge, the one the
smaller model missed and the one found by this run, respectively). Its
**one false positive is row 17 — the exact narrative this doc flagged
in advance as "the boundary case most likely to cause disagreement"**
("TUBING GETTING STUCK IN THE TBG SPINNER FREQUENTLY. JOINTS WERE TOO
TIGHT", flagged with `equipment_or_system: "TBG spinner"`,
`confidence: "medium"`). That's a reasonable, defensible read of an
ambiguous narrative, not a wiring bug — exactly the kind of call human
review should settle, not this eval.

**Failure handling (2026-09-25)**: a failed LLM call (Ollama unreachable,
timeout, HTTP error, unusable response) used to return `[]` — identical
to "no repair language found", so an outage silently made reports look
repair-free, and made `scripts/run_repair_eval.py` score a down model as
all no-flag answers. `extract_repair_events` now raises
`RepairExtractionError` instead; ingestion records it per report
(`DailyEntry.repair_check_status = "failed"`), the dashboard warns, and
failed checks can be re-run (`POST /api/repairs/recheck`). The eval
script counts such rows as `ERR` and excludes them from the metrics.

**Performance note**: ~12.3s/narrative on CPU (vs. ~4.2s for the small
model) is a real cost of the larger model, not just a quality trade.
`07_non_functional_requirements.md`'s 5-minute per-file ingest budget
holds comfortably at the sample sizes here (13 wells × 12.3s ≈ 160s),
but **at the confirmed ceiling of 30 wells/asset it would approach
6+ minutes** — over budget. Worth a real hardware benchmark (GPU
availability, model quantization) before committing to this model size
at full scale, per `05_architecture.md`'s existing "benchmark before
committing" note.

Per the existing guidance above: even with these numbers, every flagged
event still ships with `reviewed = false` and must go through human
confirmation — this eval is a wiring/regression sanity check, not a
substitute for that review queue (Phase 7).

## Prompt 2: Proposal/AFE field extraction (draft — untested against a real document)

**Status**: written from the target field list in
`02_data_dictionary.md` §B, not yet validated against a real proposal
PDF. Re-derive/adjust this prompt the same way Prompt 1 was validated —
against real text — before relying on it.

```
SYSTEM PROMPT:

You are extracting structured data from a well drilling proposal / AFE
(Authority for Expenditure) document. Extract the following fields as
JSON. Use null for anything not present in the document. Do not guess
values that aren't stated.

{
  "well_name": string or null,
  "proposed_date": "YYYY-MM-DD" or null,
  "approved_date": "YYYY-MM-DD" or null,
  "approving_authority": string or null,
  "afe_number": string or null,
  "gto_reference": string or null,
  "objective": string or null,
  "formation_tops": string or null,
  "mud_program": string or null,
  "casing_program": string or null,
  "planned_total_days": integer or null,
  "planned_total_cost_inr": number or null
}

Return ONLY the JSON object, no other text, no markdown fences.
```

[ **Action needed**: once a real sample is available, check whether
this document is regular enough that some fields could also be
regex-parsed deterministically (cheaper, more reliable) rather than
LLM-extracted — the same evaluation the DPR itself went through. Don't
assume LLM-for-everything is the right default; use it only where the
document's actual structure requires it. ]

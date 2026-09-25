"""Informal precision/recall check of app.llm_client against
eval/repair_extraction_eval.json — the real-model suite CLAUDE.md asks
to keep separate from the mocked pytest suite.

Requires a real, running Ollama with OLLAMA_MODEL pulled. Not part of
`pytest` — run manually:

    python scripts/run_repair_eval.py

Per docs/06_llm_prompts_and_eval.md's "Acceptance threshold": there's no
ground-truth hours to check against, so treat every LLM flag as needing
human confirmation regardless of this script's numbers — this is a
sanity check to catch prompt/wiring regressions, not a production gate.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm_client import (  # noqa: E402
    OLLAMA_MODEL,
    RepairExtractionError,
    extract_repair_events,
)

EVAL_FILE = Path(__file__).resolve().parent.parent / "eval" / "repair_extraction_eval.json"


def main() -> None:
    rows = json.loads(EVAL_FILE.read_text(encoding="utf-8"))

    tp = fp = tn = fn = errors = 0
    results = []

    for row in rows:
        start = time.monotonic()
        try:
            events = extract_repair_events(row["narrative_text"])
        except RepairExtractionError as exc:
            # A failed call is not a "no-flag" answer -- counting it as one
            # would silently inflate TN/FN. Excluded from the metrics.
            errors += 1
            print(f"[{row['id']:>2}] ERR  {exc}")
            continue
        elapsed = time.monotonic() - start
        actual_flag = len(events) > 0
        expected_flag = row["expected_should_flag"]

        if expected_flag and actual_flag:
            tp += 1
            outcome = "TP"
        elif not expected_flag and not actual_flag:
            tn += 1
            outcome = "TN"
        elif not expected_flag and actual_flag:
            fp += 1
            outcome = "FP"
        else:
            fn += 1
            outcome = "FN"

        results.append((row["id"], outcome, elapsed, events))
        print(
            f"[{row['id']:>2}] {outcome}  ({elapsed:5.1f}s)  "
            f"expected={'flag' if expected_flag else 'no-flag'} "
            f"actual={'flag' if actual_flag else 'no-flag'}  "
            f"{row['source']}"
        )
        if outcome in ("FP", "FN"):
            print(f"       narrative: {row['narrative_text'][:100]}...")
            print(f"       events returned: {events}")

    n = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    accuracy = (tp + tn) / n if n else float("nan")
    total_time = sum(r[2] for r in results)

    print()
    print(f"Model: {OLLAMA_MODEL}")
    if errors:
        print(f"WARNING: {errors} row(s) failed to get an LLM answer and are "
              "excluded below -- is Ollama running with this model pulled?")
    print(f"Rows: {n}  TP={tp} FP={fp} TN={tn} FN={fn}")
    print(f"Precision: {precision:.2f}  Recall: {recall:.2f}  Accuracy: {accuracy:.2f}")
    if n:
        print(f"Total time: {total_time:.1f}s  Avg per narrative: {total_time / n:.1f}s")


if __name__ == "__main__":
    main()

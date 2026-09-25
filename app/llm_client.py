"""Local Ollama client for repair/troubleshooting extraction.

Implements docs/06_llm_prompts_and_eval.md Prompt 1 exactly. This only
ever talks to a locally-running Ollama instance (docs/05_architecture.md's
hard constraint: no well/cost/operational data to any third-party API).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, TypedDict

import httpx

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")

# docs/06_llm_prompts_and_eval.md "Prompt 1: Repair/troubleshooting event
# extraction" -- copied verbatim, do not paraphrase.
SYSTEM_PROMPT = """You are reviewing a daily drilling operations narrative (OPER text)
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

If there is no repair/troubleshooting language, return an empty array: []"""


class RepairExtractionError(Exception):
    """The check did not run (Ollama unreachable, timeout, HTTP error,
    unusable response). Distinct from "ran and found nothing" (`[]`):
    callers record it so a report is never silently treated as
    repair-free just because the model was down."""


class RepairEventDict(TypedDict):
    equipment_or_system: str
    snippet: str
    confidence: str


def extract_repair_events(narrative: str) -> list[RepairEventDict]:
    """Call the local LLM once for one day's OPER narrative.

    Returns [] only when the model actually ran and found nothing. Any
    failure (Ollama unreachable, timeout, HTTP error, bad JSON, unusable
    shape) raises RepairExtractionError -- app/ingest.py catches it per
    well, so one failed call still never blocks the rest of a file.
    """
    narrative = (narrative or "").strip()
    if not narrative:
        return []

    try:
        response = httpx.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "system": SYSTEM_PROMPT,
                "prompt": narrative,
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=120.0,
        )
        response.raise_for_status()
        raw = response.json()["response"]
        events = json.loads(raw)
    except Exception as exc:
        raise RepairExtractionError(f"local LLM call failed: {exc}") from exc

    if isinstance(events, dict):
        # Smaller/weaker models sometimes return a bare object instead of
        # an array despite the prompt's explicit instruction -- `{}` for
        # "no events" (equivalent to `[]`) or a single event object
        # unwrapped. Recover both rather than discarding a real event.
        events = [events] if events else []

    if not isinstance(events, list):
        raise RepairExtractionError(f"LLM returned unusable JSON shape: {events!r:.200}")

    return [cleaned for event in events if (cleaned := _clean_event(event)) is not None]


def _clean_event(event: Any) -> RepairEventDict | None:
    if not isinstance(event, dict):
        return None
    equipment = event.get("equipment_or_system")
    snippet = event.get("snippet")
    if not equipment or not snippet:
        return None
    confidence = event.get("confidence")
    if confidence not in ("low", "medium", "high"):
        confidence = "low"
    return {
        "equipment_or_system": str(equipment),
        "snippet": str(snippet),
        "confidence": confidence,
    }

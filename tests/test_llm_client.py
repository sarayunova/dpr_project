"""Unit tests for the Ollama client boundary — mocked httpx throughout,
per CLAUDE.md ("mock the LLM client boundary for parser/API tests, and
keep a small separate suite that exercises the real model when run
locally" — that suite is scripts/run_repair_eval.py, not this file).
"""

import json
from unittest.mock import MagicMock, patch

from app.llm_client import extract_repair_events


def _mock_response(body: object, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = {"response": json.dumps(body)}
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return response


def test_blank_narrative_skips_the_llm_call_entirely():
    with patch("app.llm_client.httpx.post") as mock_post:
        result = extract_repair_events("   ")
    mock_post.assert_not_called()
    assert result == []


def test_well_formed_flag_response_is_parsed():
    body = [
        {
            "equipment_or_system": "DW drum encoder",
            "snippet": "ENCODER#2 REPLACED BY FMP(E)",
            "confidence": "high",
        }
    ]
    with patch("app.llm_client.httpx.post", return_value=_mock_response(body)):
        result = extract_repair_events("ENCOUNTERED DW DRUM ENCODER FAULT...")

    assert result == [
        {
            "equipment_or_system": "DW drum encoder",
            "snippet": "ENCODER#2 REPLACED BY FMP(E)",
            "confidence": "high",
        }
    ]


def test_empty_array_response_means_no_events():
    with patch("app.llm_client.httpx.post", return_value=_mock_response([])):
        result = extract_repair_events("CONTD DRILLING 8-1/2 HOLE FROM 2004M TO 2080M.")
    assert result == []


def test_malformed_event_missing_required_fields_is_dropped():
    body = [{"equipment_or_system": "pump"}, {"snippet": "no equipment field"}]
    with patch("app.llm_client.httpx.post", return_value=_mock_response(body)):
        result = extract_repair_events("some narrative")
    assert result == []


def test_invalid_confidence_value_defaults_to_low():
    body = [{"equipment_or_system": "pump", "snippet": "fixed it", "confidence": "extremely-high"}]
    with patch("app.llm_client.httpx.post", return_value=_mock_response(body)):
        result = extract_repair_events("some narrative")
    assert result[0]["confidence"] == "low"


def test_non_list_json_response_is_treated_as_no_events():
    with patch("app.llm_client.httpx.post", return_value=_mock_response({"not": "a list"})):
        result = extract_repair_events("some narrative")
    assert result == []


def test_bare_empty_object_is_recovered_as_no_events():
    # Observed from a real small model (qwen2.5:1.5b-instruct) during
    # eval — it sometimes returns {} instead of [] for "no events".
    with patch("app.llm_client.httpx.post", return_value=_mock_response({})):
        result = extract_repair_events("some narrative")
    assert result == []


def test_bare_single_event_object_is_recovered_as_one_event_list():
    # Same real model, same run — a single flagged event sometimes comes
    # back unwrapped instead of inside a one-item array.
    body = {"equipment_or_system": "TDS", "snippet": "arrested leakage of TDS", "confidence": "high"}
    with patch("app.llm_client.httpx.post", return_value=_mock_response(body)):
        result = extract_repair_events("some narrative")
    assert result == [
        {"equipment_or_system": "TDS", "snippet": "arrested leakage of TDS", "confidence": "high"}
    ]


def test_connection_failure_returns_empty_list_not_an_exception():
    with patch("app.llm_client.httpx.post", side_effect=ConnectionError("no ollama")):
        result = extract_repair_events("some narrative")
    assert result == []


def test_invalid_json_in_response_returns_empty_list():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"response": "not valid json {"}
    response.raise_for_status = MagicMock()
    with patch("app.llm_client.httpx.post", return_value=response):
        result = extract_repair_events("some narrative")
    assert result == []


def test_http_error_status_returns_empty_list():
    with patch("app.llm_client.httpx.post", return_value=_mock_response([], status_code=500)):
        result = extract_repair_events("some narrative")
    assert result == []


def test_request_uses_temperature_zero_and_json_format():
    with patch("app.llm_client.httpx.post", return_value=_mock_response([])) as mock_post:
        extract_repair_events("some narrative")

    _, kwargs = mock_post.call_args
    payload = kwargs["json"]
    assert payload["format"] == "json"
    assert payload["options"]["temperature"] == 0.0
    assert payload["prompt"] == "some narrative"

"""CONV-P0 P0-8B — golden-conversation eval runner + web debug endpoints.

Covers: the eval framework (suite loading, pass/fail detection, capability/route
grouping, CLI contract), the three debug endpoints (memory / reset-memory / last-trace)
through the real FastAPI app, session-scoped reset isolation, and preservation of the
existing chat API.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from agent_core.eval.conversation_eval import (
    GENERIC_FALLBACK_MARKER,
    format_text_report,
    load_suite,
    run_suite,
)
from agent_core.web_api.app import create_app

GOLDEN_SUITE_PATH = Path(__file__).parent.parent / "data" / "evals" / (
    "p0_8b_golden_conversations.json"
)


def _chat(client: TestClient, session_id: str, text: str) -> str:
    resp = client.post("/api/chat", json={"session_id": session_id, "message": text})
    assert resp.status_code == 200, resp.text
    return resp.json()["assistant_message"]["content"]


def _new_session(client: TestClient) -> str:
    resp = client.post("/api/sessions", json={})
    assert resp.status_code == 201, resp.text
    return resp.json()["session_id"]


# ---------------------------------------------------------------------------
# Part A/B — eval runner + golden suite
# ---------------------------------------------------------------------------

def test_p8b_golden_suite_loads_and_passes():
    suite = load_suite(GOLDEN_SUITE_PATH)
    assert len(suite["cases"]) >= 12
    result = run_suite(suite)
    assert result.failed == 0, format_text_report(result)
    assert result.cases >= 12
    assert result.turns >= 25
    assert result.passed == result.turns


def test_p8b_eval_runner_detects_failures():
    failing_suite = {
        "suite_id": "mini_failing",
        "cases": [
            {
                "id": "will_fail",
                "turns": [
                    {
                        "user": "tôi thích ăn kem",
                        "expect_answer_contains_all": ["THIS_TOKEN_NEVER_APPEARS"],
                        "expect_capability": "translation",
                    }
                ],
            }
        ],
    }
    result = run_suite(failing_suite)
    assert result.failed == 1 and result.passed == 0
    checks = {f.check for f in result.failures}
    assert "expect_answer_contains_all" in checks
    assert "expect_capability" in checks


def test_p8b_eval_runner_groups_by_capability_and_route():
    suite = {
        "suite_id": "mini_grouping",
        "cases": [
            {
                "id": "grouping",
                "turns": [
                    {"user": "tôi thích ăn kem"},
                    {"user": "Dịch đoạn này sang tiếng Anh: hello"},
                    {"user": "gửi email cho Nam là hello"},
                ],
            }
        ],
    }
    result = run_suite(suite)
    assert result.failed == 0
    assert "deterministic_memory" in result.by_capability
    assert "translation" in result.by_capability
    assert "tool_action_request" in result.by_capability
    assert "bounded_responder" in result.by_route
    assert "safety_gate" in result.by_route
    assert any(label.startswith("external_action") for label in result.by_safety)


def test_p8b_eval_expect_route_alias_and_memory_expectations():
    suite = {
        "suite_id": "mini_expectations",
        "cases": [
            {
                "id": "expectations",
                "turns": [
                    {
                        "user": "tôi thích ăn kem",
                        "expect_route": "deterministic_memory",
                        "expect_memory_diff_contains": ["confirmed_profile_facts:+1"],
                        "expect_memory_empty": False,
                    },
                    {"user": "xoá hết ký ức"},
                    {"user": "ok", "expect_memory_empty": True},
                ],
            }
        ],
    }
    result = run_suite(suite)
    assert result.failed == 0, format_text_report(result)


def test_p8b_eval_text_report_format():
    suite = load_suite(GOLDEN_SUITE_PATH)
    result = run_suite(suite)
    report = format_text_report(result)
    assert f"Suite: {suite['suite_id']}" in report
    assert "Failed: 0" in report
    assert "By capability:" in report
    assert "By route:" in report


def test_p8b_eval_json_dict_contract():
    suite = load_suite(GOLDEN_SUITE_PATH)
    payload = run_suite(suite).to_json_dict()
    # Contract consumed by the CLI --json mode and the runtime probe.
    assert payload["failed"] == 0
    assert payload["cases"] >= 12
    assert isinstance(payload["by_capability"], dict)
    json.dumps(payload)  # must be JSON-serializable


def test_p8b_generic_marker_constant_matches_runtime():
    # The eval marker must be the real generic fallback prefix, lowercased.
    assert GENERIC_FALLBACK_MARKER.startswith("tôi chưa xử lý được yêu cầu này")


# ---------------------------------------------------------------------------
# Part C — debug endpoints (real app, real runtime)
# ---------------------------------------------------------------------------

def test_p8b_debug_memory_endpoint_after_chat():
    with TestClient(create_app()) as client:
        session_id = _new_session(client)
        _chat(client, session_id, "tôi thích ăn kem")
        resp = client.get(f"/api/debug/memory?session_id={session_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["session_id"] == session_id
        assert "active" in body["summary"]
        values = [f["value"] for f in body["facts"] if f["active"]]
        assert any("kem" in v for v in values), body["facts"]


def test_p8b_debug_memory_unknown_session_404():
    with TestClient(create_app()) as client:
        resp = client.get("/api/debug/memory?session_id=no-such-session")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "SESSION_NOT_FOUND"


def test_p8b_reset_memory_clears_only_target_session():
    with TestClient(create_app()) as client:
        session_a = _new_session(client)
        session_b = _new_session(client)
        _chat(client, session_a, "tôi thích ăn kem")
        _chat(client, session_b, "tôi biết Python")

        reset = client.post("/api/debug/reset-memory", json={"session_id": session_a})
        assert reset.status_code == 200, reset.text
        body = reset.json()
        assert body["ok"] is True and body["session_id"] == session_a
        assert "memory reset" in body["message"]

        # Session A's fact is gone; session B's fact survives in the shared store.
        remaining = client.get(f"/api/debug/memory?session_id={session_a}").json()
        values = [f["value"] for f in remaining["facts"]]
        assert not any("kem" in v for v in values), remaining["facts"]
        assert any("Python" in v for v in values), remaining["facts"]


def test_p8b_reset_memory_unknown_session_404():
    with TestClient(create_app()) as client:
        resp = client.post("/api/debug/reset-memory", json={"session_id": "nope"})
        assert resp.status_code == 404


def test_p8b_last_trace_endpoint_bounded_responder_turn():
    with TestClient(create_app()) as client:
        session_id = _new_session(client)
        # Before any turn: trace is null.
        empty = client.get(f"/api/debug/last-trace?session_id={session_id}")
        assert empty.status_code == 200 and empty.json()["trace"] is None

        _chat(client, session_id, "Dịch đoạn này sang tiếng Anh: tôi thích học AI")
        resp = client.get(f"/api/debug/last-trace?session_id={session_id}")
        assert resp.status_code == 200, resp.text
        trace = resp.json()["trace"]
        assert trace is not None
        assert trace["capability"] == "translation"
        assert trace["route"] == "bounded_responder"
        assert trace["tool_name"] is None
        assert trace["final_answer"]


def test_p8b_last_trace_endpoint_blocked_external_action():
    with TestClient(create_app()) as client:
        session_id = _new_session(client)
        _chat(client, session_id, "gửi email cho Nam là hello")
        trace = client.get(f"/api/debug/last-trace?session_id={session_id}").json()["trace"]
        assert trace["capability"] == "tool_action_request"
        assert trace["route"] == "safety_gate"
        assert trace["safety_decision"] is not None and "blocked" in trace["safety_decision"]
        assert trace["tool_name"] == "send_email"
        assert trace["tool_ok"] is None


def test_p8b_existing_chat_api_still_works():
    with TestClient(create_app()) as client:
        session_id = _new_session(client)
        answer = _chat(client, session_id, "tôi thích ăn kem")
        assert "kem" in answer.lower()
        follow = _chat(client, session_id, "tôi thích ăn gì?")
        assert "kem" in follow.lower()

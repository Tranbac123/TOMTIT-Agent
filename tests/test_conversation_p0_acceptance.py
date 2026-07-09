"""CONV-P0 P0-1 — pytest acceptance runner for the frozen conversation dataset.

Makes ``tests/acceptance/conversation_p0_cases.yaml`` (spec
``docs/specs/SPEC_CONV_P0_BASIC_CONVERSATION.md``, FROZEN) executable as a
regression gate WITHOUT implementing CONV-P0 behavior:

- dataset integrity tests (count / unique ids / status distribution / impl flag);
- ``ALREADY_IMPLEMENTED_FIRST_PASS`` cases are asserted strictly. Cases whose behavior
  lives in the bare parser/planner (greetings, calculation, recoverable-unknown) assert
  against ``RuleBasedIntentParser`` -> ``IntentPlanner``. Cases tagged
  ``current_runner: session_runtime`` (identity/capability/memory-read/clarification,
  planning/product/writing/code task-shaped clarifications, continuation, memory-edge
  goal-read/imperative-remember/vague-forget/disable-turn/assumption) assert against the
  shipped ``SessionRuntime.handle_turn`` path (P0-7K burndown P1/P2/P3);
- the remaining ``SPEC_REQUIRED_NOT_IMPLEMENTED`` cases are ``xfail`` with an explicit
  reason — they are an executable future contract, not a premature pass.

Constraints honoured: no LLM parser / hybrid / skill-aware planner import; the
``session_runtime`` cases exercise only the already-shipped rule-based conversation
runtime (no LLM, no network).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
import yaml

from agent_core.planning.intent_parser import RuleBasedIntentParser
from agent_core.planning.intent_planner import IntentPlanner
from agent_core.planning.intents import IntentName
from agent_core.state.enums import ToolName

CASES_PATH = Path(__file__).parent / "acceptance" / "conversation_p0_cases.yaml"

_DATA = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
_CASES = _DATA["cases"] if isinstance(_DATA, dict) else []

_STRICT_STATUS = "ALREADY_IMPLEMENTED_FIRST_PASS"
_VALID_STATUSES = {
    "ALREADY_IMPLEMENTED_FIRST_PASS",
    "SPEC_REQUIRED_PARTIAL",
    "SPEC_REQUIRED_NOT_IMPLEMENTED",
    "OUT_OF_SCOPE_FOR_CONV_P0",
}
# P0-7K xfail-burndown P1: 8 cases whose current behavior lives in SessionRuntime were
# promoted NOT_IMPLEMENTED->IMPLEMENTED (current_runner: session_runtime) and greeting_002
# was promoted PARTIAL->IMPLEMENTED (passes via parser/planner).
# P0-7K xfail-burndown P2: 14 more bounded clarification cases (planning checklist/priority,
# product analysis, writing/summarization, code bug/test, bare "tiếp tục") promoted the same
# way.
# P0-7K xfail-burndown P3: 5 memory-edge cases (goal-read variant, imperative remember,
# vague forget clarification, disable-memory-for-turn, assumption/provenance limitation)
# promoted the same way. See conversation_p0_cases.yaml.
_EXPECTED_STATUS_DISTRIBUTION = {
    "ALREADY_IMPLEMENTED_FIRST_PASS": 33,
    "SPEC_REQUIRED_NOT_IMPLEMENTED": 7,
}
_REQUIRED_FIELDS = {
    "id", "group", "input", "expected_intent", "expected_handling",
    "current_status", "must_include_any", "must_not_include",
    "requires_memory", "requires_tool", "requires_llm", "notes",
}

# CONV-P0 spec intent name -> the IntentName that the bare parser produces today. Only the
# parser/planner-first-pass intents are mapped. Runtime-layer intents (IDENTITY_QUERY,
# CAPABILITY_QUERY, MEMORY_READ, CLARIFICATION_REQUEST, ...) are handled via
# current_runner: session_runtime, not through this map.
_IMPLEMENTED_INTENT_MAP = {
    "GREETING": IntentName.GREETING,
    "CALCULATION_REQUEST": IntentName.CALCULATE,
    "UNKNOWN_RECOVERABLE": IntentName.UNKNOWN,
}


def _finish_answer(steps) -> str | None:
    for step in steps:
        if step.action == ToolName.FINISH and isinstance(step.args.get("answer"), str):
            return step.args["answer"]
    return None


def _is_static_text(text: str | None) -> bool:
    # A planner FINISH answer containing "$" is a runtime template (e.g.
    # "Kết quả: ${last.output.value}") resolved by the executor — not assertable here.
    return text is not None and "$" not in text


# ---------------------------------------------------------------------------
# P0-7K xfail-burndown P1: assert current SessionRuntime behavior
# ---------------------------------------------------------------------------
# Some CONV-P0 cases (identity/capability/memory-read/clarification) are handled by the
# shipped conversation runtime, NOT by the bare parser/planner path. Cases tagged
# ``current_runner: session_runtime`` are executed against SessionRuntime.handle_turn and
# asserted against their frozen must_include_any / must_not_include contract.

_GENERIC_FALLBACK_MARKERS = ("rule-based mvp", "tôi chưa xử lý được yêu cầu này")
# A forbidden "over-claim" phrase (e.g. "tự động làm mọi thứ") is acceptable when the answer
# NEGATES it ("không tự động làm mọi thứ"). must_not_include forbids the AFFIRMATIVE claim.
_NEGATION_PREFIXES = ("không", "chưa", "đừng", "không có")


def _affirmatively_present(low_answer: str, phrase: str) -> bool:
    """True if ``phrase`` occurs NOT immediately preceded by a negation word.

    Keeps must_not_include truthful: "tự động làm mọi thứ" inside "không tự động làm mọi
    thứ" is a correct humility statement, not the forbidden over-claim.
    """
    idx = 0
    while True:
        hit = low_answer.find(phrase, idx)
        if hit == -1:
            return False
        preceding = low_answer[:hit].rstrip()
        if not any(preceding.endswith(neg) for neg in _NEGATION_PREFIXES):
            return True
        idx = hit + len(phrase)


def _assert_session_runtime_case(case) -> None:
    from agent_core.runtime.runtime_agent import build_local_agent
    from agent_core.runtime.session_runtime import SessionRuntime

    agent, store = build_local_agent()
    session = SessionRuntime(agent, store)
    answer = session.handle_turn(case["input"]).final_answer or ""
    low = answer.lower()

    # 1. Never the generic rule-based fallback.
    assert not any(m in low for m in _GENERIC_FALLBACK_MARKERS), (
        f"{case['id']}: generic fallback answer {answer!r}"
    )
    # 2. Must include at least one expected key phrase (case-insensitive).
    include_any = case.get("must_include_any") or []
    if include_any:
        assert any(tok.lower() in low for tok in include_any), (
            f"{case['id']}: none of {include_any} found in answer {answer!r}"
        )
    # 3. Must not AFFIRMATIVELY claim any forbidden over-reach (negation-aware).
    for forbidden in case.get("must_not_include") or []:
        assert not _affirmatively_present(low, forbidden.lower()), (
            f"{case['id']}: forbidden over-claim {forbidden!r} present in answer {answer!r}"
        )


# ---------------------------------------------------------------------------
# Dataset integrity
# ---------------------------------------------------------------------------

def test_conversation_p0_dataset_loads():
    assert isinstance(_DATA, dict)
    assert isinstance(_DATA.get("cases"), list)


def test_conversation_p0_dataset_case_count():
    assert len(_CASES) == 40


def test_conversation_p0_dataset_unique_ids():
    ids = [c["id"] for c in _CASES]
    assert len(set(ids)) == len(ids)


def test_conversation_p0_dataset_required_fields_present():
    missing = {c.get("id"): sorted(_REQUIRED_FIELDS - set(c)) for c in _CASES if _REQUIRED_FIELDS - set(c)}
    assert missing == {}, f"cases missing required fields: {missing}"


def test_conversation_p0_dataset_current_status_distribution():
    counts = dict(Counter(c["current_status"] for c in _CASES))
    assert counts == _EXPECTED_STATUS_DISTRIBUTION, counts


def test_conversation_p0_dataset_status_values_valid():
    bad = [c["id"] for c in _CASES if c["current_status"] not in _VALID_STATUSES]
    assert bad == [], f"unknown current_status values: {bad}"


def test_conversation_p0_dataset_implementation_authorized_false():
    assert _DATA["implementation_authorized"] is False


# ---------------------------------------------------------------------------
# Per-case current behavior (40 parametrized): 33 strict (6 parser/planner + 27 session_runtime),
# 7 xfail future-contract.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_conversation_p0_case_current_behavior(case):
    status = case["current_status"]
    if status != _STRICT_STATUS:
        if status == "SPEC_REQUIRED_PARTIAL":
            pytest.xfail(
                "CONV-P0 behavior partial by frozen dataset status; not implemented in P0-1."
            )
        pytest.xfail(
            "CONV-P0 behavior not implemented by frozen dataset status; P0-1 runner only."
        )

    # P0-7K burndown P1: runtime-layer cases assert against SessionRuntime.handle_turn.
    if case.get("current_runner") == "session_runtime":
        _assert_session_runtime_case(case)
        return

    # Strict path — current rule-based parser/planner only (no tools/memory/LLM).
    parsed = RuleBasedIntentParser().parse(case["input"])
    expected_intent = _IMPLEMENTED_INTENT_MAP.get(case["expected_intent"])
    assert expected_intent is not None, (
        f"{case['id']}: strict case has unmapped expected_intent {case['expected_intent']!r}"
    )
    assert parsed.intent == expected_intent, (
        f"{case['id']}: expected intent {expected_intent}, got {parsed.intent}"
    )

    steps = IntentPlanner().make_plan(parsed)

    if case["expected_intent"] == "CALCULATION_REQUEST":
        # The planner routes calculation to a CALCULATE step; the FINISH answer is a
        # runtime template, so the numeric `must_include_any` (e.g. "2"/"4") is produced
        # by the executor at runtime and is out of scope for this parser/planner-only
        # runner. Assert the routing (SIMPLE_TOOL_OR_CALCULATION), not the computed value.
        assert any(s.action == ToolName.CALCULATE for s in steps), (
            f"{case['id']}: expected a CALCULATE step, got {[s.action.value for s in steps]}"
        )
        return

    # Greeting / recoverable-unknown produce a deterministic static FINISH answer.
    answer = _finish_answer(steps)
    assert _is_static_text(answer), (
        f"{case['id']}: expected a static FINISH answer, got {answer!r}"
    )
    include_any = case.get("must_include_any") or []
    if include_any:
        assert any(tok in answer for tok in include_any), (
            f"{case['id']}: none of {include_any} found in answer {answer!r}"
        )
    for forbidden in case.get("must_not_include") or []:
        assert forbidden not in answer, (
            f"{case['id']}: forbidden text {forbidden!r} present in answer {answer!r}"
        )

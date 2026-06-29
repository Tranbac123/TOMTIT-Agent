"""CONV-P0 P0-1 — pytest acceptance runner for the frozen conversation dataset.

Makes ``tests/acceptance/conversation_p0_cases.yaml`` (spec
``docs/specs/SPEC_CONV_P0_BASIC_CONVERSATION.md``, FROZEN) executable as a
regression gate WITHOUT implementing CONV-P0 behavior:

- dataset integrity tests (count / unique ids / status distribution / impl flag);
- the 5 ``ALREADY_IMPLEMENTED_FIRST_PASS`` cases are asserted strictly against the
  current rule-based parser/planner path;
- the other 35 cases (1 PARTIAL + 34 NOT_IMPLEMENTED) are ``xfail`` with an explicit
  reason — they are an executable future contract, not a premature pass.

Constraints honoured: rule-based parser/planner only; NO tool execution, NO memory,
NO Web API, NO LLM, NO ConversationRouter/DirectResponder (none exist yet), and NO
import of the dormant LLM parser / hybrid / skill-aware planner modules.
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
_EXPECTED_STATUS_DISTRIBUTION = {
    "ALREADY_IMPLEMENTED_FIRST_PASS": 5,
    "SPEC_REQUIRED_PARTIAL": 1,
    "SPEC_REQUIRED_NOT_IMPLEMENTED": 34,
}
_REQUIRED_FIELDS = {
    "id", "group", "input", "expected_intent", "expected_handling",
    "current_status", "must_include_any", "must_not_include",
    "requires_memory", "requires_tool", "requires_llm", "notes",
}

# CONV-P0 spec intent name -> the IntentName that ALREADY exists in code today.
# Only the implemented-first-pass intents are mapped; unimplemented CONV-P0 intents
# (IDENTITY_QUERY, MEMORY_READ, ...) are intentionally absent — their cases xfail.
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
# Per-case current behavior (40 parametrized): 5 strict, 35 xfail
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

"""CONV-P0 P0-7F — safe numeric comparison parser.

Covers try_answer_comparison (unit) and the SessionRuntime seam (integration):
  - >, <, >=, <=, ==, != and single '=' equality
  - trailing '?' tolerated
  - "1 + 1 =" stays arithmetic (not a comparison)
  - no eval/exec anywhere in the module (source audit)
"""
from __future__ import annotations

import inspect

import pytest

from agent_core.conversation import simple_comparison
from agent_core.conversation.simple_comparison import try_answer_comparison
from agent_core.runtime.runtime_agent import build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime
from agent_core.state.enums import AgentStatus


def _make_sr() -> SessionRuntime:
    agent, store = build_local_agent()
    return SessionRuntime(agent, store)


@pytest.mark.parametrize("text, expected", [
    ("1 > 2", "Sai."),
    ("1 > 2?", "Sai."),
    ("3 > 2", "Đúng."),
    ("2 > 3?", "Sai."),
    ("2 == 2", "Đúng."),
    ("2 != 2", "Sai."),
    ("1 != 2", "Đúng."),
    ("5 >= 5", "Đúng."),
    ("5 <= 4", "Sai."),
    ("4 <= 5", "Đúng."),
    ("2 = 2", "Đúng."),
    ("2 = 3", "Sai."),
    ("2.5 > 2.1", "Đúng."),
    ("-1 < 0", "Đúng."),
])
def test_try_answer_comparison_unit(text: str, expected: str):
    assert try_answer_comparison(text) == expected


@pytest.mark.parametrize("text", [
    "1 + 1 =",       # trailing-equals arithmetic, not a comparison
    "1 + 1",
    "hello",
    "tôi thích cafe",
    "",
    "2 >",           # incomplete
    "> 2",
])
def test_try_answer_comparison_returns_none_for_non_comparison(text: str):
    assert try_answer_comparison(text) is None


def test_no_eval_or_exec_in_module_source():
    src = inspect.getsource(simple_comparison)
    assert "eval(" not in src
    assert "exec(" not in src


# --- SessionRuntime integration ---

@pytest.mark.parametrize("text, expected", [
    ("1 > 2", "Sai."),
    ("1 > 2?", "Sai."),
    ("3 > 2", "Đúng."),
    ("2 == 2", "Đúng."),
    ("5 >= 5", "Đúng."),
])
def test_comparison_answered_at_runtime(text: str, expected: str):
    sr = _make_sr()
    s = sr.handle_turn(text)
    assert s.status == AgentStatus.COMPLETED
    assert s.final_answer == expected


def test_arithmetic_still_calculates():
    sr = _make_sr()
    s = sr.handle_turn("1 + 1 =")
    assert s.status == AgentStatus.COMPLETED
    assert "2" in (s.final_answer or "")


# ---------------------------------------------------------------------------
# P0-7F-FIX5 Part A: compound comparison (arithmetic subexpression on either side)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("2 * 3 == 6", "Đúng."),
    ("2 * 3 == 7", "Sai."),
    ("2 + 3 > 4", "Đúng."),
    ("2 + 3 > 6", "Sai."),
    ("10 / 2 == 5", "Đúng."),
    ("10 / 2 == 4", "Sai."),
    ("4 != 4", "Sai."),
    ("2 * 3 != 7", "Đúng."),
    ("2 * 3 == 6?", "Đúng."),          # trailing '?' tolerated
    ("6 == 2 * 3", "Đúng."),           # arithmetic on the right side
    ("2 + 2 >= 2 * 2", "Đúng."),       # arithmetic on both sides
    ("10 - 3 < 2 * 2", "Sai."),        # subtraction honored
])
def test_compound_comparison_unit(text: str, expected: str):
    assert try_answer_comparison(text) == expected


@pytest.mark.parametrize("text", [
    "2 * 3",          # no comparator → arithmetic, not a comparison
    "2 * 3 =",        # trailing-equals arithmetic, no right operand
    "10 / 0 == 5",    # division by zero → not answerable, fall through
])
def test_compound_comparison_returns_none(text: str):
    assert try_answer_comparison(text) is None


@pytest.mark.parametrize("text, expected", [
    ("2 * 3 == 6", "Đúng."),
    ("2 + 3 > 4", "Đúng."),
    ("10 / 2 == 5", "Đúng."),
    ("4 != 4", "Sai."),
])
def test_compound_comparison_at_runtime(text: str, expected: str):
    sr = _make_sr()
    s = sr.handle_turn(text)
    assert s.status == AgentStatus.COMPLETED
    assert s.final_answer == expected

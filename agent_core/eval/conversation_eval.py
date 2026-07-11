"""CONV-P0 P0-8B — golden conversation eval runner.

Runs JSON golden suites through the real ``SessionRuntime.handle_turn`` path (fresh
session per case) and checks per-turn expectations against the answer text and the
P0-8A ``TurnTrace``. Stdlib-only: no pytest, no network, no provider.

Supported expectation fields per turn (all optional):
  expect_answer_contains_all   — every substring present (case-insensitive)
  expect_answer_contains_any   — at least one substring present (case-insensitive)
  expect_answer_not_contains   — no listed substring present (case-insensitive)
  expect_capability            — trace.capability equals (null → None)
  expect_route                 — trace.route equals; the alias "deterministic_memory"
                                 matches any deterministic conversation lane (a
                                 ``conv:*`` route that is not a capability/safety route)
  expect_safety_risk           — trace.safety_decision starts with this risk class
  expect_tool_name             — trace.tool_name equals (null → None)
  expect_tool_ok               — trace.tool_ok equals (null → None)
  expect_memory_diff_contains  — every listed entry present in trace.memory_diff
  expect_memory_empty          — confirmed-profile snapshot is empty (True) or not (False)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent_core.conversation.profile_memory import (
    ProfileSnapshot,
    collect_profile_snapshot,
)
from agent_core.runtime.runtime_agent import build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime

GENERIC_FALLBACK_MARKER = (
    "tôi chưa xử lý được yêu cầu này trong bản rule-based mvp hiện tại"
)


@dataclass
class TurnFailure:
    case_id: str
    turn_index: int
    user: str
    check: str
    detail: str


@dataclass
class SuiteResult:
    suite_id: str
    cases: int = 0
    turns: int = 0
    passed: int = 0
    failed: int = 0
    by_capability: dict[str, dict[str, int]] = field(default_factory=dict)
    by_route: dict[str, dict[str, int]] = field(default_factory=dict)
    by_safety: dict[str, dict[str, int]] = field(default_factory=dict)
    failures: list[TurnFailure] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "cases": self.cases,
            "turns": self.turns,
            "passed": self.passed,
            "failed": self.failed,
            "by_capability": self.by_capability,
            "by_route": self.by_route,
            "by_safety": self.by_safety,
            "failures": [vars(f) for f in self.failures],
        }


def load_suite(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError(f"invalid suite file: {path}")
    return data


def _default_session_factory() -> SessionRuntime:
    agent, store = build_local_agent()
    return SessionRuntime(agent, store)


def _snapshot_is_empty(snap: ProfileSnapshot) -> bool:
    list_fields = (
        snap.occupation, snap.skills, snap.learning, snap.goals, snap.marry_targets,
        snap.eat_desires, snap.today_intentions, snap.preferences_personal,
        snap.preferences_professional, snap.habits, snap.pets, snap.relations,
        snap.dislikes, snap.affections, snap.external_affections,
        snap.negative_affections, snap.negative_external_affections,
        snap.negative_skills, snap.negative_goals, snap.comparatives,
    )
    return (
        snap.name is None
        and snap.current_focus is None
        and snap.favorite_food is None
        and snap.favorite_general is None
        and all(not values for values in list_fields)
    )


def _route_matches(expected: str, actual: str | None) -> bool:
    if expected == actual:
        return True
    # Alias: any deterministic conversation lane (capability/safety routes are set
    # explicitly to "bounded_responder"/"safety_gate", never a conv:* marker).
    if expected == "deterministic_memory":
        return actual is not None and actual.startswith("conv:")
    return False


def _check_turn(
    turn: dict[str, Any],
    answer: str,
    trace: Any,
    store: Any,
    *,
    case_id: str,
    turn_index: int,
    failures: list[TurnFailure],
) -> bool:
    low = answer.lower()
    ok = True

    def fail(check: str, detail: str) -> None:
        nonlocal ok
        ok = False
        failures.append(TurnFailure(case_id, turn_index, turn["user"], check, detail))

    for token in turn.get("expect_answer_contains_all", []):
        if token.lower() not in low:
            fail("expect_answer_contains_all", f"missing {token!r} in {answer!r}")
    any_tokens = turn.get("expect_answer_contains_any", [])
    if any_tokens and not any(t.lower() in low for t in any_tokens):
        fail("expect_answer_contains_any", f"none of {any_tokens} in {answer!r}")
    for token in turn.get("expect_answer_not_contains", []):
        if token.lower() in low:
            fail("expect_answer_not_contains", f"forbidden {token!r} in {answer!r}")

    if "expect_capability" in turn and trace.capability != turn["expect_capability"]:
        fail("expect_capability", f"expected {turn['expect_capability']!r}, got {trace.capability!r}")
    if "expect_route" in turn and not _route_matches(turn["expect_route"], trace.route):
        fail("expect_route", f"expected {turn['expect_route']!r}, got {trace.route!r}")
    if "expect_safety_risk" in turn:
        actual = trace.safety_decision or ""
        if not actual.startswith(turn["expect_safety_risk"]):
            fail("expect_safety_risk", f"expected {turn['expect_safety_risk']!r}, got {actual!r}")
    if "expect_tool_name" in turn and trace.tool_name != turn["expect_tool_name"]:
        fail("expect_tool_name", f"expected {turn['expect_tool_name']!r}, got {trace.tool_name!r}")
    if "expect_tool_ok" in turn and trace.tool_ok != turn["expect_tool_ok"]:
        fail("expect_tool_ok", f"expected {turn['expect_tool_ok']!r}, got {trace.tool_ok!r}")
    for entry in turn.get("expect_memory_diff_contains", []):
        if entry not in trace.memory_diff:
            fail("expect_memory_diff_contains", f"{entry!r} not in {trace.memory_diff!r}")
    if "expect_memory_empty" in turn:
        empty = _snapshot_is_empty(collect_profile_snapshot(store))
        if empty != bool(turn["expect_memory_empty"]):
            fail("expect_memory_empty", f"expected empty={turn['expect_memory_empty']}, got {empty}")
    return ok


def _group_label_capability(trace: Any, answer: str) -> str:
    if trace.capability:
        return str(trace.capability)
    if GENERIC_FALLBACK_MARKER in answer.lower():
        return "unknown/current_limitation"
    return "deterministic_memory"


def run_suite(
    suite: dict[str, Any],
    *,
    session_factory: Callable[[], SessionRuntime] | None = None,
) -> SuiteResult:
    factory = session_factory or _default_session_factory
    result = SuiteResult(suite_id=str(suite.get("suite_id", "unknown_suite")))

    def _bump(bucket: dict[str, dict[str, int]], label: str, passed: bool) -> None:
        entry = bucket.setdefault(label, {"passed": 0, "failed": 0})
        entry["passed" if passed else "failed"] += 1

    for case in suite["cases"]:
        result.cases += 1
        session = factory()
        store = session._store  # eval harness: same-process inspection only
        for index, turn in enumerate(case.get("turns", [])):
            result.turns += 1
            answer = session.handle_turn(turn["user"]).final_answer or ""
            trace = session.last_trace
            ok = _check_turn(
                turn, answer, trace, store,
                case_id=str(case.get("id", f"case_{result.cases}")),
                turn_index=index,
                failures=result.failures,
            )
            if ok:
                result.passed += 1
            else:
                result.failed += 1
            _bump(result.by_capability, _group_label_capability(trace, answer), ok)
            _bump(result.by_route, trace.route or "none", ok)
            if trace.safety_decision:
                _bump(result.by_safety, trace.safety_decision, ok)
    return result


def format_text_report(result: SuiteResult) -> str:
    lines = [
        f"Suite: {result.suite_id}",
        f"Cases: {result.cases}",
        f"Turns: {result.turns}",
        f"Passed: {result.passed}",
        f"Failed: {result.failed}",
        "",
        "By capability:",
    ]
    for label in sorted(result.by_capability):
        counts = result.by_capability[label]
        lines.append(f"- {label}: passed={counts['passed']} failed={counts['failed']}")
    lines.append("")
    lines.append("By route:")
    for label in sorted(result.by_route):
        counts = result.by_route[label]
        lines.append(f"- {label}: passed={counts['passed']} failed={counts['failed']}")
    if result.by_safety:
        lines.append("")
        lines.append("By safety decision:")
        for label in sorted(result.by_safety):
            counts = result.by_safety[label]
            lines.append(f"- {label}: passed={counts['passed']} failed={counts['failed']}")
    if result.failures:
        lines.append("")
        lines.append("Failures:")
        for failure in result.failures:
            lines.append(
                f"- [{failure.case_id} turn {failure.turn_index}] {failure.check}: "
                f"{failure.detail}"
            )
    return "\n".join(lines)

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone

import pytest

from agent_core.state.enums import AgentStatus
from agent_core.state.session_state import SessionState, SessionStatusView, TurnRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXPECTED_TURN_RECORD_FIELDS = frozenset({
    "task_id",
    "goal",
    "final_answer",
    "status",
    "planned_actions",
    "memory_degraded",
    "memory_write_failed",
    "disclosure_reasons",
    "completed_at",
})


def _make_record(
    *,
    goal: str = "test goal",
    status: AgentStatus = AgentStatus.COMPLETED,
    final_answer: str | None = "answer",
    completed_at: datetime | None = None,
) -> TurnRecord:
    if completed_at is None:
        completed_at = datetime.now(timezone.utc)
    return TurnRecord(
        task_id="task-id-1",
        goal=goal,
        final_answer=final_answer if status == AgentStatus.COMPLETED else None,
        status=status,
        planned_actions=("calculate",),
        memory_degraded=False,
        memory_write_failed=False,
        disclosure_reasons=(),
        completed_at=completed_at,
    )


def _make_session_state() -> SessionState:
    now = datetime.now(timezone.utc)
    return SessionState(session_id="sess-1", created_at=now, updated_at=now)


# ---------------------------------------------------------------------------
# S3 — TurnRecord is frozen
# ---------------------------------------------------------------------------

def test_turn_record_is_frozen():
    record = _make_record()
    with pytest.raises(FrozenInstanceError):
        record.goal = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# S4 — TurnRecord has exactly 9 field names (no more, no less)
# ---------------------------------------------------------------------------

def test_turn_record_exact_field_set():
    actual = {f.name for f in fields(TurnRecord)}
    assert actual == _EXPECTED_TURN_RECORD_FIELDS


# ---------------------------------------------------------------------------
# S9 — status_view on empty session
# ---------------------------------------------------------------------------

def test_status_view_empty_session():
    ss = _make_session_state()
    view = ss.status_view()
    assert view.turn_count == 0
    assert view.last_status is None
    assert view.last_goal is None
    assert view.session_id == "sess-1"


# ---------------------------------------------------------------------------
# S10 — status_view after N turns reflects last turn
# ---------------------------------------------------------------------------

def test_status_view_after_turns():
    ss = _make_session_state()
    r1 = _make_record(goal="first", status=AgentStatus.COMPLETED)
    r2 = _make_record(goal="second", status=AgentStatus.FAILED, final_answer=None)
    r3 = _make_record(goal="third", status=AgentStatus.COMPLETED)
    ss.append_turn(r1)
    ss.append_turn(r2)
    ss.append_turn(r3)
    view = ss.status_view()
    assert view.turn_count == 3
    assert view.last_status == AgentStatus.COMPLETED
    assert view.last_goal == "third"


# ---------------------------------------------------------------------------
# S11 — history_view(limit) returns tuple, length ≤ limit, most recent last
# ---------------------------------------------------------------------------

def test_history_view_limit_returns_tuple():
    ss = _make_session_state()
    for i in range(5):
        ss.append_turn(_make_record(goal=f"goal-{i}"))

    result = ss.history_view(2)

    assert isinstance(result, tuple)
    assert len(result) == 2
    assert result[-1].goal == "goal-4"   # most recent


def test_history_view_limit_larger_than_turns_returns_all():
    ss = _make_session_state()
    ss.append_turn(_make_record(goal="only"))
    result = ss.history_view(10)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# S12 — history_view with limit < 1 raises ValueError
# ---------------------------------------------------------------------------

def test_history_view_limit_below_one_raises():
    ss = _make_session_state()
    with pytest.raises(ValueError):
        ss.history_view(0)
    with pytest.raises(ValueError):
        ss.history_view(-1)


# ---------------------------------------------------------------------------
# S17 — SessionStatusView is frozen
# ---------------------------------------------------------------------------

def test_session_status_view_is_frozen():
    view = SessionStatusView(
        session_id="s",
        turn_count=0,
        last_status=None,
        last_goal=None,
    )
    with pytest.raises(FrozenInstanceError):
        view.turn_count = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# S19 — append_turn sets updated_at = record.completed_at (not a second now())
# ---------------------------------------------------------------------------

def test_append_turn_sets_updated_at_to_record_completed_at():
    now = datetime.now(timezone.utc)
    ss = SessionState(session_id="s", created_at=now, updated_at=now)
    orig_created_at = ss.created_at

    record_ts = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)   # fixed future timestamp
    record = TurnRecord(
        task_id="t",
        goal="g",
        final_answer="a",
        status=AgentStatus.COMPLETED,
        planned_actions=(),
        memory_degraded=False,
        memory_write_failed=False,
        disclosure_reasons=(),
        completed_at=record_ts,
    )

    ss.append_turn(record)

    assert ss.updated_at == record_ts           # must equal record.completed_at exactly
    assert ss.created_at == orig_created_at     # created_at must not change

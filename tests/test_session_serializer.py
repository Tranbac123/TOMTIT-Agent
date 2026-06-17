from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from agent_core.session_persistence.errors import SessionDataCorruptionError
from agent_core.session_persistence.serializer import SessionSerializer
from agent_core.state.enums import AgentStatus
from agent_core.state.session_state import SessionState, TurnRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_session(*, turns: list[TurnRecord] | None = None) -> SessionState:
    now = _now()
    return SessionState(
        session_id=str(uuid4()),
        created_at=now,
        updated_at=now,
        turns=turns or [],
    )


def _make_turn(
    *,
    goal: str = "test goal",
    status: AgentStatus = AgentStatus.COMPLETED,
    final_answer: str | None = "answer",
    planned_actions: tuple[str, ...] = ("calculate",),
    disclosure_reasons: tuple[str, ...] = (),
) -> TurnRecord:
    return TurnRecord(
        task_id=str(uuid4()),
        goal=goal,
        final_answer=final_answer if status == AgentStatus.COMPLETED else None,
        status=status,
        planned_actions=planned_actions,
        memory_degraded=False,
        memory_write_failed=False,
        disclosure_reasons=disclosure_reasons,
        completed_at=_now(),
    )


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------

def test_empty_session_round_trip():
    ss = _make_session()
    d = SessionSerializer.to_dict(ss)
    ss2 = SessionSerializer.from_dict(d)
    assert ss2.session_id == ss.session_id
    assert ss2.turns == []
    assert ss2.created_at == ss.created_at
    assert ss2.updated_at == ss.updated_at


def test_session_with_completed_turn_round_trip():
    ss = _make_session()  # create session first → created_at < turn.completed_at
    turn = _make_turn(goal="hello", status=AgentStatus.COMPLETED, final_answer="world")
    ss.turns.append(turn)
    ss.updated_at = turn.completed_at

    d = SessionSerializer.to_dict(ss)
    ss2 = SessionSerializer.from_dict(d)

    assert len(ss2.turns) == 1
    r = ss2.turns[0]
    assert r.goal == "hello"
    assert r.final_answer == "world"
    assert r.status == AgentStatus.COMPLETED
    assert isinstance(r.planned_actions, tuple)
    assert isinstance(r.disclosure_reasons, tuple)
    assert r.completed_at.tzinfo is not None


def test_turn_with_none_final_answer_round_trip():
    ss = _make_session()
    turn = _make_turn(status=AgentStatus.FAILED, final_answer=None)
    ss.turns.append(turn)
    ss.updated_at = turn.completed_at

    d = SessionSerializer.to_dict(ss)
    ss2 = SessionSerializer.from_dict(d)

    assert ss2.turns[0].final_answer is None
    assert ss2.turns[0].status == AgentStatus.FAILED


def test_empty_tuples_round_trip():
    ss = _make_session()
    turn = _make_turn(planned_actions=(), disclosure_reasons=())
    ss.turns.append(turn)
    ss.updated_at = turn.completed_at

    d = SessionSerializer.to_dict(ss)
    ss2 = SessionSerializer.from_dict(d)

    assert ss2.turns[0].planned_actions == ()
    assert ss2.turns[0].disclosure_reasons == ()


def test_datetime_timezone_preserved():
    ss = _make_session()
    d = SessionSerializer.to_dict(ss)
    ss2 = SessionSerializer.from_dict(d)

    assert ss2.created_at.tzinfo is not None
    assert ss2.updated_at.tzinfo is not None


def test_schema_version_in_output():
    ss = _make_session()
    d = SessionSerializer.to_dict(ss)
    assert d["schema_version"] == SessionSerializer.SCHEMA_VERSION


def test_from_dict_with_expected_session_id_matches():
    ss = _make_session()
    d = SessionSerializer.to_dict(ss)
    ss2 = SessionSerializer.from_dict(d, expected_session_id=ss.session_id)
    assert ss2.session_id == ss.session_id


def test_from_dict_with_wrong_expected_session_id_raises():
    ss = _make_session()
    d = SessionSerializer.to_dict(ss)
    with pytest.raises(SessionDataCorruptionError, match="mismatch"):
        SessionSerializer.from_dict(d, expected_session_id=str(uuid4()))


def test_multiple_turns_preserved_in_order():
    ss = _make_session()  # session created first; turns have later timestamps
    for goal in ("first", "second", "third"):
        t = _make_turn(goal=goal)
        ss.turns.append(t)
        ss.updated_at = t.completed_at

    d = SessionSerializer.to_dict(ss)
    ss2 = SessionSerializer.from_dict(d)

    assert [t.goal for t in ss2.turns] == ["first", "second", "third"]


def test_naive_datetime_string_raises_corruption_error():
    ss = _make_session()
    d = SessionSerializer.to_dict(ss)
    d["created_at"] = "2026-01-01T12:00:00"  # no offset — must be rejected
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer.from_dict(d)


# ---------------------------------------------------------------------------
# to_dict validation errors
# ---------------------------------------------------------------------------

def test_to_dict_rejects_non_session_state():
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer.to_dict("not a session")  # type: ignore[arg-type]


def test_to_dict_rejects_non_canonical_uuid():
    now = _now()
    ss = SessionState(session_id="not-a-uuid", created_at=now, updated_at=now)
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer.to_dict(ss)


def test_to_dict_rejects_naive_created_at():
    now_naive = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo
    ss = SessionState(session_id=str(uuid4()), created_at=now_naive, updated_at=_now())
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer.to_dict(ss)


def test_to_dict_rejects_non_bool_memory_degraded():
    turn = TurnRecord(
        task_id=str(uuid4()),
        goal="g",
        final_answer=None,
        status=AgentStatus.FAILED,
        planned_actions=(),
        memory_degraded=1,          # int, not bool — type() is not bool
        memory_write_failed=False,
        disclosure_reasons=(),
        completed_at=_now(),
    )
    ss = _make_session()
    ss.turns.append(turn)
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer.to_dict(ss)


# ---------------------------------------------------------------------------
# from_dict validation errors
# ---------------------------------------------------------------------------

def test_from_dict_rejects_non_dict():
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer.from_dict("not a dict")  # type: ignore[arg-type]


def test_from_dict_rejects_list():
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer.from_dict([1, 2, 3])  # type: ignore[arg-type]


def test_from_dict_rejects_wrong_schema_version():
    ss = _make_session()
    d = SessionSerializer.to_dict(ss)
    d["schema_version"] = "99"
    with pytest.raises(SessionDataCorruptionError, match="schema_version"):
        SessionSerializer.from_dict(d)


def test_from_dict_rejects_extra_root_fields():
    ss = _make_session()
    d = SessionSerializer.to_dict(ss)
    d["extra_field"] = "not allowed"
    with pytest.raises(SessionDataCorruptionError, match="extra"):
        SessionSerializer.from_dict(d)


def test_from_dict_rejects_missing_root_fields():
    ss = _make_session()
    d = SessionSerializer.to_dict(ss)
    del d["session_id"]
    with pytest.raises(SessionDataCorruptionError, match="missing"):
        SessionSerializer.from_dict(d)


def test_from_dict_rejects_invalid_session_id():
    ss = _make_session()
    d = SessionSerializer.to_dict(ss)
    d["session_id"] = "not-a-uuid"
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer.from_dict(d)


def test_from_dict_rejects_non_list_turns():
    """RÀNG BUỘC APPROVAL: turns field is not a list → CorruptionError."""
    ss = _make_session()
    d = SessionSerializer.to_dict(ss)
    d["turns"] = "not a list"
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer.from_dict(d)


def test_from_dict_rejects_turns_as_dict():
    ss = _make_session()
    d = SessionSerializer.to_dict(ss)
    d["turns"] = {"0": "not a list element"}
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer.from_dict(d)


def test_from_dict_rejects_invalid_status_in_turn():
    ss = _make_session()
    t = _make_turn()
    ss.turns.append(t)
    ss.updated_at = t.completed_at
    d = SessionSerializer.to_dict(ss)
    d["turns"][0]["status"] = "invalid_status"
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer.from_dict(d)


def test_from_dict_rejects_invalid_turn_datetime():
    ss = _make_session()
    t = _make_turn()
    ss.turns.append(t)
    ss.updated_at = t.completed_at
    d = SessionSerializer.to_dict(ss)
    d["turns"][0]["completed_at"] = "not-a-date"
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer.from_dict(d)


def test_from_dict_rejects_non_dict_turn():
    ss = _make_session()
    t = _make_turn()
    ss.turns.append(t)
    ss.updated_at = t.completed_at
    d = SessionSerializer.to_dict(ss)
    d["turns"][0] = "not a dict"
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer.from_dict(d)


def test_from_dict_rejects_updated_before_created():
    ss = _make_session()
    d = SessionSerializer.to_dict(ss)
    # Swap timestamps so updated_at < created_at
    d["updated_at"] = "2020-01-01T00:00:00+00:00"
    d["created_at"] = "2030-01-01T00:00:00+00:00"
    with pytest.raises(SessionDataCorruptionError, match="updated_at"):
        SessionSerializer.from_dict(d)


# ---------------------------------------------------------------------------
# _require_aware
# ---------------------------------------------------------------------------

def test_require_aware_rejects_non_datetime():
    with pytest.raises(SessionDataCorruptionError):
        SessionSerializer._require_aware("2026-01-01", "field")


def test_require_aware_rejects_naive_datetime():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(SessionDataCorruptionError, match="naive"):
        SessionSerializer._require_aware(naive, "field")


def test_require_aware_accepts_utc_datetime():
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = SessionSerializer._require_aware(aware, "field")
    assert result is aware


# ---------------------------------------------------------------------------
# New invariant: non-empty turns → updated_at == turns[-1].completed_at
# ---------------------------------------------------------------------------

def test_load_rejects_inconsistent_updated_at():
    """Non-empty turns: updated_at != turns[-1].completed_at → CorruptionError."""
    ss = _make_session()
    turn = _make_turn()
    ss.turns.append(turn)
    ss.updated_at = turn.completed_at  # correct at serialization time
    d = SessionSerializer.to_dict(ss)
    # Mismatch: set updated_at to something other than turn.completed_at
    d["updated_at"] = "2030-01-01T00:00:00+00:00"
    with pytest.raises(SessionDataCorruptionError, match="updated_at"):
        SessionSerializer.from_dict(d)


def test_round_trip_preserves_order_with_equal_or_descending_timestamps():
    """Array position is authoritative; round-trip preserves insertion order
    even when all turns share the same completed_at timestamp."""
    now = _now()
    ss = SessionState(session_id=str(uuid4()), created_at=now, updated_at=now)
    for goal in ("first", "second", "third"):
        t = TurnRecord(
            task_id=str(uuid4()),
            goal=goal,
            final_answer="ok",
            status=AgentStatus.COMPLETED,
            planned_actions=(),
            memory_degraded=False,
            memory_write_failed=False,
            disclosure_reasons=(),
            completed_at=now,  # all same timestamp — order must come from array
        )
        ss.turns.append(t)
    ss.updated_at = now  # == turns[-1].completed_at ✓

    d = SessionSerializer.to_dict(ss)
    ss2 = SessionSerializer.from_dict(d)

    assert [t.goal for t in ss2.turns] == ["first", "second", "third"]

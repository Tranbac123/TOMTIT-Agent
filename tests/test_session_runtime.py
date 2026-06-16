from __future__ import annotations

import pytest

from agent_core.cli import run_interactive, should_exit
from agent_core.memory.contracts import ContextPack, WriteResponse
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.runtime.runtime_agent import RuntimeAgent, build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime
from agent_core.state.agent_state import AgentState, Step
from agent_core.state.enums import AgentStatus, ToolName


def _make_session() -> SessionRuntime:
    agent, store = build_local_agent()
    return SessionRuntime(agent, store)


# ---------------------------------------------------------------------------
# T1 — session_id is a non-empty string
# ---------------------------------------------------------------------------

def test_session_id_is_string():
    session = _make_session()
    assert isinstance(session.session_id, str)
    assert len(session.session_id) > 0


# ---------------------------------------------------------------------------
# T2 — same session_id across turns
# ---------------------------------------------------------------------------

def test_session_id_stable_across_turns():
    session = _make_session()
    state1 = session.handle_turn("Tính 1+1")
    state2 = session.handle_turn("Tính 2+2")
    assert state1.session_id == state2.session_id == session.session_id


# ---------------------------------------------------------------------------
# T3 — different task_id per turn
# ---------------------------------------------------------------------------

def test_task_id_differs_across_turns():
    session = _make_session()
    state1 = session.handle_turn("Tính 1+1")
    state2 = session.handle_turn("Tính 2+2")
    assert state1.task_id != state2.task_id


# ---------------------------------------------------------------------------
# T4 — store is shared: note written in turn 1 survives to turn 2
# ---------------------------------------------------------------------------

def test_store_shared_note_survives_across_turns():
    agent, store = build_local_agent()
    session = SessionRuntime(agent, store)

    # Turn 1: agent writes note "budget" via WRITE_NOTE tool
    state1 = session.handle_turn("Tính (15 + 5) * 3 rồi lưu vào ghi chú budget")
    assert store.read_note("budget") is not None, "turn 1 should write note to shared store"

    # Turn 2: unrelated goal — note must still be there (same store object)
    session.handle_turn("Tính 1+1")
    assert store.read_note("budget") is not None, "note must survive into turn 2"

    # Both states share the same store
    assert state1.memory is store


# ---------------------------------------------------------------------------
# T5 — memory_client injectable via RuntimeAgent kwarg (spy confirms call)
# ---------------------------------------------------------------------------

def test_memory_client_injectable_spy_receives_session_id():
    retrieve_calls: list[dict] = []

    class FakeMemoryClient:
        def retrieve_context_pack(
            self,
            goal: str,
            *,
            user_id=None,
            session_id=None,
            token_budget: int = 1500,
            max_items: int = 20,
        ) -> ContextPack:
            retrieve_calls.append({"goal": goal, "session_id": session_id})
            return ContextPack()

        def write_memory_candidates(
            self,
            candidates,
            *,
            user_id=None,
            session_id=None,
            task_id=None,
        ) -> WriteResponse:
            return WriteResponse()

    from agent_core.planning.rule_based_planner import RuleBasedPlanner
    from agent_core.tools.builtin_tools import FakeWebSearchClient
    from agent_core.tools.registry import build_tool_registry

    store = InMemoryStore()
    spy_agent = RuntimeAgent(
        planner=RuleBasedPlanner(),
        tools=build_tool_registry(FakeWebSearchClient()),
        memory_client=FakeMemoryClient(),
    )
    session = SessionRuntime(spy_agent, store)
    session.handle_turn("Tính 1+1")

    assert len(retrieve_calls) == 1
    assert retrieve_calls[0]["session_id"] == session.session_id


# ---------------------------------------------------------------------------
# T6 — should_exit: "/exit" → True
# ---------------------------------------------------------------------------

def test_should_exit_exit_command():
    assert should_exit("/exit") is True


# ---------------------------------------------------------------------------
# T7 — should_exit: "quit" → True
# ---------------------------------------------------------------------------

def test_should_exit_quit_command():
    assert should_exit("quit") is True


# ---------------------------------------------------------------------------
# T8 — should_exit: empty / whitespace → True; normal input → False
# ---------------------------------------------------------------------------

def test_should_exit_empty_and_whitespace():
    assert should_exit("") is True
    assert should_exit("   ") is True
    assert should_exit("Tính 1+1") is False
    assert should_exit("hello") is False


# ---------------------------------------------------------------------------
# T9 — run_interactive: session header printed, turn processed, /exit breaks loop
# ---------------------------------------------------------------------------

def test_run_interactive_session_header_and_exit():
    session = _make_session()
    inputs = iter(["Tính 1+1", "/exit"])
    output_lines: list[str] = []

    run_interactive(
        session,
        input_fn=lambda _: next(inputs),
        output_fn=output_lines.append,
    )

    # First line must be "Session: <session_id>"
    assert output_lines[0] == f"Session: {session.session_id}"
    # At least one more line (the agent answer for "Tính 1+1")
    assert len(output_lines) >= 3  # header + answer + exit message
    # Exit message printed
    assert any("Phiên kết thúc" in line for line in output_lines)


# ---------------------------------------------------------------------------
# T9b — run_interactive: EOF exits cleanly
# ---------------------------------------------------------------------------

def test_run_interactive_eof_exits_cleanly():
    session = _make_session()
    output_lines: list[str] = []

    def raise_eof(_):
        raise EOFError

    run_interactive(
        session,
        input_fn=raise_eof,
        output_fn=output_lines.append,
    )

    assert any("Phiên kết thúc" in line for line in output_lines)


# ---------------------------------------------------------------------------
# T10 — importing main does NOT call build_local_agent or run_interactive
# ---------------------------------------------------------------------------

def test_import_main_does_not_start_cli():
    import importlib
    import sys
    from unittest.mock import patch

    try:
        sys.modules.pop("main", None)
        with (
            patch("agent_core.runtime.runtime_agent.build_local_agent") as build_spy,
            patch("agent_core.cli.run_interactive") as cli_spy,
        ):
            importlib.import_module("main")
        build_spy.assert_not_called()
        cli_spy.assert_not_called()
    finally:
        sys.modules.pop("main", None)


# ---------------------------------------------------------------------------
# T11 — collection isolation: plan/errors/observations/slots are not shared
# ---------------------------------------------------------------------------

def test_task_state_collections_are_isolated_between_turns():
    session = _make_session()

    state1 = session.handle_turn("Tính 1+1")

    assert state1.plan is not None
    state1.slots["__turn_1_sentinel__"] = True

    state2 = session.handle_turn("Tính 2+2")

    assert state1.plan is not state2.plan
    assert state1.errors is not state2.errors
    assert state1.observations is not state2.observations
    assert state1.slots is not state2.slots
    assert "__turn_1_sentinel__" not in state2.slots


# ---------------------------------------------------------------------------
# T12 — exact shared-store identity: both turns receive the same store object
# ---------------------------------------------------------------------------

def test_both_turns_share_exact_store_reference():
    agent, store = build_local_agent()
    session = SessionRuntime(agent=agent, store=store)

    state1 = session.handle_turn("Tính 1+1")
    state2 = session.handle_turn("Tính 2+2")

    assert state1.memory is store
    assert state2.memory is store


# ---------------------------------------------------------------------------
# T13 — KeyboardInterrupt exits cleanly
# ---------------------------------------------------------------------------

def test_cli_exits_cleanly_on_keyboard_interrupt():
    session = _make_session()
    output_lines: list[str] = []

    def raise_keyboard_interrupt(_):
        raise KeyboardInterrupt

    run_interactive(
        session,
        input_fn=raise_keyboard_interrupt,
        output_fn=output_lines.append,
    )

    assert any("Phiên kết thúc" in line for line in output_lines)


# ---------------------------------------------------------------------------
# T14 — unexpected RuntimeError from handle_turn propagates, not swallowed
# ---------------------------------------------------------------------------

def test_cli_does_not_swallow_unexpected_exception():
    import pytest

    class FailingSession:
        session_id = "fake-session-id"

        def handle_turn(self, user_message: str):
            raise RuntimeError("unexpected internal error")

    output_lines: list[str] = []

    with pytest.raises(RuntimeError):
        run_interactive(
            session=FailingSession(),
            input_fn=lambda _: "hello",
            output_fn=output_lines.append,
        )


# ===========================================================================
# SR2 tests — S1–S20
# FakeAgent contract: mutate-and-return-injected-state (never return a different object)
# ===========================================================================

class _FakeAgent:
    """FakeAgent that applies mutate_fn to the injected state and returns it."""

    def __init__(self, mutate_fn):
        self._mutate = mutate_fn

    def run(self, state: AgentState) -> AgentState:
        self._mutate(state)
        return state   # return the SAME object SessionRuntime injected


def _make_fake_session(mutate_fn) -> SessionRuntime:
    store = InMemoryStore()
    return SessionRuntime(_FakeAgent(mutate_fn), store)


def _completed_mutate(state: AgentState) -> None:
    state.status = AgentStatus.COMPLETED
    state.done = True
    state.final_answer = "ok"


# ---------------------------------------------------------------------------
# S1 — handle_turn appends one record; goal matches; completed_at is tz-aware
# ---------------------------------------------------------------------------

def test_handle_turn_appends_one_record():
    session = _make_fake_session(_completed_mutate)
    session.handle_turn("my goal")

    history = session.get_history()
    assert len(history) == 1
    assert history[0].goal == "my goal"
    assert history[0].completed_at.tzinfo is not None   # timezone-aware UTC


# ---------------------------------------------------------------------------
# S2 — records accumulate in order; completed_at non-decreasing
# ---------------------------------------------------------------------------

def test_history_records_accumulate_in_order():
    session = _make_fake_session(_completed_mutate)
    session.handle_turn("turn A")
    session.handle_turn("turn B")
    session.handle_turn("turn C")

    history = session.get_history(limit=100)
    assert len(history) == 3
    assert history[0].goal == "turn A"
    assert history[1].goal == "turn B"
    assert history[2].goal == "turn C"
    assert history[0].completed_at <= history[1].completed_at <= history[2].completed_at


# ---------------------------------------------------------------------------
# S5 — planned_actions = full plan tuple (not filtered by max_steps or execution)
# ---------------------------------------------------------------------------

def test_planned_actions_is_full_plan_not_executed():
    def mutate(state: AgentState) -> None:
        state.plan = [
            Step(thought="calc", action=ToolName.CALCULATE),
            Step(thought="note", action=ToolName.WRITE_NOTE),
        ]
        state.status = AgentStatus.COMPLETED
        state.done = True
        state.final_answer = "done"

    session = _make_fake_session(mutate)
    session.handle_turn("two-step goal")

    record = session.get_history()[0]
    assert record.planned_actions == (ToolName.CALCULATE.value, ToolName.WRITE_NOTE.value)


# ---------------------------------------------------------------------------
# S6 — run() raising does NOT append a record; exception propagates
# ---------------------------------------------------------------------------

def test_run_raises_does_not_append_and_propagates():
    class _RaisingAgent:
        def run(self, state: AgentState) -> AgentState:
            raise RuntimeError("boom")

    session = SessionRuntime(_RaisingAgent(), InMemoryStore())

    with pytest.raises(RuntimeError, match="boom"):
        session.handle_turn("anything")

    assert len(session.get_history()) == 0


# ---------------------------------------------------------------------------
# S7 — non-terminal state from run() raises RuntimeError, does NOT append
# ---------------------------------------------------------------------------

def test_non_terminal_state_raises_runtimeerror():
    def mutate(state: AgentState) -> None:
        state.final_answer = "partial"
        # status stays CREATED (not terminal)

    session = _make_fake_session(mutate)

    with pytest.raises(RuntimeError, match="non-terminal"):
        session.handle_turn("anything")

    assert len(session.get_history()) == 0


# ---------------------------------------------------------------------------
# S8 — FAILED turn is recorded; record.final_answer is None (no raw error leak)
# ---------------------------------------------------------------------------

def test_failed_turn_is_recorded_with_null_answer():
    def mutate(state: AgentState) -> None:
        state.status = AgentStatus.FAILED
        state.done = True
        state.final_answer = "Tool error: internal secret details"

    session = _make_fake_session(mutate)
    session.handle_turn("failing goal")

    history = session.get_history()
    assert len(history) == 1
    record = history[0]
    assert record.status == AgentStatus.FAILED
    assert record.final_answer is None


# ---------------------------------------------------------------------------
# S13 — /status goes to get_status, NOT handle_turn
# ---------------------------------------------------------------------------

class _SpySession:
    def __init__(self, inner: SessionRuntime) -> None:
        self._inner = inner
        self.handle_turn_calls: list[str] = []
        self.get_status_calls: int = 0
        self.get_history_calls: int = 0

    @property
    def session_id(self) -> str:
        return self._inner.session_id

    def handle_turn(self, msg: str) -> AgentState:
        self.handle_turn_calls.append(msg)
        return self._inner.handle_turn(msg)

    def get_status(self):
        self.get_status_calls += 1
        return self._inner.get_status()

    def get_history(self, *, limit: int = 10):
        self.get_history_calls += 1
        return self._inner.get_history(limit=limit)


def test_cli_status_command_not_sent_to_handle_turn():
    spy = _SpySession(_make_fake_session(_completed_mutate))
    inputs = iter(["/status", "/exit"])

    run_interactive(spy, input_fn=lambda _: next(inputs), output_fn=lambda _: None)

    assert spy.handle_turn_calls == []
    assert spy.get_status_calls == 1


# ---------------------------------------------------------------------------
# S14 — /history goes to get_history, NOT handle_turn; empty → [history] no turns
# ---------------------------------------------------------------------------

def test_cli_history_command_not_sent_to_handle_turn():
    spy = _SpySession(_make_fake_session(_completed_mutate))
    inputs = iter(["/history", "/exit"])
    output_lines: list[str] = []

    run_interactive(spy, input_fn=lambda _: next(inputs), output_fn=output_lines.append)

    assert spy.handle_turn_calls == []
    assert spy.get_history_calls == 1
    assert any("[history] no turns" in line for line in output_lines)


# ---------------------------------------------------------------------------
# S15 — disclosure_reasons snapshotted directly, not re-derived from state signals
#        COUNTERFACTUAL: degraded=False + non-memory plan → re-derive would give ().
#        Record must keep the value that was actually set on state.disclosure_reasons.
# ---------------------------------------------------------------------------

def test_disclosure_reasons_snapshotted_not_derived():
    def mutate(state: AgentState) -> None:
        state.status = AgentStatus.COMPLETED
        state.done = True
        state.final_answer = "ok"
        state.memory_degraded = False        # re-derive condition is False
        state.memory_write_failed = False
        state.plan = [Step(thought="t", action=ToolName.CALCULATE)]  # non-memory tool
        state.disclosure_reasons = ["memory_degraded"]   # set directly — counterfactual

    session = _make_fake_session(mutate)
    session.handle_turn("some goal")

    record = session.get_history()[0]
    assert record.disclosure_reasons == ("memory_degraded",)


# ---------------------------------------------------------------------------
# S16 — memory_write_failed captured as-is from state (signal gốc)
# ---------------------------------------------------------------------------

def test_memory_write_failed_is_captured():
    def mutate(state: AgentState) -> None:
        state.status = AgentStatus.COMPLETED
        state.done = True
        state.final_answer = "ok"
        state.memory_write_failed = True

    session = _make_fake_session(mutate)
    session.handle_turn("any goal")

    record = session.get_history()[0]
    assert record.memory_write_failed is True


# ---------------------------------------------------------------------------
# S18 — TurnRecord is immutable snapshot: mutating AgentState after handle_turn
#        does not change the record (capture-then-assert-equality)
# ---------------------------------------------------------------------------

def test_snapshot_immutable_when_state_mutated_after():
    def mutate(state: AgentState) -> None:
        state.status = AgentStatus.COMPLETED
        state.done = True
        state.final_answer = "original answer"
        state.plan = [Step(thought="t", action=ToolName.CALCULATE)]
        state.disclosure_reasons = ["memory_degraded"]

    session = _make_fake_session(mutate)
    state = session.handle_turn("immutability goal")
    record = session.get_history()[0]

    # Capture before mutation (these must be non-empty per spec)
    orig_answer = record.final_answer           # "original answer"
    orig_disc = record.disclosure_reasons       # ("memory_degraded",) — non-empty
    orig_actions = record.planned_actions       # ("calculate",) — non-empty

    assert orig_disc != ()      # guard: non-empty before mutate
    assert orig_actions != ()   # guard: non-empty before mutate

    # Mutate AgentState after snapshot
    state.final_answer = "changed"
    state.disclosure_reasons.append("changed")
    state.plan.clear()

    # Record must retain original values (copy-by-value, not reference)
    assert record.final_answer == orig_answer
    assert record.disclosure_reasons == orig_disc
    assert record.planned_actions == orig_actions


# ---------------------------------------------------------------------------
# S20 — FAILED turn: raw exception text (sentinel) does NOT appear in any record field
# ---------------------------------------------------------------------------

def test_failed_turn_does_not_snapshot_raw_error_text():
    sentinel = "Tool error: https://secret-host/x failed"

    def mutate(state: AgentState) -> None:
        state.status = AgentStatus.FAILED
        state.done = True
        state.final_answer = sentinel   # raw exception text in final_answer

    session = _make_fake_session(mutate)
    session.handle_turn("normal goal")

    record = session.get_history()[0]
    assert record.final_answer is None
    assert sentinel not in record.goal
    assert not any(sentinel in a for a in record.planned_actions)
    assert not any(sentinel in r for r in record.disclosure_reasons)

from __future__ import annotations

from agent_core.cli import run_interactive, should_exit
from agent_core.memory.contracts import ContextPack, WriteResponse
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.runtime.runtime_agent import RuntimeAgent, build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime


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

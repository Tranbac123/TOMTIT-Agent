from __future__ import annotations

import pytest

from agent_core.confirmation.evidence_factory import make_confirmation_evidence
from agent_core.confirmation.models import ConfirmedDecision, ConfirmedSaveOperation
from agent_core.memory.contracts import MemoryCandidate, WriteResponse
from agent_core.memory.errors import RemoteMemoryWriteError
from agent_core.runtime.runtime_agent import RuntimeAgent
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus

TASK_ID = "task-1"
CONF_ID = "conf-1"
SESSION_ID = "sess-1"
USER_ID = "user-1"


def _operation(content="use postgres", task_id=TASK_ID, confirmation_id=CONF_ID, session_id=SESSION_ID):
    decision = ConfirmedDecision(
        confirmation_id=confirmation_id,
        content=content,
        confirmation_evidence=make_confirmation_evidence(
            task_id=task_id, confirmation_id=confirmation_id, content=content
        ),
    )
    return ConfirmedSaveOperation(
        request_id=f"memory-write:{confirmation_id}",
        task_id=task_id,
        session_id=session_id,
        decision=decision,
    )


def _state(operation, *, user_id=USER_ID):
    return AgentState(
        goal="Persist confirmed project decision",
        task_id=operation.task_id,
        user_id=user_id,
        session_id=operation.session_id,
        confirmed_save_operation=operation,
    )


class _ExplodingPlanner:
    def make_plan(self, state):  # pragma: no cover - must never be called
        raise AssertionError("planner must not be invoked during confirmed save")


class _SpyClient:
    def __init__(self, *, supports: bool, response=None, raise_exc=None):
        self._supports = supports
        self._response = response
        self._raise_exc = raise_exc
        self.write_calls: list[dict] = []
        self.retrieve_calls = 0

    @property
    def supports_required_write(self) -> bool:
        return self._supports

    def retrieve_context_pack(self, goal, **kw):  # pragma: no cover - must not be called here
        self.retrieve_calls += 1
        from agent_core.memory.contracts import ContextPack
        return ContextPack()

    def write_memory_candidates(self, candidates, *, user_id=None, session_id=None, task_id=None, request_id=None):
        self.write_calls.append(
            {
                "candidates": candidates,
                "user_id": user_id,
                "session_id": session_id,
                "task_id": task_id,
                "request_id": request_id,
            }
        )
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._response


def _agent(client):
    return RuntimeAgent(planner=_ExplodingPlanner(), tools={}, memory_client=client)


def _written_response():
    return WriteResponse(written_ids=["mem_1"], skipped=[])


def _skipped_response():
    return WriteResponse(written_ids=[], skipped=[CONF_ID])


# --- success paths ---------------------------------------------------------

def test_written_completes_with_safe_message():
    client = _SpyClient(supports=True, response=_written_response())
    op = _operation()
    state = _agent(client).run_confirmed_save(_state(op))
    assert state.status is AgentStatus.COMPLETED
    assert state.done is True
    assert "Decision saved." in state.final_answer
    assert "mem_1" in state.final_answer
    assert "user-explicit:task-1:conf-1" in state.final_answer
    assert state.memory_write_failed is False
    assert len(client.write_calls) == 1
    assert client.retrieve_calls == 0


def test_skipped_duplicate_completes():
    client = _SpyClient(supports=True, response=_skipped_response())
    state = _agent(client).run_confirmed_save(_state(_operation()))
    assert state.status is AgentStatus.COMPLETED
    assert "Decision already existed." in state.final_answer
    assert "user-explicit:task-1:conf-1" in state.final_answer


def test_request_id_and_correlation_passed():
    client = _SpyClient(supports=True, response=_written_response())
    op = _operation()
    _agent(client).run_confirmed_save(_state(op))
    call = client.write_calls[0]
    assert call["request_id"] == "memory-write:conf-1"
    assert call["task_id"] == TASK_ID
    assert call["session_id"] == SESSION_ID
    assert call["user_id"] == USER_ID
    assert len(call["candidates"]) == 1
    assert call["candidates"][0].metadata["candidate_id"] == CONF_ID


# --- fail-closed / no-write paths ------------------------------------------

def test_missing_operation_fails_before_client():
    client = _SpyClient(supports=True, response=_written_response())
    state = AgentState(goal="x", task_id=TASK_ID, user_id=USER_ID, session_id=SESSION_ID)
    out = _agent(client).run_confirmed_save(state)
    assert out.status is AgentStatus.FAILED
    assert out.final_answer == "Decision was not saved."
    assert client.write_calls == []
    assert out.memory_write_failed is False


def test_local_backend_fails_before_client():
    client = _SpyClient(supports=False, response=_written_response())
    out = _agent(client).run_confirmed_save(_state(_operation()))
    assert out.status is AgentStatus.FAILED
    assert out.final_answer == "Decision was not saved."
    assert client.write_calls == []
    assert out.memory_write_failed is False


def test_none_client_fails_before_client():
    out = _agent(None).run_confirmed_save(_state(_operation()))
    assert out.status is AgentStatus.FAILED
    assert out.final_answer == "Decision was not saved."


# --- failure paths after write attempt -------------------------------------

def test_backend_error_fails_safely():
    client = _SpyClient(supports=True, raise_exc=RemoteMemoryWriteError("remote down"))
    out = _agent(client).run_confirmed_save(_state(_operation()))
    assert out.status is AgentStatus.FAILED
    assert out.final_answer == "Decision was not saved."
    assert out.memory_write_failed is True
    # safe category only — no raw backend text leaks
    assert all("remote down" not in e for e in out.errors)


def test_inconsistent_response_fails_safely():
    client = _SpyClient(supports=True, response=WriteResponse(written_ids=[], skipped=[]))
    out = _agent(client).run_confirmed_save(_state(_operation()))
    assert out.status is AgentStatus.FAILED
    assert out.final_answer == "Decision was not saved."
    assert out.memory_write_failed is True


def test_terminal_state_triggers_zero_second_write():
    client = _SpyClient(supports=True, response=_written_response())
    agent = _agent(client)
    state = _state(_operation())
    agent.run_confirmed_save(state)
    assert len(client.write_calls) == 1
    # second call on a now-terminal state must not write again
    agent.run_confirmed_save(state)
    assert len(client.write_calls) == 1
    assert state.status is AgentStatus.COMPLETED


def test_no_retrieval_or_planner_invoked_on_success():
    client = _SpyClient(supports=True, response=_written_response())
    _agent(client).run_confirmed_save(_state(_operation()))
    assert client.retrieve_calls == 0  # planner is _ExplodingPlanner: would raise if called

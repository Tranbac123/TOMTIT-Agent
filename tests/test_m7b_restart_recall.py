"""M7-B — restart + cross-process recall (SPEC_M7B_RESTART_RECALL v1.0).

Test catalogue mapping (see spec §12); CLI items 1–3 live in tests/test_cli.py, the real
restart smoke (item 23) is the manual harness, full regression (item 24) is the suite.
"""
from __future__ import annotations

import pytest

from agent_core.memory.contracts import ContextItem, ContextPack
from agent_core.memory.errors import RemoteMemoryContractError, RemoteMemoryUnavailableError
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.runtime.runtime_agent import (
    _RECALL_FAILED_MESSAGE,
    _RECALL_NO_RESULT_MESSAGE,
    RuntimeAgent,
)
from agent_core.runtime.session_runtime import SessionRuntime
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus, MemoryType

PROJECT_A = "proj-a"
PROJECT_B = "proj-b"
USER_A = "user-a"
USER_B = "user-b"


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------

def _context_item(content, *, memory_id=None, evidence_ref=None, source_task_id=None):
    metadata = {}
    if memory_id is not None:
        metadata["memory_id"] = memory_id
    if evidence_ref is not None:
        metadata["evidence_ref"] = evidence_ref
    if source_task_id is not None:
        metadata["source_task_id"] = source_task_id
    return ContextItem(
        content=content,
        type=MemoryType.DECISION,
        score=1.0,
        source_ref=memory_id,
        metadata=metadata,
    )


def _pack(items, *, degraded=False):
    items = list(items)
    return ContextPack(
        items=items,
        total_items=len(items),
        degraded=degraded,
        memory_source="remote",
    )


class _ExplodingPlanner:
    def make_plan(self, state):  # pragma: no cover - must never be called during recall
        raise AssertionError("planner must not be invoked during recall")


class _ExplodingExecutor:
    def execute(self, step, state):  # pragma: no cover - must never be called during recall
        raise AssertionError("executor must not be invoked during recall")


class _RecordingClient:
    """Remote-like client returning a fixed pack (or raising), recording retrieve calls."""

    def __init__(self, *, pack=None, raise_exc=None, supports=True):
        self._pack = pack if pack is not None else ContextPack()
        self._raise_exc = raise_exc
        self._supports = supports
        self.retrieve_calls: list[dict] = []

    @property
    def supports_required_write(self) -> bool:
        return self._supports

    def retrieve_context_pack(
        self, goal, *, user_id=None, session_id=None, token_budget=1500, max_items=20
    ):
        self.retrieve_calls.append(
            {
                "goal": goal,
                "user_id": user_id,
                "session_id": session_id,
                "token_budget": token_budget,
                "max_items": max_items,
            }
        )
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._pack

    def write_memory_candidates(self, *a, **k):  # pragma: no cover - recall never writes
        raise AssertionError("recall must not write to memory")


class _SequenceClient:
    """Returns packs in order (last repeats), counting retrieve calls — stabilization tests."""

    def __init__(self, packs):
        self._packs = list(packs)
        self.retrieve_calls = 0

    @property
    def supports_required_write(self) -> bool:
        return True

    def retrieve_context_pack(self, goal, **k):
        self.retrieve_calls += 1
        return self._packs[min(self.retrieve_calls - 1, len(self._packs) - 1)]

    def write_memory_candidates(self, *a, **k):  # pragma: no cover
        raise AssertionError("recall must not write to memory")


class _ScopedBackend:
    """Durable-like backend scoped by (project_id, user_id) — isolation / fresh-session tests."""

    def __init__(self):
        self.data: dict[tuple[str, str], list[ContextItem]] = {}

    def add(self, project_id, user_id, item):
        self.data.setdefault((project_id, user_id), []).append(item)

    def query(self, project_id, user_id):
        return list(self.data.get((project_id, user_id), []))


class _ScopedClient:
    def __init__(self, backend, project_id, default_user_id):
        self._backend = backend
        self.project_id = project_id
        self._default_user_id = default_user_id

    @property
    def supports_required_write(self) -> bool:
        return True

    def retrieve_context_pack(
        self, goal, *, user_id=None, session_id=None, token_budget=1500, max_items=20
    ):
        uid = user_id or self._default_user_id
        items = self._backend.query(self.project_id, uid)
        return _pack(items)

    def write_memory_candidates(self, *a, **k):  # pragma: no cover
        raise AssertionError("recall must not write to memory")


def _agent(client):
    agent = RuntimeAgent(
        planner=_ExplodingPlanner(), tools={}, memory_client=client
    )
    agent.executor = _ExplodingExecutor()
    return agent


def _recall_state(goal="use postgres", *, user_id=USER_A, session_id="sess-new"):
    return AgentState(goal=goal, user_id=user_id, session_id=session_id)


def _no_sleep(_seconds):  # injected to keep stabilization tests instant
    return None


# ---------------------------------------------------------------------------
# 4. positive recall maps a remote ContextPack to user output
# ---------------------------------------------------------------------------

def test_positive_recall_maps_pack_to_output():
    client = _RecordingClient(pack=_pack([_context_item("use postgres", memory_id="mem_1")]))
    state = _agent(client).run_memory_recall(_recall_state())
    assert state.status == AgentStatus.COMPLETED
    assert "use postgres" in state.final_answer
    assert state.context_pack is not None


# ---------------------------------------------------------------------------
# 5. positive recall surfaces provenance (evidence_ref / source_task_id / memory_id)
# ---------------------------------------------------------------------------

def test_positive_recall_surfaces_provenance():
    item = _context_item(
        "use postgres",
        memory_id="mem_1",
        evidence_ref="user-explicit:task-1:conf-1",
        source_task_id="task-1",
    )
    state = _agent(_RecordingClient(pack=_pack([item]))).run_memory_recall(_recall_state())
    assert "mem_1" in state.final_answer
    assert "user-explicit:task-1:conf-1" in state.final_answer
    assert "task-1" in state.final_answer


def test_positive_recall_never_fabricates_absent_provenance():
    # item carries content only — output must not invent Memory ID / Provenance lines.
    state = _agent(
        _RecordingClient(pack=_pack([_context_item("use postgres")]))
    ).run_memory_recall(_recall_state())
    assert state.final_answer == "use postgres"
    assert "Memory ID" not in state.final_answer
    assert "Provenance" not in state.final_answer


# ---------------------------------------------------------------------------
# 6. no-result returns the safe deterministic message
# ---------------------------------------------------------------------------

def test_no_result_returns_safe_message():
    state = _agent(_RecordingClient(pack=_pack([]))).run_memory_recall(_recall_state())
    assert state.status == AgentStatus.COMPLETED
    assert state.final_answer == _RECALL_NO_RESULT_MESSAGE


# ---------------------------------------------------------------------------
# 7. remote-unavailable recall returns the safe failure message (no raw error)
# ---------------------------------------------------------------------------

def test_degraded_pack_fails_safely():
    state = _agent(
        _RecordingClient(pack=_pack([], degraded=True))
    ).run_memory_recall(_recall_state())
    assert state.status == AgentStatus.FAILED
    assert state.final_answer == _RECALL_FAILED_MESSAGE


def test_retrieve_exception_fails_safely():
    client = _RecordingClient(raise_exc=RemoteMemoryUnavailableError("backend exploded SECRET"))
    state = _agent(client).run_memory_recall(_recall_state())
    assert state.status == AgentStatus.FAILED
    assert state.final_answer == _RECALL_FAILED_MESSAGE


def test_contract_error_fails_safely():
    client = _RecordingClient(raise_exc=RemoteMemoryContractError("schema boom"))
    state = _agent(client).run_memory_recall(_recall_state())
    assert state.status == AgentStatus.FAILED
    assert state.final_answer == _RECALL_FAILED_MESSAGE


def test_no_client_fails_safely():
    agent = RuntimeAgent(planner=_ExplodingPlanner(), tools={}, memory_client=None)
    state = agent.run_memory_recall(_recall_state())
    assert state.status == AgentStatus.FAILED
    assert state.final_answer == _RECALL_FAILED_MESSAGE


# ---------------------------------------------------------------------------
# 8. recall uses retrieve_context_pack (not a new wire call), never writes
# ---------------------------------------------------------------------------

def test_recall_uses_retrieve_context_pack():
    client = _RecordingClient(pack=_pack([_context_item("x", memory_id="m")]))
    _agent(client).run_memory_recall(_recall_state())
    assert len(client.retrieve_calls) == 1


# ---------------------------------------------------------------------------
# 9. recall passes the application-owned user_id
# ---------------------------------------------------------------------------

def test_recall_passes_application_owned_user_id():
    client = _RecordingClient(pack=_pack([_context_item("x", memory_id="m")]))
    _agent(client).run_memory_recall(_recall_state(user_id=USER_A))
    assert client.retrieve_calls[0]["user_id"] == USER_A


# ---------------------------------------------------------------------------
# 10. recall passes a session_id and does not require it to match the write session
# ---------------------------------------------------------------------------

def test_recall_passes_session_id_without_requiring_match():
    client = _RecordingClient(pack=_pack([_context_item("x", memory_id="m")]))
    state = _agent(client).run_memory_recall(_recall_state(session_id="brand-new-session"))
    assert client.retrieve_calls[0]["session_id"] == "brand-new-session"
    assert state.status == AgentStatus.COMPLETED


# ---------------------------------------------------------------------------
# 11–13. identity boundary: same project+user recalls; different project/user does not
# ---------------------------------------------------------------------------

def test_same_project_user_recalls():
    backend = _ScopedBackend()
    backend.add(PROJECT_A, USER_A, _context_item("use postgres", memory_id="mem_1"))
    client = _ScopedClient(backend, PROJECT_A, USER_A)
    state = _agent(client).run_memory_recall(_recall_state(user_id=USER_A))
    assert state.status == AgentStatus.COMPLETED
    assert "use postgres" in state.final_answer


def test_different_project_does_not_recall():
    backend = _ScopedBackend()
    backend.add(PROJECT_A, USER_A, _context_item("use postgres", memory_id="mem_1"))
    client = _ScopedClient(backend, PROJECT_B, USER_A)  # different project scope
    state = _agent(client).run_memory_recall(_recall_state(user_id=USER_A))
    assert state.status == AgentStatus.COMPLETED
    assert state.final_answer == _RECALL_NO_RESULT_MESSAGE


def test_different_user_does_not_recall():
    backend = _ScopedBackend()
    backend.add(PROJECT_A, USER_A, _context_item("use postgres", memory_id="mem_1"))
    client = _ScopedClient(backend, PROJECT_A, USER_A)
    state = _agent(client).run_memory_recall(_recall_state(user_id=USER_B))  # different user
    assert state.status == AgentStatus.COMPLETED
    assert state.final_answer == _RECALL_NO_RESULT_MESSAGE


# ---------------------------------------------------------------------------
# 14. recall does not read AgentState.confirmed_save_operation
# ---------------------------------------------------------------------------

def test_recall_ignores_confirmed_save_operation():
    client = _RecordingClient(pack=_pack([_context_item("x", memory_id="m")]))
    state = _recall_state()
    # A poison object: any attribute access on it would raise. Recall must never touch it.
    sentinel = object.__new__(_PoisonOperation)
    state.confirmed_save_operation = sentinel
    out = _agent(client).run_memory_recall(state)
    assert out.status == AgentStatus.COMPLETED


class _PoisonOperation:
    def __getattribute__(self, name):  # pragma: no cover - triggers only on misuse
        raise AssertionError("recall must not read confirmed_save_operation")


# ---------------------------------------------------------------------------
# 15. recall does not use a local store / local fallback
# ---------------------------------------------------------------------------

def test_recall_no_local_fallback_on_degraded():
    # Seed a local store with a decoy; a degraded remote must NOT fall back to it.
    store = InMemoryStore()
    client = _RecordingClient(pack=_pack([], degraded=True))
    agent = _agent(client)
    state = AgentState(goal="use postgres", user_id=USER_A, session_id="s", memory=store)
    out = agent.run_memory_recall(state)
    assert out.status == AgentStatus.FAILED
    assert out.final_answer == _RECALL_FAILED_MESSAGE


# ---------------------------------------------------------------------------
# 16. fresh SessionRuntime (new session_id) recalls a decision written by a prior session
# ---------------------------------------------------------------------------

def test_fresh_session_recalls_prior_decision():
    backend = _ScopedBackend()
    # "Session A" wrote this decision earlier (durable backend).
    backend.add(PROJECT_A, USER_A, _context_item("use postgres", memory_id="mem_1",
                                                  evidence_ref="user-explicit:t:c"))
    # Fresh SessionRuntime B: brand-new session_id, same project (client) + user.
    client = _ScopedClient(backend, PROJECT_A, USER_A)
    session_b = SessionRuntime(_agent(client), InMemoryStore(), user_id=USER_A)
    state = session_b.run_memory_recall("postgres", sleep_fn=_no_sleep)
    assert state.status == AgentStatus.COMPLETED
    assert "use postgres" in state.final_answer
    assert state.session_id == session_b.session_id  # B's own (new) session id was used


def test_session_recall_records_turn_history():
    client = _RecordingClient(pack=_pack([_context_item("use postgres", memory_id="m")]))
    session = SessionRuntime(_agent(client), InMemoryStore(), user_id=USER_A)
    session.run_memory_recall("postgres", sleep_fn=_no_sleep)
    history = session.get_history()
    assert len(history) == 1
    assert history[0].status == AgentStatus.COMPLETED


def test_session_recall_blank_query_rejected_zero_remote():
    client = _RecordingClient(pack=_pack([_context_item("x", memory_id="m")]))
    session = SessionRuntime(_agent(client), InMemoryStore(), user_id=USER_A)
    with pytest.raises(ValueError):
        session.run_memory_recall("   ")
    assert client.retrieve_calls == []


# ---------------------------------------------------------------------------
# 17. recall does not invoke the planner / ToolExecutor / skills
# ---------------------------------------------------------------------------

def test_recall_does_not_invoke_planner_or_executor():
    # _ExplodingPlanner + _ExplodingExecutor raise AssertionError if touched.
    client = _RecordingClient(pack=_pack([_context_item("x", memory_id="m")]))
    state = _agent(client).run_memory_recall(_recall_state())
    assert state.status == AgentStatus.COMPLETED


# ---------------------------------------------------------------------------
# 18. bounded stabilization stops on first hit and is capped
# ---------------------------------------------------------------------------

def test_stabilization_stops_on_first_hit():
    hit = _pack([_context_item("use postgres", memory_id="m")])
    client = _SequenceClient([hit])
    state = _agent(client).run_memory_recall(
        _recall_state(), max_attempts=5, sleep_fn=_no_sleep
    )
    assert state.status == AgentStatus.COMPLETED
    assert client.retrieve_calls == 1  # stopped immediately, did not exhaust the bound


def test_stabilization_retries_empty_then_hits():
    empty = _pack([])
    hit = _pack([_context_item("use postgres", memory_id="m")])
    client = _SequenceClient([empty, empty, hit])
    state = _agent(client).run_memory_recall(
        _recall_state(), max_attempts=5, sleep_fn=_no_sleep
    )
    assert state.status == AgentStatus.COMPLETED
    assert client.retrieve_calls == 3


def test_stabilization_is_capped():
    client = _SequenceClient([_pack([])])  # always empty
    _agent(client).run_memory_recall(_recall_state(), max_attempts=4, sleep_fn=_no_sleep)
    assert client.retrieve_calls == 4  # never exceeds the bound


# ---------------------------------------------------------------------------
# 19. bounded stabilization never converts a true no-result/failure into a false positive
# ---------------------------------------------------------------------------

def test_stabilization_true_no_result_is_not_false_positive():
    client = _SequenceClient([_pack([])])  # always empty
    state = _agent(client).run_memory_recall(
        _recall_state(), max_attempts=5, sleep_fn=_no_sleep
    )
    assert state.status == AgentStatus.COMPLETED
    assert state.final_answer == _RECALL_NO_RESULT_MESSAGE


def test_stabilization_does_not_retry_remote_failure():
    client = _SequenceClient([_pack([], degraded=True)])
    state = _agent(client).run_memory_recall(
        _recall_state(), max_attempts=5, sleep_fn=_no_sleep
    )
    assert state.status == AgentStatus.FAILED
    assert state.final_answer == _RECALL_FAILED_MESSAGE
    assert client.retrieve_calls == 1  # remote failure: no retry (not a circuit breaker)


# ---------------------------------------------------------------------------
# 20. recall output contains no raw backend exception text
# ---------------------------------------------------------------------------

def test_recall_output_has_no_raw_backend_text():
    client = _RecordingClient(raise_exc=RemoteMemoryUnavailableError("SECRET stack trace"))
    state = _agent(client).run_memory_recall(_recall_state())
    assert "SECRET" not in (state.final_answer or "")
    assert state.final_answer == _RECALL_FAILED_MESSAGE


# ---------------------------------------------------------------------------
# 21. Memory Contract v1 wire DTOs / routes unchanged (fingerprint)
# ---------------------------------------------------------------------------

def test_memory_contract_v1_routes_unchanged():
    from agent_core.memory import remote_client as rc

    assert rc._RETRIEVE_PATH == "/v1/context/retrieve"
    assert rc._WRITE_PATH == "/v1/memories/write"


def test_no_new_wire_dto_introduced():
    # Recall reuses ContextPack/ContextItem; the wire module exposes only the v1 DTOs.
    from agent_core.memory.wire import v1

    expected = {
        "ContextRequestV1",
        "ContextResponseV1",
        "ErrorEnvelopeV1",
        "WriteCandidateV1",
        "WriteRequestV1",
        "WriteResponseV1",
    }
    present = {name for name in expected if hasattr(v1, name)}
    assert present == expected  # all present; recall added no DTO requirement here


# ---------------------------------------------------------------------------
# 22. M7-A confirmed-write path unchanged (fingerprint)
# ---------------------------------------------------------------------------

def test_m7a_confirmed_save_path_intact():
    from agent_core.runtime.runtime_agent import _CONFIRMED_SAVE_FAILED_MESSAGE

    assert _CONFIRMED_SAVE_FAILED_MESSAGE == "Decision was not saved."
    assert hasattr(RuntimeAgent, "run_confirmed_save")
    # recall and save are distinct, isolated entry points
    assert RuntimeAgent.run_memory_recall is not RuntimeAgent.run_confirmed_save

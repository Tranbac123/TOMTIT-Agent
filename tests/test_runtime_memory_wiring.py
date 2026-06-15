from __future__ import annotations

import pytest

from agent_core.memory.contracts import ContextItem, ContextPack, MemoryCandidate, WriteResponse
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.memory.local_client import LocalMemoryClient
from agent_core.memory.memory_records import MemoryRecord
from agent_core.output.final_composer import DefaultFinalComposer
from agent_core.planning.rule_based_planner import RuleBasedPlanner
from agent_core.runtime.runtime_agent import (
    RuntimeAgent,
    _DISCLOSURE_TEXT,
    append_disclosures,
    build_local_agent,
)
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus, MemoryType
from agent_core.tools.builtin_tools import FakeWebSearchClient
from agent_core.tools.registry import build_tool_registry


# ---------------------------------------------------------------------------
# Spy helpers
# ---------------------------------------------------------------------------

class SpyMemoryClient:
    """Records calls; optionally raises on retrieve or write."""

    def __init__(
        self,
        pack: ContextPack | None = None,
        raise_on_retrieve: bool = False,
        raise_on_write: bool = False,
    ) -> None:
        self.retrieve_calls: list[str] = []
        self.write_calls: list[list[MemoryCandidate]] = []
        self._pack = pack or ContextPack(degraded=True, memory_source="local")
        self._raise_on_retrieve = raise_on_retrieve
        self._raise_on_write = raise_on_write

    def retrieve_context_pack(self, goal, *, user_id=None, session_id=None, token_budget=1500, max_items=20):
        self.retrieve_calls.append(goal)
        if self._raise_on_retrieve:
            raise RuntimeError("retrieve failed (test)")
        return self._pack

    def write_memory_candidates(self, candidates, *, user_id=None, session_id=None, task_id=None):
        self.write_calls.append(list(candidates))
        if self._raise_on_write:
            raise RuntimeError("write failed (test)")
        return WriteResponse()


def _pack_with_items(degraded: bool = True) -> ContextPack:
    return ContextPack(
        degraded=degraded,
        memory_source="local" if degraded else "remote",
        items=[ContextItem(content="relevant context", type=MemoryType.NOTE)],
        total_items=1,
    )


def _make_agent(memory_client=None, planner=None):
    tools = build_tool_registry(FakeWebSearchClient())
    return RuntimeAgent(
        planner=planner or RuleBasedPlanner(),
        tools=tools,
        memory_client=memory_client,
    )


# ---------------------------------------------------------------------------
# 1. Retrieve called before plan
# ---------------------------------------------------------------------------

def test_retrieve_called_before_plan():
    call_order: list[str] = []

    class TrackingClient:
        def retrieve_context_pack(self, goal, **kw):
            call_order.append("retrieve")
            return ContextPack(degraded=True, memory_source="local")

        def write_memory_candidates(self, candidates, **kw):
            return WriteResponse()

    class TrackingPlanner:
        def __init__(self):
            self._base = RuleBasedPlanner()

        def make_plan(self, state):
            call_order.append("make_plan")
            return self._base.make_plan(state)

    agent = _make_agent(memory_client=TrackingClient(), planner=TrackingPlanner())
    state = AgentState(goal="Tính 2+2")
    agent.run(state)

    assert "retrieve" in call_order
    assert "make_plan" in call_order
    assert call_order.index("retrieve") < call_order.index("make_plan")


# ---------------------------------------------------------------------------
# 2. Degraded pack sets state flag
# ---------------------------------------------------------------------------

def test_degraded_pack_sets_state_flag():
    agent = _make_agent(memory_client=SpyMemoryClient())  # default pack: degraded=True
    state = AgentState(goal="Tính 2+2")
    agent.run(state)

    assert state.memory_degraded is True


# ---------------------------------------------------------------------------
# 3. memory_degraded is monotonic (only rises)
# ---------------------------------------------------------------------------

def test_degraded_monotonic():
    non_degraded = ContextPack(degraded=False, memory_source="remote")
    agent = _make_agent(memory_client=SpyMemoryClient(pack=non_degraded))
    state = AgentState(goal="Tính 2+2")
    state.memory_degraded = True   # already degraded from before this run

    agent.run(state)

    # non-degraded pack must NOT reset the flag
    assert state.memory_degraded is True


# ---------------------------------------------------------------------------
# 4. _finalize_run runs exactly once (idempotency guard QĐ-1)
# ---------------------------------------------------------------------------

def test_finalize_runs_once():
    complete_calls: list[str] = []

    class CountingState(AgentState):
        def complete(self, answer: str) -> None:
            complete_calls.append(answer)
            super().complete(answer)

    agent = _make_agent(memory_client=SpyMemoryClient())
    state = CountingState(goal="Tính 2+2")
    agent.run(state)

    assert len(complete_calls) == 1
    assert state.status == AgentStatus.COMPLETED


# ---------------------------------------------------------------------------
# 5. FINISH tool does NOT call state.complete() directly (QĐ-1)
# ---------------------------------------------------------------------------

def test_finish_tool_does_not_complete_directly():
    agent = _make_agent()
    state = AgentState(goal="Tính 2+2")
    state.plan = RuleBasedPlanner().make_plan(state)   # pre-build plan

    # call _execute_plan only — no _finalize_run
    agent._execute_plan(state)

    # FINISH step ran; complete() was NOT called (finalize hasn't run yet)
    assert state.done is False
    assert state.last_result is not None   # executor set this


# ---------------------------------------------------------------------------
# 6. write_memory_candidates called during finalize
# ---------------------------------------------------------------------------

def test_write_after_finish():
    spy_client = SpyMemoryClient()

    class AgentWithCandidates(RuntimeAgent):
        def _collect_candidates(self, state):
            return [MemoryCandidate(type=MemoryType.FACT, content="auto fact")]

    tools = build_tool_registry(FakeWebSearchClient())
    agent = AgentWithCandidates(
        planner=RuleBasedPlanner(),
        tools=tools,
        memory_client=spy_client,
    )
    state = AgentState(goal="Tính 2+2")
    agent.run(state)

    assert len(spy_client.write_calls) == 1
    assert state.status == AgentStatus.COMPLETED


# ---------------------------------------------------------------------------
# 7. Write failure does not fail the task
# ---------------------------------------------------------------------------

def test_write_failure_not_fatal():
    spy_client = SpyMemoryClient(raise_on_write=True)

    class AgentWithCandidates(RuntimeAgent):
        def _collect_candidates(self, state):
            return [MemoryCandidate(type=MemoryType.FACT, content="fact")]

    tools = build_tool_registry(FakeWebSearchClient())
    agent = AgentWithCandidates(
        planner=RuleBasedPlanner(),
        tools=tools,
        memory_client=spy_client,
    )
    state = AgentState(goal="Tính 2+2")
    agent.run(state)

    assert state.memory_write_failed is True
    assert state.status == AgentStatus.COMPLETED
    assert state.final_answer is not None


# ---------------------------------------------------------------------------
# 8. Disclosure when degraded + task touches memory
# ---------------------------------------------------------------------------

def test_disclosure_when_degraded_and_touches_memory():
    # degraded + plan has WRITE_NOTE → _task_touches_memory = True → disclose
    spy_client = SpyMemoryClient(pack=_pack_with_items(degraded=True))
    agent = _make_agent(memory_client=spy_client)
    state = AgentState(goal="Tính (15+5)*3 rồi lưu vào ghi chú budget")
    agent.run(state)

    assert state.memory_degraded is True
    assert "memory_degraded" in state.disclosure_reasons
    assert _DISCLOSURE_TEXT["memory_degraded"] in state.final_answer


# ---------------------------------------------------------------------------
# 9. No disclosure when pack not degraded
# ---------------------------------------------------------------------------

def test_no_disclosure_when_not_degraded():
    non_degraded = ContextPack(degraded=False, memory_source="remote")
    spy_client = SpyMemoryClient(pack=non_degraded)
    agent = _make_agent(memory_client=spy_client)
    state = AgentState(goal="Tính 2+2")
    agent.run(state)

    assert state.memory_degraded is False
    assert state.disclosure_reasons == []


# ---------------------------------------------------------------------------
# 10. memory_client=None → no crash, no retrieve/write
# ---------------------------------------------------------------------------

def test_memory_client_none_no_crash():
    agent = _make_agent(memory_client=None)
    state = AgentState(goal="Tính 2+2")
    agent.run(state)

    assert state.status == AgentStatus.COMPLETED
    assert state.context_pack is None
    assert state.memory_degraded is False


# ---------------------------------------------------------------------------
# 11. Shared store — no split brain (QĐ-2)
# ---------------------------------------------------------------------------

def test_shared_store_no_split_brain():
    store = InMemoryStore()
    memory_client = LocalMemoryClient(store)

    # Seed a record directly via shared store (as a built-in tool would)
    rec = MemoryRecord(content="shared content", type=MemoryType.FACT)
    store.write(rec)

    agent = _make_agent(memory_client=memory_client)
    state = AgentState(goal="Tính 2+2", memory=store)
    agent.run(state)

    # retrieve (pre-plan) found the seeded record via the shared store
    assert state.context_pack is not None
    assert any(item.content == "shared content" for item in state.context_pack.items)


# ---------------------------------------------------------------------------
# 12. context_pack is a field, NOT in state.slots (QĐ-3)
# ---------------------------------------------------------------------------

def test_context_pack_is_field_not_slots():
    spy_client = SpyMemoryClient()
    agent = _make_agent(memory_client=spy_client)
    state = AgentState(goal="Tính 2+2")
    agent.run(state)

    assert isinstance(state.context_pack, ContextPack)
    assert "context_pack" not in state.slots


# ---------------------------------------------------------------------------
# 13. No import cycle (TYPE_CHECKING guard works)
# ---------------------------------------------------------------------------

def test_no_import_cycle():
    import importlib
    mod_state = importlib.import_module("agent_core.state.agent_state")
    mod_contracts = importlib.import_module("agent_core.memory.contracts")
    assert hasattr(mod_state, "AgentState")
    assert hasattr(mod_contracts, "ContextPack")


# ---------------------------------------------------------------------------
# 14. Mutating tool runs under memory_degraded (QĐ-4 protection)
# ---------------------------------------------------------------------------

def test_mutating_tool_runs_under_memory_degraded():
    # LocalMemoryClient always degraded=True. write_note (mutating) MUST still run.
    store = InMemoryStore()
    memory_client = LocalMemoryClient(store)
    tools = build_tool_registry(FakeWebSearchClient())
    agent = RuntimeAgent(
        planner=RuleBasedPlanner(),
        tools=tools,
        memory_client=memory_client,
    )
    # compound goal: CALCULATE → WRITE_NOTE → FINISH
    state = AgentState(goal="Tính (15+5)*3 rồi lưu vào ghi chú budget", memory=store)
    agent.run(state)

    assert state.memory_degraded is True                  # local always degraded
    assert state.status == AgentStatus.COMPLETED          # task completed (not blocked)
    assert store.read_note("budget") is not None          # write_note ran successfully


# ---------------------------------------------------------------------------
# 15. Retrieve failure → state.fail before plan (§3b)
# ---------------------------------------------------------------------------

def test_retrieve_failure_fails_before_plan():
    planner_calls: list[str] = []

    class TrackingPlanner:
        def __init__(self):
            self._base = RuleBasedPlanner()
        def make_plan(self, state):
            planner_calls.append("make_plan")
            return self._base.make_plan(state)

    spy_client = SpyMemoryClient(raise_on_retrieve=True)
    agent = _make_agent(memory_client=spy_client, planner=TrackingPlanner())
    state = AgentState(goal="Tính 2+2")
    agent.run(state)

    assert state.status == AgentStatus.FAILED
    assert planner_calls == []                            # planner never called
    assert "memory retrieve failed" in state.final_answer


# ---------------------------------------------------------------------------
# 16. append_disclosures helper (pure, deterministic)
# ---------------------------------------------------------------------------

def test_append_disclosures_helper():
    # empty reasons → unchanged
    assert append_disclosures("answer", []) == "answer"

    # known reason → appended
    result = append_disclosures("answer", ["memory_degraded"])
    assert "answer" in result
    assert _DISCLOSURE_TEXT["memory_degraded"] in result

    # multiple reasons → both appended
    result2 = append_disclosures("ans", ["memory_degraded", "memory_write_failed"])
    assert _DISCLOSURE_TEXT["memory_degraded"] in result2
    assert _DISCLOSURE_TEXT["memory_write_failed"] in result2

    # unknown reason → silently ignored
    assert append_disclosures("ans", ["nonexistent_reason"]) == "ans"


# ---------------------------------------------------------------------------
# 17. Write fail → disclose when user expected persistence
# ---------------------------------------------------------------------------

def test_write_failure_sets_disclosure_when_expected_persistence():
    # plan has WRITE_NOTE (user expected persistence) + write raises → disclose
    spy_client = SpyMemoryClient(raise_on_write=True)

    class AgentWithCandidates(RuntimeAgent):
        def _collect_candidates(self, state):
            return [MemoryCandidate(type=MemoryType.FACT, content="fact")]

    tools = build_tool_registry(FakeWebSearchClient())
    agent = AgentWithCandidates(
        planner=RuleBasedPlanner(),
        tools=tools,
        memory_client=spy_client,
    )
    # compound: plan has WRITE_NOTE → _user_expected_persistence = True
    state = AgentState(goal="Tính (15+5)*3 rồi lưu vào ghi chú budget")
    agent.run(state)

    assert state.memory_write_failed is True
    assert "memory_write_failed" in state.disclosure_reasons
    assert state.status == AgentStatus.COMPLETED


# ---------------------------------------------------------------------------
# 18. Write fail → NO disclose when task has no persistence expectation
# ---------------------------------------------------------------------------

def test_write_failure_no_disclosure_when_no_persistence():
    # pure CALCULATE goal → no WRITE_NOTE in plan → no disclosure even if write fails
    spy_client = SpyMemoryClient(raise_on_write=True)

    class AgentWithCandidates(RuntimeAgent):
        def _collect_candidates(self, state):
            return [MemoryCandidate(type=MemoryType.FACT, content="fact")]

    tools = build_tool_registry(FakeWebSearchClient())
    agent = AgentWithCandidates(
        planner=RuleBasedPlanner(),
        tools=tools,
        memory_client=spy_client,
    )
    state = AgentState(goal="Tính 2+2")
    agent.run(state)

    assert state.memory_write_failed is True
    assert "memory_write_failed" not in state.disclosure_reasons
    assert state.status == AgentStatus.COMPLETED


# ---------------------------------------------------------------------------
# 19. Regression: Calculate + seeded store → NO degraded disclosure (bug fix)
# ---------------------------------------------------------------------------

def test_no_disclosure_for_calculate_even_when_store_has_items():
    # Bug (pre-fix): _task_touches_memory checked context_pack.items instead of plan.
    # LocalMemoryClient returns full store → Calculate task got false disclosure when
    # store was non-empty. After fix: disclosure is plan-based, not context-pack-based.
    store = InMemoryStore()
    store.write(MemoryRecord(content="unrelated note", type=MemoryType.NOTE))

    memory_client = LocalMemoryClient(store)
    agent = _make_agent(memory_client=memory_client)
    state = AgentState(goal="Tính 2+2", memory=store)
    agent.run(state)

    # store has items → context_pack.items is non-empty
    assert state.context_pack is not None
    assert len(state.context_pack.items) > 0
    # BUT plan has no memory action → no disclosure
    assert "memory_degraded" not in state.disclosure_reasons
    assert state.status == AgentStatus.COMPLETED


# ---------------------------------------------------------------------------
# 20. Disclosure for READ_NOTE goal (plan-based, not context-pack-based)
# ---------------------------------------------------------------------------

def test_disclosure_when_plan_has_read_note():
    # read_note goal → plan has READ_NOTE → _MEMORY_PLAN_ACTIONS → disclose if degraded
    store = InMemoryStore()
    store.write_note("budget", "60.0")
    memory_client = LocalMemoryClient(store)
    agent = _make_agent(memory_client=memory_client)
    state = AgentState(goal="Đọc ghi chú budget", memory=store)
    agent.run(state)

    assert state.memory_degraded is True          # local always degraded
    assert "memory_degraded" in state.disclosure_reasons

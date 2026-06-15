from __future__ import annotations

import pytest

from agent_core.memory.contracts import ContextItem, ContextPack
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.memory.local_client import LocalMemoryClient
from agent_core.memory.memory_records import MemoryRecord
from agent_core.planning.intents import IntentName
from agent_core.planning.rule_based_planner import RuleBasedPlanner
from agent_core.runtime.runtime_agent import RuntimeAgent, build_local_agent
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus, MemoryType, ToolName
from agent_core.tools.builtin_tools import FakeWebSearchClient
from agent_core.tools.registry import build_tool_registry


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class FakeMemoryClient:
    """Returns a fixed ContextPack. Never touches the store."""
    def __init__(self, pack: ContextPack):
        self._pack = pack

    def retrieve_context_pack(self, goal, **kw) -> ContextPack:
        return self._pack

    def write_memory_candidates(self, candidates, **kw):
        return None


class FailOnReadStore:
    """Sentinel store — raises if any read method is called.
    Proves tool_answer_from_context reads state.context_pack, NOT state.memory."""

    _MSG = "tool must NOT read state.memory — use state.context_pack instead"

    def search(self, *a, **k):    raise AssertionError(self._MSG)
    def get(self, *a, **k):       raise AssertionError(self._MSG)
    def list_all(self, *a, **k):  raise AssertionError(self._MSG)
    def read_note(self, *a, **k): raise AssertionError(self._MSG)
    def list_notes(self, *a, **k): raise AssertionError(self._MSG)

    # Write methods are no-ops (agent state machinery may write; we only guard reads).
    def write(self, record, **k):              return record
    def update(self, *a, **k):                return None
    def delete(self, *a, **k):                return True
    def write_note(self, name, content, **k): return None  # type: ignore[return-value]


def _decision_item(content: str) -> ContextItem:
    return ContextItem(content=content, type=MemoryType.DECISION)


def _pack_with_decision(content: str) -> ContextPack:
    return ContextPack(
        degraded=True,
        memory_source="local",
        items=[_decision_item(content)],
        total_items=1,
    )


def _empty_degraded_pack() -> ContextPack:
    return ContextPack(degraded=True, memory_source="local")


# ---------------------------------------------------------------------------
# 1. Plan PROJECT_CONTEXT_QUERY (full pipe: parser → SlotValidator → planner)
# ---------------------------------------------------------------------------

def test_project_context_query_plan():
    state = AgentState(goal="Dự án đã chốt dùng cơ chế search nào cho MVP?")
    plan = RuleBasedPlanner().make_plan(state)

    actions = [step.action for step in plan]
    assert actions == [ToolName.ANSWER_FROM_CONTEXT, ToolName.FINISH], (
        f"Expected [ANSWER_FROM_CONTEXT, FINISH], got {actions}"
    )


# ---------------------------------------------------------------------------
# 2. ANSWER_FROM_CONTEXT in registry
# ---------------------------------------------------------------------------

def test_answer_from_context_in_registry():
    registry = build_tool_registry(FakeWebSearchClient())
    assert ToolName.ANSWER_FROM_CONTEXT in registry


# ---------------------------------------------------------------------------
# 3. Registry completeness guard
# ---------------------------------------------------------------------------

def test_registry_completeness():
    registry = build_tool_registry(FakeWebSearchClient())
    assert set(registry.keys()) == set(ToolName)


# ---------------------------------------------------------------------------
# 4. E2E: one DECISION item → FTS5 in answer, context_consumed=True,
#    no READ_NOTE in plan, used_item_count not leaked, degraded discloses
# ---------------------------------------------------------------------------

def test_answer_from_context_one_item():
    pack = _pack_with_decision("MVP đã chốt dùng FTS5, chưa dùng vector database")
    client = FakeMemoryClient(pack)

    tools = build_tool_registry(FakeWebSearchClient())
    agent = RuntimeAgent(planner=RuleBasedPlanner(), tools=tools, memory_client=client)
    state = AgentState(goal="Dự án đã chốt dùng cơ chế search nào cho MVP?")
    agent.run(state)

    assert state.status == AgentStatus.COMPLETED
    assert state.context_consumed is True
    assert "FTS5" in (state.final_answer or "")
    assert "used_item_count" not in (state.final_answer or "")
    assert all(step.action != ToolName.READ_NOTE for step in state.plan)
    assert "memory_degraded" in state.disclosure_reasons
    from agent_core.runtime.runtime_agent import _DISCLOSURE_TEXT
    assert _DISCLOSURE_TEXT["memory_degraded"] in (state.final_answer or "")


# ---------------------------------------------------------------------------
# 5. Empty pack → "không có đủ project context", context_consumed=False, degraded discloses
# ---------------------------------------------------------------------------

def test_answer_from_context_empty_pack():
    client = FakeMemoryClient(_empty_degraded_pack())

    tools = build_tool_registry(FakeWebSearchClient())
    agent = RuntimeAgent(planner=RuleBasedPlanner(), tools=tools, memory_client=client)
    state = AgentState(goal="Dự án đã chốt dùng cơ chế search nào cho MVP?")
    agent.run(state)

    assert state.context_consumed is False
    assert "không có đủ project context" in (state.final_answer or "")
    # degraded still discloses even though context_consumed=False (§4b rule: plan-based)
    assert "memory_degraded" in state.disclosure_reasons


# ---------------------------------------------------------------------------
# 6. Multiple items → "chưa đủ rõ", context_consumed=False
# ---------------------------------------------------------------------------

def test_answer_from_context_multiple_items():
    pack = ContextPack(
        degraded=True,
        memory_source="local",
        items=[
            _decision_item("MVP dùng FTS5"),
            _decision_item("MVP dùng BM25"),
        ],
        total_items=2,
    )
    client = FakeMemoryClient(pack)

    tools = build_tool_registry(FakeWebSearchClient())
    agent = RuntimeAgent(planner=RuleBasedPlanner(), tools=tools, memory_client=client)
    state = AgentState(goal="Dự án đã chốt dùng cơ chế search nào cho MVP?")
    agent.run(state)

    assert state.context_consumed is False
    assert "chưa đủ rõ" in (state.final_answer or "")


# ---------------------------------------------------------------------------
# 7. Calculate task: context_consumed=False, plan has no ANSWER_FROM_CONTEXT
# ---------------------------------------------------------------------------

def test_calculate_does_not_consume_context():
    store = InMemoryStore()
    store.write(MemoryRecord(content="MVP dùng FTS5", type=MemoryType.DECISION))
    client = LocalMemoryClient(store)

    tools = build_tool_registry(FakeWebSearchClient())
    agent = RuntimeAgent(planner=RuleBasedPlanner(), tools=tools, memory_client=client)
    state = AgentState(goal="Tính (15+5)*3", memory=store)
    agent.run(state)

    assert state.context_consumed is False
    assert all(step.action != ToolName.ANSWER_FROM_CONTEXT for step in state.plan)
    assert "60" in (state.final_answer or "")


# ---------------------------------------------------------------------------
# 8. DoD counterfactual: same goal, output changes with/without seeded pack
# ---------------------------------------------------------------------------

def test_output_changes_with_pack():
    goal = "Dự án đã chốt dùng cơ chế search nào cho MVP?"

    # run with seeded decision
    tools = build_tool_registry(FakeWebSearchClient())
    client_seeded = FakeMemoryClient(_pack_with_decision("MVP dùng FTS5"))
    agent_seeded = RuntimeAgent(planner=RuleBasedPlanner(), tools=tools, memory_client=client_seeded)
    state_seeded = AgentState(goal=goal)
    agent_seeded.run(state_seeded)
    answer_seeded = state_seeded.final_answer or ""

    # run with empty pack
    client_empty = FakeMemoryClient(_empty_degraded_pack())
    agent_empty = RuntimeAgent(planner=RuleBasedPlanner(), tools=tools, memory_client=client_empty)
    state_empty = AgentState(goal=goal)
    agent_empty.run(state_empty)
    answer_empty = state_empty.final_answer or ""

    assert "FTS5" in answer_seeded
    assert "FTS5" not in answer_empty
    assert answer_seeded != answer_empty


# ---------------------------------------------------------------------------
# 9. Parser negative: "Dự án đang chạy bình thường" (no cue) → UNKNOWN
# ---------------------------------------------------------------------------

def test_parser_negative_project_running():
    from agent_core.planning.intent_parser import RuleBasedIntentParser
    parsed = RuleBasedIntentParser().parse("Dự án đang chạy bình thường")
    assert parsed.intent == IntentName.UNKNOWN


# ---------------------------------------------------------------------------
# 10. Parser negative: "Tìm thông tin về dự án" → WEB_SEARCH (not PROJECT_CONTEXT_QUERY)
# ---------------------------------------------------------------------------

def test_parser_negative_tim_still_websearch():
    from agent_core.planning.intent_parser import RuleBasedIntentParser
    parsed = RuleBasedIntentParser().parse("Tìm thông tin về dự án")
    assert parsed.intent == IntentName.WEB_SEARCH


# ---------------------------------------------------------------------------
# 11. ANSWER_FROM_CONTEXT runs under read_only=True (mutates_state=False)
# ---------------------------------------------------------------------------

def test_answer_from_context_runs_under_read_only():
    pack = _pack_with_decision("MVP dùng FTS5")
    client = FakeMemoryClient(pack)

    tools = build_tool_registry(FakeWebSearchClient())
    agent = RuntimeAgent(planner=RuleBasedPlanner(), tools=tools, memory_client=client)
    state = AgentState(goal="Dự án đã chốt dùng cơ chế search nào cho MVP?")
    state.read_only = True
    agent.run(state)

    assert state.status == AgentStatus.COMPLETED
    assert state.context_consumed is True
    assert "FTS5" in (state.final_answer or "")


# ---------------------------------------------------------------------------
# 12. DoD STRONGEST: tool reads context_pack, NOT state.memory (FailOnReadStore)
# ---------------------------------------------------------------------------

def test_answer_source_is_context_pack_not_store():
    pack = _pack_with_decision("MVP dùng FTS5")
    client = FakeMemoryClient(pack)

    tools = build_tool_registry(FakeWebSearchClient())
    agent = RuntimeAgent(planner=RuleBasedPlanner(), tools=tools, memory_client=client)

    state = AgentState(goal="Dự án đã chốt dùng cơ chế search nào cho MVP?")
    state.memory = FailOnReadStore()  # any read on store → AssertionError

    # Must NOT raise — tool must read from state.context_pack only
    agent.run(state)

    assert "FTS5" in (state.final_answer or "")
    assert state.context_consumed is True

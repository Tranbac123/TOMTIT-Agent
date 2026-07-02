"""CONV-P0 P0-3 T1B — direct/clarification route boundary gate.

Proves that DIRECT_RESPONSE / CLARIFICATION turns complete an AgentState at the
SessionRuntime.handle_turn seam WITHOUT touching planner / ToolExecutor / memory, while
RUNTIME_FALLBACK still flows through the real runtime. Spy counters live here (test-only),
never in the production route model.
"""
from __future__ import annotations

import pytest

from agent_core.conversation.models import ConversationRoute, TraceMeaning
from agent_core.conversation.router import ConversationRouter
from agent_core.memory.contracts import ContextPack, WriteResponse
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.runtime.runtime_agent import RuntimeAgent, build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus

_CONV_PREFIX = "conv:"
_FORBIDDEN_TRACE = {"planner_called", "tool_called", "memory_read_called", "memory_write_called"}
_REQUIRED_TRACE = {
    "request_received", "intent_classified", "route_selected",
    "response_generated", "state_finalized",
}


# --- test-only spies (counters are NOT in the production route model) ---

class _CountingPlanner:
    def __init__(self) -> None:
        self.calls = 0

    def make_plan(self, state):  # pragma: no cover - must not be called on direct routes
        self.calls += 1
        return []


class _CountingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, step, state):  # pragma: no cover - must not be called on direct routes
        self.calls += 1
        raise AssertionError("ToolExecutor.execute called on a direct/clarification route")


class _SpyMemoryClient:
    def __init__(self) -> None:
        self.reads = 0
        self.writes = 0

    @property
    def supports_required_write(self) -> bool:
        return False

    def retrieve_context_pack(self, *a, **k) -> ContextPack:  # pragma: no cover
        self.reads += 1
        return ContextPack()

    def write_memory_candidates(self, *a, **k) -> WriteResponse:  # pragma: no cover
        self.writes += 1
        return WriteResponse()


def _spy_session():
    planner = _CountingPlanner()
    executor = _CountingExecutor()
    memory = _SpyMemoryClient()
    agent = RuntimeAgent(
        planner=planner, tools={}, executor=executor, memory_client=memory
    )
    return SessionRuntime(agent, InMemoryStore()), planner, executor, memory


def _conv_trace(state: AgentState) -> set[str]:
    return {h[len(_CONV_PREFIX):] for h in state.history if h.startswith(_CONV_PREFIX)}


def _assert_zero_side_effects(planner, executor, memory):
    assert planner.calls == 0, f"planner_calls={planner.calls}"
    assert executor.calls == 0, f"tool_calls={executor.calls}"
    assert memory.reads == 0, f"memory_reads={memory.reads}"
    assert memory.writes == 0, f"memory_writes={memory.writes}"


def _assert_direct_state(state: AgentState):
    assert state.status == AgentStatus.COMPLETED
    assert state.final_answer and state.final_answer.strip()
    assert state.plan == []                 # no runtime plan created
    assert state.observations == []         # no ToolExecutor observations
    trace = _conv_trace(state)
    assert _REQUIRED_TRACE <= trace, f"missing trace meanings: {_REQUIRED_TRACE - trace}"
    assert not (_FORBIDDEN_TRACE & trace), f"forbidden trace meanings present: {_FORBIDDEN_TRACE & trace}"


# ---------------------------------------------------------------------------
# Route contract (router unit)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, intent, route",
    [
        ("Xin chào", "greeting", ConversationRoute.DIRECT_RESPONSE),
        ("alo", "greeting", ConversationRoute.DIRECT_RESPONSE),                 # P0-7E
        ("helo", "greeting", ConversationRoute.DIRECT_RESPONSE),                # P0-7E
        ("hêlo", "greeting", ConversationRoute.DIRECT_RESPONSE),                # P0-7E
        ("Bạn là ai?", "identity_query", ConversationRoute.DIRECT_RESPONSE),
        ("Bạn làm được gì?", "capability_query", ConversationRoute.DIRECT_RESPONSE),
        ("bạn là được gì?", "capability_query", ConversationRoute.DIRECT_RESPONSE),  # P0-7E typo
        ("làm cái đó đi", "clarification_request", ConversationRoute.CLARIFICATION),
        ("calculate 2 + 2", "calculate", ConversationRoute.RUNTIME_FALLBACK),
        ("anything", "unknown", ConversationRoute.RUNTIME_FALLBACK),
    ],
)
def test_router_route_contract(text, intent, route):
    result = ConversationRouter().route(AgentState(goal=text))
    assert result.intent == intent
    assert result.route == route
    assert TraceMeaning.REQUEST_RECEIVED in result.trace
    assert TraceMeaning.INTENT_CLASSIFIED in result.trace
    assert TraceMeaning.ROUTE_SELECTED in result.trace
    if route is not ConversationRoute.RUNTIME_FALLBACK:
        assert TraceMeaning.RESPONSE_GENERATED in result.trace
        assert result.response_text and result.response_text.strip()
    else:
        assert result.response_text is None


# ---------------------------------------------------------------------------
# T1B boundary: zero side effects on direct/clarification routes
# ---------------------------------------------------------------------------

def test_greeting_direct_response_bypasses_runtime_side_effects():
    sr, planner, executor, memory = _spy_session()
    state = sr.handle_turn("Xin chào")
    _assert_zero_side_effects(planner, executor, memory)
    _assert_direct_state(state)
    assert "đã lưu" not in state.final_answer and "đang gọi tool" not in state.final_answer


def test_identity_direct_response_bypasses_runtime_side_effects():
    sr, planner, executor, memory = _spy_session()
    state = sr.handle_turn("Bạn là ai?")
    _assert_zero_side_effects(planner, executor, memory)
    _assert_direct_state(state)
    assert "TomTit" in state.final_answer or "TOMTIT" in state.final_answer
    # non-overclaim: explicitly disclaims doing everything autonomously
    assert "không tự động làm mọi thứ" in state.final_answer


def test_capability_direct_response_bypasses_runtime_side_effects():
    sr, planner, executor, memory = _spy_session()
    state = sr.handle_turn("Bạn làm được gì?")
    _assert_zero_side_effects(planner, executor, memory)
    _assert_direct_state(state)
    assert "giới hạn" in state.final_answer.lower() or "phát triển" in state.final_answer


def test_unknown_clarification_bypasses_runtime_side_effects():
    # "Làm cái đó đi" is the ambiguous-reference case the parser returns as
    # CLARIFICATION_REQUEST → CLARIFICATION route.
    sr, planner, executor, memory = _spy_session()
    state = sr.handle_turn("làm cái đó đi")
    _assert_zero_side_effects(planner, executor, memory)
    _assert_direct_state(state)
    for forbidden in ("đã thực hiện", "đã lưu", "đang gọi tool"):
        assert forbidden not in state.final_answer


# ---------------------------------------------------------------------------
# Runtime fallback regression: non-direct turns still use the real runtime
# ---------------------------------------------------------------------------

def test_runtime_fallback_still_uses_existing_runtime_path():
    agent, store = build_local_agent()
    sr = SessionRuntime(agent, store)
    state = sr.handle_turn("calculate 2 + 2")
    assert state.status == AgentStatus.COMPLETED
    assert "4" in state.final_answer            # runtime CALCULATE actually executed
    assert state.plan, "runtime fallback should have produced a plan"
    # fallback did not write conversation direct-route trace
    assert _conv_trace(state) == set()


def test_runtime_fallback_unknown_still_reaches_runtime():
    # bare UNKNOWN intentionally stays RUNTIME_FALLBACK (recoverable _unknown_plan),
    # preserving existing SessionRuntime behavior.
    agent, store = build_local_agent()
    sr = SessionRuntime(agent, store)
    state = sr.handle_turn("blah blah không rõ ràng gì cả")
    assert state.status == AgentStatus.COMPLETED
    assert state.plan, "unknown should still flow through the runtime plan"


# ---------------------------------------------------------------------------
# Session recording + semantic trace exposure
# ---------------------------------------------------------------------------

def test_direct_response_records_session_turn():
    sr, _, _, _ = _spy_session()
    sr.handle_turn("Xin chào")
    history = sr.get_history()
    assert len(history) == 1
    rec = history[0]
    assert rec.status == AgentStatus.COMPLETED
    assert rec.goal == "Xin chào"
    assert rec.planned_actions == ()           # no runtime plan recorded


def test_direct_response_exposes_semantic_trace():
    sr, _, _, _ = _spy_session()
    state = sr.handle_turn("Bạn là ai?")
    trace = _conv_trace(state)
    assert trace == _REQUIRED_TRACE            # exactly the 5 semantic meanings
    assert not (_FORBIDDEN_TRACE & trace)

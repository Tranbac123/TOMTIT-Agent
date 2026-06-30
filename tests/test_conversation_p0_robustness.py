"""CONV-P0 P0-4A — direct-response + fallback robustness.

Covers real-user conversation variants (capability/identity/greeting), safe arithmetic
variants, and honest unsupported date/time/weather responses — all rule-based, no LLM,
no memory, no new route literal, no eval. Direct/clarification routes keep the P0-3
zero-side-effect guarantee; arithmetic flows through the existing safe runtime calculator.
"""
from __future__ import annotations

import pytest

from agent_core.conversation.models import ConversationRoute
from agent_core.conversation.router import ConversationRouter
from agent_core.memory.contracts import ContextPack, WriteResponse
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.runtime.runtime_agent import RuntimeAgent, build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus

_DIRECT_PREFIX = "conv:"


# --- spies (test-only) to prove zero side effects on direct/clarification routes ---

class _CountingPlanner:
    def __init__(self) -> None:
        self.calls = 0

    def make_plan(self, state):  # pragma: no cover
        self.calls += 1
        return []


class _CountingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, step, state):  # pragma: no cover
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
    agent = RuntimeAgent(planner=planner, tools={}, executor=executor, memory_client=memory)
    return SessionRuntime(agent, InMemoryStore()), planner, executor, memory


def _assert_direct_zero_side_effects(text, expected_intent, expected_route):
    router_result = ConversationRouter().route(AgentState(goal=text))
    assert router_result.intent == expected_intent, (text, router_result.intent)
    assert router_result.route == expected_route, (text, router_result.route)

    sr, planner, executor, memory = _spy_session()
    state = sr.handle_turn(text)
    assert state.status == AgentStatus.COMPLETED
    assert state.final_answer and state.final_answer.strip()
    assert state.plan == []
    assert planner.calls == 0 and executor.calls == 0
    assert memory.reads == 0 and memory.writes == 0
    assert len(sr.get_history()) == 1                      # session turn recorded
    return state


_CAPABILITY_VARIANTS = [
    "bạn làm được những gì?",
    "bạn có thể làm gì?",
    "bạn có thể làm gi?",
    "bạn giúp được gì?",
    "bạn hỗ trợ được gì?",
    "mày làm được gì?",
    "mày có thể làm gì?",
    "tomtit làm được gì?",
]

_IDENTITY_VARIANTS = [
    "bạn tên là gì?",
    "tên bạn là gì?",
    "mày là ai?",
    "mày tên gì?",
    "tomtit là gì?",
    "tomtit là ai?",
]

_GREETING_VARIANTS = ["chào", "hello", "hi", "chào buổi sáng", "chào buổi tối"]

_UNSUPPORTED_UTILITIES = [
    "hôm nay ngày bao nhiêu",
    "mấy giờ rồi",
    "hôm này thời tiết HCM thế nào?",
    "thời tiết HCM thế nào?",
]


@pytest.mark.parametrize("text", _CAPABILITY_VARIANTS)
def test_capability_query_variants_route_direct_response(text):
    state = _assert_direct_zero_side_effects(text, "capability_query", ConversationRoute.DIRECT_RESPONSE)
    # mentions a concrete capability AND a limit; no overclaim of autonomy/memory/LLM
    assert "tính" in state.final_answer.lower() or "ghi chú" in state.final_answer.lower()
    assert "giới hạn" in state.final_answer.lower() or "phát triển" in state.final_answer
    assert "làm được mọi thứ" not in state.final_answer.lower()


@pytest.mark.parametrize("text", _IDENTITY_VARIANTS)
def test_identity_query_variants_route_direct_response(text):
    state = _assert_direct_zero_side_effects(text, "identity_query", ConversationRoute.DIRECT_RESPONSE)
    assert "TomTit" in state.final_answer or "TOMTIT" in state.final_answer
    # calm/professional: no mirrored rude tone
    assert "mày" not in state.final_answer.lower()


@pytest.mark.parametrize("text", _GREETING_VARIANTS)
def test_greeting_variants_route_direct_response(text):
    _assert_direct_zero_side_effects(text, "greeting", ConversationRoute.DIRECT_RESPONSE)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("100 * 10 = ?", "1000"),
        ("100*10", "1000"),
        ("100 x 10", "1000"),
        ("2 + 444", "446"),
        ("tính 100 * 10", "1000"),
        ("calculate 2 + 2", "4"),
        ("calculate 2 + 444", "446"),
    ],
)
def test_simple_arithmetic_variants(text, expected):
    # arithmetic flows through the existing runtime safe calculator (RUNTIME_FALLBACK).
    assert ConversationRouter().route(AgentState(goal=text)).route == ConversationRoute.RUNTIME_FALLBACK
    agent, store = build_local_agent()
    sr = SessionRuntime(agent, store)
    state = sr.handle_turn(text)
    assert state.status == AgentStatus.COMPLETED
    assert expected in state.final_answer, (text, state.final_answer)


@pytest.mark.parametrize("text", _UNSUPPORTED_UTILITIES)
def test_specific_unsupported_date_time_weather_responses(text):
    state = _assert_direct_zero_side_effects(text, "unknown", ConversationRoute.CLARIFICATION)
    ans = state.final_answer.lower()
    # honest unsupported message; no faked date/time/weather, no fake tool/exec claim
    assert "chưa hỗ trợ" in ans
    assert "thời tiết" in ans or "thời gian" in ans
    for fake in ("đã thực hiện", "đã lưu", "đang gọi tool"):
        assert fake not in ans


def test_manual_web_regression_cases():
    direct = {
        "xin chào": ("greeting", ConversationRoute.DIRECT_RESPONSE),
        "bạn là ai": ("identity_query", ConversationRoute.DIRECT_RESPONSE),
        "bạn làm được những gì?": ("capability_query", ConversationRoute.DIRECT_RESPONSE),
        "bạn làm được gì?": ("capability_query", ConversationRoute.DIRECT_RESPONSE),
        "bạn có thể làm gi?": ("capability_query", ConversationRoute.DIRECT_RESPONSE),
        "bạn tên là gì?": ("identity_query", ConversationRoute.DIRECT_RESPONSE),
        "mày là ai?": ("identity_query", ConversationRoute.DIRECT_RESPONSE),
    }
    for text, (intent, route) in direct.items():
        _assert_direct_zero_side_effects(text, intent, route)

    # arithmetic
    agent, store = build_local_agent()
    sr = SessionRuntime(agent, store)
    for text, expected in [("calculate 2 + 2", "4"), ("calculate 2 + 444", "446"), ("100 * 10 = ?", "1000")]:
        st = sr.handle_turn(text)
        assert expected in st.final_answer, (text, st.final_answer)

    # unsupported utilities
    for text in ["hôm nay ngày bao nhiêu", "hôm này thời tiết HCM thế nào?"]:
        st = sr.handle_turn(text)
        assert "chưa hỗ trợ" in st.final_answer.lower()


def test_route_literals_still_minimal():
    # only the three approved route literals exist on the enum.
    assert {r.value for r in ConversationRoute} == {
        "DIRECT_RESPONSE", "CLARIFICATION", "RUNTIME_FALLBACK",
    }


def test_runtime_fallback_unchanged_for_plain_unknown():
    # bare unknown still goes to runtime (not the utility clarification).
    assert ConversationRouter().route(
        AgentState(goal="blah blah random không rõ")
    ).route == ConversationRoute.RUNTIME_FALLBACK

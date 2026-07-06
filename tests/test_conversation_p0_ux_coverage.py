"""CONV-P0 P0-4B — Conversation UX coverage.

Covers real-user conversation variants discovered by manual Web regression:
  - natural help/capability variants ("bạn có giúp gì được tôi không?")
  - user-memory/self-knowledge queries ("tôi là ai?", "Bạn nhớ được gì về tôi?")
  - bot meta/provenance questions ("ai tạo ra bạn?", "bạn biết nói không?")
  - general explanation request routes to the text-only LLM_RESPONSE lane
  - ambiguous user-self action ("tôi có thể làm gì?")
  - full manual Web regression set

All deterministic, rule-based, no provider calls, no memory calls, no eval.
Direct/clarification and unconfigured LLM routes keep the zero-side-effect guarantee.
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


# --- test-only spies to prove zero side effects on direct/clarification routes ---

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


def _assert_conv_zero_side_effects(text, expected_route):
    """Assert route, completed state, non-empty response, zero side effects, session recorded."""
    router_result = ConversationRouter().route(AgentState(goal=text))
    assert router_result.route == expected_route, (text, router_result.route)

    sr, planner, executor, memory = _spy_session()
    state = sr.handle_turn(text)
    assert state.status == AgentStatus.COMPLETED, (text, state.status)
    assert state.final_answer and state.final_answer.strip(), (text, "empty response")
    assert state.plan == [], (text, "non-empty plan")
    assert planner.calls == 0, (text, f"planner called {planner.calls} times")
    assert executor.calls == 0, (text, f"executor called {executor.calls} times")
    assert memory.reads == 0, (text, f"memory read {memory.reads} times")
    assert memory.writes == 0, (text, f"memory wrote {memory.writes} times")
    assert len(sr.get_history()) == 1, (text, "session not recorded")
    return state


# ---------------------------------------------------------------------------
# §6 — Natural help / capability variants
# ---------------------------------------------------------------------------

_NATURAL_HELP_VARIANTS = [
    "bạn có giúp gì được tôi không?",
    "bạn có thể giúp gì cho tôi?",
    "bạn giúp tôi được gì?",
    "bạn hỗ trợ tôi được gì?",
    "bạn có hỗ trợ gì cho tôi không?",
]


@pytest.mark.parametrize("text", _NATURAL_HELP_VARIANTS)
def test_natural_help_capability_variants_route_direct_response(text):
    state = _assert_conv_zero_side_effects(text, ConversationRoute.DIRECT_RESPONSE)
    answer = state.final_answer.lower()
    # mentions a concrete capability and a limit; does not overclaim
    assert "tính" in answer or "ghi chú" in answer or "tính toán" in answer, (text, answer)
    assert "giới hạn" in answer or "phát triển" in answer or "chưa hoàn chỉnh" in answer, (text, answer)
    assert "làm được mọi thứ" not in answer, (text, answer)
    assert "đã thực hiện" not in answer.replace("đã được hiện thực", ""), (text, answer)


# ---------------------------------------------------------------------------
# §7 — User-memory / user-self-knowledge unsupported
# ---------------------------------------------------------------------------

_USER_MEMORY_QUERIES = [
    "Bạn nhớ được gì về tôi?",
    "bạn biết gì về tôi?",
    "tôi là ai?",
    "tôi tên là gì?",
    "tôi tên là gì bạn biết không?",
    "bạn có biết tôi là ai không?",
]


@pytest.mark.parametrize("text", _USER_MEMORY_QUERIES)
def test_user_memory_self_knowledge_gets_honest_unsupported_response(text):
    state = _assert_conv_zero_side_effects(text, ConversationRoute.CLARIFICATION)
    answer = state.final_answer.lower()
    # honest: says not supported, does not fake memory, does not claim tool/memory call
    assert "chưa hỗ trợ" in answer or "chưa biết" in answer or "chưa nhớ" in answer, (text, answer)
    assert "đã lưu" not in answer, (text, answer)
    assert "đang gọi" not in answer, (text, answer)
    assert "đã tra cứu" not in answer, (text, answer)


# ---------------------------------------------------------------------------
# §8 — Bot meta / provenance questions
# ---------------------------------------------------------------------------

# "bạn biết nói không?" maps to CAPABILITY_QUERY (can-you-speak? ≈ capability).
_BOT_SPEECH_VARIANTS = [
    "bạn biết nói không?",
    "bạn có biết nói không?",
]

# Provenance questions map to IDENTITY_QUERY.
_BOT_PROVENANCE_VARIANTS = [
    "ai tạo ra bạn?",
    "ai xây dựng bạn?",
    "tomtit do ai tạo ra?",
    "tomtit được tạo ra bởi ai?",
]


@pytest.mark.parametrize("text", _BOT_SPEECH_VARIANTS)
def test_bot_speech_capability_routes_direct_response(text):
    state = _assert_conv_zero_side_effects(text, ConversationRoute.DIRECT_RESPONSE)
    answer = state.final_answer.lower()
    assert "làm được mọi thứ" not in answer, (text, answer)


@pytest.mark.parametrize("text", _BOT_PROVENANCE_VARIANTS)
def test_bot_provenance_questions_get_direct_response(text):
    state = _assert_conv_zero_side_effects(text, ConversationRoute.DIRECT_RESPONSE)
    answer = state.final_answer
    # identity response must mention TomTit
    assert "TomTit" in answer or "TOMTIT" in answer, (text, answer)
    assert "làm được mọi thứ" not in answer.lower(), (text, answer)


# ---------------------------------------------------------------------------
# §9 — General explanation request LLM lane
# ---------------------------------------------------------------------------

_EXPLANATION_REQUESTS = [
    "bạn hãy giải thích cho tôi về AI?",
    "giải thích AI là gì?",
    "hãy giải thích về AI",
    "giải thích cho tôi về machine learning",
]


@pytest.mark.parametrize("text", _EXPLANATION_REQUESTS)
def test_general_explanation_request_uses_safe_unconfigured_llm_lane(text):
    state = _assert_conv_zero_side_effects(text, ConversationRoute.LLM_RESPONSE)
    answer = state.final_answer.lower()
    assert "llmresponder chưa được cấu hình" in answer, (text, answer)
    assert "chưa gọi tool" in answer, (text, answer)
    assert "memory" in answer, (text, answer)


# ---------------------------------------------------------------------------
# §10 — Ambiguous user-self action clarification
# ---------------------------------------------------------------------------

def test_ambiguous_user_self_action_gets_clarification():
    text = "tôi có thể làm gì?"
    state = _assert_conv_zero_side_effects(text, ConversationRoute.CLARIFICATION)
    answer = state.final_answer.lower()
    # must ask user to clarify what they mean; must not answer as TomTit capability
    assert "bạn" in answer, (text, answer)
    assert "chưa đủ ngữ cảnh" in answer or "làm gì với tomtit" in answer or "gợi ý" in answer, (text, answer)


# ---------------------------------------------------------------------------
# §11 — Latest manual Web regression cases (full set)
# ---------------------------------------------------------------------------

def test_latest_manual_web_regression_cases():
    router = ConversationRouter()

    def route_of(text):
        return router.route(AgentState(goal=text)).route

    DIRECT = ConversationRoute.DIRECT_RESPONSE
    CLARIF = ConversationRoute.CLARIFICATION
    LLM = ConversationRoute.LLM_RESPONSE
    FALLBK = ConversationRoute.RUNTIME_FALLBACK

    cases = [
        # greeting / identity / capability (existing, must still pass)
        ("xin chào",                              DIRECT),
        ("bạn là ai?",                            DIRECT),
        ("bạn làm được những gì?",                DIRECT),
        ("bạn làm được gì?",                      DIRECT),
        # P0-4B: natural help variant
        ("bạn có giúp gì được tôi không?",        DIRECT),
        # P0-4B: user-memory queries
        ("Bạn nhớ được gì về tôi?",               CLARIF),
        # P0-4A: identity / provenance
        ("bạn tên là gì?",                        DIRECT),
        ("mày là ai?",                            DIRECT),
        # edge cases
        ("???",                                   CLARIF),
        ("who are you?",                          DIRECT),
        ("hello?",                                DIRECT),
        # arithmetic (existing, must still pass via runtime)
        ("calculate 2 + 2",                       FALLBK),
        ("calculate 2 + 444",                     FALLBK),
        # P0-4A: unsupported utility
        ("hôm nay ngày bao nhiêu",                CLARIF),
        ("hôm này thời tiết HCM thế nào?",        CLARIF),
        # P0-4B: bot meta / provenance
        ("bạn biết nói không?",                   DIRECT),
        # P0-5B: explanation goes to safe text-only LLM lane
        ("bạn hãy giải thích cho tôi về AI?",     LLM),
        # P0-4B: provenance
        ("Ai tạo ra bạn?",                        DIRECT),
        # P0-4B: ambiguous user-self
        ("tôi có thể làm gì?",                    CLARIF),
        # P0-4B: user-memory / self-knowledge
        ("tôi hỏi tôi mà? tôi là ai?",           CLARIF),
        ("tôi là ai?",                            CLARIF),
        ("tôi tên là gì bạn biết không?",         CLARIF),
    ]

    for text, expected in cases:
        actual = route_of(text)
        assert actual == expected, f"[{text!r}] expected {expected.value!r}, got {actual.value!r}"

    # Verify arithmetic still computes (via runtime fallback)
    agent, store = build_local_agent()
    sr = SessionRuntime(agent, store)
    s = sr.handle_turn("calculate 2 + 2")
    assert s.status == AgentStatus.COMPLETED
    assert "4" in s.final_answer

    s2 = sr.handle_turn("calculate 2 + 444")
    assert s2.status == AgentStatus.COMPLETED
    assert "446" in s2.final_answer


# ---------------------------------------------------------------------------
# §12 — Route literal contract (P0-5B adds LLM_RESPONSE only)
# ---------------------------------------------------------------------------

def test_route_literals_still_minimal_after_p0_4b():
    from agent_core.conversation.models import ConversationRoute
    assert {r.value for r in ConversationRoute} == {
        "DIRECT_RESPONSE",
        "CLARIFICATION",
        "LLM_RESPONSE",
        "RUNTIME_FALLBACK",
    }


# ---------------------------------------------------------------------------
# §13 — P0-4A regression still passes (smoke)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected_route",
    [
        ("bạn làm được những gì?",        ConversationRoute.DIRECT_RESPONSE),
        ("bạn có thể làm gì?",            ConversationRoute.DIRECT_RESPONSE),
        ("bạn giúp được gì?",             ConversationRoute.DIRECT_RESPONSE),
        ("bạn hỗ trợ được gì?",           ConversationRoute.DIRECT_RESPONSE),
        ("bạn tên là gì?",                ConversationRoute.DIRECT_RESPONSE),
        ("tomtit là gì?",                 ConversationRoute.DIRECT_RESPONSE),
        ("mày là ai?",                    ConversationRoute.DIRECT_RESPONSE),
        ("chào",                          ConversationRoute.DIRECT_RESPONSE),
        ("hello",                         ConversationRoute.DIRECT_RESPONSE),
        ("hôm nay ngày bao nhiêu",        ConversationRoute.CLARIFICATION),
        ("thời tiết HCM thế nào?",        ConversationRoute.CLARIFICATION),
        ("100 x 10",                      ConversationRoute.RUNTIME_FALLBACK),
    ],
)
def test_p0_4a_regression_still_passes(text, expected_route):
    result = ConversationRouter().route(AgentState(goal=text))
    assert result.route == expected_route, (text, result.route)


# ---------------------------------------------------------------------------
# §14 — P0-7K-FIX5B-FIX3-FIX2 slang greeting aliases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["ê", "ê ê", "lô", "ê lô", "alo", "hello", "hi", "xin chào"])
def test_p0_7k_fix5b_fix3_fix2_slang_greetings_no_fallback_no_write(text):
    state = _assert_conv_zero_side_effects(text, ConversationRoute.DIRECT_RESPONSE)
    answer = state.final_answer.lower()
    assert "rule-based mvp" not in answer, answer
    assert "đã nhớ" not in answer and "đã lưu" not in answer and "đã ghi nhận" not in answer, answer

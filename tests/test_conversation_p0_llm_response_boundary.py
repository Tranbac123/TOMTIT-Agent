"""CONV-P0 P0-5B — safe text-only LLMResponder boundary."""
from __future__ import annotations

import pytest

from agent_core.conversation.llm_responder import (
    LLMResponderRequest,
    LLMResponderResult,
)
from agent_core.conversation.models import ConversationRoute
from agent_core.conversation.router import ConversationRouter
from agent_core.memory.contracts import ContextPack, WriteResponse
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.runtime.runtime_agent import RuntimeAgent
from agent_core.runtime.session_runtime import SessionRuntime
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus

_CONV_PREFIX = "conv:"


class _CountingPlanner:
    def __init__(self) -> None:
        self.calls = 0

    def make_plan(self, state):  # pragma: no cover
        self.calls += 1
        raise AssertionError("planner called on LLM_RESPONSE route")


class _CountingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, step, state):  # pragma: no cover
        self.calls += 1
        raise AssertionError("ToolExecutor called on LLM_RESPONSE route")


class _SpyMemoryClient:
    def __init__(self) -> None:
        self.reads = 0
        self.writes = 0

    @property
    def supports_required_write(self) -> bool:
        return False

    def retrieve_context_pack(self, *a, **k) -> ContextPack:  # pragma: no cover
        self.reads += 1
        raise AssertionError("memory read called on LLM_RESPONSE route")

    def write_memory_candidates(self, *a, **k) -> WriteResponse:  # pragma: no cover
        self.writes += 1
        raise AssertionError("memory write called on LLM_RESPONSE route")


class _SpyLLMResponder:
    def __init__(self, text: str = "LLM text response") -> None:
        self.text = text
        self.requests: list[LLMResponderRequest] = []

    def generate(self, request: LLMResponderRequest) -> LLMResponderResult:
        self.requests.append(request)
        return LLMResponderResult(
            text=self.text,
            provider_name="test-provider",
            model_name="test-model",
        )


class _FailingLLMResponder:
    def generate(self, request: LLMResponderRequest) -> LLMResponderResult:
        raise RuntimeError("raw provider failure with secret stack text")


def _spy_session(llm_responder=None):
    planner = _CountingPlanner()
    executor = _CountingExecutor()
    memory = _SpyMemoryClient()
    agent = RuntimeAgent(planner=planner, tools={}, executor=executor, memory_client=memory)
    return (
        SessionRuntime(agent, InMemoryStore(), llm_responder=llm_responder),
        planner,
        executor,
        memory,
    )


def _route(text: str) -> ConversationRoute:
    return ConversationRouter().route(AgentState(goal=text)).route


def _trace(state: AgentState) -> list[str]:
    return [h[len(_CONV_PREFIX):] for h in state.history if h.startswith(_CONV_PREFIX)]


def _assert_no_runtime_side_effects(planner, executor, memory) -> None:
    assert planner.calls == 0
    assert executor.calls == 0
    assert memory.reads == 0
    assert memory.writes == 0


def test_route_literals_include_llm_response_only():
    assert {route.value for route in ConversationRoute} == {
        "DIRECT_RESPONSE",
        "CLARIFICATION",
        "LLM_RESPONSE",
        "RUNTIME_FALLBACK",
    }
    assert not {
        "MEMORY_FLOW",
        "TOOL_FLOW",
        "AUTONOMOUS_WORKER",
        "LLM_PLANNER",
    } & {route.value for route in ConversationRoute}


@pytest.mark.parametrize(
    "text",
    [
        "giải thích AI là gì?",
        "bạn hãy giải thích cho tôi về AI?",
        "giải thích cho tôi về machine learning",
        "dịch từ data sang tiếng Việt",
        'dịch "hello" sang tiếng Việt',
        "Việt Nam nằm ở đâu?",
        "2 > 3?",
    ],
)
def test_open_text_requests_route_to_llm_response(text):
    assert _route(text) == ConversationRoute.LLM_RESPONSE


@pytest.mark.parametrize(
    "text",
    [
        "xin chào",
        "bạn là ai?",
        "bạn làm được gì?",
        "bạn có giúp gì được tôi không?",
        "who are you?",
        "hello?",
    ],
)
def test_deterministic_routes_remain_direct_response(text):
    assert _route(text) == ConversationRoute.DIRECT_RESPONSE


@pytest.mark.parametrize(
    "text",
    [
        "tôi là ai?",
        "tôi tên là gì?",
        "Bạn nhớ được gì về tôi?",
        "hôm nay ngày bao nhiêu",
        "thời tiết HCM thế nào?",
        "ok",
        "?",
        "???",
        "review code này",
        "hãy lập kế hoạch cho tôi",
    ],
)
def test_memory_utility_and_missing_context_remain_clarification(text):
    assert _route(text) == ConversationRoute.CLARIFICATION


@pytest.mark.parametrize(
    "text",
    [
        "calculate 2 + 2",
        "2 + 10",
        "2 * 3 = ?",
        "lưu ghi chú tên nội dung",
        "đọc ghi chú tên",
    ],
)
def test_calculator_and_notes_remain_runtime_fallback(text):
    assert _route(text) == ConversationRoute.RUNTIME_FALLBACK


def test_injected_responder_used_and_session_recorded():
    responder = _SpyLLMResponder("Đây là câu trả lời từ responder.")
    sr, planner, executor, memory = _spy_session(responder)

    state = sr.handle_turn("giải thích AI là gì?")

    assert state.status == AgentStatus.COMPLETED
    assert state.final_answer == "Đây là câu trả lời từ responder."
    assert len(responder.requests) == 1
    assert len(sr.get_history()) == 1
    _assert_no_runtime_side_effects(planner, executor, memory)
    assert state.plan == []
    assert state.observations == []


def test_success_trace_is_state_first_and_llm_specific():
    responder = _SpyLLMResponder("AI là một lĩnh vực máy tính.")
    sr, _, _, _ = _spy_session(responder)

    state = sr.handle_turn("giải thích AI là gì?")

    assert _trace(state) == [
        "request_received",
        "intent_classified",
        "route_selected",
        "llm_response_requested",
        "llm_response_generated",
        "state_finalized",
    ]


def test_unconfigured_llm_responder_completes_safely_without_runtime_side_effects():
    sr, planner, executor, memory = _spy_session()

    state = sr.handle_turn("giải thích AI là gì?")

    assert state.status == AgentStatus.COMPLETED
    assert state.final_answer == (
        "Hiện tại trong runtime này LLMResponder chưa được cấu hình, nên tôi chưa thể trả lời yêu cầu mở này. "
        "Tôi chưa gọi tool, memory hay thực hiện hành động nào."
    )
    assert _trace(state) == [
        "request_received",
        "intent_classified",
        "route_selected",
        "llm_response_unconfigured",
        "state_finalized",
    ]
    _assert_no_runtime_side_effects(planner, executor, memory)
    assert len(sr.get_history()) == 1


def test_failure_completes_safely_without_raw_exception_or_runtime_side_effects():
    sr, planner, executor, memory = _spy_session(_FailingLLMResponder())

    state = sr.handle_turn("giải thích AI là gì?")

    assert state.status == AgentStatus.COMPLETED
    assert state.final_answer == (
        "Tôi chưa thể tạo câu trả lời LLM cho yêu cầu này lúc này. "
        "Tôi chưa gọi tool, memory hay thực hiện hành động nào."
    )
    assert "raw provider failure" not in state.final_answer
    assert "secret stack text" not in state.final_answer
    assert state.errors == ["llm_response:RuntimeError"]
    assert _trace(state) == [
        "request_received",
        "intent_classified",
        "route_selected",
        "llm_response_requested",
        "llm_response_failed",
        "state_finalized",
    ]
    _assert_no_runtime_side_effects(planner, executor, memory)


def test_responder_request_is_text_only_and_excludes_memory_tools_history_context():
    responder = _SpyLLMResponder("text")
    sr, _, _, _ = _spy_session(responder)

    state = sr.handle_turn('dịch "hello" sang tiếng Việt')

    request = responder.requests[0]
    assert request == LLMResponderRequest(
        user_text='dịch "hello" sang tiếng Việt',
        intent="translation_request",
        route="LLM_RESPONSE",
        session_id=state.session_id,
        task_id=state.task_id,
    )
    assert set(vars(request)) == {"user_text", "intent", "route", "session_id", "task_id"}
    forbidden_fields = {
        "memory",
        "memory_client",
        "tool_executor",
        "tools",
        "tool_registry",
        "history",
        "context_pack",
        "state",
        "env",
        "files",
    }
    assert not forbidden_fields & set(vars(request))

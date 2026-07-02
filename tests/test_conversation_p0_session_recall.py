"""CONV-P0 P0-7E — minimal current-session recall.

Covers "tôi vừa hỏi gì bạn?" / "câu trước tôi hỏi gì?" / "tôi vừa nói gì?":
  - answers the previous user turn from session-local history only
  - honest no-prior-turn response on the first turn
  - excludes the current recall query itself
  - writes no memory and reads no long-term memory (spy asserts zero client calls)
  - attaches no provenance/sources

All deterministic, rule-based, no provider calls.
"""
from __future__ import annotations

from agent_core.memory.contracts import ContextPack, WriteResponse
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.runtime.runtime_agent import RuntimeAgent, build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime
from agent_core.state.enums import AgentStatus


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
        raise AssertionError("ToolExecutor.execute called on a session-recall turn")


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


def _make_sr() -> SessionRuntime:
    agent, store = build_local_agent()
    return SessionRuntime(agent, store)


def test_first_turn_recall_has_no_prior_turn():
    sr = _make_sr()
    s = sr.handle_turn("tôi vừa hỏi gì bạn?")
    assert s.status == AgentStatus.COMPLETED
    answer = (s.final_answer or "").lower()
    assert "chưa có câu hỏi trước" in answer


def test_recall_previous_user_question():
    sr = _make_sr()
    sr.handle_turn("bạn biết gì về tôi")
    s = sr.handle_turn("tôi vừa hỏi gì bạn?")
    assert s.status == AgentStatus.COMPLETED
    assert "bạn biết gì về tôi" in (s.final_answer or "").lower()


def test_recall_variants_cau_truoc_and_vua_noi():
    sr = _make_sr()
    sr.handle_turn("calculate 2 + 2")
    s1 = sr.handle_turn("câu trước tôi hỏi gì?")
    assert "calculate 2 + 2" in (s1.final_answer or "").lower()

    s2 = sr.handle_turn("tôi vừa nói gì?")
    # previous user turn is now the "câu trước tôi hỏi gì?" query
    assert "câu trước tôi hỏi gì" in (s2.final_answer or "").lower()


def test_recall_excludes_current_recall_query():
    sr = _make_sr()
    sr.handle_turn("bạn biết gì về tôi")
    s = sr.handle_turn("tôi vừa hỏi gì bạn?")
    answer = (s.final_answer or "").lower()
    assert "bạn biết gì về tôi" in answer
    # must not echo the recall query itself as the answer
    assert "tôi vừa hỏi gì bạn" not in answer


def test_recall_does_not_write_or_read_long_term_memory():
    sr, planner, executor, memory = _spy_session()
    sr.handle_turn("bạn biết gì về tôi")
    memory.reads = 0
    memory.writes = 0
    s = sr.handle_turn("tôi vừa hỏi gì bạn?")
    assert s.status == AgentStatus.COMPLETED
    assert memory.reads == 0, f"recall read long-term memory {memory.reads} times"
    assert memory.writes == 0, f"recall wrote memory {memory.writes} times"
    assert planner.calls == 0
    assert executor.calls == 0


def test_recall_has_no_provenance_sources():
    sr = _make_sr()
    sr.handle_turn("bạn biết gì về tôi")
    s = sr.handle_turn("tôi vừa hỏi gì bạn?")
    assert s.sources == [], f"recall attached sources: {s.sources!r}"


def test_recall_does_not_claim_save():
    sr = _make_sr()
    sr.handle_turn("bạn biết gì về tôi")
    s = sr.handle_turn("tôi vừa hỏi gì bạn?")
    assert "đã lưu" not in (s.final_answer or "").lower()
    assert "đã nhớ" not in (s.final_answer or "").lower()

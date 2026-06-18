from __future__ import annotations

import httpx

from agent_core.memory.contracts import MemoryCandidate
from agent_core.memory.remote_client import RemoteMemoryClient
from agent_core.planning.rule_based_planner import RuleBasedPlanner
from agent_core.runtime.runtime_agent import RuntimeAgent
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus, MemoryType
from agent_core.state.session_state import TurnRecord
from agent_core.tools.builtin_tools import FakeWebSearchClient
from agent_core.tools.registry import build_tool_registry


def _remote_client(handler) -> RemoteMemoryClient:
    return RemoteMemoryClient(
        base_url="http://memory.local",
        project_id="tomtit-agent",
        default_user_id="local-user",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        request_id_factory=lambda: "req-runtime",
    )


def _agent(memory_client) -> RuntimeAgent:
    return RuntimeAgent(
        planner=RuleBasedPlanner(),
        tools=build_tool_registry(FakeWebSearchClient()),
        memory_client=memory_client,
    )


def test_remote_operational_retrieval_degrades_and_ordinary_task_continues():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    state = _agent(_remote_client(handler)).run(AgentState(goal="Tính 2+2"))

    assert state.status is AgentStatus.COMPLETED
    assert state.memory_degraded is True
    assert state.context_pack is not None
    assert state.context_pack.degraded is True
    assert state.context_pack.items == []
    assert not any(isinstance(value, httpx.Response) for value in state.__dict__.values())


def test_remote_successful_retrieval_reaches_agent_state_without_transcript_write():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "schema_version": "memory-contract-v1",
                "request_id": "req-runtime",
                "project_id": "tomtit-agent",
                "user_id": "local-user",
                "session_id": None,
                "query": "Tính 2+2",
                "memory_source": "tomtit-memory",
                "tokenizer_id": "cl100k_base",
                "items": [],
                "total_items": 0,
                "tokens_used": 0,
                "token_budget": 1500,
                "truncated": False,
                "degraded": False,
                "warnings": [],
            },
        )

    state = _agent(_remote_client(handler)).run(AgentState(goal="Tính 2+2"))

    assert state.status is AgentStatus.COMPLETED
    assert state.context_pack is not None
    assert state.context_pack.degraded is False
    assert TurnRecord.__dataclass_fields__.keys() == {
        "task_id",
        "goal",
        "final_answer",
        "status",
        "planned_actions",
        "memory_degraded",
        "memory_write_failed",
        "disclosure_reasons",
        "completed_at",
    }


def test_remote_write_failure_sets_runtime_flag_without_false_persistence():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/context/retrieve":
            return httpx.Response(
                200,
                json={
                    "schema_version": "memory-contract-v1",
                    "request_id": "req-runtime",
                    "project_id": "tomtit-agent",
                    "user_id": "local-user",
                    "session_id": None,
                    "query": "Tính 2+2",
                    "memory_source": "tomtit-memory",
                    "tokenizer_id": "cl100k_base",
                    "items": [],
                    "total_items": 0,
                    "tokens_used": 0,
                    "token_budget": 1500,
                    "truncated": False,
                    "degraded": False,
                    "warnings": [],
                },
            )
        return httpx.Response(500, json={"error": "down"})

    class CandidateAgent(RuntimeAgent):
        def _collect_candidates(self, state):
            return [
                MemoryCandidate(
                    type=MemoryType.FACT,
                    content="fact",
                    evidence_ref="user-explicit:test",
                )
            ]

    agent = CandidateAgent(
        planner=RuleBasedPlanner(),
        tools=build_tool_registry(FakeWebSearchClient()),
        memory_client=_remote_client(handler),
    )
    state = agent.run(AgentState(goal="Tính 2+2"))

    assert state.status is AgentStatus.COMPLETED
    assert state.memory_write_failed is True
    assert any("memory write failed" in error for error in state.errors)

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent_core.memory.contracts import MemoryCandidate
from agent_core.memory.errors import (
    RemoteMemoryConfigurationError,
    RemoteMemoryContractError,
    RemoteMemoryWriteError,
)
from agent_core.memory.remote_client import RemoteMemoryClient
from agent_core.state.enums import MemoryType

FIXTURES = Path(__file__).parent / "fixtures" / "memory_contract_v1"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _client(handler, *, request_id: str = "req-test") -> RemoteMemoryClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return RemoteMemoryClient(
        base_url="http://memory.local/",
        project_id="tomtit-agent",
        default_user_id="local-user",
        timeout_seconds=1.0,
        http_client=http_client,
        request_id_factory=lambda: request_id,
    )


def test_retrieve_success_exact_route_payload_and_mapping():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        payload = _fixture("context_response.json")
        payload["request_id"] = "req-context"
        payload["token_budget"] = 1500
        return httpx.Response(200, json=payload)

    client = _client(handler, request_id="req-context")
    pack = client.retrieve_context_pack("AgentState memory boundary", session_id="sess-1")

    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/context/retrieve"
    assert captured["payload"] == {
        "schema_version": "memory-contract-v1",
        "request_id": "req-context",
        "project_id": "tomtit-agent",
        "user_id": "local-user",
        "session_id": "sess-1",
        "query": "AgentState memory boundary",
        "type_filter": None,
        "token_budget": 1500,
        "max_items": 20,
    }
    assert pack.degraded is False
    assert pack.memory_source == "remote"
    assert pack.tokens_used == 19
    assert pack.truncated is False
    assert len(pack.items) == 1
    item = pack.items[0]
    assert item.type is MemoryType.DECISION
    assert item.tokens == 19
    assert item.score == 1.0
    assert item.metadata["memory_id"] == "mem_01j00000000000000000000001"
    assert item.metadata["tokenizer_id"] == "cl100k_base"


@pytest.mark.parametrize("exc", [httpx.TimeoutException("timeout"), httpx.ConnectError("nope")])
def test_retrieve_operational_exception_returns_degraded_pack(exc):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    pack = _client(handler).retrieve_context_pack("ordinary task", token_budget=321)

    assert pack.items == []
    assert pack.tokens_used == 0
    assert pack.token_budget == 321
    assert pack.truncated is False
    assert pack.degraded is True


@pytest.mark.parametrize("status_code", [500, 503])
def test_retrieve_5xx_returns_degraded_pack(status_code: int):
    client = _client(lambda request: httpx.Response(status_code, json={"error": "down"}))

    pack = client.retrieve_context_pack("ordinary task")

    assert pack.degraded is True
    assert pack.items == []


@pytest.mark.parametrize("status_code", [400, 409, 422])
def test_retrieve_contract_status_fails_loud(status_code: int):
    client = _client(lambda request: httpx.Response(status_code, json=_fixture("error_response.json")))

    with pytest.raises(RemoteMemoryContractError):
        client.retrieve_context_pack("bad request")


@pytest.mark.parametrize(
    "payload",
    [
        b"{not json",
        {
            **_fixture("context_response.json"),
            "schema_version": "wrong",
        },
        {
            **_fixture("context_response.json"),
            "items": [{**_fixture("context_response.json")["items"][0], "type": "task_summary"}],
        },
    ],
)
def test_retrieve_invalid_response_fails_loud(payload):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(payload, bytes):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, json=payload)

    with pytest.raises(RemoteMemoryContractError):
        _client(handler).retrieve_context_pack("query")


def test_write_success_exact_route_payload_and_mapping():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        payload = _fixture("write_response.json")
        payload["request_id"] = "req-write"
        return httpx.Response(200, json=payload)

    client = _client(handler, request_id="req-write")
    response = client.write_memory_candidates(
        [
            MemoryCandidate(
                type=MemoryType.DECISION,
                content="Remote durable memory and local memory must not both be active.",
                tags=["memory"],
                importance=1.0,
                confidence=1.0,
                evidence_ref="user-explicit:test",
                metadata={"candidate_id": "cand-0001"},
            ),
            MemoryCandidate(
                type=MemoryType.RULE,
                content="Writes need provenance.",
                tags=["policy"],
                importance=0.9,
                confidence=1.0,
                evidence_ref="user-explicit:test",
                metadata={"candidate_id": "cand-0002"},
            ),
        ],
        session_id="sess-1",
        task_id="task-1",
    )

    assert captured["path"] == "/v1/memories/write"
    assert captured["payload"]["request_id"] == "req-write"
    assert captured["payload"]["project_id"] == "tomtit-agent"
    assert captured["payload"]["user_id"] == "local-user"
    assert captured["payload"]["task_id"] == "task-1"
    assert [c["candidate_id"] for c in captured["payload"]["candidates"]] == [
        "cand-0001",
        "cand-0002",
    ]
    assert response.written_ids == ["mem_01j00000000000000000000002"]
    assert response.skipped == ["cand-0002"]


def test_write_rejects_unsupported_type_before_http():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = _client(handler)
    with pytest.raises(RemoteMemoryContractError):
        client.write_memory_candidates(
            [
                MemoryCandidate(
                    type=MemoryType.TASK_SUMMARY,
                    content="summary",
                    evidence_ref="evidence",
                )
            ],
            task_id="task-1",
        )
    assert called is False


def test_write_rejects_missing_evidence_before_http():
    client = _client(lambda request: httpx.Response(200, json={}))

    with pytest.raises(RemoteMemoryConfigurationError):
        client.write_memory_candidates(
            [MemoryCandidate(type=MemoryType.FACT, content="fact")],
            task_id="task-1",
        )


@pytest.mark.parametrize("response", [httpx.Response(500), httpx.Response(503)])
def test_write_5xx_raises_no_false_persistence(response: httpx.Response):
    client = _client(lambda request: response)

    with pytest.raises(RemoteMemoryWriteError):
        client.write_memory_candidates(
            [
                MemoryCandidate(
                    type=MemoryType.FACT,
                    content="fact",
                    evidence_ref="evidence",
                )
            ],
            task_id="task-1",
        )


@pytest.mark.parametrize("status_code", [409, 422])
def test_write_contract_status_raises_no_duplicate_mapping(status_code: int):
    client = _client(lambda request: httpx.Response(status_code, json=_fixture("error_response.json")))

    with pytest.raises(RemoteMemoryWriteError):
        client.write_memory_candidates(
            [
                MemoryCandidate(
                    type=MemoryType.FACT,
                    content="fact",
                    evidence_ref="evidence",
                )
            ],
            task_id="task-1",
        )


def test_write_malformed_success_response_raises():
    client = _client(lambda request: httpx.Response(200, json={"schema_version": "wrong"}))

    with pytest.raises(RemoteMemoryWriteError):
        client.write_memory_candidates(
            [
                MemoryCandidate(
                    type=MemoryType.FACT,
                    content="fact",
                    evidence_ref="evidence",
                )
            ],
            task_id="task-1",
        )

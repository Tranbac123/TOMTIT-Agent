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
from agent_core.state.enums import MemoryType, SourceType, TrustLevel

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
        # Response envelope must correlate with the request (SPEC §10.2).
        payload["session_id"] = "sess-1"
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

    # Malformed/schema-invalid success payload is a contract failure (SPEC §10.2).
    with pytest.raises(RemoteMemoryContractError):
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


# ---------------------------------------------------------------------------
# SF1 — remote adapter trust/source fields
# ---------------------------------------------------------------------------

def _retrieve_pack():
    def handler(request):
        return httpx.Response(200, json=_fixture("context_response.json"))
    client = _client(handler)
    return client.retrieve_context_pack("test goal")


def test_remote_item_source_type_is_memory():
    pack = _retrieve_pack()
    assert len(pack.items) > 0
    for item in pack.items:
        assert item.source_type is SourceType.MEMORY


def test_remote_item_trust_level_is_untrusted_evidence():
    pack = _retrieve_pack()
    assert len(pack.items) > 0
    for item in pack.items:
        assert item.trust_level is TrustLevel.UNTRUSTED_EVIDENCE


def test_remote_item_source_ref_equals_memory_id():
    pack = _retrieve_pack()
    assert len(pack.items) > 0
    for item in pack.items:
        assert item.source_ref is not None
        assert item.source_ref == item.metadata["memory_id"]


def test_remote_wire_isolation():
    """Adding agent-side fields does not affect wire fixture SHA-256."""
    import hashlib
    fixture_path = FIXTURES / "context_response.json"
    sha = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    # SHA frozen at SF1 implementation baseline — wire must not change
    assert sha == "9f7ab7e561cf43b0dd5399a31d0f12072448a849a3f6235bf59a16ebabe73186"


# ---------------------------------------------------------------------------
# M7-A — required-write capability, caller request_id, response correlation
# ---------------------------------------------------------------------------

_HASH = "a" * 64


def _decision_candidate(candidate_id: str = "conf-1"):
    return MemoryCandidate(
        type=MemoryType.DECISION,
        content="use postgres",
        tags=[],
        importance=0.5,
        confidence=1.0,
        evidence_ref="user-explicit:task-1:" + candidate_id,
        metadata={"candidate_id": candidate_id},
    )


def _ok_results(candidate_id: str = "conf-1"):
    return [
        {
            "candidate_id": candidate_id,
            "status": "written",
            "memory_id": "mem_1",
            "content_hash": _HASH,
            "reason": None,
        }
    ]


def _ok_response(*, request_id="memory-write:conf-1", session_id="sess-1", results=None, written=1, skipped=0):
    return {
        "schema_version": "memory-contract-v1",
        "request_id": request_id,
        "project_id": "tomtit-agent",
        "user_id": "local-user",
        "session_id": session_id,
        "results": results if results is not None else _ok_results(),
        "written_count": written,
        "skipped_count": skipped,
    }


def test_remote_supports_required_write_true():
    client = _client(lambda r: httpx.Response(200, json=_ok_response()))
    assert client.supports_required_write is True


def test_caller_request_id_used_unchanged():
    captured = {}

    def handler(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_response(request_id="memory-write:conf-1"))

    # factory would return "req-FACTORY"; caller request_id must win.
    client = _client(handler, request_id="req-FACTORY")
    client.write_memory_candidates(
        [_decision_candidate("conf-1")],
        session_id="sess-1",
        task_id="task-1",
        request_id="memory-write:conf-1",
    )
    assert captured["payload"]["request_id"] == "memory-write:conf-1"


def test_request_id_factory_fallback_when_absent():
    captured = {}

    def handler(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_response(request_id="req-FACTORY"))

    client = _client(handler, request_id="req-FACTORY")
    client.write_memory_candidates(
        [_decision_candidate("conf-1")], session_id="sess-1", task_id="task-1"
    )
    assert captured["payload"]["request_id"] == "req-FACTORY"


def _expect_contract_error(response_json):
    client = _client(lambda r: httpx.Response(200, json=response_json), request_id="memory-write:conf-1")
    with pytest.raises(RemoteMemoryContractError):
        client.write_memory_candidates(
            [_decision_candidate("conf-1")],
            session_id="sess-1",
            task_id="task-1",
            request_id="memory-write:conf-1",
        )


def test_response_request_id_mismatch_rejected():
    _expect_contract_error(_ok_response(request_id="memory-write:WRONG"))


def test_response_session_id_mismatch_rejected():
    _expect_contract_error(_ok_response(session_id="sess-OTHER"))


def test_response_project_id_mismatch_rejected():
    resp = _ok_response()
    resp["project_id"] = "other-project"
    _expect_contract_error(resp)


def test_response_user_id_mismatch_rejected():
    resp = _ok_response()
    resp["user_id"] = "other-user"
    _expect_contract_error(resp)


def test_response_zero_result_rejected():
    _expect_contract_error(_ok_response(results=[], written=0, skipped=0))


def test_response_extra_result_rejected():
    extra = _ok_results("conf-1") + [
        {"candidate_id": "conf-2", "status": "written", "memory_id": "mem_2", "content_hash": _HASH, "reason": None}
    ]
    _expect_contract_error(_ok_response(results=extra, written=2, skipped=0))


def test_response_candidate_mismatch_rejected():
    wrong = [
        {"candidate_id": "WRONG", "status": "written", "memory_id": "mem_1", "content_hash": _HASH, "reason": None}
    ]
    _expect_contract_error(_ok_response(results=wrong))


def test_response_duplicate_result_rejected():
    dup = [
        {"candidate_id": "conf-1", "status": "written", "memory_id": "mem_1", "content_hash": _HASH, "reason": None},
        {"candidate_id": "conf-1", "status": "written", "memory_id": "mem_2", "content_hash": _HASH, "reason": None},
    ]
    _expect_contract_error(_ok_response(results=dup, written=2, skipped=0))


def test_response_skipped_duplicate_success():
    skipped_results = [
        {"candidate_id": "conf-1", "status": "skipped_duplicate", "memory_id": "mem_x", "content_hash": _HASH, "reason": "duplicate_content"}
    ]
    client = _client(
        lambda r: httpx.Response(200, json=_ok_response(results=skipped_results, written=0, skipped=1)),
        request_id="memory-write:conf-1",
    )
    resp = client.write_memory_candidates(
        [_decision_candidate("conf-1")],
        session_id="sess-1",
        task_id="task-1",
        request_id="memory-write:conf-1",
    )
    assert resp.written_ids == []
    assert resp.skipped == ["conf-1"]

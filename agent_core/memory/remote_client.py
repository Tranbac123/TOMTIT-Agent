from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import httpx
from pydantic import ValidationError

from agent_core.memory.contracts import ContextItem, ContextPack, MemoryCandidate, WriteResponse
from agent_core.memory.errors import (
    RemoteMemoryConfigurationError,
    RemoteMemoryContractError,
    RemoteMemoryUnavailableError,
    RemoteMemoryWriteError,
)
from agent_core.memory.wire.v1 import (
    ContextRequestV1,
    ContextResponseV1,
    ErrorEnvelopeV1,
    WriteCandidateV1,
    WriteRequestV1,
    WriteResponseV1,
)
from agent_core.state.enums import MemoryType, SourceType, TrustLevel

_RETRIEVE_PATH = "/v1/context/retrieve"
_WRITE_PATH = "/v1/memories/write"
_UNSUPPORTED_REMOTE_TYPES = {MemoryType.TASK_SUMMARY, MemoryType.SOURCE}


class RemoteMemoryClient:
    """Synchronous MemoryClientProtocol adapter for TOMTIT-Memory HTTP v1."""

    def __init__(
        self,
        *,
        base_url: str,
        project_id: str,
        default_user_id: str,
        timeout_seconds: float = 5.0,
        http_client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.base_url = self._normalize_base_url(base_url)
        self.project_id = self._required(project_id, "project_id")
        self.default_user_id = self._required(default_user_id, "default_user_id")
        if timeout_seconds <= 0:
            raise RemoteMemoryConfigurationError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self._request_id_factory = request_id_factory or (lambda: str(uuid4()))
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
        )

    @property
    def supports_required_write(self) -> bool:
        # Remote durable backend can perform an M7-A required confirmed write.
        return True

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> RemoteMemoryClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def retrieve_context_pack(
        self,
        goal: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        token_budget: int = 1500,
        max_items: int = 20,
    ) -> ContextPack:
        resolved_user_id = self._resolve_user(user_id)
        request = ContextRequestV1(
            request_id=self._new_request_id(),
            project_id=self.project_id,
            user_id=resolved_user_id,
            session_id=session_id,
            query=goal,
            type_filter=None,
            token_budget=token_budget,
            max_items=max_items,
        )
        try:
            response = self._client.post(
                self._url(_RETRIEVE_PATH),
                json=request.model_dump(mode="json"),
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return self._degraded_pack(token_budget=token_budget, reason=type(exc).__name__)

        if response.status_code == 503 or response.status_code >= 500:
            return self._degraded_pack(token_budget=token_budget, reason=f"http_{response.status_code}")
        if response.status_code >= 400:
            raise RemoteMemoryContractError(self._safe_error_message(response))

        try:
            payload = response.json()
            parsed = ContextResponseV1.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            raise RemoteMemoryContractError("invalid context response") from exc
        return self._to_context_pack(parsed)

    def write_memory_candidates(
        self,
        candidates: list[MemoryCandidate],
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        request_id: str | None = None,
    ) -> WriteResponse:
        if not candidates:
            return WriteResponse()
        resolved_user_id = self._resolve_user(user_id)
        resolved_task_id = self._required(task_id, "task_id")
        # Caller-controlled request_id (M7-A deterministic replay-stable identity) takes
        # precedence; when absent, preserve the existing per-call factory behavior.
        resolved_request_id = (
            self._required(request_id, "request_id")
            if request_id is not None
            else self._new_request_id()
        )
        wire_candidates = self._to_write_candidates(candidates)
        request = WriteRequestV1(
            request_id=resolved_request_id,
            project_id=self.project_id,
            user_id=resolved_user_id,
            session_id=session_id,
            task_id=resolved_task_id,
            candidates=wire_candidates,
        )
        try:
            response = self._client.post(
                self._url(_WRITE_PATH),
                json=request.model_dump(mode="json"),
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RemoteMemoryWriteError("remote memory write unavailable") from exc

        if response.status_code == 503 or response.status_code >= 500:
            raise RemoteMemoryWriteError("remote memory write unavailable")
        if response.status_code >= 400:
            raise RemoteMemoryWriteError(self._safe_error_message(response))

        try:
            payload = response.json()
            parsed = WriteResponseV1.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            # Malformed/schema-invalid success payload is a contract failure, not a
            # generic write failure (SPEC §10.2).
            raise RemoteMemoryContractError("invalid write response") from exc
        self._verify_write_correlation(parsed, request)
        return self._to_write_response(parsed)

    def _verify_write_correlation(
        self,
        parsed: WriteResponseV1,
        request: WriteRequestV1,
    ) -> None:
        """Verify the success response envelope correlates exactly with the request.

        Any mismatch is a contract failure (SPEC §10.2): no failed validation may
        return a domain success response.
        """
        if parsed.request_id != request.request_id:
            raise RemoteMemoryContractError("write response request_id mismatch")
        if parsed.project_id != request.project_id:
            raise RemoteMemoryContractError("write response project_id mismatch")
        if parsed.user_id != request.user_id:
            raise RemoteMemoryContractError("write response user_id mismatch")
        if parsed.session_id != request.session_id:
            raise RemoteMemoryContractError("write response session_id mismatch")

        expected_ids = [candidate.candidate_id for candidate in request.candidates]
        result_ids = [result.candidate_id for result in parsed.results]

        if len(result_ids) != len(expected_ids):
            raise RemoteMemoryContractError("write response result count mismatch")
        if len(set(result_ids)) != len(result_ids):
            raise RemoteMemoryContractError("write response has duplicate candidate ids")
        if set(result_ids) != set(expected_ids):
            raise RemoteMemoryContractError(
                "write response candidate ids do not match the request"
            )

        for result in parsed.results:
            if result.status == "written":
                if not result.memory_id or not result.memory_id.strip():
                    raise RemoteMemoryContractError(
                        "written result is missing a memory id"
                    )
            elif result.status == "skipped_duplicate":
                if result.reason != "duplicate_content":
                    raise RemoteMemoryContractError(
                        "skipped_duplicate result has an invalid reason"
                    )

    def _to_write_candidates(self, candidates: list[MemoryCandidate]) -> list[WriteCandidateV1]:
        result: list[WriteCandidateV1] = []
        for index, candidate in enumerate(candidates, start=1):
            if candidate.type in _UNSUPPORTED_REMOTE_TYPES:
                raise RemoteMemoryContractError(
                    f"unsupported remote memory type: {candidate.type.value}"
                )
            evidence_ref = self._required(candidate.evidence_ref, "evidence_ref")
            candidate_id = candidate.metadata.get("candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id.strip():
                candidate_id = f"cand-{index:04d}"
            result.append(
                WriteCandidateV1(
                    candidate_id=candidate_id,
                    type=candidate.type.value,
                    content=candidate.content,
                    tags=list(candidate.tags),
                    importance=candidate.importance,
                    confidence=candidate.confidence,
                    evidence_ref=evidence_ref,
                    metadata=dict(candidate.metadata),
                )
            )
        return result

    def _to_context_pack(self, response: ContextResponseV1) -> ContextPack:
        return ContextPack(
            items=[self._to_context_item(item, response) for item in response.items],
            total_items=response.total_items,
            tokens_used=response.tokens_used,
            token_budget=response.token_budget,
            truncated=response.truncated,
            degraded=response.degraded,
            memory_source="remote",
        )

    def _to_context_item(self, item, response: ContextResponseV1) -> ContextItem:
        metadata = dict(item.metadata)
        metadata.update(
            {
                "memory_id": item.memory_id,
                "tags": list(item.tags),
                "importance": item.importance,
                "confidence": item.confidence,
                "source_task_id": item.source_task_id,
                "evidence_ref": item.evidence_ref,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
                "tokenizer_id": response.tokenizer_id,
                "warnings": list(response.warnings),
            }
        )
        return ContextItem(
            content=item.content,
            type=MemoryType(item.type),
            score=item.score,
            tokens=item.token_cost,
            source="remote_memory",
            provenance="remote",
            confidence="normal",
            freshness="fresh",
            metadata=metadata,
            source_type=SourceType.MEMORY,
            trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
            source_ref=item.memory_id,
        )

    def _to_write_response(self, response: WriteResponseV1) -> WriteResponse:
        written_ids = [
            result.memory_id for result in response.results if result.status == "written"
        ]
        skipped = [
            result.candidate_id
            for result in response.results
            if result.status == "skipped_duplicate"
        ]
        return WriteResponse(written_ids=written_ids, skipped=skipped)

    def _safe_error_message(self, response: httpx.Response) -> str:
        try:
            envelope = ErrorEnvelopeV1.model_validate(response.json())
        except Exception:
            return f"remote memory contract error: HTTP {response.status_code}"
        return f"remote memory error {envelope.error.code}"

    def _degraded_pack(self, *, token_budget: int, reason: str) -> ContextPack:
        return ContextPack(
            items=[],
            total_items=0,
            tokens_used=0,
            token_budget=token_budget,
            truncated=False,
            degraded=True,
            memory_source="remote",
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _new_request_id(self) -> str:
        return self._required(self._request_id_factory(), "request_id")

    def _resolve_user(self, user_id: str | None) -> str:
        return self._required(user_id or self.default_user_id, "user_id")

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        normalized = RemoteMemoryClient._required(value, "base_url").rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise RemoteMemoryConfigurationError("base_url must start with http:// or https://")
        return normalized

    @staticmethod
    def _required(value: str | None, field_name: str) -> str:
        if value is None:
            raise RemoteMemoryConfigurationError(f"{field_name} is required")
        normalized = str(value).strip()
        if not normalized:
            raise RemoteMemoryConfigurationError(f"{field_name} is required")
        return normalized

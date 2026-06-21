from __future__ import annotations

from agent_core.memory.contracts import ContextPack, MemoryCandidate, WriteResponse


class NullMemoryClient:
    """No-op MemoryClientProtocol implementation for memory_backend=none."""

    @property
    def supports_required_write(self) -> bool:
        # Fail-closed: the null backend cannot perform an M7-A required confirmed write.
        return False

    def retrieve_context_pack(
        self,
        goal: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        token_budget: int = 1500,
        max_items: int = 20,
    ) -> ContextPack:
        return ContextPack(
            items=[],
            total_items=0,
            tokens_used=0,
            token_budget=token_budget,
            truncated=False,
            degraded=False,
            memory_source="remote",
        )

    def write_memory_candidates(
        self,
        candidates: list[MemoryCandidate],
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        request_id: str | None = None,
    ) -> WriteResponse:
        return WriteResponse()

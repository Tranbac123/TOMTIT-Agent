from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_core.memory.contracts import ContextPack, MemoryCandidate, WriteResponse


@runtime_checkable
class MemoryClientProtocol(Protocol):
    """Hợp đồng runtime gọi memory. KHÔNG nhận full AgentState — chỉ explicit params.
    Runtime tự rút user_id/session_id/task_id từ state và truyền vào. Giảm coupling,
    dễ test, remote client không kéo theo cả runtime state."""

    @property
    def supports_required_write(self) -> bool:
        """True only for backends that can perform an M7-A required confirmed write.

        Read-only and fail-closed by implementation: remote durable backends report
        True; local/null backends report False. RuntimeAgent checks this property
        instead of inspecting concrete client types (no isinstance gate)."""
        ...

    def retrieve_context_pack(
        self,
        goal: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        token_budget: int = 1500,
        max_items: int = 20,
    ) -> ContextPack: ...

    def write_memory_candidates(
        self,
        candidates: list[MemoryCandidate],
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        request_id: str | None = None,
    ) -> WriteResponse: ...

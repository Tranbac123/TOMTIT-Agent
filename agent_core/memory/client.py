from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_core.memory.contracts import ContextPack, MemoryCandidate, WriteResponse


@runtime_checkable
class MemoryClientProtocol(Protocol):
    """Hợp đồng runtime gọi memory. KHÔNG nhận full AgentState — chỉ explicit params.
    Runtime tự rút user_id/session_id/task_id từ state và truyền vào. Giảm coupling,
    dễ test, remote client không kéo theo cả runtime state."""

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
    ) -> WriteResponse: ...

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from agent_core.memory.base import MemoryStoreProtocol
from agent_core.runtime.runtime_agent import RuntimeAgent
from agent_core.runtime.session_runtime import SessionRuntime
from agent_core.state.agent_state import AgentState
from agent_core.state.session_state import SessionState


@dataclass
class RuntimeChatResult:
    content: str
    status: str
    provenance: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    run_id: str | None = None


@dataclass
class RuntimeRecallResult:
    content: str
    status: str
    provenance: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)


def _extract_provenance(state: AgentState) -> list[dict[str, Any]]:
    """Extract provenance from context_pack without fabricating data."""
    if state.context_pack is None or not state.context_pack.items:
        return []
    result: list[dict[str, Any]] = []
    for item in state.context_pack.items:
        entry: dict[str, Any] = {}
        memory_id = item.metadata.get("memory_id") or getattr(item, "source_ref", None)
        evidence_ref = item.metadata.get("evidence_ref")
        source_task_id = item.metadata.get("source_task_id")
        if memory_id:
            entry["memory_id"] = memory_id
        if evidence_ref:
            entry["evidence_ref"] = evidence_ref
        if source_task_id:
            entry["source_task_id"] = source_task_id
        if entry:
            result.append(entry)
    return result


class RuntimeAdapter:
    """Thin bridge to a single SessionRuntime instance for one web session.

    Wraps the synchronous SessionRuntime in an async interface using
    asyncio.to_thread() to avoid blocking the FastAPI event loop.
    """

    def __init__(
        self,
        *,
        agent: RuntimeAgent,
        store: MemoryStoreProtocol,
        session_state: SessionState,
        user_id: str | None = None,
    ) -> None:
        self._session_runtime = SessionRuntime(
            agent,
            store,
            session=session_state,
            user_id=user_id if user_id else None,
        )

    @property
    def session_id(self) -> str:
        return self._session_runtime.session_id

    async def send_chat(
        self,
        *,
        session_id: str,
        user_id: str,
        project_id: str,
        message: str,
    ) -> RuntimeChatResult:
        state: AgentState = await asyncio.to_thread(
            self._session_runtime.handle_turn, message
        )
        return RuntimeChatResult(
            content=state.final_answer or "",
            status=state.status.value,
            provenance=_extract_provenance(state),
            sources=[],
            run_id=state.task_id,
        )

    async def recall_memory(
        self,
        *,
        session_id: str,
        user_id: str,
        project_id: str,
        query: str,
    ) -> RuntimeRecallResult:
        state: AgentState = await asyncio.to_thread(
            self._session_runtime.run_memory_recall, query
        )
        return RuntimeRecallResult(
            content=state.final_answer or "",
            status=state.status.value,
            provenance=_extract_provenance(state),
            sources=[],
        )

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from agent_core.memory.base import MemoryStoreProtocol
from agent_core.runtime.runtime_agent import RuntimeAgent
from agent_core.state.session_state import SessionState
from agent_core.web_api.errors import (
    ProjectIdMismatchError,
    ProjectIdRejectedError,
    WebSessionNotFoundError,
)
from agent_core.web_api.models import (
    ChatResponse,
    MemoryRecallResponse,
    MessageRecord,
    RecallResult,
    SessionListResponse,
    SessionMessagesResponse,
    SessionResponse,
)
from agent_core.web_api.runtime_adapter import RuntimeAdapter, RuntimeChatResult, RuntimeRecallResult
from agent_core.web_api.stores import InMemoryWebStore

_logger = logging.getLogger(__name__)


def _read_configured_project_id(agent: object) -> str | None:
    """Return project_id from agent.memory_client if present, else None.

    Uses duck typing only — no isinstance on runtime classes. Only
    RemoteMemoryClient exposes project_id; LocalMemoryClient and
    NullMemoryClient do not, so they fall through to None safely.
    MagicMock in tests auto-creates attributes but they are not str,
    so the isinstance guard filters them out cleanly.
    """
    mem_client = getattr(agent, "memory_client", None)
    raw = getattr(mem_client, "project_id", None)
    return raw if isinstance(raw, str) and raw.strip() else None


class SessionManager:
    """Coordinates web sessions, transcript storage, and RuntimeAdapter instances.

    One RuntimeAdapter per web session is created in create_session() and held for
    the session's lifetime so multi-turn SessionRuntime state is preserved.

    Project-id enforcement (single-project mode):
    - At init, reads configured_project_id from agent.memory_client if available
      (remote backend only; local/null backends have no configured project_id).
    - create_session rejects sessions whose project_id differs from configured_project_id.
    - send_chat and recall_memory reject requests whose project_id differs from the
      session's project_id (set at creation time).
    """

    def __init__(
        self,
        *,
        agent: RuntimeAgent,
        store: MemoryStoreProtocol,
        adapter_factory: Callable[..., RuntimeAdapter] | None = None,
    ) -> None:
        self._agent = agent
        self._store = store
        self._adapter_factory = adapter_factory or RuntimeAdapter
        self._web_store = InMemoryWebStore()
        self._adapters: dict[str, RuntimeAdapter] = {}
        self._configured_project_id: str | None = _read_configured_project_id(agent)
        if self._configured_project_id:
            _logger.debug(
                "SessionManager: runtime project_id enforcement active (configured=%s)",
                self._configured_project_id,
            )

    def create_session(
        self,
        *,
        user_id: str,
        project_id: str,
        title: str | None = None,
    ) -> SessionResponse:
        if self._configured_project_id is not None and project_id != self._configured_project_id:
            raise ProjectIdRejectedError()

        web_session = self._web_store.create(
            user_id=user_id,
            project_id=project_id,
            title=title,
        )
        session_state = SessionState(
            session_id=web_session.session_id,
            created_at=web_session.created_at,
            updated_at=web_session.updated_at,
        )
        adapter = self._adapter_factory(
            agent=self._agent,
            store=self._store,
            session_state=session_state,
            user_id=user_id or None,
        )
        self._adapters[web_session.session_id] = adapter
        return web_session.to_response()

    def list_sessions(self) -> list[SessionResponse]:
        return [s.to_response() for s in self._web_store.list_all()]

    def get_messages(self, session_id: str) -> SessionMessagesResponse:
        session = self._web_store.get(session_id)
        if session is None:
            raise WebSessionNotFoundError(session_id)
        return SessionMessagesResponse(
            session_id=session_id,
            messages=list(session.messages),
        )

    async def send_chat(
        self,
        *,
        session_id: str,
        user_id: str,
        project_id: str,
        message: str,
    ) -> ChatResponse:
        session = self._web_store.get(session_id)
        if session is None:
            raise WebSessionNotFoundError(session_id)
        adapter = self._adapters.get(session_id)
        if adapter is None:
            raise WebSessionNotFoundError(session_id)

        # Enforce project_id consistency BEFORE any transcript mutation.
        if project_id != session.project_id:
            raise ProjectIdMismatchError(session_id)

        now = datetime.now(timezone.utc)
        user_msg = MessageRecord(
            id=str(uuid4()),
            role="user",
            content=message,
            created_at=now,
        )
        self._web_store.append_message(session_id, user_msg)

        result: RuntimeChatResult = await adapter.send_chat(
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
            message=message,
        )

        assistant_msg = MessageRecord(
            id=str(uuid4()),
            role="assistant",
            content=result.content,
            created_at=datetime.now(timezone.utc),
            provenance=result.provenance,
            sources=result.sources,
            status=result.status,
        )
        self._web_store.append_message(session_id, assistant_msg)

        return ChatResponse(session_id=session_id, assistant_message=assistant_msg)

    async def recall_memory(
        self,
        *,
        session_id: str,
        user_id: str,
        project_id: str,
        query: str,
    ) -> MemoryRecallResponse:
        session = self._web_store.get(session_id)
        if session is None:
            raise WebSessionNotFoundError(session_id)
        adapter = self._adapters.get(session_id)
        if adapter is None:
            raise WebSessionNotFoundError(session_id)

        # Enforce project_id consistency before the runtime call.
        if project_id != session.project_id:
            raise ProjectIdMismatchError(session_id)

        result: RuntimeRecallResult = await adapter.recall_memory(
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
            query=query,
        )

        return MemoryRecallResponse(
            session_id=session_id,
            result=RecallResult(
                content=result.content,
                status=result.status,
                provenance=result.provenance,
                sources=result.sources,
            ),
        )

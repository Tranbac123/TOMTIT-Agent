from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from agent_core.web_api.models import MessageRecord, SessionResponse


@dataclass
class WebSession:
    session_id: str
    user_id: str
    project_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageRecord] = field(default_factory=list)

    def to_response(self) -> SessionResponse:
        return SessionResponse(
            session_id=self.session_id,
            user_id=self.user_id,
            project_id=self.project_id,
            title=self.title,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class InMemoryWebStore:
    """In-memory storage for session metadata and display transcripts."""

    def __init__(self) -> None:
        self._sessions: dict[str, WebSession] = {}

    def create(
        self,
        *,
        user_id: str,
        project_id: str,
        title: str | None = None,
    ) -> WebSession:
        now = datetime.now(timezone.utc)
        session = WebSession(
            session_id=str(uuid4()),
            user_id=user_id,
            project_id=project_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> WebSession | None:
        return self._sessions.get(session_id)

    def list_all(self) -> list[WebSession]:
        return list(self._sessions.values())

    def append_message(self, session_id: str, message: MessageRecord) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Session not found: {session_id}")
        session.messages.append(message)
        session.updated_at = datetime.now(timezone.utc)

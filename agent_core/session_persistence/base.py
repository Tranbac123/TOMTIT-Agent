from __future__ import annotations

from typing import Protocol

from agent_core.state.session_state import SessionState


class SessionStoreProtocol(Protocol):
    def save(self, session: SessionState) -> None: ...

    def load(self, session_id: str) -> SessionState | None: ...

from __future__ import annotations


class SessionPersistenceError(Exception):
    """Unable to persist session data."""

    def __init__(self, message: str = "Unable to persist session data") -> None:
        super().__init__(message)


class SessionDataCorruptionError(SessionPersistenceError):
    """Session data is corrupt or cannot be deserialized."""


class SessionNotFoundError(SessionPersistenceError):
    """Session not found when attempting to resume."""

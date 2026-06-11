from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from agent_core.state.enums import MemoryType, SourceType


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    return datetime.fromisoformat(value)


def _enum_value(value: Enum | str) -> str:
    if isinstance(value, Enum):
        return value.value
    return str(value)


@dataclass
class MemoryRecord:
    content: str
    type: MemoryType = MemoryType.NOTE
    id: str = field(default_factory=lambda: str(uuid4()))

    user_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    source_event_id: str | None = None

    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    confidence: float = 1.0
    source: SourceType = SourceType.USER

    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    deleted_at: datetime | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_updated(self) -> None:
        self.updated_at = utc_now()

    def mark_deleted(self) -> None:
        now = utc_now()
        self.deleted_at = now
        self.updated_at = now

    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "type": self.type.value,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "source_event_id": self.source_event_id,
            "tags": list(self.tags),
            "importance": self.importance,
            "confidence": self.confidence,
            "source": self.source.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryRecord:
        return cls(
            id=str(data["id"]),
            content=str(data["content"]),
            type=MemoryType(data.get("type", MemoryType.NOTE.value)),
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            task_id=data.get("task_id"),
            run_id=data.get("run_id"),
            source_event_id=data.get("source_event_id"),
            tags=list(data.get("tags") or []),
            importance=float(data.get("importance", 0.5)),
            confidence=float(data.get("confidence", 1.0)),
            source=SourceType(data.get("source", SourceType.USER.value)),
            created_at=_parse_datetime(data.get("created_at")) or utc_now(),
            updated_at=_parse_datetime(data.get("updated_at")) or utc_now(),
            deleted_at=_parse_datetime(data.get("deleted_at")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class MemoryQuery:
    text: str = ""
    user_id: str | None = None
    session_id: str | None = None
    types: list[MemoryType] | None = None
    tags: list[str] | None = None
    include_deleted: bool = False
    limit: int = 10


@dataclass
class EpisodeRecord:
    goal: str
    task_id: str
    status: str
    id: str = field(default_factory=lambda: str(uuid4()))

    user_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None

    final_answer: str | None = None
    history: list[str] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "status": self.status,
            "final_answer": self.final_answer,
            "history": list(self.history),
            "observations": list(self.observations),
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EpisodeRecord:
        return cls(
            id=str(data["id"]),
            goal=str(data["goal"]),
            task_id=str(data["task_id"]),
            run_id=data.get("run_id"),
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            status=str(data["status"]),
            final_answer=data.get("final_answer"),
            history=list(data.get("history") or []),
            observations=list(data.get("observations") or []),
            errors=list(data.get("errors") or []),
            metadata=dict(data.get("metadata") or {}),
            created_at=_parse_datetime(data.get("created_at")) or utc_now(),
        )
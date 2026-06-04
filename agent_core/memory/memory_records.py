from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_core.state.enums import MemoryType, SourceType


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class MemoryRecord:
    content: str
    type: MemoryType = MemoryType.NOTE
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str | None = None
    session_id: str | None = None
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    confidence: float = 1.0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    source: SourceType = SourceType.USER
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryQuery:
    text: str = ""
    user_id: str | None = None
    session_id: str | None = None
    types: list[MemoryType] | None = None
    tags: list[str] | None = None
    limit: int = 10

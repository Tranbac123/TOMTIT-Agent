from __future__ import annotations

from typing import Any, Protocol

from agent_core.memory.memory_records import EpisodeRecord, MemoryQuery, MemoryRecord
from agent_core.state.enums import MemoryType, SourceType


class MemoryStoreProtocol(Protocol):
    """
    Persistence-level memory store.

    Store chịu trách nhiệm lưu, đọc, search, update, delete MemoryRecord.
    Store không nên chứa logic suy luận cao cấp như chọn memory nào nên ghi
    hoặc memory nào nên promote thành decision/preference.
    """

    def write(self, record: MemoryRecord) -> MemoryRecord: ...

    def get(self, memory_id: str) -> MemoryRecord | None: ...

    def search(self, query: MemoryQuery) -> list[MemoryRecord]: ...

    def update(
        self,
        memory_id: str,
        patch: dict[str, Any],
    ) -> MemoryRecord | None: ...

    def delete(
        self,
        memory_id: str,
        *,
        reason: str | None = None,
    ) -> bool: ...

    def list_all(
        self,
        *,
        include_deleted: bool = False,
    ) -> list[MemoryRecord]: ...

    # MVP compatibility for current tools.
    # Later, these can move fully behind MemoryAgent.
    def write_note(self, name: str, content: str) -> MemoryRecord: ...

    def read_note(self, name: str) -> str | None: ...

    def list_notes(self) -> list[str]: ...


class EpisodeStoreProtocol(Protocol):
    """
    Persistence contract for runtime episodes.

    EpisodeRecord dùng để tracking/replay/eval/self-improvement sau này.
    """

    def write_episode(self, episode: EpisodeRecord) -> EpisodeRecord: ...

    def list_episodes(
        self,
        *,
        limit: int = 50,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> list[EpisodeRecord]: ...


class MemoryAgentProtocol(Protocol):
    """
    Domain-level memory API.

    MemoryAgent hiểu note/fact/preference/decision và gọi MemoryStore bên dưới.
    Runtime/tool layer nên gọi API này khi cần logic memory domain rõ hơn.
    """

    def write_note(
        self,
        name: str,
        content: str,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        source_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord: ...

    def read_note(self, name: str) -> str | None: ...

    def list_notes(self) -> list[str]: ...

    def save_fact(
        self,
        content: str,
        tags: list[str] | None = None,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        source_event_id: str | None = None,
        importance: float = 0.5,
        confidence: float = 1.0,
        source: SourceType = SourceType.USER,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord: ...

    def save_preference(
        self,
        content: str,
        tags: list[str] | None = None,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        source_event_id: str | None = None,
        importance: float = 0.7,
        confidence: float = 1.0,
        source: SourceType = SourceType.USER,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord: ...

    def save_decision(
        self,
        content: str,
        tags: list[str] | None = None,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        source_event_id: str | None = None,
        importance: float = 0.8,
        confidence: float = 1.0,
        source: SourceType = SourceType.USER,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord: ...

    def save_memory(
        self,
        content: str,
        memory_type: MemoryType,
        tags: list[str] | None = None,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        source_event_id: str | None = None,
        importance: float = 0.5,
        confidence: float = 1.0,
        source: SourceType = SourceType.USER,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord: ...

    def get_memory(self, memory_id: str) -> MemoryRecord | None: ...

    def search_memory(
        self,
        query: str,
        *,
        limit: int = 10,
        types: list[MemoryType] | None = None,
        tags: list[str] | None = None,
        include_deleted: bool = False,
    ) -> list[MemoryRecord]: ...

    def delete_memory(
        self,
        memory_id: str,
        reason: str | None = None,
    ) -> bool: ...

    def summarize_memory(
        self,
        query: str = "",
        *,
        limit: int = 10,
    ) -> str: ...
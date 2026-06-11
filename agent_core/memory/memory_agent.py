from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_core.memory.base import MemoryStoreProtocol
from agent_core.memory.memory_records import MemoryQuery, MemoryRecord
from agent_core.state.enums import MemoryType, SourceType


@dataclass
class MemoryAgent:
    store: MemoryStoreProtocol
    user_id: str | None = None
    session_id: str | None = None

    def write_note(
        self,
        name: str,
        content: str,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        source_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        note_name = name.strip()
        if not note_name:
            raise ValueError("note name cannot be empty")

        record = self._record(
            content=content,
            memory_type=MemoryType.NOTE,
            task_id=task_id,
            run_id=run_id,
            source_event_id=source_event_id,
            importance=0.5,
            confidence=1.0,
            source=SourceType.USER,
            metadata={
                **(metadata or {}),
                "name": note_name,
            },
        )
        return self.store.write(record)

    def read_note(self, name: str) -> str | None:
        return self.store.read_note(name)

    def list_notes(self) -> list[str]:
        return self.store.list_notes()

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
    ) -> MemoryRecord:
        return self.save_memory(
            content=content,
            memory_type=MemoryType.FACT,
            tags=tags,
            task_id=task_id,
            run_id=run_id,
            source_event_id=source_event_id,
            importance=importance,
            confidence=confidence,
            source=source,
            metadata=metadata,
        )

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
    ) -> MemoryRecord:
        return self.save_memory(
            content=content,
            memory_type=MemoryType.PREFERENCE,
            tags=tags,
            task_id=task_id,
            run_id=run_id,
            source_event_id=source_event_id,
            importance=importance,
            confidence=confidence,
            source=source,
            metadata=metadata,
        )

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
    ) -> MemoryRecord:
        return self.save_memory(
            content=content,
            memory_type=MemoryType.DECISION,
            tags=tags,
            task_id=task_id,
            run_id=run_id,
            source_event_id=source_event_id,
            importance=importance,
            confidence=confidence,
            source=source,
            metadata=metadata,
        )

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
    ) -> MemoryRecord:
        if not content.strip():
            raise ValueError("memory content cannot be empty")

        record = self._record(
            content=content,
            memory_type=memory_type,
            tags=tags,
            task_id=task_id,
            run_id=run_id,
            source_event_id=source_event_id,
            importance=importance,
            confidence=confidence,
            source=source,
            metadata=metadata,
        )
        return self.store.write(record)

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        return self.store.get(memory_id)

    def search_memory(
        self,
        query: str,
        *,
        limit: int = 10,
        types: list[MemoryType] | None = None,
        tags: list[str] | None = None,
        include_deleted: bool = False,
    ) -> list[MemoryRecord]:
        return self.store.search(
            MemoryQuery(
                text=query,
                user_id=self.user_id,
                session_id=self.session_id,
                types=types,
                tags=tags,
                include_deleted=include_deleted,
                limit=limit,
            )
        )

    def delete_memory(
        self,
        memory_id: str,
        reason: str | None = None,
    ) -> bool:
        return self.store.delete(memory_id, reason=reason)

    def summarize_memory(
        self,
        query: str = "",
        *,
        limit: int = 10,
    ) -> str:
        records = self.search_memory(query=query, limit=limit)

        if not records:
            return "Không có memory phù hợp."

        lines: list[str] = []
        for record in records:
            tags = f" tags={record.tags}" if record.tags else ""
            lines.append(
                f"- [{record.type.value}] {record.content}"
                f" (importance={record.importance:.2f}, "
                f"confidence={record.confidence:.2f}{tags})"
            )

        return "\n".join(lines)

    def _record(
        self,
        *,
        content: str,
        memory_type: MemoryType,
        tags: list[str] | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        source_event_id: str | None = None,
        importance: float = 0.5,
        confidence: float = 1.0,
        source: SourceType = SourceType.USER,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        return MemoryRecord(
            content=content,
            type=memory_type,
            user_id=self.user_id,
            session_id=self.session_id,
            task_id=task_id,
            run_id=run_id,
            source_event_id=source_event_id,
            tags=tags or [],
            importance=importance,
            confidence=confidence,
            source=source,
            metadata=metadata or {},
        )
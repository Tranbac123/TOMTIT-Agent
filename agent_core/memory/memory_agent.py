from __future__ import annotations

from dataclasses import dataclass

from agent_core.memory.base import MemoryStoreProtocol
from agent_core.memory.memory_records import MemoryQuery, MemoryRecord
from agent_core.state.enums import MemoryType


@dataclass
class MemoryAgent:
    store: MemoryStoreProtocol
    user_id: str | None = None
    session_id: str | None = None

    def write_note(self, name: str, content: str) -> MemoryRecord:
        record = self._record(content, MemoryType.NOTE, metadata={"name": name})
        self.store.write(record)
        return record

    def read_note(self, name: str) -> str | None:
        return self.store.read_note(name)

    def list_notes(self) -> list[str]:
        return self.store.list_notes()

    def save_fact(self, content: str, tags: list[str] | None = None) -> MemoryRecord:
        return self._write_typed(content, MemoryType.FACT, tags)

    def save_preference(self, content: str, tags: list[str] | None = None) -> MemoryRecord:
        return self._write_typed(content, MemoryType.PREFERENCE, tags)

    def save_decision(self, content: str, tags: list[str] | None = None) -> MemoryRecord:
        return self._write_typed(content, MemoryType.DECISION, tags)

    def search_memory(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        return self.store.search(MemoryQuery(text=query, user_id=self.user_id, limit=limit))

    def summarize_memory(self, query: str = "", limit: int = 10) -> str:
        records = self.search_memory(query=query, limit=limit)
        if not records:
            return "Không có memory phù hợp."
        return "\n".join(f"- [{record.type.value}] {record.content}" for record in records)

    def _write_typed(
        self,
        content: str,
        memory_type: MemoryType,
        tags: list[str] | None = None,
    ) -> MemoryRecord:
        record = self._record(content, memory_type, tags=tags or [])
        self.store.write(record)
        return record

    def _record(
        self,
        content: str,
        memory_type: MemoryType,
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ) -> MemoryRecord:
        return MemoryRecord(
            content=content,
            type=memory_type,
            user_id=self.user_id,
            session_id=self.session_id,
            tags=tags or [],
            metadata=metadata or {},
        )

from __future__ import annotations

from dataclasses import dataclass, field

from agent_core.memory.memory_records import MemoryQuery, MemoryRecord, utc_now
from agent_core.state.enums import MemoryType


@dataclass
class InMemoryMemoryStore:
    records: dict[str, MemoryRecord] = field(default_factory=dict)
    note_index: dict[str, str] = field(default_factory=dict)

    @property
    def notes(self) -> dict[str, str]:
        return {
            name: self.records[memory_id].content
            for name, memory_id in self.note_index.items()
            if memory_id in self.records
        }

    def write(self, record: MemoryRecord) -> None:
        record.updated_at = utc_now()
        self.records[record.id] = record
        if record.type == MemoryType.NOTE and "name" in record.metadata:
            self.note_index[str(record.metadata["name"])] = record.id

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self.records.get(memory_id)

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        text = query.text.lower().strip()
        tags = set(query.tags or [])
        results: list[MemoryRecord] = []

        for record in self.records.values():
            if query.user_id and record.user_id != query.user_id:
                continue
            if query.session_id and record.session_id != query.session_id:
                continue
            if query.types and record.type not in query.types:
                continue
            if tags and not tags.intersection(record.tags):
                continue
            if text:
                haystack = " ".join([record.content, " ".join(record.tags), str(record.metadata)]).lower()
                if text not in haystack:
                    continue
            results.append(record)

        results.sort(key=lambda item: (item.importance, item.updated_at), reverse=True)
        return results[: query.limit]

    def write_note(self, name: str, content: str) -> None:
        if not name.strip():
            raise ValueError("note name cannot be empty")
        memory_id = self.note_index.get(name)
        if memory_id and memory_id in self.records:
            record = self.records[memory_id]
            record.content = content
            record.updated_at = utc_now()
            return
        self.write(MemoryRecord(content=content, type=MemoryType.NOTE, metadata={"name": name}))

    def read_note(self, name: str) -> str | None:
        memory_id = self.note_index.get(name)
        if not memory_id:
            return None
        record = self.records.get(memory_id)
        return record.content if record else None

    def list_notes(self) -> list[str]:
        return list(self.note_index.keys())

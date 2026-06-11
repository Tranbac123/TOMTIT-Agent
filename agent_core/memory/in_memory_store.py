from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.memory.base import MemoryStoreProtocol
from agent_core.memory.memory_records import MemoryQuery, MemoryRecord
from agent_core.state.enums import MemoryType


@dataclass
class InMemoryStore(MemoryStoreProtocol):
    records: dict[str, MemoryRecord] = field(default_factory=dict)
    note_index: dict[str, str] = field(default_factory=dict)

    @property
    def notes(self) -> dict[str, str]:
        return {
            name: record.content
            for name, memory_id in self.note_index.items()
            if (record := self.records.get(memory_id)) is not None
            and not record.is_deleted()
        }

    def write(self, record: MemoryRecord) -> MemoryRecord:
        record.mark_updated()
        self.records[record.id] = record
        self._sync_note_index(record)
        return record

    def get(self, memory_id: str) -> MemoryRecord | None:
        record = self.records.get(memory_id)
        if record is None or record.is_deleted():
            return None
        return record

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        text = query.text.lower().strip()
        tags = set(query.tags or [])
        results: list[MemoryRecord] = []

        for record in self.records.values():
            if record.is_deleted() and not query.include_deleted:
                continue

            if query.user_id and record.user_id != query.user_id:
                continue

            if query.session_id and record.session_id != query.session_id:
                continue

            if query.types and record.type not in query.types:
                continue

            if tags and not tags.intersection(record.tags):
                continue

            if text and not self._matches_text(record, text):
                continue

            results.append(record)

        results.sort(
            key=lambda item: (item.importance, item.updated_at),
            reverse=True,
        )
        return results[: query.limit]

    def update(
        self,
        memory_id: str,
        patch: dict[str, Any],
    ) -> MemoryRecord | None:
        record = self.records.get(memory_id)
        if record is None or record.is_deleted():
            return None

        old_note_name = self._note_name(record)

        for key, value in patch.items():
            if key in {"id", "created_at"}:
                continue

            if key == "metadata":
                record.metadata.update(dict(value or {}))
                continue

            if hasattr(record, key):
                setattr(record, key, value)

        record.mark_updated()
        self._remove_stale_note_index(old_note_name, record.id)
        self._sync_note_index(record)
        return record

    def delete(
        self,
        memory_id: str,
        *,
        reason: str | None = None,
    ) -> bool:
        record = self.records.get(memory_id)
        if record is None or record.is_deleted():
            return False

        if reason:
            record.metadata["delete_reason"] = reason

        record.mark_deleted()

        note_name = self._note_name(record)
        if note_name and self.note_index.get(note_name) == memory_id:
            del self.note_index[note_name]

        return True

    def list_all(
        self,
        *,
        include_deleted: bool = False,
    ) -> list[MemoryRecord]:
        records = list(self.records.values())

        if not include_deleted:
            records = [record for record in records if not record.is_deleted()]

        records.sort(key=lambda item: item.updated_at, reverse=True)
        return records

    def write_note(self, name: str, content: str) -> MemoryRecord:
        note_name = name.strip()
        if not note_name:
            raise ValueError("note name cannot be empty")

        memory_id = self.note_index.get(note_name)
        if memory_id:
            existing = self.records.get(memory_id)
            if existing is not None and not existing.is_deleted():
                existing.content = content
                existing.mark_updated()
                return existing

        record = MemoryRecord(
            content=content,
            type=MemoryType.NOTE,
            metadata={"name": note_name},
        )
        return self.write(record)

    def read_note(self, name: str) -> str | None:
        note_name = name.strip()
        memory_id = self.note_index.get(note_name)
        if not memory_id:
            return None

        record = self.records.get(memory_id)
        if record is None or record.is_deleted():
            return None

        return record.content

    def list_notes(self) -> list[str]:
        valid_names = [
            name
            for name, memory_id in self.note_index.items()
            if (record := self.records.get(memory_id)) is not None
            and not record.is_deleted()
        ]
        return sorted(valid_names)

    def _matches_text(self, record: MemoryRecord, text: str) -> bool:
        haystack = " ".join(
            [
                record.content,
                " ".join(record.tags),
                str(record.metadata),
                record.type.value,
            ]
        ).lower()
        return text in haystack

    def _sync_note_index(self, record: MemoryRecord) -> None:
        if record.type != MemoryType.NOTE or record.is_deleted():
            return

        note_name = self._note_name(record)
        if note_name:
            self.note_index[note_name] = record.id

    def _note_name(self, record: MemoryRecord) -> str | None:
        name = record.metadata.get("name")
        if name is None:
            return None

        note_name = str(name).strip()
        return note_name or None

    def _remove_stale_note_index(
        self,
        old_note_name: str | None,
        memory_id: str,
    ) -> None:
        if old_note_name and self.note_index.get(old_note_name) == memory_id:
            del self.note_index[old_note_name]
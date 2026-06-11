from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_core.memory.base import EpisodeStoreProtocol, MemoryStoreProtocol
from agent_core.memory.memory_records import EpisodeRecord, MemoryQuery, MemoryRecord
from agent_core.state.enums import MemoryType, SourceType


@dataclass
class FileMemoryStore(MemoryStoreProtocol, EpisodeStoreProtocol):
    memory_dir: str | Path = ".agent/memory"

    def __post_init__(self) -> None:
        self.memory_dir = Path(self.memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.records_path = self.memory_dir / "records.jsonl"
        self.episodes_path = self.memory_dir / "episodes.jsonl"

    def write(self, record: MemoryRecord) -> MemoryRecord:
        record.mark_updated()
        self._append_jsonl(self.records_path, record.to_dict())
        return record

    def get(self, memory_id: str) -> MemoryRecord | None:
        record = self._latest_record_by_id(memory_id)
        if record is None or record.is_deleted():
            return None
        return record

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        text = query.text.lower().strip()
        tags = set(query.tags or [])
        results: list[MemoryRecord] = []

        for record in self.list_all(include_deleted=query.include_deleted):
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
        records = self._load_latest_records()
        record = records.get(memory_id)

        if record is None or record.is_deleted():
            return None

        self._apply_patch(record, patch)
        record.mark_updated()

        records[memory_id] = record
        self._rewrite_records(records.values())
        return record

    def delete(
        self,
        memory_id: str,
        *,
        reason: str | None = None,
    ) -> bool:
        records = self._load_latest_records()
        record = records.get(memory_id)

        if record is None or record.is_deleted():
            return False

        if reason:
            record.metadata["delete_reason"] = reason

        record.mark_deleted()

        records[memory_id] = record
        self._rewrite_records(records.values())
        return True

    def list_all(
        self,
        *,
        include_deleted: bool = False,
    ) -> list[MemoryRecord]:
        records = list(self._load_latest_records().values())

        if not include_deleted:
            records = [record for record in records if not record.is_deleted()]

        records.sort(key=lambda item: item.updated_at, reverse=True)
        return records

    def write_note(self, name: str, content: str) -> MemoryRecord:
        note_name = name.strip()
        if not note_name:
            raise ValueError("note name cannot be empty")

        existing = self._latest_note_by_name(note_name)
        if existing is not None:
            return self.update(existing.id, {"content": content}) or existing

        return self.write(
            MemoryRecord(
                content=content,
                type=MemoryType.NOTE,
                metadata={"name": note_name},
            )
        )

    def read_note(self, name: str) -> str | None:
        note = self._latest_note_by_name(name.strip())
        return note.content if note is not None else None

    def list_notes(self) -> list[str]:
        names: set[str] = set()

        for record in self.list_all():
            if record.type != MemoryType.NOTE:
                continue

            note_name = self._note_name(record)
            if note_name:
                names.add(note_name)

        return sorted(names)

    def write_episode(self, episode: EpisodeRecord) -> EpisodeRecord:
        self._append_jsonl(self.episodes_path, episode.to_dict())
        return episode

    def list_episodes(
        self,
        *,
        limit: int = 50,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> list[EpisodeRecord]:
        episodes = [
            EpisodeRecord.from_dict(row)
            for row in self._read_jsonl(self.episodes_path)
        ]

        if user_id is not None:
            episodes = [episode for episode in episodes if episode.user_id == user_id]

        if session_id is not None:
            episodes = [
                episode for episode in episodes if episode.session_id == session_id
            ]

        episodes.sort(key=lambda item: item.created_at, reverse=True)
        return episodes[:limit]

    def _latest_record_by_id(self, memory_id: str) -> MemoryRecord | None:
        return self._load_latest_records().get(memory_id)

    def _latest_note_by_name(self, name: str) -> MemoryRecord | None:
        note_name = name.strip()
        if not note_name:
            return None

        candidates = [
            record
            for record in self.list_all()
            if record.type == MemoryType.NOTE
            and self._note_name(record) == note_name
            and not record.is_deleted()
        ]

        if not candidates:
            return None

        candidates.sort(key=lambda item: item.updated_at, reverse=True)
        return candidates[0]

    def _load_latest_records(self) -> dict[str, MemoryRecord]:
        records: dict[str, MemoryRecord] = {}

        for row in self._read_jsonl(self.records_path):
            record = MemoryRecord.from_dict(row)
            current = records.get(record.id)

            if current is None or record.updated_at >= current.updated_at:
                records[record.id] = record

        return records

    def _rewrite_records(self, records: Any) -> None:
        rows = [record.to_dict() for record in records]
        self._write_jsonl_atomic(self.records_path, rows)

    def _apply_patch(self, record: MemoryRecord, patch: dict[str, Any]) -> None:
        for key, value in patch.items():
            if key in {"id", "created_at"}:
                continue

            if key == "metadata":
                record.metadata.update(dict(value or {}))
                continue

            if key == "type":
                record.type = value if isinstance(value, MemoryType) else MemoryType(value)
                continue

            if key == "source":
                record.source = (
                    value if isinstance(value, SourceType) else SourceType(value)
                )
                continue

            if hasattr(record, key):
                setattr(record, key, value)

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

    def _note_name(self, record: MemoryRecord) -> str | None:
        name = record.metadata.get("name")
        if name is None:
            return None

        note_name = str(name).strip()
        return note_name or None

    def _append_jsonl(self, path: Path, row: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []

        rows: list[dict[str, Any]] = []

        with path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()
                if not line:
                    continue

                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSONL at {path}:{line_number}: {exc}"
                    ) from exc

        return rows

    def _write_jsonl_atomic(self, path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = path.with_suffix(path.suffix + ".tmp")

        with temp_path.open("w", encoding="utf-8") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")

        temp_path.replace(path)
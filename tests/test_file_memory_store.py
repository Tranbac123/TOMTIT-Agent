from agent_core.memory.file_store import FileMemoryStore
from agent_core.memory.memory_records import EpisodeRecord, MemoryQuery, MemoryRecord
from agent_core.state.enums import MemoryType


def test_file_store_write_and_get(tmp_path):
    store = FileMemoryStore(tmp_path / ".agent" / "memory")
    record = MemoryRecord(content="TOMTIT memory", type=MemoryType.FACT)

    written = store.write(record)
    loaded = store.get(record.id)

    assert written.id == record.id
    assert loaded is not None
    assert loaded.content == "TOMTIT memory"


def test_file_store_write_read_note(tmp_path):
    store = FileMemoryStore(tmp_path / ".agent" / "memory")

    record = store.write_note("project", "TOMTIT Agent")

    assert record.type == MemoryType.NOTE
    assert store.read_note("project") == "TOMTIT Agent"
    assert store.list_notes() == ["project"]


def test_file_store_update_note(tmp_path):
    store = FileMemoryStore(tmp_path / ".agent" / "memory")

    store.write_note("project", "old")
    store.write_note("project", "new")

    assert store.read_note("project") == "new"
    assert len(store.list_all()) == 1


def test_file_store_search(tmp_path):
    store = FileMemoryStore(tmp_path / ".agent" / "memory")

    store.write(
        MemoryRecord(
            content="TOMTIT uses state-first architecture.",
            type=MemoryType.DECISION,
            tags=["architecture"],
        )
    )

    results = store.search(
        MemoryQuery(
            text="state-first",
            types=[MemoryType.DECISION],
            tags=["architecture"],
        )
    )

    assert len(results) == 1
    assert results[0].type == MemoryType.DECISION


def test_file_store_delete_soft_deletes(tmp_path):
    store = FileMemoryStore(tmp_path / ".agent" / "memory")
    record = store.write(MemoryRecord(content="temporary"))

    deleted = store.delete(record.id, reason="cleanup")

    assert deleted
    assert store.get(record.id) is None
    assert store.list_all() == []

    deleted_records = store.list_all(include_deleted=True)
    assert len(deleted_records) == 1
    assert deleted_records[0].metadata["delete_reason"] == "cleanup"


def test_file_store_episode_roundtrip(tmp_path):
    store = FileMemoryStore(tmp_path / ".agent" / "memory")
    episode = EpisodeRecord(
        goal="Tính 1 + 1",
        task_id="task-1",
        status="completed",
        final_answer="2",
    )

    store.write_episode(episode)
    episodes = store.list_episodes()

    assert len(episodes) == 1
    assert episodes[0].goal == "Tính 1 + 1"
    assert episodes[0].final_answer == "2"
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.memory.memory_records import MemoryQuery, MemoryRecord
from agent_core.state.enums import MemoryType


def test_in_memory_store_write_and_get():
    store = InMemoryStore()
    record = MemoryRecord(content="test fact", type=MemoryType.FACT)

    written = store.write(record)
    loaded = store.get(record.id)

    assert written is record
    assert loaded is record


def test_in_memory_store_write_read_note():
    store = InMemoryStore()

    record = store.write_note("project", "TOMTIT Agent")

    assert record.type == MemoryType.NOTE
    assert store.read_note("project") == "TOMTIT Agent"
    assert store.list_notes() == ["project"]


def test_in_memory_store_update():
    store = InMemoryStore()
    record = store.write(MemoryRecord(content="old", type=MemoryType.FACT))

    updated = store.update(record.id, {"content": "new", "tags": ["agent"]})

    assert updated is not None
    assert updated.content == "new"
    assert updated.tags == ["agent"]


def test_in_memory_store_delete_soft_deletes_record():
    store = InMemoryStore()
    record = store.write(MemoryRecord(content="delete me"))

    deleted = store.delete(record.id, reason="test")

    assert deleted
    assert store.get(record.id) is None
    assert store.list_all() == []
    assert store.list_all(include_deleted=True)[0].metadata["delete_reason"] == "test"


def test_in_memory_store_search_filters_deleted_by_default():
    store = InMemoryStore()
    keep = store.write(MemoryRecord(content="agent memory", type=MemoryType.FACT))
    remove = store.write(MemoryRecord(content="agent memory old", type=MemoryType.FACT))
    store.delete(remove.id)

    results = store.search(MemoryQuery(text="agent"))

    assert [record.id for record in results] == [keep.id]


def test_in_memory_store_search_by_type_and_tags():
    store = InMemoryStore()
    store.write(
        MemoryRecord(
            content="User prefers direct answers",
            type=MemoryType.PREFERENCE,
            tags=["style"],
        )
    )
    store.write(
        MemoryRecord(
            content="TOMTIT uses state-first architecture",
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
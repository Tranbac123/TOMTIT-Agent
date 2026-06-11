from agent_core.memory.memory_records import EpisodeRecord, MemoryRecord
from agent_core.state.enums import MemoryType


def test_memory_record_to_dict_and_from_dict():
    record = MemoryRecord(
        content="User prefers concise answers.",
        type=MemoryType.PREFERENCE,
        tags=["style"],
        metadata={"source": "test"},
    )

    restored = MemoryRecord.from_dict(record.to_dict())

    assert restored.id == record.id
    assert restored.content == record.content
    assert restored.type == MemoryType.PREFERENCE
    assert restored.tags == ["style"]
    assert restored.metadata["source"] == "test"


def test_memory_record_soft_delete():
    record = MemoryRecord(content="Old fact")

    record.mark_deleted()

    assert record.is_deleted()
    assert record.deleted_at is not None


def test_episode_record_to_dict_and_from_dict():
    episode = EpisodeRecord(
        goal="Tính 1 + 1",
        task_id="task-1",
        status="completed",
        final_answer="2",
    )

    restored = EpisodeRecord.from_dict(episode.to_dict())

    assert restored.id == episode.id
    assert restored.goal == "Tính 1 + 1"
    assert restored.final_answer == "2"
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.memory.memory_agent import MemoryAgent
from agent_core.state.enums import MemoryType


def test_memory_agent_write_and_read_note():
    agent = MemoryAgent(InMemoryStore(), user_id="u1", session_id="s1")

    record = agent.write_note("project", "TOMTIT Agent")

    assert record.type == MemoryType.NOTE
    assert record.user_id == "u1"
    assert record.session_id == "s1"
    assert record.metadata["name"] == "project"
    assert agent.read_note("project") == "TOMTIT Agent"


def test_memory_agent_save_fact():
    agent = MemoryAgent(InMemoryStore(), user_id="u1")

    record = agent.save_fact(
        "TOMTIT uses state-first architecture.",
        tags=["architecture"],
        task_id="task-1",
        run_id="run-1",
    )

    assert record.type == MemoryType.FACT
    assert record.task_id == "task-1"
    assert record.run_id == "run-1"
    assert record.tags == ["architecture"]


def test_memory_agent_search_memory():
    agent = MemoryAgent(InMemoryStore(), user_id="u1")

    agent.save_decision(
        "Keep ToolExecutor as the single gate.",
        tags=["tools"],
    )

    results = agent.search_memory("ToolExecutor")

    assert len(results) == 1
    assert results[0].type == MemoryType.DECISION


def test_memory_agent_delete_memory():
    agent = MemoryAgent(InMemoryStore())

    record = agent.save_fact("Temporary fact")

    deleted = agent.delete_memory(record.id, reason="cleanup")

    assert deleted
    assert agent.get_memory(record.id) is None


def test_memory_agent_summarize_memory():
    agent = MemoryAgent(InMemoryStore())

    agent.save_preference("User prefers direct technical reviews.", tags=["style"])

    summary = agent.summarize_memory("direct")

    assert "[preference]" in summary
    assert "direct technical reviews" in summary
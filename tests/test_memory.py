from agent_core import InMemoryMemoryStore, MemoryAgent


def test_memory_agent_mvp_records_and_notes():
    store = InMemoryMemoryStore()
    agent = MemoryAgent(store, user_id="u1", session_id="s1")

    agent.write_note("project", "state-first runtime")
    fact = agent.save_fact("User prefers concise answers", tags=["preference"])

    assert agent.read_note("project") == "state-first runtime"
    assert "project" in agent.list_notes()
    assert store.get(fact.id) is not None
    assert agent.search_memory("concise")[0].content == "User prefers concise answers"
    assert "User prefers concise answers" in agent.summarize_memory("concise")

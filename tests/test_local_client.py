from __future__ import annotations

from agent_core.memory.client import MemoryClientProtocol
from agent_core.memory.contracts import MemoryCandidate
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.memory.local_client import LocalMemoryClient
from agent_core.memory.memory_records import MemoryQuery, MemoryRecord
from agent_core.state.enums import MemoryType


def test_protocol_conformance():
    client = LocalMemoryClient(InMemoryStore())
    assert isinstance(client, MemoryClientProtocol)


def test_retrieve_always_degraded():
    store = InMemoryStore()
    store.write(MemoryRecord(content="hello world", type=MemoryType.FACT))
    client = LocalMemoryClient(store)
    # goal="" — test degraded flag/source, not relevance
    pack = client.retrieve_context_pack("")
    assert pack.degraded is True
    assert pack.memory_source == "local"


def test_retrieve_maps_record_fields():
    # Tests field mapping (importance→score, type, provenance, source, metadata).
    # goal="" — isolates mapping from relevance filtering.
    store = InMemoryStore()
    rec = MemoryRecord(content="some fact", type=MemoryType.FACT, importance=0.8)
    store.write(rec)
    client = LocalMemoryClient(store)
    pack = client.retrieve_context_pack("")
    assert len(pack.items) == 1
    item = pack.items[0]
    assert item.score == 0.8
    assert item.type is MemoryType.FACT
    assert item.provenance == "fallback"
    assert item.source == "local_memory"
    assert item.metadata["memory_id"] == rec.id


def test_retrieve_empty_store():
    client = LocalMemoryClient(InMemoryStore())
    # goal="" — tests empty-store behavior, not relevance
    pack = client.retrieve_context_pack("")
    assert pack.items == []
    assert pack.total_items == 0
    assert pack.truncated is False
    assert pack.degraded is True


def test_token_budget_truncates():
    # Tests token-budget truncation. goal="" — isolates budget logic from relevance.
    store = InMemoryStore()
    # 3 records, content "a" = 1 token each; budget=2 fits 2, third triggers break
    for i in range(3):
        store.write(MemoryRecord(content="a", importance=0.9 - i * 0.1, type=MemoryType.FACT))
    client = LocalMemoryClient(store)
    pack = client.retrieve_context_pack("", token_budget=2)
    assert pack.truncated is True
    assert pack.tokens_used <= 2
    assert len(pack.items) == 2


def test_preserves_store_order():
    # Tests that client preserves store's importance-DESC order without re-ranking.
    # goal="" — isolates order behavior from relevance filtering.
    store = InMemoryStore()
    for importance in [0.3, 0.9, 0.6]:
        store.write(MemoryRecord(content=f"record {importance}", importance=importance, type=MemoryType.FACT))

    store_order = store.search(MemoryQuery(text="", limit=20))

    client = LocalMemoryClient(store)
    pack = client.retrieve_context_pack("", token_budget=9999)

    assert [item.metadata["memory_id"] for item in pack.items] == [r.id for r in store_order]


def test_retrieve_ignores_goal_in_local():
    # LOCAL CLIENT KHÔNG lọc theo goal — thiết kế có chủ đích cho MVP-local.
    # InMemoryStore chỉ có substring match; goal nguyên câu gần như không bao giờ match.
    # LocalMemoryClient trả top-k theo importance bất kể goal là gì.
    # Relevance-matching theo goal là việc của RemoteMemoryClient/Memory service (P6).
    store = InMemoryStore()
    rec = MemoryRecord(content="Dự án dùng FTS5 thay vector", type=MemoryType.DECISION)
    store.write(rec)
    client = LocalMemoryClient(store)
    # Goal hoàn toàn không liên quan đến content record — vẫn phải trả về record đó
    pack = client.retrieve_context_pack("Tính (15+5)*3 rồi lưu vào ghi chú budget")
    assert len(pack.items) == 1
    assert pack.items[0].metadata["memory_id"] == rec.id


def test_write_candidates_returns_ids():
    store = InMemoryStore()
    client = LocalMemoryClient(store)
    candidates = [
        MemoryCandidate(type=MemoryType.FACT, content="fact one"),
        MemoryCandidate(type=MemoryType.NOTE, content="note one"),
    ]
    resp = client.write_memory_candidates(candidates)
    assert len(resp.written_ids) == 2
    assert all(resp.written_ids)
    for memory_id in resp.written_ids:
        assert store.get(memory_id) is not None


def test_write_note_type_goes_through_write():
    store = InMemoryStore()
    client = LocalMemoryClient(store)
    candidates = [MemoryCandidate(type=MemoryType.NOTE, content="my note content")]
    resp = client.write_memory_candidates(candidates)
    assert len(resp.written_ids) == 1
    rec = store.get(resp.written_ids[0])
    assert rec is not None
    assert rec.type == MemoryType.NOTE
    # write() without metadata["name"] → note_index NOT populated (proves path via write, not write_note)
    assert len(store.note_index) == 0

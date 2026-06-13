from __future__ import annotations

from agent_core.memory.base import MemoryStoreProtocol
from agent_core.memory.contracts import (
    ContextItem,
    ContextPack,
    MemoryCandidate,
    WriteResponse,
)
from agent_core.memory.memory_records import MemoryQuery, MemoryRecord
from agent_core.memory.token_counter import ApproxTokenCounter, TokenCounter


class LocalMemoryClient:
    """MemoryClientProtocol backend bọc MemoryStoreProtocol sẵn có.

    LUÔN trả degraded=True / memory_source="local": đây là backend fallback/demo cho
    MVP-local, KHÔNG phản ánh durable remote state (SPEC_memory_client §4.1). Backend
    local durable trong tương lai có thể non-degraded — ngoài scope.

    KHÔNG sửa store. Map MemoryRecord → ContextItem. Store đã rank + limit; client chỉ
    cắt thêm theo token_budget.
    """

    def __init__(
        self,
        store: MemoryStoreProtocol,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self._store = store
        self._tokens = token_counter or ApproxTokenCounter()

    def retrieve_context_pack(
        self,
        goal: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        token_budget: int = 1500,
        max_items: int = 20,
    ) -> ContextPack:
        # Tầng cắt 1 — store: số lượng (limit) + đã sort sẵn.
        query = MemoryQuery(
            text=goal,
            user_id=user_id,
            session_id=session_id,
            limit=max_items,
        )
        records = self._store.search(query)

        # Map record → item, rồi tầng cắt 2 — client: token_budget.
        items: list[ContextItem] = []
        tokens_used = 0
        truncated = False
        for rec in records:  # giữ NGUYÊN thứ tự store (đã rank)
            item_tokens = self._tokens.count(rec.content)
            if tokens_used + item_tokens > token_budget:
                truncated = True
                break  # dừng tại item đầu tiên vượt budget
            items.append(self._to_item(rec, item_tokens))
            tokens_used += item_tokens

        return ContextPack(
            items=items,
            total_items=len(items),
            tokens_used=tokens_used,
            token_budget=token_budget,
            truncated=truncated,
            degraded=True,  # LUÔN — local fallback
            memory_source="local",
        )

    def write_memory_candidates(
        self,
        candidates: list[MemoryCandidate],
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> WriteResponse:
        written: list[str] = []
        for cand in candidates:
            rec = MemoryRecord(
                content=cand.content,
                type=cand.type,
                tags=list(cand.tags),
                confidence=cand.confidence,
                user_id=user_id,
                session_id=session_id,
                task_id=task_id,
            )
            saved = self._store.write(rec)
            written.append(saved.id)
        return WriteResponse(written_ids=written, skipped=[])

    def _to_item(self, rec: MemoryRecord, tokens: int) -> ContextItem:
        # provenance/source/confidence cố định cho local fallback (SPEC §4c).
        return ContextItem(
            content=rec.content,
            type=rec.type,
            score=rec.importance,  # store KHÔNG có score field → map từ importance
            tokens=tokens,
            source="local_memory",
            provenance="fallback",
            confidence="limited",
            freshness="unknown",
            metadata={"memory_id": rec.id},
        )

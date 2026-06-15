# SPEC P2-local-client — `LocalMemoryClient`

> **Phase:** P2-local-client (sau P1-contract đã đóng). **Executor:** Claude Code. **Gate:** TranBac.
> **Nguồn:** file này + `SPEC_memory_client.md §3, §4c, §5, §6` + `SPEC_P1_contract.md` (contracts).
>
> **Mục tiêu P2:** một `LocalMemoryClient` implement `MemoryClientProtocol`, bọc
> `MemoryStoreProtocol` **sẵn có** (KHÔNG sửa store), map `MemoryRecord → ContextItem`,
> cắt theo `token_budget`, luôn trả `degraded=True`. KHÔNG HTTP, KHÔNG factory, KHÔNG remote.

---

## 0. SCOPE FENCE

**Vào P2 (build):**

- `agent_core/memory/local_client.py`: `class LocalMemoryClient`
- `tests/test_local_client.py`

**[deferred] — KHÔNG làm:**

- ❌ `RemoteMemoryClient`, HTTP, `/handshake`, factory chọn backend (P6)
- ❌ runtime wiring (P3)
- ❌ sửa `MemoryStoreProtocol` / `MemoryRecord` / `InMemoryStore` — **bọc, không sửa**
- ❌ ranking lại (store đã sort `importance DESC, updated_at DESC` — dùng nguyên thứ tự đó)
- ❌ confidence-based filtering, episodic, summarize (deferred)

---

## 1. Dữ kiện store API (đã inspect — viết spec trên dữ kiện thật)

| Điểm                                 | Giá trị thật                                                                          | Hệ quả cho P2                                                   |
| ------------------------------------ | ------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `store.search(MemoryQuery)`          | trả `list[MemoryRecord]`, đã sort `(importance DESC, updated_at DESC)`, đã `[:limit]` | **KHÔNG rank lại.** Dùng nguyên thứ tự store trả.               |
| `MemoryRecord.score`                 | **không có.** Chỉ `importance: float`, `confidence: float`                            | `ContextItem.score ← record.importance`                         |
| `MemoryRecord.type`                  | là `MemoryType`                                                                       | map thẳng `ContextItem.type ← record.type`                      |
| `MemoryRecord.created_at/updated_at` | có (datetime)                                                                         | đưa vào `ContextItem.metadata` nếu cần debug; KHÔNG bắt buộc    |
| `store.write(MemoryRecord)`          | trả `MemoryRecord` (có `.id`)                                                         | `write_memory_candidates` dùng cái này, KHÔNG dùng `write_note` |
| note storage                         | `MemoryRecord(type=NOTE, metadata={"name": ...})` + `note_index`                      | candidate type=NOTE vẫn ghi qua `write()` chung, không đặc cách |

---

## 2. `LocalMemoryClient` — implementation

```python
from __future__ import annotations

from agent_core.memory.client import MemoryClientProtocol  # để type-check ý định
from agent_core.memory.contracts import (
    ContextItem,
    ContextPack,
    MemoryCandidate,
    WriteResponse,
)
from agent_core.memory.base import MemoryStoreProtocol
from agent_core.memory.memory_records import MemoryRecord, MemoryQuery
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
        # Tầng cắt 1 — store: số lượng (limit) + đã sort sẵn theo importance.
        # MVP-local: text="" — KHÔNG lọc theo goal. InMemoryStore chỉ substring match,
        # match nguyên câu goal gần như luôn rỗng. LocalMemoryClient là fallback/demo
        # (luôn degraded): trả top-k theo importance, KHÔNG relevance-matching. Match
        # khớp goal là việc của RemoteMemoryClient/Memory service (P6), không phải local.
        # `goal` vẫn ở signature (contract MemoryClientProtocol — remote dùng nó).
        query = MemoryQuery(
            text="",
            user_id=user_id,
            session_id=session_id,
            limit=max_items,
        )
        records = self._store.search(query)

        # Map record → item, rồi tầng cắt 2 — client: token_budget.
        items: list[ContextItem] = []
        tokens_used = 0
        truncated = False
        for rec in records:                       # giữ NGUYÊN thứ tự store (đã rank)
            item_tokens = self._tokens.count(rec.content)
            if tokens_used + item_tokens > token_budget:
                truncated = True
                break                             # dừng tại item đầu tiên vượt budget
            items.append(self._to_item(rec, item_tokens))
            tokens_used += item_tokens

        return ContextPack(
            items=items,
            total_items=len(items),
            tokens_used=tokens_used,
            token_budget=token_budget,
            truncated=truncated,
            degraded=True,                        # LUÔN — local fallback
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
            score=rec.importance,                 # store KHÔNG có score → dùng importance
            tokens=tokens,
            source="local_memory",
            provenance="fallback",
            confidence="limited",
            freshness="unknown",
            metadata={"memory_id": rec.id},
        )
```

---

## 3. Quyết định thiết kế (đọc kỹ — đây là chỗ dễ làm sai)

1. **KHÔNG rank lại.** `store.search` đã sort `importance DESC, updated_at DESC`. Client
   giữ nguyên thứ tự. Thêm ranking riêng = trùng việc + lệch hành vi với store.

2. **Hai tầng cắt, đúng thứ tự:** (a) `limit=max_items` ở store — cắt số lượng; (b)
   `token_budget` ở client — cắt token. Item đầu tiên vượt budget → `truncated=True`,
   **break** (không skip rồi thử item sau — giữ prefix liền mạch theo thứ tự rank).

3. **`score ← importance`.** `MemoryRecord` không có `score`. Map từ `importance`. Ghi
   comment rõ để người sau không tưởng store có score.

4. **write qua `store.write(MemoryRecord)` chung**, KỂ CẢ candidate type=NOTE. Không
   dùng `store.write_note` — note chỉ là một `MemoryType`, không đặc cách. (Phân biệt với
   `write_note` _tool_ user-visible ở runtime — cái đó là chuyện khác, P3.)

5. **LUÔN `degraded=True`.** Không điều kiện. Local = fallback/demo (SPEC §4.1).

6. **KHÔNG đụng store.** Nếu thấy cần method store chưa có → **dừng, báo out-of-scope**,
   không tự thêm vào `MemoryStoreProtocol`.

7. **Local KHÔNG lọc theo goal — `text=""`.** `InMemoryStore` chỉ substring match; truyền
   goal nguyên câu → retrieval luôn rỗng. Local là fallback/demo (luôn degraded): trả top-k
   theo importance, KHÔNG relevance-matching. Đây là **ranh giới kiến trúc cố ý**: relevance
   khớp goal thuộc về Memory service remote (P6, `CLAUDE.md §7` cấm RAG/retrieval engine
   trong Agent). `goal` vẫn ở signature vì là contract chung — remote client sẽ dùng nó.

---

## 4. Test P2 — `tests/test_local_client.py`

Dùng `InMemoryStore` thật (không mock store — test adapter thật trên store thật).

| Test                                      | Assert                                                                                                                                                                                               |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_protocol_conformance`               | `isinstance(LocalMemoryClient(InMemoryStore()), MemoryClientProtocol)`                                                                                                                               |
| `test_retrieve_always_degraded`           | seed 1 record → pack `degraded is True`, `memory_source == "local"`                                                                                                                                  |
| `test_retrieve_maps_record_fields`        | seed record(importance=0.8, type=FACT) → item `score == 0.8`, `type is MemoryType.FACT`, `provenance == "fallback"`, `source == "local_memory"`, `metadata["memory_id"]` đúng                        |
| `test_retrieve_empty_store`               | store rỗng → `items == []`, `total_items == 0`, `truncated is False`, vẫn `degraded is True`                                                                                                         |
| `test_token_budget_truncates`             | seed nhiều record, `token_budget` nhỏ (vd 3) → `truncated is True`, `tokens_used <= token_budget`, items là prefix theo thứ tự store                                                                 |
| `test_preserves_store_order`              | seed records importance khác nhau → thứ tự items khớp thứ tự store.search trả (KHÔNG rank lại)                                                                                                       |
| `test_write_candidates_returns_ids`       | write 2 candidate → `written_ids` có 2 id thật, đọc lại store thấy 2 record                                                                                                                          |
| `test_write_note_type_goes_through_write` | candidate type=NOTE → ghi qua store.write (record.type == NOTE), KHÔNG qua write_note path                                                                                                           |
| `test_retrieve_ignores_goal_in_local`     | seed record content KHÔNG chứa goal string → `retrieve_context_pack("goal bất kỳ không liên quan")` vẫn trả record đó. Chứng minh local **cố ý** không lọc theo goal (hợp đồng, không phải tai nạn). |

> **Lưu ý test:** các test dùng `goal=""` test mapping/budget/order — **không** test relevance.
> `test_retrieve_ignores_goal_in_local` mới là cái khẳng định hành vi "bỏ qua goal" là **có
> chủ đích**. Nếu ai sau này thêm relevance-matching vào local (tưởng sửa bug), test này đỏ.

Chạy `pytest -q` full → phải 69 passed (60 + 9). Dán raw.

---

## 5. Acceptance P2

- `from agent_core.memory.local_client import LocalMemoryClient` OK
- `LocalMemoryClient(InMemoryStore())` là `MemoryClientProtocol` (isinstance True)
- retrieve trả `ContextPack(degraded=True, memory_source="local")`
- write trả `WriteResponse` với id thật, store có record sau write
- `pytest -q` → 69 passed; `import agent_core` vẫn OK
- KHÔNG có thay đổi nào ngoài `local_client.py` + `test_local_client.py`

---

## 6. Report mẫu

```
## P2-local-client report
- Branch: p2-local-client
- Files: agent_core/memory/local_client.py (new), tests/test_local_client.py (new)
- What/Why: <2-4 câu>
- pytest: <raw, 69 passed — acceptance: 0 failed, 0 errors (số test chỉ tham khảo)>
- Store API: dùng search/write nguyên trạng, KHÔNG sửa store? <xác nhận>
- Out-of-scope findings: <none | nếu thấy store thiếu gì>
- Spec deviations: <none | ...>
<<< git diff >>>
<<< pytest raw >>>
```

Dừng sau P2. Chờ gate. KHÔNG tự sang P3 (runtime wiring).

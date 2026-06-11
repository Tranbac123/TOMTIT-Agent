# TOMTIT MVP — Master Plan (Agent ↔ Memory integration)

> **Mục tiêu MVP (Definition of Done):** TOMTIT-Agent gọi TOMTIT-Memory lấy
> `ContextPack` **trước khi plan**, ghi memory candidates **sau khi finish** — một
> luồng end-to-end chạy thật qua HTTP, chứng minh được bằng một script demo.
>
> **Trạng thái xuất phát (đã xác nhận):**
>
> - TOMTIT-Agent: **chưa import được** (4 lỗi P0).
> - TOMTIT-Memory: **có code, chưa có HTTP server chạy được**.
>
> **Nguyên tắc tốc độ:** nhanh = làm đúng thứ tự, KHÔNG bỏ bước. Không thể test
> integration khi nền hai đầu còn gãy. Lỗi import sẽ che lỗi HTTP nếu làm ngược.

---

## 1. Critical path (6 phase, một-phase-một-gate)

| PHASE    | Tên                                                                                                | Repo   | Trạng thái  | Spec                              |
| -------- | -------------------------------------------------------------------------------------------------- | ------ | ----------- | --------------------------------- |
| **0**    | Sửa P0 → Agent import được, pytest xanh                                                            | Agent  | ⏳ làm ngay | ✅ `BUILD_SPEC.md` STEP 1–5       |
| 2        | **Chốt contract `ContextPack` + request/response** (dùng chung 2 bên)                              | cả 2   | chờ         | §3 dưới + `SPEC_memory_client.md` |
| 3a       | `contracts.py` + `MemoryClientProtocol`                                                            | Agent  | chờ         | `SPEC_memory_client.md`           |
| 3b       | **`LocalMemoryClient`** bọc `InMemoryStore` + test                                                 | Agent  | chờ         | `SPEC_memory_client.md §3,9`      |
| 4        | Wiring runtime: retrieve trước plan → inject `AgentState` → write sau finish + degraded disclosure | Agent  | chờ         | `SPEC_memory_client.md §5`        |
| 5-local  | **E2E local:** agent chạy 1 luồng với `LocalMemoryClient`, demo được                               | Agent  | chờ         | cần viết                          |
| 1        | Memory HTTP server tối thiểu (`/retrieve`, `/write`, `/handshake`)                                 | Memory | chờ         | cần viết                          |
| 3c       | `RemoteMemoryClient` + factory chọn backend (binding-at-task-start)                                | Agent  | chờ         | `SPEC_memory_client.md §3,4`      |
| 5-remote | **E2E remote:** agent ↔ TOMTIT-Memory thật qua HTTP, `degraded=False`                              | cả 2   | chờ         | cần viết                          |

**Đường găng đã đổi (local-first):**

```
PHASE 0 → 2 → 3a → 3b → 4 → 5-local      ← MVP "chạy được" đạt ở đây, KHÔNG cần Memory service
                                  └→ (1 ∥ 3c) → 5-remote   ← ghép remote sau, runtime không đổi
```

**Vì sao đảo thứ tự:** `LocalMemoryClient` (3b) cho một `MemoryClient` chạy được
**trước khi** TOMTIT-Memory có HTTP server. Demo E2E local (5-local) không bị PHASE 1
chặn. Remote (3c) ghép vào sau qua cùng `MemoryClientProtocol` — runtime không sửa một
dòng. Đây là đường nhanh nhất tới "MVP chạy được" theo DoD của bạn.

> **Memory abstraction (quan trọng):** Agent KHÔNG có hai store. Agent có **một
> `MemoryClientProtocol`**, hai backend (remote/local) hoán đổi qua factory. Chi tiết
>
> - luật binding-at-task-start + degraded mode: **`SPEC_memory_client.md`**.

---

## 2. PHASE 0 — dùng nguyên `BUILD_SPEC.md` STEP 1–5

**Không viết lại.** `BUILD_SPEC.md` (lượt trước) STEP 1–5 chính là PHASE 0:

- STEP 1: khôi phục `RuleBasedIntentParser`
- STEP 2: sửa `base.py` self-import + tách `__init__.py`
- STEP 3: khử trùng class `IntentPlanner`
- STEP 4: hợp nhất `SourceType` enum
- STEP 5: import-sanity gate + chạy lại P0 suite

→ Hết STEP 5: `python main.py` chạy, `pytest` xanh. **Đó là cổng vào PHASE 1+.**

### ⛔ ĐÓNG BĂNG STEP 6–9 của BUILD_SPEC cũ

Mục tiêu đổi từ "hardening Agent" sang "MVP integration", nên các step sau **không
còn nằm trên đường găng**, và một số **sai hướng**:

| STEP cũ                                     | Quyết định mới                                  | Lý do                                                                                                                                                                                                                                                                                          |
| ------------------------------------------- | ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 6 — persist memory nội bộ (`InMemoryStore`) | **THAY bằng `SPEC_memory_client.md`**           | Không persist `InMemoryStore` như mục tiêu cuối. Thay vào đó: `InMemoryStore` trở thành **backing store của `LocalMemoryClient`**. Vẫn bỏ `default_factory=InMemoryStore` (lỗi mỗi-state-một-store), nhưng memory giờ truy cập qua `MemoryClientProtocol`, không qua `state.memory` trực tiếp. |
| 7 — structured event log                    | **HOÃN (post-MVP)**                             | Hardening, không phải đường tới MVP. Làm sau khi luồng E2E chạy.                                                                                                                                                                                                                               |
| 8 — retry/timeout                           | **HOÃN (post-MVP)**                             | `web_search` còn fake → chưa có I/O thật cần retry. Memory HTTP call sẽ cần, nhưng xử lý tối thiểu trong PHASE 3.                                                                                                                                                                              |
| 9 — dọn file rỗng                           | **GỘP vào PHASE 0 STEP 5** nếu nhanh, hoặc hoãn | Hygiene, không chặn gì.                                                                                                                                                                                                                                                                        |

**Claude Code KHÔNG được tự làm STEP 6–9 cũ.** Sau PHASE 0, chờ spec PHASE 1.

---

## 3. DRAFT contract `ContextPack` (PHASE 2 — chốt trước khi code client)

> Bạn nói chưa có `ContextPack` rõ. Đây là **đề xuất tối thiểu** cho MVP. Đây là
> phần chết người: nếu hai service không đồng ý schema này TRƯỚC khi viết client,
> bạn sẽ phải viết lại cả hai đầu. **Chốt cái này ở gate PHASE 1.**

### Nguyên tắc thiết kế contract

- **Token-budgeted:** Agent gửi `token_budget`, Memory trả về vừa đủ, kèm số token thực dùng. Đây là khác biệt kỹ thuật cốt lõi của TOMTIT — đừng bỏ.
- **Service không đoán intent của Agent.** Agent gửi `goal` + `budget`, Memory chỉ retrieve + rank + cắt theo budget. Không suy luận thêm.
- **Structured, không phải blob text.** `ContextPack` là object có field rõ, để Agent inject vào `AgentState` mà không phải parse string.
- **Versioned từ ngày đầu.** `schema_version` để đổi contract sau không vỡ câm.

### Request — Agent → Memory `POST /retrieve`

```json
{
  "schema_version": "1",
  "goal": "tìm thông tin Ducati Monster 795 rồi ghi vào note bikes",
  "user_id": "u_123",
  "session_id": "s_456",
  "token_budget": 1500,
  "max_items": 20
}
```

### Response — Memory → Agent (`ContextPack`)

```json
{
  "schema_version": "1",
  "items": [
    {
      "id": "mem_001",
      "type": "decision",
      "content": "Dùng FTS5 thay vì vector cho scale hiện tại",
      "score": 0.82,
      "tokens": 14,
      "metadata": { "created_at": "2026-01-10T..." }
    }
  ],
  "total_items": 1,
  "tokens_used": 14,
  "token_budget": 1500,
  "truncated": false
}
```

### Request — Agent → Memory `POST /write`

```json
{
  "schema_version": "1",
  "user_id": "u_123",
  "session_id": "s_456",
  "task_id": "t_789",
  "candidates": [
    {
      "type": "fact",
      "content": "Ducati Monster 795 ra mắt 2012",
      "tags": ["bikes"],
      "confidence": 0.9
    }
  ]
}
```

### Response — `POST /write`

```json
{ "schema_version": "1", "written_ids": ["mem_010"], "skipped": [] }
```

### `GET /handshake`

> `/health` đơn thuần KHÔNG đủ để bind backend (xem `SPEC_memory_client.md §4a`).
> Dùng `/handshake` trả đủ field lõi để Agent quyết bind/fail an toàn:

```json
{
  "health_status": "ok",
  "ready": true,
  "backend_version": "0.3.1",
  "schema_version": "1",
  "capabilities": ["memory", "audit"],
  "latency_ms": 42
}
```

### Pydantic model dùng CHUNG (đề xuất đặt ở Agent side cho client; Memory side định nghĩa server-side khớp byte-by-byte)

```python
# Đặt ví dụ: agent_core/memory/contracts.py (client side)
from __future__ import annotations
from pydantic import BaseModel, Field

SCHEMA_VERSION = "1"

class ContextItem(BaseModel):
    id: str
    type: str                      # note | fact | preference | decision | ...
    content: str
    score: float = 0.0
    tokens: int = 0
    metadata: dict = Field(default_factory=dict)

class ContextPack(BaseModel):
    schema_version: str = SCHEMA_VERSION
    items: list[ContextItem] = Field(default_factory=list)
    total_items: int = 0
    tokens_used: int = 0
    token_budget: int = 0
    truncated: bool = False

class RetrieveRequest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    goal: str
    user_id: str | None = None
    session_id: str | None = None
    token_budget: int = 1500
    max_items: int = 20

class MemoryCandidate(BaseModel):
    type: str
    content: str
    tags: list[str] = Field(default_factory=list)
    confidence: float = 1.0

class WriteRequest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    user_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    candidates: list[MemoryCandidate] = Field(default_factory=list)

class WriteResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    written_ids: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
```

### Câu hỏi cần bạn chốt ở gate PHASE 1 (trước khi code PHASE 3)

1. `ContextItem.type` — dùng đúng `MemoryType` enum đã có ở Agent (`note/fact/preference/decision/...`) hay để string tự do? **Đề xuất: enum, để hai bên không lệch.**
2. Token counting — Agent và Memory phải dùng **cùng** một `TokenCounter`, nếu không `tokens_used` vô nghĩa. Memory của bạn đã có `TokenCounter` protocol; Agent phải dùng chung cách đếm. **Đây là điểm dễ lệch nhất.**
3. `MemoryClientProtocol` — bạn đã nhắc protocol này trong định hướng. PHASE 3 sẽ hiện thực nó. Cần chốt method signature: `retrieve_context_pack(goal, state) -> ContextPack` và `write_memory_candidates(...) -> WriteResponse`.

---

## 4. Map vào runtime flow mục tiêu của bạn

Flow bạn đã định nghĩa, đánh dấu phần MVP này chạm tới:

```
UserMessage
  → TurnClassifier              [post-MVP, chưa làm]
  → MemoryClient.retrieve_context_pack(goal, state)   ★ PHASE 3+4
  → IntentParser                [PHASE 0 — RuleBasedIntentParser]
  → SlotValidator               [đã có]
  → IntentPlanner               [đã có]
  → PlanValidator               [đã có]
  → ToolExecutor                [đã có — single gate]
  → Observation/EventLog        [event log: post-MVP STEP 7]
  → FinalComposer               [đã có]
  → MemoryClient.write_memory_candidates(...)         ★ PHASE 3+4
  → AgentState.complete()       [đã có]
```

★ = phần PHASE 3/4 thêm vào. Mọi thứ giữa parser và composer **đã tồn tại** (sau khi
PHASE 0 sửa import). MVP integration thực chất chỉ là **bọc hai đầu memory** quanh
runtime sẵn có — KHÔNG viết lại runtime.

---

## 5. Cảnh báo founder-mindset (đọc một lần)

- **Đừng để MVP phình.** DoD của bạn là _một luồng end-to-end chạy_. Không phải nhiều turn, không phải `TurnClassifier`, không phải event log, không phải retry hoàn chỉnh. Một luồng. Chạy. Demo được. Dừng.
- **Contract trước code.** PHASE 2 chốt `ContextPack` trên giấy/Pydantic trước khi PHASE 3 viết client. Đảo thứ tự = viết lại hai lần.
- **Cùng TokenCounter hai bên** hoặc token budget vô nghĩa — đây là nơi tôi thấy bạn dễ mất nhất.
- Sau PHASE 5 chạy được: **dừng build, đi nói chuyện user**. Một luồng chạy thật + demo là đủ để phỏng vấn design partner. Đừng polish lõi trước khi có tín hiệu thị trường.

---

## 6. Next step (một việc)

Cho Claude Code chạy **PHASE 0 = `BUILD_SPEC.md` STEP 1**, đúng lệnh khởi động ở
`BUILD_SPEC.md §5`. Song song, bạn review `§3` (draft `ContextPack`) và trả lời 3
câu hỏi chốt contract ở cuối `§3`. Khi PHASE 0 qua gate STEP 5, tôi viết spec PHASE 1
(Memory HTTP server) — và lúc đó cần bạn upload code TOMTIT-Memory để spec khớp thực tế.

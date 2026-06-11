# SPEC — MemoryClient layer (P1-contract → P4-local-demo, then P6-remote-client)

> **Quyết định kiến trúc:** Memory **không** là một store cố định trong `AgentState`.
> Nó là một **`MemoryClientProtocol` duy nhất** với **hai backend hoán đổi được**:
> remote (TOMTIT-Memory HTTP) và local (bọc `InMemoryStore`/`FileStore` sẵn có).
> Runtime chỉ biết protocol, **không bao giờ** biết phía sau là HTTP hay local.
>
> Spec này **thay thế** định hướng cũ "thay `InMemoryStore` bằng HTTP" trong
> `MVP_MASTER_PLAN.md`. STEP 6 của `BUILD_SPEC.md` vẫn HỦY; lý do giữ nguyên
> (durable memory không sống trong `AgentState`), nhưng nay có thêm local fallback
> ở lớp **client**, không phải lớp store.

---

## SCOPE FENCE (Claude Code đọc trước — chống over-build)

> Ba tầng. Critical path local (P0→P4) **chỉ cần [MVP-local must]**. KHÔNG build
> [Remote integration must] trước khi P4-local-demo chạy — nó không block local E2E.

**[MVP-local must] — build cho P1→P4, đủ để demo local:**

- `contracts.py` (`ContextPack` + `ContextItem` + `MemoryCandidate` + `WriteResponse`)
- `MemoryClientProtocol` (KHÔNG nhận full `AgentState` — §2)
- `LocalMemoryClient` bọc `InMemoryStore`
- `ContextPack.degraded` + `AgentState.memory_degraded` (đơn điệu — §5)
- runtime: retrieve trước plan, write sau finish (write best-effort — §5b)
- `FinalComposer` disclosure **deterministic** (policy set cờ, model viết chữ — §7b)
- `ApproxTokenCounter` dùng chung (§6)
- PolicyEngine chặn side-effect khi `memory_degraded` (fail-closed — §4d)
- per-item `provenance` field: **set giá trị, CHƯA ranking**

**[Remote integration must] — build cho P6, SAU local demo:**

- `RemoteMemoryClient` (httpx sync)
- `/handshake` + schema-mismatch fail bind (§4a)
- factory binding-at-task-start: mode `local`/`remote`/`auto` (§4)
- remote fail fast (mode=remote); auto fallback local; **no mid-run switch**

**[deferred] — định nghĩa field default an toàn, KHÔNG wire logic:**

- `latency_ms` auto-degraded; `auth/permission`; `backend_health_snapshot`;
  `backend_bound_at`; `state_backend` remote; `MemoryPolicy` engine;
  bảng task-classification chi tiết; confidence-based ranking

**❌ KHÔNG bao giờ (trong MVP):** handshake nhiều endpoint; policy engine phức tạp;
nhiều state backend; tự đổi backend giữa run; để model tự quyết disclosure;
`degraded_allowed(task)` tại bind-time (§4b — task policy nằm ở ToolExecutor, KHÔNG ở BackendSelector).

---

## 1. Vì sao một protocol, không phải hai store

Cái bẫy của "giữ cả hai": nếu local trả `list[MemoryRecord]` còn remote trả
`ContextPack`, runtime phải biết đang nói với backend nào → hai code path → debug
gấp đôi → đúng bệnh "hành động sai không debug được" mà TOMTIT sinh ra để chữa.

**Ràng buộc bất biến:** cả hai backend trả **cùng một kiểu `ContextPack`**. Runtime
gọi `client.retrieve_context_pack(goal, *explicit params*)` và xử lý kết quả y hệt nhau
bất kể nguồn. Đó mới là "giữ cả hai" đúng cách.

Phân biệt ba lớp (đừng trộn):

| Lớp         | Protocol                         | Trả về            | Vai trò                                 |
| ----------- | -------------------------------- | ----------------- | --------------------------------------- |
| Persistence | `MemoryStoreProtocol` (đã có)    | `MemoryRecord`    | write/get/search thô                    |
| Domain      | `MemoryAgentProtocol` (đã có)    | `MemoryRecord`    | hiểu note/fact/preference               |
| **Client**  | **`MemoryClientProtocol` (mới)** | **`ContextPack`** | cái runtime gọi trước plan / sau finish |

Fallback local nằm ở **lớp client**, không phải lớp store.

---

## 2. `MemoryClientProtocol` — hợp đồng runtime gọi

> **LUẬT [chốt]:** `MemoryClientProtocol` **KHÔNG** nhận full `AgentState`. Chỉ explicit
> params. Runtime tự rút `user_id`/`session_id`/`task_id` từ state và truyền vào. Lý do:
> giảm coupling, dễ test, remote client không kéo theo cả runtime state. (Master plan
> từng gợi ý `retrieve_context_pack(goal, state)` — bản đó SAI, bỏ.)

```python
# agent_core/memory/client.py
from __future__ import annotations
from typing import Protocol, runtime_checkable

from agent_core.memory.contracts import ContextPack, WriteResponse, MemoryCandidate

@runtime_checkable
class MemoryClientProtocol(Protocol):
    def retrieve_context_pack(
        self,
        goal: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        token_budget: int = 1500,
        max_items: int = 20,
    ) -> ContextPack: ...

    def write_memory_candidates(
        self,
        candidates: list[MemoryCandidate],
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> WriteResponse: ...
```

`ContextPack` / `MemoryCandidate` / `WriteResponse`: schema ở `MVP_MASTER_PLAN.md §3`.
**Bổ sung field degraded** (xem §5).

---

## 3. Hai implementation

### `RemoteMemoryClient` — gọi TOMTIT-Memory HTTP

- `retrieve_context_pack` → `POST /retrieve` → parse JSON thành `ContextPack`.
- `write_memory_candidates` → `POST /write` → `WriteResponse`.
- `handshake()` → `GET /handshake` → `HandshakeResult` (xem §4a). Gọi **một lần** lúc bind.
- Dùng `httpx` (sync cho MVP — đừng kéo asyncio vào). Timeout ngắn, rõ.
- **Không tự fallback bên trong.** Lỗi HTTP → raise `MemoryRemoteError`. Việc fallback
  là của factory lúc start (§4), KHÔNG phải của client giữa run.
- Mọi `ContextItem` remote trả ra phải mang `provenance="remote"` (§4c).

### `LocalMemoryClient` — bọc store sẵn có

- Nhận một `MemoryStoreProtocol` (`InMemoryStore` hoặc `FileStore`).
- **TRƯỚC khi implement: inspect `MemoryStoreProtocol` hiện tại.** KHÔNG đổi
  `MemoryStoreProtocol` ở step này trừ khi bắt buộc. Map return shape hiện có vào
  `ContextPack` bằng adapter **nhỏ nhất có thể**. Nếu store thiếu `MemoryQuery`/`score`:
  default `score=0.0` và **giữ insertion order**. KHÔNG tự chế API mới cho store.
- `retrieve_context_pack`: gọi search của store hiện có, rồi **tự ráp `ContextPack`**:
  - rank theo score sẵn có (hoặc insertion order nếu chưa có score),
  - cắt theo `token_budget` dùng **cùng TokenCounter** (xem §6),
  - set `truncated` đúng,
  - mỗi item: `provenance="fallback"`, `source="local_memory"`, `confidence="limited"` (§4c).
- `write_memory_candidates`: map candidate → `MemoryRecord` → `store.write(...)`.
- **Luôn** set `degraded=True`, `memory_source="local"` trên `ContextPack` (§5).

> **Phạm vi của "luôn degraded":** đúng **chỉ cho MVP-local**, vì `LocalMemoryClient` ở
> đây là backend fallback/demo, có thể KHÔNG phản ánh state durable remote của TOMTIT-Memory.
> Backend local durable trong tương lai (vd `FileStore` làm backend chính) **có thể
> non-degraded** — nhưng đó là [out of scope] cho MVP này.

---

## 4. Chọn backend — binding-at-task-start (LUẬT)

> **Phân tầng để chống scope creep.** Thiết kế dưới đây đầy đủ, nhưng chia rõ:
> **[MVP-must]** = build ngay để local path chạy an toàn. **[deferred]** = định nghĩa
> field/contract giờ (để không phải đổi contract sau) nhưng **chưa wire logic** cho tới
> sau khi luồng E2E local chạy. Claude Code chỉ implement [MVP-must]; [deferred] để
> field default an toàn + TODO có ghi chú.

### 4a. Handshake — `/health` chưa đủ

`/health` chỉ nói service còn sống — chưa đủ để bind. Một service sống nhưng sai
schema version sẽ làm `AgentState` mismatch, hoặc thiếu capability cần thiết. Dùng
**một** endpoint gộp (không gọi 6 lần mạng):

```
GET /handshake →
{
  "health_status": "ok",          // [MVP-must]
  "ready": true,                  // [MVP-must] sẵn sàng nhận request, không chỉ "sống"
  "backend_version": "0.3.1",     // [MVP-must]
  "schema_version": "1",          // [MVP-must] PHẢI khớp Agent's SCHEMA_VERSION
  "capabilities": ["memory", "audit"],  // [MVP-must] backend hỗ trợ gì
  "latency_ms": 42                // [deferred] đo để quyết auto-degraded khi quá chậm
}
```

**Luật handshake [MVP] — CHỈ kiểm baseline memory-client, KHÔNG kiểm task:**

Tại bind-time chưa có plan → KHÔNG biết task cần capability gì. Handshake chỉ validate
baseline:

- `schema_version` ≠ Agent's `SCHEMA_VERSION` → **fail bind** (không chạy với contract lệch).
- `ready != true` hoặc `health_status != "ok"` → coi như unhealthy.
- `capabilities` **không** chứa `"memory"` → coi như unhealthy (backend không phục vụ memory được).

**KHÔNG kiểm task/tool-specific capability ở đây.** Audit / capability theo từng tool
là việc của ToolExecutor (khi đã có plan) hoặc của remote integration phase — KHÔNG
phải MVP-local bind.

**[deferred]:** `auth/permission` và `latency budget`. Định nghĩa field `latency_ms` +
chỗ cho `auth` trong `HandshakeResult` ngay bây giờ, nhưng **chưa** dùng để quyết định.

### 4b. Binding KHÔNG xét task — task policy nằm ở ToolExecutor

> Spec trước của tôi **sai hai lần**: (1) bản đầu cho `auto` fallback bất kể task;
> (2) bản sửa lại đặt `degraded_allowed(task)` ở **bind-time** — nhưng lúc bind **chưa
> có plan**, nên chưa biết task có side-effect. Giữ logic đó mời Claude Code viết một
> pre-planner/task-classifier = scope creep. **Sửa dứt: binding mù về task; an toàn
> enforce hoàn toàn tại ToolExecutor.**

**Binding rule [MVP] — chỉ nhìn backend health, KHÔNG nhìn task:**

```
mode == local   → bind LocalMemoryClient,  memory_degraded = True
mode == remote  → handshake lành → bind RemoteMemoryClient, degraded = False
                  handshake hỏng → FAIL FAST (raise). Không fallback.
mode == auto    → handshake lành → bind RemoteMemoryClient, degraded = False
                  handshake hỏng → bind LocalMemoryClient, memory_degraded = True,
                                    fallback_reason = "remote_unavailable", log WARNING
```

Không có `degraded_allowed(task)` ở đây. Binding luôn thành công (trừ mode=remote fail fast).

**An toàn task nằm ở ToolExecutor (§4d), KHÔNG ở BackendSelector:**

Khi `memory_degraded=True`, một step side-effect sắp chạy → PolicyEngine **chặn tại
cổng execute**. Đây là chỗ duy nhất gọi `tool.fn`, và là chỗ duy nhất _đã có plan +
biết tool cụ thể_. Read-only task chạy degraded bình thường; side-effect task degraded
bị chặn/approval — **không cần biết trước plan, không cần task classifier.**

Bốn luật bất biến (giữ nguyên):

1. Read-only / answer-only chạy degraded OK (hỏi context cũ → disclose).
2. Side-effect khi degraded → chặn/approval tại ToolExecutor.
3. mode=remote fail → fail fast.
4. Degraded chỉ leo lên trong một run.

> **[deferred]** Phân loại task tinh hơn ("sửa file dựa memory cũ → hỏi user") + `MemoryPolicy`
> engine: sau khi runtime chạy. MVP chỉ nhị phân read-only-vs-không, enforce tại executor.

### 4c. Provenance — `degraded` cấp pack chưa đủ

Một `ContextPack` có thể **trộn** nhiều nguồn: prompt hiện tại, local fallback memory,
remote memory, file context, user-provided. Một cờ `degraded` cấp pack che mất _item
nào_ đáng tin. Mỗi `ContextItem` mang provenance:

```python
from typing import Literal
from agent_core.state.enums import MemoryType   # enum ĐÃ CÓ ở enums.py

MemorySource = Literal["remote_memory", "local_memory", "file", "user", "prompt"]
Provenance   = Literal["remote", "fallback", "user", "file", "prompt"]
Confidence   = Literal["normal", "limited", "unknown"]
Freshness    = Literal["fresh", "stale", "unknown"]

class ContextItem(BaseModel):
    content: str
    type: MemoryType                       # enum, KHÔNG string tự do
    score: float = 0.0
    tokens: int = 0
    source: MemorySource = "remote_memory"
    provenance: Provenance = "remote"
    confidence: Confidence = "normal"
    freshness: Freshness = "unknown"
    metadata: dict = Field(default_factory=dict)
```

> **Lưu ý cho P1-contract:** `MemoryType` enum **đã tồn tại** ở `agent_core/state/enums.py`
> (`NOTE/FACT/PREFERENCE/DECISION/...`). Nếu khi implement thấy nó thiếu/khác → **normalize
> nó trong P1-contract TRƯỚC khi viết `LocalMemoryClient`**, không để `type: str` lọt vào.
> Dùng `Literal` (không Enum riêng) cho 4 field còn lại để khóa giá trị mà không phình.

**Invariant [MVP-must]:** trong **một run**, không trộn item `provenance="remote"` với
`provenance="fallback"`. Backend đã bind một lần (§4 luật cứng) nên pack đồng nhất
nguồn. `source="user"`/`"file"`/`"prompt"` thì được phép xuất hiện cùng (chúng không
phải memory backend). Provenance per-item phục vụ debug + cho FinalComposer/policy biết
item nào "limited".

### 4d. PolicyEngine chặn side-effect khi degraded [MVP-local must]

`agent_core/safety/policy.py` — rule deterministic, **fail-closed** (không chỉ một field):

```python
is_side_effect = (
    getattr(tool, "effect_type", None) != "read"   # effect_type khác "read"
    or tool.mutates_state
    or tool.requires_approval
    or tool.risk_level >= RiskLevel.MEDIUM
    or getattr(tool, "effect_type", None) is None   # thiếu/unknown → coi là side-effect
)

if state.memory_degraded and is_side_effect:
    DENY  reason="degraded memory mode: side-effect tool blocked (fail-closed)"
```

**Nguyên tắc fail-closed:** read-only chạy degraded OK; **mọi thứ không chắc read-only
→ coi là side-effect → chặn.** Nới lỏng thì dễ; gỡ một action đã lỡ chạy degraded thì
không. Đây là nơi luật an toàn được **thực thi**, tại cổng execute, deterministic, không
giao cho model. Khớp `CLAUDE.md §1`.

> Note: `effect_type` có thể chưa tồn tại trên `ToolSpec` hiện tại. Dùng `getattr(...,
None)` để fail-closed khi thiếu. Thêm field `effect_type` vào `ToolSpec` là [deferred] —
> MVP chỉ cần `mutates_state`/`requires_approval`/`risk_level` đã có là đủ chặn.

**Phân biệt side-effect TOOL vs memory-write (quan trọng — tránh hiểu nhầm):**

Side-effect policy ở trên áp dụng cho **tool user-visible / external** chạy qua
`ToolExecutor`: email, calendar, file write/delete, external API/DB mutation.

`MemoryClient.write_memory_candidates(...)` **KHÔNG** phải tool và **KHÔNG** đi qua
`ToolExecutor`. Nó là **persistence nội bộ best-effort sau khi task xong** (§5b), nên
**không bị chặn** bởi degraded side-effect policy — nhưng phải đánh dấu non-durable/local
khi degraded.

> ⚠️ **Trường hợp `write_note`:** nếu `write_note` tồn tại như một **built-in tool**
> user-visible (user yêu cầu "ghi vào note") → nó đi qua `ToolExecutor` → degraded thì
> **block/approval** như mọi side-effect. Khác với memory-candidate-write tự động sau
> finish (không qua executor). **Chốt khi implement:** một thao tác note do user yêu cầu
> là tool; một memory-candidate do agent tự rút ra sau run là internal write. Không trộn.

---

## 5. Degraded mode — cờ đơn điệu (monotonic)

`ContextPack` và `AgentState` mang trạng thái memory. Bổ sung:

```python
# contracts.py — thêm vào ContextPack
class ContextPack(BaseModel):
    ...
    degraded: bool = False            # True nếu phục vụ bởi local fallback
    memory_source: str = "remote"     # "remote" | "local"

# agent_state.py — thêm field
@dataclass
class AgentState:
    ...
    memory_degraded: bool = False     # leo lên, KHÔNG tụt xuống trong 1 run
```

**Luật cờ degraded:**

1. `LocalMemoryClient` luôn trả `ContextPack(degraded=True, memory_source="local")`.
2. Khi runtime nhận một `ContextPack` có `degraded=True` → set `state.memory_degraded = True`.
3. **Cờ chỉ leo lên, không tụt xuống trong một run.** Một khi task chạm local fallback,
   nó degraded đến hết task — kể cả nếu lượt retrieve sau lấy được item. Nếu cho cờ
   dao động, disclosure của FinalComposer thành không xác định.
4. **Không phiền user mỗi lượt.** Nhưng `FinalComposer` **phải disclose** khi
   `state.memory_degraded == True` VÀ kết quả có thể bị ảnh hưởng về:
   - chất lượng context / recall, hoặc
   - **an toàn hành động** (quan trọng nhất).

   Ví dụ phải nói: một decision "đã chốt dùng FTS5 thay vector" nằm ở remote; local
   không có → agent có thể đề xuất ngược. Lúc đó FinalComposer thêm một dòng kiểu:
   _"(Lưu ý: đang chạy ở chế độ memory rút gọn — không kết nối TOMTIT-Memory — nên
   ngữ cảnh dự án dài hạn có thể thiếu.)"_

---

## 5b. Write-after-finish — failure policy [MVP-local must]

Flow: retrieve trước plan, **write memory candidates sau khi task xong**. Hai câu hỏi:
(a) write fail thì task coi như xong hay fail? (b) làm sao disclose write-fail mà không
phải sửa câu trả lời đã chốt?

**Policy MVP — write best-effort, KHÔNG chặn user, nhưng `complete()` là event CUỐI:**

Thứ tự đúng (sửa theo review — tránh "complete trước rồi phải sửa answer"):

```
1. draft = FinalComposer.compose(state)          # compose nháp, CHƯA complete
2. write memory (best-effort, CÓ TIMEOUT NGẮN):
       try: resp = memory_client.write_memory_candidates(...)   # timeout ~2s
       except (Error | Timeout): state.memory_write_failed = True
                                 state.errors.append(...); log WARNING
3. nếu memory_write_failed AND user kỳ vọng persistence:
       disclosure_reasons.append("memory_write_failed")
       draft = draft + disclosure_summary(disclosure_reasons)
4. AgentState.complete(draft)                    # complete là event CUỐI, answer đã final
```

**Luật:**

1. Write **không bao giờ chặn câu trả lời quá ~2s** (timeout ngắn). Write treo/chậm →
   coi như fail best-effort, không giữ user chờ. (Đây là rủi ro của "write trước
   complete" — timeout giải nó.)
2. Write fail/timeout → `state.memory_write_failed=True` + `state.errors` + WARNING.
   **Không** set `status=FAILED`. Task vẫn COMPLETED.
3. **Disclose chỉ khi user kỳ vọng persistence** (plan chứa step write-note/lưu-memory
   do user yêu cầu). Deterministic, qua `disclosure_reasons` (§7b), KHÔNG để model tự quyết.
4. `complete()` gọi **sau cùng**, với answer đã gồm disclosure nếu cần → không phải sửa
   state đã complete.
5. Local fallback write vào `InMemoryStore` → **không durable qua process restart**. Ở
   degraded, đây là expected; disclosure degraded (§5) đã bao hàm.

> **Trade-off đã cân nhắc:** "write trước complete" cho phép disclose đúng (review 4.3),
> nhưng mở rủi ro write chặn answer. Timeout ngắn đóng rủi ro đó. Nếu sau này cần đảm
> bảo durable trước khi báo thành công (write phải thành công) → [deferred], không phải MVP.

---

## 6. TokenCounter — CHỐT implementation cho MVP

`LocalMemoryClient` cắt `ContextPack` theo `token_budget`. Đếm token khác với
TOMTIT-Memory → cùng budget ra lượng context khác nhau → hành vi agent đổi tùy backend
→ không reproduce. Đây là blocker, nên **chốt luôn** chứ không chỉ cảnh báo.

**CHỐT cho MVP — `ApproxTokenCounter` (deterministic, zero dependency):**

```python
# agent_core/memory/token_counter.py
from __future__ import annotations
from typing import Protocol, runtime_checkable

@runtime_checkable
class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...

class ApproxTokenCounter:
    """MVP token counter. Word-based, deterministic. KHÔNG chính xác như tokenizer LLM
    — chỉ cần cùng-một-cách-đếm hai bên để budget reproduce được. Thay bằng tokenizer
    thật là [deferred], qua đúng interface này nên không vỡ call site."""
    def count(self, text: str) -> int:
        return max(1, len(text.split()))
```

**Luật:**

- Cả `LocalMemoryClient` và (sau này) TOMTIT-Memory HTTP server dùng **cùng** logic này.
- **KHÔNG** dùng `tiktoken`/tokenizer LLM ở MVP (tránh thêm dependency).
- Đây là **xấp xỉ tạm** — ghi rõ trong code. `token_budget=1500` ≈ 1500 _từ_, không phải
  1500 token model. Chấp nhận cho MVP vì mục tiêu là _reproduce_, không phải _chính xác_.
- Thay tokenizer thật: [deferred], qua interface `TokenCounter` → không vỡ gì.

---

## 7. `AgentState.memory` — store thuộc về `LocalMemoryClient`, KHÔNG về `AgentState`

> Reviewer đúng: giữ `AgentState.memory: MemoryStoreProtocol` lâu sẽ kéo `AgentState`
> thành memory god-object — và mâu thuẫn `CLAUDE.md §7` ("không nhồi durable memory vào
> AgentState"). Tên field cũng nguy hiểm: code sau dễ quay lại gọi `state.memory.search(...)`.

**Mô hình đúng [MVP-local must]:**

- **`LocalMemoryClient` sở hữu store.** Store inject vào client, KHÔNG vào `AgentState`.
- Wiring: `RuntimeAgent(memory_client: MemoryClientProtocol)`. **KHÔNG** `AgentState(memory=...)`.
- Runtime gọi `memory_client.retrieve_context_pack(...)` / `.write_memory_candidates(...)`.
  Runtime **không bao giờ** chạm store trực tiếp.

**Field `AgentState.memory` cũ [P1 — không làm trong P0-recovery]:**

- Bỏ `default_factory=InMemoryStore` (lỗi mỗi-state-một-store) — nhưng đây **chạm public
  contract của `AgentState`**, nên KHÔNG làm trong P0-recovery. Lên lịch ở một step P1 riêng.
- Cho tới khi bỏ được: đánh dấu field **deprecated/internal**, **cấm runtime mới gọi
  `state.memory.*` trực tiếp**. Mọi truy cập memory đi qua `memory_client`.
- Mục tiêu cuối: gỡ hẳn `memory` khỏi `AgentState`. Hoãn để giảm số call site vỡ một lần.

---

## 7b. State / contract fields — phân tầng rõ

Bạn đề xuất một nhóm field cho binding + provenance. Tất cả đúng về thiết kế. Phân
tầng để build đúng liều:

| Field                                          | Nơi           | Tầng                                  | Ghi chú                                                                                  |
| ---------------------------------------------- | ------------- | ------------------------------------- | ---------------------------------------------------------------------------------------- |
| `memory_degraded: bool`                        | `AgentState`  | **MVP-must**                          | cờ đơn điệu, §5                                                                          |
| `degraded: bool`                               | `ContextPack` | **MVP-must**                          | local client luôn True                                                                   |
| `memory_source: "remote"\|"local"`             | `ContextPack` | **MVP-must**                          | nguồn pack                                                                               |
| `provenance / source / confidence / freshness` | `ContextItem` | **MVP-must (field), logic tối thiểu** | local set "fallback/limited"; chưa ranking theo confidence (`Literal`, §4c)              |
| `fallback_reason: str\|None`                   | `AgentState`  | **MVP-must**                          | "remote_unavailable" khi auto tụt local                                                  |
| `backend_mode_requested: local\|remote\|auto`  | `AgentState`  | **MVP-must**                          | từ config                                                                                |
| `memory_backend_selected: local\|remote\|none` | `AgentState`  | **MVP-must**                          | chốt lúc bind                                                                            |
| `memory_write_failed: bool`                    | `AgentState`  | **MVP-must**                          | §5b; write best-effort fail → True                                                       |
| `disclosure_reasons: list[str]`                | `AgentState`  | **MVP-must**                          | policy append lý do; FinalComposer disclose nếu list không rỗng                          |
| ~~`can_use_side_effect_tools`~~                | —             | **BỎ**                                | derived state → dễ stale. PolicyEngine tính trực tiếp tại execute (§4d), KHÔNG lưu field |
| ~~`disclosure_required: bool`~~                | —             | **thay bằng `disclosure_reasons`**    | bool không cho biết disclose VÌ SAO; dùng list reasons                                   |
| `backend_bound_at: timestamp`                  | `AgentState`  | **deferred**                          | định nghĩa, chưa cần logic                                                               |
| `backend_health_snapshot: {...}`               | `AgentState`  | **deferred**                          | lưu `HandshakeResult` để debug; chưa wire                                                |
| `state_backend_selected`                       | `AgentState`  | **deferred**                          | MVP chưa có state backend **remote**; chỉ memory. Định nghĩa field, để "local".          |

> **Nguyên tắc:** field [deferred] được **định nghĩa với default an toàn** ngay bây giờ
> (để contract không phải đổi sau), nhưng **không wire logic** cho tới khi luồng E2E
> local chạy. Tránh đúng cái bẫy over-abstraction trong planning phase.
>
> **`disclosure_reasons` — giá trị hợp lệ [Literal]:** `"memory_degraded"`,
> `"memory_write_failed"`, `"context_recall_limited"`, `"side_effect_blocked"`,
> `"remote_unavailable"`. Khóa giá trị, không string tự do.

### Disclosure là deterministic, KHÔNG để model quyết (điểm 4)

```python
# policy layer (deterministic) — chạy TRƯỚC khi compose final
if state.memory_degraded and task_touches_memory:
    state.disclosure_reasons.append("memory_degraded")
if state.memory_write_failed and user_expected_persistence:
    state.disclosure_reasons.append("memory_write_failed")
if state.memory_degraded and step.has_side_effect:
    → PolicyEngine DENY hoặc require approval (§4d)   # KHÔNG cần lưu can_use_side_effect_tools

# FinalComposer: chỉ VIẾT câu disclose khi disclosure_reasons KHÔNG rỗng.
# Model viết chữ theo reasons; policy quyết CÓ disclose hay không + VÌ SAO.
```

Khớp `CLAUDE.md §1`: LLM hiểu ngôn ngữ, code kiểm soát hành vi.

| Test                               | Assert                                                                                                         |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| protocol conformance               | `RemoteMemoryClient` và `LocalMemoryClient` đều `isinstance(..., MemoryClientProtocol)`                        |
| local retrieve                     | seed store → `retrieve_context_pack` trả `ContextPack(degraded=True, memory_source="local")`, items đúng       |
| local budget cut                   | budget nhỏ → `truncated=True`, `tokens_used <= token_budget`                                                   |
| remote ok                          | mock `/retrieve` → `ContextPack(degraded=False)`                                                               |
| remote fail at start (mode=remote) | health-check fail → factory **raise**, KHÔNG trả local                                                         |
| auto fallback                      | health fail + mode=auto → trả `LocalMemoryClient`, log warning                                                 |
| degraded monotonic                 | inject degraded pack rồi non-degraded pack → `state.memory_degraded` vẫn True                                  |
| **no mid-run switch**              | remote chết giữa run → `state.status == FAILED`, KHÔNG có item local nào lẫn vào observations                  |
| composer disclosure                | `memory_degraded=True` → final answer chứa câu disclose                                                        |
| disclosure deterministic           | `disclosure_reasons` do policy append, KHÔNG do model; list rỗng → composer không tự thêm disclose dù degraded |
| side-effect blocked when degraded  | degraded + step `mutates_state/requires_approval` → PolicyEngine DENY, `tool.fn` KHÔNG chạy                    |
| handshake schema mismatch          | `/handshake` trả `schema_version` lệch → factory **raise**, không bind                                         |
| auto always falls back             | remote down + mode=auto → bind LocalMemoryClient, `memory_degraded=True` (KHÔNG xét task ở bind-time)          |
| same token count                   | cùng input → local `tokens_used` khớp cách đếm của Memory (dùng chung TokenCounter)                            |

---

## 9. Thứ tự build (chèn vào PHASE 3)

PHASE 3 cũ ("MemoryClient HTTP + FakeMemoryClient") mở rộng thành:

- **3a** — `contracts.py` (`ContextPack` + cờ degraded) + `MemoryClientProtocol`. Chốt contract trước (PHASE 2).
- **3b** — `LocalMemoryClient` bọc `InMemoryStore` sẵn có + test. **Làm trước remote** vì không cần Memory service chạy → test được ngay, không bị chặn bởi PHASE 1.
- **3c** — `RemoteMemoryClient` + factory chọn backend (§4) + test với mock HTTP.
- **3d** — `FakeMemoryClient` (deterministic) cho test wiring PHASE 4.

> **Lợi ích thứ tự này:** 3b cho bạn một `MemoryClient` chạy được **trước khi**
> TOMTIT-Memory có HTTP server. Tức là PHASE 4 (wiring) + demo E2E local có thể chạy
> mà không chờ PHASE 1 xong. Remote ghép vào sau, runtime không đổi một dòng.

---

## 10. Cập nhật DoD

MVP coi là đạt khi **một trong hai** đúng:

- **Local path:** agent chạy end-to-end với `LocalMemoryClient`, demo được 1 luồng,
  final answer disclose degraded mode.
- **Remote path:** agent chạy end-to-end với `RemoteMemoryClient` gọi TOMTIT-Memory
  thật, `degraded=False`, 1 luồng qua HTTP.

Đạt local path trước là đủ để đi nói chuyện design partner. Remote là bước ghép tiếp,
không phải điều kiện chặn của "MVP chạy được".

```

```

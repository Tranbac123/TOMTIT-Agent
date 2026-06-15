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
- runtime: retrieve trước plan, write sau finish (P3: write sync best-effort, KHÔNG hard-timeout; timeout là P6 — §5b)

> **[P6 cần chốt — ghi nhận, chưa chặn P3/P4]:**
>
> 1. **`ContextPack.total_items` semantics:** hiện P2 đặt `total_items = len(items)` (sau token
>    cut). Local vs remote dễ hiểu khác. Chốt trước P6: `total_items` = số record sau backend
>    retrieval/max_items **trước** token-budget cut; `len(items)` = số thực trả về.
> 2. **Candidate type NOTE:** `MemoryCandidate(type=NOTE)` ghi qua `store.write()` chung, nhưng
>    named-note nghiệp vụ phụ thuộc `note_index`/metadata tên. Hiện `_collect_candidates=[]` nên
>    chưa lỗi. Trước khi auto-sinh candidate: chốt candidate NOTE có là named-note, hay memory
>    candidate chỉ dùng FACT/PREFERENCE/DECISION/TASK_SUMMARY.

- `FinalComposer` disclosure **deterministic**: policy set `disclosure_reasons`, helper
  `append_disclosures()` thêm fixed text — model/composer KHÔNG tự quyết hay tự viết (§7b)
- `ApproxTokenCounter` dùng chung (§6)
- `memory_degraded` CHỈ disclose, KHÔNG chặn tool (§4d QĐ-4); execution safety độc lập qua risk/approval/read_only
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

`ContextPack` / `MemoryCandidate` / `WriteResponse`: **source of truth =
`agent_core/memory/contracts.py` theo `SPEC_P1_contract.md`.** `MVP_MASTER_PLAN.md` chỉ là summary.
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
  `ContextPack` bằng adapter **nhỏ nhất có thể**. KHÔNG tự chế API mới cho store.
  **(P2 đã xác nhận: store sort `importance DESC, updated_at DESC` + `[:limit]`; KHÔNG có
  field `score` → `ContextItem.score ← MemoryRecord.importance`. KHÔNG dùng `score=0.0`/
  insertion-order — đó là giả định cũ sai, store thật đã rank theo importance.)**
- `retrieve_context_pack`: gọi `store.search()` rồi **tự ráp `ContextPack`** (khớp P2 đã build):
  - **`text=""` — KHÔNG lọc theo goal.** Store substring-match nguyên câu goal gần như luôn
    rỗng; local là fallback/demo nên trả top-k, KHÔNG relevance-match (đó là việc remote P6).
  - **KHÔNG rank lại.** `store.search` đã sort `importance DESC, updated_at DESC` + `[:limit]`.
    Giữ NGUYÊN thứ tự store trả.
  - `ContextItem.score ← MemoryRecord.importance` (store KHÔNG có field `score`).
  - cắt theo `token_budget` dùng **cùng TokenCounter** (§6), break tại item đầu vượt budget,
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

**An toàn task nằm ở ToolExecutor, ĐỘC LẬP với memory_degraded (§4d QĐ-4):**

`memory_degraded=True` (luôn đúng với local) CHỈ ảnh hưởng disclosure — **KHÔNG chặn tool.**
Execution safety quyết định độc lập tại ToolExecutor bằng `risk_level`/`mutates_state`/
`requires_approval`/`read_only` sẵn có. Read-only chạy bình thường; side-effect qua
approval-gate thường nếu `requires_approval`. Việc chặn-do-degraded thuộc `execution_degraded`
([deferred] — chỉ khi audit/authz/sandbox không khả dụng), KHÔNG phải `memory_degraded`.

Luật bất biến (cập nhật QĐ-4):

1. Read-only / answer-only chạy bình thường (memory_degraded → disclose, không chặn).
2. Side-effect qua approval-gate thường (risk/approval/read_only) — KHÔNG dính memory_degraded.
3. mode=remote fail → fail fast.
4. `memory_degraded` chỉ leo lên trong một run (đơn điệu).

> **[deferred]** `execution_degraded` (block side-effect khi audit/authz/sandbox không
> khả dụng): thêm khi có tool side-effect/production thật. MVP-local KHÔNG cần.

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

### 4d. Hai loại degraded — KHÔNG trộn [QĐ-4, TranBac]

> **Lỗi thiết kế đã sửa:** spec cũ cho `memory_degraded → DENY side-effect`. Nhưng
> `LocalMemoryClient` LUÔN `memory_degraded=True`, nên mọi `write_note` luôn bị deny →
> **MVP-demo compound (calculate→write_note→finish) không chạy được.** Gốc rễ: một cờ
> gánh hai nghĩa. Tách:

| Cờ                   | Nghĩa                                                                          | Hệ quả                                                      | Trạng thái                                                      |
| -------------------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------- | --------------------------------------------------------------- |
| `memory_degraded`    | Context memory KHÔNG đầy đủ (local fallback thiếu so với remote)               | Ảnh hưởng recall + **disclosure**. **KHÔNG tự chặn write.** | **MVP-local must**                                              |
| `execution_degraded` | KHÔNG đủ điều kiện an toàn để side-effect (audit/authz/sandbox không khả dụng) | **Block/approval side-effect**                              | **[deferred]** — tới khi có email/file/API/tool production thật |

**Quy tắc P3 [MVP]:**

- `memory_degraded=True` (luôn đúng với local) → CHỈ disclose, **KHÔNG** chặn tool nào.
- **Execution safety quyết định ĐỘC LẬP** bởi cơ chế sẵn có: `risk_level`, `mutates_state`,
  `requires_approval`, `read_only` — đúng như ToolExecutor/PolicyEngine đã làm. KHÔNG dính tới `memory_degraded`.
- `write_note`/`save_*` (mutating, local-only) chạy bình thường ở MVP — vì memory-thiếu
  KHÔNG đồng nghĩa không-an-toàn-để-ghi. Chúng vẫn qua approval-gate thường nếu `requires_approval=True`.

**`execution_degraded` [deferred] — KHÔNG implement ở P3:**
Khi sau này audit/authz/sandbox không khả dụng → set `execution_degraded=True` → block side-effect:

```python
# [deferred] — chỉ khi có execution_degraded thật:
if state.execution_degraded and is_side_effect(tool):
    DENY  reason="execution degraded: side-effect blocked (audit/authz unavailable)"
```

Định nghĩa `is_side_effect` (fail-closed) giữ lại cho lúc đó:

```python
is_side_effect = (
    getattr(tool, "effect_type", None) != "read"
    or tool.mutates_state or tool.requires_approval
    or tool.risk_level >= RiskLevel.MEDIUM
    or getattr(tool, "effect_type", None) is None
)
```

> **Memory-candidate-write** (`write_memory_candidates` sau finish) KHÔNG phải tool, KHÔNG
> qua ToolExecutor — best-effort §5b, không liên quan execution safety.

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
4. **Không phiền user mỗi lượt.** Nhưng **finalization layer phải đảm bảo disclosure được
   thêm** (qua policy set `disclosure_reasons` → helper `append_disclosures`) khi
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

**Policy MVP — write best-effort, KHÔNG chặn user; `state.complete()` là terminal state
transition cuối, `run_completed` là telemetry emit sau transition.**

> **Write-path semantics (chính xác — tránh DoD nói nhiều hơn behavior):** P3 **wire + test**
> hook write sau finalize. Runtime thực hiện best-effort write **khi candidates được cung cấp**.
> Auto candidate-extraction là [deferred] → **normal MVP run có thể KHÔNG sinh candidate nào**
> (`_collect_candidates` trả `[]`). Note do user yêu cầu vẫn persist qua `write_note` **tool**
>
> - shared store (đường khác, không qua `write_memory_candidates`).

Thứ tự (tránh "complete trước rồi phải sửa answer"):

```
1. draft = FinalComposer.compose(state)          # compose nháp, CHƯA complete
2. write memory best-effort:
       try: memory_client.write_memory_candidates(...)
       except Exception:
           state.memory_write_failed = True
           state.errors.append(...); log.warning(...)   # BẮT BUỘC log WARNING
3. _apply_disclosure(state) → append_disclosures(draft, reasons)   # helper §3e (P3)
4. AgentState.complete(draft)                    # terminal state transition cuối
```

> **Timeout — phân hai backend (sửa theo TranBac, đóng mâu thuẫn với SPEC_P3):**

**P3 — `LocalMemoryClient`:**

- Write **sync best-effort** trong `try/except`. **KHÔNG hard-timeout, KHÔNG thread giả.**
- `InMemoryStore` không treo → timeout vô nghĩa cho local.
- **KHÔNG có timeout test ở P3.**

**P6 — `RemoteMemoryClient`:**

- Dùng `MEMORY_WRITE_TIMEOUT_SECONDS` làm **`httpx` timeout** (I/O mạng treo thật).
- timeout → `memory_write_failed=True` + WARNING + **KHÔNG** fail task.
- Timeout test thuộc P6.

**Luật chung (cả hai backend):**

1. Write fail/lỗi → `memory_write_failed=True` + `state.errors` + **log WARNING**. KHÔNG set
   `status=FAILED`. Task vẫn COMPLETED.
2. **Disclose chỉ khi user kỳ vọng persistence** (plan có write-note/save). Deterministic, §7b.
3. `complete()` gọi sau cùng, answer đã gồm disclosure nếu cần.
4. Local write vào `InMemoryStore` → không durable qua process restart (expected khi degraded).

> **[deferred] durable-before-success:** đảm bảo write durable TRƯỚC khi báo task thành công
> — KHÔNG phải MVP.

**Test §5b — P3 (KHÔNG có timeout test):**
| Test | Assert |
|---|---|
| write failure không FAILED | `write` raise → `memory_write_failed=True`, `status==COMPLETED`, answer vẫn trả |
| disclose khi kỳ vọng persistence | plan có write-note + write fail → `disclosure_reasons` chứa "memory_write_failed", answer disclose |
| không disclose khi không kỳ vọng | task thuần tính toán + write fail → answer KHÔNG có disclosure |
| (timeout test) | **[deferred P6]** — không làm ở P3 |

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

## 7. `AgentState.memory` — hai tầng: transitional (P3) → target (sau P4)

> Mục tiêu cuối: store KHÔNG nằm trong `AgentState` (tránh memory god-object, `CLAUDE.md §7`).
> Nhưng built-in tool cũ vẫn đọc `state.memory`, nên gỡ ngay sẽ vỡ chúng. Hai tầng:

**Tầng 1 — P3 transitional architecture (làm bây giờ, QĐ-2):**

- **Bootstrap / composition root sở hữu một `shared_store`.** KHÔNG phải RuntimeAgent, KHÔNG
  phải mỗi AgentState tự tạo.
- `shared_store` inject vào `LocalMemoryClient` **VÀ** truyền **cùng reference** vào
  `AgentState.memory` → built-in tool cũ và client mới đọc/ghi cùng một nguồn → không split-brain.
- Runtime MỚI **chỉ** gọi `MemoryClientProtocol`. KHÔNG thêm code mới dùng `state.memory`.
- `AgentState.memory` = **deprecated-but-shared** (compatibility tạm, KHÔNG dead). **GIỮ
  `default_factory=InMemoryStore`** ở P3 (bỏ sẽ phá call site cũ). Composition root có memory
  chủ động truyền `shared_store` vào; caller cũ không truyền vẫn dùng default (không vỡ).

**Tầng 2 — target architecture (sau P4-local-demo, step riêng):**

- Migrate built-in tool (`write_note` tool…) sang gọi `MemoryClientProtocol`.
- Gỡ `AgentState.memory` hoàn toàn.
- Đây là step riêng, KHÔNG làm trong P3 (giảm số call site vỡ một lần).

> Tóm: P3 = một store, cùng reference vào client + state.memory. Sau P4 = gỡ state.memory.
> §7 này thay thế mọi mô tả cũ "store KHÔNG inject vào AgentState" — bản cũ là target, không phải P3.

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
| `fallback_reason: str\|None`                   | `AgentState`  | **P6**                                | "remote_unavailable" khi auto tụt local — chỉ có nghĩa khi có factory/binding (P6)       |
| `backend_mode_requested: local\|remote\|auto`  | `AgentState`  | **P6**                                | từ config — P3 không có factory chọn backend                                             |
| `memory_backend_selected: local\|remote\|none` | `AgentState`  | **P6**                                | chốt lúc bind — P3 dựng LocalMemoryClient trực tiếp, không binding                       |
| `memory_write_failed: bool`                    | `AgentState`  | **MVP-must**                          | §5b; write best-effort fail → True                                                       |
| `disclosure_reasons: list[str]`                | `AgentState`  | **MVP-must**                          | policy append lý do; helper `append_disclosures` thêm fixed text nếu list không rỗng     |
| ~~`can_use_side_effect_tools`~~                | —             | **BỎ**                                | derived state → dễ stale. PolicyEngine tính trực tiếp tại execute (§4d), KHÔNG lưu field |
| ~~`disclosure_required: bool`~~                | —             | **thay bằng `disclosure_reasons`**    | bool không cho biết disclose VÌ SAO; dùng list reasons                                   |
| `backend_bound_at: timestamp`                  | `AgentState`  | **deferred**                          | định nghĩa, chưa cần logic                                                               |
| `backend_health_snapshot: {...}`               | `AgentState`  | **deferred**                          | lưu `HandshakeResult` để debug; chưa wire                                                |
| `state_backend_selected`                       | `AgentState`  | **deferred**                          | MVP chưa có state backend **remote**; chỉ memory. Định nghĩa field, để "local".          |

> **Nguyên tắc (sửa):** field [deferred]/P6 được **ghi tài liệu (documented) ngay bây giờ**
> để biết trước contract, nhưng **chỉ THÊM vào `AgentState` ở phase sở hữu behavior của nó**
> (vd `backend_mode_requested`/`fallback_reason`/`memory_backend_selected` → thêm ở **P6** khi
> có factory/binding, KHÔNG thêm ở P3). Tránh contract thừa + tránh executor thêm field P6
> vào P3 vì tưởng spec yêu cầu.
>
> **`disclosure_reasons` — giá trị hợp lệ [Literal]:** `"memory_degraded"`,
> `"memory_write_failed"`, `"context_recall_limited"`,
> `"remote_unavailable"`. Khóa giá trị, không string tự do.
> (`"side_effect_blocked"` bỏ — thuộc `execution_degraded` deferred, KHÔNG dùng ở MVP.)

### Disclosure là deterministic, KHÔNG để model quyết (điểm 4)

```python
# policy layer (deterministic) — chạy TRƯỚC khi compose final
if state.memory_degraded and task_touches_memory:
    state.disclosure_reasons.append("memory_degraded")
if state.memory_write_failed and user_expected_persistence:
    state.disclosure_reasons.append("memory_write_failed")
# LƯU Ý (QĐ-4): memory_degraded KHÔNG chặn side-effect. Execution safety độc lập
# (risk/approval/read_only). Block-do-degraded thuộc execution_degraded [deferred].

# append_disclosures(draft, disclosure_reasons): helper THUẦN thêm fixed text khi reasons
# KHÔNG rỗng. Policy quyết CÓ disclose + VÌ SAO (set reasons); helper ráp text cố định.
# Model/FinalComposer KHÔNG tự quyết, KHÔNG tự viết disclosure.
```

Khớp `CLAUDE.md §1`: LLM hiểu ngôn ngữ, code kiểm soát hành vi.

| Test                               | Assert                                                                                                                                                           |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| protocol conformance               | `RemoteMemoryClient` và `LocalMemoryClient` đều `isinstance(..., MemoryClientProtocol)`                                                                          |
| local retrieve                     | seed store → `retrieve_context_pack` trả `ContextPack(degraded=True, memory_source="local")`, items đúng                                                         |
| local budget cut                   | budget nhỏ → `truncated=True`, `tokens_used <= token_budget`                                                                                                     |
| remote ok                          | mock `/retrieve` → `ContextPack(degraded=False)`                                                                                                                 |
| remote fail at start (mode=remote) | health-check fail → factory **raise**, KHÔNG trả local                                                                                                           |
| auto fallback                      | health fail + mode=auto → trả `LocalMemoryClient`, log warning                                                                                                   |
| degraded monotonic                 | inject degraded pack rồi non-degraded pack → `state.memory_degraded` vẫn True                                                                                    |
| **no mid-run switch**              | remote chết giữa run → `state.status == FAILED`, KHÔNG có item local nào lẫn vào observations                                                                    |
| composer disclosure                | `memory_degraded=True` → final answer chứa câu disclose                                                                                                          |
| disclosure deterministic           | `disclosure_reasons` do policy append, KHÔNG do model; list rỗng → composer không tự thêm disclose dù degraded                                                   |
| memory_degraded does NOT block     | degraded + step `mutates_state` (vd write_note) → tool CHẠY bình thường (QĐ-4). Execution safety độc lập qua risk/approval/read_only, KHÔNG dính memory_degraded |
| handshake schema mismatch          | `/handshake` trả `schema_version` lệch → factory **raise**, không bind                                                                                           |
| auto always falls back             | remote down + mode=auto → bind LocalMemoryClient, `memory_degraded=True` (KHÔNG xét task ở bind-time)                                                            |
| same token count                   | cùng input → local `tokens_used` khớp cách đếm của Memory (dùng chung TokenCounter)                                                                              |

---

## 9. Thứ tự build — phase naming hiện tại (KHÔNG dùng 3a/3b/3c cũ)

> ⚠️ Bản cũ dùng "3a/3b/3c/3d, PHASE 4" dễ làm executor tưởng remote client là bước ngay
> sau local. Phase naming đúng:

- **P1-contract** — `contracts.py` (`ContextPack` + cờ degraded) + `MemoryClientProtocol`. ✅ CLOSED.
- **P2-local-client** — `LocalMemoryClient` bọc `InMemoryStore` + test. **Làm trước remote** vì
  không cần Memory service chạy. ✅ CLOSED.
- **P3-runtime-wiring** — wire client vào runtime loop (retrieve/finalize/write/disclose). ĐANG GATE.
- **P4-local-demo** — E2E local + test consumer thật đọc ContextPack. 🎯 MVP-local DoD.
- **P5-remote-memory** — TOMTIT-Memory HTTP server. (repo Memory)
- **P6-remote-client** — `RemoteMemoryClient` + factory chọn backend + handshake.
- **P7-remote-demo** — E2E remote. 🎯 MVP-remote DoD.

> **Lưu ý thứ tự:** remote client là **P6**, KHÔNG phải bước ngay sau local (P2). Giữa chúng
> là P3 (wiring) + P4 (demo) + P5 (server). Local path (P2→P4) chạy được trước khi có HTTP server.

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

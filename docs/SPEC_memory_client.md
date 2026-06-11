# SPEC — MemoryClient layer (PHASE 3 mở rộng)

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

**[MVP-must] build ngay:** một `MemoryClientProtocol`; `LocalMemoryClient` + `RemoteMemoryClient`;
factory binding-at-task-start; `/handshake` với 4 field lõi (health/ready/backend_version/schema_version/capabilities);
4 rule degraded tối thiểu (§4b); cờ `memory_degraded` đơn điệu; PolicyEngine chặn side-effect khi degraded (§4d);
disclosure deterministic; per-item provenance field (set giá trị, chưa ranking).

**[deferred] định nghĩa field/contract nhưng KHÔNG wire logic:** `latency_ms` auto-degraded;
`auth/permission`; `backend_health_snapshot`; `backend_bound_at`; `state_backend` remote;
`MemoryPolicy` engine; bảng task-classification chi tiết; confidence-based ranking.

**❌ KHÔNG làm trong spec này:** handshake protocol nhiều endpoint; policy engine phức tạp;
nhiều state backend; tự đổi backend giữa run; để FinalComposer/model tự quyết disclosure.

---

## 1. Vì sao một protocol, không phải hai store

Cái bẫy của "giữ cả hai": nếu local trả `list[MemoryRecord]` còn remote trả
`ContextPack`, runtime phải biết đang nói với backend nào → hai code path → debug
gấp đôi → đúng bệnh "hành động sai không debug được" mà TOMTIT sinh ra để chữa.

**Ràng buộc bất biến:** cả hai backend trả **cùng một kiểu `ContextPack`**. Runtime
gọi `client.retrieve_context_pack(goal, state)` và xử lý kết quả y hệt nhau bất kể
nguồn. Đó mới là "giữ cả hai" đúng cách.

Phân biệt ba lớp (đừng trộn):

| Lớp         | Protocol                         | Trả về            | Vai trò                                 |
| ----------- | -------------------------------- | ----------------- | --------------------------------------- |
| Persistence | `MemoryStoreProtocol` (đã có)    | `MemoryRecord`    | write/get/search thô                    |
| Domain      | `MemoryAgentProtocol` (đã có)    | `MemoryRecord`    | hiểu note/fact/preference               |
| **Client**  | **`MemoryClientProtocol` (mới)** | **`ContextPack`** | cái runtime gọi trước plan / sau finish |

Fallback local nằm ở **lớp client**, không phải lớp store.

---

## 2. `MemoryClientProtocol` — hợp đồng runtime gọi

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
- `retrieve_context_pack`: gọi `store.search(MemoryQuery(...))`, rồi **tự ráp `ContextPack`**:
  - rank theo score sẵn có (hoặc recency nếu chưa có score),
  - cắt theo `token_budget` dùng **cùng TokenCounter với Memory** (xem §6),
  - set `truncated` đúng,
  - mỗi item: `provenance="fallback"`, `source="local_memory"`, `confidence="limited"` (§4c).
- `write_memory_candidates`: map candidate → `MemoryRecord` → `store.write(...)`.
- **Luôn** set `degraded=True`, `memory_source="local"` trên `ContextPack` (§5).

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

**Luật handshake [MVP-must]:**

- `schema_version` ≠ Agent's `SCHEMA_VERSION` → **fail bind** (không chạy với contract lệch).
- `ready != true` hoặc `health_status != "ok"` → coi như unhealthy.
- Task cần capability mà backend không liệt kê → **fail bind** (đừng bind xong mới lỗi giữa run).

**[deferred]:** `auth/permission` (bind xong mới lỗi quyền) và `latency budget`
(remote quá chậm → auto coi là degraded). Định nghĩa field `latency_ms` + chỗ cho
`auth` trong `HandshakeResult` ngay bây giờ, nhưng **chưa** dùng để quyết định trong MVP.

### 4b. auto KHÔNG phải lúc nào cũng fallback — task degraded-policy

> Đây là chỗ spec trước của tôi **sai**: cho `auto` fallback local bất kể task. Hệ quả:
> task gửi email, remote audit chết, auto tụt local và vẫn gửi — **không audit trail**.
> Vi phạm safety gate. Sửa: **degraded-eligibility là thuộc tính của task.**

```
local                              local có thể trộn với remote item nếu task cho phép?  KHÔNG (xem §4c invariant)
remote   → handshake lành → bind remote; handshake hỏng → FAIL FAST, no fallback
auto     → handshake lành → bind remote
          handshake hỏng → XÉT task policy:
              degraded_allowed(task) == True  → bind local, degraded=True, fallback_reason="remote_unavailable"
              degraded_allowed(task) == False → pause/fail safely (KHÔNG chạy tiếp rồi báo nhẹ)
```

**`degraded_allowed(task)` — rule TỐI THIỂU [MVP-must], KHÔNG policy engine:**

Quyết định MVP: **không** build policy engine. Chỉ bốn rule:

1. Task **read-only / answer-only** (không side-effect, không cần audit đầy đủ):
   `auto` được fallback local, đánh dấu `degraded`.
2. Task **có side-effect HOẶC phụ thuộc memory/audit để an toàn**: degraded **không**
   tự chạy tiếp → pause/fail an toàn, hoặc yêu cầu **user approval rõ ràng**.
3. `remote` mode fail → **fail fast**, không fallback.
4. Degraded chỉ **leo lên** trong một run, không tự hạ.

```
degraded_allowed = (not task.has_side_effect) and (not task.requires_full_audit)
# Không chắc → coi là KHÔNG cho phép (fail-closed).
```

| Loại task                                                               | auto fallback local?                    |
| ----------------------------------------------------------------------- | --------------------------------------- |
| Read-only / answer-only (tính toán, checklist, tóm tắt, hỏi context cũ) | ✅ Có (hỏi context cũ thì **disclose**) |
| Side-effect (gửi email, đặt lịch, xoá/sửa file) hoặc cần audit đầy đủ   | ❌ Không — pause/fail/approval          |

> **[deferred]** Bảng phân loại chi tiết hơn (vd "sửa file dựa trên memory cũ → hỏi
> user") và một `MemoryPolicy` engine riêng: định nghĩa **sau** khi runtime loop chạy.
> MVP chỉ cần nhị phân read-only-vs-không, fail-closed. Đừng mở rộng sớm.

**Nguồn `task.has_side_effect`:** suy ra từ plan — nếu plan chứa step gọi tool có
`mutates_state=True` / `requires_approval=True` / `risk_level >= MEDIUM` → `has_side_effect=True`.
Đây là **deterministic**, đọc từ `ToolSpec` đã có, không cần model đoán.

> ⚠️ **Vấn đề thứ tự:** muốn biết `has_side_effect` cần có plan; nhưng retrieve memory
> xảy ra **trước** plan. Giải: ở MVP, **bind backend trước, kiểm side-effect tại
> ToolExecutor**. Nếu đang degraded VÀ một step side-effect sắp chạy → PolicyEngine
> chặn (xem §4d). Như vậy không cần biết trước plan; an toàn được thực thi tại cổng
> execute — đúng chỗ duy nhất gọi `tool.fn`.

### 4c. Provenance — `degraded` cấp pack chưa đủ

Một `ContextPack` có thể **trộn** nhiều nguồn: prompt hiện tại, local fallback memory,
remote memory, file context, user-provided. Một cờ `degraded` cấp pack che mất _item
nào_ đáng tin. Mỗi `ContextItem` mang provenance:

```python
class ContextItem(BaseModel):
    content: str
    type: str
    score: float = 0.0
    tokens: int = 0
    source: str = "remote_memory"      # remote_memory | local_memory | file | user | prompt
    provenance: str = "remote"          # remote | fallback | user | file
    confidence: str = "normal"          # normal | limited | unknown
    freshness: str = "unknown"          # fresh | stale | unknown
    metadata: dict = Field(default_factory=dict)
```

**Invariant [MVP-must]:** trong **một run**, không trộn item `provenance="remote"` với
`provenance="fallback"`. Backend đã bind một lần (§4 luật cứng) nên pack đồng nhất
nguồn. `source="user"`/`"file"`/`"prompt"` thì được phép xuất hiện cùng (chúng không
phải memory backend). Provenance per-item phục vụ debug + cho FinalComposer/policy biết
item nào "limited".

### 4d. PolicyEngine chặn side-effect khi degraded [MVP-must]

`agent_core/safety/policy.py` — thêm rule deterministic:

```
if state.memory_degraded and tool.requires_full_audit:   # hoặc mutates_state + cần audit
    DENY  reason="degraded memory mode: side-effect/audit tool blocked"
```

Đây là nơi điểm 2 của bạn được **thực thi**, tại cổng execute, deterministic, không
giao cho model. Khớp `CLAUDE.md §1`: code kiểm soát hành vi.

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

## 6. TokenCounter — điểm dễ lệch nhất

`LocalMemoryClient` cắt `ContextPack` theo `token_budget`. Nếu nó đếm token khác với
TOMTIT-Memory, thì cùng một budget cho ra lượng context khác nhau giữa hai backend →
hành vi agent đổi tùy backend → không reproduce được.

**Luật:** cả hai client dùng **cùng một `TokenCounter`**. TOMTIT-Memory đã có
`TokenCounter` protocol — Agent phải import/tái dùng đúng cách đếm đó, hoặc hai bên
cùng trỏ về một implementation chuẩn. Đây là chỗ tôi đánh dấu kiểm kỹ nhất ở gate.

---

## 7. Tác động lên `AgentState.memory`

- `AgentState.memory: MemoryStoreProtocol` hiện tại: **giữ lại** như backing store cho
  `LocalMemoryClient`, NHƯNG bỏ `default_factory=InMemoryStore` (lỗi cũ: mỗi state một
  store riêng). Store được inject từ ngoài, dùng chung.
- Runtime **không** gọi `state.memory` trực tiếp để lấy context nữa. Nó gọi
  `memory_client.retrieve_context_pack(...)`. `state.memory` chỉ còn là chi tiết backing
  của local client.
- Cân nhắc (ghi chú, không bắt buộc MVP): về sau có thể bỏ hẳn `memory` khỏi `AgentState`
  và để client tự giữ store. Chưa làm trong MVP để giảm số call site phải đổi.

---

## 7b. State / contract fields — phân tầng rõ

Bạn đề xuất một nhóm field cho binding + provenance. Tất cả đúng về thiết kế. Phân
tầng để build đúng liều:

| Field                                          | Nơi           | Tầng                                  | Ghi chú                                                                         |
| ---------------------------------------------- | ------------- | ------------------------------------- | ------------------------------------------------------------------------------- |
| `memory_degraded: bool`                        | `AgentState`  | **MVP-must**                          | cờ đơn điệu, §5                                                                 |
| `degraded: bool`                               | `ContextPack` | **MVP-must**                          | local client luôn True                                                          |
| `memory_source: "remote"\|"local"`             | `ContextPack` | **MVP-must**                          | nguồn pack                                                                      |
| `provenance / source / confidence / freshness` | `ContextItem` | **MVP-must (field), logic tối thiểu** | local set "fallback/limited"; chưa cần ranking theo confidence                  |
| `fallback_reason: str\|None`                   | `AgentState`  | **MVP-must**                          | "remote_unavailable" khi auto tụt local                                         |
| `backend_mode_requested: local\|remote\|auto`  | `AgentState`  | **MVP-must**                          | từ config                                                                       |
| `memory_backend_selected: local\|remote\|none` | `AgentState`  | **MVP-must**                          | chốt lúc bind                                                                   |
| `can_use_side_effect_tools: bool`              | `AgentState`  | **MVP-must**                          | False khi degraded; PolicyEngine đọc (§4d)                                      |
| `disclosure_required: bool`                    | `AgentState`  | **MVP-must**                          | policy set, FinalComposer đọc (deterministic, không để model tự quyết)          |
| `backend_bound_at: timestamp`                  | `AgentState`  | **deferred**                          | định nghĩa, chưa cần logic                                                      |
| `backend_health_snapshot: {...}`               | `AgentState`  | **deferred**                          | lưu `HandshakeResult` để debug; chưa wire                                       |
| `state_backend_selected`                       | `AgentState`  | **deferred**                          | MVP chưa có state backend **remote**; chỉ memory. Định nghĩa field, để "local". |

> **Nguyên tắc:** field [deferred] được **định nghĩa với default an toàn** ngay bây giờ
> (để contract không phải đổi sau), nhưng **không wire logic** cho tới khi luồng E2E
> local chạy. Tránh đúng cái bẫy over-abstraction trong planning phase.

### Disclosure là deterministic, KHÔNG để model quyết (điểm 4)

```
# policy layer (deterministic) — chạy TRƯỚC FinalComposer
if state.memory_degraded and task_touches_memory:
    state.disclosure_required = True
if state.memory_degraded and step.has_side_effect:
    → PolicyEngine DENY hoặc require approval (§4d)

# FinalComposer: chỉ VIẾT câu disclose khi state.disclosure_required == True.
# Model viết chữ; policy quyết có disclose hay không.
```

Khớp `CLAUDE.md §1`: LLM hiểu ngôn ngữ, code kiểm soát hành vi.

| Test                               | Assert                                                                                                                         |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| protocol conformance               | `RemoteMemoryClient` và `LocalMemoryClient` đều `isinstance(..., MemoryClientProtocol)`                                        |
| local retrieve                     | seed store → `retrieve_context_pack` trả `ContextPack(degraded=True, memory_source="local")`, items đúng                       |
| local budget cut                   | budget nhỏ → `truncated=True`, `tokens_used <= token_budget`                                                                   |
| remote ok                          | mock `/retrieve` → `ContextPack(degraded=False)`                                                                               |
| remote fail at start (mode=remote) | health-check fail → factory **raise**, KHÔNG trả local                                                                         |
| auto fallback                      | health fail + mode=auto → trả `LocalMemoryClient`, log warning                                                                 |
| degraded monotonic                 | inject degraded pack rồi non-degraded pack → `state.memory_degraded` vẫn True                                                  |
| **no mid-run switch**              | remote chết giữa run → `state.status == FAILED`, KHÔNG có item local nào lẫn vào observations                                  |
| composer disclosure                | `memory_degraded=True` → final answer chứa câu disclose                                                                        |
| disclosure deterministic           | `disclosure_required` do policy set, KHÔNG do model; `disclosure_required=False` → composer không tự thêm disclose dù degraded |
| side-effect blocked when degraded  | degraded + step `mutates_state/requires_approval` → PolicyEngine DENY, `tool.fn` KHÔNG chạy                                    |
| handshake schema mismatch          | `/handshake` trả `schema_version` lệch → factory **raise**, không bind                                                         |
| degraded_allowed fail-closed       | task không rõ side-effect + remote down + auto → KHÔNG tự chạy degraded                                                        |
| same token count                   | cùng input → local `tokens_used` khớp cách đếm của Memory (dùng chung TokenCounter)                                            |

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

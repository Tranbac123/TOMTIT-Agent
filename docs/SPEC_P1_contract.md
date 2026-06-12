# SPEC P1-contract — `contracts.py` + `MemoryClientProtocol`

> **Phase:** P1-contract (sau P0-recovery đã đóng). **Executor:** Claude Code. **Gate:** TranBac.
> **Nguồn sự thật:** file này + `SPEC_memory_client.md §2, §4c, §6, §7b`. Nếu lệch,
> `SPEC_memory_client.md` thắng về chi tiết; file này thắng về **phạm vi** (cái gì làm bây giờ).
>
> **Mục tiêu P1-contract:** định nghĩa data contract + protocol **đủ cho `LocalMemoryClient`
> (P2) dùng**. KHÔNG server schema, KHÔNG handshake, KHÔNG factory, KHÔNG HTTP. Chỉ
> Pydantic models + một Protocol + `ApproxTokenCounter`. Hết.

---

## 0. SCOPE FENCE — luật một câu

> **Mỗi field/method phải trả lời được: "P4-local-demo có đọc/ghi nó không?"**
> Có → vào P1. Không → `[deferred]`, KHÔNG định nghĩa ở P1 (hoặc định nghĩa default an
> toàn nếu nó nằm chung model, nhưng KHÔNG wire). Đây là điểm over-build nguy hiểm nhất
> của dự án — giữ kỷ luật này tuyệt đối.

**Vào P1 (build):**

- `contracts.py`: `ContextItem`, `ContextPack`, `MemoryCandidate`, `WriteResponse`
- `client.py`: `MemoryClientProtocol` (explicit params, KHÔNG nhận `AgentState`)
- `token_counter.py`: `TokenCounter` Protocol + `ApproxTokenCounter`

**[deferred] — KHÔNG làm ở P1 (chỉ cần khi có HTTP, tức P5/P6):**

- `RetrieveRequest` / `WriteRequest` (HTTP request bodies) — `LocalMemoryClient` gọi
  method trực tiếp, không serialize qua HTTP, nên chưa cần.
- `HandshakeResult` + `/handshake` — P6.
- `latency_ms`, `auth`, `backend_health_snapshot` — remote-only.
- Factory chọn backend (`local`/`remote`/`auto`) — P6. P2 dựng `LocalMemoryClient` trực tiếp.
- `schema_version` enforcement logic — field thì có (versioned từ đầu), nhưng KHÔNG có
  mismatch-handling ở P1 (đó là handshake P6).

---

## 1. `agent_core/memory/contracts.py`

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent_core.state.enums import MemoryType   # enum ĐÃ CÓ; xem §1a nếu thiếu

SCHEMA_VERSION = "1"

# Literal khóa giá trị provenance — tránh typo "fallback"/"fall_back"/"localFallback".
MemorySource = Literal["remote_memory", "local_memory", "file", "user", "prompt"]
Provenance   = Literal["remote", "fallback", "user", "file", "prompt"]
Confidence   = Literal["normal", "limited", "unknown"]
Freshness    = Literal["fresh", "stale", "unknown"]


class ContextItem(BaseModel):
    """Một mẩu context trả về cho agent. Per-item provenance để biết item nào đáng tin."""
    content: str
    type: MemoryType
    score: float = 0.0
    tokens: int = 0
    source: MemorySource = "remote_memory"
    provenance: Provenance = "remote"
    confidence: Confidence = "normal"
    freshness: Freshness = "unknown"
    metadata: dict = Field(default_factory=dict)


class ContextPack(BaseModel):
    """Kết quả retrieve, token-budgeted. Cả local lẫn remote backend trả CÙNG kiểu này."""
    schema_version: str = SCHEMA_VERSION
    items: list[ContextItem] = Field(default_factory=list)
    total_items: int = 0
    tokens_used: int = 0
    token_budget: int = 0
    truncated: bool = False
    degraded: bool = False               # True nếu phục vụ bởi local fallback
    memory_source: Literal["remote", "local"] = "remote"


class MemoryCandidate(BaseModel):
    """Ứng viên memory để ghi sau khi task xong."""
    type: MemoryType
    content: str
    tags: list[str] = Field(default_factory=list)
    confidence: float = 1.0


class WriteResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    written_ids: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
```

### 1a. Nếu `MemoryType` enum thiếu/khác

Trước khi viết `contracts.py`: **inspect `agent_core/state/enums.py`**. Nếu `MemoryType`
chưa tồn tại hoặc thiếu members (`NOTE/FACT/PREFERENCE/DECISION/...`) → **normalize nó
TRONG P1-contract** (thêm/sửa enum cho ổn định) TRƯỚC khi dùng. KHÔNG để `type: str` lọt
vào. Ghi rõ trong report đã đụng `enums.py` gì.

> Lý do không dùng `str`: `ContextItem.type` được consumer (planner/composer) so khớp;
> string tự do sinh typo âm thầm. Enum bắt lỗi tại biên.

---

## 2. `agent_core/memory/token_counter.py`

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

MEMORY_WRITE_TIMEOUT_SECONDS = 2.0   # §5b SPEC_memory_client — constant, để test inject nhỏ


@runtime_checkable
class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class ApproxTokenCounter:
    """MVP token counter. Word-based, deterministic. KHÔNG chính xác như tokenizer LLM —
    mục tiêu là CÙNG-MỘT-CÁCH-ĐẾM hai bên (local + remote sau này) để token_budget
    reproduce được. Thay bằng tokenizer thật là [deferred], qua cùng Protocol nên không vỡ."""
    def count(self, text: str) -> int:
        return max(1, len(text.split()))
```

> `LocalMemoryClient` (P2) dùng `ApproxTokenCounter` để cắt `ContextPack` theo budget.
> TOMTIT-Memory HTTP server (P5) sau này PHẢI dùng cùng logic này.

---

## 3. `agent_core/memory/client.py`

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_core.memory.contracts import ContextPack, MemoryCandidate, WriteResponse


@runtime_checkable
class MemoryClientProtocol(Protocol):
    """Hợp đồng runtime gọi memory. KHÔNG nhận full AgentState — chỉ explicit params.
    Runtime tự rút user_id/session_id/task_id từ state và truyền vào. Giảm coupling,
    dễ test, remote client không kéo theo cả runtime state."""

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

**LUẬT:** signature này là contract. `LocalMemoryClient` (P2) và `RemoteMemoryClient`
(P6) đều implement đúng nó. KHÔNG thêm param `state`. KHÔNG thêm method ở P1.

---

## 4. KHÔNG làm gì ngoài 3 file trên

P1-contract **chỉ** tạo: `contracts.py`, `token_counter.py`, `client.py` (+ có thể chỉnh
`enums.py` nếu §1a). KHÔNG:

- ❌ `LocalMemoryClient` (đó là P2)
- ❌ wiring runtime (đó là P3)
- ❌ HTTP / server schema / handshake / factory
- ❌ đụng `AgentState` (trừ khi P3, không phải P1)
- ❌ thêm dependency (Pydantic đã có; KHÔNG thêm tokenizer lib)

---

## 5. Test P1-contract — `tests/test_contracts.py`

Tối thiểu, đủ chứng minh contract dùng được:

| Test                                   | Assert                                                                                                           |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `test_contextpack_defaults`            | `ContextPack()` dựng được, `degraded=False`, `memory_source="remote"`, `items==[]`                               |
| `test_contextitem_requires_memorytype` | `ContextItem(content="x", type=MemoryType.NOTE)` OK; truyền `type="note"` string → Pydantic raise (enum enforce) |
| `test_literal_rejects_typo`            | `ContextItem(..., provenance="fall_back")` → Pydantic raise (Literal khóa giá trị)                               |
| `test_protocol_conformance`            | một stub class implement đủ 2 method → `isinstance(stub, MemoryClientProtocol)` True                             |
| `test_approx_token_counter`            | `ApproxTokenCounter().count("a b c") == 3`; `count("") == 1` (max(1, ...))                                       |

Chạy `pytest -q` full, phải xanh (55 cũ + 5 mới = 60). Dán raw.

---

## 6. Acceptance P1-contract

- `from agent_core.memory.contracts import ContextPack, ContextItem, MemoryCandidate, WriteResponse` OK
- `from agent_core.memory.client import MemoryClientProtocol` OK
- `from agent_core.memory.token_counter import TokenCounter, ApproxTokenCounter, MEMORY_WRITE_TIMEOUT_SECONDS` OK
- `pytest -q` → 60 passed
- `import agent_core` vẫn OK (không vỡ P0)

---

## 7. Report mẫu (theo `BUILD_SPEC §0`)

```
## P1-contract report
- Branch: p1-contract
- Files: agent_core/memory/{contracts,token_counter,client}.py (new), tests/test_contracts.py (new)
         [+ enums.py nếu §1a — ghi rõ đã đụng gì]
- What/Why: <2-4 câu>
- pytest: <raw, phải 60 passed>
- MemoryType: <đã có sẵn / đã normalize gì ở §1a>
- Out-of-scope findings: <none | ...>
- Spec deviations: <none | ...>
<<< git diff >>>
<<< pytest raw >>>
```

Dừng sau P1-contract. Chờ gate. KHÔNG tự sang P2 (`LocalMemoryClient`).

# ARCHIVE — BUILD_SPEC STEP 6–9 (LỖI THỜI, KHÔNG THỰC THI)

> Các STEP này thuộc kế hoạch CŨ "hardening Agent". Mục tiêu đã đổi sang "MVP
> integration Agent ↔ Memory" (xem MVP_MASTER_PLAN.md + SPEC_memory_client.md).
> Giữ lại CHỈ để tham khảo lịch sử. Claude Code KHÔNG đọc file này để thực thi.
>
> - STEP 6 (persist InMemoryStore) — SAI HƯỚNG, thay bằng SPEC_memory_client.md.
> - STEP 7 (event log), STEP 8 (retry/timeout) — HOÃN post-MVP.
> - STEP 9 (dọn file rỗng) — hygiene, làm khi tiện.

---

## STEP 6 — [LỖI THỜI — tham khảo] Persist memory (bỏ per-state `InMemoryStore`)

**Lỗi (fact):** `AgentState.memory: MemoryStoreProtocol = field(default_factory=InMemoryStore)`
→ **mỗi `AgentState` tự tạo store riêng**. Hai turn cùng session = hai memory khác
nhau → agent quên ngay turn sau. Đây đánh thẳng vào value prop "agent ngừng quên project".

**Việc cần làm:**

1. Bỏ `default_factory=InMemoryStore` trên field `memory`. Đổi signature để
   **memory được inject từ ngoài**, một instance dùng chung qua các turn/session.
   Có hai cách, chọn cách ÍT phá vỡ nhất:
   - (A) `memory` thành tham số bắt buộc của `AgentState`. Rõ ràng nhất, nhưng đổi mọi call site.
   - (B) Một `AgentSession`/factory cấp ngoài giữ một store, mỗi turn tạo `AgentState`
     và truyền store đó vào. Giữ `AgentState` dataclass nhưng caller chịu trách nhiệm.
     **Đề xuất: (A)** — ép caller nghĩ về memory lifecycle, đúng tinh thần state-first.
2. Cập nhật `main.py` và mọi test dựng `AgentState(goal=...)` để truyền store dùng chung.
3. **Không** đổi `MemoryStoreProtocol`. Chỉ đổi cách `AgentState` nhận store.

**File:** `agent_core/state/agent_state.py`, `main.py`, các test khởi tạo `AgentState`.
**Class/field:** `AgentState.memory`.
**Vì sao:** persist là điều kiện sống còn của sản phẩm, không phải tối ưu.
**Trade-off:** đổi signature → vỡ call site → đó là điểm tốt, ép xử lý memory tường minh.

**Test bổ sung:** `tests/test_memory_persistence.py`

- write rồi read cùng store trả đúng content.
- hai `AgentState` chia sẻ một store → state #2 đọc được note của state #1.

**Acceptance:** test persistence xanh; `pytest` toàn bộ vẫn xanh.

---

## STEP 7 — Structured event log (observability thật)

**Lỗi (fact):** `RuntimeLifecycle.emit_event` chỉ `state.history.append("[event]...")`
dưới dạng string; `RuntimeEvent` dataclass được tạo rồi **vứt** (return nhưng caller
bỏ). Không replay, không eval, không debug-by-trace.

**Việc cần làm (tối giản, KHÔNG thêm lib):**

1. `RuntimeLifecycle` giữ `events: list[RuntimeEvent]` (in-memory). `emit_event`
   **append vào list** thay vì chỉ nối string. Vẫn có thể giữ string history cho
   người đọc, nhưng nguồn sự thật là `events`.
2. Định nghĩa một `EventSink` Protocol tối giản (`def emit(self, event: RuntimeEvent) -> None: ...`)
   và một `InMemoryEventSink` mặc định. `RuntimeLifecycle` nhận sink qua constructor
   (default = in-memory). **Không** viết file/DB sink trong step này.
3. Đảm bảo mọi `emit_event` hiện có (`planning_*`, `running_*`, `step_*`, `run_*`)
   đều đi qua sink.

**File:** `agent_core/runtime/lifecycle.py`; chỗ khởi tạo `RuntimeLifecycle` trong `runtime_agent.py`.
**Vì sao:** replay/eval/debug bất khả thi nếu event là string vứt đi. Đây là nền cho
mọi self-improvement tương lai — nhưng step này chỉ làm event log, **không** làm eval.
**Trade-off:** thêm một Protocol + một class nhỏ. Chấp nhận được vì nó là nền có người dùng ngay (test assert được chuỗi event).

**Test bổ sung:** `tests/test_event_log.py`

- chạy một goal happy-path → assert đúng thứ tự event: `planning_started → planning_completed → running_started → step_started → step_completed → run_completed`.
- chạy một goal tool-fail → assert có `step_failed` và **không** có `step_completed` sau đó.

**Acceptance:** test event log xanh; assert được trace từ `lifecycle.events`.

---

## STEP 8 — Quyết định `timeout`/`retry`: thực thi HOẶC gỡ field

**Lỗi (fact):** `ToolSpec` khai báo `timeout_seconds` và `RetryPolicy`, nhưng
executor gọi `tool.fn(...)` **trực tiếp** — không retry, không timeout. Field đang
nói dối người đọc spec.

**Quyết định cần TranBac chốt ở gate STEP 7 trước khi làm STEP 8:**

- **Phương án A — thực thi retry trước:** wrap `tool.fn` trong loop theo
  `tool.retry_policy` (`max_attempts`, `backoff_seconds`). Chỉ retry khi `idempotent`
  hoặc khi tool báo lỗi tạm thời. **Chưa làm timeout** (timeout đồng bộ trong Python
  cần `signal` chỉ main-thread hoặc thread/subprocess — đừng kéo `asyncio` vào chỉ vì việc này).
- **Phương án B — gỡ field:** nếu chưa có tool nào thực sự cần retry/timeout, **xóa**
  `timeout_seconds`/`retry_policy` khỏi `ToolSpec` để spec không nói dối. Thêm lại khi cần thật.

**Đề xuất architect:** B cho MVP (gỡ để trung thực), A khi có tool I/O thật (web_search
thật, file I/O). Hiện `web_search` đang là `FakeWebSearchClient` → chưa cần.

**File:** `agent_core/tools/executor.py` (nếu A) hoặc `agent_core/tools/base.py` (nếu B).
**Trade-off:** A = thêm độ phức tạp executor; B = mất metadata nhưng trung thực. Không
giữ field chết.

**Acceptance:** nếu A — test retry (tool fail 2 lần rồi thành công với `max_attempts=3`);
nếu B — `grep retry_policy agent_core/` chỉ còn ở chỗ đã gỡ sạch, `pytest` xanh.

---

## STEP 9 — Dọn file rỗng

**Lỗi (fact):** `agent_core/safety/risk.py` **rỗng hoàn toàn**;
`agent_core/planning/LLMIntentParser.py` **rỗng** nhưng tên gợi ý một thành phần
chưa tồn tại.

**Việc cần làm:**

- `risk.py`: nếu STEP nào cần phân loại risk runtime → viết nội dung thật;
  nếu không → **xóa file** (đừng để file safety rỗng đánh lừa rằng có logic).
- `LLMIntentParser.py`: **xóa**. LLM parser thuộc Mid/Long-term, không có trong spec
  này. File rỗng tạo ảo giác đã có fallback.

**File:** `agent_core/safety/risk.py`, `agent_core/planning/LLMIntentParser.py`.
**Vì sao:** file rỗng = nợ kỹ thuật vô hình, gây hiểu nhầm về năng lực hệ thống.
**Trade-off:** không. Xóa an toàn vì không ai import nội dung (kiểm bằng grep trước khi xóa).

**Acceptance:** `grep -rn "LLMIntentParser\|safety.risk" agent_core/ tests/` không còn
import nào trỏ tới file đã xóa; `pytest` xanh.

---

# BUILD_SPEC — TOMTIT-Agent (Recovery + Near-term Hardening)

> **Đối tượng đọc:** Claude Code (executor) và TranBac (architect / merge gate).
> **Phạm vi:** Đưa repo từ trạng thái **không import được** trở lại xanh, rồi cứng hóa
> reliability/safety/observability. **Không** thêm feature mới, **không** LLM planner,
> **không** MCP, **không** multi-agent, **không** vector memory trong spec này.
>
> **Mục tiêu cuối của spec:** một Agent runtime local-first chạy được, test xanh,
> memory persist qua turn, observability có structured event log replay được.

---

## 0. Luật vận hành (Claude Code PHẢI tuân thủ)

Đây là phần quan trọng nhất. Vi phạm = dừng.

1. **Một `§STEP` một lần.** Không được làm `STEP N+1` khi `STEP N` chưa qua gate review.
2. **Branch-per-step:** `git checkout -b step-N-description` trước khi sửa.
3. **Commit trước khi báo cáo:** mỗi step kết thúc bằng một commit sạch trên branch của nó.
4. **Gate review bắt buộc sau mỗi step.** Claude Code dừng và nộp:
   - `git diff main...HEAD` (toàn bộ thay đổi của step)
   - Kết quả `pytest -q` đầy đủ (paste raw, không tóm tắt)
   - Một đoạn ngắn: _đã làm gì, vì sao, có lệch spec không_
     Sau đó **chờ** TranBac + architect duyệt. Không tự merge `main`.
5. **Không sửa public contract ngoài phạm vi step.** Nếu phát hiện cần đổi contract
   khác → ghi vào mục "Phát hiện ngoài phạm vi" và **hỏi**, không tự sửa.
6. **Không xóa test đang fail để cho suite xanh.** Test fail = tín hiệu, không phải rác.
7. **Không thêm dependency** nếu spec không yêu cầu. `mathjs`/LLM client/vector lib = cấm.
8. **Không thêm abstraction thừa.** Nếu thấy "có thể tổng quát hóa" → ghi chú, đừng làm.
9. **Ưu tiên git history hơn viết mới.** Với file bị mất nội dung (xem STEP 1),
   `git show <commit>:<path>` để khôi phục bản gốc TRƯỚC khi viết tay.

**Định dạng báo cáo cuối mỗi step (bắt buộc, copy nguyên mẫu):**

```
## STEP N report
- Branch: step-N-xxx
- Files changed: <list>
- What/Why: <2-4 câu>
- pytest: <PASS/FAIL counts> + raw output dán bên dưới
- Out-of-scope findings: <none | mô tả>
- Spec deviations: <none | mô tả + lý do>
<<< paste git diff >>>
<<< paste pytest output >>>
```

---

## 1. Bối cảnh kỹ thuật (Claude Code đọc kỹ trước khi sửa)

Repo `TOM_TIT`, package chính `agent_core`. Kiến trúc **state-first**: `AgentState`
là source of truth; `ToolExecutor.execute()` là single execution gate
(resolve args → validate → policy → approval → execute → validate result → record).

**Trạng thái hiện tại: repo KHÔNG import được.** Đã xác nhận 4 lỗi cứng (chi tiết
trong từng STEP). Toàn bộ `import agent_core` fail → `main.py` fail → `pytest`
collection error trên planning + runtime.

**Boundary phải giữ nguyên (không được phá):**

- `AgentState` chỉ tự đổi status qua `fail()/complete()`; executor không set status agent-level.
- Planner sinh `list[Step]`, **không** gọi tool.
- `IntentParser` sinh `ParsedIntent`, **không** sinh plan.
- `IntentPlanner` map `ParsedIntent → list[Step]`, **không** parse raw text.
- Executor là nơi duy nhất gọi `tool.fn`.
- `MemoryStoreProtocol` (persistence) tách khỏi `MemoryAgentProtocol` (domain).

**Enum nguồn:** `agent_core/state/enums.py` (StrEnum). Lưu ý có `SourceType` bị định
nghĩa trùng ở hai nơi (xem STEP 4).

---

## 2. Bản đồ STEP (Near-term, dừng tại đây)

| STEP | Tên                                                            | Loại             | Blocker?          |
| ---- | -------------------------------------------------------------- | ---------------- | ----------------- |
| 1    | Khôi phục `RuleBasedIntentParser`                              | P0 fix           | Có — chặn mọi thứ |
| 2    | Sửa `base.py` self-import + tách `__init__.py`                 | P0 fix           | Có                |
| 3    | Khử trùng class `IntentPlanner` (2 file định nghĩa giống nhau) | P0 fix           | Có                |
| 4    | Hợp nhất `SourceType` enum                                     | P0 fix           | Có                |
| 5    | Import-sanity gate tests + chạy lại P0 test suite              | Test             | —                 |
| 6    | Persist memory (bỏ per-state `InMemoryStore`)                  | P1 reliability   | —                 |
| 7    | Structured event log (observability thật)                      | P1 observability | —                 |
| 8    | Quyết định `timeout`/`retry`: thực thi HOẶC gỡ field           | P1 honesty       | —                 |
| 9    | Dọn file rỗng (`risk.py`, `LLMIntentParser.py`)                | P1 hygiene       | —                 |

> STEP 1–4 nên gộp review chung **một vòng** nếu muốn (vì cùng là "làm repo
> import được"), nhưng **vẫn mỗi STEP một commit riêng** để rollback từng phần.
> STEP 5 trở đi **bắt buộc tách PR riêng**, mỗi STEP một gate.

---

## STEP 1 — Khôi phục `RuleBasedIntentParser`

**Lỗi (fact):** `class RuleBasedIntentParser` **không tồn tại** ở bất kỳ file nào,
nhưng được import + gọi `.parse()` ở 7 nơi: `rule_based_planner.py`,
`hybrid_planner.py`, `planning/__init__.py`, `planning/base.py`, và
`tests/test_planning_p0.py` (4 lần). File `intent_parser.py` đáng lẽ chứa nó
thì lại chứa nhầm một bản `class IntentPlanner` trùng với `intent_planner.py`.

**Việc cần làm:**

1. **Thử khôi phục bản gốc trước:**

   ```bash
   git log --oneline -- agent_core/planning/intent_parser.py
   git show <commit-trước-khi-hỏng>:agent_core/planning/intent_parser.py | head -40
   ```

   Nếu thấy `class RuleBasedIntentParser` → `git checkout <commit> -- agent_core/planning/intent_parser.py`.
   **Đây là đường ưu tiên.** Bản gốc sẽ khớp `test_planning_p0.py` chính xác hơn bản viết tay.

2. **Nếu mất hẳn trong history:** dùng bản khôi phục tối thiểu kèm theo
   (`intent_parser.py` do architect cung cấp). Nó kế thừa đúng `IntentName` +
   `ParsedIntent` đã có, hỗ trợ: CALCULATE, READ_NOTE, WRITE_NOTE, WEB_SEARCH,
   và các compound (CALCULATE_THEN_SAVE_NOTE, WEB_SEARCH_THEN_SAVE_NOTE,
   READ_NOTE_THEN_SUMMARIZE), đánh dấu `missing_slots` khi thiếu slot.

3. **Đối chiếu với test trước khi chốt:** mở `tests/test_planning_p0.py`, xem nó
   assert intent/slot gì. Nếu bản viết tay thiếu nhánh test cần → bổ sung nhánh đó,
   **không** sửa test cho khớp code.

**File:** `agent_core/planning/intent_parser.py`
**Class:** `RuleBasedIntentParser` (method `parse(self, goal: str) -> ParsedIntent`)
**Vì sao:** root cause của toàn bộ import failure.
**Trade-off:** bản viết tay có thể nghèo edge-case hơn bản gốc → bắt buộc đối chiếu test.

**Acceptance:** `python -c "from agent_core.planning.intent_parser import RuleBasedIntentParser"`
không raise.

---

## STEP 2 — Sửa `base.py` self-import + tách `__init__.py`

**Lỗi (fact):** `agent_core/planning/base.py` dòng 1 là
`from agent_core.planning.base import IntentParser, Planner` — **import từ chính nó**,
và không định nghĩa `IntentParser`/`Planner` → `ImportError`. Nội dung re-export
(7 dòng import + `__all__`) hiện đang nằm nhầm trong `base.py`; đó là nội dung
thuộc về `__init__.py`.

**Việc cần làm:**

1. `base.py` phải **định nghĩa** hai Protocol nền `IntentParser` và `Planner`
   (xem bản `base.py` architect cung cấp). `base` là file nền — **cấm** import từ
   `agent_core.planning` (`__init__`) để tránh circular import.
2. Chuyển toàn bộ phần re-export (`from ... import RuleBasedIntentParser`, `IntentPlanner`,
   `RuleBasedPlanner`, `HybridPlanner`, `SlotValidator`, `IntentName`, `ParsedIntent`
   - `__all__`) vào `agent_core/planning/__init__.py`.

**File:** `agent_core/planning/base.py`, `agent_core/planning/__init__.py`
**Vì sao:** self-import = ImportError cứng; nền không được phụ thuộc ngược lên package root.
**Trade-off:** không có. Zero-risk structural fix.

**Acceptance:** `python -c "import agent_core.planning"` không raise; `from agent_core.planning import Planner, IntentParser` OK.

---

## STEP 3 — Khử trùng class `IntentPlanner`

**Lỗi (fact):** `intent_planner.py` **và** `intent_parser.py` (trước STEP 1) cùng
định nghĩa `class IntentPlanner` y hệt. Sau STEP 1, `intent_parser.py` đã thành
parser → kiểm tra để chắc chỉ còn **một** `IntentPlanner` duy nhất nằm ở
`intent_planner.py`.

**Việc cần làm:**

```bash
grep -rn "class IntentPlanner" agent_core/
```

Phải ra **đúng 1 dòng** (`agent_core/planning/intent_planner.py`). Nếu còn ở chỗ khác → xóa.

**File:** `agent_core/planning/intent_planner.py` (giữ), kiểm tra phần còn lại.
**Vì sao:** một class, một file. Tránh import nhập nhằng.
**Trade-off:** không.

**Acceptance:** `grep -rc "class IntentPlanner" agent_core/` tổng = 1.

---

## STEP 4 — Hợp nhất `SourceType` enum

**Lỗi (fact):** `SourceType` định nghĩa **hai lần, khác members**:

- `agent_core/state/enums.py`: `WEB, MEMORY, TOOL, USER`
- `agent_core/state/agent_state.py`: `USER, AGENT, TOOL, SYSTEM, MEMORY`

Hai enum cùng tên trong cùng cây package → bug chờ nổ khi so sánh `==`/lookup.

**Việc cần làm:**

1. Chọn `state/enums.py` làm **nguồn duy nhất**. Bổ sung members còn thiếu vào đó:
   thêm `AGENT = "agent"` và `SYSTEM = "system"` (union của cả hai bản).
2. Xóa `class SourceType` cục bộ trong `agent_state.py`; thay bằng
   `from agent_core.state.enums import SourceType`.
3. `grep -rn "SourceType\." agent_core/ tests/` để kiểm mọi call site vẫn hợp lệ
   sau union (không call site nào dùng member đã biến mất — vì ta union nên không mất).

**File:** `agent_core/state/enums.py` (thêm members), `agent_core/state/agent_state.py` (xóa local, import).
**Vì sao:** loại latent collision; một enum một định nghĩa.
**Trade-off:** phải grep kỹ consumer trước khi merge; union an toàn hơn chọn một bản.

**Acceptance:**

```python
from agent_core.state.enums import SourceType as A
from agent_core.state.agent_state import SourceType as B
assert A is B
```

---

## STEP 5 — Import-sanity gate + chạy lại P0 suite

**Mục tiêu:** chốt rằng repo đã xanh và CI bắt được loại lỗi split-dở này lần sau.

**Việc cần làm:**

1. Thêm `tests/test_import_sanity.py`:
   - `test_package_imports`: `import agent_core` không raise.
   - `test_planning_public_api`: `from agent_core.planning import RuleBasedIntentParser, IntentPlanner, RuleBasedPlanner, HybridPlanner, SlotValidator` OK.
   - `test_sourcetype_single`: hai đường import `SourceType` là cùng object.
   - `test_main_constructs`: dựng được `RuntimeAgent(planner=RuleBasedPlanner(), tools=build_tool_registry())` không raise (không cần `run`).
2. Chạy `pytest -q` toàn bộ. **Bắt buộc** `tests/test_planning_p0.py` xanh.
   Nếu còn đỏ → quay lại STEP 1 đối chiếu parser, **không** sửa test.

**File:** `tests/test_import_sanity.py` (mới).
**Vì sao:** biến lỗi cấu trúc thành test fail thấy ngay, không để lọt vào dump sau.
**Trade-off:** không.

**Acceptance:** `pytest -q` → 0 error, 0 failed. Dán raw output vào report.

> 🚦 **GATE LỚN:** Đến đây repo phải chạy được `python main.py` và `pytest` xanh.
> TranBac + architect duyệt xong mới sang STEP 6. STEP 6+ mỗi cái một PR riêng.

---

## STEP 6 — Persist memory (bỏ per-state `InMemoryStore`)

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

## 3. Hết phạm vi Near-term — KHÔNG viết sẵn Mid/Long-term

Spec **dừng tại STEP 9**. Các việc sau **không** được Claude Code tự khởi động:

- LLM/Hybrid intent parser thật
- `RuntimeRef` thay placeholder string
- Replay engine đầy đủ, eval harness
- MCP / A2A / multi-agent
- Vector / RAG memory
- Self-improvement / memory validator

Lý do: đúng "things to avoid" của TranBac — không build các tầng này trước khi
runtime lõi vững (state contract sạch, test xanh, memory persist, event log replay
được). Khi STEP 9 qua gate, architect sẽ viết spec Mid-term **riêng**.

---

## 4. Checklist gate cho TranBac (dùng mỗi vòng review)

Trước khi cho Claude Code sang step kế:

- [ ] `git diff` chỉ chạm file trong phạm vi step? (không scope-creep)
- [ ] `pytest` raw output dán đầy đủ, không tóm tắt? Có 0 error/0 failed?
- [ ] Public contract có bị đổi ngoài ý không? (`AgentState`, `ToolSpec`, các Protocol)
- [ ] Có test mới cho hành vi mới (persistence/event log) không?
- [ ] Có thêm dependency / abstraction thừa không?
- [ ] "Out-of-scope findings" có gì cần mở step riêng không?
- [ ] Có file rỗng / TODO câm mới sinh ra không?

Nếu mọi ô tick → duyệt merge `main` → ra lệnh STEP kế. Nếu không → trả về, không sang bước sau.

---

# BUILD_SPEC — TOMTIT-Agent (P0 Recovery — STEP 1–5)

> **Đối tượng đọc:** Claude Code (executor) và TranBac (architect / merge gate).
> **Phạm vi:** CHỈ đưa repo từ trạng thái **không import được** trở lại xanh (4 lỗi P0).
> **Không** thêm feature, **không** memory persist, **không** event log, **không** LLM
> planner, **không** MCP, **không** multi-agent, **không** vector memory.
>
> **Mục tiêu cuối của spec này:** repo `import agent_core` không lỗi, `python main.py`
> chạy, `pytest` xanh. Hết. Memory integration nằm ở `MVP_MASTER_PLAN.md` +
> `SPEC_memory_client.md` (các PHASE sau, KHÔNG trong file này).

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

## 2. Bản đồ STEP — CHỈ 1–5 (P0 recovery)

| STEP | Tên                                                            | Loại   | Blocker?          |
| ---- | -------------------------------------------------------------- | ------ | ----------------- |
| 1    | Khôi phục `RuleBasedIntentParser`                              | P0 fix | Có — chặn mọi thứ |
| 2    | Sửa `base.py` self-import + tách `__init__.py`                 | P0 fix | Có                |
| 3    | Khử trùng class `IntentPlanner` (2 file định nghĩa giống nhau) | P0 fix | Có                |
| 4    | Hợp nhất `SourceType` enum                                     | P0 fix | Có                |
| 5    | Import-sanity gate tests + chạy lại P0 test suite              | Test   | —                 |

> STEP cũ 6–9 (persist/event-log/retry/hygiene) đã chuyển ra `ARCHIVE_BUILD_SPEC_OLD.md`,
> **không thực thi**. Sau STEP 5 → chờ spec PHASE tiếp theo (`MVP_MASTER_PLAN.md`).

> **STEP 1–4 review có thể gộp** _chỉ ở khâu review_, và **chỉ khi architect cho phép**.
> **Execution vẫn một-STEP-một-lần, một-commit-một-STEP** — gộp chỉ nghĩa là review cả
> bốn report sau khi cả bốn đã nộp, KHÔNG phải làm bốn STEP trong một commit. STEP 5
> **tách gate riêng** — cổng xác nhận P0-recovery hoàn tất.

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

**Acceptance:** `grep -rn "class IntentPlanner" agent_core/ | wc -l` = 1.

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

> 🚦 **GATE LỚN — HẾT PHẠM VI PHASE 0:** Đến đây repo phải chạy được `python main.py`
> và `pytest` xanh. TranBac + architect duyệt xong → PHASE 0 hoàn tất.

---

# HẾT PHẠM VI ACTIVE SPEC — STEP 1–5 LÀ TẤT CẢ

> STEP 6–9 (kế hoạch CŨ "hardening") đã được **chuyển ra `ARCHIVE_BUILD_SPEC_OLD.md`**
> và KHÔNG còn là việc-phải-làm. Sau khi STEP 1–5 (PHASE 0) qua gate:
> **DỪNG. Chờ architect ra spec PHASE tiếp theo** (P1-contract → P2-local-client → ...,
> xem `MVP_MASTER_PLAN.md`). KHÔNG tự khởi động việc trong archive.
>
> Nếu thấy mình đang định làm "persist InMemoryStore" / "event log" / "retry" →
> đó là tín hiệu DỪNG và HỎI (`CLAUDE.md §9`). Việc memory đúng nằm ở `SPEC_memory_client.md`.

---

## 3. Hết phạm vi — KHÔNG viết sẵn việc sau

Spec này **dừng tại STEP 5** (repo import được, pytest xanh). Các việc sau **không**
được Claude Code tự khởi động:

- Bất kỳ STEP nào trong `ARCHIVE_BUILD_SPEC_OLD.md` (persist/event-log/retry/hygiene)
- Memory client / wiring (đó là PHASE sau, theo `SPEC_memory_client.md`)
- LLM/Hybrid intent parser thật
- `RuntimeRef` thay placeholder string
- MCP / A2A / multi-agent / Vector / RAG / self-improvement

Lý do: đúng "things to avoid" của TranBac — không build tầng nào trước khi runtime lõi
import được + test xanh. Khi STEP 5 qua gate, architect ra spec PHASE tiếp theo (P1-contract,
xem `MVP_MASTER_PLAN.md`).

---

## 4. Checklist gate cho TranBac (dùng mỗi vòng review)

Trước khi cho Claude Code sang step kế:

- [ ] `git diff` chỉ chạm file trong phạm vi step? (không scope-creep)
- [ ] `pytest` raw output dán đầy đủ, không tóm tắt? Có 0 error/0 failed?
- [ ] Public contract có bị đổi ngoài ý không? (`AgentState`, `ToolSpec`, các Protocol)
- [ ] Có test mới cho hành vi mới (vd import-sanity ở STEP 5) không?
- [ ] Có thêm dependency / abstraction thừa không?
- [ ] "Out-of-scope findings" có gì cần mở step riêng không?
- [ ] Có file rỗng / TODO câm mới sinh ra không?

Nếu mọi ô tick → duyệt merge `main` → ra lệnh STEP kế. Nếu không → trả về, không sang bước sau.

---

## 5. Lệnh khởi động cho Claude Code (dán nguyên văn để bắt đầu STEP 1)

```
Chỉ dùng các file hiện tại ở repo root: CLAUDE.md, BUILD_SPEC.md, MVP_MASTER_PLAN.md,
SPEC_memory_client.md. BỎ QUA mọi bản upload/chat cũ cùng tên file.
KHÔNG mở hoặc thực thi ARCHIVE_BUILD_SPEC_OLD.md trừ khi được yêu cầu rõ để tham khảo lịch sử.

Đọc CLAUDE.md, BUILD_SPEC.md, MVP_MASTER_PLAN.md trước khi làm gì.
Tuân thủ CLAUDE.md §9 (thứ tự ưu tiên khi mâu thuẫn) và BUILD_SPEC.md §0 (luật vận hành) tuyệt đối.
Bắt đầu STEP 1 và CHỈ STEP 1.
Trước khi viết tay, thử khôi phục agent_core/planning/intent_parser.py từ git history:
  git log --oneline -- agent_core/planning/intent_parser.py
  git show <commit-trước-khi-hỏng>:agent_core/planning/intent_parser.py | head -40
Nếu history còn class RuleBasedIntentParser → checkout bản đó (ưu tiên).
Nếu mất → dùng bản fallback architect cung cấp, đối chiếu tests/test_planning_p0.py (KHÔNG sửa test cho khớp code).
Tạo branch step-1-restore-intent-parser, commit, rồi nộp report theo mẫu §0.
Dừng và chờ review. KHÔNG làm STEP 2.
```

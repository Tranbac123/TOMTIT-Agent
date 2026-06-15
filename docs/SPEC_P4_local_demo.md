# SPEC P4 — local demo: consumer thật đọc ContextPack

> **Đối tượng đọc:** Claude Code (executor) + TranBac (architect / merge gate).
> **Phạm vi:** chứng minh MVP-local DoD — MỘT consumer thật đọc `state.context_pack` và
> làm THAY ĐỔI output/decision. Đường explicit: `PROJECT_CONTEXT_QUERY → ANSWER_FROM_CONTEXT
→ FINISH` (phương án A đã duyệt).
> **Tiền đề:** P0/P1/P2/P3 CLOSED. P3 đã transport `ContextPack` vào `state.context_pack`
> nhưng CHƯA component nào đọc. P4 lấp đúng gap đó — không hơn.

---

## 0. SCOPE FENCE

**Vào P4 (sửa/thêm):**

- `agent_core/state/enums.py` — `ToolName` thêm `ANSWER_FROM_CONTEXT` (member thứ 13).
- `agent_core/planning/intents.py` — `IntentName` thêm `PROJECT_CONTEXT_QUERY` (member thứ 9).
- `agent_core/planning/intent_parser.py` — thêm nhánh nhận diện project-context query (§3).
- `agent_core/planning/intent_planner.py` — thêm nhánh map `PROJECT_CONTEXT_QUERY` → plan.
- `agent_core/runtime/runtime_agent.py` — thêm `ToolName.ANSWER_FROM_CONTEXT` vào `_MEMORY_ACTIONS`
  (§4b — integration BẮT BUỘC, nếu không project-query degraded sẽ KHÔNG disclose).
- `agent_core/tools/schemas.py` — thêm `AnswerFromContextOutput` dataclass (output contract).
- `agent_core/tools/builtin_tools.py` — thêm `tool_answer_from_context` (import Output từ schemas).
- `agent_core/tools/registry.py` — đăng ký `ANSWER_FROM_CONTEXT` + guard completeness (§6).
- `agent_core/state/agent_state.py` — thêm field `context_consumed: bool = False`.
- `agent_core/planning/slot_validator.py` — **CÓ THỂ chạm** (preflight §3b): thêm
  `PROJECT_CONTEXT_QUERY` nếu validator dùng mapping required-slots; nếu default-passthrough thì
  không sửa. Ghi report.
- `main.py` — thêm scenario 4 (project-context query) vào demo.
- test wiring.

**KHÔNG vào P4 (deferred / cấm):**

- ❌ Relevance-match theo goal (LocalMemoryClient bỏ qua goal — không giả vờ semantic retrieval).
- ❌ Conflict resolution khi >1 item (P4 trả "chưa đủ rõ", KHÔNG tự chọn).
- ❌ Planner/parser đọc ContextPack để đổi plan (chỉ tool consumer đọc).
- ❌ ContextInjector tổng quát chèn context vào mọi task.
- ❌ Two-run "agent tự lưu rồi tự nhớ" (cần intent SAVE_DECISION + parser + planner — scope creep,
  để milestone sau P4).
- ❌ MemoryAwareFinalComposer (giữ DefaultFinalComposer chuyển tiếp — không mở rộng protocol).
- ❌ Sửa bug `WEB_SEARCH_THEN_SAVE_NOTE` rơi `_unknown_plan` (out-of-scope debt — §8).

---

## 1. Định nghĩa sản phẩm (đã chốt)

**"Agent nhớ project"** = agent trả lời được một câu hỏi rõ ràng về quyết định/context dự án
đã lưu trong `ContextPack`, **không cần user chỉ định tên note** và **không dựa vào `read_note`
tool để lấy cùng dữ liệu đó**.

Đây là điểm phân biệt P4 với luồng READ_NOTE: READ_NOTE đọc note theo tên user cung cấp, nội
dung về `last_result` qua tool. PROJECT_CONTEXT_QUERY không có tên note — agent phải lấy từ
`ContextPack`. Nếu bỏ `ContextPack`, output PHẢI đổi (đó là điều test chứng minh).

---

## 2. Behavior E2E (one-run seeded)

```
seed: store.write(MemoryRecord(content="MVP đã chốt dùng FTS5, chưa dùng vector database",
                               type=MemoryType.DECISION))
goal: "Dự án đã chốt dùng cơ chế search nào cho MVP?"

run():
  _retrieve_memory  → state.context_pack = pack (chứa item DECISION trên, degraded=True)
  _plan             → parser: PROJECT_CONTEXT_QUERY → planner: [ANSWER_FROM_CONTEXT, FINISH]
  _execute_plan:
    ANSWER_FROM_CONTEXT(state, query) → đọc state.context_pack, lọc DECISION/PROJECT_CONTEXT
                                       → đúng 1 item → answer dùng content, context_consumed=True
    FINISH(answer="$last.output.answer") → final_answer = đúng field answer (KHÔNG serialize cả dataclass)
  _finalize_run     → compose chuyển tiếp; disclosure theo §4b P3 (PROJECT_CONTEXT_QUERY là
                      memory action trong plan → degraded vẫn disclose)
```

**Chứng minh không qua READ_NOTE:** plan KHÔNG chứa `ToolName.READ_NOTE`. Đây là assertion
khóa định nghĩa sản phẩm.

---

## 3. Parser rule — `PROJECT_CONTEXT_QUERY` (chốt deterministic, hẹp)

> **Quyết định:** trigger KHÔNG mở đầu bằng `Tính/Đọc/Lưu/Ghi/Tìm` để tránh bị nhánh hiện có
> nuốt. Dùng `^Dự\s+án\b`. "Dự án" không khớp bốn tiền tố cũ → chèn an toàn TRƯỚC fallthrough
> `_unknown`, KHÔNG đụng nhánh nào. KHÔNG phụ thuộc dấu "?" (mong manh — TranBac đã dặn).

Chèn vào `parse()` ngay TRƯỚC `return self._unknown(text)` (sau nhánh `^Tìm`):

```python
# Project-context query: "Dự án ..." + cụm hỏi-quyết-định. Hẹp bằng AND để không bắt nhầm.
if re.match(r'^Dự\s+án\b', text, re.IGNORECASE) and _PROJECT_QUERY_CUE.search(text):
    return self._parse_project_context_query(text)

return self._unknown(text)
```

Cue regex (đặt cạnh các `_*_SUFFIX` đầu file):

```python
_PROJECT_QUERY_CUE = re.compile(
    r'(đã\s+chốt|đã\s+quyết\s+định|quyết\s+định\s+nào|dùng\s+gì|'
    r'dùng\s+cơ\s+chế\s+nào|context|ngữ\s+cảnh)',
    re.IGNORECASE,
)
```

Handler:

```python
def _parse_project_context_query(self, text: str) -> ParsedIntent:
    # query = nguyên câu (LocalMemoryClient bỏ qua goal nên query chỉ để trace/log, không
    # dùng relevance-match). KHÔNG có slot bắt buộc → không missing_slots.
    return ParsedIntent(
        intent=IntentName.PROJECT_CONTEXT_QUERY,
        confidence=0.8,
        source="rule",
        raw_text=text,
        query=text,
    )
```

> **Vì sao AND (`^Dự án` + cue):** `^Dự án` đơn lẻ quá rộng. Thêm cue làm rule chỉ bắt câu
> HỎI về quyết định/context, không bắt "Dự án này..." ngẫu nhiên. Câu "Dự án ..." không có
> cue → rơi `_unknown` (an toàn, không bịa intent).
> **Giới hạn trung thực:** đây là rule hẹp cho DEMO, KHÔNG phải NLU tổng quát. Câu hỏi
> project diễn đạt khác ("cho tôi biết ta đã quyết gì về search") sẽ rơi UNKNOWN. Đúng phạm
> vi MVP — rule-based, không LLM (CLAUDE.md §7).

---

## 3b. PREFLIGHT — `SlotValidator` (đọc TRƯỚC khi sửa, có thể chạm)

> **Vì sao bắt buộc:** luồng thật là `parser → SlotValidator.validate → IntentPlanner`
> (`rule_based_planner.py`), KHÔNG phải parser đi thẳng planner. Nếu `SlotValidator` dùng
> mapping required-slots theo `IntentName`, intent mới `PROJECT_CONTEXT_QUERY` có thể bị xử lý
> sai âm thầm (thêm missing_slots sai → rơi clarification thay vì chạy tool).

**TRƯỚC khi sửa code, inspect `agent_core/planning/slot_validator.py`:**

- Nếu validator dùng **default an toàn** cho intent chưa có mapping (passthrough không đụng) →
  KHÔNG sửa, ghi xác nhận trong report.
- Nếu validator có **mapping required-slots theo IntentName** → thêm
  `IntentName.PROJECT_CONTEXT_QUERY: ("query",)`. Parser luôn gán `query=nguyên câu` nên đường
  bình thường KHÔNG bao giờ clarification; nhưng nếu một `ParsedIntent` được tạo thủ công với
  `query=None` → fail an toàn (clarification) thay vì tạo plan lỗi. Planner + tool đều coi
  `query` là required arg, nên khai báo required ở validator cho nhất quán.
- KHÔNG đổi behavior intent cũ.
- Nếu phải chạm → thêm `slot_validator.py` vào scope, ghi report.

**Test PHẢI chạy qua `RuleBasedPlanner.make_plan(state)` (full pipe), KHÔNG gọi trực tiếp
`intent_planner.make_plan(parsed)`** — để bắt cả tầng SlotValidator:

```python
state = AgentState(goal="Dự án đã chốt dùng cơ chế search nào cho MVP?")
plan = RuleBasedPlanner().make_plan(state)
assert [step.action for step in plan] == [ToolName.ANSWER_FROM_CONTEXT, ToolName.FINISH]
```

---

## 4. IntentPlanner — nhánh mới

Thêm vào `make_plan()` (vị trí: sau nhánh `WEB_SEARCH`, trước `return self._unknown_plan()`):

```python
if parsed.intent == IntentName.PROJECT_CONTEXT_QUERY:
    return self._project_context_query_plan(parsed)
```

```python
def _project_context_query_plan(self, parsed: ParsedIntent) -> list[Step]:
    return [
        Step(
            thought="Đọc project context từ ContextPack để trả lời",
            action=ToolName.ANSWER_FROM_CONTEXT,
            args={"query": parsed.query},
        ),
        Step(
            thought="Trả câu trả lời dựa trên project context",
            action=ToolName.FINISH,
            args={"answer": "$last.output.answer"},   # nested path — KHÔNG $last_text
        ),
    ]
```

> **Vì sao `$last.output.answer` chứ KHÔNG `$last_text`:** `AnswerFromContextOutput` có HAI
> field (`answer`, `used_item_count`). `$last_text` → `stringify_output()` flatten cả dataclass
> → `used_item_count` rò vào final_answer. `$last.output.answer` lấy đúng field user-facing.
> Kiến trúc đã có nested path (`$last.output.summary` ở read-note-then-summarize) → pattern này
> nhất quán, deterministic. Test 4 khóa: `assert "used_item_count" not in state.final_answer`.

> **Bẫy đã biết (§0):** if-chain không có exhaustiveness check. Nếu QUÊN nhánh này →
> `PROJECT_CONTEXT_QUERY` rơi `_unknown_plan()` IM LẶNG (đúng như `WEB_SEARCH_THEN_SAVE_NOTE`
> đang bị). Test §7.1 khóa chống bẫy này.

---

## 4b. Runtime — nối `ANSWER_FROM_CONTEXT` vào memory-action detection (BẮT BUỘC)

> **Vì sao đây là blocker:** P3 `_task_touches_memory` xác định task dùng memory bằng tập
> `_MEMORY_ACTIONS` (action trong plan). Plan của PROJECT_CONTEXT_QUERY là
> `[ANSWER_FROM_CONTEXT, FINISH]`. Nếu `ANSWER_FROM_CONTEXT` KHÔNG có trong `_MEMORY_ACTIONS`
> → `_task_touches_memory` trả False → degraded KHÔNG disclose, dù tool dùng ContextPack.
> Đây là lỗi behavior thật. P4 PHẢI nối tool mới vào tập này.

**Inspect `runtime_agent.py` SAU P3 và bảo đảm `RuntimeAgent._task_touches_memory()` THẤY
`ToolName.ANSWER_FROM_CONTEXT`.** KHÔNG giả định tên constant (P3 có thể đã drift — vd
`_MEMORY_PLAN_ACTIONS = _MEMORY_ACTIONS | {READ_NOTE}`):

- Nếu `_task_touches_memory` dùng `_MEMORY_ACTIONS` trực tiếp → thêm `ANSWER_FROM_CONTEXT` vào `_MEMORY_ACTIONS`.
- Nếu dùng `_MEMORY_PLAN_ACTIONS` (hoặc tên khác) → thêm vào **tập nguồn** sao cho tập cuối
  chứa `ANSWER_FROM_CONTEXT`. KHÔNG tạo constant song song / nguồn-sự-thật thứ hai.
- Điều cần bảo đảm là **hành vi**: plan chứa `ANSWER_FROM_CONTEXT` → `_task_touches_memory` trả True.
  Test §7.4/§7.5 (disclosure) bắt hành vi cuối; nhưng spec chỉ đúng code thật, không ép tên symbol.

```python
# Ví dụ NẾU constant là _MEMORY_ACTIONS (đối chiếu code thật trước):
_MEMORY_ACTIONS = {
    ToolName.READ_NOTE, ToolName.LIST_NOTES, ToolName.SEARCH_MEMORY, ToolName.SUMMARIZE_MEMORY,
    ToolName.WRITE_NOTE, ToolName.SAVE_FACT, ToolName.SAVE_PREFERENCE, ToolName.SAVE_DECISION,
    ToolName.ANSWER_FROM_CONTEXT,   # P4: project-context query phụ thuộc memory
}
```

> **KHÔNG chỉ dựa `context_consumed`:** project-query với pack RỖNG hoặc NHIỀU item →
> `context_consumed=False` nhưng task VẪN phụ thuộc memory (degraded vẫn ảnh hưởng: "không đủ
> context" có thể là do degraded che mất). Nên disclose dựa **action trong plan**, KHÔNG dựa
> `context_consumed`. (Có thể thêm `or state.context_consumed` cho consumer tương lai, nhưng
> KHÔNG được CHỈ dựa cờ đó — nhánh rỗng/nhiều-item cần disclose dù cờ False.)
> `_PERSIST_ACTIONS` (P3) KHÔNG đổi — `ANSWER_FROM_CONTEXT` read-only, không kỳ vọng persistence.

---

## 5. Tool `ANSWER_FROM_CONTEXT` — consumer thật (3 nhánh deterministic)

`AnswerFromContextOutput` dataclass — đặt trong **`agent_core/tools/schemas.py`** (cạnh
`ReadNoteOutput`/`FinishOutput`/`SummarizeOutput` — schemas.py là nơi chứa output contract,
builtin_tools.py chỉ chứa tool implementation; giữ boundary sạch):

```python
# trong agent_core/tools/schemas.py
@dataclass
class AnswerFromContextOutput:
    answer: str
    used_item_count: int = 0   # 0 hoặc 1 — trace số item thực dùng
```

`tool_answer_from_context` trong `builtin_tools.py` **import** Output từ schemas:

```python
from agent_core.tools.schemas import AnswerFromContextOutput   # cùng chỗ ReadNoteOutput, ...
# Lọc theo loại context dự án — KHÔNG relevance-match (local bỏ qua goal).
_PROJECT_CONTEXT_TYPES = (MemoryType.DECISION, MemoryType.PROJECT_CONTEXT)

def tool_answer_from_context(state: AgentState, query: str) -> ToolResult:
    tool_name = ToolName.ANSWER_FROM_CONTEXT.value
    pack = state.context_pack
    items = [i for i in pack.items if i.type in _PROJECT_CONTEXT_TYPES] if pack else []

    # 0 item phù hợp → không đủ context. context_consumed GIỮ False.
    if len(items) == 0:
        return ToolResult(
            success=True,
            output=AnswerFromContextOutput(
                answer="Tôi không có đủ project context để trả lời câu hỏi này.",
                used_item_count=0,
            ),
            tool_name=tool_name, kind=ToolResultKind.TEXT,
            metadata={"reason": "no_context", "matched": 0},
        )

    # >1 item phù hợp → KHÔNG tự chọn (không có relevance). context_consumed GIỮ False.
    if len(items) > 1:
        return ToolResult(
            success=True,
            output=AnswerFromContextOutput(
                answer="Project context chưa đủ rõ (có nhiều mục liên quan).",
                used_item_count=0,
            ),
            tool_name=tool_name, kind=ToolResultKind.TEXT,
            metadata={"reason": "ambiguous_context", "matched": len(items)},
        )

    # đúng 1 item → DÙNG content. Đánh dấu context_consumed=True (consumer thực sự đọc).
    item = items[0]
    state.context_consumed = True
    return ToolResult(
        success=True,
        output=AnswerFromContextOutput(
            answer=f"Theo project context đã lưu: {item.content}",
            used_item_count=1,
        ),
        tool_name=tool_name, kind=ToolResultKind.TEXT,
        metadata={"reason": "used_context", "matched": 1, "memory_id": item.metadata.get("memory_id")},
    )
```

> **Read-only + ngữ nghĩa `mutates_state` (làm rõ):** `mutates_state` phân loại **side-effect
> lên user/domain hoặc persistent mutation** (ghi store, file, DB). Cập nhật **runtime telemetry**
> như `state.context_consumed` KHÔNG biến tool thành mutating side-effect tool — nó là cờ trace
> trong state runtime, không phải side-effect bền vững. Vì vậy `mutates_state=False` đúng dù tool
> set `context_consumed=True`. Tool đọc `state.context_pack`, KHÔNG chạm store. Đăng ký
> `mutates_state=False`, `requires_approval=False`.
> (Đổi tên field `mutates_state` hoặc thiết kế generic state-patch contract = quá scope P4.)
> **`context_consumed` là tín hiệu THẬT:** chỉ True khi tool dùng đúng 1 item. 0 hoặc >1 →
> giữ False. Đây là cái P3 §4b chừa chỗ ("P4 thêm context_consumed, set True khi consumer
> thực sự đọc") — KHÔNG suy từ "pack có items".

**`agent_state.py`** thêm field (cạnh các field P3):

```python
context_consumed: bool = False   # P4: tool consumer set True khi THỰC SỰ dùng ≥1 ContextItem
```

---

## 6. Registry — đăng ký + guard completeness

Thêm entry vào dict `registry` trong `build_tool_registry`:

```python
ToolName.ANSWER_FROM_CONTEXT: spec(
    name=ToolName.ANSWER_FROM_CONTEXT, fn=tool_answer_from_context,
    description="Answer a project-context question by reading the ContextPack (read-only).",
    required_args={"query"}, allowed_args={"query"},
    mutates_state=False,
),
```

Thêm guard SAU vòng for `key == name` hiện có:

```python
registered = set(registry.keys())
declared = set(ToolName)
if registered != declared:
    raise ValueError(
        f"Registry mismatch — missing: {declared - registered}, extra: {registered - declared}"
    )
```

> **Vì sao guard ở `build_tool_registry`, KHÔNG ở executor:** executor chỉ biết cái nó được
> đưa; registry là nơi DUY NHẤT biết "phải có đủ bao nhiêu tool" (= `set(ToolName)`). Guard
> này bắt cả trường hợp tương lai thêm `ToolName` mà quên đăng ký.
> **Executor fail-loud (đã xác nhận từ code):** nếu tool thiếu, `executor.execute` trả
> `ToolResult(success=False, error="Unknown tool: ...", metadata={"error_type": "UnknownTool"})`
> (lưu ý: `error_type` nằm trong `metadata`, KHÔNG phải field top-level của `ToolResult` — theo
> shape thật từ `_fail`),
> `_execute_plan` → `state.fail()`. Không nuốt lỗi. Nhưng guard registry bắt sớm hơn (lúc build).

---

## 7. Test P4 (12 tests)

| #   | Test                                                           | Assert                                                                                                                                                                                                                                                                                                                                                                                            |
| --- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `test_project_context_query_plan`                              | chạy qua `RuleBasedPlanner().make_plan(state)` (FULL pipe parser→SlotValidator→planner, KHÔNG gọi trực tiếp intent_planner): goal "Dự án đã chốt dùng cơ chế search nào cho MVP?" → plan đúng `[ANSWER_FROM_CONTEXT, FINISH]`. KHÔNG rơi `_unknown_plan` (chống bẫy §4) và KHÔNG rơi clarification (bắt lỗi SlotValidator §3b).                                                                   |
| 2   | `test_answer_from_context_in_registry`                         | `ToolName.ANSWER_FROM_CONTEXT in build_tool_registry()`.                                                                                                                                                                                                                                                                                                                                          |
| 3   | `test_registry_completeness`                                   | `set(build_tool_registry()) == set(ToolName)`. Bắt enum member bị bỏ quên đăng ký.                                                                                                                                                                                                                                                                                                                |
| 4   | `test_answer_from_context_one_item` (E2E chính)                | seed 1 DECISION → `state.context_consumed is True`, `"FTS5" in state.final_answer`, `all(step.action != ToolName.READ_NOTE for step in state.plan)` (từ ContextPack, không qua read_note), `"used_item_count" not in state.final_answer` (nested path không rò telemetry), VÀ `"memory_degraded" in state.disclosure_reasons` + câu disclose trong final_answer (giữ behavior degraded P3 — §4b). |
| 5   | `test_answer_from_context_empty_pack`                          | pack rỗng → answer chứa "không có đủ project context", `context_consumed is False`, VÀ `"memory_degraded" in state.disclosure_reasons` (degraded vẫn disclose dù cờ False — §4b).                                                                                                                                                                                                                 |
| 6   | `test_answer_from_context_multiple_items`                      | seed 2 DECISION → answer chứa "chưa đủ rõ", `context_consumed is False`.                                                                                                                                                                                                                                                                                                                          |
| 7   | `test_calculate_does_not_consume_context`                      | goal "Tính (15+5)\*3" + store seeded 1 DECISION → plan KHÔNG chứa `ANSWER_FROM_CONTEXT`, `context_consumed is False`, answer = kết quả tính (không đổi do pack). Khóa: task không-project KHÔNG đọc pack.                                                                                                                                                                                         |
| 8   | `test_output_changes_with_pack` (DoD trực tiếp)                | CÙNG goal project-query: run với seeded pack → answer chứa "FTS5"; run với empty pack → answer báo thiếu context; `assert answer_seeded != answer_empty`. Bằng chứng rõ nhất "bỏ ContextPack thì output đổi".                                                                                                                                                                                     |
| 9   | `test_parser_negative_project_running`                         | "Dự án đang chạy bình thường" (không có cue hỏi-quyết-định) → `IntentName.UNKNOWN`, KHÔNG phải PROJECT_CONTEXT_QUERY.                                                                                                                                                                                                                                                                             |
| 10  | `test_parser_negative_tim_still_websearch`                     | "Tìm thông tin về dự án" → `IntentName.WEB_SEARCH` (nhánh `^Tìm` vẫn thắng, không bị PROJECT_CONTEXT_QUERY nuốt). Bảo vệ intent cũ khỏi regression.                                                                                                                                                                                                                                               |
| 11  | `test_answer_from_context_runs_under_read_only`                | `state.read_only=True` + ANSWER_FROM_CONTEXT + seed 1 item → tool VẪN chạy (read-only tool không bị chặn), `context_consumed is True`. Khẳng định mutates_state=False + telemetry update hợp lệ (blocker #3).                                                                                                                                                                                     |
| 12  | `test_answer_source_is_context_pack_not_store` (DoD MẠNH NHẤT) | `FakeMemoryClient` trả pack chứa item "FTS5"; `state.memory = FailOnReadStore()` (raise nếu bị đọc). Chạy agent → `"FTS5" in final_answer`, `context_consumed is True`, KHÔNG raise. Nếu tool chạm `state.memory` → test ĐỎ. **Đây là test DUY NHẤT phân biệt "đọc ContextPack" vs "đọc store" — vì QĐ-2 shared store khiến hai đường cho cùng data, các test khác KHÔNG phân biệt được.**        |

> **Vì sao test 12 là DoD mạnh nhất (đọc kỹ):** QĐ-2 chốt shared store —
> `LocalMemoryClient.store is state.memory`. Nên tool đọc `state.context_pack` và tool đọc
> thẳng `state.memory` cho **cùng dữ liệu** → test 4/8 (FTS5 in answer, context_consumed,
> no READ_NOTE) KHÔNG phân biệt được nguồn. `!= READ_NOTE` chỉ loại MỘT tool, không loại
> direct store access. Test 12 dùng pack-có-data + store-raise-nếu-đọc → CHỈ xanh nếu tool
> thực sự lấy từ `state.context_pack`. Thiếu test này, DoD "consumer đọc ContextPack" CHƯA
> được chứng minh bởi bất kỳ test nào.

**Test helper cần thêm (trong test file hoặc conftest):**

```python
class FailOnReadStore:
    """Sentinel store — raise nếu bị đọc. Chứng minh tool KHÔNG chạm state.memory."""
    def search(self, *a, **k):    raise AssertionError("tool must NOT read state.memory (use context_pack)")
    def get(self, *a, **k):       raise AssertionError("tool must NOT read state.memory")
    def read_note(self, *a, **k): raise AssertionError("tool must NOT read state.memory")
    def list_all(self, *a, **k):  raise AssertionError("tool must NOT read state.memory")
    # các method khác của MemoryStoreProtocol: raise tương tự nếu bị gọi

class FakeMemoryClient:
    """Trả ContextPack cố định, KHÔNG chạm store. Để test consumer đọc đúng pack."""
    def __init__(self, pack): self._pack = pack
    def retrieve_context_pack(self, goal, **k): return self._pack
    def write_memory_candidates(self, candidates, **k): return None  # no-op
```

> Inspect `MemoryStoreProtocol` thật để `FailOnReadStore` raise đúng mọi method đọc. Nếu
> protocol có method đọc khác (vd `query`, `fetch`) → thêm raise cho chúng.

Chạy `pytest -q` full. **Acceptance chính: 0 failed, 0 errors.** Baseline dự kiến 89 (P3) + 11
mới = ~100 passed — nhưng số test KHÔNG phải contract; thêm test hợp lệ không làm spec "fail".
Dán raw.

> **Test 4 là E2E consumer chính** — chứng minh consumer đọc ContextPack, đổi output, set
> `context_consumed`, giữ degraded disclosure, không qua read_note. **Test 8 là counterfactual
> proof** — cùng goal, output đổi theo pack (seeded vs empty), bằng chứng DoD trực tiếp nhất
> rằng "bỏ ContextPack thì output đổi". Nếu một trong hai bị làm yếu (vd bỏ assertion
> `!= READ_NOTE` ở test 4, hoặc bỏ `answer_seeded != answer_empty` ở test 8), P4 KHÔNG đạt DoD
> dù các test khác xanh.

---

## 8. Out-of-scope findings (ghi nợ, KHÔNG sửa trong P4)

- **`IntentName.WEB_SEARCH_THEN_SAVE_NOTE` rơi `_unknown_plan`:** enum có member nhưng
  `IntentPlanner.make_plan` không có nhánh → parser parse ra intent này (khi goal "Tìm X rồi
  lưu vào ghi chú Y") thì plan thành `_unknown_plan` thay vì web-search-rồi-save. Bug CÓ SẴN,
  không do P4. Đây là **functional/planning debt, KHÔNG phải security debt** → ghi trong P4
  report (Out-of-scope findings) + tạo issue/`TECH_DEBT.md` riêng. **KHÔNG đưa vào
  `SECURITY_DEBT.md`** (file đó chỉ quản security trigger). Trigger sửa: khi thêm exhaustiveness
  guard cho planner, hoặc khi cần luồng web-search-then-save thật.
- **`LIST_NOTES` / `SUMMARIZE_MEMORY` đăng ký nhưng không intent nào tạo plan dùng trực tiếp:**
  tool tồn tại, không có đường tới. Không phải bug — chỉ là tool chưa có intent. Ghi nhận.

---

## 9. Acceptance P4

- `pytest -q` → **0 failed, 0 errors** (acceptance chính); `import agent_core` OK. Baseline
  dự kiến ~100 passed nhưng số test KHÔNG phải contract.
- `python main.py` chạy 4 scenario (3 cũ + scenario 4 project-context query) — scenario 4 PHẢI
  cho thấy answer phản ánh decision đã seed + `context_consumed=True`.
- Plan của `PROJECT_CONTEXT_QUERY` = `[ANSWER_FROM_CONTEXT, FINISH]` (test 1).
- `set(build_tool_registry()) == set(ToolName)` (test 3).
- Chạm: 10 production file ở §0 + tối đa 1 file `slot_validator.py` NẾU preflight §3b yêu cầu
  - test files. KHÔNG sửa `LocalMemoryClient`/`InMemoryStore`/`MemoryStoreProtocol`/
    `FinalComposer` protocol.
- Out-of-scope findings (§8) ghi report, KHÔNG sửa.
- Branch `p4-local-demo`. Report §10. Dừng, chờ gate.

---

## 10. Report mẫu

```
## P4-local-demo report
- Branch: p4-local-demo
- Files: <10 production files + test files>
- What/Why: <2-4 câu>
- pytest: <raw — 0 failed, 0 errors (baseline ~100 passed, số không phải contract)>
- Plan PROJECT_CONTEXT_QUERY: <dán plan thực, phải [ANSWER_FROM_CONTEXT, FINISH]>
- context_consumed: one-item=True / empty=False / multi=False / calculate=False (dán 4 giá trị thực)
- python main.py scenario 4: <output — answer + context_consumed>
- E2E test 4: <dán assert kết quả: context_consumed, "FTS5" in answer, no READ_NOTE in plan>
- Out-of-scope findings: <WEB_SEARCH_THEN_SAVE_NOTE + bất kỳ phát hiện nào>
<<< git diff >>>
<<< pytest raw >>>
<<< main.py output >>>
```

Dừng sau P4. Chờ gate. KHÔNG sang P5 (remote memory).

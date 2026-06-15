# CLAUDE.md — TOMTIT-Agent

> File này là **guardrail bất biến** cho Claude Code, đọc **mỗi session**.
> Nó mô tả LUẬT của repo, KHÔNG mô tả roadmap. Việc-làm-gì-theo-thứ-tự nằm ở
> `BUILD_SPEC.md` và `MVP_MASTER_PLAN.md` — đọc cả hai trước khi sửa code.
>
> Nếu hướng dẫn trong session mâu thuẫn với file này → **dừng và hỏi**, đừng tự quyết.

---

## 0. TOMTIT-Agent là gì (một câu)

Local-first / **state-first** AI Agent runtime. `AgentState` là source of truth.
`ToolExecutor` là cổng thực thi tool **duy nhất**. Đây **không** phải chatbot. Runtime
truy cập durable memory qua **một `MemoryClientProtocol` duy nhất** với hai backend
hoán đổi được: remote (TOMTIT-Memory HTTP service) hoặc local fallback (`InMemoryStore`/
`FileStore` trong repo, chạy degraded mode). `AgentState` **không** phải là nơi chứa
durable memory. Chi tiết: `SPEC_memory_client.md`.

---

## 1. Kiến trúc bất biến — KHÔNG được phá

Các boundary này là hợp đồng. Vi phạm = từ chối / hỏi lại, không tự sửa.

| Thành phần                      | Trách nhiệm                                                                                             | Cấm                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ------------------------------- | ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AgentState`                    | Source of truth runtime của 1 task/session                                                              | Cấm biến thành durable-memory god object. Status chỉ đổi qua `fail()`/`complete()`.                                                                                                                                                                                                                                                                                                                                  |
| `IntentParser`                  | `goal: str → ParsedIntent`                                                                              | Cấm sinh plan. Cấm gọi tool.                                                                                                                                                                                                                                                                                                                                                                                         |
| `IntentPlanner`                 | `ParsedIntent → list[Step]`                                                                             | Cấm parse raw text. Cấm gọi tool.                                                                                                                                                                                                                                                                                                                                                                                    |
| `RuleBasedPlanner`              | Ghép parser → slot_validator → planner                                                                  | Cấm chứa logic parse hoặc execute.                                                                                                                                                                                                                                                                                                                                                                                   |
| `ToolExecutor.execute()`        | **Cổng thực thi duy nhất**: resolve → validate → policy → approval → execute → validate result → record | Cấm bất kỳ nơi nào khác gọi `tool.fn`.                                                                                                                                                                                                                                                                                                                                                                               |
| `PolicyEngine` / `ApprovalGate` | Chặn trước khi execute                                                                                  | Cấm bỏ qua. Mọi tool đi qua PolicyEngine + ApprovalGate trước execute. Tool `requires_approval=True` phải được user approve trước khi `tool.fn` chạy. `mutates_state=True` **KHÔNG** tự động = cần approval (nó dùng cho read_only/risk classification); mutating low-risk nội bộ như `write_note` có thể không cần approval ở MVP. Mọi tool external/irreversible/high-impact phải phân loại + yêu cầu approval rõ. |
| `MemoryStoreProtocol`           | Persistence-level (write/get/search/...)                                                                | Cấm chứa logic domain (chọn memory nào promote).                                                                                                                                                                                                                                                                                                                                                                     |
| `MemoryAgentProtocol`           | Domain-level (note/fact/preference/decision)                                                            | Cấm gọi vector/backend trực tiếp từ runtime.                                                                                                                                                                                                                                                                                                                                                                         |

**Quy tắc vàng:** _LLM hiểu ngôn ngữ; code kiểm soát hành vi._ Planner/runtime **không**
được tự diễn giải "ok", "làm tiếp đi", "cái này". Không execute tool khi intent không
rõ hoặc thiếu slot. Không đoán khi reference không resolve được.

**Luồng runtime mục tiêu** (đầy đủ ở `MVP_MASTER_PLAN.md §4`):

```
UserMessage → TurnClassifier → MemoryClient.retrieve_context_pack(goal, *explicit state-derived params*)
→ IntentParser → SlotValidator → IntentPlanner → PlanValidator → ToolExecutor
→ Observation/EventLog → FinalComposer → MemoryClient.write_memory_candidates(...)
→ AgentState.complete()
```

> **LUẬT [chốt]:** `MemoryClientProtocol` **KHÔNG nhận full `AgentState`**. Runtime tự
> rút `user_id`/`session_id`/`task_id`/`token_budget` từ state và truyền explicit params.
> Đây là source-of-truth, khớp `SPEC_memory_client.md §2`. (Mọi flow ghi `(goal, state)`
> là cũ/sai.)

---

## 2. Cấu trúc repo

```
agent_core/
  state/        agent_state.py (AgentState, Step), enums.py (StrEnum nguồn), observation.py
  runtime/      runtime_agent.py (loop), lifecycle.py (events)
  planning/     base.py (Protocol nền), intent_parser.py, intent_planner.py,
                rule_based_planner.py, hybrid_planner.py, slot_validator.py,
                clarification.py, extractors.py, intents.py
  tools/        executor.py (cổng), registry.py, base.py (ToolSpec), builtin_tools.py,
                arg_resolver.py, schemas.py
  safety/       policy.py (PolicyEngine), approval.py (ApprovalGate)
  memory/       base.py (protocols), in_memory_store.py, file_store.py,
                memory_agent.py, memory_records.py
  skills/       base.py + *_skill.py
  output/       final_composer.py
tests/          test_*.py — mỗi tầng một file
main.py         entrypoint demo
```

**Enum nguồn duy nhất:** `agent_core/state/enums.py` (dùng `StrEnum`). Cấm định nghĩa
trùng enum (`SourceType`, `ToolName`, ...) ở file khác.

---

## 3. Lệnh chạy & kiểm tra

```bash
# Chạy demo
python main.py

# Test toàn bộ (dán RAW output vào report, không tóm tắt)
pytest -q

# Test một tầng
pytest tests/test_runtime_agent.py -q

# Kiểm import nhanh (sanity trước khi làm gì)
python -c "import agent_core"

# Kiểm trùng class / enum trước khi merge
grep -rn "class IntentPlanner" agent_core/      # phải = 1
grep -rn "class SourceType"   agent_core/        # phải = 1 (ở enums.py)
```

> Nếu `import agent_core` raise → repo đang gãy (4 lỗi P0). Xem `BUILD_SPEC.md` STEP 1–5.
> KHÔNG làm việc khác cho đến khi import xanh.

---

## 4. Quy ước code

- Python 3.11+, `from __future__ import annotations` đầu mỗi file.
- Type hint đầy đủ. `dataclass` cho state/value object; **Pydantic** cho dữ liệu qua
  ranh giới (tool args schema, HTTP contract với Memory).
- `ToolResult` là kiểu trả về bắt buộc của mọi `tool.fn`. Executor sẽ reject kiểu khác.
- `ToolSpec` invariants tự kiểm trong `__post_init__` — không nới lỏng.
- Tên: `snake_case` hàm/biến, `PascalCase` class, `UPPER_SNAKE` hằng/enum value.
- Comment: chỉ giải thích chỗ **không hiển nhiên** (vì sao, không phải cái gì).
  Cấm comment beginner kiểu `# tăng i lên 1`.
- Tiếng Việt trong message/thought hướng tới user là OK (codebase đang dùng). Code,
  tên biến, docstring kỹ thuật → tiếng Anh.

---

## 5. Test discipline

- Mỗi hành vi mới **phải** có test. Ưu tiên: state transition → tool result →
  runtime loop → safety gate → memory behavior.
- **Cấm xóa/sửa test đang fail để suite xanh.** Test fail = tín hiệu. Sửa code,
  hoặc nếu test sai → ghi vào report và hỏi, đừng tự sửa test cho khớp code.
- Safety test là bắt buộc khi đụng tool/policy/approval: high-risk bị chặn,
  read-only chặn mutating tool, approval-required chặn khi chưa duyệt.

---

## 6. Ranh giới với Memory (quan trọng cho MVP)

- Agent truy cập memory qua **một `MemoryClientProtocol` duy nhất**, nhận `ContextPack`
  có cấu trúc. KHÔNG gọi vector DB / backend / store trực tiếp từ runtime.
- Có **hai backend hoán đổi được** sau cùng một protocol:
  - `RemoteMemoryClient` → TOMTIT-Memory HTTP service (durable, ngoài repo).
  - `LocalMemoryClient` → bọc `InMemoryStore`/`FileStore` trong repo (fallback nhẹ, **degraded mode**).
- Backend được **chốt lúc task khởi tạo** (binding-at-task-start). **Cấm đổi backend
  giữa run.** Remote chết giữa chừng → pause/fail an toàn, KHÔNG nhảy sang local.
- Cờ `memory_degraded` **chỉ leo lên, không tụt xuống** trong một run. Disclosure
  **deterministic**: policy set `disclosure_reasons`, helper `append_disclosures()` thêm
  fixed text khi reasons không rỗng. Policy quyết CÓ disclose + lý do; FinalComposer/model
  KHÔNG tự quyết, KHÔNG tự sinh disclosure (KHÔNG mở rộng FinalComposer protocol).
- `LocalMemoryClient` được coi là **degraded chỉ trong ngữ cảnh MVP-local** (backend
  fallback/demo, có thể không phản ánh state durable remote). Backend local durable
  tương lai có thể non-degraded — ngoài phạm vi MVP.
- Token counting **dùng chung cách đếm** với Memory, nếu không token budget vô nghĩa.
- Contract `ContextPack` + luật chi tiết: **`SPEC_memory_client.md`** và
  `MVP_MASTER_PLAN.md §3`. **Cấm đổi contract một phía** — đổi là đổi cả hai repo + version bump.

---

## 7. CẤM TUYỆT ĐỐI (cho giai đoạn MVP hiện tại)

Không được tự ý thêm, kể cả khi thấy "hợp lý":

- ❌ Multi-agent / A2A — single-agent runtime chưa đủ ổn.
- ❌ MCP — chỉ khi HTTP API + `MemoryClientProtocol` đã ổn định.
- ❌ LLM planner / LLM intent parser — rule/parser/planner boundary phải sạch trước.
  `LLMIntentParser` là post-MVP.
- ❌ Vector / RAG / embedding trong Agent — Memory service lo retrieval.
- ❌ Self-improvement / memory validator / conflict detector — cần log + eval + data thật trước.
- ❌ Coi `AgentState` là durable memory store — `AgentState` là runtime state của 1
  task. Durable memory đi qua `MemoryClientProtocol` (remote service hoặc local backing
  store), KHÔNG nhồi vào `AgentState`.
- ❌ Thêm dependency mới nếu spec không yêu cầu.
- ❌ Thêm abstraction "để sau này dùng" — chỉ build cái MVP cần.
- ❌ Đổi public contract (`AgentState`, `ToolSpec`, các Protocol) ngoài phạm vi step đang làm.
- ❌ DAG executor / `Step.depends_on` logic — runtime chạy tuyến tính, đừng giả vờ có graph.

Phát hiện thứ gì đó nên làm nhưng ngoài phạm vi → ghi vào mục **"Out-of-scope findings"**
trong report và **hỏi**. Không tự khởi động.

---

## 8. Quy trình mỗi step (tóm tắt — chi tiết ở `BUILD_SPEC.md §0`)

1. **Một step một lần.** Không nhảy bước.
2. Tạo branch theo tên chỉ định trong **active phase spec** (vd `p3-runtime-wiring`).
   Nếu spec không chỉ định → `step-N-description`.
3. Commit sạch trước khi báo cáo.
4. Nộp report: `git diff` + `pytest` raw output + what/why + out-of-scope + deviations.
5. **Chờ TranBac + architect duyệt.** KHÔNG tự merge `main`. KHÔNG làm step kế.

TranBac là architect / product owner / merge gate. Claude Code là executor. Claude Code
**không** ra quyết định product hoặc kiến trúc lớn mà không có spec tường minh.

---

## 9. Khi không chắc

Thứ tự ưu tiên tài liệu khi mâu thuẫn (cao → thấp):

1. `CLAUDE.md` (file này) — luật bất biến xuyên phase.
2. **Spec phase hiện tại** (vd `SPEC_P3_runtime_wiring.md`) — scope + implementation hiện tại.
3. `contracts.py` — runtime schema source of truth.
4. `SPEC_memory_client.md` — invariant xuyên phase (memory layer).
5. `MVP_MASTER_PLAN.md` — roadmap + DoD + CURRENT STATUS.
6. `CURRENT_PROJECT_STATUS.md` — trạng thái mô tả (nếu có).
7. `SECURITY_DEBT.md` — non-executable, ghi nợ.
8. `BUILD_SPEC.md` — **HISTORICAL, P0 only, KHÔNG thực thi.**
9. Hướng dẫn trong session.

Phase hiện tại do `MVP_MASTER_PLAN.md` (CURRENT STATUS) định nghĩa, KHÔNG do `BUILD_SPEC.md`.
Nếu session/file thấp chọi file cao → **dừng, nêu mâu thuẫn, hỏi.** Im lặng làm theo khi nó
phá guardrail là lỗi nghiêm trọng nhất.

```

```

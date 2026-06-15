# SPEC P3-runtime-wiring — nối `LocalMemoryClient` vào runtime

> **Phase:** P3 (sau P2 đã đóng). **Executor:** Claude Code. **Gate:** TranBac.
> **Nguồn:** file này + `SPEC_memory_client.md §5, §5b, §7b` + runtime thật đã đọc.
>
> **Mục tiêu P3:** runtime gọi `retrieve_context_pack` **trước plan**, `write_memory_candidates`
> **sau khi task xong** qua MỘT điểm finalize duy nhất, set `memory_degraded` + disclosure
> deterministic. KHÔNG HTTP, KHÔNG factory, KHÔNG remote. Backend = `LocalMemoryClient` (P2).

---

## 0. SCOPE FENCE

**Vào P3 (sửa/thêm):**

- `runtime_agent.py`: nhận `memory_client` (keyword-only), chèn retrieve trước plan, gộp
  complete về một `_finalize_run()` với idempotency guard, write+disclose trong finalize.
  **KHÔNG tạo/biết store.**
- `agent_state.py`: thêm field `context_pack`, `memory_degraded`, `memory_write_failed`,
  `disclosure_reasons`. **GIỮ `default_factory=InMemoryStore` trên `memory`** (bỏ sẽ phá call
  site `AgentState(goal=...)` cũ). Composition root CÓ memory chủ động truyền `shared_store`
  vào `AgentState(memory=shared_store)`. Bỏ default + gỡ field = sau P4.
- `final_composer.py`: KHÔNG mở rộng — disclosure dùng helper thuần `append_disclosures` (§3e).
- **`main.py` / composition root**: tạo `shared_store` → `LocalMemoryClient` → `RuntimeAgent`
  → `AgentState(memory=shared_store)` trong CÙNG lifecycle (QĐ-2 §3h). **Đây là điều kiện để
  shared-store hoạt động** — nếu không sửa bootstrap, store/client/state không cùng reference.
- `append_disclosures` helper: file mới nhỏ ở `output/` (hoặc cạnh finalize).
- test wiring.

**[deferred] — KHÔNG làm:**

- ❌ RemoteMemoryClient, HTTP, handshake, factory chọn backend (P6)
- ❌ Gỡ `AgentState.memory` field / migrate built-in tool (step riêng sau P4)
- ❌ TurnClassifier, event-log structured (post-MVP)
- ❌ `execution_degraded` + block side-effect (QĐ-4 §1: `memory_degraded` KHÔNG chặn tool;
  block-do-degraded thuộc `execution_degraded`, deferred tới khi có tool side-effect/production thật)

---

## 1. Các quyết định kiến trúc đã chốt (TranBac)

### QĐ-4: `memory_degraded` KHÔNG chặn tool — tách khỏi execution safety

> Mâu thuẫn đã sửa: `LocalMemoryClient` luôn `memory_degraded=True`; nếu degraded→deny
> side-effect thì `write_note` luôn bị chặn → MVP-demo compound không chạy. Tách hai nghĩa:
>
> - `memory_degraded` = context memory KHÔNG đầy đủ → **chỉ disclose, KHÔNG chặn tool.**
> - `execution_degraded` = không đủ điều kiện an toàn để side-effect → block. **[deferred]** P3 KHÔNG làm.
>
> P3: execution safety quyết định ĐỘC LẬP bởi `risk_level`/`mutates_state`/`requires_approval`/
> `read_only` sẵn có. `write_note`/`save_*` (mutating local) chạy bình thường. KHÔNG có
> luật `memory_degraded → deny` ở bất kỳ đâu trong P3. Chi tiết: `SPEC_memory_client §4d`.

### QĐ-1: MỘT điểm complete() + idempotency guard

Runtime hiện có **hai** đường complete: (a) finish-tool trong `_execute_plan` gọi
`state.complete()` ngay; (b) fallback `_complete_with_final_composer`. Write+disclose phải
xảy ra ở **cả hai**, sau compose, trước complete → gộp về một điểm.

- **finish-tool KHÔNG còn gọi `state.complete()` trực tiếp.** Nó chỉ ghi `last_result`
  - tín hiệu thoát loop. (Bỏ dòng `state.complete(stringify_output(result))` trong nhánh FINISH.)
- Cả hai đường (finish-tool thoát loop, fallback) đều đi qua **`_finalize_run(state)`** duy nhất:
  ```
  compose draft → write memory (sync best-effort) → append disclosure nếu cần → state.complete(final_answer)
  ```
- **Idempotency guard:** `_finalize_run` không được chạy hai lần cho một state. Guard bằng
  `if state.done: return` ở đầu, HOẶC một cờ `state._finalized`. Tránh double-write +
  double-complete. **Test bắt buộc** (xem §5).

### QĐ-2: shared store, **bootstrap/composition root** sở hữu (KHÔNG phải RuntimeAgent)

- **Bootstrap / composition root** (không phải RuntimeAgent) tạo **một** store, sở hữu nó.
- Store đó inject vào `LocalMemoryClient` **VÀ** truyền cùng reference vào `AgentState.memory`
  → built-in tool cũ (dùng `state.memory`) và client mới đọc/ghi **cùng một nguồn** → không split-brain.
- **`RuntimeAgent` KHÔNG tạo, KHÔNG biết `InMemoryStore`.** Nó chỉ nhận `memory_client` đã dựng sẵn.
- Runtime **mới** chỉ gọi `memory_client.*`. KHÔNG thêm code mới dùng `state.memory`.
- `AgentState.memory` giữ field, **deprecated-but-shared**. Gỡ hẳn + migrate tool = step riêng sau P4.

---

## 2. `AgentState` — thêm field (KHÔNG đổi field cũ)

```python
# Đầu file agent_state.py — tránh import cycle (ContextPack ↔ state nhánh):
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from agent_core.memory.contracts import ContextPack

# thêm vào dataclass AgentState:
context_pack: "ContextPack | None" = None   # first-class: ảnh hưởng plan/degraded/disclosure/replay
memory_degraded: bool = False               # đơn điệu — chỉ leo lên trong 1 run (§5). CHỈ disclose, KHÔNG chặn tool (QĐ-4)
memory_write_failed: bool = False           # §5b
disclosure_reasons: list[str] = field(default_factory=list)   # §7b
# execution_degraded: KHÔNG thêm ở P3 — chưa có consumer (contract thừa). Ghi design debt,
# thêm khi triển khai execution safety thật (SECURITY_DEBT.md).
```

> **QĐ-3 (TranBac):** `ContextPack` là **first-class runtime state** — nó ảnh hưởng planning,
> degraded mode, safety, disclosure, và **replay/audit**. KHÔNG phải business slot tạm. Đây
> là đổi public contract của `AgentState` **có chủ đích, trong phạm vi P3** (không vi phạm
> `CLAUDE.md §7` — đã hỏi + chốt). Default `None` → không vỡ call-site. `TYPE_CHECKING` +
> forward annotation chuỗi → tránh import cycle (đúng loại lỗi self-import STEP 2 đã sửa).
> `state.slots` tiếp tục CHỈ chứa business data / tool args derive từ context — KHÔNG chứa context_pack.

`fail()`/`complete()` giữ nguyên signature. KHÔNG đụng `memory: MemoryStoreProtocol` field
(chỉ thêm comment deprecated-but-shared theo QĐ-2).

> `disclosure_reasons` giá trị hợp lệ (list[str], MVP): `"memory_degraded"`, `"memory_write_failed"`.

---

## 3. `RuntimeAgent` — wiring

### 3a. `__init__` nhận `memory_client` (keyword-only, sau debug — giữ backward-compat)

```python
def __init__(
    self,
    planner, tools,
    executor=None, final_composer=None, lifecycle=None,
    debug=False,
    *,                                                   # keyword-only từ đây
    memory_client: MemoryClientProtocol | None = None,   # MỚI — sau debug, keyword-only
):
    ...
    self.memory_client = memory_client   # có thể None (no-op nếu thiếu)
```

> **Backward-compat (sửa theo TranBac):** `memory_client` đặt SAU `debug` và **keyword-only**
> (`*`) → mọi call site cũ dựng `RuntimeAgent(planner, tools, ...)` không vỡ. `build_test_agent()`
> hiện tại vẫn chạy. Chỉ caller mới truyền `memory_client=...` explicit.

> Nếu `memory_client is None`: retrieve/write thành no-op (agent vẫn chạy, không memory).
> Đây KHÔNG phải degraded-mode — chỉ là "không cấu hình memory". KHÔNG raise.

### 3b. `run()` — retrieve trước plan, fail sạch nếu retrieve lỗi

```python
def run(self, state: AgentState) -> AgentState:
    self._retrieve_memory(state)      # MỚI — trước plan
    if state.is_terminal():           # retrieve có thể state.fail → dừng TRƯỚC plan
        self._finalize_run(state)
        return state
    self._plan(state)
    if state.is_terminal():
        self._finalize_run(state)     # finalize cả khi plan fail (để disclose nếu cần)
        return state
    self._execute_plan(state)
    self._finalize_run(state)         # MỘT điểm finalize — thay _complete_with_final_composer
    return state
```

> **Retrieve failure (chốt theo TranBac):** nếu `retrieve_context_pack` raise → `state.fail(...)`
> NGAY, dừng TRƯỚC planning. Không plan với context nửa vời/thiếu. Với `LocalMemoryClient`
> in-memory retrieve gần như không fail, nhưng nguyên tắc đúng cho khi remote (P6) tham gia.

### 3c. `_retrieve_memory` (mới)

```python
def _retrieve_memory(self, state: AgentState) -> None:
    if self.memory_client is None:
        return
    try:
        pack = self.memory_client.retrieve_context_pack(
            state.goal,
            user_id=state.user_id,
            session_id=state.session_id,
            token_budget=...,     # hằng MVP, vd 1500
            max_items=...,        # vd 20
        )
    except Exception as exc:
        state.fail(f"memory retrieve failed: {exc}")   # fail TRƯỚC plan (§3b)
        return
    state.context_pack = pack             # first-class field (QĐ-3), KHÔNG slots
    if pack.degraded:
        state.memory_degraded = True      # đơn điệu: chỉ set True, không set lại False
```

> **Ranh giới consumer (chốt theo TranBac — tránh plumbing chết):** P3 **CHỈ chịu trách
> nhiệm transport** — retrieve và đặt `ContextPack` vào `state.context_pack`. P3 **KHÔNG
> tuyên bố** planner/parser/composer hiện tại đã _đọc_ pack — vì chưa có code chứng minh.
> `test_retrieve_called_before_plan` chỉ chứng minh THỨ TỰ gọi, KHÔNG chứng minh memory ảnh
> hưởng behavior. Đó là đúng phạm vi P3.
>
> **P4 BẮT BUỘC** có ít nhất một E2E test chứng minh **một consumer thật đọc `ContextPack`
> và làm THAY ĐỔI output/decision** (vd planner đọc một preference từ pack → đổi plan, hoặc
> composer chèn context vào answer). **Nếu P4 thiếu test này, MVP-memory CHƯA chứng minh được
> giá trị** — đây là DoD của P4, không phải P3.

### 3d. `_execute_plan` — finish-tool KHÔNG complete nữa

```python
# trong nhánh FINISH, ĐỔI:
if step.action == ToolName.FINISH:
    # KHÔNG gọi state.complete() ở đây nữa (QĐ-1).
    state.last_result = result   # đảm bảo last_result có để compose
    self.lifecycle.emit_event(state, "finish_reached", step_index=step_index)
    break   # thoát loop, finalize lo phần complete
```

### 3e. `_finalize_run` (mới — thay `_complete_with_final_composer`)

```python
def _finalize_run(self, state: AgentState) -> None:
    if state.done:           # idempotency guard (QĐ-1) — đã finalize/fail rồi → return
        return

    # 1. compose draft (CHƯA complete)
    draft = self.final_composer.compose(state)

    # 2. write memory best-effort, sync (§3f)
    self._write_memory(state)    # set memory_write_failed nếu lỗi

    # 3. disclosure deterministic (§7b) — policy set reasons, helper append câu
    self._apply_disclosure(state)
    draft = append_disclosures(draft, state.disclosure_reasons)   # helper, KHÔNG mở rộng FinalComposer

    # 4. state.complete() — TERMINAL STATE TRANSITION cuối (set status/done/final_answer)
    state.complete(draft)
    # run_completed — telemetry emit SAU transition (không phải state change)
    self.lifecycle.emit_event(state, "run_completed", metadata={"reason": "finalize"})
```

> **Disclosure helper (sửa theo TranBac):** KHÔNG thêm `compose_with_disclosure` vào
> `FinalComposer` Protocol (tránh phình interface + ép mọi composer implement). Dùng một
> **helper thuần** `append_disclosures(draft: str, reasons: list[str]) -> str` (đặt ở
> `output/` hoặc cạnh finalize). Deterministic: map mỗi reason → một câu cố định, nối vào
> draft. `reasons` rỗng → trả `draft` nguyên. Model KHÔNG quyết disclose; helper chỉ ráp câu
> từ reasons mà policy (§3g) đã set.

```python
# helper thuần, deterministic — KHÔNG phải method của FinalComposer
_DISCLOSURE_TEXT = {
    "memory_degraded": "(Lưu ý: đang chạy ở chế độ memory rút gọn — ngữ cảnh dự án dài hạn có thể thiếu.)",
    "memory_write_failed": "(Lưu ý: lưu memory không thành công cho lần này.)",
}
def append_disclosures(draft: str, reasons: list[str]) -> str:
    if not reasons:
        return draft
    lines = [_DISCLOSURE_TEXT[r] for r in reasons if r in _DISCLOSURE_TEXT]
    return draft + ("\n\n" + "\n".join(lines) if lines else "")
```

> **Guard ↔ fail-case (ghi rõ, KHÔNG phải bug):** retrieve-fail/plan-fail set `state.done=True`
> → guard `if state.done: return` khiến `_finalize_run` KHÔNG chạy disclosure cho fail-case.
> Đây là CHỦ ĐÍCH: `state.fail()` đã set `final_answer = error message`; thêm disclosure lên
> câu lỗi chỉ gây rối. Fail-case → error message là đủ.

> **`AgentState.errors` (xác nhận theo TranBac):** field `errors: list[str]` ĐÃ tồn tại trong
> `AgentState` (dùng bởi `fail()` + `_write_memory`). KHÔNG cần thêm. Nếu khi implement thấy
> thiếu → thêm `errors: list[str] = field(default_factory=list)` và báo trong report.

### 3f. `_write_memory` (mới — best-effort write KHI CÓ candidates, sync, KHÔNG thread-timeout)

> **Mục tiêu chính xác:** runtime thực hiện best-effort write **khi có memory candidates**.
> Ở MVP `_collect_candidates` trả `[]` → write là no-op trong production (test inject candidate
> qua monkeypatch/subclass — §4a). Đây KHÔNG phải "luôn write sau mỗi task".

```python
def _write_memory(self, state: AgentState) -> None:
    if self.memory_client is None:
        return
    candidates = self._collect_candidates(state)   # MVP: trả [] — xem §4a
    if not candidates:
        return
    try:
        # P3: gọi SYNC best-effort. KHÔNG dùng thread/concurrent.futures timeout giả cho
        # local write — LocalMemoryClient là in-memory, luôn nhanh; wrap timeout chỉ thêm
        # phức tạp không giải quyết gì. Hard timeout (httpx timeout) thuộc RemoteMemoryClient
        # ở P6 — nơi I/O mạng mới có thể treo thật. MEMORY_WRITE_TIMEOUT_SECONDS để dành cho P6.
        self.memory_client.write_memory_candidates(
            candidates,
            user_id=state.user_id, session_id=state.session_id, task_id=state.task_id,
        )
    except Exception as exc:
        state.memory_write_failed = True
        state.errors.append(f"memory write failed: {exc}")
        # log WARNING (bắt buộc §5b). KHÔNG raise, KHÔNG đổi status.
```

> **Lưu ý timeout (sửa theo TranBac):** P3 KHÔNG thực thi timeout cho local write — không
> thread giả. `MEMORY_WRITE_TIMEOUT_SECONDS` (đã định nghĩa P1) được `RemoteMemoryClient`
> dùng làm `httpx` timeout ở P6, nơi treo-do-mạng là rủi ro thật. Local in-memory không treo.

### 3g. `_apply_disclosure` (mới — deterministic)

```python
def _apply_disclosure(self, state: AgentState) -> None:
    if state.memory_degraded and self._task_touches_memory(state):
        if "memory_degraded" not in state.disclosure_reasons:
            state.disclosure_reasons.append("memory_degraded")
    if state.memory_write_failed and self._user_expected_persistence(state):
        if "memory_write_failed" not in state.disclosure_reasons:
            state.disclosure_reasons.append("memory_write_failed")
```

### 3h. Bootstrap = composition root (QĐ-2 — ai tạo & sở hữu store)

Một nơi duy nhất — **bootstrap / composition root** (`main.py` hoặc một `build_*` function) —
tạo store và nối store + client + runtime + state trong **cùng một lifecycle**. KHÔNG để
`RuntimeAgent` tự tạo store, KHÔNG để mỗi `AgentState` tạo store riêng.

MVP: KHÔNG cần abstraction mới. Wiring trực tiếp trong composition root, giữ reference store:

```python
# main.py (hoặc composition root) — wiring inline, store reference KHÔNG bị mất
shared_store = InMemoryStore()
memory_client = LocalMemoryClient(shared_store)
runtime = RuntimeAgent(planner=..., tools=..., memory_client=memory_client)

# state dùng CÙNG store reference (QĐ-2 transitional — built-in tool đọc đúng nguồn)
state = AgentState(goal=goal, memory=shared_store)
runtime.run(state)
```

> **KHÔNG viết `build_agent()` trả mỗi `runtime`** — sẽ mất reference `shared_store`, khiến
> `AgentState(memory=...)` bên ngoài không có store để truyền (đúng lỗi reviewer chỉ ra). Nếu
> muốn tách function, trả cả hai: `(runtime, shared_store)` hoặc dựng state bên trong cùng scope.

> **QĐ-2 — vì sao truyền store vào CẢ `state.memory`:** built-in tool cũ (`write_note` tool…)
> vẫn đọc/ghi qua `state.memory`. Nếu client bọc store A còn `state.memory` là store B (default)
> → **split-brain**: tool ghi B, client đọc A, không thấy nhau. Truyền cùng reference → một
> nguồn dữ liệu. `state.memory` là **deprecated-but-shared** (compatibility tạm), KHÔNG dead.
> Runtime MỚI chỉ gọi `memory_client.*`; KHÔNG thêm code mới dùng `state.memory`.

> **Caller cũ không có store:** `build_test_agent()` hiện tại (`RuntimeAgent(planner, tools=...)`,
> không `memory_client`) vẫn chạy — `memory_client=None` → retrieve/write no-op. Bootstrap mới
> ở trên là đường tạo agent CÓ memory; đường cũ giữ nguyên cho test/back-compat.

---

## 4. Điểm cần Claude Code chốt (chỉ §4a) + rule đã chốt (§4b)

> (§4b `_task_touches_memory` ĐÃ CHỐT rule bên dưới — KHÔNG còn để Claude Code đoán.)

### 4a. `_collect_candidates` — memory candidates đến từ đâu ở MVP?

`write_memory_candidates` cần `list[MemoryCandidate]`. Nguồn ở MVP-local: **TỐI THIỂU**.
Đề xuất: nếu plan có step ghi note (user yêu cầu "lưu vào ghi chú") → đã ghi qua tool rồi
(built-in write_note tool), KHÔNG cần tạo candidate trùng. MVP có thể trả `[]` (không tự
rút candidate) — write path tồn tại nhưng chưa có nguồn candidate tự động. **Đây là chủ đích:**
tự-rút-candidate (memory extraction) là post-MVP/self-improvement (CLAUDE.md §7 cấm sớm).

→ **MVP production: `_collect_candidates` LUÔN trả `[]`** — P3 chỉ "hỗ trợ write KHI có
candidates", chưa tự sinh candidate (auto-extraction = post-MVP, CLAUDE.md §7 cấm sớm).

> **Test seam (chốt — tránh Claude Code tự nghĩ cách):** vì production trả `[]`, các test
> write (`test_write_after_finish`, `test_write_failure_not_fatal`) phải **monkeypatch hoặc
> subclass** `_collect_candidates` để trả đúng MỘT `MemoryCandidate` cố định, rồi mới verify
> write xảy ra sau compose + write fail không làm task fail. KHÔNG thêm auto-extraction để
> "có candidate cho test chạy". Đây là cách test một code path tồn-tại-nhưng-chưa-có-nguồn.

### 4b. `_task_touches_memory` / `_user_expected_persistence` — RULE CHỐT (KHÔNG để Claude Code đoán)

> **Bug đã sửa (false disclosure):** rule trước có nhánh `or bool(context_pack.items)`. Nhưng
> `LocalMemoryClient` **luôn trả items** (top-k theo importance, bỏ qua goal — P2). Hệ quả:
> task "Tính 2+2" sau khi store có dữ liệu → pack có items → `touches_memory=True` → disclose
> "memory rút gọn" SAI, dù task tính toán KHÔNG dùng memory và KHÔNG consumer nào đọc pack.
> Đây là **false disclosure xảy ra gần như mọi task** sau khi store có data.
>
> **Sửa: P3 chỉ dựa PLAN.** Bỏ nhánh `context_pack.items`. Case recall-fail vẫn được giải vì
> `READ_NOTE`/`SEARCH_MEMORY` là memory action **trong plan** → task đọc-note recall rỗng vẫn
> `touches_memory=True` qua nhánh plan. KHÔNG cần nhánh items.

Rule deterministic (chốt — Claude Code implement đúng, KHÔNG đổi):

```python
_MEMORY_ACTIONS = {
    ToolName.READ_NOTE, ToolName.LIST_NOTES, ToolName.SEARCH_MEMORY, ToolName.SUMMARIZE_MEMORY,
    ToolName.WRITE_NOTE, ToolName.SAVE_FACT, ToolName.SAVE_PREFERENCE, ToolName.SAVE_DECISION,
}
_PERSIST_ACTIONS = {
    ToolName.WRITE_NOTE, ToolName.SAVE_FACT, ToolName.SAVE_PREFERENCE, ToolName.SAVE_DECISION,
}

def _task_touches_memory(state) -> bool:
    # P3: CHỈ dựa plan. KHÔNG suy ra "đã dùng context" từ pack có items
    # (LocalMemoryClient luôn trả items → false disclosure).
    return any(step.action in _MEMORY_ACTIONS for step in state.plan)

def _user_expected_persistence(state) -> bool:
    return any(step.action in _PERSIST_ACTIONS for step in state.plan)
```

> **P4 — khi có consumer thật:** thêm tín hiệu rõ ràng (KHÔNG suy từ pack có items):
>
> ```python
> context_consumed: bool = False   # consumer set True khi THỰC SỰ đọc context item
> # rồi: return any(... in _MEMORY_ACTIONS ...) or state.context_consumed
> ```
>
> Field này KHÔNG thêm ở P3 (chưa consumer) — thêm ở P4 khi consumer đánh dấu. Đây là cách
> đúng để biết "task có dùng context" thay vì đoán từ "pack có items".

> **Điểm mấu chốt:** task `READ_NOTE` recall rỗng VẪN disclose (qua nhánh plan); task `CALCULATE`
> thuần KHÔNG disclose (không memory action trong plan) — kể cả khi pack có items. Cả hai đúng.

> **Lưu ý:** kiểm `ToolName` thật có đủ các member này không; thiếu member nào → dùng tập con
> có thật + báo out-of-scope, KHÔNG tự thêm ToolName.

---

## 5. Test P3 — `tests/test_runtime_memory_wiring.py`

| Test                                               | Assert                                                                                                                                                                                                                                                               |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_retrieve_called_before_plan`                 | spy memory_client → `retrieve_context_pack` gọi TRƯỚC `planner.make_plan`                                                                                                                                                                                            |
| `test_degraded_pack_sets_state_flag`               | client trả `degraded=True` → `state.memory_degraded is True` sau run                                                                                                                                                                                                 |
| `test_degraded_monotonic`                          | inject degraded rồi non-degraded (nếu có thể) → flag vẫn True (chỉ leo lên)                                                                                                                                                                                          |
| `test_finalize_runs_once`                          | task qua FINISH tool → `_finalize_run` chạy đúng 1 lần (spy/counter), KHÔNG double-write, KHÔNG double-complete                                                                                                                                                      |
| `test_finish_tool_does_not_complete_directly`      | sau FINISH, `state.complete` chỉ được gọi trong finalize (không trong execute loop)                                                                                                                                                                                  |
| `test_write_after_finish`                          | task xong → `write_memory_candidates` gọi SAU compose, TRƯỚC complete                                                                                                                                                                                                |
| `test_write_failure_not_fatal`                     | client.write raise → `state.memory_write_failed is True`, `status == COMPLETED`, answer vẫn trả                                                                                                                                                                      |
| `test_disclosure_when_degraded_and_touches_memory` | degraded + plan dùng memory → `disclosure_reasons` chứa "memory_degraded", final answer có câu disclose                                                                                                                                                              |
| `test_no_disclosure_when_not_degraded`             | non-degraded → `disclosure_reasons == []`, answer KHÔNG có disclose                                                                                                                                                                                                  |
| `test_memory_client_none_no_crash`                 | `RuntimeAgent(memory_client=None)` → run OK, không retrieve/write, không raise                                                                                                                                                                                       |
| `test_shared_store_no_split_brain`                 | tool ghi qua state.memory + client đọc qua retrieve → thấy cùng dữ liệu (cùng store reference)                                                                                                                                                                       |
| `test_state_memory_is_shared_store`                | composition root truyền `shared_store` → `state.memory is shared_store` (cùng object, không phải default mới). Khẳng định QĐ-2 wiring đúng.                                                                                                                          |
| `test_context_pack_is_field_not_slots`             | sau retrieve → `state.context_pack` là `ContextPack` (không phải `state.slots["context_pack"]`); `"context_pack" not in state.slots`                                                                                                                                 |
| `test_no_import_cycle`                             | `import agent_core.state.agent_state` và `import agent_core.memory.contracts` cùng lúc → không raise (TYPE_CHECKING guard hoạt động)                                                                                                                                 |
| `test_mutating_tool_runs_under_memory_degraded`    | memory_degraded=True (local) + plan có write_note (mutating) → write_note CHẠY (không bị deny). Khẳng định QĐ-4: memory_degraded KHÔNG chặn tool. Đây là test bảo vệ MVP-demo compound.                                                                              |
| `test_retrieve_failure_fails_before_plan`          | memory_client.retrieve raise → `state.status == FAILED`, `planner.make_plan` KHÔNG được gọi (spy). Khẳng định: không plan với context lỗi (§3b).                                                                                                                     |
| `test_append_disclosures_helper`                   | `append_disclosures("ans", [])` == "ans"; `append_disclosures("ans", ["memory_degraded"])` chứa "ans" + câu disclose. Deterministic, KHÔNG phải method FinalComposer.                                                                                                |
| `test_disclose_on_recall_fail_empty_pack`          | degraded + plan có READ_NOTE/SEARCH_MEMORY + pack RỖNG (recall fail) → `disclosure_reasons` chứa "memory_degraded", answer disclose. Khẳng định §4b: memory-read task disclose KỂ CẢ khi pack rỗng (qua nhánh plan).                                                 |
| `test_no_false_disclosure_calculate_with_items`    | degraded + plan CALCULATE thuần (KHÔNG memory action) + pack CÓ items (store có data) → `disclosure_reasons == []`, answer KHÔNG disclose. Khẳng định bug false-disclosure đã đóng: task không-memory KHÔNG disclose dù pack có items. **Test quan trọng nhất §4b.** |

Chạy `pytest -q` full → 69 (P2) + 19 mới = **88 passed**. Dán raw.

> **Quan trọng nhất:** `test_finalize_runs_once` + `test_finish_tool_does_not_complete_directly`
> bảo vệ QĐ-1 (một completion authority). `test_shared_store_no_split_brain` bảo vệ QĐ-2.

---

## 6. Acceptance P3

- `python main.py` chạy lại 3 luồng cũ (web_search, calculate, compound) — vẫn đúng, giờ
  có retrieve trước plan + finalize. Dán output cả 3.
- `pytest -q` → 88 passed; `import agent_core` OK
- `state.context_pack` là field (QĐ-3); `import agent_core.memory.contracts` không gây cycle
- finish-tool KHÔNG còn gọi `state.complete` trực tiếp (grep xác nhận)
- **Global completion authority (QĐ-1):** `grep -Rns "state\.complete(" agent_core main.py`
  — runtime production chỉ có MỘT call site trong `_finalize_run()`, ngoài định nghĩa
  `AgentState.complete()` và test. Nhiều hơn một call site runtime = vi phạm QĐ-1.
- Chạm: `runtime_agent.py`, `agent_state.py`, `final_composer.py`/helper `append_disclosures`,
  `main.py` (bootstrap wiring) (+ test). KHÔNG sửa `MemoryStoreProtocol`/`InMemoryStore`/`LocalMemoryClient`.

---

## 7. Report mẫu

```
## P3-runtime-wiring report
- Branch: p3-runtime-wiring
- Files: <list>
- What/Why: <2-4 câu>
- pytest: <raw, 88 passed>
- Quyết định đã chốt: _collect_candidates trả [] (§4a)? xác nhận local write SYNC, KHÔNG hard-timeout (§3f)?
- python main.py: <output 3 luồng>
- Out-of-scope findings / Spec deviations: <...>
<<< git diff >>>
<<< pytest raw >>>
<<< main.py output >>>
```

Dừng sau P3. Chờ gate. KHÔNG sang P4 (demo).

# CURRENT_PROJECT_STATUS.md

> File này ghi trạng thái CLOSED/OPEN của từng phase MVP.
> Cập nhật sau mỗi gate review. **Không** dùng làm spec hay roadmap.

---

## Phase status

| Phase | Tên | Status | Tests lúc close | Branch | Ngày close |
|---|---|---|---|---|---|
| P0-recovery | Sửa 4 lỗi import P0 | **CLOSED** | 55 passed | merged to main | — |
| P1-contract | Pydantic contracts + MemoryClientProtocol | **CLOSED** | 60 passed | merged to main | — |
| P2-local-client | LocalMemoryClient + fix text="" | **CLOSED** | 69 passed | merged to main | — |
| **P3-runtime-wiring** | Wire memory client vào runtime loop | **CLOSED** | **89 passed** | merged to main | 2026-06-15 |
| **P4-local-demo** | E2E local demo — consumer thật đọc ContextPack | **CLOSED** | **101 passed** (merge) / **102 passed** (post-safety-fix) | merged to main | 2026-06-15 |
| P5-remote-memory | TOMTIT-Memory HTTP server | NOT STARTED | — | — | — |
| P6-remote-client | RemoteMemoryClient + factory | NOT STARTED | — | — | — |

---

## P3-runtime-wiring — ghi chú close

**89 passed** (tăng từ 69 của P2). Branch `p3-runtime-wiring` merged to `main`.

**Những gì P3 thêm:**
- `RuntimeAgent.memory_client` kwarg — None = no-op
- `_retrieve_memory()` — gọi trước plan, `state.fail()` nếu raise (fail-first)
- `_finalize_run()` — ONE completion authority (QĐ-1), idempotency guard `if state.done: return`
- `_write_memory()` — sync best-effort, không timeout (local)
- `_apply_disclosure()` + `append_disclosures()` — deterministic, plan-based
- `_MEMORY_PLAN_ACTIONS = _MEMORY_ACTIONS | {READ_NOTE}` — phân biệt write-persistence vs plan-touches-memory
- `build_local_agent()` — composition root, 1 store shared (QĐ-2)
- `AgentState`: 4 fields mới (`context_pack`, `memory_degraded`, `memory_write_failed`, `disclosure_reasons`)
- `tests/test_runtime_memory_wiring.py`: 20 tests

**Bug sửa trong P3:**
- `_task_touches_memory` ban đầu check `context_pack.items` — sai vì LocalMemoryClient trả full store bất kể goal → false disclosure cho Calculate + seeded store. Sửa thành plan-based check.

---

## P4-local-demo — ghi chú close

**101 passed** lúc merge (commit `2cdf005`). **102 passed** sau safety fix TD-4 (commit `3171f16`).
Branch `p4-local-demo` merged to `main` 2026-06-15. Gate: APPROVED by TranBac.

**Những gì P4 thêm:**
- `ToolName.ANSWER_FROM_CONTEXT` (member thứ 13) — đọc `state.context_pack`, không chạm `state.memory`
- `IntentName.PROJECT_CONTEXT_QUERY` — intent mới, parser + slot_validator + planner đầy đủ
- `tool_answer_from_context()` — 3 nhánh deterministic (0 / 1 / >1 items), `context_consumed=True` chỉ khi đúng 1 item
- Registry completeness guard: `set(registry.keys()) == set(ToolName)` — fails at build time
- `AgentState.context_consumed: bool = False` — P4 signal
- `_MEMORY_PLAN_ACTIONS` mở rộng: thêm `ANSWER_FROM_CONTEXT`
- `tests/test_p4_local_demo.py`: 12 tests (test 12 = FailOnReadStore DoD — `call_count == 0` trên 5/5 read methods)
- `main.py` scenario 4: seed DECISION → project-context query → FTS5 in answer

**DoD đạt:** Consumer thật đọc `ContextPack`, output thay đổi theo context (test 8 counterfactual).
**DoD chưa đạt:** Durable recall / save-then-recall / persistence qua restart / relevance retrieval.
**Trạng thái:** Feature development DỪNG để user validation. P5/P6 là lựa chọn sau validation.

---

## Safety fix post-P4 — TD-4

**102 passed** (commit `3171f16`). `PolicyEngine` `== RiskLevel.HIGH` → `in (RiskLevel.HIGH, RiskLevel.CRITICAL)`.
`CRITICAL` tool không bị deny trước fix — `fn` có thể chạy. Fix: 1-line patch + spy test (`call_count == 0`).

---

## Next step

Feature development DỪNG. Đem `python3.11 main.py` scenario 4 đi validate với user thật.
P5/P6 chỉ bắt đầu sau khi có kết quả validation. Xem `VALIDATION_PLAN.md`.

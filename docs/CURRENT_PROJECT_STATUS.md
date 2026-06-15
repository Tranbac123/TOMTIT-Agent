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
| P4-local-demo | E2E local demo — consumer thật đọc ContextPack | **NOT STARTED** | — | — | — |
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

## Next step

**P4-local-demo** — architect viết spec. Bắt buộc có ít nhất 1 E2E test chứng minh consumer thật đọc `context_pack` và thay đổi plan hoặc answer. P3 chỉ transport pack vào state — nếu P4 không có consumer thật, P3 là plumbing chết.

# REPORT_M7B_MILESTONE_CLOSEOUT

**Date:** 2026-06-22 UTC
**Repository:** TOMTIT-Agent
**main == origin/main:** `41c2d929d34afdaf132862d11c1406bf8dd04846`
**Verification policy:** `docs/standards/VERIFICATION_GATE.md`

---

## 0. Milestone verdict

```
M7-B: CLOSED ON MAIN
```

## 1. Baseline and final custody

- `main == origin/main == 41c2d929d34afdaf132862d11c1406bf8dd04846` (`feat(M7-B): implement restart recall`).
- M7-B spec-merge base (frozen spec landed on main): `af30d5741724fb57dd21f393ed194c7e791abd21`.
- Frozen spec `docs/specs/SPEC_M7B_RESTART_RECALL.md` SHA `d44fab5462c6e1c8a2e93f5cec050b873c410e820917a0d02fbf7f9a00ededb6` (388 lines, Version 1.0).
- Full regression on main: **586 passed**.

## 2. What M7-B now proves

TOMTIT-Agent can recall a previously confirmed project decision from TOMTIT-Memory in a fresh Agent session/process through the existing remote `retrieve_context_pack` path, with provenance preserved, and durable recall after a TOMTIT-Memory server restart using the same SQLite DB.

Concretely proven (verified implementation + real restart smoke):
- A fresh Agent session/process (new `session_id`, no in-memory carry) recalls a decision written by a prior session.
- Recall is scoped by `project_id` + `user_id`; a new `session_id` does not block recall.
- Provenance (`memory_id`, `evidence_ref`, `source_task_id`) is surfaced only when the ContextItem carries it (never fabricated).
- No-result and remote-failure produce safe deterministic messages with no raw backend text.
- Durability survives a TOMTIT-Memory server restart on the same SQLite DB.

## 3. What M7-B does not prove

```
M7-B does not implement project resume.
M7-B does not implement SF2 safety/trust boundary.
M7-B does not implement vector/semantic retrieval.
M7-B does not implement M8.
M7-B does not change Memory Contract v1.
M7-B does not modify TOMTIT-Memory code.
M7-B does not refactor planner/tools/skills.
M7-B does not prove general long-term memory.
```

## 4. User-facing capability

A user runs `/memory recall` (interactive prompt `Recall query: `, or inline `/memory recall <query>`). The Agent retrieves the matching confirmed decision from TOMTIT-Memory for the current `project_id` + application-owned `user_id`, and prints the decision content with its provenance. A blank query cancels with zero remote call; no match prints `No matching project decision found.`; a remote failure prints `Decision recall failed.` (no raw error). The command is intercepted before `handle_turn` and never enters the planner/tools/skills.

## 5. Technical implementation summary

Agent-side only, five files (`af30d57..41c2d92`, +759/-3):
- `agent_core/runtime/runtime_agent.py` — `run_memory_recall(...)` (isolated read-only path; reuses `retrieve_context_pack`; bounded same-tick FTS stabilization; sole completion authority) + `_format_recall_output`.
- `agent_core/runtime/session_runtime.py` — `run_memory_recall(...)` (fresh-session run with application-owned `user_id`; records a `TurnRecord`).
- `agent_core/cli.py` — `/memory recall` command (`handle_recall`, intercepted before `handle_turn`).
- `tests/test_cli.py` — recall command/interactive/inline cases.
- `tests/test_m7b_restart_recall.py` — NEW (recall behavior, identity isolation, provenance, no-fallback, stabilization).

Not changed: `main.py`, `agent_core/memory/client.py`, `agent_core/memory/remote_client.py`, Memory Contract v1 wire/fixtures, planner/tools/skills, M7-A path.

## 6. Evidence chain

```
M7-A confirmed write:
closed prior to M7-B

M7-B frozen spec:
af30d5741724fb57dd21f393ed194c7e791abd21
docs/specs/SPEC_M7B_RESTART_RECALL.md
SHA d44fab5462c6e1c8a2e93f5cec050b873c410e820917a0d02fbf7f9a00ededb6

M7-B implementation:
41c2d929d34afdaf132862d11c1406bf8dd04846
feat(M7-B): implement restart recall

M7-B merge/push:
main == origin/main == 41c2d929d34afdaf132862d11c1406bf8dd04846

TOMTIT-Memory smoke revision:
6e3f0cecf9a33e768166de7a64754f8cc5502927

Regression:
586 passed

Targeted:
116 passed

Real smoke:
save confirmed decision
fresh-session recall before restart
restart Memory server with same SQLite DB
fresh-session recall after restart
different project/user isolation
provenance preserved
```

Supporting canonical evidence on main:
- `docs/reports/REPORT_M7B_RESTART_RECALL_PREFLIGHT.md` (SHA `d167c0f2…`)
- `docs/reports/REPORT_M7B_SPEC_DRAFT_REVIEW_VERIFIED.md` (SHA `d83b0db2…`)

Local (untracked) workflow reports: `REPORT_M7B_IMPLEMENTATION_VERIFIED.md` (PASS), `REPORT_M7B_IMPLEMENTATION_VERIFICATION_REVIEW.md` (GO), `REPORT_M7B_IMPLEMENTATION_MERGE_PUSH_VERIFIED.md` (GO).

## 7. Test and smoke evidence

- Full regression: **586 passed** (552 pre-M7-B baseline + 34 new), no skips.
- Targeted (`test_m7b_restart_recall` + `test_cli` + `test_session_runtime` + `test_remote_memory_client`): **116 passed**.
- Real restart smoke (independent, pinned Memory `6e3f0ce`): SAVE (M7-A) → DB row with provenance → fresh-session recall before restart (hit + provenance) → server restart (PID changed, same SQLite DB) → fresh-session recall after restart (hit + provenance) → different-project and different-user both return no-result. TOMTIT-Memory repo unchanged.

## 8. Safety/scope boundaries

- Recall is read-only; intercepted before `handle_turn`; never enters planner/ToolExecutor/skills.
- Never reads `AgentState.confirmed_save_operation`; never uses a local fallback store.
- No Memory Contract v2; no new wire DTO/endpoint; no TOMTIT-Memory code change.
- Raw backend/transport text is never surfaced; no-result and failure are deterministic.

## 9. Operational notes

- Recall uses `RemoteMemoryClient.retrieve_context_pack` against TOMTIT-Memory `/v1/context/retrieve` (Memory Contract v1).
- Identity: `project_id` from client config; `user_id` application-owned (`--memory-user-id`, same source as M7-A).
- Bounded same-tick FTS stabilization is available (max 5 attempts, stop on first hit, never retries a remote failure) but was not needed in the smoke (fresh-process recall hit on the first attempt).
- The local (in-memory) default backend remains non-durable; durable recall requires the remote TOMTIT-Memory backend.
- The frozen spec header still reads `Implementation authorization: NOT AUTHORIZED`; that is a freeze-workflow artifact of the spec document — the implementation is merged and verified on `main`.

## 10. Residual risks

1. **LOW** — bounded stabilization unexercised in the smoke; it remains unit-tested.
2. **LOW** — recall surfaces all returned ContextItems (bounded by `max_items`/`token_budget`); correct for the single-decision claim; multi-item ranking is a non-goal.
3. **External** — sibling TOMTIT-Memory at `6e3f0ce`, working tree clean, untouched.

No HIGH/CRITICAL.

## 11. Recommended next phase decision

```
Next phase is not automatically authorized.

Recommended next decision:
choose between SF2 safety/trust boundary and M8 retrieval/hybrid/vector planning.

Do not start M8/vector until M7-B closeout is committed and reviewed.
```

## 12. Final status

```
M7-B: CLOSED ON MAIN
```

M7-B (Restart + Cross-Process Recall) is closed on `main`/`origin/main` at `41c2d92`, with verified implementation, full regression (586 passed), and a real restart smoke against pinned TOMTIT-Memory `6e3f0ce`. SF2 and M8/vector are NOT STARTED and require a separate architect instruction.

# SPEC_M7B_RESTART_RECALL

**Version:** `1.0`
**Status:** `FROZEN FOR IMPLEMENTATION AUTHORIZATION REVIEW — IMPLEMENTATION NOT AUTHORIZED`
**Authoritative baseline:** `main@3737ca4d58fd516633013efc05d30106f0a1493a`
**Depends on:** `M7-A confirmed-decision write @ 3737ca4d58fd516633013efc05d30106f0a1493a`
**Preflight evidence:** `docs/reports/REPORT_M7B_RESTART_RECALL_PREFLIGHT.md`
**Preflight artifact SHA-256:** `d167c0f2e23a047bf3a8182fb713a74054011a9ec0d1671690ab856df65380fe`
**Preflight artifact lines:** `194`
**Preflight source verdict:** `M7-B RESTART RECALL PREFLIGHT: GO — READY FOR M7-B SPEC DRAFT`
**TOMTIT-Memory evidence revision:** `d4d879d29a9fe5d10bae128b2675ae256354ca87`
**Spec draft review evidence:** `docs/reports/REPORT_M7B_SPEC_DRAFT_REVIEW_VERIFIED.md`
**Spec draft review artifact SHA-256:** `d83b0db2d2e9c2b1998b3fa6c68726ee470e8335f5b18843b58861e9235a069a`
**Spec draft review artifact line count:** `165`
**Freeze authorization:** `SPEC ONLY — IMPLEMENTATION NOT AUTHORIZED`
**Implementation authorization:** `NOT AUTHORIZED`

---

# 0. Status and authorization

This document is a **draft specification** for M7-B (Restart + Cross-Process Recall). While its status remains `DRAFT FOR ARCHITECT REVIEW — IMPLEMENTATION NOT AUTHORIZED`, it authorizes nothing. Implementation may begin only after: (1) architect review and acceptance of every §14 acceptance criterion and §15 stop condition; (2) the spec is frozen at a committed revision with a recorded SHA-256; (3) a separate implementation instruction cites the frozen revision and the preflight evidence; (4) the implementation candidate later passes `docs/standards/VERIFICATION_GATE.md`.

Normative precedence for M7-B: accepted Product Spec v0.3 → accepted SPEC_M7B → `VERIFICATION_GATE.md` → frozen verification evidence → current implementation → Architecture v1.0 explanatory text.

This document does not authorize M7-A changes, SF2, LLM activation, MCP, A2A, automatic extraction, vector/semantic recall, project resume, or any TOMTIT-Memory change.

---

# 1. Problem statement

- M7-A proved confirmed **remote write**: one explicitly user-confirmed decision is written to TOMTIT-Memory with deterministic provenance and required-write failure semantics.
- M7-A did **not** prove recall. Same-process read-after-write is insufficient.
- M7-B must prove **fresh-session / fresh-process remote recall**: a new Agent runtime, holding no in-memory state from the writing session, retrieves the previously saved decision from TOMTIT-Memory as the durable source of truth, with provenance preserved.
- Cross-process recall must use TOMTIT-Memory; it must not use any local fallback store.

---

# 2. M7-B product claim

Allowed claim (target of this spec):

> TOMTIT-Agent can recall a previously confirmed project decision from TOMTIT-Memory in a fresh Agent session/process, using the existing remote context retrieval path, with provenance preserved.

Optional stronger claim (only as the §13 real-restart smoke acceptance target):

> The decision remains recallable after the TOMTIT-Memory server restarts using the same durable SQLite store.

---

# 3. M7-B non-goals

M7-B must not add or enable:

- general long-term memory or "TOMTIT remembers everything";
- automatic / autonomous memory extraction or LLM-based memory selection;
- whole-project resume;
- prompt-injection-safe recall (SF2);
- semantic / vector / embedding recall (lexical FTS context is sufficient);
- multi-agent / A2A recall, MCP;
- multi-decision batch recall semantics beyond returning matched items;
- Memory Contract v2, new wire DTOs, or a new TOMTIT-Memory endpoint;
- any TOMTIT-Memory code change;
- planner / skills / tools refactor;
- changes to the M7-A confirmed-write path (unless a bug blocks recall);
- dependency or `.gitignore` changes.

---

# 4. Evidence baseline

- Baseline: `main@3737ca4d58fd516633013efc05d30106f0a1493a`; regression `552 passed`.
- M7-A frozen spec `docs/specs/SPEC_M7A_CONFIRMED_DECISION_WRITE.md` v1.3, SHA `7e9ba4de5156fb7423f04dc1c68c8e347ebc55861ea1138192ac2f3bdc45b79f`, 1924 lines.
- M7-A inventory `docs/reports/REPORT_M7A_CONFIRMED_DECISION_WRITE_INVENTORY_VERIFIED.md`, SHA `4c9d5e044ac7955f00337d7c5058e1f98ee9a7d3da19ac3f2a4cd2d1468f16ec`, commit `dd7bfcd41c1058407135458b174202586dd30eb5`.
- M7-B preflight `docs/reports/REPORT_M7B_RESTART_RECALL_PREFLIGHT.md`, SHA `d167c0f2e23a047bf3a8182fb713a74054011a9ec0d1671690ab856df65380fe`, 194 lines, verdict GO.
- TOMTIT-Memory evidence revision `d4d879d29a9fe5d10bae128b2675ae256354ca87`.

---

# 5. Existing architecture inventory

The following are recorded from the preflight/source [VERIFIED_FROM_CODE / VERIFIED_FROM_PREFLIGHT]:

1. `RemoteMemoryClient.retrieve_context_pack(...)` exists and calls TOMTIT-Memory `POST /v1/context/retrieve`.
2. The retrieved `ContextPack` is assigned to `AgentState.context_pack` by `RuntimeAgent._retrieve_memory`.
3. `ToolName.ANSWER_FROM_CONTEXT` (`tool_answer_from_context`) consumes `state.context_pack`.
4. Remote mode does **not** disable `answer_from_context` (it is in `CONTEXT_CONSUMER_TOOLS`, not in `LOCAL_DURABLE_TOOLS`).
5. TOMTIT-Memory scopes retrieval by `project_id` + `user_id` (+ optional `type_filter`), **not** by `session_id`.
6. `ContextItem` carries `memory_id`, `evidence_ref`, and `source_task_id` (provenance).
7. TOMTIT-Memory uses a durable file-backed SQLite store that survives a server restart with the same DB path.
8. **No Memory Contract v2 is required.**
9. **No TOMTIT-Memory code change is required.**

Preflight discovery smoke (real server `d4d879d`) demonstrated: write (M7-A) → fresh-client `retrieve_context_pack` returns the decision with provenance (`degraded=False`) → still returned after a Memory server restart with the same SQLite DB → different project returns zero. These are corroborating evidence, not new contracts.

---

# 6. M7-B target behavior

```text
Session/process A:
  user invokes /memory save-decision → M7-A confirmed write → TOMTIT-Memory persists the decision

Boundary:
  Agent process/session A state is discarded (fresh process/session, no in-memory carry)
  optionally the TOMTIT-Memory server is restarted with the same durable SQLite DB

Session/process B:
  user invokes /memory recall (with a query)
  Agent calls RemoteMemoryClient.retrieve_context_pack(query, user_id=…, session_id=<new>)
  TOMTIT-Memory returns a ContextPack scoped by project_id + user_id
  Agent surfaces the matched decision content + provenance
```

Minimum proof: a fresh Agent session/process retrieves the saved decision via the remote retrieve path. The spec must not silently weaken this to same-process read-after-write.

---

# 7. Recall identity boundary

- Recall is scoped by `project_id` (RemoteMemoryClient configuration) + `user_id` (application-owned, same source as M7-A: `--memory-user-id`).
- A new `session_id` must **not** block recall (retrieval is not session-scoped).
- Recall must **not** require or read `AgentState.confirmed_save_operation` (that is the M7-A write run-input only).
- Required isolation:
  - same `project_id` + same `user_id` → recall allowed;
  - same `project_id` + different `user_id` → no recall;
  - different `project_id` + same `user_id` → no recall;
  - different `project_id` + different `user_id` → no recall.

---

# 8. Recall source/provenance contract

Recall output is built only from `ContextPack`/`ContextItem` fields returned by TOMTIT-Memory. For a positive recall the Agent surfaces:

- decision content;
- `memory_id` (if presenting an identifier is safe);
- provenance from `evidence_ref` and/or `source_task_id` when present.

Rules:
- The Agent must not fabricate provenance; it surfaces only what the ContextItem carries.
- The Agent must not claim project resume or general memory.
- Raw backend error text must never be shown to the user.
- No-result and remote-failure produce safe deterministic messages (§10 / §5.6 below).

---

# 9. Same-tick FTS visibility nuance

The preflight observed exactly one **immediate same-tick** `retrieve_context_pack` call (issued microseconds after the write, in the same script) returning 0 results, while a subsequent fresh-client retrieval and all direct queries returned the saved decision with provenance. Interpretation: likely FTS index commit/visibility timing within a single rapid script, not a capability gap.

M7-B must therefore:
- prove recall across a **fresh session/process boundary** (not same-tick read-after-write);
- if a stabilization wait is needed for recall verification/orchestration, use a **narrow, bounded, documented** strategy — **not** a generic retry controller or circuit breaker.

---

# 10. Robust recall orchestration

Recommended bounded stabilization (only if needed for recall verification/orchestration):

```text
max 5 attempts
100–250 ms delay between attempts
stop immediately on the first valid context hit
fail loudly (safe message) if still missing after the bound
```

This bound is a recall-verification/orchestration detail, not a product feature; it must be documented where used and must not become a general retry/backoff/circuit-breaker subsystem. It must never silently convert a genuine no-result or remote failure into a false positive.

---

# 11. Required Agent-side implementation scope

Narrow, Agent-side only:
- Add a CLI command `/memory recall` (read-only; intercepted before `handle_turn`; never enters the planner).
- Add a `SessionRuntime` recall method that uses the existing `RemoteMemoryClient.retrieve_context_pack` with the application-owned `user_id` and a (new) `session_id`.
- Reuse existing `ContextPack`/`ContextItem`; do not add wire DTOs.
- Use the same `project_id`/`user_id` identity boundary as M7-A.
- Surface safe recall output with provenance (§8).
- Must not use `AgentState.confirmed_save_operation`; must not use any local fallback; must not add Memory Contract v2; must not change TOMTIT-Memory.

## 11.1 Command shape (primary)

```text
/memory recall
→ prompt: "Recall query: "
→ read one nonblank query line
→ run recall
→ print result(s) or safe no-result/failure message
```

Chosen for consistency with the M7-A interactive `/memory save-decision` style. `/memory recall <query>` inline form may be supported as a convenience but the interactive prompt is the documented primary shape.

## 11.2 Recall output contract

- Positive: show decision content; `memory_id` if safe; provenance (`evidence_ref`/`source_task_id`) if present; never fabricate provenance; never claim project resume.
- No result: `No matching project decision found.`
- Remote failure: `Decision recall failed.`
- No raw backend/transport/stack text in user output.

---

# 12. Required tests

Test catalogue (continuous numbering, no duplicates):

1. `/memory recall` command is recognized and intercepted before `handle_turn`.
2. interactive recall prompts for a query and reads one nonblank line.
3. blank recall query cancels safely with zero remote call.
4. positive recall maps a remote `ContextPack` to user output.
5. positive recall surfaces provenance (`evidence_ref`/`source_task_id`/`memory_id`).
6. no-result returns the safe deterministic `No matching project decision found.`.
7. remote-unavailable recall returns the safe `Decision recall failed.` (no raw error).
8. recall uses `RemoteMemoryClient.retrieve_context_pack` (not a new wire call).
9. recall passes the application-owned `user_id`.
10. recall passes a session_id and does not require it to match the write session.
11. same `project_id` + same `user_id` recalls the saved decision.
12. different `project_id` does not recall (isolation).
13. different `user_id` does not recall (isolation).
14. recall does not read `AgentState.confirmed_save_operation`.
15. recall does not use `LocalMemoryClient`/local fallback.
16. fresh `SessionRuntime`/process (new session_id) recalls a decision written by a prior session.
17. recall does not invoke the planner / ToolExecutor / skills.
18. bounded stabilization (if implemented) stops on first hit and is capped.
19. bounded stabilization never converts a true no-result/failure into a false positive.
20. recall output contains no raw backend exception text.
21. Memory Contract v1 wire DTOs/fixtures unchanged (fingerprint).
22. M7-A confirmed-write path unchanged (fingerprint / existing tests still pass).
23. real restart smoke: write → restart TOMTIT-Memory (same SQLite DB) → fresh Agent session recalls with provenance.
24. full regression passes (existing + new).

| Category | Type | Real TOMTIT-Memory? | Owner file | Blocking? |
|---|---|---|---|---|
| command parsing / interactive (1–3) | unit | no | tests/test_cli.py | yes |
| positive/no-result/failure recall (4–7,20) | unit | no (mock transport) | tests/test_m7b_restart_recall.py | yes |
| retrieve path + identity (8–13) | unit/integration | mock/real | tests/test_m7b_restart_recall.py | yes |
| isolation from write run-input/local (14–15) | unit | no | tests/test_m7b_restart_recall.py | yes |
| fresh-session recall (16) | integration | mock/real | tests/test_m7b_restart_recall.py | yes |
| path isolation (17) | unit | no | tests/test_m7b_restart_recall.py | yes |
| stabilization bound (18–19) | unit | no | tests/test_m7b_restart_recall.py | yes |
| contract/M7-A fingerprints (21–22) | unit | no | test_remote_memory_client.py / existing | yes |
| restart smoke (23) | smoke | **yes** | manual/smoke harness | yes (acceptance) |
| full regression (24) | regression | no | full suite | yes |

---

# 13. Real restart smoke requirement

Acceptance requires one real smoke against a TOMTIT-Memory server at the evidence revision (or a later compatible one, explicitly recorded), using a disposable `/tmp` SQLite DB and disposable identities:

```text
1. Session A: /memory save-decision (M7-A) → decision written.
2. Restart the TOMTIT-Memory server with the SAME SQLite DB.
3. Fresh Agent session B (same project_id/user_id, new session_id): /memory recall <query>.
4. Recall returns the saved decision with provenance.
5. Different project_id/user_id returns no result.
```

No code edits to either repo during the smoke; server/venv/DB under `/tmp`.

---

# 14. Acceptance criteria

```text
AC-M7B-01 main baseline and M7-A custody verified
AC-M7B-02 M7-A confirmed decision save path remains unchanged
AC-M7B-03 /memory recall command exists
AC-M7B-04 recall uses existing remote retrieve_context_pack path
AC-M7B-05 fresh Agent session/process can recall saved decision
AC-M7B-06 recall works with same project_id/user_id and new session_id
AC-M7B-07 different project_id does not recall
AC-M7B-08 different user_id does not recall
AC-M7B-09 provenance/evidence_ref/source_task_id is surfaced or preserved
AC-M7B-10 no-result behavior is safe and deterministic
AC-M7B-11 remote unavailable during recall fails safely
AC-M7B-12 no local fallback
AC-M7B-13 recall does not depend on AgentState.confirmed_save_operation
AC-M7B-14 no Memory Contract v2 / no wire changes
AC-M7B-15 no TOMTIT-Memory code changes
AC-M7B-16 no planner/skills/tools refactor
AC-M7B-17 same-tick FTS timing nuance handled by bounded documented strategy
AC-M7B-18 real restart smoke passes with TOMTIT-Memory same SQLite DB
AC-M7B-19 full regression passes
AC-M7B-20 forbidden-path audit zero
```

All AC must be PASS for M7-B closure. Each AC must map to at least one §12 test or one structural/source inspection.

---

# 15. Stop conditions

Implementation must STOP and request architect review if any occurs:

1. `RemoteMemoryClient.retrieve_context_pack` is unavailable or insufficient.
2. TOMTIT-Memory `/v1/context/retrieve` is unavailable.
3. recall requires Memory Contract v2.
4. recall requires a TOMTIT-Memory code change.
5. recall requires a local fallback.
6. the project_id/user_id identity boundary cannot be proven.
7. provenance cannot be surfaced/preserved from `ContextItem`.
8. same-tick FTS visibility cannot be bounded robustly.
9. implementation requires a planner / tool / skill refactor.
10. implementation requires a `docs/standards/**` or `.gitignore` change.
11. the real restart smoke cannot be run.
12. recall would require reading `AgentState.confirmed_save_operation`.
13. recall would expose raw backend error text to the user.
14. scope would expand toward project resume / general long-term memory.

---

# 16. Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| FTS visibility timing (same-tick) | LOW | prove across fresh session/process; bounded documented stabilization only if needed (§10) |
| remote retrieval relevance/scoring | MEDIUM | spec a deterministic recall query; tests assert the saved decision is returned for a representative query |
| identity scoping (project_id/user_id) | LOW | explicit isolation tests (§12 11–13) |
| session_id not in retrieval scope | LOW | documented; new session must not block recall (§7) |
| provenance display vs privacy | MEDIUM | surface only ContextItem-provided safe fields; no fabrication |
| context pack truncation | MEDIUM | use token_budget/max_items consciously; recall test uses bounded query |
| no-result false negative | MEDIUM | safe deterministic message; stabilization never masks true no-result |
| Memory server restart fixture complexity | MEDIUM | one disposable `/tmp` smoke; not part of unit suite |
| over-expanding into project resume | HIGH | hard non-goals (§3) + stop condition #14 |
| accidental local-store use on recall | LOW | remote-only client; no-fallback test (§12 15) |
| accidental planner/tool route | LOW | command intercepted before handle_turn; isolation test (§12 17) |

No CRITICAL risk. The single HIGH (scope creep to project resume) is mitigated by explicit non-goals and a stop condition.

---

# 17. File manifest

## 17.1 Likely modified production files

| Path | Current role | M7-B action likely | Risk |
|---|---|---|---|
| `agent_core/runtime/session_runtime.py` | session orchestration | ADD recall method over `retrieve_context_pack` | LOW |
| `agent_core/cli.py` | meta-commands | ADD `/memory recall` (read-only, pre-planner) | LOW |
| `agent_core/runtime/runtime_agent.py` | run paths | thin recall helper or reuse `_retrieve_memory`; only if needed | MEDIUM |
| `main.py` | composition | only if a CLI flag/wiring gap exists | LOW |
| `agent_core/memory/client.py` | protocol | only if an interface gap exists (likely none) | LOW |
| `agent_core/memory/remote_client.py` | retrieve mapping | only if a retrieval-result mapping gap exists | LOW |

## 17.2 Likely tests

`tests/test_m7b_restart_recall.py` (NEW); `tests/test_session_runtime.py`, `tests/test_cli.py` (MODIFY); `tests/test_remote_memory_client.py` (MODIFY only if retrieval behavior needs assertion).

## 17.3 Forbidden unless separately approved

`agent_core/confirmation/**`, `agent_core/tools/**`, `agent_core/skills/**`, `agent_core/planning/**`, `agent_core/memory/wire/**`, `tests/fixtures/memory_contract_v1/**`, `docs/standards/**`, `docs/goal_product/**`, `docs/ARCHITECTURE.md`, `.gitignore`, `TOMTIT-Memory/**`.

---

# 18. Implementation order

```text
B0 custody + preflight evidence verification
B1 recall contract/spec constants if needed
B2 RemoteMemoryClient retrieval mapping — verify only (likely no change)
B3 RuntimeAgent recall/context path — only if needed, transport-neutral, no best-effort write reuse
B4 SessionRuntime recall method
B5 CLI /memory recall command
B6 unit/integration tests
B7 real restart smoke with TOMTIT-Memory (same SQLite DB)
B8 verification + merge gates
```

No phase may be implemented in this task. No later phase may weaken an earlier contract to pass tests.

---

# 19. Required verification report

The implementation candidate (future, separate instruction) must be accompanied by a read-only verification report mapping every §14 AC and §12 test to source/test evidence, plus a real §13 restart smoke result, before any merge review — consistent with the M7-A flow (`VERIFICATION_GATE.md`).

---

# 20. Explicit non-authorization statement

```text
SPEC WRITTEN
IMPLEMENTATION NOT AUTHORIZED
```

This draft does not authorize: M7-B implementation, an implementation branch, code/test edits, TOMTIT-Memory changes, Memory Contract changes, merge to main, push, or SF2. The next workflow step is architect spec review → (optional patch) → frozen spec → separate implementation instruction.

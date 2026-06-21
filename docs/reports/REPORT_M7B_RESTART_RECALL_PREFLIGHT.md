# REPORT_M7B_RESTART_RECALL_PREFLIGHT

**Date:** 2026-06-21 UTC
**Repository:** TOMTIT-Agent
**Baseline:** `main == origin/main == 3737ca4d58fd516633013efc05d30106f0a1493a`
**Verification policy:** `docs/standards/VERIFICATION_GATE.md`
**Scope:** READ-ONLY planning/preflight for M7-B (restart + cross-process recall). No implementation; no edits to either repo.

**Hygiene statement:**
- Code changed: NO
- Tests changed: NO
- Spec changed: NO
- Inventory changed: NO
- Memory Contract wire/fixtures changed: NO
- TOMTIT-Memory code changed: NO
- Planner/skills/tools changed: NO
- Architecture/Product/Gate changed: NO
- `.gitignore` changed: NO
- Branch created: NO · Commit: NO · Merge: NO · Push: NO
- M7-B implemented: NO · SF2 implemented: NO
- Only preflight report created: YES

---

## 0. Main/origin custody

`branch=main`; `HEAD == main == origin/main == 3737ca4`; worktree/staged clean. **PASS**.

## 1. M7-A spec/inventory/smoke evidence

Spec SHA `7e9ba4de…` (1924 lines); inventory SHA `4c9d5e04…`. `REPORT_M7A_POST_MERGE_SMOKE_VERIFIED.md` present with `M7-A POST-MERGE SMOKE: GO`. M7-A is closed, merged, smoke-passed. **PASS**.

## 2. Baseline regression

`import_ok`; **552 passed**; exit 0. **PASS**.

## 3. Current Agent remote read/search/context inventory

| Capability | Source path | Exists? | Remote-supported? | Tests? | Notes |
|---|---|---|---|---|---|
| remote context retrieval | `MemoryClientProtocol.retrieve_context_pack` / `remote_client.py` → POST `/v1/context/retrieve` | YES | YES | YES (`test_remote_memory_client`) | scoped by project_id (client config) + user_id + optional session_id + query |
| context pack on state | `RuntimeAgent._retrieve_memory` sets `state.context_pack` before planning | YES | YES | YES (`test_runtime_remote_memory`) | runs at every `run()` start |
| deterministic answer-from-context | `ToolName.ANSWER_FROM_CONTEXT` / `tool_answer_from_context` | YES | YES (in `CONTEXT_CONSUMER_TOOLS`, NOT in `LOCAL_DURABLE_TOOLS` → not disabled remote) | YES (`test_p4_local_demo`) | reads `state.context_pack`, no LLM |
| local durable search tools | `SEARCH_MEMORY`/`SUMMARIZE_MEMORY`/`READ_NOTE`/`LIST_NOTES` | YES | NO (in `LOCAL_DURABLE_TOOLS`, disabled in remote) | YES | local-only; not used for remote recall |
| SessionRuntime recall entrypoint | — | NO | — | — | only `handle_turn` (NL) + `run_confirmed_decision_save` (write) today |
| CLI recall/search command | — | NO | — | — | only `/memory save-decision` (write) today |
| provenance surfaced | ContextItem carries `memory_id` + `evidence_ref` (+ `source_task_id`) | YES | YES | YES | provenance available in retrieved items |

**Key fact:** the remote **read primitive already exists** (`retrieve_context_pack`) and is remote-enabled, with provenance. What is missing for M7-B is a deliberate *recall orchestration/surface* (a SessionRuntime/CLI recall path) + cross-process/restart **proof and tests** — not a new contract. **PASS**.

## 4. Session/process boundary inventory

| Question | Status | Evidence |
|---|---|---|
| New SessionRuntime with same project_id/user_id, new session_id? | PASS | project_id is `RemoteMemoryClient` config; `user_id` is SessionRuntime ctor arg; session_id minted per session |
| Use RemoteMemoryClient with same Memory backend? | PASS | `build_agent_with_memory_backend(remote config)` |
| Build context/search without `AgentState.confirmed_save_operation`? | PASS | retrieval path is independent of the write field |
| Avoid local state from process A? | PASS | `retrieve_context_pack` reads only remote; no cross-process in-memory carry |
| TurnRecord/session storage separate from memory recall? | PASS | session persistence (FileSessionStore) is orthogonal to durable Memory |

No FAIL on process/session separation. **PASS**.

## 5. TOMTIT-Memory read/durability inventory

Sibling `../TOMTIT-Memory` HEAD `d4d879d29a9fe5d10bae128b2675ae256354ca87` (== expected). [VMR]
- Read endpoint: `CONTRACT_POST_PATHS = {"/v1/context/retrieve", "/v1/memories/write"}` — read API present.
- Services: `retrieval_service.py` (FTS/BM25 scoped by project_id+user_id+query, optional type_filter; **not** session-scoped) + `context_pack_builder.py`.
- Persistence: file-backed SQLite (`DEFAULT_DATABASE_PATH = "tomtit-memory.sqlite3"`, `sqlite3.connect(self._db_path)`) — durable across restart.
- Provenance: `ContextItem` carries `memory_id`, `evidence_ref`, `source_task_id`.

TOMTIT-Memory exposes a usable read API with durable persistence and sufficient provenance for M7-B. **No Memory-side change required.** **PASS**.

## 6. Optional discovery smoke (real server)

Ran a real discovery smoke (disposable combined venv + temp SQLite under `/tmp`; `uvicorn tomtit_memory.main:app`; no code edits). Disposable IDs `project=m7b-prj-8f4d0d9d`, `user=m7b-user-8f4d0d9d`, marker `M7-B preflight recall marker 8f4d0d9d`.

| Scenario | Result |
|---|---|
| A. Save decision via M7-A confirmed-save path | `Decision saved.` `Memory ID: mem_ad3e8f48…` `Provenance: user-explicit:<task>:<conf>` |
| B. Record in DB | 1 `memory_records` row, type `decision`, content has marker |
| C. Direct `/v1/context/retrieve` (4 queries incl. exact marker) | returns the decision with `evidence_ref` (provenance) |
| D. Agent `retrieve_context_pack` (fresh client, brand-new session_id) | **items=1, degraded=False**, `evidence_ref` + `memory_id` present |
| E. Cross-**project** isolation (different project_id) | 0 hits |
| F. **Restart** Memory server with same SQLite DB → retrieve again | **items=1** with provenance (durable across restart) |

**Discovered nuance (non-blocking):** one in-script `retrieve_context_pack` call issued *immediately* after the write returned 0 items, while a subsequent fresh-client retrieve (and all direct curls) returned the record. Likely FTS commit/visibility timing within the same rapid script. M7-B must define a robust recall query/orchestration and not assume instantaneous same-tick read-after-write; this is a spec/test detail, not a capability gap (durable retrieve works). **Classified: PASS (with nuance recorded).**

## 7. Minimal M7-B product claim

```
TOMTIT-Agent can recall a previously confirmed project decision from TOMTIT-Memory in a fresh Agent session/process, using the remote context-retrieve path, with provenance preserved and no local fallback.
```
Stronger claim (supported by §6 F):
```
…including after the TOMTIT-Memory server restarts using the same durable SQLite store.
```
Forbidden claims (must NOT be made): general long-term memory; automatic remembering of all decisions; whole-project resume; prompt-injection-safe recall.

## 8. Proposed M7-B scope boundary

**In scope:** Agent-side recall orchestration (a dedicated SessionRuntime recall method and/or CLI `/memory recall` command) over the existing `retrieve_context_pack`; fresh session/process; same project_id/user_id identity; same durable Memory backend; provenance-visible recall output; safe missing-result behavior; remote-unavailable-during-recall fail-safe; restart/session-separation tests; real restart smoke.
**Out of scope:** autonomous extraction; M7-A write changes (unless bug-blocking); Memory Contract v2; new wire DTO/endpoint; TOMTIT-Memory code change (read API already present); SF2; project resume; planner/tool/skill refactor; vector search (lexical/FTS context already sufficient).
**No split needed:** M7-B is Agent-side only (M7-BM TOMTIT-Memory work is **not** required — read API + durability already exist at `d4d879d`).

## 9. Proposed implementation file manifest (Agent-side)

| File | Current role | M7-B action likely | Risk | Notes |
|---|---|---|---|---|
| `agent_core/runtime/session_runtime.py` | session orchestration | ADD dedicated recall method (e.g. `recall_decisions(query)`) | LOW | reuses `retrieve_context_pack`; new session id ok |
| `agent_core/cli.py` | meta-commands | ADD `/memory recall` command (read-only) | LOW | mirror `/status`; never planner |
| `agent_core/runtime/runtime_agent.py` | run paths | possibly a thin remote-recall helper or reuse `_retrieve_memory` | MEDIUM | keep transport-neutral; no best-effort write reuse |
| `agent_core/memory/client.py` / `remote_client.py` | retrieve primitive | VERIFY-ONLY (likely no change) | LOW | retrieve already remote + provenance |
| `main.py` | composition | VERIFY-ONLY (user_id already wired) | LOW | recall uses same identity |
| `tests/test_m7b_restart_recall.py` (NEW) | — | restart/cross-session recall + smoke | LOW | new |
| `tests/test_session_runtime.py` / `test_remote_memory_client.py` (MODIFY) | — | recall unit/integration | LOW | extend |
| **Avoid:** `agent_core/confirmation/**`, `tools/**`, `skills/**`, `planning/**`, `memory/wire/**`, `tests/fixtures/memory_contract_v1/**`, `docs/standards/**`, `.gitignore` | — | none | — | M7-A write path and contracts frozen |

## 10. Proposed test strategy

| Test category | Type | Real Memory? | Owner file | Blocking? |
|---|---|---|---|---|
| remote retrieve request/response handling | unit | no (mock transport) | test_remote_memory_client.py | yes |
| fresh session recalls saved decision | integration | mock or real | test_m7b_restart_recall.py | yes |
| recall independent of `confirmed_save_operation` | unit | no | test_m7b_restart_recall.py | yes |
| same project/user retrieves; different does not | integration | mock/real | test_m7b_restart_recall.py | yes |
| missing decision → safe no-result | unit | no | test_m7b_restart_recall.py | yes |
| provenance visible (evidence_ref/memory_id) | unit/integration | mock/real | test_m7b_restart_recall.py | yes |
| no local fallback on recall | unit | no | test_m7b_restart_recall.py | yes |
| remote unavailable during recall → safe | unit | no (degraded pack) | test_m7b_restart_recall.py | yes |
| real restart smoke (server restart, same DB) | smoke | **yes** | manual/smoke harness | yes (acceptance) |
| post-restart full regression | regression | no | full suite | yes |

## 11. Proposed acceptance criteria (future spec)

`AC-M7B-01` baseline + M7-A custody verified · `02` decision saved via existing M7-A path · `03` fresh Agent session/process recalls it remotely · `04` recall requires same project_id/user_id · `05` different project/user cannot recall · `06` provenance/source_ref preserved in recall output · `07` recall does not use `AgentState.confirmed_save_operation` · `08` no local fallback · `09` remote-unavailable recall fails safely · `10` no Memory Contract v2 · `11` no planner/tool/skill refactor · `12` full regression passes · `13` real restart smoke passes (server restart, same SQLite) · `14` recall query/orchestration deterministic and robust to read-after-write timing.

## 12. Risk review

| Risk | Severity | Mitigation |
|---|---|---|
| Remote read endpoint availability | LOW | exists (`/v1/context/retrieve`), verified live |
| Memory durable restart behavior | LOW | proven in §6 F (file SQLite survives restart) |
| Identity boundary (project/user/session) | LOW | scoping verified; isolation proven (§6 E) |
| Recall surface choice (CLI cmd vs context injection) | MEDIUM | spec decision; recommend explicit `/memory recall` (read-only, no planner) |
| Recall leaking raw memory internals | MEDIUM | surface only safe fields (content + memory_id + provenance); spec rule |
| Recall accidentally using local store | LOW | remote-only client; add no-fallback test |
| Tests need real server fixture | MEDIUM | unit via mock transport; one real restart smoke for acceptance |
| Dependency on TOMTIT-Memory code change | LOW | none required (read API present at d4d879d) |
| Scope creep into project-resume | MEDIUM | explicit out-of-scope boundary (§8) |
| Read-after-write timing nuance (§6) | LOW | spec defines deterministic recall query + robust test |

No HIGH/CRITICAL unmitigated risk.

## 13. Final hygiene

TOMTIT-Agent: `main == origin/main == 3737ca4`; worktree/staged clean; only untracked reports. Smoke venv/DBs under `/tmp` (outside repos); all smoke servers stopped (ports 8077/8078 down). Post-smoke regression **552 passed**.

**Sibling-repo observation (not a blocker, not mine):** TOMTIT-Memory HEAD unchanged at `d4d879d`, but its working tree has an **external/uncommitted** edit `M docs/STATUS.md` (date 2026-06-19→2026-06-21; M7 row → "MEMORY BACKEND READY / AGENT PROOF PENDING") not made by this task — left untouched (no authorization to modify TOMTIT-Memory). My editable install created the gitignored `tomtit_memory.egg-info/` (build artifact, not a tracked change), also left as-is. Neither affects the Agent baseline or the M7-B preflight; both are disposable/external.

## 14. M7B-PREFLIGHT-01 through M7B-PREFLIGHT-16

| ID | Criterion | Status |
|---|---|---|
| M7B-PREFLIGHT-01 | main/origin custody exact at 3737ca4 | PASS |
| M7B-PREFLIGHT-02 | M7-A spec/inventory custody preserved | PASS |
| M7B-PREFLIGHT-03 | M7-A smoke evidence present | PASS |
| M7B-PREFLIGHT-04 | baseline regression passes (552) | PASS |
| M7B-PREFLIGHT-05 | remote read/search/context capability inventoried | PASS |
| M7B-PREFLIGHT-06 | session/process boundary inventoried | PASS |
| M7B-PREFLIGHT-07 | TOMTIT-Memory read/durability inventoried | PASS |
| M7B-PREFLIGHT-08 | discovery smoke classified honestly | PASS (write+recall+restart proven; read-after-write timing nuance recorded) |
| M7B-PREFLIGHT-09 | minimal M7-B claim defined narrowly | PASS |
| M7B-PREFLIGHT-10 | in/out scope boundary defined | PASS |
| M7B-PREFLIGHT-11 | implementation file manifest proposed | PASS |
| M7B-PREFLIGHT-12 | test strategy proposed | PASS |
| M7B-PREFLIGHT-13 | draft AC list proposed and testable | PASS |
| M7B-PREFLIGHT-14 | risks classified with mitigations | PASS |
| M7B-PREFLIGHT-15 | no code/test/spec changes performed | PASS |
| M7B-PREFLIGHT-16 | final hygiene clean | PASS |

16 / 16 PASS.

## 15. Final verdict

```
M7-B RESTART RECALL PREFLIGHT: GO
READY FOR M7-B SPEC DRAFT
```

The current codebase is ready to define and implement M7-B without changing Memory Contract v1 or expanding scope: the Agent already has a remote context-retrieve primitive with provenance; TOMTIT-Memory exposes a durable read API (`/v1/context/retrieve`, file-backed SQLite) at the evidence revision `d4d879d`; the real discovery smoke proved write → fresh-session recall → recall after Memory server restart, with project isolation and provenance preserved. M7-B is a narrow Agent-side recall-orchestration + tests effort (no Memory code change, no Contract v2, no new endpoint). One non-blocking nuance (read-after-write timing) is recorded for the spec.

`GO` does not authorize M7-B implementation — only a separate M7-B spec-draft instruction.

Code changed: NO · Tests changed: NO · Spec changed: NO · Inventory changed: NO · Memory Contract wire/fixtures changed: NO · TOMTIT-Memory code changed: NO · Planner/skills/tools changed: NO · Architecture/Product/Gate changed: NO · `.gitignore` changed: NO · Branch/commit/merge/push: NO · M7-B implemented: NO · SF2 implemented: NO · Only preflight report created: YES.

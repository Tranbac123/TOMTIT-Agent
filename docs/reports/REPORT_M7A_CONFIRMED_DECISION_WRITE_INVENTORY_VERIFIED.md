# REPORT_M7A_CONFIRMED_DECISION_WRITE_INVENTORY_VERIFIED

**Date:** 2026-06-20 UTC
**Repository:** TOMTIT-Agent
**Baseline:** `0e55156ce13243386e12cb04c4aab061033cc566` (`HEAD == main == origin/main`)
**Verification policy:** `docs/standards/VERIFICATION_GATE.md`
**Directive scope:** READ-ONLY inventory — no spec, no implementation, no code/test/contract change

**Custody statement:**
- Production code changed: **NO**
- Tests changed: **NO**
- Existing specs changed: **NO**
- Memory Contract changed: **NO**
- Only M7-A inventory report created: **YES**

Evidence classification legend: `VERIFIED_FROM_CODE` (VC), `VERIFIED_FROM_ACCEPTED_PRODUCT_SPEC` (VPS), `VERIFIED_FROM_AUTHORITATIVE_ARCHITECTURE` (VA), `VERIFIED_FROM_ACCEPTED_MEMORY_CONTRACT` (VMC), `INFERRED` (INF), `UNVERIFIED_CROSS_REPO` (UXR), `UNKNOWN`.

---

## 0. Git baseline

| Field | Value |
|---|---|
| branch | `main` |
| HEAD / main / origin/main | `0e55156ce13243386e12cb04c4aab061033cc566` |
| tracked/staged changes | none |
| pre-existing untracked | none at gate start |

No `pull`/`merge`/`reset`/`rebase`/`stash`/`clean` performed. [VC]

---

## 1. Authoritative artifacts inspected

| Artifact | SHA-256 |
|---|---|
| `docs/ARCHITECTURE.md` (v1.0 AUTHORITATIVE) | `8a5e629e8b575b82cd1582a7faf4cfa381f60db4c3f60092bf96166b3ecb5796` |
| `docs/goal_product/PRODUCT_SPEC_MVP_USER_TRIAL.md` (v0.3 ACCEPTED) | `06ce02a15b6c5f5e69de43d49d744fbe99bec01183da3f776ea7b6da43210286` |
| `docs/specs/SPEC_SF1_TRUST_EVIDENCE_CONTRACTS.md` | `98bc62b7d7102bf4ac9e128be6e4debbc693a14fe59258ef377c5de551905658` |
| `docs/standards/VERIFICATION_GATE.md` | `12752a52969226b7d07c3057d3b0a23d8ce5ac73c5a729a92ccb0b0ffc975249` |
| Memory contract doc | `docs/goal_product/SPEC_M6_REMOTE_MEMORY_CLIENT.md` |

The accepted product spec (§8–§13) and architecture (§16) already define the **conceptual** M7-A contracts (`ConfirmedDecision`, `ConfirmedSaveOperation`, `ConfirmedMemoryWritePolicy`). No corresponding code exists yet — `git grep` for these symbols returns hits only in `docs/`. [VC][VPS][VA]

---

## 2. Repository-wide discovery

- Production `AgentState(...)` construction sites: **exactly one** — `agent_core/runtime/session_runtime.py:63` (keyword form). [VC]
- `write_memory_candidates` implementations: `client.py` (Protocol), `local_client.py`, `null_client.py`, `remote_client.py`. [VC]
- `request_id` handling lives only in `remote_client.py` and `wire/v1.py`. [VC]
- `ConfirmedDecision`/`ConfirmedSaveOperation`/`confirmed_decisions`/`ConfirmedMemoryWritePolicy`: **zero** code hits (docs only). [VC]
- Planner/skill/tool references to `MemoryCandidate`/`write_memory_candidates`/`ConfirmedDecision`/`EvidenceEnvelope`: **zero** — isolation intact. [VC]
- No sibling `TOMTIT-Memory` repository found under parent directories. [VC]

---

## 3. Application and CLI boundary

| Entry point | Input type | Creates AgentState? | Uses SessionRuntime? | Calls planner? | Suitable for dedicated save? |
|---|---|---|---|---|---|
| `main.py` → composition + `run_interactive` | argparse + REPL | no (delegates) | yes | no | composition only |
| `agent_core/cli.py::run_interactive` | stdin line / meta-commands | no (delegates) | yes | no | **seam host** (meta-command) |
| `SessionRuntime.handle_turn(str)` | natural-language string | **yes** (`goal=user_message`) | n/a (is SR) | yes (via agent.run) | NO (NL turn, runs planner) |
| `RuntimeAgent.run(state)` | `AgentState` | no (consumes) | no | yes | NO (full retrieve→plan→exec) |

**Answers (Step 3):** [VC]
1. NL turn arrives via `cli.run_interactive` → `session.handle_turn(user_input)` → `AgentState(goal=user_message)`.
2. **Yes** — `cli.run_interactive` already intercepts `/status` and `/history` *before* `handle_turn`. This is a working application-command seam.
3. `handle_turn()` is currently the only run seam, but it is NL-only and runs the planner; it is not the only *possible* seam.
4. **Yes** — a dedicated `run_confirmed_decision_save(...)` method (separate from `handle_turn`) keeps the planner from ever seeing confirmation, because the NL planner is only reached through `handle_turn`/`agent.run`'s plan path.
5. Application boundary owns identity: `session_id` in `SessionRuntime`/`main.py` (uuid4 or `--session-id`); `user_id`/`project_id` in `RemoteMemoryClient` config (`--memory-user-id`/`--memory-project-id`); `task_id` minted per `AgentState`.
6. `confirmation_id` should be created by the application command handler (CLI meta-command / application service), never by planner/model.
7. Evidence authority must be created **before** `AgentState`/operation construction (application boundary owns it, per spec §9.1).
8. No composition root bypasses `SessionRuntime` for turns; `build_*_agent` only assemble components.
9. A dedicated save run needs `RuntimeAgent` (completion authority) but **not** the planner/executor; whether it also produces a `TurnRecord` is M7A-D14.
10. User-facing failure message is produced at terminal transition: `AgentState.fail()` sets `final_answer=error`; `SessionRuntime` nulls it into `TurnRecord` for FAILED (anti-leak). [VC `session_runtime.py:77`]

### Seam comparison

| Option | Boundary fit | Session semantics | Risk | Required files | Recommendation |
|---|---|---|---|---|---|
| A. Extend `handle_turn` with optional confirmed input | poor — mixes NL turn with typed save; planner-adjacent | reuses turn | HIGH (planner contamination, overloaded seam) | session_runtime | reject |
| B. Dedicated `run_confirmed_decision_save(...)` on SessionRuntime/RuntimeAgent | strong — typed, planner never invoked | explicit save run | LOW | session_runtime + runtime_agent + cli | **RECOMMEND** |
| C. Separate application service bypassing SessionRuntime | strong isolation | loses session correlation/TurnRecord reuse | MEDIUM (duplicate persistence path) | new service | fallback only |

**Recommendation: Option B.** A dedicated typed method invoked from a CLI meta-command (mirroring the `/status`/`/history` pattern) preserves the NL planner boundary, keeps `RuntimeAgent` as completion authority, and avoids a second persistence path. [VC][VPS §9.1]

---

## 4. AgentState and run-input contract

Probe results [VC]:
- `AgentState` fields (24): `goal, task_id, user_id, session_id, status, plan, current_step, done, final_answer, last_result, slots, memory, history, observations, sources, errors, context_pack, memory_degraded, memory_write_failed, disclosure_reasons, context_consumed, max_steps, approved_tools, read_only`.
- `confirmed_decisions` absent; `confirmed_save_operation` absent; `project_id` absent. [VC, matches VA §16, VPS §11.6]
- `SessionState` fields: `session_id, created_at, updated_at, turns`. `TurnRecord` fields: `task_id, goal, final_answer, status, planned_actions, memory_degraded, memory_write_failed, disclosure_reasons, completed_at`. Neither serializes `AgentState` or any confirmation/evidence object. [VC]
- AgentState is per-run (new instance per `handle_turn`). [VC]

### State contract options

| Option | Description | state-first | consume-once | persistence impact | trade-off |
|---|---|---|---|---|---|
| 1 | `confirmed_decisions: tuple[ConfirmedDecision, ...] = ()` | weak — allows >1 decision | n/a | none if not serialized | violates "one decision per operation" |
| 2 | `confirmed_save_operation: ConfirmedSaveOperation \| None = None` | strong | terminal-status guard | none (not in TurnRecord/SessionState) | adds field to guarded public contract |
| 3 | separate `RunRequest` passed to dedicated method, used to build AgentState | strong, no field | request consumed by method | none | run input lives outside state (less state-first) |

**Recommendation: Option 2** — additive optional field `confirmed_save_operation: ConfirmedSaveOperation | None = None`, default `None`, **run-only**, never serialized into `TurnRecord`/`SessionState`. Backward-compatible: only one production construction site (keyword), all tests use keyword form. Exact dataclass position: append after `read_only` (last field) to avoid positional breakage. Consume-once enforced by the terminal-status guard (M7A-D12). This field addition is legitimately in M7-A scope (architecture §6 classifies `confirmed_decisions` as ACCEPTED TARGET) but modifies the CLAUDE.md-guarded `AgentState` contract → requires explicit architect sign-off in the spec. [VC][VPS §8.3][VA §16.4]

---

## 5. Exact SF1 evidence contract

Probe [VC `agent_core/safety/evidence.py`]:
- Import path: `from agent_core.safety.evidence import EvidenceEnvelope` (also re-exported via `agent_core.safety.__init__`).
- Signature: `EvidenceEnvelope(content: str, source_type: SourceType, trust_level: TrustLevel, source_ref: str | None = None, metadata: Mapping[str, MetadataValue] = {})`.
- `content` field: **required**, must be `str`.
- `source_ref`: optional; if provided must be a non-blank string.
- metadata: `Mapping[str, MetadataScalar | tuple[MetadataScalar,...]]`; validated; replaced with `MappingProxyType` (read-only).
- `@dataclass(frozen=True)` — immutable.
- Enum members: `SourceType.USER = "user"`; `TrustLevel.TRUSTED_INSTRUCTION = "trusted_instruction"`. [VC `enums.py`]
- No existing helper/factory for user-confirmation evidence; only `tool_observation_ref(...)` exists (tool path). [VC]

**Answers (Step 5):** (1) `agent_core.safety.evidence.EvidenceEnvelope`; (2) required: `content, source_type, trust_level`; (3) yes — `content` exists and is required; (4) `source_ref` optional; (5) metadata = scalar or tuple-of-scalar; (6) frozen=True; (7) `SourceType.USER`; (8) `TrustLevel.TRUSTED_INSTRUCTION`; (9) no helper; (10) recommend a **narrow factory** to standardize confirmation-evidence construction (avoids each caller hand-rolling source_type/trust_level/source_ref).

**Recommended evidence shape for M7-A:**
```text
source_type = SourceType.USER
trust_level = TrustLevel.TRUSTED_INSTRUCTION
source_ref  = "user-explicit:<task_id>:<confirmation_id>"
content     = the user-confirmed decision text (or confirmation marker per spec)
metadata    = optional (e.g. {"confirmation_id": ...})
```
[VC][VPS §9.2 line 502][VA §13.3]

---

## 6. Confirmed domain-model options

| Contract | Recommended module | Dataclass/Pydantic | Fields | Validation owner | Why |
|---|---|---|---|---|---|
| `ConfirmedDecision` | new `agent_core/confirmation/models.py` (new package) | `@dataclass(frozen=True)` | `confirmation_id: str`, `content: str`, `confirmation_evidence: EvidenceEnvelope` | `ConfirmedMemoryWritePolicy` (+ light `__post_init__` nonblank) | matches repo immutable-domain convention; near safety/state, not in memory wire |
| `ConfirmedSaveOperation` | same module | `@dataclass(frozen=True)` | `request_id: str`, `task_id: str`, `session_id: str \| None`, `decision: ConfirmedDecision` | policy + composition | one decision, frozen, run-only |
| `RequiredWriteOutcome` | reuse `WriteResponse` + a small result-consistency check; new model only if needed | n/a | n/a | required-write checker | avoid unnecessary abstraction |

Repo convention check: immutable models use `@dataclass(frozen=True)` (evidence, TurnRecord, SessionStatusView) and `MappingProxyType` for read-only maps; wire DTOs use Pydantic `extra="forbid"`. Domain/run inputs → frozen dataclass. [VC]

**ConfirmedDecision questions:** `confirmation_id: str` nonblank; `content` normalized (strip) — exact normalization is a spec/policy detail; `confirmation_evidence: EvidenceEnvelope`; blank → reject; evidence/source consistency validated by policy; equality = dataclass structural. [VPS §8.2]

**ConfirmedSaveOperation questions:** `request_id`, `task_id` required; `session_id`/session correlation = `str | None` (see §9 below); `decision` single; `user_id` does **not** belong here (supplied per accepted Agent/Memory identity contract = `RemoteMemoryClient.default_user_id` / `state.user_id`); `project_id` **must not** be here; frozen; retry reuses the identical frozen object. [VPS §8.3, §10, §11]

**RequiredWriteOutcome:** A new model is **not required**. `WriteResponse(written_ids, skipped)` already distinguishes written vs skipped_duplicate. The missing piece is **response-consistency validation** (one result per candidate, `candidate_id == confirmation_id`, no extra/zero/unknown) — this is logic, not a new DTO. Recommend a checker function, optionally returning a small typed result enum (`WRITTEN` / `SKIPPED_DUPLICATE`). [VC `remote_client.py:215-224`][VPS §13.3]

---

## 7. Current runtime memory-finalization path

Trace [VC `runtime_agent.py`]:
```
run() → _retrieve_memory → (terminal? finalize) → _plan → (terminal? finalize)
      → _execute_plan → _finalize_run
_finalize_run(): compose draft → _write_memory (best-effort) → _apply_disclosure
               → append_disclosures → state.complete(draft)   [ONE completion authority]
```

**Answers (Step 7):** [VC]
1. `_collect_candidates()` returns `[]` (line 268) — auto-extraction is post-MVP.
2. `_write_memory()` is **best-effort** (lines 245-263): catches all exceptions, sets `memory_write_failed=True`, appends error, logs warning.
3. All write exceptions are swallowed → converted to `memory_write_failed` disclosure.
4. Write failure does **not** fail the run — run still `complete()`s.
5. Final answer (`draft`) is composed **before** the write attempt.
6. **Yes** — current path can return "success" before persistence completes (best-effort). This is exactly what M7-A must avoid.
7. The current finalization path is **not** safe to reuse as-is for required write.
8. Dedicated save run should branch **before planning** (no retrieve/plan/execute).
9. Smallest seam: a dedicated `RuntimeAgent` method that validates → required-write → terminal transition.
10. No planner needed for dedicated save run.

### Runtime seam comparison

| Option | Description | Verdict |
|---|---|---|
| A. Reuse `_collect_candidates`/`_write_memory` | best-effort, swallows failure | **reject** — would emit success on write failure |
| B. Required-write branch inside RuntimeAgent (dedicated method) | new method: validate → required write → complete/fail | **RECOMMEND** |
| C. Dedicated service outside RuntimeAgent | second persistence path / completion authority | reject (splits completion authority) |

**Recommendation: Option B.** A dedicated method (e.g. `RuntimeAgent.run_confirmed_save(state)`) that (a) never invokes planner/executor, (b) calls the policy to build exactly one `MemoryCandidate(type=decision)`, (c) calls `write_memory_candidates`, (d) validates response consistency, (e) calls `state.complete()` on written/skipped_duplicate or `state.fail()` on any failure. This preserves RuntimeAgent as the single completion authority, avoids generic planner side effects, avoids two persistence paths, and keeps state-first (terminal status on the run's AgentState). [VC][VPS §13]

---

## 8. MemoryClientProtocol and wire contract

Signatures [VC]:
- `MemoryClientProtocol.write_memory_candidates(candidates, *, user_id=None, session_id=None, task_id=None) -> WriteResponse` — **no `request_id` param**, **no AgentState**.
- `RemoteMemoryClient.__init__(*, base_url, project_id, default_user_id, timeout_seconds=5.0, http_client=None, transport=None, request_id_factory=None)`.
- `RemoteMemoryClient` generates `request_id` internally via `self._request_id_factory()` (default `lambda: str(uuid4())`), per call. [VC `remote_client.py:51,121,247`]

| Item | Current type/signature | Required for M7-A | Gap |
|---|---|---|---|
| MemoryCandidate | `type, content, tags, importance, confidence, evidence_ref:str\|None, metadata` (Pydantic) | yes | none (sufficient) |
| request_id | internal factory, per-client, default random uuid4 | deterministic per-operation, caller-stable | **GAP** (mechanism) |
| task_id | `write_memory_candidates(..., task_id=None)`; required by RemoteMemoryClient (`_required`) | yes | none |
| session_id | `str \| None` param; wire `session_id: str\|None` | yes | none |
| project_id | `RemoteMemoryClient.project_id` (construction) | yes (config) | none — must stay config |
| user_id | param or `default_user_id` | yes | none |
| evidence_ref | `MemoryCandidate.evidence_ref`; RemoteMemoryClient requires non-blank | yes | none |
| write response | `WriteResponse(written_ids, skipped)`; wire `WriteResponseV1(results[], counts)` | yes | **GAP** (no per-candidate consistency check) |

Wire DTO facts [VC/VMC `wire/v1.py`]:
- `WriteRequestV1`: `request_id, project_id, user_id, session_id?, task_id, candidates[1..50]`; `extra="forbid"`; unique candidate_ids.
- `WriteCandidateV1`: `candidate_id, type, content, tags, importance, confidence, evidence_ref(required), metadata`.
- `WriteStatusV1 = Literal["written","skipped_duplicate"]` → any other status fails Pydantic validation → `RemoteMemoryWriteError`. [VC]
- `IDEMPOTENCY_CONFLICT` is an `ErrorCodeV1` (error envelope), not a result status. [VC]
- `MemoryType.DECISION` is supported (not in `_UNSUPPORTED_REMOTE_TYPES = {TASK_SUMMARY, SOURCE}`). [VC]

### Agent → Memory v1 mapping

| Agent-side | Memory Contract v1 | Transform | Validation owner |
|---|---|---|---|
| confirmation_id | `WriteCandidateV1.candidate_id` | identity (set `metadata["candidate_id"]=confirmation_id`) | policy/mapper |
| decision content | `WriteCandidateV1.content` | normalized string | policy |
| EvidenceEnvelope | `WriteCandidateV1.evidence_ref` | render `user-explicit:<task_id>:<confirmation_id>` | mapper |
| task_id | `WriteRequestV1.task_id` | from `state.task_id` | RemoteMemoryClient (required) |
| session correlation | `WriteRequestV1.session_id` | `state.session_id` (str\|None) | wire validator |
| request_id | `WriteRequestV1.request_id` | deterministic formula (M7A-D07) | client/composition |
| project_id | `RemoteMemoryClient.project_id` | config | client |
| user_id | `WriteRequestV1.user_id` | `state.user_id` or `default_user_id` | client |

No new wire DTO needed. [VC][VPS §11]

---

## 9. Request replay, duplicate and conflict semantics

Four distinct semantics confirmed against code + accepted spec [VC/VPS]:

| # | Semantics | Trigger | Expected | Current support |
|---|---|---|---|---|
| 9.1 | same-operation retry (replay) | same frozen op → same request_id + identical payload | replay stored response | request_id **not** caller-stable per-call (gap) |
| 9.2 | idempotency conflict | same request_id, different payload | `IDEMPOTENCY_CONFLICT` → FAILED | 4xx → `RemoteMemoryWriteError` (assumes 4xx) |
| 9.3 | exact duplicate | new confirmation_id/request_id, same normalized content | `skipped_duplicate` → COMPLETED | wire supports; mapping supports |
| 9.4 | process restart | op not persisted; new confirmation | new ids; duplicate handles same content | op not persisted (correct) |

**Answers (Step 9):** [VC]
1. The Agent client does **not** accept a caller-supplied request_id per call.
2. The client **generates** request_id internally.
3. Default is **random** (uuid4); a `request_id_factory` can be injected at **construction** (per-client, not per-call).
4. Retry can preserve the full envelope only if the same frozen `ConfirmedSaveOperation` is re-submitted with the same request_id — requires a caller-stable request_id mechanism.
5. Replay vs duplicate are distinguishable at the Memory layer (replay = same request_id+payload; duplicate = `skipped_duplicate` status), but the Agent must send a stable request_id to enable replay.
6. Exact statuses: `written`, `skipped_duplicate` (results); error codes incl. `IDEMPOTENCY_CONFLICT`.
7. Unknown status: rejected by `WriteStatusV1` Literal → `RemoteMemoryWriteError` (→ FAILED). [VC]
8. Response can contain zero/multiple results without raising in the **current** client (no count check) — gap.
9. Candidate/result correlation is **not** currently verified by the client — gap.
10. Idempotency conflict is an `ErrorCodeV1` envelope, conventionally a 4xx → currently raises. Exact HTTP status is [UXR] (no sibling Memory repo).

**Request-ID formula:** spec §12.1 line 610 suggests `memory-write:<confirmation_id>`; the directive (Step 9) suggests `memory-write:<task_id>:<confirmation_id>`. Character set/length/collision scope must align with `confirmation_id` uniqueness scope (`project_id + user_id`, per §8.2). Whether `task_id`/`session_id` belong in the deterministic ID is a real choice → **M7A-D07 PENDING** (architect). Both are viable; the request_id alone is never sufficient (full payload must match).

---

## 10. Required-write failure matrix

| Condition | Current client behavior | Current runtime behavior | Required M7-A behavior | Gap |
|---|---|---|---|---|
| timeout | raise `RemoteMemoryWriteError` | swallow → disclosure, COMPLETE | FAILED, no "saved" | runtime (best-effort) |
| connection error | raise | swallow → COMPLETE | FAILED | runtime |
| 5xx / 503 | raise | swallow → COMPLETE | FAILED | runtime |
| 4xx (incl. IDEMPOTENCY_CONFLICT) | raise | swallow → COMPLETE | FAILED | runtime |
| invalid JSON | raise | swallow → COMPLETE | FAILED | runtime |
| schema mismatch | raise (Pydantic) | swallow → COMPLETE | FAILED | runtime |
| unknown status | raise (Literal) | swallow → COMPLETE | FAILED | runtime |
| zero results | **no raise** → empty WriteResponse | swallow/none | FAILED (inconsistent) | **client + runtime** |
| extra results (>1 per candidate) | **no raise** → maps all | swallow/none | FAILED (inconsistent) | **client + runtime** |
| candidate_id mismatch | **no raise** → maps wrong id | swallow/none | FAILED (inconsistent) | **client + runtime** |
| written | maps to written_ids | success | COMPLETED + saved disclosure | none |
| skipped_duplicate | maps to skipped | success | COMPLETED + duplicate disclosure | none |

**Where response validation belongs:** a **narrow required-write checker** on the Agent side (in the dedicated save service/runtime method), because (a) the directive forbids changing `RemoteMemoryClient`/protocol, and (b) the generic best-effort runtime must not be the owner. The checker asserts exactly one result, `candidate_id == confirmation_id`, status ∈ {written, skipped_duplicate}. Explicit write failure must never become degraded success. [VC][VPS §13.2-13.3]

---

## 11. ConfirmedMemoryWritePolicy boundary

`PolicyEngine` (`safety/policy.py`) only checks tool risk level + read-only; it is **not** the owner of confirmed-write semantics and must not be extended for it. `ApprovalGate` governs tool approval, unrelated. [VC]

**Recommended narrow policy:**
- Module: new `agent_core/confirmation/write_policy.py` (or `agent_core/memory/confirmed_write_policy.py`) — **not** `safety/policy.py`.
- Class: `ConfirmedMemoryWritePolicy` with a method e.g. `to_candidate(operation: ConfirmedSaveOperation, *, user_id: str) -> MemoryCandidate` (validate + map in one service).
- Responsibilities (accept): exactly one decision; nonblank confirmation_id; nonblank normalized content; correct typed SF1 evidence (`SourceType.USER` + `TrustLevel.TRUSTED_INSTRUCTION` + stable source_ref); require `state.task_id`/`user_id`; map to exactly one `MemoryCandidate(type=DECISION)`; set `metadata["candidate_id"]=confirmation_id`; render evidence_ref.
- Forbidden: HTTP/store calls; tool execution; text inference; planner/model input; project_id management; duplicate detection (Memory owns it).
- Errors: typed validation errors (e.g. `ConfirmedWriteValidationError`).
[VC][VPS §10]

---

## 12. Dedicated save-run lifecycle

**Answers (Step 12):** [VC/VPS]
1. Retrieve memory first? **No.** 2. Invoke planner? **No.** 3. Create `Step`s? **No.** 4. Invoke `ToolExecutor`? **No.** 5. Call `FinalComposer`? **Optional** (a short fixed message; not required). 6. `complete()` caller: the dedicated `RuntimeAgent` method. 7. `fail()` caller: same method. 8. `written` disclosed via a saved message. 9. `skipped_duplicate` disclosed via an already-existed message. 10. Write failure surfaced as a safe fixed message (no raw error text; mirror `fail()` + TurnRecord null rule). 11. Confirmed input consumed once via terminal-status guard. 12. Retry inside one process: yes, by re-submitting the same frozen operation. 13. Retry must reuse the exact frozen operation. 14. `RuntimeAgent.run()` called twice with same terminal state: the `_finalize_run` `if state.done: return` guard prevents re-finalize; a dedicated method must add an equivalent terminal guard before writing. 15. The terminal status invariant (`is_terminal()`) prevents a second write.

**Proposed state machine** (uses existing `AgentStatus` — **sufficient**, no new enum members):
```
CREATED → validate → required write → written/skipped_duplicate → COMPLETED
CREATED → validate failure OR write failure → FAILED
```
`AgentStatus` (`created, planning, running, completed, failed`) expresses this; `skipped_duplicate` is a COMPLETED outcome distinguished by disclosure, not a status. [VC]

---

## 13. SessionRuntime and TurnRecord boundary

Trace [VC `session_runtime.py`, `session_state.py`]:
- FAILED run → `TurnRecord.final_answer = None` (anti-leak, line 77). COMPLETED → final_answer preserved.
- `TurnRecord` has no field for confirmation input/operation/evidence; `SessionState` does not serialize `AgentState`. Session resume cannot reconstruct an operation. [VC]

| Runtime outcome | AgentState status | User-facing message | TurnRecord.final_answer | Session persistence |
|---|---|---|---|---|
| written | COMPLETED | "saved" disclosure | preserved | candidate persisted before mutate |
| skipped_duplicate | COMPLETED | "already existed" | preserved | persisted |
| write failure | FAILED | safe fixed message | None | persisted (status only) |

### TurnRecord options

| Option | Description | Verdict |
|---|---|---|
| A. Save run is a normal session turn | conflates NL turn with typed save | reject |
| B. Application command that still produces a TurnRecord | records status, no operation serialized | **RECOMMEND** |
| C. Not recorded in SessionState | loses session audit continuity | acceptable fallback |

**Recommendation: Option B** — the save run produces a `TurnRecord` (status + anti-leak final_answer) so the session audit trail is complete, while the `ConfirmedSaveOperation`/evidence are **never** serialized (consistent with spec §8.3 invariants). [VC][VPS §8.3]

---

## 14. Backend and split-brain behavior

[VC `factory.py`, `registry.py`]:
- `LOCAL_DURABLE_TOOLS` includes `SAVE_DECISION` (+ WRITE_NOTE, READ_NOTE, LIST_NOTES, SAVE_FACT, SAVE_PREFERENCE, SEARCH_MEMORY, SUMMARIZE_MEMORY).
- REMOTE backend → `RemoteMemoryClient` + `disabled_tools=LOCAL_DURABLE_TOOLS` (so `save_decision` tool is not registered). NONE → `NullMemoryClient` + same disabled set. LOCAL → `LocalMemoryClient`, no disabled tools.
- `validate_memory_activation` raises `RemoteMemoryConfigurationError` if a RemoteMemoryClient (or NullMemoryClient) coexists with any local durable tool (split-brain guard).
- `project_id` configured at `RemoteMemoryClient` construction. [VC]
- `NullMemoryClient.write` returns empty `WriteResponse()` (silent no-op); `LocalMemoryClient.write` always "written", no duplicate detection. [VC]

**Decision:** M7-A is **remote-only**. The dedicated save service must reject local/none **before** any write (a save on Null/Local would silently "succeed"). Recommended: the save service requires a `RemoteMemoryClient` (isinstance check) or a composition-level guard, raising a typed error (e.g. `ConfirmedWriteBackendError`) when backend ≠ remote. Must **not** reactivate `save_decision`/`write_note`/`save_fact`/`save_preference` in remote mode. [VC][VPS §13.2 "no silent local fallback"]

---

## 15. Planner, skill and tool isolation

`git grep` across `agent_core/planning`, `agent_core/skills`, `agent_core/tools` for `MemoryCandidate|write_memory_candidates|ConfirmedDecision|EvidenceEnvelope` → **zero hits**. Isolation intact. [VC]

**Forbidden-to-change in M7-A:**
```
agent_core/planning/**            (planner must not create confirmation)
agent_core/skills/**              (skill must not create confirmation)
agent_core/tools/builtin_tools.py (no remote save_decision tool)
agent_core/tools/executor.py      (ToolExecutor not used for M7-A persistence)
agent_core/tools/registry.py      (do not re-enable LOCAL_DURABLE_TOOLS in remote)
agent_core/memory/wire/**         (no wire/endpoint change)
tests/fixtures/memory_contract_v1/**  (contract fixtures frozen)
docs/goal_product/PRODUCT_SPEC_MVP_USER_TRIAL.md, docs/ARCHITECTURE.md, docs/standards/VERIFICATION_GATE.md
```

---

## 16. Current and required test map

Existing relevant tests [VC]:

| Existing test file | Proves | Does not prove | Reusable for M7-A |
|---|---|---|---|
| test_remote_memory_client.py (15) | write success mapping; 5xx/4xx/malformed → raise; unsupported type/missing evidence rejected | response consistency (zero/extra/mismatch results), deterministic request_id | EXTEND |
| test_runtime_remote_memory.py | runtime + remote wiring | required-write FAILED semantics | EXTEND |
| test_runtime_memory_wiring.py | best-effort write path | required write | EXTEND |
| test_memory_backend_activation.py | split-brain guard | M7-A remote-only rejection of save run | EXTEND |
| test_session_runtime.py / _state / _store / _serializer | turn/persistence, anti-leak | save-run TurnRecord behavior | EXTEND |
| test_memory_contract_fixtures.py | wire fixtures valid | M7-A mapping | reuse fixtures |
| test_evidence_contracts.py | EvidenceEnvelope validation | confirmation-evidence factory | EXTEND |

Required M7-A tests (1–30 from directive) → status:

| # | Test | Status |
|---|---|---|
| 1 | valid ConfirmedDecision construction | NEW |
| 2 | invalid/blank confirmation ID | NEW |
| 3 | invalid/blank content | NEW |
| 4 | wrong SF1 source type | NEW |
| 5 | wrong trust level | NEW |
| 6 | missing/invalid source_ref | NEW |
| 7 | one operation == one decision | NEW |
| 8 | deterministic request ID | NEW |
| 9 | policy maps exactly one MemoryCandidate(decision) | NEW |
| 10 | no confirmation → no write | NEW |
| 11 | planner/model output cannot create candidate | NEW (isolation assertion) |
| 12 | local/none backend rejected before write | NEW (EXTEND activation) |
| 13 | remote written → SUCCESS | NEW (EXTEND remote) |
| 14 | remote skipped_duplicate → SUCCESS | NEW |
| 15 | timeout → FAILED, no "saved" | NEW |
| 16 | network/5xx → FAILED | NEW |
| 17 | invalid/empty/extra response → FAILED | NEW |
| 18 | candidate_id mismatch → FAILED | NEW |
| 19 | unknown status → FAILED | NEW (partly covered by Literal) |
| 20 | idempotency conflict → FAILED | NEW |
| 21 | same frozen op retry reuses request_id/payload | NEW |
| 22 | new confirmation same content → new request_id | NEW |
| 23 | confirmed input consumed once | NEW |
| 24 | failed run TurnRecord.final_answer is None | EXTEND (rule exists) |
| 25 | operation not persisted in SessionState | NEW |
| 26 | project_id remains client config | EXTEND |
| 27 | local durable store sentinel untouched | EXTEND |
| 28 | planner not invoked for save run | NEW |
| 29 | ToolExecutor not invoked for persistence | NEW |
| 30 | Memory Contract v1 wire DTO unchanged | EXTEND (fixtures) |

---

## 17. Exact proposed implementation file manifest

### 17.1 Required new production files

| Path | Class/function | Responsibility | Why new |
|---|---|---|---|
| `agent_core/confirmation/__init__.py` | package | exports | new domain package |
| `agent_core/confirmation/models.py` | `ConfirmedDecision`, `ConfirmedSaveOperation` | frozen run-only domain models | not wire, not state |
| `agent_core/confirmation/evidence_factory.py` | `make_confirmation_evidence(...)` | narrow SF1 evidence factory (USER + TRUSTED_INSTRUCTION + source_ref) | no existing helper |
| `agent_core/confirmation/write_policy.py` | `ConfirmedMemoryWritePolicy` | validate + map one decision → one MemoryCandidate(decision) | narrow policy, not PolicyEngine |
| `agent_core/confirmation/required_write.py` | required-write response checker | enforce §13.3 consistency | client/protocol unchanged |

### 17.2 Required modified production files

| Path | Class | Method/field | Exact change | Why |
|---|---|---|---|---|
| `agent_core/state/agent_state.py` | `AgentState` | `confirmed_save_operation: ConfirmedSaveOperation \| None = None` | append optional field (last) | state-first run input (M7A-D02) |
| `agent_core/runtime/runtime_agent.py` | `RuntimeAgent` | new `run_confirmed_save(state)` | required-write branch (no planner/executor) | dedicated lifecycle (M7A-D10) |
| `agent_core/runtime/session_runtime.py` | `SessionRuntime` | new `run_confirmed_decision_save(...)` | application seam → builds op → calls agent → TurnRecord | seam (M7A-D01) |
| `agent_core/cli.py` | `run_interactive` | new meta-command (e.g. `/save-decision`) | intercept before handle_turn, gather typed input | application confirmation boundary |

Each change carries its own trade-off; all are additive and avoid touching planner/tools/wire.

### 17.3 Required new/modified tests

| Path | Test group | Coverage |
|---|---|---|
| `tests/test_confirmed_decision_models.py` (NEW) | models | #1-7 |
| `tests/test_confirmed_write_policy.py` (NEW) | policy/mapping | #4-12 |
| `tests/test_confirmed_required_write.py` (NEW) | required-write | #13-20 |
| `tests/test_confirmed_save_runtime.py` (NEW) | lifecycle/retry/consume-once | #21-23,28,29 |
| `tests/test_session_runtime.py` (EXTEND) | TurnRecord/session | #24,25 |
| `tests/test_memory_backend_activation.py` (EXTEND) | remote-only | #12,27 |
| `tests/test_remote_memory_client.py` (EXTEND) | response consistency | #17,18,19 |

### 17.4 Conditional files

| Path | Trigger |
|---|---|
| thin adapter around `RemoteMemoryClient` | only if architect rejects per-operation `request_id_factory` and a request_id seam is needed without touching the client |
| new typed error module `agent_core/confirmation/errors.py` | if validation/backend errors warrant dedicated types |

### 17.5 Forbidden files
As enumerated in §15.

---

## 18. Cross-repo TOMTIT-Memory classification

No sibling `TOMTIT-Memory` repository is present. Memory server behavior is therefore classified:
- Wire shape, statuses (`written`/`skipped_duplicate`), error codes (incl. `IDEMPOTENCY_CONFLICT`), `request_id`/`task_id`/`session_id` fields, candidate_id correlation: **VERIFIED_FROM_ACCEPTED_MEMORY_CONTRACT** (`agent_core/memory/wire/v1.py` + `tests/fixtures/memory_contract_v1/`).
- Exact HTTP status code for `IDEMPOTENCY_CONFLICT` (4xx assumed), duplicate-detection normalization scope (`project_id+user_id+type+normalized content` per spec §12.3), and SQLite persistence semantics: **UNVERIFIED_CROSS_REPO**.

These UXR items do **not** block writing the Agent-side spec: the accepted Memory Contract already defines that any 4xx/5xx/invalid response → write failure, and M7-A treats all non-{written,skipped_duplicate} outcomes as FAILED. The only item to confirm with the Memory team during implementation is the HTTP status used for `IDEMPOTENCY_CONFLICT` (so the client's existing 4xx→raise path covers it). [UXR]

---

## 19. Decision closure matrix (M7A-D01–D17)

| ID | Decision | Verified options | Recommendation | Evidence | Status |
|---|---|---|---|---|---|
| M7A-D01 | Application seam | A/B/C | **B** dedicated method + CLI meta-command | cli.py meta-cmd, session_runtime | READY |
| M7A-D02 | AgentState field | 1/2/3 | **2** `confirmed_save_operation: …\|None=None` | 1 call site, VPS §8.3 | READY (needs spec sign-off on guarded contract) |
| M7A-D03 | ConfirmedDecision module/type | frozen dataclass; module choice | new `agent_core/confirmation/models.py` | repo convention | READY |
| M7A-D04 | ConfirmedSaveOperation contract | fields incl. session_id str\|None; no user_id/project_id | as §6 | VPS §8.3, §10 | READY |
| M7A-D05 | SF1 evidence constructor | direct vs factory | **narrow factory** | no helper exists | READY |
| M7A-D06 | source_ref format | `user-explicit:<task_id>:<confirmation_id>` | adopt | VPS §9.2 | READY |
| M7A-D07 | request_id formula | `memory-write:<confirmation_id>` (spec) vs `memory-write:<task_id>:<confirmation_id>` (directive) | architect choice | VPS §12.1 vs directive | **PENDING** |
| M7A-D08 | session_id nullability | `str \| None` | adopt | VC wire + state | READY |
| M7A-D09 | policy location/signature | new module, `to_candidate(...)` | as §11 | VPS §10 | READY |
| M7A-D10 | runtime write seam | A/B/C | **B** dedicated RuntimeAgent method | VC §7 | READY |
| M7A-D11 | response validation owner | client vs runtime vs adapter | **Agent-side checker** (runtime/service) | VC §10 | READY |
| M7A-D12 | consume-once mechanism | terminal-status guard | adopt | VC §12 | READY |
| M7A-D13 | retry ownership | application/composition reuses frozen op | adopt | VPS §8.4, §12.1 | READY |
| M7A-D14 | SessionRuntime/TurnRecord | A/B/C | **B** produce TurnRecord, op not serialized | VC §13 | READY |
| M7A-D15 | remote-only rejection boundary | service isinstance vs composition guard | reject before write, typed error | VC §14 | READY |
| M7A-D16 | exact file manifest | §17 | adopt | §17 | READY |
| M7A-D17 | Memory Contract sufficiency | sufficient; one UXR | no wire change | VC/VMC §8,§18 | READY (confirm IDEMPOTENCY_CONFLICT HTTP status during impl) |

One PENDING (M7A-D07) — a choice between two documented request_id formats; it does not block writing the spec (the spec records the chosen formula).

---

## 20. Risks and stop conditions

| Severity | Risk | Code fact | Smallest resolution | Owner |
|---|---|---|---|---|
| HIGH | request_id not per-call caller-controlled | `remote_client.py:51,121` factory per-client | per-operation client/factory closure, or thin adapter; record formula (D07) | architect + impl |
| HIGH | required-write response consistency unvalidated | `remote_client.py:215-224` no count/correlation check | Agent-side checker enforcing §13.3 | impl |
| MEDIUM | best-effort `_write_memory` swallows failures | `runtime_agent.py:245-263` | dedicated required-write method (D10) | impl |
| MEDIUM | Null/Local clients silently "succeed" | `null_client.py:36`, `local_client.py:79` | remote-only guard before write (D15) | impl |
| LOW | AgentState additive field touches guarded contract | CLAUDE.md §7 | explicit spec sign-off; additive default | architect |
| UXR | IDEMPOTENCY_CONFLICT HTTP status; duplicate normalization scope | no sibling repo | confirm with Memory team | cross-repo |

**Mandatory stop conditions — none triggered:**
- Memory Contract v1 can represent required write — **OK** (request_id, task_id, decision, written/skipped_duplicate, IDEMPOTENCY_CONFLICT). 
- request_id can be caller-controlled — **OK** (via `request_id_factory` seam; mechanism is D07/risk, not impossible).
- response distinguishes written/duplicate — **OK**.
- session_id contract compatible — **OK** (`str | None`).
- stable application confirmation seam exists — **OK** (CLI meta-command + SessionRuntime).
- AgentState additive field breaks external contract — **NO** (one call site, additive default).
- required-write can fail run without runtime redesign — **OK** (dedicated method + complete/fail).
- remote client silently degrades write failure to success — **NO** (client raises; only the *generic best-effort runtime* swallows, and M7-A will not use it).
- M7-A requires planner/tool-generated confirmation — **NO**.
- M7-A requires wire/endpoint change — **NO**.
- M7-A requires local fallback — **NO**.

No BLOCKER.

---

## 21. Full test baseline

| Field | Value |
|---|---|
| Python | 3.11.2 |
| pytest | 8.4.2 |
| OS | Darwin 25.5.0 |
| import | `import_ok` |
| test count | 468 passed |
| duration | ~1.29s |
| exit code | 0 |

Command: `PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider -q`. No code/tests modified.

---

## 22. Acceptance matrix (M7A-INV-01–24)

| ID | Criterion | Evidence | Status |
|---|---|---|---|
| M7A-INV-01 | Exact main/origin baseline verified | §0 `0e55156` | PASS |
| M7A-INV-02 | Authoritative Architecture/Product/SF1/Gate read | §1 SHAs | PASS |
| M7A-INV-03 | Application entry seams inventoried | §3 table+answers | PASS |
| M7A-INV-04 | AgentState constructor/call-site impact inventoried | §4 (1 site) | PASS |
| M7A-INV-05 | Exact SF1 evidence contract resolved | §5 | PASS |
| M7A-INV-06 | Confirmed domain-model options resolved | §6 | PASS |
| M7A-INV-07 | Current runtime write flow traced | §7 | PASS |
| M7A-INV-08 | MemoryClientProtocol/write signature resolved | §8 | PASS |
| M7A-INV-09 | Memory Candidate/response fields resolved | §8 | PASS |
| M7A-INV-10 | Replay/duplicate/conflict semantics separated | §9 | PASS |
| M7A-INV-11 | Required-write gap matrix completed | §10 | PASS |
| M7A-INV-12 | Narrow policy boundary resolved | §11 | PASS |
| M7A-INV-13 | Dedicated save lifecycle resolved | §12 | PASS |
| M7A-INV-14 | Session/TurnRecord behavior resolved | §13 | PASS |
| M7A-INV-15 | Remote-only/split-brain behavior resolved | §14 | PASS |
| M7A-INV-16 | Planner/skill/tool isolation verified | §15 (zero hits) | PASS |
| M7A-INV-17 | Current and required tests mapped | §16 | PASS |
| M7A-INV-18 | Exact implementation file manifest proposed | §17 | PASS |
| M7A-INV-19 | Memory cross-repo claims honestly classified | §18 | PASS |
| M7A-INV-20 | M7A-D01–D17 decision matrix completed | §19 | PASS |
| M7A-INV-21 | Full regression passes | §21 (468) | PASS |
| M7A-INV-22 | No code/test/spec/contract modification | git status clean | PASS |
| M7A-INV-23 | Inventory report is the only new repository file | §23 | PASS |
| M7A-INV-24 | No unresolved blocker prevents writing spec | §20 (no BLOCKER) | PASS |

**24 / 24: PASS.** One decision PENDING (M7A-D07) — architect-level, does not block spec authoring.

---

## 23. Unknowns requiring architect decision

1. **M7A-D07 request_id formula** — `memory-write:<confirmation_id>` (product spec §12.1) vs `memory-write:<task_id>:<confirmation_id>` (directive). Also the exact caller-control **mechanism** (per-operation client/factory closure vs thin adapter), since the protocol has no per-call request_id and the directive forbids changing it.
2. **AgentState field sign-off** — adding `confirmed_save_operation` modifies a CLAUDE.md-guarded public contract; in scope for M7-A but needs explicit approval in the spec.
3. **IDEMPOTENCY_CONFLICT HTTP status** [UXR] — confirm with Memory team that it is a 4xx so the existing `RemoteMemoryClient` 4xx→raise path yields FAILED.
4. **New package placement** — `agent_core/confirmation/` vs co-locating models under `state/` and policy under `memory/`. Recommended new package; architect may prefer otherwise.

---

## 24. Final verdict

```
M7-A INVENTORY VERIFIED
READY TO WRITE SPEC
```

Custody: production code NO, tests NO, specs NO, Memory Contract NO; only this untracked inventory report created. Baseline unchanged at `0e55156`; `main == origin/main`; 468 tests pass. **NOT READY TO IMPLEMENT** — spec authoring is the next authorized step, pending architect resolution of M7A-D07 and the AgentState field sign-off.

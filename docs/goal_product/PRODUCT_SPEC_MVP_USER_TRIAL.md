# TOMTIT-Agent — Product MVP for User Trial

**Document:** `PRODUCT_SPEC_MVP_USER_TRIAL.md`<br>
**Version:** `0.3`<br>
**Status:** `ACCEPTED FOR MEMORY WEDGE TRIAL`<br>
**Primary milestone:** Memory Wedge Trial<br>
**Secondary milestone:** Broader Agent Alpha<br>
**Target:** 3–5 design partners; chưa phải production release<br>

> `DRAFT FOR FINAL VERIFICATION` có nghĩa các quyết định kiến trúc đã được thống nhất để kiểm tra tài liệu lần cuối.<br>
> Nó không có nghĩa product spec đã được chấp nhận hoặc M7-A đã được phép implement.<br>
> Tài liệu chỉ được nâng thành `Version 0.3 / ACCEPTED FOR MEMORY WEDGE TRIAL`
> sau khi candidate docs-only được freeze, verified read-only và được human/architect phê duyệt.

---

# 0. Executive decision

TOMTIT không tiếp tục xây một general AI Agent đầy đủ trước khi chứng minh wedge sản phẩm cốt lõi.

## Long-term vision

> TOMTIT giúp coding agents duy trì project context qua nhiều phiên làm việc.

## Memory Wedge Trial claim

> TOMTIT cho phép developer lưu và truy xuất các project decisions đã được xác nhận rõ ràng, kèm provenance, qua nhiều phiên và process restart.

Memory Wedge Trial định vị TOMTIT như một **project-memory companion chạy bên cạnh coding agents**.

Trial chưa chứng minh:

- tích hợp liền mạch với Claude Code, Cursor, Codex hoặc Copilot;
- Agent tự biết điều gì cần nhớ;
- automatic memory extraction;
- autonomous project memory;
- tự động giảm token hoặc rework cho mọi coding workflow.

Roadmap được chia thành hai milestone.

## Milestone A — Memory Wedge Trial

Chứng minh workflow:

```text
User xác nhận một project decision
→ application tạo typed confirmed input
→ TOMTIT-Agent ghi qua TOMTIT-Memory
→ Agent process restart
→ TOMTIT-Memory process restart
→ Agent mới recall đúng decision và provenance
```

Milestone này không cần LLM planner, replanning, real web, workspace tools hoặc MCP.

## Milestone B — Broader Agent Alpha

Chỉ mở sau khi Memory Wedge Trial tạo đủ evidence:

```text
SF2 trust enforcement
→ Goal Interpreter
→ Guarded Planner
→ Execution/Replanning
→ Real Web/Workspace
→ Expanded Skills
→ Full Memory UX
```

---

# 1. Revision summary — v0.2 → v0.3-draft

Version 0.3-draft khóa các correction sau:

1. Sửa request replay để phù hợp Memory Contract v1:
   - replay chỉ trong cùng một frozen save operation;
   - process/run mới không được giả định replay operation cũ.
2. Tách exact duplicate khỏi request idempotency.
3. Thay raw `evidence_ref` input bằng typed SF1 confirmation evidence.
4. Thêm immutable `ConfirmedSaveOperation`.
5. Khóa confirmed input là run-only, consume-once và không được session persistence lưu/restore.
6. Thu hẹp claim trial thành project-memory companion.
7. Thu hẹp ICP theo hành vi và pain đã xảy ra.
8. Đổi metrics cho sample 3–5 người từ phần trăm sang count.
9. Bỏ “Minimal Project Resume” khỏi required Milestone A workflows.
10. Biến current project status thành snapshot không normative.
11. Thêm Agent-domain → Memory Contract v1 mapping.
12. Giữ Memory Contract v1, HTTP endpoints và SQLite schema không đổi.
13. Không tự khóa tên enum/class SF1 trước khi source inventory sau SF1 closure xác nhận.
14. Không mở M7-A implementation chỉ từ product spec.

---

# 2. Normative status and phase authorization

## 2.1 Product decisions accepted

```text
M7 mode:
FULL AGENT WRITE-AND-RECALL

Write source:
EXPLICIT USER-CONFIRMED DECISION ONLY

Automatic extraction:
FORBIDDEN

Retrieve-only:
DIAGNOSTIC SUBTEST, NOT M7 COMPLETION

SF1 prerequisite:
YES

SF2 prerequisite:
NO
```

## 2.2 What this document authorizes

This document authorizes:

- finalizing the product contract;
- SF1-closure inventory references;
- M7-A read-only inventory after SF1 is CLOSED;
- drafting a separate M7-A implementation specification.

It does not authorize:

- production code changes;
- Memory Contract changes;
- M7-A implementation;
- M7-B implementation;
- SF2;
- LLM activation;
- MCP/A2A.

## 2.3 Finalization sequence

```text
v0.3-draft
→ docs-only candidate freeze
→ read-only verification
→ human/architect approval
→ v0.3 ACCEPTED FOR MEMORY WEDGE TRIAL
```

The same editor must not silently promote the document to `ACCEPTED`.

---

# 3. Non-normative project status snapshot

This section is informational and must not be treated as the source of truth for current Git HEAD.

**Snapshot date:** `2026-06-19`<br>
**Revision source of truth:** use the latest verification/status reports for both repositories; this product document does not freeze repository SHAs.<br>

Known phase state at drafting time:

```text
SR1: completed
SR2: completed
SR3: completed
EX1: completed
EX2: completed
M6: implemented on Agent main
SF1: candidate/gate work; not CLOSED until approved and merged
M7-A: not implemented
M7-B: not implemented
SF2: not implemented
```

Current revision status belongs in verification/status reports, not in the normative product contract.

---

# 4. Target user and ICP

## 4.1 Primary ICP

Prioritize developers who satisfy most of these conditions:

- have used an AI coding agent for at least three months;
- use it at least four days per week;
- work on multi-file or multi-session repositories;
- have experienced a recent context-loss, repeated-explanation or rework incident;
- currently use `CLAUDE.md`, rules, README, notes or repeated prompts to preserve context;
- have not already built a complete custom hooks/harness/memory system;
- accept running a local companion service during the trial.

## 4.2 Exclude or deprioritize

- beginners without a repeated multi-session workflow;
- users whose work is primarily single-file or one-shot;
- teams that already solved the problem with a mature internal memory/harness platform;
- users unwilling to run a local service;
- users expecting autonomous coding or automatic extraction in the first trial.

## 4.3 Core product problem

1. Coding assistants forget architecture decisions and constraints.
2. Developers repeat context across sessions.
3. Decisions are fragmented across chat, project docs and personal notes.
4. Developers cannot easily see which stored context affected an answer.
5. A “saved” message without durable persistence is not trustworthy.

## 4.4 Trial hypotheses

If TOMTIT:

- stores exactly the decision a user confirmed;
- recalls it after process restart;
- shows provenance;
- does not silently fallback or falsely claim persistence;

then a meaningful subset of ICP developers will:

- reduce repeated context explanation;
- trust recalled project decisions;
- return for another session;
- request continued use or deeper integration.

---

# 5. Architecture boundaries

## 5.1 AgentState

`AgentState` is the source of truth for one run.

M7 may add a typed confirmed-decision run input after inventory.

The input must not be hidden in `slots`.

## 5.2 SessionState

`SessionState` is the source of truth for session continuity.

It must not persist:

- confirmed decisions awaiting write;
- frozen save operations;
- MemoryCandidate objects;
- TOMTIT-Memory records.

## 5.3 TurnRecord

`TurnRecord` is the immutable summary of a turn.

Required-write failure follows the existing safe failure policy:

```text
run status = FAILED
durable TurnRecord.final_answer = None
safe failure message returned at application/runtime boundary
raw exception text not persisted as final_answer
```

## 5.4 TOMTIT-Memory

TOMTIT-Memory is the source of truth for durable semantic memory across sessions.

TOMTIT-Agent must not:

- access TOMTIT-Memory SQLite directly;
- import TOMTIT-Memory internals;
- create a second persistence schema.

## 5.5 Boundary invariant

```text
AgentState
= truth of one run

SessionState
= truth of session continuity

TOMTIT-Memory
= truth of durable semantic project memory
```

---

# 6. SF1 dependency without inventing SF1 symbols

SF1 is a prerequisite because M7 requires typed source, trust and provenance.

The exact SF1 class paths, enum names, field names and construction APIs must be taken from the **closed SF1 implementation**, not invented by this product document.

## 6.1 Conceptual invariant

`confirmation_evidence` must be typed SF1 evidence that:

- identifies the application/user-confirmation source;
- carries the trust classification appropriate for an explicit instruction;
- contains a stable confirmation/source reference;
- cannot be created from planner or model output;
- is not treated as a cryptographic token.

## 6.2 Prohibited shortcuts

M7 must not:

- create parallel trust/source enums;
- add an M7-only EvidenceEnvelope;
- accept a raw caller-provided `evidence_ref` as authorization;
- pass SF1 domain objects through the Memory HTTP contract;
- ask TOMTIT-Memory to verify user confirmation.

## 6.3 Inventory requirement

After SF1 is CLOSED, M7-A inventory must identify:

```text
exact SF1 evidence class
exact source/trust enum values
required fields
valid constructor/factory
safe application creation boundary
```

Until then, the code examples below are conceptual contracts only.

---

# 7. M6 — Remote Memory Integration

M6 provides:

```text
RuntimeAgent
→ MemoryClientProtocol
→ RemoteMemoryClient
→ HTTP/JSON v1
→ TOMTIT-Memory
```

Required M6 properties:

- remote/local/none backend composition;
- remote mode disables local durable-memory tools;
- split-brain activation guard;
- operational retrieval degradation;
- explicit contract failure;
- remote write transport;
- project identity held by client configuration;
- no direct SQLite access.

Current product gap:

```text
remote transport exists
but production confirmed-decision candidate generation is not active
```

M7 closes that gap.

---

# 8. M7-A — Dedicated confirmed-decision save run

## 8.1 Dedicated operation

M7-A does not support compound intent such as:

```text
Do task X and remember decision Y.
```

It uses a dedicated application action:

```text
Confirm and persist this project decision.
```

Semantics:

```text
written
→ run COMPLETED

skipped_duplicate
→ run COMPLETED with duplicate disclosure

required write failure
→ run FAILED
→ no saved claim
```

## 8.2 Conceptual ConfirmedDecision

```python
@dataclass(frozen=True)
class ConfirmedDecision:
    confirmation_id: str
    content: str
    confirmation_evidence: "ClosedSF1EvidenceType"
```

This is a domain/run input, not a wire DTO.

Rules:

- `confirmation_id` is application-owned;
- `confirmation_id` must be nonblank;
- `confirmation_id` must remain stable inside one `ConfirmedSaveOperation`;
- a new confirmation must use an ID unique within the `project_id + user_id` scope;
- the same `confirmation_id` must never be reused with a different decision payload;
- `content` is the exact user-confirmed decision;
- `confirmation_evidence` is created by the application confirmation boundary;
- planner/model cannot construct or mutate this object;
- each M7 save run accepts exactly one decision.

M7 MVP rejects:

```text
0 decisions where a save was requested
more than 1 decision
blank content
blank confirmation identity
invalid/missing typed evidence
```

## 8.3 Conceptual ConfirmedSaveOperation

```python
@dataclass(frozen=True)
class ConfirmedSaveOperation:
    request_id: str
    task_id: str
    session_id: "MemoryContractV1SessionCorrelation"
    decision: ConfirmedDecision
```

`MemoryContractV1SessionCorrelation` means the exact accepted Agent/Memory contract type and nullability. M7 inventory must verify it; this document does not redefine it.

Operation invariants:

- application creates the operation once;
- request ID, task ID, session correlation and decision remain immutable;
- operation contains exactly one decision;
- planner/model cannot create or modify it;
- retries inside the same operation reuse the identical envelope;
- operation is not persisted into `SessionState`;
- operation is not persisted into `TurnRecord`;
- operation is not restored during session resume;
- operation does not survive process restart in M7 MVP.

## 8.4 Run-only and consume-once semantics

Consume-once means:

```text
structured run input
→ create one immutable save operation
→ zero or more retries of the same frozen operation
→ terminal success/failure
→ operation discarded
```

It does not mean deleting the operation before a write attempt completes.

Required test:

```text
save run completes
→ resume session
→ zero additional write calls
```

---

# 9. Confirmation and provenance ownership

## 9.1 Application boundary owns confirmation

Flow:

```text
user action / CLI confirmation
→ application creates or validates confirmation_id
→ application creates typed SF1 evidence
→ ConfirmedDecision
→ ConfirmedSaveOperation
→ Agent runtime
```

Invariant:

```text
model output
!= user confirmation
!= provenance authority
```

## 9.2 Evidence rendering

The Agent-side mapper validates typed SF1 evidence and renders a Memory v1 string such as:

```text
user-explicit:<task_id>:<confirmation_id>
```

The exact renderer belongs to M7-A technical spec after SF1 inventory.

`evidence_ref` is:

- provenance/trace metadata;
- not an authorization token;
- not proof TOMTIT-Memory can independently verify;
- not raw model output;
- not application input accepted without typed evidence validation.

---

# 10. Confirmed memory write policy

M7 uses a narrow service:

```text
ConfirmedMemoryWritePolicy
```

It must:

- accept only one `ConfirmedDecision`;
- validate confirmation identity;
- validate nonblank content;
- validate typed SF1 evidence;
- require Agent task identity;
- require `user_id` according to the accepted Agent/Memory contract;
- map to exactly one `MemoryCandidate`;
- force memory type `decision`;
- render `evidence_ref`;
- not call HTTP or a store;
- not manage tool execution;
- not receive planner/model output.

`project_id` remains configuration owned by composition/`RemoteMemoryClient`.<br>
M7 must not add `project_id` to `AgentState`, `ConfirmedDecision` or `ConfirmedSaveOperation` only to satisfy Memory transport.

Do not add memory persistence rules to the tool `PolicyEngine`.

---

# 11. Agent → TOMTIT-Memory v1 mapping

| Agent domain | TOMTIT-Memory v1 |
|---|---|
| `confirmation_id` | `MemoryCandidate.candidate_id` |
| confirmed decision content | `MemoryCandidate.content` |
| fixed domain type | `type = "decision"` |
| typed SF1 confirmation evidence | mapper renders `evidence_ref` |
| save-run task identity | `WriteRequest.task_id` |
| current session correlation | `WriteRequest.session_id` |
| frozen operation request ID | `WriteRequest.request_id` |
| RemoteMemoryClient configuration | `project_id`; `user_id` is supplied according to the accepted Agent/Memory identity contract |

Additional rules:

- `project_id` is owned by composition/`RemoteMemoryClient` configuration;
- M7 does not add `project_id` to `AgentState` solely for transport;

- TOMTIT-Memory does not receive `AgentState`;
- TOMTIT-Memory does not receive SF1 domain objects;
- TOMTIT-Memory does not verify user confirmation;
- TOMTIT-Memory does not know the planner, ToolExecutor or SessionState;
- TOMTIT-Memory validates the wire contract, idempotency, duplicate identity and persistence.

No new endpoint is needed.

Use:

```text
POST /v1/memories/write
```

Do not add:

```text
/v1/confirm
/v1/decisions
/v1/memories/save-confirmed
```

---

# 12. Request replay and exact duplicate semantics

These are separate behaviors.

## 12.1 Request replay

Replay is valid only for the **same frozen `ConfirmedSaveOperation`**:

```text
same request_id
same task_id
same session_id
same candidate order
same candidate payload
same full idempotency payload
→ replay stored response
```

A deterministic request ID may use:

```text
memory-write:<confirmation_id>
```

only when the `confirmation_id` invariants in §8.2 are satisfied.

The request ID alone is not enough. The entire payload must remain identical.

## 12.2 Process or run restart

M7 MVP does not persist `ConfirmedSaveOperation`.

Therefore:

```text
process restart
→ old operation cannot be replayed
→ user/application creates a new confirmation
→ new confirmation_id
→ new request_id
```

If content is the same, duplicate detection handles it.

The product must not promise “retry the old confirmation after restart” in M7.

## 12.3 Exact duplicate

```text
new operation
new confirmation_id
new request_id
same project_id
same user_id
same type
same normalized content
→ skipped_duplicate
→ no second memory record
```

## 12.4 Idempotency conflict

```text
same request_id
different full payload
→ IDEMPOTENCY_CONFLICT
→ no additional write
→ dedicated save run FAILED
```

---

# 13. Required-write semantics

Explicit confirmed save is a required side effect.

## 13.1 Success outcomes

```text
written
→ run COMPLETED
→ saved disclosure

skipped_duplicate
→ run COMPLETED
→ already-existed disclosure
```

## 13.2 Failure outcomes

```text
timeout
network error
5xx
contract mismatch
invalid response
empty response
inconsistent response
idempotency conflict
```

Required behavior:

```text
run FAILED
safe immediate failure message
TurnRecord.final_answer = None
no “saved” claim
no silent local fallback
```

## 13.3 Required response consistency

A required write succeeds only when the response contains exactly one semantic result for the submitted candidate:

```text
candidate_id == confirmation_id
status == written OR skipped_duplicate
no missing result
no extra result
no unknown status
```

Any of the following is an inconsistent response:

```text
zero results
more than one result
mismatched candidate_id
unknown status
response that cannot identify the submitted candidate outcome
```

An inconsistent response:

```text
→ run FAILED
→ no “saved” claim
```

Existing future best-effort memory behavior may remain for opportunistic memory, but it does not apply to M7 explicit save.

---

# 14. M7-B — Cross-process restart-and-recall

## 14.1 Main scenario

1. User enters a project decision.
2. User explicitly confirms persistence.
3. Application creates typed SF1 evidence.
4. Application creates one frozen save operation.
5. Policy maps it to one decision candidate.
6. Agent A writes through `MemoryClientProtocol`.
7. TOMTIT-Memory returns `written` or valid duplicate.
8. Agent A process terminates.
9. Agent B starts with a new state, session and client.
10. Agent B retrieves the same project/user namespace.
11. ContextPack contains the decision and provenance.
12. Runtime uses the decision in `final_answer`.
13. TOMTIT-Memory process terminates.
14. A new Memory process opens the same SQLite file.
15. Agent C starts and recalls the same decision.

## 14.2 Required negative scenarios

- no confirmed input → zero write calls;
- planner/model output → zero candidate;
- invalid evidence/identity/content → reject before client;
- more than one confirmed decision → reject;
- write outage → FAILED, no false success;
- retrieve outage → degraded, no local fallback;
- same operation retry → request replay;
- new operation with same content → duplicate;
- same request ID with different payload → conflict;
- session resume → zero repeated writes;
- local fail-on-access sentinel → never called;
- remote mode → local durable tools disabled;
- user/project isolation → enforced.

## 14.3 Retrieve-only diagnostic

Retrieve-only may seed Memory directly to isolate:

```text
service persistence
HTTP retrieval
ContextPack
final answer
```

It is not M7 completion.

---

# 15. Trial user experience

## 15.1 Explicit save

Conceptual flow:

```text
> /memory save-decision

Decision:
Use SQLite FTS5 for MVP retrieval; do not add a vector database yet.

Confirm save? [y/N]
```

Success:

```text
Decision saved.
Memory ID: ...
Provenance: user-explicit:...
```

Duplicate:

```text
Decision already existed.
Memory ID: ...  # when provided by Memory Contract v1
```

Failure inside the same live operation:

```text
Decision was not saved.
The current save operation may be retried with the same frozen request.
```

Failure after process restart:

```text
The prior save operation cannot be replayed.
Create a new confirmation; duplicate detection will prevent a second record.
```

## 15.2 Recall

```text
> Project đã chốt dùng retrieval nào?
```

Expected:

```text
Project đã chốt dùng SQLite FTS5 cho MVP
và chưa dùng vector database.

Source:
- memory_id: ...
- type: decision
- provenance: user-explicit:...
```

The output should be easy to copy into the user's current coding-agent workflow.

---

# 16. Safety and scope

## 16.1 Allowed external side effect

```text
explicit user-confirmed TOMTIT-Memory write
```

## 16.2 Forbidden

- automatic memory extraction;
- planner-triggered persistence;
- model-generated confirmation;
- model-generated confirmation ID;
- local fallback in remote mode;
- shell;
- code modification;
- Git side effects;
- dynamic plugin loading;
- MCP/A2A;
- multi-agent;
- new Memory endpoints;
- Memory Contract v2.

## 16.3 Required trust boundary

- retrieved memory remains untrusted evidence;
- explicit user confirmation is represented by the closed SF1 contract;
- evidence never grants tool approval;
- Memory service does not become a trust authority;
- confirmation objects are application-created only.

---

# 17. Milestone A workflows

Required workflows:

1. **Save Project Decision**
2. **Project Context Recall**

Removed from Milestone A:

```text
Minimal Project Resume
```

SR3 session resume remains a prerequisite/infrastructure capability, not a new M7 user workflow.

Deferred workflows:

- Project Onboarding;
- Task Planning;
- Web Research;
- Compare and Recommend;
- Session Closeout;
- broad Project Resume.

---

# 18. Packaging requirements

Required:

- fresh Python 3.11 verification;
- setup without source edits;
- documented Agent and Memory startup;
- stable project/user configuration;
- health/readiness diagnostics;
- deterministic test cleanup;
- logs for write/retrieve failures;
- clear remote-backend indicator.

Not required:

- cloud deployment;
- auth system;
- billing;
- dashboard;
- installer;
- MCP server.

---

# 19. Memory Wedge Trial acceptance criteria

## 19.1 Prerequisites

- [ ] SF1 CLOSED, merged and source symbols inventoried.
- [ ] M6 remote backend operational.
- [ ] Fresh Python 3.11 install passes.
- [ ] Product spec v0.3 is verified and accepted.
- [ ] Separate M7-A inventory and implementation spec approved.

## 19.2 Confirmation and operation

- [ ] Application owns confirmation creation.
- [ ] `confirmation_id` is nonblank, stable within one operation and not reused with a different payload.
- [ ] Exact SF1 evidence type is used.
- [ ] Model/planner cannot create confirmation.
- [ ] Exactly one decision per save run.
- [ ] Frozen save operation is immutable.
- [ ] Operation is not stored in SessionState.
- [ ] Operation is not stored in TurnRecord.
- [ ] Operation is not restored on resume.
- [ ] Session resume produces zero additional writes.

## 19.3 Write policy

- [ ] One confirmation maps to one decision candidate.
- [ ] Type is fixed to `decision`.
- [ ] Invalid input fails before MemoryClient.
- [ ] Typed evidence is rendered to wire `evidence_ref`.
- [ ] `project_id` remains client/composition configuration and is not added to AgentState for transport.
- [ ] Memory receives no AgentState or SF1 object.

## 19.4 Required write

- [ ] `written` completes the run.
- [ ] `skipped_duplicate` completes with duplicate disclosure.
- [ ] Response contains exactly one matching result for the submitted candidate.
- [ ] Missing, extra, mismatched or unknown candidate outcome marks the run FAILED.
- [ ] Write failure marks run FAILED.
- [ ] Failed TurnRecord keeps `final_answer=None`.
- [ ] No failure path claims persistence.

## 19.5 Replay and duplicate

- [ ] Retry of one frozen operation preserves the full payload.
- [ ] Same frozen payload replays the stored response.
- [ ] Same request ID with changed payload conflicts.
- [ ] Process restart does not replay old operation.
- [ ] New confirmation with same content returns duplicate.
- [ ] Duplicate creates no second record.

## 19.6 Recall and restart

- [ ] Agent B recalls after Agent A stops.
- [ ] New session recalls same project decision.
- [ ] ContextPack contains decision.
- [ ] Final answer uses the decision.
- [ ] Provenance is visible.
- [ ] Memory service restart preserves recall.
- [ ] Agent C recalls through a new process/client.

## 19.7 Isolation and failure

- [ ] Project A cannot read Project B.
- [ ] User A cannot read User B.
- [ ] Retrieve outage produces degraded state.
- [ ] Write outage produces FAILED outcome.
- [ ] Local fail-on-access sentinel is never called.
- [ ] Remote mode disables local durable-memory tools.

## 19.8 Scope

- [ ] No automatic extraction.
- [ ] No LLM planner dependency.
- [ ] No SF2 dependency.
- [ ] No new Memory endpoint/schema.
- [ ] No MCP/A2A.
- [ ] No broad Agent feature added.

---

# 20. Trial rollout and metrics

## 20.1 Internal dogfood

- save at least 10 confirmed decisions;
- restart Agent between sessions;
- restart Memory service;
- record false recall, missed recall and confusing provenance;
- compare against existing project docs.

## 20.2 Design-partner trial

Target five participants when feasible.

Screener should prefer users matching §4.

Required participation:

- real repository;
- at least one save/restart/recall flow;
- at least two sessions or one session plus restart;
- founder-assisted setup allowed;
- disconfirming feedback recorded.

## 20.3 Product metrics for a five-person trial

| Metric | Trial target |
|---|---:|
| Complete setup | at least 4/5 |
| Complete save–restart–recall | at least 4/5 |
| Provenance increases trust | at least 3/5 |
| Return for second session | at least 2/5 |
| Want to continue using | at least 2/5 |
| Willingness-to-pay or deployment commitment | at least 1 participant |

For fewer than five participants, report raw counts and narratives; do not convert to misleading percentages.

## 20.4 Technical zero-tolerance metrics

| Metric | Target |
|---|---:|
| Silent memory loss | 0 |
| False persistence claim | 0 |
| Project/user isolation failure | 0 |
| Local fallback in remote mode | 0 |
| Duplicate record caused by retry | 0 |
| Missing provenance | 0 |
| Automatic write without confirmation | 0 |

## 20.5 Interview questions

1. Bạn đã phải nhắc lại context bao nhiêu lần gần đây?
2. Explicit save có quá phiền không?
3. Provenance có làm bạn tin câu trả lời hơn không?
4. TOMTIT có hữu ích hơn `CLAUDE.md`, README hoặc manual notes không?
5. Bạn có quay lại dùng ở phiên tiếp theo không?
6. Bạn muốn TOMTIT gợi ý memory candidates tự động không?
7. Bạn có trả tiền hoặc cam kết triển khai capability hiện tại không?

---

# 21. Broader Agent Alpha

Only open after:

```text
M7 CLOSED
trial checkpoint reviewed
SF2 product gate approved
```

Order:

```text
SF2
→ Goal Interpreter
→ Guarded Planner
→ Execution/Replanning
→ Real Web/Workspace
→ Expanded Skills
→ Full Memory UX
```

These capabilities are not part of Memory Wedge Trial.

---

# 22. MCP, A2A and external extensibility

## MCP

Defer until:

1. M7 proves Memory Contract v1 end-to-end.
2. Pilot users want external coding agents to access TOMTIT-Memory.
3. HTTP and client contracts are stable.

Future shape:

```text
Claude Code / Codex / Cursor
→ MCP adapter
→ TOMTIT-Memory HTTP/contract
```

MCP must not create a second schema, persistence path or policy authority.

## A2A

Defer until independent agents exist with separate state, planner and task lifecycle.

## External skills

Dynamic plugin loading is out of scope.

---

# 23. Updated build priority

## Completed or prerequisite foundation

```text
SR1
SR2
SR3
EX1
EX2
M6
```

## Current and immediate sequence

```text
Close SF1
→ finalize and verify PRODUCT_SPEC v0.3
→ fresh Python 3.11 verification
→ M7-A inventory
→ M7-A implementation spec
→ M7-A implement and verify
→ M7-B inventory/spec
→ M7-B black-box E2E
→ minimal packaging
→ dogfood
→ design-partner trial
```

## After product evidence

```text
SF2
Goal Interpreter
Guarded Planner
Execution/Replanning
Real Web/Workspace
Expanded Skills
Full Memory UX
```

Every technical phase follows:

```text
inventory
→ spec
→ review
→ implementation branch
→ tests
→ candidate freeze
→ verification gate
→ human approval
→ merge
```

---

# 24. Final product definitions

## Memory Wedge Trial

Allowed description:

> TOMTIT is a local-first project-memory companion that lets developers save explicitly confirmed project decisions and recall them with provenance across sessions and process restarts.

Not allowed:

> TOMTIT is already an integrated memory layer for Claude Code, Cursor or Codex.

Not allowed:

> TOMTIT automatically knows what should be remembered.

## Long-term vision

> TOMTIT helps coding agents maintain durable project context across sessions.

---

# 25. Finalization gate for this document

Before promoting this document to:

```text
Version: 0.3
Status: ACCEPTED FOR MEMORY WEDGE TRIAL
```

the docs-only candidate must prove:

1. only `PRODUCT_SPEC_MVP_USER_TRIAL.md` changed;
2. all accepted v0.3 corrections are present;
3. no Memory Contract or production code changed;
4. no exact SF1 enum/class names were invented;
5. request replay semantics match full-payload idempotency;
6. `confirmation_id` identity and non-reuse invariants are explicit;
7. run-only/consume-once invariants are explicit;
8. `project_id` remains client/composition configuration rather than AgentState transport data;
9. required-write response consistency is explicit;
10. trial claim and ICP are correctly scoped;
11. Agent→Memory mapping is present;
12. human/architect explicitly approves acceptance.

After acceptance:

```text
M7-A inventory is the next technical step.
M7-A implementation remains unauthorized until its own spec passes gate.
```

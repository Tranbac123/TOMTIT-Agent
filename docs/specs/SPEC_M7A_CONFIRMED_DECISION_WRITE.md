# SPEC_M7A_CONFIRMED_DECISION_WRITE

**Version:** `1.2`
**Status:** `FROZEN FOR IMPLEMENTATION AUTHORIZATION REVIEW`
**Repository:** `TOMTIT-Agent`
**Authoritative baseline:** `main@0e55156ce13243386e12cb04c4aab061033cc566`
**Verification process:** `docs/standards/VERIFICATION_GATE.md`
**Depends on:** M6 CLOSED, SF1 CLOSED, Product Spec v0.3 CLOSED, Architecture v1.0 CLOSED, fresh Python 3.11 baseline PASS
**Inventory evidence:** `REPORT_M7A_CONFIRMED_DECISION_WRITE_INVENTORY_VERIFIED.md`
**Inventory SHA-256:** `4c9d5e044ac7955f00337d7c5058e1f98ee9a7d3da19ac3f2a4cd2d1468f16ec`
**Inventory custody at draft time:** repository-local read-only evidence; it must be committed or cited by exact SHA in the implementation authorization

---

## Revision note — v1.2-draft

This revision keeps the M7-A product scope unchanged and closes the final pre-freeze defects in:

- fail-closed transport-neutral required-write capability owned by `MemoryClientProtocol`, eliminating capability/client drift;
- exact `MemoryCandidate` → wire `candidate_id` mapping;
- application-owned `user_id`;
- failure-message versus `TurnRecord` semantics;
- intentional persistence of safe provenance text;
- replay-ready request construction versus real server replay;
- response envelope correlation;
- error taxonomy and logging data minimization;
- inventory evidence custody;
- complete protocol-double test-manifest coverage;
- removal of `MemoryBackendComponents.required_write_enabled` and `RuntimeAgent.required_memory_write_enabled` from the proposed design.

Implementation remains unauthorized.

# 0. Document authority and implementation gate

This specification defines **M7-A — Dedicated Confirmed-Decision Write** for TOMTIT-Agent.

This document is not implementation authorization while its status remains:

```text
DRAFT FOR ARCHITECT REVIEW — IMPLEMENTATION NOT AUTHORIZED
```

The implementation phase may begin only after:

1. this document is reviewed;
2. all architect decisions in §5 are explicitly accepted;
3. the approved document is frozen at a committed revision;
4. its SHA-256 is recorded;
5. the inventory evidence is either committed at a canonical path or cited by the exact SHA-256 recorded above;
6. a separate implementation instruction cites the exact accepted spec revision and inventory evidence;
7. the implementation candidate later passes `VERIFICATION_GATE.md`.

Normative precedence for M7-A:

```text
accepted Product Spec v0.3
→ accepted SPEC_M7A
→ VERIFICATION_GATE.md
→ frozen verification evidence
→ current implementation
→ Architecture v1.0 explanatory text
```

This specification does not authorize M7-B, SF2, LLM activation, MCP, A2A, automatic memory extraction, or external-agent integration.

---

# 1. Objective

M7-A adds one deterministic, explicit, required-write workflow:

```text
user invokes a structured save-decision command
→ user explicitly confirms the decision
→ application creates typed SF1 confirmation evidence
→ application creates one immutable ConfirmedSaveOperation
→ AgentState carries that operation as run-only input
→ RuntimeAgent validates and writes exactly one decision
→ TOMTIT-Memory returns written or skipped_duplicate
→ RuntimeAgent completes or fails the run truthfully
```

The capability claim after M7-A is limited to:

> TOMTIT-Agent can submit one explicitly user-confirmed project decision to TOMTIT-Memory with deterministic provenance and required-write failure semantics.

M7-A alone does **not** prove cross-process recall. That belongs to M7-B.

---

# 2. Product invariants

The following invariants are mandatory.

## 2.1 Confirmation authority

```text
model output != user confirmation
planner output != user confirmation
memory evidence != user confirmation
```

Only the application boundary may create the confirmation identity and trusted confirmation evidence.

A natural-language message such as:

```text
Remember that we use PostgreSQL.
```

is not sufficient authorization for persistence.

The accepted structured CLI path is:

```text
/memory save-decision
```

followed by explicit content entry and a positive confirmation prompt.

## 2.2 One operation, one decision

Each `ConfirmedSaveOperation` contains exactly one `ConfirmedDecision`.

M7-A does not support:

- zero decisions after a save operation has been requested;
- batches;
- compound task-and-save runs;
- multiple memory types;
- automatic candidate extraction.

## 2.3 Required write

An explicit confirmed save is a required side effect.

```text
written
→ COMPLETED

skipped_duplicate
→ COMPLETED

transport/contract/consistency/backend failure
→ FAILED
→ no saved claim
```

The current best-effort `_write_memory()` path is forbidden for M7-A.

## 2.4 Remote only

M7-A writes only when the bound `MemoryClientProtocol` implementation explicitly advertises the **required-write capability** under existing Memory Contract v1.

`RuntimeAgent` remains transport-neutral: it depends only on `MemoryClientProtocol` and checks `memory_client.supports_required_write`. It must not import, inspect or type-check `RemoteMemoryClient`, and there is no separate runtime boolean that can drift from the bound client.

Production client capabilities are fixed and fail-closed:

```text
RemoteMemoryClient → True
LocalMemoryClient  → False
NullMemoryClient   → False
```

Local and none backends must fail before any write call or local-store access.

There is no local fallback.

## 2.5 Run-only input

The confirmed operation:

- exists only for the explicit save run;
- is not persisted in `SessionState`;
- is not persisted in `TurnRecord`;
- is not restored on session resume;
- is not placed in `slots`;
- is not inferred from observations, planner output, tool output, or final answers.

A COMPLETED save may intentionally persist a deterministic final-answer string containing the memory ID and safe provenance reference. This does not serialize the operation, evidence object, decision content, request payload, or replayable command.

---

# 3. Explicit non-goals

M7-A must not add or enable:

- autonomous memory extraction;
- LLM evaluation of what should be remembered;
- planner-generated memory candidates;
- a remote `save_decision` tool;
- local durable-memory fallback;
- new TOMTIT-Memory endpoint;
- Memory Contract v2;
- Memory wire-schema changes;
- generic retry controller;
- circuit breaker;
- new `AgentStatus` values;
- multi-decision write;
- project resume;
- retrieval or restart E2E;
- SF2 prompt-injection enforcement;
- MCP or A2A;
- dynamic plugins;
- broad refactoring of RuntimeAgent, SessionRuntime, planner, skills, or tools.

---

# 4. Verified baseline facts

At baseline `0e55156ce13243386e12cb04c4aab061033cc566`:

1. `AgentState` has one production construction site in `SessionRuntime`.
2. `confirmed_save_operation` does not exist.
3. `EvidenceEnvelope` is a frozen SF1 dataclass.
4. Explicit user confirmation maps to:
   - `SourceType.USER`;
   - `TrustLevel.TRUSTED_INSTRUCTION`.
5. `_collect_candidates()` returns an empty list.
6. `_write_memory()` is best-effort and swallows write failures into disclosure state.
7. `MemoryClientProtocol` is defined in `agent_core/memory/client.py`; it currently has neither a required-write capability property nor a per-call `request_id` parameter.
8. `RemoteMemoryClient` generates `request_id` internally through `request_id_factory`.
9. `MemoryCandidate` has no typed `candidate_id` field. The current remote adapter reads the exact metadata key `"candidate_id"` and otherwise falls back to an index-derived ID.
10. Memory Contract v1 already contains:
   - request ID;
   - task ID;
   - optional session correlation;
   - candidate ID;
   - `decision` memory type;
   - `written` and `skipped_duplicate` statuses;
   - `IDEMPOTENCY_CONFLICT` error code.
11. `RemoteMemoryClient` does not fully verify result-count and candidate-correlation consistency before returning the domain `WriteResponse`.
12. Planner, skills and tools contain no confirmed-decision path.
13. `AgentStatus.CREATED`, `COMPLETED` and `FAILED` are sufficient for M7-A.
14. The full regression baseline is `468 passed`.

---

# 5. Architect decisions — locked by this specification

## M7A-D01 — Application seam

**Decision:** add a dedicated structured save path.

```text
CLI meta-command
→ SessionRuntime.run_confirmed_decision_save(operation)
→ RuntimeAgent.run_confirmed_save(state)
```

`SessionRuntime.handle_turn()` remains natural-language only.

## M7A-D02 — AgentState field

**Decision:** add one singular optional run-input field:

```python
confirmed_save_operation: ConfirmedSaveOperation | None = None
```

It must be appended as the final dataclass field.

The field is additive, defaults to `None`, and is not serialized by session persistence.

## M7A-D03 — Domain package

**Decision:** create:

```text
agent_core/confirmation/
```

This package owns confirmed-save domain models, evidence construction, mapping policy, typed errors and required-write validation.

## M7A-D04 — Domain models

**Decision:** use frozen dataclasses for `ConfirmedDecision` and `ConfirmedSaveOperation`.

Neither is a wire DTO.

## M7A-D05 — Evidence construction

**Decision:** use a narrow application-side factory. Callers must not hand-roll trusted evidence.

## M7A-D06 — Source-reference format

**Decision:**

```text
user-explicit:<task_id>:<confirmation_id>
```

## M7A-D07 — Request-ID formula and caller control

**Decision:**

```text
request_id = memory-write:<confirmation_id>
```

The Agent memory-client protocol receives a new additive optional per-call parameter:

```python
request_id: str | None = None
```

Behavior:

```text
provided request_id
→ RemoteMemoryClient uses it unchanged

request_id is None
→ preserve existing request_id_factory behavior
```

This is an Agent-side protocol/API change only. It does not change Memory Contract v1 or HTTP JSON.

## M7A-D08 — Session correlation

**Decision:** the domain type remains `session_id: str | None` to match Memory Contract v1, but the M7-A `SessionRuntime` command requires a nonblank current session ID and rejects `None`.

## M7A-D09 — Policy owner

**Decision:** `ConfirmedMemoryWritePolicy` is separate from tool `PolicyEngine`.

## M7A-D10 — Runtime seam

**Decision:** add `RuntimeAgent.run_confirmed_save(state)`.

It must not call retrieval, planner, skills, steps, ToolExecutor or model-based FinalComposer.

## M7A-D11 — Response validation ownership

**Decision:** two validation layers are required:

1. `RemoteMemoryClient` validates wire-level result count and candidate correlation before collapsing the wire response into `WriteResponse`.
2. `confirmation.required_write` validates the one-candidate domain outcome and maps it to an internal required-write result.

This split is required because candidate identity exists at the wire result boundary and may be lost when converted to the generic `WriteResponse`.

## M7A-D12 — Consume-once

**Decision:** a terminal `AgentState` cannot write again. The dedicated runtime method must return immediately or fail loudly when called with a terminal state.

No session resume path may reconstruct or automatically re-run the operation.

## M7A-D13 — Retry ownership and proof boundary

**Decision:** no automatic retry controller is added.

M7-A proves **replay-stable request construction**: reusing the same frozen operation produces the same request ID, task ID, session ID, candidate order and candidate payload.

M7-A does not claim that TOMTIT-Memory replayed a previously stored response. Real server replay is an M7-B integration proof against an exact TOMTIT-Memory revision.

## M7A-D14 — TurnRecord

**Decision:** a dedicated save attempt produces a normal `TurnRecord` for audit continuity.

The structured operation, `EvidenceEnvelope`, decision content, request payload and request ID are not serialized as session fields. A COMPLETED `final_answer` may intentionally contain the memory ID and safe provenance reference for auditability.

## M7A-D15 — Backend capability gate

**Decision:** the required-write capability belongs to `MemoryClientProtocol`, not to a separate runtime boolean.

The protocol exposes a read-only property:

```python
@property
def supports_required_write(self) -> bool:
    ...
```

Production values are fixed:

```text
RemoteMemoryClient → True
LocalMemoryClient  → False
NullMemoryClient   → False
```

`RuntimeAgent.run_confirmed_save()` checks the bound client capability before any write or store access:

```python
if self.memory_client is None or not self.memory_client.supports_required_write:
    ...
```

`RuntimeAgent` must not import, inspect or use `isinstance(..., RemoteMemoryClient)`. No `required_memory_write_enabled` constructor argument or `MemoryBackendComponents.required_write_enabled` field is allowed.

This design keeps the runtime transport-neutral, makes manual composition fail closed for Local/Null clients, and removes the possibility that a separately injected boolean disagrees with the actual client. Existing split-brain validation remains unchanged.

## M7A-D16 — File manifest

**Decision:** only files listed in §19 may change.

## M7A-D17 — Memory Contract sufficiency

**Decision:** Memory Contract v1 is sufficient. No endpoint, DTO or fixture schema changes are permitted.

---

# 6. Domain contracts

## 6.1 `ConfirmedDecision`

**File:** `agent_core/confirmation/models.py`
**Class:** `ConfirmedDecision`

Required shape:

```python
from dataclasses import dataclass

from agent_core.safety.evidence import EvidenceEnvelope


@dataclass(frozen=True)
class ConfirmedDecision:
    confirmation_id: str
    content: str
    confirmation_evidence: EvidenceEnvelope
```

Required model invariants:

1. `confirmation_id` must be `str`.
2. Leading and trailing whitespace are stripped.
3. Blank confirmation ID raises `ValueError`.
4. `content` must be `str`.
5. Leading and trailing whitespace are stripped; internal whitespace is preserved.
6. Blank content raises `ValueError`.
7. `confirmation_evidence` must be an `EvidenceEnvelope`.
8. The model does not accept raw `evidence_ref` as an alternative.
9. The model is frozen.
10. The same confirmation ID must never be reused by the application for a different payload.

Basic type/nonblank normalization belongs in `__post_init__`. Trust/source/reference consistency belongs to `ConfirmedMemoryWritePolicy`.

## 6.2 `ConfirmedSaveOperation`

**File:** `agent_core/confirmation/models.py`
**Class:** `ConfirmedSaveOperation`

Required shape:

```python
@dataclass(frozen=True)
class ConfirmedSaveOperation:
    request_id: str
    task_id: str
    session_id: str | None
    decision: ConfirmedDecision
```

Required invariants:

1. `request_id`, `task_id` are stripped and nonblank.
2. `session_id`, when not `None`, is stripped and nonblank. The M7-A SessionRuntime path additionally requires it to equal the current nonblank session ID.
3. `decision` must be `ConfirmedDecision`.
4. The operation contains exactly one decision by construction.
5. `request_id` must equal:

```text
memory-write:<decision.confirmation_id>
```

6. The operation is frozen.
7. It contains neither `project_id` nor `user_id`.
8. It contains no planner, tool, Memory wire or HTTP object.

## 6.3 Request-ID helper

**File:** `agent_core/confirmation/models.py`
**Function:** `confirmed_memory_request_id(confirmation_id: str) -> str`

Required behavior:

```python
def confirmed_memory_request_id(confirmation_id: str) -> str:
    normalized = confirmation_id.strip()
    if not normalized:
        raise ValueError("confirmation_id must be nonblank")
    return f"memory-write:{normalized}"
```

The helper must not include `task_id` or `session_id`.

---

# 7. Typed confirmation evidence

## 7.1 Factory

**File:** `agent_core/confirmation/evidence_factory.py`
**Function:** `make_confirmation_evidence`

Required signature:

```python
def make_confirmation_evidence(
    *,
    task_id: str,
    confirmation_id: str,
    content: str,
) -> EvidenceEnvelope:
    ...
```

Required output:

```python
EvidenceEnvelope(
    content=<normalized confirmed content>,
    source_type=SourceType.USER,
    trust_level=TrustLevel.TRUSTED_INSTRUCTION,
    source_ref=f"user-explicit:{task_id}:{confirmation_id}",
    metadata={"confirmation_id": confirmation_id},
)
```

Required validation:

- task ID nonblank;
- confirmation ID nonblank;
- content nonblank;
- source reference contains normalized values;
- no model/planner parameter;
- no raw caller-provided trust/source enum;
- no raw caller-provided `source_ref`.

The factory is the only application-facing constructor for trusted confirmation evidence in M7-A.

## 7.2 Evidence is not authorization at Memory boundary

The rendered `evidence_ref` is provenance metadata only.

TOMTIT-Memory does not receive `EvidenceEnvelope` and does not verify user confirmation.

---

# 8. AgentState extension

**File:** `agent_core/state/agent_state.py`
**Class:** `AgentState`
**Field:** `confirmed_save_operation`

Required change:

```python
confirmed_save_operation: ConfirmedSaveOperation | None = None
```

Placement: final dataclass field, after all existing fields.

Required properties:

- default `None`;
- no change to existing field names/defaults/order;
- no change to `AgentState` persistence because AgentState is not persisted as a whole;
- no addition of `project_id`;
- no use of `slots` for this input;
- no serialization into `TurnRecord` or `SessionState`;
- type-only import must avoid circular dependency.

Trade-off:

- modifies a guarded public contract;
- accepted because the change is additive, singular, explicit and central to state-first execution.

---

# 9. Memory client capability and request-ID seam

## 9.1 Protocol

**File:** `agent_core/memory/client.py`
**Protocol:** `MemoryClientProtocol`
**Method:** `write_memory_candidates`

Required protocol additions:

```python
@property
def supports_required_write(self) -> bool:
    ...

def write_memory_candidates(
    self,
    candidates: list[MemoryCandidate],
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
    request_id: str | None = None,
) -> WriteResponse:
    ...
```

The capability property is read-only and fail-closed by implementation. The new `request_id` parameter is keyword-only and optional.

## 9.2 Remote implementation

**File:** `agent_core/memory/remote_client.py`
**Class:** `RemoteMemoryClient`
**Method:** `write_memory_candidates`

Required capability implementation:

```python
@property
def supports_required_write(self) -> bool:
    return True
```

Required request-ID behavior:

```text
request_id provided
→ strip/validate nonblank
→ use exact value in WriteRequestV1
→ do not invoke request_id_factory

request_id is None
→ invoke existing request_id_factory exactly once
→ preserve current behavior
```

No mutable replacement of the client-level factory is allowed per operation.

## 9.3 Local and null implementations

**Files:**

- `agent_core/memory/local_client.py`
- `agent_core/memory/null_client.py`

Required capability implementation in both clients:

```python
@property
def supports_required_write(self) -> bool:
    return False
```

Required request-ID compatibility:

- accept the optional keyword parameter;
- preserve current behavior;
- do not add remote idempotency semantics;
- M7-A rejects these clients before the method is called.

## 9.4 Test doubles

Every `MemoryClientProtocol` implementation and test stub must:

- expose `supports_required_write`;
- accept the optional `request_id` parameter or intentionally use `**kwargs` where existing conventions allow;
- default to fail-closed (`False`) unless it is explicitly modeling a required-write-capable remote client.

---

# 10. Candidate identity mapping and wire-level response consistency

## 10.1 Exact candidate identity mapping

`MemoryCandidate` does not have a typed `candidate_id` field.

For M7-A, `ConfirmedMemoryWritePolicy` must set:

```python
metadata={"candidate_id": operation.decision.confirmation_id}
```

The existing remote adapter reads the exact key `"candidate_id"` when constructing `WriteCandidateV1.candidate_id`.

Normative rules:

1. the M7-A policy supplies a normalized, nonblank string;
2. M7-A must never rely on the adapter's index-derived fallback;
3. `WriteRequestV1` remains the owner of duplicate candidate-ID rejection;
4. the adapter may preserve its fallback for non-M7 callers;
5. the metadata dictionary is also copied into the wire candidate metadata under current behavior;
6. M7-A does not rely on TOMTIT-Memory persisting that metadata key—the authoritative request identity is the typed wire `candidate_id`.

The adapter must construct the wire candidate list exactly once per call. The resulting wire candidate IDs are the expected set for response correlation.

## 10.2 Response-envelope correlation

**File:** `agent_core/memory/remote_client.py`
**Class:** `RemoteMemoryClient`
**Method:** `write_memory_candidates`

Before converting `WriteResponseV1` into domain `WriteResponse`, the client must verify:

1. response `request_id` equals the submitted request ID;
2. response `project_id` equals the configured project ID;
3. response `user_id` equals the resolved request user ID;
4. response `session_id` equals the submitted session ID;
5. result count equals submitted candidate count;
6. every submitted wire candidate ID appears exactly once;
7. no unknown candidate ID appears;
8. no duplicate result candidate ID appears;
9. every `written` result contains the nonblank memory ID required by the current wire contract;
10. every `skipped_duplicate` result maps to the submitted candidate ID and uses the wire-approved duplicate reason;
11. status remains restricted by `WriteStatusV1`.

Any failure raises `RemoteMemoryWriteError` and no success response is returned.

This validation is generic transport-contract protection, not M7-specific policy.

No wire DTO or fixture shape may change.

## 10.3 Content-size discipline

The current Agent and Memory Contract v1 models define no explicit M7-A decision-content maximum. This specification must not invent an arbitrary limit.

If an accepted Memory Contract revision introduces a limit before implementation, the policy must enforce that exact limit before HTTP; otherwise existing Pydantic/wire/server validation remains authoritative.


---

# 11. Confirmed memory write policy

## 11.1 Class

**File:** `agent_core/confirmation/write_policy.py`
**Class:** `ConfirmedMemoryWritePolicy`

Required public method:

```python
def to_candidate(
    self,
    *,
    operation: ConfirmedSaveOperation,
    state: AgentState,
) -> MemoryCandidate:
    ...
```

## 11.2 Validation

The policy must reject before client access when:

- state has no confirmed operation;
- provided operation does not equal the state operation;
- state task ID is blank;
- state user ID is blank;
- operation task ID differs from state task ID;
- operation session ID differs from state session ID;
- request ID differs from `memory-write:<confirmation_id>`;
- confirmation ID is blank;
- content is blank;
- evidence content differs from normalized decision content;
- evidence source type is not `SourceType.USER`;
- evidence trust level is not `TrustLevel.TRUSTED_INSTRUCTION`;
- evidence source reference is absent or differs from:

```text
user-explicit:<operation.task_id>:<confirmation_id>
```

## 11.3 Candidate mapping

The policy returns exactly one:

```python
MemoryCandidate(
    type=MemoryType.DECISION,
    content=operation.decision.content,
    tags=[],
    importance=0.5,
    confidence=1.0,
    evidence_ref=operation.decision.confirmation_evidence.source_ref,
    metadata={"candidate_id": operation.decision.confirmation_id},
)
```

These values freeze the full one-candidate payload used for replay-stable request construction. No M7-A-specific content-size limit may be invented outside the accepted Memory Contract.

The policy must not:

- call `MemoryClientProtocol`;
- call HTTP/store;
- execute a tool;
- inspect planner output;
- manage project ID;
- perform duplicate detection;
- mutate AgentState;
- create trusted evidence.

---

# 12. Required-write outcome checker

## 12.1 Types

**File:** `agent_core/confirmation/required_write.py`

Required internal enum:

```python
class RequiredWriteStatus(StrEnum):
    WRITTEN = "written"
    SKIPPED_DUPLICATE = "skipped_duplicate"
```

Required internal result:

```python
@dataclass(frozen=True)
class RequiredWriteOutcome:
    status: RequiredWriteStatus
    memory_id: str | None = None
```

## 12.2 Checker

Required function:

```python
def validate_required_write_response(
    response: WriteResponse,
    *,
    expected_candidate_id: str,
) -> RequiredWriteOutcome:
    ...
```

Accepted domain outcomes:

```text
exactly one written ID and zero skipped IDs
→ WRITTEN
→ memory_id is the written ID

zero written IDs and skipped == [expected_candidate_id]
→ SKIPPED_DUPLICATE
→ memory_id is None unless the current domain response already carries one
```

Rejected outcomes:

- zero written and zero skipped;
- more than one written;
- more than one skipped;
- written and skipped both nonempty;
- skipped ID differs from expected candidate ID;
- blank written ID;
- any malformed structure.

Wire-level candidate correlation for written results must already have been proven by `RemoteMemoryClient` under §10.

---

# 13. Typed errors

**File:** `agent_core/confirmation/errors.py`

Required hierarchy:

```python
class ConfirmedWriteError(RuntimeError):
    pass


class ConfirmedWriteValidationError(ConfirmedWriteError):
    pass


class ConfirmedWriteBackendError(ConfirmedWriteError):
    pass


class RequiredWriteConsistencyError(ConfirmedWriteError):
    pass
```

Domain-model `__post_init__` may use `ValueError` for direct construction errors.

Policy, backend gate and response checker use the typed errors above.

Existing `RemoteMemoryConfigurationError`, `RemoteMemoryContractError`, `RemoteMemoryUnavailableError` and `RemoteMemoryWriteError` remain the transport/configuration taxonomy. A confirmed-write wrapper must preserve the original exception with `raise ... from exc`; it must not erase whether the cause was validation, timeout/transport, HTTP/backend, contract/schema, idempotency conflict or response consistency.

No raw exception message may be returned as a successful or persisted final answer.

## 13.2 Logging and diagnostic minimization

Logs and `state.errors` must not contain:

- decision content;
- `EvidenceEnvelope.content`;
- full request/response payloads;
- access tokens, secrets or configuration credentials.

Logs may contain:

- task ID;
- confirmation ID;
- request ID;
- session ID;
- safe error category/type;
- latency;
- stack trace without request/response bodies.

`state.errors` should record a safe category/code, not raw remote response content.

---

# 14. RuntimeAgent dedicated lifecycle

**File:** `agent_core/runtime/runtime_agent.py`
**Class:** `RuntimeAgent`
**Method:** `run_confirmed_save`

Required signature:

```python
def run_confirmed_save(self, state: AgentState) -> AgentState:
    ...
```

## 14.1 Preconditions

The method must:

1. require `state.status == AgentStatus.CREATED` and `not state.done`;
2. require `state.confirmed_save_operation is not None`;
3. require a bound memory client whose `supports_required_write` property is `True` before any write;
4. not call `_retrieve_memory()`;
5. not call planner;
6. not create `Step` objects;
7. not call `ToolExecutor`;
8. not call ordinary `_collect_candidates()`;
9. not call best-effort `_write_memory()`;
10. not call model-based final composition.

## 14.2 Required flow

```text
read operation from AgentState
→ remote-only backend guard
→ ConfirmedMemoryWritePolicy.to_candidate
→ MemoryClientProtocol.write_memory_candidates(
       [candidate],
       user_id=state.user_id,
       session_id=state.session_id,
       task_id=state.task_id,
       request_id=operation.request_id,
   )
→ validate_required_write_response
→ complete or fail
```

## 14.3 Completion messages

Written:

```text
Decision saved.
Memory ID: <memory_id>
Provenance: <source_ref>
```

Duplicate:

```text
Decision already existed.
Provenance: <source_ref>
```

If the current Memory Contract provides a duplicate memory ID, it may be added. M7-A must not invent one.

Failure:

```text
Decision was not saved.
```

No raw transport, HTTP, schema or stack-trace text is included in the user-facing failure message.

## 14.4 Failure behavior

For validation/backend/transport/contract/consistency failure:

- set terminal `FAILED` through `state.fail("Decision was not saved.")`;
- preserve only a safe diagnostic category in `state.errors` and preserve the original exception as the logged cause;
- set `memory_write_failed=True` only when a client write was attempted or response validation failed;
- never call `state.complete()`;
- never claim saved;
- return the terminal state.

Current `AgentState.fail()` sets the in-memory `final_answer` to the safe failure string. `SessionRuntime` must continue masking `final_answer` to `None` when creating a FAILED `TurnRecord`. The CLI may print the safe in-memory failure string, but that string is not persisted in session history.

Unexpected exceptions must be logged with stack trace under the data-minimization rules in §13.2 and converted to the same safe FAILED outcome.

## 14.5 Completion authority

Only `RuntimeAgent.run_confirmed_save()` calls `state.complete()` or `state.fail()` for this run.

The CLI and SessionRuntime must not mark the state terminal.

---

# 15. SessionRuntime integration

**File:** `agent_core/runtime/session_runtime.py`
**Class:** `SessionRuntime`

## 15.1 Session identity and constructor change

**File:** `agent_core/runtime/session_runtime.py`
**Class:** `SessionRuntime`

Add an optional keyword-only constructor parameter:

```python
user_id: str | None = None
```

The constructor stores a normalized application-owned identity as `self._user_id`. Blank non-`None` values are rejected.

For the CLI remote backend, `main.py` passes the same `--memory-user-id` application configuration used to build the remote memory backend. The save path must not recover identity from decision text, evidence metadata, planner output or a hidden client default.

Existing callers remain compatible because the parameter defaults to `None`.

## 15.2 New method

```python
def run_confirmed_decision_save(
    self,
    operation: ConfirmedSaveOperation,
) -> AgentState:
    ...
```

Required behavior:

1. require a nonblank `self._user_id`;
2. require operation session ID to be nonblank and equal the current session ID;
3. construct a new `AgentState` with:
   - fixed safe goal: `"Persist confirmed project decision"`;
   - `task_id=operation.task_id`;
   - `user_id=self._user_id`;
   - current session ID;
   - current shared memory store;
   - `confirmed_save_operation=operation`;
4. call only `self._agent.run_confirmed_save(state)`;
5. require returned state to be terminal;
6. create a `TurnRecord` using the same persistence and anti-leak rules as `handle_turn()`;
7. persist candidate SessionState before mutating live SessionState when a session store is active;
8. return state.

## 15.3 Shared terminal-record helper

To avoid duplicating SR2/SR3 persistence logic, `SessionRuntime` may extract a private helper from `handle_turn()`:

```python
def _record_terminal_state(self, state: AgentState) -> None:
    ...
```

The helper may be used by both natural-language and confirmed-save paths.

The refactor must preserve all existing SR2/SR3 tests and persist-before-mutate behavior.

## 15.4 TurnRecord rules

For M7-A:

- `goal` is the fixed safe goal, not the decision content;
- `planned_actions` is empty;
- COMPLETED persists the deterministic final answer, which may intentionally contain the memory ID and `user-explicit:<task_id>:<confirmation_id>` provenance reference;
- FAILED persists `final_answer=None`, even though the returned in-memory AgentState contains the safe failure message;
- operation, `EvidenceEnvelope`, decision content, full request payload and request ID are not serialized as TurnRecord fields;
- the provenance reference embedded in a successful final answer is deliberate audit output and is not a replayable operation.

---

# 16. CLI structured confirmation boundary

**File:** `agent_core/cli.py`
**Function:** `run_interactive`

## 16.1 Command

Add a meta-command intercepted before `handle_turn()`:

```text
/memory save-decision
```

It must never enter the planner.

## 16.2 Interaction

Required flow:

```text
Decision:
<read one nonblank decision string>

Confirm save? [y/N]
```

Only explicit `y` or `yes` proceeds. Any other response cancels with zero operation creation and zero write.

After positive confirmation, the application boundary:

1. generates `confirmation_id = str(uuid4())`;
2. generates `task_id = str(uuid4())`;
3. calls `make_confirmation_evidence(...)`;
4. creates `ConfirmedDecision`;
5. creates `ConfirmedSaveOperation` with:
   - request ID from `confirmed_memory_request_id()`;
   - current session ID;
6. calls `SessionRuntime.run_confirmed_decision_save(operation)`;
7. prints `state.final_answer` when present; for FAILED, it may fall back only to the fixed string `"Decision was not saved."`.

`user_id` is not generated by the CLI command. It comes from the application composition passed into `SessionRuntime`.

The model, planner and RuntimeAgent do not generate either ID.

## 16.3 Retry behavior

M7-A adds no automatic retry loop.

A live application caller may retain the same frozen operation, but the CLI MVP adds no interactive retry command.

M7-A tests must prove that two client calls made from the same frozen operation construct identical request identity and candidate payload. They must not claim that a real TOMTIT-Memory server replayed a stored response.

Re-running the CLI command creates a new confirmation and therefore exercises duplicate semantics, not same-request replay.

---

# 17. Backend capability and split-brain gate

## 17.1 Protocol-owned capability

**File:** `agent_core/memory/client.py`
**Protocol:** `MemoryClientProtocol`

Add the read-only property:

```python
@property
def supports_required_write(self) -> bool:
    ...
```

Required production values:

```text
RemoteMemoryClient → True
LocalMemoryClient  → False
NullMemoryClient   → False
```

The capability is part of the client contract itself. There is no separate capability field in `MemoryBackendComponents` and no separate capability constructor argument in `RuntimeAgent`.

## 17.2 Runtime capability check

**File:** `agent_core/runtime/runtime_agent.py`
**Class:** `RuntimeAgent`

`RuntimeAgent.run_confirmed_save()` checks only the bound protocol capability:

```python
if self.memory_client is None or not self.memory_client.supports_required_write:
    # fail safely before write/store access
```

`RuntimeAgent` must not import `RemoteMemoryClient`, use `isinstance`, or infer capability from tool registration.

The default `RuntimeAgent(memory_client=None)` remains fail-closed. Manual construction with `LocalMemoryClient` or `NullMemoryClient` also fails closed because those implementations expose `False`.

## 17.3 Composition and required save behavior

Existing composition roots remain the authority for selecting the client:

```text
build_local_agent()
→ LocalMemoryClient
→ supports_required_write == False

build_memory_backend(LOCAL)
→ LocalMemoryClient
→ False

build_memory_backend(NONE)
→ NullMemoryClient
→ False

build_memory_backend(REMOTE)
→ RemoteMemoryClient
→ True
```

No additional boolean is passed through composition.

Required local/none behavior:

```text
FAILED
zero write_memory_candidates calls
zero local-store access
zero planner/tool calls
no saved claim
```

Tests must cover both:

1. production factory selection and capability values;
2. manually constructed `RuntimeAgent` instances bound to Local/Null clients, proving fail-closed behavior before write/store access.

The existing `validate_memory_activation()` split-brain check and remote-mode disabled-tool set remain unchanged.

M7-A must not re-enable:

- `save_decision`;
- `write_note`;
- `save_fact`;
- `save_preference`;
- other local durable-memory tools.

`project_id` remains inside remote memory-client configuration.


---

# 18. Idempotency, replay-ready construction and duplicate semantics

## 18.1 Replay-ready request construction

For an identical frozen operation, the Agent must construct:

```text
same request_id
same task_id
same session_id
same user/project configuration
same candidate order
same candidate ID
same candidate payload
```

M7-A proves this request stability with unit/transport tests. It does **not** prove the server returned a stored replay response.

The same confirmation ID must never be reused with different content. Real stored-response replay is verified in M7-B against an exact TOMTIT-Memory revision.

## 18.2 Conflict

```text
same request_id
+ different full payload
→ IDEMPOTENCY_CONFLICT/error response
→ RemoteMemoryWriteError
→ FAILED
```

M7-A does not depend on a particular HTTP status code; any non-success Memory error envelope is a failure.

## 18.3 Exact duplicate

```text
new confirmation ID
new request ID
same normalized decision content
same project/user/type scope
→ skipped_duplicate
→ COMPLETED
```

## 18.4 Process restart

The operation is not persisted.

After restart, the old operation is not replayed. A new explicit confirmation creates a new operation.

M7-A verifies that the new operation has a new confirmation/request ID and can consume `skipped_duplicate`. Real duplicate detection and record-count behavior belong to M7-B integration with TOMTIT-Memory.

---

# 19. Exact implementation file manifest

## 19.1 Required new production files

| Path | Class/function | Responsibility |
|---|---|---|
| `agent_core/confirmation/__init__.py` | exports | stable package surface |
| `agent_core/confirmation/models.py` | `ConfirmedDecision`, `ConfirmedSaveOperation`, `confirmed_memory_request_id` | immutable run-input models |
| `agent_core/confirmation/evidence_factory.py` | `make_confirmation_evidence` | application-owned typed SF1 evidence |
| `agent_core/confirmation/errors.py` | typed errors | domain/backend/consistency failures |
| `agent_core/confirmation/write_policy.py` | `ConfirmedMemoryWritePolicy` | validate/map one decision candidate |
| `agent_core/confirmation/required_write.py` | status/result/checker | required-write semantic validation |

## 19.2 Required modified production files

| Path | Class/function | Exact change | Why | Trade-off |
|---|---|---|---|---|
| `agent_core/state/agent_state.py` | `AgentState` | append `confirmed_save_operation` | state-first run input | guarded public contract grows |
| `agent_core/memory/client.py` | `MemoryClientProtocol.supports_required_write`, `write_memory_candidates` | add read-only capability property + optional per-call `request_id` | fail-closed remote-only gate + replay-stable operation | protocol implementations and doubles must update |
| `agent_core/memory/remote_client.py` | capability property, `write_memory_candidates` | `supports_required_write=True`, caller ID precedence + wire result consistency | correct remote capability/idempotency/correlation | slightly stricter generic client |
| `agent_core/memory/local_client.py` | capability property, `write_memory_candidates` | `supports_required_write=False`, accept optional request ID | fail-closed protocol conformance | parameter unused |
| `agent_core/memory/null_client.py` | capability property, `write_memory_candidates` | `supports_required_write=False`, accept optional request ID | fail-closed protocol conformance | parameter unused |
| `agent_core/runtime/runtime_agent.py` | `run_confirmed_save`; existing constructors/factories verified | check protocol capability + dedicated required-write lifecycle | completion authority without adapter coupling or drift | new explicit path |
| `agent_core/runtime/session_runtime.py` | constructor, `run_confirmed_decision_save`, optional private helper | application user identity + typed run + TurnRecord | audit continuity | small SR2/SR3 refactor risk |
| `agent_core/cli.py` | `run_interactive` | `/memory save-decision` command | explicit confirmation boundary | CLI surface grows |
| `main.py` | `main` composition | pass application-owned memory user ID into SessionRuntime | explicit identity authority | composition signature grows |

## 19.3 Required tests

| Path | Status | Coverage |
|---|---|---|
| `tests/test_confirmed_decision_models.py` | NEW | models, normalization, immutability, request ID |
| `tests/test_confirmation_evidence_factory.py` | NEW | exact SF1 evidence shape |
| `tests/test_confirmed_write_policy.py` | NEW | validation and candidate mapping |
| `tests/test_confirmed_required_write.py` | NEW | one-result outcome validation |
| `tests/test_confirmed_save_runtime.py` | NEW | dedicated lifecycle, backend, isolation, success/failure |
| `tests/test_session_runtime.py` | MODIFY | TurnRecord, persist-before-mutate, no operation serialization |
| `tests/test_cli.py` or existing CLI test file | NEW/MODIFY | command interception and explicit confirmation |
| `tests/test_remote_memory_client.py` | MODIFY | `supports_required_write=True`, caller request ID and wire consistency |
| `tests/test_local_client.py` | MODIFY | `supports_required_write=False` and request-ID parameter compatibility |
| test file covering NullMemoryClient | MODIFY | `supports_required_write=False` and request-ID parameter compatibility |
| `tests/test_memory_backend_activation.py` | MODIFY | production client capability values, remote-only guard and local sentinel |
| `tests/test_contracts.py` | MODIFY | protocol capability + signature/conformance |
| existing main/composition test file | MODIFY or NEW | SessionRuntime receives the application-owned user ID |
| `tests/test_memory_contract_fixtures.py` | VERIFY ONLY unless test assertion addition is required | wire fixture/schema unchanged |
| `tests/test_runtime_memory_wiring.py` | MODIFY/VERIFY | runtime/factory wiring remains protocol-capability-based and fail-closed |
| `tests/test_p4_local_demo.py` | MODIFY/VERIFY | local demo client/doubles conform to capability property without enabling required writes |

## 19.4 Conditional files

| Path | Allowed only when |
|---|---|
| `agent_core/confirmation/constants.py` | exact user-facing messages or safe goal are reused in 3+ production modules |
| existing CLI test filename | repository already has a canonical CLI test module |
| `agent_core/memory/factory.py` | VERIFY ONLY by default; modify only if the existing factory cannot return the selected clients without changing behavior, which requires architect review |

## 19.5 Forbidden files

```text
agent_core/planning/**
agent_core/skills/**
agent_core/tools/**
agent_core/memory/wire/**
tests/fixtures/memory_contract_v1/**
docs/ARCHITECTURE.md
docs/goal_product/PRODUCT_SPEC_MVP_USER_TRIAL.md
docs/standards/VERIFICATION_GATE.md
requirements/constraints/pyproject dependency declarations
TOMTIT-Memory repository files
```

Any need to touch a forbidden path is a stop condition requiring a spec revision.

---

# 20. Implementation order

Implementation must proceed in this order.

## M7A-I0 — Freeze

- commit this approved spec;
- record baseline, spec commit and SHA-256;
- create implementation branch from the exact accepted baseline.

## M7A-I1 — Pure domain contracts

Implement:

- errors;
- models;
- request-ID helper;
- evidence factory;
- policy;
- required-write checker.

Run only new pure unit tests.

## M7A-I2 — Memory-client capability, request-ID and identity correlation

Implement:

- protocol parameter;
- remote caller-ID precedence;
- exact candidate metadata-to-wire-ID mapping tests;
- request/project/user/session/result correlation;
- local/null compatibility;
- protocol-owned `supports_required_write` values;
- production factory capability verification;
- manual Local/Null RuntimeAgent fail-closed tests.

Run memory-client and contract tests.

## M7A-I3 — AgentState

Add the singular optional field and run constructor/contract regression tests.

## M7A-I4 — RuntimeAgent dedicated save

Implement remote-only, no-planner required-write lifecycle.

## M7A-I5 — SessionRuntime

Add the typed application method and reuse existing terminal-record persistence rules.

## M7A-I6 — CLI

Add the structured command and confirmation prompt.

## M7A-I7 — Full regression and scope audit

Run targeted suites, full suite, architecture greps and forbidden-path checks.

No later stage may weaken an earlier contract to make tests pass.

---

# 21. Required test catalogue

At minimum, the implementation must contain explicit tests for all items below.

## 21.1 Domain and evidence

1. valid `ConfirmedDecision`;
2. blank confirmation ID rejected;
3. blank content rejected;
4. frozen decision mutation rejected;
5. valid operation;
6. invalid request-ID formula rejected;
7. task/session validation;
8. operation frozen;
9. evidence factory returns `SourceType.USER`;
10. evidence factory returns `TrustLevel.TRUSTED_INSTRUCTION`;
11. exact source reference;
12. evidence content matches normalized decision content;
13. caller cannot provide raw trust/source/ref through factory.

## 21.2 Policy

14. exact candidate type is `DECISION`;
15. exactly one candidate produced;
16. candidate content exact;
17. candidate metadata carries confirmation candidate ID;
18. evidence reference exact;
19. operation/state task mismatch rejected;
20. session mismatch rejected;
21. user ID blank rejected;
22. wrong source type rejected;
23. wrong trust level rejected;
24. evidence content mismatch rejected;
25. evidence reference mismatch rejected;
26. policy performs zero client/store/tool calls.

## 21.3 Request ID and client

27. caller-provided request ID used unchanged;
28. request factory not called when ID provided;
29. fallback factory called once when ID absent;
30. local client accepts optional request ID;
31. null client accepts optional request ID;
32. protocol test doubles conform;
33. remote request/project/user/session mismatch rejected;
34. remote zero-result response rejected;
35. remote extra-result response rejected;
36. remote candidate mismatch rejected;
37. remote duplicate candidate result rejected;
38. unknown status rejected by wire validation;
39. wire fixture shape unchanged.

## 21.4 Required-write checker

40. one written result accepted;
41. one duplicate result accepted;
42. empty result rejected;
43. written and skipped together rejected;
44. multiple written rejected;
45. multiple skipped rejected;
46. skipped candidate mismatch rejected;
46. blank written memory ID rejected.

## 21.5 Runtime

48. missing operation fails before client;
49. local backend fails before client;
50. none backend fails before client;
51. local-store fail-on-access sentinel untouched;
52. planner not invoked;
53. ToolExecutor not invoked;
54. retrieval not invoked;
55. best-effort `_write_memory` not invoked;
56. written outcome completes with safe message;
57. duplicate outcome completes with duplicate message;
58. timeout fails with no saved claim;
59. network/5xx fails;
60. idempotency conflict fails;
61. malformed response fails;
62. inconsistent response fails;
63. unexpected exception logs and returns safe failure;
64. terminal state triggers zero second write;
65. request ID passed from operation unchanged;
66. task/session/user correlation passed correctly.

## 21.6 SessionRuntime and CLI

67. dedicated run creates a new AgentState;
68. fixed safe goal does not contain decision content;
69. operation not added to TurnRecord;
70. evidence not added to TurnRecord;
71. failed TurnRecord has `final_answer=None`;
72. successful TurnRecord has safe final answer;
73. planned actions empty;
74. persistent session uses persist-before-mutate;
75. persistence failure leaves live SessionState unchanged;
76. session resume creates zero additional write calls;
77. CLI command intercepted before `handle_turn`;
78. negative confirmation produces zero operation/write;
79. positive confirmation generates IDs in application layer;
80. ordinary natural-language message cannot trigger the path;
81. re-running CLI command produces a new confirmation/request ID.

## 21.7 Isolation and regression

82. zero M7 confirmation imports in planner;
83. zero M7 confirmation imports in skills;
84. zero M7 persistence imports in tools;
85. remote local-durable tools remain disabled;
86. `AgentState` existing constructor behavior remains compatible;
87. SessionState/TurnRecord serializers retain exact field sets;
88. Memory wire DTO field sets unchanged;
89. all pre-M7 tests pass.

## 21.8 Supplemental preflight corrections

90. `RuntimeAgent` has no `RemoteMemoryClient` import or concrete type check;
91. protocol capability is false for Local/Null and true for Remote;
92. every production factory returns a client with the expected capability without passing a separate runtime flag;
93. manually constructed `RuntimeAgent` + `LocalMemoryClient` fails before client/store access;
94. manually constructed `RuntimeAgent` + `NullMemoryClient` fails before client access;
95. M7-A candidate uses exact metadata key `"candidate_id"` and never falls back to an index ID;
96. response request ID mismatch is rejected;
97. response project ID mismatch is rejected;
98. response user ID mismatch is rejected;
99. response session ID mismatch is rejected;
100. `main.py` passes application-owned user ID into `SessionRuntime`;
101. confirmed save rejects missing/blank application user ID before client access;
102. FAILED in-memory state contains only the fixed safe message while persisted TurnRecord contains `final_answer=None`;
103. COMPLETED TurnRecord intentionally contains only deterministic output and safe provenance, not decision content or request ID;
104. logs and state diagnostics exclude decision content, evidence content, full payload and secrets;
105. same frozen operation produces byte-equivalent request identity/candidate payload under mock transport;
106. no M7-A test claims real TOMTIT-Memory stored-response replay;
107. inventory report custody SHA matches the value recorded in this specification.


---

# 22. Acceptance criteria

## AC-M7A-01 — Structured confirmation only

Only `/memory save-decision` or an equivalent typed application call may create a confirmed operation. Natural language, planner, skill and tool paths cannot.

## AC-M7A-02 — Exact domain contracts

`ConfirmedDecision` and `ConfirmedSaveOperation` are frozen and satisfy §6.

## AC-M7A-03 — Typed SF1 evidence

Confirmation uses the existing `EvidenceEnvelope`, `SourceType.USER` and `TrustLevel.TRUSTED_INSTRUCTION` with exact source-reference binding.

## AC-M7A-04 — State-first input

`AgentState.confirmed_save_operation` exists as a singular optional final field and is the runtime source of truth for the save operation.

## AC-M7A-05 — No persistence of operation

Session persistence and TurnRecord field sets remain unchanged; no operation/evidence payload is serialized or restored.

## AC-M7A-06 — Deterministic request ID

The request ID is exactly `memory-write:<confirmation_id>` and remains unchanged for the frozen operation.

## AC-M7A-07 — Caller-controlled client seam

All memory clients conform to the optional request-ID parameter; RemoteMemoryClient honors caller input and preserves factory fallback.

## AC-M7A-08 — Wire contract unchanged

Memory Contract v1 DTOs, endpoints and fixtures remain byte/field compatible.

## AC-M7A-09 — Wire consistency validation

RemoteMemoryClient validates request/project/user/session correlation and rejects zero, extra, duplicate and mismatched candidate results before returning domain success.

## AC-M7A-10 — One decision candidate

Policy maps one confirmed decision to exactly one `MemoryType.DECISION` candidate.

## AC-M7A-11 — Transport-neutral remote capability

`MemoryClientProtocol` owns the read-only required-write capability. `RemoteMemoryClient` reports `True`; Local/Null report `False`. RuntimeAgent checks the bound protocol capability and has no separate capability flag, import or type-check of `RemoteMemoryClient`. Production factories and manual Local/Null composition fail before client write and local-store access.

## AC-M7A-12 — Dedicated lifecycle

The confirmed-save run invokes no retrieval, planner, skill, Step, ToolExecutor or best-effort memory finalization.

## AC-M7A-13 — Required-write success

`written` and `skipped_duplicate` are the only COMPLETED outcomes.

## AC-M7A-14 — Required-write failure

Every transport, Memory error, schema, empty, extra, mismatch or consistency failure produces FAILED and no saved claim.

## AC-M7A-15 — Safe user output and failure masking

Success/duplicate messages are deterministic. Failure output contains no raw exception details. The in-memory failed state may carry only the fixed safe message, while FAILED TurnRecord persistence masks `final_answer` to `None`.

## AC-M7A-16 — TurnRecord data boundary

FAILED runs persist `final_answer=None`. Structured confirmation operation/evidence/content/request payload is not serialized. A COMPLETED deterministic final answer may intentionally persist the memory ID and safe provenance reference.

## AC-M7A-17 — Consume-once

A terminal state produces zero additional writes; resume produces zero writes.

## AC-M7A-18 — Replay-ready construction and duplicate handling separated

M7-A tests prove caller-controlled replay-stable request construction for the same frozen operation and distinct request identity for a new confirmation. They validate consumption of `skipped_duplicate` but do not claim real server replay or duplicate-record behavior; those are M7-B proofs.

## AC-M7A-19 — Split-brain preserved

Remote mode does not register or use local durable-memory tools.

## AC-M7A-20 — Scope discipline

Only §19 allowed paths change; forbidden paths remain untouched.

## AC-M7A-21 — Full regression

All baseline tests plus M7-A tests pass in Python 3.11.

## AC-M7A-22 — Candidate verification

Candidate is committed, worktree clean, `git diff --check` clean and all evidence is mapped under `VERIFICATION_GATE.md`.

---

# 23. Verification requirements

Before implementation, the implementation instruction must freeze:

```text
BASELINE_SHA
SPEC_COMMIT_SHA
SPEC_SHA256
IMPLEMENTATION_BRANCH
ALLOWED_PATH_MANIFEST
ACCEPTANCE_CRITERIA
REQUIRED_EVIDENCE
```

After implementation:

1. commit a candidate revision;
2. stop editing;
3. run a separate read-only verification pass;
4. classify every acceptance criterion as:

```text
PASS
FAIL
UNVERIFIED
WAIVED
```

5. `FAIL` or `UNVERIFIED` means `NO-GO`;
6. only human/architect may approve a waiver;
7. `GO` means eligible for approval, not permission to start M7-B.

Minimum evidence:

```text
git ancestry and exact diff
spec SHA custody
allowed/forbidden path check
git diff --check
import sanity
new targeted suites ×3
full regression
protocol signature probes
AgentState field fingerprint
SessionState/TurnRecord field fingerprints
wire DTO/fixture fingerprints
planner/skill/tool isolation greps
remote-only sentinel proof
replay-stable request-construction proof
duplicate-outcome handling proof
required-write failure matrix
working-tree cleanliness
```

---

# 24. Stop conditions

Implementation must stop and request architect review when any of these occurs:

1. current baseline differs from the approved implementation baseline;
2. exact spec SHA differs;
3. Memory Contract v1 cannot represent a required write;
4. caller-controlled request ID requires a wire change;
5. `RemoteMemoryClient` cannot preserve backward compatibility;
6. required-write gating would force RuntimeAgent to import or inspect a concrete memory adapter;
7. any production `MemoryClientProtocol` implementation lacks `supports_required_write`, or Local/Null reports `True`;
8. a separate runtime/composition capability flag is introduced and can disagree with the bound client;
9. written candidate correlation cannot be validated without changing wire DTOs;
10. SessionRuntime cannot reuse persist-before-mutate logic without changing TurnRecord schema;
11. M7-A requires planner, skill or tool changes;
12. M7-A requires local fallback;
13. M7-A requires a new Memory endpoint;
14. a forbidden path must change;
15. any existing test fails before implementation;
16. a production file outside §19 changes;
17. user confirmation would be inferable from free-form text;
18. raw exception text would be persisted or returned as a saved claim;
19. session resume could replay a write automatically;
20. implementation needs multi-decision support;
21. project ID would need to move into AgentState;
22. IDEMPOTENCY_CONFLICT is returned as a successful write status;
23. verification evidence conflates replay-stable request construction with real server replay;
24. application-owned `user_id` cannot be supplied explicitly to the save-run AgentState;
25. the M7-A candidate would log decision/evidence content or full request payloads.

---

# 25. Risks and trade-offs

## 25.1 AgentState contract growth

Risk: public state contract expands.

Mitigation: one singular additive default field, appended last, with constructor/fingerprint regression tests.

## 25.2 Memory protocol growth

Risk: every implementation/stub must update for both the capability property and optional request-ID keyword.

Mitigation: production capabilities are fixed and fail-closed; the request-ID parameter is optional and keyword-only, so existing call sites remain valid.

## 25.3 Stricter RemoteMemoryClient

Risk: previously tolerated malformed server responses now fail.

Mitigation: this is desired contract hardening; tests must show valid current fixtures remain accepted.

## 25.4 Runtime path duplication

Risk: normal run and confirmed-save run have separate control flows.

Mitigation: separate because their side-effect semantics differ; share only terminal/session-record helpers, not best-effort persistence.

## 25.5 CLI coupling

Risk: first application boundary is CLI-specific.

Mitigation: domain operation and SessionRuntime API remain UI-independent; future GUI/API can create the same frozen operation.

## 25.6 Application identity propagation

Risk: SessionRuntime currently has no application user identity.

Mitigation: add an optional constructor parameter, pass the same configured user ID from `main.py`, and require it for confirmed saves. Do not infer it from content or hidden adapter state.

## 25.7 Diagnostic data leakage

Risk: errors or logs could expose decision content or full payloads.

Mitigation: preserve typed causes while logging only IDs, category, latency and stack trace without request/response bodies.

## 25.8 Cross-repo idempotency details

Risk: exact TOMTIT-Memory HTTP status for idempotency conflict remains externally verified later.

Mitigation: Agent treats every non-success error envelope/4xx/5xx as FAILED; M7-B must confirm the real server behavior.

---

# 26. Deferred after M7-A

The following remain outside this specification:

- M7-B restart-and-recall;
- Memory service restart test;
- automatic extraction;
- opportunistic candidate generation;
- multiple decisions;
- generic confirmation UI;
- LLM planner;
- SF2 enforcement;
- retry/backoff controller;
- circuit breaker;
- real TOMTIT-Memory stored-response replay proof;
- MCP adapter;
- A2A;
- external skills;
- dependency lockfile;
- README test-count cleanup.

---

# 27. Definition of done

M7-A is complete only when:

1. all AC-M7A-01 through AC-M7A-22 are PASS;
2. the inventory evidence custody requirement in §0 is satisfied;
3. M7-A evidence distinguishes replay-stable construction from M7-B server replay;
4. no required criterion is UNVERIFIED;
5. the candidate passes separate read-only verification;
6. human/architect approves the candidate;
7. the candidate is merged and pushed;
8. `main == origin/main`;
9. the canonical product/architecture/SF1/gate documents remain unchanged;
10. M7-B has not started automatically.

Allowed claim after M7-A:

> TOMTIT-Agent can write one explicitly user-confirmed project decision to TOMTIT-Memory with typed provenance, deterministic request identity and fail-loud required-write semantics.

Not yet allowed:

> TOMTIT-Agent remembers the decision across Agent and Memory process restarts.

That claim requires M7-B.

---

# 28. Review status

Current document state:

```text
SPEC v1.2-draft WRITTEN
CAPABILITY-DRIFT PATCH APPLIED
IMPLEMENTATION NOT AUTHORIZED
```

Next required workflow:

```text
spec review
→ correction patch if needed
→ approved spec freeze
→ implementation instruction
→ implementation candidate
→ separate verification
→ human merge authorization
```

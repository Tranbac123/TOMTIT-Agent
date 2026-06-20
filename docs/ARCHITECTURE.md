# TOMTIT-Agent Architecture

**Version:** 1.0<br>
**Status:** AUTHORITATIVE ARCHITECTURE<br>
**Scope:** TOMTIT-Agent runtime, session continuity, tool/skill systems, TOMTIT-Memory integration, and accepted M7 target<br>
**Architecture style:** state-first, local-first, contract-first, capability-aware, production-upgradable<br>
**Normative process:** `docs/standards/VERIFICATION_GATE.md`

> This document separates:
>
> - **IMPLEMENTED** — present in the current TOMTIT-Agent mainline architecture;
> - **ACCEPTED TARGET** — approved architectural direction but not yet authoritative implementation;
> - **DEFERRED** — intentionally outside the current milestone.

---

# 1. Product Direction

TOMTIT is not being built as a generic autonomous employee.

The current product wedge is:

> **TOMTIT helps developers preserve and recall confirmed project decisions across sessions and process restarts.**

The near-term product capability target is intentionally narrow:

> After M7 is completed and verified, TOMTIT-Agent will be able to save an explicitly confirmed project decision through TOMTIT-Memory and recall it later with provenance.

This capability has not yet been demonstrated end-to-end.

Current main already provides the M6 remote-memory transport, activation boundary, and retrieval path. The explicit confirmed-write producer and cross-process restart-and-recall proof belong to M7.

The project must not claim that TOMTIT:

- automatically knows what should be remembered;
- autonomously manages project memory;
- is already integrated into Claude Code, Cursor, or Codex;
- is a production-ready general coding agent;
- safely runs an LLM planner before SF2 is complete.

---

# 2. Architecture Status

## 2.1 Implemented

```text
SR1  Interactive multi-turn session
SR2  SessionState + TurnRecord
SR3  Durable local session persistence
EX1  Immutable ToolRegistry + strict tool schemas
EX2  Capability-aware static SkillCatalog
M6   RemoteMemoryClient + backend activation + split-brain guard
```

Current runtime characteristics:

- one new `AgentState` per run/turn;
- one `SessionState` for session continuity;
- rule-based planning;
- validated `Step` execution through `ToolExecutor`;
- local, remote, or null memory backend;
- memory retrieval before planning;
- no production automatic memory extraction;
- no production LLM planner.

## 2.2 In progress

SF1 is CLOSED and merged (`aa505dcc...`). The current active next phase is M7-A inventory.

```text
M7-A  Explicit confirmed-decision write inventory and spec
```

## 2.3 Accepted next target

M7 is the accepted next product-capability target:

```text
M7-A  Explicit confirmed-decision write
M7-B  Cross-process restart-and-recall
```

Dependency:

```text
SF1: CLOSED — dependency satisfied (aa505dcc...)
```

M7 uses the merged SF1 trust/source/provenance contracts for typed confirmation evidence. Resolved paths:

```text
TrustLevel, SourceType   →  agent_core.state.enums
EvidenceEnvelope         →  agent_core.safety.evidence
tool_observation_ref     →  agent_core.safety.evidence
```

## 2.4 Deferred until product evidence

```text
SF2 trust enforcement
LLM goal interpreter
LLM planner
replanning loop
real web fetch
workspace tools
automatic memory extraction
MCP/A2A
external skill loading
multi-agent execution
self-improvement/RL
```

---

# 3. Three Truth Boundaries

TOMTIT has three different sources of truth.

## 3.1 AgentState

`AgentState` is the source of truth for one task/run.

It owns:

```text
goal and task identity
runtime status
plan and current step
last result and slots
observations and sources
context pack
memory degraded/write-failure state
disclosure reasons
runtime safety flags
```

It does not own durable session history or durable semantic project memory.

## 3.2 SessionState

`SessionState` is the source of truth for continuity inside one session.

It owns:

```text
session_id
created_at
updated_at
ordered TurnRecord history
```

Each turn creates a new `AgentState`.

`SessionState` does not replace TOMTIT-Memory.

## 3.3 TOMTIT-Memory

TOMTIT-Memory is the source of truth for durable semantic memory across sessions.

It owns records such as:

```text
decision
rule
fact
preference
lesson
note
project_context
```

TOMTIT-Agent must not read TOMTIT-Memory SQLite files directly.

## 3.4 Boundary invariant

```text
AgentState
= what is true in this run

SessionState
= what happened across turns in this session

TOMTIT-Memory
= durable semantic project memory across sessions
```

These boundaries must not be collapsed.

---

# 4. High-Level Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│ User / CLI / Application Boundary                            │
│ - free-text turn                                             │
│ - session commands                                           │
│ - future structured confirmed-decision command               │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ SessionRuntime                                               │
│ - owns SessionState                                          │
│ - creates one AgentState per turn                            │
│ - runs RuntimeAgent                                          │
│ - converts terminal state to TurnRecord                      │
│ - persists candidate SessionState before mutating live state │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ RuntimeAgent                                                 │
│ 1. retrieve memory                                           │
│ 2. plan                                                      │
│ 3. validate plan                                             │
│ 4. execute steps                                             │
│ 5. compose answer                                            │
│ 6. memory finalization                                       │
│ 7. disclosure                                                │
│ 8. complete/fail                                             │
└──────────────┬───────────────────────┬───────────────────────┘
               │                       │
               ▼                       ▼
┌──────────────────────────┐  ┌───────────────────────────────┐
│ Planning                 │  │ MemoryClientProtocol          │
│ - RuleBasedPlanner       │  │ - LocalMemoryClient           │
│ - intent parser/planner  │  │ - RemoteMemoryClient          │
│ - SkillAware planner     │  │ - NullMemoryClient            │
│ - PlanValidator          │  └───────────────┬───────────────┘
└──────────────┬───────────┘                  │
               │                              ▼
               ▼                    ┌──────────────────────────┐
┌──────────────────────────┐        │ TOMTIT-Memory            │
│ ToolExecutor             │        │ HTTP/JSON Memory v1      │
│ - ArgResolver            │        │ SQLite persistence       │
│ - strict schema          │        │ retrieval + token packing│
│ - PolicyEngine           │        │ duplicate/idempotency    │
│ - ApprovalGate           │        └──────────────────────────┘
│ - tool.fn                │
│ - Observation            │
└──────────────────────────┘
```

> **Cross-repo note:** TOMTIT-Memory server internals shown above (SQLite persistence, duplicate/idempotency store, token packing) are external architectural context. They are not verifiable from the TOMTIT-Agent repository. Consult the TOMTIT-Memory repository for authoritative implementation facts.

---

# 5. Runtime Lifecycle

## 5.1 Current run flow

```text
AgentState created
→ retrieve ContextPack
→ planner.make_plan(state)
→ validate_plan(plan, resolved_tools)
→ execute each Step through ToolExecutor
→ compose draft
→ current best-effort memory finalization
→ apply disclosure reasons
→ RuntimeAgent completes the run
```

Important current facts:

- memory retrieval happens before planning;
- `RuntimeAgent` is the completion authority;
- `FINISH` does not directly complete `AgentState`;
- `ToolExecutor` records execution observations;
- automatic candidate extraction is disabled;
- current `_collect_candidates()` returns an empty list.

## 5.2 Completion authority

Only the runtime/lifecycle completes a run.

```text
FINISH tool
→ indicates execution should stop
→ does not call AgentState.complete()

RuntimeAgent finalization
→ composes answer
→ applies memory/disclosure behavior
→ calls AgentState.complete()
```

This prevents a tool from bypassing runtime finalization.

## 5.3 Failure

A failed `AgentState` may retain internal error text for runtime/debugging.

Session persistence must not store raw failed output as a successful answer:

```text
failed run
→ TurnRecord.status = FAILED
→ TurnRecord.final_answer = None
```

Safe user-facing failure messages belong at the application/runtime boundary.

---

# 6. AgentState Contract

The current `AgentState` contains these categories.

## 6.1 Identity

```text
goal
task_id
user_id
session_id
```

## 6.2 Runtime

```text
status
plan
current_step
done
final_answer
max_steps
```

## 6.3 Working result

```text
last_result
slots
history
observations
sources
errors
```

## 6.4 Memory integration

```text
context_pack
memory_degraded
memory_write_failed
disclosure_reasons
context_consumed
```

## 6.5 Safety

```text
approved_tools
read_only
```

## 6.6 Legacy local store field

`AgentState.memory` still exists for backward-compatible local built-in memory tools.

Rules:

```text
- do not add new architecture that depends on AgentState.memory;
- local composition must share the same store reference;
- remote/none modes disable local durable-memory tools;
- future architecture should converge on MemoryClientProtocol.
```

## 6.7 M7 target field

M7 may add a typed run-only confirmed input.

Conceptually:

```text
confirmed_decisions
```

This is an **ACCEPTED TARGET**, not current-main behavior.

It must not be hidden inside `slots`.

---

# 7. Session Runtime and Durable Session Persistence

## 7.1 SessionRuntime responsibilities

`SessionRuntime`:

- owns or receives `SessionState`;
- creates one `AgentState` per user turn;
- preserves `session_id`;
- invokes `RuntimeAgent`;
- creates immutable `TurnRecord`;
- persists session state;
- provides status/history views.

## 7.2 SR3 persistence invariant

The session persistence order is:

```text
terminal AgentState
→ build TurnRecord
→ build candidate serialized session
→ atomic durable save
→ mutate live SessionState
→ return
```

If save fails:

```text
live SessionState is not mutated
typed persistence error is raised
no automatic retry
```

This prevents RAM from claiming a turn that disk did not persist.

## 7.3 Session order

JSON array order is authoritative.

`completed_at` is display/provenance time and must not be used to reorder turns.

## 7.4 Session scope

Session persistence stores:

```text
TurnRecord history
```

It does not store:

```text
full AgentState
ContextPack
TOMTIT-Memory records
confirmed save operations
```

---

# 8. Planning Architecture

## 8.1 Current planner

The current production planner is deterministic and rule-based.

Main composition:

```text
RuleBasedPlanner
→ intent parser
→ SkillAwareIntentPlanner
→ fallback intent planner
→ list[Step]
```

No production LLM planner is active.

## 8.2 Planner responsibility

Planner components may:

- parse intent;
- extract structured inputs;
- select an active skill;
- create `Step` objects;
- return clarification/fallback steps.

They may not:

- call `tool.fn`;
- execute tools;
- write memory directly;
- create user confirmation authority;
- bypass `PlanValidator`;
- mutate TOMTIT-Memory.

## 8.3 PlanValidator

The validator checks the generated plan against the exact resolved `ToolRegistry`.

At minimum:

```text
registered action
required structural fields
tool availability
valid step sequence assumptions
```

Tool argument schema validation remains an executor responsibility after runtime reference resolution.

---

# 9. Tool System — EX1

## 9.1 ToolRegistry

`ToolRegistry` is an immutable `Mapping[ToolName, ToolSpec]`.

Properties:

- duplicate tool names fail loudly;
- registry contents cannot be mutated after construction;
- runtime and planner receive the same resolved registry;
- manifest output does not expose callables;
- disabled tools are removed before runtime composition.

## 9.2 ToolSpec

`ToolSpec` is the control contract for a tool.

It contains metadata such as:

```text
name
fn
description
required_args
allowed_args
args_schema
mutates_state
risk_level
side_effects
requires_approval
idempotent
timeout_seconds
retry_policy
```

Current rules:

- every built-in tool has a strict Pydantic input schema;
- unknown fields are rejected;
- schema validation occurs after placeholder resolution;
- schema validation occurs before policy and approval;
- unsupported timeout/retry behavior must not be advertised as active enforcement.

## 9.3 Declared ToolName enum

The following values are the complete declared `ToolName` vocabulary:

```text
calculate
write_note
read_note
list_notes
save_fact
save_preference
save_decision
search_memory
summarize_memory
summarize
web_search
finish
answer_from_context
```

This enum is not the tool set available in every runtime composition.

The resolved `ToolRegistry` is capability-dependent:

- local mode may include all built-in tools;
- remote mode excludes local durable-memory tools;
- none mode excludes durable-memory tools;
- a custom composition may provide another validated subset.

Planner, `SkillCatalog`, `PlanValidator`, and `RuntimeAgent` must use the same resolved `ToolRegistry` for the current composition.

## 9.4 Tool capability partitioning

`ToolName` defines the complete action vocabulary.

`ToolRegistry` defines the actions actually available in one runtime composition.

A `ToolName` may therefore be declared but absent from the resolved registry. Plans containing an unavailable tool must be rejected by validation or converted into an explicit unavailable-capability result before execution.

Backend filtering occurs before planner/runtime construction.

Current backend behavior:

```text
local
→ local durable-memory tools may remain available

remote
→ LOCAL_DURABLE_TOOLS are removed
→ answer_from_context remains available when present in the resolved registry

none
→ durable-memory tools are removed
```

The split-brain activation guard must reject remote/null memory composition if local durable-memory tools remain active.

## 9.5 Tool execution boundary

```text
Step
→ ToolRegistry lookup
→ ArgResolver
→ structural argument checks
→ strict args_schema validation
→ PolicyEngine
→ ApprovalGate
→ tool.fn
→ ToolResult validation
→ Observation
```

There must be one production `tool.fn` call site: `ToolExecutor`.

## 9.6 ToolResult

Current normalized result contract:

```text
success
output
error
tool_name
kind
sources
metadata
```

Do not replace it with old `ok/value` examples.

---

# 10. Skill System — EX2

## 10.1 Skill definition

A skill is a stateless plan factory.

```text
structured inputs
→ list[Step]
```

A skill does not receive:

```text
ToolExecutor
tool callable
MemoryClient
AgentState mutation authority
```

A skill must not execute tools.

## 10.2 SkillRegistry

`SkillRegistry` is an immutable mapping of active skills.

It validates:

- duplicate skill names;
- duplicate intent ownership;
- required tool availability.

## 10.3 SkillCatalog

`SkillCatalog` partitions every built-in skill definition into:

```text
active
disabled + exact missing tools
```

No incompatible skill silently disappears.

## 10.4 Current built-in skills

```text
calculate_and_save
read_and_summarize
web_search
```

## 10.5 Backend capability behavior

In local mode, local-memory skills may be active.

In remote mode, local durable-memory tools are removed, therefore skills requiring them are explicitly disabled.

This is expected capability partitioning, not an error.

---

# 11. Memory Architecture — M6

## 11.1 Boundary

All new durable semantic-memory access must go through:

```text
MemoryClientProtocol
```

Agent code must not import TOMTIT-Memory storage internals.

## 11.2 Protocol responsibilities

The protocol exposes two core operations:

```text
retrieve_context_pack(...)
write_memory_candidates(...)
```

It receives explicit identifiers and DTOs, not a full `AgentState`.

## 11.3 Implementations

```text
LocalMemoryClient
RemoteMemoryClient
NullMemoryClient
```

## 11.4 Backend modes

```text
local
remote
none
```

### Local

- uses shared `InMemoryStore`;
- keeps local durable-memory tools available;
- intended for local compatibility and tests.

### Remote

- uses `RemoteMemoryClient`;
- requires remote configuration;
- disables local durable-memory tools;
- does not silently fallback to local persistence.

### None

- uses null memory behavior;
- disables durable-memory tools.

## 11.5 Split-brain guard

Composition must validate:

```text
RemoteMemoryClient + local durable-memory tools
→ configuration error

NullMemoryClient + durable-memory tools
→ configuration error
```

The backend is fixed for a run.

## 11.6 Project and user scope

Memory records are scoped by:

```text
project_id + user_id
```

Ownership:

```text
project_id
→ RemoteMemoryClient/composition configuration

user_id
→ Agent/run identity
```

Do not add `project_id` to `AgentState` only for transport.

`session_id` is correlation, not storage identity.

---

# 12. Remote Memory Contract v1

## 12.1 Agent → Memory route boundary

Current remote routes:

```text
POST /v1/context/retrieve
POST /v1/memories/write
GET  /v1/memories/{memory_id}
GET  /v1/health/live
GET  /v1/health/ready
```

Do not create alternate aliases without a new accepted contract.

## 12.2 Retrieval

Remote retrieval returns an Agent-side `ContextPack`.

Authoritative retrieval order and packing belong to TOMTIT-Memory Contract v1.

The Agent consumes the returned pack without knowing whether Memory used:

```text
FTS5
BM25
token packing
future hybrid retrieval
```

## 12.3 Retrieval failure

Expected behavior:

```text
operational timeout/transport/server failure
→ RemoteMemoryClient returns degraded ContextPack

contract/schema/configuration failure
→ typed error / run failure before planning
```

Remote degradation must never activate local durable-memory fallback.

## 12.4 Current write state

The transport and API write path exist.

Current production runtime does not automatically create candidates:

```text
_collect_candidates()
→ []
```

This is intentional.

Automatic memory extraction remains out of scope.

---

# 13. ContextPack and Memory-Informed Answering

## 13.1 Retrieval flow

```text
RuntimeAgent
→ MemoryClientProtocol.retrieve_context_pack()
→ state.context_pack
→ planning
→ answer_from_context tool when selected
→ ToolResult
→ FinalComposer
```

## 13.2 Context consumption

`answer_from_context` is the explicit current capability that consumes `state.context_pack`.

The Agent must not claim it used project memory when context was not actually consumed.

## 13.3 Provenance

Memory-informed answers should preserve:

```text
memory identity
source/task evidence
record type
timestamps where available
```

SF1 is CLOSED. Trust/provenance fields are current-main authoritative: `TrustLevel` and `SourceType` in `agent_core/state/enums.py`; `source_ref` format (`task:<id>/step:<id>/tool:<name>`) in `agent_core/safety/evidence.py`; field positions in `agent_core/state/observation.py:16–18`.

---

# 14. Safety Boundaries

## 14.1 Current execution safety

Current tool safety consists of:

```text
ToolSpec risk metadata
strict arguments
PolicyEngine
ApprovalGate
single ToolExecutor call gate
```

Approval is currently tool-name scoped, not argument-bound.

Do not overstate it as production-grade authorization.

## 14.2 SF1 — implemented trust/evidence contracts

SF1 (CLOSED) implemented contracts for:

```text
trust level
source type
source reference
immutable evidence envelope
memory context provenance
tool observation provenance
```

Core principle:

```text
memory/tool/web/workspace content
= untrusted evidence
```

Evidence may inform a result but must not grant permission.

SF1 is merged. These are current-main facts in `agent_core/safety/evidence.py` and `agent_core/state/enums.py`.

## 14.3 SF2 — deferred enforcement

SF2 will enforce:

- instruction/evidence separation;
- prompt assembly boundaries;
- fail-closed handling of unknown trust;
- adversarial injection tests;
- per-LLM-component activation gates.

SF2 is required before activating an LLM planner or replanner.

SF2 is not required for deterministic M7 confirmed-save flow.

---

# 15. Observations and Trace

## 15.1 Current Observation purpose

Every tool execution path should record an observation containing current execution facts such as:

```text
step index
action
arguments
success
output/error
sources
```

Observations currently carry explicit trust/source/reference fields (SF1, CLOSED):

```text
trust_level: TrustLevel   — UNTRUSTED_EVIDENCE for all tool execution paths (P1–P9)
source_type: SourceType   — TOOL for all tool execution paths (P1–P9)
source_ref:  str | None   — format: task:<task_id>/step:<step_id>/tool:<canonical_name>
```

These fields are at positions 5–7 in `agent_core/state/observation.py:16–18`. `AgentState` is unchanged by SF1.

## 15.2 Trace use

Observations support:

- debugging;
- test assertions;
- provenance;
- future replay/evaluation;
- future learning datasets.

They are not automatically durable semantic memory.

## 15.3 Self-improvement

Automatic reflection and lesson extraction are deferred.

Future flow may be:

```text
trace
→ offline evaluator
→ reviewed lesson candidate
→ explicit policy
→ memory
```

Do not allow traces to write memory automatically in the current MVP.

---

# 16. M7 Target — Confirmed Decision Write-and-Recall

M7 is an accepted target, not an implemented current-main capability.

It must be specified separately before implementation and cannot begin until SF1 is formally CLOSED.

## 16.1 M7 scope

```text
FULL AGENT WRITE-AND-RECALL
```

Write source:

```text
explicit user-confirmed decision only
```

Not allowed:

```text
LLM extraction
planner-generated confirmation
automatic memory mining
local save_decision fallback in remote mode
```

## 16.2 Dedicated save run

M7 must not combine an arbitrary task and a required save in one run.

Use a dedicated application command:

```text
Confirm and persist this project decision.
```

Outcomes:

```text
written
→ run success

skipped_duplicate
→ run success with duplicate disclosure

write/contract/inconsistent-response failure
→ run failed
→ no “saved” claim
```

## 16.3 Domain input

Conceptual target:

```python
@dataclass(frozen=True)
class ConfirmedDecision:
    confirmation_id: str
    content: str
    confirmation_evidence: EvidenceEnvelope  # agent_core.safety.evidence.EvidenceEnvelope
```

SF1 is CLOSED. `EvidenceEnvelope` is at `agent_core.safety.evidence`; `TrustLevel` and `SourceType` are at `agent_core.state.enums`. Resolve exact constructor and field contracts from merged implementation before M7-A spec.

`confirmation_id` must be:

- nonblank;
- application-owned;
- stable within one operation;
- unique for a new confirmation within `project_id + user_id`;
- never reused with a different payload.

## 16.4 Frozen save operation

Conceptual target:

```python
@dataclass(frozen=True)
class ConfirmedSaveOperation:
    request_id: str
    task_id: str
    session_correlation: MemoryContractV1SessionCorrelation
    decision: ConfirmedDecision
```

Invariants:

- application creates it once;
- planner/model cannot create or mutate it;
- retry in the same operation reuses the complete envelope;
- it is not persisted in `SessionState`;
- it is not persisted in `TurnRecord`;
- it is not resumed after process restart;
- one operation contains one decision.

## 16.5 Confirmation policy

A narrow `ConfirmedMemoryWritePolicy` may:

- validate confirmation identity;
- validate nonblank content;
- validate typed SF1 evidence;
- require `task_id` and `user_id`;
- map one decision to one `MemoryCandidate(type=decision)`.

It must not:

- call HTTP/store;
- manage tools;
- accept planner/model output as confirmation;
- own project configuration.

## 16.6 Agent → Memory mapping

M7 writes exactly one semantic memory type:

```text
MemoryType.DECISION
```

M7 does not create:

```text
fact
preference
rule
lesson
note
project_context
task_summary
source
```

Support for other memory types remains outside the M7 confirmed-save contract.

| Agent domain | Memory Contract v1 |
|---|---|
| confirmation ID | candidate ID |
| content | content |
| fixed decision type | `decision` |
| typed confirmation evidence | rendered `evidence_ref` |
| save-run task | `task_id` |
| session correlation | `session_id` |
| frozen operation identity | `request_id` |
| client configuration | `project_id`, `user_id` |

TOMTIT-Memory:

- does not receive `AgentState`;
- does not receive SF1 domain objects;
- does not verify user confirmation;
- does not know planner, SessionRuntime, or ToolExecutor;
- validates contract, duplicate, idempotency, and persistence.

> **Cross-repo note:** TOMTIT-Memory idempotency, duplicate handling, and persistence behaviors listed here are Memory-service design intent, not facts verifiable from this repository.

## 16.7 Replay versus duplicate

### Request replay

Same frozen operation:

```text
same request_id
same task_id
same session_id
same candidate order
same candidate payload
→ replay stored response
```

### Exact duplicate

New operation:

```text
new confirmation_id
new request_id
same normalized decision content
→ skipped_duplicate
→ no second record
```

### Process restart

Because the operation is not persisted:

```text
old operation is not replayed after restart
user creates a new confirmation
duplicate detection prevents a second record
```

## 16.8 M7-B cross-process proof

M7 is complete only when:

```text
Agent A confirms and writes decision
→ Agent A stops
→ Agent B starts with new state/client/session
→ Agent B retrieves and answers with provenance
→ TOMTIT-Memory stops
→ new Memory process opens same SQLite file
→ Agent C retrieves and answers correctly
```

Retrieve-only seeding is allowed only as a diagnostic subtest.

---

# 17. Failure and Disclosure Semantics

## 17.1 Retrieval

```text
operational failure
→ degraded context
→ explicit disclosure when memory matters
→ no local fallback

contract/configuration failure
→ fail clearly
```

## 17.2 Current opportunistic write

Current runtime memory finalization is best-effort, but production candidate collection is empty.

This path must not be used to claim explicit confirmed persistence.

## 17.3 M7 required write

Explicit confirmed save uses required semantics:

```text
written
→ success

valid skipped_duplicate
→ success

timeout/network/5xx
contract error
empty response
extra/missing result
mismatched candidate
unknown status
→ failure
→ no saved claim
```

## 17.4 Session failure record

For a failed dedicated save run:

```text
TurnRecord.status = FAILED
TurnRecord.final_answer = None
```

A safe typed failure message may be shown by the application boundary.

---

# 18. Current Module Map

This is a conceptual map, not an exhaustive tree.

```text
agent_core/
├── memory/
│   ├── base.py
│   ├── client.py
│   ├── contracts.py
│   ├── factory.py
│   ├── local_client.py
│   ├── remote_client.py
│   ├── null_client.py
│   ├── in_memory_store.py
│   └── wire/
├── output/
│   └── final_composer.py
├── planning/
│   ├── base.py
│   ├── intents.py
│   ├── intent_parser.py
│   ├── intent_planner.py
│   ├── skill_aware_intent_planner.py
│   ├── plan_validator.py
│   ├── rule_based_planner.py
│   └── hybrid_planner.py
├── runtime/
│   ├── lifecycle.py
│   ├── runtime_agent.py
│   └── session_runtime.py
├── safety/
│   ├── __init__.py
│   ├── evidence.py
│   ├── policy.py
│   └── approval.py
├── session_persistence/
│   ├── base.py
│   ├── serializer.py
│   ├── file_store.py
│   └── errors.py
├── skills/
│   ├── base.py
│   ├── registry.py
│   ├── calculate_and_save_skill.py
│   ├── read_and_summarize_skill.py
│   └── web_search_skill.py
├── state/
│   ├── agent_state.py
│   ├── session_state.py
│   ├── observation.py
│   └── enums.py
└── tools/
    ├── arg_resolver.py
    ├── base.py
    ├── builtin_tools.py
    ├── executor.py
    ├── input_schemas.py
    ├── registry.py
    └── schemas.py
```


---

# 19. Verification and Change Control

All architecture implementation work follows:

```text
inventory
→ accepted spec
→ implementation branch
→ tests
→ committed candidate
→ candidate freeze
→ separate read-only verification
→ criterion-by-criterion report
→ human/architect approval
→ merge
```

## 19.1 Verification status values

```text
PASS
FAIL
UNVERIFIED
WAIVED
```

`FAIL` or `UNVERIFIED` means `NO-GO`.

Only a human/architect may approve a waiver.

## 19.2 GO semantics

`GO` means:

```text
candidate is eligible for human/architect review
```

It does not authorize:

- merge;
- push;
- next phase;
- silent scope expansion.

## 19.3 Normative source priority

For implementation decisions:

```text
accepted phase spec
→ verification standard
→ frozen evidence
→ current code
→ architecture guide
```

`ARCHITECTURE.md` explains system boundaries; it does not override an accepted phase specification.

---

# 20. Current Roadmap

## 20.1 Completed

```text
SR1
SR2
SR3
EX1
EX2
M6
SF1
```

## 20.2 Immediate work

```text
→ inventory M7-A
→ spec M7-A
→ confirmed decision write
→ spec/implement M7-B
→ restart-and-recall E2E
→ minimal packaging
→ dogfood
→ 3–5 design partners
```

## 20.3 After product evidence

```text
SF2
→ Goal Interpreter
→ Guarded LLM Planner
→ Execution/Replanning
→ Real Web/Workspace
→ Expanded Skill Bundle
→ Full Memory UX
```

---

# 21. Deferred Architecture

Do not build before M7/pilot evidence:

- autonomous memory extraction;
- vector database migration;
- graph memory;
- conflict-resolution engine;
- external plugin marketplace;
- MCP server;
- A2A;
- multi-agent runtime;
- shell/code modification;
- SaaS control plane;
- billing;
- Kubernetes;
- RL/self-training.

## 21.1 MCP criterion

Consider MCP only when:

1. M7 proves HTTP Memory Contract v1 end-to-end;
2. the protocol is stable;
3. users want Claude Code/Codex/Cursor to access TOMTIT-Memory directly.

Future MCP must be an adapter over the existing contract, not a second schema or persistence path.

## 21.2 A2A criterion

Consider A2A only when multiple independent agents have separate:

```text
AgentState
planner
tool lifecycle
task lifecycle
```

Current TOMTIT does not need A2A.

---

# 22. Mental Model

```text
Application
= owns user interaction and explicit confirmation

SessionRuntime
= owns session continuity and durable TurnRecord history

AgentState
= owns truth for one run

Planner
= proposes structured steps

Skill
= stateless plan factory

PlanValidator
= validates the plan against available capabilities

ToolRegistry
= immutable tool capability catalog

ToolExecutor
= the only production tool invocation gate

PolicyEngine / ApprovalGate
= decide whether a tool action is allowed

MemoryClientProtocol
= the only new semantic-memory boundary

TOMTIT-Memory
= durable semantic memory and retrieval service

FinalComposer
= produces user-facing output from actual state

Observation
= records what actually happened

Verification Gate
= prevents unverified candidates from becoming architecture
```

The central architecture is:

```text
state first
contracts before integrations
capabilities resolved before planning
all tool calls through one gate
memory through one client boundary
session history separate from semantic memory
explicit confirmation before durable write
verification before phase transition
```

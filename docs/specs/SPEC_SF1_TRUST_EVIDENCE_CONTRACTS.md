# SPEC_SF1_TRUST_EVIDENCE_CONTRACTS.md

> **Version:** 1.3  
> **Status:** APPROVED FOR IMPLEMENTATION  
> **Phase:** SF1 — Trust & Evidence Contracts  
> **Repository:** TOMTIT-Agent  
> **Authoritative baseline:** `main@c50f80feb65917d64135f9bf1517006a42ef342d`  
> **Verified regression baseline:** `404 passed`  
> **Preflight status:** CLOSED — `PF-01` through `PF-16` PASS  
> **Preflight report:** `REPORT_SF1_PREFLIGHT_CLOSURE_VERIFIED.md`  
> **Verification policy:** `docs/standards/VERIFICATION_GATE.md` v1.0.0  
> **Depends on:** EX2 v1.2 CLOSED; M6 memory backend composition present  
> **Primary outcome:** make source, trust, and provenance explicit at memory and tool-observation boundaries without enabling an LLM or changing runtime policy behavior.

## Revision note

Version 1.3 closes the read-only preflight and replaces all unresolved assumptions from earlier drafts with repository-verified facts:

- freezes the exact nine ToolExecutor observation-producing paths;
- confirms `ToolExecutor._record_result()` is the only production `Observation` constructor;
- freezes exact production and test file scope;
- freezes baseline public-contract and wire-contract snapshots;
- resolves `Step.id`, `AgentState.task_id`, Pydantic strict defaults, and memory-ID normalization;
- replaces all unresolved test-path placeholders with exact repository paths;
- authorizes implementation only within this specification and `VERIFICATION_GATE.md`.

---

# 0. Normative authority and execution rule

The normative sources, in priority order, are:

1. this specification, version 1.3;
2. `docs/standards/VERIFICATION_GATE.md`;
3. the frozen baseline facts and artifacts in `REPORT_SF1_PREFLIGHT_CLOSURE_VERIFIED.md`;
4. current code at baseline SHA `c50f80f`.

If implementation reveals a contradiction requiring a scope, contract, acceptance-criteria, or behavior change:

```text
STOP
→ report exact evidence
→ do not patch the spec
→ do not widen scope
→ wait for architect authorization
```

`APPROVED FOR IMPLEMENTATION` authorizes implementation of SF1 only. It does not authorize merge, push, SF2, or any LLM activation.

---

# 1. Executive decision

SF1 introduces additive trust and provenance contracts.

It answers:

```text
What is this content?
Where did it come from?
What trust level does it carry?
What stable source reference can be traced?
```

SF1 does not answer:

```text
May this content influence action selection?
May it enter a privileged prompt role?
Should it be rejected as prompt injection?
Does it grant approval or permission?
```

Those enforcement questions belong to SF2.

Target architecture:

```text
memory/tool adapter
→ explicit source + trust + provenance
→ Agent runtime structures
→ existing rule-based planner and runtime
```

Web and workspace source types are reserved in SF1, but real web-document and workspace adapters are out of scope.

---

# 2. Verified baseline facts

## 2.1 SourceType

`agent_core/state/enums.py` contains one `SourceType` enum with baseline values:

```text
web
memory
tool
user
agent
system
```

SF1 extends this enum. It must not introduce a second source enum.

## 2.2 ContextItem boundary

`agent_core/memory/contracts.py::ContextItem` is an Agent-side Pydantic model with `strict=True`.

Baseline fields:

```text
content
type
score
tokens
source
provenance
confidence
freshness
metadata
```

Agent-side `ContextItem` and wire `ContextItemV1` are separate models. Production HTTP serialization uses wire request models, not `ContextItem.model_dump()`.

## 2.3 Memory adapters

The only production Agent-side `ContextItem` construction sites are:

```text
agent_core/memory/local_client.py::LocalMemoryClient._to_item
agent_core/memory/remote_client.py::RemoteMemoryClient._to_context_item
```

`MemoryRecord.id` has a UUID default but no non-blank validator.  
`ContextItemV1.memory_id` is stripped and rejected when blank by wire validation.

## 2.4 ToolResult

`agent_core/tools/schemas.py::ToolResult` is a mutable dataclass.

Baseline field tuple:

```python
(
    "success",
    "output",
    "error",
    "tool_name",
    "kind",
    "sources",
    "metadata",
)
```

SF1 does not change this contract.

## 2.5 Observation

`agent_core/state/observation.py::Observation` is a mutable dataclass.

Baseline field tuple:

```python
(
    "step_index",
    "action",
    "args",
    "success",
    "output",
    "error",
    "sources",
)
```

`agent_core/tools/executor.py::ToolExecutor._record_result()` is the only production `Observation(...)` constructor. There are no direct `Observation(...)` constructors in tests at the baseline.

## 2.6 Step and task identity

`Step.id` and `AgentState.task_id` are strings with UUID defaults.

All production steps reaching ToolExecutor have a non-blank ID. Two test helpers use `SimpleNamespace` without `.id` and must be updated:

```text
tests/test_tools.py
tests/test_tool_registry.py
```

## 2.7 Planning and LLM state

Planning is rule-based. No production LLM goal interpreter, planner, replanner, prompt assembler, or research synthesizer is active.

SF1 records trust metadata; it does not enable or enforce LLM behavior.

---

# 3. Objective

SF1 must:

1. define explicit trust levels;
2. extend source classification;
3. define a text-only immutable evidence envelope;
4. annotate Agent-side memory context as untrusted evidence;
5. annotate every ToolExecutor observation as untrusted tool evidence;
6. retain stable source references;
7. preserve Memory Contract v1 and wire JSON;
8. preserve `ToolResult`;
9. preserve `AgentState`, `Step`, `SessionState`, and `TurnRecord` field sets;
10. preserve `RuntimeAgent.__init__`;
11. preserve execution, policy, approval, error, and ordering semantics;
12. provide reproducible evidence for every acceptance criterion.

---

# 4. Non-goals

SF1 must not implement or change:

- LLM goal understanding;
- LLM planning or replanning;
- research synthesis;
- prompt assembly;
- prompt-injection detection or sanitization;
- planner behavior;
- PolicyEngine behavior;
- ApprovalGate behavior or approval scoping;
- new tools or skills;
- real web fetch;
- workspace tools;
- external skills or plugin loading;
- MCP or A2A;
- Memory Contract v2;
- memory wire models or fixtures;
- session persistence;
- `AgentState` field set;
- `ToolResult` field set;
- dependencies or lockfiles;
- CLI behavior;
- end-user workflows;
- evidence persistence.

---

# 5. Architecture invariants

## SF1-I1 — Source and trust are independent

```text
source_type != trust_level
```

Examples:

```text
MEMORY + UNTRUSTED_EVIDENCE
TOOL + UNTRUSTED_EVIDENCE
SYSTEM + TRUSTED_CONFIGURATION
USER + TRUSTED_INSTRUCTION
```

Source type alone must never imply authority.

## SF1-I2 — Retrieved or generated content is untrusted evidence

Memory, web, tool output, and workspace content are represented as:

```text
TrustLevel.UNTRUSTED_EVIDENCE
```

## SF1-I3 — Execution flow remains unchanged

```text
planner
→ plan validation
→ ToolExecutor
→ argument resolution and validation
→ PolicyEngine
→ ApprovalGate
→ tool.fn
→ ToolResult
→ Observation
```

SF1 only adds trust/provenance recording.

## SF1-I4 — Wire contract remains unchanged

No file under these paths may change:

```text
agent_core/memory/wire/**
contracts/**
tests/fixtures/memory_contract_v1/**
```

## SF1-I5 — ToolResult remains unchanged

Trust metadata is attached at the `Observation` boundary, not by modifying `ToolResult`.

## SF1-I6 — AgentState does not become an evidence store

No field is added to `AgentState`. Existing `observations`, `sources`, and `context_pack` remain in their current roles.

## SF1-I7 — Adapter omission fails loudly

Production adapters must pass trust/source/provenance explicitly. They must not rely on Agent-side defaults.

## SF1-I8 — Evidence metadata is safely immutable for SF1

`EvidenceEnvelope` is frozen. Its metadata is defensively copied, exposed read-only, and restricted to scalar values or tuples of scalar values.

---

# 6. TrustLevel and SourceType

## 6.1 TrustLevel

Modify `agent_core/state/enums.py`.

Add exactly:

```python
class TrustLevel(StrEnum):
    TRUSTED_INSTRUCTION = "trusted_instruction"
    TRUSTED_CONFIGURATION = "trusted_configuration"
    UNTRUSTED_EVIDENCE = "untrusted_evidence"
```

Rules:

- exactly these three values;
- no `UNKNOWN`;
- arbitrary strings are not accepted where runtime validation is defined;
- `EvidenceEnvelope` has no default trust level;
- SF2, not SF1, owns fail-closed action enforcement.

## 6.2 SourceType

Preserve all baseline values and add exactly:

```python
SESSION = "session"
WORKSPACE = "workspace"
SKILL = "skill"
```

Resulting value set:

```text
web
memory
tool
user
agent
system
session
workspace
skill
```

Rules:

- one enum source only;
- do not rename `AGENT`;
- no `UNKNOWN`;
- no new runtime behavior is activated by the new values.

---

# 7. Metadata contract

Add these aliases in `agent_core/safety/evidence.py`:

```python
MetadataScalar = str | int | float | bool | None
MetadataValue = MetadataScalar | tuple[MetadataScalar, ...]
```

Metadata type:

```python
Mapping[str, MetadataValue]
```

Validation rules:

- key must be a string;
- key must not be empty or whitespace-only;
- accepted scalar types are exactly `str`, `int`, `float`, `bool`, and `None`;
- a tuple is accepted only when every item is an accepted scalar;
- lists, dictionaries, sets, bytes, enums, and arbitrary objects are rejected;
- the input mapping is copied;
- tuple values are copied using `tuple(value)`;
- the resulting mapping is wrapped in `MappingProxyType`.

No nested mutable metadata is accepted.

---

# 8. EvidenceEnvelope

## 8.1 File

Create:

```text
agent_core/safety/evidence.py
```

## 8.2 Contract

```python
from collections.abc import Mapping
from dataclasses import dataclass, field

@dataclass(frozen=True)
class EvidenceEnvelope:
    content: str
    source_type: SourceType
    trust_level: TrustLevel
    source_ref: str | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ...
```

## 8.3 Required validation

Reject:

- non-string `content`;
- non-`SourceType` source;
- non-`TrustLevel` trust;
- blank or whitespace-only `source_ref` when non-None;
- invalid metadata key;
- unsupported metadata value;
- nested mutable metadata.

Allow:

- empty content;
- `source_ref=None`;
- empty metadata.

## 8.4 Normalization

`__post_init__` must:

1. validate `content`, `source_type`, and `trust_level`;
2. strip `source_ref` when non-None;
3. reject source reference if blank after stripping;
4. defensively copy metadata;
5. normalize tuple values;
6. expose metadata as `MappingProxyType`;
7. use `object.__setattr__` for normalized frozen fields.

## 8.5 Serialization

No `to_dict`, Pydantic model, persistence model, or wire serialization is added in SF1.

`EvidenceEnvelope` is an additive foundation contract. SF1 does not require `ContextItem` or `Observation` to embed it.

---

# 9. Agent-side ContextItem

## 9.1 File

Modify:

```text
agent_core/memory/contracts.py
```

## 9.2 Additive fields

Add:

```python
source_type: SourceType = SourceType.MEMORY
trust_level: TrustLevel = TrustLevel.UNTRUSTED_EVIDENCE
source_ref: str | None = None
```

Keep every baseline field unchanged.

## 9.3 Compatibility

Defaults exist only to preserve current direct construction in tests and runtime fixtures.

Production adapters must explicitly pass all three fields. This must be proven by a counterfactual spy or equivalent architecture test capturing constructor kwargs.

## 9.4 Agent-side dump behavior

After SF1:

- Python-mode `model_dump()` contains enum objects;
- JSON-mode `model_dump(mode="json")` contains enum string values;
- the three new fields appear only on Agent-side `ContextItem`;
- no Agent-side dump is used as an HTTP request payload.

## 9.5 Wire isolation

SF1 must not change:

```text
ContextRequestV1
ContextResponseV1
ContextItemV1
WriteRequestV1
WriteResponseV1
canonical memory-contract fixtures
```

---

# 10. LocalMemoryClient adapter

## 10.1 File and method

```text
agent_core/memory/local_client.py
LocalMemoryClient._to_item
```

## 10.2 ID validation and normalization

Before constructing `ContextItem`:

```python
if not isinstance(rec.id, str) or not rec.id.strip():
    raise ValueError("MemoryRecord.id must be a non-blank string")

memory_id = rec.id.strip()
```

Use the same normalized value for:

```text
ContextItem.source_ref
ContextItem.metadata["memory_id"]
```

Do not:

- create a synthetic ID;
- use `None`;
- preserve leading/trailing whitespace;
- modify `MemoryRecord`.

## 10.3 Required explicit mapping

```python
ContextItem(
    ...,
    source_type=SourceType.MEMORY,
    trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
    source_ref=memory_id,
    metadata={
        ...,
        "memory_id": memory_id,
    },
)
```

Do not derive trust from confidence, importance, provenance, or record type.

Ranking, token-budget, retrieval, and degraded behavior remain unchanged.

---

# 11. RemoteMemoryClient adapter

## 11.1 File and method

```text
agent_core/memory/remote_client.py
RemoteMemoryClient._to_context_item
```

## 11.2 Wire invariant

`ContextItemV1.memory_id` is already stripped and rejected when blank by the wire `_non_empty` validator.

The adapter must not duplicate or alter the wire contract.

## 11.3 Required explicit mapping

```python
memory_id = item.memory_id

ContextItem(
    ...,
    source_type=SourceType.MEMORY,
    trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
    source_ref=memory_id,
    metadata={
        ...,
        "memory_id": memory_id,
    },
)
```

Required invariant:

```text
source_ref == metadata["memory_id"] == item.memory_id
```

The adapter must pass these fields explicitly, not inherit `ContextItem` defaults.

No HTTP payload, wire model, route, fixture, or split-brain behavior may change.

---

# 12. Observation contract

## 12.1 File

Modify:

```text
agent_core/state/observation.py
```

## 12.2 Resulting field order

```python
@dataclass
class Observation:
    step_index: int
    action: str
    args: dict[str, Any]
    success: bool
    trust_level: TrustLevel
    source_type: SourceType
    source_ref: str | None
    output: Any = None
    error: str | None = None
    sources: list[Source] = field(default_factory=list)
```

The three new fields:

```text
trust_level
source_type
source_ref
```

are mandatory and have no defaults.

They must precede `output`, `error`, and `sources` because:

1. Python dataclasses prohibit required fields after defaulted fields;
2. missing trust metadata must fail at construction instead of being masked by defaults.

## 12.3 Rules

For ToolExecutor observations:

```text
trust_level = UNTRUSTED_EVIDENCE
source_type = TOOL
source_ref = deterministic task/step/tool reference
```

`Observation` remains mutable.  
No new evidence store or metadata field is added.  
`AgentState.observations` remains `list[Observation]`.

---

# 13. ToolExecutor observation boundary

## 13.1 File and methods

Modify only:

```text
agent_core/tools/executor.py
ToolExecutor.execute
ToolExecutor._fail
ToolExecutor._record_result
ToolExecutor._tool_name_value
```

## 13.2 `_record_result` signature

Required shape:

```python
def _record_result(
    self,
    *,
    state: Any,
    step: Step,
    tool_name: ToolName | str,
    args: dict[str, Any],
    result: ToolResult,
) -> None:
    ...
```

Both the direct valid-result call in `execute()` and `_fail()` must pass the original `step`.

No path may derive the source reference from:

```text
state.current_step
step_index
a synthetic step ID
```

## 13.3 Canonical tool name

Use one canonical value for both `Observation.action` and the tool component of `source_ref`:

```python
canonical_tool_name = (
    tool_name.value
    if isinstance(tool_name, ToolName)
    else tool_name.strip()
)

if not canonical_tool_name:
    raise ValueError("canonical tool name must be non-blank")
```

Rules:

- no `repr()`;
- no `ToolName.MEMBER` qualified string;
- no arbitrary object coercion inside `_record_result`;
- input type remains `ToolName | str`.

## 13.4 Frozen observation-producing paths

Exactly these nine baseline paths produce an observation:

| ID | Trigger |
|---|---|
| P1 | `step.action` is not a `ToolName` |
| P2 | `ToolName` is not registered |
| P3 | PolicyEngine denies |
| P4 | ApprovalGate denies |
| P5 | `ValidationError` or `ToolArgsError` during resolve/validate |
| P6 | unexpected `Exception` during resolve/validate |
| P7 | `tool.fn` raises |
| P8 | returned value is not a `ToolResult` |
| P9 | `tool.fn` returns a valid `ToolResult`, regardless of `result.success` |

Every P1–P9 path must:

1. preserve current error/result semantics;
2. pass the original `step`;
3. call `_record_result`;
4. produce `TOOL + UNTRUSTED_EVIDENCE`;
5. use the exact source-reference format;
6. preserve observation ordering.

## 13.5 Unchanged execution behavior

Do not change:

- registry lookup;
- argument resolution;
- structural validation;
- Pydantic validation;
- PolicyEngine ordering or behavior;
- ApprovalGate ordering or behavior;
- invocation semantics;
- ToolResult mutation;
- state slots;
- error strings;
- final result behavior;
- `tool.fn` call count.

---

# 14. Tool observation source reference

## 14.1 Helper

Add to `agent_core/safety/evidence.py`:

```python
def tool_observation_ref(
    *,
    task_id: str,
    step_id: str,
    tool_name: str,
) -> str:
    ...
```

## 14.2 Exact format

```text
task:<task_id>/step:<step_id>/tool:<tool_name>
```

Example:

```text
task:task-123/step:step-456/tool:web_search
```

## 14.3 Validation

The helper must strip and validate every component.

Raise plain `ValueError` when:

- component is not a string;
- component is blank or whitespace-only.

No new exception class is added.

Do not:

- URL-encode components;
- persist the reference;
- use global state;
- create fallback IDs.

`AgentState.task_id` and `Step.id` remain unchanged; malformed explicit values fail loudly at source-reference construction.

---

# 15. Package exports

## 15.1 Safety package

Create:

```text
agent_core/safety/__init__.py
```

Export exactly:

```python
from agent_core.safety.evidence import (
    EvidenceEnvelope,
    MetadataScalar,
    MetadataValue,
)

__all__ = [
    "EvidenceEnvelope",
    "MetadataScalar",
    "MetadataValue",
]
```

Do not re-export the source-reference helper. ToolExecutor imports it directly from `agent_core.safety.evidence`.

## 15.2 State package

Do not modify `agent_core/state/__init__.py`.

Import `TrustLevel` and `SourceType` directly from:

```text
agent_core.state.enums
```

---

# 16. Contract-change classification

## 16.1 Existing contracts intentionally changed

```text
SourceType enum values
Agent-side ContextItem field set
Observation field set
```

## 16.2 New SF1 contracts

```text
TrustLevel
EvidenceEnvelope
MetadataScalar
MetadataValue
agent_core.safety package export surface
tool_observation_ref helper
```

## 16.3 Existing contracts required unchanged

```text
ToolResult
AgentState
Step
SessionState
TurnRecord
RuntimeAgent.__init__
Memory wire v1 models
Memory Contract v1 fixtures
tool execution order and semantics
PolicyEngine
ApprovalGate
session persistence
```

---

# 17. Exact implementation scope

## 17.1 Required production files

Only these production files may change:

```text
agent_core/state/enums.py
agent_core/safety/evidence.py                 # new
agent_core/safety/__init__.py                 # new
agent_core/memory/contracts.py
agent_core/memory/local_client.py
agent_core/memory/remote_client.py
agent_core/state/observation.py
agent_core/tools/executor.py
```

## 17.2 Required and allowed test files

Only these test files may change:

```text
tests/test_evidence_contracts.py              # new
tests/test_contracts.py
tests/test_local_client.py
tests/test_remote_memory_client.py
tests/test_tools.py
tests/test_tool_registry.py
tests/test_memory_contract_fixtures.py
```

Required fixture adjustment:

```text
tests/test_tools.py
tests/test_tool_registry.py
```

Their `SimpleNamespace` step helpers must include a deterministic non-blank `.id`. Prefer a fixed test ID or an explicit helper parameter rather than random UUIDs when exact source-reference assertions are needed.

## 17.3 Frozen documentation

These artifacts are normative and must not be modified during implementation:

```text
docs/specs/SPEC_SF1_TRUST_EVIDENCE_CONTRACTS.md
REPORT_SF1_PREFLIGHT_CLOSURE_VERIFIED.md
docs/standards/VERIFICATION_GATE.md
```

## 17.4 Forbidden files and paths

```text
agent_core/state/agent_state.py
agent_core/state/session_state.py
agent_core/state/__init__.py
agent_core/planning/**
agent_core/skills/**
agent_core/safety/policy.py
agent_core/safety/approval.py
agent_core/session_persistence/**
agent_core/memory/wire/**
contracts/**
tests/fixtures/memory_contract_v1/**
main.py
requirements*
pyproject.toml
lockfiles
```

Any required change outside the exact allowed manifest is a STOP condition.

---

# 18. Test requirements

Test count is not a contract. Required behaviors are.

## 18.1 Enum contracts

- `TrustLevel` has exactly three values.
- `SourceType` preserves six baseline values and adds exactly three values.
- no duplicate trust/source enum exists.

## 18.2 EvidenceEnvelope

Test:

- frozen dataclass;
- string content accepted;
- non-string content rejected;
- exact enum instances accepted;
- invalid trust/source rejected;
- blank source reference rejected;
- `None` source reference accepted;
- source reference stripped;
- metadata input copied;
- exposed mapping is read-only;
- scalar values accepted;
- tuple values accepted and copied;
- list, dict, set, bytes, enum, and arbitrary object values rejected;
- whitespace-only metadata key rejected;
- mutating the original input mapping does not change the envelope;
- no serialization method exists.

## 18.3 ContextItem

Test:

- backward-compatible direct construction;
- default `MEMORY + UNTRUSTED_EVIDENCE + None`;
- explicit trust/source/reference preserved;
- Python and JSON dumps contain the three Agent-side fields;
- baseline fields remain present and behavior remains strict;
- Agent-side fields do not affect wire models.

## 18.4 Local adapter

Test:

- explicit constructor kwargs include all trust/source/reference fields;
- default `MemoryRecord.id` is preserved;
- `id=""` raises `ValueError`;
- whitespace-only ID raises `ValueError`;
- padded ID is normalized;
- `source_ref` and `metadata["memory_id"]` use the same normalized value;
- ranking, token, provenance, and existing metadata semantics remain unchanged.

## 18.5 Remote adapter

Test:

- explicit constructor kwargs include all trust/source/reference fields;
- valid wire ID is used identically in source reference and metadata;
- padded wire ID is normalized by wire validation;
- blank and whitespace-only wire IDs fail during wire validation;
- HTTP request/response payload behavior remains unchanged;
- degraded behavior remains unchanged.

## 18.6 Observation and ToolExecutor

For every frozen path P1–P9, test:

- original step is retained;
- observation source is `TOOL`;
- observation trust is `UNTRUSTED_EVIDENCE`;
- exact source-reference format;
- task ID included;
- original step ID included;
- canonical tool name included;
- no fallback to `step_index`;
- existing result/error semantics preserved.

Also test:

- Observation constructor requires all three new fields;
- invalid args do not invoke the tool;
- policy still precedes approval;
- approval still precedes tool invocation;
- `tool.fn` retains one production call site;
- observation order remains unchanged;
- valid `ToolResult(success=False)` uses P9 and is recorded without being treated as an exception path;
- blank task/step/tool components make the helper raise `ValueError`.

## 18.7 Contract and wire snapshots

Candidate verification must compare exact field tuples/signatures and fixture hashes against §21.

No test may update a frozen fixture to make the candidate pass.

---

# 19. Acceptance criteria

| ID | Criterion |
|---|---|
| AC-SF1-01 | `TrustLevel` has exactly the three approved values in the single enum source. |
| AC-SF1-02 | `SourceType` preserves baseline values and adds exactly `SESSION`, `WORKSPACE`, and `SKILL`. |
| AC-SF1-03 | `EvidenceEnvelope` is frozen, text-only, validates source/trust/reference, and has no serialization behavior. |
| AC-SF1-04 | Envelope metadata is defensively copied, read-only, and contains no nested mutable values. |
| AC-SF1-05 | Agent-side `ContextItem` gains the three additive fields with approved defaults. |
| AC-SF1-06 | Local memory mapping explicitly emits `MEMORY + UNTRUSTED_EVIDENCE + normalized record ID`. |
| AC-SF1-07 | Local adapter rejects blank IDs and uses one normalized ID for source reference and metadata. |
| AC-SF1-08 | Remote mapping explicitly emits `MEMORY + UNTRUSTED_EVIDENCE + normalized wire ID`. |
| AC-SF1-09 | Memory wire v1 models, payloads, fixtures, and forbidden wire paths remain unchanged. |
| AC-SF1-10 | `Observation` adds exactly the three mandatory trust/source/reference fields in the approved order. |
| AC-SF1-11 | Every frozen path P1–P9 passes the original step and records `TOOL + UNTRUSTED_EVIDENCE`. |
| AC-SF1-12 | Every tool observation uses the exact task/step/tool source-reference format with canonical tool-name normalization. |
| AC-SF1-13 | `ToolResult`, `AgentState`, `Step`, `SessionState`, `TurnRecord`, and `RuntimeAgent.__init__` remain unchanged. |
| AC-SF1-14 | Tool execution, argument validation, policy, approval, error flow, observation order, and ToolResult semantics remain unchanged. |
| AC-SF1-15 | No planner, prompt, LLM, approval redesign, new dependency, or enforcement behavior is introduced. |
| AC-SF1-16 | Exact production and test scope matches §17; forbidden paths are untouched. |
| AC-SF1-17 | All baseline and SF1 tests pass, and targeted SF1 tests pass three consecutive times. |
| AC-SF1-18 | Candidate is committed, worktree is clean, evidence is reproducible, and every criterion is PASS. |

`FAIL` or `UNVERIFIED` on any criterion means `NO-GO`.

---

# 20. Completed preflight

The read-only preflight is complete and must not be rerun to silently change this contract.

Frozen facts:

```text
Observation production constructors: 1
Observation-producing paths: P1–P9
Production steps have Step.id: yes
AgentState has task_id: yes
Agent-side ContextItem isolated from wire v1: yes
Local ID needs adapter validation: yes
Remote ID normalized by wire validator: yes
Exact production files: 8
Exact test files: 7
Baseline tests: 404 passed
```

If implementation discovers different facts, STOP. Do not rewrite the frozen list inside the implementation task.

---

# 21. Frozen baseline snapshots

Baseline SHA:

```text
c50f80feb65917d64135f9bf1517006a42ef342d
```

## 21.1 Public contracts

Authoritative exact values:

```python
ToolResult = (
    "success",
    "output",
    "error",
    "tool_name",
    "kind",
    "sources",
    "metadata",
)

AgentState = (
    "goal",
    "task_id",
    "user_id",
    "session_id",
    "status",
    "plan",
    "current_step",
    "done",
    "final_answer",
    "last_result",
    "slots",
    "memory",
    "history",
    "observations",
    "sources",
    "errors",
    "context_pack",
    "memory_degraded",
    "memory_write_failed",
    "disclosure_reasons",
    "context_consumed",
    "max_steps",
    "approved_tools",
    "read_only",
)

Step = (
    "thought",
    "action",
    "args",
    "id",
    "status",
    "risk_level",
    "depends_on",
    "created_at",
    "metadata",
)

Observation = (
    "step_index",
    "action",
    "args",
    "success",
    "output",
    "error",
    "sources",
)

SessionState = (
    "session_id",
    "created_at",
    "updated_at",
    "turns",
)

TurnRecord = (
    "task_id",
    "goal",
    "final_answer",
    "status",
    "planned_actions",
    "memory_degraded",
    "memory_write_failed",
    "disclosure_reasons",
    "completed_at",
)
```

`RuntimeAgent.__init__` baseline:

```text
(self, planner: 'Any', tools: 'Mapping[ToolName, ToolSpec]',
 executor: 'ToolExecutor | None' = None,
 final_composer: 'FinalComposer | None' = None,
 lifecycle: 'RuntimeLifecycle | None' = None,
 debug: 'bool' = False, *,
 memory_client: 'MemoryClientProtocol | None' = None)
```

Baseline fingerprints, used as supplementary evidence:

| Contract | Fingerprint |
|---|---|
| ToolResult | `ab6086cb80d0385b` |
| AgentState | `8c305bf9fa470d27` |
| Step | `faca5d0708159a34` |
| Observation | `e8318730928735d6` |
| SessionState | `466d0bb05d7e8daf` |
| TurnRecord | `36639c741186bf42` |
| RuntimeAgent.__init__ | `531bfb2b67ef1987` |

Candidate expectation:

```text
Observation adds:
trust_level
source_type
source_ref

All other field tuples/signatures remain exact.
```

## 21.2 Wire model fields

```python
ContextRequestV1 = (
    "schema_version",
    "request_id",
    "project_id",
    "user_id",
    "session_id",
    "query",
    "type_filter",
    "token_budget",
    "max_items",
)

ContextResponseV1 = (
    "schema_version",
    "request_id",
    "project_id",
    "user_id",
    "session_id",
    "query",
    "memory_source",
    "tokenizer_id",
    "items",
    "total_items",
    "tokens_used",
    "token_budget",
    "truncated",
    "degraded",
    "warnings",
)

ContextItemV1 = (
    "memory_id",
    "type",
    "content",
    "tags",
    "importance",
    "confidence",
    "source_task_id",
    "evidence_ref",
    "score",
    "token_cost",
    "created_at",
    "updated_at",
    "metadata",
)
```

Fingerprints:

| Model | Fingerprint |
|---|---|
| ContextRequestV1 | `3ebd31efefde75bc` |
| ContextResponseV1 | `6d10a3bb0831c168` |
| ContextItemV1 | `3bb9c930b8fd2c7a` |

## 21.3 Canonical fixture SHA-256

| Fixture | SHA-256 |
|---|---|
| `context_request.json` | `9ff6e7bd3888ad6bfec0c509382904c530dffe097527288f86877aa09e23717c` |
| `context_response.json` | `c6f9c5c2c9eaf600f34f374f3133e4176ab33fa816d037469fa80a5826af99a7` |
| `error_response.json` | `02fb82affab0458ee72698062eabb96078984633339bb6b89daf05014846e3a4` |
| `manifest.json` | `e34480e17722a66f6eabde32aa1715350dd47eba867a1f5f465c7b2127f62eb3` |
| `write_request.json` | `834ff693b8f1b0526eb68526c80f9818f68946167e3418948fbf97720a1432b8` |
| `write_response.json` | `a14ff0fc2421e29075d247d8c472ed8e191c3b21f84d18bae7488e795c935115` |

**Important:** the `manifest.json` hash above must be verified against the preflight report before implementation. The authoritative preflight value is:

```text
e34480e17722a66f6eabde32aa1715350dd47eba867a1f5f465c7b2127f62eb3
```

Candidate verification must use the authoritative value immediately above.

Canonical JSON method:

```python
json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
```

---

# 22. Implementation procedure

## 22.1 Before coding

The implementer must:

1. confirm branch `main` and baseline SHA;
2. confirm `404 passed`;
3. confirm no tracked changes;
4. compute and record this spec's SHA-256;
5. confirm exact allowed and forbidden path manifest;
6. create implementation branch;
7. record initial untracked files without modifying them.

If baseline differs, STOP.

## 22.2 Implementation order

```text
SF1-A  add TrustLevel and SourceType values
SF1-B  add EvidenceEnvelope, metadata validation, and tool_observation_ref
SF1-C  extend Agent-side ContextItem
SF1-D  update local and remote memory adapters
SF1-E  extend Observation
SF1-F  thread original Step through ToolExecutor and cover P1–P9
SF1-G  add/update tests in the exact manifest
SF1-H  run implementation tests
SF1-I  commit candidate
SF1-J  freeze candidate and run separate read-only verification
```

## 22.3 Candidate freeze

Before verification:

- all implementation and tests are committed;
- candidate SHA is recorded;
- worktree is clean;
- spec is unchanged;
- no staged, unstaged, or untracked implementation artifacts remain;
- no additional implementation commit is permitted during verification.

---

# 23. Verification requirements

Verification must follow `VERIFICATION_GATE.md`.

Required evidence includes:

1. full committed patch;
2. exact scope diff;
3. `git diff --check`;
4. worktree status;
5. enum values;
6. EvidenceEnvelope tests;
7. ContextItem field and dump checks;
8. explicit local/remote adapter constructor kwargs;
9. local blank/padded ID tests;
10. remote wire normalization tests;
11. P1–P9 targeted observation tests;
12. exact public-contract comparison;
13. exact wire-field comparison;
14. exact fixture SHA comparison;
15. architecture grep proving one `Observation` production constructor;
16. architecture grep proving one `tool.fn` production call site;
17. targeted SF1 suite repeated three times;
18. full regression;
19. no forbidden-path changes;
20. criterion-by-criterion mapping.

Each acceptance criterion must be classified:

```text
PASS
FAIL
UNVERIFIED
WAIVED
```

Any `FAIL` or `UNVERIFIED` means `NO-GO`.  
Only a human/architect can approve a waiver.

`GO` means only:

```text
candidate is eligible for human/architect approval
```

It does not authorize merge or the next phase.

---

# 24. Stop conditions

Stop and report if:

1. any memory wire model or fixture must change;
2. Memory Contract v1 must change;
3. `ToolResult` must change;
4. `AgentState`, `Step`, `SessionState`, or `TurnRecord` must change;
5. `RuntimeAgent.__init__` must change;
6. session persistence must change;
7. planner, PolicyEngine, or ApprovalGate behavior must change;
8. a dependency must be added;
9. a production or test file outside §17 must change;
10. baseline tests must be deleted, weakened, skipped, or rewritten to hide regression;
11. a P1–P9 path cannot pass original `Step`;
12. any path needs `step_index` or a synthetic ID for provenance;
13. a second production `Observation` constructor is discovered;
14. Agent-side `ContextItem` is used as a wire payload;
15. the frozen baseline snapshots cannot be reproduced;
16. this spec or its acceptance criteria require amendment.

Do not solve a stop condition by silently widening scope.

---

# 25. Commit strategy

Recommended implementation commits:

## Commit 1

```text
feat(SF1): add trust and evidence contracts
```

Includes:

- enum additions;
- evidence module;
- safety package export;
- ContextItem additions;
- contract tests.

## Commit 2

```text
feat(SF1): annotate memory and tool observations
```

Includes:

- local and remote adapters;
- Observation;
- ToolExecutor;
- executor and adapter tests.

Do not merge.

A different intentional commit split is allowed only if the final candidate scope and behavior are identical.

---

# 26. Required implementation report

The implementer must provide:

1. baseline SHA and baseline tests;
2. spec SHA-256;
3. branch and candidate SHA;
4. exact changed files;
5. full committed patch;
6. raw targeted tests;
7. raw full regression;
8. raw three-run repeatability output;
9. `git diff --check`;
10. worktree status;
11. P1–P9 evidence;
12. AC-SF1-01 through AC-SF1-18 mapping;
13. public-contract snapshot comparison;
14. wire snapshot and fixture hash comparison;
15. proof local and remote adapters set trust explicitly;
16. proof local ID rejects blank and normalizes padded values;
17. proof remote ID is normalized by wire validation and reused consistently;
18. proof no LLM, prompt, planner, policy, approval, dependency, or forbidden-path change occurred;
19. deviations and residual risks.

Final implementation report state:

```text
SF1 IMPLEMENTED
PENDING READ-ONLY VERIFICATION
NOT MERGED
```

After the separate verification pass:

```text
GO or NO-GO
DỪNG
```

---

# 27. Definition of done

SF1 is done only when:

```text
TrustLevel is explicit
SourceType is explicit
EvidenceEnvelope is validated and immutable
memory context is marked as untrusted memory evidence
tool observations are marked as untrusted tool evidence
stable provenance references are retained
local IDs fail loud and normalize
remote wire IDs remain unchanged and consistent
wire contracts and fixtures remain unchanged
runtime behavior remains unchanged
all acceptance criteria pass
candidate is independently reviewed
human/architect approves merge
main and origin/main are synchronized after merge
```

SF1 completion does not authorize SF2 or any LLM activation.

## 27.1 Product-validation gate for SF2

This is governance, not an SF1 technical acceptance criterion.

Before SF2 starts, the project must record at least three new customer-discovery interviews with ICP developers using AI coding agents across multi-session codebases.

Track them in:

```text
docs/validation/INTERVIEWS.md
```

Each record must include:

```text
date
participant/role or anonymized identifier
stated pain
current workaround
willingness to try
key disconfirming evidence
```

Future SF2 prerequisite:

```text
SF1 CLOSED
AND
product-validation gate satisfied
```

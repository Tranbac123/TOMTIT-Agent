# SPEC_EX1_TOOL_REGISTRY.md

> **Version:** 1.0  
> **Status:** APPROVED FOR IMPLEMENTATION  
> **Phase:** EX1 — Static Tool Registry  
> **Baseline:** `503ea5d` (main; one chore/.gitignore commit on top of `44989d6`, 214 tests pass)  
> **Verified tests:** 214 passed  
> **Primary outcome:** add and describe tools without modifying runtime core
>
> **Current-HEAD facts (verified 2026-06-17, commit `44989d6` source files):**
>
> - Built-in `ToolName` members: 13
> - Registered built-in tools: 13 (CALCULATE, WRITE_NOTE, READ_NOTE, LIST_NOTES, SAVE_FACT, SAVE_PREFERENCE, SAVE_DECISION, SEARCH_MEMORY, SUMMARIZE_MEMORY, SUMMARIZE, WEB_SEARCH, FINISH, ANSWER_FROM_CONTEXT)
> - Current `ToolRegistry` class: orphaned — never instantiated in production; `build_tool_registry()` returns raw `dict[ToolName, ToolSpec]`
> - Current `ToolRegistry` does NOT implement `Mapping` (no `__getitem__`/`__iter__`/`__len__`)
> - All 13 built-ins have `args_schema = None`
> - `ToolExecutor` schema-validation path exists (lines 177–181) but is never exercised
> - `WEB_SEARCH.timeout_seconds = 15.0` — executor does not enforce; corrected to `None` in EX1
> - Pydantic version: 2.11.9 (v2 strict models supported)
> - `agent_core/tools/errors.py`: does not exist — must be created
> - `agent_core/tools/input_schemas.py`: does not exist — must be created
> - `agent_core/tools/__init__.py`: does not exist
>
> **Boundary:**
>
> - Pydantic = tool-input validation DTO only, NOT agent/domain state

---

## 0. Objective

Standardize TOMTIT-Agent's tool catalog so every executable tool has one validated specification, one strict input contract and one immutable registry entry consumed consistently by planning, safety and execution.

```text
tool implementation
→ ToolSpec
→ static provider
→ immutable ToolRegistry
→ planner / validator / executor / safety
```

EX1 does not add new user capability. It creates the extension boundary needed by real tools and the EX2 Skill Registry.

---

## 1. Product result

After EX1, adding a new built-in tool requires only:

1. add a `ToolName` enum member;
2. implement the tool function;
3. define its strict input schema;
4. add one `ToolSpec` to a static provider;
5. add tool-specific tests.

It must not require behavioral changes to:

- `RuntimeAgent`;
- `ToolExecutor`;
- `PolicyEngine`;
- `ApprovalGate`;
- the general plan validator.

---

## 2. Scope

### Included

- immutable `ToolRegistry`;
- duplicate rejection;
- deterministic registry and manifest order;
- static provider composition;
- strict input schemas for every built-in tool;
- schema/required/allowed argument parity;
- planner-safe tool manifest;
- honest timeout/retry defaults;
- compatibility with `Mapping[ToolName, ToolSpec]`;
- regression coverage for all existing tools.

### Excluded

- EX2 Skill Registry;
- LLM planner;
- real web implementation;
- asynchronous executor;
- actual timeout enforcement;
- actual retry execution;
- dynamic plugins;
- Python entry points;
- MCP;
- remote tool servers;
- marketplace;
- hot reload;
- tool version migrations;
- risk-classifier redesign;
- approval-policy redesign;
- new user-facing tools.

---

## 3. Architectural invariants

### EX1-I1 — One execution gate

All tool calls continue through `ToolExecutor`.

No provider, registry, planner or skill may call `tool.fn` directly during runtime execution.

### EX1-I2 — One specification per tool name

A registry contains at most one `ToolSpec` for each `ToolName`.

Duplicate names fail during composition.

### EX1-I3 — Immutable after construction

After `ToolRegistry.from_specs()` returns, entries cannot be added, removed or replaced.

### EX1-I4 — Registry is a Mapping

`ToolRegistry` implements:

```python
Mapping[ToolName, ToolSpec]
```

Existing consumers expecting a mapping continue to work.

### EX1-I5 — Schema is enforced before invocation

After argument placeholder resolution:

```text
resolved args
→ structural required/allowed validation
→ strict input-schema validation
→ policy
→ approval
→ tool function
```

Invalid arguments never reach the tool function.

### EX1-I6 — Safety metadata stays declarative

`risk_level`, `mutates_state`, `side_effects` and `requires_approval` remain metadata interpreted by existing safety components.

The registry does not grant approval.

### EX1-I7 — No unsupported execution-policy claims

Until a later execution-control phase:

```text
timeout_seconds must be None
retry max_attempts must be 1
retry backoff must be 0
```

Non-default values make registry construction fail.

### EX1-I8 — Manifest never exposes callable objects

Planner-facing descriptors contain no `fn`, client instance, secret or runtime state.

---

## 4. Contracts

## 4.1 ToolSpec

Preserve the current public shape unless current-HEAD inventory proves a necessary correction.

Normative semantics:

```python
@dataclass(frozen=True)
class ToolSpec:
    name: ToolName
    fn: ToolFn
    description: str
    required_args: frozenset[str]
    allowed_args: frozenset[str]
    mutates_state: bool = False
    risk_level: RiskLevel = RiskLevel.LOW
    side_effects: tuple[str, ...] = ()
    requires_approval: bool = False
    timeout_seconds: float | None = None
    retry_policy: RetryPolicy = RetryPolicy()
    idempotent: bool = True
    args_schema: type[BaseModel] | None = None
```

EX1 requires `args_schema` for all production built-in tools.

### ToolSpec validation

Construction or registry validation must reject:

- name is not `ToolName`;
- function is not callable;
- blank description;
- required args not a subset of allowed args;
- empty or duplicate argument names;
- empty or duplicate side-effect names;
- `mutates_state=True` with no declared side effect;
- schema field set differs from `allowed_args`;
- schema required-field set differs from `required_args`;
- schema allows extra fields;
- schema is non-strict;
- unsupported timeout;
- unsupported retry attempts/backoff.

Do not enforce a new rule such as “MEDIUM always requires approval” in EX1. That belongs to safety policy.

## 4.2 RetryPolicy

If the class remains in the current codebase, EX1 supports only the no-retry value:

```python
RetryPolicy(
    max_attempts=1,
    backoff_seconds=0,
)
```

Any other value raises `UnsupportedToolExecutionPolicyError`.

## 4.3 Input schemas

Create strict Pydantic v2 models:

```python
class ToolArgsModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )
```

Every built-in tool gets one model.

Examples:

```python
class EmptyArgs(ToolArgsModel):
    pass

class CalculateArgs(ToolArgsModel):
    expression: str

class WriteNoteArgs(ToolArgsModel):
    name: str
    content: str

class WebSearchArgs(ToolArgsModel):
    query: str
    max_results: int = Field(default=3, ge=1, le=10)
```

Exact models must follow the actual current tool signatures.

## 4.4 ToolManifestEntry

```python
@dataclass(frozen=True)
class ToolManifestEntry:
    name: ToolName
    description: str
    required_args: tuple[str, ...]
    allowed_args: tuple[str, ...]
    input_schema: Mapping[str, object]
    mutates_state: bool
    risk_level: RiskLevel
    side_effects: tuple[str, ...]
    requires_approval: bool
    idempotent: bool
```

Manifest values must be detached from registry internals.

---

## 5. ToolRegistry

```python
class ToolRegistry(Mapping[ToolName, ToolSpec]):

    @classmethod
    def from_specs(
        cls,
        specs: Iterable[ToolSpec],
    ) -> ToolRegistry:
        ...

    def __getitem__(self, name: ToolName) -> ToolSpec:
        ...

    def __iter__(self) -> Iterator[ToolName]:
        ...

    def __len__(self) -> int:
        ...

    def get(
        self,
        name: ToolName,
        default: ToolSpec | None = None,
    ) -> ToolSpec | None:
        ...

    def require(self, name: ToolName) -> ToolSpec:
        ...

    def all(self) -> Mapping[ToolName, ToolSpec]:
        ...

    def manifest(self) -> tuple[ToolManifestEntry, ...]:
        ...
```

### Registry behavior

- Preserve provider insertion order.
- Reject duplicate names.
- `require()` raises `UnknownToolError`.
- `all()` returns a read-only mapping or detached immutable view.
- `manifest()` returns a deterministic tuple.
- No public mutation method.
- Registry construction validates every specification.

### Typed errors

```python
class ToolRegistryError(Exception): ...
class DuplicateToolError(ToolRegistryError): ...
class UnknownToolError(ToolRegistryError): ...
class InvalidToolSpecError(ToolRegistryError): ...
class UnsupportedToolExecutionPolicyError(ToolRegistryError): ...
```

---

## 6. Static providers

Replace the monolithic dictionary construction with static provider functions.

```python
@dataclass(frozen=True)
class BuiltinToolDependencies:
    web_search_client: WebSearchClient
```

```python
def builtin_tool_specs(
    dependencies: BuiltinToolDependencies,
) -> tuple[ToolSpec, ...]:
    ...
```

```python
def build_tool_registry(
    web_search_client: WebSearchClient | None = None,
) -> ToolRegistry:
    dependencies = BuiltinToolDependencies(
        web_search_client=web_search_client or FakeWebSearchClient(),
    )
    return ToolRegistry.from_specs(
        builtin_tool_specs(dependencies)
    )
```

No provider may mutate the registry after construction.

EX1 may split providers by domain only if it reduces coupling without changing behavior:

```text
core tools
memory tools
web tools
```

Do not create a plugin-discovery abstraction.

---

## 7. ToolExecutor integration

### Required flow

```text
Step.args
→ ArgResolver.resolve_args()
→ required/allowed check
→ spec.args_schema.model_validate(...)
→ model_dump()
→ PolicyEngine.check()
→ ApprovalGate.check()
→ spec.fn(state, **validated_args)
→ ToolResult validation
→ Observation
```

### Failure behavior

Input validation failure:

- tool function is not called;
- observation records failure through the existing error path;
- error text does not expose Pydantic internals unnecessarily;
- runtime behavior remains deterministic.

Schema validation is not a policy rejection and not an approval rejection.

### Placeholder note

Schema validation must occur after placeholder resolution. Plans may contain placeholders that are not valid final argument types before resolution.

---

## 8. Planner and skill integration

### Planner

Later guarded planners consume `registry.manifest()`.

They do not receive callable functions.

EX1 does not modify current rule-based planning behavior.

### EX2 Skill Registry

A future `SkillSpec` may declare:

```text
required_tools: frozenset[ToolName]
```

EX2 validates those references against `ToolRegistry`.

EX1 must not implement skill selection.

---

## 9. Composition

`build_tool_registry()` returns `ToolRegistry`.

Because it implements `Mapping`, `RuntimeAgent` should not need behavioral changes.

If the current composition converts the registry back into a mutable dict, remove that conversion.

No change to the public return shape of the main agent factory unless separately approved.

---

## 10. File scope

Expected files:

```text
agent_core/tools/base.py
agent_core/tools/errors.py                 # new
agent_core/tools/input_schemas.py          # new
agent_core/tools/registry.py
agent_core/tools/executor.py
tests/test_tool_registry.py                # new
tests/test_tools.py
tests/test_runtime_agent.py                # only compatibility tests if needed
```

Conditionally allowed after direct verification:

```text
agent_core/runtime/runtime_agent.py         # annotation/import only
agent_core/planning/plan_validator.py       # Mapping compatibility only
main.py or composition module              # builder return type wiring only
agent_core/tools/__init__.py                # exports only
```

Out of scope:

```text
agent_core/skills/**
agent_core/safety/**                        # no policy redesign
agent_core/state/agent_state.py
agent_core/runtime/session_runtime.py
agent_core/session_persistence/**
```

---

## 11. Test matrix

### Registry

1. Build from unique specs.
2. Duplicate name raises `DuplicateToolError`.
3. No silent overwrite.
4. Registry is immutable.
5. `all()` cannot mutate internal state.
6. `require()` returns known tool.
7. `require()` rejects unknown tool.
8. Iteration order is deterministic.
9. Manifest order matches registry order.
10. Manifest contains no function object.

### ToolSpec

11. Blank description rejected.
12. Required args must be allowed.
13. Duplicate/empty arg names rejected.
14. Mutating tool without side effect rejected.
15. Duplicate/blank side effects rejected.
16. Schema fields must match allowed args.
17. Schema required fields must match required args.
18. Non-strict schema rejected.
19. Extra-allowing schema rejected.
20. Unsupported timeout rejected.
21. Unsupported retry rejected.

### Executor

22. Valid schema arguments reach tool.
23. Wrong type does not reach tool.
24. Extra argument does not reach tool.
25. Missing argument does not reach tool.
26. Defaults are applied intentionally.
27. Placeholder is resolved before schema validation.
28. Policy still runs before invocation.
29. Approval still runs before invocation.
30. ToolResult contract remains enforced.

### Built-ins

31. Every registered built-in has an input schema.
32. Every registry key equals `ToolSpec.name`.
33. No duplicate built-in names.
34. Actual current built-in count is asserted from current HEAD.
35. Existing risk/mutation/approval metadata is preserved unless a separate decision changes it.
36. Existing rule-based flows remain green.
37. Adding a test tool through a provider requires no runtime/executor modification.

### Regression

38. Full pre-EX1 suite remains green.
39. Import sanity remains green.
40. SR1–SR3 session behavior remains unchanged.

Test count is not an acceptance contract; report actual tests and map names to invariants.

---

## 12. Acceptance criteria

EX1 is complete only when:

- [ ] `ToolRegistry` is the runtime catalog object.
- [ ] It implements immutable `Mapping`.
- [ ] Duplicate names fail loud.
- [ ] All current built-ins have strict input schemas.
- [ ] Schema and required/allowed metadata cannot drift.
- [ ] ToolExecutor validates schema after argument resolution.
- [ ] Manifest is deterministic and contains no callables.
- [ ] Existing policy and approval behavior remains intact.
- [ ] Non-default timeout/retry claims are rejected.
- [ ] Existing tool flows pass unchanged.
- [ ] A new test tool can be added without editing runtime core.
- [ ] No skill, LLM or plugin-discovery work is introduced.
- [ ] Full regression suite passes.

---

## 13. Implementation order

```text
EX1-A current-HEAD verification
→ EX1-B registry errors and immutable Mapping
→ EX1-C strict built-in input schemas
→ EX1-D executor schema enforcement
→ EX1-E static providers and manifest
→ EX1-F regression and extension proof
```

Do not refactor all tool implementations at once. Preserve current tool behavior and change the contract/composition boundary first.

---

## 14. Required implementation report

The executor must provide:

1. commit hash;
2. full committed patch;
3. raw targeted tests;
4. raw full pytest;
5. exact files changed;
6. mapping of every new test to an acceptance criterion;
7. current built-in tool inventory after EX1;
8. proof that duplicate registration fails;
9. proof that manifest contains no callable;
10. proof that adding a test provider does not change runtime core;
11. all deviations and unknowns.

Do not merge before architect gate.

---

## 15. Definition of done for the roadmap

EX1 does not make the Agent substantially smarter.

It establishes:

```text
stable tool contract
+ immutable catalog
+ strict inputs
+ planner-safe manifest
```

This is the required base for:

```text
EX2 Static Skill Registry
→ SF1/SF2 Safety
→ Goal Understanding
→ Guarded Planner
→ Real Tools
```

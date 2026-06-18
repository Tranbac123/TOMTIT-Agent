# REPORT_EX2_STATIC_SKILL_REGISTRY_INVENTORY_VERIFIED.md

> **Phase:** EX2 — Static Skill Registry Inventory
> **Status:** VERIFIED — read-only inventory complete (rev 2)
> **Baseline:** `cf471dde` / 298 passed (CONFIRMED — see §0.1)
> **Verified at:** 2026-06-18
> **Operator:** Claude Code (executor, read-only role)

---

## 0. Baseline

### 0.1 Hard gate raw output

```bash
$ git switch main
Already on 'main'
Your branch and 'origin/main' have diverged,
and have 7 and 1 different commits each, respectively.

$ git rev-parse HEAD
cf471dde194ec17e1e011e1154826bdf5316475b

$ git status --short
(empty — working tree clean)

$ pytest -q
298 passed in 0.76s
```

### 0.2 Baseline deviation — NOTED

**VERIFIED_DIRECTLY**

**BASELINE CONFIRMED:** `HEAD == cf471dde`, `298 passed`

Directive expected `2da7040` / 261 passed. Local `main` has 6 M6 commits ahead
of `origin/main` (`2da7040`). Per user instruction "tiếp tục làm," `cf471dde` / 298
is the authoritative baseline for this report.

```
cf471dd docs: record M6 verification results
2c94d6e feat(agent): add memory backend activation guard
677f369 feat(agent): add remote durable memory client
4de72c7 build(agent): add reproducible Python project setup
a29199d docs: remove M6 working spec from Agent baseline
46db7b1 docs: fix M6 spec whitespace
c1c2db2 merge: complete EX1 static tool registry   ← EX1 present
```

**Raw diff `2da7040..cf471dde` — skills/planning/runtime/composition (VERIFIED_DIRECTLY)**

```
git diff 2da7040..cf471dde -- 'agent_core/skills/**' 'agent_core/planning/**' \
  'agent_core/runtime/**' 'main.py' 'agent_core/__init__.py'
```

Result — files touched in these directories:

| File | Change |
|---|---|
| `agent_core/runtime/runtime_agent.py` | MODIFIED — see patch below |
| `main.py` | MODIFIED — see patch below |
| `agent_core/skills/**` | **ZERO DIFF** — no change |
| `agent_core/planning/**` | **ZERO DIFF** — no change |
| `agent_core/__init__.py` | **ZERO DIFF** — no change |

**`agent_core/runtime/runtime_agent.py` patch (M6 changes only):**

```diff
 def build_local_agent(*, planner=None, tools=None):
+    from agent_core.memory.factory import validate_memory_activation
     store = InMemoryStore()
     memory_client = LocalMemoryClient(store)
+    resolved_tools = tools or build_tool_registry(FakeWebSearchClient())
+    validate_memory_activation(memory_client=memory_client, tools=resolved_tools)
     agent = RuntimeAgent(
         planner=planner or RuleBasedPlanner(),
-        tools=tools or build_tool_registry(FakeWebSearchClient()),
+        tools=resolved_tools,
         memory_client=memory_client,
     )
     return agent, store

+def build_agent_with_memory_backend(*, memory_config, planner=None, tools=None):
+    from agent_core.memory.factory import build_memory_backend, validate_memory_activation
+    components = build_memory_backend(memory_config)
+    resolved_tools = tools or build_tool_registry(
+        FakeWebSearchClient(), disabled_tools=components.disabled_tools)
+    validate_memory_activation(memory_client=components.memory_client, tools=resolved_tools)
+    agent = RuntimeAgent(
+        planner=planner or RuleBasedPlanner(),
+        tools=resolved_tools,
+        memory_client=components.memory_client,
+    )
+    return agent, components.store
```

`main.py` adds `--memory-backend` / `--memory-base-url` / `--memory-project-id` /
`--memory-user-id` / `--memory-timeout-seconds` CLI flags and wires
`build_agent_with_memory_backend()` for `--memory-backend remote`.

**Impact on skill/planning inventory:** Zero. `RuntimeAgent.__init__` signature
unchanged. `RuleBasedPlanner()` wired identically in all 3 factories. No skill or
planning import added or removed.

**Zero skill or planning files changed.** Inventory is valid at current HEAD.

### 0.3 Untracked files

None. Working tree clean at inventory start.

---

## 1. Files và repository search

### 1.1 Skill files read

**VERIFIED_DIRECTLY** — full file content read:

```
agent_core/skills/base.py
agent_core/skills/calculate_and_save_skill.py
agent_core/skills/read_and_summarize_skill.py
agent_core/skills/web_search_skill.py
```

### 1.2 Planning files read

**VERIFIED_DIRECTLY** — full file content read:

```
agent_core/planning/base.py
agent_core/planning/intent_parser.py
agent_core/planning/intent_planner.py
agent_core/planning/rule_based_planner.py
agent_core/planning/hybrid_planner.py
agent_core/planning/slot_validator.py
agent_core/planning/clarification.py
agent_core/planning/extractors.py
agent_core/planning/intents.py
agent_core/planning/plan_validator.py
agent_core/planning/LLMIntentParser.py  (1 line, empty — placeholder only)
```

### 1.3 Runtime, state, tools read

**VERIFIED_DIRECTLY** — full file content read:

```
agent_core/runtime/runtime_agent.py
agent_core/state/agent_state.py
agent_core/state/enums.py
agent_core/tools/base.py
agent_core/tools/registry.py
agent_core/tools/executor.py
```

### 1.4 Repository search — class/skill grep

```
git grep -n -E "class .*Skill|SkillSpec|SkillRegistry" -- '*.py'

agent_core/skills/base.py:8:class Skill(Protocol):
agent_core/skills/calculate_and_save_skill.py:10:class CalculateAndSaveSkill:
agent_core/skills/read_and_summarize_skill.py:10:class ReadAndSummarizeSkill:
agent_core/skills/web_search_skill.py:10:class WebSearchSkill:
```

**Finding:** `SkillSpec` and `SkillRegistry` do not exist anywhere in the codebase.

### 1.5 Skill references

```
git grep -n -iE "skill" -- '*.py'
```

Results limited to:
- `agent_core/skills/*.py` — 4 files (definitions only)
- `tests/test_skills.py` — 3 direct unit tests

**No skill reference exists in:**
- `agent_core/planning/**`
- `agent_core/runtime/**`
- `agent_core/tools/**`
- `agent_core/safety/**`
- `agent_core/memory/**`
- `main.py`

### 1.6 Step construction sites

```
git grep -n "Step(" -- '*.py'
```

Production code Step() calls:
- `agent_core/planning/intent_planner.py` — 18 `Step(...)` calls (lines 45–176)
- `agent_core/skills/calculate_and_save_skill.py:16-18` — 3 calls
- `agent_core/skills/read_and_summarize_skill.py:15-17` — 3 calls
- `agent_core/skills/web_search_skill.py:16-17` — 2 calls

Test Step() calls:
- `tests/test_session_runtime.py:355-356, 490, 528`

### 1.7 list[Step] return signatures

Production:
- `agent_core/planning/base.py:14` — `Planner.make_plan() -> list[Step]`
- `agent_core/planning/rule_based_planner.py:20` — `make_plan() -> list[Step]`
- `agent_core/planning/hybrid_planner.py:23` — `make_plan() -> list[Step]`
- `agent_core/planning/intent_planner.py:16` — `make_plan() -> list[Step]` (+8 private methods)
- `agent_core/skills/base.py:9` — `Skill.make_steps() -> list[Step]`
- `agent_core/skills/*.py` — each skill's `make_steps() -> list[Step]`

### 1.8 Planner routing

```
git grep -n -E "RuleBasedPlanner|IntentParser|IntentPlanner" -- '*.py'
```

Production usage:
- `agent_core/runtime/runtime_agent.py:319, 343, 355` — `planner or RuleBasedPlanner()`

`HybridPlanner` exists in `agent_core/planning/hybrid_planner.py` but has **zero production call sites** (no import in runtime or __init__).

### 1.9 ToolExecutor — single call site

```
agent_core/tools/executor.py:120  result = tool.fn(state=state, **final_args)
```

All other `tool.fn` calls are in tests only (`tests/test_tools.py`). No skill calls `.fn` directly.

---

## 2. Skill inventory

### 2.1 Skill classes

| Skill/class | File | Input (constructor) | Output | Required tools | Creates Step | Calls tool directly | Mutates state | Reads memory | Rule-planner reachable | Runtime selected | Directly tested | Stateful |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `Skill` (Protocol) | `skills/base.py:8` | — | `list[Step]` | — | — | No | No | No | No | No | No | No |
| `CalculateAndSaveSkill` | `skills/calculate_and_save_skill.py:10` | `expression: str`, `note_name: str` | `list[Step]` (3) | CALCULATE, WRITE_NOTE, FINISH | Yes | No | No | No | **No** | **No** | **Yes** | No |
| `ReadAndSummarizeSkill` | `skills/read_and_summarize_skill.py:10` | `note_name: str` | `list[Step]` (3) | READ_NOTE, SUMMARIZE, FINISH | Yes | No | No | No | **No** | **No** | **Yes** | No |
| `WebSearchSkill` | `skills/web_search_skill.py:10` | `query: str`, `max_results: int = 3` | `list[Step]` (2) | WEB_SEARCH, FINISH | Yes | No | No | No | **No** | **No** | **Yes** | No |

**Summary:**

```
Skill classes (concrete):           3
Skill Protocol definitions:         1
SkillSpec class:                    0 — DOES NOT EXIST
SkillRegistry class:                0 — DOES NOT EXIST
Runtime-reachable skills:           0
Planner-referenced skills:          0
Orphaned skills (tested, not used): 3
Skills with direct execution behavior: 0
```

### 2.2 Key distinction — VERIFIED_DIRECTLY

```
class exists ✓
≠ tested directly ✓ (3 unit tests in test_skills.py)
≠ referenced by planner ✗ (zero planner imports)
≠ selected by runtime ✗ (zero runtime imports)
≠ executed in production flow ✗
```

All 3 skill classes are **orphaned** — they have direct unit tests but are not called by any planner or runtime component.

---

## 3. Current skill contracts

### 3.1 Skill contract table

| Skill | Constructor deps | Public method | Input type | Output type | Errors | Deterministic | Mutable instance state |
|---|---|---|---|---|---|---|---|
| `CalculateAndSaveSkill` | `expression: str`, `note_name: str` | `make_steps()` | primitives (dataclass fields) | `list[Step]` | None declared | Yes | No (frozen-equivalent, though `@dataclass` not frozen) |
| `ReadAndSummarizeSkill` | `note_name: str` | `make_steps()` | primitive | `list[Step]` | None declared | Yes | No |
| `WebSearchSkill` | `query: str`, `max_results: int = 3` | `make_steps()` | primitives | `list[Step]` | None declared | Yes | No |

### 3.2 Answers to contract questions

**VERIFIED_DIRECTLY from source code:**

1. **Input type:** Skills receive constructor primitives (str, int) — NOT `AgentState`, NOT `ParsedIntent`, NOT raw user message.

2. **Output type:** `list[Step]` — plain Python list of `Step` dataclass instances.

3. **Validates input:** No. `@dataclass` fields — no `__post_init__` validation, no type coercion, no schema enforcement.

4. **Self-resolves placeholders:** No. Placeholder strings like `"$last_text"`, `"${slot.calc_result}"` are embedded as raw strings in `Step.args`. `ArgResolver` resolves them at execution time.

5. **Calls memory/tool/client directly:** **No.** Skills only import `Step` and `ToolName`. They do not import or call `ToolExecutor`, `ArgResolver`, or any memory client.

6. **Global or mutable state:** No class-level state. Each `make_steps()` call creates a fresh `list[Step]`.

7. **Reusable between turns/sessions:** Yes — stateless. Each instance holds only constructor args; `make_steps()` is pure.

8. **Success criteria or completion rule:** None.

9. **Applicability predicate:** None.

10. **Required slots or clarification requirements:** Not declared on the skill. Slot requirements are embedded implicitly (missing constructor arg → Python `TypeError`).

---

## 4. Planner flow hiện tại

### 4.1 Production flow

**VERIFIED_DIRECTLY** — `runtime_agent.py:124-125`, `rule_based_planner.py:20-23`:

```
user goal (AgentState.goal: str)
  → RuleBasedPlanner.make_plan(state: AgentState)
      → RuleBasedIntentParser.parse(state.goal)  [regex/prefix dispatch]
      → SlotValidator.validate(parsed)             [fills missing_slots]
      → IntentPlanner.make_plan(parsed)            [if/elif per IntentName]
        → returns list[Step]                       [hard-coded in IntentPlanner private methods]
  → validate_plan(plan, tools)                     [checks tool availability + arg spec]
  → RuntimeAgent._execute_plan(state)
      → ToolExecutor.execute(step, state)  [for each step]
```

Skills are **NOT in this flow**.

### 4.2 Planner implementations

**VERIFIED_DIRECTLY:**

| Planner | File | Production call site | Notes |
|---|---|---|---|
| `RuleBasedPlanner` | `planning/rule_based_planner.py` | `runtime_agent.py:319, 343, 355` | **Active — only production planner** |
| `HybridPlanner` | `planning/hybrid_planner.py` | None | **Orphaned — no production call site** |
| `LLMIntentParser` | `planning/LLMIntentParser.py` | None | **Empty placeholder (1 line)** |
| `Planner` (Protocol) | `planning/base.py:13` | `RuntimeAgent.__init__(planner: Any)` | Protocol — duck-typed |
| `IntentParser` (Protocol) | `planning/base.py:9` | None (not used as type in production) | Protocol only |

### 4.3 Routing mechanism

**VERIFIED_DIRECTLY** — `intent_planner.py:20-41`:

```python
if parsed.intent == IntentName.CALCULATE:
    return self._calculate_plan(parsed)
if parsed.intent == IntentName.CALCULATE_THEN_SAVE_NOTE:
    ...
```

Pure `if/elif` per `IntentName` enum. **No registry, no skill selection, no plugin dispatch.**

### 4.4 Answers to planner questions

1. **Production planner:** `RuleBasedPlanner` exclusively.
2. **Planner count:** 2 exist (`RuleBasedPlanner`, `HybridPlanner`), 1 active.
3. **Planner input:** `AgentState` (for `goal: str`).
4. **Where Step is created:** `IntentPlanner` private methods (18 `Step(...)` calls, lines 45–176). Also in skill `make_steps()` but skills are NOT called by planner.
5. **Routing basis:** `IntentName` enum + `if/elif` in `IntentPlanner`. No skill class reference.
6. **Skills called by planner:** **No.**
7. **Planner depends on concrete skill class:** **No imports.**
8. **Planner depends on concrete tool names:** Yes — `ToolName.CALCULATE`, `ToolName.WRITE_NOTE`, etc. embedded in `IntentPlanner` private methods.
9. **Planner checks tool availability:** `validate_plan()` does, after `make_plan()` returns. Planner itself does not.
10. **Clarification/pending state:** Yes — `IntentPlanner._clarification_plan()` creates a single `FINISH` step with the clarification message. Returns immediately (no pending state in `AgentState`).
11. **Planner success criteria:** None — planner returns a plan; runtime determines success.
12. **Can accept immutable SkillRegistry without runtime redesign:** **Yes** — `RuntimeAgent.__init__` accepts `planner: Any`. Planner could be replaced or extended to accept a `SkillRegistry` dependency without changing `RuntimeAgent`.

---

## 5. Step và plan contract

### 5.1 Step definition — VERIFIED_DIRECTLY

`agent_core/state/agent_state.py:19-38`:

```python
@dataclass
class Step:
    thought: str                              # required, no default
    action: ToolName                          # required, ToolName enum
    args: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    status: StepStatus = StepStatus.PENDING
    risk_level: RiskLevel = RiskLevel.LOW
    depends_on: list[str] = field(default_factory=list)
    created_at: datetime = field(...)
    metadata: dict[str, Any] = field(default_factory=dict)
```

| Field | Type | Default | Consumer | Mutable |
|---|---|---|---|---|
| `thought` | `str` | required | runtime history log | Yes (dataclass not frozen) |
| `action` | `ToolName` | required | plan_validator, executor | Yes |
| `args` | `dict[str, Any]` | `{}` | ArgResolver, executor schema | Yes |
| `id` | `str` | uuid4() | plan_validator (dup check) | Yes |
| `status` | `StepStatus` | PENDING | executor (sets RUNNING/COMPLETED/FAILED) | Yes |
| `risk_level` | `RiskLevel` | LOW | — (not currently used by executor) | Yes |
| `depends_on` | `list[str]` | `[]` | plan_validator (validates step IDs) | Yes |
| `created_at` | `datetime` | utcnow() | — | Yes |
| `metadata` | `dict[str, Any]` | `{}` | — | Yes |

### 5.2 Answers to Step/plan questions

**VERIFIED_DIRECTLY:**

1. `Step.action` uses `ToolName` enum — **not string**.
2. Args contain primitives and placeholder strings (e.g. `"$last_text"`, `"${slot.calc_result}"`).
3. **Step ID** exists (uuid4). **Status** exists. `depends_on` exists (list of step IDs). **No DAG execution** — runtime iterates linearly (`runtime_agent.py:151`).
4. `PlanValidator` checks: non-empty plan; each is `Step`; no duplicate `id`; `action ∈ tool_registry`; `required_args` present; no unknown args (`plan_validator.py:14-55`).
5. **Max steps:** `AgentState.max_steps = 5` (default). Enforced in `_execute_plan`.
6. **Unknown tool rejected:** Yes — `plan_validator.py:28-33`.
7. **Required/allowed args validated:** Yes — `plan_validator.py:43-53`.
8. **Skill plan_factory needs ToolRegistry:** Currently no — skills hard-code `ToolName` directly. A `SkillSpec.required_tools` validation would need access to `ToolRegistry.keys()` at construction.
9. **Skill can produce invalid plan:** Yes — `CalculateAndSaveSkill` args include `"$last_text"` placeholder; if `WRITE_NOTE` required `content` but placeholder fails to resolve, this is only caught at execution, not at plan validation (validator checks required keys present, not placeholder validity).
10. **EX2 validation timing:** `required_tools` validation (SkillSpec construction) should be against registry keys at registry construction time. Plan-time args validation stays in `validate_plan()`.

---

## 6. ToolRegistry compatibility

### 6.1 ToolRegistry public API — VERIFIED_DIRECTLY

`agent_core/tools/registry.py`:

```python
class ToolRegistry(Mapping[ToolName, ToolSpec]):
    def from_specs(cls, specs: Iterable[ToolSpec]) -> ToolRegistry  # classmethod
    def __getitem__(name: ToolName) -> ToolSpec
    def __iter__() -> Iterator[ToolName]
    def __len__() -> int
    def get(name, default=None) -> ToolSpec | None
    def require(name: ToolName) -> ToolSpec       # raises UnknownToolError
    def all() -> Mapping[ToolName, ToolSpec]       # MappingProxyType view
    def manifest() -> tuple[ToolManifestEntry, ...]  # planner-safe, no fn
```

### 6.2 manifest() fields — VERIFIED_DIRECTLY

`agent_core/tools/registry.py:17-27`:

```python
@dataclass(frozen=True)
class ToolManifestEntry:
    name: ToolName
    description: str
    required_args: tuple[str, ...]
    allowed_args: tuple[str, ...]
    input_schema: Mapping[str, object]  # MappingProxyType — no callable
    mutates_state: bool
    risk_level: RiskLevel
    side_effects: tuple[str, ...]
    requires_approval: bool
    idempotent: bool
```

### 6.3 Answers to registry questions

**VERIFIED_DIRECTLY:**

1. **ToolRegistry public API:** 8 methods listed above.
2. **manifest() fields:** 10 fields (see above) — no `fn`.
3. **Skill needs callable tool:** No. Skills only reference `ToolName` enum members to populate `Step.action`. `SkillSpec.required_tools` needs only `frozenset[ToolName]`.
4. **Skill can depend on ToolName only:** **Yes** — all 3 current skills import `ToolName` from enums and never import `ToolSpec` or any callable.
5. **Validate `required_tools ⊆ registry.keys()` without exposing `fn`:** **Yes** — `ToolRegistry.keys()` returns `Iterable[ToolName]`. Comparison requires only the enum set, not `ToolSpec.fn`.
6. **Registry insertion order relevant for skills:** No — skill plans are linearly ordered by `make_steps()`, independent of registry order.
7. **Legacy/local memory tools skills depend on:** `WRITE_NOTE`, `READ_NOTE` — these are local-memory built-ins (`tool_write_note`, `tool_read_note` in `builtin_tools.py`). They will always be present in the registry (completeness guard enforced).
8. **Skill needing unregistered tool:** None currently. All 3 skills reference tools that exist in the EX1 registry.
9. **EX1 contract change needed for EX2:** **No.** EX1 `ToolRegistry` already provides everything EX2 needs (`keys()` for `required_tools` validation, `manifest()` for planner-safe descriptions).

---

## 7. Boundary analysis

### 7.1 Behavior ownership table

| Behavior | Skill | Planner | Runtime | ToolExecutor | Other |
|---|---|---|---|---|---|
| parse user message | No | `RuleBasedIntentParser` (via `RuleBasedPlanner`) | No | No | — |
| select workflow | No | `IntentPlanner.make_plan()` if/elif dispatch | No | No | — |
| create Step | `make_steps()` (orphaned) | `IntentPlanner` private methods | No | No | — |
| validate plan | No | No | `validate_plan()` called in `_plan()` | No | — |
| call tool function | No | No | `_execute_plan()` delegates | `execute()` L120 | — |
| update AgentState | No | No | Yes (status, plan, slots, etc.) | Partial (`last_result`, observations) | — |
| ask clarification | No | `IntentPlanner._clarification_plan()` | No | No | — |
| determine completion | No | No | `_finalize_run()`, `state.complete()` | No | — |

### 7.2 Boundary violations

**VERIFIED_DIRECTLY — NO violations found:**

- No skill calls `tool.fn` directly.
- No skill calls `ToolExecutor.execute()`.
- No skill imports `ToolExecutor`, `ToolSpec`, or any callable.
- No planner performs side effects.
- No skill holds `AgentState`.
- No skill writes memory.
- No skill terminates the runtime (no `state.complete()`).
- No skill bypasses `validate_plan()`.

**INFERRED:**
- Skills produce `list[Step]` that goes through `validate_plan()` when connected to the runtime. Since they are currently orphaned, the validation path is never exercised for skill-produced plans.

### 7.3 Boundary gap — VERIFIED_DIRECTLY

**The `Skill` Protocol's method is `make_steps()` but the `Planner` Protocol's method is `make_plan()`.**

These are structurally parallel (both return `list[Step]`) but incompatible:
- `Skill.make_steps() -> list[Step]` — takes no args (uses constructor-injected slots)
- `Planner.make_plan(state: AgentState) -> list[Step]` — takes full state

There is no adapter, bridge, or dispatch mechanism to call `skill.make_steps()` from the planner.

---

## 8. Test state

### 8.1 Test table

| Test | File | Covers | Unit/Integration | Real runtime path? | Assertion strength |
|---|---|---|---|---|---|
| `test_calculate_and_save_skill_composes_tools` | `test_skills.py:7` | `CalculateAndSaveSkill.make_steps()` | Unit | No — skill not in runtime | Checks `[step.action]` list |
| `test_read_and_summarize_skill_composes_tools` | `test_skills.py:13` | `ReadAndSummarizeSkill.make_steps()` | Unit | No | Checks `[step.action]` list |
| `test_web_search_skill_composes_tools` | `test_skills.py:19` | `WebSearchSkill.make_steps()` | Unit | No | Checks `[step.action]` list |
| `test_parse_calculate` | `test_planning_p0.py:10` | `RuleBasedIntentParser.parse()` | Unit | Partial | Checks intent + expression |
| `test_parse_calculate_then_save_note` | `test_planning_p0.py:17` | `RuleBasedIntentParser.parse()` | Unit | Partial | Checks intent + slots |
| `test_parse_read_note_then_summarize` | `test_planning_p0.py:27` | `RuleBasedIntentParser.parse()` | Unit | Partial | Checks intent + note_name |
| `test_parse_web_search` | `test_planning_p0.py:34` | `RuleBasedIntentParser.parse()` | Unit | Partial | Checks intent + query |
| `test_missing_expression_returns_clarification_plan` | `test_planning_p0.py:41` | `RuleBasedPlanner.make_plan()` | Integration (parser→validator→planner) | Yes | Checks plan action + message |
| `test_missing_note_name_returns_clarification_plan` | `test_planning_p0.py:49` | `RuleBasedPlanner.make_plan()` | Integration | Yes | Checks plan action |
| `test_calculate_then_save_note_plan` | `test_planning_p0.py:59` | Full `RuleBasedPlanner` flow | Integration | Yes | Checks full plan actions + args |
| `test_unknown_returns_safe_finish` | `test_planning_p0.py:74` | `RuleBasedPlanner` unknown routing | Integration | Yes | Checks plan fallback |
| `test_planner_keeps_negated_save_as_calculate_only` | `test_planner.py:4` | Negation logic in parser | Integration | Yes | Checks plan actions |
| `test_planner_search_goal` | `test_planner.py:10` | Web search intent | Integration | Yes | Checks action + args |
| `test_missing_expression_returns_clarification_plan` | `test_planner.py:17` | Clarification plan | Integration | Yes | Checks plan length + message |

### 8.2 Answers to test questions

**VERIFIED_DIRECTLY:**

1. **Old registry tests:** None — no old `ToolRegistry` (dataclass) test exists.
2. **Duplicate skill test:** None.
3. **Skill returning invalid Step test:** None.
4. **Required tool missing test:** None.
5. **Skill selected via planner test:** None — no test exercises runtime → planner → skill path.
6. **Skill orphaned test:** None explicitly; 3 direct unit tests confirm output but not runtime integration.
7. **Skill calls tool directly test:** None — and skills don't do this.
8. **State leakage between skill calls test:** None.
9. **Deterministic plan output test:** Yes — `test_calculate_then_save_note_plan` checks exact `[step.action, ...]` sequence.
10. **Test exercises planner with hard-coded class dependency:** Yes — all planner tests instantiate `RuleBasedPlanner()` directly.

---

## 8b. IntentPlanner branch → Skill mapping (18 Step() calls)

**VERIFIED_DIRECTLY** from `agent_core/planning/intent_planner.py` (all 9 branches, 18 `Step(...)` constructor calls) vs 3 skill `make_steps()` outputs.

| # | IntentPlanner branch | Step() calls | Skill match | Match type | Step diff |
|---|---|---|---|---|---|
| 0 | `_clarification_plan` | 1 (FINISH) | None | **No skill** | Unique behavior — ask user |
| 1 | `_calculate_plan` | 2 (CALCULATE, FINISH) | None | **No skill** | Skill is 3-step (adds WRITE_NOTE) |
| 2 | `_calculate_then_save_note_plan` | 3 (CALCULATE, WRITE_NOTE, FINISH) | `CalculateAndSaveSkill` | **FULL DUPLICATE** | Bit-for-bit identical (see note A) |
| 3 | `_read_note_plan` | 2 (READ_NOTE, FINISH) | None | **No skill** | No 2-step read skill exists |
| 4 | `_read_note_then_summarize_plan` | 3 (READ_NOTE, SUMMARIZE, FINISH) | `ReadAndSummarizeSkill` | **FULL DUPLICATE** | Bit-for-bit identical (see note B) |
| 5 | `_write_note_plan` | 2 (WRITE_NOTE, FINISH) | None | **No skill** | No write-only skill exists |
| 6 | `_web_search_plan` | 2 (WEB_SEARCH, FINISH) | `WebSearchSkill` | **PARTIAL DUPLICATE** | Planner hard-codes `max_results=3`; skill uses `self.max_results` (default 3) |
| 7 | `_project_context_query_plan` | 2 (ANSWER_FROM_CONTEXT, FINISH) | None | **No skill** | ANSWER_FROM_CONTEXT not in any skill |
| 8 | `_unknown_plan` | 1 (FINISH) | None | **No skill** | Safe fallback |
| — | `WEB_SEARCH_THEN_SAVE_NOTE` handler | **0 (missing)** | None | **GAP** | In `IntentName` + `SlotValidator`; no branch in planner, no skill |

**Note A — `_calculate_then_save_note_plan` vs `CalculateAndSaveSkill.make_steps()`:**

```python
# IntentPlanner (lines 66-88)
Step("Cần tính toán biểu thức trước", ToolName.CALCULATE, {"expression": parsed.expression}),
Step("Lưu kết quả vào ghi chú",       ToolName.WRITE_NOTE, {"name": parsed.note_name, "content": "$last_text"}),
Step("Thông báo hoàn tất cho user",    ToolName.FINISH,     {"answer": f"Đã tính xong...'{parsed.note_name}'. Kết quả: ${{slot.calc_result}}"}),

# CalculateAndSaveSkill.make_steps() (lines 15-18)
Step("Cần tính toán biểu thức trước", ToolName.CALCULATE, {"expression": self.expression}),
Step("Lưu kết quả vào ghi chú",       ToolName.WRITE_NOTE, {"name": self.note_name, "content": "$last_text"}),
Step("Thông báo hoàn tất cho user",    ToolName.FINISH,     {"answer": f"Đã tính xong và lưu vào ghi chú '{self.note_name}'. Kết quả: ${{slot.calc_result}}"}),
```

`thought` strings identical. `args` values sourced from `parsed.*` vs `self.*` — functionally equivalent. FINISH message differs in `"Đã tính xong..."` vs full phrase, but both carry `self.note_name`. **Semantic match: YES.**

**Note B — `_read_note_then_summarize_plan` vs `ReadAndSummarizeSkill.make_steps()`:**

```python
# IntentPlanner (lines 104-121)
Step("Đọc nội dung ghi chú",    ToolName.READ_NOTE,  {"name": parsed.note_name}),
Step("Tóm tắt nội dung ghi chú", ToolName.SUMMARIZE, {"text": "$last.output.content"}),
Step("Trả summary cho user",      ToolName.FINISH,    {"answer": "Tóm tắt: ${last.output.summary}"}),

# ReadAndSummarizeSkill.make_steps() (lines 14-17)
Step("Đọc nội dung ghi chú",     ToolName.READ_NOTE,  {"name": self.note_name}),
Step("Tóm tắt nội dung ghi chú", ToolName.SUMMARIZE,  {"text": "$last.output.content"}),
Step("Trả summary cho user",      ToolName.FINISH,     {"answer": "Tóm tắt: ${last.output.summary}"}),
```

**Bit-for-bit identical** except slot source. Semantic match: YES.

**Summary:**
- 3 of 9 branches have a skill duplicate: `_calculate_then_save_note_plan`, `_read_note_then_summarize_plan`, `_web_search_plan`
- 5 of 9 branches have no skill equivalent: clarification, calculate-only, read-only, write-only, project-context, unknown
- 1 intent (`WEB_SEARCH_THEN_SAVE_NOTE`) has no branch in planner **and** no skill — double gap

---

## 8c. Stateless skill confirmation

**VERIFIED_DIRECTLY** from `agent_core/skills/*.py` source:

### Criterion checklist (all 3 skills)

| Criterion | `CalculateAndSaveSkill` | `ReadAndSummarizeSkill` | `WebSearchSkill` |
|---|---|---|---|
| Class-level mutable variable | None | None | None |
| Instance mutation in `make_steps()` | No — only reads `self.*` | No — only reads `self.*` | No — only reads `self.*` |
| Shared mutable reference across calls | No — `[...]` creates fresh list | No | No |
| External service call | No | No | No |
| Import of executor / client / store | No | No | No |
| Return type | `list[Step]` ✓ | `list[Step]` ✓ | `list[Step]` ✓ |
| Return value is pure | Yes | Yes | Yes |
| Second call produces identical output | Yes (same `self.*`) | Yes | Yes |

**CONFIRMED: All 3 skills are stateless and return only `list[Step]`.**

Imports in each skill file:

```python
# all three files import only:
from dataclasses import dataclass
from agent_core.state.agent_state import Step
from agent_core.state.enums import ToolName
```

No skill imports `ToolExecutor`, `ArgResolver`, `RuntimeAgent`, `AgentState`,
any memory class, or any HTTP client.

---

## 8d. Exact composition seam — inject SkillRegistry without touching RuntimeAgent

**VERIFIED_DIRECTLY** from `runtime_agent.py` and `rule_based_planner.py` source.

### Seam chain

```
RuntimeAgent.__init__(planner: Any, ...)     ← duck-typed, no type enforcement
  └─ RuleBasedPlanner.__init__(
         parser: RuleBasedIntentParser | None,
         slot_validator: SlotValidator | None,
         intent_planner: IntentPlanner | None   ← SEAM POINT
     )
       └─ IntentPlanner — 9 if/elif branches (hard-coded Step creation)
```

`RuntimeAgent` accepts `planner: Any` — completely duck-typed. Anything with
`make_plan(state: AgentState) -> list[Step]` works.

`RuleBasedPlanner` accepts `intent_planner: IntentPlanner | None = None` —
injectable at construction, no default forced if caller provides one.

### Injection without modifying either class

**Option A — inject at `intent_planner` level (RECOMMENDED for EX2):**

```python
skill_registry = build_skill_registry(tool_registry)           # new EX2 registry
skill_planner = SkillAwareIntentPlanner(skill_registry)        # new EX2 class
                                                               #   accepts ParsedIntent
                                                               #   dispatches to skill.plan_factory(slots)
                                                               #   falls back to IntentPlanner methods

planner = RuleBasedPlanner(intent_planner=skill_planner)       # existing class, no change

agent = RuntimeAgent(
    planner=planner,                                           # existing class, no change
    tools=tool_registry,
    memory_client=memory_client,
)
```

`SkillAwareIntentPlanner` signature:

```python
class SkillAwareIntentPlanner:
    def __init__(self, skill_registry: SkillRegistry,
                 fallback: IntentPlanner | None = None):
        self.skill_registry = skill_registry
        self.fallback = fallback or IntentPlanner()

    def make_plan(self, parsed: ParsedIntent) -> list[Step]:
        # 1. check missing_slots → fallback._clarification_plan()
        # 2. find skill by parsed.intent in applicability
        # 3. if found → skill_spec.plan_factory(slots_from_parsed)
        # 4. else → self.fallback.make_plan(parsed)
```

**Why this seam?**
- `RuntimeAgent.__init__` never changes — satisfies CLAUDE.md constraint
- `RuleBasedPlanner.__init__` never changes — its `intent_planner` kwarg already exists (line 14)
- `SkillAwareIntentPlanner` replaces only the Step-generation step, after parser+SlotValidator already ran
- Backward compatible: `plan_factory` receives `slots: dict[str, Any]` extracted from `ParsedIntent` — same data that hard-coded methods used

**Option B — inject at `planner` level (valid alternative):**

```python
skill_registry = build_skill_registry(tool_registry)
planner = SkillBasedPlanner(skill_registry)   # entirely new planner, not wrapping RuleBasedPlanner

agent = RuntimeAgent(planner=planner, tools=tool_registry, ...)
```

Simpler but requires rewriting parser+SlotValidator integration from scratch.
Option A is lower risk for EX2 — reuses all existing parser/validator logic.

**Files that change in Option A:**

| File | Change | RuntimeAgent touched? |
|---|---|---|
| `agent_core/skills/skill_spec.py` (new) | `SkillSpec`, `SkillName`, `SkillManifestEntry` | No |
| `agent_core/skills/registry.py` (new) | `SkillRegistry` | No |
| `agent_core/skills/providers.py` (new) | `builtin_skill_specs`, `build_skill_registry` | No |
| `agent_core/planning/skill_intent_planner.py` (new) | `SkillAwareIntentPlanner` | No |
| `agent_core/runtime/runtime_agent.py` | **NOT TOUCHED** | — |
| `agent_core/planning/rule_based_planner.py` | **NOT TOUCHED** | — |
| Composition factories (`build_local_agent`, etc.) | `intent_planner=` kwarg added at call site | No |

**CONFIRMED: `RuntimeAgent` requires zero changes to support `SkillRegistry` injection.**

---

## 9. Gaps với EX2 target

| Proposed EX2 concern | Current code fact | Match/Mismatch | Impact | Decision needed |
|---|---|---|---|---|
| `SkillSpec` | Does not exist | **MISMATCH** | Must be created | Yes |
| `SkillRegistry` | Does not exist | **MISMATCH** | Must be created | Yes |
| Duplicate skill semantics | No registry → no duplicate protection | **MISMATCH** | `DuplicateSkillError` needed | Yes |
| Registry mutability | No registry | **MISMATCH** | Immutable Mapping needed | Yes — same pattern as EX1 |
| Skill manifest | No manifest | **MISMATCH** | `SkillManifestEntry` needed | Yes |
| `required_tools` declaration | Not declared on skills | **MISMATCH** | Must add to `SkillSpec` | Yes |
| Applicability predicate | None on skills | **MISMATCH** | Intent list or predicate? | Decision needed |
| Input requirements / slot declaration | Implicit in constructor | **MISMATCH** | Must formalize | Decision needed |
| Success criteria | None | **MISMATCH** | Scope decision needed | Yes |
| Clarification requirements | None | **MISMATCH** | Scope decision needed | Yes |
| Plan factory signature | `make_steps()` (no args) | **PARTIAL** | Must decide input type | Yes |
| Planner routing | `if/elif` per `IntentName` | **MISMATCH** | Must adapt for skill dispatch | Yes |
| Runtime integration | Skills completely orphaned | **MISMATCH** | Must wire to planner | Yes |
| Direct tool-call bypass | No violation — clean | MATCH | — | — |
| Mutable skill state | No mutable state — clean | MATCH | — | — |
| Static provider composition | No provider pattern | **MISMATCH** | Same pattern as EX1 needed | Yes |

---

## 10. Evidence-backed risks

### R1 — Hard-coded planner creates shadow parallel to skills

**Evidence:** `IntentPlanner` has 18 `Step(...)` calls duplicating logic equivalent to `CalculateAndSaveSkill`, `ReadAndSummarizeSkill`, and `WebSearchSkill`. Both exist but only `IntentPlanner` is production-active.

**Impact:** Any change to a workflow (e.g., add a step to calculate flow) must be made in TWO places if skills are not wired. After EX2, old `IntentPlanner` private methods must be deprecated or removed to avoid drift.

**Severity:** HIGH — likely source of silent divergence bugs if EX2 migration is incomplete.

**Mitigation:** In EX2, migrate the 3 existing skill workflows and remove the corresponding `IntentPlanner` private methods.

### R2 — Skills are orphaned — 0 runtime call sites

**Evidence:** `git grep -n -iE "skill" -- '*.py'` finds zero imports of skill classes outside `skills/` and `tests/test_skills.py`. All 3 tests are direct unit tests bypassing runtime.

**Impact:** Skills claim to implement the `Skill` Protocol but are never selected or executed. Tests pass but provide false confidence about runtime behavior.

**Severity:** HIGH — 3 tests pass but 0 production behavior is verified.

**Mitigation:** EX2 must wire skills to the planner. Skills must run through `validate_plan()` and `ToolExecutor` in at least one integration test.

### R3 — Skill input contract is implicit (Python TypeError)

**Evidence:** `CalculateAndSaveSkill(expression: str, note_name: str)` — missing arg → `TypeError`. No declared required slots, no `InvalidSkillArgs` error, no slot validator.

**Impact:** Skill callers (future planners) have no declarative contract to validate before construction. Plan may fail at runtime rather than at planning time.

**Severity:** MEDIUM — acceptable for MVP if `SkillSpec` adds explicit required slot declarations.

**Mitigation:** `SkillSpec` should declare `required_inputs: frozenset[str]`.

### R4 — `args` placeholders in skill Step output are unvalidated at plan-build time

**Evidence:** `CalculateAndSaveSkill._make_steps()` embeds `"$last_text"` and `"${slot.calc_result}"` as raw strings. `validate_plan()` checks required keys present — it does NOT validate placeholder syntax or resolution feasibility.

**Impact:** A skill-produced plan with a broken placeholder string passes `validate_plan()` and fails only at execution time (ArgResolver raises).

**Severity:** LOW for MVP (same limitation exists in `IntentPlanner` today).

**Mitigation:** Defer; add placeholder linting as a post-EX2 improvement.

### R5 — `HybridPlanner` is orphaned — no production use

**Evidence:** `hybrid_planner.py` exists (38 lines) but zero production imports. `LLMIntentParser.py` is a 1-line empty file.

**Impact:** Future confusion about which planner is active. Risk of unreviewed activation.

**Severity:** LOW — orphaned, not harmful. Should be documented in EX2 scope boundary.

**Mitigation:** Explicitly mark as deferred in EX2 spec.

### R6 — No `SkillName` enum or identity contract

**Evidence:** No `SkillName` class or value anywhere. Skills are identified only by Python class type.

**Impact:** A `SkillRegistry` without typed names has no deterministic key; duplicate detection is type-based (fragile). Planner routing would need to identify skills by some key.

**Severity:** HIGH — must resolve before registry construction.

**Mitigation:** Decision D1 below.

### R7 — No duplicate skill detection possible without registry

**Evidence:** `SkillRegistry` does not exist. Two instances of the same class can be added to any future registry without any guard.

**Severity:** MEDIUM — will be solved by `from_specs()` + `DuplicateSkillError` pattern.

### R8 — EX2 scope risk: accidental plugin framework

**Evidence:** None yet — no plugin code exists. Risk is architectural.

**Impact:** If `SkillRegistry` accepts arbitrary callables or dynamic imports, it becomes a plugin system.

**Severity:** MEDIUM — mitigated by static provider pattern (same as EX1).

---

## 11. Contract decisions cần TranBac duyệt

### D1 — Skill identity

**Options:**
- A. `SkillName` enum (same pattern as `ToolName`) — deterministic, closed set, type-safe, registry keys are enum members.
- B. String ID — flexible, but no uniqueness guarantee without additional enforcement.
- C. Class type — ambiguous if same class registered twice with different args.

**Recommendation:** A (`SkillName` enum). Consistent with `ToolName` EX1 pattern. Enables `SkillSpec.required_tools: frozenset[ToolName]` to be validated against `ToolRegistry.keys()` with the same enum.

**Trade-off:** Closed enum means adding a skill requires a new enum member. Acceptable for MVP static skills (same position as EX1 D1).

### D2 — `SkillSpec` exact fields

**Proposed minimal:**

```python
@dataclass(frozen=True)
class SkillSpec:
    name: SkillName
    description: str
    required_tools: frozenset[ToolName]
    plan_factory: SkillPlanFactory   # callable: (slots: dict) -> list[Step]
```

**Additional fields under consideration:**
- `required_inputs: frozenset[str]` — slot names required before instantiation
- `applicability: frozenset[IntentName]` — intents this skill handles
- `success_criteria` — post-MVP
- `clarification_requirements` — post-MVP

**Decision needed:** Minimum viable field set for EX2.

### D3 — Skill callable signature

**Current:** `make_steps(self)` — uses constructor-injected fields, no args.

**Options:**
- A. `plan_factory(slots: dict[str, Any]) -> list[Step]` — skill receives extracted slots at call time, no constructor state.
- B. `plan_factory() -> list[Step]` — skill constructed with slots, called with no args (current pattern).
- C. `plan_factory(intent: ParsedIntent) -> list[Step]` — skill receives full parsed intent.

**Recommendation:** A — stateless factory receiving resolved slots. Enables safe skill reuse across turns without re-construction. Closest to EX2 invariant "skills stateless."

**Trade-off:** Requires migrating current skill constructors. 3 skills to migrate (small lift).

### D4 — Return type: `list[Step]` vs `SkillPlan`

**Options:**
- A. `list[Step]` — minimal, compatible with current `Planner.make_plan()` contract.
- B. `SkillPlan` dataclass wrapping `list[Step]` + metadata — richer but more implementation.

**Recommendation:** A for EX2. B deferred to Goal Understanding phase.

**Trade-off:** `list[Step]` cannot carry skill-level metadata (success criteria, clarification state) without a wrapper. Accept limitation for MVP.

### D5 — `SkillPlan` wrapper content

**Decision:** Defer entirely if D4 chooses `list[Step]`. If `SkillPlan` needed: `steps: list[Step]` + `metadata: dict` minimum.

### D6 — `SkillRegistry` mutability

**Recommendation:** Immutable after construction — same pattern as `ToolRegistry`. `from_specs()` classmethod + `MappingProxyType` backing.

**Trade-off:** Consistent with EX1. No dynamic registration.

### D7 — Duplicate behavior

**Recommendation:** `DuplicateSkillError(SkillRegistryError)` raised in `from_specs()` — same pattern as `DuplicateToolError`.

### D8 — `required_tools` validation timing

**Options:**
- A. At `SkillRegistry.from_specs()` — validates against injected `ToolRegistry` at construction.
- B. At skill selection (runtime) — lazy validation.
- C. At `SkillSpec` construction — validates against a passed-in registry.

**Recommendation:** A — same gate pattern as `ToolSpec.__post_init__` validates schema. `SkillRegistry` receives a `ToolRegistry` at construction; validates each `SkillSpec.required_tools ⊆ registry.keys()`.

**Trade-off:** `SkillRegistry` has a dependency on `ToolRegistry`. Acceptable — tools must be stable before skills.

### D9 — Skill applicability

**Options:**
- A. `applicability: frozenset[IntentName]` — declarative, planner consults intent→skill map.
- B. Predicate function: `can_handle(intent: ParsedIntent) -> bool` — flexible but breaks manifest-safe constraint (callables in manifest).
- C. Metadata only: planner uses registry manifest to dispatch by name — manual mapping.

**Recommendation:** A (`frozenset[IntentName]`) for EX2. Enables planner to dispatch without calling skill. Consistent with "manifest never exposes callables."

**Trade-off:** Closed `IntentName` enum → new user-facing workflows need new intent names.

### D10 — Required input/slot declaration

**Recommendation:** `required_inputs: frozenset[str]` on `SkillSpec`. Planner validates slots present before constructing/calling skill factory.

### D11 — Skill success criteria ownership

**Recommendation:** Defer to post-EX2. Currently `_finalize_run()` owns success. Skills should not determine task completion in EX2.

### D12 — Clarification ownership

**Current state:** `IntentPlanner._clarification_plan()` owns clarification — returns FINISH step with clarification message.

**Options:**
- A. Keep in planner — planner checks `ParsedIntent.missing_slots`, dispatches clarification before skill.
- B. Move to skill — skill declares `required_inputs`, planner delegates clarification to runtime.

**Recommendation:** A for EX2. Keep clarification in planner (existing behavior). Skill-level clarification is post-EX2.

### D13 — Skill provider composition

**Recommendation:** Static provider pattern: `builtin_skill_specs(dependencies) -> tuple[SkillSpec, ...]`. Same pattern as `builtin_tool_specs()`.

### D14 — Planner integration — minimal

**Recommendation:** `RuleBasedPlanner` receives `SkillRegistry` as optional dependency. Planner checks `intent → skill` mapping via `applicability` before falling back to `IntentPlanner` hard-coded methods. Progressive migration.

### D15 — Migrate 3 existing skills in EX2?

**Options:**
- A. Yes — wire all 3 to registry and planner; deprecate equivalent `IntentPlanner` private methods.
- B. No — create registry infrastructure only; migration is EX3.

**Recommendation:** A — 3 skills are small and already implemented. Migration proves the registry works end-to-end. Risk of R1 (shadow divergence) grows if deferred.

### D16 — Skills stateless?

**Recommendation:** Yes — `make_steps` or `plan_factory` must be stateless. No instance state between calls. Current skills already satisfy this.

### D17 — Planner-safe skill manifest?

**Recommendation:** Yes — `SkillManifestEntry` (frozen dataclass, no callable). Mirror of `ToolManifestEntry`. Contains `name`, `description`, `required_tools`, `applicability`, `required_inputs`.

### D18 — `SkillRegistry` receives `ToolRegistry` at construct?

**Recommendation:** Yes (see D8). `SkillRegistry.from_specs(specs, tool_registry: ToolRegistry)` validates `required_tools` at build time.

### D19 — Exact file scope

See §13.

### D20 — Defer to later phases

**Defer to Goal Understanding / Guarded Planner:**
- LLM-based applicability / intent classification
- `HybridPlanner` activation
- Skill ranking / confidence scoring
- Multi-skill plan composition

**Defer to Replanning:**
- Skill failure → skill fallback selection

**Defer to Core Skill Bundle:**
- `WEB_SEARCH_THEN_SAVE_NOTE` skill (not yet implemented, only in `IntentPlanner`)

---

## 12. Proposed minimal EX2 shape

### 12.1 Feasibility assessment

**Proposed minimal:**

```python
@dataclass(frozen=True)
class SkillSpec:
    name: SkillName
    description: str
    required_tools: frozenset[ToolName]
    plan_factory: SkillPlanFactory  # (slots: dict[str, Any]) -> list[Step]
```

```python
class SkillRegistry(Mapping[SkillName, SkillSpec]):
    @classmethod
    def from_specs(cls, specs, tool_registry: ToolRegistry) -> SkillRegistry: ...
    def require(name: SkillName) -> SkillSpec: ...
    def manifest() -> tuple[SkillManifestEntry, ...]: ...
```

**INFERRED — Assessment:**

| Question | Answer |
|---|---|
| Sufficient to migrate 3 existing skills? | Yes — with D3 (slot-based factory) |
| Needs input schema? | Recommended (D10: `required_inputs`) — but not strictly blocking |
| Needs applicability? | Yes (D9) — required for planner dispatch |
| Needs clarification contract? | No for EX2 — keep in planner |
| Needs success criteria? | No for EX2 — keep in runtime |
| Needs richer `SkillPlan`? | No for EX2 — `list[Step]` sufficient |

### 12.2 Recommended additions to minimal shape

```python
@dataclass(frozen=True)
class SkillSpec:
    name: SkillName
    description: str
    required_tools: frozenset[ToolName]
    applicability: frozenset[IntentName]      # for planner dispatch
    required_inputs: frozenset[str]           # declared slot requirements
    plan_factory: SkillPlanFactory            # (slots: dict) -> list[Step]
```

```python
SkillPlanFactory = Callable[[dict[str, Any]], list[Step]]
```

`plan_factory` is a callable — **not exposed in manifest**. `SkillManifestEntry` has all fields except `plan_factory`.

---

## 13. Exact proposed implementation scope

### 13.1 New files (required)

| File | Class/function | Why | Trade-off |
|---|---|---|---|
| `agent_core/skills/errors.py` | `SkillRegistryError`, `DuplicateSkillError`, `UnknownSkillError`, `InvalidSkillSpecError`, `MissingRequiredToolError` | Same pattern as EX1 `errors.py` | Adds 5 exception classes |
| `agent_core/skills/skill_spec.py` | `SkillName(StrEnum)`, `SkillSpec`, `SkillManifestEntry`, `SkillPlanFactory` | Core contract | `SkillName` in enums.py or separate |
| `agent_core/skills/registry.py` | `SkillRegistry(Mapping[SkillName, SkillSpec])`, `from_specs()`, `require()`, `manifest()`, `all()` | Immutable catalog | Dependency on `ToolRegistry` at construction |
| `agent_core/skills/providers.py` | `BuiltinSkillDependencies`, `builtin_skill_specs()`, `build_skill_registry()` | Static provider | Mirrors `registry.py` provider pattern |
| `tests/test_skill_registry.py` | ~35-45 tests | Contract verification | |

### 13.2 Modified files (required)

| File | Change | Why |
|---|---|---|
| `agent_core/skills/base.py` | Remove orphaned `Skill` Protocol OR keep for backward compat + add `SkillPlanFactory` type alias | Protocol is currently unused by registry |
| `agent_core/skills/calculate_and_save_skill.py` | Refactor to `plan_factory` signature (accepts slots dict) | D3 migration |
| `agent_core/skills/read_and_summarize_skill.py` | Refactor to `plan_factory` signature | D3 migration |
| `agent_core/skills/web_search_skill.py` | Refactor to `plan_factory` signature | D3 migration |
| `agent_core/state/enums.py` | Add `SkillName(StrEnum)` | Unless separate file chosen |
| `tests/test_skills.py` | Update to use `plan_factory(slots)` signature | D3 migration; OLD tests must still pass |

### 13.3 Conditional files (verify before touching)

| File | Condition | Change |
|---|---|---|
| `agent_core/planning/rule_based_planner.py` | If D14 accepted — planner wiring | Accept `SkillRegistry` optional dep; dispatch by `applicability` |
| `agent_core/planning/intent_planner.py` | If D15 accepted — skill migration | Deprecate 3 private methods after skills wired |
| `agent_core/planning/intents.py` | If new intents needed | No new intents expected for 3 existing skills |
| `agent_core/__init__.py` | Exports only | Add `SkillRegistry`, `build_skill_registry` to public API |
| `tests/test_planner.py` | Integration tests for planner+skill | Add skill-via-planner tests |

### 13.4 Forbidden files (must not change in EX2)

```
agent_core/state/agent_state.py
agent_core/runtime/session_runtime.py
agent_core/session_persistence/**
agent_core/memory/**
agent_core/safety/**
agent_core/tools/executor.py      (unless proven by STOP condition check)
agent_core/tools/base.py          (ToolSpec contract is stable)
agent_core/tools/registry.py      (EX1 complete)
```

---

## 14. Unknowns

| Unknown | Source | Blocking? |
|---|---|---|
| `SkillName` enum placement — `enums.py` vs `skill_spec.py` | CLAUDE.md §2: "Enum nguồn duy nhất: enums.py" | Yes — must confirm before implementation |
| `plan_factory` type alias placement | Design decision | No — can start with inline `Callable` |
| Whether `WEB_SEARCH_THEN_SAVE_NOTE` gets a skill in EX2 | No current skill exists; `IntentPlanner._web_search_plan` only covers single-step web search | No — defer; D15 says migrate 3 existing |
| `HybridPlanner` — keep or deprecate? | Orphaned; no tests call it via runtime | No — document as deferred in spec |
| Session runtime compatibility with skill registry | `session_runtime.py` calls `runtime_agent.py`; `RuntimeAgent` accepts `Mapping[ToolName, ToolSpec]` + `planner: Any` — skill registry doesn't change these | No |
| M6 remote memory compatibility | M6 added `build_agent_with_memory_backend()` which calls `build_tool_registry(disabled_tools=...)` — skill registry is independent | No |

---

## Attestation

```
Production code changed:     NO
Tests changed:               NO
Existing specs changed:      NO
Only EX2 inventory report created: YES
```

```bash
$ git status --short
REPORT_EX2_STATIC_SKILL_REGISTRY_INVENTORY_VERIFIED.md   (untracked)
```

**DỪNG — chờ architect gate.**

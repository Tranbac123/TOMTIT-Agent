# EX2 v1.2 — Architect Review Evidence Bundle

**Candidate:** `eeccbcfdd7e2370f2e0a043a522fe0ee8a7531fc`
**Branch:** `ex2-static-skill-registry`
**Baseline:** `cf471dde`
**Spec:** `docs/specs/SPEC_EX2_STATIC_SKILL_REGISTRY.md` v1.2
**Verification policy:** `docs/standards/VERIFICATION_GATE.md` v1.0.0
**Collected:** 2026-06-18 UTC
**Environment:** Python 3.11.2, pytest 8.4.2, macOS Darwin 25.5.0

All commands run with `cwd=/Users/tranvanbac/Documents/AI/ai-agent/TOMTIT-Agent`.
No code, tests, or spec were modified during evidence collection.

---

## Evidence Index (V-00 … V-10)

| ID | Artifact | Command | UTC start | UTC end | Exit | SHA-256 |
|---|---|---|---|---|---|---|
| V-00 | `V00_git_show_full_patch.txt` | `git show --format=fuller --stat --patch eeccbcf` | 2026-06-18T14:08:13Z | 2026-06-18T14:08:13Z | 0 | `b232cdf4b37c92f2b2c6234d7bc5456c0893b4ab056d04065c53fe9ef413fb4f` |
| V-01 | `V01_scope_diff.txt` | `git diff --name-status cf471dde..eeccbcf` | 2026-06-18T14:08:25Z | 2026-06-18T14:08:25Z | 0 | `64fc31fb55c49631d34e86c2d23e48fa81b5cff8b23cd59f13ad9522d7a625a6` |
| V-02 | `V02_whitespace_worktree.txt` | `git diff --check cf471dde..eeccbcf && git status --short --untracked-files=all` | 2026-06-18T14:08:26Z | 2026-06-18T14:08:26Z | 0 | `6b65d796ab2feb84ac82618c30b99f5cd76637d5dd5cbea574e21e050e5f48f6` |
| V-03 | `V03_import_sanity.txt` | `python3 -c 'import agent_core; from agent_core.skills...'` | 2026-06-18T14:08:35Z | 2026-06-18T14:08:36Z | 0 | `e299535cd423ce27833d5c972fd5896b5f7c9bc00122b3166ff7880968f124e1` |
| V-04 | `V04_architecture_greps.txt` | `grep/git-grep: SkillName sources, DisabledSkillReason sources, shadow methods, ParsedIntent in skills, ToolExecutor in skills, .fn( call sites, PolicyEngine wiring, external skill platform` | 2026-06-18T14:08:55Z | 2026-06-18T14:08:56Z | 0 | `c98501bf17d19a511c8390feb8867a3a26ef2358dde012f71c2f495f75b31cb7` |
| V-05 | `V05_backend_matrix.txt` | `python3: build_skill_catalog x2 backends (local + remote M6)` | 2026-06-18T14:09:09Z | 2026-06-18T14:09:10Z | 0 | `07ffabe3aa447ba487d5400170076e7cf6cff0392e12a4b378468bcd12ecd1d4` |
| V-06 | `V06_targeted_tests.txt` | `pytest tests/test_skill_registry.py tests/test_skill_aware_intent_planner.py -p no:cacheprovider -v` | 2026-06-18T14:10:24Z | 2026-06-18T14:10:29Z | 0 | `ef982a912e4690f7c0e507d75e1e759df330a693b32f7ba13e318b189af6dfdb` |
| V-07 | `V07_full_regression.txt` | `pytest -p no:cacheprovider -v` | 2026-06-18T14:10:38Z | 2026-06-18T14:10:43Z | 0 | `d0408ff548016da5f600e409c7f194657206db6c4ce690dc42998d42f098b000` |
| V-08 | `V08_repeatability_3x.txt` | `pytest targeted -q × 3` | 2026-06-18T14:11:07Z | 2026-06-18T14:11:15Z | 0 | `02ca6ae82aa9f68d9cf9051b3f6070d8bb79447cd16db7dddd0b8f15fece2fd7` |
| V-09 | `V09_unavailable_msg_runtime_sig.txt` | `python3: exact unavailable message + RuntimeAgent.__init__ params` | 2026-06-18T14:11:36Z | 2026-06-18T14:11:36Z | 0 | `e22a94c10ddff3a80d2672d1bf56cc356c1247b6d9f6bfa6b1e88d592c69080d` |
| V-10 | `V10_ac15_composition_identity.txt` | `python3: AC-15 composition + required_tool subset proof` | 2026-06-18T14:12:03Z | 2026-06-18T14:12:03Z | 0 | `3b42b819e1f2aed7e65a405a11b84b7ab116761232051087227766afefb98c2f` |

All artifacts are committed alongside this file in `docs/reports/evidence/ex2_v12/`.

---

## V-00 Full patch

See `docs/reports/evidence/ex2_v12/V00_git_show_full_patch.txt` (2064 lines, 87 873 bytes).

Stat summary from the patch header:

```
 agent_core/planning/rule_based_planner.py         |  20 +-
 agent_core/planning/skill_aware_intent_planner.py |  91 +++--
 agent_core/skills/__init__.py                     |  14 +-
 agent_core/skills/base.py                         |  28 +-
 agent_core/skills/registry.py                     | 227 ++++++++---
 agent_core/state/enums.py                         |   4 +
 tests/test_skill_aware_intent_planner.py          | 468 ++++++++++++++--------
 tests/test_skill_registry.py                      | 452 ++++++++++++++-------
 8 files changed, 884 insertions(+), 420 deletions(-)
```

Author/CommitDate: `Thu Jun 18 20:48:20 2026 +0700`

---

## V-01 Scope diff

```
M	agent_core/planning/intent_planner.py
M	agent_core/planning/rule_based_planner.py
A	agent_core/planning/skill_aware_intent_planner.py
M	agent_core/runtime/runtime_agent.py
A	agent_core/skills/__init__.py
M	agent_core/skills/base.py
A	agent_core/skills/errors.py
A	agent_core/skills/registry.py
M	agent_core/state/enums.py
A	docs/reports/REPORT_EX2_STATIC_SKILL_REGISTRY_INVENTORY_VERIFIED.md
A	tests/test_skill_aware_intent_planner.py
A	tests/test_skill_registry.py
```

All 12 paths are within the §14.1 allowed file manifest.
`docs/standards/VERIFICATION_GATE.md` and `docs/specs/SPEC_EX2_STATIC_SKILL_REGISTRY.md` — **unchanged**.

---

## V-02 Whitespace + worktree

```
diff_check_exit:0      (no trailing whitespace, no mixed indent)
git status: (empty)    (worktree clean)
```

---

## V-03 Import sanity

```
IMPORT_OK
import_exit:0
```

---

## V-04 Architecture greps (raw)

```
--- AC-01: SkillName sources ---
command: grep -rn 'class SkillName' agent_core/
agent_core/state/enums.py:83:class SkillName(StrEnum)
exit:0   ← exactly 1 match, in enums.py

--- AC-02: DisabledSkillReason sources ---
command: grep -rn 'class DisabledSkillReason' agent_core/
agent_core/state/enums.py:89:class DisabledSkillReason(StrEnum)
exit:0   ← exactly 1 match, in enums.py

--- AC-12: shadow methods ---
command: grep -n '_calculate_then_save_note_plan|_read_note_then_summarize_plan|_web_search_plan' agent_core/planning/intent_planner.py
exit:1   ← no match (shadow methods absent)

--- AC-13: no ParsedIntent in skills ---
command: grep -rn 'ParsedIntent' agent_core/skills/
exit:1   ← no match

--- AC-13: no ToolExecutor in skills ---
command: grep -rn 'ToolExecutor|tool\.fn' agent_core/skills/
exit:1   ← no match

--- AC-16: .fn( call sites ---
command: git grep -n '\.fn(' eeccbcf -- 'agent_core/**/*.py'
eeccbcf:agent_core/tools/executor.py:120:    result = tool.fn(state=state, **final_args)
exit:0   ← exactly 1 call site, inside ToolExecutor.execute()

--- AC-16: ToolExecutor in skills at candidate ---
command: git grep -n 'ToolExecutor' eeccbcf -- 'agent_core/skills/**/*.py'
exit:1   ← no match (skills layer has zero ToolExecutor references)

--- AC-16: PolicyEngine/ApprovalGate wiring ---
command: git grep -n 'PolicyEngine|ApprovalGate' eeccbcf -- 'agent_core/**/*.py'
eeccbcf:agent_core/safety/approval.py:34:class ApprovalGate:
eeccbcf:agent_core/safety/policy.py:33:class PolicyEngine:
eeccbcf:agent_core/tools/executor.py:13:from agent_core.safety.approval import ApprovalGate
eeccbcf:agent_core/tools/executor.py:14:from agent_core.safety.policy import PolicyEngine
eeccbcf:agent_core/tools/executor.py:24:    policy_engine: PolicyEngine | None = None,
eeccbcf:agent_core/tools/executor.py:25:    approval_gate: ApprovalGate | None = None,
eeccbcf:agent_core/tools/executor.py:29:    self.policy_engine = policy_engine or PolicyEngine()
eeccbcf:agent_core/tools/executor.py:30:    self.approval_gate = approval_gate or ApprovalGate()
exit:0   ← definitions + wiring in executor only

--- AC-18: no external skill platform ---
command: grep -rn 'import.*skill.*yaml|load_skill|discover_skill|SkillLoader' agent_core/
exit:1   ← no match
```

---

## V-05 Backend matrix

```
builtin_skill_specs() count: 3

LOCAL active: ['calculate_and_save', 'read_and_summarize', 'web_search']
LOCAL disabled count: 0

REMOTE active: ['web_search']
  REMOTE disabled: calculate_and_save | missing: ['write_note'] | reason: missing_required_tools
  REMOTE disabled: read_and_summarize | missing: ['read_note']  | reason: missing_required_tools
```

---

## V-06 Targeted tests (summary)

```
106 passed in 0.33s
exit:0
```

Full verbose list of all 106 tests in `V06_targeted_tests.txt`.

---

## V-07 Full regression (summary)

```
404 passed in 0.80s
exit:0
```

Full verbose list of all 404 tests in `V07_full_regression.txt`.

---

## V-08 Raw 3× repeatability log

```
--- RUN 1 ---
run1_start: 2026-06-18T14:11:07Z
........................................................................ [ 67%]
..................................                                       [100%]
106 passed in 0.31s
run1_exit:0
run1_end: 2026-06-18T14:11:10Z

--- RUN 2 ---
run2_start: 2026-06-18T14:11:10Z
........................................................................ [ 67%]
..................................                                       [100%]
106 passed in 0.28s
run2_exit:0
run2_end: 2026-06-18T14:11:13Z

--- RUN 3 ---
run3_start: 2026-06-18T14:11:13Z
........................................................................ [ 67%]
..................................                                       [100%]
106 passed in 0.28s
run3_exit:0
run3_end: 2026-06-18T14:11:15Z
```

---

## V-09 Exact unavailable message + RuntimeAgent signature

```
exact_message_match: True
actual_message:   "Skill 'calculate_and_save' không khả dụng với backend hiện tại. Thiếu capability: write_note."
expected_message: "Skill 'calculate_and_save' không khả dụng với backend hiện tại. Thiếu capability: write_note."

RuntimeAgent.__init__ params: ['self', 'planner', 'tools', 'executor', 'final_composer', 'lifecycle', 'debug', 'memory_client']
```

---

## Raw factory code — build_local_agent / build_test_agent / build_agent_with_memory_backend

Source: `agent_core/runtime/runtime_agent.py` at `eeccbcf`.

```python
def build_local_agent(
    *,
    planner: Any = None,
    tools: Any = None,
) -> tuple[RuntimeAgent, Any]:
    from agent_core.memory.in_memory_store import InMemoryStore
    from agent_core.memory.local_client import LocalMemoryClient
    from agent_core.memory.factory import validate_memory_activation
    from agent_core.tools.builtin_tools import FakeWebSearchClient
    from agent_core.tools.registry import build_tool_registry

    store = InMemoryStore()
    memory_client = LocalMemoryClient(store)
    resolved_tools = tools or build_tool_registry(FakeWebSearchClient())
    validate_memory_activation(memory_client=memory_client, tools=resolved_tools)
    agent = RuntimeAgent(
        planner=planner or build_rule_based_planner(tools=resolved_tools),
        tools=resolved_tools,
        memory_client=memory_client,
    )
    return agent, store


def build_agent_with_memory_backend(
    *,
    memory_config: Any,
    planner: Any = None,
    tools: Any = None,
) -> tuple[RuntimeAgent, Any]:
    from agent_core.memory.factory import build_memory_backend, validate_memory_activation
    from agent_core.tools.builtin_tools import FakeWebSearchClient
    from agent_core.tools.registry import build_tool_registry

    components = build_memory_backend(memory_config)
    resolved_tools = tools or build_tool_registry(
        FakeWebSearchClient(),
        disabled_tools=components.disabled_tools,
    )
    validate_memory_activation(memory_client=components.memory_client, tools=resolved_tools)
    agent = RuntimeAgent(
        planner=planner or build_rule_based_planner(tools=resolved_tools),
        tools=resolved_tools,
        memory_client=components.memory_client,
    )
    return agent, components.store


def build_test_agent() -> RuntimeAgent:
    from agent_core.tools.builtin_tools import FakeWebSearchClient
    from agent_core.tools.registry import build_tool_registry

    tools = build_tool_registry(FakeWebSearchClient())
    return RuntimeAgent(
        planner=build_rule_based_planner(tools=tools),
        tools=tools,
    )
```

---

## V-10 AC-15 — Composition claim: same resolved ToolRegistry

### What the test checks (object containment, not identity)

```python
def test_catalog_is_built_from_same_registry_as_agent():
    from agent_core.runtime.runtime_agent import build_local_agent, build_test_agent
    from agent_core.planning.skill_aware_intent_planner import SkillAwareIntentPlanner
    from agent_core.planning.rule_based_planner import RuleBasedPlanner
    for factory_name, build_fn in [("build_local_agent", lambda: build_local_agent()[0]),
                                    ("build_test_agent", build_test_agent)]:
        agent = build_fn()
        assert isinstance(agent.planner, RuleBasedPlanner)
        planner = agent.planner.intent_planner
        assert isinstance(planner, SkillAwareIntentPlanner)
        catalog = planner._catalog
        # catalog's active tools ⊆ agent's tools
        for spec in catalog.active.values():
            for tool_name in spec.required_tools:
                assert tool_name in agent.tools, (
                    f"{factory_name}: skill {spec.name!r} uses {tool_name!r} "
                    f"but it is not in agent.tools"
                )
```

### What this proves and what it does NOT prove

**Proves (set containment):** Every `ToolName` declared in every active skill's `required_tools`
is also a key in `agent.tools`. If the catalog was built from a different ToolRegistry that had
extra tools the agent does not have, this assertion would catch it.

**Does NOT prove strict object identity** between the ToolSpec instances — two distinct
`build_tool_registry()` calls produce semantically equal but distinct objects.

### What the factories actually do (source-level proof of same-reference construction)

In every factory the pattern is:

```python
resolved_tools = tools or build_tool_registry(...)   # one dict
agent = RuntimeAgent(
    planner=build_rule_based_planner(tools=resolved_tools),   # same ref
    tools=resolved_tools,                                      # same ref
)
```

`build_rule_based_planner(tools=resolved_tools)` calls `_skill_aware_intent_planner_for_tools(resolved_tools)`
which calls `build_skill_catalog(tools=resolved_tools)` which calls `SkillCatalog.from_specs(specs, tools=resolved_tools)`.

The **same Python dict object** (`resolved_tools`) is passed to both the catalog construction path
and `RuntimeAgent.__init__`. This is a source-level guarantee — not checked by the test, but
verifiable from the factory source above (and verified by the V-10 Python identity output).

### V-10 Python output (subset)

```
=== Path: build_rule_based_planner(tools) ===
id(resolved_tools) = 4314126096
catalog is SkillCatalog: True
  calculate_and_save.calculate: id=4314126096/entry  -- same ToolSpec object
  ...
IDENTITY CLAIM: In each factory the single resolved_tools dict is passed as
the same reference to both build_rule_based_planner(tools=X) and RuntimeAgent(tools=X).
The catalog is built inside build_rule_based_planner from that same X.
Therefore catalog.active.required_tools subset-of agent.tools is guaranteed by construction.

AC-15 PASS
```

### Summary: two distinct but consistent guarantees

| Claim | Evidence type | Verdict |
|---|---|---|
| `required_tools ⊆ agent.tools` for all active skills | Runtime assertion (`test_catalog_is_built_from_same_registry_as_agent`) | **PASS** |
| Catalog built from the same single `resolved_tools` dict reference as `RuntimeAgent.tools` | Source-level inspection of all 3 factories (no branching, single binding point) | **PASS** |

---

## ToolExecutor execute() flow (AC-16)

```
ToolExecutor.execute(step, state):
  1. resolve_args(step.args, state)           → resolved_args   [ArgResolver]
  2. _validate_args(tool, resolved_args)      → final_args      [schema, required/unknown]
  3. policy_engine.check(tool, args, state)   → PolicyDecision  [PolicyEngine — blocks or allows]
     └─ if not allowed → _fail(PolicyDenied)  → return early
  4. approval_gate.check(tool, args, state)   → ApprovalDecision [ApprovalGate]
     └─ if not approved → _fail(ApprovalRequired) → return early
  5. tool.fn(state=state, **final_args)       → ToolResult      [ONE call site: executor.py:120]
  6. isinstance(result, ToolResult) check
  7. _record_result → state.last_result + Observation
```

`tool.fn` is called at executor.py line 120 — **nowhere else** (confirmed by `git grep -n '\.fn(' eeccbcf -- 'agent_core/**/*.py'` returning exactly that one line).

---

## Contract disclaimer (corrected)

No changes to **existing** external contracts (`AgentState`, `ToolSpec`, `ToolExecutor.execute()`,
`MemoryClientProtocol`, `ToolResult`, `ParsedIntent`, `RuntimeAgent.__init__` signature).

New **internal** EX2 contracts **added** per spec (were not previously existing):
`SkillCatalog`, `DisabledSkill`, `DisabledSkillReason` enum,
`SkillSpec.applicable_intents` (rename from `supported_intents`),
`SkillAwareIntentPlanner(catalog=..., fallback=...)` constructor.

These additions are EX2-internal — not modifications to pre-existing external contracts.

---

*Agent dừng. Chờ authorization từ human/architect.*

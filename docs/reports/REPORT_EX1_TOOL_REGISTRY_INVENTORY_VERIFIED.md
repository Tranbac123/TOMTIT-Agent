# REPORT_EX1_TOOL_REGISTRY_INVENTORY_VERIFIED.md

> **Phase:** EX1 — Static Tool Registry
> **Status:** VERIFIED — implementation complete
> **Implementation commit:** `70f16d2861d94dc0f1eb828b7748a6f4263671ba`
> **Verified baseline:** `503ea5d` (post-SR3 + gitignore chore), 214 tests passing
> **Verified at:** 2026-06-18
> **Test result:** 261 passed (214 pre-EX1 + 47 new), 0 failures

---

## 0. Scope

This report records **post-implementation verified facts** for EX1 only. It supersedes
the provisional inventory in `docs/spects/REPORT_EX1_TOOL_REGISTRY_INVENTORY.md`.

Evidence source: `git show 70f16d2:<file>` and `pytest -q` output, run against the
committed implementation.

---

## 1. Implementation delta — `503ea5d..70f16d2`

```text
agent_core/tools/errors.py        NEW  — typed error hierarchy
agent_core/tools/input_schemas.py NEW  — 13 strict Pydantic v2 input schemas
agent_core/tools/base.py          MOD  — 16-check __post_init__, args_schema required
agent_core/tools/registry.py      MOD  — ToolRegistry(Mapping), manifest, providers
tests/test_tool_registry.py       NEW  — 47 EX1 contract tests
```

`git diff --check 503ea5d..70f16d2` exit: 0 (no whitespace errors).

---

## 2. Error hierarchy — `agent_core/tools/errors.py`

```
ToolRegistryError(Exception)
  ├── DuplicateToolError
  ├── UnknownToolError
  ├── InvalidToolSpecError
  └── UnsupportedToolExecutionPolicyError
```

All five classes committed, importable.

---

## 3. Input schema inventory — `agent_core/tools/input_schemas.py`

Base: `ToolArgsModel(BaseModel)` with `ConfigDict(extra="forbid", strict=True, frozen=True)`.

| Schema class          | Fields (required / optional)                   |
|-----------------------|------------------------------------------------|
| `CalculateArgs`       | `expression: str`                              |
| `WriteNoteArgs`       | `name: str`, `content: str`                    |
| `ReadNoteArgs`        | `name: str`                                    |
| `ListNotesArgs`       | *(empty)*                                      |
| `SaveFactArgs`        | `content: str` / `tags: list[str] | None`      |
| `SavePreferenceArgs`  | `content: str` / `tags: list[str] | None`      |
| `SaveDecisionArgs`    | `content: str` / `tags: list[str] | None`      |
| `SearchMemoryArgs`    | `query: str` / `limit: int = 10`               |
| `SummarizeMemoryArgs` | *(none required)* / `query: str = ""`, `limit: int = 10` |
| `SummarizeArgs`       | `text: str`                                    |
| `WebSearchArgs`       | `query: str` / `max_results: int = 3`          |
| `FinishArgs`          | `answer: str`                                  |
| `AnswerFromContextArgs` | `query: str`                               |

Total: 13 schemas. All use `extra="forbid"`, `strict=True`, `frozen=True`.

---

## 4. ToolSpec invariants — `agent_core/tools/base.py`

`__post_init__` enforces in order:

1. `name` is `ToolName` enum member
2. `fn` is callable
3. `description` not blank
4. `required_args ⊆ allowed_args`
5. No empty/whitespace arg names
6. No empty/whitespace side-effect names
7. No duplicate side effects
8. `mutates_state=True` requires at least one side effect
9. `args_schema` is not None
10. `args_schema` is a `BaseModel` subclass
11. `schema.model_fields.keys() == allowed_args` (field-set parity)
12. Required schema fields == `required_args` (required-parity)
13. `schema.model_config["extra"] == "forbid"`
14. `schema.model_config["strict"] == True`
15. `timeout_seconds is None` (EX1-I7)
16. `retry_policy == RetryPolicy(max_attempts=1, backoff_seconds=0.0)` (EX1-I7)

Errors raised: `InvalidToolSpecError` (checks 1–14), `UnsupportedToolExecutionPolicyError` (checks 15–16).

---

## 5. Built-in tool inventory — `agent_core/tools/registry.py`

Registered via `builtin_tool_specs(dependencies)` → `ToolRegistry.from_specs()`.

| Tool name              | Required args          | Optional args       | Mutates | Risk | Side effects    | Approval | Idempotent | Schema                  | timeout |
|------------------------|------------------------|---------------------|---------|------|-----------------|----------|------------|-------------------------|---------|
| `calculate`            | `expression`           | —                   | No      | LOW  | —               | No       | Yes        | `CalculateArgs`         | None    |
| `write_note`           | `name`, `content`      | —                   | Yes     | LOW  | `memory_write`  | No       | Yes        | `WriteNoteArgs`         | None    |
| `read_note`            | `name`                 | —                   | No      | LOW  | —               | No       | Yes        | `ReadNoteArgs`          | None    |
| `list_notes`           | —                      | —                   | No      | LOW  | —               | No       | Yes        | `ListNotesArgs`         | None    |
| `save_fact`            | `content`              | `tags`              | Yes     | LOW  | `memory_write`  | No       | No         | `SaveFactArgs`          | None    |
| `save_preference`      | `content`              | `tags`              | Yes     | LOW  | `memory_write`  | No       | No         | `SavePreferenceArgs`    | None    |
| `save_decision`        | `content`              | `tags`              | Yes     | LOW  | `memory_write`  | No       | No         | `SaveDecisionArgs`      | None    |
| `search_memory`        | `query`                | `limit`             | No      | LOW  | —               | No       | Yes        | `SearchMemoryArgs`      | None    |
| `summarize_memory`     | —                      | `query`, `limit`    | No      | LOW  | —               | No       | Yes        | `SummarizeMemoryArgs`   | None    |
| `summarize`            | `text`                 | —                   | No      | LOW  | —               | No       | Yes        | `SummarizeArgs`         | None    |
| `web_search`           | `query`                | `max_results`       | No      | LOW  | —               | No       | Yes        | `WebSearchArgs`         | None    |
| `finish`               | `answer`               | —                   | No      | LOW  | —               | No       | Yes        | `FinishArgs`            | None    |
| `answer_from_context`  | `query`                | —                   | No      | LOW  | —               | No       | Yes        | `AnswerFromContextArgs` | None    |

**Total: 13 tools. `set(registry) == set(ToolName)` verified by test.**

Completeness guard in `build_tool_registry()` raises `RuntimeError` if `registered != declared`.

---

## 6. ToolRegistry — `agent_core/tools/registry.py`

`ToolRegistry` implements `Mapping[ToolName, ToolSpec]` backed by `MappingProxyType`.

| Method | Behavior |
|---|---|
| `from_specs(specs)` | Raises `DuplicateToolError` on duplicate name |
| `__getitem__(name)` | Returns spec or `KeyError` |
| `__iter__()` | Preserves provider insertion order |
| `__len__()` | Count of registered tools |
| `get(name, default)` | Returns spec or default |
| `require(name)` | Returns spec or `UnknownToolError` |
| `all()` | `MappingProxyType` of internal dict |
| `manifest()` | `tuple[ToolManifestEntry, ...]` — no fn, fresh per call |

`ToolManifestEntry` is `@dataclass(frozen=True)` with `input_schema: MappingProxyType` (detached, mutation-safe).

No public `register()` method. Verified: `hasattr(registry, "register") is False`.

---

## 7. Executor schema flow — `agent_core/tools/executor.py`

Unchanged file. Existing schema path:

```
execute()
  L53-54  resolved_args = resolver.resolve_args(step.args, state)     # RESOLVE
  L55     final_args = _validate_args(tool, resolved_args)             # STRUCTURAL + SCHEMA
            _validate_args():
              L167-172  unknown/missing structural check (ToolArgsError)
              L177      if args_schema is None: return args             # never reached post-EX1
              L180      tool.args_schema.model_validate(args)           # PYDANTIC STRICT
              L181      return validated_args.model_dump()
  L56-67  policy_engine.check(...)                                     # POLICY
  L68-80  approval_gate.check(...)                                     # APPROVAL
  (ValidationError/ToolArgsError caught at L82-100 → fn never called)
  L120    result = tool.fn(state=state, **final_args)                  # FN
```

`ValidationError` and `ToolArgsError` are caught in the same `except` block before
policy/approval. Invalid schema input never reaches policy, approval, or tool fn.

---

## 8. Invariant verification — key tests

| Invariant | Test | Result |
|---|---|---|
| EX1-I1: One execution gate | `test_extension_proof_no_runtime_modification_needed` | PASSED |
| EX1-I2: One spec per name | `test_duplicate_registration_raises`, `test_duplicate_does_not_overwrite` | PASSED |
| EX1-I3: Immutable after construction | `test_registry_is_immutable`, `test_all_view_is_read_only` | PASSED |
| EX1-I4: Registry is Mapping | `test_registry_is_mapping`, `test_runtime_accepts_registry_as_mapping` | PASSED |
| EX1-I5: Schema enforced before invocation | `test_wrong_type_does_not_reach_tool`, `test_missing_arg_does_not_reach_tool`, `test_invalid_schema_input_does_not_call_policy`, `test_invalid_schema_input_does_not_call_approval` | PASSED |
| EX1-I6: Safety stays declarative | `test_policy_runs_before_valid_invocation`, `test_approval_runs_before_valid_invocation` | PASSED |
| EX1-I7: No unsupported exec policy | `test_unsupported_timeout_rejected`, `test_unsupported_retry_rejected`, `test_web_search_timeout_metadata_is_none` | PASSED |
| EX1-I8: Manifest no callables | `test_manifest_contains_no_callable`, `test_manifest_schema_is_detached`, `test_manifest_nested_mutation_does_not_affect_registry` | PASSED |

---

## 9. Pre-implementation gaps — resolution status

| Gap | Resolution |
|---|---|
| G1: Silent duplicate overwrite | Fixed — `DuplicateToolError` in `from_specs()` |
| G2: Registry not authoritative runtime object | Fixed — `build_tool_registry()` returns `ToolRegistry` |
| G3: Mutable after composition | Fixed — `MappingProxyType` backing |
| G4: Monolithic builder | Fixed — `BuiltinToolDependencies` + `builtin_tool_specs()` provider pattern |
| G5: No planner-safe manifest | Fixed — `ToolManifestEntry` + `manifest()` |
| G6: No completeness contract | Fixed — completeness guard in `build_tool_registry()` |
| G7: Closed ToolName enum | Accepted — MVP static tools, per D1 |
| G8: Dead execution metadata | Fixed — `timeout_seconds=None`, retry default enforced |
| G9: Args schema contract incomplete | Fixed — 13 schemas, schema/arg parity checks, executor enforces |

---

## 10. SPEC §9 verification — mandatory pre-implementation reads

All 10 files were read from `44989d6` before implementation:

1. `agent_core/tools/base.py` — VERIFIED
2. `agent_core/tools/registry.py` — VERIFIED (orphaned `ToolRegistry` dataclass confirmed)
3. `agent_core/tools/executor.py` — VERIFIED (schema path L177-181 confirmed)
4. `agent_core/tools/schemas.py` — VERIFIED
5. `agent_core/tools/builtin_tools.py` — VERIFIED (13 fns confirmed)
6. `agent_core/planning/plan_validator.py` — VERIFIED (Mapping compatible, no dict conversion)
7. `agent_core/runtime/runtime_agent.py` — VERIFIED (`tools: Mapping[ToolName, ToolSpec]`)
8. composition (`build_tool_registry()`) — VERIFIED (returned raw dict at baseline)
9. all tool-related tests — VERIFIED (214 passing)
10. `ToolName`, `RiskLevel`, approval enums — VERIFIED

Answers:

- Exact registered tool count at `44989d6`: **13** (CALCULATE through ANSWER_FROM_CONTEXT)
- Dict vs Mapping call sites: zero in production — `RuntimeAgent` already accepts `Mapping`
- `args_schema` use: declared but unused at baseline (executor had `if args_schema is None: return args` — never exercised)
- `timeout_seconds` use: declared as `15.0` for `WEB_SEARCH`, not enforced by executor
- `retry_policy` use: declared, not enforced by executor
- Duplicate behavior at baseline: silent overwrite (`self.tools[spec.name] = spec`)
- Policy/approval dependencies: unchanged — operate on `ToolSpec` metadata
- Output validation: `isinstance(result, ToolResult)` check preserved in executor
- Test mutations after construction: zero pre-EX1 test registry mutations found

---

## 11. Deviations

| Deviation | Impact | Mitigation |
|---|---|---|
| Docs-only commit skipped (`docs/` in `.gitignore`) | Low — tracked in this artifact commit | Fixed in artifact commit |
| Baseline drift: HEAD was `503ea5d` not `44989d6` (one chore commit) | Cosmetic — delta is identical 5 files | Verified `merge-base --is-ancestor 503ea5d 70f16d2` exit 0 |
| `tests/test_tools.py` has direct `.fn(` calls (pre-existing) | Not a violation — unit tests, not runtime path | EX1-I1 applies to runtime execution gate only |

---

## 12. Conclusion

EX1 is complete. All acceptance criteria from `SPEC_EX1_TOOL_REGISTRY.md §12` are met:

- [x] `ToolRegistry` is the runtime catalog object
- [x] Immutable `Mapping` implementation
- [x] Duplicate names fail loud
- [x] All 13 built-ins have strict input schemas
- [x] Schema and required/allowed metadata cannot drift
- [x] `ToolExecutor` validates schema after argument resolution
- [x] Manifest is deterministic and contains no callables
- [x] Existing policy and approval behavior remains intact
- [x] Non-default timeout/retry claims are rejected
- [x] Existing tool flows pass unchanged
- [x] New test tool can be added without editing runtime core
- [x] No skill, LLM or plugin-discovery work introduced
- [x] Full regression suite passes (261/261)

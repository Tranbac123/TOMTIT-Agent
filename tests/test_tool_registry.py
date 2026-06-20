"""EX1 — Static Tool Registry contract tests.

Covers: ToolRegistry, ToolSpec validation, ToolExecutor schema enforcement,
built-in inventory, and extension proof.
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4
from typing import Any

import pytest

from agent_core import AgentState, ToolName, build_tool_registry
from agent_core.planning.rule_based_planner import RuleBasedPlanner
from agent_core.runtime.runtime_agent import RuntimeAgent
from agent_core.safety.approval import ApprovalGate, ApprovalDecision
from agent_core.safety.policy import PolicyEngine, PolicyDecision
from agent_core.state.enums import RiskLevel, ToolResultKind
from agent_core.tools.arg_resolver import ArgResolver
from agent_core.tools.base import RetryPolicy, ToolSpec
from agent_core.tools.errors import (
    DuplicateToolError,
    InvalidToolSpecError,
    UnknownToolError,
    UnsupportedToolExecutionPolicyError,
)
from agent_core.tools.executor import ToolExecutor
from agent_core.tools.input_schemas import (
    CalculateArgs,
    FinishArgs,
    ListNotesArgs,
    SummarizeArgs,
    ToolArgsModel,
)
from agent_core.tools.registry import ToolManifestEntry, ToolRegistry
from agent_core.tools.schemas import ToolResult

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _noop(state: Any, expression: str) -> ToolResult:
    return ToolResult(success=True, output=expression, tool_name="calculate", kind=ToolResultKind.TEXT)


def _make_calc_spec(fn=None) -> ToolSpec:
    return ToolSpec(
        name=ToolName.CALCULATE,
        fn=fn or _noop,
        description="test calculate",
        required_args=frozenset({"expression"}),
        allowed_args=frozenset({"expression"}),
        args_schema=CalculateArgs,
    )


def _make_finish_spec() -> ToolSpec:
    return ToolSpec(
        name=ToolName.FINISH,
        fn=lambda state, answer: ToolResult(success=True, output=answer, tool_name="finish", kind=ToolResultKind.TEXT),
        description="test finish",
        required_args=frozenset({"answer"}),
        allowed_args=frozenset({"answer"}),
        args_schema=FinishArgs,
    )


def _make_list_spec() -> ToolSpec:
    return ToolSpec(
        name=ToolName.LIST_NOTES,
        fn=lambda state: ToolResult(success=True, output=[], tool_name="list_notes", kind=ToolResultKind.JSON),
        description="test list notes",
        required_args=frozenset(),
        allowed_args=frozenset(),
        args_schema=ListNotesArgs,
    )


def make_step(action: ToolName, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(action=action, args=args, status=None, id=str(uuid4()))


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

def test_registry_builds_from_unique_specs():
    registry = ToolRegistry.from_specs([_make_calc_spec(), _make_finish_spec()])
    assert len(registry) == 2
    assert ToolName.CALCULATE in registry
    assert ToolName.FINISH in registry


def test_duplicate_registration_raises():
    with pytest.raises(DuplicateToolError, match="calculate"):
        ToolRegistry.from_specs([_make_calc_spec(), _make_calc_spec()])


def test_duplicate_does_not_overwrite():
    spec_a = _make_calc_spec(fn=lambda state, expression: ToolResult(success=True, output="a", tool_name="x", kind=ToolResultKind.TEXT))
    spec_b = _make_calc_spec(fn=lambda state, expression: ToolResult(success=True, output="b", tool_name="x", kind=ToolResultKind.TEXT))
    with pytest.raises(DuplicateToolError):
        ToolRegistry.from_specs([spec_a, spec_b])


def test_registry_has_no_public_register():
    registry = build_tool_registry()
    assert not hasattr(registry, "register"), "registry must not expose a public register() method"


def test_registry_is_mapping():
    registry = build_tool_registry()
    # Mapping protocol
    spec = registry[ToolName.CALCULATE]
    assert isinstance(spec, ToolSpec)
    assert len(registry) == 13
    names = list(registry)
    assert ToolName.CALCULATE in names


def test_registry_is_immutable():
    registry = ToolRegistry.from_specs([_make_calc_spec()])
    # Mapping does not support item assignment
    with pytest.raises(TypeError):
        registry[ToolName.CALCULATE] = _make_calc_spec()  # type: ignore[index]


def test_all_view_is_read_only():
    registry = build_tool_registry()
    view = registry.all()
    with pytest.raises(TypeError):
        view[ToolName.CALCULATE] = _make_calc_spec()  # type: ignore[index]


def test_require_known_tool():
    registry = ToolRegistry.from_specs([_make_calc_spec()])
    spec = registry.require(ToolName.CALCULATE)
    assert spec.name == ToolName.CALCULATE


def test_require_unknown_tool_raises():
    registry = ToolRegistry.from_specs([_make_calc_spec()])
    with pytest.raises(UnknownToolError, match="finish"):
        registry.require(ToolName.FINISH)


def test_registry_preserves_provider_order():
    specs = [_make_calc_spec(), _make_finish_spec(), _make_list_spec()]
    registry = ToolRegistry.from_specs(specs)
    assert list(registry) == [ToolName.CALCULATE, ToolName.FINISH, ToolName.LIST_NOTES]


def test_manifest_preserves_registry_order():
    specs = [_make_calc_spec(), _make_finish_spec(), _make_list_spec()]
    registry = ToolRegistry.from_specs(specs)
    entries = registry.manifest()
    assert [e.name for e in entries] == [ToolName.CALCULATE, ToolName.FINISH, ToolName.LIST_NOTES]


def test_manifest_contains_no_callable():
    registry = build_tool_registry()
    for entry in registry.manifest():
        assert isinstance(entry, ToolManifestEntry)
        assert not hasattr(entry, "fn"), "manifest entry must not expose fn"
        # input_schema values are JSON-compatible — no callables at top level
        for v in entry.input_schema.values():
            assert not callable(v), f"manifest input_schema has callable value: {v!r}"


def test_manifest_schema_is_detached():
    registry = build_tool_registry()
    entries = registry.manifest()
    # input_schema is a MappingProxyType — mutation raises TypeError
    with pytest.raises(TypeError):
        entries[0].input_schema["injected"] = "attack"  # type: ignore[index]


def test_manifest_nested_mutation_does_not_affect_registry():
    """Mutating a dict extracted from manifest does not affect subsequent manifest() calls."""
    registry = build_tool_registry()
    m1 = registry.manifest()

    # Extract mutable copy of nested schema and mutate it
    schema_copy = dict(m1[0].input_schema)
    if "properties" in schema_copy:
        assert isinstance(schema_copy["properties"], dict)
        schema_copy["properties"]["__injected__"] = "attack"

    # Subsequent manifest() call returns fresh data — injection not present
    m2 = registry.manifest()
    nested = dict(m2[0].input_schema)
    assert "__injected__" not in nested.get("properties", {})


# ---------------------------------------------------------------------------
# ToolSpec validation tests
# ---------------------------------------------------------------------------

class _ValidSchema(ToolArgsModel):
    expression: str


class _EmptySchema(ToolArgsModel):
    pass


def _base_kwargs() -> dict[str, Any]:
    """Minimum valid kwargs for ToolSpec with CALCULATE identity."""
    return dict(
        name=ToolName.CALCULATE,
        fn=_noop,
        description="valid",
        required_args=frozenset({"expression"}),
        allowed_args=frozenset({"expression"}),
        args_schema=_ValidSchema,
    )


def test_blank_description_rejected():
    kw = _base_kwargs()
    kw["description"] = "   "
    with pytest.raises(InvalidToolSpecError, match="description"):
        ToolSpec(**kw)


def test_required_args_must_be_allowed():
    kw = _base_kwargs()
    kw["required_args"] = frozenset({"expression"})
    kw["allowed_args"] = frozenset()  # expression missing from allowed
    # required args not subset of allowed — schema check comes after; but required_args
    # check fires first
    with pytest.raises(InvalidToolSpecError, match="required_args"):
        ToolSpec(**kw)


def test_blank_argument_name_rejected():
    class _BlankFieldSchema(ToolArgsModel):
        expression: str
    # Can't define a field named "" in Python — test via allowed_args directly.
    # The check validates allowed_args set for empty strings.
    kw = _base_kwargs()
    kw["allowed_args"] = frozenset({"expression", ""})
    kw["required_args"] = frozenset({"expression"})
    kw["args_schema"] = _ValidSchema  # schema has only "expression" — will fail schema-fields check
    # Empty arg name is caught before schema-fields check
    with pytest.raises(InvalidToolSpecError, match="empty"):
        ToolSpec(**kw)


def test_mutating_tool_requires_side_effect():
    kw = _base_kwargs()
    kw["mutates_state"] = True
    kw["side_effects"] = ()
    with pytest.raises(InvalidToolSpecError, match="side effect"):
        ToolSpec(**kw)


def test_blank_side_effect_rejected():
    kw = _base_kwargs()
    kw["mutates_state"] = True
    kw["side_effects"] = ("",)
    with pytest.raises(InvalidToolSpecError, match="empty"):
        ToolSpec(**kw)


def test_duplicate_side_effect_rejected():
    kw = _base_kwargs()
    kw["mutates_state"] = True
    kw["side_effects"] = ("memory_write", "memory_write")
    with pytest.raises(InvalidToolSpecError, match="duplicate"):
        ToolSpec(**kw)


def test_missing_args_schema_rejected():
    kw = _base_kwargs()
    kw["args_schema"] = None
    with pytest.raises(InvalidToolSpecError, match="args_schema"):
        ToolSpec(**kw)


def test_schema_fields_match_allowed_args():
    class _WrongFields(ToolArgsModel):
        wrong_field: str  # "expression" expected

    kw = _base_kwargs()
    kw["args_schema"] = _WrongFields
    with pytest.raises(InvalidToolSpecError, match="schema fields"):
        ToolSpec(**kw)


def test_schema_required_fields_match_required_args():
    class _OptionalExpr(ToolArgsModel):
        expression: str = "default"  # has default → not required

    kw = _base_kwargs()
    kw["args_schema"] = _OptionalExpr
    # required_args={"expression"} but schema required={}
    with pytest.raises(InvalidToolSpecError, match="schema required"):
        ToolSpec(**kw)


def test_schema_forbids_extra_fields():
    class _AllowsExtra(BaseModel):
        model_config = ConfigDict(extra="allow", strict=True)
        expression: str

    kw = _base_kwargs()
    kw["args_schema"] = _AllowsExtra
    with pytest.raises(InvalidToolSpecError, match="extra"):
        ToolSpec(**kw)


def test_unsupported_timeout_rejected():
    kw = _base_kwargs()
    kw["timeout_seconds"] = 15.0
    with pytest.raises(UnsupportedToolExecutionPolicyError):
        ToolSpec(**kw)


def test_unsupported_retry_rejected():
    kw = _base_kwargs()
    kw["retry_policy"] = RetryPolicy(max_attempts=3)
    with pytest.raises(UnsupportedToolExecutionPolicyError):
        ToolSpec(**kw)


# ---------------------------------------------------------------------------
# Executor schema-enforcement tests
# ---------------------------------------------------------------------------

def test_valid_schema_args_reach_tool():
    captured: list[str] = []

    def capturing_fn(state: Any, expression: str) -> ToolResult:
        captured.append(expression)
        return ToolResult(success=True, output=expression, tool_name="calculate", kind=ToolResultKind.TEXT)

    spec = ToolSpec(
        name=ToolName.CALCULATE,
        fn=capturing_fn,
        description="capture",
        required_args=frozenset({"expression"}),
        allowed_args=frozenset({"expression"}),
        args_schema=CalculateArgs,
    )
    registry = ToolRegistry.from_specs([spec])
    executor = ToolExecutor(tools=registry, resolver=ArgResolver())
    state = AgentState(goal="x")

    result = executor.execute(make_step(ToolName.CALCULATE, {"expression": "1+1"}), state)

    assert result.success
    assert captured == ["1+1"]


def test_wrong_type_does_not_reach_tool():
    """int passed for expression: str — strict Pydantic rejects before fn is called."""
    called: list[int] = []

    def spy_fn(state: Any, expression: str) -> ToolResult:
        called.append(1)
        return ToolResult(success=True, output=expression, tool_name="calculate", kind=ToolResultKind.TEXT)

    spec = ToolSpec(
        name=ToolName.CALCULATE,
        fn=spy_fn,
        description="spy",
        required_args=frozenset({"expression"}),
        allowed_args=frozenset({"expression"}),
        args_schema=CalculateArgs,
    )
    registry = ToolRegistry.from_specs([spec])
    executor = ToolExecutor(tools=registry, resolver=ArgResolver())
    state = AgentState(goal="x")

    result = executor.execute(make_step(ToolName.CALCULATE, {"expression": 123}), state)

    assert not result.success
    assert called == []
    assert result.metadata["error_type"] == "InvalidToolArgs"


def test_extra_arg_does_not_reach_tool():
    called: list[int] = []

    def spy_fn(state: Any, expression: str) -> ToolResult:
        called.append(1)
        return ToolResult(success=True, output=expression, tool_name="calculate", kind=ToolResultKind.TEXT)

    spec = ToolSpec(
        name=ToolName.CALCULATE,
        fn=spy_fn,
        description="spy",
        required_args=frozenset({"expression"}),
        allowed_args=frozenset({"expression"}),
        args_schema=CalculateArgs,
    )
    registry = ToolRegistry.from_specs([spec])
    executor = ToolExecutor(tools=registry, resolver=ArgResolver())
    state = AgentState(goal="x")

    result = executor.execute(make_step(ToolName.CALCULATE, {"expression": "1+1", "extra": "bad"}), state)

    assert not result.success
    assert called == []
    assert result.metadata["error_type"] == "InvalidToolArgs"


def test_missing_arg_does_not_reach_tool():
    called: list[int] = []

    def spy_fn(state: Any, expression: str) -> ToolResult:
        called.append(1)
        return ToolResult(success=True, output=expression, tool_name="calculate", kind=ToolResultKind.TEXT)

    spec = ToolSpec(
        name=ToolName.CALCULATE,
        fn=spy_fn,
        description="spy",
        required_args=frozenset({"expression"}),
        allowed_args=frozenset({"expression"}),
        args_schema=CalculateArgs,
    )
    registry = ToolRegistry.from_specs([spec])
    executor = ToolExecutor(tools=registry, resolver=ArgResolver())
    state = AgentState(goal="x")

    result = executor.execute(make_step(ToolName.CALCULATE, {}), state)

    assert not result.success
    assert called == []
    assert result.metadata["error_type"] == "InvalidToolArgs"


def test_schema_default_preserves_current_behavior():
    """Optional limit arg with default=10 behaves identically to function default."""
    tools = build_tool_registry()
    executor = ToolExecutor(tools=tools, resolver=ArgResolver())
    state = AgentState(goal="x")

    # SEARCH_MEMORY: only provide required "query", omit optional "limit"
    result = executor.execute(make_step(ToolName.SEARCH_MEMORY, {"query": "test"}), state)

    assert result.success  # schema default limit=10 applied — tool runs without error
    assert result.output.query == "test"


def test_placeholder_resolves_before_schema_validation():
    """$slot.limit resolves to int 5 before strict schema validates limit: int.

    If schema ran on unresolved args, "$slot.limit" (str) would fail strict int
    validation.  With resolution first, 5 (int) passes.
    """
    tools = build_tool_registry()
    executor = ToolExecutor(tools=tools, resolver=ArgResolver())
    state = AgentState(goal="x")
    state.set_slot("limit", 5)  # int in slot

    result = executor.execute(make_step(ToolName.SEARCH_MEMORY, {"query": "test", "limit": "$slot.limit"}), state)

    assert result.success


def test_invalid_schema_input_does_not_call_policy():
    """When schema validation fails, PolicyEngine.check() is never called."""
    policy_calls: list[int] = []

    class _SpyPolicy(PolicyEngine):
        def check(self, *, tool, args, state):
            policy_calls.append(1)
            return super().check(tool=tool, args=args, state=state)

    tools = build_tool_registry()
    executor = ToolExecutor(tools=tools, resolver=ArgResolver(), policy_engine=_SpyPolicy())
    state = AgentState(goal="x")

    result = executor.execute(make_step(ToolName.CALCULATE, {"expression": 999}), state)

    assert not result.success
    assert policy_calls == []


def test_invalid_schema_input_does_not_call_approval():
    """When schema validation fails, ApprovalGate.check() is never called."""
    approval_calls: list[int] = []

    class _SpyApproval(ApprovalGate):
        def check(self, *, tool, args, state):
            approval_calls.append(1)
            return super().check(tool=tool, args=args, state=state)

    tools = build_tool_registry()
    executor = ToolExecutor(tools=tools, resolver=ArgResolver(), approval_gate=_SpyApproval())
    state = AgentState(goal="x")

    result = executor.execute(make_step(ToolName.CALCULATE, {"expression": 999}), state)

    assert not result.success
    assert approval_calls == []


def test_policy_runs_before_valid_invocation():
    """PolicyEngine is called for valid schema args and can deny the tool."""
    policy_calls: list[int] = []

    class _SpyPolicy(PolicyEngine):
        def check(self, *, tool, args, state):
            policy_calls.append(1)
            return super().check(tool=tool, args=args, state=state)

    tools = dict(build_tool_registry())
    tools[ToolName.CALCULATE] = replace(tools[ToolName.CALCULATE], risk_level=RiskLevel.HIGH)
    executor = ToolExecutor(tools=tools, resolver=ArgResolver(), policy_engine=_SpyPolicy())
    state = AgentState(goal="x")

    result = executor.execute(make_step(ToolName.CALCULATE, {"expression": "1+1"}), state)

    assert not result.success
    assert result.metadata["error_type"] == "PolicyDenied"
    assert policy_calls == [1]


def test_approval_runs_before_valid_invocation():
    """ApprovalGate is called for valid schema args and can block the tool."""
    approval_calls: list[int] = []

    class _SpyApproval(ApprovalGate):
        def check(self, *, tool, args, state):
            approval_calls.append(1)
            return super().check(tool=tool, args=args, state=state)

    tools = dict(build_tool_registry())
    tools[ToolName.CALCULATE] = replace(tools[ToolName.CALCULATE], requires_approval=True)
    executor = ToolExecutor(tools=tools, resolver=ArgResolver(), approval_gate=_SpyApproval())
    state = AgentState(goal="x")

    result = executor.execute(make_step(ToolName.CALCULATE, {"expression": "1+1"}), state)

    assert not result.success
    assert result.metadata["error_type"] == "ApprovalRequired"
    assert approval_calls == [1]


def test_existing_tool_result_validation_is_preserved():
    """Tool fn returning a non-ToolResult is still caught after EX1."""
    tools = dict(build_tool_registry())
    tools[ToolName.CALCULATE] = replace(
        tools[ToolName.CALCULATE],
        fn=lambda state, expression: "not a ToolResult",
    )
    executor = ToolExecutor(tools=tools, resolver=ArgResolver())
    state = AgentState(goal="x")

    result = executor.execute(make_step(ToolName.CALCULATE, {"expression": "1+1"}), state)

    assert not result.success
    assert result.metadata["error_type"] == "InvalidToolResult"


# ---------------------------------------------------------------------------
# Built-in inventory tests
# ---------------------------------------------------------------------------

def test_exactly_13_builtin_tools_registered():
    registry = build_tool_registry()
    assert len(registry) == 13


def test_all_toolname_members_registered():
    registry = build_tool_registry()
    assert set(registry) == set(ToolName)


def test_every_builtin_has_args_schema():
    registry = build_tool_registry()
    for name, spec in registry.items():
        assert spec.args_schema is not None, f"{name.value}: args_schema is None"


def test_registry_key_matches_spec_name():
    registry = build_tool_registry()
    for name, spec in registry.items():
        assert name == spec.name, f"key {name.value!r} != spec.name {spec.name.value!r}"


def test_builtin_names_unique():
    registry = build_tool_registry()
    names = [spec.name for spec in registry.values()]
    assert len(names) == len(set(names))


def test_existing_metadata_preserved():
    """Risk, mutation, approval and idempotency metadata unchanged after EX1."""
    registry = build_tool_registry()
    expected = {
        ToolName.CALCULATE:           dict(mutates=False, risk=RiskLevel.LOW, approval=False, idempotent=True),
        ToolName.WRITE_NOTE:          dict(mutates=True,  risk=RiskLevel.LOW, approval=False, idempotent=True),
        ToolName.READ_NOTE:           dict(mutates=False, risk=RiskLevel.LOW, approval=False, idempotent=True),
        ToolName.LIST_NOTES:          dict(mutates=False, risk=RiskLevel.LOW, approval=False, idempotent=True),
        ToolName.SAVE_FACT:           dict(mutates=True,  risk=RiskLevel.LOW, approval=False, idempotent=False),
        ToolName.SAVE_PREFERENCE:     dict(mutates=True,  risk=RiskLevel.LOW, approval=False, idempotent=False),
        ToolName.SAVE_DECISION:       dict(mutates=True,  risk=RiskLevel.LOW, approval=False, idempotent=False),
        ToolName.SEARCH_MEMORY:       dict(mutates=False, risk=RiskLevel.LOW, approval=False, idempotent=True),
        ToolName.SUMMARIZE_MEMORY:    dict(mutates=False, risk=RiskLevel.LOW, approval=False, idempotent=True),
        ToolName.SUMMARIZE:           dict(mutates=False, risk=RiskLevel.LOW, approval=False, idempotent=True),
        ToolName.WEB_SEARCH:          dict(mutates=False, risk=RiskLevel.LOW, approval=False, idempotent=True),
        ToolName.FINISH:              dict(mutates=False, risk=RiskLevel.LOW, approval=False, idempotent=True),
        ToolName.ANSWER_FROM_CONTEXT: dict(mutates=False, risk=RiskLevel.LOW, approval=False, idempotent=True),
    }
    for name, exp in expected.items():
        spec = registry[name]
        assert spec.mutates_state   == exp["mutates"],   f"{name.value}: mutates_state"
        assert spec.risk_level      == exp["risk"],      f"{name.value}: risk_level"
        assert spec.requires_approval == exp["approval"],f"{name.value}: requires_approval"
        assert spec.idempotent      == exp["idempotent"],f"{name.value}: idempotent"


def test_web_search_timeout_metadata_is_none():
    registry = build_tool_registry()
    assert registry[ToolName.WEB_SEARCH].timeout_seconds is None


def test_build_tool_registry_returns_tool_registry():
    registry = build_tool_registry()
    assert isinstance(registry, ToolRegistry)


def test_runtime_accepts_registry_as_mapping():
    """RuntimeAgent accepts ToolRegistry directly — no dict() conversion needed."""
    registry = build_tool_registry()
    agent = RuntimeAgent(planner=RuleBasedPlanner(), tools=registry)
    assert agent.tools is registry


# ---------------------------------------------------------------------------
# Extension proof
# ---------------------------------------------------------------------------

def test_extension_proof_no_runtime_modification_needed():
    """A test-only tool added via ToolRegistry.from_specs() works through the
    existing execution gate without any changes to RuntimeAgent or ToolExecutor."""
    captured: list[str] = []

    def custom_calc(state: Any, expression: str) -> ToolResult:
        captured.append(expression)
        return ToolResult(success=True, output=expression, tool_name="calculate", kind=ToolResultKind.TEXT)

    spec = ToolSpec(
        name=ToolName.CALCULATE,
        fn=custom_calc,
        description="Extension proof: custom calc implementation",
        required_args=frozenset({"expression"}),
        allowed_args=frozenset({"expression"}),
        args_schema=CalculateArgs,
    )

    # ToolRegistry.from_specs() — no runtime/executor modification
    test_registry = ToolRegistry.from_specs([spec])
    executor = ToolExecutor(tools=test_registry, resolver=ArgResolver())
    state = AgentState(goal="test")

    result = executor.execute(make_step(ToolName.CALCULATE, {"expression": "hello"}), state)

    assert result.success
    assert captured == ["hello"]
    assert isinstance(test_registry, ToolRegistry)
    # ToolExecutor.execute() used the same execution gate — no changes needed

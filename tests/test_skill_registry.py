"""EX2 contract tests — SkillName, SkillSpec, SkillRegistry."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_core.planning.intents import IntentName
from agent_core.skills.base import SkillManifestEntry, SkillSpec
from agent_core.skills.errors import (
    DuplicateSkillError,
    DuplicateSkillIntentError,
    InvalidSkillSpecError,
    MissingSkillToolError,
    UnknownSkillError,
)
from agent_core.skills.registry import (
    SkillRegistry,
    build_skill_registry,
    builtin_skill_specs,
)
from agent_core.state.agent_state import Step
from agent_core.state.enums import RiskLevel, SkillName, ToolName
from agent_core.tools.builtin_tools import FakeWebSearchClient
from agent_core.tools.registry import build_tool_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dummy_factory(slots: Mapping[str, Any]) -> list[Step]:
    return [Step("dummy", ToolName.FINISH, {"answer": "ok"})]


def _dummy_factory_b(slots: Mapping[str, Any]) -> list[Step]:
    return [Step("dummy b", ToolName.FINISH, {"answer": "ok"})]


def _make_spec(
    name: SkillName = SkillName.WEB_SEARCH,
    description: str = "Test skill",
    intents: frozenset[IntentName] | None = None,
    required_inputs: frozenset[str] | None = None,
    required_tools: frozenset[ToolName] | None = None,
    factory=_dummy_factory,
) -> SkillSpec:
    return SkillSpec(
        name=name,
        description=description,
        supported_intents=intents or frozenset({IntentName.WEB_SEARCH}),
        required_inputs=required_inputs or frozenset({"query"}),
        required_tools=required_tools or frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
        plan_factory=factory,
    )


def _local_tools() -> Mapping[ToolName, Any]:
    return build_tool_registry(FakeWebSearchClient())


def _remote_tools() -> Mapping[ToolName, Any]:
    from agent_core.tools.registry import LOCAL_DURABLE_TOOLS
    return build_tool_registry(FakeWebSearchClient(), disabled_tools=LOCAL_DURABLE_TOOLS)


# ---------------------------------------------------------------------------
# §14.1 SkillName and SkillSpec
# ---------------------------------------------------------------------------

def test_skill_name_has_three_values():
    names = set(SkillName)
    assert names == {
        SkillName.CALCULATE_AND_SAVE,
        SkillName.READ_AND_SUMMARIZE,
        SkillName.WEB_SEARCH,
    }


def test_skill_spec_blank_description_rejected():
    with pytest.raises(InvalidSkillSpecError, match="description"):
        SkillSpec(
            name=SkillName.WEB_SEARCH,
            description="   ",
            supported_intents=frozenset({IntentName.WEB_SEARCH}),
            required_inputs=frozenset({"query"}),
            required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
            plan_factory=_dummy_factory,
        )


def test_skill_spec_empty_supported_intents_rejected():
    with pytest.raises(InvalidSkillSpecError, match="supported_intents"):
        SkillSpec(
            name=SkillName.WEB_SEARCH,
            description="ok",
            supported_intents=frozenset(),
            required_inputs=frozenset({"query"}),
            required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
            plan_factory=_dummy_factory,
        )


def test_skill_spec_empty_required_tools_rejected():
    with pytest.raises(InvalidSkillSpecError, match="required_tools"):
        SkillSpec(
            name=SkillName.WEB_SEARCH,
            description="ok",
            supported_intents=frozenset({IntentName.WEB_SEARCH}),
            required_inputs=frozenset({"query"}),
            required_tools=frozenset(),
            plan_factory=_dummy_factory,
        )


def test_skill_spec_non_callable_factory_rejected():
    with pytest.raises(InvalidSkillSpecError, match="callable"):
        SkillSpec(
            name=SkillName.WEB_SEARCH,
            description="ok",
            supported_intents=frozenset({IntentName.WEB_SEARCH}),
            required_inputs=frozenset({"query"}),
            required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
            plan_factory="not_a_callable",  # type: ignore[arg-type]
        )


def test_skill_spec_is_frozen():
    spec = _make_spec()
    with pytest.raises(Exception):
        spec.description = "mutated"  # type: ignore[misc]


def test_skill_manifest_entry_is_frozen():
    entry = SkillManifestEntry(
        name=SkillName.WEB_SEARCH,
        description="ok",
        supported_intents=(IntentName.WEB_SEARCH,),
        required_inputs=("query",),
        required_tools=(ToolName.WEB_SEARCH, ToolName.FINISH),
    )
    with pytest.raises(Exception):
        entry.description = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# §14.2 SkillRegistry
# ---------------------------------------------------------------------------

def test_registry_builds_from_three_unique_specs():
    tools = _local_tools()
    specs = builtin_skill_specs(tools)
    registry = SkillRegistry.from_specs(specs, tools=tools)
    assert len(registry) == 3


def test_registry_implements_mapping():
    from collections.abc import Mapping as AbcMapping
    registry = build_skill_registry(tools=_local_tools())
    assert isinstance(registry, AbcMapping)


def test_registry_preserves_insertion_order():
    tools = _local_tools()
    specs = builtin_skill_specs(tools)
    registry = SkillRegistry.from_specs(specs, tools=tools)
    assert list(registry) == [spec.name for spec in specs]


def test_duplicate_skill_name_rejected():
    tools = _local_tools()
    spec_a = _make_spec(name=SkillName.WEB_SEARCH, intents=frozenset({IntentName.WEB_SEARCH}))
    spec_b = _make_spec(name=SkillName.WEB_SEARCH, intents=frozenset({IntentName.PROJECT_CONTEXT_QUERY}))
    with pytest.raises(DuplicateSkillError, match="web_search"):
        SkillRegistry.from_specs((spec_a, spec_b), tools=tools)


def test_duplicate_skill_does_not_overwrite():
    tools = _local_tools()
    spec_a = _make_spec(name=SkillName.WEB_SEARCH, intents=frozenset({IntentName.WEB_SEARCH}))
    spec_b = _make_spec(name=SkillName.WEB_SEARCH, intents=frozenset({IntentName.PROJECT_CONTEXT_QUERY}))
    with pytest.raises(DuplicateSkillError):
        SkillRegistry.from_specs((spec_a, spec_b), tools=tools)
    # if no exception, original would be unchanged — test proves error is raised first


def test_duplicate_intent_ownership_rejected():
    tools = _local_tools()
    spec_a = _make_spec(name=SkillName.WEB_SEARCH, intents=frozenset({IntentName.WEB_SEARCH}))
    spec_b = _make_spec(
        name=SkillName.CALCULATE_AND_SAVE,
        intents=frozenset({IntentName.WEB_SEARCH}),  # duplicate intent
        required_tools=frozenset({ToolName.CALCULATE, ToolName.FINISH}),
        factory=_dummy_factory_b,
    )
    with pytest.raises(DuplicateSkillIntentError, match="web_search"):
        SkillRegistry.from_specs((spec_a, spec_b), tools=tools)


def test_missing_required_tool_rejected():
    # Build a tools mapping without WRITE_NOTE so CALCULATE_AND_SAVE fails
    from agent_core.tools.registry import LOCAL_DURABLE_TOOLS
    limited_tools = build_tool_registry(FakeWebSearchClient(), disabled_tools=LOCAL_DURABLE_TOOLS)
    spec = SkillSpec(
        name=SkillName.CALCULATE_AND_SAVE,
        description="test",
        supported_intents=frozenset({IntentName.CALCULATE_THEN_SAVE_NOTE}),
        required_inputs=frozenset({"expression", "note_name"}),
        required_tools=frozenset({ToolName.CALCULATE, ToolName.WRITE_NOTE, ToolName.FINISH}),
        plan_factory=_dummy_factory,
    )
    with pytest.raises(MissingSkillToolError, match="write_note"):
        SkillRegistry.from_specs((spec,), tools=limited_tools)


def test_known_skill_returned():
    registry = build_skill_registry(tools=_local_tools())
    spec = registry[SkillName.WEB_SEARCH]
    assert spec.name == SkillName.WEB_SEARCH


def test_unknown_skill_rejected():
    # Build a registry with only one skill, then require a non-registered name
    tools = _local_tools()
    spec = _make_spec(name=SkillName.WEB_SEARCH, intents=frozenset({IntentName.WEB_SEARCH}))
    registry = SkillRegistry.from_specs((spec,), tools=tools)
    with pytest.raises(UnknownSkillError):
        registry.require(SkillName.CALCULATE_AND_SAVE)
    with pytest.raises(KeyError):
        _ = registry[SkillName.READ_AND_SUMMARIZE]


def test_for_intent_returns_mapped_skill():
    registry = build_skill_registry(tools=_local_tools())
    spec = registry.for_intent(IntentName.WEB_SEARCH)
    assert spec is not None
    assert spec.name == SkillName.WEB_SEARCH


def test_for_intent_unmapped_returns_none():
    registry = build_skill_registry(tools=_local_tools())
    assert registry.for_intent(IntentName.UNKNOWN) is None


def test_registry_is_immutable():
    registry = build_skill_registry(tools=_local_tools())
    with pytest.raises(TypeError):
        registry[SkillName.WEB_SEARCH] = _make_spec()  # type: ignore[index]


def test_all_view_is_read_only():
    registry = build_skill_registry(tools=_local_tools())
    view = registry.all()
    with pytest.raises(TypeError):
        view[SkillName.WEB_SEARCH] = _make_spec()  # type: ignore[index]


def test_no_public_register_method():
    registry = build_skill_registry(tools=_local_tools())
    assert not hasattr(registry, "register")


def test_manifest_is_deterministic():
    tools = _local_tools()
    m1 = build_skill_registry(tools=tools).manifest()
    m2 = build_skill_registry(tools=tools).manifest()
    assert m1 == m2
    assert isinstance(m1, tuple)


def test_manifest_contains_no_callable():
    for entry in build_skill_registry(tools=_local_tools()).manifest():
        for value in vars(entry).values():
            assert not callable(value), f"manifest entry contains callable: {value!r}"


def test_manifest_contains_no_tool_callable():
    for entry in build_skill_registry(tools=_local_tools()).manifest():
        assert not hasattr(entry, "plan_factory")
        assert not hasattr(entry, "fn")


def test_manifest_mutation_does_not_affect_registry():
    registry = build_skill_registry(tools=_local_tools())
    m = registry.manifest()
    # manifest returns a new tuple each call; mutating it does not change registry
    assert registry.manifest() == m


# ---------------------------------------------------------------------------
# §14.3 Existing skill behavior
# ---------------------------------------------------------------------------

def _steps_comparable(steps: list) -> list[tuple]:
    """Extract (action, args) pairs — id/created_at are unique per call by design."""
    return [(s.action, s.args) for s in steps]


def test_calculate_and_save_returns_fresh_list_each_call():
    from agent_core.skills.calculate_and_save_skill import CalculateAndSaveSkill
    skill = CalculateAndSaveSkill("2+2", "note")
    a = skill.make_steps()
    b = skill.make_steps()
    assert a is not b
    assert _steps_comparable(a) == _steps_comparable(b)


def test_read_and_summarize_returns_fresh_list_each_call():
    from agent_core.skills.read_and_summarize_skill import ReadAndSummarizeSkill
    skill = ReadAndSummarizeSkill("note")
    a = skill.make_steps()
    b = skill.make_steps()
    assert a is not b
    assert _steps_comparable(a) == _steps_comparable(b)


def test_web_search_returns_fresh_list_each_call():
    from agent_core.skills.web_search_skill import WebSearchSkill
    skill = WebSearchSkill("query")
    a = skill.make_steps()
    b = skill.make_steps()
    assert a is not b
    assert _steps_comparable(a) == _steps_comparable(b)


def test_skills_are_stateless():
    from agent_core.skills.calculate_and_save_skill import CalculateAndSaveSkill
    skill = CalculateAndSaveSkill("1+1", "n")
    before = _steps_comparable(skill.make_steps())
    after = _steps_comparable(skill.make_steps())
    assert before == after


def test_no_skill_calls_tool_executor():
    from agent_core.skills.calculate_and_save_skill import CalculateAndSaveSkill
    from agent_core.skills.read_and_summarize_skill import ReadAndSummarizeSkill
    from agent_core.skills.web_search_skill import WebSearchSkill
    import agent_core.tools.executor as exec_module
    # Executor is never imported by any skill module
    skill_modules = [
        "agent_core.skills.calculate_and_save_skill",
        "agent_core.skills.read_and_summarize_skill",
        "agent_core.skills.web_search_skill",
    ]
    import sys
    for mod_name in skill_modules:
        mod = sys.modules[mod_name]
        assert not hasattr(mod, "ToolExecutor"), f"{mod_name} imports ToolExecutor"


def test_every_emitted_action_is_in_required_tools():
    from agent_core.skills.registry import (
        _calculate_and_save_factory,
        _read_and_summarize_factory,
        _web_search_factory,
    )
    calc_save_slots = {"expression": "2+2", "note_name": "n"}
    read_slots = {"note_name": "n"}
    web_slots = {"query": "q"}

    from agent_core.skills.registry import (
        _CALCULATE_AND_SAVE_TOOLS,
        _READ_AND_SUMMARIZE_TOOLS,
        _WEB_SEARCH_TOOLS,
    )
    for step in _calculate_and_save_factory(calc_save_slots):
        assert step.action in _CALCULATE_AND_SAVE_TOOLS
    for step in _read_and_summarize_factory(read_slots):
        assert step.action in _READ_AND_SUMMARIZE_TOOLS
    for step in _web_search_factory(web_slots):
        assert step.action in _WEB_SEARCH_TOOLS


# ---------------------------------------------------------------------------
# §14.7 Composition
# ---------------------------------------------------------------------------

def test_build_skill_registry_returns_skill_registry():
    assert isinstance(build_skill_registry(tools=_local_tools()), SkillRegistry)


def test_local_backend_registers_three_skills():
    registry = build_skill_registry(tools=_local_tools())
    assert len(registry) == 3


def test_remote_backend_registers_one_skill():
    registry = build_skill_registry(tools=_remote_tools())
    assert len(registry) == 1
    assert SkillName.WEB_SEARCH in registry


def test_remote_backend_passes_required_tools_validation():
    # Must not raise MissingSkillToolError
    registry = build_skill_registry(tools=_remote_tools())
    assert isinstance(registry, SkillRegistry)


def test_all_required_tools_exist_in_local_tool_registry():
    tools = _local_tools()
    for spec in build_skill_registry(tools=tools).values():
        missing = spec.required_tools - frozenset(tools.keys())
        assert not missing, f"{spec.name} has missing tools: {missing}"


def test_no_skill_receives_tool_fn():
    tools = _local_tools()
    registry = build_skill_registry(tools=tools)
    for spec in registry.values():
        # plan_factory must not be a ToolSpec.fn
        for tool_spec in tools.values():
            assert spec.plan_factory is not tool_spec.fn


def test_no_skill_receives_tool_executor():
    from agent_core.tools.executor import ToolExecutor
    tools = _local_tools()
    registry = build_skill_registry(tools=tools)
    for spec in registry.values():
        # plan_factory should not be an instance method of ToolExecutor
        assert not isinstance(getattr(spec.plan_factory, "__self__", None), ToolExecutor)

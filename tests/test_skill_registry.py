"""EX2 v1.2 contract tests — SkillName, DisabledSkillReason, SkillSpec,
SkillRegistry, SkillCatalog, DisabledSkill, builtin_skill_specs."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from agent_core.planning.intents import IntentName
from agent_core.skills.base import DisabledSkill, SkillManifestEntry, SkillSpec
from agent_core.skills.errors import (
    DuplicateSkillError,
    DuplicateSkillIntentError,
    InvalidSkillSpecError,
    MissingSkillToolError,
    UnknownSkillError,
)
from agent_core.skills.registry import (
    SkillCatalog,
    SkillRegistry,
    build_skill_catalog,
    build_skill_registry,
    builtin_skill_specs,
)
from agent_core.state.agent_state import Step
from agent_core.state.enums import DisabledSkillReason, SkillName, ToolName
from agent_core.tools.builtin_tools import FakeWebSearchClient
from agent_core.tools.registry import LOCAL_DURABLE_TOOLS, build_tool_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dummy_factory(inputs: Mapping[str, Any]) -> list[Step]:
    return [Step("dummy", ToolName.FINISH, {"answer": "ok"})]


def _dummy_factory_b(inputs: Mapping[str, Any]) -> list[Step]:
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
        applicable_intents=intents or frozenset({IntentName.WEB_SEARCH}),
        required_inputs=required_inputs or frozenset({"query"}),
        required_tools=required_tools or frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
        plan_factory=factory,
    )


def _local_tools() -> Mapping[ToolName, Any]:
    return build_tool_registry(FakeWebSearchClient())


def _remote_tools() -> Mapping[ToolName, Any]:
    return build_tool_registry(FakeWebSearchClient(), disabled_tools=LOCAL_DURABLE_TOOLS)


def _steps_comparable(steps: list) -> list[tuple]:
    """Extract (action, args) pairs — id/created_at are unique per call by design."""
    return [(s.action, s.args) for s in steps]


# ---------------------------------------------------------------------------
# AC-01 SkillName
# ---------------------------------------------------------------------------

def test_skill_name_has_three_values():
    names = set(SkillName)
    assert names == {
        SkillName.CALCULATE_AND_SAVE,
        SkillName.READ_AND_SUMMARIZE,
        SkillName.WEB_SEARCH,
    }


def test_skill_name_in_single_enum_source():
    import inspect
    import agent_core.state.enums as enums_mod
    # SkillName.__module__ must point to enums.py, not any skills sub-module
    assert SkillName.__module__ == enums_mod.__name__, (
        f"SkillName is defined in {SkillName.__module__!r}, expected {enums_mod.__name__!r}"
    )
    assert inspect.getfile(SkillName) == inspect.getfile(enums_mod)


# ---------------------------------------------------------------------------
# AC-02 DisabledSkillReason
# ---------------------------------------------------------------------------

def test_disabled_skill_reason_has_one_value():
    values = set(DisabledSkillReason)
    assert values == {DisabledSkillReason.MISSING_REQUIRED_TOOLS}


def test_disabled_skill_reason_in_single_enum_source():
    import inspect, agent_core.state.enums as enums_mod
    assert inspect.getfile(DisabledSkillReason) == inspect.getfile(enums_mod)


# ---------------------------------------------------------------------------
# AC-03 SkillSpec
# ---------------------------------------------------------------------------

def test_skill_spec_blank_description_rejected():
    with pytest.raises(InvalidSkillSpecError, match="description"):
        SkillSpec(
            name=SkillName.WEB_SEARCH,
            description="   ",
            applicable_intents=frozenset({IntentName.WEB_SEARCH}),
            required_inputs=frozenset({"query"}),
            required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
            plan_factory=_dummy_factory,
        )


def test_skill_spec_empty_applicable_intents_rejected():
    with pytest.raises(InvalidSkillSpecError, match="applicable_intents"):
        SkillSpec(
            name=SkillName.WEB_SEARCH,
            description="ok",
            applicable_intents=frozenset(),
            required_inputs=frozenset({"query"}),
            required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
            plan_factory=_dummy_factory,
        )


def test_skill_spec_empty_required_inputs_rejected():
    with pytest.raises(InvalidSkillSpecError, match="required_inputs"):
        SkillSpec(
            name=SkillName.WEB_SEARCH,
            description="ok",
            applicable_intents=frozenset({IntentName.WEB_SEARCH}),
            required_inputs=frozenset(),
            required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
            plan_factory=_dummy_factory,
        )


def test_skill_spec_empty_required_tools_rejected():
    with pytest.raises(InvalidSkillSpecError, match="required_tools"):
        SkillSpec(
            name=SkillName.WEB_SEARCH,
            description="ok",
            applicable_intents=frozenset({IntentName.WEB_SEARCH}),
            required_inputs=frozenset({"query"}),
            required_tools=frozenset(),
            plan_factory=_dummy_factory,
        )


def test_skill_spec_non_callable_factory_rejected():
    with pytest.raises(InvalidSkillSpecError, match="callable"):
        SkillSpec(
            name=SkillName.WEB_SEARCH,
            description="ok",
            applicable_intents=frozenset({IntentName.WEB_SEARCH}),
            required_inputs=frozenset({"query"}),
            required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
            plan_factory="not_a_callable",  # type: ignore[arg-type]
        )


def test_skill_spec_is_frozen():
    spec = _make_spec()
    with pytest.raises(Exception):
        spec.description = "mutated"  # type: ignore[misc]


def test_skill_spec_no_enable_disable_state():
    spec = _make_spec()
    for attr in ("enabled", "disabled", "active", "missing_tools", "backend"):
        assert not hasattr(spec, attr), f"SkillSpec has unexpected field {attr!r}"


def test_skill_manifest_entry_is_frozen():
    entry = SkillManifestEntry(
        name=SkillName.WEB_SEARCH,
        description="ok",
        applicable_intents=(IntentName.WEB_SEARCH,),
        required_inputs=("query",),
        required_tools=(ToolName.WEB_SEARCH, ToolName.FINISH),
    )
    with pytest.raises(Exception):
        entry.description = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC-04 SkillRegistry — strict Mapping
# ---------------------------------------------------------------------------

def test_registry_implements_mapping():
    from collections.abc import Mapping as AbcMapping
    registry = build_skill_registry(tools=_local_tools())
    assert isinstance(registry, AbcMapping)


def test_registry_preserves_insertion_order():
    tools = _local_tools()
    specs = [s for s in builtin_skill_specs() if s.required_tools <= frozenset(tools.keys())]
    registry = SkillRegistry.from_specs(specs, tools=tools)
    assert list(registry) == [spec.name for spec in specs]


def test_registry_duplicate_skill_name_rejected():
    tools = _local_tools()
    spec_a = _make_spec(name=SkillName.WEB_SEARCH, intents=frozenset({IntentName.WEB_SEARCH}))
    spec_b = _make_spec(name=SkillName.WEB_SEARCH, intents=frozenset({IntentName.PROJECT_CONTEXT_QUERY}))
    with pytest.raises(DuplicateSkillError, match="web_search"):
        SkillRegistry.from_specs((spec_a, spec_b), tools=tools)


def test_registry_duplicate_intent_rejected():
    tools = _local_tools()
    spec_a = _make_spec(name=SkillName.WEB_SEARCH, intents=frozenset({IntentName.WEB_SEARCH}))
    spec_b = _make_spec(
        name=SkillName.CALCULATE_AND_SAVE,
        intents=frozenset({IntentName.WEB_SEARCH}),
        required_tools=frozenset({ToolName.CALCULATE, ToolName.FINISH}),
        factory=_dummy_factory_b,
    )
    with pytest.raises(DuplicateSkillIntentError, match="web_search"):
        SkillRegistry.from_specs((spec_a, spec_b), tools=tools)


def test_registry_missing_required_tool_rejected():
    spec = SkillSpec(
        name=SkillName.CALCULATE_AND_SAVE,
        description="test",
        applicable_intents=frozenset({IntentName.CALCULATE_THEN_SAVE_NOTE}),
        required_inputs=frozenset({"expression", "note_name"}),
        required_tools=frozenset({ToolName.CALCULATE, ToolName.WRITE_NOTE, ToolName.FINISH}),
        plan_factory=_dummy_factory,
    )
    with pytest.raises(MissingSkillToolError, match="write_note"):
        SkillRegistry.from_specs((spec,), tools=_remote_tools())


def test_registry_known_skill_returned():
    registry = build_skill_registry(tools=_local_tools())
    spec = registry[SkillName.WEB_SEARCH]
    assert spec.name == SkillName.WEB_SEARCH


def test_registry_unknown_skill_rejected():
    spec = _make_spec(name=SkillName.WEB_SEARCH, intents=frozenset({IntentName.WEB_SEARCH}))
    registry = SkillRegistry.from_specs((spec,), tools=_local_tools())
    with pytest.raises(UnknownSkillError):
        registry.require(SkillName.CALCULATE_AND_SAVE)
    with pytest.raises(KeyError):
        _ = registry[SkillName.READ_AND_SUMMARIZE]


def test_registry_for_intent_returns_mapped_skill():
    registry = build_skill_registry(tools=_local_tools())
    spec = registry.for_intent(IntentName.WEB_SEARCH)
    assert spec is not None
    assert spec.name == SkillName.WEB_SEARCH


def test_registry_for_intent_unmapped_returns_none():
    registry = build_skill_registry(tools=_local_tools())
    assert registry.for_intent(IntentName.UNKNOWN) is None


def test_registry_is_immutable():
    registry = build_skill_registry(tools=_local_tools())
    with pytest.raises(TypeError):
        registry[SkillName.WEB_SEARCH] = _make_spec()  # type: ignore[index]


def test_registry_all_view_is_read_only():
    registry = build_skill_registry(tools=_local_tools())
    view = registry.all()
    with pytest.raises(TypeError):
        view[SkillName.WEB_SEARCH] = _make_spec()  # type: ignore[index]


def test_registry_no_public_register_method():
    assert not hasattr(build_skill_registry(tools=_local_tools()), "register")


def test_registry_manifest_is_deterministic():
    tools = _local_tools()
    m1 = build_skill_registry(tools=tools).manifest()
    m2 = build_skill_registry(tools=tools).manifest()
    assert m1 == m2
    assert isinstance(m1, tuple)


def test_registry_manifest_contains_no_callable():
    for entry in build_skill_registry(tools=_local_tools()).manifest():
        for value in vars(entry).values():
            assert not callable(value), f"manifest entry contains callable: {value!r}"


def test_registry_manifest_has_no_plan_factory_field():
    for entry in build_skill_registry(tools=_local_tools()).manifest():
        assert not hasattr(entry, "plan_factory")
        assert not hasattr(entry, "fn")


# ---------------------------------------------------------------------------
# AC-05 / AC-06 SkillCatalog partitioning
# ---------------------------------------------------------------------------

def test_catalog_local_three_active_zero_disabled():
    catalog = build_skill_catalog(tools=_local_tools())
    assert len(catalog.active) == 3
    assert len(catalog.disabled) == 0


def test_catalog_remote_one_active_two_disabled():
    catalog = build_skill_catalog(tools=_remote_tools())
    assert len(catalog.active) == 1
    assert len(catalog.disabled) == 2


def test_catalog_remote_active_is_web_search():
    catalog = build_skill_catalog(tools=_remote_tools())
    assert SkillName.WEB_SEARCH in catalog.active


def test_catalog_remote_disabled_names():
    catalog = build_skill_catalog(tools=_remote_tools())
    disabled_names = {ds.name for ds in catalog.disabled}
    assert disabled_names == {SkillName.CALCULATE_AND_SAVE, SkillName.READ_AND_SUMMARIZE}


def test_catalog_no_skill_disappears_silently():
    """Every incompatible built-in must appear as a DisabledSkill (AC-06)."""
    catalog = build_skill_catalog(tools=_remote_tools())
    all_names = {s.name for s in builtin_skill_specs()}
    active_names = set(catalog.active)
    disabled_names = {ds.name for ds in catalog.disabled}
    assert all_names == active_names | disabled_names


def test_catalog_active_and_disabled_are_disjoint():
    catalog = build_skill_catalog(tools=_remote_tools())
    active_names = set(catalog.active)
    disabled_names = {ds.name for ds in catalog.disabled}
    assert active_names.isdisjoint(disabled_names)


def test_catalog_disabled_ordering_deterministic():
    """Same tool set produces same disabled tuple order on repeated calls."""
    c1 = build_skill_catalog(tools=_remote_tools())
    c2 = build_skill_catalog(tools=_remote_tools())
    assert [ds.name for ds in c1.disabled] == [ds.name for ds in c2.disabled]


# ---------------------------------------------------------------------------
# AC-07C exact missing tools
# ---------------------------------------------------------------------------

def test_catalog_calculate_and_save_disabled_missing_write_note():
    catalog = build_skill_catalog(tools=_remote_tools())
    ds = next(ds for ds in catalog.disabled if ds.name == SkillName.CALCULATE_AND_SAVE)
    assert ToolName.WRITE_NOTE in ds.missing_tools


def test_catalog_read_and_summarize_disabled_missing_read_note():
    catalog = build_skill_catalog(tools=_remote_tools())
    ds = next(ds for ds in catalog.disabled if ds.name == SkillName.READ_AND_SUMMARIZE)
    assert ToolName.READ_NOTE in ds.missing_tools


def test_catalog_disabled_missing_tools_subset_of_required_tools():
    for ds in build_skill_catalog(tools=_remote_tools()).disabled:
        assert frozenset(ds.missing_tools) <= frozenset(ds.required_tools)


def test_catalog_disabled_missing_tools_sorted_by_value():
    for ds in build_skill_catalog(tools=_remote_tools()).disabled:
        values = [t.value for t in ds.missing_tools]
        assert values == sorted(values)


def test_catalog_disabled_missing_tools_non_empty():
    for ds in build_skill_catalog(tools=_remote_tools()).disabled:
        assert len(ds.missing_tools) > 0


def test_catalog_disabled_has_correct_reason():
    for ds in build_skill_catalog(tools=_remote_tools()).disabled:
        assert ds.reason == DisabledSkillReason.MISSING_REQUIRED_TOOLS


def test_catalog_disabled_no_plan_factory():
    for ds in build_skill_catalog(tools=_remote_tools()).disabled:
        assert not hasattr(ds, "plan_factory")
        assert not callable(ds)


def test_catalog_disabled_no_callable():
    for ds in build_skill_catalog(tools=_remote_tools()).disabled:
        for attr in vars(ds).values():
            assert not callable(attr), f"DisabledSkill has callable field: {attr!r}"


def test_catalog_disabled_is_frozen():
    ds_list = build_skill_catalog(tools=_remote_tools()).disabled
    assert len(ds_list) > 0
    with pytest.raises(Exception):
        ds_list[0].reason = DisabledSkillReason.MISSING_REQUIRED_TOOLS  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC-05 SkillCatalog construction order — duplicates validated before partition
# ---------------------------------------------------------------------------

def test_catalog_duplicate_name_fails_before_partition():
    """DuplicateSkillError must fire before any partitioning happens."""
    spec_a = _make_spec(name=SkillName.WEB_SEARCH, intents=frozenset({IntentName.WEB_SEARCH}))
    spec_b = _make_spec(name=SkillName.WEB_SEARCH, intents=frozenset({IntentName.PROJECT_CONTEXT_QUERY}))
    with pytest.raises(DuplicateSkillError):
        SkillCatalog.from_specs((spec_a, spec_b), tools=_remote_tools())


def test_catalog_duplicate_intent_fails_before_partition():
    """DuplicateSkillIntentError fires before partition even when skills have different names."""
    spec_a = _make_spec(name=SkillName.WEB_SEARCH, intents=frozenset({IntentName.WEB_SEARCH}))
    spec_b = _make_spec(
        name=SkillName.CALCULATE_AND_SAVE,
        intents=frozenset({IntentName.WEB_SEARCH}),
        required_tools=frozenset({ToolName.CALCULATE, ToolName.FINISH}),
        factory=_dummy_factory_b,
    )
    with pytest.raises(DuplicateSkillIntentError):
        SkillCatalog.from_specs((spec_a, spec_b), tools=_remote_tools())


# ---------------------------------------------------------------------------
# AC-04 SkillRegistry remains strict when called directly
# ---------------------------------------------------------------------------

def test_registry_directly_rejects_incompatible_spec():
    """SkillRegistry.from_specs() must still raise MissingSkillToolError when
    called directly with a spec that has missing tools (not via catalog)."""
    spec = SkillSpec(
        name=SkillName.CALCULATE_AND_SAVE,
        description="test",
        applicable_intents=frozenset({IntentName.CALCULATE_THEN_SAVE_NOTE}),
        required_inputs=frozenset({"expression", "note_name"}),
        required_tools=frozenset({ToolName.CALCULATE, ToolName.WRITE_NOTE, ToolName.FINISH}),
        plan_factory=_dummy_factory,
    )
    with pytest.raises(MissingSkillToolError):
        SkillRegistry.from_specs((spec,), tools=_remote_tools())


# ---------------------------------------------------------------------------
# AC-13 / provider rules
# ---------------------------------------------------------------------------

def test_builtin_skill_specs_always_returns_three():
    """Provider returns all 3 specs regardless of backend."""
    specs = builtin_skill_specs()
    assert len(specs) == 3
    names = {spec.name for spec in specs}
    assert names == {SkillName.CALCULATE_AND_SAVE, SkillName.READ_AND_SUMMARIZE, SkillName.WEB_SEARCH}


def test_builtin_skill_specs_takes_no_args():
    """Provider must be called without arguments (spec §8.4)."""
    import inspect
    sig = inspect.signature(builtin_skill_specs)
    assert len(sig.parameters) == 0


def test_builtin_skill_specs_does_not_filter_by_backend():
    """Same function call returns the same specs regardless of backend state."""
    specs = builtin_skill_specs()
    assert SkillName.CALCULATE_AND_SAVE in {s.name for s in specs}
    assert SkillName.READ_AND_SUMMARIZE in {s.name for s in specs}


def test_skills_are_stateless():
    from agent_core.skills.calculate_and_save_skill import CalculateAndSaveSkill
    skill = CalculateAndSaveSkill("1+1", "n")
    before = _steps_comparable(skill.make_steps())
    after = _steps_comparable(skill.make_steps())
    assert before == after


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


def test_no_skill_calls_tool_executor():
    import sys
    skill_modules = [
        "agent_core.skills.calculate_and_save_skill",
        "agent_core.skills.read_and_summarize_skill",
        "agent_core.skills.web_search_skill",
    ]
    for mod_name in skill_modules:
        mod = sys.modules[mod_name]
        assert not hasattr(mod, "ToolExecutor"), f"{mod_name} imports ToolExecutor"


def test_no_skill_receives_tool_fn():
    tools = _local_tools()
    registry = build_skill_registry(tools=tools)
    for spec in registry.values():
        for tool_spec in tools.values():
            assert spec.plan_factory is not tool_spec.fn


def test_no_skill_receives_tool_executor():
    from agent_core.tools.executor import ToolExecutor
    for spec in build_skill_registry(tools=_local_tools()).values():
        assert not isinstance(getattr(spec.plan_factory, "__self__", None), ToolExecutor)


# ---------------------------------------------------------------------------
# AC-07E remote active skills do not use local-memory tools
# ---------------------------------------------------------------------------

def test_remote_active_skills_reference_no_local_memory_tools():
    """No active remote skill's required_tools may overlap LOCAL_DURABLE_TOOLS (AC-07E)."""
    catalog = build_skill_catalog(tools=_remote_tools())
    for spec in catalog.active.values():
        overlap = spec.required_tools & LOCAL_DURABLE_TOOLS
        assert not overlap, (
            f"Active remote skill {spec.name!r} references local-memory tools: {overlap}"
        )


def test_remote_catalog_build_does_not_raise():
    """Remote startup succeeds even with incompatible skills (AC-07B)."""
    catalog = build_skill_catalog(tools=_remote_tools())
    assert isinstance(catalog, SkillCatalog)


# ---------------------------------------------------------------------------
# AC-15 catalog uses exact resolved ToolRegistry
# ---------------------------------------------------------------------------

def test_local_backend_all_active_required_tools_present():
    tools = _local_tools()
    catalog = build_skill_catalog(tools=tools)
    for spec in catalog.active.values():
        missing = spec.required_tools - frozenset(tools.keys())
        assert not missing, f"{spec.name} has missing tools: {missing}"


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

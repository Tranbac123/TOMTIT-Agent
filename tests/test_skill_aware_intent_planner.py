"""EX2 v1.2 — SkillAwareIntentPlanner routing, parity, fallback, unavailable,
and regression tests."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_core.planning.intent_planner import IntentPlanner
from agent_core.planning.intents import IntentName, ParsedIntent
from agent_core.planning.rule_based_planner import RuleBasedPlanner, build_rule_based_planner
from agent_core.planning.skill_aware_intent_planner import SkillAwareIntentPlanner
from agent_core.skills.base import DisabledSkill, SkillSpec
from agent_core.skills.errors import InvalidSkillPlanError
from agent_core.skills.registry import SkillCatalog, SkillRegistry, build_skill_catalog
from agent_core.state.agent_state import AgentState, Step
from agent_core.state.enums import DisabledSkillReason, SkillName, ToolName
from agent_core.tools.builtin_tools import FakeWebSearchClient
from agent_core.tools.registry import LOCAL_DURABLE_TOOLS, build_tool_registry


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_NOTE = "budget"
_EXPR = "(15+5)*3"
_QUERY = "thông tin về Ducati Monster 795"


def _golden_calculate_save(expr: str = _EXPR, note: str = _NOTE) -> list[tuple]:
    return [
        (ToolName.CALCULATE,  {"expression": expr}),
        (ToolName.WRITE_NOTE, {"name": note, "content": "$last_text"}),
        (ToolName.FINISH,     {"answer": f"Đã tính xong và lưu vào ghi chú '{note}'. Kết quả: ${{slot.calc_result}}"}),
    ]


def _golden_read_summarize(note: str = _NOTE) -> list[tuple]:
    return [
        (ToolName.READ_NOTE, {"name": note}),
        (ToolName.SUMMARIZE, {"text": "$last.output.content"}),
        (ToolName.FINISH,    {"answer": "Tóm tắt: ${last.output.summary}"}),
    ]


def _golden_web_search(query: str = _QUERY) -> list[tuple]:
    return [
        (ToolName.WEB_SEARCH, {"query": query, "max_results": 3}),
        (ToolName.FINISH,     {"answer": "$last_text"}),
    ]


def _plan_signature(steps: list[Step]) -> list[tuple]:
    return [(s.action, s.args) for s in steps]


def _local_tools():
    return build_tool_registry(FakeWebSearchClient())


def _remote_tools():
    return build_tool_registry(FakeWebSearchClient(), disabled_tools=LOCAL_DURABLE_TOOLS)


def _parsed(
    intent: IntentName,
    *,
    expression: str | None = None,
    note_name: str | None = None,
    query: str | None = None,
    content: str | None = None,
    missing_slots: tuple[str, ...] = (),
) -> ParsedIntent:
    return ParsedIntent(
        intent=intent,
        confidence=1.0,
        source="test",
        raw_text="",
        expression=expression,
        note_name=note_name,
        query=query,
        content=content,
        missing_slots=missing_slots,
    )


def _build_local_planner() -> SkillAwareIntentPlanner:
    return SkillAwareIntentPlanner(
        catalog=build_skill_catalog(tools=_local_tools()),
        fallback=IntentPlanner(),
    )


def _build_remote_planner() -> SkillAwareIntentPlanner:
    return SkillAwareIntentPlanner(
        catalog=build_skill_catalog(tools=_remote_tools()),
        fallback=IntentPlanner(),
    )


def _dummy_factory(inputs: Mapping[str, Any]) -> list[Step]:
    return [Step("dummy", ToolName.FINISH, {"answer": "ok"})]


# ---------------------------------------------------------------------------
# AC-11 Exact plan parity
# ---------------------------------------------------------------------------

def test_calculate_save_parity_via_skill_aware():
    planner = _build_local_planner()
    parsed = _parsed(IntentName.CALCULATE_THEN_SAVE_NOTE, expression=_EXPR, note_name=_NOTE)
    steps = planner.make_plan(parsed)
    assert _plan_signature(steps) == _golden_calculate_save()


def test_read_summarize_parity_via_skill_aware():
    planner = _build_local_planner()
    steps = planner.make_plan(_parsed(IntentName.READ_NOTE_THEN_SUMMARIZE, note_name=_NOTE))
    assert _plan_signature(steps) == _golden_read_summarize()


def test_web_search_parity_via_skill_aware():
    planner = _build_local_planner()
    steps = planner.make_plan(_parsed(IntentName.WEB_SEARCH, query=_QUERY))
    assert _plan_signature(steps) == _golden_web_search()


def test_web_search_max_results_exactly_3():
    steps = _build_local_planner().make_plan(_parsed(IntentName.WEB_SEARCH, query="test"))
    assert steps[0].action == ToolName.WEB_SEARCH
    assert steps[0].args["max_results"] == 3


def test_calculate_save_step_order_preserved():
    steps = _build_local_planner().make_plan(
        _parsed(IntentName.CALCULATE_THEN_SAVE_NOTE, expression=_EXPR, note_name=_NOTE)
    )
    assert [s.action for s in steps] == [ToolName.CALCULATE, ToolName.WRITE_NOTE, ToolName.FINISH]


def test_read_summarize_step_order_preserved():
    steps = _build_local_planner().make_plan(
        _parsed(IntentName.READ_NOTE_THEN_SUMMARIZE, note_name=_NOTE)
    )
    assert [s.action for s in steps] == [ToolName.READ_NOTE, ToolName.SUMMARIZE, ToolName.FINISH]


def test_finish_step_preserved_calculate_save():
    steps = _build_local_planner().make_plan(
        _parsed(IntentName.CALCULATE_THEN_SAVE_NOTE, expression=_EXPR, note_name=_NOTE)
    )
    finish = steps[-1]
    assert finish.action == ToolName.FINISH
    assert _NOTE in finish.args["answer"]
    assert "${slot.calc_result}" in finish.args["answer"]


def test_parity_via_full_rule_based_planner():
    planner = build_rule_based_planner(tools=_local_tools())
    state = AgentState(goal=f"Tính {_EXPR} rồi lưu vào ghi chú {_NOTE}")
    steps = planner.make_plan(state)
    assert _plan_signature(steps) == _golden_calculate_save(_EXPR, _NOTE)


def test_web_parity_via_full_rule_based_planner():
    planner = build_rule_based_planner(tools=_local_tools())
    state = AgentState(goal=f"Tìm {_QUERY}")
    steps = planner.make_plan(state)
    assert steps[0].action == ToolName.WEB_SEARCH
    assert steps[0].args["max_results"] == 3


# ---------------------------------------------------------------------------
# AC-09 Routing — mapped active skills
# ---------------------------------------------------------------------------

def test_mapped_calculate_save_calls_skill():
    fallback = MagicMock(spec=IntentPlanner)
    planner = SkillAwareIntentPlanner(
        catalog=build_skill_catalog(tools=_local_tools()), fallback=fallback
    )
    steps = planner.make_plan(
        _parsed(IntentName.CALCULATE_THEN_SAVE_NOTE, expression="1+1", note_name="n")
    )
    fallback.make_plan.assert_not_called()
    assert steps[0].action == ToolName.CALCULATE


def test_mapped_read_summarize_calls_skill():
    fallback = MagicMock(spec=IntentPlanner)
    planner = SkillAwareIntentPlanner(
        catalog=build_skill_catalog(tools=_local_tools()), fallback=fallback
    )
    steps = planner.make_plan(_parsed(IntentName.READ_NOTE_THEN_SUMMARIZE, note_name="n"))
    fallback.make_plan.assert_not_called()
    assert steps[0].action == ToolName.READ_NOTE


def test_mapped_web_search_calls_skill():
    fallback = MagicMock(spec=IntentPlanner)
    planner = SkillAwareIntentPlanner(
        catalog=build_skill_catalog(tools=_local_tools()), fallback=fallback
    )
    steps = planner.make_plan(_parsed(IntentName.WEB_SEARCH, query="q"))
    fallback.make_plan.assert_not_called()
    assert steps[0].action == ToolName.WEB_SEARCH


def test_fallback_not_called_for_mapped_intent():
    fallback = MagicMock(spec=IntentPlanner)
    planner = SkillAwareIntentPlanner(
        catalog=build_skill_catalog(tools=_local_tools()), fallback=fallback
    )
    planner.make_plan(_parsed(IntentName.WEB_SEARCH, query="q"))
    fallback.make_plan.assert_not_called()


# ---------------------------------------------------------------------------
# AC-10 Routing — unknown → fallback exactly once
# ---------------------------------------------------------------------------

def test_fallback_called_for_unmapped_intent():
    fallback = MagicMock(spec=IntentPlanner)
    fallback.make_plan.return_value = [Step("done", ToolName.FINISH, {"answer": "ok"})]
    planner = SkillAwareIntentPlanner(
        catalog=build_skill_catalog(tools=_local_tools()), fallback=fallback
    )
    planner.make_plan(_parsed(IntentName.CALCULATE, expression="1+1"))
    fallback.make_plan.assert_called_once()


def test_fallback_called_exactly_once_for_unknown():
    fallback = MagicMock(spec=IntentPlanner)
    fallback.make_plan.return_value = [Step("done", ToolName.FINISH, {"answer": "ok"})]
    planner = SkillAwareIntentPlanner(
        catalog=build_skill_catalog(tools=_local_tools()), fallback=fallback
    )
    planner.make_plan(_parsed(IntentName.UNKNOWN))
    assert fallback.make_plan.call_count == 1


# ---------------------------------------------------------------------------
# AC-07D Routing — disabled → unavailable FINISH
# ---------------------------------------------------------------------------

def test_disabled_calculate_save_produces_unavailable_plan():
    planner = _build_remote_planner()
    steps = planner.make_plan(
        _parsed(IntentName.CALCULATE_THEN_SAVE_NOTE, expression="1+1", note_name="n")
    )
    assert len(steps) == 1
    assert steps[0].action == ToolName.FINISH
    assert "calculate_and_save" in steps[0].args["answer"]
    assert "write_note" in steps[0].args["answer"]


def test_disabled_read_summarize_produces_unavailable_plan():
    planner = _build_remote_planner()
    steps = planner.make_plan(_parsed(IntentName.READ_NOTE_THEN_SUMMARIZE, note_name="n"))
    assert len(steps) == 1
    assert steps[0].action == ToolName.FINISH
    assert "read_and_summarize" in steps[0].args["answer"]
    assert "read_note" in steps[0].args["answer"]


def test_unavailable_exact_message_format():
    planner = _build_remote_planner()
    steps = planner.make_plan(
        _parsed(IntentName.CALCULATE_THEN_SAVE_NOTE, expression="1+1", note_name="n")
    )
    assert steps[0].args["answer"] == (
        "Skill 'calculate_and_save' không khả dụng với backend hiện tại. "
        "Thiếu capability: write_note."
    )


def test_unavailable_does_not_call_fallback():
    fallback = MagicMock(spec=IntentPlanner)
    planner = SkillAwareIntentPlanner(
        catalog=build_skill_catalog(tools=_remote_tools()), fallback=fallback
    )
    planner.make_plan(
        _parsed(IntentName.CALCULATE_THEN_SAVE_NOTE, expression="1+1", note_name="n")
    )
    fallback.make_plan.assert_not_called()


def test_unavailable_does_not_call_plan_factory():
    factory_called: list[bool] = []

    def spy_factory(inputs: Mapping[str, Any]) -> list[Step]:
        factory_called.append(True)
        return [Step("x", ToolName.FINISH, {"answer": "ok"})]

    tools_no_web = build_tool_registry(
        FakeWebSearchClient(), disabled_tools=frozenset({ToolName.WEB_SEARCH})
    )
    spec = SkillSpec(
        name=SkillName.WEB_SEARCH,
        description="web",
        applicable_intents=frozenset({IntentName.WEB_SEARCH}),
        required_inputs=frozenset({"query"}),
        required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
        plan_factory=spy_factory,
    )
    catalog = SkillCatalog.from_specs((spec,), tools=tools_no_web)
    planner = SkillAwareIntentPlanner(catalog=catalog, fallback=IntentPlanner())
    planner.make_plan(_parsed(IntentName.WEB_SEARCH, query="q"))
    assert not factory_called, "plan_factory was called for a disabled skill"


def test_unavailable_multiple_missing_tools_sorted():
    spec = SkillSpec(
        name=SkillName.CALCULATE_AND_SAVE,
        description="test",
        applicable_intents=frozenset({IntentName.CALCULATE_THEN_SAVE_NOTE}),
        required_inputs=frozenset({"expression", "note_name"}),
        required_tools=frozenset({
            ToolName.CALCULATE, ToolName.WRITE_NOTE, ToolName.READ_NOTE, ToolName.FINISH
        }),
        plan_factory=_dummy_factory,
    )
    catalog = SkillCatalog.from_specs((spec,), tools=_remote_tools())
    planner = SkillAwareIntentPlanner(catalog=catalog, fallback=IntentPlanner())
    steps = planner.make_plan(
        _parsed(IntentName.CALCULATE_THEN_SAVE_NOTE, expression="1", note_name="n")
    )
    msg = steps[0].args["answer"]
    assert "read_note, write_note" in msg  # lexicographic: read_note < write_note


# ---------------------------------------------------------------------------
# AC-08 Clarification precedes skill dispatch (missing_slots)
# ---------------------------------------------------------------------------

def test_missing_slots_delegates_to_fallback_before_active():
    fallback = MagicMock(spec=IntentPlanner)
    fallback.make_plan.return_value = [Step("clarify", ToolName.FINISH, {"answer": "?"})]
    planner = SkillAwareIntentPlanner(
        catalog=build_skill_catalog(tools=_local_tools()), fallback=fallback
    )
    planner.make_plan(_parsed(IntentName.WEB_SEARCH, missing_slots=("query",)))
    fallback.make_plan.assert_called_once()


def test_missing_slots_delegates_to_fallback_before_unavailable():
    fallback = MagicMock(spec=IntentPlanner)
    fallback.make_plan.return_value = [Step("clarify", ToolName.FINISH, {"answer": "?"})]
    planner = SkillAwareIntentPlanner(
        catalog=build_skill_catalog(tools=_remote_tools()), fallback=fallback
    )
    planner.make_plan(_parsed(
        IntentName.CALCULATE_THEN_SAVE_NOTE, missing_slots=("expression",)
    ))
    fallback.make_plan.assert_called_once()


# ---------------------------------------------------------------------------
# AC-12 Shadow logic absent
# ---------------------------------------------------------------------------

def test_shadow_methods_absent_from_intent_planner():
    planner = IntentPlanner()
    assert not hasattr(planner, "_calculate_then_save_note_plan")
    assert not hasattr(planner, "_read_note_then_summarize_plan")
    assert not hasattr(planner, "_web_search_plan")


def test_shadow_routing_produces_unknown_via_intent_planner_alone():
    """IntentPlanner alone for skill intents → unknown (shadow removed)."""
    planner = IntentPlanner()
    result = planner.make_plan(
        _parsed(IntentName.CALCULATE_THEN_SAVE_NOTE, expression="1+1", note_name="n")
    )
    assert len(result) == 1
    assert result[0].action == ToolName.FINISH


def test_registered_skill_failure_does_not_silently_fall_back():
    def bad_factory(inputs: Mapping[str, Any]) -> list[Step]:
        return []

    spec = SkillSpec(
        name=SkillName.WEB_SEARCH,
        description="bad",
        applicable_intents=frozenset({IntentName.WEB_SEARCH}),
        required_inputs=frozenset({"query"}),
        required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
        plan_factory=bad_factory,
    )
    registry = SkillRegistry.from_specs((spec,), tools=_local_tools())
    catalog = SkillCatalog(active=registry, disabled=())
    fallback = MagicMock(spec=IntentPlanner)
    planner = SkillAwareIntentPlanner(catalog=catalog, fallback=fallback)

    with pytest.raises(InvalidSkillPlanError, match="empty"):
        planner.make_plan(_parsed(IntentName.WEB_SEARCH, query="q"))
    fallback.make_plan.assert_not_called()


def test_non_list_skill_output_rejected():
    def bad_factory(inputs: Mapping[str, Any]) -> list[Step]:  # type: ignore[return-value]
        return None  # type: ignore[return-value]

    spec = SkillSpec(
        name=SkillName.WEB_SEARCH, description="bad",
        applicable_intents=frozenset({IntentName.WEB_SEARCH}),
        required_inputs=frozenset({"query"}),
        required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
        plan_factory=bad_factory,
    )
    registry = SkillRegistry.from_specs((spec,), tools=_local_tools())
    catalog = SkillCatalog(active=registry, disabled=())
    planner = SkillAwareIntentPlanner(catalog=catalog, fallback=IntentPlanner())
    with pytest.raises(InvalidSkillPlanError, match="NoneType"):
        planner.make_plan(_parsed(IntentName.WEB_SEARCH, query="q"))


def test_non_step_item_rejected():
    def bad_factory(inputs: Mapping[str, Any]) -> list[Step]:  # type: ignore[return-value]
        return ["not_a_step"]  # type: ignore[return-value]

    spec = SkillSpec(
        name=SkillName.WEB_SEARCH, description="bad",
        applicable_intents=frozenset({IntentName.WEB_SEARCH}),
        required_inputs=frozenset({"query"}),
        required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
        plan_factory=bad_factory,
    )
    registry = SkillRegistry.from_specs((spec,), tools=_local_tools())
    catalog = SkillCatalog(active=registry, disabled=())
    planner = SkillAwareIntentPlanner(catalog=catalog, fallback=IntentPlanner())
    with pytest.raises(InvalidSkillPlanError, match="Step"):
        planner.make_plan(_parsed(IntentName.WEB_SEARCH, query="q"))


def test_undeclared_tool_action_rejected():
    def bad_factory(inputs: Mapping[str, Any]) -> list[Step]:
        return [Step("bad", ToolName.CALCULATE, {"expression": "1"})]

    spec = SkillSpec(
        name=SkillName.WEB_SEARCH, description="bad",
        applicable_intents=frozenset({IntentName.WEB_SEARCH}),
        required_inputs=frozenset({"query"}),
        required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
        plan_factory=bad_factory,
    )
    registry = SkillRegistry.from_specs((spec,), tools=_local_tools())
    catalog = SkillCatalog(active=registry, disabled=())
    planner = SkillAwareIntentPlanner(catalog=catalog, fallback=IntentPlanner())
    with pytest.raises(InvalidSkillPlanError, match="required_tools"):
        planner.make_plan(_parsed(IntentName.WEB_SEARCH, query="q"))


def test_fresh_plan_returned_on_repeated_calls():
    planner = _build_local_planner()
    parsed = _parsed(IntentName.WEB_SEARCH, query="q")
    a = planner.make_plan(parsed)
    b = planner.make_plan(parsed)
    assert a is not b
    assert _plan_signature(a) == _plan_signature(b)


# ---------------------------------------------------------------------------
# AC-14 RuntimeAgent class unchanged
# ---------------------------------------------------------------------------

def test_all_production_factories_use_skill_aware_planner():
    from agent_core.runtime.runtime_agent import build_local_agent, build_test_agent
    agent_local, _ = build_local_agent()
    agent_test = build_test_agent()
    for agent in (agent_local, agent_test):
        assert isinstance(agent.planner, RuleBasedPlanner)
        assert isinstance(agent.planner.intent_planner, SkillAwareIntentPlanner)


def test_skill_aware_planner_uses_catalog_not_registry_directly():
    catalog = build_skill_catalog(tools=_local_tools())
    planner = SkillAwareIntentPlanner(catalog=catalog, fallback=IntentPlanner())
    assert hasattr(planner, "_catalog")
    assert isinstance(planner._catalog, SkillCatalog)


def test_runtime_agent_class_unchanged():
    from agent_core.runtime.runtime_agent import RuntimeAgent
    import inspect
    sig = inspect.signature(RuntimeAgent.__init__)
    params = list(sig.parameters)
    assert "planner" in params
    assert "tools" in params
    assert "memory_client" in params
    assert "skill_registry" not in params
    assert "skill_catalog" not in params


# ---------------------------------------------------------------------------
# Non-skill regression parity
# ---------------------------------------------------------------------------

def test_clarification_plan_unchanged():
    planner = build_rule_based_planner(tools=_local_tools())
    state = AgentState(goal="Tính giúp tôi")
    steps = planner.make_plan(state)
    assert len(steps) == 1
    assert steps[0].action == ToolName.FINISH
    assert "biểu thức" in steps[0].args["answer"]


def test_calculate_only_plan_unchanged():
    planner = build_rule_based_planner(tools=_local_tools())
    state = AgentState(goal="Tính (15 + 5) * 3 nhưng không lưu ghi chú")
    steps = planner.make_plan(state)
    assert [s.action for s in steps] == [ToolName.CALCULATE, ToolName.FINISH]


def test_read_note_plan_unchanged():
    planner = build_rule_based_planner(tools=_local_tools())
    state = AgentState(goal="Đọc ghi chú budget")
    steps = planner.make_plan(state)
    assert [s.action for s in steps] == [ToolName.READ_NOTE, ToolName.FINISH]


def test_write_note_plan_unchanged():
    planner = build_rule_based_planner(tools=_local_tools())
    state = AgentState(goal="Lưu ghi chú budget với nội dung test nội dung")
    steps = planner.make_plan(state)
    assert steps[0].action == ToolName.WRITE_NOTE


def test_unknown_plan_unchanged():
    planner = build_rule_based_planner(tools=_local_tools())
    state = AgentState(goal="abc xyz không rõ")
    steps = planner.make_plan(state)
    assert len(steps) == 1
    assert steps[0].action == ToolName.FINISH


def test_web_search_then_save_note_remains_unsupported():
    planner_direct = _build_local_planner()
    steps = planner_direct.make_plan(
        _parsed(IntentName.WEB_SEARCH_THEN_SAVE_NOTE, query="q")
    )
    assert len(steps) == 1
    assert steps[0].action == ToolName.FINISH


# ---------------------------------------------------------------------------
# AC-16 Backend safety / composition
# ---------------------------------------------------------------------------

def test_m6_local_composition_still_builds():
    from agent_core.runtime.runtime_agent import build_local_agent
    agent, store = build_local_agent()
    assert agent is not None and store is not None


def test_remote_active_skill_does_not_use_write_note():
    catalog = build_skill_catalog(tools=_remote_tools())
    for spec in catalog.active.values():
        assert ToolName.WRITE_NOTE not in spec.required_tools


def test_remote_active_skill_does_not_use_read_note():
    catalog = build_skill_catalog(tools=_remote_tools())
    for spec in catalog.active.values():
        assert ToolName.READ_NOTE not in spec.required_tools


def test_produced_plans_pass_plan_validator():
    from agent_core.planning.plan_validator import validate_plan
    tools = _local_tools()
    planner = build_rule_based_planner(tools=tools)
    for goal in [
        f"Tính {_EXPR} rồi lưu vào ghi chú {_NOTE}",
        f"Đọc ghi chú {_NOTE} rồi tóm tắt",
        "Tìm thông tin về Ducati",
    ]:
        validate_plan(planner.make_plan(AgentState(goal=goal)), tools)


# ---------------------------------------------------------------------------
# AC-13 Skills are stateless / slot-only
# ---------------------------------------------------------------------------

def test_plan_factory_receives_only_required_inputs():
    """Factory receives only required_inputs fields, not full ParsedIntent."""
    received: list[dict] = []

    def capturing_factory(inputs: Mapping[str, Any]) -> list[Step]:
        received.append(dict(inputs))
        return [
            Step("s1", ToolName.WEB_SEARCH, {"query": inputs["query"], "max_results": 3}),
            Step("s2", ToolName.FINISH, {"answer": "$last_text"}),
        ]

    spec = SkillSpec(
        name=SkillName.WEB_SEARCH, description="capturing",
        applicable_intents=frozenset({IntentName.WEB_SEARCH}),
        required_inputs=frozenset({"query"}),
        required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
        plan_factory=capturing_factory,
    )
    registry = SkillRegistry.from_specs((spec,), tools=_local_tools())
    catalog = SkillCatalog(active=registry, disabled=())
    planner = SkillAwareIntentPlanner(catalog=catalog, fallback=IntentPlanner())
    planner.make_plan(_parsed(IntentName.WEB_SEARCH, query="test"))

    assert len(received) == 1
    assert set(received[0].keys()) == {"query"}  # only required_inputs
    assert received[0]["query"] == "test"


def test_runtime_path_calculate_save_uses_skill():
    from agent_core.runtime.runtime_agent import build_test_agent
    agent = build_test_agent()
    state = AgentState(goal=f"Tính {_EXPR} rồi lưu vào ghi chú {_NOTE}")
    agent.run(state)
    assert state.done
    assert any(s.action == ToolName.WRITE_NOTE for s in state.plan)


def test_runtime_path_web_search_uses_skill():
    from agent_core.runtime.runtime_agent import build_test_agent
    agent = build_test_agent()
    state = AgentState(goal="Tìm thông tin về Ducati Monster 795")
    agent.run(state)
    assert any(s.action == ToolName.WEB_SEARCH for s in state.plan)

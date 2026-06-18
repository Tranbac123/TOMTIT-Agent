"""EX2 — SkillAwareIntentPlanner routing, parity, fallback and regression tests."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_core.planning.intent_planner import IntentPlanner
from agent_core.planning.intents import IntentName, ParsedIntent
from agent_core.planning.rule_based_planner import RuleBasedPlanner, build_rule_based_planner
from agent_core.planning.skill_aware_intent_planner import SkillAwareIntentPlanner
from agent_core.skills.base import SkillSpec
from agent_core.skills.errors import InvalidSkillPlanError
from agent_core.skills.registry import SkillRegistry, build_skill_registry
from agent_core.state.agent_state import AgentState, Step
from agent_core.state.enums import SkillName, ToolName
from agent_core.tools.builtin_tools import FakeWebSearchClient
from agent_core.tools.registry import build_tool_registry


# ---------------------------------------------------------------------------
# Pre-EX2 "golden" plans — captured from production planner BEFORE shadow
# removal.  These are the exact Step sequences the planner used to produce.
# ---------------------------------------------------------------------------

_NOTE = "budget"
_EXPR = "(15+5)*3"
_QUERY = "thông tin về Ducati Monster 795"


def _golden_calculate_save(expr: str = _EXPR, note: str = _NOTE) -> list[tuple]:
    """(action, args) pairs from pre-EX2 _calculate_then_save_note_plan."""
    return [
        (ToolName.CALCULATE,  {"expression": expr}),
        (ToolName.WRITE_NOTE, {"name": note, "content": "$last_text"}),
        (ToolName.FINISH,     {"answer": f"Đã tính xong và lưu vào ghi chú '{note}'. Kết quả: ${{slot.calc_result}}"}),
    ]


def _golden_read_summarize(note: str = _NOTE) -> list[tuple]:
    """(action, args) pairs from pre-EX2 _read_note_then_summarize_plan."""
    return [
        (ToolName.READ_NOTE, {"name": note}),
        (ToolName.SUMMARIZE, {"text": "$last.output.content"}),
        (ToolName.FINISH,    {"answer": "Tóm tắt: ${last.output.summary}"}),
    ]


def _golden_web_search(query: str = _QUERY) -> list[tuple]:
    """(action, args) pairs from pre-EX2 _web_search_plan."""
    return [
        (ToolName.WEB_SEARCH, {"query": query, "max_results": 3}),
        (ToolName.FINISH,     {"answer": "$last_text"}),
    ]


def _plan_signature(steps: list[Step]) -> list[tuple]:
    return [(s.action, s.args) for s in steps]


def _local_tools():
    return build_tool_registry(FakeWebSearchClient())


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


def _build_planner(tools=None) -> SkillAwareIntentPlanner:
    t = tools or _local_tools()
    return SkillAwareIntentPlanner(
        skills=build_skill_registry(tools=t),
        fallback=IntentPlanner(),
        tools=t,
    )


# ---------------------------------------------------------------------------
# §14.4 Plan parity
# ---------------------------------------------------------------------------

def test_calculate_save_parity_via_skill_aware():
    planner = _build_planner()
    parsed = _parsed(
        IntentName.CALCULATE_THEN_SAVE_NOTE,
        expression=_EXPR,
        note_name=_NOTE,
    )
    steps = planner.make_plan(parsed)
    assert _plan_signature(steps) == _golden_calculate_save()


def test_read_summarize_parity_via_skill_aware():
    planner = _build_planner()
    parsed = _parsed(IntentName.READ_NOTE_THEN_SUMMARIZE, note_name=_NOTE)
    steps = planner.make_plan(parsed)
    assert _plan_signature(steps) == _golden_read_summarize()


def test_web_search_parity_via_skill_aware():
    planner = _build_planner()
    parsed = _parsed(IntentName.WEB_SEARCH, query=_QUERY)
    steps = planner.make_plan(parsed)
    assert _plan_signature(steps) == _golden_web_search()


def test_web_search_max_results_exactly_3():
    planner = _build_planner()
    parsed = _parsed(IntentName.WEB_SEARCH, query="test")
    steps = planner.make_plan(parsed)
    assert steps[0].action == ToolName.WEB_SEARCH
    assert steps[0].args["max_results"] == 3


def test_calculate_save_step_order_preserved():
    steps = _build_planner().make_plan(
        _parsed(IntentName.CALCULATE_THEN_SAVE_NOTE, expression=_EXPR, note_name=_NOTE)
    )
    assert [s.action for s in steps] == [ToolName.CALCULATE, ToolName.WRITE_NOTE, ToolName.FINISH]


def test_read_summarize_step_order_preserved():
    steps = _build_planner().make_plan(
        _parsed(IntentName.READ_NOTE_THEN_SUMMARIZE, note_name=_NOTE)
    )
    assert [s.action for s in steps] == [ToolName.READ_NOTE, ToolName.SUMMARIZE, ToolName.FINISH]


def test_finish_step_preserved_calculate_save():
    steps = _build_planner().make_plan(
        _parsed(IntentName.CALCULATE_THEN_SAVE_NOTE, expression=_EXPR, note_name=_NOTE)
    )
    finish = steps[-1]
    assert finish.action == ToolName.FINISH
    assert _NOTE in finish.args["answer"]
    assert "${slot.calc_result}" in finish.args["answer"]


def test_parity_via_full_rule_based_planner():
    """End-to-end: RuleBasedPlanner → SkillAwareIntentPlanner → skill."""
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
# §14.5 SkillAwareIntentPlanner routing
# ---------------------------------------------------------------------------

def test_mapped_calculate_save_calls_skill():
    skills = build_skill_registry(tools=_local_tools())
    fallback = MagicMock(spec=IntentPlanner)
    planner = SkillAwareIntentPlanner(
        skills=skills, fallback=fallback, tools=_local_tools()
    )
    parsed = _parsed(
        IntentName.CALCULATE_THEN_SAVE_NOTE, expression="1+1", note_name="n"
    )
    steps = planner.make_plan(parsed)
    fallback.make_plan.assert_not_called()
    assert steps[0].action == ToolName.CALCULATE


def test_mapped_read_summarize_calls_skill():
    skills = build_skill_registry(tools=_local_tools())
    fallback = MagicMock(spec=IntentPlanner)
    planner = SkillAwareIntentPlanner(
        skills=skills, fallback=fallback, tools=_local_tools()
    )
    parsed = _parsed(IntentName.READ_NOTE_THEN_SUMMARIZE, note_name="n")
    steps = planner.make_plan(parsed)
    fallback.make_plan.assert_not_called()
    assert steps[0].action == ToolName.READ_NOTE


def test_mapped_web_search_calls_skill():
    skills = build_skill_registry(tools=_local_tools())
    fallback = MagicMock(spec=IntentPlanner)
    planner = SkillAwareIntentPlanner(
        skills=skills, fallback=fallback, tools=_local_tools()
    )
    parsed = _parsed(IntentName.WEB_SEARCH, query="q")
    steps = planner.make_plan(parsed)
    fallback.make_plan.assert_not_called()
    assert steps[0].action == ToolName.WEB_SEARCH


def test_fallback_not_called_for_mapped_intent():
    skills = build_skill_registry(tools=_local_tools())
    fallback = MagicMock(spec=IntentPlanner)
    planner = SkillAwareIntentPlanner(
        skills=skills, fallback=fallback, tools=_local_tools()
    )
    planner.make_plan(_parsed(IntentName.WEB_SEARCH, query="q"))
    fallback.make_plan.assert_not_called()


def test_fallback_called_for_unmapped_intent():
    skills = build_skill_registry(tools=_local_tools())
    fallback = MagicMock(spec=IntentPlanner)
    fallback.make_plan.return_value = [Step("done", ToolName.FINISH, {"answer": "ok"})]
    planner = SkillAwareIntentPlanner(
        skills=skills, fallback=fallback, tools=_local_tools()
    )
    planner.make_plan(_parsed(IntentName.CALCULATE, expression="1+1"))
    fallback.make_plan.assert_called_once()


def test_missing_slots_delegates_to_fallback_before_skill_dispatch():
    """v1.1 change 3: missing_slots check is BEFORE skill dispatch."""
    skills = build_skill_registry(tools=_local_tools())
    fallback = MagicMock(spec=IntentPlanner)
    fallback.make_plan.return_value = [Step("clarify", ToolName.FINISH, {"answer": "?"})]
    planner = SkillAwareIntentPlanner(
        skills=skills, fallback=fallback, tools=_local_tools()
    )
    # WEB_SEARCH is a registered skill, but missing_slots is non-empty
    parsed = _parsed(IntentName.WEB_SEARCH, missing_slots=("query",))
    planner.make_plan(parsed)
    fallback.make_plan.assert_called_once()


def test_registered_skill_failure_does_not_silently_fall_back():
    """§9.5: InvalidSkillPlanError on bad plan — no silent fallback."""
    from collections.abc import Mapping as AbcMapping
    tools = _local_tools()

    def bad_factory(slots: AbcMapping) -> list[Step]:
        return []  # empty plan — forbidden

    from agent_core.planning.intents import IntentName as IN
    spec = SkillSpec(
        name=SkillName.WEB_SEARCH,
        description="bad",
        supported_intents=frozenset({IntentName.WEB_SEARCH}),
        required_inputs=frozenset({"query"}),
        required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
        plan_factory=bad_factory,
    )
    registry = SkillRegistry.from_specs((spec,), tools=tools)
    fallback = MagicMock(spec=IntentPlanner)
    planner = SkillAwareIntentPlanner(skills=registry, fallback=fallback, tools=tools)

    with pytest.raises(InvalidSkillPlanError, match="empty"):
        planner.make_plan(_parsed(IntentName.WEB_SEARCH, query="q"))
    fallback.make_plan.assert_not_called()


def test_non_list_skill_output_rejected():
    tools = _local_tools()

    def bad_factory(slots) -> list[Step]:  # type: ignore[return-value]
        return None  # type: ignore[return-value]

    spec = SkillSpec(
        name=SkillName.WEB_SEARCH,
        description="bad",
        supported_intents=frozenset({IntentName.WEB_SEARCH}),
        required_inputs=frozenset({"query"}),
        required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
        plan_factory=bad_factory,
    )
    registry = SkillRegistry.from_specs((spec,), tools=tools)
    planner = SkillAwareIntentPlanner(
        skills=registry, fallback=IntentPlanner(), tools=tools
    )
    with pytest.raises(InvalidSkillPlanError, match="NoneType"):
        planner.make_plan(_parsed(IntentName.WEB_SEARCH, query="q"))


def test_non_step_item_rejected():
    tools = _local_tools()

    def bad_factory(slots) -> list[Step]:  # type: ignore[return-value]
        return ["not_a_step"]  # type: ignore[return-value]

    spec = SkillSpec(
        name=SkillName.WEB_SEARCH,
        description="bad",
        supported_intents=frozenset({IntentName.WEB_SEARCH}),
        required_inputs=frozenset({"query"}),
        required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
        plan_factory=bad_factory,
    )
    registry = SkillRegistry.from_specs((spec,), tools=tools)
    planner = SkillAwareIntentPlanner(
        skills=registry, fallback=IntentPlanner(), tools=tools
    )
    with pytest.raises(InvalidSkillPlanError, match="Step"):
        planner.make_plan(_parsed(IntentName.WEB_SEARCH, query="q"))


def test_undeclared_tool_action_rejected():
    tools = _local_tools()

    def bad_factory(slots) -> list[Step]:
        # Emits a tool NOT in required_tools
        return [Step("bad", ToolName.CALCULATE, {"expression": "1"})]

    spec = SkillSpec(
        name=SkillName.WEB_SEARCH,
        description="bad",
        supported_intents=frozenset({IntentName.WEB_SEARCH}),
        required_inputs=frozenset({"query"}),
        required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
        plan_factory=bad_factory,
    )
    registry = SkillRegistry.from_specs((spec,), tools=tools)
    planner = SkillAwareIntentPlanner(
        skills=registry, fallback=IntentPlanner(), tools=tools
    )
    with pytest.raises(InvalidSkillPlanError, match="required_tools"):
        planner.make_plan(_parsed(IntentName.WEB_SEARCH, query="q"))


def test_fresh_plan_returned_on_repeated_calls():
    planner = _build_planner()
    parsed = _parsed(IntentName.WEB_SEARCH, query="q")
    a = planner.make_plan(parsed)
    b = planner.make_plan(parsed)
    assert a is not b
    assert _plan_signature(a) == _plan_signature(b)


# ---------------------------------------------------------------------------
# §14.6 Non-skill regression parity
# ---------------------------------------------------------------------------

def test_clarification_plan_unchanged():
    planner = build_rule_based_planner(tools=_local_tools())
    state = AgentState(goal="Tính giúp tôi")  # missing expression
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
    """WEB_SEARCH_THEN_SAVE_NOTE must not produce a skill plan."""
    planner = build_rule_based_planner(tools=_local_tools())
    # The intent exists in IntentName but has no skill and no planner branch
    parsed = _parsed(IntentName.WEB_SEARCH_THEN_SAVE_NOTE, query="q")
    planner_direct = _build_planner()
    steps = planner_direct.make_plan(parsed)
    # Must fall to unknown plan (FINISH with unknown message)
    assert len(steps) == 1
    assert steps[0].action == ToolName.FINISH


# ---------------------------------------------------------------------------
# §14.7 Composition
# ---------------------------------------------------------------------------

def test_all_production_factories_use_skill_aware_planner():
    """build_local_agent and build_test_agent use build_rule_based_planner."""
    from agent_core.runtime.runtime_agent import build_local_agent, build_test_agent
    agent_local, _ = build_local_agent()
    agent_test = build_test_agent()
    for agent in (agent_local, agent_test):
        planner = agent.planner
        assert isinstance(planner, RuleBasedPlanner)
        assert isinstance(planner.intent_planner, SkillAwareIntentPlanner)


def test_runtime_agent_class_unchanged():
    """RuntimeAgent.__init__ signature and core methods must not have changed."""
    from agent_core.runtime.runtime_agent import RuntimeAgent
    import inspect
    sig = inspect.signature(RuntimeAgent.__init__)
    params = list(sig.parameters)
    # Core params still present; SkillRegistry not injected into RuntimeAgent
    assert "planner" in params
    assert "tools" in params
    assert "memory_client" in params
    assert "skill_registry" not in params


# ---------------------------------------------------------------------------
# §14.8 Runtime integration
# ---------------------------------------------------------------------------

def test_calculate_save_skill_selected_in_production_path():
    from agent_core.runtime.runtime_agent import build_test_agent
    agent = build_test_agent()
    state = AgentState(goal=f"Tính {_EXPR} rồi lưu vào ghi chú {_NOTE}")
    agent.run(state)
    assert state.done
    # Plan was built via skill (not shadow IntentPlanner branch)
    assert any(s.action == ToolName.WRITE_NOTE for s in state.plan)


def test_web_search_skill_selected_in_production_path():
    from agent_core.runtime.runtime_agent import build_test_agent
    agent = build_test_agent()
    state = AgentState(goal="Tìm thông tin về Ducati Monster 795")
    agent.run(state)
    assert any(s.action == ToolName.WEB_SEARCH for s in state.plan)


def test_produced_plans_pass_plan_validator():
    from agent_core.planning.plan_validator import validate_plan
    tools = _local_tools()
    planner = build_rule_based_planner(tools=tools)
    for goal, intent_args in [
        (f"Tính {_EXPR} rồi lưu vào ghi chú {_NOTE}", {}),
        (f"Đọc ghi chú {_NOTE} rồi tóm tắt", {}),
        ("Tìm thông tin về Ducati", {}),
    ]:
        state = AgentState(goal=goal)
        steps = planner.make_plan(state)
        validate_plan(steps, tools)  # must not raise


def test_m6_local_composition_still_builds():
    from agent_core.runtime.runtime_agent import build_local_agent
    agent, store = build_local_agent()
    assert agent is not None
    assert store is not None

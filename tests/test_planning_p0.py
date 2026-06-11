from __future__ import annotations

from agent_core.planning.intent_parser import RuleBasedIntentParser
from agent_core.planning.intents import IntentName
from agent_core.planning.rule_based_planner import RuleBasedPlanner
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import ToolName


def test_parse_calculate():
    parsed = RuleBasedIntentParser().parse("Tính (15 + 5) * 3")

    assert parsed.intent == IntentName.CALCULATE
    assert parsed.expression == "(15+5)*3"


def test_parse_calculate_then_save_note():
    parsed = RuleBasedIntentParser().parse(
        "Tính (15 + 5) * 3 rồi lưu vào ghi chú budget"
    )

    assert parsed.intent == IntentName.CALCULATE_THEN_SAVE_NOTE
    assert parsed.expression == "(15+5)*3"
    assert parsed.note_name == "budget"


def test_parse_read_note_then_summarize():
    parsed = RuleBasedIntentParser().parse("Đọc ghi chú project rồi tóm tắt")

    assert parsed.intent == IntentName.READ_NOTE_THEN_SUMMARIZE
    assert parsed.note_name == "project"


def test_parse_web_search():
    parsed = RuleBasedIntentParser().parse("Tìm thông tin về Ducati Monster 795")

    assert parsed.intent == IntentName.WEB_SEARCH
    assert parsed.query == "thông tin về Ducati Monster 795"


def test_missing_expression_returns_clarification_plan():
    plan = RuleBasedPlanner().make_plan(AgentState(goal="Tính giúp tôi"))

    assert len(plan) == 1
    assert plan[0].action == ToolName.FINISH
    assert "biểu thức" in plan[0].args["answer"]


def test_missing_note_name_returns_clarification_plan():
    plan = RuleBasedPlanner().make_plan(
        AgentState(goal="Tính (15 + 5) * 3 rồi lưu vào ghi chú")
    )

    assert len(plan) == 1
    assert plan[0].action == ToolName.FINISH
    assert "ghi chú" in plan[0].args["answer"]


def test_calculate_then_save_note_plan():
    plan = RuleBasedPlanner().make_plan(
        AgentState(goal="Tính (15 + 5) * 3 rồi lưu vào ghi chú budget")
    )

    assert [step.action for step in plan] == [
        ToolName.CALCULATE,
        ToolName.WRITE_NOTE,
        ToolName.FINISH,
    ]
    assert plan[0].args["expression"] == "(15+5)*3"
    assert plan[1].args["name"] == "budget"
    assert plan[1].args["content"] == "$last_text"


def test_unknown_returns_safe_finish():
    plan = RuleBasedPlanner().make_plan(AgentState(goal="abc xyz không rõ"))

    assert len(plan) == 1
    assert plan[0].action == ToolName.FINISH

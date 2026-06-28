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


# ---------------------------------------------------------------------------
# B.8 — English calculate trigger
# ---------------------------------------------------------------------------

def test_parse_english_calculate():
    parsed = RuleBasedIntentParser().parse("calculate 2 + 2")

    assert parsed.intent == IntentName.CALCULATE
    assert parsed.expression == "2+2"


def test_parse_calc_shorthand():
    parsed = RuleBasedIntentParser().parse("calc 3 * 4")

    assert parsed.intent == IntentName.CALCULATE
    assert parsed.expression == "3*4"


def test_parse_calc_case_insensitive():
    parsed = RuleBasedIntentParser().parse("Calculate 10 / 2")

    assert parsed.intent == IntentName.CALCULATE
    assert parsed.expression == "10/2"


# ---------------------------------------------------------------------------
# B.8 — Bare math trigger
# ---------------------------------------------------------------------------

def test_parse_bare_math_with_trailing_equals():
    parsed = RuleBasedIntentParser().parse("1 + 1 =")

    assert parsed.intent == IntentName.CALCULATE
    assert parsed.expression == "1+1"


def test_parse_bare_math_simple():
    parsed = RuleBasedIntentParser().parse("1 + 1")

    assert parsed.intent == IntentName.CALCULATE
    assert parsed.expression == "1+1"


def test_parse_bare_math_parentheses():
    parsed = RuleBasedIntentParser().parse("(4 + 5) / 3")

    assert parsed.intent == IntentName.CALCULATE
    assert parsed.expression == "(4+5)/3"


# ---------------------------------------------------------------------------
# B.8 — Vietnamese natural math suffix
# ---------------------------------------------------------------------------

def test_parse_viet_math_bang_may():
    parsed = RuleBasedIntentParser().parse("1 + 1 bằng mấy")

    assert parsed.intent == IntentName.CALCULATE
    assert parsed.expression == "1+1"


def test_parse_viet_math_bang_bao_nhieu():
    parsed = RuleBasedIntentParser().parse("1 + 1 bằng bao nhiêu")

    assert parsed.intent == IntentName.CALCULATE
    assert parsed.expression == "1+1"


def test_parse_viet_math_la_bao_nhieu():
    parsed = RuleBasedIntentParser().parse("2 * 3 là bao nhiêu")

    assert parsed.intent == IntentName.CALCULATE
    assert parsed.expression == "2*3"


# ---------------------------------------------------------------------------
# B.8 — Existing Vietnamese calculate regression guard
# ---------------------------------------------------------------------------

def test_parse_viet_tinh_still_works():
    parsed = RuleBasedIntentParser().parse("Tính 1 + 1")

    assert parsed.intent == IntentName.CALCULATE
    assert parsed.expression == "1+1"


def test_parse_viet_tinh_lowercase_still_works():
    parsed = RuleBasedIntentParser().parse("tính 2 * 3")

    assert parsed.intent == IntentName.CALCULATE
    assert parsed.expression == "2*3"


# ---------------------------------------------------------------------------
# B.8 — Greeting handling
# ---------------------------------------------------------------------------

def test_parse_greeting_hi():
    parsed = RuleBasedIntentParser().parse("hi")

    assert parsed.intent == IntentName.GREETING


def test_parse_greeting_hello():
    parsed = RuleBasedIntentParser().parse("hello")

    assert parsed.intent == IntentName.GREETING


def test_parse_greeting_xin_chao():
    parsed = RuleBasedIntentParser().parse("xin chào")

    assert parsed.intent == IntentName.GREETING


def test_parse_greeting_chao():
    parsed = RuleBasedIntentParser().parse("chào")

    assert parsed.intent == IntentName.GREETING


def test_greeting_plan_is_finish_with_helpful_text():
    plan = RuleBasedPlanner().make_plan(AgentState(goal="hi"))

    assert len(plan) == 1
    assert plan[0].action == ToolName.FINISH
    assert "TomTit" in plan[0].args["answer"]


# ---------------------------------------------------------------------------
# B.8 — Improved UNKNOWN fallback message
# ---------------------------------------------------------------------------

def test_unknown_fallback_message_is_helpful():
    plan = RuleBasedPlanner().make_plan(AgentState(goal="random unsupported request"))

    assert plan[0].action == ToolName.FINISH
    answer = plan[0].args["answer"]
    assert "Tính" in answer or "calculate" in answer


# ---------------------------------------------------------------------------
# B.8 — End-to-end planner steps
# ---------------------------------------------------------------------------

def test_planner_english_calculate_steps():
    plan = RuleBasedPlanner().make_plan(AgentState(goal="calculate 2 + 2"))

    assert [s.action for s in plan] == [ToolName.CALCULATE, ToolName.FINISH]
    assert plan[0].args["expression"] == "2+2"


def test_planner_bare_math_steps():
    plan = RuleBasedPlanner().make_plan(AgentState(goal="1 + 1 ="))

    assert [s.action for s in plan] == [ToolName.CALCULATE, ToolName.FINISH]
    assert plan[0].args["expression"] == "1+1"

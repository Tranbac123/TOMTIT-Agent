from agent_core import RuleBasedPlanner, AgentState, ToolName


def test_planner_keeps_negated_save_as_calculate_only():
    plan = RuleBasedPlanner().make_plan(AgentState(goal="Tính (15 + 5) * 3 nhưng không lưu ghi chú"))

    assert [step.action for step in plan] == [ToolName.CALCULATE, ToolName.FINISH]


def test_planner_search_goal():
    plan = RuleBasedPlanner().make_plan(AgentState(goal="tìm thông tin về Ducati Monster 795"))

    assert plan[0].action == ToolName.WEB_SEARCH
    assert plan[0].args["query"] == "thông tin về Ducati Monster 795"


def test_missing_expression_returns_clarification_plan():
    planner = RuleBasedPlanner()
    state = AgentState(goal="tính giúp tôi")

    plan = planner.make_plan(state)

    assert len(plan) == 1
    assert plan[0].action == ToolName.FINISH
    assert "biểu thức" in plan[0].args["answer"]
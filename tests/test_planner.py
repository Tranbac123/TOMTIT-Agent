from agent_core import RuleBasedPlanner, AgentState, ToolName


def test_planner_keeps_negated_save_as_calculate_only():
    plan = RuleBasedPlanner().make_plan(AgentState(goal="Tính (15 + 5) * 3 nhưng không lưu ghi chú"))

    assert [step.action for step in plan] == [ToolName.CALCULATE, ToolName.FINISH]


def test_planner_search_goal():
    plan = RuleBasedPlanner().make_plan(AgentState(goal="tìm thông tin về Ducati Monster 795"))

    assert plan[0].action == ToolName.WEB_SEARCH
    assert plan[0].args["query"] == "thông tin về Ducati Monster 795"

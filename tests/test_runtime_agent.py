from agent_core import AgentState, AgentStatus, FakeWebSearchClient, RuleBasedPlanner, RuntimeAgent, build_tool_registry


def build_agent() -> RuntimeAgent:
    return RuntimeAgent(planner=RuleBasedPlanner(), tools=build_tool_registry(FakeWebSearchClient()))


def test_agent_calculate_write_note_finish():
    result = build_agent().run(AgentState(goal="Tính (15 + 5) * 3 rồi lưu vào ghi chú budget"))

    assert result.status == AgentStatus.COMPLETED
    assert result.memory.read_note("budget") == "60.0"
    assert "60.0" in (result.final_answer or "")


def test_agent_calculate_without_save_when_negated():
    result = build_agent().run(AgentState(goal="Tính (15 + 5) * 3 nhưng không lưu ghi chú"))

    assert result.status == AgentStatus.COMPLETED
    assert result.memory.list_notes() == []
    assert "60.0" in (result.final_answer or "")


def test_agent_read_note_summarize_finish():
    state = AgentState(goal="Đọc ghi chú project rồi tóm tắt")
    state.memory.write_note("project", "Agent state-first cần runtime rõ ràng. Tool phải trả ToolResult thống nhất. Planner không nên hard-code quá nhiều.")

    result = build_agent().run(state)

    assert result.status == AgentStatus.COMPLETED
    assert (result.final_answer or "").startswith("Tóm tắt:")


def test_agent_web_search_finish():
    result = build_agent().run(AgentState(goal="tìm thông tin về Ducati Monster 795"))

    assert result.status == AgentStatus.COMPLETED
    assert "Ducati Monster 795" in (result.final_answer or "")
    assert len(result.sources) == 1

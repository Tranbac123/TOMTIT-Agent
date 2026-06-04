from agent_core import AgentState, ToolName, build_tool_registry


def test_calculate_tool():
    tools = build_tool_registry()
    result = tools[ToolName.CALCULATE].fn(state=AgentState(goal="x"), expression="(15 + 5) * 2")

    assert result.success
    assert result.output.value == 60.0


def test_write_and_read_note_tools():
    state = AgentState(goal="x")
    tools = build_tool_registry()

    written = tools[ToolName.WRITE_NOTE].fn(state=state, name="budget", content="60.0")
    read = tools[ToolName.READ_NOTE].fn(state=state, name="budget")

    assert written.success
    assert read.success
    assert read.output.content == "60.0"


def test_summarize_tool():
    tools = build_tool_registry()
    result = tools[ToolName.SUMMARIZE].fn(state=AgentState(goal="x"), text="A. B. C.")

    assert result.success
    assert result.output.summary == "A. B"

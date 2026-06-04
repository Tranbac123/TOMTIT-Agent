from agent_core import AgentState, ArgResolver, CalculateOutput, ReadNoteOutput, ToolResult


def test_resolve_last_output_value():
    state = AgentState(goal="test")
    state.last_result = ToolResult(success=True, output=CalculateOutput(expression="1 + 2", value=3))

    assert ArgResolver().resolve_value("$last.output.value", state) == 3


def test_resolve_last_output_content():
    state = AgentState(goal="test")
    state.last_result = ToolResult(success=True, output=ReadNoteOutput(name="project", content="hello world"))

    assert ArgResolver().resolve_value("$last.output.content", state) == "hello world"


def test_resolve_template_slot():
    state = AgentState(goal="test")
    state.set_slot("calc_result", 60)

    assert ArgResolver().resolve_value("Kết quả là ${slot.calc_result}", state) == "Kết quả là 60"

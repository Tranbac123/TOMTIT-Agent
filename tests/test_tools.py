from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from agent_core import AgentState, ToolName, build_tool_registry
from agent_core.state.enums import RiskLevel
from agent_core.tools.arg_resolver import ArgResolver
from agent_core.tools.executor import ToolExecutor


def make_step(action: ToolName, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(action=action, args=args, status=None)


def make_executor(tools: dict[ToolName, Any]) -> ToolExecutor:
    return ToolExecutor(tools=tools, resolver=ArgResolver())


def test_calculate_tool():
    tools = build_tool_registry()

    result = tools[ToolName.CALCULATE].fn(
        state=AgentState(goal="x"),
        expression="(15 + 5) * 3",
    )

    assert result.success
    assert result.output.value == 60.0


def test_write_and_read_note_tools():
    state = AgentState(goal="x")
    tools = build_tool_registry()

    written = tools[ToolName.WRITE_NOTE].fn(
        state=state,
        name="budget",
        content="60.0",
    )
    read = tools[ToolName.READ_NOTE].fn(
        state=state,
        name="budget",
    )

    assert written.success
    assert read.success
    assert read.output.content == "60.0"


def test_summarize_tool():
    tools = build_tool_registry()

    result = tools[ToolName.SUMMARIZE].fn(
        state=AgentState(goal="x"),
        text="A. B. C.",
    )

    assert result.success
    assert result.output.summary == "A. B"


def test_executor_runs_low_risk_tool():
    state = AgentState(goal="x")
    tools = build_tool_registry()
    executor = make_executor(tools)

    step = make_step(
        ToolName.CALCULATE,
        {"expression": "(15 + 5) * 3"},
    )

    result = executor.execute(step, state)

    assert result.success
    assert result.output.value == 60.0
    assert state.last_result is result


def test_executor_blocks_tool_when_policy_denies():
    state = AgentState(goal="x")
    tools = dict(build_tool_registry())

    tools[ToolName.CALCULATE] = replace(
        tools[ToolName.CALCULATE],
        risk_level=RiskLevel.HIGH,
    )

    executor = make_executor(tools)
    step = make_step(
        ToolName.CALCULATE,
        {"expression": "(15 + 5) * 3"},
    )

    result = executor.execute(step, state)

    assert not result.success
    assert result.metadata["error_type"] == "PolicyDenied"
    assert state.last_result is result


def test_executor_blocks_tool_when_approval_required():
    state = AgentState(goal="x")
    tools = dict(build_tool_registry())

    tools[ToolName.CALCULATE] = replace(
        tools[ToolName.CALCULATE],
        requires_approval=True,
    )

    executor = make_executor(tools)
    step = make_step(
        ToolName.CALCULATE,
        {"expression": "(15 + 5) * 3"},
    )

    result = executor.execute(step, state)

    assert not result.success
    assert result.metadata["error_type"] == "ApprovalRequired"
    assert state.last_result is result


def test_executor_runs_approval_required_tool_when_approved():
    state = AgentState(goal="x")
    state.approved_tools = {ToolName.CALCULATE}

    tools = dict(build_tool_registry())
    tools[ToolName.CALCULATE] = replace(
        tools[ToolName.CALCULATE],
        requires_approval=True,
    )

    executor = make_executor(tools)
    step = make_step(
        ToolName.CALCULATE,
        {"expression": "(15 + 5) * 3"},
    )

    result = executor.execute(step, state)

    assert result.success
    assert result.output.value == 60.0
    assert state.last_result is result


def test_executor_rejects_unknown_args():
    state = AgentState(goal="x")
    tools = build_tool_registry()
    executor = make_executor(tools)

    step = make_step(
        ToolName.CALCULATE,
        {
            "expression": "1 + 1",
            "unexpected": "bad",
        },
    )

    result = executor.execute(step, state)

    assert not result.success
    assert result.metadata["error_type"] in {"InvalidToolArgs", "ValueError"}
    assert state.last_result is result


def test_executor_rejects_missing_required_args():
    state = AgentState(goal="x")
    tools = build_tool_registry()
    executor = make_executor(tools)

    step = make_step(
        ToolName.CALCULATE,
        {},
    )

    result = executor.execute(step, state)

    assert not result.success
    assert result.metadata["error_type"] in {"InvalidToolArgs", "ValueError"}
    assert state.last_result is result
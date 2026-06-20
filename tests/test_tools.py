from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from agent_core import AgentState, ToolName, build_tool_registry
from agent_core.state.enums import RiskLevel, SourceType, TrustLevel
from agent_core.tools.arg_resolver import ArgResolver
from agent_core.tools.executor import ToolExecutor


def make_step(action: ToolName, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(action=action, args=args, status=None, id=str(uuid4()))


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
    # P5: arg/schema failure records observation with full SF1 contract
    obs = _last_obs(state)
    assert obs.source_type is SourceType.TOOL
    assert obs.trust_level is TrustLevel.UNTRUSTED_EVIDENCE
    assert obs.source_ref == f"task:{state.task_id}/step:{step.id}/tool:calculate"


def test_executor_blocks_critical_risk_tool():
    """CRITICAL risk must be denied — fn must never execute (spy call_count = 0)."""
    call_count = 0

    def spy_fn(**_):
        nonlocal call_count
        call_count += 1
        from agent_core.tools.schemas import ToolResult, ToolResultKind
        return ToolResult(success=True, output=None, tool_name="calculate", kind=ToolResultKind.TEXT)

    state = AgentState(goal="x")
    tools = dict(build_tool_registry())
    tools[ToolName.CALCULATE] = replace(
        tools[ToolName.CALCULATE],
        fn=spy_fn,
        risk_level=RiskLevel.CRITICAL,
    )

    executor = make_executor(tools)
    step = make_step(ToolName.CALCULATE, {"expression": "1+1"})

    result = executor.execute(step, state)

    assert not result.success
    assert result.metadata["error_type"] == "PolicyDenied"
    assert call_count == 0  # fn must NOT have run


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


# ---------------------------------------------------------------------------
# P1–P9 observation path tests (SF1)
# ---------------------------------------------------------------------------

def _last_obs(state: AgentState):
    return state.observations[-1]


def test_p1_invalid_action_observation():
    """P1: invalid action type → observation with TOOL source, UNTRUSTED_EVIDENCE."""
    state = AgentState(goal="x")
    step = SimpleNamespace(action="not_a_toolname", args={}, status=None, id=str(uuid4()))
    executor = ToolExecutor(tools=build_tool_registry(), resolver=ArgResolver())

    result = executor.execute(step, state)

    assert not result.success
    obs = _last_obs(state)
    assert obs.source_type is SourceType.TOOL
    assert obs.trust_level is TrustLevel.UNTRUSTED_EVIDENCE
    assert obs.source_ref is not None


def test_p2_unknown_tool_observation():
    """P2: known ToolName but not in registry → observation recorded."""
    state = AgentState(goal="x")
    executor = ToolExecutor(tools={}, resolver=ArgResolver())
    step = make_step(ToolName.CALCULATE, {})

    result = executor.execute(step, state)

    assert not result.success
    obs = _last_obs(state)
    assert obs.source_type is SourceType.TOOL
    assert obs.trust_level is TrustLevel.UNTRUSTED_EVIDENCE
    assert obs.source_ref is not None


def test_p3_policy_denied_observation():
    """P3: policy denied → observation with TOOL source."""
    from agent_core.state.enums import RiskLevel
    from dataclasses import replace as dc_replace

    state = AgentState(goal="x")
    tools = dict(build_tool_registry())
    tools[ToolName.CALCULATE] = dc_replace(tools[ToolName.CALCULATE], risk_level=RiskLevel.CRITICAL)
    executor = make_executor(tools)
    step = make_step(ToolName.CALCULATE, {"expression": "1+1"})

    result = executor.execute(step, state)

    assert not result.success
    obs = _last_obs(state)
    assert obs.source_type is SourceType.TOOL
    assert obs.trust_level is TrustLevel.UNTRUSTED_EVIDENCE
    assert obs.source_ref is not None


def test_p4_approval_required_observation():
    """P4: approval required and not given → observation with exact source_ref."""
    from dataclasses import replace as dc_replace

    state = AgentState(goal="x")
    tools = dict(build_tool_registry())
    tools[ToolName.CALCULATE] = dc_replace(tools[ToolName.CALCULATE], requires_approval=True)
    executor = make_executor(tools)
    step = make_step(ToolName.CALCULATE, {"expression": "1+1"})

    result = executor.execute(step, state)

    assert not result.success
    assert result.metadata["error_type"] == "ApprovalRequired"
    obs = _last_obs(state)
    assert obs.source_type is SourceType.TOOL
    assert obs.trust_level is TrustLevel.UNTRUSTED_EVIDENCE
    assert obs.source_ref == f"task:{state.task_id}/step:{step.id}/tool:calculate"


def test_p9_success_observation():
    """P9: successful execution → observation with correct source_ref."""
    state = AgentState(goal="x")
    tools = build_tool_registry()
    executor = make_executor(tools)
    step = make_step(ToolName.CALCULATE, {"expression": "2+2"})

    result = executor.execute(step, state)

    assert result.success
    obs = _last_obs(state)
    assert obs.success is True
    assert obs.source_type is SourceType.TOOL
    assert obs.trust_level is TrustLevel.UNTRUSTED_EVIDENCE
    assert obs.source_ref.startswith("task:")
    assert "/step:" in obs.source_ref
    assert "/tool:calculate" in obs.source_ref
    assert state.task_id in obs.source_ref
    assert step.id in obs.source_ref


def test_observation_source_ref_contains_step_id():
    """source_ref embeds the step.id of the executing step."""
    state = AgentState(goal="x")
    tools = build_tool_registry()
    executor = make_executor(tools)
    step = make_step(ToolName.CALCULATE, {"expression": "1+1"})

    executor.execute(step, state)

    obs = _last_obs(state)
    assert step.id in obs.source_ref


def test_p6_unexpected_resolve_exception_observation():
    """P6: unexpected exception from resolve boundary → observation with exact source_ref."""

    class _FailResolver:
        def resolve_args(self, args: dict, state: Any) -> dict:
            raise RuntimeError("injected resolve failure")

    state = AgentState(goal="x")
    tools = build_tool_registry()
    executor = ToolExecutor(tools=tools, resolver=_FailResolver())
    step = make_step(ToolName.CALCULATE, {"expression": "1+1"})

    result = executor.execute(step, state)

    assert not result.success
    assert result.metadata["error_type"] == "RuntimeError"
    obs = _last_obs(state)
    assert obs.source_type is SourceType.TOOL
    assert obs.trust_level is TrustLevel.UNTRUSTED_EVIDENCE
    assert obs.source_ref == f"task:{state.task_id}/step:{step.id}/tool:calculate"


def test_p7_tool_fn_exception_observation():
    """P7: tool.fn raises → observation recorded with exact source_ref."""

    def _crashing_fn(**_: Any) -> Any:
        raise RuntimeError("tool function crashed")

    state = AgentState(goal="x")
    tools = dict(build_tool_registry())
    tools[ToolName.CALCULATE] = replace(tools[ToolName.CALCULATE], fn=_crashing_fn)
    executor = make_executor(tools)
    step = make_step(ToolName.CALCULATE, {"expression": "1+1"})

    result = executor.execute(step, state)

    assert not result.success
    assert result.metadata["error_type"] == "RuntimeError"
    assert result.metadata.get("unexpected") is True
    obs = _last_obs(state)
    assert obs.source_type is SourceType.TOOL
    assert obs.trust_level is TrustLevel.UNTRUSTED_EVIDENCE
    assert obs.source_ref == f"task:{state.task_id}/step:{step.id}/tool:calculate"


def test_p8_invalid_tool_result_observation():
    """P8: tool.fn returns non-ToolResult → observation recorded with exact source_ref."""

    def _invalid_fn(**_: Any) -> Any:
        return "not a ToolResult"

    state = AgentState(goal="x")
    tools = dict(build_tool_registry())
    tools[ToolName.CALCULATE] = replace(tools[ToolName.CALCULATE], fn=_invalid_fn)
    executor = make_executor(tools)
    step = make_step(ToolName.CALCULATE, {"expression": "1+1"})

    result = executor.execute(step, state)

    assert not result.success
    assert result.metadata["error_type"] == "InvalidToolResult"
    obs = _last_obs(state)
    assert obs.source_type is SourceType.TOOL
    assert obs.trust_level is TrustLevel.UNTRUSTED_EVIDENCE
    assert obs.source_ref == f"task:{state.task_id}/step:{step.id}/tool:calculate"
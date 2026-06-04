from __future__ import annotations

from typing import Any

from agent_core.output.final_composer import DefaultFinalComposer, FinalComposer
from agent_core.planning.plan_validator import validate_plan
from agent_core.planning.rule_based_planner import RuleBasedPlanner
from agent_core.safety.policy import DefaultPolicyEngine, PolicyEngine
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus, ToolName
from agent_core.tools.arg_resolver import ArgResolver, stringify_output
from agent_core.tools.base import ToolSpec
from agent_core.tools.executor import ToolExecutor


class RuntimeAgent:
    def __init__(
        self,
        planner: Any,
        tools: dict[ToolName, ToolSpec],
        executor: ToolExecutor | None = None,
        policy: PolicyEngine | None = None,
        final_composer: FinalComposer | None = None,
        debug: bool = False,
    ):
        self.planner = planner
        self.tools = tools
        self.debug = debug
        self.executor = executor or ToolExecutor(tools=tools, resolver=ArgResolver())
        self.policy = policy or DefaultPolicyEngine()
        self.final_composer = final_composer or DefaultFinalComposer()

    def run(self, state: AgentState) -> AgentState:
        state.status = AgentStatus.PLANNING
        try:
            state.plan = self.planner.make_plan(state)
            validate_plan(state.plan, self.tools)
        except Exception as exc:
            state.fail(f"Plan validation failed: {exc}")
            return state

        state.status = AgentStatus.RUNNING
        state.history.append(f"Goal: {state.goal}")
        state.history.append(f"Plan length: {len(state.plan)}")

        for i, step in enumerate(state.plan, start=1):
            if state.done:
                break
            if i > state.max_steps:
                state.fail(f"Max steps exceeded: {state.max_steps}")
                break
            state.current_step = i
            state.history.append(f"[Step {i}] thought={step.thought}")
            state.history.append(f"[Step {i}] action={step.action.value}")

            tool = self.tools[step.action]
            if not self.policy.allow(step, tool):
                state.fail(f"Tool requires approval: {step.action.value}")
                break

            result = self.executor.execute(step, state)
            if not result.success:
                state.fail(f"Tool error: {result.error}")
                break

            state.history.append(f"[Step {i}] output={stringify_output(result)}")
            if step.action == ToolName.FINISH:
                state.complete(stringify_output(result))

        if not state.done:
            state.complete(self.final_composer.compose(state))
        return state


def build_test_agent() -> RuntimeAgent:
    from agent_core.tools.builtin_tools import FakeWebSearchClient, build_tool_registry

    return RuntimeAgent(planner=RuleBasedPlanner(), tools=build_tool_registry(FakeWebSearchClient()))

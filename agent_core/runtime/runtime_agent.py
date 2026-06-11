from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_core.output.final_composer import DefaultFinalComposer, FinalComposer
from agent_core.planning.plan_validator import validate_plan
from agent_core.planning.rule_based_planner import RuleBasedPlanner
from agent_core.runtime.lifecycle import RuntimeLifecycle
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus, ToolName
from agent_core.tools.arg_resolver import ArgResolver, stringify_output
from agent_core.tools.base import ToolSpec
from agent_core.tools.executor import ToolExecutor


class RuntimeAgent:
    def __init__(
        self,
        planner: Any,
        tools: Mapping[ToolName, ToolSpec],
        executor: ToolExecutor | None = None,
        final_composer: FinalComposer | None = None,
        lifecycle: RuntimeLifecycle | None = None,
        debug: bool = False,
    ):
        self.planner = planner
        self.tools = tools
        self.debug = debug
        self.executor = executor or ToolExecutor(
            tools=tools,
            resolver=ArgResolver(),
        )
        self.final_composer = final_composer or DefaultFinalComposer()
        self.lifecycle = lifecycle or RuntimeLifecycle()

    def run(self, state: AgentState) -> AgentState:
        self._plan(state)

        if state.is_terminal():
            return state

        self._execute_plan(state)

        if not state.done:
            self._complete_with_final_composer(state)

        return state

    def _plan(self, state: AgentState) -> None:
        state.status = AgentStatus.PLANNING
        self.lifecycle.emit_event(state, "planning_started")

        try:
            state.plan = self.planner.make_plan(state)
            validate_plan(state.plan, self.tools)
        except Exception as exc:
            state.fail(f"Plan validation failed: {exc}")
            self.lifecycle.emit_event(
                state,
                "planning_failed",
                metadata={"error": str(exc)},
            )
            return

        state.history.append(f"Goal: {state.goal}")
        state.history.append(f"Plan length: {len(state.plan)}")
        self.lifecycle.emit_event(
            state,
            "planning_completed",
            metadata={"plan_length": len(state.plan)},
        )

    def _execute_plan(self, state: AgentState) -> None:
        state.status = AgentStatus.RUNNING
        self.lifecycle.emit_event(state, "running_started")

        for step_index, step in enumerate(state.plan, start=1):
            if state.is_terminal():
                break

            if step_index > state.max_steps:
                state.fail(f"Max steps exceeded: {state.max_steps}")
                self.lifecycle.emit_event(
                    state,
                    "run_failed",
                    step_index=step_index,
                    metadata={"reason": "max_steps_exceeded"},
                )
                break

            state.current_step = step_index
            state.history.append(f"[Step {step_index}] thought={step.thought}")
            state.history.append(f"[Step {step_index}] action={step.action.value}")

            self.lifecycle.emit_event(
                state,
                "step_started",
                step_index=step_index,
                metadata={
                    "step_id": step.id,
                    "action": step.action.value,
                },
            )

            result = self.executor.execute(step, state)

            if result.success:
                state.history.append(
                    f"[Step {step_index}] output={stringify_output(result)}"
                )
                self.lifecycle.emit_event(
                    state,
                    "step_completed",
                    step_index=step_index,
                    metadata={
                        "step_id": step.id,
                        "action": step.action.value,
                        "tool_name": result.tool_name,
                    },
                )
            else:
                state.fail(f"Tool error: {result.error}")
                self.lifecycle.emit_event(
                    state,
                    "step_failed",
                    step_index=step_index,
                    metadata={
                        "step_id": step.id,
                        "action": step.action.value,
                        "tool_name": result.tool_name,
                        "error": result.error,
                        "error_type": result.metadata.get("error_type"),
                    },
                )
                break

            if step.action == ToolName.FINISH:
                state.complete(stringify_output(result))
                self.lifecycle.emit_event(
                    state,
                    "run_completed",
                    step_index=step_index,
                    metadata={"reason": "finish_tool"},
                )
                break

    def _complete_with_final_composer(self, state: AgentState) -> None:
        answer = self.final_composer.compose(state)
        state.complete(answer)
        self.lifecycle.emit_event(
            state,
            "run_completed",
            metadata={"reason": "final_composer"},
        )


def build_test_agent() -> RuntimeAgent:
    from agent_core.tools.builtin_tools import FakeWebSearchClient
    from agent_core.tools.registry import build_tool_registry

    return RuntimeAgent(
        planner=RuleBasedPlanner(),
        tools=build_tool_registry(FakeWebSearchClient()),
    )
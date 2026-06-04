from __future__ import annotations

from typing import Any

from agent_core.state.enums import StepStatus, ToolName, ToolResultKind
from agent_core.state.observation import Observation
from agent_core.tools.arg_resolver import ArgResolver
from agent_core.tools.base import ToolSpec
from agent_core.tools.schemas import CalculateOutput, ToolResult


class ToolExecutor:
    def __init__(self, tools: dict[ToolName, ToolSpec], resolver: ArgResolver):
        self.tools = tools
        self.resolver = resolver

    def execute(self, step: Any, state: Any) -> ToolResult:
        tool_name = step.action
        if tool_name not in self.tools:
            return self._error(tool_name, f"Unknown tool: {tool_name.value}", "UnknownTool")

        tool = self.tools[tool_name]
        step.status = StepStatus.RUNNING
        try:
            resolved_args = self.resolver.resolve_args(step.args, state)
            final_args = self._validate_args(tool, resolved_args)
            result = tool.fn(state=state, **final_args)
            if not isinstance(result, ToolResult):
                return self._error(
                    tool_name,
                    f"Tool '{tool_name.value}' returned invalid result type",
                    "InvalidToolResult",
                    {"actual_type": type(result).__name__, "raw_args": step.args},
                )
            if not result.tool_name:
                result.tool_name = tool_name.value
            state.last_result = result
            if tool_name == ToolName.CALCULATE and isinstance(result.output, CalculateOutput):
                state.set_slot("calc_result", result.output.value)
            state.add_observation(
                Observation(
                    step_index=state.current_step,
                    action=tool_name.value,
                    args=final_args,
                    success=result.success,
                    output=result.output,
                    error=result.error,
                    sources=result.sources,
                )
            )
            step.status = StepStatus.COMPLETED if result.success else StepStatus.FAILED
            return result
        except Exception as exc:
            step.status = StepStatus.FAILED
            return self._error(
                tool_name,
                f"Tool '{tool_name.value}' crashed: {exc}",
                type(exc).__name__,
                {"raw_args": step.args, "unexpected": True},
            )

    def _validate_args(self, tool: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
        if getattr(tool, "args_schema", None) is None:
            return args
        validated_args = tool.args_schema.model_validate(args)
        return validated_args.model_dump()

    def _error(
        self,
        tool_name: ToolName,
        message: str,
        error_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        return ToolResult(
            success=False,
            error=message,
            tool_name=tool_name.value,
            kind=ToolResultKind.JSON,
            metadata={"error_type": error_type, **(metadata or {})},
        )

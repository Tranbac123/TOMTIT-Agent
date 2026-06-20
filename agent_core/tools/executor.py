from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from agent_core.safety.evidence import tool_observation_ref
from agent_core.state.enums import SourceType, StepStatus, ToolName, ToolResultKind, TrustLevel
from agent_core.state.observation import Observation
from agent_core.tools.arg_resolver import ArgResolver
from agent_core.tools.base import ToolSpec
from agent_core.tools.schemas import CalculateOutput, ToolResult
from agent_core.safety.approval import ApprovalGate
from agent_core.safety.policy import PolicyEngine

class ToolArgsError(ValueError):
    pass

class ToolExecutor:
    def __init__(
        self,
        tools: Mapping[ToolName, ToolSpec],
        resolver: ArgResolver,
        policy_engine: PolicyEngine | None = None,
        approval_gate: ApprovalGate | None = None,
    ):
        self.tools = tools
        self.resolver = resolver
        self.policy_engine = policy_engine or PolicyEngine()
        self.approval_gate = approval_gate or ApprovalGate()

    def execute(self, step: Any, state: Any) -> ToolResult:
        tool_name = step.action

        if not isinstance(tool_name, ToolName):
            return self._fail(
                step=step,
                state=state,
                tool_name=str(tool_name),
                message=f"Invalid tool action: {tool_name}",
                error_type="InvalidToolAction",
                metadata={"raw_action": str(tool_name)},
            )

        tool = self.tools.get(tool_name)
        if tool is None:
            return self._fail(
                step=step,
                state=state,
                tool_name=tool_name,
                message=f"Unknown tool: {tool_name.value}",
                error_type="UnknownTool",
            )

        step.status = StepStatus.RUNNING

        try:
            resolved_args = self.resolver.resolve_args(step.args, state)
            final_args = self._validate_args(tool, resolved_args)
            policy_decision = self.policy_engine.check(
                tool=tool,
                args=final_args,
                state=state,
            )
            if not policy_decision.allowed:
                return self._fail(
                    step=step,
                    state=state,
                    tool_name=tool_name,
                    message=policy_decision.reason,
                    error_type="PolicyDenied",
                    metadata={
                        **policy_decision.metadata,
                        "resolved_args": final_args,
                    }
                )

            approval_decision = self.approval_gate.check(
                tool=tool,
                args=final_args,
                state=state,
            )
            if not approval_decision.approved:
                return self._fail(
                    step=step,
                    state=state,
                    tool_name=tool_name,
                    message=approval_decision.reason,
                    error_type="ApprovalRequired",
                    metadata={
                        **approval_decision.metadata,
                        "resolved_args": final_args,
                    }
                )
        except (ValidationError, ToolArgsError) as exc:
            metadata: dict[str, Any] = {"raw_args": step.args}

            if isinstance(exc, ValidationError):
                metadata["validation_errors"] = exc.errors()

            return self._fail(
                step=step,
                state=state,
                tool_name=tool_name,
                message=f"Invalid args for tool '{tool_name.value}': {exc}",
                error_type="InvalidToolArgs",
                metadata=metadata,
            )
        except Exception as exc:
            return self._fail(
                step=step,
                state=state,
                tool_name=tool_name,
                message=f"Failed to resolve or validate args for tool '{tool_name.value}': {exc}",
                error_type=type(exc).__name__,
                metadata={"raw_args": step.args},
            )

        try:
            result = tool.fn(state=state, **final_args)
        except Exception as exc:
            return self._fail(
                step=step,
                state=state,
                tool_name=tool_name,
                message=f"Tool '{tool_name.value}' crashed: {exc}",
                error_type=type(exc).__name__,
                metadata={
                    "raw_args": step.args,
                    "resolved_args": final_args,
                    "unexpected": True,
                },
            )

        if not isinstance(result, ToolResult):
            return self._fail(
                step=step,
                state=state,
                tool_name=tool_name,
                message=f"Tool '{tool_name.value}' returned invalid result type.",
                error_type="InvalidToolResult",
                metadata={
                    "actual_type": type(result).__name__,
                    "raw_args": step.args,
                    "resolved_args": final_args,
                },
            )

        if not result.tool_name:
            result.tool_name = tool_name.value

        if tool_name == ToolName.CALCULATE and isinstance(result.output, CalculateOutput):
            state.set_slot("calc_result", result.output.value)

        step.status = StepStatus.COMPLETED if result.success else StepStatus.FAILED
        self._record_result(
            state=state,
            step=step,
            tool_name=tool_name,
            args=final_args,
            result=result,
        )
        return result

    def _validate_args(self, tool: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
        unknown_args = set(args) - set(tool.allowed_args)
        if unknown_args:
            raise ToolArgsError(
                f"Unknown args for tool '{tool.name.value}': {sorted(unknown_args)}"
            )

        missing_args = set(tool.required_args) - set(args)
        if missing_args:
            raise ToolArgsError(
                f"Missing required args for tool '{tool.name.value}': {sorted(missing_args)}"
            )

        if tool.args_schema is None:
            return args

        validated_args = tool.args_schema.model_validate(args)
        return validated_args.model_dump()

    def _fail(
        self,
        *,
        step: Any,
        state: Any,
        tool_name: ToolName | str,
        message: str,
        error_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        step.status = StepStatus.FAILED

        result = self._error(
            tool_name=tool_name,
            message=message,
            error_type=error_type,
            metadata=metadata,
        )

        self._record_result(
            state=state,
            step=step,
            tool_name=tool_name,
            args=metadata.get("resolved_args", {}) if metadata else {},
            result=result,
        )
        return result

    def _record_result(
        self,
        *,
        state: Any,
        step: Any,
        tool_name: ToolName | str,
        args: dict[str, Any],
        result: ToolResult,
    ) -> None:
        canonical = self._canonical_tool_name(tool_name)

        state.last_result = result
        state.add_observation(
            Observation(
                step_index=state.current_step,
                action=canonical,
                args=args,
                success=result.success,
                trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
                source_type=SourceType.TOOL,
                source_ref=tool_observation_ref(
                    task_id=state.task_id,
                    step_id=step.id,
                    tool_name=canonical,
                ),
                output=result.output,
                error=result.error,
                sources=result.sources,
            )
        )

    def _error(
        self,
        tool_name: ToolName | str,
        message: str,
        error_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        return ToolResult(
            success=False,
            error=message,
            tool_name=self._tool_name_value(tool_name),
            kind=ToolResultKind.JSON,
            metadata={"error_type": error_type, **(metadata or {})},
        )

    def _canonical_tool_name(self, tool_name: ToolName | str) -> str:
        if isinstance(tool_name, ToolName):
            return tool_name.value
        stripped = tool_name.strip()
        if not stripped:
            raise ValueError("tool_name must be a non-blank string")
        return stripped

    def _tool_name_value(self, tool_name: ToolName | str) -> str:
        if isinstance(tool_name, ToolName):
            return tool_name.value
        return tool_name
from __future__ import annotations

from agent_core.state.agent_state import Step
from agent_core.state.enums import ToolName
from agent_core.tools.base import ToolSpec


def validate_plan(plan: list[Step], tools: dict[ToolName, ToolSpec]) -> None:
    available = set(tools.keys())
    for i, step in enumerate(plan, start=1):
        if step.action not in available:
            raise ValueError(
                f"Invalid action at step {i}: {step.action}. "
                f"Available tools: {[tool.value for tool in sorted(available, key=lambda x: x.value)]}"
            )
        spec = tools[step.action]
        provided_args = set(step.args.keys())
        missing_args = spec.required_args - provided_args
        unknown_args = provided_args - spec.allowed_args
        if missing_args:
            raise ValueError(f"Missing required args at step {i} for action {step.action}: {sorted(missing_args)}")
        if unknown_args:
            raise ValueError(f"Unknown args at step {i} for action {step.action}: {sorted(unknown_args)}")

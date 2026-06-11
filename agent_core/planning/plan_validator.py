from __future__ import annotations

from collections.abc import Mapping

from agent_core.state.agent_state import Step
from agent_core.state.enums import ToolName
from agent_core.tools.base import ToolSpec


def validate_plan(
    plan: list[Step],
    tools: Mapping[ToolName, ToolSpec],
) -> None:
    if not plan:
        raise ValueError("Plan cannot be empty.")

    available = set(tools.keys())
    step_ids: set[str] = set()

    for index, step in enumerate(plan, start=1):
        if not isinstance(step, Step):
            raise ValueError(f"Invalid step at index {index}: expected Step.")

        if step.id in step_ids:
            raise ValueError(f"Duplicate step id at step {index}: {step.id}")
        step_ids.add(step.id)

        if step.action not in available:
            raise ValueError(
                f"Invalid action at step {index}: {step.action}. "
                f"Available tools: "
                f"{[tool.value for tool in sorted(available, key=lambda x: x.value)]}"
            )

        unknown_dependencies = set(step.depends_on) - step_ids
        if unknown_dependencies:
            raise ValueError(
                f"Invalid depends_on at step {index}: "
                f"{sorted(unknown_dependencies)}"
            )

        spec = tools[step.action]
        provided_args = set(step.args.keys())
        missing_args = spec.required_args - provided_args
        unknown_args = provided_args - spec.allowed_args

        if missing_args:
            raise ValueError(
                f"Missing required args at step {index} "
                f"for action {step.action}: {sorted(missing_args)}"
            )

        if unknown_args:
            raise ValueError(
                f"Unknown args at step {index} "
                f"for action {step.action}: {sorted(unknown_args)}"
            )
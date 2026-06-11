from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.tools.base import ToolSpec


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    required: bool = False
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def approved_now(cls) -> ApprovalDecision:
        return cls(approved=True)

    @classmethod
    def required_approval(
        cls,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalDecision:
        return cls(
            approved=False,
            required=True,
            reason=reason,
            metadata=metadata or {},
        )


class ApprovalGate:
    def check(
        self,
        *,
        tool: ToolSpec,
        args: dict[str, Any],
        state: Any,
    ) -> ApprovalDecision:
        if not tool.requires_approval:
            return ApprovalDecision.approved_now()

        approved_tools = getattr(state, "approved_tools", set())
        approved_tool_names = {
            item.value if hasattr(item, "value") else str(item)
            for item in approved_tools
        }

        if tool.name.value in approved_tool_names:
            return ApprovalDecision.approved_now()

        return ApprovalDecision.required_approval(
            reason=f"Tool '{tool.name.value}' requires user approval before execution.",
            metadata={
                "tool": tool.name.value,
                "args": args,
            },
        )
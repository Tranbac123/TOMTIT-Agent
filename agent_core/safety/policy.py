from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.state.enums import RiskLevel
from agent_core.tools.base import ToolSpec


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allow(cls) -> PolicyDecision:
        return cls(allowed=True)

    @classmethod
    def deny(
        cls,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        return cls(
            allowed=False,
            reason=reason,
            metadata=metadata or {},
        )


class PolicyEngine:
    def check(
        self,
        *,
        tool: ToolSpec,
        args: dict[str, Any],
        state: Any,
    ) -> PolicyDecision:
        if tool.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            return PolicyDecision.deny(
                reason=f"Tool '{tool.name.value}' is high risk and blocked by MVP policy.",
                metadata={
                    "tool": tool.name.value,
                    "risk_level": tool.risk_level.value,
                },
            )

        if tool.mutates_state and getattr(state, "read_only", False):
            return PolicyDecision.deny(
                reason=f"Tool '{tool.name.value}' mutates state but current run is read-only.",
                metadata={
                    "tool": tool.name.value,
                    "mutates_state": tool.mutates_state,
                },
            )

        return PolicyDecision.allow()
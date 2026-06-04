from __future__ import annotations

from typing import Protocol

from agent_core.state.agent_state import Step
from agent_core.tools.base import ToolSpec


class PolicyEngine(Protocol):
    def allow(self, step: Step, tool: ToolSpec) -> bool: ...


class DefaultPolicyEngine:
    def allow(self, step: Step, tool: ToolSpec) -> bool:
        return not tool.requires_approval

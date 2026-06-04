from __future__ import annotations

from dataclasses import dataclass, field

from agent_core.state.enums import ToolName
from agent_core.tools.base import ToolSpec


@dataclass
class ToolRegistry:
    tools: dict[ToolName, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        self.tools[spec.name] = spec

    def get(self, name: ToolName) -> ToolSpec | None:
        return self.tools.get(name)

    def all(self) -> dict[ToolName, ToolSpec]:
        return dict(self.tools)

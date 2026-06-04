from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from agent_core.state.enums import RiskLevel, ToolName
from agent_core.tools.schemas import ToolResult


ToolFn = Callable[..., ToolResult]


@dataclass
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 0.0


@dataclass
class ToolSpec:
    name: ToolName
    fn: ToolFn
    description: str
    required_args: set[str]
    allowed_args: set[str]
    mutates_state: bool = False
    risk_level: RiskLevel = RiskLevel.LOW
    side_effects: list[str] = field(default_factory=list)
    requires_approval: bool = False
    timeout_seconds: float | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    args_schema: type | None = None


class ToolRegistryProtocol(Protocol):
    def get(self, name: ToolName) -> ToolSpec | None: ...
    def all(self) -> dict[ToolName, ToolSpec]: ...


class ToolExecutorProtocol(Protocol):
    def execute(self, step: Any, state: Any) -> ToolResult: ...

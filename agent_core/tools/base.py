from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_core.state.enums import RiskLevel, ToolName
from agent_core.tools.schemas import ToolResult


ToolFn = Callable[..., ToolResult]
# production:
# ToolFn = Callable[[dict[str, Any], Any], ToolResult]


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("RetryPolicy.max_attempts must be >= 1.")

        if self.backoff_seconds < 0:
            raise ValueError("RetryPolicy.backoff_seconds must be >= 0.")


@dataclass(frozen=True)
class ToolSpec:
    name: ToolName
    fn: ToolFn
    description: str
    required_args: frozenset[str] | set[str]
    allowed_args: frozenset[str] | set[str]
    mutates_state: bool = False
    risk_level: RiskLevel = RiskLevel.LOW
    side_effects: tuple[str, ...] | list[str] = field(default_factory=tuple)
    requires_approval: bool = False
    timeout_seconds: float | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    idempotent: bool = True
    args_schema: type | None = None

    def __post_init__(self) -> None:
        required_args = frozenset(self.required_args)
        allowed_args = frozenset(self.allowed_args)
        side_effects = tuple(self.side_effects)

        missing_allowed_args = required_args - allowed_args
        if missing_allowed_args:
            raise ValueError(
                f"Tool {self.name.value} has required args not present in allowed_args: "
                f"{sorted(missing_allowed_args)}"
            )

        if self.mutates_state and not side_effects:
            raise ValueError(
                f"Tool {self.name.value} mutates state but has no side_effects metadata."
            )

        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError(
                f"Tool {self.name.value} timeout_seconds must be > 0 when provided."
            )

        if not self.idempotent and self.retry_policy.max_attempts > 1:
            raise ValueError(
                f"Tool {self.name.value} is not idempotent and cannot use retry max_attempts > 1."
            )

        object.__setattr__(self, "required_args", required_args)
        object.__setattr__(self, "allowed_args", allowed_args)
        object.__setattr__(self, "side_effects", side_effects)


class ToolRegistryProtocol(Protocol):
    def get(self, name: ToolName) -> ToolSpec | None: ...

    def all(self) -> Mapping[ToolName, ToolSpec]: ...


class ToolExecutorProtocol(Protocol):
    def execute(self, step: Any, state: Any) -> ToolResult: ...
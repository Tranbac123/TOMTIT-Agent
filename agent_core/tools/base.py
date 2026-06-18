from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from agent_core.state.enums import RiskLevel, ToolName
from agent_core.tools.schemas import ToolResult


ToolFn = Callable[..., ToolResult]


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
    args_schema: type[BaseModel] | None = None

    def __post_init__(self) -> None:
        from agent_core.tools.errors import InvalidToolSpecError, UnsupportedToolExecutionPolicyError

        required_args = frozenset(self.required_args)
        allowed_args = frozenset(self.allowed_args)
        side_effects = tuple(self.side_effects)

        # name must be a ToolName enum member
        if not isinstance(self.name, ToolName):
            raise InvalidToolSpecError(
                f"name must be a ToolName enum member, got {type(self.name).__name__!r}"
            )

        name_value = self.name.value

        # fn must be callable
        if not callable(self.fn):
            raise InvalidToolSpecError(f"Tool {name_value!r}: fn must be callable")

        # description must not be blank
        if not self.description.strip():
            raise InvalidToolSpecError(f"Tool {name_value!r}: description must not be blank")

        # required_args must be subset of allowed_args
        missing_allowed = required_args - allowed_args
        if missing_allowed:
            raise InvalidToolSpecError(
                f"Tool {name_value!r}: required_args {sorted(missing_allowed)} "
                f"not present in allowed_args"
            )

        # argument names must not be empty strings
        empty_args = {a for a in allowed_args if not a.strip()}
        if empty_args:
            raise InvalidToolSpecError(
                f"Tool {name_value!r}: argument names must not be empty or whitespace-only"
            )

        # side_effect names must not be empty
        empty_se = {s for s in side_effects if not s.strip()}
        if empty_se:
            raise InvalidToolSpecError(
                f"Tool {name_value!r}: side_effect names must not be empty or whitespace-only"
            )

        # side_effects must not contain duplicates
        if len(side_effects) != len(set(side_effects)):
            raise InvalidToolSpecError(
                f"Tool {name_value!r}: side_effects must not contain duplicates"
            )

        # mutates_state=True requires at least one side effect
        if self.mutates_state and not side_effects:
            raise InvalidToolSpecError(
                f"Tool {name_value!r}: mutates_state=True requires at least one side effect"
            )

        # args_schema is required
        if self.args_schema is None:
            raise InvalidToolSpecError(
                f"Tool {name_value!r}: args_schema must be a Pydantic BaseModel subclass, got None"
            )

        # args_schema must be a BaseModel subclass
        if not (isinstance(self.args_schema, type) and issubclass(self.args_schema, BaseModel)):
            raise InvalidToolSpecError(
                f"Tool {name_value!r}: args_schema must be a subclass of pydantic.BaseModel"
            )

        # schema field names must equal allowed_args
        schema_fields = frozenset(self.args_schema.model_fields.keys())
        if schema_fields != allowed_args:
            raise InvalidToolSpecError(
                f"Tool {name_value!r}: schema fields {sorted(schema_fields)} "
                f"!= allowed_args {sorted(allowed_args)}"
            )

        # schema required fields must equal required_args
        schema_required = frozenset(
            n for n, f in self.args_schema.model_fields.items() if f.is_required()
        )
        if schema_required != required_args:
            raise InvalidToolSpecError(
                f"Tool {name_value!r}: schema required fields {sorted(schema_required)} "
                f"!= required_args {sorted(required_args)}"
            )

        # schema must forbid extra fields
        if self.args_schema.model_config.get("extra") != "forbid":
            raise InvalidToolSpecError(
                f"Tool {name_value!r}: args_schema must have extra='forbid'"
            )

        # schema must use strict validation
        if not self.args_schema.model_config.get("strict", False):
            raise InvalidToolSpecError(
                f"Tool {name_value!r}: args_schema must have strict=True"
            )

        # EX1: timeout not supported — must be None
        if self.timeout_seconds is not None:
            raise UnsupportedToolExecutionPolicyError(
                f"Tool {name_value!r}: timeout_seconds must be None (not supported in EX1, "
                f"got {self.timeout_seconds})"
            )

        # EX1: only default retry (1 attempt, 0 backoff) is supported
        if self.retry_policy.max_attempts != 1 or self.retry_policy.backoff_seconds != 0.0:
            raise UnsupportedToolExecutionPolicyError(
                f"Tool {name_value!r}: retry_policy must be default "
                f"(max_attempts=1, backoff_seconds=0.0); "
                f"got max_attempts={self.retry_policy.max_attempts}, "
                f"backoff_seconds={self.retry_policy.backoff_seconds}"
            )

        object.__setattr__(self, "required_args", required_args)
        object.__setattr__(self, "allowed_args", allowed_args)
        object.__setattr__(self, "side_effects", side_effects)


class ToolExecutorProtocol(Protocol):
    def execute(self, step: Any, state: Any) -> ToolResult: ...

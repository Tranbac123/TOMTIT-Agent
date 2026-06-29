from __future__ import annotations

from pathlib import Path
from typing import Iterable, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


Route = Literal[
    "DIRECT_RESPONSE",
    "CLARIFICATION",
    "RUNTIME",
    "MEMORY_FLOW",
    "LLM_RESPONSE",
    "UNKNOWN_RECOVERABLE",
]

TraceMeaning = Literal[
    "request_received",
    "intent_classified",
    "route_selected",
    "response_generated",
    "state_finalized",
    "planner_called",
    "tool_called",
    "memory_read_called",
    "memory_write_called",
]


class StrictScenarioModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ExpectedSideEffects(StrictScenarioModel):
    planner_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    memory_reads: int = Field(ge=0)
    memory_writes: int = Field(ge=0)


class ExpectedResponse(StrictScenarioModel):
    must_include_any: list[str] = Field(default_factory=list)
    must_not_include_any: list[str] = Field(default_factory=list)


class ExpectedTrace(StrictScenarioModel):
    must_include_meanings: list[TraceMeaning] = Field(default_factory=list)
    must_not_include_meanings: list[TraceMeaning] = Field(default_factory=list)


class ExpectedOutcome(StrictScenarioModel):
    intent: str = Field(min_length=1)
    route: Route
    state_status_any: list[str] | None = None
    side_effects: ExpectedSideEffects
    response: ExpectedResponse
    trace: ExpectedTrace

    @field_validator("intent")
    @classmethod
    def intent_must_be_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("intent must be non-empty")
        return value

    @field_validator("state_status_any")
    @classmethod
    def state_status_any_must_be_non_empty_if_present(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if value is not None and not value:
            raise ValueError("state_status_any must be non-empty if present")
        if value is not None and any(not item.strip() for item in value):
            raise ValueError("state_status_any entries must be non-empty")
        return value


class ScenarioTurn(StrictScenarioModel):
    user: str = Field(min_length=1)
    expect: ExpectedOutcome

    @field_validator("user")
    @classmethod
    def user_must_be_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user must be non-empty")
        return value


class Scenario(StrictScenarioModel):
    id: str = Field(min_length=1)
    description: str | None = None
    turns: list[ScenarioTurn] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def id_must_be_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("id must be non-empty")
        return value


def load_scenario(path: Path) -> Scenario:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Scenario.model_validate(data)


def load_scenarios(paths: Iterable[Path]) -> list[Scenario]:
    return [load_scenario(path) for path in paths]

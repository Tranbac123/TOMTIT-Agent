from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from agent_core.planning.intents import IntentName
from agent_core.skills.errors import InvalidSkillSpecError
from agent_core.state.agent_state import Step
from agent_core.state.enums import SkillName, ToolName


class Skill(Protocol):
    def make_steps(self) -> list[Step]: ...


class SkillPlanFactory(Protocol):
    def __call__(self, slots: Mapping[str, Any]) -> list[Step]: ...


@dataclass(frozen=True)
class SkillSpec:
    name: SkillName
    description: str
    supported_intents: frozenset[IntentName]
    required_inputs: frozenset[str]
    required_tools: frozenset[ToolName]
    plan_factory: SkillPlanFactory

    def __post_init__(self) -> None:
        if not isinstance(self.name, SkillName):
            raise InvalidSkillSpecError(f"name must be SkillName, got {type(self.name)}")
        if not self.description or not self.description.strip():
            raise InvalidSkillSpecError(f"Skill {self.name}: description must not be blank")
        if not self.supported_intents:
            raise InvalidSkillSpecError(f"Skill {self.name}: supported_intents must not be empty")
        for intent in self.supported_intents:
            if not isinstance(intent, IntentName):
                raise InvalidSkillSpecError(
                    f"Skill {self.name}: invalid intent value {intent!r}"
                )
        if not self.required_tools:
            raise InvalidSkillSpecError(f"Skill {self.name}: required_tools must not be empty")
        for tool in self.required_tools:
            if not isinstance(tool, ToolName):
                raise InvalidSkillSpecError(
                    f"Skill {self.name}: invalid tool value {tool!r}"
                )
        if not callable(self.plan_factory):
            raise InvalidSkillSpecError(f"Skill {self.name}: plan_factory must be callable")


@dataclass(frozen=True)
class SkillManifestEntry:
    name: SkillName
    description: str
    supported_intents: tuple[IntentName, ...]
    required_inputs: tuple[str, ...]
    required_tools: tuple[ToolName, ...]

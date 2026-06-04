from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_core.state.agent_state import AgentState, Step


class Planner(Protocol):
    def make_plan(self, state: AgentState) -> list[Step]: ...


@dataclass
class Intent:
    name: str
    confidence: float


class IntentClassifier(Protocol):
    def classify(self, text: str) -> Intent: ...

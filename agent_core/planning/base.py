from __future__ import annotations

from typing import Protocol

from agent_core.planning.intents import ParsedIntent
from agent_core.state.agent_state import AgentState, Step


class IntentParser(Protocol):
    def parse(self, goal: str) -> ParsedIntent: ...


class Planner(Protocol):
    def make_plan(self, state: AgentState) -> list[Step]: ...

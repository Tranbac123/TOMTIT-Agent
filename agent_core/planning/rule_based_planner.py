from __future__ import annotations

from agent_core.planning.intent_parser import RuleBasedIntentParser
from agent_core.planning.intent_planner import IntentPlanner
from agent_core.planning.slot_validator import SlotValidator
from agent_core.state.agent_state import AgentState, Step


class RuleBasedPlanner:
    def __init__(
        self,
        parser: RuleBasedIntentParser | None = None,
        slot_validator: SlotValidator | None = None,
        intent_planner: IntentPlanner | None = None,
    ):
        self.parser = parser or RuleBasedIntentParser()
        self.slot_validator = slot_validator or SlotValidator()
        self.intent_planner = intent_planner or IntentPlanner()

    def make_plan(self, state: AgentState) -> list[Step]:
        parsed = self.parser.parse(state.goal)
        parsed = self.slot_validator.validate(parsed)
        return self.intent_planner.make_plan(parsed)

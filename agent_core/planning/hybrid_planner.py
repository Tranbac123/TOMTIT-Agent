from __future__ import annotations

from agent_core.planning.intent_parser import RuleBasedIntentParser
from agent_core.planning.intent_planner import IntentPlanner
from agent_core.planning.intents import IntentName, ParsedIntent
from agent_core.planning.slot_validator import SlotValidator
from agent_core.state.agent_state import AgentState, Step


class HybridPlanner:
    def __init__(
        self,
        rule_parser: RuleBasedIntentParser | None = None,
        slot_validator: SlotValidator | None = None,
        intent_planner: IntentPlanner | None = None,
        rule_confidence_threshold: float = 0.5,
    ):
        self.rule_parser = rule_parser or RuleBasedIntentParser()
        self.slot_validator = slot_validator or SlotValidator()
        self.intent_planner = intent_planner or IntentPlanner()
        self.rule_confidence_threshold = rule_confidence_threshold

    def make_plan(self, state: AgentState) -> list[Step]:
        parsed = self.rule_parser.parse(state.goal)

        if parsed.confidence < self.rule_confidence_threshold:
            parsed = ParsedIntent(
                intent=IntentName.UNKNOWN,
                confidence=parsed.confidence,
                source=parsed.source,
                raw_text=state.goal,
                missing_slots=("intent",),
                metadata={"reason": "low_rule_confidence"},
            )

        parsed = self.slot_validator.validate(parsed)
        return self.intent_planner.make_plan(parsed)

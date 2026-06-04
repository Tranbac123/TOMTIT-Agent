from __future__ import annotations

from agent_core.planning.rule_based_planner import RuleBasedIntentClassifier, RuleBasedPlanner
from agent_core.state.agent_state import AgentState, Step
from agent_core.state.enums import ToolName


class HybridPlanner:
    def __init__(self, deterministic: RuleBasedPlanner | None = None):
        self.deterministic = deterministic or RuleBasedPlanner()
        self.intent_classifier = RuleBasedIntentClassifier()

    def make_plan(self, state: AgentState) -> list[Step]:
        intent = self.intent_classifier.classify(state.goal)
        if intent.confidence >= 0.5:
            return self.deterministic.make_plan(state)
        return [
            Step(
                thought="Intent chưa đủ rõ; cần clarification hoặc hook LLM planner trong bản sau",
                action=ToolName.FINISH,
                args={"answer": "Tôi cần bạn mô tả rõ hơn mục tiêu cần làm."},
            )
        ]

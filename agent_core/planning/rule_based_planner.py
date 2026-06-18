from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_core.planning.intent_parser import RuleBasedIntentParser
from agent_core.planning.intent_planner import IntentPlanner
from agent_core.planning.slot_validator import SlotValidator
from agent_core.state.agent_state import AgentState, Step
from agent_core.state.enums import ToolName


class RuleBasedPlanner:
    def __init__(
        self,
        parser: RuleBasedIntentParser | None = None,
        slot_validator: SlotValidator | None = None,
        intent_planner: IntentPlanner | None = None,
    ):
        self.parser = parser or RuleBasedIntentParser()
        self.slot_validator = slot_validator or SlotValidator()
        self.intent_planner = intent_planner or _default_skill_aware_intent_planner()

    def make_plan(self, state: AgentState) -> list[Step]:
        parsed = self.parser.parse(state.goal)
        parsed = self.slot_validator.validate(parsed)
        return self.intent_planner.make_plan(parsed)


def build_rule_based_planner(*, tools: Mapping[ToolName, Any]) -> RuleBasedPlanner:
    """Composition helper: wires SkillRegistry → SkillAwareIntentPlanner → RuleBasedPlanner.

    Every production factory must use this helper (EX2 §11.1) so that the
    SkillRegistry is built from the same resolved ToolRegistry as the agent.
    """
    return RuleBasedPlanner(intent_planner=_skill_aware_intent_planner_for_tools(tools))


def _default_skill_aware_intent_planner() -> Any:
    from agent_core.tools.builtin_tools import FakeWebSearchClient
    from agent_core.tools.registry import build_tool_registry

    tools = build_tool_registry(FakeWebSearchClient())
    return _skill_aware_intent_planner_for_tools(tools)


def _skill_aware_intent_planner_for_tools(tools: Mapping[ToolName, Any]) -> Any:
    from agent_core.planning.skill_aware_intent_planner import SkillAwareIntentPlanner
    from agent_core.skills.registry import build_skill_registry

    skills = build_skill_registry(tools=tools)
    fallback = IntentPlanner()
    return SkillAwareIntentPlanner(
        skills=skills,
        fallback=fallback,
        tools=tools,
    )

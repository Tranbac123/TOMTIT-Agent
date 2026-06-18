from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_core.planning.intent_planner import IntentPlanner
from agent_core.planning.intents import ParsedIntent
from agent_core.skills.base import SkillSpec
from agent_core.skills.errors import InvalidSkillPlanError
from agent_core.skills.registry import SkillRegistry
from agent_core.state.agent_state import Step
from agent_core.state.enums import ToolName
from agent_core.tools.base import ToolSpec


class SkillAwareIntentPlanner:
    """Planner adapter: routes ParsedIntent to a registered skill or falls
    back to the legacy IntentPlanner for non-skill intents.

    Public method is ``make_plan(parsed)`` — same signature expected by
    ``RuleBasedPlanner.intent_planner``.
    """

    def __init__(
        self,
        *,
        skills: SkillRegistry,
        fallback: IntentPlanner,
        tools: Mapping[ToolName, ToolSpec],
    ) -> None:
        self._skills = skills
        self._fallback = fallback
        self._tools = tools

    def make_plan(self, parsed: ParsedIntent) -> list[Step]:
        # v1.1 change 3: missing_slots MUST be handled before skill dispatch.
        if parsed.missing_slots:
            return self._fallback.make_plan(parsed)

        spec = self._skills.for_intent(parsed.intent)
        if spec is None:
            return self._fallback.make_plan(parsed)

        slots = self._extract_slots(parsed)
        steps = spec.plan_factory(slots)
        self._validate_skill_plan(spec, steps)
        return steps

    # ------------------------------------------------------------------
    # Slot extraction
    # ------------------------------------------------------------------

    def _extract_slots(self, parsed: ParsedIntent) -> dict[str, Any]:
        """Extract all non-None slot fields from ParsedIntent into a plain dict.
        Factory receives Mapping[str, Any] — no ParsedIntent exposure."""
        slots: dict[str, Any] = {}
        if parsed.expression is not None:
            slots["expression"] = parsed.expression
        if parsed.note_name is not None:
            slots["note_name"] = parsed.note_name
        if parsed.content is not None:
            slots["content"] = parsed.content
        if parsed.query is not None:
            slots["query"] = parsed.query
        return slots

    # ------------------------------------------------------------------
    # Skill plan validation (§9.3)
    # ------------------------------------------------------------------

    def _validate_skill_plan(self, spec: SkillSpec, steps: object) -> None:
        if not isinstance(steps, list):
            raise InvalidSkillPlanError(
                f"Skill {spec.name!r} plan_factory returned {type(steps).__name__}, expected list"
            )
        if not steps:
            raise InvalidSkillPlanError(
                f"Skill {spec.name!r} plan_factory returned an empty plan"
            )
        for i, step in enumerate(steps):
            if not isinstance(step, Step):
                raise InvalidSkillPlanError(
                    f"Skill {spec.name!r} step[{i}] is {type(step).__name__}, expected Step"
                )
            if step.action not in spec.required_tools:
                raise InvalidSkillPlanError(
                    f"Skill {spec.name!r} step[{i}] action {step.action!r} "
                    f"not declared in required_tools"
                )
            if step.action not in self._tools:
                raise InvalidSkillPlanError(
                    f"Skill {spec.name!r} step[{i}] action {step.action!r} "
                    f"not in ToolRegistry"
                )

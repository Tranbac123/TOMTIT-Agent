from __future__ import annotations

from agent_core.planning.intent_planner import IntentPlanner
from agent_core.planning.intents import ParsedIntent
from agent_core.skills.base import DisabledSkill, SkillSpec
from agent_core.skills.errors import InvalidSkillPlanError
from agent_core.skills.registry import SkillCatalog
from agent_core.state.agent_state import Step
from agent_core.state.enums import ToolName


class SkillAwareIntentPlanner:
    """Routes ParsedIntent to:
    - mapped  : active skill plan_factory
    - unavailable: deterministic capability-unavailable FINISH plan
    - unknown : existing IntentPlanner fallback (exactly once)

    Clarification (missing_slots) precedes all skill dispatch.
    """

    def __init__(
        self,
        *,
        catalog: SkillCatalog,
        fallback: IntentPlanner,
    ) -> None:
        self._catalog = catalog
        self._fallback = fallback

    def make_plan(self, parsed: ParsedIntent) -> list[Step]:
        # 1. Clarification before any skill classification (EX2-I6, v1.1 change 3)
        if parsed.missing_slots:
            return self._fallback.make_plan(parsed)

        # 2. Active skill → mapped
        active = self._catalog.active_for_intent(parsed.intent)
        if active is not None:
            inputs = self._extract_inputs(active, parsed)
            steps = active.plan_factory(inputs)
            self._validate_skill_plan(active, steps)
            return steps

        # 3. Disabled skill → unavailable
        disabled = self._catalog.unavailable_for_intent(parsed.intent)
        if disabled is not None:
            return self._capability_unavailable_plan(disabled)

        # 4. Unknown → existing fallback exactly once
        return self._fallback.make_plan(parsed)

    # ------------------------------------------------------------------
    # Input extraction (spec §10.3)
    # ------------------------------------------------------------------

    def _extract_inputs(self, spec: SkillSpec, parsed: ParsedIntent) -> dict[str, object]:
        """Extract only the fields declared in spec.required_inputs from parsed.
        Returns a detached dict; does not expose full ParsedIntent."""
        return {name: getattr(parsed, name) for name in spec.required_inputs}

    # ------------------------------------------------------------------
    # Unavailable plan (spec §10.5)
    # ------------------------------------------------------------------

    def _capability_unavailable_plan(self, disabled: DisabledSkill) -> list[Step]:
        missing_values = ", ".join(t.value for t in disabled.missing_tools)
        return [
            Step(
                thought="Thông báo skill không khả dụng với backend hiện tại",
                action=ToolName.FINISH,
                args={
                    "answer": (
                        f"Skill '{disabled.name.value}' không khả dụng với backend hiện tại. "
                        f"Thiếu capability: {missing_values}."
                    )
                },
            )
        ]

    # ------------------------------------------------------------------
    # Skill plan validation (spec §11)
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

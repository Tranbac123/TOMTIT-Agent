from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import Any

from agent_core.planning.intents import IntentName
from agent_core.skills.base import SkillManifestEntry, SkillPlanFactory, SkillSpec
from agent_core.skills.calculate_and_save_skill import CalculateAndSaveSkill
from agent_core.skills.errors import (
    DuplicateSkillError,
    DuplicateSkillIntentError,
    MissingSkillToolError,
    UnknownSkillError,
)
from agent_core.skills.read_and_summarize_skill import ReadAndSummarizeSkill
from agent_core.skills.web_search_skill import WebSearchSkill
from agent_core.state.agent_state import Step
from agent_core.state.enums import SkillName, ToolName
from agent_core.tools.base import ToolSpec


class SkillRegistry(Mapping[SkillName, SkillSpec]):
    """Immutable catalog of static skills, indexed by SkillName and IntentName."""

    def __init__(
        self,
        data: MappingProxyType[SkillName, SkillSpec],
        intent_index: MappingProxyType[IntentName, SkillName],
    ) -> None:
        self._data = data
        self._intent_index = intent_index

    @classmethod
    def from_specs(
        cls,
        specs: tuple[SkillSpec, ...],
        *,
        tools: Mapping[ToolName, ToolSpec],
    ) -> SkillRegistry:
        seen_names: dict[SkillName, SkillSpec] = {}
        intent_index: dict[IntentName, SkillName] = {}

        for spec in specs:
            if spec.name in seen_names:
                raise DuplicateSkillError(
                    f"Skill {spec.name!r} registered more than once"
                )
            missing = spec.required_tools - frozenset(tools.keys())
            if missing:
                raise MissingSkillToolError(
                    f"Skill {spec.name!r} requires tools not in registry: "
                    + ", ".join(sorted(str(t) for t in missing))
                )
            for intent in spec.supported_intents:
                if intent in intent_index:
                    raise DuplicateSkillIntentError(
                        f"Intent {intent!r} already owned by skill "
                        f"{intent_index[intent]!r}; cannot also assign to {spec.name!r}"
                    )
                intent_index[intent] = spec.name
            seen_names[spec.name] = spec

        return cls(
            data=MappingProxyType(seen_names),
            intent_index=MappingProxyType(intent_index),
        )

    # ------------------------------------------------------------------
    # Mapping interface
    # ------------------------------------------------------------------

    def __getitem__(self, name: SkillName) -> SkillSpec:
        return self._data[name]

    def __iter__(self) -> Iterator[SkillName]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def get(self, name: SkillName, default: SkillSpec | None = None) -> SkillSpec | None:
        return self._data.get(name, default)

    # ------------------------------------------------------------------
    # Extended API
    # ------------------------------------------------------------------

    def require(self, name: SkillName) -> SkillSpec:
        try:
            return self._data[name]
        except KeyError:
            raise UnknownSkillError(f"No skill registered for {name!r}")

    def for_intent(self, intent: IntentName) -> SkillSpec | None:
        skill_name = self._intent_index.get(intent)
        if skill_name is None:
            return None
        return self._data[skill_name]

    def all(self) -> Mapping[SkillName, SkillSpec]:
        return self._data

    def manifest(self) -> tuple[SkillManifestEntry, ...]:
        return tuple(
            SkillManifestEntry(
                name=spec.name,
                description=spec.description,
                supported_intents=tuple(sorted(spec.supported_intents, key=lambda i: i.value)),
                required_inputs=tuple(sorted(spec.required_inputs)),
                required_tools=tuple(sorted(spec.required_tools, key=lambda t: t.value)),
            )
            for spec in self._data.values()
        )


# ---------------------------------------------------------------------------
# Slot-based adapters (stateless, no tool callable)
# ---------------------------------------------------------------------------

def _calculate_and_save_factory(slots: Mapping[str, Any]) -> list[Step]:
    return CalculateAndSaveSkill(
        expression=slots["expression"],
        note_name=slots["note_name"],
    ).make_steps()


def _read_and_summarize_factory(slots: Mapping[str, Any]) -> list[Step]:
    return ReadAndSummarizeSkill(
        note_name=slots["note_name"],
    ).make_steps()


def _web_search_factory(slots: Mapping[str, Any]) -> list[Step]:
    # max_results is hard-coded to 3 to match pre-EX2 production planner behavior.
    return WebSearchSkill(
        query=slots["query"],
        max_results=3,
    ).make_steps()


# ---------------------------------------------------------------------------
# Static provider — pre-filters skills to only those whose required tools
# are available in the supplied ToolRegistry.  This ensures both local and
# M6 remote backends pass SkillRegistry.from_specs() validation (change 7).
# ---------------------------------------------------------------------------

_CALCULATE_AND_SAVE_TOOLS = frozenset({
    ToolName.CALCULATE, ToolName.WRITE_NOTE, ToolName.FINISH,
})
_READ_AND_SUMMARIZE_TOOLS = frozenset({
    ToolName.READ_NOTE, ToolName.SUMMARIZE, ToolName.FINISH,
})
_WEB_SEARCH_TOOLS = frozenset({
    ToolName.WEB_SEARCH, ToolName.FINISH,
})


def builtin_skill_specs(
    tools: Mapping[ToolName, ToolSpec],
) -> tuple[SkillSpec, ...]:
    """Return SkillSpec instances for built-in skills whose required tools are
    all present in *tools*.  Skills with missing tool dependencies are silently
    omitted so that each backend can construct a valid SkillRegistry."""
    available = frozenset(tools.keys())
    specs: list[SkillSpec] = []

    if _CALCULATE_AND_SAVE_TOOLS <= available:
        specs.append(SkillSpec(
            name=SkillName.CALCULATE_AND_SAVE,
            description=(
                "Calculate a numeric expression then save the result as a note."
            ),
            supported_intents=frozenset({IntentName.CALCULATE_THEN_SAVE_NOTE}),
            required_inputs=frozenset({"expression", "note_name"}),
            required_tools=_CALCULATE_AND_SAVE_TOOLS,
            plan_factory=_calculate_and_save_factory,
        ))

    if _READ_AND_SUMMARIZE_TOOLS <= available:
        specs.append(SkillSpec(
            name=SkillName.READ_AND_SUMMARIZE,
            description="Read a note from memory then summarize its content.",
            supported_intents=frozenset({IntentName.READ_NOTE_THEN_SUMMARIZE}),
            required_inputs=frozenset({"note_name"}),
            required_tools=_READ_AND_SUMMARIZE_TOOLS,
            plan_factory=_read_and_summarize_factory,
        ))

    if _WEB_SEARCH_TOOLS <= available:
        specs.append(SkillSpec(
            name=SkillName.WEB_SEARCH,
            description="Search the web and return the top results.",
            supported_intents=frozenset({IntentName.WEB_SEARCH}),
            required_inputs=frozenset({"query"}),
            required_tools=_WEB_SEARCH_TOOLS,
            plan_factory=_web_search_factory,
        ))

    return tuple(specs)


def build_skill_registry(*, tools: Mapping[ToolName, ToolSpec]) -> SkillRegistry:
    return SkillRegistry.from_specs(builtin_skill_specs(tools), tools=tools)

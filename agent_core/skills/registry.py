from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from agent_core.planning.intents import IntentName
from agent_core.skills.base import (
    DisabledSkill,
    SkillManifestEntry,
    SkillPlanFactory,
    SkillSpec,
)
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
from agent_core.state.enums import DisabledSkillReason, SkillName, ToolName
from agent_core.tools.base import ToolSpec


# ---------------------------------------------------------------------------
# SkillRegistry — strict immutable Mapping[SkillName, SkillSpec]
# ---------------------------------------------------------------------------

class SkillRegistry(Mapping[SkillName, SkillSpec]):
    """Strict immutable registry of active skills. Every spec admitted here
    has all its required tools present in the resolved ToolRegistry."""

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
        specs: Iterable[SkillSpec],
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
            for intent in spec.applicable_intents:
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
                applicable_intents=tuple(sorted(spec.applicable_intents, key=lambda i: i.value)),
                required_inputs=tuple(sorted(spec.required_inputs)),
                required_tools=tuple(sorted(spec.required_tools, key=lambda t: t.value)),
            )
            for spec in self._data.values()
        )


# ---------------------------------------------------------------------------
# SkillCatalog — capability-aware partition of all built-in skill definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillCatalog:
    """Partitions all built-in SkillSpecs into active (compatible) and disabled
    (missing tools) sets against the exact resolved ToolRegistry.

    Construction follows the spec §5.7 order:
    1. materialize specs once
    2. validate duplicate SkillName
    3. validate duplicate intent ownership
    4. compute missing tools vs exact resolved ToolRegistry
    5. partition into compatible/incompatible
    6. build strict active SkillRegistry
    7. build deterministic disabled records
    8. build immutable intent indexes
    """

    active: SkillRegistry
    disabled: tuple[DisabledSkill, ...]

    def __post_init__(self) -> None:
        # Build disabled intent index for O(1) lookup (step 8).
        idx: dict[IntentName, DisabledSkill] = {}
        for ds in self.disabled:
            for intent in ds.applicable_intents:
                idx[intent] = ds
        object.__setattr__(self, "_disabled_intent_index", MappingProxyType(idx))

    @classmethod
    def from_specs(
        cls,
        specs: Iterable[SkillSpec],
        *,
        tools: Mapping[ToolName, ToolSpec],
    ) -> SkillCatalog:
        # Step 1: materialize
        specs_list = list(specs)

        # Step 2+3: validate duplicates across ALL specs before partitioning
        seen_names: set[SkillName] = set()
        seen_intents: dict[IntentName, SkillName] = {}
        for spec in specs_list:
            if spec.name in seen_names:
                raise DuplicateSkillError(
                    f"Skill {spec.name!r} defined more than once"
                )
            seen_names.add(spec.name)
            for intent in spec.applicable_intents:
                if intent in seen_intents:
                    raise DuplicateSkillIntentError(
                        f"Intent {intent!r} owned by both {seen_intents[intent]!r} "
                        f"and {spec.name!r}"
                    )
                seen_intents[intent] = spec.name

        # Step 4+5: compute missing tools and partition
        available = frozenset(tools.keys())
        active_specs: list[SkillSpec] = []
        disabled: list[DisabledSkill] = []

        for spec in specs_list:
            missing = spec.required_tools - available
            if missing:
                # Step 7: deterministic disabled record
                disabled.append(DisabledSkill(
                    name=spec.name,
                    description=spec.description,
                    applicable_intents=tuple(
                        sorted(spec.applicable_intents, key=lambda i: i.value)
                    ),
                    required_tools=tuple(
                        sorted(spec.required_tools, key=lambda t: t.value)
                    ),
                    missing_tools=tuple(
                        sorted(missing, key=lambda t: t.value)
                    ),
                    reason=DisabledSkillReason.MISSING_REQUIRED_TOOLS,
                ))
            else:
                active_specs.append(spec)

        # Step 6: build strict active SkillRegistry (raises if invariant violated)
        active = SkillRegistry.from_specs(active_specs, tools=tools)

        return cls(active=active, disabled=tuple(disabled))

    def active_for_intent(self, intent: IntentName) -> SkillSpec | None:
        return self.active.for_intent(intent)

    def unavailable_for_intent(self, intent: IntentName) -> DisabledSkill | None:
        idx: MappingProxyType = object.__getattribute__(self, "_disabled_intent_index")
        return idx.get(intent)


# ---------------------------------------------------------------------------
# Slot-based adapters (stateless, no tool callable/executor)
# ---------------------------------------------------------------------------

def _calculate_and_save_factory(inputs: Mapping[str, Any]) -> list[Step]:
    return CalculateAndSaveSkill(
        expression=inputs["expression"],
        note_name=inputs["note_name"],
    ).make_steps()


def _read_and_summarize_factory(inputs: Mapping[str, Any]) -> list[Step]:
    return ReadAndSummarizeSkill(
        note_name=inputs["note_name"],
    ).make_steps()


def _web_search_factory(inputs: Mapping[str, Any]) -> list[Step]:
    # max_results=3 is locked to match accepted pre-EX2 production behavior (spec §8.3).
    return WebSearchSkill(
        query=inputs["query"],
        max_results=3,
    ).make_steps()


# ---------------------------------------------------------------------------
# Built-in skill provider — always returns all three definitions, no filtering.
# Capability partitioning occurs only in SkillCatalog.from_specs().
# ---------------------------------------------------------------------------

def builtin_skill_specs() -> tuple[SkillSpec, ...]:
    """Return all three static built-in SkillSpec definitions.

    The provider does not filter by backend, memory_mode, or tool availability.
    Partitioning is the responsibility of SkillCatalog.from_specs().
    """
    return (
        SkillSpec(
            name=SkillName.CALCULATE_AND_SAVE,
            description="Calculate a numeric expression then save the result as a note.",
            applicable_intents=frozenset({IntentName.CALCULATE_THEN_SAVE_NOTE}),
            required_inputs=frozenset({"expression", "note_name"}),
            required_tools=frozenset({ToolName.CALCULATE, ToolName.WRITE_NOTE, ToolName.FINISH}),
            plan_factory=_calculate_and_save_factory,
        ),
        SkillSpec(
            name=SkillName.READ_AND_SUMMARIZE,
            description="Read a note from memory then summarize its content.",
            applicable_intents=frozenset({IntentName.READ_NOTE_THEN_SUMMARIZE}),
            required_inputs=frozenset({"note_name"}),
            required_tools=frozenset({ToolName.READ_NOTE, ToolName.SUMMARIZE, ToolName.FINISH}),
            plan_factory=_read_and_summarize_factory,
        ),
        SkillSpec(
            name=SkillName.WEB_SEARCH,
            description="Search the web and return the top results.",
            applicable_intents=frozenset({IntentName.WEB_SEARCH}),
            required_inputs=frozenset({"query"}),
            required_tools=frozenset({ToolName.WEB_SEARCH, ToolName.FINISH}),
            plan_factory=_web_search_factory,
        ),
    )


# ---------------------------------------------------------------------------
# Composition helpers
# ---------------------------------------------------------------------------

def build_skill_catalog(*, tools: Mapping[ToolName, ToolSpec]) -> SkillCatalog:
    """Build a capability-aware SkillCatalog from all built-in specs and the
    given resolved ToolRegistry."""
    return SkillCatalog.from_specs(builtin_skill_specs(), tools=tools)


def build_skill_registry(*, tools: Mapping[ToolName, ToolSpec]) -> SkillRegistry:
    """Build a strict SkillRegistry from only the skills compatible with *tools*.

    Used in tests that exercise SkillRegistry directly. Production code should
    prefer build_skill_catalog() to retain DisabledSkill evidence.
    """
    compatible = [
        spec for spec in builtin_skill_specs()
        if spec.required_tools <= frozenset(tools.keys())
    ]
    return SkillRegistry.from_specs(compatible, tools=tools)

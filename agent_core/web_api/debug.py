"""CONV-P0 P0-8B — debug/eval views over the conversation memory and turn trace.

Read-only projections for the debug endpoints. These convert the confirmed-profile
snapshot into a safe, storage-agnostic fact list (no raw record ids, no store internals)
and the ``TurnTrace`` dataclass into a JSON-safe dict. No memory is written here.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from agent_core.conversation.profile_memory import (
    ProfileSnapshot,
    collect_profile_snapshot,
)
from agent_core.memory.base import MemoryStoreProtocol
from agent_core.runtime.turn_trace import TurnTrace


def build_memory_debug_facts(store: MemoryStoreProtocol) -> list[dict[str, Any]]:
    """Project the confirmed-profile snapshot into `{kind, value, active}` entries.

    ``active=False`` marks explicit negative evidence (retracted/negated facts) — the
    same unknown-vs-negative distinction the runtime answers with.
    """
    snap: ProfileSnapshot = collect_profile_snapshot(store)
    facts: list[dict[str, Any]] = []

    def _add(kind: str, values: list[str], *, active: bool = True) -> None:
        for value in values:
            facts.append({"kind": kind, "value": value, "active": active})

    if snap.name:
        _add("name", [snap.name])
    _add("previous_name", snap.previous_names, active=False)
    _add("occupation", snap.occupation)
    _add("skill", snap.skills)
    _add("skill", snap.negative_skills, active=False)
    _add("learning_focus", snap.learning)
    _add("goal", snap.goals)
    _add("goal", snap.negative_goals, active=False)
    _add("today_plan", snap.today_intentions)
    _add("preference", snap.preferences_personal + snap.preferences_professional)
    _add("preference", snap.dislikes, active=False)
    _add("habit", snap.habits)
    _add("pet", snap.pets)
    _add("wants_to_eat", snap.eat_desires)
    _add("wants_to_marry", snap.marry_targets)
    _add("affection_outgoing", snap.affections)
    _add("affection_outgoing", snap.negative_affections, active=False)
    _add("affection_incoming", snap.external_affections)
    _add("affection_incoming", snap.negative_external_affections, active=False)
    for label, name in snap.relations:
        facts.append({"kind": f"relation:{label}", "value": name, "active": True})
    if snap.favorite_food:
        _add("favorite_food", [snap.favorite_food])
    if snap.favorite_general:
        _add("favorite", [snap.favorite_general])
    if snap.current_focus:
        _add("goal_focus", [snap.current_focus])
    return facts


def build_memory_debug_summary(facts: list[dict[str, Any]]) -> str:
    active = sum(1 for f in facts if f["active"])
    inactive = len(facts) - active
    if not facts:
        return "no confirmed profile facts"
    return f"{active} active fact(s), {inactive} retracted/negative"


def trace_to_dict(trace: TurnTrace | None) -> dict[str, Any] | None:
    """JSON-safe view of the last turn trace (None when no turn has run yet)."""
    if trace is None:
        return None
    return dataclasses.asdict(trace)

"""CONV-P0 P0-3 conversation route + trace model (production-owned, test-independent).

Internal route model only — NOT a Web API/public DTO, and NO test-only spy counters
(planner_calls/tool_calls/memory_reads/memory_writes live in T1B test spies). The trace
meanings intentionally mirror the test-only T1A schema literals but are defined here so
production never imports `tests/`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ConversationRoute(StrEnum):
    DIRECT_RESPONSE = "DIRECT_RESPONSE"
    CLARIFICATION = "CLARIFICATION"
    RUNTIME_FALLBACK = "RUNTIME_FALLBACK"


class TraceMeaning(StrEnum):
    REQUEST_RECEIVED = "request_received"
    INTENT_CLASSIFIED = "intent_classified"
    ROUTE_SELECTED = "route_selected"
    RESPONSE_GENERATED = "response_generated"
    STATE_FINALIZED = "state_finalized"


@dataclass(frozen=True)
class RouteResult:
    """Outcome of ConversationRouter.route(). `response_text` is set only for
    DIRECT_RESPONSE/CLARIFICATION; RUNTIME_FALLBACK leaves it None (runtime composes)."""

    intent: str
    route: ConversationRoute
    response_text: str | None = None
    trace: tuple[TraceMeaning, ...] = field(default_factory=tuple)

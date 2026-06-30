"""CONV-P0 P0-3 ConversationRouter.

Classifies a turn with the existing rule-based parser and selects a route. It NEVER
calls the planner, ToolExecutor, memory, or an LLM — it only reads `state.goal`,
parses it, and (for direct/clarification) composes deterministic text.

Routing (deliberately narrow for P0-3):
  GREETING / IDENTITY_QUERY / CAPABILITY_QUERY -> DIRECT_RESPONSE
  CLARIFICATION_REQUEST                        -> CLARIFICATION
  everything else (incl. bare UNKNOWN)         -> RUNTIME_FALLBACK

Bare UNKNOWN stays RUNTIME_FALLBACK so arbitrary input continues through the existing
runtime recoverable path (and to preserve existing SessionRuntime tests); the explicit
ambiguous-reference case ("Làm cái đó đi") is what the parser returns as
CLARIFICATION_REQUEST and is the P0-3 clarification target.
"""
from __future__ import annotations

import re

from agent_core.conversation.models import ConversationRoute, RouteResult, TraceMeaning
from agent_core.conversation.response_composer import ResponseComposer
from agent_core.planning.intent_parser import RuleBasedIntentParser
from agent_core.planning.intents import IntentName
from agent_core.state.agent_state import AgentState

_DIRECT_INTENTS = frozenset(
    {IntentName.GREETING, IntentName.IDENTITY_QUERY, IntentName.CAPABILITY_QUERY}
)
_CLARIFICATION_INTENTS = frozenset({IntentName.CLARIFICATION_REQUEST})

# P0-4A: unsupported date/time/weather utilities. Handled via the existing CLARIFICATION
# route (NO new route literal) with a specific honest "not supported" response, instead of
# the generic fallback. Detected at the conversation layer because the rule parser returns
# UNKNOWN for these.
_UNSUPPORTED_UTILITY = re.compile(
    r'(?:thời\s+tiết|mấy\s+giờ|giờ\s+rồi|'
    r'ngày\s+(?:bao\s+nhiêu|mấy)|hôm\s+nay.*ngày|hôm\s+nào.*ngày)',
    re.IGNORECASE,
)


class ConversationRouter:
    def __init__(
        self,
        parser: RuleBasedIntentParser | None = None,
        composer: ResponseComposer | None = None,
    ) -> None:
        self._parser = parser or RuleBasedIntentParser()
        self._composer = composer or ResponseComposer()

    def route(self, state: AgentState) -> RouteResult:
        trace: list[TraceMeaning] = [TraceMeaning.REQUEST_RECEIVED]
        intent = self._parser.parse(state.goal).intent
        trace.append(TraceMeaning.INTENT_CLASSIFIED)

        if intent in _DIRECT_INTENTS:
            route = ConversationRoute.DIRECT_RESPONSE
            response_text: str | None = self._composer.compose_direct(intent)
        elif intent in _CLARIFICATION_INTENTS:
            route = ConversationRoute.CLARIFICATION
            response_text = self._composer.compose_clarification(intent)
        elif _UNSUPPORTED_UTILITY.search(state.goal):
            # P0-4A: date/time/weather not supported — honest specific response via the
            # existing CLARIFICATION route (no new route literal).
            route = ConversationRoute.CLARIFICATION
            response_text = self._composer.compose_unsupported_utility()
        else:
            route = ConversationRoute.RUNTIME_FALLBACK
            response_text = None

        trace.append(TraceMeaning.ROUTE_SELECTED)
        if route is not ConversationRoute.RUNTIME_FALLBACK:
            trace.append(TraceMeaning.RESPONSE_GENERATED)

        return RouteResult(
            intent=intent.value,
            route=route,
            response_text=response_text,
            trace=tuple(trace),
        )

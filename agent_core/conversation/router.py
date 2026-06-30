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

# P0-4B: user-memory / user-self-identity queries. The user is asking about themselves
# or what TomTit knows/remembers about them — honest "memory not supported" response via
# the existing CLARIFICATION route (NO new route literal). Checked before intent dispatch
# because MEMORY_READ intent (if matched by parser) would otherwise fall to RUNTIME_FALLBACK.
_USER_MEMORY_CUE = re.compile(
    r'(?:'
    r'tôi\s+(?:là\s+ai|tên\s+(?:là\s+)?g[ìi])\b|'
    r'bạn\s+(?:nhớ|biết)\s+(?:được\s+)?g[ìi]\s+(?:về\s+)?tôi|'
    r'bạn\s+có\s+biết\s+tôi\s+(?:là\s+ai|tên)'
    r')',
    re.IGNORECASE,
)

# P0-4B: ambiguous user-self capability query ("tôi có thể làm gì?"). The user is asking
# what THEY can do, not asking about TomTit's capabilities — needs clarification, not a
# DIRECT_RESPONSE. Checked before intent dispatch to intercept the false capability match.
_USER_SELF_ACTION_CUE = re.compile(
    r'^tôi\s+có\s+thể\s+(?:làm|giúp|hỗ\s+trợ)\s+(?:được\s+)?(?:những\s+)?g[ìi]',
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
        goal = state.goal
        intent = self._parser.parse(goal).intent
        trace.append(TraceMeaning.INTENT_CLASSIFIED)

        # P0-4B: pre-dispatch intercepts for user-self patterns (before intent-based routing
        # to prevent false capability/identity matches when subject is "tôi").
        if _USER_MEMORY_CUE.search(goal):
            # User asking about themselves or what TomTit knows about them.
            route = ConversationRoute.CLARIFICATION
            response_text: str | None = self._composer.compose_user_memory_unsupported()
        elif _USER_SELF_ACTION_CUE.search(goal):
            # User asking what they themselves can do, not about TomTit's capabilities.
            route = ConversationRoute.CLARIFICATION
            response_text = self._composer.compose_user_self_action()
        elif intent in _DIRECT_INTENTS:
            route = ConversationRoute.DIRECT_RESPONSE
            response_text = self._composer.compose_direct(intent)
        elif intent in _CLARIFICATION_INTENTS:
            route = ConversationRoute.CLARIFICATION
            response_text = self._composer.compose_clarification(intent)
        elif _UNSUPPORTED_UTILITY.search(goal):
            # P0-4A: date/time/weather not supported — honest specific response via the
            # existing CLARIFICATION route (no new route literal).
            route = ConversationRoute.CLARIFICATION
            response_text = self._composer.compose_unsupported_utility()
        elif intent is IntentName.TECHNICAL_EXPLANATION_REQUEST:
            # P0-4B: general open-ended explanation requests (AI, ML, etc.) that the
            # rule-based runtime cannot fulfil — honest "not supported" via CLARIFICATION.
            route = ConversationRoute.CLARIFICATION
            response_text = self._composer.compose_explanation_unsupported()
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

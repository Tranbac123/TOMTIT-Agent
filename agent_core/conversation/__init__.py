"""CONV-P0 conversation layer: router + deterministic/text responder boundaries.

Sits above the runtime at the SessionRuntime.handle_turn seam; classifies a turn and,
for direct/clarification/LLM_RESPONSE routes, produces a completed AgentState without
invoking planner/tools/memory. Runtime-only routes fall back to RuntimeAgent.run.
"""
from __future__ import annotations

from agent_core.conversation.llm_responder import (
    LLMResponderRequest,
    LLMResponderResult,
    TextLLMResponder,
)
from agent_core.conversation.models import ConversationRoute, RouteResult, TraceMeaning
from agent_core.conversation.pending_state import PendingConversationState
from agent_core.conversation.profile_memory import (
    PendingProfileConfirmationState,
    ProfileFactCandidate,
    ProfileQuery,
)
from agent_core.conversation.response_composer import ResponseComposer
from agent_core.conversation.router import ConversationRouter

__all__ = [
    "LLMResponderRequest",
    "LLMResponderResult",
    "TextLLMResponder",
    "ConversationRoute",
    "RouteResult",
    "TraceMeaning",
    "PendingConversationState",
    "PendingProfileConfirmationState",
    "ProfileFactCandidate",
    "ProfileQuery",
    "ResponseComposer",
    "ConversationRouter",
]

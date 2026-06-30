"""CONV-P0 conversation layer (P0-3): minimal router + deterministic responders.

Sits above the runtime at the SessionRuntime.handle_turn seam; classifies a turn and,
for direct/clarification routes, produces a completed AgentState without invoking the
planner/tools/memory/LLM. Everything else falls back to the existing RuntimeAgent.run.
"""
from __future__ import annotations

from agent_core.conversation.models import ConversationRoute, RouteResult, TraceMeaning
from agent_core.conversation.response_composer import ResponseComposer
from agent_core.conversation.router import ConversationRouter

__all__ = [
    "ConversationRoute",
    "RouteResult",
    "TraceMeaning",
    "ResponseComposer",
    "ConversationRouter",
]

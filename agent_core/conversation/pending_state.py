"""CONV-P0 P0-6B short-term pending conversation state for slot continuation.

Stored on SessionRuntime only; never written to TOMTIT-Memory, never placed in
AgentState, never exposed via Web API or CLI.  Expires after a bounded number of
turns or on any high-confidence unrelated command.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class PendingConversationState:
    """Minimal pending state for one note-name slot clarification.

    ``collected_slots`` is a plain dict; frozen=True prevents reassignment of
    the attribute but NOT dict mutation — callers must treat it as read-only.
    """

    kind: Literal["write_note_missing_note_name"]
    intent: str
    original_goal: str
    missing_slots: tuple[str, ...]
    collected_slots: dict[str, str] = field(default_factory=dict)
    prompt_text: str = ""
    source_route: str = ""
    session_id: str = ""
    created_at_turn: int = 0
    expires_after_turns: int = 2

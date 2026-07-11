"""CONV-P0 P0-8A — per-turn observability trace.

One immutable snapshot per handled turn, attached to ``SessionRuntime.last_trace`` in a
backward-compatible way (``handle_turn`` still returns the same ``AgentState``). Eval
harnesses and tests read: which capability was classified, which route answered, what the
safety gate decided, whether any tool was requested/executed, and the memory-write delta.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TurnTrace:
    user_text: str
    normalized_text: str | None
    capability: str | None
    route: str | None
    safety_decision: str | None
    memory_diff: list[str] = field(default_factory=list)
    tool_name: str | None = None
    tool_ok: bool | None = None
    final_answer: str = ""

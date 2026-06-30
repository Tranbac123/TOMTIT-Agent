"""Safe text-only LLM responder boundary for CONV-P0 P0-5B.

This module defines a narrow protocol only. It does not configure providers, read
environment variables, perform network I/O, or expose tools/memory/runtime state to
the responder request.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMResponderRequest:
    user_text: str
    intent: str
    route: str
    session_id: str | None = None
    task_id: str | None = None


@dataclass(frozen=True)
class LLMResponderResult:
    text: str
    provider_name: str | None = None
    model_name: str | None = None


class TextLLMResponder(Protocol):
    def generate(self, request: LLMResponderRequest) -> LLMResponderResult:
        """Generate a text answer from the safe request boundary."""

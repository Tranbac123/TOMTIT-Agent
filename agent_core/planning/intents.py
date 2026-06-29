from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IntentName(str, Enum):
    CALCULATE = "calculate"
    CALCULATE_THEN_SAVE_NOTE = "calculate_then_save_note"
    READ_NOTE = "read_note"
    READ_NOTE_THEN_SUMMARIZE = "read_note_then_summarize"
    WRITE_NOTE = "write_note"
    WEB_SEARCH = "web_search"
    WEB_SEARCH_THEN_SAVE_NOTE = "web_search_then_save_note"
    PROJECT_CONTEXT_QUERY = "project_context_query"  # P4: reads ContextPack
    GREETING = "greeting"                            # B.8: simple hi/hello/chào
    # CONV-P0 P0-2: conversational taxonomy (rule-based classification only;
    # user-facing response handling is P0-3/P0-5/P0-6, not implemented here).
    IDENTITY_QUERY = "identity_query"
    CAPABILITY_QUERY = "capability_query"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE_REQUEST = "memory_write_request"
    PLANNING_REQUEST = "planning_request"
    WRITING_REQUEST = "writing_request"
    SUMMARIZATION_REQUEST = "summarization_request"
    TRANSLATION_REQUEST = "translation_request"
    TECHNICAL_EXPLANATION_REQUEST = "technical_explanation_request"
    CODE_REVIEW_REQUEST = "code_review_request"
    CLARIFICATION_REQUEST = "clarification_request"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ParsedIntent:
    intent: IntentName
    confidence: float
    source: str
    raw_text: str
    expression: str | None = None
    note_name: str | None = None
    content: Any | None = None
    query: str | None = None
    missing_slots: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_missing_slots(self, slots: list[str] | tuple[str, ...]) -> ParsedIntent:
        return ParsedIntent(
            intent=self.intent,
            confidence=self.confidence,
            source=self.source,
            raw_text=self.raw_text,
            expression=self.expression,
            note_name=self.note_name,
            content=self.content,
            query=self.query,
            missing_slots=tuple(slots),
            metadata=dict(self.metadata),
        )

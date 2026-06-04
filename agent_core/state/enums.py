from __future__ import annotations

from enum import StrEnum


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class SourceType(StrEnum):
    WEB = "web"
    MEMORY = "memory"
    TOOL = "tool"
    USER = "user"


class MemoryType(StrEnum):
    NOTE = "note"
    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    TASK_SUMMARY = "task_summary"
    SOURCE = "source"
    LESSON = "lesson"
    PROJECT_CONTEXT = "project_context"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AgentStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Language(StrEnum):
    VI = "vi"
    EN = "en"
    UNKNOWN = "unknown"


class ToolName(StrEnum):
    CALCULATE = "calculate"
    WRITE_NOTE = "write_note"
    READ_NOTE = "read_note"
    LIST_NOTES = "list_notes"
    SAVE_FACT = "save_fact"
    SAVE_PREFERENCE = "save_preference"
    SAVE_DECISION = "save_decision"
    SEARCH_MEMORY = "search_memory"
    SUMMARIZE_MEMORY = "summarize_memory"
    SUMMARIZE = "summarize"
    WEB_SEARCH = "web_search"
    FINISH = "finish"


class ToolResultKind(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    JSON = "json"
    SEARCH = "search"
    ACTION = "action"
    FILE = "file"
    EMPTY = "empty"

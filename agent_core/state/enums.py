from __future__ import annotations

from enum import StrEnum


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


# NOTE [P0 union]: enum này hợp nhất 2 khái niệm cũ — nguồn thông tin (web/memory/tool)
#  và người phát ngôn (user/agent/system). Union để P0-recovery không vỡ consumer.
#  Nợ thiết kế: cân nhắc tách InformationSource vs Speaker ở giai đoạn sau nếu cần
#  type-safety chặt hơn. KHÔNG tách trong P0.
class SourceType(StrEnum):
    WEB = "web"
    MEMORY = "memory"
    TOOL = "tool"
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
    SESSION = "session"
    WORKSPACE = "workspace"
    SKILL = "skill"


class TrustLevel(StrEnum):
    TRUSTED_INSTRUCTION = "trusted_instruction"
    TRUSTED_CONFIGURATION = "trusted_configuration"
    UNTRUSTED_EVIDENCE = "untrusted_evidence"


class MemoryType(StrEnum):
    NOTE = "note"
    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    RULE = "rule"
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
    ANSWER_FROM_CONTEXT = "answer_from_context"  # P4: reads state.context_pack


class SkillName(StrEnum):
    CALCULATE_AND_SAVE = "calculate_and_save"
    READ_AND_SUMMARIZE = "read_and_summarize"
    WEB_SEARCH = "web_search"


class DisabledSkillReason(StrEnum):
    MISSING_REQUIRED_TOOLS = "missing_required_tools"


class ToolResultKind(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    JSON = "json"
    SEARCH = "search"
    ACTION = "action"
    FILE = "file"
    EMPTY = "empty"

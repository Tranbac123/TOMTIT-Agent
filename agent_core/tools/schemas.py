from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.state.enums import ToolResultKind


@dataclass
class Source:
    title: str
    url: str | None = None
    snippet: str | None = None
    source_type: str = "web"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WebSearchOutput:
    answer: str
    snippets: list[str]
    sources: list[str]


@dataclass
class CalculateOutput:
    expression: str
    value: int | float


@dataclass
class WriteNoteOutput:
    name: str
    saved: bool
    message: str
    memory_id: str | None = None


@dataclass
class ReadNoteOutput:
    name: str
    content: str


@dataclass
class ListNotesOutput:
    names: list[str]


@dataclass
class MemoryWriteOutput:
    id: str
    type: str
    content: str
    tags: list[str] = field(default_factory=list)
    importance: float | None = None
    confidence: float | None = None


@dataclass
class SearchMemoryOutput:
    records: list[dict[str, Any]]
    query: str = ""
    count: int | None = None


@dataclass
class SummarizeOutput:
    summary: str
    original_length: int
    summary_length: int
    sentence_count: int


@dataclass
class FinishOutput:
    answer: str


@dataclass
class DeleteFileOutput:
    deleted_files: list[str]
    skipped_files: list[str]
    dry_run: bool
    directory: str | None = None
    freed_bytes: int | None = None


@dataclass
class DeleteMailOutput:
    deleted_mails: list[str]
    skipped_mails: list[str]
    dry_run: bool
    mailbox: str | None = None


@dataclass
class ToolResult:
    success: bool
    output: Any = None
    error: str | None = None
    tool_name: str | None = None
    kind: ToolResultKind = ToolResultKind.JSON
    sources: list[Source] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
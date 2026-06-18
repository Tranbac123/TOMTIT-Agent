from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ToolArgsModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )


# ── Core tools ────────────────────────────────────────────────────────────────

class CalculateArgs(ToolArgsModel):
    expression: str


class SummarizeArgs(ToolArgsModel):
    text: str


class FinishArgs(ToolArgsModel):
    answer: str


# ── Note tools ────────────────────────────────────────────────────────────────

class WriteNoteArgs(ToolArgsModel):
    name: str
    content: str


class ReadNoteArgs(ToolArgsModel):
    name: str


class ListNotesArgs(ToolArgsModel):
    pass


# ── Memory tools ──────────────────────────────────────────────────────────────

class SaveFactArgs(ToolArgsModel):
    content: str
    tags: list[str] | None = None


class SavePreferenceArgs(ToolArgsModel):
    content: str
    tags: list[str] | None = None


class SaveDecisionArgs(ToolArgsModel):
    content: str
    tags: list[str] | None = None


class SearchMemoryArgs(ToolArgsModel):
    query: str
    limit: int = 10


class SummarizeMemoryArgs(ToolArgsModel):
    query: str = ""
    limit: int = 10


# ── Context tools ─────────────────────────────────────────────────────────────

class AnswerFromContextArgs(ToolArgsModel):
    query: str


# ── Web tools ─────────────────────────────────────────────────────────────────

class WebSearchArgs(ToolArgsModel):
    query: str
    max_results: int = 3

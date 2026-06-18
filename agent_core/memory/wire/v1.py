from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "memory-contract-v1"
TOKENIZER_ID = "cl100k_base"

MemoryTypeV1 = Literal[
    "fact",
    "decision",
    "preference",
    "rule",
    "note",
    "lesson",
    "project_context",
]
WriteStatusV1 = Literal["written", "skipped_duplicate"]
ErrorCodeV1 = Literal[
    "INVALID_REQUEST",
    "MEMORY_NOT_FOUND",
    "IDEMPOTENCY_CONFLICT",
    "REQUEST_TOO_LARGE",
    "VALIDATION_ERROR",
    "STORE_UNAVAILABLE",
    "INTERNAL_ERROR",
]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _non_empty(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


class ContextRequestV1(WireModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    request_id: str
    project_id: str
    user_id: str
    session_id: str | None = None
    query: str
    type_filter: list[MemoryTypeV1] | None = None
    token_budget: int = Field(ge=0, le=8000)
    max_items: int = Field(ge=0, le=50)

    @field_validator("request_id", "project_id", "user_id", "session_id", "query")
    @classmethod
    def validate_strings(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _non_empty(value, info.field_name)

    @field_validator("type_filter")
    @classmethod
    def validate_type_filter(cls, value: list[MemoryTypeV1] | None) -> list[MemoryTypeV1] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("type_filter must be null or a non-empty list")
        if len(set(value)) != len(value):
            raise ValueError("type_filter must not contain duplicates")
        return value


class ContextItemV1(WireModel):
    memory_id: str
    type: MemoryTypeV1
    content: str
    tags: list[str] = Field(default_factory=list)
    importance: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    source_task_id: str | None = None
    evidence_ref: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    token_cost: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("memory_id", "content")
    @classmethod
    def validate_required_strings(cls, value: str, info) -> str:
        return _non_empty(value, info.field_name)


class ContextResponseV1(WireModel):
    schema_version: Literal[SCHEMA_VERSION]
    request_id: str
    project_id: str
    user_id: str
    session_id: str | None = None
    query: str
    memory_source: Literal["tomtit-memory"]
    tokenizer_id: Literal[TOKENIZER_ID]
    items: list[ContextItemV1]
    total_items: int = Field(ge=0)
    tokens_used: int = Field(ge=0)
    token_budget: int = Field(ge=0, le=8000)
    truncated: bool
    degraded: Literal[False]
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_totals(self) -> Self:
        if self.tokens_used != sum(item.token_cost for item in self.items):
            raise ValueError("tokens_used must equal item token_cost sum")
        if self.total_items < len(self.items):
            raise ValueError("total_items must be >= len(items)")
        if self.tokens_used > self.token_budget:
            raise ValueError("tokens_used must not exceed token_budget")
        return self


class WriteCandidateV1(WireModel):
    candidate_id: str
    type: MemoryTypeV1
    content: str
    tags: list[str] = Field(default_factory=list)
    importance: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ref: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("candidate_id", "content", "evidence_ref")
    @classmethod
    def validate_required_strings(cls, value: str, info) -> str:
        return _non_empty(value, info.field_name)


class WriteRequestV1(WireModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    request_id: str
    project_id: str
    user_id: str
    session_id: str | None = None
    task_id: str
    candidates: list[WriteCandidateV1] = Field(min_length=1, max_length=50)

    @field_validator("request_id", "project_id", "user_id", "session_id", "task_id")
    @classmethod
    def validate_strings(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _non_empty(value, info.field_name)

    @model_validator(mode="after")
    def validate_candidate_ids(self) -> Self:
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("candidate_id values must be unique")
        return self


class WriteResultV1(WireModel):
    candidate_id: str
    status: WriteStatusV1
    memory_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> Self:
        if self.status == "written" and self.reason is not None:
            raise ValueError("written results must have reason=null")
        if self.status == "skipped_duplicate" and self.reason != "duplicate_content":
            raise ValueError("skipped_duplicate results must use duplicate_content")
        return self


class WriteResponseV1(WireModel):
    schema_version: Literal[SCHEMA_VERSION]
    request_id: str
    project_id: str
    user_id: str
    session_id: str | None = None
    results: list[WriteResultV1]
    written_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        written = sum(result.status == "written" for result in self.results)
        skipped = sum(result.status == "skipped_duplicate" for result in self.results)
        if self.written_count != written:
            raise ValueError("written_count must equal written result count")
        if self.skipped_count != skipped:
            raise ValueError("skipped_count must equal skipped result count")
        return self


class ErrorBodyV1(WireModel):
    code: ErrorCodeV1
    message: str
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelopeV1(WireModel):
    schema_version: Literal[SCHEMA_VERSION]
    request_id: str | None = None
    error: ErrorBodyV1

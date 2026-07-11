from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    ok: bool = True
    service: str = "tomtit-agent-web-api"
    version: str = "dev"


class CreateSessionRequest(BaseModel):
    user_id: str = "local-user"
    project_id: str = "local-project"
    title: str | None = None


class SessionResponse(BaseModel):
    session_id: str
    user_id: str
    project_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]


class MessageRecord(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    provenance: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    status: str | None = None


class SessionMessagesResponse(BaseModel):
    session_id: str
    messages: list[MessageRecord]


class ChatRequest(BaseModel):
    session_id: str
    message: str
    user_id: str = "local-user"
    project_id: str = "local-project"


class ChatResponse(BaseModel):
    session_id: str
    assistant_message: MessageRecord


class MemoryRecallRequest(BaseModel):
    session_id: str
    query: str
    user_id: str = "local-user"
    project_id: str = "local-project"


class RecallResult(BaseModel):
    content: str
    status: str
    provenance: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []


class MemoryRecallResponse(BaseModel):
    session_id: str
    result: RecallResult


class ErrorResponse(BaseModel):
    status: str = "error"
    error_code: str
    message: str
    request_id: str | None = None
    session_id: str | None = None


# --- P0-8B debug endpoints -------------------------------------------------

class DebugMemoryFact(BaseModel):
    kind: str
    value: str
    active: bool = True


class DebugMemoryResponse(BaseModel):
    session_id: str
    summary: str
    facts: list[DebugMemoryFact] = []


class DebugResetRequest(BaseModel):
    session_id: str


class DebugResetResponse(BaseModel):
    ok: bool
    session_id: str
    message: str


class DebugTraceResponse(BaseModel):
    session_id: str
    trace: dict[str, Any] | None = None

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agent_core.web_api.errors import (
    ProjectIdMismatchError,
    ProjectIdRejectedError,
    WebSessionNotFoundError,
    safe_error_response,
)
from agent_core.web_api.models import (
    ChatRequest,
    ChatResponse,
    CreateSessionRequest,
    HealthResponse,
    MemoryRecallRequest,
    MemoryRecallResponse,
    SessionListResponse,
    SessionMessagesResponse,
    SessionResponse,
)
from agent_core.web_api.session_manager import SessionManager

_logger = logging.getLogger(__name__)

router = APIRouter()


def _get_session_manager(request: Request) -> SessionManager:
    return request.app.state.session_manager


@router.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.post("/api/sessions", response_model=SessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    request: Request,
) -> SessionResponse | JSONResponse:
    sm: SessionManager = _get_session_manager(request)
    try:
        return sm.create_session(
            user_id=body.user_id,
            project_id=body.project_id,
            title=body.title,
        )
    except ProjectIdRejectedError:
        return safe_error_response(
            error_code="PROJECT_ID_REJECTED",
            message="The requested project_id is not accepted by the runtime configuration.",
            status_code=400,
        )


@router.get("/api/sessions", response_model=SessionListResponse)
async def list_sessions(request: Request) -> SessionListResponse:
    sm: SessionManager = _get_session_manager(request)
    return SessionListResponse(sessions=sm.list_sessions())


@router.get(
    "/api/sessions/{session_id}/messages",
    response_model=SessionMessagesResponse,
)
async def get_session_messages(
    session_id: str,
    request: Request,
) -> SessionMessagesResponse | JSONResponse:
    sm: SessionManager = _get_session_manager(request)
    try:
        return sm.get_messages(session_id)
    except WebSessionNotFoundError as exc:
        return safe_error_response(
            error_code="SESSION_NOT_FOUND",
            message="Session not found.",
            status_code=404,
            session_id=exc.session_id,
        )


@router.post("/api/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
) -> ChatResponse | JSONResponse:
    sm: SessionManager = _get_session_manager(request)
    request_id = str(uuid4())

    if not body.message or not body.message.strip():
        return safe_error_response(
            error_code="VALIDATION_ERROR",
            message="Message must not be blank.",
            status_code=422,
            request_id=request_id,
            session_id=body.session_id,
        )

    try:
        return await sm.send_chat(
            session_id=body.session_id,
            user_id=body.user_id,
            project_id=body.project_id,
            message=body.message,
        )
    except WebSessionNotFoundError as exc:
        return safe_error_response(
            error_code="SESSION_NOT_FOUND",
            message="Session not found.",
            status_code=404,
            request_id=request_id,
            session_id=exc.session_id,
        )
    except ProjectIdMismatchError as exc:
        return safe_error_response(
            error_code="PROJECT_ID_MISMATCH",
            message="Request project_id does not match session project_id.",
            status_code=400,
            request_id=request_id,
            session_id=exc.session_id,
        )
    except Exception:
        _logger.exception("Runtime error in /api/chat (request_id=%s)", request_id)
        return safe_error_response(
            error_code="RUNTIME_ERROR",
            message="The agent runtime failed while processing the request.",
            status_code=500,
            request_id=request_id,
            session_id=body.session_id,
        )


@router.post("/api/memory/recall", response_model=MemoryRecallResponse)
async def memory_recall(
    body: MemoryRecallRequest,
    request: Request,
) -> MemoryRecallResponse | JSONResponse:
    sm: SessionManager = _get_session_manager(request)
    request_id = str(uuid4())

    if not body.query or not body.query.strip():
        return safe_error_response(
            error_code="VALIDATION_ERROR",
            message="Query must not be blank.",
            status_code=422,
            request_id=request_id,
            session_id=body.session_id,
        )

    try:
        return await sm.recall_memory(
            session_id=body.session_id,
            user_id=body.user_id,
            project_id=body.project_id,
            query=body.query,
        )
    except WebSessionNotFoundError as exc:
        return safe_error_response(
            error_code="SESSION_NOT_FOUND",
            message="Session not found.",
            status_code=404,
            request_id=request_id,
            session_id=exc.session_id,
        )
    except ProjectIdMismatchError as exc:
        return safe_error_response(
            error_code="PROJECT_ID_MISMATCH",
            message="Request project_id does not match session project_id.",
            status_code=400,
            request_id=request_id,
            session_id=exc.session_id,
        )
    except Exception:
        _logger.exception(
            "Runtime error in /api/memory/recall (request_id=%s)", request_id
        )
        return safe_error_response(
            error_code="MEMORY_RECALL_ERROR",
            message="Memory recall failed while processing the request.",
            status_code=500,
            request_id=request_id,
            session_id=body.session_id,
        )

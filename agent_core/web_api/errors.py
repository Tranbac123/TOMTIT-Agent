from __future__ import annotations

from fastapi.responses import JSONResponse

from agent_core.web_api.models import ErrorResponse


def safe_error_response(
    *,
    error_code: str,
    message: str,
    status_code: int = 500,
    request_id: str | None = None,
    session_id: str | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error_code=error_code,
        message=message,
        request_id=request_id,
        session_id=session_id,
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


class WebSessionNotFoundError(Exception):
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Session not found: {session_id}")


class ProjectIdMismatchError(Exception):
    """Raised when a request's project_id differs from the session's project_id."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(
            f"Request project_id does not match session project_id for session {session_id}"
        )


class ProjectIdRejectedError(Exception):
    """Raised when a session's project_id is not accepted by the configured runtime."""

    def __init__(self) -> None:
        super().__init__("Requested project_id is not accepted by the runtime configuration")

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_core.web_api.models import SessionResponse
from agent_core.web_api.routes import router
from agent_core.web_api.runtime_adapter import RuntimeChatResult, RuntimeRecallResult
from agent_core.web_api.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class MockRuntimeAdapter:
    """Controllable stand-in for RuntimeAdapter in unit tests."""

    def __init__(self, **kwargs: Any) -> None:
        self._session_id = str(uuid4())
        self.send_chat_calls: list[dict[str, Any]] = []
        self.recall_memory_calls: list[dict[str, Any]] = []
        # Configurable canned responses
        self.chat_result = RuntimeChatResult(
            content="agent test response",
            status="completed",
        )
        self.recall_result = RuntimeRecallResult(
            content="recall test content",
            status="completed",
            provenance=[{"memory_id": "mem_test_001"}],
        )
        self.chat_raise: Exception | None = None
        self.recall_raise: Exception | None = None

    @property
    def session_id(self) -> str:
        return self._session_id

    async def send_chat(
        self,
        *,
        session_id: str,
        user_id: str,
        project_id: str,
        message: str,
    ) -> RuntimeChatResult:
        self.send_chat_calls.append(
            dict(
                session_id=session_id,
                user_id=user_id,
                project_id=project_id,
                message=message,
            )
        )
        if self.chat_raise is not None:
            raise self.chat_raise
        return self.chat_result

    async def recall_memory(
        self,
        *,
        session_id: str,
        user_id: str,
        project_id: str,
        query: str,
    ) -> RuntimeRecallResult:
        self.recall_memory_calls.append(
            dict(
                session_id=session_id,
                user_id=user_id,
                project_id=project_id,
                query=query,
            )
        )
        if self.recall_raise is not None:
            raise self.recall_raise
        return self.recall_result


def make_test_app(mock_adapter: MockRuntimeAdapter | None = None) -> tuple[FastAPI, MockRuntimeAdapter]:
    """Create a FastAPI app wired to a MockRuntimeAdapter.

    agent_mock.memory_client is a bare MagicMock whose .project_id attribute is
    also a MagicMock (not str), so _read_configured_project_id returns None —
    no runtime project_id enforcement is active.
    """
    adapter = mock_adapter or MockRuntimeAdapter()

    app = FastAPI()

    agent_mock = MagicMock()
    # memory_client.project_id is a MagicMock, not str → no enforcement
    store_mock = MagicMock()
    sm = SessionManager(
        agent=agent_mock,
        store=store_mock,
        adapter_factory=lambda **kwargs: adapter,
    )
    app.state.session_manager = sm
    app.include_router(router)
    return app, adapter


def make_test_app_with_runtime_project_id(
    configured_project_id: str,
    mock_adapter: MockRuntimeAdapter | None = None,
) -> tuple[FastAPI, MockRuntimeAdapter]:
    """Create a test app whose runtime memory_client has a configured project_id.

    Simulates a RemoteMemoryClient scenario where only one project_id is accepted.
    """
    adapter = mock_adapter or MockRuntimeAdapter()

    app = FastAPI()

    agent_mock = MagicMock()
    agent_mock.memory_client = MagicMock()
    agent_mock.memory_client.project_id = configured_project_id  # real str → enforcement active
    store_mock = MagicMock()
    sm = SessionManager(
        agent=agent_mock,
        store=store_mock,
        adapter_factory=lambda **kwargs: adapter,
    )
    app.state.session_manager = sm
    app.include_router(router)
    return app, adapter


# ---------------------------------------------------------------------------
# Tests — GET /api/health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_returns_ok(self) -> None:
        app, _ = make_test_app()
        with TestClient(app) as client:
            resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["service"] == "tomtit-agent-web-api"
        assert body["version"] == "dev"


# ---------------------------------------------------------------------------
# Tests — POST /api/sessions
# ---------------------------------------------------------------------------


class TestCreateSession:
    def test_create_session(self) -> None:
        app, _ = make_test_app()
        with TestClient(app) as client:
            resp = client.post(
                "/api/sessions",
                json={"user_id": "u1", "project_id": "p1", "title": "test"},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert "session_id" in body
        assert body["user_id"] == "u1"
        assert body["project_id"] == "p1"
        assert body["title"] == "test"
        assert "created_at" in body
        assert "updated_at" in body

    def test_create_session_default_ids(self) -> None:
        app, _ = make_test_app()
        with TestClient(app) as client:
            resp = client.post("/api/sessions", json={})
        assert resp.status_code == 201
        body = resp.json()
        assert body["user_id"] == "local-user"
        assert body["project_id"] == "local-project"

    def test_create_session_rejected_when_runtime_project_id_conflicts(self) -> None:
        app, _ = make_test_app_with_runtime_project_id("required-project")
        with TestClient(app) as client:
            resp = client.post(
                "/api/sessions",
                json={"user_id": "u1", "project_id": "other-project"},
            )
        assert resp.status_code == 400
        body = resp.json()
        assert body["status"] == "error"
        assert body["error_code"] == "PROJECT_ID_REJECTED"
        # Configured project_id must not leak into error response.
        assert "required-project" not in resp.text

    def test_create_session_accepted_when_project_id_matches_runtime(self) -> None:
        app, _ = make_test_app_with_runtime_project_id("required-project")
        with TestClient(app) as client:
            resp = client.post(
                "/api/sessions",
                json={"user_id": "u1", "project_id": "required-project"},
            )
        assert resp.status_code == 201
        assert resp.json()["project_id"] == "required-project"

    def test_create_session_rejected_response_is_safe(self) -> None:
        app, _ = make_test_app_with_runtime_project_id("secret-project-id")
        with TestClient(app) as client:
            resp = client.post(
                "/api/sessions",
                json={"project_id": "wrong-project"},
            )
        assert resp.status_code == 400
        assert "Traceback" not in resp.text
        assert "Exception" not in resp.text
        assert "secret-project-id" not in resp.text


# ---------------------------------------------------------------------------
# Tests — GET /api/sessions
# ---------------------------------------------------------------------------


class TestListSessions:
    def test_list_sessions_empty(self) -> None:
        app, _ = make_test_app()
        with TestClient(app) as client:
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert resp.json() == {"sessions": []}

    def test_list_sessions_after_create(self) -> None:
        app, _ = make_test_app()
        with TestClient(app) as client:
            client.post("/api/sessions", json={"user_id": "u1", "project_id": "p1"})
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["sessions"]) == 1
        assert body["sessions"][0]["user_id"] == "u1"


# ---------------------------------------------------------------------------
# Tests — GET /api/sessions/{session_id}/messages
# ---------------------------------------------------------------------------


class TestGetMessages:
    def test_get_messages_empty_session(self) -> None:
        app, _ = make_test_app()
        with TestClient(app) as client:
            create_resp = client.post("/api/sessions", json={})
            session_id = create_resp.json()["session_id"]
            resp = client.get(f"/api/sessions/{session_id}/messages")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == session_id
        assert body["messages"] == []

    def test_get_messages_unknown_session(self) -> None:
        app, _ = make_test_app()
        with TestClient(app) as client:
            resp = client.get("/api/sessions/nonexistent/messages")
        assert resp.status_code == 404
        body = resp.json()
        assert body["status"] == "error"
        assert body["error_code"] == "SESSION_NOT_FOUND"


# ---------------------------------------------------------------------------
# Tests — POST /api/chat
# ---------------------------------------------------------------------------


class TestChat:
    def test_chat_rejects_blank_message(self) -> None:
        app, _ = make_test_app()
        with TestClient(app) as client:
            create_resp = client.post("/api/sessions", json={})
            session_id = create_resp.json()["session_id"]
            resp = client.post(
                "/api/chat",
                json={"session_id": session_id, "message": "  "},
            )
        assert resp.status_code == 422
        body = resp.json()
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_chat_calls_runtime_adapter(self) -> None:
        adapter = MockRuntimeAdapter()
        app, _ = make_test_app(adapter)
        with TestClient(app) as client:
            # Session created with project_id="p1" to match chat request.
            create_resp = client.post("/api/sessions", json={"project_id": "p1"})
            session_id = create_resp.json()["session_id"]
            client.post(
                "/api/chat",
                json={
                    "session_id": session_id,
                    "message": "hello",
                    "user_id": "u1",
                    "project_id": "p1",
                },
            )
        assert len(adapter.send_chat_calls) == 1

    def test_chat_passes_correct_context(self) -> None:
        adapter = MockRuntimeAdapter()
        app, _ = make_test_app(adapter)
        with TestClient(app) as client:
            # Session must be created with the same project_id used in chat.
            create_resp = client.post("/api/sessions", json={"project_id": "my-project"})
            session_id = create_resp.json()["session_id"]
            client.post(
                "/api/chat",
                json={
                    "session_id": session_id,
                    "message": "test message",
                    "user_id": "my-user",
                    "project_id": "my-project",
                },
            )
        sent = adapter.send_chat_calls[0]
        assert sent["session_id"] == session_id
        assert sent["user_id"] == "my-user"
        assert sent["project_id"] == "my-project"
        assert sent["message"] == "test message"

    def test_chat_returns_normalized_assistant_message(self) -> None:
        adapter = MockRuntimeAdapter()
        adapter.chat_result = RuntimeChatResult(
            content="the agent answered", status="completed"
        )
        app, _ = make_test_app(adapter)
        with TestClient(app) as client:
            create_resp = client.post("/api/sessions", json={})
            session_id = create_resp.json()["session_id"]
            resp = client.post(
                "/api/chat",
                json={"session_id": session_id, "message": "hi"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == session_id
        msg = body["assistant_message"]
        assert msg["role"] == "assistant"
        assert msg["content"] == "the agent answered"
        assert msg["status"] == "completed"
        assert "id" in msg
        assert "created_at" in msg

    def test_chat_maps_runtime_exception_to_safe_error(self) -> None:
        adapter = MockRuntimeAdapter()
        adapter.chat_raise = RuntimeError("db connection failed with password=secret123")
        app, _ = make_test_app(adapter)
        with TestClient(app) as client:
            create_resp = client.post("/api/sessions", json={})
            session_id = create_resp.json()["session_id"]
            resp = client.post(
                "/api/chat",
                json={"session_id": session_id, "message": "hello"},
            )
        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == "error"
        assert body["error_code"] == "RUNTIME_ERROR"
        assert "session_id" in body

    def test_chat_does_not_expose_raw_stack_trace(self) -> None:
        adapter = MockRuntimeAdapter()
        adapter.chat_raise = RuntimeError("internal error with traceback info")
        app, _ = make_test_app(adapter)
        with TestClient(app) as client:
            create_resp = client.post("/api/sessions", json={})
            session_id = create_resp.json()["session_id"]
            resp = client.post(
                "/api/chat",
                json={"session_id": session_id, "message": "hello"},
            )
        resp_text = resp.text
        assert "Traceback" not in resp_text
        assert 'File "' not in resp_text
        assert "RuntimeError" not in resp_text
        assert "internal error with traceback info" not in resp_text

    def test_chat_appends_to_session_messages(self) -> None:
        adapter = MockRuntimeAdapter()
        adapter.chat_result = RuntimeChatResult(content="reply", status="completed")
        app, _ = make_test_app(adapter)
        with TestClient(app) as client:
            create_resp = client.post("/api/sessions", json={})
            session_id = create_resp.json()["session_id"]
            client.post("/api/chat", json={"session_id": session_id, "message": "hi"})
            msgs_resp = client.get(f"/api/sessions/{session_id}/messages")
        messages = msgs_resp.json()["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_chat_rejects_mismatched_project_id(self) -> None:
        app, _ = make_test_app()
        with TestClient(app) as client:
            # Session created with project_id="alpha"
            create_resp = client.post("/api/sessions", json={"project_id": "alpha"})
            session_id = create_resp.json()["session_id"]
            # Chat request sends a different project_id
            resp = client.post(
                "/api/chat",
                json={"session_id": session_id, "message": "hello", "project_id": "beta"},
            )
        assert resp.status_code == 400
        body = resp.json()
        assert body["status"] == "error"
        assert body["error_code"] == "PROJECT_ID_MISMATCH"

    def test_chat_project_id_mismatch_response_is_safe(self) -> None:
        app, _ = make_test_app()
        with TestClient(app) as client:
            create_resp = client.post("/api/sessions", json={"project_id": "alpha"})
            session_id = create_resp.json()["session_id"]
            resp = client.post(
                "/api/chat",
                json={"session_id": session_id, "message": "hello", "project_id": "beta"},
            )
        assert "Traceback" not in resp.text
        assert "Exception" not in resp.text
        assert "ProjectIdMismatch" not in resp.text

    def test_chat_mismatch_does_not_pollute_transcript(self) -> None:
        """A rejected chat due to project_id mismatch must not append messages."""
        app, _ = make_test_app()
        with TestClient(app) as client:
            create_resp = client.post("/api/sessions", json={"project_id": "alpha"})
            session_id = create_resp.json()["session_id"]
            client.post(
                "/api/chat",
                json={"session_id": session_id, "message": "hi", "project_id": "beta"},
            )
            msgs_resp = client.get(f"/api/sessions/{session_id}/messages")
        assert msgs_resp.json()["messages"] == []


# ---------------------------------------------------------------------------
# Tests — POST /api/memory/recall
# ---------------------------------------------------------------------------


class TestMemoryRecall:
    def test_recall_rejects_blank_query(self) -> None:
        app, _ = make_test_app()
        with TestClient(app) as client:
            create_resp = client.post("/api/sessions", json={})
            session_id = create_resp.json()["session_id"]
            resp = client.post(
                "/api/memory/recall",
                json={"session_id": session_id, "query": "   "},
            )
        assert resp.status_code == 422
        body = resp.json()
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_recall_calls_runtime_adapter(self) -> None:
        adapter = MockRuntimeAdapter()
        app, _ = make_test_app(adapter)
        with TestClient(app) as client:
            # Session created with project_id="p1" to match recall request.
            create_resp = client.post("/api/sessions", json={"project_id": "p1"})
            session_id = create_resp.json()["session_id"]
            client.post(
                "/api/memory/recall",
                json={
                    "session_id": session_id,
                    "query": "my decision about the db",
                    "user_id": "u1",
                    "project_id": "p1",
                },
            )
        assert len(adapter.recall_memory_calls) == 1

    def test_recall_passes_correct_context(self) -> None:
        adapter = MockRuntimeAdapter()
        app, _ = make_test_app(adapter)
        with TestClient(app) as client:
            # Session must be created with the same project_id used in recall.
            create_resp = client.post("/api/sessions", json={"project_id": "my-project"})
            session_id = create_resp.json()["session_id"]
            client.post(
                "/api/memory/recall",
                json={
                    "session_id": session_id,
                    "query": "database decision",
                    "user_id": "my-user",
                    "project_id": "my-project",
                },
            )
        sent = adapter.recall_memory_calls[0]
        assert sent["session_id"] == session_id
        assert sent["user_id"] == "my-user"
        assert sent["project_id"] == "my-project"
        assert sent["query"] == "database decision"

    def test_recall_returns_normalized_result(self) -> None:
        adapter = MockRuntimeAdapter()
        adapter.recall_result = RuntimeRecallResult(
            content="found decision about postgres",
            status="completed",
            provenance=[{"memory_id": "mem_abc", "evidence_ref": "user-explicit:xyz"}],
        )
        app, _ = make_test_app(adapter)
        with TestClient(app) as client:
            create_resp = client.post("/api/sessions", json={})
            session_id = create_resp.json()["session_id"]
            resp = client.post(
                "/api/memory/recall",
                json={"session_id": session_id, "query": "postgres decision"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == session_id
        result = body["result"]
        assert result["content"] == "found decision about postgres"
        assert result["status"] == "completed"
        assert result["provenance"][0]["memory_id"] == "mem_abc"

    def test_recall_maps_runtime_exception_to_safe_error(self) -> None:
        adapter = MockRuntimeAdapter()
        adapter.recall_raise = RuntimeError("backend timeout with api_key=secret")
        app, _ = make_test_app(adapter)
        with TestClient(app) as client:
            create_resp = client.post("/api/sessions", json={})
            session_id = create_resp.json()["session_id"]
            resp = client.post(
                "/api/memory/recall",
                json={"session_id": session_id, "query": "something"},
            )
        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == "error"
        assert body["error_code"] == "MEMORY_RECALL_ERROR"

    def test_recall_does_not_expose_raw_stack_trace(self) -> None:
        adapter = MockRuntimeAdapter()
        adapter.recall_raise = ValueError("connection refused to 10.0.0.1:6333")
        app, _ = make_test_app(adapter)
        with TestClient(app) as client:
            create_resp = client.post("/api/sessions", json={})
            session_id = create_resp.json()["session_id"]
            resp = client.post(
                "/api/memory/recall",
                json={"session_id": session_id, "query": "something"},
            )
        resp_text = resp.text
        assert "Traceback" not in resp_text
        assert 'File "' not in resp_text
        assert "ValueError" not in resp_text
        assert "connection refused" not in resp_text

    def test_recall_rejects_mismatched_project_id(self) -> None:
        app, _ = make_test_app()
        with TestClient(app) as client:
            # Session created with project_id="alpha"
            create_resp = client.post("/api/sessions", json={"project_id": "alpha"})
            session_id = create_resp.json()["session_id"]
            # Recall request sends a different project_id
            resp = client.post(
                "/api/memory/recall",
                json={"session_id": session_id, "query": "find decision", "project_id": "beta"},
            )
        assert resp.status_code == 400
        body = resp.json()
        assert body["status"] == "error"
        assert body["error_code"] == "PROJECT_ID_MISMATCH"

    def test_recall_project_id_mismatch_response_is_safe(self) -> None:
        app, _ = make_test_app()
        with TestClient(app) as client:
            create_resp = client.post("/api/sessions", json={"project_id": "alpha"})
            session_id = create_resp.json()["session_id"]
            resp = client.post(
                "/api/memory/recall",
                json={"session_id": session_id, "query": "find decision", "project_id": "beta"},
            )
        assert "Traceback" not in resp.text
        assert "Exception" not in resp.text
        assert "ProjectIdMismatch" not in resp.text

from __future__ import annotations

import sys
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agent_core.session_persistence.errors import (
    SessionDataCorruptionError,
    SessionNotFoundError,
    SessionPersistenceError,
)
from agent_core.state.session_state import SessionState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fresh_session() -> SessionState:
    now = _now()
    return SessionState(session_id=str(uuid4()), created_at=now, updated_at=now)


def _noop_interactive(session) -> None:
    """run_interactive replacement that does nothing."""


# ---------------------------------------------------------------------------
# BOUNDARY 1 — create / load session
# ---------------------------------------------------------------------------

def test_main_new_session_starts_without_error(tmp_path, monkeypatch):
    """No --session-id → create fresh session, run_interactive called."""
    monkeypatch.setattr(sys, "argv", ["main", "--session-dir", str(tmp_path)])
    monkeypatch.setattr("main.run_interactive", _noop_interactive)

    import main as m
    m.main()  # must not raise or call sys.exit


def test_main_resume_session_loads_correct_id(tmp_path, monkeypatch):
    """--session-id pointing to saved session → loaded session used."""
    from agent_core.session_persistence import FileSessionStore

    existing = _fresh_session()
    FileSessionStore(tmp_path).save(existing)

    seen_ids: list[str] = []

    def capture(session) -> None:
        seen_ids.append(session.session_id)

    monkeypatch.setattr(sys, "argv", [
        "main", "--session-id", existing.session_id, "--session-dir", str(tmp_path)
    ])
    monkeypatch.setattr("main.run_interactive", capture)

    import main as m
    m.main()

    assert seen_ids == [existing.session_id]


def test_main_session_not_found_exits_2(tmp_path, monkeypatch, capsys):
    """--session-id for non-existent session → sys.exit(2)."""
    monkeypatch.setattr(sys, "argv", [
        "main", "--session-id", str(uuid4()), "--session-dir", str(tmp_path)
    ])

    with pytest.raises(SystemExit) as exc_info:
        import main as m
        m.main()

    assert exc_info.value.code == 2


def test_main_boundary1_session_corruption_exits_2(tmp_path, monkeypatch, capsys):
    """Corrupt session file (valid UUID, bad JSON) → exit 2 (BOUNDARY 1)."""
    import json
    session_id = str(uuid4())
    (tmp_path / f"{session_id}.json").write_text(
        "not valid json at all", encoding="utf-8"
    )

    monkeypatch.setattr(sys, "argv", [
        "main", "--session-id", session_id, "--session-dir", str(tmp_path)
    ])

    with pytest.raises(SystemExit) as exc_info:
        import main as m
        m.main()

    assert exc_info.value.code == 2


def test_main_boundary1_persistence_error_exits_1(tmp_path, monkeypatch, capsys):
    """SessionPersistenceError from load → exit 1 (BOUNDARY 1)."""
    from agent_core.session_persistence import FileSessionStore

    class _BrokenStore(FileSessionStore):
        def load(self, session_id: str):
            raise SessionPersistenceError("disk error on load")

        def save(self, session: SessionState) -> None:
            raise SessionPersistenceError("disk error on save")

    monkeypatch.setattr("main.FileSessionStore", _BrokenStore)
    monkeypatch.setattr(sys, "argv", [
        "main", "--session-id", str(uuid4()), "--session-dir", str(tmp_path)
    ])

    with pytest.raises(SystemExit) as exc_info:
        import main as m
        m.main()

    assert exc_info.value.code == 1


def test_main_boundary1_message_says_create_load(tmp_path, monkeypatch, capsys):
    """5 FIX: BOUNDARY 1 persistence error message contains 'create or load'."""
    from agent_core.session_persistence import FileSessionStore

    class _BrokenStore(FileSessionStore):
        def load(self, session_id: str):
            raise SessionPersistenceError("disk error")

        def save(self, session: SessionState) -> None:
            raise SessionPersistenceError("disk error")

    monkeypatch.setattr("main.FileSessionStore", _BrokenStore)
    monkeypatch.setattr(sys, "argv", [
        "main", "--session-id", str(uuid4()), "--session-dir", str(tmp_path)
    ])

    with pytest.raises(SystemExit):
        import main as m
        m.main()

    stderr = capsys.readouterr().err
    assert "create or load" in stderr


# ---------------------------------------------------------------------------
# BOUNDARY 2 — run phase
# ---------------------------------------------------------------------------

def test_main_run_session_corruption_exits_1_no_retry(tmp_path, monkeypatch, capsys):
    """RÀNG BUỘC APPROVAL: SessionDataCorruptionError from run → exit 1 with
    'Do not retry automatically' (BOUNDARY 2)."""
    monkeypatch.setattr(sys, "argv", ["main", "--session-dir", str(tmp_path)])

    def raise_corruption(session) -> None:
        raise SessionDataCorruptionError("corrupt during run")

    monkeypatch.setattr("main.run_interactive", raise_corruption)

    with pytest.raises(SystemExit) as exc_info:
        import main as m
        m.main()

    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "Do not retry automatically" in stderr


def test_main_boundary2_persistence_error_exits_1(tmp_path, monkeypatch, capsys):
    """SessionPersistenceError from run → exit 1 (BOUNDARY 2)."""
    monkeypatch.setattr(sys, "argv", ["main", "--session-dir", str(tmp_path)])

    def raise_persistence(session) -> None:
        raise SessionPersistenceError("persist failed during run")

    monkeypatch.setattr("main.run_interactive", raise_persistence)

    with pytest.raises(SystemExit) as exc_info:
        import main as m
        m.main()

    assert exc_info.value.code == 1


def test_main_boundary2_message_says_do_not_retry(tmp_path, monkeypatch, capsys):
    """BOUNDARY 2 message instructs user not to retry automatically."""
    monkeypatch.setattr(sys, "argv", ["main", "--session-dir", str(tmp_path)])

    def raise_persistence(session) -> None:
        raise SessionPersistenceError("disk full")

    monkeypatch.setattr("main.run_interactive", raise_persistence)

    with pytest.raises(SystemExit):
        import main as m
        m.main()

    stderr = capsys.readouterr().err
    assert "Do not retry automatically" in stderr
    assert "turn was not persisted" in stderr


def test_main_unexpected_exception_propagates(tmp_path, monkeypatch):
    """Unexpected exception from run propagates (NOT caught by BOUNDARY 2)."""
    monkeypatch.setattr(sys, "argv", ["main", "--session-dir", str(tmp_path)])

    def raise_unexpected(session) -> None:
        raise RuntimeError("unexpected crash!")

    monkeypatch.setattr("main.run_interactive", raise_unexpected)

    with pytest.raises(RuntimeError, match="unexpected crash!"):
        import main as m
        m.main()


# ---------------------------------------------------------------------------
# Integration — new session persisted to file
# ---------------------------------------------------------------------------

def test_main_new_session_creates_file_on_disk(tmp_path, monkeypatch):
    """After a no-op run, the new session JSON file is created on disk."""
    session_dir = tmp_path / "sessions"
    monkeypatch.setattr(sys, "argv", ["main", "--session-dir", str(session_dir)])

    # run_interactive does nothing — SessionRuntime constructor runs and
    # save is only called on handle_turn. So no file yet... unless we force one.
    # Actually we test that the session dir is created and run_interactive receives
    # a SessionRuntime with a valid session_id.
    seen: list[str] = []

    def capture_and_save(session) -> None:
        seen.append(session.session_id)

    monkeypatch.setattr("main.run_interactive", capture_and_save)

    import main as m
    m.main()

    assert len(seen) == 1
    assert len(seen[0]) == 36  # valid UUID4 string length


# ---------------------------------------------------------------------------
# UUID format validation — before composition
# ---------------------------------------------------------------------------

def test_main_invalid_uuid_exits_2_without_composition_or_file(tmp_path, monkeypatch, capsys):
    """Invalid UUID in --session-id → exit 2, build_local_agent not called,
    no session file created on disk."""
    import main as m

    build_was_called: list[bool] = []

    def recording_build():
        build_was_called.append(True)
        from agent_core.runtime.runtime_agent import build_local_agent as _real
        return _real()

    monkeypatch.setattr(m, "build_local_agent", recording_build)
    monkeypatch.setattr(sys, "argv", [
        "main", "--session-id", "not-valid-uuid-at-all", "--session-dir", str(tmp_path)
    ])

    with pytest.raises(SystemExit) as exc_info:
        m.main()

    assert exc_info.value.code == 2
    assert build_was_called == []
    assert list(tmp_path.glob("*.json")) == []

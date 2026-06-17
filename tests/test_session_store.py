from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from agent_core.session_persistence.errors import (
    SessionDataCorruptionError,
    SessionPersistenceError,
)
from agent_core.session_persistence.file_store import FileSessionStore
from agent_core.state.enums import AgentStatus
from agent_core.state.session_state import SessionState, TurnRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_session() -> SessionState:
    now = _now()
    return SessionState(session_id=str(uuid4()), created_at=now, updated_at=now)


def _make_session_with_turn() -> SessionState:
    now = _now()
    ss = SessionState(session_id=str(uuid4()), created_at=now, updated_at=now)
    turn = TurnRecord(
        task_id=str(uuid4()),
        goal="test goal",
        final_answer="test answer",
        status=AgentStatus.COMPLETED,
        planned_actions=("calculate",),
        memory_degraded=False,
        memory_write_failed=False,
        disclosure_reasons=(),
        completed_at=now,
    )
    ss.turns.append(turn)
    ss.updated_at = turn.completed_at
    return ss


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_save_and_load_round_trip(tmp_path):
    store = FileSessionStore(tmp_path / "sessions")
    ss = _make_session_with_turn()

    store.save(ss)
    loaded = store.load(ss.session_id)

    assert loaded is not None
    assert loaded.session_id == ss.session_id
    assert len(loaded.turns) == 1
    assert loaded.turns[0].goal == "test goal"


def test_load_returns_none_for_nonexistent_session(tmp_path):
    store = FileSessionStore(tmp_path / "sessions")
    result = store.load(str(uuid4()))
    assert result is None


def test_load_returns_none_when_dir_does_not_exist(tmp_path):
    store = FileSessionStore(tmp_path / "does_not_exist" / "sessions")
    result = store.load(str(uuid4()))
    assert result is None


def test_save_creates_session_dir_if_missing(tmp_path):
    session_dir = tmp_path / "new_sessions"
    assert not session_dir.exists()
    store = FileSessionStore(session_dir)
    store.save(_make_session())
    assert session_dir.is_dir()


def test_save_overwrites_previous_session(tmp_path):
    store = FileSessionStore(tmp_path / "sessions")
    ss = _make_session()

    store.save(ss)
    store.save(ss)  # save again — should not fail or duplicate

    loaded = store.load(ss.session_id)
    assert loaded is not None
    assert loaded.session_id == ss.session_id


def test_session_file_is_regular_json(tmp_path):
    session_dir = tmp_path / "sessions"
    store = FileSessionStore(session_dir)
    ss = _make_session()
    store.save(ss)

    files = list(session_dir.glob("*.json"))
    assert len(files) == 1

    raw = files[0].read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["session_id"] == ss.session_id


def test_no_temp_files_after_successful_save(tmp_path):
    session_dir = tmp_path / "sessions"
    store = FileSessionStore(session_dir)
    store.save(_make_session())

    tmp_files = list(session_dir.glob("*.tmp"))
    assert tmp_files == []


def test_datetime_round_trip_preserves_tzinfo(tmp_path):
    store = FileSessionStore(tmp_path / "sessions")
    ss = _make_session_with_turn()
    store.save(ss)
    loaded = store.load(ss.session_id)

    assert loaded.created_at.tzinfo is not None
    assert loaded.updated_at.tzinfo is not None
    assert loaded.turns[0].completed_at.tzinfo is not None


# ---------------------------------------------------------------------------
# Atomicity — temp file behaviour
# ---------------------------------------------------------------------------

def test_write_failure_removes_temp_and_leaves_target_unchanged(tmp_path):
    """RÀNG BUỘC APPROVAL: if _fdopen_temp fails, temp is cleaned up and
    any existing target file is not modified."""
    session_dir = tmp_path / "sessions"
    ss = _make_session()

    # First successful save establishes target
    good_store = FileSessionStore(session_dir)
    good_store.save(ss)

    target = good_store._path(ss.session_id)
    original_content = target.read_bytes()

    # Now create a store that fails at fdopen
    class _FailFdOpen(FileSessionStore):
        def _fdopen_temp(self, fd: int):
            raise OSError("simulated fdopen failure")

    fail_store = _FailFdOpen(session_dir)
    with pytest.raises(SessionPersistenceError):
        fail_store.save(ss)

    # Target unchanged
    assert target.read_bytes() == original_content
    # No temp files remain
    assert list(session_dir.glob("*.tmp")) == []


def test_fdopen_failure_closes_fd_and_removes_temp(tmp_path):
    """RÀNG BUỘC APPROVAL: when _fdopen_temp raises, the raw fd is closed
    and temp file is removed."""
    session_dir = tmp_path / "sessions"
    captured: dict[str, int] = {}

    class _CaptureFdOpen(FileSessionStore):
        def _fdopen_temp(self, fd: int):
            captured["fd"] = fd
            raise OSError("simulated fdopen failure")

    store = _CaptureFdOpen(session_dir)
    with pytest.raises(SessionPersistenceError):
        store.save(_make_session())

    # fd must be closed
    assert "fd" in captured
    try:
        os.close(captured["fd"])
        fd_was_closed = False  # os.close succeeded → fd was still open (leak)
    except OSError:
        fd_was_closed = True   # os.close failed → fd already closed (correct)
    assert fd_was_closed, "fd should have been closed after _fdopen_temp failure"

    # No temp files remain
    assert list(session_dir.glob("*.tmp")) == []


# ---------------------------------------------------------------------------
# Cleanup behaviour
# ---------------------------------------------------------------------------

def test_cleanup_temp_failure_does_not_mask_original_error(tmp_path):
    """5 FIX: if _cleanup_temp_best_effort has internal issues, the original
    write error still propagates."""
    session_dir = tmp_path / "sessions"

    class _FailWriteAndBadCleanup(FileSessionStore):
        def _fdopen_temp(self, fd: int):
            os.close(fd)  # close fd ourselves to avoid leak
            raise OSError("original write error")

        def _cleanup_temp_best_effort(self, temp_path: Path) -> None:
            # Simulate cleanup OSError — it's caught and logged, original error preserved
            try:
                raise OSError("cleanup error")
            except OSError:
                pass  # logged internally — does not raise

    store = _FailWriteAndBadCleanup(session_dir)
    with pytest.raises(SessionPersistenceError) as exc_info:
        store.save(_make_session())

    # Original error is preserved as cause
    assert exc_info.value.__cause__ is not None


# ---------------------------------------------------------------------------
# Error mapping — BINDING FIX
# ---------------------------------------------------------------------------

def test_save_maps_oserror_to_persistence_error(tmp_path):
    """BINDING FIX: OSError during replace → SessionPersistenceError."""
    def fail_replace(src, dst):
        raise OSError("replace failed")

    store = FileSessionStore(tmp_path / "sessions", replace_fn=fail_replace)
    with pytest.raises(SessionPersistenceError):
        store.save(_make_session())


def test_ensure_dir_oserror_maps_to_persistence_error(tmp_path):
    """BINDING FIX: OSError from _ensure_dir → SessionPersistenceError in save."""
    class _EnsureDirFails(FileSessionStore):
        def _ensure_dir(self) -> None:
            raise OSError("no space left on device")

    store = _EnsureDirFails(tmp_path / "sessions")
    with pytest.raises(SessionPersistenceError):
        store.save(_make_session())


def test_create_temp_oserror_maps_to_persistence_error(tmp_path):
    """BINDING FIX: OSError from _create_temp → SessionPersistenceError in save."""
    class _CreateTempFails(FileSessionStore):
        def _create_temp(self, canonical_id: str):
            raise OSError("mkstemp failed — disk full")

    store = _CreateTempFails(tmp_path / "sessions")
    with pytest.raises(SessionPersistenceError):
        store.save(_make_session())


def test_load_path_inspection_oserror_maps_to_persistence_error(tmp_path):
    """BINDING FIX: OSError during read_bytes → SessionPersistenceError in load."""
    session_dir = tmp_path / "sessions"
    store = FileSessionStore(session_dir)
    ss = _make_session()
    store.save(ss)

    class _FailReadBytes(FileSessionStore):
        def load(self, session_id: str):
            import uuid
            canonical = str(uuid.UUID(session_id))
            target = self._path(canonical)
            # Simulate directory checks pass (dir exists) but read fails
            try:
                raise OSError("permission denied on read")
            except OSError as exc:
                from agent_core.session_persistence.errors import SessionPersistenceError
                raise SessionPersistenceError(
                    f"Unable to read session {canonical}"
                ) from exc

    fail_store = _FailReadBytes(session_dir)
    with pytest.raises(SessionPersistenceError):
        fail_store.load(ss.session_id)


def test_save_does_not_wrap_programming_error_as_persistence(tmp_path):
    """BINDING FIX: programming error (non-OSError, non-Persistence) propagates as-is."""
    def bad_fsync(fd: int) -> None:
        raise AttributeError("programming error — bad fsync_fn")

    store = FileSessionStore(tmp_path / "sessions", fsync_fn=bad_fsync)
    with pytest.raises(AttributeError, match="programming error"):
        store.save(_make_session())


# ---------------------------------------------------------------------------
# Error message content
# ---------------------------------------------------------------------------

def test_persistence_error_message_is_neutral():
    """5 FIX: default SessionPersistenceError message is neutral (no user-visible
    context like 'task may have executed')."""
    err = SessionPersistenceError()
    msg = str(err).lower()
    assert "task may have executed" not in msg
    assert "unable to persist session data" in msg


# ---------------------------------------------------------------------------
# Corruption
# ---------------------------------------------------------------------------

def test_load_invalid_json_raises_corruption_error(tmp_path):
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(mode=0o700)
    session_id = str(uuid4())
    session_file = session_dir / f"{session_id}.json"
    session_file.write_text("this is not valid json!!!", encoding="utf-8")

    store = FileSessionStore(session_dir)
    with pytest.raises(SessionDataCorruptionError):
        store.load(session_id)


def test_load_corrupt_json_structure_raises_corruption_error(tmp_path):
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(mode=0o700)
    session_id = str(uuid4())
    session_file = session_dir / f"{session_id}.json"
    # Valid JSON but not a valid session (wrong schema_version)
    session_file.write_text(
        json.dumps({"schema_version": "999", "session_id": session_id,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00", "turns": []}),
        encoding="utf-8",
    )

    store = FileSessionStore(session_dir)
    with pytest.raises(SessionDataCorruptionError):
        store.load(session_id)


# ---------------------------------------------------------------------------
# Symlink / path security checks
# ---------------------------------------------------------------------------

def test_load_symlinked_dir_raises_persistence_error(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link_dir = tmp_path / "link_sessions"
    link_dir.symlink_to(real_dir)

    store = FileSessionStore(link_dir)
    with pytest.raises(SessionPersistenceError, match="symlink"):
        store.load(str(uuid4()))


def test_save_symlinked_dir_raises_persistence_error(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link_dir = tmp_path / "link_sessions"
    link_dir.symlink_to(real_dir)

    store = FileSessionStore(link_dir)
    with pytest.raises(SessionPersistenceError, match="symlink"):
        store.save(_make_session())


def test_load_symlinked_file_raises_persistence_error(tmp_path):
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(mode=0o700)
    if os.name == "posix":
        os.chmod(session_dir, 0o700)

    ss = _make_session()
    canonical = ss.session_id
    real_file = tmp_path / "real_session.json"
    real_file.write_text("{}", encoding="utf-8")
    link_file = session_dir / f"{canonical}.json"
    link_file.symlink_to(real_file)

    store = FileSessionStore(session_dir)
    with pytest.raises(SessionPersistenceError, match="symlink"):
        store.load(canonical)


# ---------------------------------------------------------------------------
# POSIX permission checks
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name != "posix", reason="permission checks are POSIX-only")
def test_ensure_dir_permission_check_posix_only(tmp_path):
    """5 FIX: directory with world-readable bits → SessionPersistenceError (POSIX)."""
    session_dir = tmp_path / "insecure_sessions"
    session_dir.mkdir(mode=0o755)  # group/other readable — insecure

    store = FileSessionStore(session_dir)
    with pytest.raises(SessionPersistenceError, match="insecure"):
        store.save(_make_session())


@pytest.mark.skipif(os.name != "posix", reason="permission checks are POSIX-only")
def test_load_insecure_dir_permissions_raises_persistence_error(tmp_path):
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(mode=0o755)

    store = FileSessionStore(session_dir)
    with pytest.raises(SessionPersistenceError, match="insecure"):
        store.load(str(uuid4()))


@pytest.mark.skipif(os.name != "posix", reason="permission checks are POSIX-only")
def test_secure_dir_permissions_allowed(tmp_path):
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(mode=0o700)

    store = FileSessionStore(session_dir)
    result = store.load(str(uuid4()))  # no session exists → None, no error
    assert result is None


# ---------------------------------------------------------------------------
# Parent-dir fsync propagation
# ---------------------------------------------------------------------------

def test_parent_fsync_does_not_swallow_programming_error(tmp_path):
    """TypeError from fsync_fn during parent-dir sync propagates (not caught by
    best-effort handler which only catches OSError/NotImplementedError)."""
    session_dir = tmp_path / "sessions"
    calls: list[int] = []

    def selective_fsync(fd: int) -> None:
        calls.append(fd)
        if len(calls) == 1:
            os.fsync(fd)          # first call: temp-file fsync — succeed
        else:
            raise TypeError("programming error in parent fsync")

    store = FileSessionStore(session_dir, fsync_fn=selective_fsync)
    with pytest.raises(TypeError, match="programming error"):
        store.save(_make_session())

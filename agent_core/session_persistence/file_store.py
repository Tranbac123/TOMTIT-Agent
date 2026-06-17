from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Callable

from agent_core.session_persistence.errors import (
    SessionDataCorruptionError,
    SessionPersistenceError,
)
from agent_core.session_persistence.serializer import SessionSerializer
from agent_core.state.session_state import SessionState

logger = logging.getLogger(__name__)


class FileSessionStore:
    """Single-writer, single-process file-per-session store.

    Each session is stored as an atomic JSON file under session_dir/.
    Default dir: .agent/sessions/
    """

    def __init__(
        self,
        session_dir: str | Path = ".agent/sessions",
        *,
        fsync_fn: Callable[[int], None] = os.fsync,
        replace_fn: Callable[[str | Path, str | Path], None] = os.replace,
    ) -> None:
        self._dir = Path(session_dir)
        self._fsync_fn = fsync_fn
        self._replace_fn = replace_fn

    # ------------------------------------------------------------------
    # Public protocol
    # ------------------------------------------------------------------

    def save(self, session: SessionState) -> None:
        document = SessionSerializer.to_dict(session)  # CorruptionError → passthrough
        payload = json.dumps(document, ensure_ascii=False).encode("utf-8")
        canonical = session.session_id
        target = self._path(canonical)
        temp_path: Path | None = None

        try:
            self._ensure_dir()
            fd, temp_path = self._create_temp(canonical)
            self._write_and_fsync_temp(fd, payload)
            # ── COMMIT BOUNDARY ──
            self._replace_fn(temp_path, target)
        except SessionDataCorruptionError:
            raise
        except SessionPersistenceError:
            raise
        except OSError as exc:
            raise SessionPersistenceError(
                f"Unable to persist session {canonical}"
            ) from exc
        # programming errors propagate — not caught, not wrapped
        finally:
            if temp_path is not None:
                self._cleanup_temp_best_effort(temp_path)

        self._fsync_parent_best_effort(self._dir)

    def load(self, session_id: str) -> SessionState | None:
        canonical = str(uuid.UUID(session_id))
        target = self._path(canonical)

        try:
            if not self._dir.exists():
                return None
            if self._dir.is_symlink():
                raise SessionPersistenceError(
                    f"session directory must not be a symlink: {self._dir}"
                )
            if not self._dir.is_dir():
                raise SessionPersistenceError(
                    f"session directory path is not a directory: {self._dir}"
                )
            if os.name == "posix":
                mode = stat.S_IMODE(self._dir.stat().st_mode)
                if mode & 0o077:
                    raise SessionPersistenceError(
                        f"session directory has insecure permissions "
                        f"{oct(mode)}: {self._dir}"
                    )
            if not target.exists():
                return None
            if target.is_symlink():
                raise SessionPersistenceError(
                    f"session file must not be a symlink: {target}"
                )
            if not target.is_file():
                raise SessionPersistenceError(
                    f"session file is not a regular file: {target}"
                )
            raw = target.read_bytes()
        except SessionPersistenceError:
            raise
        except OSError as exc:
            raise SessionPersistenceError(
                f"Unable to read session {canonical}"
            ) from exc

        # Parse OUTSIDE the I/O catch — data error ≠ I/O error
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SessionDataCorruptionError(
                f"Invalid JSON in session {canonical}"
            ) from exc

        return SessionSerializer.from_dict(data, expected_session_id=canonical)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _path(self, session_id: str) -> Path:
        canonical = str(uuid.UUID(session_id))
        return self._dir / f"{canonical}.json"

    def _ensure_dir(self) -> None:
        """Validate or create session directory with secure permissions."""
        if self._dir.is_symlink():
            raise SessionPersistenceError(
                f"session directory must not be a symlink: {self._dir}"
            )
        if self._dir.exists():
            if not self._dir.is_dir():
                raise SessionPersistenceError(
                    f"session directory path is not a directory: {self._dir}"
                )
            if os.name == "posix":
                mode = stat.S_IMODE(self._dir.stat().st_mode)
                if mode & 0o077:
                    raise SessionPersistenceError(
                        f"session directory has insecure permissions "
                        f"{oct(mode)}: {self._dir}"
                    )
        else:
            self._dir.mkdir(parents=True, mode=0o700)
            if os.name == "posix":
                os.chmod(self._dir, 0o700)  # enforce exact mode against umask

    def _create_temp(self, canonical_id: str) -> tuple[int, Path]:
        fd, raw = tempfile.mkstemp(
            dir=self._dir,
            prefix=f".{canonical_id}.",
            suffix=".tmp",
        )
        return fd, Path(raw)

    def _fdopen_temp(self, fd: int):  # protected test seam
        return os.fdopen(fd, "wb")

    def _write_and_fsync_temp(self, fd: int, data: bytes) -> None:
        from contextlib import closing

        try:
            file_obj = self._fdopen_temp(fd)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        with closing(file_obj):
            file_obj.write(data)
            file_obj.flush()
            self._fsync_fn(file_obj.fileno())

    def _cleanup_temp_best_effort(self, temp_path: Path) -> None:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Unable to remove temp %s: %s", temp_path, exc)

    def _fsync_parent_best_effort(self, directory: Path) -> None:
        dir_fd: int | None = None
        try:
            dir_fd = os.open(str(directory), os.O_RDONLY)
            self._fsync_fn(dir_fd)
        except (OSError, NotImplementedError) as exc:
            logger.warning("Parent dir fsync failed: %s", exc)
        finally:
            if dir_fd is not None:
                try:
                    os.close(dir_fd)
                except OSError:
                    pass

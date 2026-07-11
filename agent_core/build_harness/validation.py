"""P0-9A-R2 — strict identifier and repository-path validation (fail-closed).

One grammar per identifier class, shared by contracts, reports, the evidence store, and
the change gate. Invalid values are REJECTED, never sanitized — "a/b" must never silently
become the same namespace as "a_b".
"""
from __future__ import annotations

import re

# Task ids: filesystem-safe, collision-free single names. "." and ".." cannot match
# (first character must be alphanumeric); separators are simply not in the alphabet.
_RE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# Artifact names (roles, gate names, prompt/report slots).
_RE_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

_RE_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


class InvalidEvidenceIdentifierError(ValueError):
    """An identifier used in filesystem paths failed the strict grammar."""


class InvalidRepoPathError(ValueError):
    """A changed-file path is not a clean repository-relative path."""


def validate_task_id(value: object) -> str:
    if not isinstance(value, str) or not _RE_TASK_ID.match(value):
        raise InvalidEvidenceIdentifierError(
            f"invalid task_id {value!r}: must match [A-Za-z0-9][A-Za-z0-9._-]{{0,127}} "
            "(no separators, no traversal, no whitespace/control characters)"
        )
    return value


def is_valid_task_id(value: object) -> bool:
    return isinstance(value, str) and bool(_RE_TASK_ID.match(value))


def validate_artifact_name(value: object, *, kind: str = "artifact name") -> str:
    if not isinstance(value, str) or not _RE_ARTIFACT_NAME.match(value):
        raise InvalidEvidenceIdentifierError(
            f"invalid {kind} {value!r}: must match [A-Za-z0-9][A-Za-z0-9_-]{{0,63}}"
        )
    return value


def normalize_repo_path(path: object) -> str:
    """Canonicalize a repository-relative file path or raise InvalidRepoPathError.

    Accepts forward- or backslash-separated relative paths; returns the "/" form with a
    harmless leading "./" removed. Rejects empty values, absolute POSIX paths, Windows
    drive/UNC paths, NUL/control characters, and any ".." segment.
    """
    if not isinstance(path, str) or not path.strip():
        raise InvalidRepoPathError(f"empty or non-string path: {path!r}")
    raw = path.strip()
    if any(ord(ch) < 32 or ch == "\x7f" for ch in raw):
        raise InvalidRepoPathError(f"path contains control characters: {path!r}")
    if raw.startswith("\\\\"):
        raise InvalidRepoPathError(f"UNC path rejected: {path!r}")
    if _RE_WINDOWS_DRIVE.match(raw):
        raise InvalidRepoPathError(f"Windows drive path rejected: {path!r}")
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/"):
        raise InvalidRepoPathError(f"absolute path rejected: {path!r}")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    segments = [seg for seg in normalized.split("/") if seg not in ("", ".")]
    if not segments:
        raise InvalidRepoPathError(f"path resolves to nothing: {path!r}")
    if any(seg == ".." for seg in segments):
        raise InvalidRepoPathError(f"path traversal segment rejected: {path!r}")
    return "/".join(segments)

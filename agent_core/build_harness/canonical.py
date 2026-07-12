"""P0-9B1 — pure validation primitives + canonical serialization for Git-evidence domain.

No I/O, no clock, no git, no environment, no subprocess. Every helper is deterministic and
side-effect free. Validation is strict and NEVER coerces: a bool is not an int, a scalar is
not a list, an uppercase digest is not a digest. Malformed input raises P09BValidationError
identifying the model/field, not an unrelated Attribute/TypeError.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, TypeGuard

__all__ = [
    "P09BValidationError",
    "is_exact_type",
    "is_exact_str",
    "is_exact_bool",
    "is_exact_int",
    "is_exact_float",
    "is_exact_bytes",
    "is_exact_tuple",
    "is_exact_list",
    "is_exact_dict",
    "validate_task_id",
    "validate_generated_id",
    "validate_sha256_digest",
    "validate_git_object_sha",
    "validate_rfc3339_utc",
    "parse_rfc3339_utc",
    "validate_duration_ms",
    "validate_repo_path",
    "validate_working_directory",
    "validate_repository_root_hint",
    "validate_diagnostic_text",
    "reject_control_characters",
    "canonical_json_bytes",
    "sha256_digest_bytes",
    "canonical_digest",
    "changed_files_digest",
    "require_str",
    "require_int",
    "require_bool",
    "require_str_tuple",
    "require_sorted_unique_str_tuple",
]


class P09BValidationError(ValueError):
    """A P0-9B domain value failed strict validation. Message names the field path."""


def is_exact_type(value: object, expected: type) -> bool:
    """True only when ``value``'s type is EXACTLY ``expected`` — no subclass coercion.

    This is the single place the codebase's no-coercion rule lives: a bool is not an int,
    so ``is_exact_type(True, int)`` is False. ``isinstance`` would (wrongly) accept it.
    """
    return type(value) is expected  # noqa: E721 — exact type identity is intentional here


# Per-type exact guards. Each is a ``TypeGuard`` so a public trust boundary can reject a
# subclass (a malicious ``dict``/``tuple``/``str`` subclass whose ``items``/``__iter__``/
# behavior lies) WHILE mypy still narrows the value — reconciling B1-CODEX-002's exact-type
# rule with static typing. ``isinstance`` narrows but accepts subclasses; ``type() is`` is
# exact but does not narrow; a ``TypeGuard`` gives us both.
def is_exact_str(value: object) -> TypeGuard[str]:
    return type(value) is str  # noqa: E721 — exact type identity is intentional here


def is_exact_bool(value: object) -> TypeGuard[bool]:
    return type(value) is bool  # noqa: E721 — exact type identity is intentional here


def is_exact_int(value: object) -> TypeGuard[int]:
    # ``bool`` is an ``int`` subclass; exact-type identity excludes it (no coercion).
    return type(value) is int  # noqa: E721 — exact type identity is intentional here


def is_exact_float(value: object) -> TypeGuard[float]:
    return type(value) is float  # noqa: E721 — exact type identity is intentional here


def is_exact_bytes(value: object) -> TypeGuard[bytes]:
    return type(value) is bytes  # noqa: E721 — exact type identity is intentional here


def is_exact_tuple(value: object) -> TypeGuard[tuple[Any, ...]]:
    return type(value) is tuple  # noqa: E721 — exact type identity is intentional here


def is_exact_list(value: object) -> TypeGuard[list[Any]]:
    return type(value) is list  # noqa: E721 — exact type identity is intentional here


def is_exact_dict(value: object) -> TypeGuard[dict[Any, Any]]:
    return type(value) is dict  # noqa: E721 — exact type identity is intentional here


# --- identifier grammars ----------------------------------------------------
# Existing P0-9A task grammar (mixed case allowed; no lower-casing).
_RE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# New P0-9B generated ids: lowercase, digits, hyphen only.
_RE_GENERATED_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

_RE_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_RE_SHA1_HEX = re.compile(r"^[0-9a-f]{40}$")
_RE_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
# Strict UTC RFC3339 with exactly six fractional digits and a literal Z.
_RE_RFC3339_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"
)
_RFC3339_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_RE_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def _field(path: str) -> str:
    return path


def reject_control_characters(value: str, *, field: str) -> None:
    if any(ord(ch) < 32 or ch == "\x7f" for ch in value):
        raise P09BValidationError(f"{field} contains control characters")
    if "\x00" in value:
        raise P09BValidationError(f"{field} contains a NUL character")


def require_str(value: object, *, field: str, allow_empty: bool = False) -> str:
    # Exact str only: a str subclass with overridden behavior is rejected at the boundary.
    if not is_exact_str(value):
        raise P09BValidationError(f"{field} must be a string, got {type(value).__name__}")
    if not allow_empty and not value:
        raise P09BValidationError(f"{field} must be a non-empty string")
    return value


def require_int(value: object, *, field: str) -> int:
    # Exact int only: bool is an int subclass and is rejected (no coercion).
    if not is_exact_int(value):
        raise P09BValidationError(
            f"{field} must be an int (not bool/float/str), got {type(value).__name__}"
        )
    return value


def require_bool(value: object, *, field: str) -> bool:
    if not is_exact_bool(value):
        raise P09BValidationError(
            f"{field} must be a bool, got {type(value).__name__}"
        )
    return value


def require_str_tuple(value: object, *, field: str) -> tuple[str, ...]:
    # Exact tuple only: a tuple subclass whose ``__iter__`` lies is rejected here.
    if not is_exact_tuple(value):
        raise P09BValidationError(f"{field} must be a tuple, got {type(value).__name__}")
    for index, item in enumerate(value):
        require_str(item, field=f"{field}[{index}]")
    return value


def require_sorted_unique_str_tuple(value: object, *, field: str) -> tuple[str, ...]:
    """A SET-LIKE diagnostic tuple: exact tuple of non-empty, NUL/control-free strings that
    is already lexicographically sorted and duplicate-free.

    Malformed input is REJECTED, never silently sorted or deduped (B1-CODEX-009): a signed
    diagnostic set must not have order-sensitive or redundant encodings.
    """
    items = require_str_tuple(value, field=field)
    for index, item in enumerate(items):
        if not item:
            raise P09BValidationError(f"{field}[{index}] must be a non-empty string")
        reject_control_characters(item, field=f"{field}[{index}]")
    if list(items) != sorted(items):
        raise P09BValidationError(f"{field} must be lexicographically sorted")
    if len(set(items)) != len(items):
        raise P09BValidationError(f"{field} must not contain duplicate entries")
    return items


def validate_task_id(value: object, *, field: str = "task_id") -> str:
    text = require_str(value, field=field)
    if not _RE_TASK_ID.match(text):
        raise P09BValidationError(
            f"{field} {value!r} must match the P0-9A task grammar "
            "[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
        )
    return text


def validate_generated_id(value: object, *, field: str) -> str:
    text = require_str(value, field=field)
    if not _RE_GENERATED_ID.match(text):
        raise P09BValidationError(
            f"{field} {value!r} must match the generated-id grammar "
            "[a-z0-9][a-z0-9-]{0,63} (lowercase, digits, hyphen only)"
        )
    return text


def validate_sha256_digest(value: object, *, field: str) -> str:
    text = require_str(value, field=field)
    if not _RE_SHA256_DIGEST.match(text):
        raise P09BValidationError(
            f"{field} {value!r} must be 'sha256:' + 64 lowercase hex characters"
        )
    return text


def validate_git_object_sha(value: object, object_format: str, *, field: str) -> str:
    text = require_str(value, field=field)
    if object_format == "sha1":
        if not _RE_SHA1_HEX.match(text):
            raise P09BValidationError(
                f"{field} {value!r} must be 40 lowercase hex characters for a sha1 object"
            )
    elif object_format == "sha256":
        if not _RE_SHA256_HEX.match(text):
            raise P09BValidationError(
                f"{field} {value!r} must be 64 lowercase hex characters for a sha256 object"
            )
    else:
        raise P09BValidationError(
            f"{field}: unknown object_format {object_format!r}"
        )
    return text


def parse_rfc3339_utc(value: str) -> datetime:
    return datetime.strptime(value, _RFC3339_FORMAT).replace(tzinfo=timezone.utc)


def validate_rfc3339_utc(value: object, *, field: str) -> str:
    text = require_str(value, field=field)
    if not _RE_RFC3339_UTC.match(text):
        raise P09BValidationError(
            f"{field} {value!r} must be strict UTC RFC3339 "
            "YYYY-MM-DDTHH:MM:SS.ffffffZ"
        )
    try:
        parse_rfc3339_utc(text)  # rejects invalid calendar values
    except ValueError as exc:
        raise P09BValidationError(f"{field} {value!r} is not a valid timestamp: {exc}")
    return text


_DURATION_TOLERANCE_MS = 1.0  # versioned tolerance between declared duration and timestamps


def validate_duration_ms(
    duration_ms: int, started_at: str, completed_at: str, *, field: str = "duration_ms",
) -> None:
    """The declared millisecond duration must equal the UTC timestamp difference within a
    single, explicit tolerance. SHARED by every model that carries started/completed
    timestamps plus a duration (provenance, command execution), so the exact relationship is
    defined once (B1-CODEX-004). Callers validate the timestamp FORMAT and non-negativity
    first; this asserts the relationship.
    """
    start = parse_rfc3339_utc(started_at)
    end = parse_rfc3339_utc(completed_at)
    expected_ms = (end - start).total_seconds() * 1000.0
    if abs(duration_ms - expected_ms) > _DURATION_TOLERANCE_MS:
        raise P09BValidationError(
            f"{field} {duration_ms} disagrees with timestamps "
            f"({expected_ms:.3f}ms) by more than {_DURATION_TOLERANCE_MS:g}ms"
        )


def validate_repo_path(value: object, *, field: str) -> str:
    """Canonical repository-relative FILE path (mirrors the P0-9A change-gate policy).

    Reject every noncanonical spelling; NEVER normalize-and-retain. Backslash is not a
    separator (rejected outright, not converted to '/'), the string must already be NFC,
    and '.'/'..'/empty segments are rejected. Two spellings of one path (e.g. ``a/b`` and
    ``a\\b``) must never both survive validation → sort → dedup, so we reject rather than
    silently fold them together. The returned value is the input unchanged.
    """
    text = require_str(value, field=field)
    reject_control_characters(text, field=field)
    if "\\" in text:
        raise P09BValidationError(
            f"{field} {value!r}: backslash is not a path separator (canonical paths use '/')"
        )
    if _RE_WINDOWS_DRIVE.match(text):
        raise P09BValidationError(f"{field} {value!r}: Windows drive path rejected")
    if text.startswith("/"):
        raise P09BValidationError(f"{field} {value!r}: absolute path rejected")
    if unicodedata.normalize("NFC", text) != text:
        raise P09BValidationError(
            f"{field} {value!r}: path must already be NFC-normalized"
        )
    segments = text.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        raise P09BValidationError(
            f"{field} {value!r}: empty/'.'/'..' path segment rejected"
        )
    return text


def validate_working_directory(value: object, *, field: str) -> str:
    """'.' is explicitly valid; otherwise a canonical repository-relative directory path."""
    text = require_str(value, field=field)
    if text == ".":
        return "."
    return validate_repo_path(text, field=field)


def validate_repository_root_hint(value: object, *, field: str) -> str:
    """Diagnostic-only locator: non-empty, no NUL/control; may be absolute / contain spaces."""
    text = require_str(value, field=field)
    reject_control_characters(text, field=field)
    return text


def validate_diagnostic_text(value: object, *, field: str, max_len: int = 4096) -> str:
    text = require_str(value, field=field, allow_empty=True)
    if "\x00" in text:
        raise P09BValidationError(f"{field} contains a NUL character")
    if len(text) > max_len:
        raise P09BValidationError(f"{field} exceeds {max_len} characters")
    return text


# --- canonical serialization ------------------------------------------------

def _canonicalize(value: Any, *, path: str = "$") -> Any:
    """Return a JSON-safe, NFC-normalized structure or raise for unsupported inputs.

    Only EXACT built-in container/primitive types are accepted (B1-CODEX-002): a ``dict``/
    ``list``/``tuple``/``str``/``int``/``bool``/``float`` subclass whose iteration or key
    view can lie is rejected here rather than silently canonicalized. At every mapping depth,
    NFC-normalized keys are checked for collision BEFORE assignment (B1-CODEX-001) so
    ``{"é": 1, "é": 2}`` (in either insertion order, nested or not) is rejected instead
    of silently dropping one authorization value.
    """
    if isinstance(value, Enum):
        member_value = value.value
        if not is_exact_str(member_value):
            raise P09BValidationError(f"{path}: enum {value!r} value must be a string")
        return unicodedata.normalize("NFC", member_value)
    if value is None or is_exact_bool(value):
        return value
    if is_exact_int(value):
        return value
    if is_exact_float(value):
        if value != value or value in (float("inf"), float("-inf")):
            raise P09BValidationError(f"{path}: NaN/Infinity is not allowed")
        return value
    if is_exact_str(value):
        return unicodedata.normalize("NFC", value)
    if is_exact_list(value) or is_exact_tuple(value):
        return [_canonicalize(item, path=f"{path}[{i}]") for i, item in enumerate(value)]
    if is_exact_dict(value):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not is_exact_str(key):
                raise P09BValidationError(
                    f"{path}: object keys must be exact str, got {type(key).__name__}"
                )
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in result:
                raise P09BValidationError(
                    f"{path}: duplicate object key {normalized_key!r} after NFC normalization"
                )
            result[normalized_key] = _canonicalize(item, path=f"{path}.{key}")
        return result
    raise P09BValidationError(
        f"{path}: unsupported type for canonical serialization: {type(value).__name__}"
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Deterministic canonical JSON: UTF-8, NFC strings, sorted keys, compact, no NaN/Inf."""
    canonical = _canonicalize(value)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_digest_bytes(value: bytes) -> str:
    if not is_exact_bytes(value):
        raise P09BValidationError("sha256_digest_bytes expects bytes")
    return "sha256:" + sha256(value).hexdigest()


def canonical_digest(value: Any) -> str:
    """sha256 digest of the canonical JSON encoding of ``value``."""
    return sha256_digest_bytes(canonical_json_bytes(value))


def changed_files_digest(paths: tuple[str, ...]) -> str:
    """Digest of a changed-files collection under an explicit, versioned payload.

    The caller is responsible for supplying an already validated, sorted, deduped tuple;
    this payload shape is stable so identical file sets always digest identically.
    """
    return canonical_digest({
        "kind": "p0-9b.changed-files.v1",
        "paths": list(paths),
    })

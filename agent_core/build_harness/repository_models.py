"""P0-9B1 — closed enums + immutable repository/candidate/command domain models.

Pure domain: no git, no I/O, no clock. Each model validates the explicit facts supplied to
it and never inspects the environment. ``str, Enum`` is used (Python 3.11 target) so enum
members are their exact string values for canonical serialization.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from agent_core.build_harness.canonical import (
    P09BValidationError,
    canonical_digest,
    is_exact_type,
    changed_files_digest,
    require_bool,
    require_int,
    require_str_tuple,
    validate_generated_id,
    validate_git_object_sha,
    validate_repo_path,
    validate_repository_root_hint,
    validate_rfc3339_utc,
    validate_sha256_digest,
    validate_working_directory,
)

__all__ = [
    "GitObjectFormat",
    "DirtyState",
    "EvidenceSource",
    "VerificationStatus",
    "RepositoryInspectionErrorCode",
    "CommandExecutionErrorCode",
    "CandidateBinding",
    "RepositorySnapshot",
    "CommandRequirement",
]


class GitObjectFormat(str, Enum):
    SHA1 = "sha1"
    SHA256 = "sha256"


class DirtyState(str, Enum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"


class EvidenceSource(str, Enum):
    LOCAL_CONTROLLED_COLLECTOR = "LOCAL_CONTROLLED_COLLECTOR"
    IMPORTED_CLAIM = "IMPORTED_CLAIM"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    REPOSITORY_MISMATCH = "REPOSITORY_MISMATCH"
    COMMIT_MISMATCH = "COMMIT_MISMATCH"
    TREE_MISMATCH = "TREE_MISMATCH"
    DIRTY_WORKTREE = "DIRTY_WORKTREE"
    COMMAND_MISMATCH = "COMMAND_MISMATCH"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    SNAPSHOT_CHANGED = "SNAPSHOT_CHANGED"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    INVALID_PROVENANCE = "INVALID_PROVENANCE"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
    UNSUPPORTED_COLLECTOR = "UNSUPPORTED_COLLECTOR"
    INSPECTION_FAILED = "INSPECTION_FAILED"


class RepositoryInspectionErrorCode(str, Enum):
    GIT_UNAVAILABLE = "GIT_UNAVAILABLE"
    NOT_A_REPOSITORY = "NOT_A_REPOSITORY"
    TIMEOUT = "TIMEOUT"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    UNBORN_BRANCH = "UNBORN_BRANCH"
    REPOSITORY_CHANGED = "REPOSITORY_CHANGED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SUBMODULE_UNSUPPORTED = "SUBMODULE_UNSUPPORTED"
    PATH_MISSING = "PATH_MISSING"
    CANDIDATE_MISSING = "CANDIDATE_MISSING"
    CANDIDATE_NOT_HEAD = "CANDIDATE_NOT_HEAD"
    BASE_NOT_ANCESTOR = "BASE_NOT_ANCESTOR"
    DIRTY_WORKTREE = "DIRTY_WORKTREE"
    UNKNOWN_GIT_FAILURE = "UNKNOWN_GIT_FAILURE"


class CommandExecutionErrorCode(str, Enum):
    EXECUTABLE_UNAVAILABLE = "EXECUTABLE_UNAVAILABLE"
    INVALID_WORKING_DIRECTORY = "INVALID_WORKING_DIRECTORY"
    TIMEOUT = "TIMEOUT"
    OUTPUT_LIMIT_EXCEEDED = "OUTPUT_LIMIT_EXCEEDED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INTERRUPTED = "INTERRUPTED"
    FAILED_TO_START = "FAILED_TO_START"
    UNKNOWN_EXECUTION_FAILURE = "UNKNOWN_EXECUTION_FAILURE"


def _require_schema(value: object, expected: str, *, field: str = "schema_version") -> str:
    if not isinstance(value, str) or value != expected:
        raise P09BValidationError(f"{field} must be exactly {expected!r}, got {value!r}")
    return value


def _enum(value: object, enum_cls: type[Enum], *, field: str) -> Any:
    if isinstance(value, enum_cls):
        return value
    # Exact string membership only — no case-variant normalization.
    if is_exact_type(value, str):
        for member in enum_cls:
            if member.value == value:
                return member
    raise P09BValidationError(
        f"{field} {value!r} is not a valid {enum_cls.__name__}"
    )


def _require_mapping(data: object, *, model: str) -> dict:
    if not isinstance(data, dict):
        raise P09BValidationError(f"{model}: root must be a mapping")
    return data


def _require_exact_keys(data: dict, required: frozenset[str], *, model: str) -> None:
    keys = set(data)
    missing = sorted(required - keys)
    unknown = sorted(keys - required)
    if missing:
        raise P09BValidationError(f"{model}: missing field(s) {missing}")
    if unknown:
        raise P09BValidationError(f"{model}: unknown field(s) {unknown}")


def _tuple_from_json_list(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise P09BValidationError(f"{field} must be a JSON list")
    return tuple(value)


# ---------------------------------------------------------------------------
# CandidateBinding
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CandidateBinding:
    schema_version: str
    repository_id: str
    object_format: GitObjectFormat
    base_commit_sha: str
    candidate_commit_sha: str
    candidate_tree_sha: str
    contract_digest: str
    changed_files_digest: str

    SCHEMA_VERSION = "p0-9b.candidate-binding.v1"
    _KEYS = frozenset({
        "schema_version", "repository_id", "object_format", "base_commit_sha",
        "candidate_commit_sha", "candidate_tree_sha", "contract_digest",
        "changed_files_digest",
    })

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, self.SCHEMA_VERSION)
        validate_sha256_digest(self.repository_id, field="repository_id")
        object.__setattr__(
            self, "object_format", _enum(self.object_format, GitObjectFormat, field="object_format")
        )
        fmt = self.object_format.value
        validate_git_object_sha(self.base_commit_sha, fmt, field="base_commit_sha")
        validate_git_object_sha(self.candidate_commit_sha, fmt, field="candidate_commit_sha")
        validate_git_object_sha(self.candidate_tree_sha, fmt, field="candidate_tree_sha")
        validate_sha256_digest(self.contract_digest, field="contract_digest")
        validate_sha256_digest(self.changed_files_digest, field="changed_files_digest")

    def to_json_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "repository_id": self.repository_id,
            "object_format": self.object_format.value,
            "base_commit_sha": self.base_commit_sha,
            "candidate_commit_sha": self.candidate_commit_sha,
            "candidate_tree_sha": self.candidate_tree_sha,
            "contract_digest": self.contract_digest,
            "changed_files_digest": self.changed_files_digest,
        }

    @classmethod
    def from_json_dict(cls, data: object) -> "CandidateBinding":
        d = _require_mapping(data, model="CandidateBinding")
        _require_exact_keys(d, cls._KEYS, model="CandidateBinding")
        return cls(
            schema_version=d["schema_version"],
            repository_id=d["repository_id"],
            object_format=_enum(d["object_format"], GitObjectFormat, field="object_format"),
            base_commit_sha=d["base_commit_sha"],
            candidate_commit_sha=d["candidate_commit_sha"],
            candidate_tree_sha=d["candidate_tree_sha"],
            contract_digest=d["contract_digest"],
            changed_files_digest=d["changed_files_digest"],
        )


# ---------------------------------------------------------------------------
# RepositorySnapshot
# ---------------------------------------------------------------------------

def _validate_sorted_unique_paths(paths: tuple[str, ...], *, field: str) -> None:
    require_str_tuple(paths, field=field)
    for p in paths:
        validate_repo_path(p, field=field)
    if list(paths) != sorted(paths):
        raise P09BValidationError(f"{field} must be lexicographically sorted")
    if len(set(paths)) != len(paths):
        raise P09BValidationError(f"{field} must not contain duplicates")


@dataclass(frozen=True)
class RepositorySnapshot:
    schema_version: str
    snapshot_id: str
    repository_id: str
    repository_root_hint: str
    object_format: GitObjectFormat
    head_commit_sha: str
    head_tree_sha: str
    base_commit_sha: str
    branch_name: str | None
    detached_head: bool
    staged_changes: tuple[str, ...]
    unstaged_changes: tuple[str, ...]
    untracked_files: tuple[str, ...]
    submodule_changes: tuple[str, ...]
    changed_files: tuple[str, ...]
    changed_files_digest: str
    is_release_clean: bool
    captured_at: str
    inspector_version: str

    SCHEMA_VERSION = "p0-9b.repository-snapshot.v1"
    _KEYS = frozenset({
        "schema_version", "snapshot_id", "repository_id", "repository_root_hint",
        "object_format", "head_commit_sha", "head_tree_sha", "base_commit_sha",
        "branch_name", "detached_head", "staged_changes", "unstaged_changes",
        "untracked_files", "submodule_changes", "changed_files", "changed_files_digest",
        "is_release_clean", "captured_at", "inspector_version",
    })

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, self.SCHEMA_VERSION)
        validate_generated_id(self.snapshot_id, field="snapshot_id")
        validate_sha256_digest(self.repository_id, field="repository_id")
        validate_repository_root_hint(self.repository_root_hint, field="repository_root_hint")
        object.__setattr__(
            self, "object_format", _enum(self.object_format, GitObjectFormat, field="object_format")
        )
        fmt = self.object_format.value
        validate_git_object_sha(self.head_commit_sha, fmt, field="head_commit_sha")
        validate_git_object_sha(self.head_tree_sha, fmt, field="head_tree_sha")
        validate_git_object_sha(self.base_commit_sha, fmt, field="base_commit_sha")
        require_bool(self.detached_head, field="detached_head")
        if self.detached_head:
            if self.branch_name is not None:
                raise P09BValidationError("detached_head=True requires branch_name=None")
        else:
            if not is_exact_type(self.branch_name, str) or not self.branch_name:
                raise P09BValidationError(
                    "detached_head=False requires a non-empty branch_name"
                )
        for field in ("staged_changes", "unstaged_changes", "untracked_files",
                      "submodule_changes", "changed_files"):
            _validate_sorted_unique_paths(getattr(self, field), field=field)
        validate_sha256_digest(self.changed_files_digest, field="changed_files_digest")
        expected = changed_files_digest(self.changed_files)
        if self.changed_files_digest != expected:
            raise P09BValidationError(
                "changed_files_digest does not match changed_files"
            )
        require_bool(self.is_release_clean, field="is_release_clean")
        computed_clean = (
            not self.staged_changes and not self.unstaged_changes
            and not self.untracked_files and not self.submodule_changes
        )
        if self.is_release_clean != computed_clean:
            raise P09BValidationError(
                "is_release_clean must equal (no staged/unstaged/untracked/submodule changes)"
            )
        validate_rfc3339_utc(self.captured_at, field="captured_at")
        require_str_tuple((self.inspector_version,), field="inspector_version")
        if not self.inspector_version:
            raise P09BValidationError("inspector_version must be a non-empty string")

    def to_json_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "repository_id": self.repository_id,
            "repository_root_hint": self.repository_root_hint,
            "object_format": self.object_format.value,
            "head_commit_sha": self.head_commit_sha,
            "head_tree_sha": self.head_tree_sha,
            "base_commit_sha": self.base_commit_sha,
            "branch_name": self.branch_name,
            "detached_head": self.detached_head,
            "staged_changes": list(self.staged_changes),
            "unstaged_changes": list(self.unstaged_changes),
            "untracked_files": list(self.untracked_files),
            "submodule_changes": list(self.submodule_changes),
            "changed_files": list(self.changed_files),
            "changed_files_digest": self.changed_files_digest,
            "is_release_clean": self.is_release_clean,
            "captured_at": self.captured_at,
            "inspector_version": self.inspector_version,
        }

    @classmethod
    def from_json_dict(cls, data: object) -> "RepositorySnapshot":
        d = _require_mapping(data, model="RepositorySnapshot")
        _require_exact_keys(d, cls._KEYS, model="RepositorySnapshot")
        branch = d["branch_name"]
        if branch is not None and not is_exact_type(branch, str):
            raise P09BValidationError("branch_name must be a string or null")
        return cls(
            schema_version=d["schema_version"],
            snapshot_id=d["snapshot_id"],
            repository_id=d["repository_id"],
            repository_root_hint=d["repository_root_hint"],
            object_format=_enum(d["object_format"], GitObjectFormat, field="object_format"),
            head_commit_sha=d["head_commit_sha"],
            head_tree_sha=d["head_tree_sha"],
            base_commit_sha=d["base_commit_sha"],
            branch_name=branch,
            detached_head=d["detached_head"],
            staged_changes=_tuple_from_json_list(d["staged_changes"], field="staged_changes"),
            unstaged_changes=_tuple_from_json_list(d["unstaged_changes"], field="unstaged_changes"),
            untracked_files=_tuple_from_json_list(d["untracked_files"], field="untracked_files"),
            submodule_changes=_tuple_from_json_list(d["submodule_changes"], field="submodule_changes"),
            changed_files=_tuple_from_json_list(d["changed_files"], field="changed_files"),
            changed_files_digest=d["changed_files_digest"],
            is_release_clean=d["is_release_clean"],
            captured_at=d["captured_at"],
            inspector_version=d["inspector_version"],
        )


# ---------------------------------------------------------------------------
# CommandRequirement
# ---------------------------------------------------------------------------

def command_requirement_payload(
    argv: tuple[str, ...], working_directory: str, timeout_seconds: int
) -> dict:
    """Explicit canonical payload for the command digest (excludes the digest itself)."""
    return {
        "kind": "p0-9b.command-requirement-payload.v1",
        "argv": list(argv),
        "working_directory": working_directory,
        "timeout_seconds": timeout_seconds,
    }


def _validate_argv(argv: object, *, field: str = "argv") -> tuple[str, ...]:
    if not isinstance(argv, tuple):
        raise P09BValidationError(f"{field} must be a tuple")
    if not argv:
        raise P09BValidationError(f"{field} must be a non-empty tuple")
    for index, arg in enumerate(argv):
        if not isinstance(arg, str) or not arg:
            raise P09BValidationError(f"{field}[{index}] must be a non-empty string")
        if any(ord(ch) < 32 or ch == "\x7f" or ch == "\x00" for ch in arg):
            raise P09BValidationError(f"{field}[{index}] contains NUL/control characters")
    return argv


@dataclass(frozen=True)
class CommandRequirement:
    schema_version: str
    requirement_id: str
    argv: tuple[str, ...]
    working_directory: str
    timeout_seconds: int
    command_digest: str

    SCHEMA_VERSION = "p0-9b.command-requirement.v1"
    _KEYS = frozenset({
        "schema_version", "requirement_id", "argv", "working_directory",
        "timeout_seconds", "command_digest",
    })

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, self.SCHEMA_VERSION)
        validate_generated_id(self.requirement_id, field="requirement_id")
        _validate_argv(self.argv)
        validate_working_directory(self.working_directory, field="working_directory")
        require_int(self.timeout_seconds, field="timeout_seconds")
        if not (1 <= self.timeout_seconds <= 3600):
            raise P09BValidationError("timeout_seconds must be in 1..3600")
        validate_sha256_digest(self.command_digest, field="command_digest")
        expected = canonical_digest(
            command_requirement_payload(self.argv, self.working_directory, self.timeout_seconds)
        )
        if self.command_digest != expected:
            raise P09BValidationError("command_digest does not match argv/cwd/timeout")

    def to_json_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "requirement_id": self.requirement_id,
            "argv": list(self.argv),
            "working_directory": self.working_directory,
            "timeout_seconds": self.timeout_seconds,
            "command_digest": self.command_digest,
        }

    @classmethod
    def from_json_dict(cls, data: object) -> "CommandRequirement":
        d = _require_mapping(data, model="CommandRequirement")
        _require_exact_keys(d, cls._KEYS, model="CommandRequirement")
        return cls(
            schema_version=d["schema_version"],
            requirement_id=d["requirement_id"],
            argv=_tuple_from_json_list(d["argv"], field="argv"),
            working_directory=d["working_directory"],
            timeout_seconds=d["timeout_seconds"],
            command_digest=d["command_digest"],
        )

"""P0-9B1 — narrow ports (Protocols) + immutable request/result/error port models.

Protocols only: no adapter, no subprocess, no git, no network, no filesystem persistence is
implemented here. Adapters land in later slices behind these boundaries. All request/result
models are immutable and validate their explicit inputs; process execution never happens in
B1.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Protocol, TypeVar, runtime_checkable

from agent_core.build_harness.canonical import (
    P09BValidationError,
    is_exact_type,
    parse_rfc3339_utc,
    require_bool,
    require_int,
    require_str,
    reject_control_characters,
    validate_diagnostic_text,
    validate_generated_id,
    validate_git_object_sha,
    validate_rfc3339_utc,
    validate_repository_root_hint,
    validate_task_id,
    validate_working_directory,
)
from agent_core.build_harness.repository_models import (
    CandidateBinding,
    CommandExecutionErrorCode,
    CommandRequirement,
    GitObjectFormat,
    RepositoryInspectionErrorCode,
    RepositorySnapshot,
    _enum,
    _validate_argv,
)
from agent_core.build_harness.provenance import (
    CollectedCommandEvidence,
    EvidenceVerificationBundle,
)

__all__ = [
    "Outcome",
    "RepositoryInspectionRequest",
    "RepositoryInspectionError",
    "CommandExecutionSpec",
    "CommandExecutionResult",
    "CommandExecutionError",
    "EvidenceVerificationRequest",
    "EvidenceRunRecord",
    "RepositoryInspector",
    "CommandRunner",
    "EvidenceVerifier",
    "Clock",
    "RunIdGenerator",
    "EvidenceRepository",
]

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True)
class Outcome(Generic[T, E]):
    """Immutable success/failure result. EXACTLY one of value/error is non-None.

    Success is determined by which slot is set, never by truthiness of ``value``.
    """
    value: T | None = None
    error: E | None = None

    def __post_init__(self) -> None:
        if (self.value is None) == (self.error is None):
            raise P09BValidationError(
                "Outcome must have exactly one of value/error set (not both, not neither)"
            )

    @property
    def is_success(self) -> bool:
        return self.error is None

    @classmethod
    def success(cls, value: T) -> "Outcome[T, E]":
        if value is None:
            raise P09BValidationError("Outcome.success requires a non-None value")
        return cls(value=value, error=None)

    @classmethod
    def failure(cls, error: E) -> "Outcome[T, E]":
        if error is None:
            raise P09BValidationError("Outcome.failure requires a non-None error")
        return cls(value=None, error=error)


# ---------------------------------------------------------------------------
# Repository inspection port models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RepositoryInspectionRequest:
    """An untrusted repository locator + the candidate/base commits to inspect."""
    repository_path: str
    candidate_commit_sha: str
    base_commit_sha: str
    object_format: GitObjectFormat = GitObjectFormat.SHA1

    def __post_init__(self) -> None:
        validate_repository_root_hint(self.repository_path, field="repository_path")
        object.__setattr__(
            self, "object_format", _enum(self.object_format, GitObjectFormat, field="object_format")
        )
        fmt = self.object_format.value
        validate_git_object_sha(self.candidate_commit_sha, fmt, field="candidate_commit_sha")
        validate_git_object_sha(self.base_commit_sha, fmt, field="base_commit_sha")


@dataclass(frozen=True)
class RepositoryInspectionError:
    code: RepositoryInspectionErrorCode
    message: str
    command: tuple[str, ...] | None = None
    stderr_excerpt: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "code", _enum(self.code, RepositoryInspectionErrorCode, field="code")
        )
        require_str(self.message, field="message")
        if self.command is not None:
            _validate_argv(self.command, field="command")
        validate_diagnostic_text(self.stderr_excerpt, field="stderr_excerpt")


# ---------------------------------------------------------------------------
# Command execution port models
# ---------------------------------------------------------------------------

def _validate_environment(env: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(env, tuple):
        raise P09BValidationError("environment must be a tuple of (key, value) tuples")
    seen: set[str] = set()
    for index, pair in enumerate(env):
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise P09BValidationError(f"environment[{index}] must be a (key, value) tuple")
        key, value = pair
        require_str(key, field=f"environment[{index}].key")
        require_str(value, field=f"environment[{index}].value", allow_empty=True)
        reject_control_characters(key, field=f"environment[{index}].key")
        reject_control_characters(value, field=f"environment[{index}].value")
        seen.add(key)
    if list(env) != sorted(env):
        raise P09BValidationError("environment must be sorted by key/value")
    if len(seen) != len(env):
        raise P09BValidationError("environment keys must be unique")
    return env


@dataclass(frozen=True)
class CommandExecutionSpec:
    argv: tuple[str, ...]
    repository_root: str
    working_directory: str
    timeout_seconds: int
    max_stdout_bytes: int
    max_stderr_bytes: int
    environment: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _validate_argv(self.argv)
        validate_repository_root_hint(self.repository_root, field="repository_root")
        validate_working_directory(self.working_directory, field="working_directory")
        require_int(self.timeout_seconds, field="timeout_seconds")
        if not (1 <= self.timeout_seconds <= 3600):
            raise P09BValidationError("timeout_seconds must be in 1..3600")
        for name in ("max_stdout_bytes", "max_stderr_bytes"):
            value = getattr(self, name)
            require_int(value, field=name)
            if value <= 0:
                raise P09BValidationError(f"{name} must be a positive int")
        _validate_environment(self.environment)


@dataclass(frozen=True)
class CommandExecutionResult:
    argv: tuple[str, ...]
    exit_code: int | None
    completed: bool
    timed_out: bool
    interrupted: bool
    started_at: str
    completed_at: str
    duration_ms: int
    stdout: bytes
    stderr: bytes

    def __post_init__(self) -> None:
        _validate_argv(self.argv)
        if self.exit_code is not None:
            require_int(self.exit_code, field="exit_code")
        require_bool(self.completed, field="completed")
        require_bool(self.timed_out, field="timed_out")
        require_bool(self.interrupted, field="interrupted")
        if self.completed and self.exit_code is None:
            raise P09BValidationError("completed=True requires an integer exit_code")
        if self.completed and (self.timed_out or self.interrupted):
            raise P09BValidationError("completed=True is inconsistent with timed_out/interrupted")
        validate_rfc3339_utc(self.started_at, field="started_at")
        validate_rfc3339_utc(self.completed_at, field="completed_at")
        if parse_rfc3339_utc(self.completed_at) < parse_rfc3339_utc(self.started_at):
            raise P09BValidationError("completed_at must be >= started_at")
        require_int(self.duration_ms, field="duration_ms")
        if self.duration_ms < 0:
            raise P09BValidationError("duration_ms must be non-negative")
        if not is_exact_type(self.stdout, bytes) or not is_exact_type(self.stderr, bytes):
            raise P09BValidationError("stdout and stderr must be bytes")


@dataclass(frozen=True)
class CommandExecutionError:
    code: CommandExecutionErrorCode
    message: str
    stderr_excerpt: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "code", _enum(self.code, CommandExecutionErrorCode, field="code")
        )
        require_str(self.message, field="message")
        validate_diagnostic_text(self.stderr_excerpt, field="stderr_excerpt")


# ---------------------------------------------------------------------------
# Verifier request + run record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceVerificationRequest:
    """Explicit, self-contained inputs for a future PURE verifier.

    No repository path lookup, no Clock call, no Git call, no mutable store.
    """
    task_id: str
    requirements: tuple[CommandRequirement, ...]
    candidate_binding: CandidateBinding
    collected_evidence: tuple[CollectedCommandEvidence, ...]
    current_snapshot: RepositorySnapshot
    verifier_version: str
    verified_at: str

    def __post_init__(self) -> None:
        validate_task_id(self.task_id, field="task_id")
        if not is_exact_type(self.requirements, tuple):
            raise P09BValidationError("requirements must be a tuple")
        for r in self.requirements:
            if not isinstance(r, CommandRequirement):
                raise P09BValidationError("requirements must contain CommandRequirement")
        if not isinstance(self.candidate_binding, CandidateBinding):
            raise P09BValidationError("candidate_binding must be a CandidateBinding")
        if not is_exact_type(self.collected_evidence, tuple):
            raise P09BValidationError("collected_evidence must be a tuple")
        for c in self.collected_evidence:
            if not isinstance(c, CollectedCommandEvidence):
                raise P09BValidationError(
                    "collected_evidence must contain CollectedCommandEvidence"
                )
        if not isinstance(self.current_snapshot, RepositorySnapshot):
            raise P09BValidationError("current_snapshot must be a RepositorySnapshot")
        require_str(self.verifier_version, field="verifier_version")
        validate_rfc3339_utc(self.verified_at, field="verified_at")


@dataclass(frozen=True)
class EvidenceRunRecord:
    """Immutable link between a task/run, its collected evidence, final snapshot, and an
    optional verification bundle. Persistence behavior is defined by adapters, not here."""
    schema_version: str
    task_id: str
    run_id: str
    collected_evidence: tuple[CollectedCommandEvidence, ...]
    final_snapshot: RepositorySnapshot
    verification_bundle: EvidenceVerificationBundle | None

    SCHEMA_VERSION = "p0-9b.evidence-run-record.v1"

    def __post_init__(self) -> None:
        if not is_exact_type(self.schema_version, str) or self.schema_version != self.SCHEMA_VERSION:
            raise P09BValidationError(
                f"schema_version must be {self.SCHEMA_VERSION!r}"
            )
        validate_task_id(self.task_id, field="task_id")
        validate_generated_id(self.run_id, field="run_id")
        if not is_exact_type(self.collected_evidence, tuple):
            raise P09BValidationError("collected_evidence must be a tuple")
        for c in self.collected_evidence:
            if not isinstance(c, CollectedCommandEvidence):
                raise P09BValidationError(
                    "collected_evidence must contain CollectedCommandEvidence"
                )
        if not isinstance(self.final_snapshot, RepositorySnapshot):
            raise P09BValidationError("final_snapshot must be a RepositorySnapshot")
        if self.verification_bundle is not None and not isinstance(
            self.verification_bundle, EvidenceVerificationBundle
        ):
            raise P09BValidationError(
                "verification_bundle must be an EvidenceVerificationBundle or None"
            )


# ---------------------------------------------------------------------------
# Protocols (structural interfaces only)
# ---------------------------------------------------------------------------

@runtime_checkable
class RepositoryInspector(Protocol):
    def inspect(
        self, request: RepositoryInspectionRequest,
    ) -> Outcome[RepositorySnapshot, RepositoryInspectionError]:
        ...


@runtime_checkable
class CommandRunner(Protocol):
    def run(
        self, spec: CommandExecutionSpec,
    ) -> Outcome[CommandExecutionResult, CommandExecutionError]:
        ...


@runtime_checkable
class EvidenceVerifier(Protocol):
    def verify_run(
        self, request: EvidenceVerificationRequest,
    ) -> EvidenceVerificationBundle:
        ...


@runtime_checkable
class Clock(Protocol):
    def now_utc(self) -> datetime:
        ...


@runtime_checkable
class RunIdGenerator(Protocol):
    def new_run_id(self) -> str:
        ...

    def new_evidence_id(self) -> str:
        ...


@runtime_checkable
class EvidenceRepository(Protocol):
    def save_run(self, record: EvidenceRunRecord) -> None:
        ...

    def load_run(self, task_id: str, run_id: str) -> EvidenceRunRecord | None:
        ...

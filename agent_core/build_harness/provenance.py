"""P0-9B1 — collected provenance, verification results, and the verified bundle.

Pure domain. These models validate explicit facts and cross-field consistency only; they
NEVER decide whether evidence is "verified" — that is the future EvidenceVerifier service's
job. A digest field is always validated against a canonical payload that excludes itself, so
a correctly shaped but incorrect digest is detected.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent_core.build_harness.canonical import (
    P09BValidationError,
    canonical_digest,
    is_exact_type,
    parse_rfc3339_utc,
    require_bool,
    require_int,
    require_str,
    require_str_tuple,
    validate_generated_id,
    validate_git_object_sha,
    validate_rfc3339_utc,
    validate_sha256_digest,
    validate_task_id,
    validate_working_directory,
)
from agent_core.build_harness.repository_models import (
    CandidateBinding,
    DirtyState,
    EvidenceSource,
    GitObjectFormat,
    RepositorySnapshot,
    VerificationStatus,
    _enum,
    _require_exact_keys,
    _require_mapping,
    _require_schema,
    _tuple_from_json_list,
    _validate_argv,
)

__all__ = [
    "EvidenceProvenance",
    "CollectedCommandEvidence",
    "EvidenceVerificationResult",
    "VerifiedCommandEvidence",
    "EvidenceVerificationBundle",
]


# ---------------------------------------------------------------------------
# EvidenceProvenance
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceProvenance:
    schema_version: str
    evidence_id: str
    task_id: str
    run_id: str
    collector_id: str
    collector_version: str
    requirement_id: str
    argv: tuple[str, ...]
    working_directory: str
    command_digest: str
    exit_code: int | None
    completed: bool
    started_at: str
    completed_at: str
    duration_ms: int
    repository_id: str
    object_format: GitObjectFormat
    base_commit_sha: str
    commit_sha: str
    tree_sha: str
    pre_snapshot_id: str
    post_snapshot_id: str
    dirty_state: DirtyState
    changed_files_digest: str
    stdout_digest: str
    stderr_digest: str
    artifact_digest: str | None
    source: EvidenceSource

    SCHEMA_VERSION = "p0-9b.provenance.v1"
    _KEYS = frozenset({
        "schema_version", "evidence_id", "task_id", "run_id", "collector_id",
        "collector_version", "requirement_id", "argv", "working_directory",
        "command_digest", "exit_code", "completed", "started_at", "completed_at",
        "duration_ms", "repository_id", "object_format", "base_commit_sha",
        "commit_sha", "tree_sha", "pre_snapshot_id", "post_snapshot_id", "dirty_state",
        "changed_files_digest", "stdout_digest", "stderr_digest", "artifact_digest",
        "source",
    })

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, self.SCHEMA_VERSION)
        validate_generated_id(self.evidence_id, field="evidence_id")
        validate_task_id(self.task_id, field="task_id")
        validate_generated_id(self.run_id, field="run_id")
        validate_generated_id(self.collector_id, field="collector_id")
        require_str(self.collector_version, field="collector_version")
        validate_generated_id(self.requirement_id, field="requirement_id")
        _validate_argv(self.argv)
        validate_working_directory(self.working_directory, field="working_directory")
        # command_digest binds argv/cwd/timeout; provenance keeps no timeout, so the digest
        # is validated as a well-formed sha256 (its binding is checked against the matched
        # CommandRequirement by the verifier). Format-validate here.
        validate_sha256_digest(self.command_digest, field="command_digest")

        if self.exit_code is not None:
            require_int(self.exit_code, field="exit_code")
        require_bool(self.completed, field="completed")
        if self.completed and self.exit_code is None:
            raise P09BValidationError("completed=True requires an integer exit_code")

        validate_rfc3339_utc(self.started_at, field="started_at")
        validate_rfc3339_utc(self.completed_at, field="completed_at")
        start = parse_rfc3339_utc(self.started_at)
        end = parse_rfc3339_utc(self.completed_at)
        if end < start:
            raise P09BValidationError("completed_at must be >= started_at")
        require_int(self.duration_ms, field="duration_ms")
        if self.duration_ms < 0:
            raise P09BValidationError("duration_ms must be non-negative")
        expected_ms = (end - start).total_seconds() * 1000.0
        if abs(self.duration_ms - expected_ms) > 1.0:
            raise P09BValidationError(
                f"duration_ms {self.duration_ms} disagrees with timestamps "
                f"({expected_ms:.3f}ms) by more than 1ms"
            )

        validate_sha256_digest(self.repository_id, field="repository_id")
        object.__setattr__(
            self, "object_format", _enum(self.object_format, GitObjectFormat, field="object_format")
        )
        fmt = self.object_format.value
        validate_git_object_sha(self.base_commit_sha, fmt, field="base_commit_sha")
        validate_git_object_sha(self.commit_sha, fmt, field="commit_sha")
        validate_git_object_sha(self.tree_sha, fmt, field="tree_sha")
        validate_generated_id(self.pre_snapshot_id, field="pre_snapshot_id")
        validate_generated_id(self.post_snapshot_id, field="post_snapshot_id")
        object.__setattr__(self, "dirty_state", _enum(self.dirty_state, DirtyState, field="dirty_state"))
        object.__setattr__(self, "source", _enum(self.source, EvidenceSource, field="source"))
        validate_sha256_digest(self.changed_files_digest, field="changed_files_digest")
        validate_sha256_digest(self.stdout_digest, field="stdout_digest")
        validate_sha256_digest(self.stderr_digest, field="stderr_digest")
        if self.artifact_digest is not None:
            validate_sha256_digest(self.artifact_digest, field="artifact_digest")

    def to_json_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "collector_id": self.collector_id,
            "collector_version": self.collector_version,
            "requirement_id": self.requirement_id,
            "argv": list(self.argv),
            "working_directory": self.working_directory,
            "command_digest": self.command_digest,
            "exit_code": self.exit_code,
            "completed": self.completed,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "repository_id": self.repository_id,
            "object_format": self.object_format.value,
            "base_commit_sha": self.base_commit_sha,
            "commit_sha": self.commit_sha,
            "tree_sha": self.tree_sha,
            "pre_snapshot_id": self.pre_snapshot_id,
            "post_snapshot_id": self.post_snapshot_id,
            "dirty_state": self.dirty_state.value,
            "changed_files_digest": self.changed_files_digest,
            "stdout_digest": self.stdout_digest,
            "stderr_digest": self.stderr_digest,
            "artifact_digest": self.artifact_digest,
            "source": self.source.value,
        }

    @classmethod
    def from_json_dict(cls, data: object) -> "EvidenceProvenance":
        d = _require_mapping(data, model="EvidenceProvenance")
        _require_exact_keys(d, cls._KEYS, model="EvidenceProvenance")
        artifact = d["artifact_digest"]
        if artifact is not None and not is_exact_type(artifact, str):
            raise P09BValidationError("artifact_digest must be a string or null")
        exit_code = d["exit_code"]
        if exit_code is not None and not is_exact_type(exit_code, int):
            raise P09BValidationError("exit_code must be an int or null")
        return cls(
            schema_version=d["schema_version"],
            evidence_id=d["evidence_id"],
            task_id=d["task_id"],
            run_id=d["run_id"],
            collector_id=d["collector_id"],
            collector_version=d["collector_version"],
            requirement_id=d["requirement_id"],
            argv=_tuple_from_json_list(d["argv"], field="argv"),
            working_directory=d["working_directory"],
            command_digest=d["command_digest"],
            exit_code=exit_code,
            completed=d["completed"],
            started_at=d["started_at"],
            completed_at=d["completed_at"],
            duration_ms=d["duration_ms"],
            repository_id=d["repository_id"],
            object_format=_enum(d["object_format"], GitObjectFormat, field="object_format"),
            base_commit_sha=d["base_commit_sha"],
            commit_sha=d["commit_sha"],
            tree_sha=d["tree_sha"],
            pre_snapshot_id=d["pre_snapshot_id"],
            post_snapshot_id=d["post_snapshot_id"],
            dirty_state=_enum(d["dirty_state"], DirtyState, field="dirty_state"),
            changed_files_digest=d["changed_files_digest"],
            stdout_digest=d["stdout_digest"],
            stderr_digest=d["stderr_digest"],
            artifact_digest=artifact,
            source=_enum(d["source"], EvidenceSource, field="source"),
        )


# ---------------------------------------------------------------------------
# CollectedCommandEvidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CollectedCommandEvidence:
    schema_version: str
    provenance: EvidenceProvenance
    pre_snapshot: RepositorySnapshot
    post_snapshot: RepositorySnapshot

    SCHEMA_VERSION = "p0-9b.collected-evidence.v1"
    _KEYS = frozenset({"schema_version", "provenance", "pre_snapshot", "post_snapshot"})

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, self.SCHEMA_VERSION)
        if not isinstance(self.provenance, EvidenceProvenance):
            raise P09BValidationError("provenance must be an EvidenceProvenance")
        for name in ("pre_snapshot", "post_snapshot"):
            if not isinstance(getattr(self, name), RepositorySnapshot):
                raise P09BValidationError(f"{name} must be a RepositorySnapshot")
        prov = self.provenance
        if self.pre_snapshot.snapshot_id != prov.pre_snapshot_id:
            raise P09BValidationError("pre_snapshot.snapshot_id != provenance.pre_snapshot_id")
        if self.post_snapshot.snapshot_id != prov.post_snapshot_id:
            raise P09BValidationError("post_snapshot.snapshot_id != provenance.post_snapshot_id")
        for name, snap in (("pre_snapshot", self.pre_snapshot),
                           ("post_snapshot", self.post_snapshot)):
            if snap.repository_id != prov.repository_id:
                raise P09BValidationError(f"{name}.repository_id != provenance.repository_id")
            if snap.object_format != prov.object_format:
                raise P09BValidationError(f"{name}.object_format != provenance.object_format")
            if snap.base_commit_sha != prov.base_commit_sha:
                raise P09BValidationError(f"{name}.base_commit_sha != provenance.base_commit_sha")
        # The post snapshot records the state the command observed as HEAD.
        if self.post_snapshot.head_commit_sha != prov.commit_sha:
            raise P09BValidationError("post_snapshot.head_commit_sha != provenance.commit_sha")
        if self.post_snapshot.head_tree_sha != prov.tree_sha:
            raise P09BValidationError("post_snapshot.head_tree_sha != provenance.tree_sha")

    def to_json_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "provenance": self.provenance.to_json_dict(),
            "pre_snapshot": self.pre_snapshot.to_json_dict(),
            "post_snapshot": self.post_snapshot.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, data: object) -> "CollectedCommandEvidence":
        d = _require_mapping(data, model="CollectedCommandEvidence")
        _require_exact_keys(d, cls._KEYS, model="CollectedCommandEvidence")
        return cls(
            schema_version=d["schema_version"],
            provenance=EvidenceProvenance.from_json_dict(d["provenance"]),
            pre_snapshot=RepositorySnapshot.from_json_dict(d["pre_snapshot"]),
            post_snapshot=RepositorySnapshot.from_json_dict(d["post_snapshot"]),
        )


# ---------------------------------------------------------------------------
# EvidenceVerificationResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceVerificationResult:
    schema_version: str
    accepted: bool
    status: VerificationStatus
    reason_codes: tuple[str, ...]
    evidence_id: str
    run_id: str
    task_id: str
    candidate_binding: CandidateBinding | None
    repository_snapshot: RepositorySnapshot | None
    matched_requirement_id: str | None
    claim_digest: str
    verified_at: str
    verifier_version: str
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    SCHEMA_VERSION = "p0-9b.verification.v1"
    _KEYS = frozenset({
        "schema_version", "accepted", "status", "reason_codes", "evidence_id", "run_id",
        "task_id", "candidate_binding", "repository_snapshot", "matched_requirement_id",
        "claim_digest", "verified_at", "verifier_version", "warnings", "errors",
    })

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, self.SCHEMA_VERSION)
        require_bool(self.accepted, field="accepted")
        object.__setattr__(self, "status", _enum(self.status, VerificationStatus, field="status"))
        if self.accepted != (self.status is VerificationStatus.VERIFIED):
            raise P09BValidationError(
                "accepted must be True iff status == VERIFIED"
            )
        require_str_tuple(self.reason_codes, field="reason_codes")
        for index, code in enumerate(self.reason_codes):
            if not code:
                raise P09BValidationError(f"reason_codes[{index}] must be non-empty")
        validate_generated_id(self.evidence_id, field="evidence_id")
        validate_generated_id(self.run_id, field="run_id")
        validate_task_id(self.task_id, field="task_id")
        if self.candidate_binding is not None and not isinstance(
            self.candidate_binding, CandidateBinding
        ):
            raise P09BValidationError("candidate_binding must be a CandidateBinding or None")
        if self.repository_snapshot is not None and not isinstance(
            self.repository_snapshot, RepositorySnapshot
        ):
            raise P09BValidationError("repository_snapshot must be a RepositorySnapshot or None")
        if self.matched_requirement_id is not None:
            validate_generated_id(self.matched_requirement_id, field="matched_requirement_id")
        if self.accepted:
            if self.candidate_binding is None or self.repository_snapshot is None \
                    or self.matched_requirement_id is None:
                raise P09BValidationError(
                    "accepted result requires candidate_binding, repository_snapshot, "
                    "and matched_requirement_id"
                )
        else:
            if self.matched_requirement_id is not None:
                raise P09BValidationError(
                    "a rejected result cannot claim a matched requirement"
                )
        validate_sha256_digest(self.claim_digest, field="claim_digest")
        validate_rfc3339_utc(self.verified_at, field="verified_at")
        require_str(self.verifier_version, field="verifier_version")
        require_str_tuple(self.warnings, field="warnings")
        require_str_tuple(self.errors, field="errors")

    def to_json_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "accepted": self.accepted,
            "status": self.status.value,
            "reason_codes": list(self.reason_codes),
            "evidence_id": self.evidence_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "candidate_binding": self.candidate_binding.to_json_dict()
            if self.candidate_binding is not None else None,
            "repository_snapshot": self.repository_snapshot.to_json_dict()
            if self.repository_snapshot is not None else None,
            "matched_requirement_id": self.matched_requirement_id,
            "claim_digest": self.claim_digest,
            "verified_at": self.verified_at,
            "verifier_version": self.verifier_version,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_json_dict(cls, data: object) -> "EvidenceVerificationResult":
        d = _require_mapping(data, model="EvidenceVerificationResult")
        _require_exact_keys(d, cls._KEYS, model="EvidenceVerificationResult")
        binding = d["candidate_binding"]
        snapshot = d["repository_snapshot"]
        return cls(
            schema_version=d["schema_version"],
            accepted=d["accepted"],
            status=_enum(d["status"], VerificationStatus, field="status"),
            reason_codes=_tuple_from_json_list(d["reason_codes"], field="reason_codes"),
            evidence_id=d["evidence_id"],
            run_id=d["run_id"],
            task_id=d["task_id"],
            candidate_binding=CandidateBinding.from_json_dict(binding)
            if binding is not None else None,
            repository_snapshot=RepositorySnapshot.from_json_dict(snapshot)
            if snapshot is not None else None,
            matched_requirement_id=d["matched_requirement_id"],
            claim_digest=d["claim_digest"],
            verified_at=d["verified_at"],
            verifier_version=d["verifier_version"],
            warnings=_tuple_from_json_list(d["warnings"], field="warnings"),
            errors=_tuple_from_json_list(d["errors"], field="errors"),
        )


# ---------------------------------------------------------------------------
# VerifiedCommandEvidence
# ---------------------------------------------------------------------------

def _verified_payload(evidence_id, run_id, task_id, requirement_id, candidate) -> dict:
    return {
        "kind": "p0-9b.verified-evidence-payload.v1",
        "evidence_id": evidence_id,
        "run_id": run_id,
        "task_id": task_id,
        "requirement_id": requirement_id,
        "candidate_binding": candidate.to_json_dict(),
    }


@dataclass(frozen=True)
class VerifiedCommandEvidence:
    schema_version: str
    evidence_id: str
    run_id: str
    task_id: str
    requirement_id: str
    candidate_binding: CandidateBinding
    verification_digest: str

    SCHEMA_VERSION = "p0-9b.verified-evidence.v1"
    _KEYS = frozenset({
        "schema_version", "evidence_id", "run_id", "task_id", "requirement_id",
        "candidate_binding", "verification_digest",
    })

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, self.SCHEMA_VERSION)
        validate_generated_id(self.evidence_id, field="evidence_id")
        validate_generated_id(self.run_id, field="run_id")
        validate_task_id(self.task_id, field="task_id")
        validate_generated_id(self.requirement_id, field="requirement_id")
        if not isinstance(self.candidate_binding, CandidateBinding):
            raise P09BValidationError("candidate_binding must be a CandidateBinding")
        validate_sha256_digest(self.verification_digest, field="verification_digest")
        expected = canonical_digest(_verified_payload(
            self.evidence_id, self.run_id, self.task_id, self.requirement_id,
            self.candidate_binding,
        ))
        if self.verification_digest != expected:
            raise P09BValidationError(
                "verification_digest does not match the canonical payload"
            )

    def to_json_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "requirement_id": self.requirement_id,
            "candidate_binding": self.candidate_binding.to_json_dict(),
            "verification_digest": self.verification_digest,
        }

    @classmethod
    def from_json_dict(cls, data: object) -> "VerifiedCommandEvidence":
        d = _require_mapping(data, model="VerifiedCommandEvidence")
        _require_exact_keys(d, cls._KEYS, model="VerifiedCommandEvidence")
        return cls(
            schema_version=d["schema_version"],
            evidence_id=d["evidence_id"],
            run_id=d["run_id"],
            task_id=d["task_id"],
            requirement_id=d["requirement_id"],
            candidate_binding=CandidateBinding.from_json_dict(d["candidate_binding"]),
            verification_digest=d["verification_digest"],
        )

    @staticmethod
    def compute_verification_digest(
        evidence_id: str, run_id: str, task_id: str, requirement_id: str,
        candidate_binding: CandidateBinding,
    ) -> str:
        return canonical_digest(_verified_payload(
            evidence_id, run_id, task_id, requirement_id, candidate_binding))


# ---------------------------------------------------------------------------
# EvidenceVerificationBundle
# ---------------------------------------------------------------------------

def _bundle_payload(candidate, verified, rejected, snapshot) -> dict:
    return {
        "kind": "p0-9b.verification-bundle-payload.v1",
        "candidate_binding": candidate.to_json_dict(),
        "verified": [v.to_json_dict() for v in verified],
        "rejected": [r.to_json_dict() for r in rejected],
        "verified_at_snapshot": snapshot.to_json_dict(),
    }


@dataclass(frozen=True)
class EvidenceVerificationBundle:
    schema_version: str
    candidate_binding: CandidateBinding
    verified: tuple[VerifiedCommandEvidence, ...]
    rejected: tuple[EvidenceVerificationResult, ...]
    verified_at_snapshot: RepositorySnapshot
    bundle_digest: str

    SCHEMA_VERSION = "p0-9b.verification-bundle.v1"
    _KEYS = frozenset({
        "schema_version", "candidate_binding", "verified", "rejected",
        "verified_at_snapshot", "bundle_digest",
    })

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, self.SCHEMA_VERSION)
        if not isinstance(self.candidate_binding, CandidateBinding):
            raise P09BValidationError("candidate_binding must be a CandidateBinding")
        if not is_exact_type(self.verified, tuple) or not is_exact_type(self.rejected, tuple):
            raise P09BValidationError("verified and rejected must be tuples")
        for v in self.verified:
            if not isinstance(v, VerifiedCommandEvidence):
                raise P09BValidationError(
                    "verified may only contain VerifiedCommandEvidence (no raw evidence)"
                )
        for r in self.rejected:
            if not isinstance(r, EvidenceVerificationResult):
                raise P09BValidationError(
                    "rejected may only contain EvidenceVerificationResult"
                )
            if r.accepted:
                raise P09BValidationError("rejected tuple cannot contain an accepted result")
        if not isinstance(self.verified_at_snapshot, RepositorySnapshot):
            raise P09BValidationError("verified_at_snapshot must be a RepositorySnapshot")

        ids = [v.evidence_id for v in self.verified] + [r.evidence_id for r in self.rejected]
        if len(set(ids)) != len(ids):
            raise P09BValidationError("evidence IDs must be unique across verified and rejected")

        candidate = self.candidate_binding
        for v in self.verified:
            if v.candidate_binding != candidate:
                raise P09BValidationError(
                    "every verified record must match the bundle candidate binding"
                )
            if v.task_id != _first_task_id(self.verified):
                raise P09BValidationError(
                    "verified records must share the same task candidate context"
                )

        snap = self.verified_at_snapshot
        if snap.repository_id != candidate.repository_id:
            raise P09BValidationError("verified_at_snapshot.repository_id != candidate.repository_id")
        if snap.object_format != candidate.object_format:
            raise P09BValidationError("verified_at_snapshot.object_format != candidate.object_format")
        if snap.head_commit_sha != candidate.candidate_commit_sha:
            raise P09BValidationError("verified_at_snapshot.head_commit_sha != candidate_commit_sha")
        if snap.head_tree_sha != candidate.candidate_tree_sha:
            raise P09BValidationError("verified_at_snapshot.head_tree_sha != candidate_tree_sha")
        if snap.base_commit_sha != candidate.base_commit_sha:
            raise P09BValidationError("verified_at_snapshot.base_commit_sha != candidate base")

        validate_sha256_digest(self.bundle_digest, field="bundle_digest")
        expected = canonical_digest(_bundle_payload(
            candidate, self.verified, self.rejected, snap))
        if self.bundle_digest != expected:
            raise P09BValidationError("bundle_digest does not match the canonical payload")

    def to_json_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "candidate_binding": self.candidate_binding.to_json_dict(),
            "verified": [v.to_json_dict() for v in self.verified],
            "rejected": [r.to_json_dict() for r in self.rejected],
            "verified_at_snapshot": self.verified_at_snapshot.to_json_dict(),
            "bundle_digest": self.bundle_digest,
        }

    @classmethod
    def from_json_dict(cls, data: object) -> "EvidenceVerificationBundle":
        d = _require_mapping(data, model="EvidenceVerificationBundle")
        _require_exact_keys(d, cls._KEYS, model="EvidenceVerificationBundle")
        if not is_exact_type(d["verified"], list) or not is_exact_type(d["rejected"], list):
            raise P09BValidationError("verified and rejected must be JSON lists")
        return cls(
            schema_version=d["schema_version"],
            candidate_binding=CandidateBinding.from_json_dict(d["candidate_binding"]),
            verified=tuple(VerifiedCommandEvidence.from_json_dict(v) for v in d["verified"]),
            rejected=tuple(EvidenceVerificationResult.from_json_dict(r) for r in d["rejected"]),
            verified_at_snapshot=RepositorySnapshot.from_json_dict(d["verified_at_snapshot"]),
            bundle_digest=d["bundle_digest"],
        )

    @staticmethod
    def compute_bundle_digest(
        candidate_binding: CandidateBinding,
        verified: tuple[VerifiedCommandEvidence, ...],
        rejected: tuple[EvidenceVerificationResult, ...],
        verified_at_snapshot: RepositorySnapshot,
    ) -> str:
        return canonical_digest(_bundle_payload(
            candidate_binding, verified, rejected, verified_at_snapshot))


def _first_task_id(verified: tuple[VerifiedCommandEvidence, ...]) -> str | None:
    return verified[0].task_id if verified else None

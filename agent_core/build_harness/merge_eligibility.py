"""ChangeGate Slice 1B-A — merge eligibility typed input and policy contracts.

Transcribes the accepted Slice 1A contract (spec + golden fixture +
``slice_1a_semantic_manifest``) into production typed models. This module
owns only: closed value contracts, ``EligibilityFacts``,
``MergeEligibilityPolicyInput`` (+ canonical payload / ``input_digest``),
``PolicyIdentity`` / ``EvaluatorIdentity``, and the frozen policy-data model
(``ReasonDefinition`` / ``MergeEligibilityPolicy`` /
``MERGE_ELIGIBILITY_POLICY_V1``). No evaluator, decision, record, facade, or
replay logic belongs here (Gates 1B-B/1B-C/1B-D).

Pure domain: no clock, no environment, no network, no subprocess, no
filesystem, no randomness. Every constructor validates the explicit facts
supplied to it and never inspects ambient state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from agent_core.build_harness.canonical import (
    P09BValidationError,
    canonical_digest,
    is_exact_bool,
    is_exact_dict,
    is_exact_list,
    is_exact_str,
    reject_control_characters,
)

__all__ = [
    "MergeEligibilityInputError",
    "TaskContextCurrency",
    "CandidateBindingCurrency",
    "RepositorySnapshotCurrency",
    "ReleaseCleanliness",
    "PolicyContextCurrency",
    "EvidenceContextStatus",
    "EvidenceContextViolation",
    "ScopeStatus",
    "ApprovalStatus",
    "AuthorityStatus",
    "VerifierIdentityStatus",
    "VerifierIndependenceStatus",
    "EvaluationMode",
    "Disposition",
    "DecisionAuthority",
    "EligibilityFacts",
    "MergeEligibilityPolicyInput",
    "PolicyIdentity",
    "EvaluatorIdentity",
    "ReasonDefinition",
    "VerifierRuleRow",
    "MergeEligibilityPolicy",
    "MERGE_ELIGIBILITY_POLICY_V1",
    "APPROVAL_SENTINEL",
    "POLICY_RECORD_SCHEMA_VERSION",
    "POLICY_RECORD_SCHEMA_DIGEST",
    "CANONICALIZATION_VERSION",
    "CANONICALIZATION_CONTRACT_DIGEST",
    "INPUT_PAYLOAD_KIND",
]


class MergeEligibilityInputError(P09BValidationError):
    """A Slice 1B merge-eligibility input value failed strict, deterministic
    construction. The message names the failing field/path — never a raw
    ``KeyError``/``TypeError``/``ValueError``/``AssertionError`` for
    externally malformed input."""


# ---------------------------------------------------------------------------
# Closed value contracts (spec §6 + fixture ``fact_state_mapping``)
# ---------------------------------------------------------------------------


class TaskContextCurrency(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class CandidateBindingCurrency(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class RepositorySnapshotCurrency(StrEnum):
    CURRENT = "CURRENT"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


class ReleaseCleanliness(StrEnum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"
    UNKNOWN = "UNKNOWN"


class PolicyContextCurrency(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class EvidenceContextStatus(StrEnum):
    COHERENT = "COHERENT"
    INCOHERENT = "INCOHERENT"
    UNKNOWN = "UNKNOWN"


class EvidenceContextViolation(StrEnum):
    TASK_MISMATCH = "TASK_MISMATCH"
    RUN_MISMATCH = "RUN_MISMATCH"
    CANDIDATE_MISMATCH = "CANDIDATE_MISMATCH"
    PROVENANCE_INVALID = "PROVENANCE_INVALID"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"


class ScopeStatus(StrEnum):
    COMPLIANT = "COMPLIANT"
    VIOLATION = "VIOLATION"
    SEMANTIC_UNCERTAIN = "SEMANTIC_UNCERTAIN"
    NOT_EVALUATED = "NOT_EVALUATED"


class ApprovalStatus(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class AuthorityStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class VerifierIdentityStatus(StrEnum):
    ATTESTED = "ATTESTED"
    PRESENT_UNATTESTED = "PRESENT_UNATTESTED"
    ABSENT = "ABSENT"
    INVALID = "INVALID"


class VerifierIndependenceStatus(StrEnum):
    INDEPENDENT = "INDEPENDENT"
    NOT_INDEPENDENT = "NOT_INDEPENDENT"
    UNKNOWN = "UNKNOWN"


class EvaluationMode(StrEnum):
    ENFORCE = "ENFORCE"
    SHADOW = "SHADOW"


class Disposition(StrEnum):
    ELIGIBLE_TO_MERGE_UNDER_POLICY = "ELIGIBLE_TO_MERGE_UNDER_POLICY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCK = "BLOCK"


class DecisionAuthority(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    ADVISORY_ONLY = "ADVISORY_ONLY"


APPROVAL_SENTINEL = "NO_APPROVAL_SUPPLIED"
INPUT_PAYLOAD_KIND = "changegate.merge-eligibility-policy-input.test-oracle.v1"

# --- Slice 1A committed record-schema / canonicalization bindings ----------
# Transcribed verbatim from ``slice_1a_semantic_manifest.deterministic_identity``.
# ``POLICY_RECORD_SCHEMA_DIGEST`` and ``CANONICALIZATION_CONTRACT_DIGEST`` are
# recomputed at import time from these constants — never pasted unexplained.

POLICY_RECORD_SCHEMA_VERSION = "changegate.policy-evaluation-record.v1"
CANONICALIZATION_VERSION = "tomtit.canonical.v1"

_TYPED_FIELD_CONTRACT: Mapping[str, Any] = MappingProxyType(
    {
        "schema_version": {
            "type": "const",
            "value": "changegate.policy-evaluation-record.v1",
        },
        "task_id": {"type": "string", "grammar": "task_id"},
        "task_contract_digest": {"type": "string", "grammar": "canonical_digest"},
        "candidate_digest": {"type": "string", "grammar": "canonical_digest"},
        "repository_snapshot_digest": {
            "type": "string",
            "grammar": "canonical_digest",
        },
        "verification_bundle_digest": {
            "type": "string",
            "grammar": "canonical_digest",
        },
        "approval_digest_or_sentinel": {
            "type": "string",
            "grammar": "canonical_digest_or_sentinel",
            "sentinel": "NO_APPROVAL_SUPPLIED",
        },
        "authority_binding_digest": {"type": "string", "grammar": "canonical_digest"},
        "verifier_binding_digest": {"type": "string", "grammar": "canonical_digest"},
        "policy_digest": {"type": "string", "grammar": "canonical_digest"},
        "policy_version": {"type": "string", "grammar": "version"},
        "evaluator_version": {"type": "string", "grammar": "version"},
        "evaluation_mode": {"type": "enum", "values": ["ENFORCE", "SHADOW"]},
        "input_digest": {"type": "string", "grammar": "canonical_digest"},
        "disposition": {
            "type": "enum",
            "values": [
                "ELIGIBLE_TO_MERGE_UNDER_POLICY",
                "REVIEW_REQUIRED",
                "BLOCK",
            ],
        },
        "decision_authority": {
            "type": "enum",
            "values": ["AUTHORITATIVE", "ADVISORY_ONLY"],
        },
        "primary_reason_code": {
            "type": "nullable_enum",
            "values_from": "reason_taxonomy",
        },
        "complete_reason_codes": {
            "type": "sorted_unique_list",
            "items_from": "reason_taxonomy",
        },
        "blocking_reason_codes": {
            "type": "sorted_unique_list",
            "items_from": "reason_taxonomy",
        },
        "review_reason_codes": {
            "type": "sorted_unique_list",
            "items_from": "reason_taxonomy",
        },
        "required_requirement_ids": {
            "type": "sorted_unique_list",
            "items_from": "requirement_id_universe",
        },
        "satisfied_requirement_ids": {
            "type": "sorted_unique_list",
            "items_from": "requirement_id_universe",
        },
        "invalid_requirement_ids": {
            "type": "sorted_unique_list",
            "items_from": "requirement_id_universe",
        },
        "missing_requirement_ids": {
            "type": "sorted_unique_list",
            "items_from": "requirement_id_universe",
        },
        "rejected_evidence_ids": {
            "type": "sorted_unique_list",
            "items_from": "evidence_record_id_universe",
        },
        "invalid_provenance_evidence_ids": {
            "type": "sorted_unique_list",
            "items_from": "evidence_record_id_universe",
        },
        "unexpected_evidence_ids": {
            "type": "sorted_unique_list",
            "items_from": "evidence_record_id_universe",
        },
        "decision_digest": {"type": "string", "grammar": "canonical_digest"},
    }
)

_CANONICALIZATION_CONTRACT: Mapping[str, Any] = MappingProxyType(
    {
        "kind": "changegate.canonicalization-contract.v1",
        "encoding": "UTF-8",
        "unicode_normalization": "NFC",
        "object_keys": (
            "lexicographically sorted by the serializer; JSON insertion "
            "order is NOT semantic"
        ),
        "separators": "compact (',', ':')",
        "non_finite_numbers": "rejected (no NaN/Infinity)",
        "digest": "'sha256:' + 64 lowercase hex over the canonical JSON bytes",
        "implementation": (
            "agent_core.build_harness.canonical.canonical_json_bytes/canonical_digest"
        ),
    }
)

POLICY_RECORD_SCHEMA_DIGEST = canonical_digest(dict(_TYPED_FIELD_CONTRACT))
CANONICALIZATION_CONTRACT_DIGEST = canonical_digest(dict(_CANONICALIZATION_CONTRACT))


# ---------------------------------------------------------------------------
# Boundary primitives
# ---------------------------------------------------------------------------

_RE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RE_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_RE_MACHINE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_RE_OWNER_DECISION = re.compile(r"^OD-[A-Z0-9-]+$")


def _require_mapping(data: object, *, model: str) -> dict:
    if not is_exact_dict(data):
        raise MergeEligibilityInputError(f"{model}: root must be a JSON object")
    return data


def _require_exact_keys(data: dict, required: frozenset[str], *, model: str) -> None:
    keys = set(data)
    missing = sorted(required - keys)
    unknown = sorted(keys - required)
    if missing:
        raise MergeEligibilityInputError(f"{model}: missing field(s) {missing}")
    if unknown:
        raise MergeEligibilityInputError(f"{model}: unknown field(s) {unknown}")


def _require_str(value: object, *, field: str) -> str:
    if not is_exact_str(value):
        raise MergeEligibilityInputError(
            f"{field} must be a string, got {type(value).__name__}"
        )
    if not value:
        raise MergeEligibilityInputError(f"{field} must be a non-empty string")
    if not value.strip():
        raise MergeEligibilityInputError(f"{field} must not be whitespace-only")
    reject_control_characters(value, field=field)
    return value


def _require_pattern(value: object, pattern: re.Pattern[str], *, field: str) -> str:
    text = _require_str(value, field=field)
    if not pattern.match(text):
        raise MergeEligibilityInputError(
            f"{field} {text!r} does not match the required grammar"
        )
    return text


def _require_task_id(value: object, *, field: str) -> str:
    return _require_pattern(value, _RE_TASK_ID, field=field)


def _require_version(value: object, *, field: str) -> str:
    return _require_pattern(value, _RE_VERSION, field=field)


def _require_digest(value: object, *, field: str) -> str:
    return _require_pattern(value, _RE_SHA256_DIGEST, field=field)


def _require_digest_or_sentinel(value: object, *, field: str) -> str:
    text = _require_str(value, field=field)
    if text == APPROVAL_SENTINEL:
        return text
    if not _RE_SHA256_DIGEST.match(text):
        raise MergeEligibilityInputError(
            f"{field} {text!r} must be a sha256 digest or the exact sentinel "
            f"{APPROVAL_SENTINEL!r}"
        )
    return text


def _require_exact_literal(value: object, expected: str, *, field: str) -> str:
    text = _require_str(value, field=field)
    if text != expected:
        raise MergeEligibilityInputError(
            f"{field} must equal the committed constant {expected!r}, got {text!r}"
        )
    return text


def _require_enum(value: object, enum_cls: type[StrEnum], *, field: str) -> Any:
    if type(value) is enum_cls:  # noqa: E721 — exact member, no subclass coercion
        return value
    if not is_exact_str(value):
        raise MergeEligibilityInputError(
            f"{field} must be a string enum value, got {type(value).__name__}"
        )
    for member in enum_cls:
        if member.value == value:
            return member
    raise MergeEligibilityInputError(
        f"{field} {value!r} is not a valid {enum_cls.__name__}"
    )


def _require_sorted_unique_str_tuple(
    value: object, *, field: str
) -> tuple[str, ...]:
    """A committed sorted-unique identifier set. Rejects (never silently
    normalizes) unsorted, duplicated, empty, or non-string entries."""
    if not is_exact_list(value):
        raise MergeEligibilityInputError(
            f"{field} must be a JSON list, got {type(value).__name__}"
        )
    items: list[str] = []
    for index, item in enumerate(value):
        if is_exact_bool(item) or not is_exact_str(item):
            raise MergeEligibilityInputError(
                f"{field}[{index}] must be a string, got {type(item).__name__}"
            )
        if not item:
            raise MergeEligibilityInputError(
                f"{field}[{index}] must be a non-empty string"
            )
        reject_control_characters(item, field=f"{field}[{index}]")
        items.append(item)
    result = tuple(items)
    if list(result) != sorted(result):
        raise MergeEligibilityInputError(
            f"{field} must be lexicographically sorted"
        )
    if len(set(result)) != len(result):
        raise MergeEligibilityInputError(
            f"{field} must not contain duplicate entries"
        )
    return result


def _require_sorted_unique_enum_tuple(
    value: object, enum_cls: type[StrEnum], *, field: str
) -> tuple[Any, ...]:
    raw = _require_sorted_unique_str_tuple(value, field=field)
    return tuple(_require_enum(item, enum_cls, field=f"{field}[]") for item in raw)


# ---------------------------------------------------------------------------
# EligibilityFacts
# ---------------------------------------------------------------------------

_REQUIREMENT_SET_FIELDS = (
    "required_requirement_ids",
    "satisfied_requirement_ids",
    "invalid_requirement_ids",
    "missing_requirement_ids",
)
_EVIDENCE_SET_FIELDS = (
    "rejected_evidence_ids",
    "invalid_provenance_evidence_ids",
    "unexpected_evidence_ids",
)
_FACTS_KEYS = frozenset(
    {
        "task_context_current",
        "candidate_binding_current",
        "repository_snapshot_current",
        "repository_release_clean",
        "policy_context_current",
        "evidence_context_status",
        "evidence_context_violations",
        "scope_status",
        "approval_status",
        "authority_status",
        "verifier_identity_status",
        "verifier_independence_status",
        *_REQUIREMENT_SET_FIELDS,
        *_EVIDENCE_SET_FIELDS,
    }
)


@dataclass(frozen=True)
class EligibilityFacts:
    """The committed 19-key typed-fact model (spec §6 + fixture
    ``fact_state_mapping``). Every field is required; incomplete construction
    is impossible."""

    task_context_current: TaskContextCurrency
    candidate_binding_current: CandidateBindingCurrency
    repository_snapshot_current: RepositorySnapshotCurrency
    repository_release_clean: ReleaseCleanliness
    policy_context_current: PolicyContextCurrency
    evidence_context_status: EvidenceContextStatus
    evidence_context_violations: tuple[EvidenceContextViolation, ...]
    scope_status: ScopeStatus
    approval_status: ApprovalStatus
    authority_status: AuthorityStatus
    verifier_identity_status: VerifierIdentityStatus
    verifier_independence_status: VerifierIndependenceStatus
    required_requirement_ids: tuple[str, ...]
    satisfied_requirement_ids: tuple[str, ...]
    invalid_requirement_ids: tuple[str, ...]
    missing_requirement_ids: tuple[str, ...]
    rejected_evidence_ids: tuple[str, ...]
    invalid_provenance_evidence_ids: tuple[str, ...]
    unexpected_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        # Violation coherence: non-empty exactly when INCOHERENT.
        is_incoherent = self.evidence_context_status is EvidenceContextStatus.INCOHERENT
        has_violations = len(self.evidence_context_violations) > 0
        if is_incoherent and not has_violations:
            raise MergeEligibilityInputError(
                "facts.evidence_context_violations must be non-empty when "
                "evidence_context_status is INCOHERENT"
            )
        if has_violations and not is_incoherent:
            raise MergeEligibilityInputError(
                "facts.evidence_context_violations must be empty unless "
                "evidence_context_status is INCOHERENT"
            )

        # Requirement partition: required == satisfied ∪ invalid ∪ missing,
        # and satisfied/invalid/missing are pairwise disjoint.
        required = set(self.required_requirement_ids)
        satisfied = set(self.satisfied_requirement_ids)
        invalid = set(self.invalid_requirement_ids)
        missing = set(self.missing_requirement_ids)
        if satisfied & invalid:
            raise MergeEligibilityInputError(
                "facts: satisfied_requirement_ids and invalid_requirement_ids "
                "must be disjoint"
            )
        if satisfied & missing:
            raise MergeEligibilityInputError(
                "facts: satisfied_requirement_ids and missing_requirement_ids "
                "must be disjoint"
            )
        if invalid & missing:
            raise MergeEligibilityInputError(
                "facts: invalid_requirement_ids and missing_requirement_ids "
                "must be disjoint"
            )
        if (satisfied | invalid | missing) != required:
            raise MergeEligibilityInputError(
                "facts: required_requirement_ids must equal the union of "
                "satisfied_requirement_ids, invalid_requirement_ids and "
                "missing_requirement_ids"
            )

    @classmethod
    def from_json_dict(cls, data: object) -> "EligibilityFacts":
        d = _require_mapping(data, model="EligibilityFacts")
        _require_exact_keys(d, _FACTS_KEYS, model="EligibilityFacts")
        return cls(
            task_context_current=_require_enum(
                d["task_context_current"],
                TaskContextCurrency,
                field="facts.task_context_current",
            ),
            candidate_binding_current=_require_enum(
                d["candidate_binding_current"],
                CandidateBindingCurrency,
                field="facts.candidate_binding_current",
            ),
            repository_snapshot_current=_require_enum(
                d["repository_snapshot_current"],
                RepositorySnapshotCurrency,
                field="facts.repository_snapshot_current",
            ),
            repository_release_clean=_require_enum(
                d["repository_release_clean"],
                ReleaseCleanliness,
                field="facts.repository_release_clean",
            ),
            policy_context_current=_require_enum(
                d["policy_context_current"],
                PolicyContextCurrency,
                field="facts.policy_context_current",
            ),
            evidence_context_status=_require_enum(
                d["evidence_context_status"],
                EvidenceContextStatus,
                field="facts.evidence_context_status",
            ),
            evidence_context_violations=_require_sorted_unique_enum_tuple(
                d["evidence_context_violations"],
                EvidenceContextViolation,
                field="facts.evidence_context_violations",
            ),
            scope_status=_require_enum(
                d["scope_status"], ScopeStatus, field="facts.scope_status"
            ),
            approval_status=_require_enum(
                d["approval_status"], ApprovalStatus, field="facts.approval_status"
            ),
            authority_status=_require_enum(
                d["authority_status"], AuthorityStatus, field="facts.authority_status"
            ),
            verifier_identity_status=_require_enum(
                d["verifier_identity_status"],
                VerifierIdentityStatus,
                field="facts.verifier_identity_status",
            ),
            verifier_independence_status=_require_enum(
                d["verifier_independence_status"],
                VerifierIndependenceStatus,
                field="facts.verifier_independence_status",
            ),
            required_requirement_ids=_require_sorted_unique_str_tuple(
                d["required_requirement_ids"], field="facts.required_requirement_ids"
            ),
            satisfied_requirement_ids=_require_sorted_unique_str_tuple(
                d["satisfied_requirement_ids"],
                field="facts.satisfied_requirement_ids",
            ),
            invalid_requirement_ids=_require_sorted_unique_str_tuple(
                d["invalid_requirement_ids"], field="facts.invalid_requirement_ids"
            ),
            missing_requirement_ids=_require_sorted_unique_str_tuple(
                d["missing_requirement_ids"], field="facts.missing_requirement_ids"
            ),
            rejected_evidence_ids=_require_sorted_unique_str_tuple(
                d["rejected_evidence_ids"], field="facts.rejected_evidence_ids"
            ),
            invalid_provenance_evidence_ids=_require_sorted_unique_str_tuple(
                d["invalid_provenance_evidence_ids"],
                field="facts.invalid_provenance_evidence_ids",
            ),
            unexpected_evidence_ids=_require_sorted_unique_str_tuple(
                d["unexpected_evidence_ids"], field="facts.unexpected_evidence_ids"
            ),
        )

    def to_json_dict(self) -> dict:
        return {
            "task_context_current": self.task_context_current.value,
            "candidate_binding_current": self.candidate_binding_current.value,
            "repository_snapshot_current": self.repository_snapshot_current.value,
            "repository_release_clean": self.repository_release_clean.value,
            "policy_context_current": self.policy_context_current.value,
            "evidence_context_status": self.evidence_context_status.value,
            "evidence_context_violations": [
                item.value for item in self.evidence_context_violations
            ],
            "scope_status": self.scope_status.value,
            "approval_status": self.approval_status.value,
            "authority_status": self.authority_status.value,
            "verifier_identity_status": self.verifier_identity_status.value,
            "verifier_independence_status": self.verifier_independence_status.value,
            "required_requirement_ids": list(self.required_requirement_ids),
            "satisfied_requirement_ids": list(self.satisfied_requirement_ids),
            "invalid_requirement_ids": list(self.invalid_requirement_ids),
            "missing_requirement_ids": list(self.missing_requirement_ids),
            "rejected_evidence_ids": list(self.rejected_evidence_ids),
            "invalid_provenance_evidence_ids": list(
                self.invalid_provenance_evidence_ids
            ),
            "unexpected_evidence_ids": list(self.unexpected_evidence_ids),
        }


# ---------------------------------------------------------------------------
# MergeEligibilityPolicyInput
# ---------------------------------------------------------------------------

_POLICY_INPUT_KEYS = frozenset(
    {
        "task_id",
        "task_contract_digest",
        "candidate_digest",
        "repository_snapshot_digest",
        "verification_bundle_digest",
        "approval_digest_or_sentinel",
        "authority_binding_digest",
        "verifier_binding_digest",
        "policy_digest",
        "policy_version",
        "evaluator_version",
        "evaluation_mode",
        "policy_record_schema_version",
        "policy_record_schema_digest",
        "canonicalization_version",
        "canonicalization_contract_digest",
        "facts",
    }
)

_SOURCE_BINDING_FIELDS = (
    "task_contract_digest",
    "candidate_digest",
    "repository_snapshot_digest",
    "verification_bundle_digest",
    "approval_digest_or_sentinel",
    "authority_binding_digest",
    "verifier_binding_digest",
    "policy_digest",
)


@dataclass(frozen=True)
class MergeEligibilityPolicyInput:
    """The committed 17-field canonical policy input (spec §5.2 + manifest
    ``deterministic_identity.merge_eligibility_policy_input_fields``)."""

    task_id: str
    task_contract_digest: str
    candidate_digest: str
    repository_snapshot_digest: str
    verification_bundle_digest: str
    approval_digest_or_sentinel: str
    authority_binding_digest: str
    verifier_binding_digest: str
    policy_digest: str
    policy_version: str
    evaluator_version: str
    evaluation_mode: EvaluationMode
    policy_record_schema_version: str
    policy_record_schema_digest: str
    canonicalization_version: str
    canonicalization_contract_digest: str
    facts: EligibilityFacts

    def __post_init__(self) -> None:
        if self.policy_record_schema_version != POLICY_RECORD_SCHEMA_VERSION:
            raise MergeEligibilityInputError(
                "policy_record_schema_version must equal the committed constant "
                f"{POLICY_RECORD_SCHEMA_VERSION!r}, got "
                f"{self.policy_record_schema_version!r}"
            )
        if self.policy_record_schema_digest != POLICY_RECORD_SCHEMA_DIGEST:
            raise MergeEligibilityInputError(
                "policy_record_schema_digest must equal "
                "canonical_digest(TYPED_FIELD_CONTRACT) "
                f"({POLICY_RECORD_SCHEMA_DIGEST!r}), got "
                f"{self.policy_record_schema_digest!r}"
            )
        if self.canonicalization_version != CANONICALIZATION_VERSION:
            raise MergeEligibilityInputError(
                "canonicalization_version must equal the committed constant "
                f"{CANONICALIZATION_VERSION!r}, got {self.canonicalization_version!r}"
            )
        if self.canonicalization_contract_digest != CANONICALIZATION_CONTRACT_DIGEST:
            raise MergeEligibilityInputError(
                "canonicalization_contract_digest must equal the recomputed "
                f"committed constant {CANONICALIZATION_CONTRACT_DIGEST!r}, got "
                f"{self.canonicalization_contract_digest!r}"
            )

    @classmethod
    def from_json_dict(cls, data: object) -> "MergeEligibilityPolicyInput":
        d = _require_mapping(data, model="MergeEligibilityPolicyInput")
        _require_exact_keys(d, _POLICY_INPUT_KEYS, model="MergeEligibilityPolicyInput")
        return cls(
            task_id=_require_task_id(d["task_id"], field="task_id"),
            task_contract_digest=_require_digest(
                d["task_contract_digest"], field="task_contract_digest"
            ),
            candidate_digest=_require_digest(
                d["candidate_digest"], field="candidate_digest"
            ),
            repository_snapshot_digest=_require_digest(
                d["repository_snapshot_digest"], field="repository_snapshot_digest"
            ),
            verification_bundle_digest=_require_digest(
                d["verification_bundle_digest"], field="verification_bundle_digest"
            ),
            approval_digest_or_sentinel=_require_digest_or_sentinel(
                d["approval_digest_or_sentinel"], field="approval_digest_or_sentinel"
            ),
            authority_binding_digest=_require_digest(
                d["authority_binding_digest"], field="authority_binding_digest"
            ),
            verifier_binding_digest=_require_digest(
                d["verifier_binding_digest"], field="verifier_binding_digest"
            ),
            policy_digest=_require_digest(d["policy_digest"], field="policy_digest"),
            policy_version=_require_version(
                d["policy_version"], field="policy_version"
            ),
            evaluator_version=_require_version(
                d["evaluator_version"], field="evaluator_version"
            ),
            evaluation_mode=_require_enum(
                d["evaluation_mode"], EvaluationMode, field="evaluation_mode"
            ),
            policy_record_schema_version=_require_str(
                d["policy_record_schema_version"],
                field="policy_record_schema_version",
            ),
            policy_record_schema_digest=_require_digest(
                d["policy_record_schema_digest"],
                field="policy_record_schema_digest",
            ),
            canonicalization_version=_require_str(
                d["canonicalization_version"], field="canonicalization_version"
            ),
            canonicalization_contract_digest=_require_digest(
                d["canonicalization_contract_digest"],
                field="canonicalization_contract_digest",
            ),
            facts=EligibilityFacts.from_json_dict(d["facts"]),
        )

    def to_canonical_payload(self) -> dict:
        """Byte-for-byte the committed Slice 1A test-oracle payload
        (kind ``changegate.merge-eligibility-policy-input.test-oracle.v1``)."""
        bindings = {
            "task_contract_digest": self.task_contract_digest,
            "candidate_digest": self.candidate_digest,
            "repository_snapshot_digest": self.repository_snapshot_digest,
            "verification_bundle_digest": self.verification_bundle_digest,
            "approval_digest_or_sentinel": self.approval_digest_or_sentinel,
            "authority_binding_digest": self.authority_binding_digest,
            "verifier_binding_digest": self.verifier_binding_digest,
            "policy_digest": self.policy_digest,
        }
        facts_dict = self.facts.to_json_dict()
        return {
            "kind": INPUT_PAYLOAD_KIND,
            "task_id": self.task_id,
            **{field: bindings[field] for field in _SOURCE_BINDING_FIELDS},
            "policy_version": self.policy_version,
            "evaluator_version": self.evaluator_version,
            "evaluation_mode": self.evaluation_mode.value,
            "policy_record_schema_version": self.policy_record_schema_version,
            "policy_record_schema_digest": self.policy_record_schema_digest,
            "canonicalization_version": self.canonicalization_version,
            "canonicalization_contract_digest": self.canonicalization_contract_digest,
            "facts": {key: facts_dict[key] for key in sorted(facts_dict)},
        }

    def input_digest(self) -> str:
        return canonical_digest(self.to_canonical_payload())


# ---------------------------------------------------------------------------
# Identity models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyIdentity:
    """The full mandatory pair — version alone is never a complete identity."""

    policy_version: str
    policy_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_version", _require_version(self.policy_version, field="policy_version")
        )
        object.__setattr__(
            self, "policy_digest", _require_digest(self.policy_digest, field="policy_digest")
        )


@dataclass(frozen=True)
class EvaluatorIdentity:
    evaluator_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evaluator_version",
            _require_version(self.evaluator_version, field="evaluator_version"),
        )


# ---------------------------------------------------------------------------
# Policy data contracts
# ---------------------------------------------------------------------------

_REASON_CATEGORIES = frozenset(
    {
        "SCOPE",
        "REPO_STATE",
        "INDEPENDENCE",
        "EVIDENCE",
        "FRESHNESS",
        "INTEGRITY",
        "APPROVAL",
        "CONTEXT",
    }
)
_REASON_KINDS = frozenset({"FACTUAL", "SEMANTIC"})


@dataclass(frozen=True)
class ReasonDefinition:
    code: str
    precedence_rank: int
    category: str
    kind: str
    default_disposition: Disposition
    owner_decision_pending: str | None

    def __post_init__(self) -> None:
        if not is_exact_str(self.code) or not _RE_MACHINE_CODE.match(self.code):
            raise MergeEligibilityInputError(
                f"ReasonDefinition.code {self.code!r} must match [A-Z][A-Z0-9_]*"
            )
        if not isinstance(self.precedence_rank, int) or isinstance(
            self.precedence_rank, bool
        ):
            raise MergeEligibilityInputError(
                "ReasonDefinition.precedence_rank must be a non-bool int"
            )
        if self.precedence_rank <= 0:
            raise MergeEligibilityInputError(
                "ReasonDefinition.precedence_rank must be positive"
            )
        if self.category not in _REASON_CATEGORIES:
            raise MergeEligibilityInputError(
                f"ReasonDefinition.category {self.category!r} is not a committed category"
            )
        if self.kind not in _REASON_KINDS:
            raise MergeEligibilityInputError(
                f"ReasonDefinition.kind {self.kind!r} is not a committed kind"
            )
        if type(self.default_disposition) is not Disposition:  # noqa: E721
            raise MergeEligibilityInputError(
                "ReasonDefinition.default_disposition must be a Disposition member"
            )
        if self.owner_decision_pending is not None and (
            not is_exact_str(self.owner_decision_pending)
            or not _RE_OWNER_DECISION.match(self.owner_decision_pending)
        ):
            raise MergeEligibilityInputError(
                "ReasonDefinition.owner_decision_pending must be None or match OD-*"
            )


@dataclass(frozen=True)
class VerifierRuleRow:
    """One ordered row of the committed 12-combination first-match verifier
    rule. ``identity``/``independence`` of ``None`` denote the wildcard
    ``"*"``."""

    identity: tuple[str, ...] | None
    independence: tuple[str, ...] | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.identity is not None:
            for value in self.identity:
                _require_enum(value, VerifierIdentityStatus, field="verifier_rule.identity[]")
        if self.independence is not None:
            for value in self.independence:
                _require_enum(
                    value, VerifierIndependenceStatus, field="verifier_rule.independence[]"
                )

    def matches(self, identity: str, independence: str) -> bool:
        identity_ok = self.identity is None or identity in self.identity
        independence_ok = self.independence is None or independence in self.independence
        return identity_ok and independence_ok


_ENUM_FACT_FIELDS: Mapping[str, type[StrEnum]] = MappingProxyType(
    {
        "task_context_current": TaskContextCurrency,
        "candidate_binding_current": CandidateBindingCurrency,
        "repository_snapshot_current": RepositorySnapshotCurrency,
        "repository_release_clean": ReleaseCleanliness,
        "policy_context_current": PolicyContextCurrency,
        "evidence_context_status": EvidenceContextStatus,
        "scope_status": ScopeStatus,
        "approval_status": ApprovalStatus,
        "authority_status": AuthorityStatus,
    }
)
_SET_FACT_FIELDS = frozenset({*_REQUIREMENT_SET_FIELDS, *_EVIDENCE_SET_FIELDS})


@dataclass(frozen=True)
class MergeEligibilityPolicy:
    """Frozen, fingerprint-bound policy-semantic data. Carries its own
    declared :class:`PolicyIdentity` separately from the evaluator-facing
    semantic fields (spec §9/§10; manifest ``fact_state_mapping``). No
    evaluation function belongs to this type — Gate 1B-B consumes it."""

    declared_identity: PolicyIdentity
    reason_definitions: tuple[ReasonDefinition, ...]
    enum_fact_reasons: Mapping[str, Mapping[str, str | None]]
    violation_tag_reasons: Mapping[str, str]
    set_fact_triggers: Mapping[str, str | None]
    verifier_rule: tuple[VerifierRuleRow, ...]

    def __post_init__(self) -> None:
        if type(self.declared_identity) is not PolicyIdentity:  # noqa: E721
            raise MergeEligibilityInputError(
                "MergeEligibilityPolicy.declared_identity must be a PolicyIdentity"
            )

        codes = [r.code for r in self.reason_definitions]
        if len(set(codes)) != len(codes):
            raise MergeEligibilityInputError(
                "MergeEligibilityPolicy: duplicate reason code in reason_definitions"
            )
        ranks = [r.precedence_rank for r in self.reason_definitions]
        if len(set(ranks)) != len(ranks):
            raise MergeEligibilityInputError(
                "MergeEligibilityPolicy: duplicate precedence_rank in reason_definitions"
            )
        known_codes = frozenset(codes)

        if set(self.enum_fact_reasons) != set(_ENUM_FACT_FIELDS):
            raise MergeEligibilityInputError(
                "MergeEligibilityPolicy.enum_fact_reasons must have exactly the "
                "committed 9 enum-fact keys (missing or extra row)"
            )
        for fact_name, enum_cls in _ENUM_FACT_FIELDS.items():
            mapping = self.enum_fact_reasons[fact_name]
            expected_values = {member.value for member in enum_cls}
            if set(mapping) != expected_values:
                raise MergeEligibilityInputError(
                    f"MergeEligibilityPolicy.enum_fact_reasons[{fact_name!r}] must "
                    "be total over the closed enum domain (missing or extra value)"
                )
            for reason_code in mapping.values():
                if reason_code is not None and reason_code not in known_codes:
                    raise MergeEligibilityInputError(
                        f"MergeEligibilityPolicy.enum_fact_reasons[{fact_name!r}] "
                        f"references unknown reason code {reason_code!r}"
                    )

        expected_violation_tags = {member.value for member in EvidenceContextViolation}
        if set(self.violation_tag_reasons) != expected_violation_tags:
            raise MergeEligibilityInputError(
                "MergeEligibilityPolicy.violation_tag_reasons must be total over "
                "the closed violation-tag domain (missing or extra row)"
            )
        for reason_code in self.violation_tag_reasons.values():
            if reason_code not in known_codes:
                raise MergeEligibilityInputError(
                    "MergeEligibilityPolicy.violation_tag_reasons references "
                    f"unknown reason code {reason_code!r}"
                )

        if set(self.set_fact_triggers) != _SET_FACT_FIELDS:
            raise MergeEligibilityInputError(
                "MergeEligibilityPolicy.set_fact_triggers must have exactly the "
                "committed 7 set-fact keys (missing or extra row)"
            )
        for reason_code in self.set_fact_triggers.values():
            if reason_code is not None and reason_code not in known_codes:
                raise MergeEligibilityInputError(
                    "MergeEligibilityPolicy.set_fact_triggers references unknown "
                    f"reason code {reason_code!r}"
                )

        if not self._verifier_rule_is_total():
            raise MergeEligibilityInputError(
                "MergeEligibilityPolicy.verifier_rule must resolve all 12 "
                "identity x independence combinations via first match"
            )
        for row in self.verifier_rule:
            if row.reason is not None and row.reason not in known_codes:
                raise MergeEligibilityInputError(
                    f"MergeEligibilityPolicy.verifier_rule references unknown "
                    f"reason code {row.reason!r}"
                )

    def _verifier_rule_is_total(self) -> bool:
        for identity in VerifierIdentityStatus:
            for independence in VerifierIndependenceStatus:
                if not any(
                    row.matches(identity.value, independence.value)
                    for row in self.verifier_rule
                ):
                    return False
        return True

    def resolve_verifier_reason(self, identity: str, independence: str) -> str | None:
        """First-match resolution over the ordered rule table (structural
        lookup over already-total policy data; not evaluator logic)."""
        for row in self.verifier_rule:
            if row.matches(identity, independence):
                return row.reason
        raise MergeEligibilityInputError(
            f"no verifier_rule row matches ({identity!r}, {independence!r})"
        )


# ---------------------------------------------------------------------------
# Production policy constant — MERGE_ELIGIBILITY_POLICY_V1
# ---------------------------------------------------------------------------

_MAJORITY_POLICY_VERSION = "changegate-merge-eligibility-policy.v2-draft"
_MAJORITY_POLICY_DIGEST = (
    "sha256:88304ee85d7d10c2124d75b0de11cb8d8f91a8707945cabc651c0cbdedc71934"
)

_REASON_DEFINITIONS: tuple[ReasonDefinition, ...] = (
    ReasonDefinition("AUTHORITY_INVALID", 10, "INTEGRITY", "FACTUAL", Disposition.BLOCK, None),
    ReasonDefinition(
        "REQUIRED_CONTEXT_INCOMPLETE", 20, "CONTEXT", "FACTUAL", Disposition.BLOCK, None
    ),
    ReasonDefinition(
        "EVIDENCE_TASK_MISMATCH", 30, "INTEGRITY", "FACTUAL", Disposition.BLOCK, None
    ),
    ReasonDefinition(
        "EVIDENCE_RUN_MISMATCH", 40, "INTEGRITY", "FACTUAL", Disposition.BLOCK, None
    ),
    ReasonDefinition(
        "EVIDENCE_CANDIDATE_MISMATCH", 50, "INTEGRITY", "FACTUAL", Disposition.BLOCK, None
    ),
    ReasonDefinition(
        "REPOSITORY_CONTEXT_MISMATCH", 60, "INTEGRITY", "FACTUAL", Disposition.BLOCK, None
    ),
    ReasonDefinition(
        "EVIDENCE_PROVENANCE_INVALID", 70, "INTEGRITY", "FACTUAL", Disposition.BLOCK, None
    ),
    ReasonDefinition(
        "EVIDENCE_DUPLICATE_IDENTITY", 80, "INTEGRITY", "FACTUAL", Disposition.BLOCK, None
    ),
    ReasonDefinition(
        "REQUIRED_EVIDENCE_INVALID", 90, "EVIDENCE", "FACTUAL", Disposition.BLOCK, None
    ),
    ReasonDefinition(
        "TASK_CONTEXT_STALE", 95, "FRESHNESS", "FACTUAL", Disposition.BLOCK, None
    ),
    ReasonDefinition("CANDIDATE_STALE", 100, "FRESHNESS", "FACTUAL", Disposition.BLOCK, None),
    ReasonDefinition(
        "POLICY_CONTEXT_STALE", 110, "FRESHNESS", "FACTUAL", Disposition.BLOCK, None
    ),
    ReasonDefinition(
        "REQUIRED_EVIDENCE_MISSING", 120, "EVIDENCE", "FACTUAL", Disposition.BLOCK, None
    ),
    ReasonDefinition(
        "RELEASE_STATE_NOT_CLEAN", 130, "REPO_STATE", "FACTUAL", Disposition.BLOCK, None
    ),
    ReasonDefinition("SCOPE_VIOLATION", 140, "SCOPE", "FACTUAL", Disposition.BLOCK, None),
    ReasonDefinition(
        "APPROVAL_MISSING", 150, "APPROVAL", "FACTUAL", Disposition.BLOCK, "OD-S1A-001"
    ),
    ReasonDefinition(
        "APPROVAL_STALE", 160, "APPROVAL", "FACTUAL", Disposition.BLOCK, "OD-S1A-002"
    ),
    ReasonDefinition(
        "VERIFIER_NOT_INDEPENDENT", 170, "INDEPENDENCE", "FACTUAL", Disposition.BLOCK, None
    ),
    ReasonDefinition(
        "SCOPE_UNCERTAIN", 180, "SCOPE", "SEMANTIC", Disposition.REVIEW_REQUIRED, None
    ),
    ReasonDefinition(
        "VERIFIER_INDEPENDENCE_UNKNOWN",
        190,
        "INDEPENDENCE",
        "SEMANTIC",
        Disposition.REVIEW_REQUIRED,
        "OD-S1A-003",
    ),
)

_ENUM_FACT_REASONS: Mapping[str, Mapping[str, str | None]] = MappingProxyType(
    {
        "task_context_current": MappingProxyType(
            {"CURRENT": None, "STALE": "TASK_CONTEXT_STALE", "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE"}
        ),
        "candidate_binding_current": MappingProxyType(
            {"CURRENT": None, "STALE": "CANDIDATE_STALE", "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE"}
        ),
        "repository_snapshot_current": MappingProxyType(
            {
                "CURRENT": None,
                "MISMATCH": "REPOSITORY_CONTEXT_MISMATCH",
                "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE",
            }
        ),
        "repository_release_clean": MappingProxyType(
            {"CLEAN": None, "DIRTY": "RELEASE_STATE_NOT_CLEAN", "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE"}
        ),
        "policy_context_current": MappingProxyType(
            {"CURRENT": None, "STALE": "POLICY_CONTEXT_STALE", "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE"}
        ),
        "evidence_context_status": MappingProxyType(
            {"COHERENT": None, "INCOHERENT": None, "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE"}
        ),
        "scope_status": MappingProxyType(
            {
                "COMPLIANT": None,
                "VIOLATION": "SCOPE_VIOLATION",
                "SEMANTIC_UNCERTAIN": "SCOPE_UNCERTAIN",
                "NOT_EVALUATED": "REQUIRED_CONTEXT_INCOMPLETE",
            }
        ),
        "approval_status": MappingProxyType(
            {
                "VALID": None,
                "MISSING": "APPROVAL_MISSING",
                "STALE": "APPROVAL_STALE",
                "UNKNOWN": "APPROVAL_MISSING",
            }
        ),
        "authority_status": MappingProxyType(
            {"VALID": None, "INVALID": "AUTHORITY_INVALID", "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE"}
        ),
    }
)

_VIOLATION_TAG_REASONS: Mapping[str, str] = MappingProxyType(
    {
        "TASK_MISMATCH": "EVIDENCE_TASK_MISMATCH",
        "RUN_MISMATCH": "EVIDENCE_RUN_MISMATCH",
        "CANDIDATE_MISMATCH": "EVIDENCE_CANDIDATE_MISMATCH",
        "PROVENANCE_INVALID": "EVIDENCE_PROVENANCE_INVALID",
        "DUPLICATE_IDENTITY": "EVIDENCE_DUPLICATE_IDENTITY",
    }
)

_SET_FACT_TRIGGERS: Mapping[str, str | None] = MappingProxyType(
    {
        "required_requirement_ids": None,
        "satisfied_requirement_ids": None,
        "missing_requirement_ids": "REQUIRED_EVIDENCE_MISSING",
        "invalid_requirement_ids": "REQUIRED_EVIDENCE_INVALID",
        "invalid_provenance_evidence_ids": "EVIDENCE_PROVENANCE_INVALID",
        "rejected_evidence_ids": None,
        "unexpected_evidence_ids": None,
    }
)

_VERIFIER_RULE: tuple[VerifierRuleRow, ...] = (
    VerifierRuleRow(("INVALID",), None, "AUTHORITY_INVALID"),
    VerifierRuleRow(("ABSENT",), None, "REQUIRED_CONTEXT_INCOMPLETE"),
    VerifierRuleRow(
        ("ATTESTED", "PRESENT_UNATTESTED"), ("NOT_INDEPENDENT",), "VERIFIER_NOT_INDEPENDENT"
    ),
    VerifierRuleRow(("ATTESTED",), ("INDEPENDENT",), None),
    VerifierRuleRow(("ATTESTED",), ("UNKNOWN",), "VERIFIER_INDEPENDENCE_UNKNOWN"),
    VerifierRuleRow(
        ("PRESENT_UNATTESTED",), ("INDEPENDENT", "UNKNOWN"), "VERIFIER_INDEPENDENCE_UNKNOWN"
    ),
)

MERGE_ELIGIBILITY_POLICY_V1 = MergeEligibilityPolicy(
    declared_identity=PolicyIdentity(
        policy_version=_MAJORITY_POLICY_VERSION,
        policy_digest=_MAJORITY_POLICY_DIGEST,
    ),
    reason_definitions=_REASON_DEFINITIONS,
    enum_fact_reasons=_ENUM_FACT_REASONS,
    violation_tag_reasons=_VIOLATION_TAG_REASONS,
    set_fact_triggers=_SET_FACT_TRIGGERS,
    verifier_rule=_VERIFIER_RULE,
)

"""Versioned registries and deterministic semantic replay for ChangeGate.

This Gate 1B-D leaf module resolves the exact policy and evaluator identities
stored in a canonical record, then independently replays the pure evaluator.
It deliberately has no facade, persistence, event, adapter, or runtime-loading
dependency.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import InitVar, dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from agent_core.build_harness.merge_eligibility import (
    DecisionCore,
    EvaluatorIdentity,
    MergeEligibilityPolicy,
    MergeEligibilityPolicyInput,
    PolicyIdentity,
)
from agent_core.build_harness.merge_eligibility_record import (
    PolicyEvaluationRecord,
    build_policy_evaluation_record,
    finalize_decision,
    validate_policy_evaluation_record,
)

__all__ = [
    "EvaluatorRegistry",
    "PolicyRegistry",
    "RegistryConstructionError",
    "ReplayClassification",
    "SemanticReplayResult",
    "verify_semantic_replay",
]


class RegistryConstructionError(ValueError):
    """A versioned replay registry was not constructed deterministically."""


class ReplayClassification(StrEnum):
    RECORD_STRUCTURALLY_INVALID = "RECORD_STRUCTURALLY_INVALID"
    INPUT_BINDING_MISMATCH = "INPUT_BINDING_MISMATCH"
    UNKNOWN_POLICY_IDENTITY = "UNKNOWN_POLICY_IDENTITY"
    UNKNOWN_EVALUATOR_IDENTITY = "UNKNOWN_EVALUATOR_IDENTITY"
    SEMANTIC_REPLAY_MISMATCH = "SEMANTIC_REPLAY_MISMATCH"
    SEMANTICALLY_REPLAY_VERIFIED = "SEMANTICALLY_REPLAY_VERIFIED"


CoreEvaluator = Callable[[MergeEligibilityPolicyInput, MergeEligibilityPolicy], DecisionCore]
_SLICE_1B_LIMIT_DIAGNOSTICS: Final[tuple[str, ...]] = (
    "NOT_VERIFIED_IN_SLICE_1B:FACTS_VS_REALITY",
    "NOT_VERIFIED_IN_SLICE_1B:IDENTIFIER_UNIVERSE_TRUTH",
    "NOT_VERIFIED_IN_SLICE_1B:POLICY_ARTIFACT_PROVENANCE",
    "NOT_VERIFIED_IN_SLICE_1B:SOURCE_BINDING_AUTHENTICITY",
)
_DECISION_FIELDS: Final[tuple[str, ...]] = (
    "disposition",
    "decision_authority",
    "primary_reason_code",
    "complete_reason_codes",
    "blocking_reason_codes",
    "review_reason_codes",
    "required_requirement_ids",
    "satisfied_requirement_ids",
    "invalid_requirement_ids",
    "missing_requirement_ids",
    "rejected_evidence_ids",
    "invalid_provenance_evidence_ids",
    "unexpected_evidence_ids",
    "decision_digest",
)
_ACCOUNTING_FIELDS: Final[tuple[str, ...]] = _DECISION_FIELDS[6:13]
_TUPLE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "complete_reason_codes",
        "blocking_reason_codes",
        "review_reason_codes",
        *_ACCOUNTING_FIELDS,
    }
)


def _pairs(source: object, name: str) -> Iterable[tuple[object, object]]:
    if isinstance(source, Mapping):
        return source.items()
    try:
        return tuple(source)  # type: ignore[arg-type]
    except TypeError as error:
        raise RegistryConstructionError(f"{name} entries must be a mapping or pairs") from error


@dataclass(frozen=True)
class PolicyRegistry:
    """An immutable registry keyed by the complete declared policy identity."""

    source: InitVar[Mapping[PolicyIdentity, MergeEligibilityPolicy] | Iterable[
        tuple[PolicyIdentity, MergeEligibilityPolicy]
    ]]
    entries: Mapping[PolicyIdentity, MergeEligibilityPolicy] = field(init=False)

    def __post_init__(self, source: object) -> None:
        built: dict[PolicyIdentity, MergeEligibilityPolicy] = {}
        for key, policy in _pairs(source, "policy"):
            if type(key) is not PolicyIdentity or type(policy) is not MergeEligibilityPolicy:  # noqa: E721
                raise RegistryConstructionError("policy entries require exact identity and policy values")
            if key != policy.declared_identity:
                raise RegistryConstructionError("policy registry key must equal declared policy identity")
            if key in built:
                raise RegistryConstructionError("duplicate policy identity")
            built[key] = policy
        ordered = dict(sorted(built.items(), key=lambda item: (item[0].policy_version, item[0].policy_digest)))
        object.__setattr__(self, "entries", MappingProxyType(ordered))

    def resolve(self, identity: PolicyIdentity) -> MergeEligibilityPolicy | None:
        return self.entries.get(identity)

    def has_version(self, policy_version: str) -> bool:
        return any(identity.policy_version == policy_version for identity in self.entries)


@dataclass(frozen=True)
class EvaluatorRegistry:
    """An immutable registry keyed by exact evaluator-version identity."""

    source: InitVar[Mapping[str, CoreEvaluator] | Iterable[tuple[str, CoreEvaluator]]]
    entries: Mapping[str, CoreEvaluator] = field(init=False)

    def __post_init__(self, source: object) -> None:
        built: dict[str, CoreEvaluator] = {}
        for key, evaluator in _pairs(source, "evaluator"):
            if type(key) is not str or not callable(evaluator):  # noqa: E721
                raise RegistryConstructionError("evaluator entries require a version string and callable")
            try:
                EvaluatorIdentity(key)
            except ValueError as error:
                raise RegistryConstructionError("invalid evaluator identity") from error
            if key in built:
                raise RegistryConstructionError("duplicate evaluator identity")
            built[key] = evaluator
        object.__setattr__(self, "entries", MappingProxyType(dict(sorted(built.items()))))

    def resolve(self, evaluator_version: str) -> CoreEvaluator | None:
        return self.entries.get(evaluator_version)


@dataclass(frozen=True)
class SemanticReplayResult:
    """Deterministic, bounded result of a Gate 1B-D semantic replay."""

    classification: ReplayClassification
    mismatch_codes: tuple[str, ...]
    diagnostics: tuple[str, ...]
    record_structurally_valid: bool
    policy_identity_resolved: bool
    evaluator_identity_resolved: bool
    semantic_replay_performed: bool
    decision_identity_matches: bool
    record_identity_matches: bool

    def __post_init__(self) -> None:
        if type(self.classification) is not ReplayClassification:
            raise ValueError("classification must be a ReplayClassification")
        for name in ("mismatch_codes", "diagnostics"):
            value = getattr(self, name)
            if type(value) is not tuple or any(type(item) is not str for item in value):  # noqa: E721
                raise ValueError(f"{name} must be a tuple of strings")
            if value != tuple(sorted(set(value))):
                raise ValueError(f"{name} must be sorted and duplicate-free")
        for name in (
            "record_structurally_valid",
            "policy_identity_resolved",
            "evaluator_identity_resolved",
            "semantic_replay_performed",
            "decision_identity_matches",
            "record_identity_matches",
        ):
            if type(getattr(self, name)) is not bool:  # noqa: E721
                raise ValueError(f"{name} must be bool")


def _result(
    classification: ReplayClassification,
    *,
    mismatch_codes: Iterable[str] = (),
    diagnostics: Iterable[str] = (),
    record_structurally_valid: bool,
    policy_identity_resolved: bool = False,
    evaluator_identity_resolved: bool = False,
    semantic_replay_performed: bool = False,
    decision_identity_matches: bool = False,
    record_identity_matches: bool = False,
) -> SemanticReplayResult:
    return SemanticReplayResult(
        classification=classification,
        mismatch_codes=tuple(sorted(set(mismatch_codes))),
        diagnostics=tuple(sorted(set((*_SLICE_1B_LIMIT_DIAGNOSTICS, *diagnostics)))),
        record_structurally_valid=record_structurally_valid,
        policy_identity_resolved=policy_identity_resolved,
        evaluator_identity_resolved=evaluator_identity_resolved,
        semantic_replay_performed=semantic_replay_performed,
        decision_identity_matches=decision_identity_matches,
        record_identity_matches=record_identity_matches,
    )


def _record_value(record: object, field: str) -> object:
    value = getattr(record, field) if type(record) is PolicyEvaluationRecord else record[field]  # type: ignore[index]  # noqa: E721
    if hasattr(value, "value"):
        value = value.value
    return tuple(value) if field in _TUPLE_FIELDS else value


def _mismatch_codes(replayed: PolicyEvaluationRecord, stored: object) -> tuple[str, ...]:
    codes: set[str] = set()
    if replayed.disposition.value != _record_value(stored, "disposition"):
        codes.add("DISPOSITION_MISMATCH")
    if replayed.primary_reason_code != _record_value(stored, "primary_reason_code"):
        codes.add("PRIMARY_REASON_MISMATCH")
    if replayed.complete_reason_codes != _record_value(stored, "complete_reason_codes"):
        codes.add("REASON_SET_MISMATCH")
    if (
        replayed.blocking_reason_codes != _record_value(stored, "blocking_reason_codes")
        or replayed.review_reason_codes != _record_value(stored, "review_reason_codes")
    ):
        codes.add("PARTITION_MISMATCH")
    if any(getattr(replayed, field) != _record_value(stored, field) for field in _ACCOUNTING_FIELDS):
        codes.add("ACCOUNTING_MISMATCH")
    if replayed.decision_digest != _record_value(stored, "decision_digest"):
        codes.add("DECISION_DIGEST_MISMATCH")
    if replayed.policy_record_digest != _record_value(stored, "policy_record_digest"):
        codes.add("RECORD_DIGEST_MISMATCH")
    return tuple(sorted(codes))


def verify_semantic_replay(
    canonical_input: MergeEligibilityPolicyInput,
    record: PolicyEvaluationRecord,
    policy_registry: PolicyRegistry,
    evaluator_registry: EvaluatorRegistry,
) -> SemanticReplayResult:
    """Validate, exactly resolve, and replay a canonical policy record.

    Structural and input-binding failures short-circuit before any registry
    lookup or evaluator invocation. Unexpected infrastructure faults are left
    visible to the caller instead of being fabricated as protocol outcomes.
    """
    structural = validate_policy_evaluation_record(record)
    if structural["errors"]:
        return _result(
            ReplayClassification.RECORD_STRUCTURALLY_INVALID,
            diagnostics=structural["errors"],
            record_structurally_valid=False,
        )

    binding = validate_policy_evaluation_record(record, canonical_input)
    if binding["errors"]:
        return _result(
            ReplayClassification.INPUT_BINDING_MISMATCH,
            diagnostics=binding["errors"],
            record_structurally_valid=True,
        )

    policy_identity = PolicyIdentity(
        str(_record_value(record, "policy_version")),
        str(_record_value(record, "policy_digest")),
    )
    policy = policy_registry.resolve(policy_identity)
    if policy is None:
        diagnostics = ("POLICY_DIGEST_MISMATCH",) if policy_registry.has_version(policy_identity.policy_version) else ()
        return _result(
            ReplayClassification.UNKNOWN_POLICY_IDENTITY,
            diagnostics=diagnostics,
            record_structurally_valid=True,
        )

    evaluator_version = str(_record_value(record, "evaluator_version"))
    evaluator = evaluator_registry.resolve(evaluator_version)
    if evaluator is None:
        return _result(
            ReplayClassification.UNKNOWN_EVALUATOR_IDENTITY,
            record_structurally_valid=True,
            policy_identity_resolved=True,
        )

    core = evaluator(canonical_input, policy)
    replayed_decision = finalize_decision(canonical_input, core)
    replayed_record = build_policy_evaluation_record(canonical_input, replayed_decision)
    mismatches = _mismatch_codes(replayed_record, record)
    decision_matches = replayed_decision.decision_digest == _record_value(record, "decision_digest")
    record_matches = replayed_record.policy_record_digest == _record_value(record, "policy_record_digest")
    if mismatches:
        return _result(
            ReplayClassification.SEMANTIC_REPLAY_MISMATCH,
            mismatch_codes=mismatches,
            record_structurally_valid=True,
            policy_identity_resolved=True,
            evaluator_identity_resolved=True,
            semantic_replay_performed=True,
            decision_identity_matches=decision_matches,
            record_identity_matches=record_matches,
        )
    return _result(
        ReplayClassification.SEMANTICALLY_REPLAY_VERIFIED,
        record_structurally_valid=True,
        policy_identity_resolved=True,
        evaluator_identity_resolved=True,
        semantic_replay_performed=True,
        decision_identity_matches=True,
        record_identity_matches=True,
    )

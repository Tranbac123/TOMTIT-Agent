"""Canonical, deterministic ChangeGate merge-eligibility records.

This module deliberately attaches identity to an already-evaluated
``DecisionCore``.  It contains no policy lookup or semantic evaluation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from agent_core.build_harness.canonical import (
    canonical_digest,
    is_exact_dict,
    is_exact_list,
    is_exact_str,
    is_exact_tuple,
)
from agent_core.build_harness.merge_eligibility import (
    APPROVAL_SENTINEL,
    CANONICALIZATION_CONTRACT_DIGEST,
    CANONICALIZATION_VERSION,
    POLICY_RECORD_SCHEMA_DIGEST,
    POLICY_RECORD_SCHEMA_VERSION,
    DecisionAuthority,
    DecisionCore,
    Disposition,
    EvaluationMode,
    MergeEligibilityPolicyInput,
)

__all__ = [
    "RecordConstructionError",
    "MergeEligibilityDecision",
    "PolicyEvaluationRecord",
    "decision_digest_for",
    "finalize_decision",
    "build_policy_evaluation_record",
    "validate_policy_evaluation_record",
]


class RecordConstructionError(ValueError):
    """An internal inconsistency prevented canonical record construction."""


_DECISION_KIND = "changegate.merge-eligibility-decision.test-oracle.v1"
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
_CORE_FIELDS = (
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
)
_IDENTITY_FIELDS = (
    "task_id",
    *_SOURCE_BINDING_FIELDS,
    "policy_version",
    "evaluator_version",
    "evaluation_mode",
    "input_digest",
    *_CORE_FIELDS,
)
_ACCOUNTING_FIELDS = _CORE_FIELDS[6:]
_RE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_RE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_REASON_CODES = frozenset(
    {
        "AUTHORITY_INVALID", "REQUIRED_CONTEXT_INCOMPLETE",
        "EVIDENCE_TASK_MISMATCH", "EVIDENCE_RUN_MISMATCH",
        "EVIDENCE_CANDIDATE_MISMATCH", "REPOSITORY_CONTEXT_MISMATCH",
        "EVIDENCE_PROVENANCE_INVALID", "EVIDENCE_DUPLICATE_IDENTITY",
        "REQUIRED_EVIDENCE_INVALID", "TASK_CONTEXT_STALE", "CANDIDATE_STALE",
        "POLICY_CONTEXT_STALE", "REQUIRED_EVIDENCE_MISSING",
        "RELEASE_STATE_NOT_CLEAN", "SCOPE_VIOLATION", "APPROVAL_MISSING",
        "APPROVAL_STALE", "VERIFIER_NOT_INDEPENDENT", "SCOPE_UNCERTAIN",
        "VERIFIER_INDEPENDENCE_UNKNOWN",
    }
)


def _value(value: Any) -> Any:
    return value.value if isinstance(value, (Disposition, DecisionAuthority, EvaluationMode)) else value


def _identity_payload(source: object) -> dict[str, Any]:
    return {field: _value(getattr(source, field)) for field in _IDENTITY_FIELDS}


def _record_payload(source: object) -> dict[str, Any]:
    return {
        "schema_version": getattr(source, "schema_version"),
        **_identity_payload(source),
        "decision_digest": getattr(source, "decision_digest"),
    }


def _require_digest(value: object, field: str, *, sentinel: bool = False) -> None:
    if not is_exact_str(value) or (sentinel and value == APPROVAL_SENTINEL):
        if sentinel and value == APPROVAL_SENTINEL:
            return
        raise RecordConstructionError(f"{field} must be a canonical digest")
    if not _RE_DIGEST.fullmatch(value):
        raise RecordConstructionError(f"{field} must be a canonical digest")


def _require_token(value: object, field: str) -> None:
    if not is_exact_str(value) or not _RE_TOKEN.fullmatch(value):
        raise RecordConstructionError(f"{field} must match the committed token grammar")


def _require_tuple(value: object, field: str, *, reason: bool = False) -> None:
    if not is_exact_tuple(value):
        raise RecordConstructionError(f"{field} must be an exact tuple")
    pattern = _RE_CODE if reason else _RE_TOKEN
    if any(not is_exact_str(item) or not item or not pattern.fullmatch(item) for item in value):
        raise RecordConstructionError(f"{field} must contain valid identifiers")
    if list(value) != sorted(value) or len(set(value)) != len(value):
        raise RecordConstructionError(f"{field} must be sorted and duplicate-free")
    if reason and any(item not in _REASON_CODES for item in value):
        raise RecordConstructionError(f"{field} contains an unknown reason code")


def _validate_decision_fields(source: object) -> None:
    if type(getattr(source, "disposition")) is not Disposition:
        raise RecordConstructionError("disposition must be a Disposition member")
    if type(getattr(source, "decision_authority")) is not DecisionAuthority:
        raise RecordConstructionError("decision_authority must be a DecisionAuthority member")
    primary = getattr(source, "primary_reason_code")
    if primary is not None and (not is_exact_str(primary) or primary not in _REASON_CODES):
        raise RecordConstructionError("primary_reason_code must be a known reason code or None")
    for field in _CORE_FIELDS[3:6]:
        _require_tuple(getattr(source, field), field, reason=True)
    for field in _ACCOUNTING_FIELDS:
        _require_tuple(getattr(source, field), field)
    complete = set(getattr(source, "complete_reason_codes"))
    blocking = set(getattr(source, "blocking_reason_codes"))
    review = set(getattr(source, "review_reason_codes"))
    if blocking & review or blocking | review != complete:
        raise RecordConstructionError("reason partitions must be disjoint and exhaustive")
    if (primary is None) != (not complete) or primary is not None and primary not in complete:
        raise RecordConstructionError("primary reason must agree with complete reasons")
    expected = Disposition.BLOCK if blocking else Disposition.REVIEW_REQUIRED if review else Disposition.ELIGIBLE_TO_MERGE_UNDER_POLICY
    if getattr(source, "disposition") is not expected:
        raise RecordConstructionError("disposition must be derived from reason partitions")
    required = set(getattr(source, "required_requirement_ids"))
    partitions = [set(getattr(source, field)) for field in _ACCOUNTING_FIELDS[1:4]]
    if set().union(*partitions) != required or any(left & right for number, left in enumerate(partitions) for right in partitions[number + 1:]):
        raise RecordConstructionError("requirement accounting partitions must be disjoint and exhaustive")


def _validate_identity_fields(source: object, *, include_digest: bool) -> None:
    _require_token(getattr(source, "task_id"), "task_id")
    for field in _SOURCE_BINDING_FIELDS:
        _require_digest(getattr(source, field), field, sentinel=field == "approval_digest_or_sentinel")
    _require_token(getattr(source, "policy_version"), "policy_version")
    _require_token(getattr(source, "evaluator_version"), "evaluator_version")
    if type(getattr(source, "evaluation_mode")) is not EvaluationMode:
        raise RecordConstructionError("evaluation_mode must be an EvaluationMode member")
    _require_digest(getattr(source, "input_digest"), "input_digest")
    _validate_decision_fields(source)
    if include_digest:
        _require_digest(getattr(source, "decision_digest"), "decision_digest")


def decision_digest_for(identity: Mapping[str, Any]) -> str:
    """Return the manifest-bound digest for an exact 26-field identity payload."""
    if not is_exact_dict(identity) or set(identity) != set(_IDENTITY_FIELDS):
        raise RecordConstructionError("decision identity payload has an invalid field set")
    return canonical_digest({"kind": _DECISION_KIND, **{field: _value(identity[field]) for field in _IDENTITY_FIELDS}})


@dataclass(frozen=True)
class MergeEligibilityDecision:
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
    input_digest: str
    disposition: Disposition
    decision_authority: DecisionAuthority
    primary_reason_code: str | None
    complete_reason_codes: tuple[str, ...]
    blocking_reason_codes: tuple[str, ...]
    review_reason_codes: tuple[str, ...]
    required_requirement_ids: tuple[str, ...]
    satisfied_requirement_ids: tuple[str, ...]
    invalid_requirement_ids: tuple[str, ...]
    missing_requirement_ids: tuple[str, ...]
    rejected_evidence_ids: tuple[str, ...]
    invalid_provenance_evidence_ids: tuple[str, ...]
    unexpected_evidence_ids: tuple[str, ...]
    decision_digest: str

    def __post_init__(self) -> None:
        _validate_identity_fields(self, include_digest=True)
        if self.decision_digest != decision_digest_for(_identity_payload(self)):
            raise RecordConstructionError("decision_digest is inconsistent with decision identity")


@dataclass(frozen=True)
class PolicyEvaluationRecord:
    schema_version: str
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
    input_digest: str
    disposition: Disposition
    decision_authority: DecisionAuthority
    primary_reason_code: str | None
    complete_reason_codes: tuple[str, ...]
    blocking_reason_codes: tuple[str, ...]
    review_reason_codes: tuple[str, ...]
    required_requirement_ids: tuple[str, ...]
    satisfied_requirement_ids: tuple[str, ...]
    invalid_requirement_ids: tuple[str, ...]
    missing_requirement_ids: tuple[str, ...]
    rejected_evidence_ids: tuple[str, ...]
    invalid_provenance_evidence_ids: tuple[str, ...]
    unexpected_evidence_ids: tuple[str, ...]
    decision_digest: str
    policy_record_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != POLICY_RECORD_SCHEMA_VERSION:
            raise RecordConstructionError("schema_version is not the committed record schema")
        _validate_identity_fields(self, include_digest=True)
        _require_digest(self.policy_record_digest, "policy_record_digest")
        if self.decision_digest != decision_digest_for(_identity_payload(self)):
            raise RecordConstructionError("decision_digest is inconsistent with record identity")
        if self.policy_record_digest != canonical_digest(_record_payload(self)):
            raise RecordConstructionError("policy_record_digest is inconsistent with record payload")

    def to_canonical_payload(self) -> dict[str, Any]:
        payload = _record_payload(self)
        return {
            field: list(value) if is_exact_tuple(value) else value
            for field, value in payload.items()
        }


def _input_echoes_match(policy_input: MergeEligibilityPolicyInput, source: object) -> bool:
    return all(getattr(policy_input, field) == getattr(source, field) for field in ("task_id", *_SOURCE_BINDING_FIELDS, "policy_version", "evaluator_version", "evaluation_mode"))


def _core_matches_input(policy_input: MergeEligibilityPolicyInput, core: DecisionCore) -> bool:
    return all(getattr(policy_input.facts, field) == getattr(core, field) for field in _ACCOUNTING_FIELDS)


def finalize_decision(policy_input: MergeEligibilityPolicyInput, core: DecisionCore) -> MergeEligibilityDecision:
    if type(policy_input) is not MergeEligibilityPolicyInput or type(core) is not DecisionCore:
        raise RecordConstructionError("finalize_decision requires exact policy input and DecisionCore")
    if not _core_matches_input(policy_input, core):
        raise RecordConstructionError("DecisionCore accounting does not match policy input facts")
    input_digest = policy_input.input_digest()
    values = {
        field: getattr(policy_input, field) if field in ("task_id", *_SOURCE_BINDING_FIELDS, "policy_version", "evaluator_version", "evaluation_mode") else getattr(core, field)
        for field in _IDENTITY_FIELDS
        if field != "input_digest"
    }
    values["input_digest"] = input_digest
    digest = decision_digest_for(values)
    return MergeEligibilityDecision(**values, decision_digest=digest)


def build_policy_evaluation_record(policy_input: MergeEligibilityPolicyInput, decision: MergeEligibilityDecision) -> PolicyEvaluationRecord:
    if type(policy_input) is not MergeEligibilityPolicyInput or type(decision) is not MergeEligibilityDecision:
        raise RecordConstructionError("builder requires exact policy input and MergeEligibilityDecision")
    if policy_input.input_digest() != decision.input_digest:
        raise RecordConstructionError("decision input_digest is inconsistent with policy input")
    if not _input_echoes_match(policy_input, decision):
        raise RecordConstructionError("decision input echoes are inconsistent with policy input")
    identity = _identity_payload(decision)
    if decision_digest_for(identity) != decision.decision_digest:
        raise RecordConstructionError("decision_digest is inconsistent with decision identity")
    payload = {"schema_version": POLICY_RECORD_SCHEMA_VERSION, **identity, "decision_digest": decision.decision_digest}
    values = {
        "schema_version": POLICY_RECORD_SCHEMA_VERSION,
        **{field: getattr(decision, field) for field in _IDENTITY_FIELDS},
        "decision_digest": decision.decision_digest,
    }
    return PolicyEvaluationRecord(**values, policy_record_digest=canonical_digest(payload))


def _result(errors: list[str]) -> dict[str, list[str]]:
    return {"errors": sorted(set(errors)), "classifications": [] if errors else ["STRUCTURALLY_VALIDATED", "IDENTITY_RECOMPUTED", "SEMANTIC_REPLAY_NOT_PERFORMED"]}


_RAW_RECORD_FIELD_ORDER = (
    "schema_version", *_IDENTITY_FIELDS, "decision_digest", "policy_record_digest",
)
_RAW_RECORD_FIELDS = frozenset(_RAW_RECORD_FIELD_ORDER)
_RAW_INPUT_FIELDS = frozenset(
    {
        "kind", "task_id", *_SOURCE_BINDING_FIELDS, "policy_version",
        "evaluator_version", "evaluation_mode", "policy_record_schema_version",
        "policy_record_schema_digest", "canonicalization_version",
        "canonicalization_contract_digest", "facts",
    }
)


def _raw_record_payload(record: object) -> dict[str, Any] | None:
    """Normalize only the two committed representations to a JSON payload."""
    if is_exact_dict(record):
        return record
    if type(record) is PolicyEvaluationRecord:
        return {
            field: (
                list(value) if is_exact_tuple(value) else _value(value)
            )
            for field, value in (
                (name, getattr(record, name)) for name in _RAW_RECORD_FIELD_ORDER
            )
        }
    return None


def _raw_string_list(value: object) -> bool:
    return is_exact_list(value) and all(is_exact_str(item) for item in value)


def _validate_raw_fields(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record["schema_version"] != POLICY_RECORD_SCHEMA_VERSION:
        errors.append("RECORD_TYPE_INVALID")
    if not is_exact_str(record["task_id"]) or not _RE_TOKEN.fullmatch(record["task_id"]):
        errors.append("RECORD_TYPE_INVALID")
    for field in ("policy_version", "evaluator_version"):
        if not is_exact_str(record[field]) or not _RE_TOKEN.fullmatch(record[field]):
            errors.append("RECORD_TYPE_INVALID")
    for field in (*_SOURCE_BINDING_FIELDS, "input_digest", "decision_digest", "policy_record_digest"):
        value = record[field]
        if field == "approval_digest_or_sentinel" and value == APPROVAL_SENTINEL:
            continue
        if not is_exact_str(value) or not _RE_DIGEST.fullmatch(value):
            errors.append("RECORD_TYPE_INVALID")
    enum_values = {
        "evaluation_mode": {item.value for item in EvaluationMode},
        "disposition": {item.value for item in Disposition},
        "decision_authority": {item.value for item in DecisionAuthority},
    }
    for field, allowed in enum_values.items():
        if not is_exact_str(record[field]) or record[field] not in allowed:
            errors.append("RECORD_TYPE_INVALID")
    for field in _CORE_FIELDS[3:]:
        value = record[field]
        if not _raw_string_list(value):
            errors.append("RECORD_TYPE_INVALID")
        elif value != sorted(value) or len(value) != len(set(value)):
            errors.append("RECORD_NOT_NORMALIZED")
    primary = record["primary_reason_code"]
    if primary is not None and (not is_exact_str(primary) or primary not in _REASON_CODES):
        errors.append("RECORD_TYPE_INVALID")
    for field in _CORE_FIELDS[3:6]:
        value = record[field]
        if _raw_string_list(value) and any(item not in _REASON_CODES for item in value):
            errors.append("RECORD_TYPE_INVALID")
    if all(_raw_string_list(record[field]) for field in _CORE_FIELDS[3:6]):
        complete = set(record["complete_reason_codes"])
        blocking = set(record["blocking_reason_codes"])
        review = set(record["review_reason_codes"])
        if blocking & review or blocking | review != complete:
            errors.append("RECORD_NOT_NORMALIZED")
        if (primary is None) != (not complete) or primary is not None and primary not in complete:
            errors.append("RECORD_NOT_NORMALIZED")
        expected = "BLOCK" if blocking else "REVIEW_REQUIRED" if review else "ELIGIBLE_TO_MERGE_UNDER_POLICY"
        if record["disposition"] != expected:
            errors.append("RECORD_NOT_NORMALIZED")
    requirement_fields = _ACCOUNTING_FIELDS[:4]
    if all(_raw_string_list(record[field]) for field in requirement_fields):
        parts = [set(record[field]) for field in requirement_fields[1:]]
        if set().union(*parts) != set(record[requirement_fields[0]]) or any(
            left & right for index, left in enumerate(parts) for right in parts[index + 1:]
        ):
            errors.append("RECORD_NOT_NORMALIZED")
    return errors


def _validate_input_binding(record: dict[str, Any], candidate: object) -> list[str]:
    if type(candidate) is MergeEligibilityPolicyInput:
        keys = ("task_id", *_SOURCE_BINDING_FIELDS, "policy_version", "evaluator_version", "evaluation_mode")
        if any(_value(getattr(candidate, key)) != record[key] for key in keys):
            return ["SOURCE_BINDING_MISMATCH"]
        return [] if candidate.input_digest() == record["input_digest"] else ["INPUT_DIGEST_MISMATCH"]
    if not is_exact_dict(candidate) or not all(is_exact_str(key) for key in candidate):
        return ["INPUT_NOT_AN_OBJECT"]
    keys = ("task_id", *_SOURCE_BINDING_FIELDS, "policy_version", "evaluator_version", "evaluation_mode")
    errors = ["SOURCE_BINDING_MISMATCH"] if any(candidate.get(key) != record[key] for key in keys) else []
    if candidate.get("policy_record_schema_version") != record["schema_version"] or candidate.get(
        "policy_record_schema_digest"
    ) != POLICY_RECORD_SCHEMA_DIGEST:
        errors.append("SCHEMA_BINDING_MISMATCH")
    if candidate.get("canonicalization_version") != CANONICALIZATION_VERSION or candidate.get(
        "canonicalization_contract_digest"
    ) != CANONICALIZATION_CONTRACT_DIGEST:
        errors.append("CANONICALIZATION_BINDING_MISMATCH")
    field_set_matches = set(candidate) == _RAW_INPUT_FIELDS
    try:
        input_digest = canonical_digest(candidate)
    except (TypeError, ValueError):
        return [*errors, "INPUT_NOT_CANONICALIZABLE"]
    if not field_set_matches or input_digest != record["input_digest"]:
        errors.append("INPUT_DIGEST_MISMATCH")
    return errors


def validate_policy_evaluation_record(record: object, canonical_input: object = None, identifier_universes: object = None) -> dict[str, list[str]]:
    """Total, fail-closed structural validation; it never performs semantic replay."""
    raw = _raw_record_payload(record)
    if raw is None or not all(is_exact_str(key) for key in raw):
        return _result(["RECORD_NOT_AN_OBJECT"])
    if set(raw) != _RAW_RECORD_FIELDS:
        return _result(["RECORD_FIELD_SET_DRIFT"])
    try:
        structural_errors = _validate_raw_fields(raw)
        if structural_errors:
            return _result(structural_errors)
        identity = {field: raw[field] for field in _IDENTITY_FIELDS}
        if raw["decision_digest"] != decision_digest_for(identity):
            return _result(["DECISION_DIGEST_NOT_DERIVED"])
        payload = {field: raw[field] for field in raw if field != "policy_record_digest"}
        if raw["policy_record_digest"] != canonical_digest(payload):
            return _result(["RECORD_DIGEST_MISMATCH"])
    except (KeyError, TypeError, ValueError, RecordConstructionError):
        return _result(["RECORD_TYPE_INVALID"])
    errors: list[str] = []
    if identifier_universes is not None:
        if not is_exact_dict(identifier_universes):
            errors.append("IDENTIFIER_UNIVERSES_INVALID")
        else:
            for fields, key in ((_ACCOUNTING_FIELDS[:4], "requirement_id_universe"), (_ACCOUNTING_FIELDS[4:], "evidence_record_id_universe")):
                universe = identifier_universes.get(key)
                if (not is_exact_tuple(universe) and not is_exact_list(universe)) or any(not is_exact_str(item) for item in universe):
                    errors.append("IDENTIFIER_UNIVERSES_INVALID")
                elif any(item not in universe for field in fields for item in raw[field]):
                    errors.append("IDENTIFIER_UNIVERSE_MISMATCH")
    if canonical_input is not None:
        errors.extend(_validate_input_binding(raw, canonical_input))
    return _result(errors)

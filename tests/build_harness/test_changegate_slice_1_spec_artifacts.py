"""Executable contract checks for ChangeGate Slice 1A R7 (artifact-only).

Slice 1A boundary (accepted OD-S1A-009): deterministic structural policy
contracts only. The validators in this module prove typed field correctness,
canonical representation, digest derivation, collection normalization,
binding consistency, identity recomputation, and total fail-closed structural
validation. They never perform, claim, or imply semantic replay: a
semantically forged but internally consistent policy result can be
STRUCTURALLY_VALIDATED and IDENTITY_RECOMPUTED, and is always
SEMANTIC_REPLAY_NOT_PERFORMED. SEMANTICALLY_REPLAY_VERIFIED is a Slice 1B
protocol status that no Slice 1A artifact may return.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from agent_core.build_harness.canonical import canonical_digest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs/strategy/CHANGEGATE_VERTICAL_MVP_SLICE_1_POLICY_SPEC.md"
FIXTURE = ROOT / "data/evals/changegate_merge_eligibility_golden_cases.json"
SCHEMA = ROOT / "data/schemas/changegate_evaluation_event_v1.schema.json"

EVENT_TYPES = {
    "CHANGEGATE_EVALUATION_COMPLETED",
    "CHANGEGATE_MERGE_ATTEMPTED",
    "CHANGEGATE_MERGE_COMPLETED",
    "CHANGEGATE_POST_MERGE_VALIDATION",
    "CHANGEGATE_ROLLBACK_RECORDED",
    "CHANGEGATE_USER_FEEDBACK_RECORDED",
}
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
TASK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MACHINE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")
APPROVAL_SENTINEL = "NO_APPROVAL_SUPPLIED"
SOURCE_BINDING_FIELDS = (
    "task_contract_digest",
    "candidate_digest",
    "repository_snapshot_digest",
    "verification_bundle_digest",
    "approval_digest_or_sentinel",
    "authority_binding_digest",
    "verifier_binding_digest",
    "policy_digest",
)
PAYLOAD_FIELDS = (
    "schema_version",
    "task_id",
    *SOURCE_BINDING_FIELDS[:4],
    *SOURCE_BINDING_FIELDS[4:],
    "policy_version",
    "evaluator_version",
    "evaluation_mode",
    "input_digest",
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
REASON_LIST_FIELDS = (
    "complete_reason_codes",
    "blocking_reason_codes",
    "review_reason_codes",
)
REQUIREMENT_LIST_FIELDS = (
    "required_requirement_ids",
    "satisfied_requirement_ids",
    "invalid_requirement_ids",
    "missing_requirement_ids",
)
EVIDENCE_LIST_FIELDS = (
    "rejected_evidence_ids",
    "invalid_provenance_evidence_ids",
    "unexpected_evidence_ids",
)
LIST_FIELDS = REASON_LIST_FIELDS + REQUIREMENT_LIST_FIELDS + EVIDENCE_LIST_FIELDS
LINEAGE = (
    "evaluation_id",
    "task_ref",
    "candidate_digest",
    "decision_digest",
    "input_digest",
    "policy_record_digest",
)
RUNTIME_FIELDS = {
    "trace_id",
    "request_id",
    "evaluation_id",
    "event_id",
    "occurred_at",
    "timestamp",
    "evaluation_latency_ms",
    "storage_location",
    "redaction_classification",
}
# Slice 1A structural classifications. SEMANTICALLY_REPLAY_VERIFIED is a
# Slice 1B protocol status and deliberately absent from this tuple.
SLICE_1A_CLASSIFICATIONS = (
    "STRUCTURALLY_VALIDATED",
    "IDENTITY_RECOMPUTED",
    "SEMANTIC_REPLAY_NOT_PERFORMED",
)
FORBIDDEN_CLASSIFICATION_VALUES = (
    "NOT_OVERRIDEABLE",
    "POLICY_EXCEPTION_REQUIRED",
    "HUMAN_REVIEW_RESOLVABLE",
)
REASON_ENTRY_FIELDS = {
    "code",
    "precedence_rank",
    "category",
    "kind",
    "default_disposition",
    "owner_decision_pending",
}
CASE_FIELDS = {
    "case_id",
    "summary",
    "tags",
    "identifier_universes",
    "policy_input_bindings",
    "policy_input_facts",
    "expected_disposition",
    "expected_decision_authority",
    "expected_primary_reason",
    "expected_complete_reason_codes",
    "expected_event_assertions",
    "owner_decisions_pending",
}
OPTIONAL_CASE_FIELDS = {"notes"}


def assert_case_shape(item: dict) -> None:
    assert CASE_FIELDS <= set(item) <= CASE_FIELDS | OPTIONAL_CASE_FIELDS, (
        item["case_id"]
    )

# --- Independent oracles (pinned here, never read from the fixture) --------

INDEPENDENT_PRECEDENCE_RANKS = {
    "AUTHORITY_INVALID": 10,
    "REQUIRED_CONTEXT_INCOMPLETE": 20,
    "EVIDENCE_TASK_MISMATCH": 30,
    "EVIDENCE_RUN_MISMATCH": 40,
    "EVIDENCE_CANDIDATE_MISMATCH": 50,
    "REPOSITORY_CONTEXT_MISMATCH": 60,
    "EVIDENCE_PROVENANCE_INVALID": 70,
    "EVIDENCE_DUPLICATE_IDENTITY": 80,
    "REQUIRED_EVIDENCE_INVALID": 90,
    "TASK_CONTEXT_STALE": 95,
    "CANDIDATE_STALE": 100,
    "POLICY_CONTEXT_STALE": 110,
    "REQUIRED_EVIDENCE_MISSING": 120,
    "RELEASE_STATE_NOT_CLEAN": 130,
    "SCOPE_VIOLATION": 140,
    "APPROVAL_MISSING": 150,
    "APPROVAL_STALE": 160,
    "VERIFIER_NOT_INDEPENDENT": 170,
    "SCOPE_UNCERTAIN": 180,
    "VERIFIER_INDEPENDENCE_UNKNOWN": 190,
}
INDEPENDENT_DEFAULT_DISPOSITIONS = {
    "AUTHORITY_INVALID": "BLOCK",
    "REQUIRED_CONTEXT_INCOMPLETE": "BLOCK",
    "EVIDENCE_TASK_MISMATCH": "BLOCK",
    "EVIDENCE_RUN_MISMATCH": "BLOCK",
    "EVIDENCE_CANDIDATE_MISMATCH": "BLOCK",
    "REPOSITORY_CONTEXT_MISMATCH": "BLOCK",
    "EVIDENCE_PROVENANCE_INVALID": "BLOCK",
    "EVIDENCE_DUPLICATE_IDENTITY": "BLOCK",
    "REQUIRED_EVIDENCE_INVALID": "BLOCK",
    "TASK_CONTEXT_STALE": "BLOCK",
    "CANDIDATE_STALE": "BLOCK",
    "POLICY_CONTEXT_STALE": "BLOCK",
    "REQUIRED_EVIDENCE_MISSING": "BLOCK",
    "RELEASE_STATE_NOT_CLEAN": "BLOCK",
    "SCOPE_VIOLATION": "BLOCK",
    "APPROVAL_MISSING": "BLOCK",
    "APPROVAL_STALE": "BLOCK",
    "VERIFIER_NOT_INDEPENDENT": "BLOCK",
    "SCOPE_UNCERTAIN": "REVIEW_REQUIRED",
    "VERIFIER_INDEPENDENCE_UNKNOWN": "REVIEW_REQUIRED",
}
ORACLE_ENUM_FACT_REASONS = {
    "task_context_current": {
        "CURRENT": None,
        "STALE": "TASK_CONTEXT_STALE",
        "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE",
    },
    "candidate_binding_current": {
        "CURRENT": None,
        "STALE": "CANDIDATE_STALE",
        "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE",
    },
    "repository_snapshot_current": {
        "CURRENT": None,
        "MISMATCH": "REPOSITORY_CONTEXT_MISMATCH",
        "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE",
    },
    "repository_release_clean": {
        "CLEAN": None,
        "DIRTY": "RELEASE_STATE_NOT_CLEAN",
        "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE",
    },
    "policy_context_current": {
        "CURRENT": None,
        "STALE": "POLICY_CONTEXT_STALE",
        "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE",
    },
    "evidence_context_status": {
        "COHERENT": None,
        "INCOHERENT": None,
        "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE",
    },
    "scope_status": {
        "COMPLIANT": None,
        "VIOLATION": "SCOPE_VIOLATION",
        "SEMANTIC_UNCERTAIN": "SCOPE_UNCERTAIN",
        "NOT_EVALUATED": "REQUIRED_CONTEXT_INCOMPLETE",
    },
    "approval_status": {
        "VALID": None,
        "MISSING": "APPROVAL_MISSING",
        "STALE": "APPROVAL_STALE",
        "UNKNOWN": "APPROVAL_MISSING",
    },
    "authority_status": {
        "VALID": None,
        "INVALID": "AUTHORITY_INVALID",
        "UNKNOWN": "REQUIRED_CONTEXT_INCOMPLETE",
    },
}
ORACLE_VIOLATION_TAG_REASONS = {
    "TASK_MISMATCH": "EVIDENCE_TASK_MISMATCH",
    "RUN_MISMATCH": "EVIDENCE_RUN_MISMATCH",
    "CANDIDATE_MISMATCH": "EVIDENCE_CANDIDATE_MISMATCH",
    "PROVENANCE_INVALID": "EVIDENCE_PROVENANCE_INVALID",
    "DUPLICATE_IDENTITY": "EVIDENCE_DUPLICATE_IDENTITY",
}
ORACLE_SET_FACT_REASONS = {
    "missing_requirement_ids": "REQUIRED_EVIDENCE_MISSING",
    "invalid_requirement_ids": "REQUIRED_EVIDENCE_INVALID",
    "invalid_provenance_evidence_ids": "EVIDENCE_PROVENANCE_INVALID",
}
VERIFIER_IDENTITY_VALUES = ("ATTESTED", "PRESENT_UNATTESTED", "ABSENT", "INVALID")
VERIFIER_INDEPENDENCE_VALUES = ("INDEPENDENT", "NOT_INDEPENDENT", "UNKNOWN")


def oracle_verifier_reason(identity: str, independence: str) -> str | None:
    """Pinned ordered first-match verifier rule (spec §15), total over 12 combos."""
    if identity == "INVALID":
        return "AUTHORITY_INVALID"
    if identity == "ABSENT":
        return "REQUIRED_CONTEXT_INCOMPLETE"
    if independence == "NOT_INDEPENDENT":
        return "VERIFIER_NOT_INDEPENDENT"
    if identity == "ATTESTED" and independence == "INDEPENDENT":
        return None
    return "VERIFIER_INDEPENDENCE_UNKNOWN"


def oracle_outcome(facts: dict, evaluation_mode: str) -> dict:
    """Derive a golden case's complete expectation from its facts alone."""
    reasons: set[str] = set()
    for fact, mapping in ORACLE_ENUM_FACT_REASONS.items():
        code = mapping[facts[fact]]
        if code:
            reasons.add(code)
    for tag in facts["evidence_context_violations"]:
        reasons.add(ORACLE_VIOLATION_TAG_REASONS[tag])
    for fact, code in ORACLE_SET_FACT_REASONS.items():
        if facts[fact]:
            reasons.add(code)
    verifier = oracle_verifier_reason(
        facts["verifier_identity_status"], facts["verifier_independence_status"]
    )
    if verifier:
        reasons.add(verifier)
    complete = sorted(reasons)
    blocking = [
        code
        for code in complete
        if INDEPENDENT_DEFAULT_DISPOSITIONS[code] == "BLOCK"
    ]
    review = [
        code
        for code in complete
        if INDEPENDENT_DEFAULT_DISPOSITIONS[code] == "REVIEW_REQUIRED"
    ]
    if blocking:
        disposition = "BLOCK"
    elif review:
        disposition = "REVIEW_REQUIRED"
    else:
        disposition = "ELIGIBLE_TO_MERGE_UNDER_POLICY"
    primary = (
        min(complete, key=INDEPENDENT_PRECEDENCE_RANKS.__getitem__)
        if complete
        else None
    )
    authority = "AUTHORITATIVE" if evaluation_mode == "ENFORCE" else "ADVISORY_ONLY"
    return {
        "complete_reason_codes": complete,
        "blocking_reason_codes": blocking,
        "review_reason_codes": review,
        "disposition": disposition,
        "primary_reason_code": primary,
        "decision_authority": authority,
    }


# --- Artifact loaders and builders ------------------------------------------


def fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def schema() -> dict:
    return json.loads(SCHEMA.read_text())


def validator() -> Draft202012Validator:
    value = schema()
    Draft202012Validator.check_schema(value)
    return Draft202012Validator(value)


def case(case_id: str = "GC-S1-001") -> dict:
    return copy.deepcopy(
        next(item for item in fixture()["cases"] if item["case_id"] == case_id)
    )


def identity() -> dict:
    return fixture()["slice_1a_semantic_manifest"]["deterministic_identity"]


def manifest() -> dict:
    return fixture()["slice_1a_semantic_manifest"]


def known_ids(key: str) -> set[str]:
    return {
        value
        for item in fixture()["cases"]
        for value in item["identifier_universes"][key]
    }


def input_payload(bindings: dict, facts: dict) -> dict:
    contract = identity()
    return {
        "kind": "changegate.merge-eligibility-policy-input.test-oracle.v1",
        "task_id": bindings["task_id"],
        **{field: bindings[field] for field in SOURCE_BINDING_FIELDS},
        "policy_version": bindings["policy_version"],
        "evaluator_version": bindings["evaluator_version"],
        "evaluation_mode": bindings["evaluation_mode"],
        "policy_record_schema_version": contract["policy_record_schema_version"],
        "policy_record_schema_digest": contract["policy_record_schema_digest"],
        "canonicalization_version": contract["canonicalization_version"],
        "canonicalization_contract_digest": contract[
            "canonicalization_contract_digest"
        ],
        "facts": {key: facts[key] for key in sorted(facts)},
    }


def decision_digest_for(record: dict) -> str:
    fields = fixture()["slice_1a_semantic_manifest"]["replay"][
        "decision_identity_fields"
    ]
    return canonical_digest(
        {
            "kind": "changegate.merge-eligibility-decision.test-oracle.v1",
            **{field: record[field] for field in fields},
        }
    )


def record_for(case_id: str = "GC-S1-001") -> tuple[dict, dict]:
    item = case(case_id)
    bindings, facts = item["policy_input_bindings"], item["policy_input_facts"]
    payload = {
        "schema_version": "changegate.policy-evaluation-record.v1",
        "task_id": bindings["task_id"],
        **{field: bindings[field] for field in SOURCE_BINDING_FIELDS},
        "policy_version": bindings["policy_version"],
        "evaluator_version": bindings["evaluator_version"],
        "evaluation_mode": bindings["evaluation_mode"],
        "input_digest": canonical_digest(input_payload(bindings, facts)),
        "disposition": item["expected_disposition"],
        "decision_authority": item["expected_decision_authority"],
        "primary_reason_code": item["expected_primary_reason"],
        "complete_reason_codes": item["expected_complete_reason_codes"],
        "blocking_reason_codes": [
            code
            for code in item["expected_complete_reason_codes"]
            if INDEPENDENT_DEFAULT_DISPOSITIONS[code] == "BLOCK"
        ],
        "review_reason_codes": [
            code
            for code in item["expected_complete_reason_codes"]
            if INDEPENDENT_DEFAULT_DISPOSITIONS[code] == "REVIEW_REQUIRED"
        ],
        **{
            field: sorted(facts[field])
            for field in REQUIREMENT_LIST_FIELDS + EVIDENCE_LIST_FIELDS
        },
    }
    payload["decision_digest"] = decision_digest_for(payload)
    return {
        **payload,
        "policy_record_digest": canonical_digest(payload),
    }, input_payload(bindings, facts)


def rehash(record: dict) -> dict:
    payload = {
        key: value for key, value in record.items() if key != "policy_record_digest"
    }
    return {**payload, "policy_record_digest": canonical_digest(payload)}


def rederive(record: dict) -> dict:
    """Recompute decision and record digests so identity is self-consistent."""
    payload = {
        key: value for key, value in record.items() if key != "policy_record_digest"
    }
    payload["decision_digest"] = decision_digest_for(payload)
    return {**payload, "policy_record_digest": canonical_digest(payload)}


# --- Total, fail-closed structural validation --------------------------------


def _valid_string(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and bool(pattern.fullmatch(value))


def _valid_string_list(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) for item in value
    )


def validate_record_structure(
    record: object, canonical_input: object = None
) -> dict:
    """Total, fail-closed Slice 1A structural validation of a policy record.

    Returns {"errors": [...], "classifications": [...]}. Accepts any
    JSON-compatible value without raising. On success the classifications are
    exactly SLICE_1A_CLASSIFICATIONS; this helper can never return a semantic
    replay status (SEMANTICALLY_REPLAY_VERIFIED is Slice 1B protocol only).
    """
    errors: list[str] = []
    if not isinstance(record, dict) or not all(
        isinstance(key, str) for key in record
    ):
        return {"errors": ["RECORD_NOT_AN_OBJECT"], "classifications": []}
    expected_fields = set(PAYLOAD_FIELDS) | {"policy_record_digest"}
    if set(record) != expected_fields:
        if RUNTIME_FIELDS & set(record):
            errors.append("RECORD_RUNTIME_FIELD")
        errors.append("RECORD_FIELD_SET_DRIFT")
        return {"errors": errors, "classifications": []}
    if record["schema_version"] != "changegate.policy-evaluation-record.v1":
        errors.append("RECORD_TYPE_INVALID")
    if not _valid_string(record["task_id"], TASK):
        errors.append("RECORD_TYPE_INVALID")
    for field in ("policy_version", "evaluator_version"):
        if not _valid_string(record[field], VERSION):
            errors.append("RECORD_TYPE_INVALID")
    digest_fields = set(SOURCE_BINDING_FIELDS) - {"approval_digest_or_sentinel"}
    digest_fields |= {"input_digest", "decision_digest", "policy_record_digest"}
    for field in sorted(digest_fields):
        if not _valid_string(record[field], DIGEST):
            errors.append("RECORD_TYPE_INVALID")
    approval = record["approval_digest_or_sentinel"]
    if not isinstance(approval, str) or (
        approval != APPROVAL_SENTINEL and not DIGEST.fullmatch(approval)
    ):
        errors.append("RECORD_TYPE_INVALID")
    if (
        record["evaluation_mode"] not in {"ENFORCE", "SHADOW"}
        or record["disposition"]
        not in {"ELIGIBLE_TO_MERGE_UNDER_POLICY", "REVIEW_REQUIRED", "BLOCK"}
        or record["decision_authority"] not in {"AUTHORITATIVE", "ADVISORY_ONLY"}
    ):
        errors.append("RECORD_TYPE_INVALID")
    taxonomy = {entry["code"] for entry in fixture()["reason_codes"]}
    for field in LIST_FIELDS:
        value = record[field]
        if not _valid_string_list(value):
            errors.append("RECORD_TYPE_INVALID")
        elif value != sorted(value) or len(value) != len(set(value)):
            errors.append("RECORD_NOT_NORMALIZED")
    primary = record["primary_reason_code"]
    if primary is not None and primary not in taxonomy:
        errors.append("RECORD_TYPE_INVALID")
    for field in REASON_LIST_FIELDS:
        value = record[field]
        if _valid_string_list(value) and any(
            code not in taxonomy for code in value
        ):
            errors.append("RECORD_TYPE_INVALID")
    for fields, universe_key in (
        (REQUIREMENT_LIST_FIELDS, "requirement_id_universe"),
        (EVIDENCE_LIST_FIELDS, "evidence_record_id_universe"),
    ):
        universe = known_ids(universe_key)
        for field in fields:
            value = record[field]
            if _valid_string_list(value) and any(
                item not in universe for item in value
            ):
                errors.append("RECORD_TYPE_INVALID")
    if all(_valid_string_list(record[field]) for field in REASON_LIST_FIELDS):
        blocking = set(record["blocking_reason_codes"])
        review = set(record["review_reason_codes"])
        if (
            blocking | review != set(record["complete_reason_codes"])
            or blocking & review
        ):
            errors.append("RECORD_NOT_NORMALIZED")
    if all(
        _valid_string_list(record[field]) for field in REQUIREMENT_LIST_FIELDS
    ):
        partitions = [set(record[field]) for field in REQUIREMENT_LIST_FIELDS[1:]]
        if set().union(*partitions) != set(
            record["required_requirement_ids"]
        ) or any(
            left & right
            for position, left in enumerate(partitions)
            for right in partitions[position + 1 :]
        ):
            errors.append("RECORD_NOT_NORMALIZED")
    if errors:
        return {"errors": errors, "classifications": []}
    if record["decision_digest"] != decision_digest_for(record):
        errors.append("DECISION_DIGEST_NOT_DERIVED")
    if record["policy_record_digest"] != canonical_digest(
        {key: value for key, value in record.items() if key != "policy_record_digest"}
    ):
        errors.append("RECORD_DIGEST_MISMATCH")
    if canonical_input is not None:
        errors.extend(_binding_consistency_errors(record, canonical_input))
    if errors:
        return {"errors": errors, "classifications": []}
    return {"errors": [], "classifications": list(SLICE_1A_CLASSIFICATIONS)}


def _binding_consistency_errors(record: dict, canonical_input: object) -> list[str]:
    """Equality of every binding already present in both record and input.

    This is a structural binding check only: it proves the record is bound to
    the presented canonical input, never that the disposition or reasons are
    the production evaluator's semantic result for that input.
    """
    if not isinstance(canonical_input, dict):
        return ["INPUT_NOT_AN_OBJECT"]
    errors: list[str] = []
    sentinel = object()
    for field in ("task_id", *SOURCE_BINDING_FIELDS):
        if record[field] != canonical_input.get(field, sentinel):
            errors.append("SOURCE_BINDING_MISMATCH")
    for field in ("policy_version", "evaluator_version", "evaluation_mode"):
        if record[field] != canonical_input.get(field, sentinel):
            errors.append("SOURCE_BINDING_MISMATCH")
    contract = identity()
    if canonical_input.get(
        "policy_record_schema_version", sentinel
    ) != record["schema_version"] or canonical_input.get(
        "policy_record_schema_digest", sentinel
    ) != contract["policy_record_schema_digest"]:
        errors.append("SCHEMA_BINDING_MISMATCH")
    if canonical_input.get(
        "canonicalization_version", sentinel
    ) != contract["canonicalization_version"] or canonical_input.get(
        "canonicalization_contract_digest", sentinel
    ) != contract["canonicalization_contract_digest"]:
        errors.append("CANONICALIZATION_BINDING_MISMATCH")
    try:
        input_digest = canonical_digest(canonical_input)
    except (TypeError, ValueError):
        return errors + ["INPUT_NOT_CANONICALIZABLE"]
    if record["input_digest"] != input_digest:
        errors.append("INPUT_DIGEST_MISMATCH")
    return errors


# --- Event and causal-graph validation ---------------------------------------


def dref(tag: str = "one") -> dict:
    def digest(field: str) -> str:
        return canonical_digest({field: tag})

    return {
        "evaluation_id": f"evaluation-{tag}",
        "task_ref": f"task-{tag}",
        "candidate_digest": digest("candidate"),
        "decision_digest": digest("decision"),
        "input_digest": digest("input"),
        "policy_record_digest": digest("record"),
        "disposition": "BLOCK",
        "decision_authority": "AUTHORITATIVE",
    }


def event(event_id: str, event_type: str, ref: dict, **extra: object) -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2026-07-17T00:00:00Z",
        "schema_version": "changegate-evaluation-event.v1",
        "product": "changegate",
        "project_ref": "project-1",
        "task_ref": ref["task_ref"],
        "run_ref": "run-1",
        "subject_ref": {
            "namespace": "changegate",
            "kind": "git_candidate",
            "value": "candidate",
            "commit_sha": "a" * 40,
            "digest": ref["candidate_digest"],
        },
        "provenance": {
            "emitter": "changegate",
            "emitter_version": "1.0",
            "trace_id": None,
            "request_id": None,
        },
        "privacy_classification": "INTERNAL",
        **extra,
    }


PARENTS = {
    "CHANGEGATE_EVALUATION_COMPLETED": (),
    "CHANGEGATE_MERGE_ATTEMPTED": (
        ("evaluation_event_ref", "CHANGEGATE_EVALUATION_COMPLETED", True),
    ),
    "CHANGEGATE_MERGE_COMPLETED": (
        ("attempt_event_ref", "CHANGEGATE_MERGE_ATTEMPTED", True),
    ),
    "CHANGEGATE_POST_MERGE_VALIDATION": (
        ("merge_event_ref", "CHANGEGATE_MERGE_COMPLETED", True),
    ),
    "CHANGEGATE_ROLLBACK_RECORDED": (
        ("merge_event_ref", "CHANGEGATE_MERGE_COMPLETED", True),
        ("validation_event_ref", "CHANGEGATE_POST_MERGE_VALIDATION", False),
    ),
    "CHANGEGATE_USER_FEEDBACK_RECORDED": (("target_event_ref", None, True),),
}


def validate_graph(events: list[dict]) -> list[str]:
    """Local causal validation over the contract's declared invariants.

    Bounded to the existing contract: event/evaluation uniqueness, immutable
    root identity, predecessor existence/type, orphan and cycle rejection,
    multi-parent same-lineage, changed-candidate-new-root, and the explicit
    event identity equality matrix (task, candidate, input digest).
    """
    errors: list[str] = []
    by_id: dict[str, dict] = {}
    lineages: dict[str, dict | None] = {}
    evaluations: dict[str, dict] = {}
    for item in events:
        eid, etype = item.get("event_id"), item.get("event_type")
        ref = item.get("decision_ref") or {}
        if not isinstance(eid, str) or etype not in PARENTS:
            errors.append("EVENT_MALFORMED")
            continue
        if eid in by_id:
            errors.append("EVENT_ID_DUPLICATE")
        # Explicit event identity equality matrix (duplicated identity values
        # already present in the event; no new binding is added).
        if item.get("task_ref") != ref.get("task_ref"):
            errors.append("TASK_IDENTITY_MISMATCH")
        subject = item.get("subject_ref") or {}
        if (
            isinstance(subject, dict)
            and subject.get("kind") == "git_candidate"
            and subject.get("digest") is not None
            and subject.get("digest") != ref.get("candidate_digest")
        ):
            errors.append("CANDIDATE_IDENTITY_MISMATCH")
        if etype == "CHANGEGATE_EVALUATION_COMPLETED" and item.get(
            "context_digest"
        ) != ref.get("input_digest"):
            errors.append("INPUT_DIGEST_REFERENCE_MISMATCH")
        parents = []
        for field, required_type, required in PARENTS[etype]:
            target = item.get(field)
            if target is None and not required:
                continue
            parent = by_id.get(target)
            if parent is None:
                errors.append("PREDECESSOR_MISSING")
            elif required_type and parent["event_type"] != required_type:
                errors.append("PREDECESSOR_TYPE")
            else:
                parents.append(lineages.get(parent["event_id"]))
                if (
                    etype == "CHANGEGATE_USER_FEEDBACK_RECORDED"
                    and item.get("target_event_type") != parent["event_type"]
                ):
                    errors.append("FEEDBACK_TARGET_TYPE_MISMATCH")
        if etype == "CHANGEGATE_EVALUATION_COMPLETED":
            lineage = {field: ref.get(field) for field in LINEAGE}
            if ref.get("evaluation_id") in evaluations:
                errors.append("EVALUATION_ID_DUPLICATE")
            evaluations[ref.get("evaluation_id")] = lineage
        elif not parents or any(parent is None for parent in parents):
            lineage = None
            errors.append("ORPHAN")
        elif any(parent != parents[0] for parent in parents[1:]):
            lineage = None
            errors.append("AMBIGUOUS_PREDECESSOR_LINEAGE")
        else:
            lineage = parents[0]
            for field in LINEAGE:
                if ref.get(field) != lineage[field]:
                    errors.append(
                        "EVALUATION_ID_DRIFT"
                        if field == "evaluation_id"
                        else "LINEAGE_DIVERGES"
                    )
        if lineage is not None:
            lineages[eid] = lineage
        by_id[eid] = item
    edges = {
        item["event_id"]: [
            item[field]
            for field, _, _ in PARENTS[item["event_type"]]
            if item.get(field)
        ]
        for item in events
        if isinstance(item.get("event_id"), str) and item.get("event_type") in PARENTS
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        found = any(walk(next_node) for next_node in edges[node] if next_node in edges)
        visiting.remove(node)
        visited.add(node)
        return found

    if any(walk(node) for node in edges):
        errors.append("CAUSAL_CYCLE")
    return errors


def evaluation_event(event_id: str, ref: dict) -> dict:
    return event(
        event_id,
        "CHANGEGATE_EVALUATION_COMPLETED",
        ref,
        decision_ref=ref,
        context_digest=ref["input_digest"],
        policy_version="policy.v7",
        evaluator_version="1.0",
        outcome={"status": "SUCCESS", "detail_code": "OK"},
    )


def chain_for(ref: dict, prefix: str) -> list[dict]:
    ok = {"status": "SUCCESS", "detail_code": "OK"}
    return [
        evaluation_event(f"{prefix}-root", ref),
        event(
            f"{prefix}-attempt",
            "CHANGEGATE_MERGE_ATTEMPTED",
            ref,
            decision_ref=ref,
            evaluation_event_ref=f"{prefix}-root",
            outcome=ok,
        ),
        event(
            f"{prefix}-merge",
            "CHANGEGATE_MERGE_COMPLETED",
            ref,
            decision_ref=ref,
            attempt_event_ref=f"{prefix}-attempt",
            outcome={**ok, "resulting_commit_sha": "b" * 40},
        ),
        event(
            f"{prefix}-validation",
            "CHANGEGATE_POST_MERGE_VALIDATION",
            ref,
            decision_ref=ref,
            merge_event_ref=f"{prefix}-merge",
            outcome=ok,
        ),
        event(
            f"{prefix}-rollback",
            "CHANGEGATE_ROLLBACK_RECORDED",
            ref,
            decision_ref=ref,
            merge_event_ref=f"{prefix}-merge",
            validation_event_ref=f"{prefix}-validation",
            outcome=ok,
        ),
        event(
            f"{prefix}-feedback",
            "CHANGEGATE_USER_FEEDBACK_RECORDED",
            ref,
            decision_ref=ref,
            target_event_ref=f"{prefix}-root",
            target_event_type="CHANGEGATE_EVALUATION_COMPLETED",
            feedback={
                "actor_ref": "person",
                "verdict": "DISAGREE",
                "category_code": "TEST",
                "reason_code": None,
                "comment_digest": None,
            },
        ),
    ]


# --- Taxonomy, precedence, and oracle protections -----------------------------


def test_fixture_version_status_and_case_shape_are_exact():
    suite = fixture()
    assert suite["schema_version"] == "changegate-merge-eligibility-golden.v8"
    assert suite["status"] == "DRAFT_FOR_OWNER_REVIEW"
    cases = suite["cases"]
    assert len(cases) == 41
    assert len({item["case_id"] for item in cases}) == 41
    for item in cases:
        assert_case_shape(item)


def test_reason_taxonomy_is_closed_grammatical_and_classification_free():
    entries = fixture()["reason_codes"]
    assert len(entries) == 20
    codes = [entry["code"] for entry in entries]
    assert len(set(codes)) == 20
    ranks = [entry["precedence_rank"] for entry in entries]
    assert len(set(ranks)) == 20
    for entry in entries:
        assert set(entry) == REASON_ENTRY_FIELDS, entry["code"]
        assert MACHINE_CODE.fullmatch(entry["code"])
        assert isinstance(entry["precedence_rank"], int)
        assert not isinstance(entry["precedence_rank"], bool)
        assert entry["default_disposition"] in {"BLOCK", "REVIEW_REQUIRED"}
    taxonomy = fixture()["slice_1a_semantic_manifest"]["policy_semantics"][
        "reason_code_taxonomy"
    ]
    for entry in taxonomy:
        assert set(entry) == REASON_ENTRY_FIELDS - {"owner_decision_pending"}


def test_independent_precedence_table_protects_ranks():
    entries = {
        entry["code"]: entry["precedence_rank"]
        for entry in fixture()["reason_codes"]
    }
    assert entries == INDEPENDENT_PRECEDENCE_RANKS
    manifest_ranks = fixture()["slice_1a_semantic_manifest"]["policy_semantics"][
        "precedence_ranks"
    ]
    assert manifest_ranks == INDEPENDENT_PRECEDENCE_RANKS
    for item in fixture()["cases"]:
        expected = item["expected_complete_reason_codes"]
        primary = (
            min(expected, key=INDEPENDENT_PRECEDENCE_RANKS.__getitem__)
            if expected
            else None
        )
        assert item["expected_primary_reason"] == primary, item["case_id"]


def test_independent_disposition_table_and_coverage():
    entries = {
        entry["code"]: entry["default_disposition"]
        for entry in fixture()["reason_codes"]
    }
    assert entries == INDEPENDENT_DEFAULT_DISPOSITIONS
    manifest_dispositions = fixture()["slice_1a_semantic_manifest"][
        "policy_semantics"
    ]["default_dispositions"]
    assert manifest_dispositions == INDEPENDENT_DEFAULT_DISPOSITIONS
    dispositions = {item["expected_disposition"] for item in fixture()["cases"]}
    assert dispositions == {
        "ELIGIBLE_TO_MERGE_UNDER_POLICY",
        "REVIEW_REQUIRED",
        "BLOCK",
    }
    authorities = {
        item["expected_decision_authority"] for item in fixture()["cases"]
    }
    assert authorities == {"AUTHORITATIVE", "ADVISORY_ONLY"}


def test_every_reason_code_is_covered_by_a_golden_case():
    used = {
        code
        for item in fixture()["cases"]
        for code in item["expected_complete_reason_codes"]
    }
    declared = {entry["code"] for entry in fixture()["reason_codes"]}
    assert used == declared


def test_fact_state_mapping_is_total_and_matches_pinned_oracle():
    mapping = fixture()["fact_state_mapping"]
    assert mapping["enum_facts"] == ORACLE_ENUM_FACT_REASONS
    assert mapping["violation_tag_reasons"] == ORACLE_VIOLATION_TAG_REASONS
    for fact, code in ORACLE_SET_FACT_REASONS.items():
        assert mapping["set_facts"][fact] == code
    for fact, states in ORACLE_ENUM_FACT_REASONS.items():
        for item in fixture()["cases"]:
            assert item["policy_input_facts"][fact] in states, (
                item["case_id"],
                fact,
            )
    combinations = [
        (identity_value, independence_value)
        for identity_value in VERIFIER_IDENTITY_VALUES
        for independence_value in VERIFIER_INDEPENDENCE_VALUES
    ]
    assert len(combinations) == 12
    for identity_value, independence_value in combinations:
        result = oracle_verifier_reason(identity_value, independence_value)
        assert result is None or result in INDEPENDENT_PRECEDENCE_RANKS


def test_independent_oracle_reproduces_every_golden_expectation():
    for item in fixture()["cases"]:
        outcome = oracle_outcome(
            item["policy_input_facts"],
            item["policy_input_bindings"]["evaluation_mode"],
        )
        label = item["case_id"]
        assert outcome["complete_reason_codes"] == (
            item["expected_complete_reason_codes"]
        ), label
        assert outcome["disposition"] == item["expected_disposition"], label
        assert outcome["primary_reason_code"] == (
            item["expected_primary_reason"]
        ), label
        assert outcome["decision_authority"] == (
            item["expected_decision_authority"]
        ), label
    golden = {
        entry["case_id"]: entry
        for entry in fixture()["slice_1a_semantic_manifest"]["golden_semantics"]
    }
    for item in fixture()["cases"]:
        entry = golden[item["case_id"]]
        assert entry["disposition"] == item["expected_disposition"]
        assert entry["complete_reason_codes"] == (
            item["expected_complete_reason_codes"]
        )


def test_independent_oracle_detects_fact_mutations():
    facts = case("GC-S1-001")["policy_input_facts"]
    baseline = oracle_outcome(facts, "ENFORCE")
    assert baseline["disposition"] == "ELIGIBLE_TO_MERGE_UNDER_POLICY"
    mutations = {
        "repository_release_clean": ("DIRTY", "RELEASE_STATE_NOT_CLEAN"),
        "scope_status": ("VIOLATION", "SCOPE_VIOLATION"),
        "authority_status": ("INVALID", "AUTHORITY_INVALID"),
        "approval_status": ("MISSING", "APPROVAL_MISSING"),
        "task_context_current": ("STALE", "TASK_CONTEXT_STALE"),
    }
    for fact, (state, code) in mutations.items():
        mutated = {**facts, fact: state}
        outcome = oracle_outcome(mutated, "ENFORCE")
        assert outcome["disposition"] == "BLOCK", fact
        assert code in outcome["complete_reason_codes"], fact
    moved = {**facts, "satisfied_requirement_ids": ["req-compileall"]}
    moved["missing_requirement_ids"] = ["req-pytest-full"]
    outcome = oracle_outcome(moved, "ENFORCE")
    assert "REQUIRED_EVIDENCE_MISSING" in outcome["complete_reason_codes"]
    shadow = oracle_outcome(facts, "SHADOW")
    assert shadow["decision_authority"] == "ADVISORY_ONLY"


def test_evidence_accounting_partition_and_disjointness_hold_per_case():
    for item in fixture()["cases"]:
        facts = item["policy_input_facts"]
        label = item["case_id"]
        required = set(facts["required_requirement_ids"])
        satisfied = set(facts["satisfied_requirement_ids"])
        invalid = set(facts["invalid_requirement_ids"])
        missing = set(facts["missing_requirement_ids"])
        assert satisfied | invalid | missing == required, label
        assert not satisfied & invalid, label
        assert not satisfied & missing, label
        assert not invalid & missing, label
        universes = item["identifier_universes"]
        requirement_universe = set(universes["requirement_id_universe"])
        evidence_universe = set(universes["evidence_record_id_universe"])
        assert not requirement_universe & evidence_universe, label
        assert required <= requirement_universe, label
        for field in EVIDENCE_LIST_FIELDS:
            assert set(facts[field]) <= evidence_universe, label
    empty_blocked = case("GC-S1-002")
    assert empty_blocked["policy_input_facts"]["missing_requirement_ids"]
    assert empty_blocked["expected_primary_reason"] == "REQUIRED_EVIDENCE_MISSING"
    empty_eligible = case("GC-S1-020")
    assert empty_eligible["policy_input_facts"]["required_requirement_ids"] == []
    assert empty_eligible["expected_disposition"] == (
        "ELIGIBLE_TO_MERGE_UNDER_POLICY"
    )


def test_identifier_namespace_swap_is_rejected():
    record, _ = record_for()
    requirement_id = record["required_requirement_ids"][0]
    evidence_id = sorted(known_ids("evidence_record_id_universe"))[0]
    swapped = rederive(
        {**record, "rejected_evidence_ids": [requirement_id]}
    )
    assert "RECORD_TYPE_INVALID" in validate_record_structure(swapped)["errors"]
    swapped = rederive(
        {
            **record,
            "required_requirement_ids": sorted(
                [evidence_id, *record["required_requirement_ids"]]
            ),
        }
    )
    assert "RECORD_TYPE_INVALID" in validate_record_structure(swapped)["errors"]


# --- Digest grammar and privacy ------------------------------------------------


def test_canonical_digest_grammar_is_enforced_everywhere():
    record, _ = record_for()
    produced = canonical_digest({"probe": True})
    assert DIGEST.fullmatch(produced)
    for field in ("candidate_digest", "input_digest", "policy_digest"):
        accepted = rederive({**record, field: produced})
        assert validate_record_structure(accepted)["errors"] == []
    bare = produced.split(":", 1)[1]
    malformed = (
        bare,
        f"SHA256:{bare}",
        f"sha256:{bare.upper()}",
        f"md5:{bare}",
        f"sha256:{bare[:10]}",
        f"sha256:{bare}\n",
        f" sha256:{bare}",
    )
    for value in malformed:
        rejected = rehash({**record, "candidate_digest": value})
        assert validate_record_structure(rejected)["errors"], value
    for value in malformed:
        instance = evaluation_event("evt", dref())
        instance["decision_ref"] = {**dref(), "decision_digest": value}
        assert list(validator().iter_errors(instance)), value


def test_no_artifact_contains_secret_material_or_raw_content_fields():
    credential_shapes = (
        "ghp_",
        "github_pat_",
        "xoxb-",
        "sk_live",
        "AKIA",
        "AIza",
        "BEGIN RSA PRIVATE KEY",
        "BEGIN OPENSSH PRIVATE KEY",
    )
    fixture_blob = FIXTURE.read_text()
    for shape in credential_shapes:
        assert shape not in fixture_blob, shape
    schema_properties = set(schema()["properties"])
    for forbidden in ("stdout", "stderr", "file_contents", "prompt", "command_output"):
        assert forbidden not in schema_properties
    check = validator()
    base = evaluation_event("evt", dref())
    for value in ("../secret", "a b", "https://x", "ghp_" + "a" * 30, "x\n"):
        bad = copy.deepcopy(base)
        bad["subject_ref"]["value"] = value
        assert list(check.iter_errors(bad)), value


# --- Deterministic identity and schema-digest derivation -----------------------


def test_policy_record_schema_digest_derives_from_the_typed_contract():
    contract = identity()
    declared = contract["policy_record_schema_digest"]
    derived = canonical_digest(contract["typed_field_contract"])
    assert declared == derived
    assert contract["policy_record_schema_digest_derivation"] == (
        "canonical_digest(deterministic_identity.typed_field_contract)"
    )
    typed = contract["typed_field_contract"]
    assert set(typed) == set(PAYLOAD_FIELDS)
    assert contract["canonicalization_contract_digest"] == canonical_digest(
        contract["canonicalization_contract"]
    )


def test_schema_digest_mutations_track_contract_changes():
    typed = identity()["typed_field_contract"]
    baseline = canonical_digest(typed)
    renamed = {
        ("renamed_task_id" if key == "task_id" else key): value
        for key, value in typed.items()
    }
    assert canonical_digest(renamed) != baseline
    retyped = copy.deepcopy(typed)
    retyped["task_id"] = {"type": "integer"}
    assert canonical_digest(retyped) != baseline
    collections = copy.deepcopy(typed)
    collections["complete_reason_codes"]["type"] = "list"
    assert canonical_digest(collections) != baseline
    suite = fixture()
    suite["status"] = "ACCEPTED_BY_OWNER"
    suite["description"] = "metadata change"
    unchanged = suite["slice_1a_semantic_manifest"]["deterministic_identity"][
        "typed_field_contract"
    ]
    assert canonical_digest(unchanged) == baseline


def test_complete_replay_key_binding_mutations_change_input_identity():
    replay, contract = fixture()["slice_1a_semantic_manifest"]["replay"], identity()
    assert set(replay["complete_replay_key"]) == {
        "canonical MergeEligibilityPolicyInput",
        "policy_version",
        "evaluator_version",
        "evaluation_mode",
        "policy_record_schema_version",
        "policy_record_schema_digest",
        "canonicalization_version",
        "canonicalization_contract_digest",
    }
    record, source = record_for()
    assert validate_record_structure(record, source)["errors"] == []
    baseline = record["input_digest"]
    for field in (
        "policy_record_schema_version",
        "policy_record_schema_digest",
        "canonicalization_version",
        "canonicalization_contract_digest",
    ):
        mutated = copy.deepcopy(source)
        mutated[field] = f"changed-{field}"
        assert canonical_digest(mutated) != baseline, field
    for field in (
        "task_id",
        *SOURCE_BINDING_FIELDS,
        "policy_version",
        "evaluator_version",
        "evaluation_mode",
    ):
        mutated = copy.deepcopy(source)
        mutated[field] = "changed-value"
        assert canonical_digest(mutated) != baseline, field
    mutated = copy.deepcopy(source)
    mutated["facts"]["repository_release_clean"] = "DIRTY"
    assert canonical_digest(mutated) != baseline
    assert contract["field_order_status"] == "NON_SEMANTIC_DOCUMENTATION_ORDER"


# --- Total fail-closed record validation ---------------------------------------


@pytest.mark.parametrize(
    "label,value",
    [
        ("integer", 3),
        ("float", 1.5),
        ("string", "record"),
        ("none", None),
        ("boolean", True),
        ("list", [1, 2]),
        ("nested-list", [["a"]]),
    ],
)
def test_record_validator_is_total_and_fail_closed(label: str, value: object):
    result = validate_record_structure(value)
    assert result["errors"] == ["RECORD_NOT_AN_OBJECT"], label
    assert result["classifications"] == [], label
    record, source = record_for()
    collection_mutations = {
        "integer collection": 7,
        "object collection": {"a": 1},
        "null collection": None,
        "nested list": [["AUTHORITY_INVALID"]],
        "mixed-type list": ["AUTHORITY_INVALID", 5],
        "boolean collection": True,
    }
    for name, bad_value in collection_mutations.items():
        for field in ("complete_reason_codes", "required_requirement_ids"):
            bad = dict(record)
            bad[field] = bad_value
            result = validate_record_structure(bad)
            assert "RECORD_TYPE_INVALID" in result["errors"], (name, field)
            assert result["classifications"] == [], (name, field)
            result = validate_record_structure(bad, source)
            assert result["errors"], (name, field)
    scalar_mutations = {
        "boolean task": {"task_id": True},
        "integer task": {"task_id": 3},
        "boolean mode": {"evaluation_mode": True},
        "integer digest": {"candidate_digest": 42},
        "null disposition": {"disposition": None},
        "unknown reason": {"complete_reason_codes": ["UNKNOWN_REASON"]},
        "foreign namespace": {"required_requirement_ids": ["ev-pytest-1"]},
    }
    for name, change in scalar_mutations.items():
        result = validate_record_structure(rehash({**record, **change}))
        assert result["errors"], name
        assert result["classifications"] == [], name
    unknown = rehash({**record, "unexpected_field": "x"})
    assert "RECORD_FIELD_SET_DRIFT" in validate_record_structure(unknown)["errors"]
    runtime = rehash({**record, "trace_id": "trace-1"})
    result = validate_record_structure(runtime)
    assert "RECORD_RUNTIME_FIELD" in result["errors"]
    missing = {
        key: value for key, value in record.items() if key != "disposition"
    }
    assert validate_record_structure(rehash(missing))["errors"]
    assert validate_record_structure({}, {})["errors"]


def test_valid_records_classify_structurally_for_every_case():
    for item in fixture()["cases"]:
        record, source = record_for(item["case_id"])
        alone = validate_record_structure(record)
        assert alone["errors"] == [], item["case_id"]
        assert alone["classifications"] == list(SLICE_1A_CLASSIFICATIONS)
        bound = validate_record_structure(record, source)
        assert bound["errors"] == [], item["case_id"]
        assert bound["classifications"] == list(SLICE_1A_CLASSIFICATIONS)


def test_key_order_is_not_identity():
    record, source = record_for()
    reordered = {key: record[key] for key in reversed(record)}
    result = validate_record_structure(reordered, source)
    assert result["errors"] == []
    assert (
        canonical_digest(
            {
                key: value
                for key, value in reordered.items()
                if key != "policy_record_digest"
            }
        )
        == record["policy_record_digest"]
    )


def test_collection_normalization_and_partitions_fail_closed():
    record, _ = record_for("GC-S1-021")
    unsorted = rederive(
        {
            **record,
            "complete_reason_codes": list(
                reversed(record["complete_reason_codes"])
            ),
        }
    )
    assert "RECORD_NOT_NORMALIZED" in validate_record_structure(unsorted)["errors"]
    duplicated = rederive(
        {
            **record,
            "rejected_evidence_ids": ["ev-pytest-1", "ev-pytest-1"],
        }
    )
    assert "RECORD_NOT_NORMALIZED" in (
        validate_record_structure(duplicated)["errors"]
    )
    broken_reasons = rederive({**record, "blocking_reason_codes": []})
    assert "RECORD_NOT_NORMALIZED" in (
        validate_record_structure(broken_reasons)["errors"]
    )
    overlap, _ = record_for("GC-S1-033")
    both = rederive(
        {
            **overlap,
            "review_reason_codes": overlap["complete_reason_codes"],
        }
    )
    assert "RECORD_NOT_NORMALIZED" in validate_record_structure(both)["errors"]
    bad_partition = rederive(
        {**record, "missing_requirement_ids": [], "invalid_requirement_ids": []}
    )
    if record["missing_requirement_ids"] or record["invalid_requirement_ids"]:
        assert "RECORD_NOT_NORMALIZED" in (
            validate_record_structure(bad_partition)["errors"]
        )
    record_one, _ = record_for("GC-S1-003")
    overlap_partition = rederive(
        {
            **record_one,
            "invalid_requirement_ids": record_one["missing_requirement_ids"],
        }
    )
    assert "RECORD_NOT_NORMALIZED" in (
        validate_record_structure(overlap_partition)["errors"]
    )


def test_decision_identity_recomputation_rejects_semantic_mutations():
    record, _ = record_for("GC-S1-010")
    mutations = {
        "disposition": {"disposition": "ELIGIBLE_TO_MERGE_UNDER_POLICY"},
        "authority": {"decision_authority": "ADVISORY_ONLY"},
        "primary reason": {"primary_reason_code": "SCOPE_VIOLATION"},
        "complete set emptied": {
            "complete_reason_codes": [],
            "blocking_reason_codes": [],
            "review_reason_codes": [],
            "primary_reason_code": None,
        },
        "task": {"task_id": "another-task"},
        "candidate": {"candidate_digest": canonical_digest({"candidate": "x"})},
        "source binding": {
            "repository_snapshot_digest": canonical_digest({"snapshot": "x"})
        },
        "evaluation mode": {"evaluation_mode": "SHADOW"},
        "input digest": {"input_digest": canonical_digest({"input": "x"})},
    }
    for label, change in mutations.items():
        forged = rehash({**record, **change})
        result = validate_record_structure(forged)
        assert "DECISION_DIGEST_NOT_DERIVED" in result["errors"], label
        assert result["classifications"] == [], label
    arbitrary = rehash(
        {**record, "decision_digest": canonical_digest({"forged": True})}
    )
    assert "DECISION_DIGEST_NOT_DERIVED" in (
        validate_record_structure(arbitrary)["errors"]
    )
    rederived = rederive({**record, "disposition": "REVIEW_REQUIRED"})
    assert rederived["decision_digest"] != record["decision_digest"]
    assert rederived["policy_record_digest"] != record["policy_record_digest"]


def test_policy_record_identity_recomputation_rejects_outer_mutations():
    record, _ = record_for()
    stale = {**record, "policy_version": "policy.v999"}
    result = validate_record_structure(stale)
    assert "RECORD_DIGEST_MISMATCH" in result["errors"]
    assert result["classifications"] == []
    truncated = {**record, "policy_record_digest": canonical_digest({"x": 1})}
    assert "RECORD_DIGEST_MISMATCH" in (
        validate_record_structure(truncated)["errors"]
    )


def test_record_input_binding_consistency_is_enforced():
    record, source = record_for()
    assert validate_record_structure(record, source)["errors"] == []
    for field in ("task_id", *SOURCE_BINDING_FIELDS):
        drifted = rederive(
            {
                **record,
                field: (
                    canonical_digest({"drift": field})
                    if field != "task_id"
                    else "another-task"
                ),
            }
        )
        result = validate_record_structure(drifted, source)
        assert "SOURCE_BINDING_MISMATCH" in result["errors"], field
        assert result["classifications"] == [], field
    for field in ("policy_version", "evaluator_version"):
        drifted = rederive({**record, field: "drifted.v9"})
        assert "SOURCE_BINDING_MISMATCH" in (
            validate_record_structure(drifted, source)["errors"]
        ), field
    mode_drift = rederive({**record, "evaluation_mode": "SHADOW"})
    assert "SOURCE_BINDING_MISMATCH" in (
        validate_record_structure(mode_drift, source)["errors"]
    )
    schema_claim = copy.deepcopy(source)
    schema_claim["policy_record_schema_version"] = (
        "changegate.policy-evaluation-record.v2"
    )
    bound = rederive({**record, "input_digest": canonical_digest(schema_claim)})
    result = validate_record_structure(bound, schema_claim)
    assert "SCHEMA_BINDING_MISMATCH" in result["errors"]
    stale_digest = copy.deepcopy(source)
    stale_digest["policy_record_schema_digest"] = canonical_digest({"stale": 1})
    bound = rederive({**record, "input_digest": canonical_digest(stale_digest)})
    assert "SCHEMA_BINDING_MISMATCH" in (
        validate_record_structure(bound, stale_digest)["errors"]
    )
    recanonicalized = copy.deepcopy(source)
    recanonicalized["canonicalization_version"] = "tomtit.canonical.v999"
    bound = rederive(
        {**record, "input_digest": canonical_digest(recanonicalized)}
    )
    assert "CANONICALIZATION_BINDING_MISMATCH" in (
        validate_record_structure(bound, recanonicalized)["errors"]
    )
    wrong_input = copy.deepcopy(source)
    wrong_input["facts"]["repository_release_clean"] = "DIRTY"
    assert "INPUT_DIGEST_MISMATCH" in (
        validate_record_structure(record, wrong_input)["errors"]
    )
    assert "INPUT_NOT_AN_OBJECT" in (
        validate_record_structure(record, "not-an-input")["errors"]
    )


def test_semantic_replay_is_never_claimed_in_slice_1a():
    record, source = record_for()
    forged = rederive(
        {
            **record,
            "disposition": "BLOCK",
            "primary_reason_code": "SCOPE_VIOLATION",
            "complete_reason_codes": ["SCOPE_VIOLATION"],
            "blocking_reason_codes": ["SCOPE_VIOLATION"],
            "review_reason_codes": [],
        }
    )
    result = validate_record_structure(forged, source)
    assert result["errors"] == []
    assert result["classifications"] == list(SLICE_1A_CLASSIFICATIONS)
    assert "SEMANTIC_REPLAY_NOT_PERFORMED" in result["classifications"]
    assert "SEMANTICALLY_REPLAY_VERIFIED" not in result["classifications"]
    genuine = validate_record_structure(record, source)
    assert genuine["classifications"] == result["classifications"]
    levels = identity()["validation_levels"]
    assert set(levels) == {
        "STRUCTURALLY_VALIDATED",
        "IDENTITY_RECOMPUTED",
        "SEMANTIC_REPLAY_NOT_PERFORMED",
        "SEMANTICALLY_REPLAY_VERIFIED",
    }
    assert levels["SEMANTICALLY_REPLAY_VERIFIED"].startswith(
        "SLICE_1B_PROTOCOL_ONLY"
    )
    assert "SEMANTICALLY_REPLAY_VERIFIED" not in SLICE_1A_CLASSIFICATIONS


# --- Event schema -------------------------------------------------------------


def test_event_schema_meta_validates_with_six_event_types():
    value = schema()
    Draft202012Validator.check_schema(value)
    assert value["properties"]["schema_version"]["const"] == (
        "changegate-evaluation-event.v1"
    )
    assert set(value["properties"]["event_type"]["enum"]) == EVENT_TYPES


def test_event_schema_digest_matches_manifest_binding():
    declared = fixture()["slice_1a_semantic_manifest"]["event_semantics"][
        "event_schema_digest"
    ]
    assert declared == canonical_digest(schema())


def test_removed_model_b_surfaces_cannot_be_reintroduced():
    value = schema()
    blob = json.dumps(value, sort_keys=True)
    for forbidden in (
        "CHANGEGATE_REVIEW_OVERRIDDEN",
        "CHANGEGATE_REVIEW_RECORDED",
        "replacement_decision_ref",
        '"override"',
        "override_class",
        "exception_ref",
        "expires_at",
        "authorization",
    ):
        assert forbidden not in blob
    check = validator()
    base = evaluation_event("evt", dref())
    for extra_field, extra_value in (
        ("replacement_decision_ref", dref("two")),
        ("exception_ref", "exception-1"),
        ("authorization", {"actor_ref": "person"}),
        ("expires_at", "2026-08-01T00:00:00Z"),
    ):
        attack = copy.deepcopy(base)
        attack[extra_field] = extra_value
        assert list(check.iter_errors(attack)), extra_field
    for removed_type in ("CHANGEGATE_REVIEW_OVERRIDDEN", "CHANGEGATE_REVIEW_RECORDED"):
        attack = copy.deepcopy(base)
        attack["event_type"] = removed_type
        assert list(check.iter_errors(attack)), removed_type
    module_source = Path(__file__).read_text()
    for helper in ("_make_replacement", "_validate_replacement", "_record_registry"):
        assert module_source.count(helper) <= 2


@pytest.mark.parametrize("event_type", sorted(EVENT_TYPES))
def test_each_event_type_requires_its_local_contract(event_type: str):
    ref = dref()
    extras = {
        "CHANGEGATE_EVALUATION_COMPLETED": {
            "decision_ref": ref,
            "context_digest": ref["input_digest"],
            "policy_version": "policy.v7",
            "evaluator_version": "1.0",
            "outcome": {"status": "SUCCESS", "detail_code": "OK"},
        },
        "CHANGEGATE_MERGE_ATTEMPTED": {
            "decision_ref": ref,
            "evaluation_event_ref": "root",
            "outcome": {"status": "SUCCESS", "detail_code": "OK"},
        },
        "CHANGEGATE_MERGE_COMPLETED": {
            "decision_ref": ref,
            "attempt_event_ref": "attempt",
            "outcome": {
                "status": "SUCCESS",
                "detail_code": "OK",
                "resulting_commit_sha": "b" * 40,
            },
        },
        "CHANGEGATE_POST_MERGE_VALIDATION": {
            "decision_ref": ref,
            "merge_event_ref": "merge",
            "outcome": {"status": "SUCCESS", "detail_code": "OK"},
        },
        "CHANGEGATE_ROLLBACK_RECORDED": {
            "decision_ref": ref,
            "merge_event_ref": "merge",
            "outcome": {"status": "SUCCESS", "detail_code": "OK"},
        },
        "CHANGEGATE_USER_FEEDBACK_RECORDED": {
            "decision_ref": ref,
            "target_event_ref": "root",
            "target_event_type": "CHANGEGATE_EVALUATION_COMPLETED",
            "feedback": {
                "actor_ref": "person",
                "verdict": "DISAGREE",
                "category_code": "TEST",
                "reason_code": None,
                "comment_digest": None,
            },
        },
    }
    assert (
        list(
            validator().iter_errors(event("evt", event_type, ref, **extras[event_type]))
        )
        == []
    )


@pytest.mark.parametrize("event_type", sorted(EVENT_TYPES))
def test_minimal_envelope_only_instance_is_rejected_for_every_event_type(
    event_type: str,
):
    minimal = event("evt", event_type, dref())
    assert list(validator().iter_errors(minimal)), event_type


# --- Explicit event identity equality matrix -----------------------------------


def test_event_identity_equality_matrix_is_enforced():
    matrix = fixture()["slice_1a_semantic_manifest"]["event_semantics"][
        "event_identity_equality_matrix"
    ]
    assert {
        (row["identity"], row["event_path"], row["reference_path"])
        for row in matrix
    } == {
        ("task", "task_ref", "decision_ref.task_ref"),
        (
            "candidate",
            "subject_ref.digest",
            "decision_ref.candidate_digest",
        ),
        ("input_digest", "context_digest", "decision_ref.input_digest"),
    }
    assert all(row["equality_required"] is True for row in matrix)
    ref = dref()
    valid = evaluation_event("root", ref)
    assert validate_graph([valid]) == []
    task_mismatch = copy.deepcopy(valid)
    task_mismatch["task_ref"] = "task-other"
    assert "TASK_IDENTITY_MISMATCH" in validate_graph([task_mismatch])
    candidate_mismatch = copy.deepcopy(valid)
    candidate_mismatch["subject_ref"]["digest"] = canonical_digest({"other": 1})
    assert "CANDIDATE_IDENTITY_MISMATCH" in validate_graph([candidate_mismatch])
    input_mismatch = copy.deepcopy(valid)
    input_mismatch["context_digest"] = canonical_digest({"other": 2})
    assert "INPUT_DIGEST_REFERENCE_MISMATCH" in validate_graph([input_mismatch])
    downstream = chain_for(ref, "chain")
    assert validate_graph(downstream) == []
    attempt_task_mismatch = copy.deepcopy(downstream)
    attempt_task_mismatch[1]["task_ref"] = "task-other"
    assert "TASK_IDENTITY_MISMATCH" in validate_graph(attempt_task_mismatch)
    attempt_candidate_mismatch = copy.deepcopy(downstream)
    attempt_candidate_mismatch[1]["subject_ref"]["digest"] = canonical_digest(
        {"other": 3}
    )
    assert "CANDIDATE_IDENTITY_MISMATCH" in validate_graph(
        attempt_candidate_mismatch
    )


def test_multiroot_multiparent_graph_positives_validate():
    one, two = dref("one"), dref("two")
    chain_one, chain_two = chain_for(one, "one"), chain_for(two, "two")
    interleaved = [item for pair in zip(chain_one, chain_two) for item in pair]
    assert validate_graph(interleaved) == []
    same_task = dref("one")
    same_task["evaluation_id"] = "evaluation-one-second"
    same_task["candidate_digest"] = canonical_digest({"candidate": "one-second"})
    second_root = evaluation_event("one-second-root", same_task)
    assert validate_graph([*chain_one, second_root]) == []
    rollback_without_validation = [
        *chain_for(one, "short")[:3],
        event(
            "short-rollback",
            "CHANGEGATE_ROLLBACK_RECORDED",
            one,
            decision_ref=one,
            merge_event_ref="short-merge",
            outcome={"status": "SUCCESS", "detail_code": "OK"},
        ),
    ]
    assert validate_graph(rollback_without_validation) == []


def test_causal_graph_negative_controls_are_rejected():
    one, two = dref("one"), dref("two")
    chain = chain_for(one, "one")
    duplicate_event = copy.deepcopy(chain)
    duplicate_event[1]["event_id"] = "one-root"
    result = validate_graph(duplicate_event)
    assert "EVENT_ID_DUPLICATE" in result
    duplicate_evaluation = [
        evaluation_event("root-a", one),
        evaluation_event(
            "root-b", {**two, "evaluation_id": one["evaluation_id"]}
        ),
    ]
    assert "EVALUATION_ID_DUPLICATE" in validate_graph(duplicate_evaluation)
    orphan = event(
        "orphan-attempt",
        "CHANGEGATE_MERGE_ATTEMPTED",
        one,
        decision_ref=one,
        evaluation_event_ref="missing-root",
        outcome={"status": "SUCCESS", "detail_code": "OK"},
    )
    assert "PREDECESSOR_MISSING" in validate_graph([orphan])
    wrong_type = copy.deepcopy(chain)
    wrong_type[2]["attempt_event_ref"] = "one-root"
    assert "PREDECESSOR_TYPE" in validate_graph(wrong_type)
    cross_root = [
        *chain_for(one, "one"),
        *chain_for(two, "two")[:4],
        event(
            "conflicted-rollback",
            "CHANGEGATE_ROLLBACK_RECORDED",
            one,
            decision_ref=one,
            merge_event_ref="one-merge",
            validation_event_ref="two-validation",
            outcome={"status": "SUCCESS", "detail_code": "OK"},
        ),
    ]
    assert "AMBIGUOUS_PREDECESSOR_LINEAGE" in validate_graph(cross_root)
    diverged = copy.deepcopy(chain)
    diverged[1]["decision_ref"] = two
    diverged[1]["task_ref"] = two["task_ref"]
    diverged[1]["subject_ref"]["digest"] = two["candidate_digest"]
    assert "LINEAGE_DIVERGES" in validate_graph(diverged)
    drifted = copy.deepcopy(chain)
    drifted[1]["decision_ref"] = {
        **one,
        "evaluation_id": "evaluation-drifted",
    }
    assert "EVALUATION_ID_DRIFT" in validate_graph(drifted)
    changed_candidate = copy.deepcopy(chain)
    changed_candidate[1]["decision_ref"] = {
        **one,
        "candidate_digest": canonical_digest({"candidate": "new"}),
    }
    changed_candidate[1]["subject_ref"]["digest"] = changed_candidate[1][
        "decision_ref"
    ]["candidate_digest"]
    assert "LINEAGE_DIVERGES" in validate_graph(changed_candidate)
    ok = {"status": "SUCCESS", "detail_code": "OK"}
    cycle = [
        event(
            "a",
            "CHANGEGATE_MERGE_ATTEMPTED",
            one,
            decision_ref=one,
            evaluation_event_ref="b",
            outcome=ok,
        ),
        event(
            "b",
            "CHANGEGATE_MERGE_ATTEMPTED",
            one,
            decision_ref=one,
            evaluation_event_ref="a",
            outcome=ok,
        ),
    ]
    assert "CAUSAL_CYCLE" in validate_graph(cycle)
    feedback_type_mismatch = copy.deepcopy(chain)
    feedback_type_mismatch[5]["target_event_type"] = "CHANGEGATE_MERGE_COMPLETED"
    assert "FEEDBACK_TARGET_TYPE_MISMATCH" in validate_graph(
        feedback_type_mismatch
    )
    malformed = validate_graph([{"event_id": 1, "event_type": "UNKNOWN"}])
    assert "EVENT_MALFORMED" in malformed


# --- Owner decisions, manifest, fingerprint, and governance --------------------


def test_owner_decision_statuses_and_records_are_pending_except_009():
    suite = fixture()
    statuses = suite["owner_decision_statuses"]
    assert statuses["OD-S1A-009"] == "ACCEPTED"
    assert all(
        statuses[f"OD-S1A-{number:03d}"] == "PENDING_OWNER_DECISION"
        for number in range(1, 9)
    )
    assert suite["od_s1a_009_decision_record"]["status"] == "ACCEPTED"
    record = suite["od_s1a_008_decision_record"]
    assert record["status"] == "PENDING_OWNER_DECISION"
    assert len(record["owner_must_decide"]) == 10
    assert len(record["pre_1c_1_declaration_fields"]) == 10
    assert record["blocks"]["slice_1c_1_a3"] == "BLOCKED_UNTIL_ACCEPTED"
    marked: dict[str, list[str]] = {}
    for item in suite["cases"]:
        for od in item["owner_decisions_pending"]:
            marked.setdefault(od, []).append(item["case_id"])
    for number in range(1, 9):
        assert marked[f"OD-S1A-{number:03d}"], number
    boundary = suite["slice_1a_semantic_manifest"]["authority_boundary"]
    assert boundary["od_s1a_009_status"] == "ACCEPTED"
    assert "PENDING_OWNER_DECISION" in boundary["od_s1a_005_dependency"]


def test_manifest_binds_required_controls_and_only_accepted_semantics():
    value = manifest()
    controls = {
        item["id"]: item
        for item in value["causal_semantics"]["semantic_controls"]
    }
    required = {
        "REC-EXACT-FIELD-SET",
        "REC-TYPED-VALUES",
        "REC-DIGEST-GRAMMAR",
        "REC-COLLECTION-NORMALIZATION",
        "REC-DECISION-SELF-DERIVATION",
        "REC-DIGEST-RECOMPUTE",
        "REC-NO-RUNTIME",
        "REC-KEY-ORDER-NEUTRAL",
        "REC-SCHEMA-DIGEST-DERIVATION",
        "REC-TOTAL-FAIL-CLOSED",
        "REC-BINDING-CONSISTENCY",
        "REPLAY-BOUNDARY",
        "AUTH-PURE-EVALUATOR-ONLY",
        "AUTH-NO-OVERRIDE-IN-1A",
        "AUTH-NO-ACTIVE-OVERRIDE-CLASSIFICATION",
        "AUTH-WRITER-NO-MUTATION",
        "EVENT-TASK-IDENTITY-EQUALITY",
        "EVENT-CANDIDATE-IDENTITY-EQUALITY",
        "EVENT-INPUT-DIGEST-REFERENCE-EQUALITY",
        "EVAL-ID-UNIQUE",
        "EVAL-ID-NO-DRIFT",
        "LINEAGE-SIX-FIELDS",
        "LINEAGE-IMMUTABLE",
        "MULTI-PARENT-LINEAGE",
        "MULTI-ROOT",
        "CAUSAL-CYCLE",
        "CANDIDATE-NEW-ROOT",
    }
    assert set(controls) == required
    for control in controls.values():
        assert control["predicate"]
        assert "failure_code" in control
    boundary = value["authority_boundary"]
    assert boundary["policy_semantic_producer"] == "PURE_EVALUATOR_ONLY"
    assert boundary["override_semantics_in_slice_1a"] == "ABSENT"
    assert boundary["exception_semantics_in_slice_1a"] == "ABSENT"
    assert "ABSENT" in boundary["active_override_exception_classification"]
    blob = json.dumps(value, sort_keys=True)
    assert "RPL-SAME-INPUT-OK" not in blob
    assert value["deterministic_identity"]["structural_validation_totality"]


def test_semantic_fingerprint_changes_for_required_mutations():
    baseline_manifest = manifest()
    baseline = canonical_digest(baseline_manifest)

    def mutated(apply) -> str:
        changed = copy.deepcopy(baseline_manifest)
        apply(changed)
        return canonical_digest(changed)

    mutations = {
        "override_class reintroduced": lambda m: m["policy_semantics"][
            "reason_code_taxonomy"
        ][0].__setitem__("override_class", "NOT_OVERRIDEABLE"),
        "renamed classification": lambda m: m["policy_semantics"][
            "reason_code_taxonomy"
        ][0].__setitem__("resolution_class", "EXCEPTION_NEEDED"),
        "OD-S1A-005 resolved": lambda m: m["authority_boundary"].__setitem__(
            "od_s1a_005_dependency", "ACCEPTED"
        ),
        "typed contract change": lambda m: m["deterministic_identity"][
            "typed_field_contract"
        ].pop("task_id"),
        "schema digest not derived": lambda m: m["deterministic_identity"].__setitem__(
            "policy_record_schema_digest", canonical_digest({"stale": 1})
        ),
        "canonicalization change": lambda m: m["deterministic_identity"].__setitem__(
            "canonicalization_version", "tomtit.canonical.v999"
        ),
        "validation weakened": lambda m: m["deterministic_identity"].pop(
            "structural_validation_totality"
        ),
        "crash allowed": lambda m: [
            control
            for control in m["causal_semantics"]["semantic_controls"]
            if control["id"] == "REC-TOTAL-FAIL-CLOSED"
        ][0].__setitem__("predicate", "validators may raise on malformed input"),
        "decision recomputation removed": lambda m: m["causal_semantics"][
            "semantic_controls"
        ].remove(
            next(
                control
                for control in m["causal_semantics"]["semantic_controls"]
                if control["id"] == "REC-DECISION-SELF-DERIVATION"
            )
        ),
        "record recomputation removed": lambda m: m["causal_semantics"][
            "semantic_controls"
        ].remove(
            next(
                control
                for control in m["causal_semantics"]["semantic_controls"]
                if control["id"] == "REC-DIGEST-RECOMPUTE"
            )
        ),
        "semantic replay claimed": lambda m: m["deterministic_identity"][
            "validation_levels"
        ].__setitem__(
            "SEMANTICALLY_REPLAY_VERIFIED", "returnable by Slice 1A helpers"
        ),
        "task equality removed": lambda m: m["causal_semantics"][
            "semantic_controls"
        ].remove(
            next(
                control
                for control in m["causal_semantics"]["semantic_controls"]
                if control["id"] == "EVENT-TASK-IDENTITY-EQUALITY"
            )
        ),
        "candidate equality removed": lambda m: m["causal_semantics"][
            "semantic_controls"
        ].remove(
            next(
                control
                for control in m["causal_semantics"]["semantic_controls"]
                if control["id"] == "EVENT-CANDIDATE-IDENTITY-EQUALITY"
            )
        ),
        "input reference equality removed": lambda m: m["event_semantics"][
            "event_identity_equality_matrix"
        ].pop(),
        "retained coverage removed": lambda m: m["contract_to_test_coverage"].pop(),
        "removed surface reintroduced": lambda m: [
            entry
            for entry in m["contract_to_test_coverage"]
            if entry["disposition"] == "DELETE_BY_MODEL_B"
        ][0].__setitem__("disposition", "RETAIN"),
        "cycle rejection removed": lambda m: m["causal_semantics"][
            "semantic_controls"
        ].remove(
            next(
                control
                for control in m["causal_semantics"]["semantic_controls"]
                if control["id"] == "CAUSAL-CYCLE"
            )
        ),
        "owner statuses changed": lambda m: m["authority_boundary"].__setitem__(
            "od_s1a_009_status", "WITHDRAWN"
        ),
    }
    assert len(mutations) == 18
    for label, apply in mutations.items():
        assert mutated(apply) != baseline, label


def test_metadata_only_changes_preserve_fingerprint():
    suite = fixture()
    baseline = canonical_digest(suite["slice_1a_semantic_manifest"])
    metadata = copy.deepcopy(suite)
    metadata["status"] = "ACCEPTED_BY_OWNER"
    metadata["description"] = "owner acceptance metadata patch"
    metadata["owner_decision_statuses"]["OD-S1A-004"] = "ACCEPTED"
    assert canonical_digest(metadata["slice_1a_semantic_manifest"]) == baseline


def test_exact_artifact_governance_is_declared():
    governance = fixture()["acceptance_governance"]
    contract = governance["exact_artifact_hash_contract"]
    assert contract["compared_files"] == [
        "data/schemas/changegate_evaluation_event_v1.schema.json",
        "tests/build_harness/test_changegate_slice_1_spec_artifacts.py",
    ]
    assert contract["future_hashes_hard_coded"] is False
    assert governance["semantic_fingerprint_source"] == "slice_1a_semantic_manifest"
    assert "contract_to_test_coverage" in (
        governance["semantic_fingerprint_components"]
    )
    assert governance["precedence_change_classification"] == (
        "SEMANTIC_PATCH_REQUIRES_REVERIFICATION"
    )


def test_no_active_override_or_exception_classification_remains():
    suite_blob = FIXTURE.read_text()
    assert "override_class" not in suite_blob
    for value in FORBIDDEN_CLASSIFICATION_VALUES:
        assert value not in suite_blob, value
    schema_blob = SCHEMA.read_text()
    for value in FORBIDDEN_CLASSIFICATION_VALUES:
        assert value not in schema_blob, value
    spec_text = SPEC.read_text()
    for value in FORBIDDEN_CLASSIFICATION_VALUES:
        assert value not in spec_text, value
    assert "override_class" not in spec_text
    for entry in fixture()["reason_codes"]:
        assert set(entry) == REASON_ENTRY_FIELDS
    for item in fixture()["cases"]:
        assert_case_shape(item)
    statuses = fixture()["owner_decision_statuses"]
    assert statuses["OD-S1A-005"] == "PENDING_OWNER_DECISION"


def test_contract_to_test_coverage_matrix_is_complete_and_bound():
    matrix = manifest()["contract_to_test_coverage"]
    required_keys = {
        "invariant_id",
        "normative_source",
        "disposition",
        "positive_oracle",
        "negative_oracle",
        "mutation_or_reintroduction_oracle",
        "test_references",
    }
    allowed_dispositions = {"RETAIN", "REWRITE", "DELETE_BY_MODEL_B"}
    module_names = set(globals())
    retained_ids, removed_ids = set(), set()
    for entry in matrix:
        assert set(entry) == required_keys, entry.get("invariant_id")
        assert entry["disposition"] in allowed_dispositions
        assert entry["test_references"], entry["invariant_id"]
        for reference in entry["test_references"]:
            assert reference in module_names, (entry["invariant_id"], reference)
            assert reference.startswith("test_")
        if entry["disposition"] == "DELETE_BY_MODEL_B":
            removed_ids.add(entry["invariant_id"])
            assert "reintroduc" in (
                entry["mutation_or_reintroduction_oracle"].lower()
            )
        else:
            retained_ids.add(entry["invariant_id"])
    assert retained_ids >= {
        "reason-taxonomy-completeness",
        "disposition-coverage",
        "independent-precedence-protection",
        "fact-state-totality",
        "evidence-accounting-partition",
        "requirement-evidence-namespace-separation",
        "canonical-digest-grammar",
        "privacy-raw-content-exclusion",
        "deterministic-identity-key",
        "schema-digest-derivation",
        "canonicalization-binding",
        "source-binding-consistency",
        "decision-identity-recomputation",
        "policy-record-identity-recomputation",
        "total-fail-closed-validation",
        "semantic-replay-boundary",
        "task-identity-equality",
        "candidate-identity-equality",
        "input-digest-reference-equality",
        "evaluation-id-uniqueness-and-no-drift",
        "immutable-root-identity",
        "multi-parent-equality",
        "cycle-rejection",
        "owner-decision-status-coverage",
        "exact-artifact-governance",
        "metadata-only-fingerprint-stability",
    }
    assert removed_ids == {
        "replacement-policy-record",
        "replacement-registry",
        "replacement-decision-reference",
        "review-override-event",
        "policy-lineage-switch",
        "active-exception-override-classification",
    }
    uncovered = [
        entry["invariant_id"]
        for entry in matrix
        if entry["disposition"] != "DELETE_BY_MODEL_B"
        and not entry["test_references"]
    ]
    assert uncovered == []


def test_spec_pins_replay_boundary_and_forbidden_terms():
    text = SPEC.read_text()
    for required in (
        "STRUCTURALLY_VALIDATED",
        "IDENTITY_RECOMPUTED",
        "SEMANTIC_REPLAY_NOT_PERFORMED",
        "SEMANTICALLY_REPLAY_VERIFIED",
        "sole semantic producer",
        "PENDING_OWNER_DECISION OD-S1A-005",
    ):
        assert required in text, required
    assert "Slice 1B" in text
    fixture_blob = FIXTURE.read_text()
    for forbidden in ("SAFE_TO_MERGE", "VERIFIED_AND_MERGE"):
        assert forbidden not in fixture_blob
        assert forbidden not in SCHEMA.read_text()
    machine = json.dumps(fixture()["cases"], sort_keys=True)
    assert "SAFE_TO_MERGE" not in machine


def test_legitimate_identifiers_remain_representable():
    for value in ("changegate-slice1a-demo", "TASK-2026.07.17_r7", "a1"):
        assert TASK.fullmatch(value), value
    generated = "run-0123456789abcdef"
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", generated)
    ref = dref()
    ref["task_ref"] = "changegate-slice1a-demo"
    instance = evaluation_event("evt", ref)
    assert list(validator().iter_errors(instance)) == []

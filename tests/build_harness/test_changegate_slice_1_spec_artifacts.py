"""Executable contract checks for ChangeGate Slice 1A R6 (artifact-only)."""
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
PAYLOAD_FIELDS = (
    "schema_version",
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


def input_payload(bindings: dict, facts: dict) -> dict:
    contract = identity()
    return {
        "kind": "changegate.merge-eligibility-policy-input.test-oracle.v1",
        "task_id": bindings["task_id"],
        **{field: bindings[field] for field in contract["source_binding_field_set"]},
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


def record_for(case_id: str = "GC-S1-001") -> tuple[dict, dict]:
    item = case(case_id)
    bindings, facts = item["policy_input_bindings"], item["policy_input_facts"]
    fixture()["fact_state_mapping"]
    reasons = item["expected_complete_reason_codes"]
    taxonomy = {
        entry["code"]: entry["default_disposition"]
        for entry in fixture()["reason_codes"]
    }
    payload = {
        "schema_version": "changegate.policy-evaluation-record.v1",
        "task_id": bindings["task_id"],
        **{field: bindings[field] for field in identity()["source_binding_field_set"]},
        "policy_version": bindings["policy_version"],
        "evaluator_version": bindings["evaluator_version"],
        "evaluation_mode": bindings["evaluation_mode"],
        "input_digest": canonical_digest(input_payload(bindings, facts)),
        "disposition": item["expected_disposition"],
        "decision_authority": item["expected_decision_authority"],
        "primary_reason_code": item["expected_primary_reason"],
        "complete_reason_codes": reasons,
        "blocking_reason_codes": [
            code for code in reasons if taxonomy[code] == "BLOCK"
        ],
        "review_reason_codes": [
            code for code in reasons if taxonomy[code] == "REVIEW_REQUIRED"
        ],
        **{
            field: sorted(facts[field])
            for field in (
                "required_requirement_ids",
                "satisfied_requirement_ids",
                "invalid_requirement_ids",
                "missing_requirement_ids",
                "rejected_evidence_ids",
                "invalid_provenance_evidence_ids",
                "unexpected_evidence_ids",
            )
        },
    }
    decision_fields = fixture()["slice_1a_semantic_manifest"]["replay"][
        "decision_identity_fields"
    ]
    payload["decision_digest"] = canonical_digest(
        {
            "kind": "changegate.merge-eligibility-decision.test-oracle.v1",
            **{field: payload[field] for field in decision_fields},
        }
    )
    return {
        **payload,
        "policy_record_digest": canonical_digest(payload),
    }, input_payload(bindings, facts)


def rehash(record: dict) -> dict:
    payload = {
        key: value for key, value in record.items() if key != "policy_record_digest"
    }
    return {**payload, "policy_record_digest": canonical_digest(payload)}


def known_ids(key: str) -> set[str]:
    return {
        value
        for item in fixture()["cases"]
        for value in item["identifier_universes"][key]
    }


def validate_record(record: dict, canonical_input: dict | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict) or set(record) != set(
        PAYLOAD_FIELDS + ("policy_record_digest",)
    ):
        return ["RECORD_SHAPE_DRIFT"]
    if RUNTIME_FIELDS & set(record):
        errors.append("RECORD_RUNTIME_FIELD")
    if record["schema_version"] != "changegate.policy-evaluation-record.v1":
        errors.append("RECORD_TYPE_INVALID")
    if not isinstance(record["task_id"], str) or not TASK.fullmatch(record["task_id"]):
        errors.append("RECORD_TYPE_INVALID")
    for field in ("policy_version", "evaluator_version"):
        if not isinstance(record[field], str) or not VERSION.fullmatch(record[field]):
            errors.append("RECORD_TYPE_INVALID")
    digest_fields = {
        "task_contract_digest",
        "candidate_digest",
        "repository_snapshot_digest",
        "verification_bundle_digest",
        "authority_binding_digest",
        "verifier_binding_digest",
        "policy_digest",
        "input_digest",
        "decision_digest",
        "policy_record_digest",
    }
    if any(
        not isinstance(record[field], str) or not DIGEST.fullmatch(record[field])
        for field in digest_fields
    ):
        errors.append("RECORD_TYPE_INVALID")
    approval = record["approval_digest_or_sentinel"]
    if not isinstance(approval, str) or (
        approval != "NO_APPROVAL_SUPPLIED" and not DIGEST.fullmatch(approval)
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
    list_fields = (
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
    for field in list_fields:
        value = record[field]
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            errors.append("RECORD_TYPE_INVALID")
        elif value != sorted(value) or len(value) != len(set(value)):
            errors.append("RECORD_NOT_NORMALIZED")
    if (
        record["primary_reason_code"] is not None
        and record["primary_reason_code"] not in taxonomy
    ):
        errors.append("RECORD_TYPE_INVALID")
    if any(code not in taxonomy for field in list_fields[:3] for code in record[field]):
        errors.append("RECORD_TYPE_INVALID")
    if any(
        value not in known_ids("requirement_id_universe")
        for field in list_fields[3:7]
        for value in record[field]
    ):
        errors.append("RECORD_TYPE_INVALID")
    if any(
        value not in known_ids("evidence_record_id_universe")
        for field in list_fields[7:]
        for value in record[field]
    ):
        errors.append("RECORD_TYPE_INVALID")
    if set(record["blocking_reason_codes"]) | set(record["review_reason_codes"]) != set(
        record["complete_reason_codes"]
    ) or set(record["blocking_reason_codes"]) & set(record["review_reason_codes"]):
        errors.append("RECORD_NOT_NORMALIZED")
    partitions = [set(record[field]) for field in list_fields[4:7]]
    if set().union(*partitions) != set(record["required_requirement_ids"]) or any(
        left & right
        for position, left in enumerate(partitions)
        for right in partitions[position + 1 :]
    ):
        errors.append("RECORD_NOT_NORMALIZED")
    decision_fields = fixture()["slice_1a_semantic_manifest"]["replay"][
        "decision_identity_fields"
    ]
    expected = canonical_digest(
        {
            "kind": "changegate.merge-eligibility-decision.test-oracle.v1",
            **{field: record[field] for field in decision_fields},
        }
    )
    if record["decision_digest"] != expected:
        errors.append("DECISION_DIGEST_NOT_DERIVED")
    if record["policy_record_digest"] != canonical_digest(
        {key: value for key, value in record.items() if key != "policy_record_digest"}
    ):
        errors.append("RECORD_DIGEST_MISMATCH")
    if canonical_input is not None and record["input_digest"] != canonical_digest(
        canonical_input
    ):
        errors.append("REPLAY_NOT_VERIFIED")
    return errors


def dref(tag: str = "one") -> dict:
    def digest(field):
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
        "occurred_at": "2026-07-16T00:00:00Z",
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
        ("evaluation_event_ref", "CHANGEGATE_EVALUATION_COMPLETED"),
    ),
    "CHANGEGATE_MERGE_COMPLETED": (
        ("attempt_event_ref", "CHANGEGATE_MERGE_ATTEMPTED"),
    ),
    "CHANGEGATE_POST_MERGE_VALIDATION": (
        ("merge_event_ref", "CHANGEGATE_MERGE_COMPLETED"),
    ),
    "CHANGEGATE_ROLLBACK_RECORDED": (
        ("merge_event_ref", "CHANGEGATE_MERGE_COMPLETED"),
        ("validation_event_ref", "CHANGEGATE_POST_MERGE_VALIDATION"),
    ),
    "CHANGEGATE_USER_FEEDBACK_RECORDED": (("target_event_ref", None),),
}


def validate_graph(events: list[dict]) -> list[str]:
    errors, by_id, lineages, evaluations = [], {}, {}, {}
    for item in events:
        eid, etype, ref = item["event_id"], item["event_type"], item.get("decision_ref")
        if eid in by_id:
            errors.append("EVENT_ID_DUPLICATE")
        parents = []
        for field, required_type in PARENTS[etype]:
            parent = by_id.get(item.get(field))
            if parent is None:
                errors.append("PREDECESSOR_MISSING")
            elif required_type and parent["event_type"] != required_type:
                errors.append("PREDECESSOR_TYPE")
            else:
                parents.append(lineages.get(parent["event_id"]))
        if etype == "CHANGEGATE_EVALUATION_COMPLETED":
            lineage = {field: ref[field] for field in LINEAGE}
            if ref["evaluation_id"] in evaluations:
                errors.append("EVALUATION_ID_DUPLICATE")
            evaluations[ref["evaluation_id"]] = lineage
        elif not parents or any(parent is None for parent in parents):
            lineage = None
            errors.append("ORPHAN")
        elif any(parent != parents[0] for parent in parents[1:]):
            lineage = None
            errors.append("AMBIGUOUS_PREDECESSOR_LINEAGE")
        else:
            lineage = parents[0]
            for field in LINEAGE:
                if ref[field] != lineage[field]:
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
            item[field] for field, _ in PARENTS[item["event_type"]] if item.get(field)
        ]
        for item in events
    }
    visiting, visited = set(), set()

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


def test_fixture_and_owner_boundary_are_model_b():
    suite, text = fixture(), SPEC.read_text()
    assert suite["schema_version"] == "changegate-merge-eligibility-golden.v7"
    statuses = suite["owner_decision_statuses"]
    assert statuses["OD-S1A-009"] == "ACCEPTED"
    assert all(
        statuses[f"OD-S1A-{number:03d}"] == "PENDING_OWNER_DECISION"
        for number in range(1, 9)
    )
    assert (
        suite["od_s1a_008_decision_record"]["blocks"]["slice_1c_1_a3"]
        == "BLOCKED_UNTIL_ACCEPTED"
    )
    assert (
        "sole semantic producer" in text and "PENDING_OWNER_DECISION OD-S1A-005" in text
    )


def test_complete_determinism_key_and_schema_bindings_are_explicit():
    replay, contract = fixture()["slice_1a_semantic_manifest"]["replay"], identity()
    assert set(replay["complete_replay_key"]) >= {
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
    assert not validate_record(record, source)
    baseline = record["input_digest"]
    for field in (
        "policy_record_schema_version",
        "policy_record_schema_digest",
        "canonicalization_version",
        "canonicalization_contract_digest",
    ):
        changed = copy.deepcopy(contract)
        changed[field] = f"changed-{field}"
        mutated = copy.deepcopy(source)
        mutated[field] = changed[field]
        assert canonical_digest(mutated) != baseline


def test_portable_record_validation_and_replay_levels():
    record, source = record_for()
    assert validate_record(record) == [] and validate_record(record, source) == []
    reordered = {key: record[key] for key in reversed(record)}
    assert validate_record(reordered) == []
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
    wrong_input = copy.deepcopy(source)
    wrong_input["facts"]["repository_release_clean"] = "DIRTY"
    assert "REPLAY_NOT_VERIFIED" in validate_record(record, wrong_input)
    mutations = {
        "wrong type": {"task_id": 3},
        "bad digest": {"candidate_digest": "sha256:no"},
        "unknown reason": {"complete_reason_codes": ["UNKNOWN_REASON"]},
        "unsorted": {"complete_reason_codes": ["SCOPE_VIOLATION", "AUTHORITY_INVALID"]},
        "duplicate": {"complete_reason_codes": ["SCOPE_VIOLATION", "SCOPE_VIOLATION"]},
        "forged decision": {"decision_digest": canonical_digest({"forged": True})},
    }
    for label, change in mutations.items():
        bad = rehash({**record, **change})
        assert validate_record(bad), label


def test_schema_is_path_b_without_review_or_authority_fields():
    value = schema()
    blob = json.dumps(value, sort_keys=True)
    Draft202012Validator.check_schema(value)
    assert set(value["properties"]["event_type"]["enum"]) == EVENT_TYPES
    for forbidden in (
        "CHANGEGATE_REVIEW_OVERRIDDEN",
        "CHANGEGATE_REVIEW_RECORDED",
        "replacement_decision_ref",
        '"override"',
        "exception_ref",
        "expires_at",
        "authorization",
    ):
        assert forbidden not in blob


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


def test_immutable_multiroot_graph_and_negative_controls():
    one, two = dref("one"), dref("two")
    root_one = event(
        "root-one",
        "CHANGEGATE_EVALUATION_COMPLETED",
        one,
        decision_ref=one,
        context_digest=one["input_digest"],
        policy_version="policy.v7",
        evaluator_version="1.0",
        outcome={"status": "SUCCESS", "detail_code": "OK"},
    )
    root_two = event(
        "root-two",
        "CHANGEGATE_EVALUATION_COMPLETED",
        two,
        decision_ref=two,
        context_digest=two["input_digest"],
        policy_version="policy.v7",
        evaluator_version="1.0",
        outcome={"status": "SUCCESS", "detail_code": "OK"},
    )
    attempt_one = event(
        "attempt-one",
        "CHANGEGATE_MERGE_ATTEMPTED",
        one,
        decision_ref=one,
        evaluation_event_ref="root-one",
        outcome={"status": "SUCCESS", "detail_code": "OK"},
    )
    attempt_two = event(
        "attempt-two",
        "CHANGEGATE_MERGE_ATTEMPTED",
        two,
        decision_ref=two,
        evaluation_event_ref="root-two",
        outcome={"status": "SUCCESS", "detail_code": "OK"},
    )
    assert validate_graph([root_one, root_two, attempt_two, attempt_one]) == []
    mismatch = copy.deepcopy(attempt_one)
    mismatch["decision_ref"] = two
    assert "LINEAGE_DIVERGES" in validate_graph([root_one, mismatch])
    duplicate = copy.deepcopy(root_two)
    duplicate["decision_ref"] = {**two, "evaluation_id": one["evaluation_id"]}
    assert "EVALUATION_ID_DUPLICATE" in validate_graph([root_one, duplicate])
    cycle_a = event(
        "a",
        "CHANGEGATE_MERGE_ATTEMPTED",
        one,
        decision_ref=one,
        evaluation_event_ref="b",
        outcome={"status": "SUCCESS", "detail_code": "OK"},
    )
    cycle_b = event(
        "b",
        "CHANGEGATE_MERGE_ATTEMPTED",
        one,
        decision_ref=one,
        evaluation_event_ref="a",
        outcome={"status": "SUCCESS", "detail_code": "OK"},
    )
    assert "CAUSAL_CYCLE" in validate_graph([cycle_a, cycle_b])


def test_manifest_fingerprint_and_required_model_b_controls():
    suite, manifest = fixture(), fixture()["slice_1a_semantic_manifest"]
    assert canonical_digest(manifest) == canonical_digest(
        fixture()["slice_1a_semantic_manifest"]
    )
    controls = {
        item["id"] for item in manifest["causal_semantics"]["semantic_controls"]
    }
    assert {
        "REC-TYPED-VALUES",
        "REC-COLLECTION-NORMALIZATION",
        "REC-DECISION-SELF-DERIVATION",
        "AUTH-PURE-EVALUATOR-ONLY",
        "AUTH-NO-OVERRIDE-IN-1A",
        "CAUSAL-CYCLE",
        "LINEAGE-IMMUTABLE",
    } <= controls
    for mutate in (
        lambda value: value["replay"]["complete_replay_key"].append("changed"),
        lambda value: value["causal_semantics"]["semantic_controls"].pop(),
        lambda value: value["deterministic_identity"]["typed_field_contract"].pop(
            "task_id"
        ),
    ):
        changed = copy.deepcopy(manifest)
        mutate(changed)
        assert canonical_digest(changed) != canonical_digest(manifest)
    metadata = copy.deepcopy(suite)
    metadata["status"] = "ACCEPTED_BY_OWNER"
    assert canonical_digest(metadata["slice_1a_semantic_manifest"]) == canonical_digest(
        manifest
    )

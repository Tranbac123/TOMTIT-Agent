"""Gate 1B-C conformance tests for canonical decision and record identity."""
from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path

import pytest

from agent_core.build_harness.canonical import canonical_digest
from agent_core.build_harness.merge_eligibility import (
    CANONICALIZATION_CONTRACT_DIGEST,
    CANONICALIZATION_VERSION,
    MERGE_ELIGIBILITY_POLICY_V1,
    POLICY_RECORD_SCHEMA_DIGEST,
    POLICY_RECORD_SCHEMA_VERSION,
    DecisionAuthority,
    MergeEligibilityPolicyInput,
    evaluate_decision_core,
)
from agent_core.build_harness.merge_eligibility_facade import (
    _PRODUCTION_POLICY,
    evaluate_merge_eligibility,
)
from agent_core.build_harness.merge_eligibility_record import (
    RecordConstructionError,
    build_policy_evaluation_record,
    finalize_decision,
    validate_policy_evaluation_record,
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = json.loads(
    (_ROOT / "data/evals/changegate_merge_eligibility_golden_cases.json").read_text()
)
_CASES = _FIXTURE["cases"]
_IDENTITY_FIELDS = _FIXTURE["slice_1a_semantic_manifest"]["replay"][
    "decision_identity_fields"
]


def _input(case: dict) -> MergeEligibilityPolicyInput:
    return MergeEligibilityPolicyInput.from_json_dict(
        {
            **case["policy_input_bindings"],
            "facts": case["policy_input_facts"],
            "policy_record_schema_version": POLICY_RECORD_SCHEMA_VERSION,
            "policy_record_schema_digest": POLICY_RECORD_SCHEMA_DIGEST,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "canonicalization_contract_digest": CANONICALIZATION_CONTRACT_DIGEST,
        }
    )


def _outputs(case: dict):
    policy_input = _input(case)
    core = evaluate_decision_core(policy_input, MERGE_ELIGIBILITY_POLICY_V1)
    decision = finalize_decision(policy_input, core)
    return policy_input, core, decision, build_policy_evaluation_record(policy_input, decision)


def _oracle(case: dict, policy_input: MergeEligibilityPolicyInput) -> tuple[str, str]:
    """Fixture/manifest-only oracle; it does not call record production helpers."""
    facts = case["policy_input_facts"]
    bindings = case["policy_input_bindings"]
    input_payload = {
        "kind": "changegate.merge-eligibility-policy-input.test-oracle.v1",
        "task_id": bindings["task_id"],
        **{key: bindings[key] for key in _IDENTITY_FIELDS[1:9]},
        "policy_version": bindings["policy_version"],
        "evaluator_version": bindings["evaluator_version"],
        "evaluation_mode": bindings["evaluation_mode"],
        "policy_record_schema_version": POLICY_RECORD_SCHEMA_VERSION,
        "policy_record_schema_digest": POLICY_RECORD_SCHEMA_DIGEST,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "canonicalization_contract_digest": CANONICALIZATION_CONTRACT_DIGEST,
        "facts": {key: facts[key] for key in sorted(facts)},
    }
    complete = case["expected_complete_reason_codes"]
    blocking = [
        code
        for code in complete
        if code not in {"SCOPE_UNCERTAIN", "VERIFIER_INDEPENDENCE_UNKNOWN"}
    ]
    review = [code for code in complete if code not in blocking]
    values = {
        "task_id": bindings["task_id"],
        **{key: bindings[key] for key in _IDENTITY_FIELDS[1:9]},
        "policy_version": bindings["policy_version"],
        "evaluator_version": bindings["evaluator_version"],
        "evaluation_mode": bindings["evaluation_mode"],
        "input_digest": canonical_digest(input_payload),
        "disposition": case["expected_disposition"],
        "decision_authority": case["expected_decision_authority"],
        "primary_reason_code": case["expected_primary_reason"],
        "complete_reason_codes": complete,
        "blocking_reason_codes": blocking,
        "review_reason_codes": review,
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
    assert values["input_digest"] == policy_input.input_digest()
    decision_digest = canonical_digest(
        {"kind": "changegate.merge-eligibility-decision.test-oracle.v1", **values}
    )
    record_payload = {
        "schema_version": "changegate.policy-evaluation-record.v1",
        **values,
        "decision_digest": decision_digest,
    }
    return decision_digest, canonical_digest(record_payload)


@pytest.mark.parametrize("case", _CASES, ids=lambda item: item["case_id"])
def test_all_golden_decision_and_record_digests_match_independent_oracle(case: dict) -> None:
    policy_input, _core, decision, record = _outputs(case)
    expected_decision, expected_record = _oracle(case, policy_input)
    assert decision.decision_digest == expected_decision
    assert record.policy_record_digest == expected_record
    assert validate_policy_evaluation_record(record)["errors"] == []
    assert validate_policy_evaluation_record(record, policy_input)["errors"] == []


@pytest.mark.parametrize("case", _CASES, ids=lambda item: item["case_id"])
def test_facade_is_exact_fixed_policy_composition(case: dict) -> None:
    policy_input, core, decision, record = _outputs(case)
    assert inspect.signature(evaluate_merge_eligibility).parameters.keys() == {"policy_input"}
    assert _PRODUCTION_POLICY is MERGE_ELIGIBILITY_POLICY_V1
    assert evaluate_merge_eligibility(policy_input) == (decision, record)
    if case["case_id"] == "GC-S1-018":
        facade_decision, _facade_record = evaluate_merge_eligibility(policy_input)
        assert facade_decision.disposition.value == "BLOCK"
        assert facade_decision.primary_reason_code == "POLICY_CONTEXT_STALE"
    assert core == evaluate_decision_core(policy_input, _PRODUCTION_POLICY)


def test_finalizer_copies_core_and_changes_only_corresponding_identity_digest() -> None:
    policy_input, core, decision, _record = _outputs(_CASES[0])
    changed_core = dataclasses.replace(
        core,
        decision_authority=(
            DecisionAuthority.ADVISORY_ONLY
            if core.decision_authority is DecisionAuthority.AUTHORITATIVE
            else DecisionAuthority.AUTHORITATIVE
        ),
    )
    changed = finalize_decision(policy_input, changed_core)
    for field in (
        "disposition", "primary_reason_code",
        "complete_reason_codes", "blocking_reason_codes", "review_reason_codes",
        "required_requirement_ids", "satisfied_requirement_ids",
        "invalid_requirement_ids", "missing_requirement_ids", "rejected_evidence_ids",
        "invalid_provenance_evidence_ids", "unexpected_evidence_ids",
    ):
        assert getattr(changed, field) == getattr(decision, field)
    assert changed.decision_authority is changed_core.decision_authority
    assert changed.decision_digest != decision.decision_digest


def test_builder_rejects_input_echo_and_digest_inconsistency() -> None:
    policy_input, _core, decision, _record = _outputs(_CASES[0])
    object.__setattr__(decision, "task_id", "different-task")
    with pytest.raises(RecordConstructionError):
        build_policy_evaluation_record(policy_input, decision)


@pytest.mark.parametrize("malformed", [None, 1, "record", [], {}, {1: "mixed"}])
def test_validator_is_total_for_malformed_candidates(malformed: object) -> None:
    result = validate_policy_evaluation_record(malformed)
    assert result["errors"]
    assert result["classifications"] == []


def test_validator_rejects_inner_and_outer_digest_tampering() -> None:
    policy_input, _core, _decision, record = _outputs(_CASES[0])
    object.__setattr__(record, "decision_digest", canonical_digest({"tamper": 1}))
    object.__setattr__(record, "policy_record_digest", canonical_digest(record.to_canonical_payload()))
    assert "DECISION_DIGEST_NOT_DERIVED" in validate_policy_evaluation_record(record)["errors"]
    assert validate_policy_evaluation_record(record, policy_input)["classifications"] == []


def test_identifier_universes_are_optional_and_enforced_when_supplied() -> None:
    case = _CASES[0]
    policy_input, _core, _decision, record = _outputs(case)
    universes = case["identifier_universes"]
    assert validate_policy_evaluation_record(record, policy_input, universes)["errors"] == []
    rejected_universe = {**universes, "requirement_id_universe": ()}
    assert "IDENTIFIER_UNIVERSE_MISMATCH" in validate_policy_evaluation_record(record, identifier_universes=rejected_universe)["errors"]

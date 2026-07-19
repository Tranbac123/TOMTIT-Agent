"""Gate 1B-D conformance tests for versioned semantic replay."""
from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from agent_core.build_harness.canonical import canonical_digest
from agent_core.build_harness.merge_eligibility import (
    CANONICALIZATION_CONTRACT_DIGEST,
    CANONICALIZATION_VERSION,
    MERGE_ELIGIBILITY_POLICY_V1,
    POLICY_RECORD_SCHEMA_DIGEST,
    POLICY_RECORD_SCHEMA_VERSION,
    DecisionAuthority,
    Disposition,
    MergeEligibilityPolicyInput,
    PolicyIdentity,
    evaluate_decision_core,
)
from agent_core.build_harness.merge_eligibility_record import (
    build_policy_evaluation_record,
    finalize_decision,
)
from agent_core.build_harness.merge_eligibility_replay import (
    EvaluatorRegistry,
    PolicyRegistry,
    RegistryConstructionError,
    ReplayClassification,
    verify_semantic_replay,
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = json.loads(
    (_ROOT / "data/evals/changegate_merge_eligibility_golden_cases.json").read_text()
)
_CASES = _FIXTURE["cases"]
_STALE_CASE = next(case for case in _CASES if case["case_id"] == "GC-S1-018")
_STALE_IDENTITY = PolicyIdentity(
    "changegate-merge-eligibility-policy.v2-draft",
    "sha256:9b2460a983b6b8222da7d2bd0fc344891a75468fe87f41064f817cdd94bcac48",
)
_EVALUATOR_VERSION = "changegate-merge-eligibility-evaluator.0-unimplemented"


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


def _policies():
    majority = MERGE_ELIGIBILITY_POLICY_V1
    stale = dataclasses.replace(majority, declared_identity=_STALE_IDENTITY)
    return majority, stale


def _registries():
    majority, stale = _policies()
    return (
        PolicyRegistry({majority.declared_identity: majority, stale.declared_identity: stale}),
        EvaluatorRegistry({_EVALUATOR_VERSION: evaluate_decision_core}),
    )


def _record(policy_input: MergeEligibilityPolicyInput, policy=MERGE_ELIGIBILITY_POLICY_V1):
    decision = finalize_decision(policy_input, evaluate_decision_core(policy_input, policy))
    return build_policy_evaluation_record(policy_input, decision)


def _raw_record(policy_input: MergeEligibilityPolicyInput) -> dict:
    record = _record(policy_input)
    return {
        **record.to_canonical_payload(),
        "policy_record_digest": record.policy_record_digest,
    }


def _rehash_record(raw: dict) -> None:
    raw["policy_record_digest"] = canonical_digest(
        {key: value for key, value in raw.items() if key != "policy_record_digest"}
    )


def _multi_reason_input() -> MergeEligibilityPolicyInput:
    return _input(
        next(
            case
            for case in _CASES
            if len(evaluate_decision_core(_input(case), MERGE_ELIGIBILITY_POLICY_V1).complete_reason_codes) >= 2
        )
    )


class _LookupCounterPolicyRegistry:
    def __init__(self) -> None:
        self.resolve_calls = 0
        self.version_checks = 0

    def resolve(self, _identity: PolicyIdentity):
        self.resolve_calls += 1
        raise AssertionError("structurally invalid records must not resolve policy")

    def has_version(self, _policy_version: str) -> bool:
        self.version_checks += 1
        raise AssertionError("structurally invalid records must not inspect policy versions")


class _LookupCounterEvaluatorRegistry:
    def __init__(self) -> None:
        self.resolve_calls = 0

    def resolve(self, _evaluator_version: str):
        self.resolve_calls += 1
        raise AssertionError("structurally invalid records must not resolve evaluators")


def test_dual_policy_instances_are_distinct_and_semantically_equal() -> None:
    majority, stale = _policies()
    assert majority is not stale
    assert majority.declared_identity != stale.declared_identity
    for field in dataclasses.fields(majority):
        if field.name != "declared_identity":
            assert getattr(majority, field.name) == getattr(stale, field.name)


@pytest.mark.parametrize("case", _CASES, ids=lambda item: item["case_id"])
def test_all_golden_records_replay_with_exact_registered_identities(case: dict) -> None:
    policy_input = _input(case)
    policy_registry, evaluator_registry = _registries()
    record = _record(policy_input)
    result = verify_semantic_replay(policy_input, record, policy_registry, evaluator_registry)
    assert result.classification is ReplayClassification.SEMANTICALLY_REPLAY_VERIFIED
    assert result.semantic_replay_performed
    assert result.decision_identity_matches and result.record_identity_matches
    assert result.mismatch_codes == ()


def test_stale_identity_resolves_its_own_policy_instance() -> None:
    policy_input = _input(_STALE_CASE)
    majority, stale = _policies()
    policy_registry = PolicyRegistry({majority.declared_identity: majority, stale.declared_identity: stale})
    result = verify_semantic_replay(
        policy_input,
        _record(policy_input, stale),
        policy_registry,
        EvaluatorRegistry({_EVALUATOR_VERSION: evaluate_decision_core}),
    )
    assert result.classification is ReplayClassification.SEMANTICALLY_REPLAY_VERIFIED
    assert policy_registry.resolve(_STALE_IDENTITY) is stale


def test_policy_digest_miss_fails_closed_before_evaluator_execution() -> None:
    policy_input = _input(_STALE_CASE)
    majority, stale = _policies()
    calls = 0

    def counted_evaluator(policy_input: MergeEligibilityPolicyInput, policy):
        nonlocal calls
        calls += 1
        return evaluate_decision_core(policy_input, policy)

    result = verify_semantic_replay(
        policy_input,
        _record(policy_input, stale),
        PolicyRegistry({majority.declared_identity: majority}),
        EvaluatorRegistry({_EVALUATOR_VERSION: counted_evaluator}),
    )
    assert result.classification is ReplayClassification.UNKNOWN_POLICY_IDENTITY
    assert "POLICY_DIGEST_MISMATCH" in result.diagnostics
    assert not result.semantic_replay_performed
    assert calls == 0


def test_unknown_evaluator_fails_closed_after_exact_policy_resolution() -> None:
    policy_input = _input(_CASES[0])
    policy_registry, _evaluator_registry = _registries()
    result = verify_semantic_replay(policy_input, _record(policy_input), policy_registry, EvaluatorRegistry({}))
    assert result.classification is ReplayClassification.UNKNOWN_EVALUATOR_IDENTITY
    assert result.policy_identity_resolved
    assert not result.evaluator_identity_resolved
    assert not result.semantic_replay_performed


def test_both_unknown_identities_use_policy_miss_precedence() -> None:
    policy_input = _input(_CASES[0])
    result = verify_semantic_replay(
        policy_input,
        _record(policy_input),
        PolicyRegistry({}),
        EvaluatorRegistry({}),
    )
    assert result.classification is ReplayClassification.UNKNOWN_POLICY_IDENTITY
    assert not result.policy_identity_resolved
    assert not result.evaluator_identity_resolved
    assert not result.semantic_replay_performed


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param(lambda: (lambda raw: (raw.pop("task_id"), raw)[1])(_raw_record(_input(_CASES[0]))), id="field-set-drift"),
        pytest.param(lambda: (lambda raw: (raw.__setitem__("policy_record_digest", "sha256:" + "z" * 64), raw)[1])(_raw_record(_input(_CASES[0]))), id="malformed-record-digest"),
        pytest.param(
            lambda: (lambda raw: (raw.__setitem__("decision_digest", "sha256:" + "0" * 64), _rehash_record(raw), raw)[2])(_raw_record(_input(_CASES[0]))),
            id="decision-digest-not-derived",
        ),
        pytest.param(
            lambda: (lambda raw: (raw.__setitem__("complete_reason_codes", list(reversed(raw["complete_reason_codes"]))), raw)[1])(_raw_record(_multi_reason_input())),
            id="malformed-collection-ordering",
        ),
        pytest.param(lambda: [], id="malformed-top-level"),
    ],
)
def test_structural_invalidity_short_circuits_all_registry_and_evaluator_work(malformed) -> None:
    policy_registry = _LookupCounterPolicyRegistry()
    evaluator_registry = _LookupCounterEvaluatorRegistry()
    result = verify_semantic_replay(_input(_CASES[0]), malformed(), policy_registry, evaluator_registry)  # type: ignore[arg-type]
    assert result.classification is ReplayClassification.RECORD_STRUCTURALLY_INVALID
    assert not result.record_structurally_valid
    assert not result.policy_identity_resolved
    assert not result.semantic_replay_performed
    assert policy_registry.resolve_calls == 0
    assert policy_registry.version_checks == 0
    assert evaluator_registry.resolve_calls == 0


def test_input_binding_mismatch_short_circuits_replay() -> None:
    original = _input(_CASES[0])
    changed = dataclasses.replace(original, candidate_digest="sha256:" + "0" * 64)
    policy_registry, _evaluator_registry = _registries()
    calls = 0

    def counted_evaluator(policy_input: MergeEligibilityPolicyInput, policy):
        nonlocal calls
        calls += 1
        return evaluate_decision_core(policy_input, policy)

    result = verify_semantic_replay(
        changed,
        _record(original),
        policy_registry,
        EvaluatorRegistry({_EVALUATOR_VERSION: counted_evaluator}),
    )
    assert result.classification is ReplayClassification.INPUT_BINDING_MISMATCH
    assert result.record_structurally_valid
    assert not result.semantic_replay_performed
    assert calls == 0


def test_evaluator_disposition_drift_is_an_isolated_semantic_mismatch() -> None:
    policy_input = _multi_reason_input()
    policy_registry, _evaluator_registry = _registries()

    def disposition_drift(policy_input: MergeEligibilityPolicyInput, policy):
        core = evaluate_decision_core(policy_input, policy)
        return dataclasses.replace(
            core,
            disposition=Disposition.ELIGIBLE_TO_MERGE_UNDER_POLICY,
            primary_reason_code=None,
            complete_reason_codes=(),
            blocking_reason_codes=(),
            review_reason_codes=(),
        )

    result = verify_semantic_replay(
        policy_input,
        _record(policy_input),
        policy_registry,
        EvaluatorRegistry({_EVALUATOR_VERSION: disposition_drift}),
    )
    assert result.classification is ReplayClassification.SEMANTIC_REPLAY_MISMATCH
    assert "DISPOSITION_MISMATCH" in result.mismatch_codes
    assert result.policy_identity_resolved and result.evaluator_identity_resolved
    assert result.semantic_replay_performed


def test_evaluator_reason_set_drift_is_an_isolated_semantic_mismatch() -> None:
    policy_input = _multi_reason_input()
    policy_registry, _evaluator_registry = _registries()

    def reason_set_drift(policy_input: MergeEligibilityPolicyInput, policy):
        core = evaluate_decision_core(policy_input, policy)
        removed = next(code for code in core.complete_reason_codes if code != core.primary_reason_code)
        return dataclasses.replace(
            core,
            complete_reason_codes=tuple(code for code in core.complete_reason_codes if code != removed),
            blocking_reason_codes=tuple(code for code in core.blocking_reason_codes if code != removed),
            review_reason_codes=tuple(code for code in core.review_reason_codes if code != removed),
        )

    result = verify_semantic_replay(
        policy_input,
        _record(policy_input),
        policy_registry,
        EvaluatorRegistry({_EVALUATOR_VERSION: reason_set_drift}),
    )
    assert result.classification is ReplayClassification.SEMANTIC_REPLAY_MISMATCH
    assert "REASON_SET_MISMATCH" in result.mismatch_codes
    assert result.policy_identity_resolved and result.evaluator_identity_resolved
    assert result.semantic_replay_performed


def test_evaluator_primary_reason_drift_is_an_isolated_semantic_mismatch() -> None:
    policy_input = _multi_reason_input()
    policy_registry, _evaluator_registry = _registries()

    def primary_reason_drift(policy_input: MergeEligibilityPolicyInput, policy):
        core = evaluate_decision_core(policy_input, policy)
        replacement = next(code for code in core.complete_reason_codes if code != core.primary_reason_code)
        return dataclasses.replace(core, primary_reason_code=replacement)

    result = verify_semantic_replay(
        policy_input,
        _record(policy_input),
        policy_registry,
        EvaluatorRegistry({_EVALUATOR_VERSION: primary_reason_drift}),
    )
    assert result.classification is ReplayClassification.SEMANTIC_REPLAY_MISMATCH
    assert "PRIMARY_REASON_MISMATCH" in result.mismatch_codes
    assert result.policy_identity_resolved and result.evaluator_identity_resolved
    assert result.semantic_replay_performed


def test_wrapped_evaluator_semantic_drift_is_a_mismatch() -> None:
    policy_input = _input(_CASES[0])
    policy_registry, _evaluator_registry = _registries()

    def authority_drift(policy_input: MergeEligibilityPolicyInput, policy):
        core = evaluate_decision_core(policy_input, policy)
        authority = (
            DecisionAuthority.ADVISORY_ONLY
            if core.decision_authority is DecisionAuthority.AUTHORITATIVE
            else DecisionAuthority.AUTHORITATIVE
        )
        return dataclasses.replace(core, decision_authority=authority)

    result = verify_semantic_replay(
        policy_input,
        _record(policy_input),
        policy_registry,
        EvaluatorRegistry({_EVALUATOR_VERSION: authority_drift}),
    )
    assert result.classification is ReplayClassification.SEMANTIC_REPLAY_MISMATCH
    assert {"DECISION_DIGEST_MISMATCH", "RECORD_DIGEST_MISMATCH"} <= set(result.mismatch_codes)


def test_semantically_different_but_structurally_valid_record_is_detected() -> None:
    policy_input = _input(next(case for case in _CASES if case["expected_complete_reason_codes"]))
    core = evaluate_decision_core(policy_input, MERGE_ELIGIBILITY_POLICY_V1)
    altered = dataclasses.replace(
        core,
        disposition=Disposition.ELIGIBLE_TO_MERGE_UNDER_POLICY,
        primary_reason_code=None,
        complete_reason_codes=(),
        blocking_reason_codes=(),
        review_reason_codes=(),
    )
    forged = build_policy_evaluation_record(policy_input, finalize_decision(policy_input, altered))
    policy_registry, evaluator_registry = _registries()
    result = verify_semantic_replay(policy_input, forged, policy_registry, evaluator_registry)
    assert result.classification is ReplayClassification.SEMANTIC_REPLAY_MISMATCH
    assert {"DISPOSITION_MISMATCH", "PRIMARY_REASON_MISMATCH", "REASON_SET_MISMATCH"} <= set(result.mismatch_codes)


def test_registry_construction_rejects_duplicate_and_identity_mismatch() -> None:
    majority, stale = _policies()
    with pytest.raises(RegistryConstructionError):
        PolicyRegistry(((majority.declared_identity, majority), (majority.declared_identity, majority)))
    with pytest.raises(RegistryConstructionError):
        PolicyRegistry({stale.declared_identity: majority})
    with pytest.raises(RegistryConstructionError):
        EvaluatorRegistry(((_EVALUATOR_VERSION, evaluate_decision_core), (_EVALUATOR_VERSION, evaluate_decision_core)))


def test_registry_is_order_independent_and_isolated_from_source_mutation() -> None:
    majority, stale = _policies()
    source = {majority.declared_identity: majority, stale.declared_identity: stale}
    left = PolicyRegistry(source)
    right = PolicyRegistry(dict(reversed(tuple(source.items()))))
    source.clear()
    assert tuple(left.entries) == tuple(right.entries)
    assert left.resolve(majority.declared_identity) is majority
    with pytest.raises(TypeError):
        left.entries[majority.declared_identity] = majority  # type: ignore[index]


def test_result_is_frozen_and_replay_is_deterministic() -> None:
    policy_input = _input(_CASES[0])
    policy_registry, evaluator_registry = _registries()
    record = _record(policy_input)
    first = verify_semantic_replay(policy_input, record, policy_registry, evaluator_registry)
    second = verify_semantic_replay(policy_input, record, policy_registry, evaluator_registry)
    assert first == second
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.classification = ReplayClassification.SEMANTIC_REPLAY_MISMATCH  # type: ignore[misc]
    assert all(item.startswith("NOT_VERIFIED_IN_SLICE_1B:") for item in first.diagnostics)


def test_replay_module_has_no_facade_import_or_dynamic_loading() -> None:
    source = (_ROOT / "agent_core/build_harness/merge_eligibility_replay.py").read_text()
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "agent_core.build_harness.merge_eligibility_facade" not in imported
    for forbidden in ("importlib", "eval(", "exec(", "open(", "subprocess"):
        assert forbidden not in source
    assert MappingProxyType.__name__ == "mappingproxy"

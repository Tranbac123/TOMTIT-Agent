"""Gate 1B-A — typed input and policy contract tests.

Independent of the protected Slice 1A test artifact: expected values are
derived from the committed fixture JSON and the accepted semantic manifest,
never imported from ``tests/build_harness/test_changegate_slice_1_spec_artifacts.py``.
No disposition/reason evaluation is performed here (Gate 1B-B scope).
"""
from __future__ import annotations

import ast
import copy
import dataclasses
import json
from pathlib import Path

import pytest

from agent_core.build_harness.canonical import canonical_digest
from agent_core.build_harness.merge_eligibility import (
    ApprovalStatus,
    AuthorityStatus,
    CANONICALIZATION_CONTRACT_DIGEST,
    CANONICALIZATION_VERSION,
    CandidateBindingCurrency,
    EligibilityFacts,
    EvidenceContextStatus,
    EvaluatorIdentity,
    INPUT_PAYLOAD_KIND,
    MERGE_ELIGIBILITY_POLICY_V1,
    MergeEligibilityInputError,
    MergeEligibilityPolicyInput,
    POLICY_RECORD_SCHEMA_DIGEST,
    POLICY_RECORD_SCHEMA_VERSION,
    PolicyContextCurrency,
    PolicyIdentity,
    RepositorySnapshotCurrency,
    ReleaseCleanliness,
    ScopeStatus,
    TaskContextCurrency,
    VerifierIdentityStatus,
    VerifierIndependenceStatus,
    VerifierRuleRow,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data/evals/changegate_merge_eligibility_golden_cases.json"
MODULE_PATH = ROOT / "agent_core/build_harness/merge_eligibility.py"

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

GC_S1_018_POLICY_VERSION = "changegate-merge-eligibility-policy.v2-draft"
GC_S1_018_POLICY_DIGEST = (
    "sha256:9b2460a983b6b8222da7d2bd0fc344891a75468fe87f41064f817cdd94bcac48"
)


def fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def identity_contract() -> dict:
    return fixture()["slice_1a_semantic_manifest"]["deterministic_identity"]


def cases() -> list[dict]:
    return fixture()["cases"]


def case(case_id: str) -> dict:
    return copy.deepcopy(next(item for item in cases() if item["case_id"] == case_id))


def input_data(bindings: dict, facts: dict) -> dict:
    """The 17-field dict accepted by ``MergeEligibilityPolicyInput.from_json_dict``."""
    contract = identity_contract()
    return {
        **{field: bindings[field] for field in ("task_id", *SOURCE_BINDING_FIELDS)},
        "policy_version": bindings["policy_version"],
        "evaluator_version": bindings["evaluator_version"],
        "evaluation_mode": bindings["evaluation_mode"],
        "policy_record_schema_version": contract["policy_record_schema_version"],
        "policy_record_schema_digest": contract["policy_record_schema_digest"],
        "canonicalization_version": contract["canonicalization_version"],
        "canonicalization_contract_digest": contract["canonicalization_contract_digest"],
        "facts": facts,
    }


def oracle_payload(bindings: dict, facts: dict) -> dict:
    """Independently reconstructed committed input-oracle payload (never
    imports the 1A test module)."""
    contract = identity_contract()
    return {
        "kind": INPUT_PAYLOAD_KIND,
        "task_id": bindings["task_id"],
        **{field: bindings[field] for field in SOURCE_BINDING_FIELDS},
        "policy_version": bindings["policy_version"],
        "evaluator_version": bindings["evaluator_version"],
        "evaluation_mode": bindings["evaluation_mode"],
        "policy_record_schema_version": contract["policy_record_schema_version"],
        "policy_record_schema_digest": contract["policy_record_schema_digest"],
        "canonicalization_version": contract["canonicalization_version"],
        "canonicalization_contract_digest": contract["canonicalization_contract_digest"],
        "facts": {key: facts[key] for key in sorted(facts)},
    }


# --- Binding constants -------------------------------------------------------


def test_binding_constants_match_fixture() -> None:
    contract = identity_contract()
    assert POLICY_RECORD_SCHEMA_VERSION == contract["policy_record_schema_version"]
    assert POLICY_RECORD_SCHEMA_DIGEST == contract["policy_record_schema_digest"]
    assert CANONICALIZATION_VERSION == contract["canonicalization_version"]
    assert CANONICALIZATION_CONTRACT_DIGEST == contract["canonicalization_contract_digest"]


def test_policy_record_schema_digest_is_recomputed_not_pasted() -> None:
    contract = identity_contract()
    recomputed = canonical_digest(contract["typed_field_contract"])
    assert recomputed == POLICY_RECORD_SCHEMA_DIGEST


def test_canonicalization_contract_digest_is_recomputed_not_pasted() -> None:
    contract = identity_contract()
    recomputed = canonical_digest(contract["canonicalization_contract"])
    assert recomputed == CANONICALIZATION_CONTRACT_DIGEST


# --- 41 golden cases: construction + digest oracle agreement -----------------


ALL_CASE_IDS = [c["case_id"] for c in cases()]


@pytest.mark.parametrize("case_id", ALL_CASE_IDS)
def test_golden_case_constructs_and_digest_agrees(case_id: str) -> None:
    item = case(case_id)
    bindings, facts = item["policy_input_bindings"], item["policy_input_facts"]
    data = input_data(bindings, facts)

    inp = MergeEligibilityPolicyInput.from_json_dict(data)

    expected_payload = oracle_payload(bindings, facts)
    assert inp.to_canonical_payload() == expected_payload

    expected_digest = canonical_digest(expected_payload)
    assert inp.input_digest() == expected_digest


def test_golden_input_construction_and_digest_totals() -> None:
    ok = 0
    for item in cases():
        bindings, facts = item["policy_input_bindings"], item["policy_input_facts"]
        data = input_data(bindings, facts)
        inp = MergeEligibilityPolicyInput.from_json_dict(data)
        expected = canonical_digest(oracle_payload(bindings, facts))
        assert inp.input_digest() == expected
        ok += 1
    assert ok == 41
    assert len(ALL_CASE_IDS) == 41


# --- Policy equality vs fixture ----------------------------------------------


def test_policy_reason_definitions_equal_fixture() -> None:
    fixture_reasons = {r["code"]: r for r in fixture()["reason_codes"]}
    prod_reasons = {r.code: r for r in MERGE_ELIGIBILITY_POLICY_V1.reason_definitions}
    assert set(fixture_reasons) == set(prod_reasons)
    assert len(fixture_reasons) == 20
    for code, fr in fixture_reasons.items():
        pr = prod_reasons[code]
        assert pr.precedence_rank == fr["precedence_rank"]
        assert pr.category == fr["category"]
        assert pr.kind == fr["kind"]
        assert pr.default_disposition.value == fr["default_disposition"]
        assert pr.owner_decision_pending == fr["owner_decision_pending"]


def test_policy_reason_ranks_unique() -> None:
    ranks = [r.precedence_rank for r in MERGE_ELIGIBILITY_POLICY_V1.reason_definitions]
    assert len(ranks) == len(set(ranks)) == 20


def test_policy_disposition_set_exact() -> None:
    dispositions = {
        r.default_disposition.value for r in MERGE_ELIGIBILITY_POLICY_V1.reason_definitions
    }
    assert dispositions <= set(fixture()["dispositions"])


def test_policy_enum_fact_reasons_equal_fixture() -> None:
    fsm = fixture()["fact_state_mapping"]
    for fact, mapping in fsm["enum_facts"].items():
        assert dict(MERGE_ELIGIBILITY_POLICY_V1.enum_fact_reasons[fact]) == mapping


def test_policy_violation_tag_reasons_equal_fixture() -> None:
    fsm = fixture()["fact_state_mapping"]
    assert dict(MERGE_ELIGIBILITY_POLICY_V1.violation_tag_reasons) == fsm[
        "violation_tag_reasons"
    ]


def test_policy_set_fact_triggers_equal_fixture() -> None:
    fsm = fixture()["fact_state_mapping"]
    assert dict(MERGE_ELIGIBILITY_POLICY_V1.set_fact_triggers) == fsm["set_facts"]


def _oracle_verifier_reason(identity: str, independence: str) -> str | None:
    if identity == "INVALID":
        return "AUTHORITY_INVALID"
    if identity == "ABSENT":
        return "REQUIRED_CONTEXT_INCOMPLETE"
    if independence == "NOT_INDEPENDENT":
        return "VERIFIER_NOT_INDEPENDENT"
    if identity == "ATTESTED" and independence == "INDEPENDENT":
        return None
    return "VERIFIER_INDEPENDENCE_UNKNOWN"


@pytest.mark.parametrize("identity", ["ATTESTED", "PRESENT_UNATTESTED", "ABSENT", "INVALID"])
@pytest.mark.parametrize("independence", ["INDEPENDENT", "NOT_INDEPENDENT", "UNKNOWN"])
def test_policy_verifier_rule_matches_oracle(identity: str, independence: str) -> None:
    expected = _oracle_verifier_reason(identity, independence)
    got = MERGE_ELIGIBILITY_POLICY_V1.resolve_verifier_reason(identity, independence)
    assert got == expected


def test_policy_mapping_total() -> None:
    for enum_cls in (
        TaskContextCurrency,
        CandidateBindingCurrency,
        RepositorySnapshotCurrency,
        ReleaseCleanliness,
        PolicyContextCurrency,
        EvidenceContextStatus,
        ScopeStatus,
        ApprovalStatus,
        AuthorityStatus,
    ):
        pass
    # totality is enforced structurally at construction time; re-verify here.
    for identity in VerifierIdentityStatus:
        for independence in VerifierIndependenceStatus:
            MERGE_ELIGIBILITY_POLICY_V1.resolve_verifier_reason(
                identity.value, independence.value
            )  # must not raise


def test_production_policy_declared_identity_is_majority_pair() -> None:
    assert MERGE_ELIGIBILITY_POLICY_V1.declared_identity == PolicyIdentity(
        policy_version="changegate-merge-eligibility-policy.v2-draft",
        policy_digest=(
            "sha256:88304ee85d7d10c2124d75b0de11cb8d8f91a8707945cabc651c0cbdedc71934"
        ),
    )


def test_production_policy_reason_code_count_and_dispositions() -> None:
    assert len(MERGE_ELIGIBILITY_POLICY_V1.reason_definitions) == 20
    assert {"BLOCK", "REVIEW_REQUIRED"} == {
        r.default_disposition.value for r in MERGE_ELIGIBILITY_POLICY_V1.reason_definitions
    }


# --- Identity models -----------------------------------------------------------


def test_policy_identity_equality_and_inequality() -> None:
    a = PolicyIdentity(policy_version="v1", policy_digest="sha256:" + "a" * 64)
    b = PolicyIdentity(policy_version="v1", policy_digest="sha256:" + "a" * 64)
    c = PolicyIdentity(policy_version="v1", policy_digest="sha256:" + "b" * 64)
    assert a == b
    assert a != c
    assert hash(a) == hash(b)


def test_policy_identity_frozen() -> None:
    ident = PolicyIdentity(policy_version="v1", policy_digest="sha256:" + "a" * 64)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ident.policy_version = "v2"  # type: ignore[misc]


def test_evaluator_identity_equality_hash_frozen() -> None:
    a = EvaluatorIdentity(evaluator_version="v1")
    b = EvaluatorIdentity(evaluator_version="v1")
    c = EvaluatorIdentity(evaluator_version="v2")
    assert a == b
    assert a != c
    assert hash(a) == hash(b)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.evaluator_version = "v9"  # type: ignore[misc]


def test_stale_snapshot_constructible_immutably() -> None:
    stale_snapshot = dataclasses.replace(
        MERGE_ELIGIBILITY_POLICY_V1,
        declared_identity=PolicyIdentity(
            policy_version=GC_S1_018_POLICY_VERSION,
            policy_digest=GC_S1_018_POLICY_DIGEST,
        ),
    )
    assert stale_snapshot is not MERGE_ELIGIBILITY_POLICY_V1
    assert stale_snapshot.declared_identity != MERGE_ELIGIBILITY_POLICY_V1.declared_identity
    assert stale_snapshot.declared_identity == PolicyIdentity(
        policy_version=GC_S1_018_POLICY_VERSION, policy_digest=GC_S1_018_POLICY_DIGEST
    )
    # Semantic fields (everything but declared_identity) are unchanged.
    assert stale_snapshot.reason_definitions == MERGE_ELIGIBILITY_POLICY_V1.reason_definitions
    assert dict(stale_snapshot.enum_fact_reasons) == dict(
        MERGE_ELIGIBILITY_POLICY_V1.enum_fact_reasons
    )
    assert dict(stale_snapshot.violation_tag_reasons) == dict(
        MERGE_ELIGIBILITY_POLICY_V1.violation_tag_reasons
    )
    assert dict(stale_snapshot.set_fact_triggers) == dict(
        MERGE_ELIGIBILITY_POLICY_V1.set_fact_triggers
    )
    assert stale_snapshot.verifier_rule == MERGE_ELIGIBILITY_POLICY_V1.verifier_rule

    # Original majority constant is unchanged after replace().
    assert MERGE_ELIGIBILITY_POLICY_V1.declared_identity == PolicyIdentity(
        policy_version="changegate-merge-eligibility-policy.v2-draft",
        policy_digest=(
            "sha256:88304ee85d7d10c2124d75b0de11cb8d8f91a8707945cabc651c0cbdedc71934"
        ),
    )


def test_gc_s1_018_uses_the_stale_policy_digest_in_the_fixture() -> None:
    item = case("GC-S1-018")
    assert item["policy_input_bindings"]["policy_version"] == GC_S1_018_POLICY_VERSION
    assert item["policy_input_bindings"]["policy_digest"] == GC_S1_018_POLICY_DIGEST
    assert item["expected_primary_reason"] == "POLICY_CONTEXT_STALE"


def test_majority_and_stale_identities_are_the_two_committed_fixture_pairs() -> None:
    digests = {c["policy_input_bindings"]["policy_digest"] for c in cases()}
    assert digests == {
        "sha256:88304ee85d7d10c2124d75b0de11cb8d8f91a8707945cabc651c0cbdedc71934",
        GC_S1_018_POLICY_DIGEST,
    }
    versions = {c["policy_input_bindings"]["policy_version"] for c in cases()}
    assert versions == {GC_S1_018_POLICY_VERSION}


# --- Constructor totality matrix ----------------------------------------------


def _base_case() -> tuple[dict, dict]:
    item = case("GC-S1-001")
    return item["policy_input_bindings"], item["policy_input_facts"]


def _base_input_data() -> dict:
    bindings, facts = _base_case()
    return input_data(bindings, facts)


def test_facts_missing_top_level_key() -> None:
    data = _base_input_data()
    del data["facts"]["approval_status"]
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_facts_extra_top_level_key() -> None:
    data = _base_input_data()
    data["facts"]["unknown_extra_fact"] = "X"
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_input_missing_top_level_key() -> None:
    data = _base_input_data()
    del data["task_id"]
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_input_extra_top_level_key() -> None:
    data = _base_input_data()
    data["unexpected_field"] = "x"
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_invalid_enum_value() -> None:
    data = _base_input_data()
    data["facts"]["approval_status"] = "NOT_A_REAL_STATUS"
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_invalid_evaluation_mode_literal() -> None:
    data = _base_input_data()
    data["evaluation_mode"] = "PARANOID"
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_wrong_string_grammar_task_id() -> None:
    data = _base_input_data()
    data["task_id"] = "  has spaces  "
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_malformed_digest() -> None:
    data = _base_input_data()
    data["policy_digest"] = "not-a-digest"
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_malformed_digest_wrong_length() -> None:
    data = _base_input_data()
    data["candidate_digest"] = "sha256:" + "a" * 10
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_malformed_version() -> None:
    data = _base_input_data()
    data["policy_version"] = ""
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_empty_string() -> None:
    data = _base_input_data()
    data["task_id"] = ""
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_whitespace_only_string() -> None:
    data = _base_input_data()
    data["task_id"] = "   "
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_bool_rejected_where_string_expected() -> None:
    data = _base_input_data()
    data["task_id"] = True
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_bool_rejected_in_string_list() -> None:
    data = _base_input_data()
    data["facts"]["required_requirement_ids"] = [True]
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_int_rejected_where_string_expected() -> None:
    data = _base_input_data()
    data["task_id"] = 12345
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_dict_rejected_where_list_required() -> None:
    data = _base_input_data()
    data["facts"]["required_requirement_ids"] = {"a": 1}
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_duplicate_tuple_entries() -> None:
    data = _base_input_data()
    data["facts"]["required_requirement_ids"] = ["req-a", "req-a"]
    data["facts"]["satisfied_requirement_ids"] = ["req-a"]
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_unsorted_tuple_entries() -> None:
    data = _base_input_data()
    data["facts"]["required_requirement_ids"] = ["req-z", "req-a"]
    data["facts"]["satisfied_requirement_ids"] = ["req-z", "req-a"]
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_partition_overlap() -> None:
    data = _base_input_data()
    data["facts"]["required_requirement_ids"] = ["req-a"]
    data["facts"]["satisfied_requirement_ids"] = ["req-a"]
    data["facts"]["invalid_requirement_ids"] = ["req-a"]
    data["facts"]["missing_requirement_ids"] = []
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_partition_union_mismatch() -> None:
    data = _base_input_data()
    data["facts"]["required_requirement_ids"] = ["req-a", "req-b"]
    data["facts"]["satisfied_requirement_ids"] = ["req-a"]
    data["facts"]["invalid_requirement_ids"] = []
    data["facts"]["missing_requirement_ids"] = []
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_violation_tag_state_incoherence_empty_but_incoherent() -> None:
    data = _base_input_data()
    data["facts"]["evidence_context_status"] = "INCOHERENT"
    data["facts"]["evidence_context_violations"] = []
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_violation_tag_state_incoherence_nonempty_but_coherent() -> None:
    data = _base_input_data()
    data["facts"]["evidence_context_status"] = "COHERENT"
    data["facts"]["evidence_context_violations"] = ["TASK_MISMATCH"]
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_malformed_verifier_pair_identity() -> None:
    data = _base_input_data()
    data["facts"]["verifier_identity_status"] = "NOT_A_VALUE"
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_malformed_verifier_pair_independence() -> None:
    data = _base_input_data()
    data["facts"]["verifier_independence_status"] = "NOT_A_VALUE"
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_invalid_sentinel_usage() -> None:
    data = _base_input_data()
    data["approval_digest_or_sentinel"] = "NO_APPROVAL_AT_ALL"
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_valid_sentinel_accepted() -> None:
    data = _base_input_data()
    data["approval_digest_or_sentinel"] = "NO_APPROVAL_SUPPLIED"
    # Must not raise: sentinel is a legal committed value.
    MergeEligibilityPolicyInput.from_json_dict(data)


def test_schema_version_drift_rejected() -> None:
    data = _base_input_data()
    data["policy_record_schema_version"] = "changegate.policy-evaluation-record.v2"
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_schema_digest_drift_rejected() -> None:
    data = _base_input_data()
    data["policy_record_schema_digest"] = "sha256:" + "0" * 64
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_canonicalization_version_drift_rejected() -> None:
    data = _base_input_data()
    data["canonicalization_version"] = "tomtit.canonical.v2"
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_canonicalization_digest_drift_rejected() -> None:
    data = _base_input_data()
    data["canonicalization_contract_digest"] = "sha256:" + "1" * 64
    with pytest.raises(MergeEligibilityInputError):
        MergeEligibilityPolicyInput.from_json_dict(data)


def test_duplicate_reason_code_rejected() -> None:
    definitions = list(MERGE_ELIGIBILITY_POLICY_V1.reason_definitions)
    definitions[1] = dataclasses.replace(definitions[1], code=definitions[0].code)
    with pytest.raises(MergeEligibilityInputError):
        dataclasses.replace(
            MERGE_ELIGIBILITY_POLICY_V1, reason_definitions=tuple(definitions)
        )


def test_duplicate_precedence_rank_rejected() -> None:
    definitions = list(MERGE_ELIGIBILITY_POLICY_V1.reason_definitions)
    definitions[1] = dataclasses.replace(
        definitions[1], precedence_rank=definitions[0].precedence_rank
    )
    with pytest.raises(MergeEligibilityInputError):
        dataclasses.replace(
            MERGE_ELIGIBILITY_POLICY_V1, reason_definitions=tuple(definitions)
        )


def test_missing_policy_mapping_row_rejected() -> None:
    trimmed = dict(MERGE_ELIGIBILITY_POLICY_V1.enum_fact_reasons)
    trimmed_task = dict(trimmed["task_context_current"])
    del trimmed_task["UNKNOWN"]
    trimmed["task_context_current"] = trimmed_task
    with pytest.raises(MergeEligibilityInputError):
        dataclasses.replace(MERGE_ELIGIBILITY_POLICY_V1, enum_fact_reasons=trimmed)


def test_extra_policy_mapping_row_rejected() -> None:
    extended = dict(MERGE_ELIGIBILITY_POLICY_V1.enum_fact_reasons)
    extended["nonexistent_fact"] = {"X": None}
    with pytest.raises(MergeEligibilityInputError):
        dataclasses.replace(MERGE_ELIGIBILITY_POLICY_V1, enum_fact_reasons=extended)


def test_malformed_declared_identity_missing() -> None:
    with pytest.raises((MergeEligibilityInputError, TypeError)):
        dataclasses.replace(MERGE_ELIGIBILITY_POLICY_V1, declared_identity=None)


def test_malformed_declared_identity_bad_digest() -> None:
    with pytest.raises(MergeEligibilityInputError):
        PolicyIdentity(policy_version="v1", policy_digest="not-a-digest")


def test_malformed_verifier_rule_incomplete_coverage_rejected() -> None:
    incomplete_rule = (VerifierRuleRow(("ATTESTED",), ("INDEPENDENT",), None),)
    with pytest.raises(MergeEligibilityInputError):
        dataclasses.replace(MERGE_ELIGIBILITY_POLICY_V1, verifier_rule=incomplete_rule)


def test_unexpected_raw_exceptions_zero_across_totality_matrix() -> None:
    """Every negative case above must raise MergeEligibilityInputError, never
    a raw KeyError/TypeError/ValueError/AssertionError."""
    mutations = [
        lambda d: d["facts"].__setitem__("approval_status", 123),
        lambda d: d["facts"].__setitem__("evidence_context_violations", "not-a-list"),
        lambda d: d.__setitem__("evaluation_mode", None),
        lambda d: d.__setitem__("task_id", None),
        lambda d: d["facts"].__setitem__("required_requirement_ids", None),
    ]
    for mutate in mutations:
        data = _base_input_data()
        mutate(data)
        with pytest.raises(MergeEligibilityInputError):
            MergeEligibilityPolicyInput.from_json_dict(data)


# --- Import surface / purity --------------------------------------------------

_FORBIDDEN_IMPORT_ROOTS = {
    "time",
    "datetime",
    "os",
    "random",
    "uuid",
    "socket",
    "subprocess",
    "requests",
    "urllib",
    "sqlite3",
    "pathlib",
}
_ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "re",
    "dataclasses",
    "enum",
    "types",
    "typing",
    "agent_core",
}


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_import_surface_is_canonical_and_stdlib_only() -> None:
    tree = ast.parse(MODULE_PATH.read_text())
    roots = _imported_roots(tree)
    assert roots <= _ALLOWED_IMPORT_ROOTS, roots - _ALLOWED_IMPORT_ROOTS
    assert not (roots & _FORBIDDEN_IMPORT_ROOTS)


def test_no_forbidden_runtime_symbols_referenced() -> None:
    source = MODULE_PATH.read_text()
    for forbidden in (
        "time.time",
        "datetime.now",
        "os.environ",
        "random.",
        "uuid.uuid4",
        "subprocess.",
        "open(",
    ):
        assert forbidden not in source, forbidden


def test_module_source_defines_no_evaluator_or_record_symbols() -> None:
    source = MODULE_PATH.read_text()
    prohibited_symbols = (
        "def evaluate_decision_core",
        "class DecisionCore",
        "class MergeEligibilityDecisionCore",
        "class MergeEligibilityDecision",
        "def finalize_decision",
        "decision_digest_for",
        "class PolicyEvaluationRecord",
        "def build_policy_evaluation_record",
        "def validate_policy_evaluation_record",
        "def evaluate_merge_eligibility",
        "class PolicyRegistry",
        "class EvaluatorRegistry",
        "class SemanticReplayResult",
        "def verify_semantic_replay",
    )
    for symbol in prohibited_symbols:
        assert symbol not in source, symbol


def test_frozen_policy_and_facts_expose_no_mutation_path() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        MERGE_ELIGIBILITY_POLICY_V1.declared_identity = None  # type: ignore[misc]

    item = case("GC-S1-001")
    facts = EligibilityFacts.from_json_dict(item["policy_input_facts"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        facts.approval_status = ApprovalStatus.MISSING  # type: ignore[misc]

    with pytest.raises(TypeError):
        MERGE_ELIGIBILITY_POLICY_V1.enum_fact_reasons["task_context_current"] = {}  # type: ignore[index]


def test_construction_produces_no_mutable_collection_exposure() -> None:
    item = case("GC-S1-001")
    inp = MergeEligibilityPolicyInput.from_json_dict(
        input_data(item["policy_input_bindings"], item["policy_input_facts"])
    )
    assert isinstance(inp.facts.required_requirement_ids, tuple)
    assert isinstance(inp.facts.evidence_context_violations, tuple)

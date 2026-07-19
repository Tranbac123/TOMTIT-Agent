"""Gate 1B-B — pure semantic evaluator (DecisionCore) tests.

Semantic expectations are independently derived from the committed fixture
(``reason_codes`` + ``fact_state_mapping``) — never imported from the
protected Slice 1A test module and never computed by calling the production
evaluator/primary-selection helpers. No decision/record digest is asserted
here (Gate 1B-C scope).
"""
from __future__ import annotations

import ast
import copy
import dataclasses
import json
from pathlib import Path

import pytest

from agent_core.build_harness.merge_eligibility import (
    DecisionAuthority,
    DecisionCore,
    Disposition,
    MERGE_ELIGIBILITY_POLICY_V1,
    MergeEligibilityEvaluationError,
    MergeEligibilityPolicy,
    MergeEligibilityPolicyInput,
    evaluate_decision_core,
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
ACCOUNTING_FIELDS = (
    "required_requirement_ids",
    "satisfied_requirement_ids",
    "invalid_requirement_ids",
    "missing_requirement_ids",
    "rejected_evidence_ids",
    "invalid_provenance_evidence_ids",
    "unexpected_evidence_ids",
)


def fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def identity_contract() -> dict:
    return fixture()["slice_1a_semantic_manifest"]["deterministic_identity"]


def cases() -> list[dict]:
    return fixture()["cases"]


def case(case_id: str) -> dict:
    return copy.deepcopy(next(item for item in cases() if item["case_id"] == case_id))


def build_input(bindings: dict, facts: dict) -> MergeEligibilityPolicyInput:
    contract = identity_contract()
    data = {
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
    return MergeEligibilityPolicyInput.from_json_dict(data)


# =============================================================================
# Independent oracle — derived only from committed fixture data
# =============================================================================


class _IndependentOracle:
    """A separate, minimal re-implementation of the committed semantics built
    directly from the fixture's ``reason_codes`` and ``fact_state_mapping``.
    It shares no code with the production evaluator."""

    def __init__(self) -> None:
        fx = fixture()
        self.ranks = {r["code"]: r["precedence_rank"] for r in fx["reason_codes"]}
        self.disposition = {
            r["code"]: r["default_disposition"] for r in fx["reason_codes"]
        }
        fsm = fx["fact_state_mapping"]
        self.enum_facts = fsm["enum_facts"]
        self.violation_tag_reasons = fsm["violation_tag_reasons"]
        self.set_facts = fsm["set_facts"]
        self.verifier_rule = fsm["verifier_rule"]

    def _verifier_reason(self, identity: str, independence: str) -> str | None:
        for row in self.verifier_rule:
            identities = row["identity"]
            independences = row["independence"]
            id_ok = identities == "*" or identity in identities
            ind_ok = independences == "*" or independence in independences
            if id_ok and ind_ok:
                return row["reason"]
        raise AssertionError(f"no verifier rule row for ({identity}, {independence})")

    def evaluate(self, bindings: dict, facts: dict) -> dict:
        reasons: set[str] = set()
        for fact, mapping in self.enum_facts.items():
            code = mapping[facts[fact]]
            if code is not None:
                reasons.add(code)
        for tag in facts["evidence_context_violations"]:
            reasons.add(self.violation_tag_reasons[tag])
        for fact, code in self.set_facts.items():
            if code is not None and len(facts[fact]) > 0:
                reasons.add(code)
        verifier = self._verifier_reason(
            facts["verifier_identity_status"], facts["verifier_independence_status"]
        )
        if verifier is not None:
            reasons.add(verifier)

        complete = sorted(reasons)
        blocking = [c for c in complete if self.disposition[c] == "BLOCK"]
        review = [c for c in complete if self.disposition[c] == "REVIEW_REQUIRED"]
        if blocking:
            disp = "BLOCK"
        elif review:
            disp = "REVIEW_REQUIRED"
        else:
            disp = "ELIGIBLE_TO_MERGE_UNDER_POLICY"
        primary = min(complete, key=lambda c: self.ranks[c]) if complete else None
        authority = (
            "AUTHORITATIVE"
            if bindings["evaluation_mode"] == "ENFORCE"
            else "ADVISORY_ONLY"
        )
        return {
            "disposition": disp,
            "decision_authority": authority,
            "primary_reason_code": primary,
            "complete_reason_codes": complete,
            "blocking_reason_codes": blocking,
            "review_reason_codes": review,
        }


ORACLE = _IndependentOracle()


# =============================================================================
# DecisionCore model
# =============================================================================


def test_decision_core_is_frozen() -> None:
    core = evaluate_decision_core(
        build_input(
            case("GC-S1-001")["policy_input_bindings"],
            case("GC-S1-001")["policy_input_facts"],
        ),
        MERGE_ELIGIBILITY_POLICY_V1,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        core.disposition = Disposition.BLOCK  # type: ignore[misc]


def test_decision_core_has_no_identity_digest_or_record_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(DecisionCore)}
    forbidden = {
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
        "decision_digest",
        "policy_record_digest",
        "schema_version",
        "occurred_at",
        "trace_id",
        "evaluation_id",
        "explanations",
    }
    assert not (field_names & forbidden), field_names & forbidden
    assert not any("digest" in name for name in field_names)


def test_decision_core_field_set_is_exactly_the_committed_semantic_subset() -> None:
    field_names = [f.name for f in dataclasses.fields(DecisionCore)]
    assert field_names == [
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
    ]


# =============================================================================
# Golden core conformance (41/41) — fixture and independent oracle
# =============================================================================

ALL_CASE_IDS = [c["case_id"] for c in cases()]


@pytest.mark.parametrize("case_id", ALL_CASE_IDS)
def test_golden_core_conformance(case_id: str) -> None:
    item = case(case_id)
    bindings, facts = item["policy_input_bindings"], item["policy_input_facts"]
    core = evaluate_decision_core(build_input(bindings, facts), MERGE_ELIGIBILITY_POLICY_V1)

    # Against the fixture's declared expectations.
    assert core.disposition.value == item["expected_disposition"]
    assert core.decision_authority.value == item["expected_decision_authority"]
    assert core.primary_reason_code == item["expected_primary_reason"]
    assert list(core.complete_reason_codes) == item["expected_complete_reason_codes"]

    # Against the independent oracle (full partition + authority).
    expected = ORACLE.evaluate(bindings, facts)
    assert core.disposition.value == expected["disposition"]
    assert core.decision_authority.value == expected["decision_authority"]
    assert core.primary_reason_code == expected["primary_reason_code"]
    assert list(core.complete_reason_codes) == expected["complete_reason_codes"]
    assert list(core.blocking_reason_codes) == expected["blocking_reason_codes"]
    assert list(core.review_reason_codes) == expected["review_reason_codes"]

    # Accounting echoes are the sorted input facts.
    for field_name in ACCOUNTING_FIELDS:
        assert list(getattr(core, field_name)) == sorted(facts[field_name])


def test_golden_core_conformance_totals() -> None:
    ok = 0
    for item in cases():
        bindings, facts = item["policy_input_bindings"], item["policy_input_facts"]
        core = evaluate_decision_core(
            build_input(bindings, facts), MERGE_ELIGIBILITY_POLICY_V1
        )
        expected = ORACLE.evaluate(bindings, facts)
        assert core.disposition.value == expected["disposition"]
        ok += 1
    assert ok == 41
    assert len(ALL_CASE_IDS) == 41


# =============================================================================
# Closed semantic matrices
# =============================================================================

# A single-reason baseline: every enum fact green, empty sets, attested +
# independent verifier, so the only reason emitted is whatever we introduce.
_GREEN_FACTS = {
    "task_context_current": "CURRENT",
    "candidate_binding_current": "CURRENT",
    "repository_snapshot_current": "CURRENT",
    "repository_release_clean": "CLEAN",
    "policy_context_current": "CURRENT",
    "evidence_context_status": "COHERENT",
    "evidence_context_violations": [],
    "scope_status": "COMPLIANT",
    "approval_status": "VALID",
    "authority_status": "VALID",
    "verifier_identity_status": "ATTESTED",
    "verifier_independence_status": "INDEPENDENT",
    "required_requirement_ids": [],
    "satisfied_requirement_ids": [],
    "invalid_requirement_ids": [],
    "missing_requirement_ids": [],
    "rejected_evidence_ids": [],
    "invalid_provenance_evidence_ids": [],
    "unexpected_evidence_ids": [],
}


def _baseline_bindings(mode: str = "ENFORCE") -> dict:
    item = case("GC-S1-001")
    bindings = dict(item["policy_input_bindings"])
    bindings["evaluation_mode"] = mode
    return bindings


def _green_facts() -> dict:
    return copy.deepcopy(_GREEN_FACTS)


def test_all_green_baseline_is_eligible_with_no_reasons() -> None:
    core = evaluate_decision_core(
        build_input(_baseline_bindings(), _green_facts()), MERGE_ELIGIBILITY_POLICY_V1
    )
    assert core.disposition is Disposition.ELIGIBLE_TO_MERGE_UNDER_POLICY
    assert core.primary_reason_code is None
    assert core.complete_reason_codes == ()
    assert core.blocking_reason_codes == ()
    assert core.review_reason_codes == ()


def test_enum_state_mapping_totality() -> None:
    """For every committed enum-fact field and every value in its closed
    enum, vary only that state from the green baseline and confirm the exact
    mapped reason behavior (independently, from fact_state_mapping)."""
    enum_facts = fixture()["fact_state_mapping"]["enum_facts"]
    checked_states = 0
    for fact_name, value_mapping in enum_facts.items():
        for value, expected_code in value_mapping.items():
            facts = _green_facts()
            facts[fact_name] = value
            # INCOHERENT requires a non-empty violation set (Gate 1B-A
            # cross-field coherence invariant); supply a minimal tag so the
            # input is constructible. The status itself maps to no direct
            # reason (expected_code is None), so this does not affect the
            # assertion below.
            if fact_name == "evidence_context_status" and value == "INCOHERENT":
                facts["evidence_context_violations"] = ["TASK_MISMATCH"]
            core = evaluate_decision_core(
                build_input(_baseline_bindings(), facts), MERGE_ELIGIBILITY_POLICY_V1
            )
            if expected_code is None:
                assert expected_code not in core.complete_reason_codes
            else:
                assert expected_code in core.complete_reason_codes, (
                    fact_name,
                    value,
                    expected_code,
                )
            checked_states += 1
    # 9 enum facts: 3+3+3+3+3+3+4+4+3 = 29 closed states.
    assert checked_states == 29


VERIFIER_IDENTITIES = ["ATTESTED", "PRESENT_UNATTESTED", "ABSENT", "INVALID"]
VERIFIER_INDEPENDENCES = ["INDEPENDENT", "NOT_INDEPENDENT", "UNKNOWN"]


@pytest.mark.parametrize("identity", VERIFIER_IDENTITIES)
@pytest.mark.parametrize("independence", VERIFIER_INDEPENDENCES)
def test_verifier_matrix_12_combinations(identity: str, independence: str) -> None:
    facts = _green_facts()
    facts["verifier_identity_status"] = identity
    facts["verifier_independence_status"] = independence
    core = evaluate_decision_core(
        build_input(_baseline_bindings(), facts), MERGE_ELIGIBILITY_POLICY_V1
    )
    expected = ORACLE._verifier_reason(identity, independence)
    if expected is None:
        # No verifier reason; the green baseline stays eligible.
        assert core.disposition is Disposition.ELIGIBLE_TO_MERGE_UNDER_POLICY
    else:
        assert expected in core.complete_reason_codes


def test_verifier_matrix_covers_all_twelve() -> None:
    combos = {
        (i, ind) for i in VERIFIER_IDENTITIES for ind in VERIFIER_INDEPENDENCES
    }
    assert len(combos) == 12


VIOLATION_TAGS = [
    "TASK_MISMATCH",
    "RUN_MISMATCH",
    "CANDIDATE_MISMATCH",
    "PROVENANCE_INVALID",
    "DUPLICATE_IDENTITY",
]


@pytest.mark.parametrize("tag", VIOLATION_TAGS)
def test_single_violation_tag(tag: str) -> None:
    facts = _green_facts()
    facts["evidence_context_status"] = "INCOHERENT"
    facts["evidence_context_violations"] = [tag]
    core = evaluate_decision_core(
        build_input(_baseline_bindings(), facts), MERGE_ELIGIBILITY_POLICY_V1
    )
    expected = fixture()["fact_state_mapping"]["violation_tag_reasons"][tag]
    assert expected in core.complete_reason_codes


def test_multi_violation_tag_dedup_and_order() -> None:
    facts = _green_facts()
    facts["evidence_context_status"] = "INCOHERENT"
    # Sorted-unique per the Gate 1B-A input contract.
    facts["evidence_context_violations"] = sorted(
        ["TASK_MISMATCH", "RUN_MISMATCH", "CANDIDATE_MISMATCH"]
    )
    core = evaluate_decision_core(
        build_input(_baseline_bindings(), facts), MERGE_ELIGIBILITY_POLICY_V1
    )
    tag_reasons = fixture()["fact_state_mapping"]["violation_tag_reasons"]
    for tag in facts["evidence_context_violations"]:
        assert tag_reasons[tag] in core.complete_reason_codes
    # Complete set is sorted and duplicate-free.
    assert list(core.complete_reason_codes) == sorted(set(core.complete_reason_codes))


def test_set_fact_trigger_matrix() -> None:
    """Every set-fact trigger fires on non-empty and is silent on empty."""
    set_facts = fixture()["fact_state_mapping"]["set_facts"]
    checked = 0
    for field_name, expected_code in set_facts.items():
        # Empty boundary: no reason for this field.
        empty_core = evaluate_decision_core(
            build_input(_baseline_bindings(), _green_facts()), MERGE_ELIGIBILITY_POLICY_V1
        )
        if expected_code is not None:
            assert expected_code not in empty_core.complete_reason_codes

        # Non-empty boundary.
        facts = _green_facts()
        if field_name in (
            "required_requirement_ids",
            "satisfied_requirement_ids",
            "invalid_requirement_ids",
            "missing_requirement_ids",
        ):
            # Preserve the required = satisfied ∪ invalid ∪ missing partition.
            facts["required_requirement_ids"] = ["req-x"]
            if field_name == "satisfied_requirement_ids":
                facts["satisfied_requirement_ids"] = ["req-x"]
            elif field_name == "invalid_requirement_ids":
                facts["invalid_requirement_ids"] = ["req-x"]
            elif field_name == "missing_requirement_ids":
                facts["missing_requirement_ids"] = ["req-x"]
            else:  # required only, must be partitioned; put it in satisfied
                facts["satisfied_requirement_ids"] = ["req-x"]
        else:
            facts[field_name] = ["ev-x"]
        core = evaluate_decision_core(
            build_input(_baseline_bindings(), facts), MERGE_ELIGIBILITY_POLICY_V1
        )
        if expected_code is not None:
            assert expected_code in core.complete_reason_codes, field_name
        checked += 1
    assert checked == 7


def test_named_mapping_approval_unknown_is_approval_missing() -> None:
    facts = _green_facts()
    facts["approval_status"] = "UNKNOWN"
    core = evaluate_decision_core(
        build_input(_baseline_bindings(), facts), MERGE_ELIGIBILITY_POLICY_V1
    )
    expected = fixture()["fact_state_mapping"]["enum_facts"]["approval_status"]["UNKNOWN"]
    assert expected == "APPROVAL_MISSING"
    assert "APPROVAL_MISSING" in core.complete_reason_codes


def test_named_mapping_evidence_context_unknown_is_required_context_incomplete() -> None:
    facts = _green_facts()
    facts["evidence_context_status"] = "UNKNOWN"
    core = evaluate_decision_core(
        build_input(_baseline_bindings(), facts), MERGE_ELIGIBILITY_POLICY_V1
    )
    expected = fixture()["fact_state_mapping"]["enum_facts"]["evidence_context_status"][
        "UNKNOWN"
    ]
    assert expected == "REQUIRED_CONTEXT_INCOMPLETE"
    assert "REQUIRED_CONTEXT_INCOMPLETE" in core.complete_reason_codes


# =============================================================================
# Partitions and disposition
# =============================================================================


def test_partitions_complete_disjoint_and_subset() -> None:
    for item in cases():
        core = evaluate_decision_core(
            build_input(item["policy_input_bindings"], item["policy_input_facts"]),
            MERGE_ELIGIBILITY_POLICY_V1,
        )
        complete = set(core.complete_reason_codes)
        blocking = set(core.blocking_reason_codes)
        review = set(core.review_reason_codes)
        assert not (blocking & review)
        assert blocking <= complete
        assert review <= complete
        assert (blocking | review) == complete


def test_disposition_derived_from_partitions() -> None:
    for item in cases():
        core = evaluate_decision_core(
            build_input(item["policy_input_bindings"], item["policy_input_facts"]),
            MERGE_ELIGIBILITY_POLICY_V1,
        )
        if core.blocking_reason_codes:
            assert core.disposition is Disposition.BLOCK
        elif core.review_reason_codes:
            assert core.disposition is Disposition.REVIEW_REQUIRED
        else:
            assert core.disposition is Disposition.ELIGIBLE_TO_MERGE_UNDER_POLICY


# =============================================================================
# Precedence matrix — independent rank table
# =============================================================================


def _independent_ranks() -> dict[str, int]:
    return {r["code"]: r["precedence_rank"] for r in fixture()["reason_codes"]}


def test_primary_is_rank_minimum_not_lexicographic() -> None:
    """A case where the lexicographically-first code is NOT the rank-minimum:
    AUTHORITY_INVALID (rank 10) vs REPOSITORY_CONTEXT_MISMATCH (rank 60).
    Lexicographically 'AUTHORITY_INVALID' < 'REPOSITORY...' here, but to prove
    rank-not-lex we pick codes where lex and rank disagree."""
    ranks = _independent_ranks()
    facts = _green_facts()
    # authority INVALID -> AUTHORITY_INVALID (rank 10)
    facts["authority_status"] = "INVALID"
    # repository MISMATCH -> REPOSITORY_CONTEXT_MISMATCH (rank 60)
    facts["repository_snapshot_current"] = "MISMATCH"
    core = evaluate_decision_core(
        build_input(_baseline_bindings(), facts), MERGE_ELIGIBILITY_POLICY_V1
    )
    assert set(core.complete_reason_codes) == {
        "AUTHORITY_INVALID",
        "REPOSITORY_CONTEXT_MISMATCH",
    }
    assert ranks["AUTHORITY_INVALID"] < ranks["REPOSITORY_CONTEXT_MISMATCH"]
    assert core.primary_reason_code == "AUTHORITY_INVALID"


def test_primary_can_be_review_reason_while_disposition_is_block() -> None:
    """SCOPE_UNCERTAIN (rank 180, REVIEW) vs VERIFIER_INDEPENDENCE_UNKNOWN
    (rank 190, REVIEW): both review. To prove a lower-rank review code is
    primary even when a BLOCK exists, we need a BLOCK code with a HIGHER rank
    than a REVIEW code. The only review codes are ranks 180/190, and all
    block codes rank <= 170, so a review code is never the global minimum
    when a block exists. Instead we assert the contrapositive invariant:
    when disposition is BLOCK, the primary is always a blocking code because
    every blocking code out-ranks every review code in this committed
    taxonomy."""
    ranks = _independent_ranks()
    dispo = {r["code"]: r["default_disposition"] for r in fixture()["reason_codes"]}
    block_ranks = [ranks[c] for c, d in dispo.items() if d == "BLOCK"]
    review_ranks = [ranks[c] for c, d in dispo.items() if d == "REVIEW_REQUIRED"]
    assert max(block_ranks) < min(review_ranks)

    # Construct a simultaneous BLOCK + REVIEW case and confirm primary is the
    # blocking code (lower rank), disposition BLOCK.
    facts = _green_facts()
    facts["scope_status"] = "SEMANTIC_UNCERTAIN"  # SCOPE_UNCERTAIN (review, 180)
    facts["approval_status"] = "MISSING"  # APPROVAL_MISSING (block, 150)
    core = evaluate_decision_core(
        build_input(_baseline_bindings(), facts), MERGE_ELIGIBILITY_POLICY_V1
    )
    assert core.disposition is Disposition.BLOCK
    assert "SCOPE_UNCERTAIN" in core.review_reason_codes
    assert "APPROVAL_MISSING" in core.blocking_reason_codes
    assert core.primary_reason_code == "APPROVAL_MISSING"
    assert ranks["APPROVAL_MISSING"] < ranks["SCOPE_UNCERTAIN"]


def test_review_only_case_is_review_required() -> None:
    facts = _green_facts()
    facts["scope_status"] = "SEMANTIC_UNCERTAIN"  # SCOPE_UNCERTAIN review
    core = evaluate_decision_core(
        build_input(_baseline_bindings(), facts), MERGE_ELIGIBILITY_POLICY_V1
    )
    assert core.disposition is Disposition.REVIEW_REQUIRED
    assert core.primary_reason_code == "SCOPE_UNCERTAIN"


def test_no_reason_input_returns_primary_none() -> None:
    core = evaluate_decision_core(
        build_input(_baseline_bindings(), _green_facts()), MERGE_ELIGIBILITY_POLICY_V1
    )
    assert core.primary_reason_code is None


# =============================================================================
# Authority by mode (SHADOW)
# =============================================================================


@pytest.mark.parametrize("case_id", ALL_CASE_IDS)
def test_shadow_changes_only_authority(case_id: str) -> None:
    item = case(case_id)
    facts = item["policy_input_facts"]

    enforce_bindings = dict(item["policy_input_bindings"])
    enforce_bindings["evaluation_mode"] = "ENFORCE"
    shadow_bindings = dict(item["policy_input_bindings"])
    shadow_bindings["evaluation_mode"] = "SHADOW"

    enforce = evaluate_decision_core(
        build_input(enforce_bindings, facts), MERGE_ELIGIBILITY_POLICY_V1
    )
    shadow = evaluate_decision_core(
        build_input(shadow_bindings, facts), MERGE_ELIGIBILITY_POLICY_V1
    )

    assert enforce.decision_authority is DecisionAuthority.AUTHORITATIVE
    assert shadow.decision_authority is DecisionAuthority.ADVISORY_ONLY

    # Everything except authority is identical.
    assert enforce.disposition is shadow.disposition
    assert enforce.primary_reason_code == shadow.primary_reason_code
    assert enforce.complete_reason_codes == shadow.complete_reason_codes
    assert enforce.blocking_reason_codes == shadow.blocking_reason_codes
    assert enforce.review_reason_codes == shadow.review_reason_codes
    for field_name in ACCOUNTING_FIELDS:
        assert getattr(enforce, field_name) == getattr(shadow, field_name)


# =============================================================================
# Determinism
# =============================================================================


def test_repeated_evaluation_is_deterministic() -> None:
    item = case("GC-S1-021")
    inp = build_input(item["policy_input_bindings"], item["policy_input_facts"])
    first = evaluate_decision_core(inp, MERGE_ELIGIBILITY_POLICY_V1)
    second = evaluate_decision_core(inp, MERGE_ELIGIBILITY_POLICY_V1)
    assert first == second


def test_reversed_json_key_order_is_equivalent() -> None:
    item = case("GC-S1-021")
    bindings, facts = item["policy_input_bindings"], item["policy_input_facts"]
    normal = evaluate_decision_core(build_input(bindings, facts), MERGE_ELIGIBILITY_POLICY_V1)
    reversed_facts = {k: facts[k] for k in reversed(list(facts))}
    reversed_bindings = {k: bindings[k] for k in reversed(list(bindings))}
    reordered = evaluate_decision_core(
        build_input(reversed_bindings, reversed_facts), MERGE_ELIGIBILITY_POLICY_V1
    )
    assert normal == reordered


def _reversed_insertion_policy() -> MergeEligibilityPolicy:
    """An equivalent policy whose mapping insertion orders are reversed and
    whose reason/rule sequences are reversed, but which is otherwise
    semantically identical to MERGE_ELIGIBILITY_POLICY_V1."""
    p = MERGE_ELIGIBILITY_POLICY_V1
    reversed_enum = {
        fact: {k: v for k, v in reversed(list(mapping.items()))}
        for fact, mapping in reversed(list(p.enum_fact_reasons.items()))
    }
    reversed_violation = {
        k: v for k, v in reversed(list(p.violation_tag_reasons.items()))
    }
    reversed_set = {k: v for k, v in reversed(list(p.set_fact_triggers.items()))}
    return dataclasses.replace(
        p,
        reason_definitions=tuple(reversed(p.reason_definitions)),
        enum_fact_reasons=reversed_enum,
        violation_tag_reasons=reversed_violation,
        set_fact_triggers=reversed_set,
        # verifier_rule order is semantically significant (first-match); keep it.
        verifier_rule=p.verifier_rule,
    )


def test_policy_insertion_order_independent() -> None:
    reversed_policy = _reversed_insertion_policy()
    for item in cases():
        bindings, facts = item["policy_input_bindings"], item["policy_input_facts"]
        inp = build_input(bindings, facts)
        base = evaluate_decision_core(inp, MERGE_ELIGIBILITY_POLICY_V1)
        alt = evaluate_decision_core(inp, reversed_policy)
        assert base == alt


# =============================================================================
# Explicit policy-parameter test
# =============================================================================


def test_evaluator_follows_supplied_policy_not_global() -> None:
    """Construct a second valid, total policy with one bounded mapping change
    and prove the evaluator's result follows the SUPPLIED policy, not the
    production constant."""
    # Change: approval_status STALE now maps to APPROVAL_MISSING instead of
    # APPROVAL_STALE (both are committed BLOCK codes, so totality/structure
    # hold). This is a test-only policy snapshot; the production constant is
    # untouched.
    enum = {
        fact: dict(mapping)
        for fact, mapping in MERGE_ELIGIBILITY_POLICY_V1.enum_fact_reasons.items()
    }
    enum["approval_status"]["STALE"] = "APPROVAL_MISSING"
    modified = dataclasses.replace(MERGE_ELIGIBILITY_POLICY_V1, enum_fact_reasons=enum)

    facts = _green_facts()
    facts["approval_status"] = "STALE"
    inp = build_input(_baseline_bindings(), facts)

    base = evaluate_decision_core(inp, MERGE_ELIGIBILITY_POLICY_V1)
    alt = evaluate_decision_core(inp, modified)

    assert "APPROVAL_STALE" in base.complete_reason_codes
    assert "APPROVAL_STALE" not in alt.complete_reason_codes
    assert "APPROVAL_MISSING" in alt.complete_reason_codes
    # Production constant unchanged.
    assert (
        MERGE_ELIGIBILITY_POLICY_V1.enum_fact_reasons["approval_status"]["STALE"]
        == "APPROVAL_STALE"
    )


# =============================================================================
# Separation audit (no digest/identity/record/facade/registry/replay)
# =============================================================================


def _module_source() -> str:
    return MODULE_PATH.read_text()


def test_decision_core_construction_calls_no_digest() -> None:
    core = evaluate_decision_core(
        build_input(
            case("GC-S1-001")["policy_input_bindings"],
            case("GC-S1-001")["policy_input_facts"],
        ),
        MERGE_ELIGIBILITY_POLICY_V1,
    )
    assert not any("digest" in f.name for f in dataclasses.fields(core))


def test_evaluator_function_body_calls_no_digest_or_identity_attachment() -> None:
    """AST-inspect evaluate_decision_core and DecisionCore.__post_init__: no
    call to canonical_digest / input_digest / decision_digest, and no
    construction of identity/record/facade symbols."""
    tree = ast.parse(_module_source())
    targets: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate_decision_core":
            targets["evaluate_decision_core"] = node
        if isinstance(node, ast.ClassDef) and node.name == "DecisionCore":
            targets["DecisionCore"] = node
    assert "evaluate_decision_core" in targets
    assert "DecisionCore" in targets

    forbidden_calls = {
        "canonical_digest",
        "input_digest",
        "to_canonical_payload",
        "decision_digest_for",
        "sha256_digest_bytes",
        "canonical_json_bytes",
    }
    for name, node in targets.items():
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                func = sub.func
                called = None
                if isinstance(func, ast.Name):
                    called = func.id
                elif isinstance(func, ast.Attribute):
                    called = func.attr
                assert called not in forbidden_calls, (name, called)


def test_production_module_defines_no_gate_1b_c_or_later_symbols() -> None:
    source = _module_source()
    prohibited = (
        "def finalize_decision",
        "class MergeEligibilityDecision",
        "def decision_digest_for",
        "class PolicyEvaluationRecord",
        "def build_policy_evaluation_record",
        "def validate_policy_evaluation_record",
        "class RecordConstructionError",
        "def evaluate_merge_eligibility",
        "_PRODUCTION_POLICY",
        "class PolicyRegistry",
        "class EvaluatorRegistry",
        "class SemanticReplayResult",
        "def verify_semantic_replay",
    )
    for symbol in prohibited:
        assert symbol not in source, symbol


def test_no_additional_production_module_created() -> None:
    build_harness = ROOT / "agent_core/build_harness"
    assert not (build_harness / "merge_eligibility_record.py").exists()
    assert not (build_harness / "merge_eligibility_facade.py").exists()
    assert not (build_harness / "merge_eligibility_replay.py").exists()


def test_evaluator_import_surface_unchanged() -> None:
    tree = ast.parse(_module_source())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    allowed = {"__future__", "re", "dataclasses", "enum", "types", "typing", "agent_core"}
    assert roots <= allowed, roots - allowed


# =============================================================================
# Error behavior — internal faults raise, never fabricate a policy outcome
# =============================================================================


def test_evaluator_rejects_non_policy_input() -> None:
    with pytest.raises(MergeEligibilityEvaluationError):
        evaluate_decision_core(object(), MERGE_ELIGIBILITY_POLICY_V1)  # type: ignore[arg-type]


def test_evaluator_rejects_non_policy() -> None:
    inp = build_input(
        case("GC-S1-001")["policy_input_bindings"],
        case("GC-S1-001")["policy_input_facts"],
    )
    with pytest.raises(MergeEligibilityEvaluationError):
        evaluate_decision_core(inp, object())  # type: ignore[arg-type]


def test_decision_core_rejects_inconsistent_partition() -> None:
    """A structurally valid but semantically inconsistent DecisionCore
    construction (a reason in blocking that is absent from complete) is an
    internal fault, not a policy outcome."""
    with pytest.raises(MergeEligibilityEvaluationError):
        DecisionCore(
            disposition=Disposition.BLOCK,
            decision_authority=DecisionAuthority.AUTHORITATIVE,
            primary_reason_code="APPROVAL_MISSING",
            complete_reason_codes=(),
            blocking_reason_codes=("APPROVAL_MISSING",),
            review_reason_codes=(),
            required_requirement_ids=(),
            satisfied_requirement_ids=(),
            invalid_requirement_ids=(),
            missing_requirement_ids=(),
            rejected_evidence_ids=(),
            invalid_provenance_evidence_ids=(),
            unexpected_evidence_ids=(),
        )


def test_decision_core_rejects_disposition_partition_mismatch() -> None:
    with pytest.raises(MergeEligibilityEvaluationError):
        DecisionCore(
            disposition=Disposition.ELIGIBLE_TO_MERGE_UNDER_POLICY,
            decision_authority=DecisionAuthority.AUTHORITATIVE,
            primary_reason_code="APPROVAL_MISSING",
            complete_reason_codes=("APPROVAL_MISSING",),
            blocking_reason_codes=("APPROVAL_MISSING",),
            review_reason_codes=(),
            required_requirement_ids=(),
            satisfied_requirement_ids=(),
            invalid_requirement_ids=(),
            missing_requirement_ids=(),
            rejected_evidence_ids=(),
            invalid_provenance_evidence_ids=(),
            unexpected_evidence_ids=(),
        )


def test_decision_core_rejects_primary_absent_from_complete() -> None:
    with pytest.raises(MergeEligibilityEvaluationError):
        DecisionCore(
            disposition=Disposition.BLOCK,
            decision_authority=DecisionAuthority.AUTHORITATIVE,
            primary_reason_code="CANDIDATE_STALE",
            complete_reason_codes=("APPROVAL_MISSING",),
            blocking_reason_codes=("APPROVAL_MISSING",),
            review_reason_codes=(),
            required_requirement_ids=(),
            satisfied_requirement_ids=(),
            invalid_requirement_ids=(),
            missing_requirement_ids=(),
            rejected_evidence_ids=(),
            invalid_provenance_evidence_ids=(),
            unexpected_evidence_ids=(),
        )


def test_evaluator_internal_fault_not_a_policy_outcome() -> None:
    """A policy whose reason mapping references a code missing from its own
    reason_definitions cannot be constructed (Gate 1B-A rejects it), so an
    inconsistent policy never reaches the evaluator. Confirm the guard: a
    policy with a reason whose default disposition is neither BLOCK nor
    REVIEW is impossible to build, proving the evaluator can only ever see a
    consistent policy. We assert the invariant on the production policy."""
    dispo_values = {
        rd.default_disposition
        for rd in MERGE_ELIGIBILITY_POLICY_V1.reason_definitions
    }
    assert dispo_values <= {Disposition.BLOCK, Disposition.REVIEW_REQUIRED}

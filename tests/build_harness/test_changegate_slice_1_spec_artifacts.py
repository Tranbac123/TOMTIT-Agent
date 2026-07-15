"""ChangeGate Slice 1A (R2) — executable validation of the specification artifacts ONLY.

R2 hardening on top of R1, per the independent Sol High reverify (H-R1-01…03,
M-R1-01…03):

- the A2 input binds every deterministic SOURCE digest, and the ten §18.3 replay
  invariants are pinned with a test-only digest oracle built on the REAL production
  helper `agent_core.build_harness.canonical.canonical_digest()`;
- ONE canonical digest representation (`sha256:` + 64 lowercase hex) across spec, fixture,
  schema and tests — a real `canonical_digest()` value must validate in every digest field,
  and bare/uppercase/wrong-algorithm/whitespace forms must not;
- the event schema carries the full causal chain (evaluation → attempt → completion →
  validation/rollback, plus feedback targeting an exact prior event with a human actor),
  validated both locally (JSON Schema) and across events (a test-only chain validator);
- the precedence table and the load-bearing dispositions are pinned INDEPENDENTLY here,
  so a coordinated rank change in the fixture alone fails even when its expectations are
  recomputed consistently;
- requirement-id and evidence-record-id universes are declared and enforced disjoint;
- privacy claims match enforcement: URL/traversal/multiline/diff/token-shaped values are
  rejected, and the schema is documented as shape-level control only.

These tests validate artifacts only. The oracles are acceptance-test oracles, NOT the
future production evaluator or event store (Production Implementation: NOT_STARTED).
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

SPEC_PATH = ROOT / "docs/strategy/CHANGEGATE_VERTICAL_MVP_SLICE_1_POLICY_SPEC.md"
FIXTURE_PATH = ROOT / "data/evals/changegate_merge_eligibility_golden_cases.json"
SCHEMA_PATH = ROOT / "data/schemas/changegate_evaluation_event_v1.schema.json"

DISPOSITIONS = ("ELIGIBLE_TO_MERGE_UNDER_POLICY", "REVIEW_REQUIRED", "BLOCK")
AUTHORITIES = ("AUTHORITATIVE", "ADVISORY_ONLY")
NO_APPROVAL_SENTINEL = "NO_APPROVAL_SUPPLIED"

EVENT_TYPES = (
    "CHANGEGATE_EVALUATION_COMPLETED",
    "CHANGEGATE_REVIEW_OVERRIDDEN",
    "CHANGEGATE_MERGE_ATTEMPTED",
    "CHANGEGATE_MERGE_COMPLETED",
    "CHANGEGATE_POST_MERGE_VALIDATION",
    "CHANGEGATE_ROLLBACK_RECORDED",
    "CHANGEGATE_USER_FEEDBACK_RECORDED",
)

OD_S1A_IDS = tuple(f"OD-S1A-{i:03d}" for i in range(1, 9))

# ---------------------------------------------------------------------------
# INDEPENDENT DRAFT NORMATIVE TABLES (M-R1-01).
#
# Hard-coded here, NOT derived from the fixture. The fixture taxonomy, the spec §9 table
# and this table must agree exactly, so a coordinated rank change made in the fixture
# alone — even with its expected primaries recomputed consistently — fails.
#
# STATUS: this is the currently proposed DRAFT precedence (spec §10). Owner acceptance
# (OD-S1A-007) may change it. Any change requires an explicit owner-acceptance patch that
# updates the spec, the fixture AND this table together.
# ---------------------------------------------------------------------------
DRAFT_PRECEDENCE_PENDING_OD_S1A_007: dict[str, int] = {
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

DRAFT_DISPOSITION_BY_CODE: dict[str, str] = {
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

REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
CANONICAL_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# evaluation_mode is NOT here (R3): it is single-sourced in policy_input_bindings, not a
# fact. ENUM_FACT_VALUES lists only EligibilityFacts enum states.
ENUM_FACT_VALUES = {
    "task_context_current": ("CURRENT", "STALE", "UNKNOWN"),
    "candidate_binding_current": ("CURRENT", "STALE", "UNKNOWN"),
    "repository_snapshot_current": ("CURRENT", "MISMATCH", "UNKNOWN"),
    "repository_release_clean": ("CLEAN", "DIRTY", "UNKNOWN"),
    "policy_context_current": ("CURRENT", "STALE", "UNKNOWN"),
    "evidence_context_status": ("COHERENT", "INCOHERENT", "UNKNOWN"),
    "scope_status": ("COMPLIANT", "VIOLATION", "SEMANTIC_UNCERTAIN", "NOT_EVALUATED"),
    "approval_status": ("VALID", "MISSING", "STALE", "UNKNOWN"),
    "authority_status": ("VALID", "INVALID", "UNKNOWN"),
}
EVALUATION_MODES = ("ENFORCE", "SHADOW")
VERIFIER_IDENTITY_VALUES = ("ATTESTED", "PRESENT_UNATTESTED", "ABSENT", "INVALID")
VERIFIER_INDEPENDENCE_VALUES = ("INDEPENDENT", "NOT_INDEPENDENT", "UNKNOWN")
VIOLATION_TAGS = ("TASK_MISMATCH", "RUN_MISMATCH", "CANDIDATE_MISMATCH",
                  "PROVENANCE_INVALID", "DUPLICATE_IDENTITY")
REQUIREMENT_SETS = ("required_requirement_ids", "satisfied_requirement_ids",
                    "invalid_requirement_ids", "missing_requirement_ids")
EVIDENCE_RECORD_SETS = ("rejected_evidence_ids", "invalid_provenance_evidence_ids",
                        "unexpected_evidence_ids")
SET_FACTS = REQUIREMENT_SETS + EVIDENCE_RECORD_SETS

SOURCE_DIGEST_FIELDS = (
    "task_contract_digest", "candidate_digest", "repository_snapshot_digest",
    "verification_bundle_digest", "approval_digest", "authority_binding_digest",
    "verifier_binding_digest", "policy_digest",
)

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN"),
    re.compile(r"PRIVATE KEY"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"eyJhbGciOi"),
)


def _spec_text() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validator() -> Draft202012Validator:
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _is_valid(validator: Draft202012Validator, instance: dict) -> bool:
    return not list(validator.iter_errors(instance))


def _case(case_id: str) -> dict:
    return copy.deepcopy(
        next(c for c in _fixture()["cases"] if c["case_id"] == case_id)
    )


# ---------------------------------------------------------------------------
# Independent test-only semantic oracle. Derives reasons from FACTS alone (never from a
# case's expected_* fields), using the fixture's normative fact_state_mapping for the
# fact→reason edges and this module's INDEPENDENT tables for precedence/disposition.
# Acceptance-test oracle only — not the production evaluator.
# ---------------------------------------------------------------------------

def oracle_reason_codes(facts: dict, mapping: dict) -> set[str]:
    reasons: set[str] = set()
    for fact, table in mapping["enum_facts"].items():
        value = facts[fact]
        assert value in table, f"unmapped state {fact}={value!r}"
        code = table[value]
        if code:
            reasons.add(code)
    for tag in facts["evidence_context_violations"]:
        reasons.add(mapping["violation_tag_reasons"][tag])
    for set_fact, code in mapping["set_facts"].items():
        if code and facts[set_fact]:
            reasons.add(code)
    for rule in mapping["verifier_rule"]:  # ordered first-match (spec §15)
        if facts["verifier_identity_status"] in rule["identity"] and (
            rule["independence"] == "*"
            or facts["verifier_independence_status"] in rule["independence"]
        ):
            if rule["reason"]:
                reasons.add(rule["reason"])
            break
    else:  # pragma: no cover - totality is separately asserted
        raise AssertionError("verifier rule is not total")
    return reasons


def oracle_decision(facts: dict, mapping: dict, evaluation_mode: str) -> dict:
    """Precedence and disposition come from this module's INDEPENDENT draft tables;
    authority comes from the single-sourced evaluation_mode (an A2-input field, §5.2 /
    §6.3), NOT from facts."""
    assert evaluation_mode in EVALUATION_MODES, evaluation_mode
    reasons = oracle_reason_codes(facts, mapping)
    if reasons:
        primary = min(reasons, key=lambda code: DRAFT_PRECEDENCE_PENDING_OD_S1A_007[code])
        disposition = (
            "BLOCK"
            if any(DRAFT_DISPOSITION_BY_CODE[c] == "BLOCK" for c in reasons)
            else "REVIEW_REQUIRED"
        )
    else:
        primary = None
        disposition = "ELIGIBLE_TO_MERGE_UNDER_POLICY"
    authority = "AUTHORITATIVE" if evaluation_mode == "ENFORCE" else "ADVISORY_ONLY"
    blocking = sorted(c for c in reasons if DRAFT_DISPOSITION_BY_CODE[c] == "BLOCK")
    review = sorted(c for c in reasons if DRAFT_DISPOSITION_BY_CODE[c] == "REVIEW_REQUIRED")
    return {
        "complete": sorted(reasons),
        "blocking": blocking,
        "review": review,
        "primary": primary,
        "disposition": disposition,
        "authority": authority,
    }


def case_mode(case: dict) -> str:
    return case["policy_input_bindings"]["evaluation_mode"]


# ---------------------------------------------------------------------------
# Test-only digest oracles for the §18.5 replay invariants and the exact §7.3 /
# §18.2 record and trace payloads. Every digest uses the REAL production
# canonical_digest(), so the tests exercise the repository's canonical representation.
# These are acceptance-test oracles, NOT the production evaluator or event store.
# ---------------------------------------------------------------------------

def a2_input_payload(bindings: dict, facts: dict) -> dict:
    """evaluation_mode comes from bindings (single source); facts carry no mode."""
    assert "evaluation_mode" not in facts, "facts must not carry evaluation_mode (R3)"
    return {
        "kind": "changegate.merge-eligibility-policy-input.test-oracle.v1",
        "task_id": bindings["task_id"],
        **{field: bindings[field] for field in SOURCE_DIGEST_FIELDS},
        "policy_version": bindings["policy_version"],
        "evaluator_version": bindings["evaluator_version"],
        "evaluation_mode": bindings["evaluation_mode"],
        "facts": {key: facts[key] for key in sorted(facts)},
    }


def input_digest_oracle(bindings: dict, facts: dict) -> str:
    return canonical_digest(a2_input_payload(bindings, facts))


def _decision_core(bindings: dict, facts: dict, mapping: dict) -> dict:
    """The deterministic decision fields shared by the decision digest and the record."""
    outcome = oracle_decision(facts, mapping, bindings["evaluation_mode"])
    return {
        "task_id": bindings["task_id"],
        **{field: bindings[field] for field in SOURCE_DIGEST_FIELDS},
        "policy_version": bindings["policy_version"],
        "evaluator_version": bindings["evaluator_version"],
        "evaluation_mode": bindings["evaluation_mode"],
        "input_digest": input_digest_oracle(bindings, facts),
        "disposition": outcome["disposition"],
        "decision_authority": outcome["authority"],
        "primary_reason_code": outcome["primary"],
        "complete_reason_codes": outcome["complete"],
        "blocking_reason_codes": outcome["blocking"],
        "review_reason_codes": outcome["review"],
        **{s: sorted(facts[s]) for s in SET_FACTS},
    }


def decision_digest_oracle(bindings: dict, facts: dict, mapping: dict) -> str:
    payload = {"kind": "changegate.merge-eligibility-decision.test-oracle.v1",
               **_decision_core(bindings, facts, mapping)}
    return canonical_digest(payload)


def policy_record_payload(bindings: dict, facts: dict, mapping: dict) -> dict:
    """Exact §7.3 PolicyEvaluationRecordPayload (excludes policy_record_digest and any
    application/trace metadata). Includes decision_digest."""
    core = _decision_core(bindings, facts, mapping)
    return {
        "schema_version": "changegate.policy-evaluation-record.v1",
        **core,
        "decision_digest": decision_digest_oracle(bindings, facts, mapping),
    }


def build_policy_record(bindings: dict, facts: dict, mapping: dict) -> dict:
    payload = policy_record_payload(bindings, facts, mapping)
    return {**payload, "policy_record_digest": canonical_digest(payload)}


def recompute_record_digest(record: dict) -> str:
    payload = {k: v for k, v in record.items() if k != "policy_record_digest"}
    return canonical_digest(payload)


def validate_policy_record(record: dict) -> list[str]:
    """Independent record validator: recompute the digest and check self-consistency.
    Does NOT read any fixture expected_* value."""
    errors: list[str] = []
    if record.get("schema_version") != "changegate.policy-evaluation-record.v1":
        errors.append("record schema_version mismatch")
    for forbidden in ("redaction_classification", "trace_id", "request_id",
                      "evaluation_id", "occurred_at", "timestamp",
                      "evaluation_latency_ms", "event_id", "storage_location"):
        if forbidden in record:
            errors.append(f"record must not contain application field {forbidden!r}")
    if recompute_record_digest(record) != record.get("policy_record_digest"):
        errors.append("policy_record_digest does not match the recomputed payload")
    # blocking ∪ review == complete, and both are the correct partition.
    complete = set(record.get("complete_reason_codes", []))
    if set(record.get("blocking_reason_codes", [])) | set(
        record.get("review_reason_codes", [])
    ) != complete:
        errors.append("blocking ∪ review != complete reason set")
    return errors


def build_trace_envelope(record: dict, meta: dict) -> dict:
    payload = {
        "schema_version": "changegate.evaluation-trace-envelope.v1",
        "trace_id": meta["trace_id"],
        "evaluation_id": meta["evaluation_id"],
        "request_id": meta["request_id"],
        "occurred_at": meta["occurred_at"],
        "evaluation_latency_ms": meta["evaluation_latency_ms"],
        "redaction_classification": meta["redaction_classification"],
        "policy_record": record,
        "policy_record_digest": record["policy_record_digest"],
        "input_digest": record["input_digest"],
        "decision_digest": record["decision_digest"],
    }
    return {**payload, "trace_digest": canonical_digest(payload)}


def validate_trace_envelope(trace: dict) -> list[str]:
    """Independent trace validator (§18.3/§18.4). Recomputes every dependent digest and
    checks embedded==top-level. Never reads fixture expected_* values."""
    errors: list[str] = []
    record = trace.get("policy_record")
    if not isinstance(record, dict):
        return ["trace has no embedded policy_record"]
    errors.extend(validate_policy_record(record))
    if trace.get("policy_record_digest") != record.get("policy_record_digest"):
        errors.append("trace.policy_record_digest != embedded record digest")
    if trace.get("input_digest") != record.get("input_digest"):
        errors.append("trace.input_digest != embedded record input_digest")
    if trace.get("decision_digest") != record.get("decision_digest"):
        errors.append("trace.decision_digest != embedded record decision_digest")
    payload = {k: v for k, v in trace.items() if k != "trace_digest"}
    if trace.get("trace_digest") != canonical_digest(payload):
        errors.append("trace_digest not recomputed after a change")
    return errors


def _trace_meta(**overrides) -> dict:
    meta = {
        "trace_id": "trace-1", "evaluation_id": "eval-1", "request_id": "req-1",
        "occurred_at": "2026-07-15T00:00:00Z", "evaluation_latency_ms": 7,
        "redaction_classification": "INTERNAL",
    }
    meta.update(overrides)
    return meta


# ---------------------------------------------------------------------------
# Policy specification document
# ---------------------------------------------------------------------------

def test_policy_spec_exists():
    assert SPEC_PATH.is_file(), f"missing policy spec: {SPEC_PATH}"


def test_policy_spec_status_remains_draft_for_owner_review():
    text = _spec_text()
    assert re.search(r"^Status:\s*DRAFT_FOR_OWNER_REVIEW\s*$", text, re.MULTILINE)
    header = "\n".join(text.splitlines()[:25])
    assert "ACCEPTED_BY_OWNER" not in header
    assert re.search(
        r"^Production Implementation:\s*NOT_STARTED\s*$", text, re.MULTILINE
    )
    assert re.search(r"^Independent Verification:\s*PENDING\s*$", text, re.MULTILINE)
    assert re.search(r"^Owner:\s*TranBac\s*$", text, re.MULTILINE)
    assert "Baseline: 3e72e93bfac8da2ecdb7960a55ae0357135eb61e" in text


def test_policy_spec_contains_all_three_dispositions_and_authorities():
    text = _spec_text()
    for value in DISPOSITIONS + AUTHORITIES:
        assert value in text, f"spec must define {value}"


def test_safe_to_merge_is_absent_as_an_output_term_in_spec():
    for lineno, line in enumerate(_spec_text().splitlines(), start=1):
        for term in ("SAFE_TO_MERGE", "VERIFIED_AND_MERGE"):
            if term in line:
                lowered = line.lower()
                assert (
                    "forbidden" in lowered or "must never" in lowered
                    or "must not" in lowered
                ), f"spec line {lineno} uses {term} outside a forbidding statement"


def test_safe_to_merge_never_appears_in_machine_artifacts():
    for path in (FIXTURE_PATH, SCHEMA_PATH):
        content = path.read_text(encoding="utf-8")
        assert "SAFE_TO_MERGE" not in content
        assert "VERIFIED_AND_MERGE" not in content


def test_policy_spec_keeps_required_normative_invariants():
    text = _spec_text()
    normalized = " ".join(text.split())
    # ADR-001 durable obligations.
    assert "FOLLOWUP-P0-9B1-001" in text and "FOLLOWUP-P0-9B1-002" in text
    assert "required evidence  ⊆  valid verified evidence bound to the current task" in text
    assert "required_requirement_ids = satisfied ∪ invalid ∪ missing" in text
    assert "pairwise disjoint" in text
    assert "never authorization to merge" in text
    assert "`UNKNOWN` never defaults toward eligibility" in normalized
    assert "Facts grant no authority by themselves" in text
    # R1 closures that must stay closed.
    assert "matched_requirement_id is None" in text
    assert "EligibilityFactDerivationInput" in text
    assert "MergeEligibilityPolicyInput" in text
    assert "SHADOW  mode → decision_authority = ADVISORY_ONLY" in text
    assert "automatic policy weakening" in text
    assert "direct active-policy mutation" in text
    # R2: construction boundary and one canonical digest representation.
    assert "PolicyEvaluationRecord" in text
    assert "EvaluationTraceEnvelope" in text
    assert "It returns **no** trace envelope" in text
    assert "sha256:<64 lowercase hexadecimal characters>" in text
    assert "Bare 64-hex digests are not a valid representation" in normalized
    # R2: identifier universes and privacy scope limit.
    assert "requirement_id_universe" in text and "evidence_record_id_universe" in text
    assert "Schema-level controls" in text and "Application sink controls" in text
    assert "cannot, identify every possible secret value" in normalized


def test_policy_spec_has_all_required_sections():
    text = _spec_text()
    required_sections = [
        "## 1. Context", "## 2. Goals", "## 3. Non-Goals",
        "## 4. Existing Contract Inventory", "## 5. Policy Input",
        "## 6. Eligibility Facts", "## 7. Policy Output",
        "## 8. Disposition Semantics", "## 9. Reason-Code Taxonomy",
        "## 10. Deterministic Precedence", "## 11. Required Evidence Completeness",
        "## 12. Candidate and Repository Freshness", "## 13. Scope Semantics",
        "## 14. Approval and Authority", "## 15. Verifier Independence",
        "## 16. Multiple-Failure Behavior", "## 17. Human Override Boundaries",
        "## 18. EvaluationTraceEnvelope", "## 19. Product Event Schema",
        "## 20. Outcome and Feedback Linkage",
        "## 21. Privacy, Security and Redaction", "## 22. Golden Evaluation Matrix",
        "## 23. Proposed A2 Implementation Scope", "## 24. Deferred Decisions",
        "## 25. Owner Decision Points", "## 26. Exit Criteria",
    ]
    for section in required_sections:
        assert section in text, f"spec is missing required section {section!r}"


def test_policy_spec_declares_every_a2_source_binding():
    """H-R1-01: the A2 input must bind every deterministic source digest."""
    text = _spec_text()
    section = text.split("### 5.2 MergeEligibilityPolicyInput")[1].split("For every proposed")[0]
    for field in SOURCE_DIGEST_FIELDS:
        assert field in section, f"A2 input does not bind {field}"
    assert NO_APPROVAL_SENTINEL in section, "no-approval sentinel must be explicit"
    assert "must not inspect the" in section and "clock" in section


def test_policy_spec_pins_the_ten_replay_invariants():
    text = _spec_text()
    section = text.split("### 18.5 Digest replay invariants")[1].split("Three layers")[0]
    for n in range(1, 11):
        assert f"| {n} |" in section, f"replay invariant {n} is not stated"
    assert "never** excluded from decision" in section
    assert "FULLY_SPECIFIED_AND_REPRODUCIBLE" in section


def test_policy_spec_cites_deferred_owner_decisions_without_resolving_them():
    text = _spec_text()
    for decision_id in ("OD-G1-001", "OD-G1-002", "OD-G1-003", "OD-G1-004"):
        assert decision_id in text


def test_owner_review_is_still_required_and_all_eight_od_points_registered():
    text = _spec_text()
    assert "PENDING_OWNER_DECISION" in text
    for od in OD_S1A_IDS:
        assert od in text, f"spec must list owner decision point {od}"
    # OD-S1A-008 classification is explicit and blocks A3 (Slice 1C-1) only.
    assert "Slice 1C-1 / A3:         BLOCKED UNTIL ACCEPTED" in text
    assert "Slice 1B / A2:           NOT BLOCKED" in text
    assert "Slice 1A owner review:   NOT BLOCKED" in text
    # The precedence table is a draft pending OD-S1A-007.
    assert "DRAFT PROPOSAL, PENDING_OWNER_DECISION OD-S1A-007" in text


# ---------------------------------------------------------------------------
# Canonical digest representation (H-R1-02)
# ---------------------------------------------------------------------------

def test_production_canonical_digest_is_accepted_by_every_digest_field():
    """The value the repository's own canonical_digest() emits must be carriable, with no
    conversion, in every schema field intended to hold a canonical digest."""
    real = canonical_digest({"kind": "changegate.slice1a.test-probe.v1", "n": 1})
    assert CANONICAL_DIGEST_RE.match(real), real
    validator = _validator()
    instance = {
        **_base_envelope("CHANGEGATE_EVALUATION_COMPLETED"),
        "decision_ref": {
            "evaluation_id": "eval-1", "decision_digest": real,
            "policy_record_digest": real, "input_digest": real,
            "task_ref": _ROOT_TASK, "candidate_digest": real,
            "disposition": "BLOCK", "decision_authority": "AUTHORITATIVE",
            "primary_reason_code": "SCOPE_VIOLATION", "evaluation_mode": "ENFORCE",
        },
        "context_digest": real,
        "policy_version": "changegate-policy.v4-draft",
        "evaluator_version": "0.1.0",
        "outcome": {"status": "SUCCESS", "detail_code": "EVALUATION_OK"},
        "evidence_refs": [{"evidence_id": "ev-pytest-1", "requirement_id": "req-pytest-full",
                           "digest": real}],
        "subject_ref": {"namespace": "changegate", "kind": "git_candidate",
                        "value": "cand-1", "digest": real},
    }
    errors = list(validator.iter_errors(instance))
    assert not errors, f"canonical digest rejected: {errors[0].message}"


@pytest.mark.parametrize("bad", [
    "a" * 64,                              # bare hex (the old private convention)
    "SHA256:" + "a" * 64,                  # uppercase prefix
    "sha256:" + "A" * 64,                  # uppercase hex
    "sha512:" + "a" * 64,                  # wrong algorithm
    "sha256:" + "a" * 63,                  # wrong length
    "sha256: " + "a" * 64,                 # whitespace
    "sha256:" + "a" * 64 + "\n",           # newline
])
def test_malformed_digest_representations_are_rejected(bad):
    validator = _validator()
    instance = {**_base_envelope("CHANGEGATE_MERGE_ATTEMPTED"),
                "evaluation_event_ref": "evt-eval-1",
                "decision_ref": {"evaluation_id": "eval-1", "decision_digest": bad},
                "outcome": {"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"}}
    assert not _is_valid(validator, instance), f"malformed digest accepted: {bad!r}"


def test_fixture_bindings_use_the_canonical_digest_representation():
    suite = _fixture()
    assert suite["digest_representation"] == "sha256:<64 lowercase hex>"
    for c in suite["cases"]:
        bindings = c["policy_input_bindings"]
        for field in SOURCE_DIGEST_FIELDS:
            value = bindings[field]
            if field == "approval_digest" and value == NO_APPROVAL_SENTINEL:
                continue
            assert CANONICAL_DIGEST_RE.match(value), (c["case_id"], field, value)


# ---------------------------------------------------------------------------
# Event schema — meta-validation, positive and negative instances, causal linkage
# ---------------------------------------------------------------------------

_DIGEST_A = canonical_digest({"probe": "decision-a"})
_DIGEST_B = canonical_digest({"probe": "input-a"})
_DIGEST_C = canonical_digest({"probe": "record-a"})
_COMMIT = "b" * 40
_ROOT_TASK = "changegate-slice1a-demo"
_ROOT_CANDIDATE = canonical_digest({"probe": "candidate-a"})


def _base_envelope(event_type: str) -> dict:
    return {
        "event_id": "evt-1",
        "event_type": event_type,
        "occurred_at": "2026-07-15T00:00:00Z",
        "schema_version": "changegate-evaluation-event.v1",
        "product": "changegate",
        "task_ref": _ROOT_TASK,
        "subject_ref": {
            "namespace": "changegate", "kind": "git_candidate", "value": "cand-1",
            "commit_sha": _COMMIT, "digest": _ROOT_CANDIDATE,
        },
        "provenance": {"emitter": "changegate-cli", "emitter_version": "0.1.0",
                       "trace_id": None, "request_id": None},
        "privacy_classification": "INTERNAL",
    }


# A decision_ref now carries the COMPLETE decision identity + task/candidate lineage
# (schema-required for every event type, §11/§19.3).
_DECISION_REF = {
    "evaluation_id": "eval-1", "trace_id": "trace-1",
    "decision_digest": _DIGEST_A, "input_digest": _DIGEST_B,
    "policy_record_digest": _DIGEST_C,
    "task_ref": _ROOT_TASK, "candidate_digest": _ROOT_CANDIDATE,
    "disposition": "ELIGIBLE_TO_MERGE_UNDER_POLICY",
    "decision_authority": "AUTHORITATIVE", "primary_reason_code": None,
    "evaluation_mode": "ENFORCE",
}
_OUTCOME = {"status": "SUCCESS", "detail_code": "OK", "target_ref": None}
_MERGE_OUTCOME = {"status": "SUCCESS", "detail_code": "MERGE_FAST_FORWARD",
                  "resulting_commit_sha": "c" * 40}
_FEEDBACK = {"actor_ref": "user-42", "verdict": "DISAGREE",
             "category_code": "DISPUTED_BLOCK", "reason_code": None,
             "comment_digest": None}
_OVERRIDE = {"actor_ref": "owner-1", "reason_code": "SCOPE_EXCEPTION",
             "new_decision_digest": None, "exception_ref": "exc-1",
             "expires_at": "2026-08-01T00:00:00Z"}

_POSITIVE_EXTRAS: dict[str, dict] = {
    "CHANGEGATE_EVALUATION_COMPLETED": {
        "decision_ref": _DECISION_REF, "context_digest": _DIGEST_B,
        "policy_version": "changegate-policy.v3-draft", "evaluator_version": "0.1.0",
        "outcome": {"status": "SUCCESS", "detail_code": "EVALUATION_OK"},
    },
    "CHANGEGATE_REVIEW_OVERRIDDEN": {
        "decision_ref": _DECISION_REF, "evaluation_event_ref": "evt-eval-1",
        "override": _OVERRIDE,
    },
    "CHANGEGATE_MERGE_ATTEMPTED": {
        "decision_ref": _DECISION_REF, "evaluation_event_ref": "evt-eval-1",
        "outcome": {"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"},
    },
    "CHANGEGATE_MERGE_COMPLETED": {
        "decision_ref": _DECISION_REF, "attempt_event_ref": "evt-attempt-1",
        "outcome": _MERGE_OUTCOME,
    },
    "CHANGEGATE_POST_MERGE_VALIDATION": {
        "decision_ref": _DECISION_REF, "merge_event_ref": "evt-merge-1",
        "outcome": {"status": "FAILURE", "detail_code": "CI_SUITE_FAILED"},
    },
    "CHANGEGATE_ROLLBACK_RECORDED": {
        "decision_ref": _DECISION_REF, "merge_event_ref": "evt-merge-1",
        "validation_event_ref": "evt-validation-1",
        "outcome": {"status": "SUCCESS", "detail_code": "ROLLBACK_REVERTED"},
    },
    "CHANGEGATE_USER_FEEDBACK_RECORDED": {
        "decision_ref": _DECISION_REF, "target_event_ref": "evt-eval-1",
        "target_event_type": "CHANGEGATE_EVALUATION_COMPLETED", "feedback": _FEEDBACK,
    },
}


def test_event_schema_meta_validates_as_draft_2020_12():
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    assert schema.get("type") == "object"
    assert schema.get("additionalProperties") is False
    assert any("if" in clause for clause in schema.get("allOf", []))
    digest_def = schema["$defs"]["canonicalDigest"]["allOf"][0]
    assert digest_def["pattern"] == r"^sha256:[0-9a-f]{64}$"
    assert digest_def["minLength"] == digest_def["maxLength"] == 71
    # Anchors alone would let a TRAILING newline through (Python/ECMA '$'), so every
    # string grammar must additionally forbid whitespace.
    assert schema["$defs"]["noWhitespace"]["not"]["pattern"] == r"\s"


def test_event_schema_has_fixed_version_and_all_event_types():
    schema = _schema()
    assert schema["properties"]["schema_version"]["const"] == (
        "changegate-evaluation-event.v1"
    )
    assert set(schema["properties"]["event_type"]["enum"]) == set(EVENT_TYPES)
    assert "privacy_classification" in schema["required"]
    assert set(schema["properties"]["privacy_classification"]["enum"]) == {
        "PUBLIC", "INTERNAL", "SENSITIVE",
    }


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_minimal_unlinked_instance_is_rejected_for_every_event_type(event_type):
    validator = _validator()
    assert not _is_valid(validator, _base_envelope(event_type)), (
        f"{event_type} must not validate with only the common envelope"
    )


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_fully_linked_instance_is_accepted_for_every_event_type(event_type):
    validator = _validator()
    instance = {**_base_envelope(event_type), **_POSITIVE_EXTRAS[event_type]}
    errors = list(validator.iter_errors(instance))
    assert not errors, f"{event_type} positive instance rejected: {errors[0].message}"


def test_event_causal_linkage_negatives_are_rejected():
    """H-R1-03: an event may not omit the exact prior event it descends from."""
    validator = _validator()
    negatives = {
        "merge completed without attempt_event_ref": {
            **_base_envelope("CHANGEGATE_MERGE_COMPLETED"),
            "decision_ref": _DECISION_REF, "outcome": _MERGE_OUTCOME,
        },
        "merge completed without resulting commit": {
            **_base_envelope("CHANGEGATE_MERGE_COMPLETED"),
            "decision_ref": _DECISION_REF, "attempt_event_ref": "evt-attempt-1",
            "outcome": {"status": "SUCCESS", "detail_code": "MERGE_OK"},
        },
        "merge attempted without originating evaluation": {
            **_base_envelope("CHANGEGATE_MERGE_ATTEMPTED"),
            "decision_ref": _DECISION_REF, "outcome": _OUTCOME,
        },
        "feedback without actor_ref": {
            **_base_envelope("CHANGEGATE_USER_FEEDBACK_RECORDED"),
            "decision_ref": _DECISION_REF, "target_event_ref": "evt-eval-1",
            "target_event_type": "CHANGEGATE_EVALUATION_COMPLETED",
            "feedback": {"verdict": "DISAGREE", "category_code": "DISPUTED_BLOCK"},
        },
        "feedback without target event ref": {
            **_base_envelope("CHANGEGATE_USER_FEEDBACK_RECORDED"),
            "decision_ref": _DECISION_REF,
            "target_event_type": "CHANGEGATE_EVALUATION_COMPLETED",
            "feedback": _FEEDBACK,
        },
        "feedback without target event type": {
            **_base_envelope("CHANGEGATE_USER_FEEDBACK_RECORDED"),
            "decision_ref": _DECISION_REF, "target_event_ref": "evt-eval-1",
            "feedback": _FEEDBACK,
        },
        "feedback with null feedback": {
            **_base_envelope("CHANGEGATE_USER_FEEDBACK_RECORDED"),
            "decision_ref": _DECISION_REF, "target_event_ref": "evt-eval-1",
            "target_event_type": "CHANGEGATE_EVALUATION_COMPLETED", "feedback": None,
        },
        "override without evaluation_event_ref": {
            **_base_envelope("CHANGEGATE_REVIEW_OVERRIDDEN"),
            "decision_ref": _DECISION_REF, "override": _OVERRIDE,
        },
        "override exception without expiry": {
            **_base_envelope("CHANGEGATE_REVIEW_OVERRIDDEN"),
            "decision_ref": _DECISION_REF, "evaluation_event_ref": "evt-eval-1",
            "override": {**_OVERRIDE, "expires_at": None},
        },
        "rollback without merge_event_ref": {
            **_base_envelope("CHANGEGATE_ROLLBACK_RECORDED"),
            "decision_ref": _DECISION_REF, "outcome": _OUTCOME,
        },
        "post-merge validation without merge_event_ref": {
            **_base_envelope("CHANGEGATE_POST_MERGE_VALIDATION"),
            "decision_ref": _DECISION_REF, "outcome": _OUTCOME,
        },
        "evaluation without decision authority": {
            **_base_envelope("CHANGEGATE_EVALUATION_COMPLETED"),
            "decision_ref": {"evaluation_id": "e", "decision_digest": _DIGEST_A,
                             "disposition": "BLOCK"},
            "context_digest": _DIGEST_B, "policy_version": "v",
            "evaluator_version": "v", "outcome": _OUTCOME,
        },
        "empty outcome object": {
            **_base_envelope("CHANGEGATE_MERGE_ATTEMPTED"),
            "decision_ref": _DECISION_REF, "evaluation_event_ref": "evt-eval-1",
            "outcome": {},
        },
    }
    for name, instance in negatives.items():
        assert not _is_valid(validator, instance), f"negative accepted: {name}"


# ---------------------------------------------------------------------------
# Test-only causal-chain validator (cross-event; JSON Schema is local-shape only).
# NOT production event processing.
# ---------------------------------------------------------------------------

CHAIN_PARENT_RULES: dict[str, tuple[tuple[str, str], ...]] = {
    # event_type -> ((reference field, required type of the referenced event), ...)
    "CHANGEGATE_EVALUATION_COMPLETED": (),
    "CHANGEGATE_REVIEW_OVERRIDDEN": (
        ("evaluation_event_ref", "CHANGEGATE_EVALUATION_COMPLETED"),
    ),
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
    "CHANGEGATE_USER_FEEDBACK_RECORDED": (
        ("target_event_ref", "*"),
    ),
}


def validate_event_chain(events: list[dict]) -> list[str]:
    """Cross-event relationships a JSON Schema cannot express, INCLUDING root
    task/candidate/decision lineage (§19.3). Returns error strings.

    The first CHANGEGATE_EVALUATION_COMPLETED establishes the active root lineage
    (task_ref, candidate_digest, decision/input/policy-record digests). Every downstream
    event must match the ACTIVE lineage. A review override carrying a complete replacement
    decision (all three new_* digests) switches the active decision lineage while
    preserving task/candidate. A changed candidate cannot continue the chain; it needs a
    new evaluation event.
    """
    errors: list[str] = []
    by_id: dict[str, dict] = {}
    active: dict | None = None  # root/active lineage

    def _dref(event: dict) -> dict | None:
        dr = event.get("decision_ref")
        return dr if isinstance(dr, dict) else None

    for event in events:
        event_id = event["event_id"]
        etype = event["event_type"]
        if event_id in by_id:
            errors.append(f"duplicate event_id {event_id!r}")

        # 1. structural references resolve to an EARLIER event of the correct type.
        for field, required_type in CHAIN_PARENT_RULES[etype]:
            ref = event.get(field)
            if ref is None:
                continue
            parent = by_id.get(ref)
            if parent is None:
                errors.append(
                    f"{event_id}: {field}={ref!r} does not resolve to an EARLIER event"
                )
                continue
            if required_type != "*" and parent["event_type"] != required_type:
                errors.append(
                    f"{event_id}: {field} points at {parent['event_type']}, "
                    f"expected {required_type}"
                )

        # 2. feedback target-type label must match the referenced event's actual type.
        if etype == "CHANGEGATE_USER_FEEDBACK_RECORDED":
            target = by_id.get(event.get("target_event_ref") or "")
            if target is not None and event.get("target_event_type") != target["event_type"]:
                errors.append(
                    f"{event_id}: target_event_type {event.get('target_event_type')!r} "
                    f"!= referenced event type {target['event_type']!r}"
                )

        # 3. lineage.
        dref = _dref(event)
        if etype == "CHANGEGATE_EVALUATION_COMPLETED":
            if active is None:
                if dref is None:
                    errors.append(f"{event_id}: evaluation without decision_ref")
                else:
                    active = {
                        "task_ref": dref["task_ref"],
                        "candidate_digest": dref["candidate_digest"],
                        "decision_digest": dref["decision_digest"],
                        "input_digest": dref["input_digest"],
                        "policy_record_digest": dref["policy_record_digest"],
                    }
            # A second evaluation for a DIFFERENT candidate legitimately starts a new
            # root; for the same candidate it must keep the task. (Not exercised by the
            # positive chain, but kept coherent.)
        elif dref is not None:
            if active is None:
                errors.append(f"{event_id}: causal event before any evaluation event")
            else:
                if dref["task_ref"] != active["task_ref"]:
                    errors.append(
                        f"{event_id}: task_ref {dref['task_ref']!r} != root "
                        f"{active['task_ref']!r}"
                    )
                if dref["candidate_digest"] != active["candidate_digest"]:
                    errors.append(
                        f"{event_id}: candidate_digest diverges from the root candidate"
                    )
                if dref["decision_digest"] != active["decision_digest"]:
                    errors.append(f"{event_id}: decision_digest diverges from the chain")
                if dref["input_digest"] != active["input_digest"]:
                    errors.append(f"{event_id}: input_digest diverges from the chain")
                if dref["policy_record_digest"] != active["policy_record_digest"]:
                    errors.append(
                        f"{event_id}: policy_record_digest diverges from the chain"
                    )

        # 4. an override with a complete replacement switches the active decision lineage.
        if etype == "CHANGEGATE_REVIEW_OVERRIDDEN":
            override = event.get("override") or {}
            triple = ("new_decision_digest", "new_input_digest",
                      "new_policy_record_digest")
            present = [k for k in triple if override.get(k)]
            if present and len(present) != 3:
                errors.append(
                    f"{event_id}: override mixes an incomplete replacement decision"
                )
            elif len(present) == 3 and active is not None:
                active = {
                    **active,
                    "decision_digest": override["new_decision_digest"],
                    "input_digest": override["new_input_digest"],
                    "policy_record_digest": override["new_policy_record_digest"],
                }

        by_id[event_id] = event

    # 5. every non-root event must be causally connected (some *_event_ref present).
    ref_fields = ("evaluation_event_ref", "attempt_event_ref", "merge_event_ref",
                  "validation_event_ref", "target_event_ref")
    for event in events:
        if event["event_type"] == "CHANGEGATE_EVALUATION_COMPLETED":
            continue
        if not any(event.get(f) for f in ref_fields):
            errors.append(f"{event['event_id']}: causally disconnected (no event ref)")
    return errors


def _dref(**overrides) -> dict:
    return {**_DECISION_REF, **overrides}


def _full_chain() -> list[dict]:
    def envelope(event_id: str, event_type: str, **extra) -> dict:
        return {**_base_envelope(event_type), "event_id": event_id, **extra}

    return [
        envelope("evt-eval-1", "CHANGEGATE_EVALUATION_COMPLETED",
                 **_POSITIVE_EXTRAS["CHANGEGATE_EVALUATION_COMPLETED"]),
        envelope("evt-attempt-1", "CHANGEGATE_MERGE_ATTEMPTED",
                 decision_ref=_DECISION_REF, evaluation_event_ref="evt-eval-1",
                 outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"}),
        envelope("evt-merge-1", "CHANGEGATE_MERGE_COMPLETED",
                 decision_ref=_DECISION_REF, attempt_event_ref="evt-attempt-1",
                 outcome=_MERGE_OUTCOME),
        envelope("evt-validation-1", "CHANGEGATE_POST_MERGE_VALIDATION",
                 decision_ref=_DECISION_REF, merge_event_ref="evt-merge-1",
                 outcome={"status": "FAILURE", "detail_code": "CI_SUITE_FAILED"}),
        envelope("evt-rollback-1", "CHANGEGATE_ROLLBACK_RECORDED",
                 decision_ref=_DECISION_REF, merge_event_ref="evt-merge-1",
                 validation_event_ref="evt-validation-1",
                 outcome={"status": "SUCCESS", "detail_code": "ROLLBACK_REVERTED"}),
        envelope("evt-feedback-1", "CHANGEGATE_USER_FEEDBACK_RECORDED",
                 decision_ref=_DECISION_REF, target_event_ref="evt-merge-1",
                 target_event_type="CHANGEGATE_MERGE_COMPLETED", feedback=_FEEDBACK),
    ]


def test_complete_event_chain_validates_locally_and_causally():
    validator = _validator()
    chain = _full_chain()
    for event in chain:
        errors = list(validator.iter_errors(event))
        assert not errors, f"{event['event_id']} invalid: {errors[0].message}"
    assert validate_event_chain(chain) == []
    # attempt/result pairing is deterministic.
    completion = next(e for e in chain if e["event_type"] == "CHANGEGATE_MERGE_COMPLETED")
    assert completion["attempt_event_ref"] == "evt-attempt-1"
    assert completion["outcome"]["resulting_commit_sha"] == "c" * 40
    # every lineage field reconstructs from the root evaluation.
    root = chain[0]["decision_ref"]
    for event in chain[1:]:
        dr = event["decision_ref"]
        assert dr["task_ref"] == root["task_ref"]
        assert dr["candidate_digest"] == root["candidate_digest"]
        assert dr["decision_digest"] == root["decision_digest"]
        assert dr["input_digest"] == root["input_digest"]
        assert dr["policy_record_digest"] == root["policy_record_digest"]


def test_chain_validator_full_lineage_negative_controls():
    """END_TO_END_RECONSTRUCTABLE: all sixteen §19.3 negative controls are detected."""
    foreign_task = _dref(task_ref="other-task")
    foreign_cand = _dref(candidate_digest=canonical_digest({"probe": "other-candidate"}))

    def with_dref(chain, idx, dref):
        c = copy.deepcopy(chain)
        c[idx]["decision_ref"] = dref
        return c

    chain = _full_chain()
    controls = {
        # 1 nonexistent reference
        "nonexistent": (lambda c: _set(c, 2, "attempt_event_ref", "evt-nope"),
                        "does not resolve"),
        # 2 forward reference
        "forward": (lambda c: _set(c, 1, "evaluation_event_ref", "evt-merge-1"),
                    "does not resolve"),
        # 3 wrong event type
        "wrong_type": (lambda c: _set(c, 2, "attempt_event_ref", "evt-eval-1"),
                       "expected CHANGEGATE_MERGE_ATTEMPTED"),
        # 4 duplicate event id
        "duplicate_id": (lambda c: _set(c, 2, "event_id", "evt-attempt-1"),
                         "duplicate event_id"),
        # 5 decision-digest drift
        "decision_drift": (lambda c: with_dref(c, 3, _dref(decision_digest=_DIGEST_B)),
                           "decision_digest diverges"),
        # 6 input-digest drift
        "input_drift": (lambda c: with_dref(c, 3, _dref(input_digest=_DIGEST_A)),
                        "input_digest diverges"),
        # 7 policy-record-digest drift
        "record_drift": (lambda c: with_dref(c, 3, _dref(policy_record_digest=_DIGEST_A)),
                         "policy_record_digest diverges"),
        # 8 feedback target-type mismatch
        "feedback_type": (lambda c: _set(c, 5, "target_event_type",
                                         "CHANGEGATE_EVALUATION_COMPLETED"),
                          "target_event_type"),
        # 9 completion referencing another task's attempt
        "completion_foreign_task": (lambda c: with_dref(c, 2, foreign_task),
                                    "task_ref"),
        # 10 completion referencing another candidate's attempt
        "completion_foreign_candidate": (lambda c: with_dref(c, 2, foreign_cand),
                                        "candidate_digest diverges"),
        # 11 rollback referencing another task/candidate's merge
        "rollback_foreign": (lambda c: with_dref(c, 4, foreign_task), "task_ref"),
        # 12 feedback referencing another task
        "feedback_foreign_task": (lambda c: with_dref(c, 5, foreign_task), "task_ref"),
        # 13 feedback referencing another candidate
        "feedback_foreign_candidate": (lambda c: with_dref(c, 5, foreign_cand),
                                      "candidate_digest diverges"),
    }
    for name, (mutate, expected) in controls.items():
        errors = validate_event_chain(mutate(copy.deepcopy(chain)))
        assert any(expected in e for e in errors), f"{name} not detected: {errors}"

    # 14 locally valid but disconnected event.
    disconnected = copy.deepcopy(chain)
    del disconnected[1]["evaluation_event_ref"]
    assert any("disconnected" in e for e in validate_event_chain(disconnected))

    # 15 changed candidate continuing the old chain without a new evaluation event.
    changed_candidate = copy.deepcopy(chain)
    changed_candidate[2]["decision_ref"] = foreign_cand
    assert any("candidate_digest diverges" in e
               for e in validate_event_chain(changed_candidate))

    # 16 override mixing the old decision digest with new input/record digests.
    override_event = {
        **_base_envelope("CHANGEGATE_REVIEW_OVERRIDDEN"), "event_id": "evt-override-1",
        "decision_ref": _DECISION_REF, "evaluation_event_ref": "evt-eval-1",
        "override": {"actor_ref": "owner-1", "reason_code": "SCOPE_EXCEPTION",
                     "new_decision_digest": _DIGEST_B, "new_input_digest": None,
                     "new_policy_record_digest": None, "exception_ref": None,
                     "expires_at": None},
    }
    mixed_chain = [chain[0], override_event]
    assert any("incomplete replacement" in e for e in validate_event_chain(mixed_chain))


def test_override_switches_active_decision_lineage():
    """A complete replacement decision switches the active lineage; a subsequent event
    matching the REPLACEMENT (not the original) validates, and one matching the original
    afterwards fails."""
    new_decision = canonical_digest({"probe": "replacement-decision"})
    new_input = canonical_digest({"probe": "replacement-input"})
    new_record = canonical_digest({"probe": "replacement-record"})
    replacement_dref = _dref(decision_digest=new_decision, input_digest=new_input,
                             policy_record_digest=new_record)

    def env(event_id, event_type, **extra):
        return {**_base_envelope(event_type), "event_id": event_id, **extra}

    override = env("evt-override-1", "CHANGEGATE_REVIEW_OVERRIDDEN",
                   decision_ref=_DECISION_REF, evaluation_event_ref="evt-eval-1",
                   override={"actor_ref": "owner-1", "reason_code": "SCOPE_EXCEPTION",
                             "new_decision_digest": new_decision,
                             "new_input_digest": new_input,
                             "new_policy_record_digest": new_record,
                             "exception_ref": None, "expires_at": None})
    good_attempt = env("evt-attempt-1", "CHANGEGATE_MERGE_ATTEMPTED",
                       decision_ref=replacement_dref, evaluation_event_ref="evt-eval-1",
                       outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"})
    stale_attempt = env("evt-attempt-2", "CHANGEGATE_MERGE_ATTEMPTED",
                        decision_ref=_DECISION_REF, evaluation_event_ref="evt-eval-1",
                        outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"})
    evaluation = {**_base_envelope("CHANGEGATE_EVALUATION_COMPLETED"),
                  "event_id": "evt-eval-1",
                  **_POSITIVE_EXTRAS["CHANGEGATE_EVALUATION_COMPLETED"]}
    validator = _validator()
    for e in (evaluation, override, good_attempt):
        assert not list(validator.iter_errors(e)), e["event_id"]
    assert validate_event_chain([evaluation, override, good_attempt]) == []
    stale_errors = validate_event_chain([evaluation, override, stale_attempt])
    assert any("decision_digest diverges" in e for e in stale_errors)


def _set(chain: list[dict], idx: int, key: str, value) -> list[dict]:
    chain[idx][key] = value
    return chain


# ---------------------------------------------------------------------------
# Privacy: enforcement matches the claim (M-R1-03)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,value", [
    ("traversal", "x/../../etc/passwd"),
    ("dotdot", "cand..1"),
    ("url", "https://example.com/path"),
    ("url scheme only", "file:///etc/shadow"),
    ("path separator", "a/b/c"),
    ("multiline", "line1\nline2"),
    ("trailing newline", "cand-1\n"),
    ("trailing tab", "cand-1\t"),
    ("whitespace", "cand 1"),
    ("diff-like", "a/foo.py:b/foo.py"),
    ("github token", "ghp_" + "A" * 36),
    ("aws key", "AKIA" + "B" * 16),
    ("slack token", "xoxb-1234567890"),
    ("openai key", "sk-" + "c" * 32),
    ("jwt", "eyJhbGciOiJIUzI1NiJ9"),
    ("overlong", "x" * 200),
])
def test_opaque_reference_grammar_rejects_content_bearing_values(label, value):
    validator = _validator()
    instance = {
        **_base_envelope("CHANGEGATE_MERGE_ATTEMPTED"),
        "decision_ref": _DECISION_REF, "evaluation_event_ref": "evt-eval-1",
        "outcome": _OUTCOME,
        "subject_ref": {"namespace": "changegate", "kind": "git_candidate",
                        "value": value},
    }
    assert not _is_valid(validator, instance), f"{label} accepted in subject_ref.value"


def test_legitimate_tomtit_identifiers_remain_representable():
    """The narrow grammar must not break current TOMTIT task/project/run/evidence ids."""
    validator = _validator()
    for task_id in ("p0-9b1", "BH-P0-A", "changegate-slice1a-demo", "task.v2_1"):
        instance = {
            **_base_envelope("CHANGEGATE_MERGE_ATTEMPTED"),
            "task_ref": task_id, "run_ref": "run-01hxyz", "project_ref": "tomtit-agent",
            "decision_ref": _DECISION_REF, "evaluation_event_ref": "evt-eval-1",
            "outcome": _OUTCOME,
            "evidence_refs": [{"evidence_id": "pytest-focused-1",
                               "requirement_id": "req-pytest-full", "digest": None}],
        }
        errors = list(validator.iter_errors(instance))
        assert not errors, f"legitimate id {task_id!r} rejected: {errors[0].message}"


def test_structured_values_use_dedicated_fields():
    schema = _schema()
    subject = schema["properties"]["subject_ref"]["properties"]
    assert "commit_sha" in subject, "a Git commit needs its own field"
    assert subject["kind"]["enum"], "subject kind must be a closed machine enum"
    outcome = schema["properties"]["outcome"]["properties"]
    assert "resulting_commit_sha" in outcome
    assert schema["$defs"]["gitCommitSha"]["allOf"][0]["pattern"] == (
        r"^([0-9a-f]{40}|[0-9a-f]{64})$"
    )


def test_privacy_claim_is_scoped_to_what_the_schema_enforces():
    """The schema must NOT claim it can identify every secret; it must document the split
    between schema-level shape control and application-sink redaction/scanning."""
    schema = _schema()
    description = schema["description"]
    assert "SCOPE LIMIT" in description
    assert "not" in description.lower() and "secret scanner" in description.lower()
    assert "application-sink" in description.lower() or "sink" in description.lower()


def test_event_schema_defines_no_raw_content_fields():
    schema = _schema()
    forbidden_fragments = (
        "prompt", "stdout", "stderr", "source_code", "file_content",
        "credential", "secret", "private_key", "command_output", "token",
        "policy_mutation",
    )

    def property_names(node: object) -> list[str]:
        names: list[str] = []
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties" and isinstance(value, dict):
                    names.extend(value.keys())
                names.extend(property_names(value))
        elif isinstance(node, list):
            for item in node:
                names.extend(property_names(item))
        return names

    for name in property_names(schema):
        for fragment in forbidden_fragments:
            assert fragment not in name.lower(), (
                f"event schema defines a raw-content field {name!r}"
            )


def test_no_artifact_contains_secret_material():
    for path in (FIXTURE_PATH, SCHEMA_PATH, SPEC_PATH):
        content = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            # The schema legitimately names these prefixes in its credential deny-list.
            if path is SCHEMA_PATH:
                continue
            assert not pattern.search(content), (
                f"{path.name} matches secret pattern {pattern.pattern!r}"
            )


# ---------------------------------------------------------------------------
# Golden fixture — structure, taxonomy, independent precedence, coverage
# ---------------------------------------------------------------------------

def test_golden_fixture_is_valid_json_with_version_and_status():
    suite = _fixture()
    assert suite["schema_version"] == "changegate-merge-eligibility-golden.v4"
    assert suite["status"] == "DRAFT_FOR_OWNER_REVIEW"
    assert suite["policy_spec"] == (
        "docs/strategy/CHANGEGATE_VERTICAL_MVP_SLICE_1_POLICY_SPEC.md"
    )
    assert list(suite["dispositions"]) == list(DISPOSITIONS)
    assert list(suite["decision_authorities"]) == list(AUTHORITIES)
    assert suite["precedence_status"] == "DRAFT_PENDING_OD_S1A_007"
    assert list(suite["owner_decisions"]) == list(OD_S1A_IDS)


def test_golden_fixture_case_ids_are_unique_and_at_least_25_cases():
    cases = _fixture()["cases"]
    assert len(cases) >= 25, f"expected >= 25 golden cases, found {len(cases)}"
    ids = [c["case_id"] for c in cases]
    assert len(set(ids)) == len(ids), "duplicate case_id in golden fixture"


def test_independent_draft_precedence_table_matches_fixture_and_spec():
    """M-R1-01: the rank table is pinned HERE, independently of fixture content. A
    coordinated rank change in the fixture (even with expectations recomputed) fails."""
    suite = _fixture()
    fixture_ranks = {e["code"]: e["precedence_rank"] for e in suite["reason_codes"]}
    assert fixture_ranks == DRAFT_PRECEDENCE_PENDING_OD_S1A_007, (
        "fixture taxonomy ranks diverge from the independently pinned draft table; a "
        "precedence change requires an owner-acceptance patch to spec + fixture + tests"
    )
    fixture_dispositions = {
        e["code"]: e["default_disposition"] for e in suite["reason_codes"]
    }
    assert fixture_dispositions == DRAFT_DISPOSITION_BY_CODE
    # The spec's §9 table must carry the same ranks for the same codes.
    spec_text = _spec_text()
    for code, rank in DRAFT_PRECEDENCE_PENDING_OD_S1A_007.items():
        assert re.search(rf"^\| {rank} \| `{code}` \|", spec_text, re.MULTILINE), (
            f"spec §9 does not rank {code} at {rank}"
        )


def test_independent_load_bearing_semantics_are_pinned():
    assert DRAFT_DISPOSITION_BY_CODE["AUTHORITY_INVALID"] == "BLOCK"
    assert DRAFT_DISPOSITION_BY_CODE["SCOPE_UNCERTAIN"] == "REVIEW_REQUIRED"
    # BLOCK dominates REVIEW_REQUIRED.
    mixed_case = _case("GC-S1-033")
    mixed = oracle_decision(
        mixed_case["policy_input_facts"], _fixture()["fact_state_mapping"],
        case_mode(mixed_case),
    )
    assert set(mixed["complete"]) == {"RELEASE_STATE_NOT_CLEAN", "SCOPE_UNCERTAIN"}
    assert mixed["disposition"] == "BLOCK"
    # SHADOW is ADVISORY_ONLY.
    shadow_case = _case("GC-S1-031")
    shadow = oracle_decision(
        shadow_case["policy_input_facts"], _fixture()["fact_state_mapping"],
        case_mode(shadow_case),
    )
    assert shadow["authority"] == "ADVISORY_ONLY"


def test_coordinated_precedence_drift_is_detected():
    """Swap two integrity ranks in a fixture COPY and recompute the expected primaries
    consistently — exactly the mutation that slipped past R1. The independent rank
    assertion must still fail."""
    suite = copy.deepcopy(_fixture())
    by_code = {e["code"]: e for e in suite["reason_codes"]}
    a, b = by_code["AUTHORITY_INVALID"], by_code["EVIDENCE_TASK_MISMATCH"]
    a["precedence_rank"], b["precedence_rank"] = b["precedence_rank"], a["precedence_rank"]
    mutated_ranks = {e["code"]: e["precedence_rank"] for e in suite["reason_codes"]}
    # A fixture-internal-consistency check would still pass, because expectations can be
    # recomputed from the mutated table:
    for c in suite["cases"]:
        codes = c["expected_complete_reason_codes"]
        if codes:
            c["expected_primary_reason"] = min(codes, key=lambda x: mutated_ranks[x])
    assert all(
        not c["expected_complete_reason_codes"]
        or c["expected_primary_reason"] == min(
            c["expected_complete_reason_codes"], key=lambda x: mutated_ranks[x]
        )
        for c in suite["cases"]
    )
    # ...but the independent table pin catches it.
    assert mutated_ranks != DRAFT_PRECEDENCE_PENDING_OD_S1A_007
    gc40 = next(c for c in suite["cases"] if c["case_id"] == "GC-S1-040")
    assert gc40["expected_primary_reason"] == "EVIDENCE_TASK_MISMATCH"  # silently flipped
    real = _case("GC-S1-040")
    assert real["expected_primary_reason"] == "AUTHORITY_INVALID"


def test_every_declared_fact_state_is_mapped_and_totality_holds():
    suite = _fixture()
    mapping = suite["fact_state_mapping"]
    taxonomy_codes = set(DRAFT_PRECEDENCE_PENDING_OD_S1A_007)
    assert {e["code"] for e in suite["reason_codes"]} == taxonomy_codes
    assert set(mapping["enum_facts"]) == set(ENUM_FACT_VALUES)
    for fact, values in ENUM_FACT_VALUES.items():
        table = mapping["enum_facts"][fact]
        assert set(table) == set(values), f"{fact}: mapped states != declared states"
        for value, code in table.items():
            assert code is None or code in taxonomy_codes, f"{fact}={value} -> {code}"
    assert set(mapping["violation_tag_reasons"]) == set(VIOLATION_TAGS)
    for tag, code in mapping["violation_tag_reasons"].items():
        assert code in taxonomy_codes
    assert set(mapping["set_facts"]) == set(SET_FACTS)
    for set_fact, code in mapping["set_facts"].items():
        assert code is None or code in taxonomy_codes
    for identity in VERIFIER_IDENTITY_VALUES:
        for independence in VERIFIER_INDEPENDENCE_VALUES:
            matched = any(
                identity in rule["identity"]
                and (rule["independence"] == "*"
                     or independence in rule["independence"])
                for rule in mapping["verifier_rule"]
            )
            assert matched, f"verifier rule not total: {identity}/{independence}"
    assert mapping["decision_authority_by_mode"] == {
        "ENFORCE": "AUTHORITATIVE", "SHADOW": "ADVISORY_ONLY",
    }


def test_every_case_declares_the_complete_fact_set_and_valid_expectations():
    for c in _fixture()["cases"]:
        cid = c["case_id"]
        facts = c["policy_input_facts"]
        for fact, values in ENUM_FACT_VALUES.items():
            assert facts.get(fact) in values, f"{cid}: bad {fact}={facts.get(fact)!r}"
        assert facts["verifier_identity_status"] in VERIFIER_IDENTITY_VALUES, cid
        assert facts["verifier_independence_status"] in VERIFIER_INDEPENDENCE_VALUES, cid
        for set_fact in SET_FACTS:
            assert isinstance(facts.get(set_fact), list), f"{cid}: {set_fact}"
        for tag in facts["evidence_context_violations"]:
            assert tag in VIOLATION_TAGS, f"{cid}: unknown violation tag {tag}"
        assert c["expected_disposition"] in DISPOSITIONS, cid
        assert c["expected_decision_authority"] in AUTHORITIES, cid
        assert isinstance(c["expected_event_assertions"], dict), cid
        assert isinstance(c["owner_decisions_pending"], list), cid
        assert c["summary"].strip(), cid
        for code in c["expected_complete_reason_codes"]:
            assert REASON_CODE_RE.match(code), f"{cid}: {code!r}"
        for field in SOURCE_DIGEST_FIELDS + ("task_id", "policy_version",
                                             "evaluator_version"):
            assert field in c["policy_input_bindings"], f"{cid}: missing {field}"


# ---------------------------------------------------------------------------
# Identifier namespaces (M-R1-02)
# ---------------------------------------------------------------------------

def test_identifier_universes_are_declared_and_disjoint():
    suite = _fixture()
    top = suite["identifier_universes"]
    assert not set(top["requirement_id_universe"]) & set(top["evidence_record_id_universe"])
    for c in suite["cases"]:
        cid = c["case_id"]
        universes = c["identifier_universes"]
        req_u = set(universes["requirement_id_universe"])
        ev_u = set(universes["evidence_record_id_universe"])
        assert req_u and ev_u, cid
        assert not (req_u & ev_u), f"{cid}: identifier universes overlap"
        facts = c["policy_input_facts"]
        for set_name in REQUIREMENT_SETS:
            assert set(facts[set_name]) <= req_u, (
                f"{cid}: {set_name} escapes the requirement-id universe"
            )
        for set_name in EVIDENCE_RECORD_SETS:
            assert set(facts[set_name]) <= ev_u, (
                f"{cid}: {set_name} escapes the evidence-record-id universe"
            )


def test_disjoint_evidence_accounting_invariants_hold_per_case():
    for c in _fixture()["cases"]:
        cid = c["case_id"]
        f = c["policy_input_facts"]
        required = set(f["required_requirement_ids"])
        satisfied = set(f["satisfied_requirement_ids"])
        invalid = set(f["invalid_requirement_ids"])
        missing = set(f["missing_requirement_ids"])
        assert required == satisfied | invalid | missing, f"{cid}: partition broken"
        assert not (satisfied & invalid) and not (satisfied & missing), cid
        assert not (invalid & missing), cid
        assert set(f["invalid_provenance_evidence_ids"]) <= set(
            f["rejected_evidence_ids"]
        ), f"{cid}: invalid-provenance ids must be rejected record ids"
        assert (f["evidence_context_status"] == "INCOHERENT") == bool(
            f["evidence_context_violations"]
        ), cid


def _namespace_errors(case: dict) -> list[str]:
    """The namespace rule, applied to one case (used by the mutation tests)."""
    errors: list[str] = []
    req_u = set(case["identifier_universes"]["requirement_id_universe"])
    ev_u = set(case["identifier_universes"]["evidence_record_id_universe"])
    facts = case["policy_input_facts"]
    if req_u & ev_u:
        errors.append("universes overlap")
    for set_name in REQUIREMENT_SETS:
        stray = set(facts[set_name]) - req_u
        if stray:
            errors.append(f"{set_name} contains non-requirement ids {sorted(stray)}")
    for set_name in EVIDENCE_RECORD_SETS:
        stray = set(facts[set_name]) - ev_u
        if stray:
            errors.append(f"{set_name} contains non-record ids {sorted(stray)}")
    return errors


def test_requirement_id_in_an_evidence_record_set_is_detected():
    mutated = _case("GC-S1-001")
    mutated["policy_input_facts"]["rejected_evidence_ids"] = ["req-pytest-full"]
    errors = _namespace_errors(mutated)
    assert any("rejected_evidence_ids" in e for e in errors), errors


def test_evidence_record_id_in_a_requirement_set_is_detected():
    mutated = _case("GC-S1-026")
    facts = mutated["policy_input_facts"]
    facts["required_requirement_ids"] = sorted(
        facts["required_requirement_ids"] + ["ev-pytest-try1"]
    )
    facts["missing_requirement_ids"] = ["ev-pytest-try1"]
    errors = _namespace_errors(mutated)
    assert any("required_requirement_ids" in e for e in errors), errors
    assert any("missing_requirement_ids" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Independent semantic oracle + mutation negatives
# ---------------------------------------------------------------------------

def test_oracle_derives_every_case_expectation_from_facts_alone():
    suite = _fixture()
    mapping = suite["fact_state_mapping"]
    for c in suite["cases"]:
        cid = c["case_id"]
        derived = oracle_decision(c["policy_input_facts"], mapping, case_mode(c))
        assert derived["complete"] == c["expected_complete_reason_codes"], (
            f"{cid}: oracle derived {derived['complete']} from facts, fixture expects "
            f"{c['expected_complete_reason_codes']}"
        )
        assert derived["primary"] == c["expected_primary_reason"], cid
        assert derived["disposition"] == c["expected_disposition"], cid
        assert derived["authority"] == c["expected_decision_authority"], cid


def test_oracle_is_total_over_every_single_fact_deviation():
    suite = _fixture()
    mapping = suite["fact_state_mapping"]
    green = _case("GC-S1-001")["policy_input_facts"]
    for mode in EVALUATION_MODES:
        for fact, values in ENUM_FACT_VALUES.items():
            for value in values:
                facts = copy.deepcopy(green)
                facts[fact] = value
                if fact == "evidence_context_status" and value == "INCOHERENT":
                    facts["evidence_context_violations"] = ["TASK_MISMATCH"]
                assert oracle_decision(facts, mapping, mode)["disposition"] in DISPOSITIONS
        for identity in VERIFIER_IDENTITY_VALUES:
            for independence in VERIFIER_INDEPENDENCE_VALUES:
                facts = copy.deepcopy(green)
                facts["verifier_identity_status"] = identity
                facts["verifier_independence_status"] = independence
                assert oracle_decision(facts, mapping, mode)["disposition"] in DISPOSITIONS


def _oracle_for(case: dict) -> dict:
    return oracle_decision(
        case["policy_input_facts"], _fixture()["fact_state_mapping"], case_mode(case)
    )


def test_mutation_dirty_repository_on_eligible_case_is_detected():
    mutated = _case("GC-S1-001")
    mutated["policy_input_facts"]["repository_release_clean"] = "DIRTY"
    derived = _oracle_for(mutated)
    assert derived["complete"] != mutated["expected_complete_reason_codes"]
    assert derived["disposition"] == "BLOCK" != mutated["expected_disposition"]


def test_mutation_scope_compliant_to_violation_is_detected():
    mutated = _case("GC-S1-001")
    mutated["policy_input_facts"]["scope_status"] = "VIOLATION"
    derived = _oracle_for(mutated)
    assert "SCOPE_VIOLATION" in derived["complete"]
    assert derived["complete"] != mutated["expected_complete_reason_codes"]


def test_mutation_removing_mandatory_satisfied_requirement_is_detected():
    mutated = _case("GC-S1-001")
    facts = mutated["policy_input_facts"]
    facts["satisfied_requirement_ids"] = ["req-compileall"]
    facts["missing_requirement_ids"] = ["req-pytest-full"]
    derived = _oracle_for(mutated)
    assert "REQUIRED_EVIDENCE_MISSING" in derived["complete"]
    assert derived["disposition"] != mutated["expected_disposition"]


def test_mutation_enforce_to_shadow_without_authority_change_is_detected():
    # evaluation_mode is single-sourced in bindings (R3), not facts.
    mutated = _case("GC-S1-001")
    assert "evaluation_mode" not in mutated["policy_input_facts"]
    mutated["policy_input_bindings"]["evaluation_mode"] = "SHADOW"
    derived = _oracle_for(mutated)
    assert derived["authority"] == "ADVISORY_ONLY"
    assert derived["authority"] != mutated["expected_decision_authority"]


def test_mutation_adding_invalid_provenance_without_expected_reason_is_detected():
    mutated = _case("GC-S1-001")
    facts = mutated["policy_input_facts"]
    facts["rejected_evidence_ids"] = ["ev-pytest-forged"]
    facts["invalid_provenance_evidence_ids"] = ["ev-pytest-forged"]
    derived = _oracle_for(mutated)
    assert "EVIDENCE_PROVENANCE_INVALID" in derived["complete"]
    assert derived["complete"] != mutated["expected_complete_reason_codes"]


# ---------------------------------------------------------------------------
# Replay identity — the ten §18.5 invariants (R3: also covers policy_record_digest)
# ---------------------------------------------------------------------------

def _green() -> tuple[dict, dict, dict]:
    case = _case("GC-S1-001")
    return (case["policy_input_bindings"], case["policy_input_facts"],
            _fixture()["fact_state_mapping"])


def _digests(bindings, facts, mapping):
    record = build_policy_record(bindings, facts, mapping)
    return record["decision_digest"], record["policy_record_digest"]


def test_replay_1_2_same_input_same_decision_and_record_digests():
    bindings, facts, mapping = _green()
    d1, r1 = _digests(bindings, facts, mapping)
    d2, r2 = _digests(bindings, facts, mapping)
    assert d1 == d2 and r1 == r2
    assert CANONICAL_DIGEST_RE.match(d1) and CANONICAL_DIGEST_RE.match(r1)


def test_replay_3_4_trace_and_privacy_metadata_never_change_decision_or_record():
    bindings, facts, mapping = _green()
    d0, r0 = _digests(bindings, facts, mapping)
    record = build_policy_record(bindings, facts, mapping)
    trace_a = build_trace_envelope(record, _trace_meta(
        trace_id="t-a", evaluation_id="e-a", request_id="q-a",
        occurred_at="2026-07-15T00:00:00Z", evaluation_latency_ms=3,
        redaction_classification="INTERNAL"))
    trace_b = build_trace_envelope(record, _trace_meta(
        trace_id="t-b", evaluation_id="e-b", request_id="q-b",
        occurred_at="2026-07-15T09:30:00Z", evaluation_latency_ms=4210,
        redaction_classification="SENSITIVE"))
    # decision & record identity unchanged; trace identity differs.
    assert trace_a["decision_digest"] == trace_b["decision_digest"] == d0
    assert trace_a["policy_record_digest"] == trace_b["policy_record_digest"] == r0
    assert trace_a["trace_digest"] != trace_b["trace_digest"]
    assert validate_trace_envelope(trace_a) == []
    assert validate_trace_envelope(trace_b) == []


@pytest.mark.parametrize("field", [
    "repository_snapshot_digest", "verification_bundle_digest", "approval_digest",
    "authority_binding_digest", "verifier_binding_digest", "task_contract_digest",
    "candidate_digest", "policy_digest",
])
def test_replay_5_to_8_every_source_digest_changes_decision_and_record(field):
    bindings, facts, mapping = _green()
    d0, r0 = _digests(bindings, facts, mapping)
    changed = {**bindings, field: canonical_digest({"probe": f"different-{field}"})}
    d1, r1 = _digests(changed, facts, mapping)
    assert d1 != d0 and r1 != r0, f"{field} does not affect decision/record identity"


def test_replay_7_no_approval_sentinel_changes_decision_and_record():
    bindings, facts, mapping = _green()
    d0, r0 = _digests(bindings, facts, mapping)
    without = {**bindings, "approval_digest": NO_APPROVAL_SENTINEL}
    d1, r1 = _digests(without, facts, mapping)
    assert d1 != d0 and r1 != r0


@pytest.mark.parametrize("field", ["policy_version", "evaluator_version",
                                   "evaluation_mode"])
def test_replay_9_version_and_mode_changes_change_decision_and_record(field):
    bindings, facts, mapping = _green()
    d0, r0 = _digests(bindings, facts, mapping)
    new = "SHADOW" if field == "evaluation_mode" else bindings[field] + "-next"
    changed = {**bindings, field: new}
    d1, r1 = _digests(changed, facts, mapping)
    assert d1 != d0 and r1 != r0


def test_replay_policy_fact_change_changes_decision_and_record():
    bindings, facts, mapping = _green()
    d0, r0 = _digests(bindings, facts, mapping)
    dirty = copy.deepcopy(facts)
    dirty["repository_release_clean"] = "DIRTY"
    d1, r1 = _digests(bindings, dirty, mapping)
    assert d1 != d0 and r1 != r0


def test_replay_10_trace_metadata_change_changes_only_the_trace_digest():
    bindings, facts, mapping = _green()
    record = build_policy_record(bindings, facts, mapping)
    trace_a = build_trace_envelope(record, _trace_meta(evaluation_latency_ms=1))
    trace_b = build_trace_envelope(record, _trace_meta(evaluation_latency_ms=900))
    assert trace_a["trace_digest"] != trace_b["trace_digest"]
    assert trace_a["decision_digest"] == trace_b["decision_digest"]
    assert trace_a["policy_record_digest"] == trace_b["policy_record_digest"]


# ---------------------------------------------------------------------------
# Single-source evaluation_mode (H-R2V-01)
# ---------------------------------------------------------------------------

def test_evaluation_mode_is_single_sourced_in_bindings_not_facts():
    suite = _fixture()
    assert "evaluation_mode" not in suite["fact_state_mapping"]["enum_facts"]
    for c in suite["cases"]:
        assert "evaluation_mode" not in c["policy_input_facts"], c["case_id"]
        assert c["policy_input_bindings"]["evaluation_mode"] in EVALUATION_MODES
    # The A2 input payload draws the mode from bindings; a facts-level copy is impossible
    # (a2_input_payload asserts facts carry no mode).
    bindings, facts, _ = _green()
    a2_input_payload(bindings, facts)  # must not raise
    facts_with_mode = {**facts, "evaluation_mode": "SHADOW"}
    with pytest.raises(AssertionError):
        a2_input_payload(bindings, facts_with_mode)
    # spec forbids a second facts-level mode.
    text = _spec_text()
    assert "evaluation_mode` is NOT an eligibility fact" in text
    assert "single source" in text


# ---------------------------------------------------------------------------
# PolicyEvaluationRecord consistency (H-R2V-02)
# ---------------------------------------------------------------------------

def test_policy_record_is_self_consistent_and_reproducible_from_input():
    bindings, facts, mapping = _green()
    record = build_policy_record(bindings, facts, mapping)
    # independent validator: recompute digest + structural checks.
    assert validate_policy_record(record) == []
    # reproducible from the input alone (no application metadata).
    again = build_policy_record(bindings, facts, mapping)
    assert record == again
    assert "redaction_classification" not in record
    # record ↔ decision consistency.
    assert record["input_digest"] == input_digest_oracle(bindings, facts)
    assert record["decision_digest"] == decision_digest_oracle(bindings, facts, mapping)
    for field in SOURCE_DIGEST_FIELDS:
        assert record[field] == bindings[field]
    outcome = oracle_decision(facts, mapping, bindings["evaluation_mode"])
    assert record["disposition"] == outcome["disposition"]
    assert record["decision_authority"] == outcome["authority"]
    assert record["complete_reason_codes"] == outcome["complete"]


def test_policy_record_field_mutation_invalidates_its_digest():
    bindings, facts, mapping = _green()
    record = build_policy_record(bindings, facts, mapping)
    for mutation in (
        {"disposition": "BLOCK"},
        {"decision_authority": "ADVISORY_ONLY"},
        {"repository_snapshot_digest": canonical_digest({"x": "other"})},
        {"complete_reason_codes": ["RELEASE_STATE_NOT_CLEAN"]},
        {"decision_digest": _DIGEST_A},
    ):
        tampered = {**record, **mutation}
        assert validate_policy_record(tampered), f"mutation {mutation} not detected"


def test_matching_golden_case_facts_reproduce_a_valid_record_for_every_case():
    suite = _fixture()
    mapping = suite["fact_state_mapping"]
    for c in suite["cases"]:
        record = build_policy_record(
            c["policy_input_bindings"], c["policy_input_facts"], mapping
        )
        assert validate_policy_record(record) == [], c["case_id"]
        assert record["disposition"] == c["expected_disposition"], c["case_id"]
        assert record["decision_authority"] == c["expected_decision_authority"], c["case_id"]


# ---------------------------------------------------------------------------
# Trace envelope consistency + the ten §18.4 negative controls (H-R2V-02)
# ---------------------------------------------------------------------------

def test_trace_envelope_positive_is_consistent():
    bindings, facts, mapping = _green()
    record = build_policy_record(bindings, facts, mapping)
    trace = build_trace_envelope(record, _trace_meta())
    assert validate_trace_envelope(trace) == []
    assert trace["policy_record"] == record
    assert trace["input_digest"] == record["input_digest"]
    assert trace["decision_digest"] == record["decision_digest"]


def test_trace_envelope_negative_controls_are_all_detected():
    bindings, facts, mapping = _green()
    record = build_policy_record(bindings, facts, mapping)
    other = build_policy_record(
        _case("GC-S1-010")["policy_input_bindings"],
        _case("GC-S1-010")["policy_input_facts"], mapping)
    other_task = build_policy_record(
        {**bindings, "task_id": "other-task"}, facts, mapping)
    other_candidate = build_policy_record(
        {**bindings, "candidate_digest": canonical_digest({"x": "other-cand"})},
        facts, mapping)

    def tampered(**overrides) -> dict:
        return {**build_trace_envelope(record, _trace_meta()), **overrides}

    def tampered_record(**record_overrides) -> dict:
        trace = build_trace_envelope(record, _trace_meta())
        trace["policy_record"] = {**record, **record_overrides}
        return trace

    controls = {
        # 1 mismatched top-level decision digest
        "decision": tampered(decision_digest=_DIGEST_A),
        # 2 mismatched top-level input digest
        "input": tampered(input_digest=_DIGEST_A),
        # 3 mismatched top-level policy-record digest
        "record_digest": tampered(policy_record_digest=_DIGEST_A),
        # 4 changed source digest inside record without record-digest update
        "source_in_record": tampered_record(
            repository_snapshot_digest=canonical_digest({"x": "z"})),
        # 5 changed disposition inside record
        "disposition": tampered_record(disposition="BLOCK"),
        # 6 changed complete reason set inside record
        "reasons": tampered_record(complete_reason_codes=["SCOPE_VIOLATION"]),
        # 7 changed authority inside record
        "authority": tampered_record(decision_authority="ADVISORY_ONLY"),
        # 8 trace digest not recomputed after a metadata change
        "stale_trace": tampered(occurred_at="2030-01-01T00:00:00Z"),
        # 9 embedded record from another task
        "foreign_task": tampered(policy_record=other_task),
        # 10 embedded record from another candidate
        "foreign_candidate": tampered(policy_record=other_candidate),
        # (bonus) wholesale swap for another case's record
        "wholesale_swap": tampered(policy_record=other),
    }
    for name, trace in controls.items():
        assert validate_trace_envelope(trace), f"control {name} not detected"


# ---------------------------------------------------------------------------
# Coverage: reason codes, owner decisions, policy boundaries
# ---------------------------------------------------------------------------

def test_every_reason_code_is_covered_by_at_least_one_case():
    used = {
        code for c in _fixture()["cases"]
        for code in c["expected_complete_reason_codes"]
    }
    uncovered = sorted(set(DRAFT_PRECEDENCE_PENDING_OD_S1A_007) - used)
    assert not uncovered, f"reason codes with no golden coverage: {uncovered}"


def test_every_owner_decision_point_has_a_marked_case():
    suite = _fixture()
    marked = {od for c in suite["cases"] for od in c["owner_decisions_pending"]}
    missing = sorted(set(OD_S1A_IDS) - marked)
    assert not missing, f"OD-S1A decisions with no marked golden case: {missing}"
    gc21 = next(c for c in suite["cases"] if c["case_id"] == "GC-S1-021")
    assert "OD-S1A-007" in gc21["owner_decisions_pending"]
    spec_text = _spec_text()
    for od in marked:
        assert re.match(r"^OD-S1A-\d{3}$", od), od
        assert od in spec_text, f"{od} is marked in the fixture but not in the spec"


def test_requirement_declaration_mapping_case_is_external_to_a2():
    """OD-S1A-008: requirement ids are declared (A3), never inferred from display
    strings; A2's decision is unaffected."""
    case = _case("GC-S1-041")
    assert "OD-S1A-008" in case["owner_decisions_pending"]
    assertions = case["expected_event_assertions"]
    assert assertions["requirement_ids_derived_from_display_strings"] is False
    assert assertions["requirement_declaration_source"] == "A3_REQUIREMENT_DECLARATION_SET"
    # Same facts as the green case ⇒ same decision: the mapping is outside A2.
    green = _case("GC-S1-001")
    assert case["expected_disposition"] == green["expected_disposition"]
    assert case["expected_complete_reason_codes"] == []


def test_all_three_dispositions_and_both_authorities_are_covered():
    cases = _fixture()["cases"]
    assert {c["expected_disposition"] for c in cases} == set(DISPOSITIONS)
    assert {c["expected_decision_authority"] for c in cases} == set(AUTHORITIES)


def _cases_by_tag(tag: str) -> list[dict]:
    return [c for c in _fixture()["cases"] if tag in c.get("tags", [])]


def test_empty_mandatory_bundle_case_exists():
    cases = _cases_by_tag("empty_bundle_with_requirements")
    assert cases
    for c in cases:
        facts = c["policy_input_facts"]
        assert facts["required_requirement_ids"]
        assert facts["satisfied_requirement_ids"] == []
        assert c["expected_disposition"] == "BLOCK"
        assert c["expected_primary_reason"] == "REQUIRED_EVIDENCE_MISSING"


def test_no_requirement_empty_bundle_case_exists_and_is_not_blocked_for_emptiness():
    cases = _cases_by_tag("no_requirement_empty_bundle")
    assert cases
    for c in cases:
        facts = c["policy_input_facts"]
        assert facts["required_requirement_ids"] == []
        assert facts["satisfied_requirement_ids"] == []
        assert c["expected_disposition"] != "BLOCK"


def test_structural_verified_with_dirty_repository_case_exists():
    cases = _cases_by_tag("structural_verified_dirty_repository")
    assert cases
    for c in cases:
        facts = c["policy_input_facts"]
        assert facts["repository_release_clean"] == "DIRTY"
        assert set(facts["required_requirement_ids"]) <= set(
            facts["satisfied_requirement_ids"]
        )
        assert c["expected_disposition"] == "BLOCK"
        assert c["expected_primary_reason"] == "RELEASE_STATE_NOT_CLEAN"


def test_multiple_failure_and_mixed_block_review_cases_exist():
    multi = _cases_by_tag("multiple_failure_precedence")
    assert multi
    for c in multi:
        assert len(c["expected_complete_reason_codes"]) >= 2
    mixed = _cases_by_tag("mixed_block_and_review")
    assert mixed
    for c in mixed:
        kinds = {
            DRAFT_DISPOSITION_BY_CODE[code]
            for code in c["expected_complete_reason_codes"]
        }
        assert kinds == {"BLOCK", "REVIEW_REQUIRED"}
        assert c["expected_disposition"] == "BLOCK"


def test_shadow_mode_counterfactual_cases_exist_with_advisory_authority():
    eligible = _cases_by_tag("shadow_eligible_counterfactual")
    blocked = _cases_by_tag("shadow_block_counterfactual")
    assert eligible and blocked
    for c in eligible + blocked:
        assert "evaluation_mode" not in c["policy_input_facts"]
        assert case_mode(c) == "SHADOW"
        assert c["expected_decision_authority"] == "ADVISORY_ONLY"
    assert any(
        c["expected_disposition"] == "ELIGIBLE_TO_MERGE_UNDER_POLICY" for c in eligible
    )
    assert any(c["expected_disposition"] == "BLOCK" for c in blocked)


def test_rejected_and_provenance_boundary_cases_exist():
    rejected_only = _cases_by_tag("rejected_only_requirement")
    assert rejected_only
    for c in rejected_only:
        assert c["expected_primary_reason"] == "REQUIRED_EVIDENCE_INVALID"
        assert c["policy_input_facts"]["missing_requirement_ids"] == []
    both = _cases_by_tag("valid_and_rejected_same_requirement")
    assert both
    for c in both:
        facts = c["policy_input_facts"]
        assert facts["rejected_evidence_ids"]
        assert set(facts["required_requirement_ids"]) == set(
            facts["satisfied_requirement_ids"]
        )
        assert c["expected_disposition"] == "ELIGIBLE_TO_MERGE_UNDER_POLICY"
    corrupted = _cases_by_tag("satisfied_with_invalid_provenance")
    assert corrupted
    for c in corrupted:
        assert "EVIDENCE_PROVENANCE_INVALID" in c["expected_complete_reason_codes"]
        assert c["expected_disposition"] == "BLOCK"


def test_task_stale_scope_not_evaluated_and_verifier_identity_cases_exist():
    assert _cases_by_tag("task_context_stale")
    assert _cases_by_tag("scope_not_evaluated")
    assert _cases_by_tag("scope_semantic_uncertain")
    absent = _cases_by_tag("verifier_identity_absent")
    unattested = _cases_by_tag("verifier_identity_present_unattested")
    assert absent and unattested
    for c in absent:
        assert c["expected_primary_reason"] == "REQUIRED_CONTEXT_INCOMPLETE"
    for c in unattested:
        assert c["expected_primary_reason"] == "VERIFIER_INDEPENDENCE_UNKNOWN"
        assert c["expected_disposition"] == "REVIEW_REQUIRED"


def test_unexpected_evidence_case_is_diagnostic_only_and_pending():
    cases = _cases_by_tag("unexpected_valid_evidence")
    assert cases
    for c in cases:
        assert c["policy_input_facts"]["unexpected_evidence_ids"]
        assert c["expected_complete_reason_codes"] == []
        assert "OD-S1A-006" in c["owner_decisions_pending"]


def test_feedback_does_not_mutate_policy_case_exists():
    cases = _cases_by_tag("feedback_no_policy_mutation")
    assert cases
    for c in cases:
        assertions = c["expected_event_assertions"]
        assert "CHANGEGATE_USER_FEEDBACK_RECORDED" in assertions["emits"]
        assert assertions["active_policy_mutated"] is False
        assert assertions.get("decision_digest_unchanged") is True
        assert c["expected_disposition"] == "BLOCK"


def test_authority_boundary_case_rejects_caller_authored_decision():
    cases = _cases_by_tag("caller_authored_decision")
    assert cases
    for c in cases:
        assert c["expected_disposition"] == "BLOCK"
        assert c["expected_primary_reason"] == "AUTHORITY_INVALID"


def test_fixture_event_assertions_use_only_schema_event_types():
    schema_events = set(_schema()["properties"]["event_type"]["enum"])
    for c in _fixture()["cases"]:
        for event_type in c["expected_event_assertions"].get("emits", []):
            assert event_type in schema_events, (
                f"{c['case_id']} asserts unknown event type {event_type}"
            )


# ---------------------------------------------------------------------------
# Acceptance governance + semantic fingerprint (H-R2V-04)
# ---------------------------------------------------------------------------

_METADATA_ONLY_ALLOWED = {
    "owner_decision_status", "acceptance_record", "accepted_candidate_sha",
    "artifact_digests", "verification_report_references", "deferred_decision_register",
    "audit_metadata", "document_status",
}
_METADATA_ONLY_FORBIDDEN = {
    "disposition_semantics", "reason_code_taxonomy", "reason_precedence",
    "golden_expected_results", "replay_or_source_binding_rules", "policy_record_payload",
    "event_schema_behavior", "oracle_or_validation_logic", "production_code",
}


def semantic_fingerprint(suite: dict) -> str:
    """Deterministic fingerprint over the load-bearing semantic artifacts (§27.3). A
    metadata-only acceptance patch must preserve it; any semantic change alters it."""
    return canonical_digest({
        "kind": "changegate.slice1a.semantic-fingerprint.v1",
        "reason_code_taxonomy_and_ranks": sorted(
            (e["code"], e["precedence_rank"], e["default_disposition"])
            for e in suite["reason_codes"]
        ),
        "fact_state_mapping": suite["fact_state_mapping"],
        "golden_expected_results": [
            {
                "case_id": c["case_id"],
                "disposition": c["expected_disposition"],
                "authority": c["expected_decision_authority"],
                "primary": c["expected_primary_reason"],
                "complete": c["expected_complete_reason_codes"],
            }
            for c in sorted(suite["cases"], key=lambda c: c["case_id"])
        ],
        "decision_authority_by_mode": suite["fact_state_mapping"]["decision_authority_by_mode"],
        "identifier_universes": suite["identifier_universes"],
        "digest_representation": suite["digest_representation"],
    })


def test_acceptance_governance_declares_allowed_and_forbidden_sets():
    gov = _fixture()["acceptance_governance"]
    assert set(gov["metadata_only_allowed_changes"]) == _METADATA_ONLY_ALLOWED
    assert set(gov["metadata_only_forbidden_changes"]) == _METADATA_ONLY_FORBIDDEN
    assert gov["precedence_change_classification"] == (
        "SEMANTIC_PATCH_REQUIRES_REVERIFICATION"
    )
    # both required rules present.
    assert "merge allowed after PASS" in gov["metadata_only_rule"]
    for phrase in ("invalidated", "new implementation candidate",
                   "fresh independent adversarial verification"):
        assert phrase in gov["semantic_change_rule"]
    # spec §27 states the same governance (whitespace-normalized: phrases wrap lines).
    text = _spec_text()
    normalized = " ".join(text.split())
    assert "## 27. Acceptance Governance" in text
    assert "metadata-only acceptance patch" in text
    assert "semantic patch, not an acceptance metadata patch" in normalized
    # §10 no longer calls a precedence change a mere acceptance patch (strip blockquote
    # markers before whitespace-normalizing).
    s10_raw = text.split("## 10. Deterministic Precedence")[1].split("## 11.")[0]
    s10 = " ".join(s10_raw.replace(">", " ").split())
    assert "SEMANTIC change, not a metadata acceptance patch" in s10
    assert "invalidates the current independent verification" in s10
    assert "fresh independent adversarial reverification" in s10


def test_semantic_fingerprint_is_stable_and_reproducible():
    suite = _fixture()
    assert semantic_fingerprint(suite) == semantic_fingerprint(_fixture())
    assert CANONICAL_DIGEST_RE.match(semantic_fingerprint(suite))
    # the fingerprint components named in the spec/fixture match what we digest.
    gov = suite["acceptance_governance"]
    assert set(gov["semantic_fingerprint_components"]) == {
        "reason_code_taxonomy_and_ranks", "fact_state_mapping",
        "golden_expected_results", "decision_authority_by_mode",
        "identifier_universes", "digest_representation",
    }


def test_precedence_change_alters_the_semantic_fingerprint():
    """A metadata acceptance patch must PRESERVE the fingerprint; a precedence swap (a
    semantic change) alters it, so it can never be mislabeled as metadata-only."""
    suite = _fixture()
    baseline = semantic_fingerprint(suite)
    mutated = copy.deepcopy(suite)
    by = {e["code"]: e for e in mutated["reason_codes"]}
    by["AUTHORITY_INVALID"]["precedence_rank"], by["EVIDENCE_TASK_MISMATCH"]["precedence_rank"] = (
        by["EVIDENCE_TASK_MISMATCH"]["precedence_rank"],
        by["AUTHORITY_INVALID"]["precedence_rank"],
    )
    assert semantic_fingerprint(mutated) != baseline, (
        "a precedence swap must change the semantic fingerprint"
    )


def test_metadata_only_change_preserves_the_semantic_fingerprint():
    """A document-status / acceptance-metadata change must NOT alter the fingerprint."""
    suite = _fixture()
    baseline = semantic_fingerprint(suite)
    metadata_patched = copy.deepcopy(suite)
    metadata_patched["status"] = "ACCEPTED_BY_OWNER"          # document status
    metadata_patched["policy_version_ref"] = "accepted-2026-07-15"  # acceptance record
    assert semantic_fingerprint(metadata_patched) == baseline


# ---------------------------------------------------------------------------
# OD-S1A-008 completion (M-R2V-01)
# ---------------------------------------------------------------------------

def test_od_s1a_008_decision_record_is_complete_and_pending():
    record = _fixture()["od_s1a_008_decision_record"]
    assert record["id"] == "OD-S1A-008"
    assert record["status"] == "PENDING_OWNER_DECISION"
    assert record["blocks"] == {
        "slice_1a_owner_review": "NOT_BLOCKED",
        "slice_1b_a2": "NOT_BLOCKED",
        "slice_1c_1_a3": "BLOCKED_UNTIL_ACCEPTED",
    }
    questions = {q["question"] for q in record["owner_must_decide"]}
    for needed in ("unknown display strings", "duplicate declarations", "aliases",
                   "deprecated aliases", "alias conflicts", "mapping version",
                   "declaration-set schema version",
                   "stable requirement_id namespace"):
        assert any(needed in q for q in questions), f"missing owner question: {needed}"
    # all 10 owner questions present.
    assert len(record["owner_must_decide"]) == 10
    # the ten pre-1C-1 declaration fields.
    assert set(record["pre_1c_1_declaration_fields"]) == {
        "requirement_id", "display_label", "source_contract_version",
        "declaration_set_version", "mapping_version", "aliases", "deprecated_aliases",
        "unknown_value_policy", "duplicate_policy", "conflict_policy",
    }
    # spec §25.1 enumerates the same questions and fields, still pending, no answer chosen.
    text = _spec_text()
    assert "Slice 1C-1 / A3:         BLOCKED UNTIL ACCEPTED" in text
    for field in ("unknown_value_policy", "duplicate_policy", "conflict_policy",
                  "deprecated_aliases", "mapping_version", "declaration_set_version"):
        assert field in text, f"spec must list pre-1C-1 field {field}"
    # A2 stays independent (GC-S1-041), A3 stays blocked; no mapping is chosen.
    case = _case("GC-S1-041")
    assert "OD-S1A-008" in case["owner_decisions_pending"]
    assert case["expected_event_assertions"][
        "requirement_ids_derived_from_display_strings"] is False


def test_all_eight_owner_decisions_remain_pending():
    suite = _fixture()
    assert list(suite["owner_decisions"]) == list(OD_S1A_IDS)
    text = _spec_text()
    for od in OD_S1A_IDS:
        assert od in text
    assert "PENDING_OWNER_DECISION" in text
    # status is still draft for owner review.
    assert re.search(r"^Status:\s*DRAFT_FOR_OWNER_REVIEW\s*$", text, re.MULTILINE)

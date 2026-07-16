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
    "verification_bundle_digest", "approval_digest_or_sentinel",
    "authority_binding_digest",
    "verifier_binding_digest", "policy_digest",
)

# The ONE exact, ordered PolicyEvaluationRecordPayload field contract (§7.3 / manifest).
# The record OBJECT is these fields in this order followed by policy_record_digest. The
# canonical approval field is approval_digest_or_sentinel; no alias is permitted.
POLICY_RECORD_PAYLOAD_FIELDS = (
    "schema_version", "task_id", *SOURCE_DIGEST_FIELDS, "policy_version",
    "evaluator_version", "evaluation_mode", "input_digest", "disposition",
    "decision_authority", "primary_reason_code", "complete_reason_codes",
    "blocking_reason_codes", "review_reason_codes", *REQUIREMENT_SETS,
    *EVIDENCE_RECORD_SETS, "decision_digest",
)
POLICY_RECORD_OBJECT_FIELDS = POLICY_RECORD_PAYLOAD_FIELDS + ("policy_record_digest",)

# Application/runtime fields a deterministic record must NEVER contain.
_RECORD_FORBIDDEN_FIELDS = (
    "redaction_classification", "trace_id", "request_id", "evaluation_id",
    "occurred_at", "timestamp", "evaluation_latency_ms", "event_id", "storage_location",
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
    """Independent record validator (R5): enforce the EXACT canonical payload shape BEFORE
    digest recomputation, so a renamed/missing/extra field can never be laundered by
    recomputing the digest. Does NOT read any fixture expected_* value.

    failure_code tags map to the named manifest predicates (validator↔manifest equivalence).
    """
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["RECORD_SHAPE_DRIFT: record is not an object"]
    # REC-NO-RUNTIME — no runtime/application field (checked against the actual record).
    for forbidden in _RECORD_FORBIDDEN_FIELDS:
        if forbidden in record:
            errors.append(f"RECORD_RUNTIME_FIELD: {forbidden!r} present in the record")
    # REC-EXACT-KEYS — exact ordered key set (payload fields + trailing digest). Rejects a
    # renamed approval field, a missing canonical field, an extra field, a
    # duplicate-under-another-key, and any reordering.
    if tuple(record.keys()) != POLICY_RECORD_OBJECT_FIELDS:
        errors.append(
            "RECORD_SHAPE_DRIFT: record keys/order != POLICY_RECORD_PAYLOAD_FIELDS + "
            "(policy_record_digest,)"
        )
        return errors  # shape is wrong; nothing else is trustworthy
    if record["schema_version"] != "changegate.policy-evaluation-record.v1":
        errors.append("RECORD_SHAPE_DRIFT: bad schema_version")
    # REC-DIGEST-RECOMPUTE — the digest must recompute over EXACTLY this payload.
    if recompute_record_digest(record) != record["policy_record_digest"]:
        errors.append("RECORD_DIGEST_MISMATCH: policy_record_digest != recomputed payload")
    # blocking ∪ review == complete, and both partition it.
    complete = set(record["complete_reason_codes"])
    if set(record["blocking_reason_codes"]) | set(
        record["review_reason_codes"]
    ) != complete:
        errors.append("RECORD_SHAPE_DRIFT: blocking ∪ review != complete reason set")
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
            if field == "approval_digest_or_sentinel" and value == NO_APPROVAL_SENTINEL:
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
# Exception-path override (no replacement decision).
_OVERRIDE = {"actor_ref": "owner-1", "reason_code": "SCOPE_EXCEPTION",
             "replacement_decision_ref": None, "exception_ref": "exc-1",
             "expires_at": "2026-08-01T00:00:00Z"}


def _replacement_dref(**overrides) -> dict:
    """A complete atomic replacement_decision_ref (all six fields)."""
    base = {
        "evaluation_id": "eval-repl", "task_ref": _ROOT_TASK,
        "candidate_digest": _ROOT_CANDIDATE,
        "decision_digest": canonical_digest({"repl": "decision"}),
        "input_digest": canonical_digest({"repl": "input"}),
        "policy_record_digest": canonical_digest({"repl": "record"}),
    }
    base.update(overrides)
    return base

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

# A decision "head" for a root is either the originating evaluation or a review override
# that produced a replacement decision for it; both may parent a merge attempt / override.
_DECISION_HEAD = ("CHANGEGATE_EVALUATION_COMPLETED", "CHANGEGATE_REVIEW_OVERRIDDEN")

CHAIN_PARENT_RULES: dict[str, tuple[tuple[str, object], ...]] = {
    # event_type -> ((reference field, required type(s) of the referenced event), ...)
    "CHANGEGATE_EVALUATION_COMPLETED": (),
    "CHANGEGATE_REVIEW_OVERRIDDEN": (
        ("evaluation_event_ref", _DECISION_HEAD),
    ),
    "CHANGEGATE_MERGE_ATTEMPTED": (
        ("evaluation_event_ref", _DECISION_HEAD),
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


def _type_matches(actual: str, required: object) -> bool:
    if required == "*":
        return True
    if isinstance(required, tuple):
        return actual in required
    return actual == required


# The six-field active lineage (R5) — evaluation_id is a first-class lineage field.
_LINEAGE_KEYS = ("evaluation_id", "task_ref", "candidate_digest", "decision_digest",
                 "input_digest", "policy_record_digest")
# Every explicit causal reference each event type carries (multi-parent consistency, §12).
_PARENT_FIELDS_BY_TYPE = {
    "CHANGEGATE_REVIEW_OVERRIDDEN": ("evaluation_event_ref",),
    "CHANGEGATE_MERGE_ATTEMPTED": ("evaluation_event_ref",),
    "CHANGEGATE_MERGE_COMPLETED": ("attempt_event_ref",),
    "CHANGEGATE_POST_MERGE_VALIDATION": ("merge_event_ref",),
    "CHANGEGATE_ROLLBACK_RECORDED": ("merge_event_ref", "validation_event_ref"),
    "CHANGEGATE_USER_FEEDBACK_RECORDED": ("target_event_ref",),
}


def _lineage_of(ref: dict) -> dict:
    return {k: ref[k] for k in _LINEAGE_KEYS}


def _record_registry(*records: dict) -> dict:
    """An immutable record store keyed by policy_record_digest (test-level stand-in for
    the future application record store §7)."""
    return {r["policy_record_digest"]: r for r in records}


def validate_event_chain(events: list[dict], records: dict | None = None) -> list[str]:
    """Cross-event relationships JSON Schema cannot express, using a GRAPH keyed by causal
    event references with EVALUATION IDENTITY and MULTI-PARENT lineage consistency (§19.3–
    §19.6, R5). `records` maps policy_record_digest -> PolicyEvaluationRecord and is used to
    verify replacement decisions coherently. Returns error strings.
    """
    errors: list[str] = []
    records = records or {}
    by_id: dict[str, dict] = {}
    lineage_at: dict[str, dict] = {}          # event_id -> lineage it propagates
    eval_registry: dict[str, dict] = {}       # evaluation_id -> its complete lineage

    def dref_of(event: dict) -> dict | None:
        dr = event.get("decision_ref")
        return dr if isinstance(dr, dict) else None

    def register_evaluation(eval_id: str, lineage: dict, where: str) -> None:
        prior = eval_registry.get(eval_id)
        if prior is None:
            eval_registry[eval_id] = lineage
        elif prior != lineage:
            errors.append(
                f"{where}: EVALUATION_ID_DUPLICATE {eval_id!r} maps to two identities"
            )
        else:
            errors.append(
                f"{where}: EVALUATION_ID_DUPLICATE {eval_id!r} re-registered"
            )

    for event in events:
        event_id = event["event_id"]
        etype = event["event_type"]
        if event_id in by_id:
            errors.append(f"duplicate event_id {event_id!r}")
        dref = dref_of(event)

        # 0. envelope/decision task equality + candidate-subject-digest equality (§19.5).
        if dref is not None:
            if event.get("task_ref") != dref.get("task_ref"):
                errors.append(
                    f"{event_id}: envelope task_ref {event.get('task_ref')!r} != "
                    f"decision_ref.task_ref {dref.get('task_ref')!r}"
                )
            subject = event.get("subject_ref") or {}
            if (subject.get("kind") == "git_candidate" and subject.get("digest")
                    and subject["digest"] != dref.get("candidate_digest")):
                errors.append(
                    f"{event_id}: subject_ref.digest != decision_ref.candidate_digest"
                )

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
            if not _type_matches(parent["event_type"], required_type):
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

        # 3. lineage — graph-based, six-field, MULTI-PARENT consistent.
        if etype == "CHANGEGATE_EVALUATION_COMPLETED":
            if dref is None:
                errors.append(f"{event_id}: evaluation without decision_ref")
            else:
                lineage = _lineage_of(dref)
                register_evaluation(dref["evaluation_id"], lineage, event_id)
                lineage_at[event_id] = lineage
        else:
            # collect EVERY explicit predecessor's propagated lineage; all must agree.
            parent_lineages: list[tuple[str, dict]] = []
            reachable = True
            for pfield in _PARENT_FIELDS_BY_TYPE[etype]:
                pref = event.get(pfield)
                if not pref:
                    continue
                plin = lineage_at.get(pref)
                if plin is None:
                    reachable = False
                    continue
                parent_lineages.append((pfield, plin))
            if not parent_lineages:
                if reachable:
                    errors.append(f"{event_id}: no reachable evaluation root")
                inherited = None
            else:
                distinct = {tuple(sorted(pl.items())) for _, pl in parent_lineages}
                if len(distinct) != 1:
                    errors.append(
                        f"{event_id}: AMBIGUOUS_PREDECESSOR_LINEAGE — predecessors "
                        f"{[f for f, _ in parent_lineages]} carry different lineages"
                    )
                    inherited = None
                elif not reachable:
                    errors.append(f"{event_id}: no reachable evaluation root")
                    inherited = None
                else:
                    inherited = parent_lineages[0][1]
            if inherited is not None and dref is not None:
                for key in _LINEAGE_KEYS:
                    if dref[key] != inherited[key]:
                        code = ("EVALUATION_ID_DRIFT" if key == "evaluation_id"
                                else "LINEAGE_DIVERGES")
                        errors.append(f"{event_id}: {key} diverges ({code})")
                lineage_at[event_id] = inherited

        # 4. review override: atomic + coherent replacement decision (§19.4), then switch.
        if etype == "CHANGEGATE_REVIEW_OVERRIDDEN":
            override = event.get("override") or {}
            repl = override.get("replacement_decision_ref")
            inherited = lineage_at.get(event.get("evaluation_event_ref") or "")
            if repl is not None and inherited is not None and dref is not None:
                errors.extend(
                    _validate_replacement(event_id, repl, _lineage_of(dref), inherited,
                                          records, eval_registry)
                )
                lineage_at[event_id] = _lineage_of(repl)

        by_id[event_id] = event

    # cycle detection over the causal reference graph.
    errors.extend(_detect_causal_cycle(events))
    return errors


def _validate_replacement(event_id, repl, original, root, records, eval_registry):
    """§19.4/§8 coherent replacement identity. `records` verifies the replacement is a real
    PolicyEvaluationRecord, not six strings in a JSON object."""
    errs: list[str] = []
    new = _lineage_of(repl)
    # RPL-ROOT-OWNERSHIP + RPL-CANDIDATE-NEW-ROOT
    if new["task_ref"] != root["task_ref"]:
        errs.append(f"{event_id}: REPLACEMENT_ROOT_MISMATCH task_ref != root task")
    if new["candidate_digest"] != root["candidate_digest"]:
        errs.append(
            f"{event_id}: REPLACEMENT_CANDIDATE_CHANGED candidate_digest != root candidate")
    # RPL-DECISION-DIFFERS / RPL-RECORD-DIFFERS
    if new["decision_digest"] == original["decision_digest"]:
        errs.append(f"{event_id}: REPLACEMENT_DECISION_NOT_CHANGED")
    if new["policy_record_digest"] == original["policy_record_digest"]:
        errs.append(f"{event_id}: REPLACEMENT_RECORD_NOT_CHANGED")
    # RPL-NO-OP — the three decision-identity digests all unchanged from the original.
    if (new["decision_digest"] == original["decision_digest"]
            and new["input_digest"] == original["input_digest"]
            and new["policy_record_digest"] == original["policy_record_digest"]):
        errs.append(f"{event_id}: REPLACEMENT_NO_OP identical to original")
    # RPL-EVAL-UNIQUE — replacement evaluation_id must be new+unique.
    if new["evaluation_id"] in eval_registry:
        errs.append(f"{event_id}: REPLACEMENT_EVALUATION_NOT_UNIQUE {new['evaluation_id']!r}")
    # RPL-REGISTERED-RECORD + record-consistency equalities (do NOT trust the six strings).
    record = records.get(new["policy_record_digest"])
    if record is None:
        errs.append(f"{event_id}: REPLACEMENT_RECORD_MISSING (no registered record)")
    else:
        if validate_policy_record(record):
            errs.append(f"{event_id}: REPLACEMENT_RECORD_DIGEST_MISMATCH (invalid record)")
        else:
            if record["policy_record_digest"] != new["policy_record_digest"]:
                errs.append(f"{event_id}: REPLACEMENT_RECORD_DIGEST_MISMATCH")
            if record["decision_digest"] != new["decision_digest"]:
                errs.append(f"{event_id}: REPLACEMENT_DECISION_MISMATCH")
            if record["input_digest"] != new["input_digest"]:
                errs.append(f"{event_id}: REPLACEMENT_INPUT_MISMATCH")
            if record["task_id"] != new["task_ref"]:
                errs.append(f"{event_id}: REPLACEMENT_TASK_MISMATCH")
            if record["candidate_digest"] != new["candidate_digest"]:
                errs.append(f"{event_id}: REPLACEMENT_CANDIDATE_MISMATCH")
    # register the replacement evaluation identity (if unique).
    if new["evaluation_id"] not in eval_registry:
        eval_registry[new["evaluation_id"]] = new
    return errs


def _detect_causal_cycle(events: list[dict]) -> list[str]:
    ref_fields = ("evaluation_event_ref", "attempt_event_ref", "merge_event_ref",
                  "validation_event_ref", "target_event_ref")
    edges: dict[str, list[str]] = {}
    for e in events:
        edges[e["event_id"]] = [e[f] for f in ref_fields if e.get(f)]
    color: dict[str, int] = {}

    def dfs(node: str) -> bool:
        color[node] = 1
        for nxt in edges.get(node, []):
            if color.get(nxt) == 1:
                return True
            if color.get(nxt, 0) == 0 and nxt in edges and dfs(nxt):
                return True
        color[node] = 2
        return False

    for node in edges:
        if color.get(node, 0) == 0 and dfs(node):
            return [f"causal cycle detected at {node}"]
    return []


def _dref(**overrides) -> dict:
    return {**_DECISION_REF, **overrides}


def _make_replacement(root_task: str, root_candidate: str, original: dict, *,
                      same_input: bool, tag: str) -> tuple[dict, dict]:
    """Build a COHERENT replacement: a real PolicyEvaluationRecord bound to the root
    task/candidate with a genuinely new decision identity, plus the matching atomic
    replacement_decision_ref. Returns (replacement_ref, replacement_record). The record is
    what the registry serves; the ref's six digests are verified against it, never trusted
    on their own. `same_input=True` keeps the original input_digest (a human-resolved
    override on identical deterministic input, §8)."""
    case = _case("GC-S1-001")
    bindings = {**case["policy_input_bindings"], "task_id": root_task,
                "candidate_digest": root_candidate}
    facts = case["policy_input_facts"]
    record = build_policy_record(bindings, facts, _fixture()["fact_state_mapping"])
    payload = {k: v for k, v in record.items() if k != "policy_record_digest"}
    payload["decision_digest"] = canonical_digest({"replacement-decision": tag})
    payload["input_digest"] = (original["input_digest"] if same_input
                               else canonical_digest({"replacement-input": tag}))
    record = {**payload, "policy_record_digest": canonical_digest(payload)}
    ref = {
        "evaluation_id": f"eval-repl-{tag}",
        "task_ref": root_task, "candidate_digest": root_candidate,
        "decision_digest": record["decision_digest"],
        "input_digest": record["input_digest"],
        "policy_record_digest": record["policy_record_digest"],
    }
    return ref, record


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

    # 14 locally valid but disconnected event (no reachable evaluation root).
    disconnected = copy.deepcopy(chain)
    del disconnected[1]["evaluation_event_ref"]
    assert any("no reachable evaluation root" in e
               for e in validate_event_chain(disconnected))

    # 15 changed candidate continuing the old chain without a new evaluation event.
    changed_candidate = copy.deepcopy(chain)
    changed_candidate[2]["decision_ref"] = foreign_cand
    assert any("candidate_digest diverges" in e
               for e in validate_event_chain(changed_candidate))

    # 16 replacement mixing digests / incoherent record — see the dedicated §19.4 test.
    repl, record = _make_replacement(_ROOT_TASK, _ROOT_CANDIDATE, _lineage_of(_DECISION_REF),
                                     same_input=False, tag="c16")
    tampered = {**repl, "decision_digest": _DECISION_REF["decision_digest"]}  # claim old dec
    override_event = _override_event("evt-override-1", tampered)
    assert any("REPLACEMENT_DECISION" in e for e in validate_event_chain(
        [chain[0], override_event], records=_record_registry(record)))


def _override_event(event_id: str, repl: dict, evaluation_event_ref: str = "evt-eval-1",
                    decision_ref: dict | None = None) -> dict:
    return {**_base_envelope("CHANGEGATE_REVIEW_OVERRIDDEN"), "event_id": event_id,
            "decision_ref": decision_ref or _DECISION_REF,
            "evaluation_event_ref": evaluation_event_ref,
            "override": {"actor_ref": "owner-1", "reason_code": "SCOPE_EXCEPTION",
                         "replacement_decision_ref": repl,
                         "exception_ref": None, "expires_at": None}}


def _root_eval_event() -> dict:
    return {**_base_envelope("CHANGEGATE_EVALUATION_COMPLETED"), "event_id": "evt-eval-1",
            **_POSITIVE_EXTRAS["CHANGEGATE_EVALUATION_COMPLETED"]}


def test_replacement_positive_same_input_is_permitted():
    """§8 RPL-SAME-INPUT-OK: same input_digest + new decision + new coherent record passes."""
    original = _lineage_of(_DECISION_REF)
    repl, record = _make_replacement(_ROOT_TASK, _ROOT_CANDIDATE, original,
                                     same_input=True, tag="ok")
    assert repl["input_digest"] == original["input_digest"]        # same input
    assert repl["decision_digest"] != original["decision_digest"]  # new decision
    assert repl["policy_record_digest"] != original["policy_record_digest"]
    chain = [_root_eval_event(), _override_event("evt-ovr", repl)]
    assert validate_event_chain(chain, records=_record_registry(record)) == []


def test_replacement_decision_negative_controls_are_all_detected():
    """§9: all fourteen replacement-integrity controls are detected."""
    original = _lineage_of(_DECISION_REF)
    evaluation = _root_eval_event()

    def run(repl, record):
        return validate_event_chain([evaluation, _override_event("evt-ovr", repl)],
                                    records=_record_registry(record) if record else {})

    base_repl, base_record = _make_replacement(_ROOT_TASK, _ROOT_CANDIDATE, original,
                                               same_input=False, tag="base")

    # 1 old decision + new input + new record (claim original decision digest).
    r = {**base_repl, "decision_digest": original["decision_digest"]}
    assert any("REPLACEMENT_DECISION" in e for e in run(r, base_record))
    # 2 new decision + old input + new record whose EMBEDDED input differs from the ref.
    r = {**base_repl, "input_digest": original["input_digest"]}   # ref says old input
    assert any("REPLACEMENT_INPUT_MISMATCH" in e for e in run(r, base_record))
    # 3 new decision + new input + old record (claim original record digest).
    r = {**base_repl, "policy_record_digest": original["policy_record_digest"]}
    assert any("REPLACEMENT_RECORD" in e for e in run(r, base_record))
    # 4 record digest not matching the replacement record (tamper the record).
    bad_record = {**base_record, "task_id": base_record["task_id"]}  # same shape
    bad_record = {**base_record}
    bad_record["policy_record_digest"] = canonical_digest({"tampered": 1})
    assert any("REPLACEMENT_RECORD" in e for e in run(base_repl, bad_record))
    # 5 decision digest not matching the replacement record.
    r = {**base_repl, "decision_digest": canonical_digest({"mismatch": "dec"})}
    assert any("REPLACEMENT_DECISION_MISMATCH" in e for e in run(r, base_record))
    # 6 task mismatch (ref task != root).
    r = {**base_repl, "task_ref": "other-task"}
    assert any("REPLACEMENT_ROOT_MISMATCH" in e for e in run(r, base_record))
    # 7 candidate mismatch.
    r = {**base_repl, "candidate_digest": canonical_digest({"c": "other"})}
    assert any("REPLACEMENT_CANDIDATE_CHANGED" in e for e in run(r, base_record))
    # 8 partial replacement object — schema-rejected.
    validator = _validator()
    partial = _override_event("evt-ovr", {"evaluation_id": "e", "task_ref": _ROOT_TASK,
                              "candidate_digest": _ROOT_CANDIDATE,
                              "decision_digest": base_repl["decision_digest"]})
    assert list(validator.iter_errors(partial))
    # 9 identical / no-op replacement.
    noop = {**base_repl, "decision_digest": original["decision_digest"],
            "input_digest": original["input_digest"],
            "policy_record_digest": original["policy_record_digest"]}
    assert any("REPLACEMENT" in e for e in run(noop, base_record))
    # 10 duplicate evaluation ID (reuse the root's evaluation_id).
    r = {**base_repl, "evaluation_id": _DECISION_REF["evaluation_id"]}
    assert any("REPLACEMENT_EVALUATION_NOT_UNIQUE" in e for e in run(r, base_record))
    # 11 arbitrary evaluation ID with NO registered replacement record.
    assert any("REPLACEMENT_RECORD_MISSING" in e
               for e in run(base_repl, None))
    # 12 replacement record copied from ANOTHER root (different task/candidate record).
    other_repl, other_record = _make_replacement(
        "task-OTHER", canonical_digest({"c": "OTHER"}), original, same_input=False,
        tag="other")
    # point the ref at our root but serve the other-root record:
    r = {**base_repl, "policy_record_digest": other_record["policy_record_digest"]}
    assert any("REPLACEMENT" in e for e in run(r, other_record))
    # 13 downstream revert to original decision identity after activation.
    override = _override_event("evt-ovr", base_repl)
    revert = {**_base_envelope("CHANGEGATE_MERGE_ATTEMPTED"), "event_id": "evt-att",
              "decision_ref": _DECISION_REF, "evaluation_event_ref": "evt-ovr",
              "outcome": {"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"}}
    errs = validate_event_chain([evaluation, override, revert],
                                records=_record_registry(base_record))
    assert any("diverges" in e for e in errs)
    # 14 replacement candidate change without a new evaluation root (== control 7 form).
    r = {**base_repl, "candidate_digest": canonical_digest({"c": "z"})}
    assert any("REPLACEMENT_CANDIDATE_CHANGED" in e for e in run(r, base_record))


def test_override_switches_active_decision_lineage():
    """A coherent atomic replacement switches the lineage; a subsequent event matching the
    REPLACEMENT validates, and one reverting to the original afterwards fails."""
    original = _lineage_of(_DECISION_REF)
    repl, record = _make_replacement(_ROOT_TASK, _ROOT_CANDIDATE, original,
                                     same_input=False, tag="switch")
    replacement_lineage = _dref(evaluation_id=repl["evaluation_id"],
                                decision_digest=repl["decision_digest"],
                                input_digest=repl["input_digest"],
                                policy_record_digest=repl["policy_record_digest"])

    def env(event_id, event_type, **extra):
        return {**_base_envelope(event_type), "event_id": event_id, **extra}

    override = _override_event("evt-override-1", repl)
    good_attempt = env("evt-attempt-1", "CHANGEGATE_MERGE_ATTEMPTED",
                       decision_ref=replacement_lineage,
                       evaluation_event_ref="evt-override-1",
                       outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"})
    stale_attempt = env("evt-attempt-2", "CHANGEGATE_MERGE_ATTEMPTED",
                        decision_ref=_DECISION_REF, evaluation_event_ref="evt-override-1",
                        outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"})
    evaluation = _root_eval_event()
    validator = _validator()
    for e in (evaluation, override, good_attempt):
        assert not list(validator.iter_errors(e)), e["event_id"]
    registry = _record_registry(record)
    assert validate_event_chain([evaluation, override, good_attempt], records=registry) == []
    stale_errors = validate_event_chain([evaluation, override, stale_attempt],
                                        records=registry)
    assert any("diverges" in e for e in stale_errors)


def _set(chain: list[dict], idx: int, key: str, value) -> list[dict]:
    chain[idx][key] = value
    return chain


# ---------------------------------------------------------------------------
# Multi-root causal graph (M-R3V-01)
# ---------------------------------------------------------------------------

def _root_lineage(task: str, candidate: str, tag: str) -> dict:
    return _dref(evaluation_id=f"eval-{tag}", task_ref=task, candidate_digest=candidate,
                 decision_digest=canonical_digest({"d": tag}),
                 input_digest=canonical_digest({"i": tag}),
                 policy_record_digest=canonical_digest({"r": tag}))


def _evt(event_id: str, event_type: str, lineage: dict, **extra) -> dict:
    """An event whose envelope task/subject-digest match its decision_ref lineage."""
    e = copy.deepcopy(_base_envelope(event_type))
    e["event_id"] = event_id
    e["task_ref"] = lineage["task_ref"]
    e["subject_ref"] = {"namespace": "changegate", "kind": "git_candidate",
                        "value": "cand", "commit_sha": _COMMIT,
                        "digest": lineage["candidate_digest"]}
    e["decision_ref"] = lineage
    e.update(extra)
    return e


def _root_event(event_id: str, lineage: dict) -> dict:
    return _evt(event_id, "CHANGEGATE_EVALUATION_COMPLETED", lineage,
                context_digest=lineage["input_digest"],
                policy_version="changegate-policy.v5-draft", evaluator_version="0.1.0",
                outcome={"status": "SUCCESS", "detail_code": "EVALUATION_OK"},
                decision_ref={**lineage, "disposition": "BLOCK",
                              "decision_authority": "AUTHORITATIVE"})


def test_multi_root_positive_chains_validate():
    validator = _validator()
    A = _root_lineage("task-A", canonical_digest({"c": "A"}), "A")
    B = _root_lineage("task-B", canonical_digest({"c": "B"}), "B")
    # same task-A, different candidate:
    A2 = _root_lineage("task-A", canonical_digest({"c": "A2"}), "A2")

    def attempt(eid, lineage, root_id):
        return _evt(eid, "CHANGEGATE_MERGE_ATTEMPTED", lineage,
                    evaluation_event_ref=root_id,
                    outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"})

    scenarios = {
        # 1 two sequential independent roots
        "sequential": [_root_event("evt-A", A), attempt("evt-A-att", A, "evt-A"),
                       _root_event("evt-B", B), attempt("evt-B-att", B, "evt-B")],
        # 2 two interleaved roots for different tasks
        "interleaved": [_root_event("evt-A", A), _root_event("evt-B", B),
                        attempt("evt-B-att", B, "evt-B"),
                        attempt("evt-A-att", A, "evt-A")],
        # 3 two roots for the same task, different candidates
        "same_task_diff_candidate": [_root_event("evt-A", A), _root_event("evt-A2", A2),
                                     attempt("evt-A-att", A, "evt-A"),
                                     attempt("evt-A2-att", A2, "evt-A2")],
    }
    for name, chain in scenarios.items():
        for e in chain:
            assert not list(validator.iter_errors(e)), f"{name}/{e['event_id']}"
        assert validate_event_chain(chain) == [], f"{name}: {validate_event_chain(chain)}"

    # 4 one root with an override (coherent replacement), one without.
    repl, record = _make_replacement("task-A", A["candidate_digest"], A,
                                     same_input=False, tag="A-repl")
    repl_lineage = _dref(evaluation_id=repl["evaluation_id"], task_ref="task-A",
                         candidate_digest=A["candidate_digest"],
                         decision_digest=repl["decision_digest"],
                         input_digest=repl["input_digest"],
                         policy_record_digest=repl["policy_record_digest"])
    override = _evt("evt-A-ovr", "CHANGEGATE_REVIEW_OVERRIDDEN", A,
                    evaluation_event_ref="evt-A",
                    override={"actor_ref": "owner-1", "reason_code": "SCOPE_EXCEPTION",
                              "replacement_decision_ref": repl,
                              "exception_ref": None, "expires_at": None})
    a_after_override = _evt("evt-A-att2", "CHANGEGATE_MERGE_ATTEMPTED", repl_lineage,
                            evaluation_event_ref="evt-A-ovr",
                            outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"})
    b_plain = attempt("evt-B-att", B, "evt-B")
    mixed = [_root_event("evt-A", A), _root_event("evt-B", B), override,
             a_after_override, b_plain]
    for e in mixed:
        assert not list(validator.iter_errors(e)), e["event_id"]
    assert validate_event_chain(mixed, records=_record_registry(record)) == [], (
        validate_event_chain(mixed, records=_record_registry(record)))


def test_multi_root_negative_controls_are_detected():
    A = _root_lineage("task-A", canonical_digest({"c": "A"}), "A")
    B = _root_lineage("task-B", canonical_digest({"c": "B"}), "B")

    def attempt(eid, lineage, root_id):
        return _evt(eid, "CHANGEGATE_MERGE_ATTEMPTED", lineage,
                    evaluation_event_ref=root_id,
                    outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"})

    # attempt carrying its own (task-B) lineage but referencing task-A's evaluation.
    cross = attempt("evt-x", B, "evt-A")
    errs = validate_event_chain([_root_event("evt-A", A), _root_event("evt-B", B), cross])
    assert any("diverges" in e for e in errs), f"cross-root not detected: {errs}"

    # completion linked to an attempt from another candidate.
    att_A = attempt("evt-A-att", A, "evt-A")
    comp_wrong = _evt("evt-comp", "CHANGEGATE_MERGE_COMPLETED", B,
                      attempt_event_ref="evt-A-att",
                      outcome={"status": "SUCCESS", "detail_code": "MERGE_OK",
                               "resulting_commit_sha": "c" * 40})
    errs = validate_event_chain([_root_event("evt-A", A), att_A, comp_wrong])
    assert any("diverges" in e for e in errs)

    # feedback targeting another root while carrying current-root identity.
    fb = _evt("evt-fb", "CHANGEGATE_USER_FEEDBACK_RECORDED", B,
              target_event_ref="evt-A", target_event_type="CHANGEGATE_EVALUATION_COMPLETED",
              feedback=_FEEDBACK)
    errs = validate_event_chain([_root_event("evt-A", A), _root_event("evt-B", B), fb])
    assert any("diverges" in e for e in errs)

    # event with no reachable evaluation root (disconnected: no evaluation_event_ref).
    orphan = _evt("evt-orphan", "CHANGEGATE_MERGE_ATTEMPTED", A,
                  outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"})
    assert any("no reachable evaluation root" in e
               for e in validate_event_chain([orphan]))

    # duplicate EVENT id.
    dup_event = [_root_event("evt-A", A), _root_event("evt-A", B)]
    assert any("duplicate event_id" in e for e in validate_event_chain(dup_event))

    # duplicate ROOT EVALUATION id even with different event ids.
    A_dup_eval = _dref(evaluation_id="eval-A", task_ref="task-C",
                       candidate_digest=canonical_digest({"c": "C"}),
                       decision_digest=canonical_digest({"d": "C"}),
                       input_digest=canonical_digest({"i": "C"}),
                       policy_record_digest=canonical_digest({"r": "C"}))
    dup_eval = [_root_event("evt-A", A), _root_event("evt-C", A_dup_eval)]
    assert any("EVALUATION_ID_DUPLICATE" in e for e in validate_event_chain(dup_eval))

    # downstream evaluation-ID drift (same other lineage, different evaluation_id).
    drift = attempt("evt-drift", {**A, "evaluation_id": "eval-DRIFT"}, "evt-A")
    errs = validate_event_chain([_root_event("evt-A", A), drift])
    assert any("EVALUATION_ID_DRIFT" in e for e in errs), errs

    # rollback combining a merge from root A with a validation from root B (multi-parent).
    att_A = attempt("evt-A-att", A, "evt-A")
    merge_A = _evt("evt-A-merge", "CHANGEGATE_MERGE_COMPLETED", A,
                   attempt_event_ref="evt-A-att",
                   outcome={"status": "SUCCESS", "detail_code": "MERGE_OK",
                            "resulting_commit_sha": "c" * 40})
    att_B = attempt("evt-B-att", B, "evt-B")
    merge_B = _evt("evt-B-merge", "CHANGEGATE_MERGE_COMPLETED", B,
                   attempt_event_ref="evt-B-att",
                   outcome={"status": "SUCCESS", "detail_code": "MERGE_OK",
                            "resulting_commit_sha": "d" * 40})
    val_B = _evt("evt-B-val", "CHANGEGATE_POST_MERGE_VALIDATION", B,
                 merge_event_ref="evt-B-merge",
                 outcome={"status": "FAILURE", "detail_code": "CI_FAILED"})
    rollback_cross = _evt("evt-roll", "CHANGEGATE_ROLLBACK_RECORDED", A,
                          merge_event_ref="evt-A-merge", validation_event_ref="evt-B-val",
                          outcome={"status": "SUCCESS", "detail_code": "ROLLED_BACK"})
    cross_chain = [_root_event("evt-A", A), _root_event("evt-B", B), att_A, merge_A,
                   att_B, merge_B, val_B, rollback_cross]
    assert any("AMBIGUOUS_PREDECESSOR_LINEAGE" in e
               for e in validate_event_chain(cross_chain))

    # causal cycle.
    cyc_a = attempt("evt-cyc-a", A, "evt-cyc-b")
    cyc_b = attempt("evt-cyc-b", A, "evt-cyc-a")
    assert any("cycle" in e for e in validate_event_chain([cyc_a, cyc_b]))


def test_multi_parent_rollback_positive_shares_lineage():
    """§12: a rollback whose merge and validation predecessors share one lineage passes."""
    A = _root_lineage("task-A", canonical_digest({"c": "A"}), "A")

    def ev(eid, etype, **extra):
        return _evt(eid, etype, A, **extra)

    chain = [
        _root_event("evt-A", A),
        ev("evt-att", "CHANGEGATE_MERGE_ATTEMPTED", evaluation_event_ref="evt-A",
           outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"}),
        ev("evt-merge", "CHANGEGATE_MERGE_COMPLETED", attempt_event_ref="evt-att",
           outcome={"status": "SUCCESS", "detail_code": "MERGE_OK",
                    "resulting_commit_sha": "c" * 40}),
        ev("evt-val", "CHANGEGATE_POST_MERGE_VALIDATION", merge_event_ref="evt-merge",
           outcome={"status": "FAILURE", "detail_code": "CI_FAILED"}),
        ev("evt-roll", "CHANGEGATE_ROLLBACK_RECORDED", merge_event_ref="evt-merge",
           validation_event_ref="evt-val",
           outcome={"status": "SUCCESS", "detail_code": "ROLLED_BACK"}),
    ]
    validator = _validator()
    for e in chain:
        assert not list(validator.iter_errors(e)), e["event_id"]
    assert validate_event_chain(chain) == [], validate_event_chain(chain)


# ---------------------------------------------------------------------------
# Task identity consistency (M-R3V-02)
# ---------------------------------------------------------------------------

def test_nested_decision_ref_task_ref_reuses_the_no_whitespace_grammar():
    schema = _schema()
    # both event.task_ref and decision_ref.task_ref reference the ONE taskRef def.
    assert schema["properties"]["task_ref"]["$ref"] == "#/$defs/taskRef"
    assert schema["properties"]["decision_ref"]["properties"]["task_ref"]["$ref"] == (
        "#/$defs/taskRef"
    )
    assert (schema["properties"]["override"]["properties"]["replacement_decision_ref"]
            ["properties"]["task_ref"]["$ref"] == "#/$defs/taskRef")
    validator = _validator()
    for bad in ("task-A\n", "task-A\t", "task A", "task/A", " taskA"):
        inst = {**_base_envelope("CHANGEGATE_MERGE_ATTEMPTED"),
                "evaluation_event_ref": "evt-eval-1",
                "decision_ref": _dref(task_ref=bad),
                "outcome": {"status": "SUCCESS", "detail_code": "OK"}}
        assert list(validator.iter_errors(inst)), f"nested task_ref accepted {bad!r}"


def test_envelope_and_decision_task_equality_is_enforced():
    # envelope task A / decision task B — schema-valid but identity-inconsistent.
    validator = _validator()
    inst = {**_base_envelope("CHANGEGATE_EVALUATION_COMPLETED"), "event_id": "evt-eval-1",
            "task_ref": "task-A",
            **_POSITIVE_EXTRAS["CHANGEGATE_EVALUATION_COMPLETED"]}
    inst["decision_ref"] = _dref(task_ref="task-B")
    assert not list(validator.iter_errors(inst)), "schema shape is still valid"
    assert any("envelope task_ref" in e for e in validate_event_chain([inst]))


def test_candidate_subject_digest_must_match_decision_candidate_digest():
    inst = {**_base_envelope("CHANGEGATE_EVALUATION_COMPLETED"), "event_id": "evt-eval-1",
            **_POSITIVE_EXTRAS["CHANGEGATE_EVALUATION_COMPLETED"]}
    inst["subject_ref"] = {"namespace": "changegate", "kind": "git_candidate",
                           "value": "cand-1", "digest": canonical_digest({"c": "other"})}
    assert any("subject_ref.digest" in e for e in validate_event_chain([inst]))


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
    assert suite["schema_version"] == "changegate-merge-eligibility-golden.v6"
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
    "repository_snapshot_digest", "verification_bundle_digest",
    "approval_digest_or_sentinel",
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
    without = {**bindings, "approval_digest_or_sentinel": NO_APPROVAL_SENTINEL}
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
    """The R4 fingerprint is the canonical digest of the COMPLETE machine manifest (§27.3);
    the manifest binds every load-bearing semantic area. A metadata-only acceptance patch
    preserves it; any semantic change alters it."""
    return canonical_digest(suite["slice_1a_semantic_manifest"])


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


# ---------------------------------------------------------------------------
# Semantic manifest — the complete manifest binds the executable artifacts (H-R3V-02)
# ---------------------------------------------------------------------------

def test_semantic_manifest_binds_every_load_bearing_area():
    suite = _fixture()
    m = suite["slice_1a_semantic_manifest"]
    assert m["manifest_version"] == "changegate.slice1a.semantic-manifest.v1"
    assert set(m) == {"manifest_version", "policy_semantics", "deterministic_identity",
                      "replay", "event_semantics", "causal_semantics", "golden_semantics"}
    # POLICY: taxonomy/ranks/dispositions match the reason_codes table.
    ps = m["policy_semantics"]
    assert ps["precedence_ranks"] == {
        e["code"]: e["precedence_rank"] for e in suite["reason_codes"]
    } == DRAFT_PRECEDENCE_PENDING_OD_S1A_007
    assert ps["default_dispositions"] == DRAFT_DISPOSITION_BY_CODE
    assert ps["fact_state_mapping"] == suite["fact_state_mapping"]
    assert ps["canonical_digest_representation"] == suite["digest_representation"]
    # DETERMINISTIC IDENTITY: the manifest's source-binding set == the test constant AND
    # the executable builder's payload field order.
    di = m["deterministic_identity"]
    assert list(di["source_binding_field_set"]) == list(SOURCE_DIGEST_FIELDS)
    assert di["approval_sentinel"] == NO_APPROVAL_SENTINEL
    bindings, facts, mapping = _green()
    record_payload = policy_record_payload(bindings, facts, mapping)
    assert list(record_payload.keys()) == di["policy_record_payload_field_order"], (
        "manifest payload field order must equal the executable builder's key order"
    )
    # EVENT SEMANTICS: schema digest, decision-ref required, override replacement required.
    es = m["event_semantics"]
    assert es["event_schema_digest"] == canonical_digest(_schema()), (
        "manifest event_schema_digest must equal the digest of the actual event schema"
    )
    assert es["decision_ref_required_fields"] == _schema()["properties"]["decision_ref"]["required"]
    assert es["override_replacement_required_fields"] == (
        _schema()["properties"]["override"]["properties"]
                 ["replacement_decision_ref"]["required"]
    )
    assert set(es["event_type_set"]) == set(EVENT_TYPES)
    # CAUSAL SEMANTICS: SIX-field lineage (incl evaluation_id), multi-root, named controls.
    cs = m["causal_semantics"]
    assert cs["multi_root_support"] is True
    assert set(cs["lineage_field_set"]) == {
        "evaluation_id", "task_ref", "candidate_digest", "decision_digest", "input_digest",
        "policy_record_digest",
    }
    assert set(cs["lineage_field_set"]) == set(_LINEAGE_KEYS)
    # named machine-readable semantic controls (not opaque ids).
    controls = cs["semantic_controls"]
    for c in controls:
        assert set(c) >= {"id", "subject", "required_fields", "predicate", "failure_code"}
    assert "causal_negative_control_ids" not in cs
    assert "replacement_negative_control_ids" not in cs
    # GOLDEN SEMANTICS: one entry per case, matching expectations.
    gs = {g["case_id"]: g for g in m["golden_semantics"]}
    assert set(gs) == {c["case_id"] for c in suite["cases"]}
    for c in suite["cases"]:
        g = gs[c["case_id"]]
        assert g["disposition"] == c["expected_disposition"]
        assert g["decision_authority"] == c["expected_decision_authority"]
        assert g["primary_reason"] == c["expected_primary_reason"]
        assert g["complete_reason_codes"] == c["expected_complete_reason_codes"]


def test_semantic_fingerprint_is_stable_and_reproducible():
    suite = _fixture()
    fp = semantic_fingerprint(suite)
    assert fp == canonical_digest(suite["slice_1a_semantic_manifest"])
    assert fp == semantic_fingerprint(_fixture())
    assert CANONICAL_DIGEST_RE.match(fp)
    gov = suite["acceptance_governance"]
    assert gov["semantic_fingerprint_source"] == "slice_1a_semantic_manifest"
    # the named components are exactly the manifest's semantic areas.
    assert set(gov["semantic_fingerprint_components"]) == (
        set(suite["slice_1a_semantic_manifest"]) - {"manifest_version"}
    )


# ---------------------------------------------------------------------------
# Exact record-shape negative controls (H-R4V-01 / §6)
# ---------------------------------------------------------------------------

def test_policy_record_payload_fields_match_spec_manifest_and_builder():
    suite = _fixture()
    order = suite["slice_1a_semantic_manifest"]["deterministic_identity"][
        "policy_record_payload_field_order"]
    assert tuple(order) == POLICY_RECORD_PAYLOAD_FIELDS
    bindings, facts, mapping = _green()
    assert tuple(policy_record_payload(bindings, facts, mapping).keys()) == (
        POLICY_RECORD_PAYLOAD_FIELDS
    )
    assert tuple(build_policy_record(bindings, facts, mapping).keys()) == (
        POLICY_RECORD_OBJECT_FIELDS
    )
    # the exact approval field is canonical; no alias name appears in the contract.
    assert "approval_digest_or_sentinel" in POLICY_RECORD_PAYLOAD_FIELDS
    assert "approval_digest" not in POLICY_RECORD_PAYLOAD_FIELDS


def test_valid_record_passes_and_shape_drift_is_rejected():
    bindings, facts, mapping = _green()
    record = build_policy_record(bindings, facts, mapping)
    assert validate_policy_record(record) == []

    # 1 renamed approval field, rehashed — rejected.
    renamed = {("approval_digest" if k == "approval_digest_or_sentinel" else k): v
               for k, v in record.items()}
    renamed = _rehash(renamed)
    assert validate_policy_record(renamed), "renamed approval field must fail"
    # 2 missing approval field, rehashed — rejected.
    missing = _rehash({k: v for k, v in record.items()
                       if k != "approval_digest_or_sentinel"})
    assert validate_policy_record(missing), "missing approval field must fail"
    # 3 extra unknown field, rehashed — rejected.
    extra = _rehash({**record, "surprise": 1})
    assert validate_policy_record(extra), "extra field must fail"
    # 4 every canonical field removal is rejected (independent negative per field).
    for field in POLICY_RECORD_PAYLOAD_FIELDS:
        dropped = _rehash({k: v for k, v in record.items() if k != field})
        assert validate_policy_record(dropped), f"missing {field} must fail"
    # 5 duplicate semantic field under another key, rehashed — rejected.
    dup_key = _rehash({**record, "task_id_alias": record["task_id"]})
    assert validate_policy_record(dup_key)
    # 6 wrong type on a canonical field, rehashed — rejected only via shape? type is a
    #   value change; keys stay exact, so it passes key check but the digest recompute is
    #   over the wrong shape only if the caller lies about the digest. A type change that is
    #   rehashed stays self-consistent, so the SHAPE check is the load-bearing guard; a
    #   type contract is enforced by the SCHEMA at the event boundary. Assert the key guard.
    #   (documented: order is normative)
    reordered = {k: record[k] for k in reversed(list(record))}
    assert validate_policy_record(reordered), "reordered keys must fail (order normative)"
    # 7 record digest recomputed over the wrong shape (renamed but NOT rehashed).
    renamed_no_rehash = {("approval_digest" if k == "approval_digest_or_sentinel" else k): v
                         for k, v in record.items()}
    assert validate_policy_record(renamed_no_rehash)
    # 8 self-digest included in the payload (policy_record_digest twice / inside payload).
    #   Adding a second digest-like key breaks the exact key set.
    self_dig = _rehash({**record, "nested_digest": record["policy_record_digest"]})
    assert validate_policy_record(self_dig)
    # 9 runtime metadata included — rejected (extra key -> shape drift).
    runtime = _rehash({**record, "trace_id": "t-1"})
    assert validate_policy_record(runtime)
    # a malicious caller cannot make an invalid record valid by recomputing the digest.
    assert all(validate_policy_record(_rehash(bad)) for bad in (renamed, missing, extra))


def _rehash(record: dict) -> dict:
    payload = {k: v for k, v in record.items() if k != "policy_record_digest"}
    return {**payload, "policy_record_digest": canonical_digest(payload)}


# ---------------------------------------------------------------------------
# Named semantic predicates: validator ↔ manifest equivalence (H-R4V-04 / §14–§15)
# ---------------------------------------------------------------------------

def _run_named_control(control_id: str) -> list[str]:
    """Execute the scenario that the named manifest control governs and return the
    validator errors. For a negative control the returned errors must contain the control's
    failure_code; for a positive control they must be empty. This binds every named manifest
    predicate to an executable validator check."""
    original = _lineage_of(_DECISION_REF)
    evaluation = _root_eval_event()
    base_repl, base_record = _make_replacement(_ROOT_TASK, _ROOT_CANDIDATE, original,
                                               same_input=False, tag="eq")

    def run_override(repl, record):
        return validate_event_chain([evaluation, _override_event("evt-ovr", repl)],
                                    records=_record_registry(record) if record else {})

    # --- record shape ---
    if control_id == "REC-EXACT-KEYS":
        rec = _rehash({("approval_digest" if k == "approval_digest_or_sentinel" else k): v
                       for k, v in build_policy_record(*_green()).items()})
        return validate_policy_record(rec)
    if control_id == "REC-DIGEST-RECOMPUTE":
        rec = build_policy_record(*_green())
        rec = {**rec, "disposition": "REVIEW_REQUIRED"}  # value changed, digest stale
        return validate_policy_record(rec)
    if control_id == "REC-NO-RUNTIME":
        rec = _rehash({**build_policy_record(*_green()), "trace_id": "t-1"})
        return validate_policy_record(rec)
    # --- replacement ---
    if control_id == "RPL-REGISTERED-RECORD":
        return run_override(base_repl, None)                      # no registry
    if control_id == "RPL-RECORD-DIGEST-EQ":
        # keep the record's key (= base_repl.policy_record_digest) but change a field so its
        # recomputed digest no longer matches -> invalid record served under that key.
        bad = {**base_record, "disposition": "REVIEW_REQUIRED"}
        return run_override(base_repl, bad)
    if control_id == "RPL-DECISION-EQ":
        return run_override({**base_repl,
                             "decision_digest": canonical_digest({"mismatch": 1})},
                            base_record)
    if control_id == "RPL-INPUT-EQ":
        return run_override({**base_repl, "input_digest": original["input_digest"]},
                            base_record)
    if control_id == "RPL-TASK-EQ":
        # record built for another task, ref claims the root task -> task mismatch.
        r2, rec2 = _make_replacement("task-OTHER", _ROOT_CANDIDATE, original,
                                     same_input=False, tag="task")
        ref = {**r2, "task_ref": _ROOT_TASK}
        return run_override(ref, rec2)
    if control_id == "RPL-CANDIDATE-EQ":
        r2, rec2 = _make_replacement(_ROOT_TASK, canonical_digest({"c": "OTHER"}), original,
                                     same_input=False, tag="cand")
        ref = {**r2, "candidate_digest": _ROOT_CANDIDATE}
        return run_override(ref, rec2)
    if control_id == "RPL-DECISION-DIFFERS":
        r2, rec2 = _make_replacement(_ROOT_TASK, _ROOT_CANDIDATE, original,
                                     same_input=False, tag="dd")
        ref = {**r2, "decision_digest": original["decision_digest"]}
        return run_override(ref, rec2)
    if control_id == "RPL-RECORD-DIFFERS":
        ref = {**base_repl, "policy_record_digest": original["policy_record_digest"]}
        return run_override(ref, base_record)
    if control_id == "RPL-SAME-INPUT-OK":                          # POSITIVE
        r2, rec2 = _make_replacement(_ROOT_TASK, _ROOT_CANDIDATE, original,
                                     same_input=True, tag="si")
        return run_override(r2, rec2)
    if control_id == "RPL-EVAL-UNIQUE":
        ref = {**base_repl, "evaluation_id": _DECISION_REF["evaluation_id"]}
        return run_override(ref, base_record)
    if control_id == "RPL-ROOT-OWNERSHIP":
        return run_override({**base_repl, "task_ref": "other-task"}, base_record)
    if control_id == "RPL-NO-OP":
        noop = {**base_repl, "decision_digest": original["decision_digest"],
                "input_digest": original["input_digest"],
                "policy_record_digest": original["policy_record_digest"]}
        return run_override(noop, base_record)
    if control_id == "RPL-CANDIDATE-NEW-ROOT":
        return run_override({**base_repl,
                             "candidate_digest": canonical_digest({"c": "z"})}, base_record)
    if control_id == "RPL-PARTIAL-OBJECT":
        v = _validator()
        partial = _override_event("evt-ovr", {"evaluation_id": "e", "task_ref": _ROOT_TASK,
                                  "candidate_digest": _ROOT_CANDIDATE,
                                  "decision_digest": base_repl["decision_digest"]})
        return ["REPLACEMENT_PARTIAL"] if list(v.iter_errors(partial)) else []
    # --- evaluation identity / lineage ---
    A = _root_lineage("task-A", canonical_digest({"c": "A"}), "A")
    if control_id == "EVAL-ID-UNIQUE":
        dup = _dref(evaluation_id="eval-A", task_ref="task-C",
                    candidate_digest=canonical_digest({"c": "C"}),
                    decision_digest=canonical_digest({"d": "C"}),
                    input_digest=canonical_digest({"i": "C"}),
                    policy_record_digest=canonical_digest({"r": "C"}))
        return validate_event_chain([_root_event("evt-A", A), _root_event("evt-C", dup)])
    if control_id == "EVAL-ID-NO-DRIFT":
        drift = _evt("evt-drift", "CHANGEGATE_MERGE_ATTEMPTED",
                     {**A, "evaluation_id": "eval-DRIFT"}, evaluation_event_ref="evt-A",
                     outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"})
        return validate_event_chain([_root_event("evt-A", A), drift])
    if control_id == "LINEAGE-SIX-FIELDS":
        bad = _evt("evt-att", "CHANGEGATE_MERGE_ATTEMPTED",
                   {**A, "decision_digest": canonical_digest({"d": "X"})},
                   evaluation_event_ref="evt-A",
                   outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"})
        return validate_event_chain([_root_event("evt-A", A), bad])
    if control_id == "MULTI-PARENT-LINEAGE":
        return _cross_root_rollback_errors()
    if control_id == "DOWNSTREAM-NO-REVERT":
        override = _override_event("evt-ovr", base_repl)
        revert = _evt("evt-att", "CHANGEGATE_MERGE_ATTEMPTED", original,
                      evaluation_event_ref="evt-ovr",
                      outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"})
        return validate_event_chain([evaluation, override, revert],
                                    records=_record_registry(base_record))
    if control_id == "MULTI-ROOT":                                # POSITIVE
        B = _root_lineage("task-B", canonical_digest({"c": "B"}), "B")
        return validate_event_chain([_root_event("evt-A", A), _root_event("evt-B", B)])
    raise AssertionError(f"no executable scenario for control {control_id!r}")


def _cross_root_rollback_errors() -> list[str]:
    A = _root_lineage("task-A", canonical_digest({"c": "A"}), "A")
    B = _root_lineage("task-B", canonical_digest({"c": "B"}), "B")

    def att(eid, lin, root):
        return _evt(eid, "CHANGEGATE_MERGE_ATTEMPTED", lin, evaluation_event_ref=root,
                    outcome={"status": "SUCCESS", "detail_code": "ATTEMPT_STARTED"})

    merge_A = _evt("evt-A-merge", "CHANGEGATE_MERGE_COMPLETED", A,
                   attempt_event_ref="evt-A-att",
                   outcome={"status": "SUCCESS", "detail_code": "MERGE_OK",
                            "resulting_commit_sha": "c" * 40})
    val_B = _evt("evt-B-val", "CHANGEGATE_POST_MERGE_VALIDATION", B,
                 merge_event_ref="evt-B-merge",
                 outcome={"status": "FAILURE", "detail_code": "CI"})
    merge_B = _evt("evt-B-merge", "CHANGEGATE_MERGE_COMPLETED", B,
                   attempt_event_ref="evt-B-att",
                   outcome={"status": "SUCCESS", "detail_code": "MERGE_OK",
                            "resulting_commit_sha": "d" * 40})
    rollback = _evt("evt-roll", "CHANGEGATE_ROLLBACK_RECORDED", A,
                    merge_event_ref="evt-A-merge", validation_event_ref="evt-B-val",
                    outcome={"status": "SUCCESS", "detail_code": "ROLLED_BACK"})
    chain = [_root_event("evt-A", A), _root_event("evt-B", B), att("evt-A-att", A, "evt-A"),
             merge_A, att("evt-B-att", B, "evt-B"), merge_B, val_B, rollback]
    return validate_event_chain(chain)


def _manifest_controls() -> list[dict]:
    return _fixture()["slice_1a_semantic_manifest"]["causal_semantics"]["semantic_controls"]


def test_every_named_manifest_control_has_an_executable_check():
    ids = {c["id"] for c in _manifest_controls()}
    # every named predicate is executable; the registry covers exactly the manifest set.
    for cid in ids:
        _run_named_control(cid)  # must not raise "no executable scenario"
    # no load-bearing validator rule is missing from the manifest: the failure codes the
    # validator can emit are all declared.
    declared_codes = {c["failure_code"] for c in _manifest_controls()
                      if c["failure_code"]}
    for code in ("RECORD_SHAPE_DRIFT", "RECORD_DIGEST_MISMATCH", "RECORD_RUNTIME_FIELD",
                 "REPLACEMENT_RECORD_MISSING", "REPLACEMENT_DECISION_MISMATCH",
                 "REPLACEMENT_INPUT_MISMATCH", "REPLACEMENT_TASK_MISMATCH",
                 "REPLACEMENT_CANDIDATE_MISMATCH", "REPLACEMENT_DECISION_NOT_CHANGED",
                 "REPLACEMENT_RECORD_NOT_CHANGED", "REPLACEMENT_EVALUATION_NOT_UNIQUE",
                 "REPLACEMENT_ROOT_MISMATCH", "REPLACEMENT_CANDIDATE_CHANGED",
                 "EVALUATION_ID_DUPLICATE", "EVALUATION_ID_DRIFT", "LINEAGE_DIVERGES",
                 "AMBIGUOUS_PREDECESSOR_LINEAGE", "REPLACEMENT_NO_OP",
                 "REPLACEMENT_RECORD_DIGEST_MISMATCH", "REPLACEMENT_PARTIAL"):
        assert code in declared_codes, f"validator failure code {code} not in manifest"


@pytest.mark.parametrize("control", [pytest.param(c, id=c["id"])
                                     for c in _manifest_controls()])
def test_named_control_is_enforced_by_the_validator(control):
    errors = _run_named_control(control["id"])
    if control["failure_code"] is None:            # positive control
        assert errors == [], f"{control['id']} positive control failed: {errors}"
    else:                                          # negative control
        blob = " ".join(errors)
        assert control["failure_code"] in blob, (
            f"{control['id']} expected failure_code {control['failure_code']} in {errors}"
        )


def test_removing_or_changing_any_named_predicate_changes_the_fingerprint():
    suite = _fixture()
    baseline = semantic_fingerprint(suite)
    controls = _manifest_controls()
    for i in range(len(controls)):
        mutated = copy.deepcopy(suite)
        del mutated["slice_1a_semantic_manifest"]["causal_semantics"]["semantic_controls"][i]
        assert semantic_fingerprint(mutated) != baseline, f"removing control {i} kept fp"
    # changing a predicate's failure_code also changes the fingerprint.
    mutated = copy.deepcopy(suite)
    mutated["slice_1a_semantic_manifest"]["causal_semantics"]["semantic_controls"][0][
        "failure_code"] = "CHANGED"
    assert semantic_fingerprint(mutated) != baseline


def test_ten_required_semantic_mutations_are_detected():
    """§15: the ten explicitly required behaviors are each caught by the validator."""
    required = {
        "LINEAGE-SIX-FIELDS": "LINEAGE_DIVERGES",         # 1 evaluation id in lineage
        "EVAL-ID-UNIQUE": "EVALUATION_ID_DUPLICATE",      # 2 duplicate evaluation ids
        "EVAL-ID-NO-DRIFT": "EVALUATION_ID_DRIFT",        # 3 downstream drift
        "RPL-ROOT-OWNERSHIP": "REPLACEMENT_ROOT_MISMATCH",  # 4 replacement from another root
        "RPL-INPUT-EQ": "REPLACEMENT_INPUT_MISMATCH",     # 5 new decision + incoherent input
        "MULTI-PARENT-LINEAGE": "AMBIGUOUS_PREDECESSOR_LINEAGE",  # 6 secondary predecessor
        "REC-EXACT-KEYS": "RECORD_SHAPE_DRIFT",           # 7 weakened record keys
        "RPL-NO-OP": "REPLACEMENT_NO_OP",                 # 8 no-op replacement
        "DOWNSTREAM-NO-REVERT": "diverges",               # 9 downstream revert
        "RPL-REGISTERED-RECORD": "REPLACEMENT_RECORD_MISSING",  # 10 replacement rec recompute
    }
    for cid, expected in required.items():
        errors = _run_named_control(cid)
        assert any(expected in e for e in errors), f"{cid}: {errors}"


def _fingerprint_after(mutate) -> tuple[str, str]:
    """Return (baseline, mutated) fingerprints after applying `mutate` to a fixture copy.
    Independent of any expected-fingerprint value stored in the object."""
    suite = _fixture()
    baseline = semantic_fingerprint(suite)
    mutated = copy.deepcopy(suite)
    mutate(mutated)
    return baseline, semantic_fingerprint(mutated)


def test_fingerprint_changes_for_all_fourteen_forbidden_mutations():
    m = "slice_1a_semantic_manifest"

    def mut_precedence(s):
        s[m]["policy_semantics"]["precedence_ranks"]["AUTHORITY_INVALID"] = 999

    def mut_default_disposition(s):
        s[m]["policy_semantics"]["default_dispositions"]["SCOPE_UNCERTAIN"] = "BLOCK"

    def mut_golden_outcome(s):
        s[m]["golden_semantics"][0]["disposition"] = "REVIEW_REQUIRED"

    def mut_source_binding_set(s):
        s[m]["deterministic_identity"]["source_binding_field_set"].append("extra_digest")

    def mut_mep_input_fields(s):
        s[m]["deterministic_identity"]["merge_eligibility_policy_input_fields"].append("x")

    def mut_record_payload_order(s):
        order = s[m]["deterministic_identity"]["policy_record_payload_field_order"]
        order[1], order[2] = order[2], order[1]

    def mut_replay_invariant(s):
        s[m]["replay"]["replay_invariant_ids"].append("R11")

    def mut_event_schema(s):
        s[m]["event_semantics"]["event_schema_digest"] = canonical_digest({"x": "other"})

    def mut_decision_ref_required(s):
        s[m]["event_semantics"]["decision_ref_required_fields"].append("extra")

    def mut_lineage_field_set(s):
        s[m]["causal_semantics"]["lineage_field_set"].append("extra")

    def mut_override_switch_rule(s):
        s[m]["causal_semantics"]["override_lineage_switch_rule"] = "changed"

    def mut_multi_root(s):
        s[m]["causal_semantics"]["multi_root_support"] = False

    def mut_authority_map(s):
        s[m]["policy_semantics"]["decision_authority_by_mode"]["SHADOW"] = "AUTHORITATIVE"

    def mut_digest_representation(s):
        s[m]["policy_semantics"]["canonical_digest_representation"] = "hex64"

    mutations = {
        "1 precedence": mut_precedence,
        "2 default disposition": mut_default_disposition,
        "3 golden outcome": mut_golden_outcome,
        "4 source-binding set": mut_source_binding_set,
        "5 MEP input fields": mut_mep_input_fields,
        "6 record payload order": mut_record_payload_order,
        "7 replay invariant": mut_replay_invariant,
        "8 event-schema behavior": mut_event_schema,
        "9 decision-ref required": mut_decision_ref_required,
        "10 causal lineage field set": mut_lineage_field_set,
        "11 override-switch rule": mut_override_switch_rule,
        "12 multi-root rule": mut_multi_root,
        "13 decision-authority mapping": mut_authority_map,
        "14 canonical digest representation": mut_digest_representation,
    }
    for name, mutate in mutations.items():
        baseline, changed = _fingerprint_after(mutate)
        assert changed != baseline, f"fingerprint unchanged for mutation {name}"


def test_precedence_change_alters_the_semantic_fingerprint():
    """A precedence swap in the manifest (the fingerprint's sole input) alters it, so a
    precedence change can never be mislabeled as metadata-only."""
    def swap(s):
        ranks = s["slice_1a_semantic_manifest"]["policy_semantics"]["precedence_ranks"]
        ranks["AUTHORITY_INVALID"], ranks["EVIDENCE_TASK_MISMATCH"] = (
            ranks["EVIDENCE_TASK_MISMATCH"], ranks["AUTHORITY_INVALID"])
    baseline, changed = _fingerprint_after(swap)
    assert changed != baseline


def test_metadata_only_change_preserves_the_semantic_fingerprint():
    """A document-status / acceptance-metadata change must NOT alter the fingerprint."""
    def metadata(s):
        s["status"] = "ACCEPTED_BY_OWNER"
        s["policy_version_ref"] = "accepted-2026-07-16"
        s["acceptance_governance"]["exact_artifact_hash_contract"]["note"] = "recorded"
    baseline, changed = _fingerprint_after(metadata)
    assert changed == baseline


def test_exact_artifact_hash_contract_is_declared_without_hardcoded_hashes():
    gov = _fixture()["acceptance_governance"]
    contract = gov["exact_artifact_hash_contract"]
    assert set(contract["compared_files"]) == {
        "data/schemas/changegate_evaluation_event_v1.schema.json",
        "tests/build_harness/test_changegate_slice_1_spec_artifacts.py",
    }
    assert contract["future_hashes_hard_coded"] is False
    # no 64-hex or sha256:-prefixed literal is stored as a "recorded" hash value.
    blob = json.dumps(contract)
    assert not re.search(r"sha256:[0-9a-f]{64}", blob)
    assert not re.search(r"\b[0-9a-f]{64}\b", blob)
    # spec §27.4 defines the comparison contract.
    text = _spec_text()
    assert "### 27.4 Exact-artifact no-semantic-change controls" in text
    assert "does not hard-code any future verifier hash" in " ".join(text.split())


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

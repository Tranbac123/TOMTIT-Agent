"""ChangeGate Slice 1A (R1) — executable validation of the specification artifacts ONLY.

R1-hardened per the independent Sol High review (H-01…H-04, M-01…M-03):

- JSON Schema meta-validation plus positive AND negative event-instance validation for
  every event type (minimal common-envelope-only instances must fail for all seven);
- privacy/reference-grammar rejection cases (no raw source-like content, no empty
  outcome, no raw feedback text);
- total fact-state mapping: every enum value of every EligibilityFact maps to a reason
  or explicitly to none — no state is left to the A2 implementer;
- disjoint evidence accounting invariants per golden case;
- an INDEPENDENT test-only semantic oracle that derives each case's complete reason set,
  primary reason, disposition and decision authority from its facts alone (never from
  the case's own expectations), plus mutation-negative tests proving the oracle detects
  semantic drift;
- replay-identity invariants: decision digest independent of trace identity; trace
  digest sensitive to trace metadata.

These tests validate artifacts only. The oracle is an acceptance-test oracle, NOT the
future production evaluator (Production Implementation: NOT_STARTED).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]

SPEC_PATH = ROOT / "docs/strategy/CHANGEGATE_VERTICAL_MVP_SLICE_1_POLICY_SPEC.md"
FIXTURE_PATH = ROOT / "data/evals/changegate_merge_eligibility_golden_cases.json"
SCHEMA_PATH = ROOT / "data/schemas/changegate_evaluation_event_v1.schema.json"

DISPOSITIONS = ("ELIGIBLE_TO_MERGE_UNDER_POLICY", "REVIEW_REQUIRED", "BLOCK")
AUTHORITIES = ("AUTHORITATIVE", "ADVISORY_ONLY")

EVENT_TYPES = (
    "CHANGEGATE_EVALUATION_COMPLETED",
    "CHANGEGATE_REVIEW_OVERRIDDEN",
    "CHANGEGATE_MERGE_ATTEMPTED",
    "CHANGEGATE_MERGE_COMPLETED",
    "CHANGEGATE_POST_MERGE_VALIDATION",
    "CHANGEGATE_ROLLBACK_RECORDED",
    "CHANGEGATE_USER_FEEDBACK_RECORDED",
)

REQUIRED_REASON_CODES = {
    "REQUIRED_EVIDENCE_MISSING", "REQUIRED_EVIDENCE_INVALID",
    "EVIDENCE_TASK_MISMATCH", "EVIDENCE_RUN_MISMATCH", "EVIDENCE_CANDIDATE_MISMATCH",
    "EVIDENCE_PROVENANCE_INVALID", "EVIDENCE_DUPLICATE_IDENTITY",
    "CANDIDATE_STALE", "TASK_CONTEXT_STALE", "REPOSITORY_CONTEXT_MISMATCH",
    "RELEASE_STATE_NOT_CLEAN",
    "SCOPE_VIOLATION", "SCOPE_UNCERTAIN",
    "APPROVAL_MISSING", "APPROVAL_STALE",
    "AUTHORITY_INVALID",
    "VERIFIER_NOT_INDEPENDENT", "VERIFIER_INDEPENDENCE_UNKNOWN",
    "POLICY_CONTEXT_STALE", "REQUIRED_CONTEXT_INCOMPLETE",
}

OD_S1A_IDS = tuple(f"OD-S1A-00{i}" for i in range(1, 8))

REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Facts the fixture must declare per case; enum facts vs set facts are checked exactly.
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
    "evaluation_mode": ("ENFORCE", "SHADOW"),
}
VERIFIER_IDENTITY_VALUES = ("ATTESTED", "PRESENT_UNATTESTED", "ABSENT", "INVALID")
VERIFIER_INDEPENDENCE_VALUES = ("INDEPENDENT", "NOT_INDEPENDENT", "UNKNOWN")
VIOLATION_TAGS = ("TASK_MISMATCH", "RUN_MISMATCH", "CANDIDATE_MISMATCH",
                  "PROVENANCE_INVALID", "DUPLICATE_IDENTITY")
SET_FACTS = ("required_requirement_ids", "satisfied_requirement_ids",
             "invalid_requirement_ids", "missing_requirement_ids",
             "rejected_evidence_ids", "invalid_provenance_evidence_ids",
             "unexpected_evidence_ids")

# Secret material patterns (case-sensitive on the token shapes themselves).
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN"),
    re.compile(r"PRIVATE KEY"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"eyJhbGciOi"),  # JWT header prefix
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


# ---------------------------------------------------------------------------
# Independent test-only semantic oracle (M-01). Derives the complete reason set,
# primary reason, disposition and decision authority from a case's FACTS plus the
# fixture's normative fact_state_mapping and taxonomy. It never reads a case's
# expected_* fields. It is an acceptance-test oracle, not the production evaluator.
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


def oracle_decision(facts: dict, mapping: dict, taxonomy: list[dict]) -> dict:
    rank = {e["code"]: e["precedence_rank"] for e in taxonomy}
    dispo = {e["code"]: e["default_disposition"] for e in taxonomy}
    reasons = oracle_reason_codes(facts, mapping)
    if reasons:
        primary = min(reasons, key=lambda code: rank[code])
        disposition = (
            "BLOCK" if any(dispo[c] == "BLOCK" for c in reasons)
            else "REVIEW_REQUIRED"
        )
    else:
        primary = None
        disposition = "ELIGIBLE_TO_MERGE_UNDER_POLICY"
    return {
        "complete": sorted(reasons),
        "primary": primary,
        "disposition": disposition,
        "authority": mapping["decision_authority_by_mode"][facts["evaluation_mode"]],
    }


# ---------------------------------------------------------------------------
# Test-only replay-identity oracle (H-02). Canonical-JSON sha256 digests over a
# decision payload (deterministic policy fields only) and a trace payload (which adds
# trace/request identity, timestamp and latency). Artifact-level pin of spec §18 —
# not a production evaluator.
# ---------------------------------------------------------------------------

def _canonical_digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def decision_digest_oracle(facts: dict, mapping: dict, taxonomy: list[dict]) -> str:
    outcome = oracle_decision(facts, mapping, taxonomy)
    payload = {
        "kind": "changegate.merge-eligibility-decision-payload.test-oracle",
        "task_id": "task-r1", "contract_digest": "c" * 64,
        "candidate_digest": "d" * 64,
        "policy_digest": "e" * 64, "policy_version": "v2-draft",
        "evaluator_version": "test-oracle",
        "input_digest": _canonical_digest({"facts": facts}),
        "disposition": outcome["disposition"],
        "decision_authority": outcome["authority"],
        "primary_reason_code": outcome["primary"],
        "complete_reason_codes": outcome["complete"],
        "required_requirement_ids": sorted(facts["required_requirement_ids"]),
        "satisfied_requirement_ids": sorted(facts["satisfied_requirement_ids"]),
        "invalid_requirement_ids": sorted(facts["invalid_requirement_ids"]),
        "missing_requirement_ids": sorted(facts["missing_requirement_ids"]),
    }
    return _canonical_digest(payload)


def trace_digest_oracle(decision_digest: str, trace_meta: dict) -> str:
    payload = {
        "kind": "changegate.evaluation-trace-payload.test-oracle",
        "decision_digest": decision_digest,
        **trace_meta,
    }
    return _canonical_digest(payload)


# ---------------------------------------------------------------------------
# Policy specification document
# ---------------------------------------------------------------------------

def test_policy_spec_exists():
    assert SPEC_PATH.is_file(), f"missing policy spec: {SPEC_PATH}"


def test_policy_spec_status_remains_draft_for_owner_review():
    text = _spec_text()
    assert re.search(r"^Status:\s*DRAFT_FOR_OWNER_REVIEW\s*$", text, re.MULTILINE), (
        "policy spec Status metadata must remain DRAFT_FOR_OWNER_REVIEW; only the "
        "owner may flip it in a separate reviewed change"
    )
    header = "\n".join(text.splitlines()[:25])
    assert "ACCEPTED_BY_OWNER" not in header, (
        "the spec header must not claim owner acceptance"
    )
    assert re.search(
        r"^Production Implementation:\s*NOT_STARTED\s*$", text, re.MULTILINE
    ), "spec must declare Production Implementation: NOT_STARTED"
    assert re.search(r"^Independent Verification:\s*PENDING\s*$", text, re.MULTILINE)


def test_policy_spec_metadata_is_bound_to_baseline():
    text = _spec_text()
    assert "Baseline: 3e72e93bfac8da2ecdb7960a55ae0357135eb61e" in text
    assert re.search(r"^Owner:\s*TranBac\s*$", text, re.MULTILINE)


def test_policy_spec_contains_all_three_dispositions_and_authorities():
    text = _spec_text()
    for disposition in DISPOSITIONS:
        assert disposition in text, f"spec must define disposition {disposition}"
    for authority in AUTHORITIES:
        assert authority in text, f"spec must define decision authority {authority}"
    assert "decision_authority" in text


def test_safe_to_merge_is_absent_as_an_output_term_in_spec():
    # SAFE_TO_MERGE may appear in the spec ONLY on lines that mark it forbidden.
    for lineno, line in enumerate(_spec_text().splitlines(), start=1):
        for term in ("SAFE_TO_MERGE", "VERIFIED_AND_MERGE"):
            if term in line:
                lowered = line.lower()
                assert (
                    "forbidden" in lowered
                    or "must never" in lowered
                    or "must not" in lowered
                ), (
                    f"spec line {lineno} uses {term} outside a forbidding statement: "
                    f"{line!r}"
                )


def test_safe_to_merge_never_appears_in_machine_artifacts():
    for path in (FIXTURE_PATH, SCHEMA_PATH):
        content = path.read_text(encoding="utf-8")
        assert "SAFE_TO_MERGE" not in content, f"{path.name} contains SAFE_TO_MERGE"
        assert "VERIFIED_AND_MERGE" not in content, (
            f"{path.name} contains VERIFIED_AND_MERGE"
        )


def test_policy_spec_keeps_required_normative_invariants():
    """The ADR-001 durable obligations and R1 contract invariants, checked as exact
    normative phrases (not bare keywords)."""
    text = _spec_text()
    # FOLLOWUP obligations.
    assert "FOLLOWUP-P0-9B1-001" in text
    assert "FOLLOWUP-P0-9B1-002" in text
    # required ⊆ verified completeness rule, and the disjoint partition.
    assert "required evidence  ⊆  valid verified evidence bound to the current task" in text
    assert "required_requirement_ids = satisfied ∪ invalid ∪ missing" in text
    assert "pairwise disjoint" in text
    # structural VERIFIED is never merge eligibility.
    assert "never authorization to merge" in text
    # unknown facts never default toward eligibility (whitespace-normalized: the
    # phrase may wrap across lines in the markdown source).
    normalized = " ".join(text.split())
    assert "`UNKNOWN` never defaults toward eligibility" in normalized
    # facts grant no authority; evaluator returns trace as data.
    assert "Facts grant no authority by themselves" in text
    assert "returns the trace as data" in text
    # replay identity: decision digest excludes trace identity.
    assert "same `decision_digest`" in text
    assert "must NOT cover:" in text and "`trace_id`" in text
    # SHADOW authority rule.
    assert "SHADOW  mode → decision_authority = ADVISORY_ONLY" in text
    # feedback cannot mutate active policy.
    assert "automatic policy weakening" in text
    assert "direct active-policy mutation" in text
    # rejected-requirement binding constraint (H-01).
    assert "matched_requirement_id is None" in text
    assert "EligibilityFactDerivationInput" in text
    assert "MergeEligibilityPolicyInput" in text


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
        "## 18. EvaluationTrace", "## 19. Product Event Schema",
        "## 20. Outcome and Feedback Linkage",
        "## 21. Privacy, Security and Redaction", "## 22. Golden Evaluation Matrix",
        "## 23. Proposed A2 Implementation Scope", "## 24. Deferred Decisions",
        "## 25. Owner Decision Points", "## 26. Exit Criteria",
    ]
    for section in required_sections:
        assert section in text, f"spec is missing required section {section!r}"


def test_policy_spec_cites_deferred_owner_decisions_without_resolving_them():
    text = _spec_text()
    for decision_id in ("OD-G1-001", "OD-G1-002", "OD-G1-003", "OD-G1-004"):
        assert decision_id in text, f"spec must cite deferred decision {decision_id}"


def test_owner_review_is_still_required_and_all_od_points_registered():
    text = _spec_text()
    assert "PENDING_OWNER_DECISION" in text
    for od in OD_S1A_IDS:
        assert od in text, f"spec must list owner decision point {od}"


# ---------------------------------------------------------------------------
# Product event schema — meta-validation, positive and negative instances
# ---------------------------------------------------------------------------

def _base_envelope(event_type: str) -> dict:
    return {
        "event_id": "evt-1",
        "event_type": event_type,
        "occurred_at": "2026-07-14T00:00:00Z",
        "schema_version": "changegate-evaluation-event.v1",
        "product": "changegate",
        "task_ref": "task-r1",
        "subject_ref": {
            "namespace": "changegate", "kind": "git_candidate", "value": "cand-1",
            "digest": None,
        },
        "provenance": {"emitter": "cli", "emitter_version": "0.1.0",
                       "trace_id": None, "request_id": None},
        "privacy_classification": "INTERNAL",
    }


_DECISION_REF = {
    "evaluation_id": "eval-1", "trace_id": "trace-1",
    "decision_digest": "a" * 64, "disposition": "BLOCK",
    "decision_authority": "AUTHORITATIVE",
    "primary_reason_code": "SCOPE_VIOLATION", "evaluation_mode": "ENFORCE",
}
_OUTCOME = {"status": "SUCCESS", "detail_code": "EVALUATION_OK", "target_ref": None}
_FEEDBACK = {"verdict": "DISAGREE", "category_code": "DISPUTED_BLOCK",
             "reason_code": None, "actor_ref": "user-1", "comment_digest": None}
_OVERRIDE = {"actor_ref": "owner-1", "reason_code": "SCOPE_EXCEPTION",
             "new_decision_digest": None, "exception_ref": "exc-1",
             "expires_at": "2026-08-01T00:00:00Z"}

_POSITIVE_EXTRAS: dict[str, dict] = {
    "CHANGEGATE_EVALUATION_COMPLETED": {
        "decision_ref": _DECISION_REF, "context_digest": "b" * 64,
        "policy_version": "changegate-policy.v2-draft", "evaluator_version": "0.1.0",
        "outcome": _OUTCOME,
    },
    "CHANGEGATE_REVIEW_OVERRIDDEN": {"decision_ref": _DECISION_REF,
                                     "override": _OVERRIDE},
    "CHANGEGATE_MERGE_ATTEMPTED": {"decision_ref": _DECISION_REF, "outcome": _OUTCOME},
    "CHANGEGATE_MERGE_COMPLETED": {"decision_ref": _DECISION_REF, "outcome": _OUTCOME},
    "CHANGEGATE_POST_MERGE_VALIDATION": {
        "decision_ref": _DECISION_REF, "merge_event_ref": "evt-0", "outcome": _OUTCOME,
    },
    "CHANGEGATE_ROLLBACK_RECORDED": {
        "decision_ref": _DECISION_REF, "merge_event_ref": "evt-0",
        "outcome": {"status": "SUCCESS", "detail_code": "ROLLBACK_CLEAN",
                    "target_ref": None},
    },
    "CHANGEGATE_USER_FEEDBACK_RECORDED": {"decision_ref": _DECISION_REF,
                                          "feedback": _FEEDBACK},
}


def test_event_schema_meta_validates_as_draft_2020_12():
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    assert schema.get("type") == "object"
    assert schema.get("additionalProperties") is False
    assert any("if" in clause for clause in schema.get("allOf", [])), (
        "schema must use per-event conditional constraints"
    )


def test_event_schema_has_fixed_version_and_all_event_types():
    schema = _schema()
    assert schema["properties"]["schema_version"]["const"] == (
        "changegate-evaluation-event.v1"
    )
    assert "schema_version" in schema["required"]
    assert set(schema["properties"]["event_type"]["enum"]) == set(EVENT_TYPES)


def test_event_schema_requires_privacy_classification():
    schema = _schema()
    assert "privacy_classification" in schema["required"]
    assert set(schema["properties"]["privacy_classification"]["enum"]) == {
        "PUBLIC", "INTERNAL", "SENSITIVE",
    }


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_minimal_unlinked_instance_is_rejected_for_every_event_type(event_type):
    validator = _validator()
    assert not _is_valid(validator, _base_envelope(event_type)), (
        f"{event_type} must not validate with only the common envelope "
        "(no decision/outcome/feedback linkage)"
    )


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_fully_linked_instance_is_accepted_for_every_event_type(event_type):
    validator = _validator()
    instance = {**_base_envelope(event_type), **_POSITIVE_EXTRAS[event_type]}
    errors = list(validator.iter_errors(instance))
    assert not errors, f"{event_type} positive instance rejected: {errors[0].message}"


def test_event_negative_linkage_cases_are_rejected():
    validator = _validator()
    negatives = {
        "evaluation without decision_ref": {
            **_base_envelope("CHANGEGATE_EVALUATION_COMPLETED"),
            "context_digest": "b" * 64, "policy_version": "v",
            "evaluator_version": "v", "outcome": _OUTCOME,
        },
        "evaluation with null outcome": {
            **_base_envelope("CHANGEGATE_EVALUATION_COMPLETED"),
            "decision_ref": _DECISION_REF, "context_digest": "b" * 64,
            "policy_version": "v", "evaluator_version": "v", "outcome": None,
        },
        "merge completed without outcome": {
            **_base_envelope("CHANGEGATE_MERGE_COMPLETED"),
            "decision_ref": _DECISION_REF,
        },
        "feedback with null feedback": {
            **_base_envelope("CHANGEGATE_USER_FEEDBACK_RECORDED"),
            "decision_ref": _DECISION_REF, "feedback": None,
        },
        "feedback without decision_ref": {
            **_base_envelope("CHANGEGATE_USER_FEEDBACK_RECORDED"),
            "feedback": _FEEDBACK,
        },
        "override without override object": {
            **_base_envelope("CHANGEGATE_REVIEW_OVERRIDDEN"),
            "decision_ref": _DECISION_REF,
        },
        "rollback without prior merge reference": {
            **_base_envelope("CHANGEGATE_ROLLBACK_RECORDED"),
            "decision_ref": _DECISION_REF, "outcome": _OUTCOME,
        },
        "post-merge validation without merge reference": {
            **_base_envelope("CHANGEGATE_POST_MERGE_VALIDATION"),
            "decision_ref": _DECISION_REF, "outcome": _OUTCOME,
        },
        "exception without expiry": {
            **_base_envelope("CHANGEGATE_REVIEW_OVERRIDDEN"),
            "decision_ref": _DECISION_REF,
            "override": {**_OVERRIDE, "expires_at": None},
        },
        "override naming neither new decision nor exception": {
            **_base_envelope("CHANGEGATE_REVIEW_OVERRIDDEN"),
            "decision_ref": _DECISION_REF,
            "override": {"actor_ref": "owner-1", "reason_code": "X",
                         "new_decision_digest": None, "exception_ref": None,
                         "expires_at": None},
        },
    }
    for name, instance in negatives.items():
        assert not _is_valid(validator, instance), f"negative accepted: {name}"


def test_event_privacy_and_reference_grammar_rejections():
    validator = _validator()
    source_like = "def steal():\n    return open('/etc/passwd').read()"
    base = {**_base_envelope("CHANGEGATE_MERGE_ATTEMPTED"),
            "decision_ref": _DECISION_REF, "outcome": _OUTCOME}
    negatives = {
        "source-like subject_ref.value": {
            **base,
            "subject_ref": {"namespace": "x", "kind": "y", "value": source_like},
        },
        "whitespace in run_ref": {**base, "run_ref": "run 1"},
        "newline in event_id": {**base, "event_id": "evt\n1"},
        "overlong task_ref": {**base, "task_ref": "t" * 200},
        "empty outcome object": {**base, "outcome": {}},
        "outcome without machine-readable code": {
            **base, "outcome": {"status": "SUCCESS"},
        },
        "prose detail_code": {
            **base, "outcome": {"status": "SUCCESS",
                                "detail_code": "it worked fine today"},
        },
        "raw feedback text property": {
            **_base_envelope("CHANGEGATE_USER_FEEDBACK_RECORDED"),
            "decision_ref": _DECISION_REF,
            "feedback": {**_FEEDBACK, "text": "raw user rant"},
        },
        "uppercase digest": {
            **base,
            "decision_ref": {**_DECISION_REF, "decision_digest": "A" * 64},
        },
        "unknown top-level property": {**base, "raw_prompt": "hi"},
    }
    for name, instance in negatives.items():
        assert not _is_valid(validator, instance), f"negative accepted: {name}"


def test_event_schema_defines_no_raw_content_fields():
    """Digest-and-reference only: the envelope must not define fields for raw prompts,
    source contents, secrets, credentials, or entire command output."""
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
        lowered = name.lower()
        for fragment in forbidden_fragments:
            assert fragment not in lowered, (
                f"event schema defines a raw-content field {name!r}"
            )


def test_event_schema_dispositions_and_authorities_are_the_authorized_vocabulary():
    schema = _schema()
    decision_ref = schema["properties"]["decision_ref"]
    dispositions = decision_ref["properties"]["disposition"]["enum"]
    assert set(v for v in dispositions if v is not None) == set(DISPOSITIONS)
    authorities = decision_ref["properties"]["decision_authority"]["enum"]
    assert set(v for v in authorities if v is not None) == set(AUTHORITIES)


# ---------------------------------------------------------------------------
# Golden evaluation fixture — structure, taxonomy, coverage
# ---------------------------------------------------------------------------

def test_golden_fixture_is_valid_json_with_version_and_status():
    suite = _fixture()
    assert suite["schema_version"] == "changegate-merge-eligibility-golden.v2"
    assert suite["status"] == "DRAFT_FOR_OWNER_REVIEW"
    assert suite["policy_spec"] == (
        "docs/strategy/CHANGEGATE_VERTICAL_MVP_SLICE_1_POLICY_SPEC.md"
    )
    assert list(suite["dispositions"]) == list(DISPOSITIONS)
    assert list(suite["decision_authorities"]) == list(AUTHORITIES)


def test_golden_fixture_case_ids_are_unique_and_at_least_25_cases():
    cases = _fixture()["cases"]
    assert len(cases) >= 25, f"expected >= 25 golden cases, found {len(cases)}"
    ids = [c["case_id"] for c in cases]
    assert len(set(ids)) == len(ids), "duplicate case_id in golden fixture"


def test_reason_code_taxonomy_is_machine_readable_with_unique_ranks():
    suite = _fixture()
    table_codes = {entry["code"] for entry in suite["reason_codes"]}
    assert table_codes == REQUIRED_REASON_CODES, (
        f"taxonomy mismatch: missing {sorted(REQUIRED_REASON_CODES - table_codes)}, "
        f"extra {sorted(table_codes - REQUIRED_REASON_CODES)}"
    )
    for entry in suite["reason_codes"]:
        assert REASON_CODE_RE.match(entry["code"]), entry["code"]
        assert isinstance(entry["precedence_rank"], int)
        assert entry["default_disposition"] in ("BLOCK", "REVIEW_REQUIRED")
        assert entry["kind"] in ("FACTUAL", "SEMANTIC")
        assert entry["override_class"] in (
            "NOT_OVERRIDEABLE", "POLICY_EXCEPTION_REQUIRED", "HUMAN_REVIEW_RESOLVABLE",
        )
    ranks = [entry["precedence_rank"] for entry in suite["reason_codes"]]
    assert len(set(ranks)) == len(ranks), "precedence ranks must be unique"


def test_every_declared_fact_state_is_mapped_and_totality_holds():
    """Total fact-state mapping (spec §6.4): every enum value of every fact maps to a
    reason or explicitly to none; the verifier combination rule is total over all 12
    identity × independence combinations; set facts are all classified."""
    mapping = _fixture()["fact_state_mapping"]
    assert set(mapping["enum_facts"]) == set(ENUM_FACT_VALUES)
    taxonomy_codes = {e["code"] for e in _fixture()["reason_codes"]}
    for fact, values in ENUM_FACT_VALUES.items():
        table = mapping["enum_facts"][fact]
        assert set(table) == set(values), f"{fact}: mapped states != declared states"
        for value, code in table.items():
            assert code is None or code in taxonomy_codes, f"{fact}={value} -> {code}"
    assert set(mapping["violation_tag_reasons"]) == set(VIOLATION_TAGS)
    for tag, code in mapping["violation_tag_reasons"].items():
        assert code in taxonomy_codes, f"tag {tag} -> {code}"
    assert set(mapping["set_facts"]) == set(SET_FACTS), "set facts must be classified"
    for set_fact, code in mapping["set_facts"].items():
        assert code is None or code in taxonomy_codes, f"{set_fact} -> {code}"
    # Verifier rule totality: every identity/independence combination hits a rule.
    assert list(mapping["verifier_identity_values"]) == list(VERIFIER_IDENTITY_VALUES)
    assert list(mapping["verifier_independence_values"]) == list(
        VERIFIER_INDEPENDENCE_VALUES
    )
    for identity in VERIFIER_IDENTITY_VALUES:
        for independence in VERIFIER_INDEPENDENCE_VALUES:
            matched = False
            for rule in mapping["verifier_rule"]:
                if identity in rule["identity"] and (
                    rule["independence"] == "*"
                    or independence in rule["independence"]
                ):
                    assert rule["reason"] is None or rule["reason"] in taxonomy_codes
                    matched = True
                    break
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
        assert isinstance(c["expected_complete_reason_codes"], list), cid
        assert isinstance(c["expected_event_assertions"], dict), cid
        assert isinstance(c["owner_decisions_pending"], list), cid
        assert c["summary"].strip(), cid
        for code in c["expected_complete_reason_codes"]:
            assert REASON_CODE_RE.match(code), f"{cid}: {code!r}"


def test_disjoint_evidence_accounting_invariants_hold_per_case():
    """Spec §6.1: required = satisfied ∪ invalid ∪ missing, pairwise disjoint;
    invalid-provenance record ids are a subset of rejected record ids."""
    for c in _fixture()["cases"]:
        cid = c["case_id"]
        f = c["policy_input_facts"]
        required = set(f["required_requirement_ids"])
        satisfied = set(f["satisfied_requirement_ids"])
        invalid = set(f["invalid_requirement_ids"])
        missing = set(f["missing_requirement_ids"])
        assert required == satisfied | invalid | missing, f"{cid}: partition broken"
        assert not (satisfied & invalid), cid
        assert not (satisfied & missing), cid
        assert not (invalid & missing), cid
        assert set(f["invalid_provenance_evidence_ids"]) <= set(
            f["rejected_evidence_ids"]
        ), f"{cid}: invalid-provenance ids must be rejected record ids"
        # INCOHERENT ⇔ violations non-empty.
        assert (f["evidence_context_status"] == "INCOHERENT") == bool(
            f["evidence_context_violations"]
        ), f"{cid}: INCOHERENT must coincide with violation tags"


# ---------------------------------------------------------------------------
# Independent semantic oracle over every golden case (M-01)
# ---------------------------------------------------------------------------

def test_oracle_derives_every_case_expectation_from_facts_alone():
    suite = _fixture()
    mapping = suite["fact_state_mapping"]
    taxonomy = suite["reason_codes"]
    for c in suite["cases"]:
        cid = c["case_id"]
        derived = oracle_decision(c["policy_input_facts"], mapping, taxonomy)
        assert derived["complete"] == c["expected_complete_reason_codes"], (
            f"{cid}: oracle derived {derived['complete']} from facts, fixture expects "
            f"{c['expected_complete_reason_codes']}"
        )
        assert derived["primary"] == c["expected_primary_reason"], cid
        assert derived["disposition"] == c["expected_disposition"], cid
        assert derived["authority"] == c["expected_decision_authority"], cid


def test_oracle_is_total_over_every_single_fact_deviation():
    """Run the oracle over a synthesized green fact set with every enum value of every
    fact substituted one at a time: the oracle must produce a defined result for each,
    proving no fact state is left unmapped for the A2 implementer."""
    suite = _fixture()
    mapping = suite["fact_state_mapping"]
    taxonomy = suite["reason_codes"]
    green = next(
        c for c in suite["cases"] if c["case_id"] == "GC-S1-001"
    )["policy_input_facts"]
    for fact, values in ENUM_FACT_VALUES.items():
        for value in values:
            facts = copy.deepcopy(green)
            facts[fact] = value
            if fact == "evidence_context_status" and value == "INCOHERENT":
                facts["evidence_context_violations"] = ["TASK_MISMATCH"]
            outcome = oracle_decision(facts, mapping, taxonomy)
            assert outcome["disposition"] in DISPOSITIONS, f"{fact}={value}"
    for identity in VERIFIER_IDENTITY_VALUES:
        for independence in VERIFIER_INDEPENDENCE_VALUES:
            facts = copy.deepcopy(green)
            facts["verifier_identity_status"] = identity
            facts["verifier_independence_status"] = independence
            outcome = oracle_decision(facts, mapping, taxonomy)
            assert outcome["disposition"] in DISPOSITIONS, (identity, independence)


# ---------------------------------------------------------------------------
# Mutation-negative tests: the oracle must DETECT semantic drift (M-01/M-02)
# ---------------------------------------------------------------------------

def _oracle_for(case: dict) -> dict:
    suite = _fixture()
    return oracle_decision(
        case["policy_input_facts"], suite["fact_state_mapping"], suite["reason_codes"]
    )


def _case(case_id: str) -> dict:
    return copy.deepcopy(
        next(c for c in _fixture()["cases"] if c["case_id"] == case_id)
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
    mutated = _case("GC-S1-001")
    mutated["policy_input_facts"]["evaluation_mode"] = "SHADOW"
    derived = _oracle_for(mutated)
    assert derived["authority"] == "ADVISORY_ONLY"
    assert derived["authority"] != mutated["expected_decision_authority"]


def test_mutation_adding_invalid_provenance_without_expected_reason_is_detected():
    mutated = _case("GC-S1-001")
    facts = mutated["policy_input_facts"]
    facts["rejected_evidence_ids"] = ["ev-forged"]
    facts["invalid_provenance_evidence_ids"] = ["ev-forged"]
    derived = _oracle_for(mutated)
    assert "EVIDENCE_PROVENANCE_INVALID" in derived["complete"]
    assert derived["complete"] != mutated["expected_complete_reason_codes"]


# ---------------------------------------------------------------------------
# Replay-identity invariants (H-02)
# ---------------------------------------------------------------------------

def test_replay_same_input_different_trace_ids_same_decision_digest():
    suite = _fixture()
    facts = next(
        c for c in suite["cases"] if c["case_id"] == "GC-S1-001"
    )["policy_input_facts"]
    d1 = decision_digest_oracle(facts, suite["fact_state_mapping"],
                                suite["reason_codes"])
    d2 = decision_digest_oracle(facts, suite["fact_state_mapping"],
                                suite["reason_codes"])
    assert d1 == d2
    t1 = trace_digest_oracle(d1, {"trace_id": "trace-aaa", "evaluation_id": "e-1",
                                  "request_id": "r-1",
                                  "timestamp": "2026-07-14T00:00:00Z",
                                  "evaluation_latency_ms": 3})
    t2 = trace_digest_oracle(d2, {"trace_id": "trace-bbb", "evaluation_id": "e-2",
                                  "request_id": "r-2",
                                  "timestamp": "2026-07-14T01:00:00Z",
                                  "evaluation_latency_ms": 9})
    # Same decision identity even though every trace identity differs.
    assert t1 != t2


def test_replay_policy_fact_change_changes_decision_digest():
    suite = _fixture()
    green = next(
        c for c in suite["cases"] if c["case_id"] == "GC-S1-001"
    )["policy_input_facts"]
    dirty = copy.deepcopy(green)
    dirty["repository_release_clean"] = "DIRTY"
    d_green = decision_digest_oracle(green, suite["fact_state_mapping"],
                                     suite["reason_codes"])
    d_dirty = decision_digest_oracle(dirty, suite["fact_state_mapping"],
                                     suite["reason_codes"])
    assert d_green != d_dirty


def test_replay_trace_metadata_change_never_changes_decision_digest():
    suite = _fixture()
    facts = next(
        c for c in suite["cases"] if c["case_id"] == "GC-S1-032"
    )["policy_input_facts"]
    digest_before = decision_digest_oracle(facts, suite["fact_state_mapping"],
                                           suite["reason_codes"])
    meta_a = {"trace_id": "t-1", "evaluation_id": "e-1", "request_id": "r-1",
              "timestamp": "2026-07-14T00:00:00Z", "evaluation_latency_ms": 1}
    meta_b = {**meta_a, "trace_id": "t-2", "evaluation_latency_ms": 500}
    digest_after = decision_digest_oracle(facts, suite["fact_state_mapping"],
                                          suite["reason_codes"])
    assert digest_before == digest_after
    assert trace_digest_oracle(digest_before, meta_a) != trace_digest_oracle(
        digest_before, meta_b
    )


# ---------------------------------------------------------------------------
# Coverage: reason codes, owner decisions, policy boundaries
# ---------------------------------------------------------------------------

def test_every_reason_code_is_covered_by_at_least_one_case():
    suite = _fixture()
    used = {
        code for c in suite["cases"] for code in c["expected_complete_reason_codes"]
    }
    table = {e["code"] for e in suite["reason_codes"]}
    uncovered = sorted(table - used)
    assert not uncovered, f"reason codes with no golden coverage: {uncovered}"


def test_every_owner_decision_point_has_a_marked_case():
    suite = _fixture()
    marked = {
        od for c in suite["cases"] for od in c["owner_decisions_pending"]
    }
    missing = sorted(set(OD_S1A_IDS) - marked)
    assert not missing, f"OD-S1A decisions with no marked golden case: {missing}"
    # GC-S1-021 (multi-failure precedence) must be marked for OD-S1A-007.
    gc21 = next(c for c in suite["cases"] if c["case_id"] == "GC-S1-021")
    assert "OD-S1A-007" in gc21["owner_decisions_pending"]
    # Marked ids must be registered in the spec.
    spec_text = _spec_text()
    for od in marked:
        assert re.match(r"^OD-S1A-\d{3}$", od), od
        assert od in spec_text, f"{od} is marked in the fixture but not in the spec"


def test_all_three_dispositions_and_both_authorities_are_covered():
    cases = _fixture()["cases"]
    assert {c["expected_disposition"] for c in cases} == set(DISPOSITIONS)
    assert {c["expected_decision_authority"] for c in cases} == set(AUTHORITIES)


def _cases_by_tag(tag: str) -> list[dict]:
    return [c for c in _fixture()["cases"] if tag in c.get("tags", [])]


def test_empty_mandatory_bundle_case_exists():
    cases = _cases_by_tag("empty_bundle_with_requirements")
    assert cases, "missing the empty-bundle-with-mandatory-evidence case"
    for c in cases:
        facts = c["policy_input_facts"]
        assert facts["required_requirement_ids"], c["case_id"]
        assert facts["satisfied_requirement_ids"] == [], c["case_id"]
        assert c["expected_disposition"] == "BLOCK", c["case_id"]
        assert c["expected_primary_reason"] == "REQUIRED_EVIDENCE_MISSING", c["case_id"]


def test_no_requirement_empty_bundle_case_exists_and_is_not_blocked_for_emptiness():
    cases = _cases_by_tag("no_requirement_empty_bundle")
    assert cases, "missing the no-requirement empty-bundle case"
    for c in cases:
        facts = c["policy_input_facts"]
        assert facts["required_requirement_ids"] == [], c["case_id"]
        assert facts["satisfied_requirement_ids"] == [], c["case_id"]
        assert c["expected_disposition"] != "BLOCK", (
            f"{c['case_id']}: an empty bundle with no requirements must not be "
            "blocked solely for being empty"
        )


def test_structural_verified_with_dirty_repository_case_exists():
    cases = _cases_by_tag("structural_verified_dirty_repository")
    assert cases, "missing the VERIFIED-with-dirty-repository case"
    for c in cases:
        facts = c["policy_input_facts"]
        assert facts["repository_release_clean"] == "DIRTY", c["case_id"]
        assert set(facts["required_requirement_ids"]) <= set(
            facts["satisfied_requirement_ids"]
        ), c["case_id"]
        assert c["expected_disposition"] == "BLOCK", c["case_id"]
        assert c["expected_primary_reason"] == "RELEASE_STATE_NOT_CLEAN", c["case_id"]


def test_multiple_failure_and_mixed_block_review_cases_exist():
    multi = _cases_by_tag("multiple_failure_precedence")
    assert multi, "missing the multiple-failure precedence case"
    for c in multi:
        assert len(c["expected_complete_reason_codes"]) >= 2, c["case_id"]
    mixed = _cases_by_tag("mixed_block_and_review")
    assert mixed, "missing the simultaneous BLOCK+REVIEW_REQUIRED case"
    suite = _fixture()
    dispo = {e["code"]: e["default_disposition"] for e in suite["reason_codes"]}
    for c in mixed:
        kinds = {dispo[code] for code in c["expected_complete_reason_codes"]}
        assert kinds == {"BLOCK", "REVIEW_REQUIRED"}, c["case_id"]
        assert c["expected_disposition"] == "BLOCK", c["case_id"]


def test_shadow_mode_counterfactual_cases_exist_with_advisory_authority():
    eligible = _cases_by_tag("shadow_eligible_counterfactual")
    blocked = _cases_by_tag("shadow_block_counterfactual")
    assert eligible and blocked, "missing SHADOW counterfactual cases"
    for c in eligible + blocked:
        assert c["policy_input_facts"]["evaluation_mode"] == "SHADOW", c["case_id"]
        assert c["expected_decision_authority"] == "ADVISORY_ONLY", c["case_id"]
    assert any(
        c["expected_disposition"] == "ELIGIBLE_TO_MERGE_UNDER_POLICY" for c in eligible
    )
    assert any(c["expected_disposition"] == "BLOCK" for c in blocked)


def test_rejected_and_provenance_boundary_cases_exist():
    rejected_only = _cases_by_tag("rejected_only_requirement")
    assert rejected_only, "missing the rejected-only requirement case"
    for c in rejected_only:
        assert c["expected_primary_reason"] == "REQUIRED_EVIDENCE_INVALID", c["case_id"]
        assert c["policy_input_facts"]["missing_requirement_ids"] == [], (
            f"{c['case_id']}: rejected-only must be invalid, not missing (disjoint)"
        )
    both = _cases_by_tag("valid_and_rejected_same_requirement")
    assert both, "missing the valid+rejected same-requirement case"
    for c in both:
        facts = c["policy_input_facts"]
        assert facts["rejected_evidence_ids"], c["case_id"]
        assert set(facts["required_requirement_ids"]) == set(
            facts["satisfied_requirement_ids"]
        ), c["case_id"]
        assert c["expected_disposition"] == "ELIGIBLE_TO_MERGE_UNDER_POLICY", (
            f"{c['case_id']}: a benign rejection must not taint a satisfied requirement"
        )
    corrupted = _cases_by_tag("satisfied_with_invalid_provenance")
    assert corrupted, "missing the satisfied-plus-invalid-provenance case"
    for c in corrupted:
        assert "EVIDENCE_PROVENANCE_INVALID" in c["expected_complete_reason_codes"], (
            c["case_id"]
        )
        assert c["expected_disposition"] == "BLOCK", c["case_id"]


def test_task_stale_scope_not_evaluated_and_verifier_identity_cases_exist():
    assert _cases_by_tag("task_context_stale"), "missing TASK_CONTEXT_STALE case"
    assert _cases_by_tag("scope_not_evaluated"), "missing scope NOT_EVALUATED case"
    assert _cases_by_tag("scope_semantic_uncertain"), (
        "missing scope SEMANTIC_UNCERTAIN case"
    )
    absent = _cases_by_tag("verifier_identity_absent")
    unattested = _cases_by_tag("verifier_identity_present_unattested")
    assert absent and unattested, "missing verifier identity boundary cases"
    for c in absent:
        assert c["expected_primary_reason"] == "REQUIRED_CONTEXT_INCOMPLETE", c["case_id"]
    for c in unattested:
        assert c["expected_primary_reason"] == "VERIFIER_INDEPENDENCE_UNKNOWN", (
            c["case_id"]
        )
        assert c["expected_disposition"] == "REVIEW_REQUIRED", c["case_id"]


def test_unexpected_evidence_case_is_diagnostic_only_and_pending():
    cases = _cases_by_tag("unexpected_valid_evidence")
    assert cases, "missing the unexpected-valid-evidence case"
    for c in cases:
        assert c["policy_input_facts"]["unexpected_evidence_ids"], c["case_id"]
        assert c["expected_complete_reason_codes"] == [], c["case_id"]
        assert "OD-S1A-006" in c["owner_decisions_pending"], c["case_id"]


def test_feedback_does_not_mutate_policy_case_exists():
    cases = _cases_by_tag("feedback_no_policy_mutation")
    assert cases, "missing the feedback-does-not-mutate-policy case"
    for c in cases:
        assertions = c["expected_event_assertions"]
        assert "CHANGEGATE_USER_FEEDBACK_RECORDED" in assertions["emits"], c["case_id"]
        assert assertions["active_policy_mutated"] is False, c["case_id"]
        assert assertions.get("decision_digest_unchanged") is True, c["case_id"]
        assert c["expected_disposition"] == "BLOCK", c["case_id"]


def test_authority_boundary_case_rejects_caller_authored_decision():
    cases = _cases_by_tag("caller_authored_decision")
    assert cases, "missing the caller-authored-decision authority-boundary case"
    for c in cases:
        assert c["expected_disposition"] == "BLOCK", c["case_id"]
        assert c["expected_primary_reason"] == "AUTHORITY_INVALID", c["case_id"]


def test_fixture_event_assertions_use_only_schema_event_types():
    schema_events = set(_schema()["properties"]["event_type"]["enum"])
    for c in _fixture()["cases"]:
        for event_type in c["expected_event_assertions"].get("emits", []):
            assert event_type in schema_events, (
                f"{c['case_id']} asserts unknown event type {event_type}"
            )


def test_no_artifact_contains_secret_material():
    for path in (FIXTURE_PATH, SCHEMA_PATH, SPEC_PATH):
        content = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            assert not pattern.search(content), (
                f"{path.name} matches secret pattern {pattern.pattern!r}"
            )

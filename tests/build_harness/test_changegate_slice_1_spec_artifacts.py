"""ChangeGate Slice 1A — executable validation of the specification artifacts ONLY.

These tests pin the policy-spec document, the golden evaluation fixture, and the product
event schema against the Slice 1A contract (spec §17 of the task):

- the spec exists, stays DRAFT_FOR_OWNER_REVIEW, and keeps its normative invariants;
- the event schema is valid JSON with a fixed version and the full v1 event vocabulary;
- the golden fixture is valid JSON with >= 25 unique, internally consistent cases whose
  precedence/disposition semantics are deterministic;
- no artifact leaks secret material or the forbidden SAFE_TO_MERGE output vocabulary.

They deliberately do NOT construct or simulate a production eligibility evaluator — the
evaluator does not exist yet (Production Implementation: NOT_STARTED).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SPEC_PATH = ROOT / "docs/strategy/CHANGEGATE_VERTICAL_MVP_SLICE_1_POLICY_SPEC.md"
FIXTURE_PATH = ROOT / "data/evals/changegate_merge_eligibility_golden_cases.json"
SCHEMA_PATH = ROOT / "data/schemas/changegate_evaluation_event_v1.schema.json"

DISPOSITIONS = ("ELIGIBLE_TO_MERGE_UNDER_POLICY", "REVIEW_REQUIRED", "BLOCK")

REQUIRED_EVENT_TYPES = {
    "CHANGEGATE_EVALUATION_COMPLETED",
    "CHANGEGATE_REVIEW_OVERRIDDEN",
    "CHANGEGATE_MERGE_ATTEMPTED",
    "CHANGEGATE_MERGE_COMPLETED",
    "CHANGEGATE_POST_MERGE_VALIDATION",
    "CHANGEGATE_ROLLBACK_RECORDED",
    "CHANGEGATE_USER_FEEDBACK_RECORDED",
}

REQUIRED_REASON_CODES = {
    "REQUIRED_EVIDENCE_MISSING", "REQUIRED_EVIDENCE_INVALID",
    "EVIDENCE_TASK_MISMATCH", "EVIDENCE_RUN_MISMATCH", "EVIDENCE_CANDIDATE_MISMATCH",
    "EVIDENCE_PROVENANCE_INVALID", "EVIDENCE_DUPLICATE_IDENTITY",
    "CANDIDATE_STALE", "REPOSITORY_CONTEXT_MISMATCH", "RELEASE_STATE_NOT_CLEAN",
    "SCOPE_VIOLATION", "SCOPE_UNCERTAIN",
    "APPROVAL_MISSING", "APPROVAL_STALE",
    "AUTHORITY_INVALID",
    "VERIFIER_NOT_INDEPENDENT", "VERIFIER_INDEPENDENCE_UNKNOWN",
    "POLICY_CONTEXT_STALE", "REQUIRED_CONTEXT_INCOMPLETE",
}

REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

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


# ---------------------------------------------------------------------------
# Policy specification document
# ---------------------------------------------------------------------------

def test_policy_spec_exists():
    assert SPEC_PATH.is_file(), f"missing policy spec: {SPEC_PATH}"


def test_policy_spec_status_remains_draft_for_owner_review():
    text = _spec_text()
    assert re.search(r"^Status:\s*DRAFT_FOR_OWNER_REVIEW\s*$", text, re.MULTILINE), (
        "policy spec Status metadata must remain DRAFT_FOR_OWNER_REVIEW; only the owner "
        "may flip it in a separate reviewed change"
    )
    header = "\n".join(text.splitlines()[:20])
    assert "ACCEPTED_BY_OWNER" not in header, (
        "the spec header must not claim owner acceptance"
    )
    assert re.search(
        r"^Production Implementation:\s*NOT_STARTED\s*$", text, re.MULTILINE
    ), "spec must declare Production Implementation: NOT_STARTED"


def test_policy_spec_metadata_is_bound_to_baseline():
    text = _spec_text()
    assert "Baseline: 3e72e93bfac8da2ecdb7960a55ae0357135eb61e" in text
    assert re.search(r"^Owner:\s*TranBac\s*$", text, re.MULTILINE)
    assert re.search(r"^Independent Verification:\s*PENDING\s*$", text, re.MULTILINE)


def test_policy_spec_contains_all_three_dispositions():
    text = _spec_text()
    for disposition in DISPOSITIONS:
        assert disposition in text, f"spec must define disposition {disposition}"


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


def test_policy_spec_keeps_required_followup_invariants():
    """The two ADR-001 durable obligations and the core policy invariants must stay
    stated in the spec verbatim enough to be greppable."""
    text = _spec_text()
    # FOLLOWUP-P0-9B1-002 / ADR-001 §7: structural VERIFIED is not merge eligibility.
    assert "FOLLOWUP-P0-9B1-002" in text
    assert "not" in text and "ELIGIBLE_TO_MERGE_UNDER_POLICY" in text
    # FOLLOWUP-P0-9B1-001 / ADR-001 §8: empty bundle is not completeness; subset rule.
    assert "FOLLOWUP-P0-9B1-001" in text
    assert "⊆" in text or "subset" in text.lower(), (
        "spec must state the required ⊆ verified completeness rule"
    )
    # Unknown mandatory facts never default to eligible.
    assert "never default" in text.lower()
    # Facts must not grant authority by themselves.
    assert "facts grant no authority" in text.lower() or (
        "grant no authority" in text.lower()
    )
    # The evaluator returns the trace as data and does not write to sinks itself.
    assert "returns the trace as data" in text.lower()
    # Feedback must not mutate active policy.
    assert "automatic policy weakening" in text
    assert "direct active-policy mutation" in text


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


def test_owner_review_is_still_required():
    text = _spec_text()
    assert "PENDING_OWNER_DECISION" in text, (
        "spec must mark owner-sensitive semantics PENDING_OWNER_DECISION"
    )
    # Every Slice-1A owner decision point is present.
    for od in ("OD-S1A-001", "OD-S1A-002", "OD-S1A-003", "OD-S1A-004",
               "OD-S1A-005", "OD-S1A-006", "OD-S1A-007"):
        assert od in text, f"spec must list owner decision point {od}"


# ---------------------------------------------------------------------------
# Product event schema
# ---------------------------------------------------------------------------

def test_event_schema_is_valid_json_object():
    schema = _schema()
    assert isinstance(schema, dict)
    assert schema.get("type") == "object"
    assert schema.get("additionalProperties") is False


def test_event_schema_has_fixed_version():
    schema = _schema()
    version = schema["properties"]["schema_version"]
    assert version.get("const") == "changegate-evaluation-event.v1"
    assert "schema_version" in schema["required"]


def test_event_schema_represents_all_required_event_types():
    schema = _schema()
    enum = set(schema["properties"]["event_type"]["enum"])
    missing = REQUIRED_EVENT_TYPES - enum
    assert not missing, f"event schema is missing event types: {sorted(missing)}"


def test_event_schema_requires_privacy_classification():
    schema = _schema()
    assert "privacy_classification" in schema["required"]
    assert set(schema["properties"]["privacy_classification"]["enum"]) == {
        "PUBLIC", "INTERNAL", "SENSITIVE",
    }


def test_event_schema_defines_no_raw_content_fields():
    """Digest-and-reference only: the envelope must not define fields for raw prompts,
    source contents, secrets, credentials, or entire command output."""
    schema = _schema()
    forbidden_fragments = (
        "prompt", "stdout", "stderr", "source_code", "file_content",
        "credential", "secret", "private_key", "command_output", "token",
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


def test_event_schema_dispositions_are_the_authorized_vocabulary():
    schema = _schema()
    decision_ref = schema["properties"]["decision_ref"]
    enum = decision_ref["properties"]["disposition"]["enum"]
    assert set(v for v in enum if v is not None) == set(DISPOSITIONS)


# ---------------------------------------------------------------------------
# Golden evaluation fixture
# ---------------------------------------------------------------------------

def test_golden_fixture_is_valid_json_with_version_and_status():
    suite = _fixture()
    assert suite["schema_version"] == "changegate-merge-eligibility-golden.v1"
    assert suite["status"] == "DRAFT_FOR_OWNER_REVIEW"
    assert suite["policy_spec"] == (
        "docs/strategy/CHANGEGATE_VERTICAL_MVP_SLICE_1_POLICY_SPEC.md"
    )
    assert list(suite["dispositions"]) == list(DISPOSITIONS)


def test_golden_fixture_case_ids_are_unique_and_at_least_25_cases():
    cases = _fixture()["cases"]
    assert len(cases) >= 25, f"expected >= 25 golden cases, found {len(cases)}"
    ids = [c["case_id"] for c in cases]
    assert len(set(ids)) == len(ids), "duplicate case_id in golden fixture"


def test_every_case_has_expected_disposition_and_reasons():
    for c in _fixture()["cases"]:
        cid = c["case_id"]
        assert c["expected_disposition"] in DISPOSITIONS, cid
        assert "expected_primary_reason" in c, cid
        assert isinstance(c["expected_complete_reason_codes"], list), cid
        assert isinstance(c["policy_input_facts"], dict), cid
        assert c["summary"].strip(), cid
        assert "override_class" in c, cid
        assert isinstance(c["expected_event_assertions"], dict), cid
        if c["expected_disposition"] == "ELIGIBLE_TO_MERGE_UNDER_POLICY":
            assert c["expected_primary_reason"] is None, (
                f"{cid}: an eligible decision has no primary reason"
            )
            assert c["expected_complete_reason_codes"] == [], (
                f"{cid}: an eligible decision has an empty complete reason set"
            )
        else:
            assert c["expected_primary_reason"], (
                f"{cid}: non-eligible case needs a primary reason"
            )
            assert c["expected_primary_reason"] in c["expected_complete_reason_codes"], (
                f"{cid}: primary reason must be in the complete reason set"
            )


def test_all_three_dispositions_are_covered_by_cases():
    covered = {c["expected_disposition"] for c in _fixture()["cases"]}
    assert covered == set(DISPOSITIONS)


def test_reason_codes_are_machine_readable_stable_identifiers():
    suite = _fixture()
    table_codes = {entry["code"] for entry in suite["reason_codes"]}
    assert REQUIRED_REASON_CODES <= table_codes, (
        f"missing required reason codes: {sorted(REQUIRED_REASON_CODES - table_codes)}"
    )
    for entry in suite["reason_codes"]:
        assert REASON_CODE_RE.match(entry["code"]), entry["code"]
        assert isinstance(entry["precedence_rank"], int)
        assert entry["default_disposition"] in ("BLOCK", "REVIEW_REQUIRED")
        assert entry["kind"] in ("FACTUAL", "SEMANTIC")
    ranks = [entry["precedence_rank"] for entry in suite["reason_codes"]]
    assert len(set(ranks)) == len(ranks), "precedence ranks must be unique"
    for c in suite["cases"]:
        for code in c["expected_complete_reason_codes"]:
            assert REASON_CODE_RE.match(code), f"{c['case_id']}: {code!r}"
            assert code in table_codes, (
                f"{c['case_id']} uses a reason code missing from the taxonomy: {code}"
            )


def test_precedence_and_disposition_are_deterministic_per_case():
    """Executable form of spec §10/§16: primary = lowest rank in the complete set,
    complete set lexicographically sorted, disposition follows the reason partition."""
    suite = _fixture()
    rank_by_code = {e["code"]: e["precedence_rank"] for e in suite["reason_codes"]}
    dispo_by_code = {e["code"]: e["default_disposition"] for e in suite["reason_codes"]}
    for c in suite["cases"]:
        cid = c["case_id"]
        codes = c["expected_complete_reason_codes"]
        assert codes == sorted(codes), f"{cid}: complete set must be sorted"
        assert len(set(codes)) == len(codes), f"{cid}: complete set must be unique"
        if not codes:
            assert c["expected_disposition"] == "ELIGIBLE_TO_MERGE_UNDER_POLICY", cid
            continue
        expected_primary = min(codes, key=lambda code: rank_by_code[code])
        assert c["expected_primary_reason"] == expected_primary, (
            f"{cid}: primary must be the lowest-rank code "
            f"({expected_primary}, got {c['expected_primary_reason']})"
        )
        dispositions = {dispo_by_code[code] for code in codes}
        expected_disposition = (
            "BLOCK" if "BLOCK" in dispositions else "REVIEW_REQUIRED"
        )
        assert c["expected_disposition"] == expected_disposition, (
            f"{cid}: disposition must follow the reason partition"
        )


def _cases_by_tag(tag: str) -> list[dict]:
    return [c for c in _fixture()["cases"] if tag in c.get("tags", [])]


def test_empty_mandatory_bundle_case_exists():
    cases = _cases_by_tag("empty_bundle_with_requirements")
    assert cases, "missing the empty-bundle-with-mandatory-evidence case"
    for c in cases:
        facts = c["policy_input_facts"]
        assert facts["required_evidence_ids"], c["case_id"]
        assert facts["verified_evidence_ids"] == [], c["case_id"]
        assert c["expected_disposition"] == "BLOCK", c["case_id"]
        assert c["expected_primary_reason"] == "REQUIRED_EVIDENCE_MISSING", c["case_id"]


def test_no_requirement_empty_bundle_case_exists_and_is_not_blocked_for_emptiness():
    cases = _cases_by_tag("no_requirement_empty_bundle")
    assert cases, "missing the no-requirement empty-bundle case"
    for c in cases:
        facts = c["policy_input_facts"]
        assert facts["required_evidence_ids"] == [], c["case_id"]
        assert facts["verified_evidence_ids"] == [], c["case_id"]
        assert c["expected_disposition"] != "BLOCK", (
            f"{c['case_id']}: an empty bundle with no requirements must not be blocked "
            "solely for being empty"
        )


def test_structural_verified_with_dirty_repository_case_exists():
    cases = _cases_by_tag("structural_verified_dirty_repository")
    assert cases, "missing the VERIFIED-with-dirty-repository case"
    for c in cases:
        facts = c["policy_input_facts"]
        assert facts["repository_release_clean"] == "DIRTY", c["case_id"]
        # All required evidence structurally verified — and it still cannot ship.
        assert set(facts["required_evidence_ids"]) <= set(
            facts["verified_evidence_ids"]
        ), c["case_id"]
        assert c["expected_disposition"] == "BLOCK", c["case_id"]
        assert c["expected_primary_reason"] == "RELEASE_STATE_NOT_CLEAN", c["case_id"]


def test_multiple_failure_precedence_case_exists():
    cases = _cases_by_tag("multiple_failure_precedence")
    assert cases, "missing the multiple-failure precedence case"
    for c in cases:
        assert len(c["expected_complete_reason_codes"]) >= 2, c["case_id"]
        assert c["expected_primary_reason"], c["case_id"]


def test_feedback_does_not_mutate_policy_case_exists():
    cases = _cases_by_tag("feedback_no_policy_mutation")
    assert cases, "missing the feedback-does-not-mutate-policy case"
    for c in cases:
        assertions = c["expected_event_assertions"]
        assert "CHANGEGATE_USER_FEEDBACK_RECORDED" in assertions["emits"], c["case_id"]
        assert assertions["active_policy_mutated"] is False, c["case_id"]
        # The valid block stands.
        assert c["expected_disposition"] == "BLOCK", c["case_id"]


def test_authority_boundary_case_rejects_caller_authored_decision():
    cases = _cases_by_tag("caller_authored_decision")
    assert cases, "missing the caller-authored-decision authority-boundary case"
    for c in cases:
        assert c["expected_disposition"] == "BLOCK", c["case_id"]
        assert c["expected_primary_reason"] == "AUTHORITY_INVALID", c["case_id"]


def test_owner_pending_cases_reference_registered_decision_points():
    spec_text = _spec_text()
    pending_cases = [
        c for c in _fixture()["cases"] if c.get("owner_decision_pending")
    ]
    assert pending_cases, (
        "approval-semantics cases must be marked owner_decision_pending"
    )
    for c in pending_cases:
        od = c["owner_decision_pending"]
        assert re.match(r"^OD-S1A-\d{3}$", od), f"{c['case_id']}: bad decision id {od!r}"
        assert od in spec_text, (
            f"{c['case_id']} references {od} which the spec does not register"
        )


def test_no_artifact_contains_secret_material():
    for path in (FIXTURE_PATH, SCHEMA_PATH, SPEC_PATH):
        content = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            assert not pattern.search(content), (
                f"{path.name} matches secret pattern {pattern.pattern!r}"
            )


def test_fixture_event_assertions_use_only_schema_event_types():
    schema_events = set(_schema()["properties"]["event_type"]["enum"])
    for c in _fixture()["cases"]:
        for event_type in c["expected_event_assertions"].get("emits", []):
            assert event_type in schema_events, (
                f"{c['case_id']} asserts unknown event type {event_type}"
            )

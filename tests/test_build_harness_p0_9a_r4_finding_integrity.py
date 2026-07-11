"""P0-9A-R4 — ChangeGate finding integrity + duplicate evidence accounting.

Closes the two Codex R3 re-verification findings:
  R3-CODEX-001 — a forged PASS ChangeGateDecision must not authorize any release action
    when it carries a warning finding, an unknown finding, or a known non-PASS finding
    type relabeled "info".
  R3-CODEX-002 — a valid record and a malformed record sharing the SAME valid evidence_id
    must be counted as a duplicate (before body validation), so the valid record is not
    left matched.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_core.build_harness.change_gate import (
    BLOCK_FINDING_TYPES,
    ChangeGateDecision,
    ChangeGateInput,
    CommandEvidence,
    Finding,
    INFO_FINDING_TYPES,
    REVIEW_FINDING_TYPES,
    evaluate_change_gate,
    producer_finding_types,
    validate_change_gate_decision,
)
from agent_core.build_harness.contracts import load_task_contract
from agent_core.build_harness.process_guard import (
    IntendedAction,
    ProcessGuardInput,
    evaluate_process_guard,
)
from agent_core.build_harness.reports import AgentReport
from agent_core.build_harness.state import TaskState

ROOT = Path(__file__).parent.parent
CONTRACT_PATH = ROOT / "examples/build_harness/task_contract_dependency_scanner.json"
SHA = "0737577a2d2351947f412ed29d73722f18491c89"
CMD = "pytest tests/test_build_harness_p0_9a_core.py"
ALLOWED = ["agent_core/build_harness/dependency_scanner.py"]

# Every legal shipping action and a state/approval combination that is valid for it.
SHIP_MATRIX = [
    (IntendedAction.MERGE, TaskState.READY_FOR_MERGE, True),
    (IntendedAction.PUSH, TaskState.APPROVED, True),
    (IntendedAction.DEPLOY, TaskState.APPROVED, True),
    (IntendedAction.DONE, TaskState.APPROVED, True),
]


def _contract():
    return load_task_contract(CONTRACT_PATH)


def _good_ev(**kw) -> CommandEvidence:
    base = dict(command=CMD, exit_code=0, completed=True, commit_sha=SHA,
                evidence_id="ev-1")
    base.update(kw)
    return CommandEvidence(**base)


class _Raw:
    """Bypass-constructed evidence (skips CommandEvidence validation) for adversarial tests."""
    def __init__(self, **kw):
        self.__dict__.update(dict(command=CMD, exit_code=0, completed=True,
                                  commit_sha=SHA, evidence_id="ev-1",
                                  completed_at=None, artifact_digest=None))
        self.__dict__.update(kw)


def _real_pass_gate():
    return evaluate_change_gate(ChangeGateInput(
        contract=_contract(), changed_files=ALLOWED, expected_commit_sha=SHA,
        test_evidence=[_good_ev()]))


def _forged_pass(findings) -> ChangeGateDecision:
    return ChangeGateDecision(
        decision="PASS", findings=findings,
        matched_required_evidence=[CMD], missing_required_evidence=[],
        rejected_evidence=[], expected_commit_sha=SHA)


def _impl():
    return AgentReport(task_id="BH-P0-A", role="implementer",
                       status="IMPLEMENTED", result="PASS")


def _verifier():
    return AgentReport(task_id="BH-P0-A", role="verifier",
                       status="VERIFIED_PASS", result="PASS")


def _guard(gate, action, state, approved=True):
    return evaluate_process_guard(ProcessGuardInput(
        contract=_contract(), task_state=state,
        implementer_report=_impl(), verifier_report=_verifier(),
        changegate_decision=gate, human_approved=approved, intended_action=action))


# ---------------------------------------------------------------------------
# Finding vocabulary (1-10)
# ---------------------------------------------------------------------------

def test_r4_producer_finding_types_all_classified():
    classified = INFO_FINDING_TYPES | REVIEW_FINDING_TYPES | BLOCK_FINDING_TYPES
    assert producer_finding_types() <= classified
    assert producer_finding_types() - classified == set()


def test_r4_classification_sets_disjoint():
    assert not (INFO_FINDING_TYPES & REVIEW_FINDING_TYPES)
    assert not (REVIEW_FINDING_TYPES & BLOCK_FINDING_TYPES)
    assert not (INFO_FINDING_TYPES & BLOCK_FINDING_TYPES)


def _has_errors(findings) -> bool:
    return bool(validate_change_gate_decision(_contract(), _forged_pass(findings)))


def test_r4_unknown_finding_type_invalidates_pass():
    assert _has_errors([Finding(type="mystery", severity="info", file=None, reason="r")])


def test_r4_unknown_severity_invalidates_pass():
    assert _has_errors([Finding(type="forbidden_path", severity="critical", file=None, reason="r")])


def test_r4_warning_always_invalidates_pass():
    assert _has_errors([Finding(type="out_of_scope", severity="warning", file="f", reason="r")])
    assert _has_errors([Finding(type="unrecognized", severity="warning", file=None, reason="r")])


def test_r4_block_always_invalidates_pass():
    assert _has_errors([Finding(type="forbidden_path", severity="block", file="f", reason="r")])


@pytest.mark.parametrize("block_type", sorted(BLOCK_FINDING_TYPES))
def test_r4_block_type_relabeled_info_invalidates_pass(block_type):
    errors = validate_change_gate_decision(
        _contract(),
        _forged_pass([Finding(type=block_type, severity="info", file=None, reason="r")]))
    assert errors and any("info" in e for e in errors)


@pytest.mark.parametrize("review_type", sorted(REVIEW_FINDING_TYPES))
def test_r4_review_type_relabeled_info_invalidates_pass(review_type):
    errors = validate_change_gate_decision(
        _contract(),
        _forged_pass([Finding(type=review_type, severity="info", file=None, reason="r")]))
    assert errors and any("info" in e for e in errors)


@pytest.mark.parametrize("bad_findings", [
    None, "warning", [{}], [Finding(type="", severity="info", file=None, reason="r")],
])
def test_r4_malformed_findings_invalidate_pass(bad_findings):
    decision = ChangeGateDecision(
        decision="PASS", findings=bad_findings, matched_required_evidence=[CMD],
        missing_required_evidence=[], rejected_evidence=[], expected_commit_sha=SHA)
    assert validate_change_gate_decision(_contract(), decision)


def test_r4_finding_bad_field_types_invalidate_pass():
    class BadFinding:
        type = None; severity = True; file = 5; reason = ""; evidence = 9
    assert _has_errors([BadFinding()])


def test_r4_empty_reason_invalidates_pass():
    assert _has_errors([Finding(type="mystery", severity="info", file=None, reason="")])


# ---------------------------------------------------------------------------
# Release action matrix (11-21)
# ---------------------------------------------------------------------------

_FORGED_FINDINGS = {
    "unknown_warning": Finding(type="unrecognized_review", severity="warning",
                               file=None, reason="unknown review"),
    "forbidden_info": Finding(type="forbidden_path", severity="info",
                              file="forbidden.py", reason="forbidden"),
    "dependency_info": Finding(type="dependency_change", severity="info",
                               file="requirements.txt", reason="dependency changed"),
    "invalid_path_info": Finding(type="invalid_changed_path", severity="info",
                                 file="x", reason="bad path"),
    "duplicate_info": Finding(type="duplicate_evidence_id", severity="info",
                              file=None, reason="dup"),
}


@pytest.mark.parametrize("action, state, approved", SHIP_MATRIX)
@pytest.mark.parametrize("finding_key", sorted(_FORGED_FINDINGS))
def test_r4_forged_pass_blocks_every_action(action, state, approved, finding_key):
    gate = _forged_pass([_FORGED_FINDINGS[finding_key]])
    decision = _guard(gate, action, state, approved)
    assert decision.decision == "BLOCK", (action, finding_key, decision)
    assert "valid_changegate_decision" in decision.missing_steps
    assert finding_key.split("_")[0] in decision.reason or "inconsistent" in decision.reason


# ---------------------------------------------------------------------------
# Duplicate identity accounting (22-29)
# ---------------------------------------------------------------------------

def _mixed_gate():
    return evaluate_change_gate(ChangeGateInput(
        contract=_contract(), changed_files=ALLOWED, expected_commit_sha=SHA,
        test_evidence=[_good_ev(evidence_id="codex-1"),
                       _Raw(evidence_id="codex-1", completed="false")]))


def test_r4_mixed_valid_malformed_same_id_emits_duplicate():
    decision = _mixed_gate()
    assert decision.decision == "BLOCK"
    assert any(f.type == "duplicate_evidence_id" for f in decision.findings)


def test_r4_mixed_valid_malformed_same_id_emits_invalid():
    assert any(f.type == "invalid_evidence" for f in _mixed_gate().findings)


def test_r4_mixed_valid_malformed_same_id_no_match():
    assert _mixed_gate().matched_required_evidence == []


def test_r4_mixed_valid_malformed_same_id_missing_required():
    assert CMD in _mixed_gate().missing_required_evidence


def test_r4_mixed_rejected_evidence_identifies_both():
    reasons = " ".join(r["reason"] for r in _mixed_gate().rejected_evidence)
    assert "malformed" in reasons and "duplicate" in reasons


def test_r4_two_malformed_sharing_valid_id_are_duplicate():
    decision = evaluate_change_gate(ChangeGateInput(
        contract=_contract(), changed_files=ALLOWED, expected_commit_sha=SHA,
        test_evidence=[_Raw(evidence_id="dup", completed="false"),
                       _Raw(evidence_id="dup", exit_code="0")]))
    assert decision.decision == "BLOCK"
    assert any(f.type == "duplicate_evidence_id" for f in decision.findings)


@pytest.mark.parametrize("bad_id", [None, 123, "", "../x", True, "bad id"])
def test_r4_malformed_ids_not_grouped_into_fake_duplicate(bad_id):
    decision = evaluate_change_gate(ChangeGateInput(
        contract=_contract(), changed_files=ALLOWED, expected_commit_sha=SHA,
        test_evidence=[_Raw(evidence_id=bad_id), _Raw(evidence_id=bad_id)]))
    # Malformed ids produce invalid_evidence but never a duplicate identity.
    assert any(f.type == "invalid_evidence" for f in decision.findings)
    assert not any(f.type == "duplicate_evidence_id" for f in decision.findings)


def test_r4_identical_valid_duplicates_still_block():
    decision = evaluate_change_gate(ChangeGateInput(
        contract=_contract(), changed_files=ALLOWED, expected_commit_sha=SHA,
        test_evidence=[_good_ev(), _good_ev()]))
    assert decision.decision == "BLOCK"
    assert any(f.type == "duplicate_evidence_id" for f in decision.findings)


def test_r4_conflicting_valid_duplicates_still_block():
    decision = evaluate_change_gate(ChangeGateInput(
        contract=_contract(), changed_files=ALLOWED, expected_commit_sha=SHA,
        test_evidence=[_good_ev(), _good_ev(exit_code=1)]))
    assert decision.decision == "BLOCK"


# ---------------------------------------------------------------------------
# Valid behavior preserved (30-35)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action, state, approved", SHIP_MATRIX)
def test_r4_genuine_pass_authorizes_legal_action(action, state, approved):
    decision = _guard(_real_pass_gate(), action, state, approved)
    assert decision.decision == "PASS", (action, decision)


def test_r4_valid_non_duplicated_evidence_matches():
    decision = _real_pass_gate()
    assert decision.decision == "PASS"
    assert decision.matched_required_evidence == [CMD]
    assert validate_change_gate_decision(_contract(), decision) == []


def test_r4_real_pass_has_empty_findings():
    assert _real_pass_gate().findings == []


def test_r4_r3_forged_missing_evidence_still_blocks():
    # R3 behavior intact: a PASS claiming matched but with missing evidence is invalid.
    forged = ChangeGateDecision(
        decision="PASS", findings=[], matched_required_evidence=[],
        missing_required_evidence=[CMD], rejected_evidence=[], expected_commit_sha=SHA)
    assert validate_change_gate_decision(_contract(), forged)
    decision = _guard(forged, IntendedAction.MERGE, TaskState.READY_FOR_MERGE)
    assert decision.decision == "BLOCK"

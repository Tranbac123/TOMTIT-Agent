"""P0-9A-R3 — evidence type strictness and decision integrity regressions.

Covers the five reliability-review findings: strict CommandEvidence types (no coercion),
CLI evidence deserialization, duplicate evidence_id fail-closed, ProcessGuard revalidation
of ChangeGateDecision integrity, EvidenceStore structural validation, and exact
AgentReport schema (unknown fields rejected).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_core.build_harness.change_gate import (
    ChangeGateDecision,
    ChangeGateInput,
    CommandEvidence,
    Finding,
    InvalidCommandEvidenceError,
    evaluate_change_gate,
    validate_change_gate_decision,
)
from agent_core.build_harness.cli import main as cli_main
from agent_core.build_harness.contracts import load_task_contract, validate_contract_dict
from agent_core.build_harness.evidence_store import (
    EvidenceCorruptionError,
    EvidenceStore,
    EvidenceStructureError,
)
from agent_core.build_harness.process_guard import (
    IntendedAction,
    ProcessGuardInput,
    evaluate_process_guard,
)
from agent_core.build_harness.reports import AgentReport, parse_agent_report
from agent_core.build_harness.state import TaskState

ROOT = Path(__file__).parent.parent
CONTRACT_PATH = ROOT / "examples/build_harness/task_contract_dependency_scanner.json"
EXPECTED_SHA = "0737577a2d2351947f412ed29d73722f18491c89"
REQUIRED_CMD = "pytest tests/test_build_harness_p0_9a_core.py"
ALLOWED = ["agent_core/build_harness/dependency_scanner.py"]


def _contract():
    return load_task_contract(CONTRACT_PATH)


def _ev(**overrides) -> CommandEvidence:
    base = dict(command=REQUIRED_CMD, exit_code=0, completed=True,
                commit_sha=EXPECTED_SHA, evidence_id="ev-1")
    base.update(overrides)
    return CommandEvidence(**base)


def _gate(evidence, changed=None):
    return evaluate_change_gate(ChangeGateInput(
        contract=_contract(), changed_files=changed or ALLOWED,
        expected_commit_sha=EXPECTED_SHA, test_evidence=evidence,
    ))


def _impl_pass():
    return AgentReport(task_id="BH-P0-A", role="implementer",
                       status="IMPLEMENTED", result="PASS")


def _verifier_pass():
    return AgentReport(task_id="BH-P0-A", role="verifier",
                       status="VERIFIED_PASS", result="PASS")


# ---------------------------------------------------------------------------
# CommandEvidence strict types (1-13)
# ---------------------------------------------------------------------------

def test_r3_valid_exact_types_accepted():
    ev = _ev(completed_at="2026-07-11T00:00:00Z", artifact_digest="sha256:abc")
    assert ev.exit_code == 0 and ev.completed is True


@pytest.mark.parametrize("field, value", [
    ("completed", "false"), ("completed", "true"), ("completed", 0), ("completed", 1),
    ("exit_code", False), ("exit_code", True), ("exit_code", "0"), ("exit_code", 0.0),
    ("evidence_id", 123), ("evidence_id", " "), ("evidence_id", "bad id"),
    ("command", True), ("command", ""), ("command", 5),
    ("commit_sha", None), ("commit_sha", ""),
    ("completed_at", 123), ("completed_at", ""), ("artifact_digest", False),
])
def test_r3_invalid_command_evidence_rejected(field, value):
    with pytest.raises(InvalidCommandEvidenceError):
        _ev(**{field: value})


class _RawEvidence:
    """Duck-typed evidence bypassing CommandEvidence validation (for defensive tests)."""
    def __init__(self, **kw):
        self.__dict__.update(dict(
            command=REQUIRED_CMD, exit_code=0, completed=True,
            commit_sha=EXPECTED_SHA, evidence_id="ev-1", completed_at=None,
            artifact_digest=None,
        ))
        self.__dict__.update(kw)


def test_r3_malformed_evidence_does_not_crash_gate():
    decision = _gate([_RawEvidence(completed="false")])
    assert decision.decision != "PASS"
    assert any(f.type == "invalid_evidence" for f in decision.findings)


def test_r3_malformed_evidence_cannot_produce_pass():
    for bad in (_RawEvidence(exit_code="0"), _RawEvidence(evidence_id=123),
                _RawEvidence(commit_sha=None)):
        decision = _gate([bad])
        assert decision.decision == "BLOCK", bad.__dict__
        assert decision.matched_required_evidence == []


# ---------------------------------------------------------------------------
# CLI evidence deserialization (14-23)
# ---------------------------------------------------------------------------

def _write_evidence(tmp_path: Path, entries) -> Path:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({"evidence": entries}), encoding="utf-8")
    return path


def _good_entry(**overrides):
    entry = {"evidence_id": "ev-1", "command": REQUIRED_CMD, "exit_code": 0,
             "completed": True, "commit_sha": EXPECTED_SHA}
    entry.update(overrides)
    return entry


def _run_changegate(evidence_file: Path, capsys, changed=None):
    rc = cli_main([
        "changegate", "--contract", str(CONTRACT_PATH),
        "--changed-files", *(changed or ALLOWED),
        "--expected-commit", EXPECTED_SHA,
        "--evidence-file", str(evidence_file),
    ])
    return rc, json.loads(capsys.readouterr().out)


def test_r3_cli_valid_evidence_passes(tmp_path, capsys):
    ef = _write_evidence(tmp_path, [_good_entry()])
    rc, out = _run_changegate(ef, capsys)
    assert rc == 0 and out["decision"] == "PASS" and out["accepted"] is True


@pytest.mark.parametrize("bad_entry, _label", [
    (_good_entry(completed="false"), "completed_str"),
    (_good_entry(completed=1), "completed_int"),
    (_good_entry(exit_code=False), "exit_code_bool"),
    (_good_entry(exit_code="0"), "exit_code_str"),
    (_good_entry(evidence_id=123), "evidence_id_num"),
    (_good_entry(surprise="x"), "unknown_field"),
])
def test_r3_cli_invalid_entry_nonzero(bad_entry, _label, tmp_path, capsys):
    ef = _write_evidence(tmp_path, [bad_entry])
    rc, out = _run_changegate(ef, capsys)
    assert rc != 0 and out["accepted"] is False
    assert out["validation_errors"]


def test_r3_cli_non_object_entry_nonzero(tmp_path, capsys):
    ef = _write_evidence(tmp_path, ["not-an-object"])
    rc, out = _run_changegate(ef, capsys)
    assert rc != 0 and out["accepted"] is False


def test_r3_cli_non_list_root_nonzero(tmp_path, capsys):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({"evidence": {"not": "a list"}}), encoding="utf-8")
    rc, out = _run_changegate(path, capsys)
    assert rc != 0 and out["accepted"] is False
    assert any("list" in e for e in out["validation_errors"])


def test_r3_cli_validation_errors_machine_readable(tmp_path, capsys):
    ef = _write_evidence(tmp_path, [_good_entry(exit_code="0")])
    rc, out = _run_changegate(ef, capsys)
    assert rc != 0
    # Machine-readable: a JSON object with a validation_errors list, not a traceback.
    assert isinstance(out, dict) and isinstance(out["validation_errors"], list)


# ---------------------------------------------------------------------------
# Duplicate evidence IDs (24-30)
# ---------------------------------------------------------------------------

def test_r3_identical_duplicate_id_blocks():
    decision = _gate([_ev(), _ev()])
    assert decision.decision == "BLOCK"
    assert any(f.type == "duplicate_evidence_id" for f in decision.findings)


@pytest.mark.parametrize("second", [
    dict(command="pytest other.py"),
    dict(exit_code=1),
    dict(commit_sha="deadbeef00000000000000000000000000000000"),
    dict(completed=False),
])
def test_r3_conflicting_duplicate_id_blocks(second):
    decision = _gate([_ev(), _ev(**second)])
    assert decision.decision == "BLOCK"
    assert any(f.type == "duplicate_evidence_id" for f in decision.findings)


def test_r3_valid_plus_failed_duplicate_blocks():
    decision = _gate([_ev(), _ev(exit_code=2)])
    assert decision.decision == "BLOCK"


def test_r3_duplicate_id_cannot_satisfy_required():
    decision = _gate([_ev(), _ev()])
    assert decision.matched_required_evidence == []
    assert REQUIRED_CMD in decision.missing_required_evidence


# ---------------------------------------------------------------------------
# ProcessGuard gate integrity (31-44)
# ---------------------------------------------------------------------------

def _guard(gate_decision, action=IntendedAction.MERGE,
           state=TaskState.READY_FOR_MERGE, approved=True):
    return evaluate_process_guard(ProcessGuardInput(
        contract=_contract(), task_state=state,
        implementer_report=_impl_pass(), verifier_report=_verifier_pass(),
        changegate_decision=gate_decision, human_approved=approved,
        intended_action=action,
    ))


def _forged_pass(**overrides) -> ChangeGateDecision:
    base = dict(
        decision="PASS", findings=[],
        matched_required_evidence=[REQUIRED_CMD], missing_required_evidence=[],
        rejected_evidence=[], expected_commit_sha=EXPECTED_SHA,
    )
    base.update(overrides)
    return ChangeGateDecision(**base)


def test_r3_pass_with_missing_evidence_blocks():
    forged = _forged_pass(matched_required_evidence=[],
                          missing_required_evidence=[REQUIRED_CMD])
    decision = _guard(forged)
    assert decision.decision == "BLOCK"
    assert "valid_changegate_decision" in decision.missing_steps


def test_r3_pass_empty_matches_for_required_blocks():
    forged = _forged_pass(matched_required_evidence=[], missing_required_evidence=[])
    decision = _guard(forged)
    assert decision.decision == "BLOCK"


@pytest.mark.parametrize("finding", [
    Finding(type="forbidden_path", severity="block", file="x", reason="r"),
    Finding(type="invalid_changed_path", severity="block", file="x", reason="r"),
    Finding(type="no_changed_files", severity="warning", file=None, reason="r"),
    Finding(type="duplicate_evidence_id", severity="block", file=None, reason="r"),
    Finding(type="whatever", severity="explode", file=None, reason="r"),
])
def test_r3_pass_with_bad_finding_blocks(finding):
    forged = _forged_pass(findings=[finding])
    decision = _guard(forged)
    assert decision.decision == "BLOCK"
    assert "valid_changegate_decision" in decision.missing_steps


@pytest.mark.parametrize("action, state, approved", [
    (IntendedAction.MERGE, TaskState.READY_FOR_MERGE, True),
    (IntendedAction.PUSH, TaskState.APPROVED, True),
    (IntendedAction.DEPLOY, TaskState.APPROVED, True),
    (IntendedAction.DONE, TaskState.APPROVED, True),
])
def test_r3_inconsistent_pass_never_authorizes(action, state, approved):
    forged = _forged_pass(findings=[
        Finding(type="forbidden_path", severity="block", file="x", reason="r")])
    decision = _guard(forged, action=action, state=state, approved=approved)
    assert decision.decision == "BLOCK"


def test_r3_valid_pass_authorizes_merge():
    decision = _guard(_gate([_ev()]), action=IntendedAction.MERGE,
                      state=TaskState.READY_FOR_MERGE)
    assert decision.decision == "PASS"


def test_r3_valid_pass_authorizes_push():
    decision = _guard(_gate([_ev()]), action=IntendedAction.PUSH,
                      state=TaskState.APPROVED)
    assert decision.decision == "PASS"


def test_r3_no_required_evidence_contract_empty_matches_ok():
    no_ev_contract = validate_contract_dict({
        "task_id": "NOEV", "title": "t", "goal": "g",
        "acceptance_criteria": ["c"], "allowed_paths": ["src/**"],
        "required_evidence": [],
    })
    errors = validate_change_gate_decision(no_ev_contract, ChangeGateDecision(
        decision="PASS", findings=[], matched_required_evidence=[],
        missing_required_evidence=[], rejected_evidence=[], expected_commit_sha="",
    ))
    assert errors == []


def test_r3_valid_pass_with_unrelated_rejected_record_still_valid():
    # A rejected extra record does not invalidate a PASS when every requirement is met by
    # unique valid evidence and there are no blocking/review findings.
    decision = evaluate_change_gate(ChangeGateInput(
        contract=_contract(), changed_files=ALLOWED, expected_commit_sha=EXPECTED_SHA,
        test_evidence=[_ev(), _ev(command="pytest extra.py", evidence_id="ev-2")],
    ))
    assert decision.decision == "PASS"
    assert validate_change_gate_decision(_contract(), decision) == []


# ---------------------------------------------------------------------------
# EvidenceStore structural validation (45-53)
# ---------------------------------------------------------------------------

def test_r3_contract_json_list_rejected(tmp_path):
    store = EvidenceStore(tmp_path)
    (tmp_path / "TASK").mkdir(parents=True)
    (tmp_path / "TASK" / "contract.json").write_text("[]", encoding="utf-8")
    with pytest.raises(EvidenceStructureError):
        store.load_task_summary("TASK")


def test_r3_contract_json_boolean_rejected(tmp_path):
    store = EvidenceStore(tmp_path)
    (tmp_path / "TASK").mkdir(parents=True)
    (tmp_path / "TASK" / "contract.json").write_text("true", encoding="utf-8")
    with pytest.raises(EvidenceStructureError):
        store.load_task_summary("TASK")


def test_r3_contract_wrong_task_rejected(tmp_path):
    store = EvidenceStore(tmp_path)
    (tmp_path / "TASK").mkdir(parents=True)
    (tmp_path / "TASK" / "contract.json").write_text(
        json.dumps({"task_id": "OTHER"}), encoding="utf-8")
    with pytest.raises(EvidenceStructureError):
        store.load_task_summary("TASK")


@pytest.mark.parametrize("body", ["true", "[]", "123", '"scalar"'])
def test_r3_gate_json_non_object_rejected(tmp_path, body):
    store = EvidenceStore(tmp_path)
    (tmp_path / "TASK" / "gate").mkdir(parents=True)
    (tmp_path / "TASK" / "gate" / "changegate.json").write_text(body, encoding="utf-8")
    with pytest.raises(EvidenceStructureError):
        store.load_task_summary("TASK")


@pytest.mark.parametrize("line", ['"hello"', "123", "[]", "null"])
def test_r3_scalar_or_list_event_rejected(tmp_path, line):
    store = EvidenceStore(tmp_path)
    (tmp_path / "TASK").mkdir(parents=True)
    (tmp_path / "TASK" / "events.jsonl").write_text(line + "\n", encoding="utf-8")
    with pytest.raises(EvidenceStructureError):
        store.load_task_summary("TASK")


def test_r3_wrong_task_event_rejected(tmp_path):
    store = EvidenceStore(tmp_path)
    (tmp_path / "TASK").mkdir(parents=True)
    event = {"task_id": "OTHER", "event_type": "x", "timestamp": "t", "payload": {}}
    (tmp_path / "TASK" / "events.jsonl").write_text(
        json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(EvidenceStructureError):
        store.load_task_summary("TASK")


def test_r3_non_object_payload_event_rejected(tmp_path):
    store = EvidenceStore(tmp_path)
    (tmp_path / "TASK").mkdir(parents=True)
    event = {"task_id": "TASK", "event_type": "x", "timestamp": "t", "payload": "str"}
    (tmp_path / "TASK" / "events.jsonl").write_text(
        json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(EvidenceStructureError):
        store.load_task_summary("TASK")


def test_r3_valid_stored_summary_loads(tmp_path):
    store = EvidenceStore(tmp_path)
    store.save_contract(_contract())
    store.save_gate_result("BH-P0-A", "changegate", {"decision": "PASS"})
    store.append_event("BH-P0-A", "contract_validated", {"by": "test"})
    summary = store.load_task_summary("BH-P0-A")
    assert summary["contract"]["task_id"] == "BH-P0-A"
    assert summary["gates"]["changegate"]["decision"] == "PASS"
    assert summary["events"][0]["event_type"] == "contract_validated"


def test_r3_syntactically_corrupt_json_still_raises(tmp_path):
    store = EvidenceStore(tmp_path)
    (tmp_path / "TASK" / "gate").mkdir(parents=True)
    (tmp_path / "TASK" / "gate" / "changegate.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(EvidenceCorruptionError):
        store.load_task_summary("TASK")


# ---------------------------------------------------------------------------
# AgentReport exact schema (54-57)
# ---------------------------------------------------------------------------

_VALID_JSON = """```json
{"machine_summary": {"task_id": "BH-P0-A", "role": "implementer",
 "status": "IMPLEMENTED", "result": "PASS",
 "files_changed": [], "tests_run": [], "blockers": []}}
```"""


@pytest.mark.parametrize("extra", [
    '"debug": true', '"extra": "value"', '"confidence": 0.9', '"metadata": {}',
])
def test_r3_unknown_json_field_rejected(extra):
    text = _VALID_JSON.replace('"blockers": []', '"blockers": [], ' + extra)
    report = parse_agent_report(text)
    assert not report.parse_ok and report.result == "BLOCKED"
    assert "unknown field" in (report.parse_error or "")


def test_r3_unknown_yaml_field_rejected():
    text = """machine_summary:
  task_id: BH-P0-A
  role: verifier
  status: VERIFIED_PASS
  result: PASS
  files_changed: []
  tests_run: []
  blockers: []
  surprise: value
"""
    report = parse_agent_report(text)
    assert not report.parse_ok
    assert "unknown field" in (report.parse_error or "")


def test_r3_valid_exact_schema_still_parses():
    report = parse_agent_report(_VALID_JSON)
    assert report.parse_ok and report.role == "implementer"


def test_r3_multiple_summary_and_contradiction_still_rejected():
    assert not parse_agent_report(_VALID_JSON + "\n" + _VALID_JSON).parse_ok
    contradiction = _VALID_JSON.replace('"status": "IMPLEMENTED"', '"status": "BLOCKED"')
    assert not parse_agent_report(contradiction).parse_ok

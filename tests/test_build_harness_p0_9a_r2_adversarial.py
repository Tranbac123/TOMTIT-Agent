"""P0-9A-R2 — frozen adversarial regressions for the Codex Sol deep-audit findings.

One test class per confirmed Build Harness finding (BH-A01..BH-A08). These reproduce the
original attack shapes and pin the fail-closed behavior. Runtime/web findings (RT-A09,
WEB-A10) are explicitly out of scope for this module.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_core.build_harness.change_gate import (
    ChangeGateInput,
    CommandEvidence,
    evaluate_change_gate,
)
from agent_core.build_harness.contracts import (
    ContractValidationError,
    load_task_contract,
    validate_contract_dict,
)
from agent_core.build_harness.evidence_store import (
    EvidenceConflictError,
    EvidenceCorruptionError,
    EvidencePathEscapeError,
    EvidenceStore,
    InvalidEvidenceIdentifierError,
)
from agent_core.build_harness.next_action import recommend_next_action
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


def _contract():
    return load_task_contract(CONTRACT_PATH)


def _evidence(command: str = REQUIRED_CMD, *, exit_code: int = 0,
              completed: bool = True, sha: str = EXPECTED_SHA,
              evidence_id: str = "ev-1") -> CommandEvidence:
    return CommandEvidence(
        command=command, exit_code=exit_code, completed=completed,
        commit_sha=sha, evidence_id=evidence_id,
    )


def _gate(changed_files: list[str], evidence: list[CommandEvidence] | None = None,
          tests_run: list[str] | None = None):
    return evaluate_change_gate(ChangeGateInput(
        contract=_contract(),
        changed_files=changed_files,
        tests_run=tests_run or [],
        expected_commit_sha=EXPECTED_SHA,
        test_evidence=evidence if evidence is not None else [_evidence()],
    ))


def _impl_pass() -> AgentReport:
    return AgentReport(task_id="BH-P0-A", role="implementer",
                       status="IMPLEMENTED", result="PASS")


def _verifier_pass() -> AgentReport:
    return AgentReport(task_id="BH-P0-A", role="verifier",
                       status="VERIFIED_PASS", result="PASS")


def _pass_gate():
    return _gate(["agent_core/build_harness/dependency_scanner.py"])


# ---------------------------------------------------------------------------
# BH-A01 — EvidenceStore path traversal
# ---------------------------------------------------------------------------

class TestBHA01Traversal:
    def test_prompt_role_traversal_rejected(self, tmp_path):
        store = EvidenceStore(tmp_path)
        with pytest.raises(InvalidEvidenceIdentifierError):
            store.save_prompt("TASK", "../../../escaped", "owned")
        assert not (tmp_path.parent / "escaped.md").exists()

    def test_report_role_traversal_rejected(self, tmp_path):
        store = EvidenceStore(tmp_path)
        with pytest.raises(InvalidEvidenceIdentifierError):
            store.save_report("TASK", "../x", "owned")

    def test_gate_name_traversal_rejected(self, tmp_path):
        store = EvidenceStore(tmp_path)
        with pytest.raises(InvalidEvidenceIdentifierError):
            store.save_gate_result("TASK", "../contract", {"decision": "PASS"})

    def test_absolute_identifiers_rejected(self, tmp_path):
        store = EvidenceStore(tmp_path)
        with pytest.raises(InvalidEvidenceIdentifierError):
            store.save_prompt("TASK", "/tmp/abs", "owned")
        with pytest.raises(InvalidEvidenceIdentifierError):
            store.save_prompt("/tmp/task", "implementer", "owned")

    def test_backslash_and_control_identifiers_rejected(self, tmp_path):
        store = EvidenceStore(tmp_path)
        for bad in ("a\\b", "task\nx", "task\x00x", "C:\\task", "..", ".", "", " "):
            with pytest.raises(InvalidEvidenceIdentifierError):
                store.save_prompt(bad, "implementer", "owned")

    def test_symlink_escape_rejected(self, tmp_path):
        store = EvidenceStore(tmp_path / "root")
        outside = tmp_path / "outside"
        outside.mkdir()
        # Pre-create the task dir and replace its prompts dir with a symlink outside.
        task_dir = tmp_path / "root" / "TASK"
        task_dir.mkdir(parents=True)
        os.symlink(outside, task_dir / "prompts")
        with pytest.raises(EvidencePathEscapeError):
            store.save_prompt("TASK", "implementer", "owned")
        assert not (outside / "implementer.md").exists()

    def test_writes_stay_under_task_directory(self, tmp_path):
        store = EvidenceStore(tmp_path)
        path = store.save_prompt("TASK", "implementer", "content")
        assert path.resolve().is_relative_to((tmp_path / "TASK").resolve())


# ---------------------------------------------------------------------------
# BH-A02 — task-ID collisions and overwrite integrity
# ---------------------------------------------------------------------------

class TestBHA02Collision:
    def test_slash_task_id_rejected_not_sanitized(self, tmp_path):
        store = EvidenceStore(tmp_path)
        with pytest.raises(InvalidEvidenceIdentifierError):
            store.save_prompt("a/b", "implementer", "x")
        # The underscore variant is a DIFFERENT, valid namespace — no aliasing.
        store.save_prompt("a_b", "implementer", "x")
        assert (tmp_path / "a_b" / "prompts" / "implementer.md").exists()

    def test_duplicate_artifact_write_rejected(self, tmp_path):
        store = EvidenceStore(tmp_path)
        store.save_prompt("TASK", "implementer", "first")
        with pytest.raises(EvidenceConflictError):
            store.save_prompt("TASK", "implementer", "second (different)")
        assert (tmp_path / "TASK" / "prompts" / "implementer.md").read_text(
            encoding="utf-8") == "first"

    def test_identical_rewrite_is_idempotent(self, tmp_path):
        store = EvidenceStore(tmp_path)
        store.save_prompt("TASK", "implementer", "same")
        store.save_prompt("TASK", "implementer", "same")  # no error
        assert (tmp_path / "TASK" / "prompts" / "implementer.md").read_text(
            encoding="utf-8") == "same"

    def test_corrupt_json_raises_corruption_error(self, tmp_path):
        store = EvidenceStore(tmp_path)
        task_dir = tmp_path / "TASK"
        (task_dir / "gate").mkdir(parents=True)
        (task_dir / "gate" / "changegate.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(EvidenceCorruptionError):
            store.load_task_summary("TASK")

    def test_corrupt_event_line_raises(self, tmp_path):
        store = EvidenceStore(tmp_path)
        store.append_event("TASK", "contract_validated", {})
        with (tmp_path / "TASK" / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("{broken\n")
        with pytest.raises(EvidenceCorruptionError):
            store.load_task_summary("TASK")


# ---------------------------------------------------------------------------
# BH-A03 — ChangeGate path normalization bypass
# ---------------------------------------------------------------------------

class TestBHA03PathBypass:
    def test_dotdot_traversal_blocks(self):
        decision = _gate(["agent_core/build_harness/../conversation/router.py"])
        assert decision.decision == "BLOCK"
        assert any(f.type == "invalid_changed_path" for f in decision.findings)

    def test_backslash_forbidden_path_blocks(self):
        decision = _gate(["agent_core\\conversation\\router.py"])
        assert decision.decision == "BLOCK"
        assert any(f.type == "forbidden_path" for f in decision.findings)

    def test_absolute_posix_path_blocks(self):
        decision = _gate(["/absolute/file.py"])
        assert decision.decision == "BLOCK"
        assert any(f.type == "invalid_changed_path" for f in decision.findings)

    def test_windows_drive_path_blocks(self):
        decision = _gate(["C:\\repo\\file.py"])
        assert decision.decision == "BLOCK"
        assert any(f.type == "invalid_changed_path" for f in decision.findings)

    def test_leading_dot_slash_normalized_and_allowed(self):
        decision = _gate(["./agent_core/build_harness/contracts.py"])
        assert decision.decision == "PASS", decision

    def test_forbidden_wins_over_allowed(self):
        broad = validate_contract_dict({
            "task_id": "T", "title": "t", "goal": "g",
            "acceptance_criteria": ["c"],
            "allowed_paths": ["agent_core/**"],
            "forbidden_paths": ["agent_core/conversation/**"],
        })
        decision = evaluate_change_gate(ChangeGateInput(
            contract=broad,
            changed_files=["agent_core/conversation/router.py"],
            expected_commit_sha=EXPECTED_SHA,
            test_evidence=[],
        ))
        assert decision.decision == "BLOCK"
        assert any(f.type == "forbidden_path" for f in decision.findings)

    def test_duplicates_deduplicated(self):
        decision = _gate([
            "agent_core/build_harness/contracts.py",
            "./agent_core/build_harness/contracts.py",
            "agent_core\\build_harness\\contracts.py",
        ])
        out_of_scope = [f for f in decision.findings if f.type == "out_of_scope"]
        assert not out_of_scope
        assert decision.decision == "PASS"

    def test_empty_changed_files_review_required(self):
        decision = _gate([])
        assert decision.decision == "REVIEW_REQUIRED"
        assert any(f.type == "no_changed_files" for f in decision.findings)


# ---------------------------------------------------------------------------
# BH-A04 — broad_scope_allowed type-coercion bypass
# ---------------------------------------------------------------------------

class TestBHA04BroadScope:
    @pytest.mark.parametrize("bad", ["false", "true", 0, 1, None, [], {}])
    def test_non_boolean_broad_scope_rejected(self, bad):
        with pytest.raises(ContractValidationError, match="broad_scope_allowed"):
            validate_contract_dict({
                "task_id": "T", "title": "t", "goal": "g",
                "acceptance_criteria": ["c"], "allowed_paths": [],
                "broad_scope_allowed": bad,
            })

    def test_real_booleans_accepted(self):
        contract = validate_contract_dict({
            "task_id": "T", "title": "t", "goal": "g",
            "acceptance_criteria": ["c"], "allowed_paths": [],
            "broad_scope_allowed": True,
        })
        assert contract.broad_scope_allowed is True
        contract = validate_contract_dict({
            "task_id": "T", "title": "t", "goal": "g",
            "acceptance_criteria": ["c"], "allowed_paths": ["src/**"],
            "broad_scope_allowed": False,
        })
        assert contract.broad_scope_allowed is False

    def test_non_list_security_fields_rejected(self):
        with pytest.raises(ContractValidationError, match="allowed_paths"):
            validate_contract_dict({
                "task_id": "T", "title": "t", "goal": "g",
                "acceptance_criteria": ["c"], "allowed_paths": "src/**",
            })

    def test_non_string_or_empty_list_items_rejected(self):
        for bad_list in (["src/**", 3], ["src/**", ""], ["src/**", True]):
            with pytest.raises(ContractValidationError):
                validate_contract_dict({
                    "task_id": "T", "title": "t", "goal": "g",
                    "acceptance_criteria": ["c"], "allowed_paths": bad_list,
                })

    def test_unknown_risk_level_rejected(self):
        with pytest.raises(ContractValidationError, match="risk_level"):
            validate_contract_dict({
                "task_id": "T", "title": "t", "goal": "g",
                "acceptance_criteria": ["c"], "allowed_paths": ["src/**"],
                "risk_level": "critical",
            })


# ---------------------------------------------------------------------------
# BH-A05 — deceptive/unproven evidence bypass
# ---------------------------------------------------------------------------

class TestBHA05Evidence:
    ALLOWED = ["agent_core/build_harness/dependency_scanner.py"]

    @pytest.mark.parametrize("fake_command", [
        'echo "pytest tests/test_build_harness_p0_9a_core.py"',
        "pytest tests/test_build_harness_p0_9a_core.py --collect-only",
        "not-pytest tests/test_build_harness_p0_9a_core.py",
        "pytest tests/test_build_harness_p0_9a_core.py && false",
    ])
    def test_deceptive_commands_never_match(self, fake_command):
        decision = _gate(self.ALLOWED, evidence=[_evidence(command=fake_command)])
        assert decision.decision == "REVIEW_REQUIRED", decision
        assert decision.missing_required_evidence == [REQUIRED_CMD]

    def test_nonzero_exit_rejected(self):
        decision = _gate(self.ALLOWED, evidence=[_evidence(exit_code=1)])
        assert decision.decision == "REVIEW_REQUIRED"
        assert any("exit_code" in r["reason"] for r in decision.rejected_evidence)

    def test_incomplete_evidence_rejected(self):
        decision = _gate(self.ALLOWED, evidence=[_evidence(completed=False)])
        assert decision.decision == "REVIEW_REQUIRED"
        assert any("did not complete" in r["reason"] for r in decision.rejected_evidence)

    def test_wrong_commit_sha_rejected(self):
        decision = _gate(self.ALLOWED, evidence=[_evidence(sha="deadbeef")])
        assert decision.decision == "REVIEW_REQUIRED"
        assert any("commit_sha mismatch" in r["reason"] for r in decision.rejected_evidence)

    def test_empty_evidence_id_rejected(self):
        decision = _gate(self.ALLOWED, evidence=[_evidence(evidence_id=" ")])
        assert decision.decision == "REVIEW_REQUIRED"

    def test_legacy_strings_alone_never_pass(self):
        decision = _gate(self.ALLOWED, evidence=[], tests_run=[REQUIRED_CMD])
        assert decision.decision == "REVIEW_REQUIRED"
        assert any("unverified" in f.reason for f in decision.findings)

    def test_exact_evidence_at_expected_sha_passes(self):
        decision = _gate(self.ALLOWED)
        assert decision.decision == "PASS"
        assert decision.matched_required_evidence == [REQUIRED_CMD]


# ---------------------------------------------------------------------------
# BH-A06 — unknown/deploy actions fail closed
# ---------------------------------------------------------------------------

class TestBHA06Actions:
    def _guard(self, action, state=TaskState.APPROVED, approved=True):
        return evaluate_process_guard(ProcessGuardInput(
            contract=_contract(),
            task_state=state,
            implementer_report=_impl_pass(),
            verifier_report=_verifier_pass(),
            changegate_decision=_pass_gate(),
            human_approved=approved,
            intended_action=action,
        ))

    @pytest.mark.parametrize("bad_action", ["", "Merge", "ship-it", "MERGE", None])
    def test_unknown_actions_block(self, bad_action):
        decision = self._guard(bad_action)
        assert decision.decision == "BLOCK", bad_action
        assert "valid_intended_action" in decision.missing_steps

    def test_deploy_from_draft_blocks(self):
        decision = self._guard(IntendedAction.DEPLOY, state=TaskState.DRAFT)
        assert decision.decision == "BLOCK"
        assert "valid_task_state_for_deploy" in decision.missing_steps

    def test_deploy_without_approval_blocks(self):
        decision = self._guard(IntendedAction.DEPLOY, approved=False)
        assert decision.decision == "BLOCK"
        assert decision.missing_steps == ["human_approval"]

    def test_deploy_approved_from_approved_passes(self):
        decision = self._guard(IntendedAction.DEPLOY)
        assert decision.decision == "PASS"


# ---------------------------------------------------------------------------
# BH-A07 — untrusted report identity bypass
# ---------------------------------------------------------------------------

class TestBHA07ReportIdentity:
    def _guard_with(self, implementer, verifier):
        return evaluate_process_guard(ProcessGuardInput(
            contract=_contract(),
            task_state=TaskState.APPROVED,
            implementer_report=implementer,
            verifier_report=verifier,
            changegate_decision=_pass_gate(),
            human_approved=True,
            intended_action=IntendedAction.MERGE,
        ))

    def test_wrong_task_implementer_blocks(self):
        wrong = AgentReport(task_id="OTHER-TASK", role="implementer",
                            status="IMPLEMENTED", result="PASS")
        decision = self._guard_with(wrong, _verifier_pass())
        assert decision.decision == "BLOCK"
        assert "trusted_implementer_report" in decision.missing_steps

    def test_wrong_task_verifier_blocks(self):
        wrong = AgentReport(task_id="OTHER-TASK", role="verifier",
                            status="VERIFIED_PASS", result="PASS")
        decision = self._guard_with(_impl_pass(), wrong)
        assert decision.decision == "BLOCK"
        assert "trusted_verifier_report" in decision.missing_steps

    def test_swapped_roles_block(self):
        decision = self._guard_with(_verifier_pass(), _impl_pass())
        assert decision.decision == "BLOCK"

    def test_contradictory_report_blocks(self):
        contradictory = AgentReport(task_id="BH-P0-A", role="implementer",
                                    status="BLOCKED", result="PASS")
        decision = self._guard_with(contradictory, _verifier_pass())
        assert decision.decision == "BLOCK"
        assert "contradictory" in decision.reason

    def test_valid_reports_pass(self):
        decision = self._guard_with(_impl_pass(), _verifier_pass())
        assert decision.decision == "PASS"

    def test_next_action_never_releases_on_bad_identity(self):
        wrong = AgentReport(task_id="OTHER-TASK", role="implementer",
                            status="IMPLEMENTED", result="PASS")
        action = recommend_next_action(_contract(), wrong, _verifier_pass(), None, None)
        assert action.action == "ESCALATE_TO_HUMAN"
        assert "identity" in action.reason

    def test_next_action_never_releases_on_guard_block(self):
        guard = self._guard_with(
            AgentReport(task_id="OTHER-TASK", role="implementer",
                        status="IMPLEMENTED", result="PASS"),
            _verifier_pass(),
        )
        action = recommend_next_action(
            _contract(), _impl_pass(), _verifier_pass(), _pass_gate(), guard
        )
        assert action.action != "READY_FOR_MERGE_OR_PUSH"


# ---------------------------------------------------------------------------
# BH-A08 — conflicting/semantically invalid machine summaries
# ---------------------------------------------------------------------------

_JSON_SUMMARY = """```json
{"machine_summary": {"task_id": "BH-P0-A", "role": "implementer",
 "status": "IMPLEMENTED", "result": "PASS",
 "files_changed": [], "tests_run": [], "blockers": []}}
```"""

_YAML_SUMMARY = """machine_summary:
  task_id: BH-P0-A
  role: verifier
  status: VERIFIED_PASS
  result: PASS
  files_changed: []
  tests_run: []
  blockers: []
"""


class TestBHA08StrictParsing:
    def test_json_plus_yaml_blocked(self):
        report = parse_agent_report(_JSON_SUMMARY + "\n\n" + _YAML_SUMMARY)
        assert not report.parse_ok and report.result == "BLOCKED"
        assert "multiple" in (report.parse_error or "")

    def test_two_json_summaries_blocked(self):
        report = parse_agent_report(_JSON_SUMMARY + "\n\n" + _JSON_SUMMARY)
        assert not report.parse_ok
        assert "multiple" in (report.parse_error or "")

    def test_two_yaml_summaries_blocked(self):
        report = parse_agent_report(_YAML_SUMMARY + "\n" + _YAML_SUMMARY)
        assert not report.parse_ok
        assert "multiple" in (report.parse_error or "")

    def test_missing_required_field_blocked(self):
        text = """```json
{"machine_summary": {"task_id": "BH-P0-A", "role": "implementer",
 "status": "IMPLEMENTED", "result": "PASS"}}
```"""
        report = parse_agent_report(text)
        assert not report.parse_ok
        assert "missing required field" in (report.parse_error or "")

    @pytest.mark.parametrize("field_override, expected_fragment", [
        ('"role": "hacker"', "unknown role"),
        ('"result": "MAYBE"', "unknown result"),
        ('"status": "WHATEVER"', "contradictory or unknown"),
    ])
    def test_unknown_vocabulary_blocked(self, field_override, expected_fragment):
        text = _JSON_SUMMARY.replace(
            {"\"role\": \"hacker\"": '"role": "implementer"',
             "\"result\": \"MAYBE\"": '"result": "PASS"',
             "\"status\": \"WHATEVER\"": '"status": "IMPLEMENTED"'}[field_override],
            field_override,
        )
        report = parse_agent_report(text)
        assert not report.parse_ok
        assert expected_fragment in (report.parse_error or "")

    def test_contradictory_status_result_blocked(self):
        text = _JSON_SUMMARY.replace('"status": "IMPLEMENTED"', '"status": "BLOCKED"')
        report = parse_agent_report(text)
        assert not report.parse_ok
        assert "contradictory" in (report.parse_error or "")

    def test_boolean_scalar_field_blocked(self):
        text = _JSON_SUMMARY.replace('"task_id": "BH-P0-A"', '"task_id": true')
        report = parse_agent_report(text)
        assert not report.parse_ok

    def test_duplicate_json_key_blocked(self):
        text = """```json
{"machine_summary": {"task_id": "BH-P0-A", "task_id": "BH-P0-B",
 "role": "implementer", "status": "IMPLEMENTED", "result": "PASS",
 "files_changed": [], "tests_run": [], "blockers": []}}
```"""
        report = parse_agent_report(text)
        assert not report.parse_ok
        assert "duplicate key" in (report.parse_error or "")

    def test_duplicate_yaml_key_blocked(self):
        text = _YAML_SUMMARY + "  task_id: BH-P0-B\n"
        # Insert the duplicate INSIDE the block: rebuild with a dup line before the end.
        text = _YAML_SUMMARY.rstrip() + "\n  role: implementer\n"
        report = parse_agent_report(text)
        assert not report.parse_ok
        assert "duplicate key" in (report.parse_error or "")

    def test_malformed_list_indentation_blocked(self):
        text = """machine_summary:
  task_id: BH-P0-A
  role: verifier
  status: VERIFIED_PASS
  result: PASS
  files_changed:
  - badly-indented-item
  tests_run: []
  blockers: []
"""
        report = parse_agent_report(text)
        assert not report.parse_ok

    def test_oversized_report_blocked(self):
        text = _JSON_SUMMARY + "\n" + ("x" * (1024 * 1024 + 1))
        report = parse_agent_report(text)
        assert not report.parse_ok
        assert "byte limit" in (report.parse_error or "")

    def test_valid_json_implementer_passes(self):
        report = parse_agent_report(_JSON_SUMMARY)
        assert report.parse_ok and report.role == "implementer"

    def test_valid_yamlish_verifier_passes(self):
        report = parse_agent_report(_YAML_SUMMARY)
        assert report.parse_ok and report.role == "verifier"
        assert report.status == "VERIFIED_PASS"

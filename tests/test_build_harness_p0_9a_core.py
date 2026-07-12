"""P0-9A — Build Harness core: contracts, state machine, prompts, ingestion, gates,
evidence store, next-action recommender, and CLI.

All harness logic is exercised with explicit inputs (no git/shell execution); the
scenario fixtures in data/evals/p0_9a_build_harness_cases.json drive the end-to-end
gate/next-action expectations.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_core.build_harness.change_gate import (
    ChangeGateInput,
    CommandEvidence,
    evaluate_change_gate,
)
from agent_core.build_harness.cli import main as cli_main
from agent_core.build_harness.contracts import (
    ContractValidationError,
    TaskContract,
    load_task_contract,
    validate_contract_dict,
)
from agent_core.build_harness.evidence_store import EvidenceStore
from agent_core.build_harness.next_action import recommend_next_action
from agent_core.build_harness.process_guard import (
    ProcessGuardInput,
    evaluate_process_guard,
)
from agent_core.build_harness.prompt_generator import AgentRole, generate_prompt
from agent_core.build_harness.reports import AgentReport, parse_agent_report
from agent_core.build_harness.state import (
    InvalidTransitionError,
    TaskEvent,
    TaskState,
    transition,
)

ROOT = Path(__file__).parent.parent
CONTRACT_PATH = ROOT / "examples/build_harness/task_contract_dependency_scanner.json"
CLAUDE_REPORT_PATH = ROOT / "examples/build_harness/claude_report.md"
CODEX_REPORT_PATH = ROOT / "examples/build_harness/codex_report.md"
EVAL_CASES_PATH = ROOT / "data/evals/p0_9a_build_harness_cases.json"


def _contract() -> TaskContract:
    return load_task_contract(CONTRACT_PATH)


EXPECTED_SHA = "0737577a2d2351947f412ed29d73722f18491c89"

_PASS_STATUS_BY_ROLE = {"implementer": "IMPLEMENTED", "verifier": "VERIFIED_PASS"}


def _pass_report(role: str) -> AgentReport:
    return AgentReport(
        task_id="BH-P0-A", role=role,
        status=_PASS_STATUS_BY_ROLE[role], result="PASS",
    )


def _valid_evidence(command: str = "pytest tests/test_build_harness_p0_9a_core.py",
                    sha: str = EXPECTED_SHA) -> CommandEvidence:
    return CommandEvidence(
        command=command, exit_code=0, completed=True,
        commit_sha=sha, evidence_id="ev-1",
    )


def _pass_gate():
    return evaluate_change_gate(ChangeGateInput(
        contract=_contract(),
        changed_files=["agent_core/build_harness/dependency_scanner.py"],
        expected_commit_sha=EXPECTED_SHA,
        test_evidence=[_valid_evidence()],
    ))


# ---------------------------------------------------------------------------
# 1-2. TaskContract
# ---------------------------------------------------------------------------

def test_contract_loads_and_validates():
    contract = _contract()
    assert contract.task_id == "BH-P0-A"
    assert contract.risk_level == "medium"
    assert "agent_core/build_harness/**" in contract.allowed_paths
    assert "dependency_change" in contract.requires_human_approval_for


def test_invalid_contract_fails_with_clear_errors():
    with pytest.raises(ContractValidationError) as exc:
        validate_contract_dict({"title": "x", "allowed_paths": ["a"]})
    message = str(exc.value)
    assert "task_id" in message and "goal" in message and "acceptance_criteria" in message


def test_contract_empty_allowed_paths_requires_broad_scope_flag():
    base = {
        "task_id": "T", "title": "t", "goal": "g",
        "acceptance_criteria": ["c"],
    }
    with pytest.raises(ContractValidationError, match="broad_scope_allowed"):
        validate_contract_dict(base)
    contract = validate_contract_dict({**base, "broad_scope_allowed": True})
    assert contract.broad_scope_allowed and contract.allowed_paths == []


def test_contract_defaults_applied():
    contract = validate_contract_dict({
        "task_id": "T", "title": "t", "goal": "g",
        "acceptance_criteria": ["c"], "allowed_paths": ["src/**"],
    })
    assert contract.risk_level == "medium"
    assert contract.forbidden_paths == []
    assert contract.requires_human_approval_for == [
        "merge", "push", "deploy", "dependency_change"
    ]


# ---------------------------------------------------------------------------
# 3. TaskState machine
# ---------------------------------------------------------------------------

def test_state_machine_happy_path():
    state = TaskState.DRAFT
    for event, expected in [
        (TaskEvent.CONTRACT_VALIDATED, TaskState.READY_FOR_IMPLEMENTATION),
        (TaskEvent.IMPLEMENTATION_STARTED, TaskState.IMPLEMENTING),
        (TaskEvent.IMPLEMENTATION_REPORT_INGESTED, TaskState.IMPLEMENTED),
        (TaskEvent.VERIFICATION_REQUESTED, TaskState.READY_FOR_VERIFICATION),
        (TaskEvent.VERIFICATION_PASSED, TaskState.VERIFIED_PASS),
        (TaskEvent.CHANGEGATE_PASSED, TaskState.READY_FOR_HUMAN_APPROVAL),
        (TaskEvent.HUMAN_APPROVED, TaskState.APPROVED),
        (TaskEvent.MERGED, TaskState.DONE),
    ]:
        state = transition(state, event)
        assert state is expected


def test_state_machine_fix_loop_and_blocked():
    state = transition(TaskState.READY_FOR_VERIFICATION, TaskEvent.VERIFICATION_FAILED)
    assert state is TaskState.NEEDS_FIX
    assert transition(state, TaskEvent.IMPLEMENTATION_STARTED) is TaskState.IMPLEMENTING
    assert transition(TaskState.IMPLEMENTING, TaskEvent.BLOCKED) is TaskState.BLOCKED
    with pytest.raises(InvalidTransitionError):
        transition(TaskState.DRAFT, TaskEvent.MERGED)


# ---------------------------------------------------------------------------
# 4-6. Prompt generator
# ---------------------------------------------------------------------------

def test_implementer_prompt_contents():
    prompt = generate_prompt(_contract(), AgentRole.IMPLEMENTER)
    for token in (
        "BH-P0-A", "Build DependencyScanner",
        "agent_core/build_harness/**",           # allowed
        "agent_core/conversation/**",             # forbidden
        "pytest tests/test_build_harness_p0_9a_core.py",  # evidence
        "Do not merge.", "Do not push.", "Do not edit forbidden files.",
        "Do not add dependencies unless approved",
        "machine_summary",
    ):
        assert token in prompt, token


def test_verifier_prompt_contents():
    prompt = generate_prompt(_contract(), AgentRole.VERIFIER)
    for token in (
        "Verify only", "Do not edit code", "Do not commit", "Do not merge",
        "Do not push", "PASS / NEEDS_FIX / BLOCKED", "machine_summary",
        "Check scope", "forbidden paths", "dependency files",
    ):
        assert token in prompt, token


def test_release_operator_prompt_contents():
    prompt = generate_prompt(_contract(), AgentRole.RELEASE_OPERATOR)
    for token in (
        "Do not force push", "commit identity", "clean tracked/staged",
        "final remote SHA", "machine_summary",
    ):
        assert token in prompt, token


# ---------------------------------------------------------------------------
# 7-9. Report ingestion
# ---------------------------------------------------------------------------

def test_json_machine_summary_parses():
    report = parse_agent_report(CLAUDE_REPORT_PATH.read_text(encoding="utf-8"))
    assert report.parse_ok
    assert report.task_id == "BH-P0-A"
    assert report.role == "implementer"
    assert report.result == "PASS"
    assert "agent_core/build_harness/dependency_scanner.py" in report.files_changed
    assert report.next_recommended_action == "independent_verification"


def test_yamlish_machine_summary_parses():
    report = parse_agent_report(CODEX_REPORT_PATH.read_text(encoding="utf-8"))
    assert report.parse_ok
    assert report.task_id == "BH-P0-A"
    assert report.role == "verifier"
    assert report.result == "PASS"
    assert report.tests_run == ["pytest tests/test_build_harness_p0_9a_core.py"]
    assert report.blockers == []


def test_missing_machine_summary_fails_closed():
    report = parse_agent_report("# A report with prose only\nEverything looks fine.")
    assert not report.parse_ok
    assert report.result == "BLOCKED"
    assert report.parse_error and "machine_summary" in report.parse_error


# ---------------------------------------------------------------------------
# 10-14. ChangeGate Lite
# ---------------------------------------------------------------------------

def test_changegate_pass_for_allowed_files_and_evidence():
    decision = _pass_gate()
    assert decision.decision == "PASS"
    assert decision.missing_required_evidence == []
    assert decision.matched_required_evidence == [
        "pytest tests/test_build_harness_p0_9a_core.py"
    ]


def test_changegate_blocks_forbidden_path():
    decision = evaluate_change_gate(ChangeGateInput(
        contract=_contract(),
        changed_files=["agent_core/conversation/profile_memory.py"],
        expected_commit_sha=EXPECTED_SHA,
        test_evidence=[_valid_evidence()],
    ))
    assert decision.decision == "BLOCK"
    assert any(f.type == "forbidden_path" and f.severity == "block"
               for f in decision.findings)


def test_changegate_review_for_out_of_scope():
    decision = evaluate_change_gate(ChangeGateInput(
        contract=_contract(),
        changed_files=["agent_core/eval/conversation_eval.py"],
        expected_commit_sha=EXPECTED_SHA,
        test_evidence=[_valid_evidence()],
    ))
    assert decision.decision == "REVIEW_REQUIRED"
    assert any(f.type == "out_of_scope" for f in decision.findings)


def test_changegate_review_for_dependency_file_change():
    decision = evaluate_change_gate(ChangeGateInput(
        contract=_contract(),
        changed_files=["agent_core/build_harness/x.py", "pyproject.toml"],
        expected_commit_sha=EXPECTED_SHA,
        test_evidence=[_valid_evidence()],
    ))
    assert decision.decision == "REVIEW_REQUIRED"
    assert any(f.type == "dependency_change" for f in decision.findings)


def test_changegate_review_for_missing_evidence():
    decision = evaluate_change_gate(ChangeGateInput(
        contract=_contract(),
        changed_files=["agent_core/build_harness/x.py"],
        expected_commit_sha=EXPECTED_SHA,
        test_evidence=[],
    ))
    assert decision.decision == "REVIEW_REQUIRED"
    assert decision.missing_required_evidence == [
        "pytest tests/test_build_harness_p0_9a_core.py"
    ]


# ---------------------------------------------------------------------------
# 15-17. ProcessGuard
# ---------------------------------------------------------------------------

def test_processguard_blocks_merge_without_verifier():
    decision = evaluate_process_guard(ProcessGuardInput(
        contract=_contract(),
        task_state=TaskState.IMPLEMENTED,
        implementer_report=_pass_report("implementer"),
        verifier_report=None,
        changegate_decision=_pass_gate(),
        human_approved=True,
        intended_action="merge",
    ))
    assert decision.decision == "BLOCK"
    assert "verifier_report_pass" in decision.missing_steps


def test_processguard_blocks_push_without_human_approval():
    # APPROVED is the only valid push state (R1), so this isolates the approval check.
    decision = evaluate_process_guard(ProcessGuardInput(
        contract=_contract(),
        task_state=TaskState.APPROVED,
        implementer_report=_pass_report("implementer"),
        verifier_report=_pass_report("verifier"),
        changegate_decision=_pass_gate(),
        human_approved=False,
        intended_action="push",
    ))
    assert decision.decision == "BLOCK"
    assert decision.missing_steps == ["human_approval"]


def test_processguard_blocks_verifier_needs_fix():
    needs_fix = AgentReport(task_id="BH-P0-A", role="verifier",
                            status="NEEDS_FIX", result="NEEDS_FIX")
    decision = evaluate_process_guard(ProcessGuardInput(
        contract=_contract(),
        task_state=TaskState.READY_FOR_VERIFICATION,
        implementer_report=_pass_report("implementer"),
        verifier_report=needs_fix,
        changegate_decision=_pass_gate(),
        human_approved=True,
        intended_action="merge",
    ))
    assert decision.decision == "BLOCK"
    assert "NEEDS_FIX" in decision.reason


def test_processguard_review_when_only_approval_missing():
    decision = evaluate_process_guard(ProcessGuardInput(
        contract=_contract(),
        task_state=TaskState.READY_FOR_MERGE,
        implementer_report=_pass_report("implementer"),
        verifier_report=_pass_report("verifier"),
        changegate_decision=_pass_gate(),
        human_approved=False,
        intended_action="merge",
    ))
    assert decision.decision == "REVIEW_REQUIRED"
    assert decision.missing_steps == ["human_approval"]


# ---------------------------------------------------------------------------
# P0-9A-R1 — fail-closed state enforcement for shipping actions
# ---------------------------------------------------------------------------

def _all_green_guard_input(task_state: TaskState, intended_action: str,
                           human_approved: bool = True) -> ProcessGuardInput:
    return ProcessGuardInput(
        contract=_contract(),
        task_state=task_state,
        implementer_report=_pass_report("implementer"),
        verifier_report=_pass_report("verifier"),
        changegate_decision=_pass_gate(),
        human_approved=human_approved,
        intended_action=intended_action,
    )


@pytest.mark.parametrize("bad_state", [
    TaskState.DRAFT, TaskState.READY_FOR_IMPLEMENTATION, TaskState.IMPLEMENTING,
    TaskState.IMPLEMENTED, TaskState.READY_FOR_VERIFICATION, TaskState.NEEDS_FIX,
    TaskState.BLOCKED, TaskState.VERIFIED_PASS,
])
def test_r1_processguard_blocks_merge_from_invalid_state(bad_state):
    decision = evaluate_process_guard(_all_green_guard_input(bad_state, "merge"))
    assert decision.decision == "BLOCK", (bad_state, decision)
    assert "valid_task_state_for_merge" in decision.missing_steps
    assert bad_state.value in decision.reason


def test_r1_processguard_blocks_push_from_draft():
    decision = evaluate_process_guard(_all_green_guard_input(TaskState.DRAFT, "push"))
    assert decision.decision == "BLOCK"
    assert "valid_task_state_for_push" in decision.missing_steps


def test_r1_processguard_push_only_from_approved():
    # READY_FOR_MERGE is valid for merge but NOT for push.
    decision = evaluate_process_guard(
        _all_green_guard_input(TaskState.READY_FOR_MERGE, "push")
    )
    assert decision.decision == "BLOCK"
    assert "valid_task_state_for_push" in decision.missing_steps
    approved = evaluate_process_guard(_all_green_guard_input(TaskState.APPROVED, "push"))
    assert approved.decision == "PASS"


def test_r1_processguard_merge_passes_from_ready_for_merge_and_approved():
    for state in (TaskState.READY_FOR_MERGE, TaskState.APPROVED):
        decision = evaluate_process_guard(_all_green_guard_input(state, "merge"))
        assert decision.decision == "PASS", (state, decision)


def test_r1_processguard_done_only_from_approved_or_done():
    for state in (TaskState.APPROVED, TaskState.DONE):
        decision = evaluate_process_guard(_all_green_guard_input(state, "done"))
        assert decision.decision == "PASS", (state, decision)
    blocked = evaluate_process_guard(_all_green_guard_input(TaskState.IMPLEMENTED, "done"))
    assert blocked.decision == "BLOCK"
    assert "valid_task_state_for_done" in blocked.missing_steps


def test_r1_processguard_needs_fix_still_blocks_regardless_of_state():
    needs_fix = AgentReport(task_id="BH-P0-A", role="verifier",
                            status="NEEDS_FIX", result="NEEDS_FIX")
    for state in (TaskState.APPROVED, TaskState.READY_FOR_MERGE, TaskState.DRAFT):
        decision = evaluate_process_guard(ProcessGuardInput(
            contract=_contract(),
            task_state=state,
            implementer_report=_pass_report("implementer"),
            verifier_report=needs_fix,
            changegate_decision=_pass_gate(),
            human_approved=True,
            intended_action="merge",
        ))
        assert decision.decision == "BLOCK", state
        assert "NEEDS_FIX" in decision.reason


def test_r1_processguard_state_block_reports_other_missing_steps_too():
    # Merge from IMPLEMENTED with a missing verifier: both problems are surfaced.
    decision = evaluate_process_guard(ProcessGuardInput(
        contract=_contract(),
        task_state=TaskState.IMPLEMENTED,
        implementer_report=_pass_report("implementer"),
        verifier_report=None,
        changegate_decision=_pass_gate(),
        human_approved=True,
        intended_action="merge",
    ))
    assert decision.decision == "BLOCK"
    assert "valid_task_state_for_merge" in decision.missing_steps
    assert "verifier_report_pass" in decision.missing_steps


def test_processguard_blocks_unparseable_report():
    broken = parse_agent_report("prose only, no summary")
    decision = evaluate_process_guard(ProcessGuardInput(
        contract=_contract(),
        task_state=TaskState.IMPLEMENTED,
        implementer_report=broken,
        verifier_report=None,
        changegate_decision=None,
        human_approved=False,
        intended_action="continue",
    ))
    assert decision.decision == "BLOCK"


# ---------------------------------------------------------------------------
# 18-19. NextAction recommender
# ---------------------------------------------------------------------------

def test_next_action_no_implementer_report():
    action = recommend_next_action(_contract(), None, None, None, None)
    assert action.action == "SEND_TO_IMPLEMENTER"
    assert action.prompt and "Do not merge." in action.prompt


def test_next_action_verifier_after_implementer_pass():
    implementer = parse_agent_report(CLAUDE_REPORT_PATH.read_text(encoding="utf-8"))
    action = recommend_next_action(_contract(), implementer, None, None, None)
    assert action.action == "SEND_TO_VERIFIER"
    assert action.prompt and "Verify only" in action.prompt


def test_next_action_fix_prompt_on_needs_fix():
    implementer = parse_agent_report(CLAUDE_REPORT_PATH.read_text(encoding="utf-8"))
    needs_fix = AgentReport(task_id="BH-P0-A", role="verifier", status="NEEDS_FIX",
                            result="NEEDS_FIX", blockers=["missing tests"])
    action = recommend_next_action(_contract(), implementer, needs_fix, None, None)
    assert action.action == "SEND_FIX_PROMPT_TO_IMPLEMENTER"
    assert action.prompt and "missing tests" in action.prompt


def test_next_action_requests_human_approval_when_gates_pass():
    implementer = parse_agent_report(CLAUDE_REPORT_PATH.read_text(encoding="utf-8"))
    verifier = parse_agent_report(CODEX_REPORT_PATH.read_text(encoding="utf-8"))
    gate = _pass_gate()
    guard = evaluate_process_guard(ProcessGuardInput(
        contract=_contract(),
        task_state=TaskState.READY_FOR_MERGE,
        implementer_report=implementer, verifier_report=verifier,
        changegate_decision=gate, human_approved=False, intended_action="merge",
    ))
    action = recommend_next_action(_contract(), implementer, verifier, gate, guard)
    assert action.action == "REQUEST_HUMAN_APPROVAL"


def test_next_action_ready_when_approved():
    implementer = parse_agent_report(CLAUDE_REPORT_PATH.read_text(encoding="utf-8"))
    verifier = parse_agent_report(CODEX_REPORT_PATH.read_text(encoding="utf-8"))
    gate = _pass_gate()
    guard = evaluate_process_guard(ProcessGuardInput(
        contract=_contract(),
        task_state=TaskState.APPROVED,
        implementer_report=implementer, verifier_report=verifier,
        changegate_decision=gate, human_approved=True, intended_action="merge",
    ))
    action = recommend_next_action(_contract(), implementer, verifier, gate, guard)
    assert action.action == "READY_FOR_MERGE_OR_PUSH"
    assert action.prompt and "Do not force push" in action.prompt


def test_next_action_review_on_changegate_review():
    implementer = parse_agent_report(CLAUDE_REPORT_PATH.read_text(encoding="utf-8"))
    verifier = parse_agent_report(CODEX_REPORT_PATH.read_text(encoding="utf-8"))
    review_gate = evaluate_change_gate(ChangeGateInput(
        contract=_contract(),
        changed_files=["pyproject.toml"],
        expected_commit_sha=EXPECTED_SHA,
        test_evidence=[_valid_evidence()],
    ))
    action = recommend_next_action(_contract(), implementer, verifier, review_gate, None)
    assert action.action == "REQUEST_HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# 20-21. EvidenceStore
# ---------------------------------------------------------------------------

def test_evidence_store_saves_all_artifact_kinds(tmp_path):
    store = EvidenceStore(tmp_path)
    contract = _contract()
    store.save_contract(contract)
    store.save_prompt(contract.task_id, "implementer",
                      generate_prompt(contract, AgentRole.IMPLEMENTER))
    store.save_report(contract.task_id, "implementer",
                      CLAUDE_REPORT_PATH.read_text(encoding="utf-8"))
    store.save_gate_result(contract.task_id, "changegate", _pass_gate().to_dict())
    store.append_event(contract.task_id, "contract_validated", {"by": "test"})
    store.append_event(contract.task_id, "implementation_report_ingested", {})

    task_dir = tmp_path / contract.task_id
    assert (task_dir / "contract.json").exists()
    assert (task_dir / "prompts" / "implementer.md").exists()
    assert (task_dir / "reports" / "implementer.md").exists()
    assert (task_dir / "gate" / "changegate.json").exists()
    events = (task_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 2
    first = json.loads(events[0])
    assert first["task_id"] == contract.task_id
    assert first["event_type"] == "contract_validated"
    assert "timestamp" in first


def test_evidence_store_summary_contains_structured_artifacts(tmp_path):
    store = EvidenceStore(tmp_path)
    contract = _contract()
    store.save_contract(contract)
    store.save_prompt(contract.task_id, "verifier",
                      generate_prompt(contract, AgentRole.VERIFIER))
    store.save_gate_result(contract.task_id, "processguard", {"decision": "PASS"})
    store.append_event(contract.task_id, "verification_passed", {})

    summary = store.load_task_summary(contract.task_id)
    assert summary["contract"]["task_id"] == "BH-P0-A"
    assert "verifier" in summary["prompts"]
    assert summary["gates"]["processguard"]["decision"] == "PASS"
    assert summary["events"][0]["event_type"] == "verification_passed"


# ---------------------------------------------------------------------------
# 22-24. CLI
# ---------------------------------------------------------------------------

def test_cli_validate_contract(capsys):
    rc = cli_main(["validate-contract", "--contract", str(CONTRACT_PATH)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["ok"] is True
    assert out["contract"]["task_id"] == "BH-P0-A"


def test_cli_validate_contract_invalid(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"title": "no task_id"}', encoding="utf-8")
    with pytest.raises(SystemExit):
        cli_main(["validate-contract", "--contract", str(bad)])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "task_id" in out["error"]


def test_cli_generate_prompt(capsys):
    rc = cli_main(["generate-prompt", "--contract", str(CONTRACT_PATH),
                   "--role", "implementer"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Do not merge." in out and "Do not push." in out
    assert "machine_summary" in out


def test_cli_changegate_pass_with_structured_evidence(capsys):
    rc = cli_main([
        "changegate", "--contract", str(CONTRACT_PATH),
        "--changed-files", "agent_core/build_harness/contracts.py",
        "tests/test_build_harness_p0_9a_core.py",
        "--expected-commit", EXPECTED_SHA,
        "--evidence-file", str(ROOT / "examples/build_harness/evidence.json"),
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["decision"] == "PASS"
    assert out["expected_commit_sha"] == EXPECTED_SHA
    assert out["matched_required_evidence"] and not out["missing_required_evidence"]


def test_cli_changegate_legacy_strings_review_exits_nonzero(capsys):
    # R2: a bare --tests-run string is unverified legacy evidence — never PASS/exit 0.
    rc = cli_main([
        "changegate", "--contract", str(CONTRACT_PATH),
        "--changed-files", "agent_core/build_harness/contracts.py",
        "--tests-run", "pytest tests/test_build_harness_p0_9a_core.py",
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc != 0 and out["decision"] == "REVIEW_REQUIRED"
    assert out["missing_required_evidence"]


def test_cli_ingest_report(capsys):
    rc = cli_main([
        "ingest-report", "--contract", str(CONTRACT_PATH),
        "--report", str(CLAUDE_REPORT_PATH), "--role", "implementer",
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["ok"] is True
    assert out["parse_ok"] is True and out["result"] == "PASS"
    assert out["task_matches"] is True and out["role_matches"] is True
    assert out["requested_role"] == "implementer"


# ---------------------------------------------------------------------------
# P0-9A-R1 — fail-closed ingest-report exit codes
# ---------------------------------------------------------------------------

def _write_report(tmp_path: Path, task_id: str, role: str, result: str,
                  status: str | None = None) -> Path:
    if status is None:
        status = {"PASS": _PASS_STATUS_BY_ROLE.get(role, "IMPLEMENTED"),
                  "NEEDS_FIX": "NEEDS_FIX", "BLOCKED": "BLOCKED"}[result]
    path = tmp_path / f"{role}_{result.lower()}.md"
    path.write_text(
        "machine_summary:\n"
        f"  task_id: {task_id}\n"
        f"  role: {role}\n"
        f"  status: {status}\n"
        f"  result: {result}\n"
        "  files_changed: []\n"
        "  tests_run: []\n"
        "  blockers: []\n"
        "  next_recommended_action: human_review\n",
        encoding="utf-8",
    )
    return path


def test_r1_cli_ingest_blocked_report_exits_nonzero(tmp_path, capsys):
    report = _write_report(tmp_path, "BH-P0-A", "implementer", "BLOCKED")
    rc = cli_main(["ingest-report", "--contract", str(CONTRACT_PATH),
                   "--report", str(report), "--role", "implementer"])
    out = json.loads(capsys.readouterr().out)
    assert rc != 0 and out["ok"] is False
    assert out["parse_ok"] is True and out["result"] == "BLOCKED"
    assert any("BLOCKED" in r for r in out["rejection_reasons"])


def test_r1_cli_ingest_role_mismatch_exits_nonzero(capsys):
    # The codex fixture is a verifier report — submitting it as implementer must fail.
    rc = cli_main(["ingest-report", "--contract", str(CONTRACT_PATH),
                   "--report", str(CODEX_REPORT_PATH), "--role", "implementer"])
    out = json.loads(capsys.readouterr().out)
    assert rc != 0 and out["ok"] is False
    assert out["role_matches"] is False and out["task_matches"] is True
    assert any("role mismatch" in r for r in out["rejection_reasons"])


def test_r1_cli_ingest_task_mismatch_exits_nonzero(tmp_path, capsys):
    report = _write_report(tmp_path, "WRONG-TASK", "implementer", "PASS")
    rc = cli_main(["ingest-report", "--contract", str(CONTRACT_PATH),
                   "--report", str(report), "--role", "implementer"])
    out = json.loads(capsys.readouterr().out)
    assert rc != 0 and out["ok"] is False
    assert out["task_matches"] is False
    assert any("task mismatch" in r for r in out["rejection_reasons"])


def test_r1_cli_ingest_unparseable_report_exits_nonzero(tmp_path, capsys):
    report = tmp_path / "prose.md"
    report.write_text("No machine summary here.", encoding="utf-8")
    rc = cli_main(["ingest-report", "--contract", str(CONTRACT_PATH),
                   "--report", str(report), "--role", "implementer"])
    out = json.loads(capsys.readouterr().out)
    assert rc != 0 and out["ok"] is False and out["parse_ok"] is False


def test_r1_cli_ingest_needs_fix_with_matches_exits_zero(tmp_path, capsys):
    # NEEDS_FIX ingests fine — the verdict is ProcessGuard/NextAction's job. R2: the
    # NEEDS_FIX vocabulary belongs to the verifier role.
    report = _write_report(tmp_path, "BH-P0-A", "verifier", "NEEDS_FIX")
    rc = cli_main(["ingest-report", "--contract", str(CONTRACT_PATH),
                   "--report", str(report), "--role", "verifier"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["ok"] is True and out["result"] == "NEEDS_FIX"


def test_cli_next_action_with_reports(capsys):
    rc = cli_main([
        "next-action", "--contract", str(CONTRACT_PATH),
        "--implementer-report", str(CLAUDE_REPORT_PATH),
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["action"] == "SEND_TO_VERIFIER"


# ---------------------------------------------------------------------------
# Scenario fixtures (data/evals/p0_9a_build_harness_cases.json)
# ---------------------------------------------------------------------------

def _load_eval_suite() -> dict:
    return json.loads(EVAL_CASES_PATH.read_text(encoding="utf-8"))


def _suite_evidence(suite: dict, case: dict) -> list[CommandEvidence]:
    if not case.get("use_valid_evidence"):
        return []
    return [CommandEvidence(**entry) for entry in suite["valid_evidence"]]


@pytest.mark.parametrize(
    "case", _load_eval_suite()["cases"], ids=lambda c: c["id"]
)
def test_eval_scenario_cases(case):
    suite = _load_eval_suite()
    contract = _contract()
    expected_sha = suite["expected_commit_sha"]
    if case["kind"] == "changegate":
        decision = evaluate_change_gate(ChangeGateInput(
            contract=contract,
            changed_files=case["changed_files"],
            tests_run=case.get("tests_run", []),
            expected_commit_sha=expected_sha,
            test_evidence=_suite_evidence(suite, case),
        ))
        assert decision.decision == case["expected_decision"], decision
        return

    implementer = verifier = None
    if case.get("implementer_report_path"):
        implementer = parse_agent_report(
            (ROOT / case["implementer_report_path"]).read_text(encoding="utf-8"))
    if case.get("verifier_report_path"):
        verifier = parse_agent_report(
            (ROOT / case["verifier_report_path"]).read_text(encoding="utf-8"))

    if case["kind"] == "next_action":
        action = recommend_next_action(contract, implementer, verifier, None, None)
        assert action.action == case["expected_action"], action
        return

    # next_action_full: run both gates first. R1/R2: READY_FOR_MERGE is the gates-passed
    # shipping stage; ChangeGate PASS requires the structured commit-bound evidence.
    gate = evaluate_change_gate(ChangeGateInput(
        contract=contract,
        changed_files=case["changed_files"],
        tests_run=case.get("tests_run", []),
        expected_commit_sha=expected_sha,
        test_evidence=_suite_evidence(suite, case),
    ))
    guard = evaluate_process_guard(ProcessGuardInput(
        contract=contract,
        task_state=TaskState.READY_FOR_MERGE,
        implementer_report=implementer,
        verifier_report=verifier,
        changegate_decision=gate,
        human_approved=case["human_approved"],
        intended_action=case["intended_action"],
    ))
    action = recommend_next_action(contract, implementer, verifier, gate, guard)
    assert action.action == case["expected_action"], (gate, guard, action)


# ---------------------------------------------------------------------------
# 25. Existing P0-8B eval runner still passes
# ---------------------------------------------------------------------------

def test_p0_8b_golden_eval_still_passes():
    from agent_core.eval.conversation_eval import load_suite, run_suite
    suite = load_suite(ROOT / "data/evals/p0_8b_golden_conversations.json")
    result = run_suite(suite)
    assert result.failed == 0 and result.cases >= 12

"""P0-9A — ProcessGuard: did the delivery PROCESS actually happen, in order?

ChangeGate judges the change; ProcessGuard judges the workflow around it — reports
present, trusted, and passing; gates passed; a human in the loop before anything ships.
Fail-closed: a missing artifact is a missing step, never an implicit pass.

P0-9A-R2 hardening:
- intended actions are a closed ``IntendedAction`` enum; unknown/empty/case-variant
  inputs BLOCK instead of being treated as a non-shipping continuation;
- the guard REVALIDATES report identity itself (never trusting CLI ingestion): a report
  is trusted only when it parsed, its task_id matches the contract, its role matches the
  slot it was supplied in, and its (role, status, result) combination is allowed;
- ``deploy`` is modeled explicitly; push and deploy require human approval;
- shipping actions are only legal from explicit task states.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent_core.build_harness.change_gate import (
    ChangeGateDecision,
    validate_change_gate_decision,
)
from agent_core.build_harness.contracts import TaskContract
from agent_core.build_harness.reports import AgentReport, is_allowed_status_result
from agent_core.build_harness.state import TaskState


class IntendedAction(StrEnum):
    CONTINUE = "continue"
    MERGE = "merge"
    PUSH = "push"
    DEPLOY = "deploy"
    DONE = "done"


_SHIP_ACTIONS = frozenset({
    IntendedAction.MERGE, IntendedAction.PUSH, IntendedAction.DEPLOY, IntendedAction.DONE,
})

# Shipping actions are only legal from these task states (P0-9A-R1/R2). Green reports and
# gates are NOT enough — a merge attempted from DRAFT/IMPLEMENTED means the workflow
# itself was skipped, so the guard fails closed regardless of artifact quality.
_VALID_SHIP_STATES: dict[IntendedAction, frozenset[TaskState]] = {
    IntendedAction.MERGE: frozenset({TaskState.READY_FOR_MERGE, TaskState.APPROVED}),
    IntendedAction.PUSH: frozenset({TaskState.APPROVED}),
    IntendedAction.DEPLOY: frozenset({TaskState.APPROVED}),
    IntendedAction.DONE: frozenset({TaskState.APPROVED, TaskState.DONE}),
}

# push/deploy are hard-gated on human approval (BLOCK); merge/done surface a missing
# approval as REVIEW_REQUIRED so the recommender can ask for it.
_APPROVAL_HARD_ACTIONS = frozenset({IntendedAction.PUSH, IntendedAction.DEPLOY})


@dataclass(frozen=True)
class ProcessGuardInput:
    contract: TaskContract
    task_state: TaskState
    implementer_report: AgentReport | None
    verifier_report: AgentReport | None
    changegate_decision: ChangeGateDecision | None
    human_approved: bool
    intended_action: IntendedAction | str  # raw strings are validated fail-closed


@dataclass(frozen=True)
class ProcessGuardDecision:
    decision: str  # PASS / REVIEW_REQUIRED / BLOCK
    missing_steps: list[str]
    reason: str

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "missing_steps": self.missing_steps,
            "reason": self.reason,
        }


def _report_identity_error(
    report: AgentReport | None, contract: TaskContract, expected_role: str
) -> str | None:
    """None when the report slot is trustworthy (or empty); else the rejection reason.

    This runs on every evaluation — ProcessGuard never trusts upstream CLI validation.
    """
    if report is None:
        return None
    if not report.parse_ok:
        return f"{expected_role} report is unparseable: {report.parse_error}"
    if report.task_id != contract.task_id:
        return (
            f"{expected_role} report belongs to task {report.task_id!r}, "
            f"contract is {contract.task_id!r}"
        )
    if report.role != expected_role:
        return (
            f"report in the {expected_role} slot has role {report.role!r}"
        )
    if not is_allowed_status_result(report.role, report.status, report.result):
        return (
            f"{expected_role} report has a contradictory status/result: "
            f"status={report.status!r}, result={report.result!r}"
        )
    return None


def evaluate_process_guard(guard_input: ProcessGuardInput) -> ProcessGuardDecision:
    # 0. Action must be a known enum member — unknown/empty/case-variant fails closed.
    raw_action = guard_input.intended_action
    if isinstance(raw_action, IntendedAction):
        action = raw_action
    else:
        try:
            action = IntendedAction(raw_action)
        except (ValueError, TypeError):
            return ProcessGuardDecision(
                decision="BLOCK", missing_steps=["valid_intended_action"],
                reason=f"unknown intended_action {raw_action!r}; allowed: "
                       f"{[a.value for a in IntendedAction]}",
            )

    contract = guard_input.contract

    # 1. Report identity revalidation — wrong task, swapped role, or contradictory
    # status/result can never authorize anything.
    for report, slot in (
        (guard_input.implementer_report, "implementer"),
        (guard_input.verifier_report, "verifier"),
    ):
        identity_error = _report_identity_error(report, contract, slot)
        if identity_error is not None:
            return ProcessGuardDecision(
                decision="BLOCK", missing_steps=[f"trusted_{slot}_report"],
                reason=identity_error,
            )

    impl = guard_input.implementer_report
    verifier = guard_input.verifier_report
    impl_result = impl.result if impl is not None else None
    verifier_result = verifier.result if verifier is not None else None

    # 2. Hard blocks — a blocked artifact or failed verification can never ship.
    if impl_result == "BLOCKED" or verifier_result == "BLOCKED":
        return ProcessGuardDecision(
            decision="BLOCK", missing_steps=[],
            reason="an agent report is BLOCKED; resolve it before proceeding",
        )
    if verifier_result == "NEEDS_FIX":
        return ProcessGuardDecision(
            decision="BLOCK", missing_steps=["fix_and_reverify"],
            reason="verifier returned NEEDS_FIX",
        )

    # R3: a ChangeGateDecision is only trusted when it is PASS AND internally consistent.
    gate = guard_input.changegate_decision
    gate_integrity_errors: list[str] = []
    gate_is_pass = gate is not None and getattr(gate, "decision", None) == "PASS"
    if gate_is_pass:
        gate_integrity_errors = validate_change_gate_decision(contract, gate)

    shipping = action in _SHIP_ACTIONS
    missing: list[str] = []
    if shipping:
        valid_states = _VALID_SHIP_STATES[action]
        if guard_input.task_state not in valid_states:
            missing.append(f"valid_task_state_for_{action.value}")
        if impl_result != "PASS":
            missing.append("implementer_report_pass")
        if verifier_result != "PASS":
            missing.append("verifier_report_pass")
        if gate is None or getattr(gate, "decision", None) != "PASS":
            missing.append("changegate_pass")
        elif gate_integrity_errors:
            missing.append("valid_changegate_decision")
        if missing:
            reason = (
                f"cannot ship from task_state={guard_input.task_state.value}: "
                "missing " + ", ".join(missing)
            )
            if "valid_changegate_decision" in missing:
                reason += (
                    "; ChangeGateDecision marked PASS is internally inconsistent: "
                    + "; ".join(gate_integrity_errors)
                )
            return ProcessGuardDecision(
                decision="BLOCK", missing_steps=missing, reason=reason,
            )
        if action in _APPROVAL_HARD_ACTIONS and not guard_input.human_approved:
            return ProcessGuardDecision(
                decision="BLOCK", missing_steps=["human_approval"],
                reason=f"cannot {action.value} without human approval",
            )
        if not guard_input.human_approved:
            return ProcessGuardDecision(
                decision="REVIEW_REQUIRED", missing_steps=["human_approval"],
                reason="all gates pass but human approval is missing",
            )
        return ProcessGuardDecision(
            decision="PASS", missing_steps=[],
            reason="all reports, gates, and human approval are in place",
        )

    # Non-shipping continuation: report what is still outstanding, never block progress.
    if impl_result != "PASS":
        missing.append("implementer_report_pass")
    if verifier_result != "PASS":
        missing.append("verifier_report_pass")
    if gate is None or getattr(gate, "decision", None) != "PASS":
        missing.append("changegate_pass")
    elif gate_integrity_errors:
        missing.append("valid_changegate_decision")
    if not guard_input.human_approved:
        missing.append("human_approval")
    if missing:
        return ProcessGuardDecision(
            decision="REVIEW_REQUIRED", missing_steps=missing,
            reason="workflow incomplete: " + ", ".join(missing),
        )
    return ProcessGuardDecision(
        decision="PASS", missing_steps=[], reason="workflow complete",
    )

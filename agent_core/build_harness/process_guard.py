"""P0-9A — ProcessGuard: did the delivery PROCESS actually happen, in order?

ChangeGate judges the change; ProcessGuard judges the workflow around it — reports
present and passing, gates passed, and a human in the loop before anything ships.
Fail-closed: a missing artifact is a missing step, never an implicit pass.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent_core.build_harness.change_gate import ChangeGateDecision
from agent_core.build_harness.reports import AgentReport
from agent_core.build_harness.state import TaskState

_SHIP_ACTIONS = ("merge", "push", "done")


@dataclass(frozen=True)
class ProcessGuardInput:
    task_state: TaskState
    implementer_report: AgentReport | None
    verifier_report: AgentReport | None
    changegate_decision: ChangeGateDecision | None
    human_approved: bool
    intended_action: str  # merge / push / done / continue


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


def _report_result(report: AgentReport | None) -> str | None:
    if report is None:
        return None
    if not report.parse_ok:
        return "BLOCKED"
    return report.result.upper()


def evaluate_process_guard(guard_input: ProcessGuardInput) -> ProcessGuardDecision:
    missing: list[str] = []
    impl_result = _report_result(guard_input.implementer_report)
    verifier_result = _report_result(guard_input.verifier_report)

    # Hard blocks first — a broken artifact can never ship.
    if impl_result == "BLOCKED" or verifier_result == "BLOCKED":
        return ProcessGuardDecision(
            decision="BLOCK", missing_steps=[],
            reason="an agent report is BLOCKED (or unparseable); resolve it before proceeding",
        )
    if verifier_result == "NEEDS_FIX":
        return ProcessGuardDecision(
            decision="BLOCK", missing_steps=["fix_and_reverify"],
            reason="verifier returned NEEDS_FIX",
        )

    shipping = guard_input.intended_action in _SHIP_ACTIONS
    if shipping:
        if impl_result != "PASS":
            missing.append("implementer_report_pass")
        if verifier_result != "PASS":
            missing.append("verifier_report_pass")
        if guard_input.changegate_decision is None or guard_input.changegate_decision.decision != "PASS":
            missing.append("changegate_pass")
        if missing:
            return ProcessGuardDecision(
                decision="BLOCK", missing_steps=missing,
                reason="cannot ship without: " + ", ".join(missing),
            )
        if guard_input.intended_action == "push" and not guard_input.human_approved:
            return ProcessGuardDecision(
                decision="BLOCK", missing_steps=["human_approval"],
                reason="cannot push without human approval",
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
    if guard_input.changegate_decision is None or guard_input.changegate_decision.decision != "PASS":
        missing.append("changegate_pass")
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

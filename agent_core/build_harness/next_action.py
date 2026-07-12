"""P0-9A — NextAction recommender: the single "what now?" answer for a task.

Deterministic rule cascade over the artifacts collected so far. When the action is a
handoff to an agent, the recommendation carries the generated role prompt so the
operator can paste it directly.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent_core.build_harness.change_gate import ChangeGateDecision
from agent_core.build_harness.contracts import TaskContract
from agent_core.build_harness.process_guard import ProcessGuardDecision
from agent_core.build_harness.prompt_generator import AgentRole, generate_prompt
from agent_core.build_harness.reports import AgentReport


@dataclass(frozen=True)
class NextAction:
    action: str
    reason: str
    prompt: str | None = None

    def to_dict(self) -> dict:
        return {"action": self.action, "reason": self.reason, "prompt": self.prompt}


def _identity_error(
    report: AgentReport | None, contract: TaskContract, expected_role: str
) -> str | None:
    """P0-9A-R2: a report with the wrong task/role identity can never drive a handoff."""
    if report is None or not report.parse_ok:
        return None  # parse failures are handled by the dedicated branches below
    if report.task_id != contract.task_id:
        return (
            f"{expected_role} report belongs to task {report.task_id!r}, "
            f"contract is {contract.task_id!r}"
        )
    if report.role != expected_role:
        return f"report in the {expected_role} slot has role {report.role!r}"
    return None


def recommend_next_action(
    contract: TaskContract,
    implementer_report: AgentReport | None,
    verifier_report: AgentReport | None,
    changegate_decision: ChangeGateDecision | None,
    processguard_decision: ProcessGuardDecision | None,
) -> NextAction:
    # 0. P0-9A-R2 severity-first: invalid report identity is a hard stop for any
    # recommendation beyond a human look — and can never lead to the release branch.
    for report, slot in (
        (implementer_report, "implementer"), (verifier_report, "verifier"),
    ):
        identity_error = _identity_error(report, contract, slot)
        if identity_error is not None:
            return NextAction(
                action="ESCALATE_TO_HUMAN",
                reason=f"report identity is invalid: {identity_error}",
            )

    # 1. Nothing implemented yet → send to implementer.
    if implementer_report is None:
        return NextAction(
            action="SEND_TO_IMPLEMENTER",
            reason="no implementer report has been ingested for this task",
            prompt=generate_prompt(contract, AgentRole.IMPLEMENTER),
        )

    # 2. A broken/blocked implementer report needs a human, not another agent hop.
    if not implementer_report.parse_ok or implementer_report.result.upper() == "BLOCKED":
        return NextAction(
            action="ESCALATE_TO_HUMAN",
            reason="implementer report is BLOCKED or unparseable: "
                   f"{implementer_report.parse_error or 'reported blocked'}",
        )

    # 3. Verifier fix loop.
    if verifier_report is not None and verifier_report.result.upper() == "NEEDS_FIX":
        fix_prompt = generate_prompt(contract, AgentRole.IMPLEMENTER) + (
            "\n\n## Fix context\nThe independent verifier returned NEEDS_FIX. Address the "
            "verifier's blockers, then report again:\n"
            + "\n".join(f"- {b}" for b in verifier_report.blockers or ["(see verifier report)"])
        )
        return NextAction(
            action="SEND_FIX_PROMPT_TO_IMPLEMENTER",
            reason="verifier returned NEEDS_FIX",
            prompt=fix_prompt,
        )

    # 4. Implemented but not independently verified.
    if verifier_report is None:
        return NextAction(
            action="SEND_TO_VERIFIER",
            reason="implementer reported PASS; independent verification is missing",
            prompt=generate_prompt(contract, AgentRole.VERIFIER),
        )

    # 5. Gate outcomes.
    if changegate_decision is not None and changegate_decision.decision == "BLOCK":
        return NextAction(
            action="SEND_FIX_PROMPT_TO_IMPLEMENTER",
            reason="ChangeGate blocked the change: "
                   + "; ".join(f.reason for f in changegate_decision.findings
                               if f.severity == "block"),
            prompt=generate_prompt(contract, AgentRole.IMPLEMENTER),
        )
    if changegate_decision is not None and changegate_decision.decision == "REVIEW_REQUIRED":
        return NextAction(
            action="REQUEST_HUMAN_REVIEW",
            reason="ChangeGate requires human review: "
                   + "; ".join(f.reason for f in changegate_decision.findings) ,
        )

    # 6. P0-9A-R2: a ProcessGuard BLOCK is a hard stop — release is never recommended.
    if processguard_decision is not None and processguard_decision.decision == "BLOCK":
        return NextAction(
            action="REQUEST_HUMAN_REVIEW",
            reason="ProcessGuard blocked the workflow: " + processguard_decision.reason,
        )

    # 7. Everything passing but approval outstanding.
    if processguard_decision is not None and processguard_decision.decision == "REVIEW_REQUIRED" \
            and "human_approval" in processguard_decision.missing_steps:
        return NextAction(
            action="REQUEST_HUMAN_APPROVAL",
            reason="all gates pass but human approval is missing",
        )

    # 8. Fully green — the ONLY branch that recommends release, and it is reachable only
    # with a ProcessGuard PASS (which itself revalidated report identity and state).
    if processguard_decision is not None and processguard_decision.decision == "PASS":
        return NextAction(
            action="READY_FOR_MERGE_OR_PUSH",
            reason="all reports, gates, and human approval are in place",
            prompt=generate_prompt(contract, AgentRole.RELEASE_OPERATOR),
        )

    # Default: something is outstanding but not classified above — ask a human.
    return NextAction(
        action="REQUEST_HUMAN_REVIEW",
        reason="workflow state is ambiguous; a human should inspect the evidence",
    )

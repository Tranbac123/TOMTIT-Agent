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


def recommend_next_action(
    contract: TaskContract,
    implementer_report: AgentReport | None,
    verifier_report: AgentReport | None,
    changegate_decision: ChangeGateDecision | None,
    processguard_decision: ProcessGuardDecision | None,
) -> NextAction:
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

    # 6. Everything passing but approval outstanding.
    if processguard_decision is not None and processguard_decision.decision == "REVIEW_REQUIRED" \
            and "human_approval" in processguard_decision.missing_steps:
        return NextAction(
            action="REQUEST_HUMAN_APPROVAL",
            reason="all gates pass but human approval is missing",
        )

    # 7. Fully green.
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

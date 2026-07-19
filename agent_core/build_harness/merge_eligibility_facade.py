"""Fixed-policy public composition for ChangeGate merge eligibility."""
from __future__ import annotations

from typing import Final

from agent_core.build_harness.merge_eligibility import (
    MERGE_ELIGIBILITY_POLICY_V1,
    MergeEligibilityPolicy,
    MergeEligibilityPolicyInput,
    evaluate_decision_core,
)
from agent_core.build_harness.merge_eligibility_record import (
    MergeEligibilityDecision,
    PolicyEvaluationRecord,
    build_policy_evaluation_record,
    finalize_decision,
)

_PRODUCTION_POLICY: Final[MergeEligibilityPolicy] = MERGE_ELIGIBILITY_POLICY_V1


def evaluate_merge_eligibility(policy_input: MergeEligibilityPolicyInput) -> tuple[MergeEligibilityDecision, PolicyEvaluationRecord]:
    core = evaluate_decision_core(policy_input, _PRODUCTION_POLICY)
    decision = finalize_decision(policy_input, core)
    record = build_policy_evaluation_record(policy_input, decision)
    return decision, record

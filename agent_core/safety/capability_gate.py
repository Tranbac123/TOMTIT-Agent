"""CONV-P0 P0-8A — capability-level safety/permission gate.

A small declarative policy over action risk classes, used by the capability layer and the
tool-runtime scaffold BEFORE anything executes. This complements (does not replace) the
per-tool ``PolicyEngine``/``ApprovalGate`` guarding ``ToolExecutor`` — real tools still go
through that single execution gate; this gate is the conversation-level policy for the
P0-8A capability lanes, where external/irreversible actions are never executed in MVP.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ActionRisk(StrEnum):
    READ_ONLY = "read_only"
    MEMORY_WRITE = "memory_write"
    MEMORY_DELETE = "memory_delete"
    EXTERNAL_ACTION = "external_action"
    IRREVERSIBLE_ACTION = "irreversible_action"
    HIGH_RISK = "high_risk"


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    requires_confirmation: bool
    risk: ActionRisk
    reason: str


# MVP policy table. EXTERNAL/IRREVERSIBLE are "allowed=False" in the execution sense:
# nothing may run; the runtime answers with a confirmation-needed/current-limitation
# response instead. MEMORY_DELETE is allowed only via the existing pending-confirmation
# flow (the gate encodes the policy; SessionRuntime's delete lane implements the flow).
_POLICY: dict[ActionRisk, SafetyDecision] = {
    ActionRisk.READ_ONLY: SafetyDecision(
        allowed=True, requires_confirmation=False, risk=ActionRisk.READ_ONLY,
        reason="read-only action; no side effects",
    ),
    ActionRisk.MEMORY_WRITE: SafetyDecision(
        allowed=True, requires_confirmation=False, risk=ActionRisk.MEMORY_WRITE,
        reason="memory write via existing deterministic write lanes",
    ),
    ActionRisk.MEMORY_DELETE: SafetyDecision(
        allowed=True, requires_confirmation=True, risk=ActionRisk.MEMORY_DELETE,
        reason="memory delete allowed only through the pending-confirmation flow",
    ),
    ActionRisk.EXTERNAL_ACTION: SafetyDecision(
        allowed=False, requires_confirmation=True, risk=ActionRisk.EXTERNAL_ACTION,
        reason="external actions are not executed in MVP; confirmation + tool support required",
    ),
    ActionRisk.IRREVERSIBLE_ACTION: SafetyDecision(
        allowed=False, requires_confirmation=True, risk=ActionRisk.IRREVERSIBLE_ACTION,
        reason="irreversible actions are never executed in MVP",
    ),
    ActionRisk.HIGH_RISK: SafetyDecision(
        allowed=False, requires_confirmation=False, risk=ActionRisk.HIGH_RISK,
        reason="high-risk request refused",
    ),
}


class CapabilitySafetyGate:
    """Declarative risk → decision mapping. Deterministic; no I/O."""

    def evaluate(self, risk: ActionRisk) -> SafetyDecision:
        return _POLICY[risk]

"""P0-9A — deterministic task state machine.

A plain transition table — no async orchestration, no side effects. Undefined
(state, event) pairs raise instead of guessing, so a harness bug surfaces immediately.

Canonical happy path:
    DRAFT → READY_FOR_IMPLEMENTATION → IMPLEMENTING → IMPLEMENTED
    → READY_FOR_VERIFICATION → VERIFIED_PASS → READY_FOR_HUMAN_APPROVAL
    → APPROVED → DONE

``READY_FOR_MERGE`` is the gates-passed stage for flows whose contract does not require
human approval for merge; it accepts the same terminal events as APPROVED.
"""
from __future__ import annotations

from enum import StrEnum


class TaskState(StrEnum):
    DRAFT = "DRAFT"
    READY_FOR_IMPLEMENTATION = "READY_FOR_IMPLEMENTATION"
    IMPLEMENTING = "IMPLEMENTING"
    IMPLEMENTED = "IMPLEMENTED"
    READY_FOR_VERIFICATION = "READY_FOR_VERIFICATION"
    VERIFIED_PASS = "VERIFIED_PASS"
    NEEDS_FIX = "NEEDS_FIX"
    READY_FOR_MERGE = "READY_FOR_MERGE"
    READY_FOR_HUMAN_APPROVAL = "READY_FOR_HUMAN_APPROVAL"
    APPROVED = "APPROVED"
    DONE = "DONE"
    BLOCKED = "BLOCKED"


class TaskEvent(StrEnum):
    CONTRACT_VALIDATED = "contract_validated"
    IMPLEMENTATION_STARTED = "implementation_started"
    IMPLEMENTATION_REPORT_INGESTED = "implementation_report_ingested"
    VERIFICATION_REQUESTED = "verification_requested"
    VERIFICATION_PASSED = "verification_passed"
    VERIFICATION_FAILED = "verification_failed"
    CHANGEGATE_PASSED = "changegate_passed"
    CHANGEGATE_FAILED = "changegate_failed"
    HUMAN_APPROVED = "human_approved"
    MERGED = "merged"
    BLOCKED = "blocked"


class InvalidTransitionError(ValueError):
    """Raised for a (state, event) pair the machine does not define."""


_TRANSITIONS: dict[tuple[TaskState, TaskEvent], TaskState] = {
    (TaskState.DRAFT, TaskEvent.CONTRACT_VALIDATED): TaskState.READY_FOR_IMPLEMENTATION,
    (TaskState.READY_FOR_IMPLEMENTATION, TaskEvent.IMPLEMENTATION_STARTED): TaskState.IMPLEMENTING,
    (TaskState.IMPLEMENTING, TaskEvent.IMPLEMENTATION_REPORT_INGESTED): TaskState.IMPLEMENTED,
    (TaskState.IMPLEMENTED, TaskEvent.VERIFICATION_REQUESTED): TaskState.READY_FOR_VERIFICATION,
    (TaskState.READY_FOR_VERIFICATION, TaskEvent.VERIFICATION_PASSED): TaskState.VERIFIED_PASS,
    (TaskState.READY_FOR_VERIFICATION, TaskEvent.VERIFICATION_FAILED): TaskState.NEEDS_FIX,
    # Fix loop: a NEEDS_FIX task goes back through implementation.
    (TaskState.NEEDS_FIX, TaskEvent.IMPLEMENTATION_STARTED): TaskState.IMPLEMENTING,
    # Gates after verification.
    (TaskState.VERIFIED_PASS, TaskEvent.CHANGEGATE_PASSED): TaskState.READY_FOR_HUMAN_APPROVAL,
    (TaskState.VERIFIED_PASS, TaskEvent.CHANGEGATE_FAILED): TaskState.NEEDS_FIX,
    # Human approval and terminal merge.
    (TaskState.READY_FOR_HUMAN_APPROVAL, TaskEvent.HUMAN_APPROVED): TaskState.APPROVED,
    (TaskState.APPROVED, TaskEvent.MERGED): TaskState.DONE,
    # Gates-passed stage for no-approval flows; same terminal events as APPROVED.
    (TaskState.READY_FOR_MERGE, TaskEvent.HUMAN_APPROVED): TaskState.APPROVED,
    (TaskState.READY_FOR_MERGE, TaskEvent.MERGED): TaskState.DONE,
}


def transition(current: TaskState, event: TaskEvent) -> TaskState:
    """Return the next state; ``blocked`` is accepted from every non-terminal state."""
    if event is TaskEvent.BLOCKED:
        if current is TaskState.DONE:
            raise InvalidTransitionError("cannot block a DONE task")
        return TaskState.BLOCKED
    key = (current, event)
    if key not in _TRANSITIONS:
        raise InvalidTransitionError(
            f"no transition defined for state={current.value!r} event={event.value!r}"
        )
    return _TRANSITIONS[key]

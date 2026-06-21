from __future__ import annotations

from typing import TYPE_CHECKING

from agent_core.confirmation.errors import ConfirmedWriteValidationError
from agent_core.confirmation.models import (
    ConfirmedSaveOperation,
    confirmed_memory_request_id,
)
from agent_core.memory.contracts import MemoryCandidate
from agent_core.state.enums import MemoryType, SourceType, TrustLevel

if TYPE_CHECKING:
    from agent_core.state.agent_state import AgentState


class ConfirmedMemoryWritePolicy:
    """Validate one confirmed save operation and map it to exactly one DECISION candidate.

    This is NOT the tool ``PolicyEngine``. It performs no HTTP/store/tool access, does not
    mutate ``AgentState``, does not create trusted evidence, and does not manage project_id.
    """

    def to_candidate(
        self,
        *,
        operation: ConfirmedSaveOperation,
        state: "AgentState",
    ) -> MemoryCandidate:
        state_operation = getattr(state, "confirmed_save_operation", None)
        if state_operation is None:
            raise ConfirmedWriteValidationError("state has no confirmed save operation")
        if state_operation is not operation:
            raise ConfirmedWriteValidationError(
                "provided operation does not match the state operation"
            )

        state_task_id = state.task_id
        if not isinstance(state_task_id, str) or not state_task_id.strip():
            raise ConfirmedWriteValidationError("state task_id is blank")
        state_user_id = state.user_id
        if not isinstance(state_user_id, str) or not state_user_id.strip():
            raise ConfirmedWriteValidationError("state user_id is blank")

        if operation.task_id != state_task_id:
            raise ConfirmedWriteValidationError(
                "operation task_id differs from state task_id"
            )
        if operation.session_id != state.session_id:
            raise ConfirmedWriteValidationError(
                "operation session_id differs from state session_id"
            )

        decision = operation.decision
        confirmation_id = decision.confirmation_id
        if not confirmation_id:
            raise ConfirmedWriteValidationError("confirmation_id is blank")
        if not decision.content:
            raise ConfirmedWriteValidationError("content is blank")

        if operation.request_id != confirmed_memory_request_id(confirmation_id):
            raise ConfirmedWriteValidationError(
                "request_id differs from memory-write:<confirmation_id>"
            )

        evidence = decision.confirmation_evidence
        if evidence.content != decision.content:
            raise ConfirmedWriteValidationError(
                "evidence content differs from normalized decision content"
            )
        if evidence.source_type is not SourceType.USER:
            raise ConfirmedWriteValidationError("evidence source_type is not USER")
        if evidence.trust_level is not TrustLevel.TRUSTED_INSTRUCTION:
            raise ConfirmedWriteValidationError(
                "evidence trust_level is not TRUSTED_INSTRUCTION"
            )
        expected_source_ref = f"user-explicit:{operation.task_id}:{confirmation_id}"
        if evidence.source_ref is None or evidence.source_ref != expected_source_ref:
            raise ConfirmedWriteValidationError(
                "evidence source_ref is absent or does not match the expected reference"
            )

        return MemoryCandidate(
            type=MemoryType.DECISION,
            content=decision.content,
            tags=[],
            importance=0.5,
            confidence=1.0,
            evidence_ref=evidence.source_ref,
            metadata={"candidate_id": confirmation_id},
        )

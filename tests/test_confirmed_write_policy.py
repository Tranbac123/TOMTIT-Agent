from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from agent_core.confirmation.errors import ConfirmedWriteValidationError
from agent_core.confirmation.evidence_factory import make_confirmation_evidence
from agent_core.confirmation.models import ConfirmedDecision, ConfirmedSaveOperation
from agent_core.confirmation.write_policy import ConfirmedMemoryWritePolicy
from agent_core.safety.evidence import EvidenceEnvelope
from agent_core.state.enums import MemoryType, SourceType, TrustLevel


def _operation(task_id="task-1", confirmation_id="conf-1", content="use postgres", session_id="sess-1"):
    decision = ConfirmedDecision(
        confirmation_id=confirmation_id,
        content=content,
        confirmation_evidence=make_confirmation_evidence(
            task_id=task_id, confirmation_id=confirmation_id, content=content
        ),
    )
    return ConfirmedSaveOperation(
        request_id=f"memory-write:{confirmation_id}",
        task_id=task_id,
        session_id=session_id,
        decision=decision,
    )


def _state(operation, *, task_id="task-1", user_id="user-1", session_id="sess-1"):
    # Lightweight stand-in for AgentState (field added in I3); policy uses getattr/attrs only.
    return SimpleNamespace(
        confirmed_save_operation=operation,
        task_id=task_id,
        user_id=user_id,
        session_id=session_id,
    )


def test_policy_maps_one_decision_candidate():
    op = _operation()
    cand = ConfirmedMemoryWritePolicy().to_candidate(operation=op, state=_state(op))
    assert cand.type is MemoryType.DECISION
    assert cand.content == "use postgres"
    assert cand.metadata["candidate_id"] == "conf-1"
    assert cand.evidence_ref == "user-explicit:task-1:conf-1"
    assert cand.tags == []
    assert cand.importance == 0.5
    assert cand.confidence == 1.0


def test_policy_no_state_operation_rejected():
    op = _operation()
    st = _state(op)
    st.confirmed_save_operation = None
    with pytest.raises(ConfirmedWriteValidationError):
        ConfirmedMemoryWritePolicy().to_candidate(operation=op, state=st)


def test_policy_operation_mismatch_rejected():
    op = _operation()
    other = _operation(confirmation_id="conf-2")
    st = _state(other)  # state carries a different operation object
    with pytest.raises(ConfirmedWriteValidationError):
        ConfirmedMemoryWritePolicy().to_candidate(operation=op, state=st)


def test_policy_blank_user_id_rejected():
    op = _operation()
    with pytest.raises(ConfirmedWriteValidationError):
        ConfirmedMemoryWritePolicy().to_candidate(operation=op, state=_state(op, user_id="  "))


def test_policy_task_id_mismatch_rejected():
    op = _operation(task_id="task-1")
    with pytest.raises(ConfirmedWriteValidationError):
        ConfirmedMemoryWritePolicy().to_candidate(operation=op, state=_state(op, task_id="task-OTHER"))


def test_policy_session_mismatch_rejected():
    op = _operation(session_id="sess-1")
    with pytest.raises(ConfirmedWriteValidationError):
        ConfirmedMemoryWritePolicy().to_candidate(operation=op, state=_state(op, session_id="sess-OTHER"))


def test_policy_wrong_source_type_rejected():
    op = _operation()
    bad_evidence = EvidenceEnvelope(
        content=op.decision.content,
        source_type=SourceType.AGENT,
        trust_level=TrustLevel.TRUSTED_INSTRUCTION,
        source_ref="user-explicit:task-1:conf-1",
    )
    bad_decision = dataclasses.replace(op.decision, confirmation_evidence=bad_evidence)
    bad_op = dataclasses.replace(op, decision=bad_decision)
    with pytest.raises(ConfirmedWriteValidationError):
        ConfirmedMemoryWritePolicy().to_candidate(operation=bad_op, state=_state(bad_op))


def test_policy_wrong_trust_level_rejected():
    op = _operation()
    bad_evidence = EvidenceEnvelope(
        content=op.decision.content,
        source_type=SourceType.USER,
        trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
        source_ref="user-explicit:task-1:conf-1",
    )
    bad_decision = dataclasses.replace(op.decision, confirmation_evidence=bad_evidence)
    bad_op = dataclasses.replace(op, decision=bad_decision)
    with pytest.raises(ConfirmedWriteValidationError):
        ConfirmedMemoryWritePolicy().to_candidate(operation=bad_op, state=_state(bad_op))


def test_policy_evidence_content_mismatch_rejected():
    op = _operation()
    bad_evidence = EvidenceEnvelope(
        content="something else",
        source_type=SourceType.USER,
        trust_level=TrustLevel.TRUSTED_INSTRUCTION,
        source_ref="user-explicit:task-1:conf-1",
    )
    bad_decision = dataclasses.replace(op.decision, confirmation_evidence=bad_evidence)
    bad_op = dataclasses.replace(op, decision=bad_decision)
    with pytest.raises(ConfirmedWriteValidationError):
        ConfirmedMemoryWritePolicy().to_candidate(operation=bad_op, state=_state(bad_op))


def test_policy_evidence_source_ref_mismatch_rejected():
    op = _operation()
    bad_evidence = EvidenceEnvelope(
        content=op.decision.content,
        source_type=SourceType.USER,
        trust_level=TrustLevel.TRUSTED_INSTRUCTION,
        source_ref="user-explicit:WRONG:conf-1",
    )
    bad_decision = dataclasses.replace(op.decision, confirmation_evidence=bad_evidence)
    bad_op = dataclasses.replace(op, decision=bad_decision)
    with pytest.raises(ConfirmedWriteValidationError):
        ConfirmedMemoryWritePolicy().to_candidate(operation=bad_op, state=_state(bad_op))

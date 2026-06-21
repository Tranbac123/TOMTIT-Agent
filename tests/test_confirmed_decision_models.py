from __future__ import annotations

import dataclasses

import pytest

from agent_core.confirmation.evidence_factory import make_confirmation_evidence
from agent_core.confirmation.models import (
    ConfirmedDecision,
    ConfirmedSaveOperation,
    confirmed_memory_request_id,
)
from agent_core.safety.evidence import EvidenceEnvelope
from agent_core.state.enums import SourceType, TrustLevel


def _evidence(task_id: str = "task-1", confirmation_id: str = "conf-1", content: str = "use postgres"):
    return make_confirmation_evidence(
        task_id=task_id, confirmation_id=confirmation_id, content=content
    )


# --- request_id helper -----------------------------------------------------

def test_request_id_formula():
    assert confirmed_memory_request_id("conf-1") == "memory-write:conf-1"


def test_request_id_strips():
    assert confirmed_memory_request_id("  conf-1  ") == "memory-write:conf-1"


def test_request_id_blank_rejected():
    with pytest.raises(ValueError):
        confirmed_memory_request_id("   ")


# --- ConfirmedDecision -----------------------------------------------------

def test_valid_confirmed_decision():
    d = ConfirmedDecision(
        confirmation_id="conf-1", content="use postgres", confirmation_evidence=_evidence()
    )
    assert d.confirmation_id == "conf-1"
    assert d.content == "use postgres"
    assert d.confirmation_evidence.source_type is SourceType.USER


def test_confirmed_decision_strips_id_and_content():
    d = ConfirmedDecision(
        confirmation_id="  conf-1  ",
        content="  use postgres  ",
        confirmation_evidence=_evidence(content="  use postgres  "),
    )
    assert d.confirmation_id == "conf-1"
    assert d.content == "use postgres"


def test_confirmed_decision_preserves_internal_whitespace():
    d = ConfirmedDecision(
        confirmation_id="conf-1",
        content="use   postgres   here",
        confirmation_evidence=_evidence(content="use   postgres   here"),
    )
    assert d.content == "use   postgres   here"


def test_confirmed_decision_blank_id_rejected():
    with pytest.raises(ValueError):
        ConfirmedDecision(confirmation_id="  ", content="x", confirmation_evidence=_evidence())


def test_confirmed_decision_blank_content_rejected():
    with pytest.raises(ValueError):
        ConfirmedDecision(confirmation_id="conf-1", content="   ", confirmation_evidence=_evidence())


def test_confirmed_decision_wrong_evidence_type_rejected():
    with pytest.raises(ValueError):
        ConfirmedDecision(confirmation_id="conf-1", content="x", confirmation_evidence="not-evidence")  # type: ignore[arg-type]


def test_confirmed_decision_is_frozen():
    d = ConfirmedDecision(
        confirmation_id="conf-1", content="x", confirmation_evidence=_evidence(content="x")
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.content = "y"  # type: ignore[misc]


# --- ConfirmedSaveOperation ------------------------------------------------

def _decision(confirmation_id: str = "conf-1", content: str = "use postgres", task_id: str = "task-1"):
    return ConfirmedDecision(
        confirmation_id=confirmation_id,
        content=content,
        confirmation_evidence=make_confirmation_evidence(
            task_id=task_id, confirmation_id=confirmation_id, content=content
        ),
    )


def test_valid_operation():
    op = ConfirmedSaveOperation(
        request_id="memory-write:conf-1",
        task_id="task-1",
        session_id="sess-1",
        decision=_decision(),
    )
    assert op.request_id == "memory-write:conf-1"
    assert op.task_id == "task-1"
    assert op.session_id == "sess-1"


def test_operation_session_id_may_be_none():
    op = ConfirmedSaveOperation(
        request_id="memory-write:conf-1", task_id="task-1", session_id=None, decision=_decision()
    )
    assert op.session_id is None


def test_operation_request_id_formula_enforced():
    with pytest.raises(ValueError):
        ConfirmedSaveOperation(
            request_id="memory-write:WRONG", task_id="task-1", session_id="s", decision=_decision()
        )


def test_operation_blank_task_id_rejected():
    with pytest.raises(ValueError):
        ConfirmedSaveOperation(
            request_id="memory-write:conf-1", task_id="  ", session_id="s", decision=_decision()
        )


def test_operation_blank_session_id_rejected():
    with pytest.raises(ValueError):
        ConfirmedSaveOperation(
            request_id="memory-write:conf-1", task_id="task-1", session_id="  ", decision=_decision()
        )


def test_operation_wrong_decision_type_rejected():
    with pytest.raises(ValueError):
        ConfirmedSaveOperation(
            request_id="memory-write:conf-1", task_id="task-1", session_id="s", decision="nope"  # type: ignore[arg-type]
        )


def test_operation_is_frozen():
    op = ConfirmedSaveOperation(
        request_id="memory-write:conf-1", task_id="task-1", session_id="s", decision=_decision()
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        op.task_id = "other"  # type: ignore[misc]


def test_operation_has_no_project_or_user_fields():
    names = {f.name for f in dataclasses.fields(ConfirmedSaveOperation)}
    assert "project_id" not in names
    assert "user_id" not in names
    assert names == {"request_id", "task_id", "session_id", "decision"}

from __future__ import annotations

import inspect

import pytest

from agent_core.confirmation.evidence_factory import make_confirmation_evidence
from agent_core.safety.evidence import EvidenceEnvelope
from agent_core.state.enums import SourceType, TrustLevel


def test_factory_returns_user_trusted_evidence():
    ev = make_confirmation_evidence(task_id="task-1", confirmation_id="conf-1", content="use postgres")
    assert isinstance(ev, EvidenceEnvelope)
    assert ev.source_type is SourceType.USER
    assert ev.trust_level is TrustLevel.TRUSTED_INSTRUCTION


def test_factory_exact_source_ref():
    ev = make_confirmation_evidence(task_id="task-1", confirmation_id="conf-1", content="x")
    assert ev.source_ref == "user-explicit:task-1:conf-1"


def test_factory_content_matches_normalized_content():
    ev = make_confirmation_evidence(task_id="task-1", confirmation_id="conf-1", content="  use postgres  ")
    assert ev.content == "use postgres"


def test_factory_metadata_carries_confirmation_id():
    ev = make_confirmation_evidence(task_id="task-1", confirmation_id="conf-1", content="x")
    assert ev.metadata["confirmation_id"] == "conf-1"


def test_factory_rejects_blank_task_id():
    with pytest.raises(ValueError):
        make_confirmation_evidence(task_id="  ", confirmation_id="conf-1", content="x")


def test_factory_rejects_blank_confirmation_id():
    with pytest.raises(ValueError):
        make_confirmation_evidence(task_id="task-1", confirmation_id="  ", content="x")


def test_factory_rejects_blank_content():
    with pytest.raises(ValueError):
        make_confirmation_evidence(task_id="task-1", confirmation_id="conf-1", content="   ")


def test_factory_signature_is_keyword_only_and_has_no_trust_source_params():
    sig = inspect.signature(make_confirmation_evidence)
    params = sig.parameters
    assert set(params) == {"task_id", "confirmation_id", "content"}
    for p in params.values():
        assert p.kind is inspect.Parameter.KEYWORD_ONLY
    # caller cannot inject trust/source/source_ref
    assert "source_type" not in params
    assert "trust_level" not in params
    assert "source_ref" not in params

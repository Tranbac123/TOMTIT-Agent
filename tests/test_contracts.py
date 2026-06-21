from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_core.memory.client import MemoryClientProtocol
from agent_core.memory.contracts import (
    ContextItem,
    ContextPack,
    MemoryCandidate,
    WriteResponse,
)
from agent_core.memory.token_counter import ApproxTokenCounter
from agent_core.state.enums import MemoryType, SourceType, TrustLevel


def test_contextpack_defaults():
    pack = ContextPack()
    assert pack.degraded is False
    assert pack.memory_source == "remote"
    assert pack.items == []


def test_contextitem_requires_memorytype():
    item = ContextItem(content="x", type=MemoryType.NOTE)
    assert item.type is MemoryType.NOTE

    with pytest.raises(ValidationError):
        ContextItem(content="x", type="note")


def test_literal_rejects_typo():
    with pytest.raises(ValidationError):
        ContextItem(content="x", type=MemoryType.NOTE, provenance="fall_back")


def test_protocol_conformance():
    class StubClient:
        @property
        def supports_required_write(self) -> bool:
            return False

        def retrieve_context_pack(
            self,
            goal: str,
            *,
            user_id: str | None = None,
            session_id: str | None = None,
            token_budget: int = 1500,
            max_items: int = 20,
        ) -> ContextPack:
            return ContextPack()

        def write_memory_candidates(
            self,
            candidates: list[MemoryCandidate],
            *,
            user_id: str | None = None,
            session_id: str | None = None,
            task_id: str | None = None,
            request_id: str | None = None,
        ) -> WriteResponse:
            return WriteResponse()

    stub = StubClient()
    assert isinstance(stub, MemoryClientProtocol)


def test_approx_token_counter():
    counter = ApproxTokenCounter()
    assert counter.count("a b c") == 3
    assert counter.count("") == 1


# ---------------------------------------------------------------------------
# SF1 — ContextItem trust and source fields
# ---------------------------------------------------------------------------

def test_contextitem_sf1_defaults():
    """New SF1 fields have correct defaults when not specified."""
    item = ContextItem(content="x", type=MemoryType.NOTE)
    assert item.source_type is SourceType.MEMORY
    assert item.trust_level is TrustLevel.UNTRUSTED_EVIDENCE
    assert item.source_ref is None


def test_contextitem_sf1_explicit_fields():
    """Explicit SF1 field values are preserved."""
    item = ContextItem(
        content="x",
        type=MemoryType.FACT,
        source_type=SourceType.TOOL,
        trust_level=TrustLevel.TRUSTED_INSTRUCTION,
        source_ref="task:t1/step:s1/tool:calculate",
    )
    assert item.source_type is SourceType.TOOL
    assert item.trust_level is TrustLevel.TRUSTED_INSTRUCTION
    assert item.source_ref == "task:t1/step:s1/tool:calculate"


def test_contextitem_source_ref_none_accepted():
    item = ContextItem(content="x", type=MemoryType.NOTE, source_ref=None)
    assert item.source_ref is None


def test_contextitem_model_dump_python_mode():
    """model_dump() includes SF1 fields with enum instances (python mode)."""
    item = ContextItem(content="x", type=MemoryType.NOTE)
    d = item.model_dump()
    assert "source_type" in d
    assert "trust_level" in d
    assert "source_ref" in d
    assert d["source_ref"] is None


def test_contextitem_model_dump_json_mode():
    """model_dump(mode='json') serializes SF1 enum fields to their string values."""
    item = ContextItem(content="x", type=MemoryType.NOTE)
    d = item.model_dump(mode="json")
    assert d["source_type"] == "memory"
    assert d["trust_level"] == "untrusted_evidence"


def test_contextitem_strict_unchanged():
    """Existing strict=True behavior is not broken by SF1 additions."""
    with pytest.raises(ValidationError):
        ContextItem(content="x", type="note")

    with pytest.raises(ValidationError):
        ContextItem(content="x", type=MemoryType.NOTE, source_type="memory")

    with pytest.raises(ValidationError):
        ContextItem(content="x", type=MemoryType.NOTE, trust_level="untrusted_evidence")

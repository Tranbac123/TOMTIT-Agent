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
from agent_core.state.enums import MemoryType


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
        ) -> WriteResponse:
            return WriteResponse()

    stub = StubClient()
    assert isinstance(stub, MemoryClientProtocol)


def test_approx_token_counter():
    counter = ApproxTokenCounter()
    assert counter.count("a b c") == 3
    assert counter.count("") == 1

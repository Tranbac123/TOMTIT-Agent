"""CONV-P0 P0-7J — Memory Kernel v1 unit tests (dataclass, helpers, parser)."""
from __future__ import annotations

import dataclasses

import pytest

from agent_core.conversation.memory_operations import (
    MemoryOperation,
    canonicalize_memory_value,
    parse_memory_operation,
    strip_temporal_update_marker,
    strip_terminal_discourse_marker,
    validate_memory_operation,
)


# ---------------------------------------------------------------------------
# Dataclass contract
# ---------------------------------------------------------------------------

def test_memory_operation_is_frozen():
    op = MemoryOperation(
        op="ADD", domain="goal", subject="self", value="build LLM",
        canonical_key="llm",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        op.value = "other"  # type: ignore[misc]


def test_memory_operation_defaults():
    op = MemoryOperation(
        op="REMOVE", domain="occupation", subject="self", value="blogger",
        canonical_key="blogger",
    )
    assert op.source == "user_explicit"
    assert op.confidence == 1.0
    assert op.polarity is None
    assert op.relation is None


# ---------------------------------------------------------------------------
# Canonicalization helpers
# ---------------------------------------------------------------------------

def test_canonicalize_memory_value_normalizes_case_and_whitespace():
    assert canonicalize_memory_value("  Ăn   Kem !! ") == "ăn kem"
    assert canonicalize_memory_value("Blogger.") == "blogger"


def test_strip_temporal_update_marker_variants():
    for prefix in ["bây giờ", "hiện tại", "từ nay", "giờ"]:
        remainder, had = strip_temporal_update_marker(
            f"{prefix} người yêu của tôi là quý"
        )
        assert had, f"marker not stripped for {prefix!r}"
        assert remainder == "người yêu của tôi là quý"


def test_strip_temporal_update_marker_absent():
    remainder, had = strip_temporal_update_marker("người yêu của tôi là quý")
    assert not had
    assert remainder == "người yêu của tôi là quý"


def test_strip_terminal_discourse_marker():
    assert strip_terminal_discourse_marker("quý mà") == "quý"
    assert strip_terminal_discourse_marker("quý") == "quý"
    # A bare discourse word is never emptied.
    assert strip_terminal_discourse_marker("mà") == "mà"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def test_parse_occupation_stop_variants():
    for text in [
        "tôi không làm blogger nữa",
        "tôi không còn làm blogger",
        "tôi nghỉ làm blogger",
    ]:
        op = parse_memory_operation(text)
        assert op is not None, f"no operation parsed from {text!r}"
        assert (op.op, op.domain) == ("REMOVE", "occupation")
        assert op.value == "blogger"


def test_parse_affection_removal_strips_nua():
    op = parse_memory_operation("tôi không thích quý nữa")
    assert op is not None
    assert (op.op, op.domain) == ("REMOVE", "affection")
    assert op.value == "quý"
    assert "nữa" not in op.value


def test_parse_relationship_current_update():
    op = parse_memory_operation("bây giờ người yêu của tôi là quý")
    assert op is not None
    assert (op.op, op.domain) == ("UPDATE_CURRENT", "relationship")
    assert op.relation == "người yêu"
    assert op.value == "quý"


def test_parse_goal_switch_carries_old_key_and_new_value():
    op = parse_memory_operation("tôi không muốn build LLM nữa tôi muốn build AI Agent")
    assert op is not None
    assert (op.op, op.domain) == ("SWITCH", "goal")
    assert op.value == "build AI Agent"
    assert op.canonical_key == "llm"  # old goal key, verb-stripped


def test_parse_goal_will_requires_professional_token():
    op = parse_memory_operation("tôi sẽ build AI model LLM")
    assert op is not None
    assert (op.op, op.domain) == ("ADD", "goal")
    assert op.value == "build AI model LLM"
    assert parse_memory_operation("tôi sẽ đi ngủ sớm") is None


def test_parse_rejects_questions_and_unrelated_text():
    assert parse_memory_operation("tôi không làm gì?") is None
    assert parse_memory_operation("tôi làm AI") is None
    assert parse_memory_operation("hôm nay trời đẹp") is None


def test_validate_rejects_unsafe_value():
    op = MemoryOperation(
        op="ADD", domain="goal", subject="self", value="mua cần sa",
        canonical_key="mua cần sa",
    )
    assert not validate_memory_operation(op)

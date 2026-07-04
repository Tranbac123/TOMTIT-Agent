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


# ---------------------------------------------------------------------------
# P0-7J-FIX1 unit tests
# ---------------------------------------------------------------------------

def test_p0_7j_fix1_strip_additive_target_marker():
    from agent_core.conversation.profile_semantics import strip_additive_target_marker
    assert strip_additive_target_marker("cả may") == "may"
    assert strip_additive_target_marker("cả may nữa") == "may"
    assert strip_additive_target_marker("thêm quý nhé") == "quý"
    assert strip_additive_target_marker("may") == "may"
    # Never emptied.
    assert strip_additive_target_marker("cả") == "cả"


def test_p0_7j_fix1_parse_relationship_bay_gio_typo_marker():
    op = parse_memory_operation("bay giờ người yêu của tôi là may")
    assert op is not None
    assert (op.op, op.domain) == ("UPDATE_CURRENT", "relationship")
    assert op.relation == "người yêu"
    assert op.value == "may"


def test_p0_7j_fix1_parse_relationship_marker_inside_phrase():
    for text in [
        "người yêu bây giờ của tôi là may",
        "người yêu của tôi bây giờ là may",
    ]:
        op = parse_memory_operation(text)
        assert op is not None, f"no operation parsed from {text!r}"
        assert (op.op, op.domain) == ("UPDATE_CURRENT", "relationship")
        assert op.value == "may"


def test_p0_7j_fix1_parse_goal_standalone_negation():
    for text in [
        "tôi sẽ không làm LLM nữa",
        "tôi không muốn làm LLM nữa",
        "tôi không muốn build LLM nữa",
        "tôi không build LLM nữa",
    ]:
        op = parse_memory_operation(text)
        assert op is not None, f"no operation parsed from {text!r}"
        assert (op.op, op.domain) == ("REMOVE", "goal"), f"wrong op for {text!r}: {op}"
        assert op.canonical_key == "llm", f"wrong key for {text!r}: {op.canonical_key}"
    # Non-goal desires stay out of the kernel ("tôi không muốn đi học").
    assert parse_memory_operation("tôi không muốn đi học") is None


def test_p0_7j_fix1_parse_goal_yes_no_query():
    from agent_core.conversation.profile_memory import detect_profile_query
    for text in [
        "tôi có làm LLM nữa không?",
        "tôi có còn làm LLM không?",
        "tôi có muốn làm LLM nữa không?",
        "tôi có build LLM nữa không?",
    ]:
        query = detect_profile_query(text)
        assert query is not None, f"no query detected from {text!r}"
        assert query.kind == "self_do_yesno", f"wrong kind for {text!r}: {query.kind}"
        assert query.value == "LLM", f"wrong value for {text!r}: {query.value}"


def test_p0_7j_fix1_parse_goal_no_accent_query():
    from agent_core.conversation.profile_memory import detect_profile_query
    for text in ["tôi se làm gì?", "tôi se build gì?", "toi se lam gi?"]:
        query = detect_profile_query(text)
        assert query is not None, f"no query detected from {text!r}"
        assert query.kind == "self_current_goal", f"wrong kind for {text!r}: {query.kind}"

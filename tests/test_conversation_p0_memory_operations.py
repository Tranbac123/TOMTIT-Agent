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


# ---------------------------------------------------------------------------
# P0-7K-FIX1 unit tests
# ---------------------------------------------------------------------------

def test_p0_7k_fix1_detects_query_write_guard_markers():
    from agent_core.conversation.profile_semantics import _value_is_query_polluted
    assert _value_is_query_polluted("gì nhata")
    assert _value_is_query_polluted("gì nhất")
    assert _value_is_query_polluted("code hơn vẽ nhất")
    # Valid preference values are not blocked.
    assert not _value_is_query_polluted("ăn cay")
    assert not _value_is_query_polluted("cafe không đường")
    assert not _value_is_query_polluted("AI")


def test_p0_7k_fix1_semantic_extractor_does_not_emit_add_for_question():
    from agent_core.conversation.profile_semantics import classify_profile_semantic_intent
    # A query phrase must never classify as a preference write.
    intent = classify_profile_semantic_intent("tôi thích gì nhất")
    if intent is not None:
        assert not (intent.kind == "profile_write" and intent.category
                    and intent.category.startswith("preference")), intent


def test_p0_7k_fix1_parse_current_state_preference_update():
    op = parse_memory_operation("bây giờ tôi thích bơi rồi")
    assert op is not None
    assert (op.op, op.domain, op.polarity) == ("UPDATE_CURRENT", "preference", "positive")
    assert op.value == "bơi"


def test_p0_7k_fix1_parse_negative_skill():
    from agent_core.conversation.profile_semantics import classify_profile_semantic_intent
    intent = classify_profile_semantic_intent("tôi không biết bơi")
    assert intent is not None
    assert intent.category == "negative_skill"
    assert intent.value == "bơi"


def test_p0_7k_fix1_parse_goal_multiset():
    # "tôi sẽ làm AI" parses as a goal ADD (uppercase AI is not a question word).
    op = parse_memory_operation("tôi sẽ làm AI")
    assert op is not None
    assert (op.op, op.domain) == ("ADD", "goal")
    assert op.value == "làm AI"
    assert op.canonical_key == "ai"
    # Goal focus keeps other goals (UPDATE_CURRENT).
    focus = parse_memory_operation("mục tiêu chính của tôi là AI Agent")
    assert focus is not None
    assert (focus.op, focus.domain) == ("UPDATE_CURRENT", "goal")
    # Replace-all is a SWITCH with the wildcard key.
    only = parse_memory_operation("tôi chỉ làm blogger thôi")
    assert only is not None
    assert (only.op, only.domain, only.canonical_key) == ("SWITCH", "goal", "*")


def test_p0_7k_fix1_goal_taxonomy_ai_matcher():
    from agent_core.conversation.profile_memory import _value_relates_to_ai
    assert _value_relates_to_ai("làm LLM")
    assert _value_relates_to_ai("Agent AI")
    assert _value_relates_to_ai("AI Agent coder")
    assert _value_relates_to_ai("machine learning")
    assert not _value_relates_to_ai("blogger")
    assert not _value_relates_to_ai("nấu ăn")


def test_p0_7k_fix1_memory_challenge_detector():
    from agent_core.conversation.profile_memory import detect_profile_query
    query = detect_profile_query("bạn không nhớ tôi sẽ làm LLM và Agent AI à?")
    assert query is not None
    assert query.kind == "goal_challenge"
    assert "llm" in (query.value or "").lower()


def test_p0_7k_fix1_followup_goal_context_detector():
    from agent_core.conversation.profile_memory import detect_profile_query
    for text in ["và gì nữa?", "còn gì nữa?", "ngoài ra còn gì?"]:
        query = detect_profile_query(text)
        assert query is not None, f"no query for {text!r}"
        assert query.kind == "goal_followup", f"wrong kind for {text!r}: {query.kind}"

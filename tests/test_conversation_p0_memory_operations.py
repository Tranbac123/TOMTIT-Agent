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


def test_parse_one_sided_affection_adds_affection_not_relationship():
    op = parse_memory_operation("tôi thích đơn phương Quý")
    assert op is not None
    assert (op.op, op.domain) == ("ADD", "affection")
    assert op.subject == "self"
    assert op.value == "Quý"
    assert op.relation is None
    assert op.source == "one_sided_affection"


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
    # P0-7K-FIX2: the guard blocks bare QUESTION-WORD tokens ("gì"). "nhất"/"hơn" are no
    # longer blanket-blocked here — they are favorite/comparative markers owned by their
    # own parsers; a value containing a query word is still blocked.
    assert _value_is_query_polluted("gì nhata")
    assert _value_is_query_polluted("gì nhất")
    assert _value_is_query_polluted("ăn gì nhất")
    # Favorite/comparative phrasings (no query word) are not blocked by this guard.
    assert not _value_is_query_polluted("ăn chuối nhất")
    assert not _value_is_query_polluted("code hơn vẽ")
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


# ---------------------------------------------------------------------------
# P0-7K-FIX2 unit tests
# ---------------------------------------------------------------------------

def test_p0_7k_fix2_detects_food_ranking_query_as_query():
    from agent_core.conversation.profile_memory import detect_profile_query
    q = detect_profile_query("tôi thích ăn gì nhất")
    assert q is not None and q.kind == "self_food_favorite"
    q2 = detect_profile_query("tôi thích ăn gì nhất?")
    assert q2 is not None and q2.kind == "self_food_favorite"


def test_p0_7k_fix2_parses_food_favorite_statement():
    from agent_core.conversation.profile_semantics import classify_profile_semantic_intent
    intent = classify_profile_semantic_intent("tôi thích ăn chuối nhất")
    assert intent is not None
    assert intent.category == "favorite.food"
    assert intent.value == "ăn chuối"


def test_p0_7k_fix2_parses_general_favorite_statement():
    from agent_core.conversation.profile_semantics import classify_profile_semantic_intent
    intent = classify_profile_semantic_intent("tôi thích xem phim nhất")
    assert intent is not None
    assert intent.category == "favorite.general"
    assert intent.value == "xem phim"


def test_p0_7k_fix2_parses_comparative_preference_statement():
    from agent_core.conversation.profile_semantics import classify_profile_semantic_intent
    intent = classify_profile_semantic_intent("tôi thích code hơn là vẽ")
    assert intent is not None
    assert intent.category.startswith("comparative")
    assert intent.value == "code" and intent.relation_label == "vẽ"


def test_p0_7k_fix2_detects_comparative_query():
    from agent_core.conversation.profile_memory import detect_profile_query
    q = detect_profile_query("tôi thích code hay thích vẽ hơn?")
    assert q is not None and q.kind == "self_comparative"
    assert q.value == "code" and q.object_value == "vẽ"


def test_p0_7k_fix2_splits_skill_multitem_values():
    from agent_core.conversation.semantic_extractor import (
        RuleBasedSemanticOperationExtractor, SemanticExtractionRequest,
    )
    ex = RuleBasedSemanticOperationExtractor()
    r = ex.extract(SemanticExtractionRequest(raw_text="tôi biết đọc sách và hát"))
    values = [(op.value, op.polarity) for op in r.operations]
    assert ("đọc sách", "positive") in values and ("hát", "positive") in values
    assert all(op.domain == "skill" for op in r.operations)


def test_p0_7k_fix2_ai_taxonomy_remove_all_matcher():
    from agent_core.conversation.profile_memory import _value_relates_to_ai
    for term in ["LLM", "SLM", "Agent AI", "AI Agent coder", "machine learning", "deep learning"]:
        assert _value_relates_to_ai(term), term
    assert not _value_relates_to_ai("blogger")


def test_p0_7k_fix2_goal_replace_only_want_parser():
    from agent_core.conversation.memory_operations import parse_memory_operation
    for text in [
        "tôi chỉ làm blogger thôi",
        "bây giờ tôi chỉ muốn làm LLM",
        "tôi chỉ muốn build AI Agent",
    ]:
        op = parse_memory_operation(text)
        assert op is not None, f"no op for {text!r}"
        assert (op.op, op.domain, op.canonical_key) == ("SWITCH", "goal", "*"), text


def test_p0_7k_fix2_food_preference_filter():
    from agent_core.conversation.semantic_extractor import _split_items
    # A leading food verb distributes over bare items so "me" survives as "ăn me".
    assert _split_items("ăn kem, me và dâu tây") == ["ăn kem", "ăn me", "ăn dâu tây"]
    # No food context → items stay bare.
    assert _split_items("bơi, hát và code") == ["bơi", "hát", "code"]


# ---------------------------------------------------------------------------
# P0-7K-FIX3 unit tests
# ---------------------------------------------------------------------------

def test_p0_7k_fix3_extracts_inner_clause_from_da_noi_colon():
    from agent_core.conversation.profile_memory import detect_reminder_inner_clause
    inner = detect_reminder_inner_clause(
        "tôi thích ăn kẹo nữa tôi đã nói: tôi thích ăn kẹo hơn ăn kem"
    )
    assert inner == "tôi thích ăn kẹo hơn ăn kem"


def test_p0_7k_fix3_extracts_inner_clause_from_bao_roi_ma():
    from agent_core.conversation.profile_memory import detect_reminder_inner_clause
    assert detect_reminder_inner_clause("tôi bảo tôi thích ăn chuối nhất rồi mà") == "tôi thích ăn chuối nhất"
    assert detect_reminder_inner_clause(
        "tôi đã nói tôi không biết đánh đàn nữa rồi mà"
    ) == "tôi không biết đánh đàn nữa"
    # No inner memory clause → None (routes to repair).
    assert detect_reminder_inner_clause("tôi đã nói rồi mà") is None


def test_p0_7k_fix3_detects_standalone_repair_intent():
    from agent_core.conversation.profile_memory import detect_repair_intent
    for text in ["sai rồi", "không đúng", "nhầm rồi", "tôi đã nói rồi mà"]:
        assert detect_repair_intent(text), text
    assert not detect_repair_intent("tôi thích ăn kem")


def test_p0_7k_fix3_splits_skill_multiclause():
    from agent_core.conversation.semantic_extractor import (
        RuleBasedSemanticOperationExtractor, SemanticExtractionRequest,
    )
    ex = RuleBasedSemanticOperationExtractor()
    r = ex.extract(SemanticExtractionRequest(raw_text="tôi biết nấu ăn, tôi biết đọc sách và hát"))
    values = [(op.value, op.polarity) for op in r.operations]
    assert values == [("nấu ăn", "positive"), ("đọc sách", "positive"), ("hát", "positive")]
    rn = ex.extract(SemanticExtractionRequest(raw_text="tôi không biết đọc sách và tôi không biết hát"))
    assert [(op.value, op.polarity) for op in rn.operations] == [
        ("đọc sách", "negative"), ("hát", "negative"),
    ]


def test_p0_7k_fix3_strips_terminal_discourse_markers():
    from agent_core.conversation.profile_semantics import strip_terminal_discourse_markers
    assert strip_terminal_discourse_markers("đánh đàn nữa") == "đánh đàn"
    assert strip_terminal_discourse_markers("ăn kẹo nữa") == "ăn kẹo"
    assert strip_terminal_discourse_markers("tên là Bắc mới đúng") == "tên là Bắc"
    assert strip_terminal_discourse_markers("đọc sách") == "đọc sách"
    # Never emptied.
    assert strip_terminal_discourse_markers("nữa") == "nữa"


def test_p0_7k_fix3_detects_followup_continuation():
    from agent_core.runtime.session_runtime import _RE_CONTINUATION
    m = _RE_CONTINUATION.match("và ML nữa")
    assert m is not None and m.group(1).strip() == "ML"
    for text in ["cả ML nữa", "thêm ML nữa", "còn ML nữa"]:
        assert _RE_CONTINUATION.match(text) is not None, text
    assert _RE_CONTINUATION.match("tôi biết ML") is None


def test_p0_7k_fix3_detects_delete_all_profile_memory_intent():
    from agent_core.conversation.profile_memory import detect_delete_all_memory_request
    for text in [
        "bạn hãy xoá hết ký ức về tôi đi",
        "xóa toàn bộ thông tin về tôi",
        "quên hết về tôi",
        "đừng nhớ gì về tôi nữa",
        "xoá memory của tôi",
        "clear memory",
        "forget me",
    ]:
        assert detect_delete_all_memory_request(text), text
    # Deleting a single note must NOT trigger a full wipe.
    assert not detect_delete_all_memory_request("xoá ghi chú của tôi")


def test_p0_7k_fix3_detects_delete_confirmation():
    from agent_core.conversation.profile_memory import detect_delete_all_confirmation
    for text in ["xác nhận xoá ký ức", "xác nhận xóa ký ức", "đồng ý xoá", "yes delete", "confirm delete"]:
        assert detect_delete_all_confirmation(text), text
    assert not detect_delete_all_confirmation("có")


def test_p0_7k_fix3_dirty_memory_value_filter():
    from agent_core.conversation.profile_memory import _is_dirty_value
    for bad in ["tôi biết đọc sách", "tôi không biết hát", "đánh đàn nữa", "ăn kẹo nữa tôi đã nói: x"]:
        assert _is_dirty_value(bad), bad
    for good in ["đọc sách", "nấu ăn", "ăn kẹo", "code", "ăn chuối"]:
        assert not _is_dirty_value(good), good


# ---------------------------------------------------------------------------
# P0-7K-FIX4 unit tests
# ---------------------------------------------------------------------------

def test_p0_7k_fix4_parses_contrast_skill_clause():
    from agent_core.conversation.semantic_extractor import (
        RuleBasedSemanticOperationExtractor, SemanticExtractionRequest,
    )
    ex = RuleBasedSemanticOperationExtractor()
    r = ex.extract(SemanticExtractionRequest(raw_text="tôi biết hát nhưng không biết đọc sách"))
    values = [(op.value, op.polarity) for op in r.operations]
    assert values == [("hát", "positive"), ("đọc sách", "negative")]


def test_p0_7k_fix4_splits_batch_skill_yesno_values():
    from agent_core.conversation.profile_memory import _split_skill_query_items
    assert _split_skill_query_items("hát và đọc sách") == ["hát", "đọc sách"]
    assert _split_skill_query_items("nấu ăn, hát và đọc sách") == ["nấu ăn", "hát", "đọc sách"]
    assert _split_skill_query_items("bơi") == ["bơi"]


def test_p0_7k_fix4_detects_skill_query_aliases():
    from agent_core.conversation.profile_memory import detect_profile_query
    for text in ["bạn biết tôi biết gì?", "bạn nhớ tôi biết gì?", "bạn có nhớ tôi biết gì không?"]:
        q = detect_profile_query(text)
        assert q is not None and q.kind == "self_skill", f"{text!r} → {q}"


def test_p0_7k_fix4_detects_current_state_skill_update():
    from agent_core.runtime.session_runtime import _RE_CURRENT_STATE_SKILL
    m = _RE_CURRENT_STATE_SKILL.match("bây giờ tôi biết hát và đọc sách")
    assert m is not None and m.group(1).strip() == "tôi biết hát và đọc sách"
    assert _RE_CURRENT_STATE_SKILL.match("hiện tại tôi biết bơi") is not None
    assert _RE_CURRENT_STATE_SKILL.match("tôi biết bơi") is None


def test_p0_7k_fix4_delete_confirmation_variants():
    from agent_core.conversation.profile_memory import detect_delete_all_confirmation as c
    for text in ["ok xoá đi", "ok xóa đi", "xoá đi", "xóa đi", "đồng ý xoá", "yes delete", "confirm delete", "xác nhận xoá ký ức"]:
        assert c(text), text
    assert not c("có")


def test_p0_7k_fix4_comparative_winner_projects_to_preference_snapshot():
    from agent_core.conversation.profile_memory import (
        collect_profile_snapshot, save_comparative_fact, _norm_cmp,
    )
    from agent_core.memory.in_memory_store import InMemoryStore
    store = InMemoryStore()
    save_comparative_fact("ăn kẹo", "ăn kem", "food", store, "s1")
    snap = collect_profile_snapshot(store)
    assert any(_norm_cmp(p) == "ăn kẹo" for p in snap.preferences_personal)
    assert ("ăn kẹo", "ăn kem") in snap.comparatives


def test_p0_7k_fix4_current_food_comparative_supersedes_favorite():
    from agent_core.conversation.memory_operations import parse_memory_operation
    op = parse_memory_operation("bây giờ tôi thích ăn táo hơn")
    assert op is not None
    assert (op.op, op.domain) == ("UPDATE_CURRENT", "favorite")
    assert op.value == "ăn táo"


def test_p0_7k_fix4_snapshot_hygiene_rejects_contrast_dirty_skill():
    from agent_core.conversation.profile_memory import _is_dirty_value
    assert _is_dirty_value("hát nhưng không biết đọc sách")
    assert _is_dirty_value("tôi biết đọc sách")
    assert not _is_dirty_value("hát")
    assert not _is_dirty_value("đọc sách")


# ---------------------------------------------------------------------------
# P0-7K-FIX5A unit tests
# ---------------------------------------------------------------------------

def test_p0_7k_fix5a_splits_batch_preference_query_values():
    from agent_core.conversation.profile_memory import _split_preference_query_items

    assert _split_preference_query_items("ăn kem và chuối") == ["ăn kem", "ăn chuối"]
    assert _split_preference_query_items("ăn cua và ốc") == ["ăn cua", "ăn ốc"]
    assert _split_preference_query_items("AI và ML") == ["AI", "ML"]
    assert _split_preference_query_items("ăn kem, bánh mì và uống cafe") == [
        "ăn kem", "ăn bánh mì", "uống cafe",
    ]


# ---------------------------------------------------------------------------
# P0-7K-FIX5B unit tests
# ---------------------------------------------------------------------------

def test_p0_7k_fix5b_known_preference_canonicalizer_is_memory_backed_and_narrow():
    from agent_core.conversation.profile_memory import canonicalize_known_preference_query_object

    candidates = ["ăn chuối", "ăn kem", "AI"]
    assert canonicalize_known_preference_query_object("ăn chối", candidates) == "ăn chuối"
    assert canonicalize_known_preference_query_object("ăn lem", candidates) == "ăn kem"
    assert canonicalize_known_preference_query_object("A1", candidates) is None
    assert canonicalize_known_preference_query_object("Quy", candidates) is None


def test_p0_7k_fix5b_parse_inline_temporal_negative_preference():
    from agent_core.conversation.memory_operations import parse_memory_operation

    op = parse_memory_operation("tôi bây giờ không thích AI nữa")
    assert op is not None
    assert (op.op, op.domain, op.polarity, op.value) == (
        "UPDATE_CURRENT", "preference", "negative", "AI",
    )

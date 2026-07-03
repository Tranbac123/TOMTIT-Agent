"""CONV-P0 P0-7F — semantic profile intent classification (unit).

Exercises classify_profile_semantic_intent for the coverage gaps P0-7F closes:
preference personal/professional split, person-affinity guard, skill/ability,
occupation shorthand, "muốn" desires, relationship "của tôi" variants, summary
variants, yes/no memory queries, and the "gì nữa" follow-up.

Rule-based, deterministic, provider-free.
"""
from __future__ import annotations

import pytest

from agent_core.conversation.profile_semantics import (
    SemanticProfileIntent,
    classify_profile_semantic_intent,
    normalize_text,
)


def _c(text: str) -> SemanticProfileIntent | None:
    return classify_profile_semantic_intent(text)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def test_normalize_text_lowercases_collapses_and_strips():
    assert normalize_text("  Tôi   Thích  CAFE!! ") == "tôi thích cafe"


# ---------------------------------------------------------------------------
# Preference: personal / professional / person-affinity / unsafe
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, value", [
    ("tôi thích uống cafe", "uống cafe"),
    ("tôi thích đi du lịch", "đi du lịch"),
    ("tôi thích bơi", "bơi"),
])
def test_preference_personal(text: str, value: str):
    c = _c(text)
    assert c is not None
    assert c.kind == "profile_write"
    assert c.category == "preference.personal"
    assert c.value == value
    assert c.write_policy == "auto_safe"


def test_preference_professional():
    c = _c("tôi thích build AI")
    assert c is not None
    assert c.category == "preference.professional"
    assert c.write_policy == "auto_safe"


def test_person_affinity_not_saved_as_preference():
    # P0-7G: person affection is now SAVED as affection/person memory (was clarify),
    # but still carries person_affinity sensitivity so it is never an ordinary preference.
    c = _c("tôi thích Quý")
    assert c is not None
    assert c.category == "relationship.affection_candidate"
    assert c.sensitivity == "person_affinity"
    assert c.write_policy == "auto_safe"


def test_bare_affection_verb_is_person_affinity():
    # P0-7G: "tôi yêu Quý" now saves affection/person memory.
    c = _c("tôi yêu Quý")
    assert c is not None
    assert c.sensitivity == "person_affinity"
    assert c.write_policy == "auto_safe"


def test_preference_unsafe_is_blocked():
    c = _c("tôi thích cocaine")
    assert c is not None
    assert c.category == "sensitive"
    assert c.sensitivity == "unsafe"
    assert c.write_policy == "block"


# ---------------------------------------------------------------------------
# Skill / ability
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, value", [
    ("tôi biết bơi", "bơi"),
    ("tôi biết làm web", "làm web"),
    ("tôi có thể code Python", "code Python"),
    ("tôi giỏi C++", "C++"),
])
def test_skill_writes(text: str, value: str):
    c = _c(text)
    assert c is not None
    assert c.category == "skill"
    assert c.value == value
    assert c.write_policy == "auto_safe"


# ---------------------------------------------------------------------------
# Occupation shorthand
# ---------------------------------------------------------------------------

def test_occupation_toi_lam_ai():
    c = _c("tôi làm AI")
    assert c is not None
    assert c.category == "occupation"
    assert c.value == "AI"


def test_toi_lam_bai_tap_is_not_occupation():
    c = _c("tôi làm bài tập")
    assert c is None or c.category != "occupation"


# ---------------------------------------------------------------------------
# "muốn" desires
# ---------------------------------------------------------------------------

def test_muon_hoc_is_learning_topic():
    c = _c("tôi muốn học LLM")
    assert c is not None
    assert c.category == "learning_topic"
    assert c.value == "LLM"


def test_muon_build_is_goal():
    c = _c("tôi muốn build AI Agent")
    assert c is not None
    assert c.category == "goal"
    assert c.value == "build AI Agent"


def test_muon_tro_thanh_is_goal():
    c = _c("tôi muốn trở thành AI engineer")
    assert c is not None
    assert c.category == "goal"
    assert "trở thành AI engineer" in c.value


def test_muon_di_du_lich_is_preference_personal():
    c = _c("tôi muốn đi du lịch")
    assert c is not None
    assert c.category == "preference.personal"


def test_muon_di_choi_is_near_miss_clarify():
    c = _c("tôi muốn đi chơi")
    assert c is not None
    assert c.write_policy == "clarify"
    assert c.category == "near_miss"


# ---------------------------------------------------------------------------
# Relationship "của tôi" variants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "bạn gái của tôi là Quý",
    "bạn gái của tôi tên là Quý",
    "bạn gái tôi là Quý",
    "bạn gái tôi tên là Quý",
])
def test_relationship_partner_name(text: str):
    c = _c(text)
    assert c is not None
    assert c.category == "relationship.partner_name"
    assert c.value == "Quý"
    assert c.relation_label == "bạn gái"
    assert c.write_policy == "auto_safe"


# ---------------------------------------------------------------------------
# Query kinds
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "bạn đã nhớ gì về tôi",
    "bạn đang nhớ gì về tôi",
    "hồ sơ của tôi có gì",
])
def test_profile_summary_query(text: str):
    c = _c(text)
    assert c is not None
    assert c.kind == "profile_summary_query"


@pytest.mark.parametrize("text, category, value", [
    ("tôi có thích uống cafe không?", "preference", "uống cafe"),
    ("tôi thích bơi đúng không?", "preference", "bơi"),
    ("tôi có biết bơi không?", "skill", "bơi"),
    ("tôi biết bơi đúng không?", "skill", "bơi"),
])
def test_yes_no_memory_query(text: str, category: str, value: str):
    c = _c(text)
    assert c is not None
    assert c.kind == "yes_no_memory_query"
    assert c.category == category
    assert c.value == value


@pytest.mark.parametrize("text", ["gì nữa", "gì nữa?", "còn gì nữa?", "thêm gì nữa?"])
def test_followup(text: str):
    c = _c(text)
    assert c is not None
    assert c.kind == "clarification_followup"


# ---------------------------------------------------------------------------
# Fall-through: legacy-owned inputs return None
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "tôi là Bắc",             # self-name (legacy)
    "tôi là AI engineer",     # "tôi là X" occupation (legacy)
    "tôi đang học LLM",       # non-"muốn" learning (legacy)
    "tôi hay đi phượt",       # habit (legacy)
    "xin chào",               # greeting
    "calculate 2 + 2",        # runtime
])
def test_legacy_inputs_fall_through(text: str):
    assert _c(text) is None


# ---------------------------------------------------------------------------
# P0-7F-FIX2: Interrogative value guard
# ---------------------------------------------------------------------------

from agent_core.conversation.profile_semantics import (
    _is_interrogative_value,
    _is_person_affinity_value,
)


@pytest.mark.parametrize("value", ["ai", "gì", "gi", "uống gì", "ăn gì", "làm gì"])
def test_is_interrogative_value_true(value: str):
    assert _is_interrogative_value(value)


@pytest.mark.parametrize("value", ["build AI", "AI", "cafe", "bơi", "Quý", "uống cafe"])
def test_is_interrogative_value_false(value: str):
    assert not _is_interrogative_value(value)


def test_toi_thich_ai_does_not_save():
    """Bare 'ai' is a Vietnamese question word — must not be saved as a preference."""
    assert _c("tôi thích ai") is None


def test_toi_thich_uong_gi_does_not_save():
    """'uống gì' ends with interrogative — must not be saved as a preference."""
    assert _c("tôi thích uống gì") is None


def test_toi_thich_build_ai_still_saves():
    """'build AI' has a professional token — must still save as professional preference."""
    c = _c("tôi thích build AI")
    assert c is not None
    assert c.category == "preference.professional"
    assert c.write_policy == "auto_safe"


# ---------------------------------------------------------------------------
# P0-7F-FIX2: Lowercase person-affinity guard
# ---------------------------------------------------------------------------

def test_lowercase_viet_name_is_person_affinity():
    """'quý' (lowercase, 3-char Vietnamese word) → person_affinity affection memory (P0-7G)."""
    c = _c("tôi thích quý")
    assert c is not None
    assert c.category == "relationship.affection_candidate"
    assert c.sensitivity == "person_affinity"
    assert c.write_policy == "auto_safe"


def test_person_affinity_two_char_lowercase_excluded():
    """2-char lowercase tokens must not trigger person-affinity (filler word guard)."""
    assert not _is_person_affinity_value("ok")


def test_person_affinity_three_char_lowercase_included():
    """3-char Vietnamese name 'quý' must be detected as person-affinity."""
    assert _is_person_affinity_value("quý")


# ---------------------------------------------------------------------------
# P0-7F-FIX2: Negation no-affection
# ---------------------------------------------------------------------------

def test_toi_khong_thich_ai_is_negation_clarify():
    c = _c("tôi không thích ai")
    assert c is not None
    assert c.category == "negation_no_affection"
    assert c.write_policy == "clarify"
    assert c.value is None


def test_toi_khong_thich_ai_ca_is_negation():
    c = _c("tôi không thích ai cả")
    assert c is not None
    assert c.category == "negation_no_affection"


# ---------------------------------------------------------------------------
# P0-7F-FIX2: Person-affection phrase
# ---------------------------------------------------------------------------

def test_nguoi_toi_thich_ten_la_quy():
    # P0-7G: "người tôi thích tên là Quý" now saves affection/person memory.
    c = _c("người tôi thích tên là Quý")
    assert c is not None
    assert c.category == "relationship.affection_candidate"
    assert c.sensitivity == "person_affinity"
    assert c.write_policy == "auto_safe"
    assert c.value == "Quý"


def test_nguoi_minh_thich_la_nam():
    c = _c("người mình thích là Nam")
    assert c is not None
    assert c.category == "relationship.affection_candidate"
    assert c.value == "Nam"


# ---------------------------------------------------------------------------
# P0-7F-FIX3 Part A: Yes/No query suffix guard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, value", [
    ("tôi thích cafe không", "cafe"),
    ("tôi thích cafe không?", "cafe"),
    ("tôi thích cafe đúng không", "cafe"),
    ("tôi thích cafe phải không", "cafe"),
    ("tôi thích cafe chưa", "cafe"),
    ("tôi có thích cafe không", "cafe"),
])
def test_yesno_suffix_is_query_not_write(text: str, value: str):
    c = _c(text)
    assert c is not None
    assert c.kind == "yes_no_memory_query"
    assert c.category == "preference"
    assert c.value == value
    assert c.write_policy == "none"


def test_cafe_khong_duong_is_still_a_write():
    """'không đường' is content (no-sugar), not a question particle → preference write."""
    c = _c("tôi thích cafe không đường")
    assert c is not None
    assert c.kind == "profile_write"
    assert c.category == "preference.personal"
    assert c.value == "cafe không đường"
    assert c.write_policy == "auto_safe"


def test_yesno_skill_suffix_is_query():
    c = _c("tôi biết bơi phải không")
    assert c is not None
    assert c.kind == "yes_no_memory_query"
    assert c.category == "skill"
    assert c.value == "bơi"


# ---------------------------------------------------------------------------
# P0-7F-FIX3 Part B: AI technology vs ai question word (semantic write side)
# ---------------------------------------------------------------------------

def test_toi_thich_AI_uppercase_saves_professional():
    c = _c("tôi thích AI")
    assert c is not None
    assert c.kind == "profile_write"
    assert c.category == "preference.professional"
    assert c.value == "AI"
    assert c.write_policy == "auto_safe"


def test_toi_lam_AI_is_occupation():
    c = _c("tôi làm AI")
    assert c is not None
    assert c.category == "occupation"
    assert c.write_policy == "auto_safe"


# ---------------------------------------------------------------------------
# P0-7F-FIX3 Part C: Affection explanation guard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, value", [
    ("tôi thích quý có nghĩa là tôi thích đơn phương và chúng tôi chưa là người yêu", "quý"),
    ("tôi thích Quý có nghĩa là tôi thích đơn phương", "Quý"),
    ("tôi thích quý nghĩa là tôi thích đơn phương", "quý"),
    ("tôi thích quý tức là bạn thân", "quý"),
    ("tôi thích quý đơn phương", "quý"),
    ("tôi thích quý nhưng chúng tôi chưa là người yêu", "quý"),
])
def test_affection_explanation_is_clarify_not_write(text: str, value: str):
    c = _c(text)
    assert c is not None
    assert c.category == "affection_explanation"
    assert c.value == value
    assert c.write_policy == "clarify"


# ---------------------------------------------------------------------------
# P0-7F-FIX4 Part A: Affection relation phrase ("có tình cảm với X", "crush X")
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, value", [
    ("tôi có tình cảm với quý", "quý"),
    ("mình có tình cảm với quý", "quý"),
    ("tôi có cảm tình với quý", "quý"),
    ("mình có cảm tình với quý", "quý"),
    ("tôi crush quý", "quý"),
    ("mình crush quý", "quý"),
])
def test_affection_relation_is_saved_as_affection(text: str, value: str):
    # P0-7G: "có tình cảm với X" / "crush X" now saves affection/person memory (was clarify).
    c = _c(text)
    assert c is not None
    assert c.category == "affection_relation"
    assert c.value == value
    assert c.sensitivity == "person_affinity"
    assert c.write_policy == "auto_safe"


# ---------------------------------------------------------------------------
# P0-7F-FIX4 Part B: common object/food is a preference, not a person name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, value", [
    ("tôi thích kem", "kem"),
    ("tôi thích trà", "trà"),
    ("tôi thích phở", "phở"),
    ("tôi thích bánh", "bánh"),
])
def test_common_object_food_is_preference_not_person(text: str, value: str):
    c = _c(text)
    assert c is not None
    assert c.kind == "profile_write"
    assert c.category == "preference.personal"
    assert c.value == value
    assert c.write_policy == "auto_safe"


def test_toi_thich_an_kem_is_preference():
    c = _c("tôi thích ăn kem")
    assert c is not None
    assert c.category == "preference.personal"
    assert c.value == "ăn kem"


@pytest.mark.parametrize("text", ["tôi thích quý", "tôi yêu quý"])
def test_person_name_still_person_affinity(text: str):
    # P0-7G: still person_affinity, now saved as affection (was clarify).
    c = _c(text)
    assert c is not None
    assert c.sensitivity == "person_affinity"
    assert c.write_policy == "auto_safe"


# ---------------------------------------------------------------------------
# P0-7F-FIX4 Part C: friend relation write ("bạn của tôi tên là meo")
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "bạn tôi tên là meo",
    "bạn của tôi tên là meo",
    "bạn mình tên là meo",
    "bạn của mình tên là meo",
])
def test_friend_relation_write(text: str):
    c = _c(text)
    assert c is not None
    assert c.kind == "profile_write"
    assert c.category == "relationship.partner_name"
    assert c.relation_label == "bạn"
    assert c.value == "meo"
    assert c.write_policy == "auto_safe"


# ---------------------------------------------------------------------------
# P0-7F-FIX4 Part D: household pet fact ("nhà tôi có nuôi 1 con mèo")
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "nhà tôi có nuôi 1 con mèo",
    "nhà tôi có nuôi một con mèo",
    "nhà tôi nuôi mèo",
    "nhà mình nuôi mèo",
    "tôi nuôi mèo",
    "mình nuôi mèo",
])
def test_household_pet_write(text: str):
    c = _c(text)
    assert c is not None
    assert c.kind == "profile_write"
    assert c.category == "household_pet"
    assert c.value == "mèo"
    assert c.write_policy == "auto_safe"


# ---------------------------------------------------------------------------
# P0-7F-FIX5 Part B: one-sided affection phrase ("tôi thích đơn phương Quý")
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "tôi thích đơn phương Quý",
    "mình thích đơn phương Quý",
    "tôi đang thích đơn phương Quý",
    "tôi đơn phương Quý",
    "mình đơn phương Quý",
])
def test_one_sided_affection_is_clarify_not_write(text: str):
    c = _c(text)
    assert c is not None
    assert c.kind == "profile_write"
    assert c.category == "one_sided_affection"
    assert c.value == "Quý"
    assert c.sensitivity == "person_affinity"
    assert c.write_policy == "clarify"


def test_affection_explanation_target_before_don_phuong_unchanged():
    # "tôi thích X đơn phương" (target BEFORE "đơn phương") stays affection_explanation,
    # distinct from the new one_sided_affection lane ("đơn phương" BEFORE the target).
    c = _c("tôi thích quý đơn phương")
    assert c is not None
    assert c.category == "affection_explanation"


# ---------------------------------------------------------------------------
# P0-7G: negation / affection classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, value", [
    ("tôi không thích ăn cá", "ăn cá"),
    ("mình không thích chơi game", "chơi game"),
])
def test_p0_7g_negative_preference_write(text: str, value: str):
    c = _c(text)
    assert c is not None
    assert c.category == "negative_preference"
    assert c.value == value
    assert c.write_policy == "auto_safe"


def test_p0_7g_negative_preference_person_stays_clarify():
    # "tôi không thích Quý" is a person, not a durable dislike → clarify, never a write.
    c = _c("tôi không thích Quý")
    assert c is not None
    assert c.write_policy == "clarify"
    assert c.category != "negative_preference"


def test_p0_7g_khong_thich_ai_still_negation():
    c = _c("tôi không thích ai")
    assert c is not None
    assert c.category == "negation_no_affection"


@pytest.mark.parametrize("text, value", [
    ("tôi không muốn đi học", "đi học"),
    ("mình không muốn đi chơi", "đi chơi"),
])
def test_p0_7g_negative_desire_clarify(text: str, value: str):
    c = _c(text)
    assert c is not None
    assert c.category == "negative_desire"
    assert c.value == value
    assert c.write_policy == "clarify"


@pytest.mark.parametrize("text, subj, obj", [
    ("Quý thích tôi", "Quý", "tôi"),
    ("Quý thích Bắc", "Quý", "Bắc"),
])
def test_p0_7g_external_affection_classified(text: str, subj: str, obj: str):
    c = _c(text)
    assert c is not None
    assert c.category == "external_affection"
    assert c.value == subj
    assert c.relation_label == obj
    assert c.write_policy == "auto_safe"


def test_p0_7g_self_affection_not_external():
    # "tôi thích Quý" is self affection, never external.
    c = _c("tôi thích Quý")
    assert c is not None
    assert c.category == "relationship.affection_candidate"


# ---------------------------------------------------------------------------
# P0-7G-FIX3 — memory variant coverage (classification)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, subj, label", [
    ("Quý là người yêu của tôi", "Quý", "người yêu"),
    ("Quý là bạn gái của tôi", "Quý", "bạn gái"),
    ("Quý là bạn trai của tôi", "Quý", "bạn trai"),
])
def test_p0_7g_fix3_reverse_partner_classified(text: str, subj: str, label: str):
    c = _c(text)
    assert c is not None
    assert c.category == "relationship.partner_name"
    assert c.value == subj
    assert c.relation_label == label
    assert c.write_policy == "auto_safe"


@pytest.mark.parametrize("text, value", [
    ("bạn của tôi tên là Meo", "Meo"),
    ("bạn thân của tôi tên là Nam", "Nam"),
])
def test_p0_7g_fix3_friend_variants_classified(text: str, value: str):
    c = _c(text)
    assert c is not None
    assert c.category == "relationship.partner_name"
    assert c.relation_label == "bạn"
    assert c.value == value
    assert c.write_policy == "auto_safe"


def test_p0_7g_fix3_name_change_want_defers_to_name_update():
    # "tôi muốn đổi tên thành X" must NOT be a near-miss desire — the semantic layer
    # defers (returns None) so the dedicated self-name update path owns it.
    assert _c("tôi muốn đổi tên thành Bắc Trần") is None


def test_p0_7g_fix3_reverse_partner_self_word_rejected():
    # A self word as the subject must not be saved as a partner.
    assert _c("tôi là người yêu của tôi") is None

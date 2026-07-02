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
    c = _c("tôi thích Quý")
    assert c is not None
    assert c.category == "relationship.affection_candidate"
    assert c.sensitivity == "person_affinity"
    assert c.write_policy == "clarify"


def test_bare_affection_verb_is_person_affinity():
    c = _c("tôi yêu Quý")
    assert c is not None
    assert c.sensitivity == "person_affinity"
    assert c.write_policy == "clarify"


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

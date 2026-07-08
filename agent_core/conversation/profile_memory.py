"""CONV-P0 P0-7B/7C/7D: Rule-based user profile fact detection and retrieval.

Provider-free. Covers self-name, relation-name, and AUTO_SAFE self-profile facts.
No LLM, no network, no TOMTIT-Memory changes.

P0-7C adds:
- anchored self-identity query (prevents "tôi là AI engineer" from triggering recall)
- relation synonym queries: người yêu, partner → match bạn gái/bạn trai records
- profile summary query: bạn biết/nhớ gì về tôi?

P0-7D adds:
- AUTO_SAFE extraction: occupation, preference, goal, learning_focus
- confirmation-gated relation.name for người yêu / partner forms
- category-specific query answering with unknown-state responses
- profile summary expanded to include v2 categories
- backward-compatible v1/v2 schema retrieval

P0-7E adds:
- AUTO_SAFE for self.habit (lifestyle) and direct self.name / relation.name
- natural, category-specific post-save acknowledgements (build_profile_ack)
- deterministic safety response for unsafe/sensitive blocked values
- conflict-safe name/relation writes (never silently overwrite an existing value)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from agent_core.memory.memory_records import MemoryQuery
from agent_core.state.enums import MemoryType, SourceType

if TYPE_CHECKING:
    from agent_core.memory.base import MemoryStoreProtocol


# ---------------------------------------------------------------------------
# Data objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfileFactCandidate:
    subject: Literal["self", "relation"]
    relation: Literal["name"]
    value: str
    relation_label: str | None = None   # "bạn gái", "vợ", "người yêu", etc.
    original_text: str = ""


@dataclass(frozen=True)
class AutoProfileCandidate:
    """An AUTO_SAFE profile fact — written without confirmation."""
    subject: Literal["self"] = "self"
    relation: Literal[
        "occupation", "preference", "goal", "learning_focus", "habit", "skill",
        # P0-7F-FIX4 Part D
        "household_pet",
        # P0-7G: durable negative preference ("tôi không thích ăn cá")
        "negative_preference",
        # P0-7K-FIX1: negative skill ("tôi không biết bơi"), goal focus ("mục tiêu chính")
        "negative_skill", "goal_focus",
    ] = "occupation"
    value: str = ""
    original_text: str = ""
    # P0-7F: personal vs professional split for preferences (metadata only; the storage
    # relation stays "preference" so existing retrieval keeps working).
    preference_kind: str | None = None


@dataclass(frozen=True)
class BlockedProfileAttempt:
    """A message that matched an auto-profile pattern but carried an unsafe/sensitive value.

    Detected so the runtime can return a specific safety response instead of silently
    saving (P0-7D guard) then falling through to a generic fallback (P0-7E UX).
    """
    relation: str
    value: str
    original_text: str = ""


@dataclass(frozen=True)
class PendingProfileConfirmationState:
    kind: Literal["profile_fact_confirmation"]
    candidate: ProfileFactCandidate
    prompt_text: str
    session_id: str
    created_at_turn: int
    expires_after_turns: int = 2


@dataclass(frozen=True)
class ProfileQuery:
    kind: Literal[
        "self_name", "self_identity", "relation_name",
        "inverse_value", "profile_summary",
        # P0-7D new query kinds
        "self_occupation", "self_preference", "self_goal",
        "self_learning_focus", "relation_existence",
        # P0-7E
        "self_habit",
        # P0-7F
        "self_skill",
        # P0-7F-FIX2
        "self_affection", "self_drink_preference",
        # P0-7F-FIX3
        "third_party_affection",
        # P0-7F-FIX4
        "friend_name", "self_pet",
        # P0-7F-FIX5
        "self_pet_yesno",
        # P0-7G
        "reverse_entity", "named_affection_yesno",
        # P0-7G-FIX3
        "self_dislike",
        # P0-7H
        "relation_yesno",
        # P0-7I
        "self_occupation_yesno",
        # P0-7J
        "self_current_goal", "old_name_confirm",
        # P0-7J-FIX1
        "self_do_yesno",
        # P0-7K-FIX1
        "self_preference_ranking", "self_ai_yesno", "goal_challenge", "goal_followup",
        # P0-7K-FIX2
        "self_food_favorite", "self_comparative", "self_food_preference",
        "self_food_dislike", "self_negative_skill",
        # P0-7K-FIX5C-LITE — person relation query core
        "incoming_affection_set", "batch_incoming_affection", "person_affection_target",
        # P0-7K-FIX6-LITE — predicate/action fact core
        "wants_to_marry_query", "wants_to_learn_query", "wants_to_build_query",
    ]
    value: str | None = None          # for inverse_value: the name to look up
    relation_label: str | None = None  # for relation_name / relation_existence
    object_value: str | None = None    # P0-7G named_affection_yesno: the object of "A thích B"


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_QUESTION_WORDS = frozenset({"ai", "gì", "đây", "đó", "thế", "sao", "vậy", "như_thế_nào"})

# Storage-level relation labels (used in candidate detection and save).
_RELATIONS_CANDIDATE_PATTERN = r'(bạn\s+gái|bạn\s+trai|vợ|chồng)'

# Query-level relation labels: storage labels + P0-7C synonyms (người yêu, partner).
_RELATIONS_QUERY_PATTERN = r'(bạn\s+gái|bạn\s+trai|người\s+yêu|vợ|chồng|partner)'

_RELATION_TAG_MAP: dict[str, str] = {
    "bạn gái": "ban_gai",
    "bạn trai": "ban_trai",
    "vợ": "vo",
    "chồng": "chong",
    "người yêu": "nguoi_yeu",
    "partner": "partner",
}

# P0-7C: synonym expansion for relation queries.
_RELATION_SYNONYM_MAP: dict[str, frozenset[str]] = {
    "người yêu": frozenset({"bạn gái", "bạn trai", "người yêu", "partner"}),
    "partner": frozenset({"bạn gái", "bạn trai", "người yêu", "partner"}),
}


def _get_lookup_labels(query_label: str | None) -> frozenset[str]:
    """Expand a query relation label to the set of stored labels to search."""
    if query_label is None:
        return frozenset()
    return _RELATION_SYNONYM_MAP.get(query_label, frozenset({query_label}))


def _remember_wrapper(inner: str) -> str:
    """Build a bounded "bạn biết/nhớ ... không?" query wrapper around an inner pattern."""
    return r'bạn\s+(?:có\s+)?(?:biết|nhớ)\s+' + inner + r'\s+(?:không|ko|hông|hong)'


# ---------------------------------------------------------------------------
# P0-7D constants — AUTO_SAFE safety guards
# ---------------------------------------------------------------------------

# Keywords that indicate a professional role; used to gate "tôi là VALUE" occupation
# auto-save so it doesn't fire for general descriptions like "người tốt".
_ROLE_KEYWORDS: frozenset[str] = frozenset({
    "engineer", "developer", "designer", "manager", "analyst", "doctor",
    "teacher", "researcher", "consultant", "architect", "programmer",
    "scientist", "writer", "director", "specialist", "expert", "trainer",
    "advisor", "agent", "officer", "intern", "lead", "senior", "junior",
    "data", "backend", "frontend", "fullstack", "devops", "ai", "ml",
    "ux", "ui", "qa", "sre", "cto", "ceo", "cfo", "vp",
    "enginer",   # typo accepted per spec
    "blogger", "bloger",  # P0-7H: occupation variants (bloger = common typo of blogger)
    "founder", "startup",
    # P0-7J: short role terms — "tôi là DEV/IT/developper" saves occupation, never a name.
    "it", "dev", "developper",
    "kỹ sư", "lập trình", "bác sĩ", "giáo viên", "chuyên gia",
    "nhà nghiên cứu", "nhà thiết kế", "giám đốc", "kế toán", "nhà báo",
    "nông dân", "sinh viên",  # P0-7H: Vietnamese occupation phrases
})

# Vague reference words that should not be saved as preference/occupation values.
_VAGUE_REFS: frozenset[str] = frozenset({
    "nó", "đó", "này", "kia", "vậy", "thế",
    "cái này", "cái đó", "cái kia",
    "thứ này", "thứ kia",
    "việc này", "việc đó",
    "điều này", "điều đó",
})

# Prefix patterns that mark text as a note/command/correction → skip auto-save.
_RE_NOTE_CMD_PREFIX = re.compile(
    r'^(?:'
    r'note|ghi\s+chú|lưu\s+ghi\s+chú|lưu\s+note|viết\s+ghi\s+chú'
    r'|calculate|tính|tìm|search'
    r'|đọc|read\s+note'
    r'|xóa|xoá|sửa|cập\s+nhật|delete|update|remove|thay\s+đổi'
    r'|remind|nhắc|schedule'
    r')\s+',
    re.IGNORECASE,
)


def _is_safe_for_auto_save(text: str) -> bool:
    """Return False if text starts with a note/command/correction prefix."""
    return not _RE_NOTE_CMD_PREFIX.match(text.strip())


# Single-token keywords (all ASCII) must match on a WHOLE token, not as a substring —
# otherwise short ones like "ai"/"ml" over-match ("ai" inside "trai"/"hai", "con trai").
# Multi-word Vietnamese phrases ("kỹ sư", "lập trình", …) stay substring-matched: they are
# specific enough that a substring hit is a genuine hit.
_ROLE_KEYWORD_TOKENS: frozenset[str] = frozenset(k for k in _ROLE_KEYWORDS if " " not in k)
_ROLE_KEYWORD_PHRASES: frozenset[str] = frozenset(k for k in _ROLE_KEYWORDS if " " in k)
_RE_ASCII_TOKEN = re.compile(r"[a-z0-9]+")

# P0-7H: Vietnamese single-word occupation terms whose diacritics prevent ASCII-token matching.
# Matched as whole Unicode words (split on whitespace) to avoid substring over-match.
_VN_ROLE_KEYWORD_SINGLE: frozenset[str] = frozenset({"nông"})


def _has_role_keyword(value: str) -> bool:
    """True if value contains a known role/profession keyword.

    Single-word keywords are matched against whole ASCII tokens (so "ai enginer" matches
    but "con trai" does not); multi-word phrases are matched as substrings.
    Vietnamese diacritic single-word terms are matched as whole Unicode words.
    """
    value_lower = value.lower()
    if any(phrase in value_lower for phrase in _ROLE_KEYWORD_PHRASES):
        return True
    tokens = _RE_ASCII_TOKEN.findall(value_lower)
    if any(tok in _ROLE_KEYWORD_TOKENS for tok in tokens):
        return True
    return any(w in _VN_ROLE_KEYWORD_SINGLE for w in value_lower.split())


# P0-7D-FIX2: rule-based unsafe/sensitive value guard for AUTO_SAFE writes.
# Deterministic, conservative, no NLP/LLM. AUTO_SAFE silently persists profile facts
# without confirmation, so a value that names an illegal drug, a secret/credential, a
# government ID, or exact private contact info must NOT be auto-written to durable memory.
# Blocked auto-save falls through to the normal router/fallback (no "Đã lưu" claim).
#
# Multi-word / diacritic phrases are substring-matched (specific enough that a hit is real);
# single ASCII-ish terms are whole-token matched (avoid substring over-match); a small set
# of short ambiguous terms ("đá") is matched only as the entire value (so "đá bóng" survives).
_UNSAFE_VALUE_PHRASES: frozenset[str] = frozenset({
    # illegal / recreational drugs
    "thuốc phiện", "thuoc phien", "ma túy", "ma tuy", "cần sa", "can sa",
    "ma đá", "ma da", "chất cấm", "chat cam",
    # credentials / secrets
    "mật khẩu", "mat khau", "api key",
    # government id / private identity
    "căn cước", "can cuoc", "số tài khoản", "so tai khoan",
    "số điện thoại", "so dien thoai", "địa chỉ nhà", "dia chi nha",
})
_UNSAFE_VALUE_TOKENS: frozenset[str] = frozenset({
    # illegal / recreational drugs
    "cocaine", "cocain", "coke", "heroin", "heroine", "meth",
    "methamphetamine", "amphetamine", "cannabis", "marijuana", "weed", "opium",
    "ketamine", "lsd", "mdma", "ecstasy",
    # credentials / secrets
    "password", "passwd", "token", "secret", "otp",
    # government id
    "cmnd", "cccd", "passport",
})
# Short ambiguous terms blocked only when they are the ENTIRE value.
_UNSAFE_VALUE_EXACT: frozenset[str] = frozenset({"đá", "da"})
_RE_UNICODE_TOKEN = re.compile(r"\w+", re.UNICODE)


def _is_unsafe_or_sensitive_auto_value(value: str) -> bool:
    """True if value names an unsafe/sensitive thing that must not be auto-saved."""
    v = value.strip().lower()
    if not v:
        return False
    if v in _UNSAFE_VALUE_EXACT:
        return True
    if any(phrase in v for phrase in _UNSAFE_VALUE_PHRASES):
        return True
    tokens = _RE_UNICODE_TOKEN.findall(v)
    return any(tok in _UNSAFE_VALUE_TOKENS for tok in tokens)


# P0-7K-FIX2: query/ranking/comparative markers that must never enter an ordinary
# preference via the legacy auto-save path (defense in depth for the semantic guard).
_LEGACY_QUERY_WORD_TOKENS: frozenset[str] = frozenset({"gì", "gi", "nào", "đâu"})
_LEGACY_RANKING_COMPARATIVE_TOKENS: frozenset[str] = frozenset({
    "nhất", "nhat", "nhata", "hơn", "hay",
})


def _value_has_query_word(value: str) -> bool:
    """True if value contains a bare query word or a ranking/comparative marker token.

    Blocks the legacy preference auto-save for phrases like "ăn gì nhất",
    "code hay thích vẽ hơn" — favorites/comparatives are owned by the semantic layer.
    """
    tokens = re.sub(r"\s+", " ", value.strip().lower()).split()
    return any(
        t in _LEGACY_QUERY_WORD_TOKENS or t in _LEGACY_RANKING_COMPARATIVE_TOKENS
        for t in tokens
    )


def _is_valid_auto_value_shape(value: str) -> bool:
    """True if value has a meaningful, non-vague, bounded SHAPE (ignores safety).

    P0-7E splits shape from safety so the runtime can distinguish "not a profile claim"
    (shape invalid) from "a profile claim carrying an unsafe value" (shape valid but
    blocked) — the latter gets a specific safety response instead of a generic fallback.
    """
    v = value.strip()
    if not v or len(v) > 80:
        return False
    # P0-7K-FIX5A: short technical acronyms are meaningful preference/topic objects
    # ("AI", "ML"). Keep this uppercase-only so lowercase "ai" remains a question word.
    if len(v) < 3:
        return bool(re.fullmatch(r"[A-Z0-9]{2,5}", v))
    if v.lower() in _VAGUE_REFS:
        return False
    return True


def _is_valid_auto_value(value: str) -> bool:
    """True if value is a meaningful, non-vague, bounded, SAFE string for auto-save."""
    if not _is_valid_auto_value_shape(value):
        return False
    # P0-7D-FIX2: never auto-save unsafe/sensitive values into durable profile memory.
    if _is_unsafe_or_sensitive_auto_value(value.strip()):
        return False
    return True


# ---------------------------------------------------------------------------
# Candidate detection patterns
# ---------------------------------------------------------------------------

# "tôi tên là Bắc", "mình tên là Bắc"
# "tôi tên là Bắc", "tôi tên Bắc" (P0-7F-FIX3 Part E: "là" optional)
_RE_SELF_TEN_LA = re.compile(
    r'^(?:tôi|mình)\s+tên\s+(?:là\s+)?([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# "tên tôi là Bắc", "tên mình là Bắc", "tên tôi Bắc" (P0-7F-FIX3 Part E: "là" optional)
_RE_TEN_TOI_LA = re.compile(
    r'^tên\s+(?:tôi|mình)\s+(?:là\s+)?([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# "lưu tên tôi là Bắc"
_RE_LUU_TEN_LA = re.compile(
    r'^lưu\s+tên\s+(?:tôi|mình)\s+là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# "tôi là Bắc" / "mình là Bắc" — single proper name (uppercase first char)
_RE_SELF_IS = re.compile(
    r'^(?:tôi|mình)\s+là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.DOTALL,
)
# Relation-name candidate (storage labels): "bạn gái tôi tên là Quý"
_RE_RELATION_NAME = re.compile(
    r'^' + _RELATIONS_CANDIDATE_PATTERN + r'\s+(?:tôi|mình)\s+tên\s+là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7D: "người yêu của tôi tên là Quý", "người yêu tôi là Quý", "partner của tôi là Quý"
_RE_NGUOI_YEU_PARTNER_NAME = re.compile(
    r'^(?:người\s+yêu|partner)\s+(?:của\s+)?(?:tôi|mình)\s+(?:tên\s+)?là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7G: explicit self-name update/correction — "sửa tên tôi thành bb", "đổi tên của
# tôi thành Nam", "cập nhật tên tôi là Bắc Trần". The new value (group 1) may be multi-word.
_RE_NAME_UPDATE_CMD = re.compile(
    r'^(?:sửa|đổi|thay\s+đổi|cập\s+nhật|đổi\s+lại)\s+tên\s+'
    r'(?:của\s+)?(?:tôi|mình)\s+(?:thành|là|sang)\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7G-FIX3 A1: "tên mới của tôi là Bắc Trần" — explicit new-name declaration.
_RE_NAME_NEW_IS = re.compile(
    r'^tên\s+mới\s+(?:của\s+)?(?:tôi|mình)\s+(?:là|:)\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7G-FIX3 A1: "tôi muốn đổi tên thành Bắc Trần" — bounded name-change desire treated as
# an explicit update (only this "đổi/đặt lại tên" phrasing; general "muốn" stays a desire).
_RE_NAME_WANT_CHANGE = re.compile(
    r'^(?:tôi|mình)\s+muốn\s+(?:đổi|thay\s+đổi|đổi\s+lại|đặt\s+lại)\s+tên\s+'
    r'(?:(?:của\s+)?(?:tôi|mình)\s+)?(?:thành|là|sang)\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7G: full-name self assertion — "tôi là Bắc Trần" (multi-word). Used ONLY for name
# UPDATE when a name already exists; a full-name phrase (all tokens name-like, no role
# keyword) is treated as a name correction rather than an occupation.
_RE_SELF_IS_PHRASE = re.compile(
    r'^(?:tôi|mình)\s+là\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
# Common non-name descriptor tokens that must never be captured as a self-name phrase.
_NON_NAME_WORDS: frozenset[str] = frozenset({
    "người", "một", "đang", "rất", "ai", "gì", "gi", "cái", "con", "the",
})

# ---------------------------------------------------------------------------
# AUTO_SAFE extraction patterns (P0-7D)
# ---------------------------------------------------------------------------

# Occupation — "tôi là VALUE" (multi-word + role keyword required to avoid name/description clash)
_RE_OCCUPATION_TOI_LA = re.compile(
    r'^(?:tôi|mình)\s+là\s+(.{3,60}?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# Occupation — "tôi làm VALUE", "mình làm việc VALUE"
_RE_OCCUPATION_TOI_LAM = re.compile(
    r'^(?:tôi|mình)\s+làm\s+(?:việc\s+)?(.{3,60}?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# Occupation — "nghề của tôi là", "công việc của tôi là", "vai trò của tôi là"
_RE_OCCUPATION_CONTEXT = re.compile(
    r'^(?:nghề|công\s+việc|vai\s+trò)\s+(?:của\s+)?(?:tôi|mình)\s+là\s+(.{3,60}?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# Preference — "tôi thích VALUE", "mình thích VALUE"
_RE_PREFERENCE_THICH = re.compile(
    r'^(?:tôi|mình)\s+thích\s+(.{3,60}?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# Preference — "tôi quan tâm đến VALUE"
_RE_PREFERENCE_QUAN_TAM = re.compile(
    r'^(?:tôi|mình)\s+quan\s+tâm\s+đến\s+(.{3,60}?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# Preference — "sở thích của tôi là VALUE"
_RE_PREFERENCE_SO_THICH = re.compile(
    r'^sở\s+thích\s+(?:của\s+)?(?:tôi|mình)\s+là\s+(.{3,60}?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# Learning focus — "tôi đang học", "tôi muốn học", "tôi đang tập trung học", "tôi học"
_RE_LEARNING = re.compile(
    r'^(?:tôi|mình)\s+(?:đang\s+tập\s+trung\s+học|đang\s+học|muốn\s+học|học)\s+(.{2,60}?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# Goal — "mục tiêu của tôi là VALUE", "goal của tôi là VALUE"
_RE_GOAL = re.compile(
    r'^(?:mục\s+tiêu|goal)\s+(?:của\s+)?(?:tôi|mình)\s+là\s+(.{3,80}?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7E Habit / lifestyle — "tôi hay VALUE", "tôi thường VALUE" (incl. "hay đi", "thường đi")
_RE_HABIT = re.compile(
    r'^(?:tôi|mình)\s+(?:hay|thường|thường\s+xuyên)\s+(.{2,60}?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)

# ---------------------------------------------------------------------------
# Query detection patterns
# ---------------------------------------------------------------------------

# Self-name queries — unanchored (.search) intentional.
# "bạn tên là gì?" / "tên bạn là gì?" are intentionally EXCLUDED: they ask about TomTit,
# not the user's name, and are handled by the router as DIRECT_RESPONSE (identity).
# "bạn nhớ tôi tên gì?" is INCLUDED: "bạn nhớ" marks it as a recall request about the user.
_RE_SELF_NAME_Q = re.compile(
    r'(?:tôi|mình)\s+tên\s+(?:là\s+)?g[ìi]\s*\??'
    r'|tên\s+(?:tôi|mình)\s+(?:là\s+)?g[ìi]\s*\??'
    r'|tên\s+của\s+(?:tôi|mình)\s+(?:là\s+)?g[ìi]\s*\??'
    r'|bạn\s+nhớ\s+(?:tôi|mình)\s+tên\s+g[ìi]',
    re.IGNORECASE,
)

# P0-7C FIX: fully anchored
_RE_SELF_IDENTITY_Q = re.compile(
    (
        r'^\s*(?:'
        r'(?:tôi|mình)\s+là\s+ai'
        r'|' + _remember_wrapper(r'(?:tôi|mình)\s+là\s+ai')
        + r')\s*[?？]?\s*$'
    ),
    re.IGNORECASE,
)
_RE_SELF_NAME_REMEMBER_Q = re.compile(
    r'^\s*(?:'
    + _remember_wrapper(r'tên\s+(?:của\s+)?(?:tôi|mình)')
    + r'|'
    + _remember_wrapper(r'(?:tôi|mình)\s+tên\s+g[ìi]')
    + r')\s*[?？]?\s*$',
    re.IGNORECASE,
)

# Relation name query "tên gì?" — includes P0-7C synonyms + optional "của"
_RE_RELATION_NAME_Q = re.compile(
    (
        r'^(?:'
        + _RELATIONS_QUERY_PATTERN
        + r'(?:\s+của)?\s+(?:tôi|mình)\s+tên\s+(?:là\s+)?g[ìi]'
        + r'|'
        + _remember_wrapper(
            _RELATIONS_QUERY_PATTERN
            + r'(?:\s+của)?\s+(?:tôi|mình)\s+tên\s+(?:là\s+)?g[ìi]'
        )
        + r')\s*[?？]?\s*$'
    ),
    re.IGNORECASE,
)

# P0-7C: relation "là ai?" form
_RE_RELATION_LA_AI_Q = re.compile(
    (
        r'^(?:'
        + _RELATIONS_QUERY_PATTERN
        + r'(?:\s+của)?\s+(?:tôi|mình)\s+là\s+ai'
        + r'|'
        + _remember_wrapper(
            _RELATIONS_QUERY_PATTERN + r'(?:\s+của)?\s+(?:tôi|mình)\s+là\s+ai'
        )
        + r')\s*[?？]?\s*$'
    ),
    re.IGNORECASE,
)

# P0-7H: relation yes/no query — "Quý có phải là bạn gái của tôi không?"
# Person name (group 1) + relation label (group 2); runtime checks stored relation.
_RE_RELATION_YESNO_Q = re.compile(
    r'^(\S+)\s+có\s+phải\s+là\s+'
    r'(bạn\s+gái|bạn\s+trai|người\s+yêu|vợ|chồng|partner)\s+'
    r'(?:của\s+)?(?:tôi|mình)\s+(?:không|ko|hông|hong)\s*[?？]?\s*$',
    re.IGNORECASE,
)

# P0-7H: relation update command — "sửa bạn gái của tôi thành May"
_RE_RELATION_UPDATE_CMD = re.compile(
    r'^(?:sửa|đổi|cập\s+nhật|thay\s+đổi)\s+'
    r'(bạn\s+gái|bạn\s+trai|người\s+yêu|vợ|chồng|partner)\s+'
    r'(?:của\s+)?(?:tôi|mình)\s+(?:thành|sang|là)\s+(\S+)\s*[.!]*\s*$',
    re.IGNORECASE,
)

# P0-7H: relation removal command — "cập nhật Quý không phải là bạn gái của tôi"
_RE_RELATION_REMOVAL_CMD = re.compile(
    r'^(?:cập\s+nhật|sửa|đổi)\s+(\S+)\s+không\s+phải\s+là\s+'
    r'(bạn\s+gái|bạn\s+trai|người\s+yêu|vợ|chồng|partner)\s+'
    r'(?:của\s+)?(?:tôi|mình)\s*[.!]*\s*$',
    re.IGNORECASE,
)

# P0-7H-FIX1 A6: left-side form — "VALUE là nghề/công việc/nghề nghiệp của tôi [chứ/không phải tên]"
# Must run before the generic CHU pattern to avoid capturing "của tôi" as the occupation.
_RE_OCC_CORRECTION_LEFT = re.compile(
    r'^(\S+(?:\s+\S+)?)\s+là\s+(?:nghề|công\s+việc|nghề\s+nghiệp)\s+(?:của\s+)?(?:tôi|mình)',
    re.IGNORECASE,
)

# P0-7H-FIX1 A6: correction of occupation/name confusion — "là X chứ không phải tên"
# Used as generic fallback when the left-side form does not match.
_RE_OCC_CORRECTION_CHU = re.compile(
    r'(?:là\s+)?(\S+(?:\s+\S+)?)\s+chứ\s+không\s+phải\s+(?:là\s+)?tên',
    re.IGNORECASE,
)

# P0-7H-FIX1 A6: standalone form — "X là nghề/công việc của tôi" (no trailing correction guard)
_RE_OCC_CORRECTION_NGHE = re.compile(
    r'^(\S+(?:\s+\S+)?)\s+là\s+(?:nghề|công\s+việc)\s+(?:của\s+)?(?:tôi|mình)\s*[.!]*\s*$',
    re.IGNORECASE,
)

# P0-7H-FIX1 B: alias relation query — "bạn gái của Bắc là ai?" (Bắc = current user alias)
_RE_RELATION_ALIAS_Q = re.compile(
    r'^(bạn\s+gái|bạn\s+trai|người\s+yêu|vợ|chồng|partner)\s+(?:của\s+)?(\S+)\s+(?:là\s+)?ai\s*[?？]?\s*$',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# P0-7I: correction lead-in stripping
# ---------------------------------------------------------------------------

# "không, tôi ..." / "không tôi ..." — a leading negation/correction marker followed by a
# self-assertion clause. Requires "tôi/mình" directly after "không" so this never matches
# an ordinary negative-preference sentence ("tôi không thích X"), which has "không" in the
# MIDDLE, not as the first token.
_RE_CORRECTION_KHONG = re.compile(
    r'^không[,]?\s+((?:tôi|mình)\b.*)$',
    re.IGNORECASE | re.DOTALL,
)
# "ý tôi là ..." / "ý mình là ..." — explicit correction lead-in.
_RE_CORRECTION_Y_TOI_LA = re.compile(
    r'^ý\s+(?:tôi|mình)\s+là\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
# "tôi mới/vừa nói ... mà" — the user restates what they just said as a correction.
# Trailing "mà" is stripped from the captured clause.
_RE_CORRECTION_MOI_NOI = re.compile(
    r'^(?:tôi|mình)\s+(?:mới|vừa)\s+nói\s+(?:là\s+)?(.+?)\s*(?:mà)?\s*[.!?]*\s*$',
    re.IGNORECASE | re.DOTALL,
)

# P0-7I: occupation removal — "tôi không phải (là) VALUE". Extraction only; the caller
# checks the value against currently stored occupations before acting, so an unrelated
# denial never fires.
_RE_OCC_REMOVAL = re.compile(
    r'^(?:tôi|mình)\s+không\s+phải\s+(?:là\s+)?(.+?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)

# P0-7I: self occupation yes/no — "tôi có phải là AI không?", "tôi có phải là nông dân không?"
_RE_SELF_OCC_YESNO_Q = re.compile(
    r'^(?:tôi|mình)\s+có\s+phải\s+là\s+(.+?)\s+(?:không|ko|hông|hong)\s*[?？]?\s*$',
    re.IGNORECASE,
)

# P0-7J: current goal/intention query — "tôi đang muốn làm gì?", "tôi đang định build gì?"
# P0-7J-FIX1: no-diacritic/typo variants ("tôi se làm gì?", "toi se lam gi?").
_RE_CURRENT_GOAL_Q = re.compile(
    r'^(?:tôi|mình|toi|minh)\s+(?:đang\s+|dang\s+)?(?:muốn|muon|định|dinh|sẽ|se)\s+'
    r'(?:làm|lam|build)\s+g[ìi]\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7K-FIX6-LITE: action-specific "muốn <action> <pronoun>" queries. "cưới ai" is a query
# (with or without a "?"), so the write path never stores it. Checked before the general
# "muốn làm/build gì?" goal query so build/marry/learn keep distinct answers.
_RE_WANTS_MARRY_Q = re.compile(
    r'^(?:tôi|mình)\s+(?:đang\s+)?muốn\s+cưới\s+(?:ai|gì|gi)\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7K-FIX6-LITE-FIX1: lowercase "ai" is the question pronoun and routes here as a query;
# uppercase "AI" ("tôi muốn học AI") is a tech topic and must fall through to the write
# path. The scoped case-sensitive group ``(?-i:ai)`` matches only lowercase "ai".
_RE_WANTS_LEARN_Q = re.compile(
    r'^(?:tôi|mình)\s+(?:đang\s+)?muốn\s+học\s+(?:gì|gi|(?-i:ai))\s*[?？]?\s*$',
    re.IGNORECASE,
)
_RE_WANTS_BUILD_Q = re.compile(
    r'^(?:tôi|mình)\s+(?:đang\s+)?muốn\s+build\s+(?:gì|gi)\s*[?？]?\s*$',
    re.IGNORECASE,
)

# P0-7J-FIX1: self do/goal yes-no — "tôi có làm LLM nữa không?", "tôi có còn làm X không?",
# "tôi có muốn làm X nữa không?", "tôi có build X nữa không?". Answered against active
# occupations and active goals (current-state).
_RE_SELF_DO_YESNO_Q = re.compile(
    r'^(?:tôi|mình)\s+có\s+(?:còn\s+)?(?:muốn\s+)?(?:làm|build)\s+'
    r'(.+?)(?:\s+nữa)?\s+(?:không|ko|hông|hong)\s*[?？]?\s*$',
    re.IGNORECASE,
)

# P0-7J: old-name confirmation — "Bắc là tên cũ của tôi, bạn còn nhớ không?"
_RE_OLD_NAME_CONFIRM_Q = re.compile(
    r'^(.+?)\s+là\s+tên\s+(?:cũ|trước\s+đây)\s+của\s+(?:tôi|mình)\b',
    re.IGNORECASE,
)

# P0-7K-FIX1 J: preference ranking query — "tôi thích gì nhất", "tôi thích gì nhata"
# (with or without "?"). Answered safely (no ranking engine), never written as a fact.
_RE_PREF_RANKING_Q = re.compile(
    r'^(?:tôi|mình)\s+thích\s+(?:cái\s+)?g[ìi]\s+(?:\S.*)$',
    re.IGNORECASE,
)
# P0-7K-FIX2 A/B: food-favorite / food-ranking query — "tôi thích ăn gì nhất".
_RE_FOOD_FAVORITE_Q = re.compile(
    r'^(?:tôi|mình)\s+thích\s+(?:ăn|uống)\s+(?:cái\s+)?g[ìi]\s+nhất\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7K-FIX2 C: comparative query — "tôi thích A hay (thích) B hơn?".
_RE_COMPARATIVE_Q = re.compile(
    r'^(?:tôi|mình)\s+thích\s+(.+?)\s+hay\s+(?:thích\s+)?(.+?)\s+hơn\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7K-FIX2 H: food-specific negative query — "tôi không thích ăn gì?".
_RE_FOOD_NEG_Q = re.compile(
    r'^(?:tôi|mình)\s+không\s+thích\s+ăn\s+(?:cái\s+)?g[ìi]\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7K-FIX2 H: food-specific positive query — "tôi thích ăn gì?".
_RE_FOOD_POS_Q = re.compile(
    r'^(?:tôi|mình)\s+thích\s+ăn\s+(?:cái\s+)?g[ìi]\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7K-FIX2 E: negative-skill list query — "tôi không biết gì?", "tôi không biết làm gì?".
_RE_NEGATIVE_SKILL_Q = re.compile(
    r'^(?:tôi|mình)\s+không\s+biết\s+(?:làm\s+)?g[ìi]\s*[?？]?\s*$',
    re.IGNORECASE,
)

# P0-7K-FIX1 E: self AI-domain yes/no — "tôi có làm AI không?". Answered via the
# lightweight AI taxonomy against active goals/occupations.
_RE_SELF_AI_YESNO_Q = re.compile(
    r'^(?:tôi|mình)\s+có\s+(?:còn\s+)?(?:muốn\s+)?(?:làm|build)\s+'
    r'ai\s+(?:không|ko|hông|hong)\s*[?？]?\s*$',
    re.IGNORECASE,
)

# P0-7K-FIX1 G: memory-challenge / reminder — "bạn không nhớ tôi sẽ làm X à?".
_RE_GOAL_CHALLENGE_Q = re.compile(
    r'^bạn\s+không\s+nhớ\s+(?:là\s+)?(?:tôi|mình)\s+(?:sẽ|se|muốn|định)\s+'
    r'(?:làm|build)\s+(.+?)\s*(?:à|ư|hả|sao)?\s*[?？]*\s*$',
    re.IGNORECASE,
)

# P0-7K-FIX1 H: goal follow-up — "và gì nữa?", "còn gì nữa?", "ngoài ra còn gì?".
_RE_GOAL_FOLLOWUP_Q = re.compile(
    r'^(?:và|còn|ngoài\s+ra\s+còn|thế\s+còn)\s+(?:gì|cái\s+gì)(?:\s+(?:nữa|khác))?\s*[?？]*\s*$',
    re.IGNORECASE,
)

# P0-7C: profile summary queries. P0-7F broadens to "đã/đang" tenses,
# "lưu thông tin gì", and "hồ sơ của tôi có gì".
_RE_PROFILE_SUMMARY_Q = re.compile(
    r'^\s*(?:'
    r'bạn\s+(?:đã\s+|đang\s+)?(?:biết|nhớ|lưu)\s+(?:gì\s+)?về\s+(?:tôi|mình)'
    r'|bạn\s+(?:đã\s+|đang\s+)?lưu\s+(?:thông\s+tin\s+)?gì\s+về\s+(?:tôi|mình)'
    r'|bạn\s+(?:đã\s+|đang\s+)?nhớ\s+(?:những\s+)?gì\s+về\s+(?:tôi|mình)'
    r'|hồ\s+sơ\s+(?:của\s+)?(?:tôi|mình)\s+có\s+gì'
    r')\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7F: skill/ability query — "tôi biết làm gì?", "tôi biết gì?", "tôi có kỹ năng gì?"
# P0-7K-FIX4 B: aliases "bạn biết/nhớ tôi biết (làm) gì?" (no trailing "không" required).
_RE_SKILL_Q = re.compile(
    (
        r'^(?:'
        r'(?:tôi|mình)\s+biết\s+(?:làm\s+)?gì'
        r'|(?:tôi|mình)\s+có\s+(?:những\s+)?kỹ\s+năng\s+gì'
        r'|bạn\s+(?:có\s+)?(?:biết|nhớ)\s+(?:tôi|mình)\s+biết\s+(?:làm\s+)?g[ìi]'
        r'(?:\s+(?:không|ko|hông|hong))?'
        + r'|' + _remember_wrapper(r'kỹ\s+năng\s+(?:của\s+)?(?:tôi|mình)')
        + r'|' + _remember_wrapper(r'(?:tôi|mình)\s+biết\s+(?:làm\s+)?gì')
        + r')\s*[?？]?\s*$'
    ),
    re.IGNORECASE,
)

# "Bắc là ai?" — inverse lookup; subject must NOT be self-word
_RE_INVERSE_Q = re.compile(
    r'^([^\s.!?,]+)\s+là\s+ai\s*[?？]?\s*$',
    re.IGNORECASE,
)
_SELF_WORDS = frozenset({"tôi", "mình", "bạn", "tao", "ta"})

# P0-7D query patterns
_RE_OCCUPATION_Q = re.compile(
    (
        r'^(?:'
        r'(?:tôi|mình)\s+làm\s+gì'
        r'|(?:tôi|mình)\s+làm\s+nghề\s+gì'
        r'|nghề\s+(?:của\s+)?(?:tôi|mình)\s+là\s+gì'
        r'|công\s+việc\s+(?:của\s+)?(?:tôi|mình)\s+là\s+gì'
        r'|vai\s+trò\s+(?:của\s+)?(?:tôi|mình)\s+là\s+gì'
        + r'|' + _remember_wrapper(r'công\s+việc\s+(?:của\s+)?(?:tôi|mình)')
        + r'|' + _remember_wrapper(r'(?:tôi|mình)\s+làm\s+gì')
        + r')\s*[?？]?\s*$'
    ),
    re.IGNORECASE,
)
_RE_PREFERENCE_Q = re.compile(
    r'^(?:'
    r'(?:tôi|mình)\s+thích\s+gì'
    r'|sở\s+thích\s+(?:của\s+)?(?:tôi|mình)\s+là\s+gì'
    r'|(?:tôi|mình)\s+quan\s+tâm\s+đến\s+gì'
    r')\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7G-FIX3 A3: negative-preference query — "tôi không thích gì?", "tôi ghét gì?".
# Distinct from the positive preference query (no "không"/"ghét" there); lists dislikes.
_RE_NEGATIVE_PREF_Q = re.compile(
    r'^(?:'
    r'(?:tôi|mình)\s+không\s+thích\s+(?:cái\s+|thứ\s+|những\s+)?gì'
    r'|(?:tôi|mình)\s+ghét\s+(?:cái\s+|thứ\s+|những\s+)?gì'
    r')\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7F-FIX2/FIX3: "tôi thích ai?" — affection query (who do I like?).
# P0-7F-FIX3 Part B: "ai" is matched case-sensitively via a scoped no-ignorecase group
# so the lowercase question word "ai" routes here, while the uppercase technology token
# "AI" ("tôi thích AI") does NOT — it falls through to a professional-interest write.
# P0-7J: thích/yêu/quan tâm/crush are one affection domain — all query the same lane;
# optional "đang" covers "tôi đang crush ai?".
_RE_AFFECTION_Q = re.compile(
    r'^(?:tôi|mình)\s+(?:đang\s+)?'
    r'(?:thích|yêu|crush|quan\s+tâm(?:\s+(?:đến|tới))?)\s+(?-i:ai)\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7F-FIX3 Part D: third-party mind-state ("quý có thích tôi không?"). Subject (group 1)
# is any non-self token; runtime returns a deterministic "cannot know" response, never a save.
_RE_THIRD_PARTY_AFFECTION_Q = re.compile(
    r'^(\S+)\s+có\s+(?:thích|yêu|quý|thương)\s+(?:tôi|mình)\s+'
    r'(?:không|ko|hông|hong)\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7F-FIX2: "tôi thích uống gì?" / "tôi thích ăn gì?" — food/drink preference query
_RE_DRINK_PREF_Q = re.compile(
    r'^(?:tôi|mình)\s+thích\s+(?:uống|ăn)\s+gì\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7F-FIX4 Part C: friend-name query — "bạn (của) tôi tên là gì?". Must be checked BEFORE
# the self-name query, whose unanchored search would otherwise match the "tôi tên là gì"
# substring and wrongly answer with the USER's own name. Bare "bạn tên là gì?" (about the
# assistant) is intentionally NOT matched — it requires an explicit "tôi/mình" possessor.
_RE_FRIEND_NAME_Q = re.compile(
    (
        r'^(?:'
        r'bạn\s+(?:của\s+)?(?:tôi|mình)\s+tên\s+(?:là\s+)?g[ìi]'
        + r'|' + _remember_wrapper(
            r'bạn\s+(?:của\s+)?(?:tôi|mình)\s+tên\s+(?:là\s+)?g[ìi]'
        )
        + r')\s*[?？]?\s*$'
    ),
    re.IGNORECASE,
)
# P0-7F-FIX4 Part D: household-pet query — "nhà tôi nuôi con gì?".
_RE_PET_Q = re.compile(
    (
        r'^(?:'
        r'(?:nhà\s+)?(?:tôi|mình)\s+nuôi\s+(?:con\s+)?gì'
        + r'|' + _remember_wrapper(r'(?:nhà\s+)?(?:tôi|mình)\s+nuôi\s+(?:con\s+)?gì')
        + r')\s*[?？]?\s*$'
    ),
    re.IGNORECASE,
)
# P0-7F-FIX5 Part C: household-pet yes/no query — "tôi có nuôi mèo không?",
# "nhà tôi có nuôi chó không?". Animal is group(1); answered against stored pets. Checked
# before the household-pet WRITE pattern (which would otherwise capture "mèo không").
_RE_PET_YESNO_Q = re.compile(
    r'^(?:nhà\s+)?(?:tôi|mình)\s+có\s+nuôi\s+(?:con\s+)?(.+?)\s+(?:không|ko)\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7F-FIX5 Part D: affection-query alias — "người tôi thích là ai?",
# "người mình thích tên là ai?". Routes to the same self_affection lane as "tôi thích ai?".
_RE_AFFECTION_ALIAS_Q = re.compile(
    r'^người\s+(?:mà\s+)?(?:tôi|mình)\s+thích\s+(?:tên\s+)?là\s+ai\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7G: named affection yes/no — "Bắc có thích Quý không?", "Quý có thích Bắc không?".
# Both subject (group 1) and object (group 2) are non-self name tokens; the runtime maps
# whichever equals the saved self-name to the current user and answers from affection /
# external-affection memory. Checked AFTER _RE_THIRD_PARTY_AFFECTION_Q (which owns the
# "... có thích tôi/mình không?" form), so the object here is never a bare self-word.
# P0-7G-FIX4: subject uses .+? (non-greedy) to capture multi-word names ("Bắc Trần");
# single-word names still captured correctly because .+? stops at the first " có ".
# P0-7G-FIX4A: object also uses .+? so "Quý có thích Bắc Trần không?" is captured;
# non-greedy stops at the first " không/ko/..." terminal.
_RE_NAMED_AFFECTION_YESNO_Q = re.compile(
    r'^(.+?)\s+có\s+(?:thích|yêu|thương|quý)\s+(.+?)\s+'
    r'(?:không|ko|hông|hong|chưa)\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7G: reverse entity lookup — "ai là Quý?" (the mirror of "Quý là ai?").
_RE_REVERSE_ENTITY_Q = re.compile(
    r'^ai\s+là\s+([^\s?？]+)\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7K-FIX5C-LITE A: incoming-affection set query ("ai đang thích tôi?"). "tích" is a
# light typo of "thích" accepted only in this affection-query context. Lists the active
# person -> USER edges.
_RE_INCOMING_AFFECTION_SET_Q = re.compile(
    r'^ai\s+(?:đang\s+)?(?:thích|tích)\s+(?:tôi|mình)\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7K-FIX5C-LITE F: person-relation target query ("May thích ai?"). Subject (group 1) is
# a non-self token; answered from the person -> USER edge (the only person-object relation
# this lite core stores). Object facts ("May thích ăn kem") are out of scope.
_RE_PERSON_AFFECTION_TARGET_Q = re.compile(
    r'^(\S+(?:\s+\S+)?)\s+(?:đang\s+)?(?:thích|tích|yêu|thương|quý)\s+ai\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7K-FIX5C-LITE B: batch third-party relation query ("Quý và May có thích tôi không?").
# Subjects (group 1) split on "và"/","; object (group 2) is resolved to USER at answer time.
_RE_BATCH_INCOMING_AFFECTION_Q = re.compile(
    r'^(.+?(?:\s*,\s*|\s+và\s+).+?)\s+có\s+(?:thích|tích|yêu|thương|quý)\s+'
    r'(\S+(?:\s+\S+)?)\s+(?:không|ko|hông|hong|chưa)\s*[?？]?\s*$',
    re.IGNORECASE,
)


def _split_person_subjects(phrase: str) -> list[str]:
    """Split "Quý, May và Linh" into ["Quý", "May", "Linh"] (no empty tokens)."""
    parts = re.split(r'\s*,\s*|\s+và\s+', phrase.strip())
    return [p.strip() for p in parts if p.strip()]

# P0-7F-FIX2/FIX3: values that leaked into the preference store before the write guards
# were in place. Filtered at read time (never deleted from durable store).
_POLLUTED_PREFERENCE_VALUES: frozenset[str] = frozenset({
    "ai", "gì", "gi", "uống gì", "uong gi", "ăn gì", "an gi",
})
# P0-7F-FIX3 Part G: interrogative-phrase suffixes and yes/no question particles that make
# a stored preference value obviously polluted ("uống gì", "cafe không"). A trailing
# " đường" (as in "cafe không đường") is NOT a particle, so valid values survive.
_POLLUTED_INTERROGATIVE_ENDINGS: tuple[str, ...] = (
    " gì", " gi", " đâu", " nào",
)
_POLLUTED_YESNO_ENDINGS: tuple[str, ...] = (
    " đúng không", " phải không", " không", " chưa", " à", " hả", " nhỉ",
)
# Affection-explanation fragments that indicate a person-affection sentence was mis-saved
# as an ordinary preference.
_POLLUTED_AFFECTION_MARKERS: tuple[str, ...] = (
    "có nghĩa là tôi thích", "nghĩa là tôi thích",
    "tôi thích đơn phương", "đơn phương", "chưa là người yêu",
)
_RE_LEARNING_Q = re.compile(
    r'^(?:tôi|mình)\s+(?:đang\s+)?học\s+gì\s*[?？]?\s*$',
    re.IGNORECASE,
)
_RE_GOAL_Q = re.compile(
    r'^(?:mục\s+tiêu|goal)\s+(?:của\s+)?(?:tôi|mình)\s+là\s+gì\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7E habit query: "tôi hay làm gì?", "thói quen của tôi là gì?"
_RE_HABIT_Q = re.compile(
    r'^(?:'
    r'(?:tôi|mình)\s+hay\s+làm\s+gì'
    r'|thói\s+quen\s+(?:của\s+)?(?:tôi|mình)\s+là\s+gì'
    r')\s*[?？]?\s*$',
    re.IGNORECASE,
)
# Relation existence query: "tôi có người yêu chưa?" — captures relation label in group 1
_RE_RELATION_EXIST_Q = re.compile(
    r'^(?:tôi|mình)\s+có\s+(người\s+yêu|bạn\s+gái|bạn\s+trai|vợ|chồng|partner)\s+chưa\s*[?？]?\s*$',
    re.IGNORECASE,
)

# --- Confirmation / cancel ---

PROFILE_CONFIRM = re.compile(
    r'^(?:có|ok|okay|đúng|đúng\s+rồi|lưu\s+đi|đồng\s+ý|yes|save\s+it)\s*[.!?]*\s*$',
    re.IGNORECASE,
)
PROFILE_CANCEL = re.compile(
    r'^(?:không|hủy|bỏ\s+qua|thôi|cancel|no)\s*[.!?]*\s*$',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _is_proper_name(s: str) -> bool:
    """True if s looks like a proper noun (first char uppercase in Unicode)."""
    return bool(s) and s[0].isupper()


def _is_name_like_token(value: str) -> bool:
    """True if value is a plausible person-name token, regardless of case (P0-7F-FIX3 Part E).

    Accepts single short alphabetic tokens ("Bắc", "bắc", "Nam"); rejects question words,
    role/occupation/technology keywords ("developer", "AI", "ml"), digits, and multi-word or
    over-long phrases. This lets "tôi là bắc" save a lowercase name while "tôi là developer"
    / "tôi là AI engineer" stay out of the name path.
    """
    v = value.strip()
    if not v or " " in v:
        return False
    if any(ch.isdigit() for ch in v):
        return False
    if len(v) < 2 or len(v) > 15:
        return False
    if v.lower() in _QUESTION_WORDS:
        return False
    if _has_role_keyword(v):
        return False
    return v.replace("-", "").isalpha()


def _normalize_relation_label(raw: str) -> str:
    return re.sub(r'\s+', ' ', raw.strip().lower())


def _extract_query_relation_label(text: str) -> str:
    m = re.search(_RELATIONS_QUERY_PATTERN, text, re.IGNORECASE)
    return _normalize_relation_label(m.group(1)) if m else ""


def _is_polluted_preference(val: str) -> bool:
    """True if val is an obviously polluted preference value (read-time hygiene, P0-7F-FIX3).

    Covers bare interrogative words, interrogative-phrase / yes-no question suffixes, and
    affection-explanation fragments. Valid values ("cafe", "cafe không đường", "build AI",
    "đi du lịch") are preserved.
    """
    raw = re.sub(r"\s+", " ", val.strip())
    v = raw.lower()
    if not v:
        return True
    # "ai" is case-ambiguous: bare lowercase "ai" is the question word (polluted), while
    # "AI"/"Ai" is the technology token (valid). Other bare interrogatives are unambiguous.
    if raw == "ai":
        return True
    if v in (_POLLUTED_PREFERENCE_VALUES - {"ai"}):
        return True
    if any(v.endswith(end) for end in _POLLUTED_INTERROGATIVE_ENDINGS):
        return True
    if any(v.endswith(end) for end in _POLLUTED_YESNO_ENDINGS):
        return True
    if any(marker in v for marker in _POLLUTED_AFFECTION_MARKERS):
        return True
    return False


# ---------------------------------------------------------------------------
# Detection — confirmation-gated candidates
# ---------------------------------------------------------------------------

def detect_profile_fact_candidate(text: str) -> ProfileFactCandidate | None:
    """Return a ProfileFactCandidate if text is an explicit profile assertion, else None."""
    stripped = text.strip()

    # Reject if it looks like a question overall
    bare = stripped.rstrip('.!? ')
    if bare.endswith('?'):
        return None

    # Self-name — unambiguous ("tên" keyword present)
    for pattern in (_RE_SELF_TEN_LA, _RE_TEN_TOI_LA, _RE_LUU_TEN_LA):
        m = pattern.match(stripped)
        if m:
            value = m.group(1).rstrip('.!?').strip()
            if value and value.lower() not in _QUESTION_WORDS:
                return ProfileFactCandidate(
                    subject="self", relation="name",
                    value=value, original_text=stripped,
                )

    # Self-is — single token that looks like a person name. P0-7F-FIX3 Part E accepts
    # lowercase names ("tôi là bắc") while still excluding role/technology/demographic tokens.
    m = _RE_SELF_IS.match(stripped)
    if m:
        value = m.group(1).rstrip('.!?').strip()
        if value and _is_name_like_token(value) and value.lower() not in _QUESTION_WORDS:
            return ProfileFactCandidate(
                subject="self", relation="name",
                value=value, original_text=stripped,
            )

    # Relation-name — storage labels only
    m = _RE_RELATION_NAME.match(stripped)
    if m:
        raw_label = m.group(1).strip()
        value = m.group(2).rstrip('.!?').strip()
        label = _normalize_relation_label(raw_label)
        if value and value.lower() not in _QUESTION_WORDS:
            return ProfileFactCandidate(
                subject="relation", relation="name",
                value=value, relation_label=label, original_text=stripped,
            )

    # P0-7D: "người yêu của tôi tên là Quý" / "partner của tôi là Quý" — confirm-gated
    m = _RE_NGUOI_YEU_PARTNER_NAME.match(stripped)
    if m:
        raw_label = stripped.split()[0].lower()  # "người" or "partner"
        # Normalize multi-word "người yêu"
        if stripped.lower().startswith("người yêu"):
            raw_label = "người yêu"
        elif stripped.lower().startswith("partner"):
            raw_label = "partner"
        value = m.group(1).rstrip('.!?').strip()
        if value and value.lower() not in _QUESTION_WORDS:
            return ProfileFactCandidate(
                subject="relation", relation="name",
                value=value, relation_label=raw_label, original_text=stripped,
            )

    return None


def _is_self_name_phrase(value: str) -> bool:
    """True if value is a plausible 1–3 word person-name phrase (P0-7G name update).

    Accepts "Bắc", "Bắc Trần", "bb"; rejects occupations ("AI engineer" — role keyword),
    question words, digits, and common descriptor words ("người tốt"). Used only for the
    name-update path, so it is intentionally stricter than a general name check.
    """
    v = re.sub(r"\s+", " ", value.strip().rstrip(".!?？ ")).strip()
    if not v:
        return False
    tokens = v.split()
    if not (1 <= len(tokens) <= 3):
        return False
    if _has_role_keyword(v):
        return False
    for t in tokens:
        low = t.lower()
        if low in _QUESTION_WORDS or low in _NON_NAME_WORDS:
            return False
        if any(ch.isdigit() for ch in t):
            return False
        if len(t) > 15 or not t.replace("-", "").isalpha():
            return False
    return True


def detect_self_name_update(text: str) -> str | None:
    """Return the new name for an explicit self-name update command, else None.

    Handles "sửa/đổi/cập nhật tên (của) tôi thành/là X". Does NOT handle the implicit
    "tôi là X" full-name form — that is decided in the runtime, which knows whether a name
    already exists (a first-time "tôi là X" is a fresh save, not an update).
    """
    stripped = text.strip()
    for pat in (_RE_NAME_UPDATE_CMD, _RE_NAME_NEW_IS, _RE_NAME_WANT_CHANGE):
        m = pat.match(stripped)
        if m is None:
            continue
        value = _clean_query_value(m.group(1))
        if not value or not _is_self_name_phrase(value):
            return None
        if _is_unsafe_or_sensitive_auto_value(value):
            return None
        return value
    return None


def detect_self_name_phrase_update(text: str) -> str | None:
    """Return the name for an implicit full-name self assertion ("tôi là Bắc Trần").

    Returns the captured phrase only when it is a clean self-name phrase (not an
    occupation). The caller applies this as an UPDATE only when a name already exists.
    """
    m = _RE_SELF_IS_PHRASE.match(text.strip())
    if m is None:
        return None
    value = _clean_query_value(m.group(1))
    if not value or not _is_self_name_phrase(value):
        return None
    if _is_unsafe_or_sensitive_auto_value(value):
        return None
    return value


# P0-7K-HOTFIX1 A: natural name assertion with the "tên" keyword (always an update).
# Covers a leading temporal marker, an inline "bây giờ", and a trailing "mới đúng".
_RE_NAME_TEN_ASSERT = re.compile(
    r'^(?:(?:bây\s+giờ|hiện\s+tại|từ\s+nay|giờ)\s*,?\s+)?'
    r'(?:tôi|mình)\s+tên\s+(?:bây\s+giờ\s+)?(?:là\s+)?(.+?)'
    r'(?:\s+mới\s+đúng)?\s*[.!?]*\s*$',
    re.IGNORECASE,
)
_RE_TEN_TOI_ASSERT = re.compile(
    r'^(?:(?:bây\s+giờ|hiện\s+tại|từ\s+nay|giờ)\s*,?\s+)?'
    r'tên\s+(?:tôi|mình)\s+(?:bây\s+giờ\s+)?(?:là\s+)?(.+?)'
    r'(?:\s+mới\s+đúng)?\s*[.!?]*\s*$',
    re.IGNORECASE,
)


def detect_self_name_ten_assertion(text: str) -> str | None:
    """Return the asserted name for a natural "tên" self-name assertion, else None.

    "bây giờ tôi tên là BB", "tên tôi là BB", "tôi tên là BB mới đúng" → "BB". The "tên"
    keyword makes this an explicit name assertion, so the caller always applies it as an
    update (no "sửa tên tôi thành X" required). Role/occupation-shaped values are rejected
    by ``_is_self_name_phrase``, so "tôi là DEV" never reaches here (no "tên" keyword).
    """
    stripped = text.strip()
    for pat in (_RE_NAME_TEN_ASSERT, _RE_TEN_TOI_ASSERT):
        m = pat.match(stripped)
        if m is None:
            continue
        value = _clean_query_value(m.group(1))
        if not value or not _is_self_name_phrase(value):
            return None
        if _is_unsafe_or_sensitive_auto_value(value):
            return None
        return value
    return None


def _clean_query_value(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.strip().rstrip(".!?？ ")).strip()


def looks_like_proper_full_name(phrase: str) -> bool:
    """True if phrase is a multi-word Title-Case person name ("Bắc Trần").

    P0-7G-FIX3 A2: used to accept a first-time multi-word "tôi là <full name>" as a name
    save while rejecting lowercase common-word phrases ("trai làng", "con trai") that pass
    the looser single-token name check. Proper Vietnamese names are conventionally
    capitalized, so Title Case is a deterministic disambiguator for the first-time case.
    """
    tokens = phrase.split()
    if len(tokens) < 2:
        return False
    if not _is_self_name_phrase(phrase):
        return False
    return all(tok[:1].isupper() for tok in tokens)


# ---------------------------------------------------------------------------
# Detection — queries
# ---------------------------------------------------------------------------

def detect_profile_query(text: str) -> ProfileQuery | None:
    """Return a ProfileQuery if text is a profile question, else None.

    Priority order (P0-7D):
    1.  Relation name "tên gì?" — anchored, extended with synonyms
    2.  Relation "là ai?" — P0-7C, anchored
    3.  Profile summary — P0-7C
    4.  Self-name — unanchored
    5.  Self-identity — P0-7C FIX: fully anchored
    6.  Occupation query — P0-7D
    7.  Preference query — P0-7D
    8.  Learning focus query — P0-7D
    9.  Goal query — P0-7D
    10. Relation existence query — P0-7D
    11. Inverse value lookup
    """
    stripped = text.strip()

    # 0. P0-7K-FIX5C-LITE A: incoming-affection set query ("ai đang thích tôi?").
    if _RE_INCOMING_AFFECTION_SET_Q.match(stripped):
        return ProfileQuery(kind="incoming_affection_set")

    # 0.02. P0-7K-FIX5C-LITE B: batch third-party relation query ("Quý và May có thích
    #       tôi không?"). Multi-subject; object resolved to USER at answer time. Checked
    #       before the single-subject third-party and named-affection forms.
    m = _RE_BATCH_INCOMING_AFFECTION_Q.match(stripped)
    if m:
        subjects_raw = m.group(1).strip()
        obj = m.group(2).strip().rstrip('?')
        if len(_split_person_subjects(subjects_raw)) >= 2:
            return ProfileQuery(
                kind="batch_incoming_affection", value=subjects_raw, object_value=obj
            )

    # 0.03. P0-7K-FIX5C-LITE F: person-relation target query ("May thích ai?"). A self-word
    # subject (incl. "tôi đang") is left to the self-affection lane ("tôi đang thích ai?").
    m = _RE_PERSON_AFFECTION_TARGET_Q.match(stripped)
    if m:
        subject = m.group(1).strip().rstrip('?')
        first_token = subject.lower().split()[0] if subject.split() else ""
        if subject.lower() not in _SELF_WORDS and first_token not in _SELF_WORDS:
            return ProfileQuery(kind="person_affection_target", value=subject)

    # 0. P0-7F-FIX3 Part D: third-party mind-state ("quý có thích tôi không?").
    #    Subject must not be a self-word (that would be a yes/no self-preference query).
    m = _RE_THIRD_PARTY_AFFECTION_Q.match(stripped)
    if m:
        subject = m.group(1).strip().rstrip('?')
        if subject.lower() not in _SELF_WORDS:
            return ProfileQuery(kind="third_party_affection", value=subject)

    # 0.1. P0-7G: named affection yes/no ("Bắc có thích Quý không?"). Both sides are
    #      non-self tokens; runtime resolves the saved self-name. Checked after the
    #      third-party form above so "... có thích tôi không?" keeps its own lane.
    m = _RE_NAMED_AFFECTION_YESNO_Q.match(stripped)
    if m:
        subj = m.group(1).strip().rstrip('?')
        obj = m.group(2).strip().rstrip('?')
        if subj.lower() not in _SELF_WORDS and obj.lower() not in _SELF_WORDS:
            return ProfileQuery(kind="named_affection_yesno", value=subj, object_value=obj)

    # 0.5. P0-7F-FIX4 Part C: friend-name query ("bạn của tôi tên là gì?"). Before the
    #      self-name query so it never resolves to the user's own name.
    if _RE_FRIEND_NAME_Q.match(stripped):
        return ProfileQuery(kind="friend_name", relation_label="bạn")

    # 0.6. P0-7F-FIX4 Part D: household-pet query ("nhà tôi nuôi con gì?").
    if _RE_PET_Q.match(stripped):
        return ProfileQuery(kind="self_pet")

    # 0.7. P0-7F-FIX5 Part C: household-pet yes/no query ("tôi có nuôi mèo không?").
    #      Before the semantic household-pet WRITE (priority 4.5) reads it as a fact.
    m = _RE_PET_YESNO_Q.match(stripped)
    if m:
        animal = re.sub(r"\s+", " ", m.group(1).strip().rstrip(".!?？ ")).strip()
        if animal:
            return ProfileQuery(kind="self_pet_yesno", value=animal)

    # 0.8. P0-7H: relation yes/no ("Quý có phải là bạn gái của tôi không?").
    m = _RE_RELATION_YESNO_Q.match(stripped)
    if m:
        person = re.sub(r"\s+", " ", m.group(1).strip().rstrip("?")).strip()
        label = _normalize_relation_label(m.group(2))
        if person:
            return ProfileQuery(kind="relation_yesno", value=person, relation_label=label)

    # 0.9. P0-7J: old-name confirmation ("Bắc là tên cũ của tôi, bạn còn nhớ không?").
    m = _RE_OLD_NAME_CONFIRM_Q.match(stripped)
    if m:
        name = re.sub(r"\s+", " ", m.group(1).strip()).strip()
        if name and _is_self_name_phrase(name):
            return ProfileQuery(kind="old_name_confirm", value=name)

    # 1. Relation name "tên gì?" form
    m = _RE_RELATION_NAME_Q.match(stripped)
    if m:
        label = _extract_query_relation_label(stripped)
        return ProfileQuery(kind="relation_name", relation_label=label)

    # 2. P0-7C: relation "là ai?" form
    m = _RE_RELATION_LA_AI_Q.match(stripped)
    if m:
        label = _extract_query_relation_label(stripped)
        return ProfileQuery(kind="relation_name", relation_label=label)

    # 3. P0-7C: profile summary
    if _RE_PROFILE_SUMMARY_Q.match(stripped):
        return ProfileQuery(kind="profile_summary")

    # 4. Self-name (unanchored)
    if _RE_SELF_NAME_Q.search(stripped) or _RE_SELF_NAME_REMEMBER_Q.match(stripped):
        return ProfileQuery(kind="self_name")

    # 5. Self-identity — P0-7C FIX: fully anchored
    if _RE_SELF_IDENTITY_Q.match(stripped):
        return ProfileQuery(kind="self_identity")

    # 6. P0-7D: occupation query
    if _RE_OCCUPATION_Q.match(stripped):
        return ProfileQuery(kind="self_occupation")

    # 6b. P0-7I: self occupation yes/no ("tôi có phải là AI không?")
    m = _RE_SELF_OCC_YESNO_Q.match(stripped)
    if m:
        value = re.sub(r"\s+", " ", m.group(1).strip().rstrip("?？")).strip()
        if value:
            return ProfileQuery(kind="self_occupation_yesno", value=value)

    # 6c'. P0-7K-FIX1 E: self AI-domain yes/no ("tôi có làm AI không?") — before the
    #      generic do/yes-no so "AI" is answered via the taxonomy, not literal token match.
    if _RE_SELF_AI_YESNO_Q.match(stripped):
        return ProfileQuery(kind="self_ai_yesno", value="AI")

    # 6c. P0-7J-FIX1: self do/goal yes-no ("tôi có làm LLM nữa không?").
    m = _RE_SELF_DO_YESNO_Q.match(stripped)
    if m:
        value = re.sub(r"\s+", " ", m.group(1).strip().rstrip("?？")).strip()
        if value:
            return ProfileQuery(kind="self_do_yesno", value=value)

    # 6d. P0-7K-FIX1 G: memory-challenge / reminder ("bạn không nhớ tôi sẽ làm X à?").
    m = _RE_GOAL_CHALLENGE_Q.match(stripped)
    if m:
        value = re.sub(r"\s+", " ", m.group(1).strip().rstrip("?？àưhả ")).strip()
        if value:
            return ProfileQuery(kind="goal_challenge", value=value)

    # 6e. P0-7K-FIX1 H: goal follow-up ("và gì nữa?"). Runtime gates this on a recent
    #     goal query so it only fires as an immediate follow-up.
    if _RE_GOAL_FOLLOWUP_Q.match(stripped):
        return ProfileQuery(kind="goal_followup")

    # 6f. P0-7K-FIX2 C: comparative query ("tôi thích A hay B hơn?") — most specific
    #     "thích ... hơn" form; before affection/ranking/preference lanes.
    m = _RE_COMPARATIVE_Q.match(stripped)
    if m:
        a = re.sub(r"\s+", " ", m.group(1).strip().rstrip("?？")).strip()
        b = re.sub(r"\s+", " ", m.group(2).strip().rstrip("?？")).strip()
        if a and b:
            return ProfileQuery(kind="self_comparative", value=a, object_value=b)

    # 6g. P0-7K-FIX2 A/B: food-favorite / food-ranking query ("tôi thích ăn gì nhất").
    if _RE_FOOD_FAVORITE_Q.match(stripped):
        return ProfileQuery(kind="self_food_favorite")

    # 6h. P0-7K-FIX2 H: food-specific negative query ("tôi không thích ăn gì?") — before
    #     the general negative-preference query so it is not read as "không thích gì".
    if _RE_FOOD_NEG_Q.match(stripped):
        return ProfileQuery(kind="self_food_dislike")

    # 7. P0-7F-FIX2: affection query ("tôi thích ai?") — before general preference query.
    #    P0-7F-FIX5 Part D adds the "người tôi thích là ai?" alias to the same lane.
    if _RE_AFFECTION_Q.match(stripped) or _RE_AFFECTION_ALIAS_Q.match(stripped):
        return ProfileQuery(kind="self_affection")

    # 7a. P0-7K-FIX2 H: food-specific positive query ("tôi thích ăn gì?"). Answers only
    #     food preferences + a food favorite (drink query stays "tôi thích uống gì?").
    if _RE_FOOD_POS_Q.match(stripped):
        return ProfileQuery(kind="self_food_preference")

    # 7b. P0-7F-FIX2: drink/food preference query ("tôi thích uống gì?")
    if _RE_DRINK_PREF_Q.match(stripped):
        return ProfileQuery(kind="self_drink_preference")

    # 7b0. P0-7K-FIX1 J: preference ranking query ("tôi thích gì nhất", "tôi thích gì nhata")
    #      — checked before the plain "tôi thích gì" preference query; answered safely, and
    #      critically prevents "gì nhất"/"gì nhata" from being written as a preference.
    if _RE_PREF_RANKING_Q.match(stripped):
        return ProfileQuery(kind="self_preference_ranking")

    # 7b'. P0-7G-FIX3: negative-preference query ("tôi không thích gì?") — before the
    #      positive preference query so "không thích gì" is never read as "thích gì".
    if _RE_NEGATIVE_PREF_Q.match(stripped):
        return ProfileQuery(kind="self_dislike")

    # 7c. P0-7D: preference query
    if _RE_PREFERENCE_Q.match(stripped):
        return ProfileQuery(kind="self_preference")

    # 8. P0-7D: learning focus query
    if _RE_LEARNING_Q.match(stripped):
        return ProfileQuery(kind="self_learning_focus")

    # 8b. P0-7K-FIX6-LITE: action-specific "muốn <action> <pronoun>" queries. Before the
    #     general "muốn làm/build gì?" so marry/learn/build stay distinct (marry is not a
    #     general work goal; build filters build goals; learn filters learn goals).
    if _RE_WANTS_MARRY_Q.match(stripped):
        return ProfileQuery(kind="wants_to_marry_query")
    if _RE_WANTS_LEARN_Q.match(stripped):
        return ProfileQuery(kind="wants_to_learn_query")
    if _RE_WANTS_BUILD_Q.match(stripped):
        return ProfileQuery(kind="wants_to_build_query")

    # 8c. P0-7J: current goal/intention query ("tôi đang muốn làm gì?") — before the
    #     legacy goal query; answers with the LATEST goal (current-state semantics).
    if _RE_CURRENT_GOAL_Q.match(stripped):
        return ProfileQuery(kind="self_current_goal")

    # 9. P0-7D: goal query
    if _RE_GOAL_Q.match(stripped):
        return ProfileQuery(kind="self_goal")

    # 9b. P0-7E: habit query
    if _RE_HABIT_Q.match(stripped):
        return ProfileQuery(kind="self_habit")

    # 9c'. P0-7K-FIX2 E: negative-skill list query ("tôi không biết gì?") — before the
    #      positive skill query so "không biết gì" is never read as "biết gì".
    if _RE_NEGATIVE_SKILL_Q.match(stripped):
        return ProfileQuery(kind="self_negative_skill")

    # 9c. P0-7F: skill query
    if _RE_SKILL_Q.match(stripped):
        return ProfileQuery(kind="self_skill")

    # 10. P0-7D: relation existence query
    m = _RE_RELATION_EXIST_Q.match(stripped)
    if m:
        label = _normalize_relation_label(m.group(1))
        return ProfileQuery(kind="relation_existence", relation_label=label)

    # 11. Inverse lookup: "Bắc là ai?" — exclude self-words as subject
    m = _RE_INVERSE_Q.match(stripped)
    if m:
        subject_word = m.group(1).strip().lower().rstrip('?')
        if subject_word not in _SELF_WORDS:
            return ProfileQuery(kind="inverse_value", value=m.group(1).strip().rstrip('?'))

    # 12. P0-7G: reverse entity lookup "ai là Quý?" — mirror of "Quý là ai?".
    m = _RE_REVERSE_ENTITY_Q.match(stripped)
    if m:
        subject_word = m.group(1).strip().rstrip('?')
        if subject_word.lower() not in _SELF_WORDS:
            return ProfileQuery(kind="reverse_entity", value=subject_word)

    return None


# ---------------------------------------------------------------------------
# Detection — AUTO_SAFE extraction
# ---------------------------------------------------------------------------

def _match_auto_pattern(stripped: str) -> tuple[str, str] | None:
    """Return (relation, value) if text matches an AUTO_SAFE pattern with valid SHAPE.

    Applies the extraction regexes and shape validity (length/vagueness) plus the
    occupation-specific multi-word + role-keyword guard, but NOT the unsafe/sensitive
    guard — callers decide save-vs-block based on ``_is_unsafe_or_sensitive_auto_value``.
    Never matches questions or note/command/correction prefixes.
    """
    if '?' in stripped or '？' in stripped:
        return None
    if not _is_safe_for_auto_save(stripped):
        return None

    # --- Goal (checked first: unambiguous keyword "mục tiêu"/"goal") ---
    m = _RE_GOAL.match(stripped)
    if m:
        value = m.group(1).strip().rstrip('.!')
        if _is_valid_auto_value_shape(value):
            return ("goal", value)

    # --- Learning focus ---
    m = _RE_LEARNING.match(stripped)
    if m:
        value = m.group(1).strip().rstrip('.!')
        if _is_valid_auto_value_shape(value):
            return ("learning_focus", value)

    # --- Preference (explicit "thích"/"quan tâm đến"/"sở thích") ---
    for pat in (_RE_PREFERENCE_SO_THICH, _RE_PREFERENCE_QUAN_TAM, _RE_PREFERENCE_THICH):
        m = pat.match(stripped)
        if m:
            value = m.group(1).strip().rstrip('.!')
            # P0-7K-FIX2: the legacy auto-save path must also reject query phrases
            # ("ăn gì nhất") and ranking/comparative markers so they never leak into
            # ordinary preferences when the semantic layer declined the turn.
            if _is_valid_auto_value_shape(value) and not _value_has_query_word(value):
                return ("preference", value)

    # --- Habit / lifestyle ("tôi hay ...", "tôi thường ...") ---
    m = _RE_HABIT.match(stripped)
    if m:
        value = m.group(1).strip().rstrip('.!')
        if _is_valid_auto_value_shape(value):
            return ("habit", value)

    # --- Occupation (explicit context: "nghề/công việc/vai trò của tôi là") ---
    m = _RE_OCCUPATION_CONTEXT.match(stripped)
    if m:
        value = m.group(1).strip().rstrip('.!')
        if _is_valid_auto_value_shape(value):
            return ("occupation", value)

    # --- Occupation ("tôi làm VALUE") — P0-7F: require a role keyword so task/object
    # phrases ("tôi làm bài tập", "tôi làm việc này") no longer auto-save as occupation. ---
    m = _RE_OCCUPATION_TOI_LAM.match(stripped)
    if m:
        value = m.group(1).strip().rstrip('.!')
        if _is_valid_auto_value_shape(value) and _has_role_keyword(value):
            return ("occupation", value)

    # --- Occupation ("tôi là VALUE") — requires role keyword to avoid description clash ---
    m = _RE_OCCUPATION_TOI_LA.match(stripped)
    if m:
        value = m.group(1).strip().rstrip('.!')
        tokens = value.split()
        if (
            _is_valid_auto_value_shape(value)
            and _has_role_keyword(value)      # contains known role term
            # Multi-word ("AI engineer") OR a single whole-word role term ("developer").
            # A bare name ("Bắc") has no role keyword, so it never reaches here.
            and (len(tokens) >= 2 or tokens[0].lower() in _ROLE_KEYWORD_TOKENS)
        ):
            return ("occupation", value)

    return None


def detect_auto_profile_candidate(text: str) -> AutoProfileCandidate | None:
    """Return an AutoProfileCandidate for AUTO_SAFE extraction, or None.

    Never fires for questions, note/command/correction prefixes, vague values, or
    unsafe/sensitive values (those are surfaced by detect_blocked_auto_profile_value).
    """
    stripped = text.strip()
    match = _match_auto_pattern(stripped)
    if match is None:
        return None
    relation, value = match
    if _is_unsafe_or_sensitive_auto_value(value):
        return None
    return AutoProfileCandidate(
        subject="self", relation=relation, value=value, original_text=stripped,
    )


def detect_blocked_auto_profile_value(text: str) -> BlockedProfileAttempt | None:
    """Return a BlockedProfileAttempt if text is an auto-profile claim with an unsafe value.

    Fires only when the message matches an AUTO_SAFE pattern (so arbitrary unsupported
    sentences never trigger the safety response) AND the extracted value is unsafe/sensitive.
    """
    stripped = text.strip()
    match = _match_auto_pattern(stripped)
    if match is None:
        return None
    relation, value = match
    if not _is_unsafe_or_sensitive_auto_value(value):
        return None
    return BlockedProfileAttempt(relation=relation, value=value, original_text=stripped)


# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------

def build_confirmation_prompt(candidate: ProfileFactCandidate) -> str:
    if candidate.subject == "self":
        intro = "Tôi hiểu đây là thông tin về bạn"
        fact_desc = f"tên của bạn là {candidate.value}"
    else:
        intro = "Tôi hiểu đây là thông tin liên quan đến bạn"
        fact_desc = f"{candidate.relation_label} của bạn tên là {candidate.value}"
    return f'{intro}: "{fact_desc}". Bạn muốn tôi lưu không?'


def _preference_ack(value: str) -> str:
    """Natural preference ack with a light, non-overclaiming contextual note for a few
    common safe interests; generic otherwise. Rule-based, no advice engine."""
    value = canonicalize_known_preference_value(value)
    v = value.lower()
    base = f"Đã nhớ là bạn thích {value}."
    if "cafe" in v or "cà phê" in v:
        return (
            f"{base} Cà phê có thể giúp bạn tỉnh táo hơn khi học tập và làm việc, "
            "nhưng nên uống vừa phải, nhất là buổi chiều/tối."
        )
    if "phượt" in v:
        return (
            f"{base} Khi nói về lịch trình hoặc di chuyển xa, mình sẽ ưu tiên nhắc bạn "
            "chuẩn bị an toàn, thời tiết và thời gian nghỉ."
        )
    if "thể thao" in v or "the thao" in v:
        return (
            f"{base} Đây là thói quen tốt cho sức khỏe nếu duy trì đều và tránh tập quá sức."
        )
    return f"{base} Mình sẽ tính đến sở thích này khi gợi ý những việc liên quan."


def build_auto_ack_message(candidate: AutoProfileCandidate) -> str:
    """Natural, category-specific acknowledgement after an AUTO_SAFE save (P0-7E).

    Rule-based templates only. Always begins with "Đã nhớ" (never "Đã lưu vào hồ sơ")
    and never over-claims medical/legal advice.
    """
    rel = candidate.relation
    value = candidate.value
    if rel == "preference":
        return _preference_ack(value)
    if rel == "skill":
        return (
            f"Đã nhớ là bạn biết {value}. Mình sẽ tính đến kỹ năng này khi gợi ý "
            "những việc liên quan."
        )
    if rel == "occupation":
        return (
            f"Đã nhớ công việc/lĩnh vực của bạn là {value}. Thông tin này giúp mình ưu tiên "
            "ngữ cảnh kỹ thuật, AI agent, LLM và workflow build sản phẩm khi hỗ trợ bạn."
        )
    if rel == "learning_focus":
        return (
            f"Đã nhớ bạn đang học {value}. Mình có thể giải thích theo hướng thực hành "
            "hơn khi phù hợp."
        )
    if rel == "goal":
        return (
            f"Đã nhớ mục tiêu của bạn là {value}. Mình sẽ ưu tiên gợi ý gần với mục tiêu đó."
        )
    if rel == "habit":
        return (
            f"Đã nhớ là bạn hay {value}. Khi nói về phượt hoặc di chuyển xa, mình sẽ ưu "
            "tiên nhắc đến an toàn, đồ bảo hộ, thời tiết và lịch trình nghỉ ngơi."
        )
    if rel == "household_pet":
        return (
            f"Đã nhớ nhà bạn có nuôi một con {value}. Mình sẽ tính đến điều này khi trò "
            "chuyện về thú cưng hoặc lịch sinh hoạt của bạn."
        )
    return f"Đã nhớ {rel}: {value}."


def build_profile_fact_ack(candidate: ProfileFactCandidate) -> str:
    """Natural ack after a direct self.name / relation.name AUTO_SAFE save (P0-7E)."""
    if candidate.subject == "self":
        return f"Đã nhớ tên bạn là {candidate.value}."
    label = candidate.relation_label or "người thân"
    return f"Đã nhớ {label} của bạn tên là {candidate.value}."


def build_profile_conflict_message(
    candidate: ProfileFactCandidate, existing_value: str
) -> str:
    """Deterministic guidance when a name/relation claim conflicts with a stored value.

    P0-7E does not silently overwrite; correction/delete/update remains a future phase.
    """
    if candidate.subject == "self":
        if existing_value == candidate.value:
            return f"Mình vẫn đang nhớ tên bạn là {existing_value}."
        return (
            f"Mình đang nhớ tên bạn là {existing_value}. Nếu muốn đổi, hãy nói rõ, "
            f'ví dụ: "sửa tên tôi thành {candidate.value}".'
        )
    label = candidate.relation_label or "người thân"
    if existing_value == candidate.value:
        return f"Mình vẫn đang nhớ {label} của bạn tên là {existing_value}."
    return (
        f"Mình đang nhớ {label} của bạn tên là {existing_value}. Nếu muốn đổi, hãy nói rõ, "
        f'ví dụ: "sửa {label} của tôi thành {candidate.value}".'
    )


def build_blocked_value_response(attempt: BlockedProfileAttempt) -> str:
    """Deterministic safety response for an unsafe/sensitive blocked profile value (P0-7E).

    Names the value, states it will not be saved, and offers a safe reframing. Never gives
    operational/harmful guidance.
    """
    return (
        f"Tôi hiểu bạn đang nói về {attempt.value}, nhưng đây là nội dung nhạy cảm/có rủi ro "
        "nghiêm trọng về sức khỏe hoặc pháp lý. Tôi sẽ không lưu nó như một thông tin hồ sơ "
        "thông thường. Nếu bạn đang nói về chủ đề này trong ngữ cảnh nghiên cứu, viết nội "
        "dung, hoặc cần hỗ trợ an toàn, hãy nói rõ hơn."
    )


# ---------------------------------------------------------------------------
# P0-7F response builders
# ---------------------------------------------------------------------------

def build_person_affinity_response(value: str) -> str:
    """Person-affinity ("tôi thích Quý") is not a hobby — clarify, never save as preference."""
    return (
        f"Mình hiểu bạn đang nói về {value} như một người, nên mình sẽ không lưu đây là "
        "sở thích thông thường. Nếu " + value + " là người yêu/bạn gái/bạn trai của bạn, "
        f'hãy nói rõ, ví dụ: "người yêu của tôi là {value}".'
    )


def build_near_miss_response(value: str) -> str:
    """Short-term/ambiguous desire ("tôi muốn đi chơi") — offer to remember, do not save."""
    return (
        f"Mình hiểu đây có thể là mong muốn ngắn hạn ({value}). Bạn muốn mình lưu nó như một "
        "sở thích/kế hoạch lâu dài không, hay chỉ đang nói về hiện tại?"
    )


def build_followup_response(has_context: bool) -> str:
    """Answer for a "gì nữa?" follow-up after a profile query (session-local, no memory)."""
    if has_context:
        return "Hiện tại mình chỉ thấy các thông tin đó trong hồ sơ của bạn."
    return "Bạn muốn hỏi tiếp về thông tin nào trong hồ sơ của bạn?"


def build_negation_no_affection_response() -> str:
    """Response for "tôi không thích ai" — acknowledge negation, never save."""
    return (
        "Mình hiểu là hiện tại bạn không muốn lưu thông tin về người bạn thích. "
        "Mình sẽ không lưu gì từ câu này."
    )


def build_affection_explanation_response(value: str) -> str:
    """Response for an affection explanation ("tôi thích quý có nghĩa là ...") — never save.

    Acknowledges the affection context and offers the explicit relationship phrasing that
    WOULD be saved, without persisting the explanation as an ordinary preference (P0-7F-FIX3).
    """
    return (
        f"Mình hiểu bạn đang giải thích về tình cảm với {value}. Mình sẽ không lưu đây là "
        f'sở thích thông thường. Nếu bạn muốn lưu rõ quan hệ, hãy nói: "người yêu của tôi '
        f'là {value}" hoặc "bạn gái của tôi là {value}".'
    )


def build_affection_relation_response(value: str) -> str:
    """Response for an affection relation phrase ("tôi có tình cảm với X", "tôi crush X").

    Acknowledges the feeling, refuses to store it as an ordinary preference, and offers the
    explicit relationship phrasing that WOULD be saved (P0-7F-FIX4 Part A).
    """
    return (
        f"Mình hiểu bạn có tình cảm với {value}. Mình sẽ không lưu đây là sở thích thông "
        f'thường. Nếu bạn muốn lưu rõ quan hệ, hãy nói: "người yêu của tôi là {value}" '
        f'hoặc "bạn gái của tôi là {value}".'
    )


def build_one_sided_affection_response(value: str) -> str:
    """Response for a one-sided ("đơn phương") affection phrase (P0-7F-FIX5 Part B).

    Acknowledges the unrequited feeling, refuses to store it as an ordinary preference, and
    offers the explicit relationship phrasing that WOULD be saved. Never saved automatically.
    """
    return (
        f"Mình hiểu bạn đang nói về tình cảm đơn phương với {value}. Mình sẽ không lưu đây "
        'là sở thích thông thường. Nếu bạn muốn lưu rõ quan hệ, hãy nói: "người yêu của tôi '
        f'là {value}" hoặc "người tôi thích tên là {value}".'
    )


# ---------------------------------------------------------------------------
# P0-7G response builders
# ---------------------------------------------------------------------------

def build_negative_preference_ack(value: str) -> str:
    """Ack after saving a durable negative preference ("tôi không thích ăn cá")."""
    value = canonicalize_known_preference_value(value)
    return (
        f"Đã nhớ là bạn không thích {value}. Mình sẽ tính đến điều này khi gợi ý "
        "những việc liên quan."
    )


def build_negative_skill_ack(value: str) -> str:
    """P0-7K-FIX1: ack after saving a negative skill ("tôi không biết bơi")."""
    return (
        f"Đã nhớ là bạn không biết {value}. Mình sẽ không xếp đây là kỹ năng bạn có."
    )


def build_negative_desire_response(value: str) -> str:
    """Clarify (no-save) for a short-term negative desire ("tôi không muốn đi học")."""
    return (
        f"Mình hiểu hiện tại bạn không muốn {value}. Đây có vẻ là trạng thái/mong muốn "
        "ngắn hạn, nên mình sẽ không lưu như sở thích lâu dài."
    )


def build_affection_memory_ack(value: str) -> str:
    """Ack after saving affection/person memory ("tôi thích/yêu/crush Quý") — P0-7G.

    Explicitly separates this from an ordinary hobby/preference.
    """
    return (
        f"Đã nhớ là bạn có tình cảm/thích {value}. Mình sẽ không xếp thông tin này vào "
        "sở thích thông thường."
    )


def build_external_affection_ack(admirer: str) -> str:
    """Ack after saving a user-reported external affection fact ("Quý thích tôi") — P0-7G.

    Framed as reported information, never as objective truth.
    """
    return (
        f"Đã nhớ theo thông tin bạn cung cấp: {admirer} thích bạn. Mình ghi nhận đây là "
        "thông tin do bạn kể lại."
    )


def build_unrelated_external_affection_response(subject: str, obj: str) -> str:
    """Narrow safe/no-save reply for third-party affection between two other people
    ("Quý thích Nam") — P0-7G-FIX1. Not saved, nothing inferred about the user; never a
    generic fallback."""
    return (
        f"Mình hiểu bạn đang nói về việc {subject} thích {obj}, nhưng đây không phải thông "
        "tin trực tiếp về bạn nên mình sẽ không lưu vào hồ sơ của bạn."
    )


def build_name_update_ack(old_name: str, new_name: str) -> str:
    """Ack after an explicit/implicit self-name update ("sửa tên tôi thành ...")."""
    if _norm_cmp(old_name) == _norm_cmp(new_name):
        return f"Mình vẫn đang nhớ tên bạn là {new_name}."
    return f"Đã cập nhật tên bạn từ {old_name} thành {new_name}."


def answer_yes_no_memory_query(
    category: str, value: str, store: "MemoryStoreProtocol"
) -> str:
    """Deterministic yes/no reasoning over the profile snapshot (P0-7F).

    Names the stored category explicitly; never infers a "yes" across unrelated categories
    without saying so. Three states: matched, cross-category note, unknown.
    """
    snap = collect_profile_snapshot(store)
    target = _norm_cmp(value)
    raw_target = value.strip()
    pref_values = snap.preferences_personal + snap.preferences_professional
    prefs = [_norm_cmp(v) for v in pref_values]
    skills = [_norm_cmp(v) for v in snap.skills]
    affections = [_norm_cmp(v) for v in snap.affections]
    dislikes = [_norm_cmp(v) for v in snap.dislikes]

    if category == "preference":
        # P0-7K-FIX5A: answer visible multi-object preference queries per item; never
        # look up the raw joined phrase ("A và B") as a single preference object.
        items = _split_preference_query_items(raw_target)
        if len(items) >= 2:
            return _answer_batch_preference_yesno(items, snap)
        query_value = _canonicalize_preference_query_object(value, snap)
        target = _norm_cmp(query_value)
        if raw_target == "ai":
            # P0-7G: lowercase "ai" is the person question word — route to affection state.
            if snap.affections:
                return f"Có, mình đang nhớ là bạn thích {snap.affections[0]}."
            return "Mình chưa có thông tin về người bạn thích."
        # P0-7G: person affection ("tôi có thích Quý không?") answers from affection memory.
        if target in affections:
            return f"Có, mình đang nhớ là bạn thích {query_value}."
        # P0-7K-HOTFIX1 C: retracted affection ("không thích quý nữa") answers "no",
        # never unknown — before the generic "chưa thấy" fallthrough.
        if any(_norm_cmp(v) == target for v in snap.negative_affections):
            return f"Không, hiện tại bạn không còn thích/quan tâm {query_value}."
        # P0-7G: durable dislike ("tôi có thích ăn cá không?" after "tôi không thích ăn cá").
        if target in dislikes or any(_matches_preference_query(v, query_value) for v in snap.dislikes):
            return f"Không, bạn từng nói là không thích {query_value}."
        if target in prefs or any(_matches_preference_query(v, query_value) for v in pref_values):
            return f"Có, mình đang nhớ bạn thích {query_value}."
        # P0-7K-FIX2: a comparative winner ("thích cafe hơn trà") answers the yes/no too.
        if any(_norm_cmp(w) == target for w, _l in snap.comparatives):
            return f"Có, mình đang nhớ bạn thích {query_value}."
        if snap.favorite_food and _norm_cmp(snap.favorite_food) == target:
            return f"Có, mình đang nhớ bạn thích {query_value}."
        if snap.favorite_general and _norm_cmp(snap.favorite_general) == target:
            return f"Có, mình đang nhớ bạn thích {query_value}."
        if target in skills:
            return (
                f'Mình đang nhớ bạn biết {query_value}, nhưng chưa lưu "{query_value}" như một sở thích.'
            )
        return f"Mình chưa thấy thông tin rằng bạn thích {query_value}."

    if category == "skill":
        negative_skills = [_norm_cmp(v) for v in snap.negative_skills]
        # P0-7K-FIX4 D: a batch yes/no ("tôi biết A và B không?") is answered per item,
        # never as one raw object. Single-item queries keep the original phrasing.
        items = _split_skill_query_items(raw_target)
        if len(items) >= 2:
            known, neg, unknown = [], [], []
            for item in items:
                it = _norm_cmp(item)
                if it in skills:
                    known.append(item)
                elif it in negative_skills:
                    neg.append(item)
                else:
                    unknown.append(item)
            parts: list[str] = []
            if known:
                parts.append(f"Có, mình đang nhớ bạn biết {', '.join(known)}")
            if neg:
                parts.append(f"mình đang nhớ bạn không biết {', '.join(neg)}")
            if unknown:
                parts.append(f"mình chưa rõ về {', '.join(unknown)}")
            return "; ".join(parts) + "." if parts else (
                f"Mình chưa thấy thông tin rằng bạn biết {value}."
            )
        if target in skills:
            return f"Đúng, mình đang nhớ bạn biết {value}."
        # P0-7K-FIX1: known negative skill ("tôi không biết bơi").
        if target in negative_skills:
            return f"Không, bạn từng nói là không biết {value}."
        if target in prefs:
            return (
                f'Mình đang nhớ bạn thích {value}, nhưng chưa lưu là bạn biết "{value}".'
            )
        return f"Mình chưa thấy thông tin rằng bạn biết {value}."

    return f"Mình chưa thấy thông tin về {value}."


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def save_confirmed_profile_fact(
    candidate: ProfileFactCandidate,
    store: "MemoryStoreProtocol",
    session_id: str,
    *,
    confirmation_source: str = "explicit_user_confirmation",
) -> bool:
    """Write a name/relation profile fact to store. Returns True on success.

    ``confirmation_source`` is "explicit_user_confirmation" for the legacy confirm flow or
    "auto_safe" for P0-7E direct auto-save. Schema stays v1; retrieval reads v1 and v2.
    """
    from agent_core.memory.memory_agent import MemoryAgent

    tags = ["user_profile"]
    metadata: dict = {
        "profile_schema": "user_profile_fact_v1",
        "subject": candidate.subject,
        "relation": candidate.relation,
        "value": candidate.value,
        "confirmed": True,
        "confirmation_source": confirmation_source,
        "original_text": candidate.original_text,
    }
    if confirmation_source == "auto_safe":
        metadata["write_policy"] = "auto_safe"

    if candidate.subject == "self":
        tags += ["self", "name"]
        content = f"tên của bạn là {candidate.value}"
    else:
        label = candidate.relation_label or "relation"
        tag_key = _RELATION_TAG_MAP.get(label, label.replace(" ", "_"))
        tags += ["relation", "name", tag_key]
        metadata["relation_label"] = label
        content = f"{label} của bạn tên là {candidate.value}"

    try:
        mem_agent = MemoryAgent(store, user_id=None, session_id=session_id)
        mem_agent.save_fact(
            content=content,
            tags=tags,
            source=SourceType.USER,
            importance=0.9,
            confidence=1.0,
            metadata=metadata,
        )
        return True
    except Exception:
        return False


def save_auto_profile_fact(
    candidate: AutoProfileCandidate,
    store: "MemoryStoreProtocol",
    session_id: str,
) -> bool:
    """Write an AUTO_SAFE profile fact without explicit user confirmation. Returns True on success."""
    from agent_core.memory.memory_agent import MemoryAgent

    value = (
        canonicalize_known_preference_value(candidate.value)
        if candidate.relation in ("preference", "negative_preference")
        else candidate.value
    )
    if candidate.relation in ("preference", "negative_preference"):
        _delete_canonical_alias_preference_records(value, candidate.relation, store)

    tags = ["user_profile", "self", candidate.relation]
    if candidate.relation == "preference":
        tags.append("interest")

    metadata: dict = {
        "profile_schema": "user_profile_fact_v2",
        "subject": "self",
        "relation": candidate.relation,
        "value": value,
        "confirmed": True,
        "confirmation_source": "auto_safe",
        "write_policy": "auto_safe",
        "source": "conversation",
        "confidence_label": "high",
        "extractor": "rule_based_profile_v1",
        "original_text": candidate.original_text,
    }
    # P0-7F: preference personal/professional subcategory (metadata only).
    if candidate.relation == "preference" and candidate.preference_kind:
        metadata["preference_kind"] = candidate.preference_kind

    _content_map = {
        "occupation": f"bạn là {value}",
        "preference": f"bạn thích {value}",
        "goal": f"mục tiêu của bạn là {value}",
        "wants_to_marry": f"bạn muốn cưới {value}",
        "learning_focus": f"bạn đang học {value}",
        "habit": f"bạn hay {value}",
        "skill": f"bạn biết {value}",
        "household_pet": f"nhà bạn có nuôi {value}",
        "negative_preference": f"bạn không thích {value}",
        "negative_skill": f"bạn không biết {value}",
        "goal_focus": f"mục tiêu chính của bạn là {value}",
    }
    content = _content_map.get(candidate.relation, f"{candidate.relation}: {value}")

    try:
        mem_agent = MemoryAgent(store, user_id=None, session_id=session_id)
        if candidate.relation == "preference":
            mem_agent.save_preference(
                content=content,
                tags=tags,
                source=SourceType.USER,
                importance=0.7,
                confidence=0.95,
                metadata=metadata,
            )
        else:
            mem_agent.save_fact(
                content=content,
                tags=tags,
                source=SourceType.USER,
                importance=0.8,
                confidence=0.95,
                metadata=metadata,
            )
        return True
    except Exception:
        return False


def _save_profile_v2_fact(
    store: "MemoryStoreProtocol",
    session_id: str,
    *,
    subject: str,
    relation: str,
    value: str,
    content: str,
    tags: list[str],
    original_text: str = "",
    extra_metadata: dict | None = None,
) -> bool:
    """Write a v2 profile FACT with the standard confirmed/auto_safe metadata. P0-7G helper."""
    from agent_core.memory.memory_agent import MemoryAgent

    metadata: dict = {
        "profile_schema": "user_profile_fact_v2",
        "subject": subject,
        "relation": relation,
        "value": value,
        "confirmed": True,
        "confirmation_source": "auto_safe",
        "write_policy": "auto_safe",
        "source": "conversation",
        "confidence_label": "high",
        "extractor": "rule_based_profile_v1",
        "original_text": original_text,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    try:
        mem_agent = MemoryAgent(store, user_id=None, session_id=session_id)
        mem_agent.save_fact(
            content=content,
            tags=tags,
            source=SourceType.USER,
            importance=0.8,
            confidence=0.95,
            metadata=metadata,
        )
        return True
    except Exception:
        return False


def save_affection_fact(
    value: str, store: "MemoryStoreProtocol", session_id: str, *, original_text: str = ""
) -> bool:
    """P0-7G: save affection/person memory ("bạn thích Quý") as a distinct self fact.

    Stored under relation ``affection`` so it never pollutes ordinary preference retrieval
    ("tôi thích gì?") while still answering the affection lane ("tôi thích ai?").
    """
    # P0-7K-HOTFIX1 C: re-liking a person clears a prior negative-affection record.
    _delete_profile_records(
        store, subject="self", relation="negative_affection", value=value,
    )
    return _save_profile_v2_fact(
        store, session_id,
        subject="self", relation="affection", value=value,
        content=f"bạn có tình cảm/thích {value}",
        tags=["user_profile", "self", "affection"],
        original_text=original_text,
    )


def save_favorite_fact(
    value: str, domain: str, store: "MemoryStoreProtocol", session_id: str,
    *, original_text: str = "",
) -> bool:
    """P0-7K-FIX2: save a favorite ("tôi thích X nhất") as a distinct self fact.

    Stored under relation ``favorite`` with a ``favorite_domain`` (food/general), so it
    never pollutes ordinary preference retrieval while answering the "... gì nhất?" lane.
    """
    return _save_profile_v2_fact(
        store, session_id,
        subject="self", relation="favorite", value=value,
        content=f"bạn thích {value} nhất",
        tags=["user_profile", "self", "favorite"],
        original_text=original_text,
        extra_metadata={"favorite_domain": domain},
    )


def save_comparative_fact(
    winner: str, loser: str, domain: str, store: "MemoryStoreProtocol", session_id: str,
    *, original_text: str = "",
) -> bool:
    """P0-7K-FIX2: save a comparative preference ("tôi thích A hơn B") as a self fact.

    Stored under relation ``comparative`` (winner value + ``compared_to`` loser), so the
    raw comparative phrase never enters ordinary preference retrieval.
    """
    return _save_profile_v2_fact(
        store, session_id,
        subject="self", relation="comparative", value=winner,
        content=f"bạn thích {winner} hơn {loser}",
        tags=["user_profile", "self", "comparative"],
        original_text=original_text,
        extra_metadata={"compared_to": loser, "comparative_domain": domain},
    )


def save_external_affection_fact(
    admirer: str, store: "MemoryStoreProtocol", session_id: str, *, original_text: str = ""
) -> bool:
    """P0-7G: save a user-reported external affection fact ("Quý thích tôi").

    Recorded as reported information (admirer → the user), never as objective truth.
    """
    _delete_profile_records(
        store, subject="external", relation="affection_to_user_negative", value=admirer,
    )
    return _save_profile_v2_fact(
        store, session_id,
        subject="external", relation="affection_to_user", value=admirer,
        content=f"{admirer} thích bạn (theo thông tin bạn cung cấp)",
        tags=["user_profile", "external", "affection"],
        original_text=original_text,
    )


def save_negative_external_affection_fact(
    admirer: str, store: "MemoryStoreProtocol", session_id: str, *, original_text: str = ""
) -> bool:
    """P0-7K-HOTFIX1 D: user-reported NEGATIVE external affection ("Quý không thích tôi").

    Supersedes any prior positive external-affection record for the same person.
    """
    _delete_profile_records(
        store, subject="external", relation="affection_to_user", value=admirer,
    )
    return _save_profile_v2_fact(
        store, session_id,
        subject="external", relation="affection_to_user_negative", value=admirer,
        content=f"{admirer} không thích bạn (theo thông tin bạn cung cấp)",
        tags=["user_profile", "external", "affection"],
        original_text=original_text,
    )


def save_negative_affection_fact(
    value: str, store: "MemoryStoreProtocol", session_id: str, *, original_text: str = ""
) -> bool:
    """P0-7K-HOTFIX1 C: record that the user no longer likes a person ("không thích quý nữa").

    Supersedes any active positive affection so the yes/no query answers "no", not unknown.
    """
    _delete_profile_records(
        store, subject="self", relation="affection", value=value,
    )
    return _save_profile_v2_fact(
        store, session_id,
        subject="self", relation="negative_affection", value=value,
        content=f"bạn không còn thích/quan tâm {value}",
        tags=["user_profile", "self", "affection"],
        original_text=original_text,
    )


def _delete_profile_records(
    store: "MemoryStoreProtocol", *, subject: str, relation: str, value: str,
) -> None:
    """Delete confirmed profile records matching (subject, relation, value)."""
    target = _norm_cmp(value)
    for rec in list(store.search(MemoryQuery(
        text="", types=[MemoryType.FACT], tags=["user_profile"], limit=200,
    ))):
        md = rec.metadata
        if not (md.get("confirmed") and md.get("profile_schema") in (
            "user_profile_fact_v1", "user_profile_fact_v2"
        )):
            continue
        if (
            md.get("subject") == subject and md.get("relation") == relation
            and _norm_cmp(md.get("value", "")) == target
        ):
            store.delete(rec.id, reason="affection_polarity_superseded")


def save_self_name_update(
    value: str, store: "MemoryStoreProtocol", session_id: str, *, original_text: str = ""
) -> bool:
    """P0-7G: persist a self-name update. Appends a v1 name record; retrieval returns the
    latest (by created_at), so the newest name supersedes older ones."""
    candidate = ProfileFactCandidate(
        subject="self", relation="name", value=value, original_text=original_text,
    )
    return save_confirmed_profile_fact(
        candidate, store, session_id, confirmation_source="auto_safe"
    )


# ---------------------------------------------------------------------------
# P0-7H relation update / removal
# ---------------------------------------------------------------------------

def detect_relation_update_cmd(text: str) -> tuple[str, str] | None:
    """Return (relation_label, new_name) for an explicit relation update command, else None.

    Handles "sửa bạn gái của tôi thành May", "đổi người yêu của tôi thành Nam".
    """
    m = _RE_RELATION_UPDATE_CMD.match(text.strip())
    if not m:
        return None
    label = _normalize_relation_label(m.group(1))
    name = re.sub(r"\s+", " ", m.group(2).strip().rstrip(".!?")).strip()
    if not name or _is_unsafe_or_sensitive_auto_value(name):
        return None
    return label, name


def detect_relation_removal_cmd(text: str) -> tuple[str, str] | None:
    """Return (relation_label, person_name) for an explicit relation removal command, else None.

    Handles "cập nhật Quý không phải là bạn gái của tôi".
    """
    m = _RE_RELATION_REMOVAL_CMD.match(text.strip())
    if not m:
        return None
    person = re.sub(r"\s+", " ", m.group(1).strip().rstrip(".!?")).strip()
    label = _normalize_relation_label(m.group(2))
    if not person:
        return None
    return label, person


def delete_relation_fact(label: str, store: "MemoryStoreProtocol") -> str | None:
    """Delete the stored relation fact for the given label. Returns the deleted value, or None if not found."""
    lookup_labels = _get_lookup_labels(label) or frozenset({label})
    records = list(store.search(MemoryQuery(
        text="", types=[MemoryType.FACT], tags=["user_profile"], limit=100,
    )))
    for rec in records:
        md = rec.metadata
        if not (md.get("confirmed") and md.get("profile_schema") in (
            "user_profile_fact_v1", "user_profile_fact_v2"
        )):
            continue
        if (
            md.get("subject") == "relation"
            and md.get("relation") == "name"
            and md.get("relation_label") in lookup_labels
        ):
            store.delete(rec.id, reason="user_removal")
            return md.get("value", "")
    return None


def save_relation_update(
    label: str, new_name: str,
    store: "MemoryStoreProtocol", session_id: str,
    *, original_text: str = "",
) -> bool:
    """Delete any existing relation record for label, then save new_name. Returns True on success."""
    delete_relation_fact(label, store)
    candidate = ProfileFactCandidate(
        subject="relation", relation="name",
        value=new_name, relation_label=label,
        original_text=original_text,
    )
    return save_confirmed_profile_fact(candidate, store, session_id, confirmation_source="auto_safe")


def build_relation_update_ack(label: str, new_name: str) -> str:
    return f"Đã cập nhật {label} của bạn thành {new_name}."


def build_relation_removal_ack(label: str) -> str:
    return f"Đã xóa thông tin {label} của bạn."


def build_relation_removal_not_found() -> str:
    return "Tôi chưa lưu thông tin về đối tượng này."


# ---------------------------------------------------------------------------
# P0-7H-FIX1: occupation/name correction + alias relation query
# ---------------------------------------------------------------------------

def detect_occupation_name_correction(text: str) -> str | None:
    """Return the corrected occupation value if text corrects name/occupation confusion.

    Handles:
    - "VALUE là nghề/công việc của tôi chứ không phải tên" (left-side form, checked first)
    - "... là X chứ không phải tên ..." (generic CHU form, fallback)
    - "VALUE là nghề/công việc của tôi" (standalone form)
    """
    stripped = text.strip()
    if re.search(r'không\s+phải\s+(?:là\s+)?tên', stripped, re.IGNORECASE):
        # Left-side form captures VALUE before "là nghề/công việc của tôi".
        # Must run before CHU to avoid capturing "của tôi" as the occupation.
        m0 = _RE_OCC_CORRECTION_LEFT.match(stripped)
        if m0:
            value = re.sub(r"\s+", " ", m0.group(1).strip().rstrip(".!?,")).strip()
            if value and _is_valid_auto_value(value):
                return value
        # Generic CHU fallback: "là X chứ không phải tên"
        m = _RE_OCC_CORRECTION_CHU.search(stripped)
        if m:
            value = re.sub(r"\s+", " ", m.group(1).strip().rstrip(".!?,")).strip()
            if value and _is_valid_auto_value(value):
                return value
    # Standalone form: "VALUE là nghề/công việc của tôi" (no correction guard)
    m2 = _RE_OCC_CORRECTION_NGHE.match(stripped)
    if m2:
        value = re.sub(r"\s+", " ", m2.group(1).strip().rstrip(".!?,")).strip()
        if value and _is_valid_auto_value(value):
            return value
    return None


def build_occ_correction_ack(value: str) -> str:
    return f"Mình hiểu: '{value}' là nghề/công việc của bạn, không phải tên. Mình đã cập nhật lại."


def detect_relation_alias_query(text: str) -> tuple[str, str] | None:
    """Return (relation_label, name_in_query) for 'RELATION của NAME là ai?' queries.

    The caller compares name_in_query against the saved self-name to decide
    whether this is a current-user query or an unknown third-party query.
    """
    m = _RE_RELATION_ALIAS_Q.match(text.strip())
    if not m:
        return None
    label = _normalize_relation_label(m.group(1))
    name = re.sub(r"\s+", " ", m.group(2).strip()).strip()
    if not name:
        return None
    return label, name


# ---------------------------------------------------------------------------
# P0-7I: correction lead-in stripping + occupation removal
# ---------------------------------------------------------------------------

def detect_correction_remainder(text: str) -> str | None:
    """Return the corrected assertion clause for a leading correction phrase, else None.

    Strips lead-ins like "không, ", "ý tôi là ", and "tôi mới/vừa nói ... mà" so the
    remainder can be re-dispatched through the normal write detectors as if the user had
    said it directly.
    """
    stripped = text.strip()
    for pat in (_RE_CORRECTION_KHONG, _RE_CORRECTION_Y_TOI_LA, _RE_CORRECTION_MOI_NOI):
        m = pat.match(stripped)
        if m:
            remainder = re.sub(r"\s+", " ", m.group(1).strip()).strip()
            if remainder:
                return remainder
    return None


def detect_occupation_removal(text: str) -> str | None:
    """Return the occupation value to retract for "tôi không phải (là) X", else None.

    Extraction only — the caller checks the value against currently stored occupations
    before acting, so an unrelated denial ("tôi không phải là người xấu") never fires.
    """
    stripped = text.strip()
    if '?' in stripped or '？' in stripped:
        return None
    m = _RE_OCC_REMOVAL.match(stripped)
    if not m:
        return None
    value = re.sub(r"\s+", " ", m.group(1).strip().rstrip(".!?,")).strip()
    return value or None


def delete_occupation_fact(value: str, store: "MemoryStoreProtocol") -> str | None:
    """Delete all stored occupation records matching value (case-insensitive).

    Returns the matched stored display value, or None if no stored occupation matches.
    Never removes an unrelated occupation.
    """
    target = _norm_cmp(value)
    records = list(store.search(MemoryQuery(
        text="", types=[MemoryType.FACT], tags=["user_profile"], limit=200,
    )))
    matched_value: str | None = None
    for rec in records:
        md = rec.metadata
        if not (md.get("confirmed") and md.get("profile_schema") in (
            "user_profile_fact_v1", "user_profile_fact_v2"
        )):
            continue
        if md.get("subject") != "self" or md.get("relation") != "occupation":
            continue
        stored_value = md.get("value", "")
        if _norm_cmp(stored_value) == target:
            store.delete(rec.id, reason="user_removal")
            matched_value = matched_value or stored_value
    return matched_value


def build_occupation_removal_ack(value: str) -> str:
    return f"Đã xóa thông tin nghề nghiệp/công việc '{value}' khỏi hồ sơ của bạn."


# ---------------------------------------------------------------------------
# P0-7K-FIX1 I: low-confidence relationship typo — clarify, never write
# ---------------------------------------------------------------------------

# Bounded near-miss map for relationship labels (NOT a full typo engine). Each maps a
# common mistype to its intended label; only these exact near-misses trigger a
# clarification instead of a memory write.
_RELATION_TYPO_MAP: dict[str, str] = {
    "bạn ái": "bạn gái",
    "bặn gái": "bạn gái",
    "bạn gaí": "bạn gái",
    "bạn traí": "bạn trai",
    "ngừoi yêu": "người yêu",
    "ngươi yêu": "người yêu",
}
_RE_RELATION_TYPO = re.compile(
    r'^(\S+\s+\S+|\S+)\s+(?:của\s+)?(?:tôi|mình)\s+(?:tên\s+)?là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE,
)


def detect_relationship_typo(text: str) -> tuple[str, str, str] | None:
    """Return (raw_label, corrected_label, name) for a near-miss relationship typo, else None.

    Only fires for a bounded set of common mistypes ("bạn ái" → "bạn gái"), so a genuine
    unknown phrase still falls through to the normal router. The caller asks for
    confirmation and does NOT write memory (fail-safe).
    """
    m = _RE_RELATION_TYPO.match(text.strip())
    if not m:
        return None
    raw_label = re.sub(r"\s+", " ", m.group(1).strip().lower())
    corrected = _RELATION_TYPO_MAP.get(raw_label)
    if not corrected:
        return None
    name = re.sub(r"\s+", " ", m.group(2).strip()).strip()
    if not name:
        return None
    return raw_label, corrected, name


def build_relationship_typo_clarification(corrected_label: str, name: str) -> str:
    return f"Bạn muốn nói \"{corrected_label} của tôi là {name}\" phải không?"


# ---------------------------------------------------------------------------
# P0-7K-FIX3: reminder/repair, delete-all, dirty-value filter
# ---------------------------------------------------------------------------

# Inner memory clause must start with a supported memory pattern.
_RE_MEMORY_CLAUSE_START = re.compile(
    r'^(?:'
    # P0-7K-FIX5C-LITE E: allow a "cũng/vẫn" modifier so an embedded self-affection
    # reminder ("... tôi cũng thích may rồi") is recognized as a memory clause.
    r'(?:tôi|mình)\s+(?:cũng\s+|vẫn\s+)?(?:không\s+thích|thích|không\s+biết|biết|làm|là|tên|sẽ|muốn|định|có)'
    r'|(?:bạn\s+gái|bạn\s+trai|người\s+yêu|vợ|chồng|partner)\b'
    r')',
    re.IGNORECASE,
)
# "... đã nói: <inner>" — the inner clause is everything after the colon.
_RE_REMINDER_COLON = re.compile(
    r'(?:(?:tôi|mình)\s+)?(?:đã\s+)?(?:nói|bảo)\s*:\s*(.+)$', re.IGNORECASE,
)
# Leading reminder markers ("tôi đã nói rồi mà ...", "mình đã nói là ...", "tôi bảo ...").
_RE_REMINDER_LEADING = re.compile(
    r'^(?:(?:tôi|mình)\s+)?(?:đã\s+)?(?:nói|bảo)(?:\s+là)?(?:\s+rồi)?(?:\s+mà)?\s*',
    re.IGNORECASE,
)
# Trailing reminder tails to drop from an inner clause ("... rồi mà").
_RE_REMINDER_TRAILING = re.compile(
    r'\s+(?:rồi\s+mà|rồi|mà)\s*[.!]*\s*$', re.IGNORECASE,
)
# Standalone generic repair phrases.
_RE_REPAIR_STANDALONE = re.compile(
    r'^(?:sai\s+rồi|sai|không\s+đúng|nhầm\s+rồi|nhầm)\s*[.!]*\s*$', re.IGNORECASE,
)
# Any reminder/correction marker (used to route to repair when no inner clause parses).
_RE_REMINDER_MARKER = re.compile(
    r'(?:tôi\s+(?:đã\s+)?(?:nói|bảo)(?:\s+rồi)?\s+mà|(?:đã\s+)?nói\s*:|rồi\s+mà)',
    re.IGNORECASE,
)


def detect_reminder_inner_clause(text: str) -> str | None:
    """Return the inner memory clause of a reminder/correction sentence, else None.

    "... tôi đã nói: tôi thích ăn kẹo hơn ăn kem" → "tôi thích ăn kẹo hơn ăn kem".
    "tôi bảo tôi thích ăn chuối nhất rồi mà" → "tôi thích ăn chuối nhất".
    Only returns a clause that starts with a supported memory pattern; otherwise None
    (the caller routes to repair clarification instead of writing the raw sentence).
    """
    stripped = re.sub(r"\s+", " ", text.strip())
    m = _RE_REMINDER_COLON.search(stripped)
    if m:
        inner = _RE_REMINDER_TRAILING.sub("", m.group(1).strip()).strip()
        return inner if inner and _RE_MEMORY_CLAUSE_START.match(inner) else None
    lead = _RE_REMINDER_LEADING.match(stripped)
    if lead and lead.end() > 0:
        inner = _RE_REMINDER_TRAILING.sub("", stripped[lead.end():].strip()).strip()
        if inner and _RE_MEMORY_CLAUSE_START.match(inner):
            return inner
    return None


def detect_repair_intent(text: str) -> bool:
    """True if text is a standalone repair phrase or a reminder marker with no clause."""
    stripped = text.strip()
    if _RE_REPAIR_STANDALONE.match(stripped):
        return True
    return bool(_RE_REMINDER_MARKER.search(stripped))


# P0-7K-HOTFIX1-FIX1 B: a bare "you forgot" reminder, optionally led by a "tôi (đã) nói/bảo
# rồi" marker. Anchored end-to-end so a goal/fact-bearing sentence like "tôi vẫn muốn làm ML
# bạn không nhớ à" is NOT matched (its "tôi vẫn muốn làm ML" is not a nói/bảo lead), leaving
# it to the goal-reminder path.
_RE_GENERIC_REMINDER = re.compile(
    r'^(?:(?:tôi|mình)\s+(?:đã\s+)?(?:nói|bảo)(?:\s+là)?(?:\s+rồi)?(?:\s+mà)?\s+)?'
    r'bạn\s+(?:không|ko)\s+nhớ\s*(?:à|a|sao|hả|gì|nữa)?\s*[.!?]*\s*$',
    re.IGNORECASE,
)


def detect_generic_reminder(text: str) -> bool:
    """True if text is a generic "bạn không nhớ (à/sao)?" reminder with no embedded fact."""
    return bool(_RE_GENERIC_REMINDER.match(text.strip()))


def build_generic_reminder_repair(corrected: str | None) -> str:
    """Acknowledge a generic reminder; re-answer the last query when one is resolvable."""
    if corrected:
        return "Đúng, mình cần kiểm tra lại thông tin đã nhớ. Câu đúng là: " + corrected
    return (
        "Mình hiểu là bạn đang nhắc mình đã bỏ sót thông tin. "
        "Bạn muốn mình kiểm tra lại thông tin nào?"
    )


def build_repair_clarification() -> str:
    return (
        "Mình hiểu là câu trả lời trước có lỗi. Bạn muốn sửa phần nào: sở thích, "
        "kỹ năng, mục tiêu, tên, hay quan hệ?"
    )


# P0-7K-HOTFIX1 F: answer-feedback phrases ("bạn trả lời sai rồi", "bạn phải trả lời
# là ...", "tôi đã cung cấp thông tin ... rồi"). These are meta-feedback about the
# previous answer — never saved as memory, never a generic fallback.
_RE_ANSWER_FEEDBACK = re.compile(
    r'(?:bạn\s+)?(?:trả\s+lời|nói)\s+sai(?:\s+rồi)?'
    r'|bạn\s+phải\s+trả\s+lời\s+là'
    r'|(?:câu\s+)?trả\s+lời\s+(?:trước\s+)?(?:chưa|không)\s+đúng'
    r'|tôi\s+(?:đã\s+)?cung\s+cấp\s+thông\s+tin.*rồi',
    re.IGNORECASE,
)


def detect_answer_feedback(text: str) -> bool:
    """True if text is meta-feedback about the previous answer (no memory write)."""
    return bool(_RE_ANSWER_FEEDBACK.search(text.strip()))


def build_answer_feedback_repair(corrected: str | None) -> str:
    """Acknowledge answer feedback; include the corrected answer when available."""
    if corrected:
        return (
            "Đúng, câu trả lời trước chưa chính xác. Câu đúng là: " + corrected
        )
    return (
        "Mình hiểu là câu trả lời trước chưa đúng. Bạn muốn mình sửa phần nào?"
    )


# Delete-all profile memory request phrases. Requires EITHER a "hết/toàn bộ/sạch"
# quantifier OR an explicit memory noun (ký ức/thông tin/memory), so deleting a single
# note ("xoá ghi chú của tôi") never triggers a full memory wipe.
# "xóa" (ó on o) and "xoá" (á on a) are both valid spellings — match both.
_XOA = r'x[oó][áa]'
_RE_DELETE_ALL_MEMORY = re.compile(
    r'(?:' + _XOA + r'|quên)\s+'
    r'(?:(?:hết|toàn\s+bộ|sạch)\s*(?:ký\s+ức|thông\s+tin|memory|mọi\s+thứ)?'
    r'|(?:ký\s+ức|thông\s+tin|memory))'
    r'.*?(?:về|của)\s+(?:tôi|mình)'
    r'|đừng\s+nhớ\s+gì\s+(?:về\s+)?(?:tôi|mình)\s+nữa'
    r'|clear\s+memory|forget\s+me',
    re.IGNORECASE,
)
# P0-7K-FIX4 F: expanded confirmation allowlist — "xác nhận xoá ký ức", "ok xoá đi",
# "xoá đi", "đồng ý xoá", "yes delete", "confirm delete" (both "xóa"/"xoá" spellings).
_RE_DELETE_CONFIRM = re.compile(
    r'^(?:'
    r'xác\s+nhận\s+' + _XOA + r'(?:\s+ký\s+ức)?'
    r'|đồng\s+ý\s+' + _XOA + r'(?:\s+(?:đi|ký\s+ức))?'
    r'|(?:ok|okay|đồng\s+ý|ừ|ừm|vâng)\s+' + _XOA + r'\s+đi'
    r'|' + _XOA + r'\s+đi'
    r'|yes\s+delete|confirm\s+delete'
    r')\s*[.!]*\s*$',
    re.IGNORECASE,
)


def detect_delete_all_memory_request(text: str) -> bool:
    return bool(_RE_DELETE_ALL_MEMORY.search(text.strip()))


def detect_delete_all_confirmation(text: str) -> bool:
    return bool(_RE_DELETE_CONFIRM.match(text.strip()))


def delete_all_profile_memory(store: "MemoryStoreProtocol") -> int:
    """Delete every confirmed user-profile record. Returns the count removed."""
    records = list(store.search(MemoryQuery(
        text="", types=[MemoryType.FACT], tags=["user_profile"], limit=500,
    ))) + list(store.search(MemoryQuery(
        text="", types=[MemoryType.PREFERENCE], tags=["user_profile"], limit=500,
    )))
    removed = 0
    seen: set[str] = set()
    for rec in records:
        if rec.id in seen:
            continue
        seen.add(rec.id)
        md = rec.metadata
        if md.get("profile_schema") in ("user_profile_fact_v1", "user_profile_fact_v2"):
            store.delete(rec.id, reason="user_delete_all_memory")
            removed += 1
    return removed


def build_delete_all_confirmation_prompt() -> str:
    return (
        "Bạn chắc muốn xoá toàn bộ thông tin mình đang nhớ về bạn không? "
        'Hãy trả lời "xác nhận xoá ký ức" để mình xoá.'
    )


def build_delete_all_done() -> str:
    return "Đã xoá toàn bộ thông tin mình nhớ về bạn."


# P0-7K-FIX3 L: dirty object-value markers — a stored value containing any of these is
# leftover reminder/predicate pollution and must be filtered from summary/queries.
_DIRTY_VALUE_MARKERS: tuple[str, ...] = (
    "tôi biết", "tôi không biết", "mình biết", "mình không biết",
    "tôi đã nói", "tôi bảo", "đã nói:", "nữa tôi", ":",
    # P0-7K-FIX4 I: contrast fragments must never be stored as one value.
    "nhưng không", "mà không biết", "còn không biết",
)
_DIRTY_VALUE_TERMINAL: tuple[str, ...] = (" nữa", " rồi", " mà", " đấy", " đó")
# P0-7K-FIX6-LITE: question pronouns that must never appear as a stored object value.
# "ai" is checked case-sensitively (see _is_dirty_value) so "AI" the tech token survives.
_DIRTY_VALUE_QUESTION_TAILS: tuple[str, ...] = (
    "gì", "gi", "nào", "đâu", "dau", "bao giờ", "khi nào",
)
_KNOWN_PREFERENCE_TOKEN_CANONICALS: dict[str, str] = {
    "chối": "chuối",
    "lem": "kem",
}


def canonicalize_known_preference_value(value: str) -> str:
    """Canonicalize a tiny allowlist of known food typos in preference values.

    This is intentionally not broad fuzzy matching: it only rewrites exact tokens
    already covered by the memory-core regression surface.
    """
    cleaned = re.sub(r"\s+", " ", value.strip()).strip()
    if not cleaned:
        return value
    mapped = [
        _KNOWN_PREFERENCE_TOKEN_CANONICALS.get(part.lower(), part)
        for part in cleaned.split()
    ]
    return " ".join(mapped)


def _is_dirty_value(value: str) -> bool:
    """True if value is polluted with reminder/predicate/terminal-marker fragments."""
    v = re.sub(r"\s+", " ", value.strip().lower())
    if any(marker in v for marker in _DIRTY_VALUE_MARKERS):
        return True
    # P0-7K-FIX6-LITE: a stored object that is (or ends with) a question pronoun
    # ("cưới ai") is dirty query pollution — never surface it in summary/recall.
    if any(v == p or v.endswith(" " + p) for p in _DIRTY_VALUE_QUESTION_TAILS):
        return True
    # Lowercase "ai" is the question word; uppercase "AI" (tech token) must survive.
    raw_tokens = value.strip().split()
    if raw_tokens and raw_tokens[-1] == "ai":
        return True
    return any(v.endswith(t) for t in _DIRTY_VALUE_TERMINAL)


# ---------------------------------------------------------------------------
# P0-7I: preference conflict resolution (positive vs negative)
# ---------------------------------------------------------------------------

def _preference_conflicts(a: str, b: str) -> bool:
    """True if a and b denote the same preference OBJECT (bounded canonical match).

    Exact normalized match, or a shared alias term via ``_positive_preference_terms``
    (e.g. "ăn kem" and "kem"). Deliberately conservative: never fuzzy-matches typos.
    """
    a = canonicalize_known_preference_value(a)
    b = canonicalize_known_preference_value(b)
    if _norm_cmp(a) == _norm_cmp(b):
        return True
    return bool(_positive_preference_terms(a) & _positive_preference_terms(b))


def _find_conflicting_preference_records(value: str, store: "MemoryStoreProtocol") -> list:
    """Return confirmed self preference/negative_preference records matching value."""
    fact_records = list(store.search(MemoryQuery(
        text="", types=[MemoryType.FACT], tags=["user_profile"], limit=200,
    )))
    pref_records = list(store.search(MemoryQuery(
        text="", types=[MemoryType.PREFERENCE], tags=["user_profile"], limit=200,
    )))
    matches = []
    for rec in fact_records + pref_records:
        md = rec.metadata
        if not (md.get("confirmed") and md.get("profile_schema") in (
            "user_profile_fact_v1", "user_profile_fact_v2"
        )):
            continue
        if md.get("subject") != "self" or md.get("relation") not in (
            "preference", "negative_preference"
        ):
            continue
        stored_value = md.get("value", "")
        if stored_value and _preference_conflicts(stored_value, value):
            matches.append(rec)
    return matches


def resolve_preference_conflicts(
    value: str, new_relation: str, store: "MemoryStoreProtocol"
) -> None:
    """Delete stored preference records of the OPPOSITE polarity that conflict with value.

    Called before saving a new preference/negative_preference so the newer polarity
    supersedes the older one for the same object (P0-7I memory conflict resolution).
    """
    opposite = "negative_preference" if new_relation == "preference" else "preference"
    for rec in _find_conflicting_preference_records(value, store):
        if rec.metadata.get("relation") == opposite:
            store.delete(rec.id, reason="preference_conflict_resolved")


def _delete_canonical_alias_preference_records(
    value: str, relation: str, store: "MemoryStoreProtocol"
) -> None:
    """Deactivate same-polarity dirty aliases for a canonical preference object."""
    canonical = _norm_cmp(canonicalize_known_preference_value(value))
    for rec in _find_conflicting_preference_records(value, store):
        if rec.metadata.get("relation") != relation:
            continue
        stored = rec.metadata.get("value", "")
        if _norm_cmp(stored) == canonical:
            continue
        if _norm_cmp(canonicalize_known_preference_value(stored)) == canonical:
            store.delete(rec.id, reason="preference_alias_canonicalized")


def resolve_skill_conflicts(
    value: str, new_relation: str, store: "MemoryStoreProtocol"
) -> None:
    """P0-7K-FIX1: delete stored skill records of the OPPOSITE polarity for value.

    "biết X" then "không biết X" → the negative wins (positive removed), and vice
    versa. Matching is exact-normalized (conservative, no fuzzy typo matching).
    """
    opposite = "negative_skill" if new_relation == "skill" else "skill"
    target = _norm_cmp(value)
    records = list(store.search(MemoryQuery(
        text="", types=[MemoryType.FACT], tags=["user_profile"], limit=200,
    )))
    for rec in records:
        md = rec.metadata
        if not (md.get("confirmed") and md.get("profile_schema") in (
            "user_profile_fact_v1", "user_profile_fact_v2"
        )):
            continue
        if md.get("subject") == "self" and md.get("relation") == opposite:
            if _norm_cmp(md.get("value", "")) == target:
                store.delete(rec.id, reason="skill_conflict_resolved")


# ---------------------------------------------------------------------------
# Retrieval / answering
# ---------------------------------------------------------------------------

def find_existing_profile_value(
    candidate: ProfileFactCandidate,
    store: "MemoryStoreProtocol",
) -> str | None:
    """Return the stored name value for the candidate's subject/relation, or None.

    Used for P0-7E conflict-safe writes: a direct name/relation claim is only auto-saved
    when no confirmed value already exists for that slot (never a silent overwrite).
    """
    records = list(store.search(MemoryQuery(
        text="",
        types=[MemoryType.FACT],
        tags=["user_profile"],
        limit=100,
    )))
    for rec in records:
        md = rec.metadata
        if not (
            md.get("confirmed")
            and md.get("profile_schema") in ("user_profile_fact_v1", "user_profile_fact_v2")
        ):
            continue
        if candidate.subject == "self":
            if md.get("subject") == "self" and md.get("relation") == "name":
                return md.get("value", "")
        else:
            if (
                md.get("subject") == "relation"
                and md.get("relation") == "name"
                and md.get("relation_label") == candidate.relation_label
            ):
                return md.get("value", "")
    return None


@dataclass
class ProfileSnapshot:
    """Aggregated view of confirmed profile records for query reasoning (P0-7F)."""
    name: str | None = None
    occupation: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    learning: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    marry_targets: list[str] = field(default_factory=list)  # P0-7K-FIX6-LITE wants_to_marry
    preferences_personal: list[str] = field(default_factory=list)
    preferences_professional: list[str] = field(default_factory=list)
    habits: list[str] = field(default_factory=list)
    pets: list[str] = field(default_factory=list)  # P0-7F-FIX4: household pets
    relations: list[tuple[str, str]] = field(default_factory=list)  # (label, name)
    # P0-7G
    dislikes: list[str] = field(default_factory=list)          # negative preferences
    affections: list[str] = field(default_factory=list)        # people the user likes
    external_affections: list[str] = field(default_factory=list)  # people who like the user
    # P0-7K-HOTFIX1 C/D: retracted/negative affection evidence (answers "no", not unknown)
    negative_affections: list[str] = field(default_factory=list)      # people the user no longer likes
    negative_external_affections: list[str] = field(default_factory=list)  # people who do NOT like the user
    # P0-7J: names the user held before the current one (oldest-first, current excluded)
    previous_names: list[str] = field(default_factory=list)
    # P0-7K-FIX1: abilities the user has said they do NOT have ("tôi không biết bơi")
    negative_skills: list[str] = field(default_factory=list)
    # P0-7K-FIX1: the user's stated main goal focus ("mục tiêu chính của tôi là X")
    current_focus: str | None = None
    # P0-7K-FIX2: favorites ("tôi thích X nhất") — latest wins per domain
    favorite_food: str | None = None
    favorite_general: str | None = None
    # P0-7K-FIX2: comparative preferences ("tôi thích A hơn B") — (winner, loser)
    comparatives: list[tuple[str, str]] = field(default_factory=list)


def _norm_cmp(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _split_skill_query_items(value: str) -> list[str]:
    """Split a batch skill query object ("hát và đọc sách") into individual items."""
    parts: list[str] = []
    for chunk in re.split(r'\s*,\s*|\s+và\s+', value.strip(), flags=re.IGNORECASE):
        item = re.sub(r"\s+", " ", chunk.strip().rstrip(".!?,")).strip()
        if item:
            parts.append(item)
    return parts


_PREFERENCE_QUERY_SHARED_PREFIXES: tuple[str, ...] = ("ăn ", "uống ")
_TECHNICAL_CONCEPT_TOKENS: frozenset[str] = frozenset({
    "AI", "ML", "LLM", "SLM", "NLP", "Agent",
})
_TECHNICAL_CONCEPT_PHRASES: frozenset[str] = frozenset({"AI Agent"})


def _strip_batch_item_marker(value: str) -> str:
    return re.sub(
        r'^(?:cả|cũng|còn|thêm)\s+',
        "",
        re.sub(r"\s+", " ", value.strip().rstrip(".!?,?？")),
        flags=re.IGNORECASE,
    ).strip()


def _split_preference_query_items(value: str) -> list[str]:
    """Split a batch preference yes/no object without raw "A và B" lookup.

    Narrow by design: visible list separators only, plus food/drink prefix carry-over
    ("ăn kem và chuối" -> "ăn kem", "ăn chuối"). This is not a fuzzy/entity parser.
    """
    raw = re.sub(r"\s+", " ", value.strip()).strip()
    if not raw:
        return []
    parts: list[str] = []
    for chunk in re.split(r'\s*,\s*', raw):
        for item in re.split(r'\s+và\s+', chunk, flags=re.IGNORECASE):
            cleaned = _strip_batch_item_marker(item)
            if cleaned:
                parts.append(cleaned)
    if not parts:
        return parts
    first_low = parts[0].lower()
    for prefix in _PREFERENCE_QUERY_SHARED_PREFIXES:
        if first_low.startswith(prefix):
            return [
                p if p.lower().startswith(_PREFERENCE_QUERY_SHARED_PREFIXES) else f"{prefix}{p}"
                for p in parts
            ]
    return parts


def _join_vietnamese_items(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} và {items[1]}"
    return ", ".join(items[:-1]) + f" và {items[-1]}"


def _goal_has_verb(goal: str, verb: str) -> bool:
    """True if goal starts with an action verb ("build Agent" → verb "build")."""
    return _norm_cmp(goal).startswith(verb.lower() + " ")


def _strip_goal_verb(goal: str, verb: str) -> str:
    """Drop a leading action verb from a goal ("build Agent" → "Agent")."""
    stripped = goal.strip()
    prefix = verb + " "
    if stripped.lower().startswith(prefix.lower()):
        return stripped[len(prefix):].strip()
    return stripped


def _active_preference_query_candidates(snap: ProfileSnapshot) -> list[str]:
    candidates: list[str] = []
    for value in snap.preferences_personal + snap.preferences_professional + snap.dislikes:
        if _norm_cmp(value) not in {_norm_cmp(v) for v in candidates}:
            candidates.append(value)
    return candidates


def _looks_like_technical_concept(value: str) -> bool:
    stripped = re.sub(r"\s+", " ", value.strip())
    if stripped in _TECHNICAL_CONCEPT_PHRASES:
        return True
    tokens = stripped.split()
    if not tokens:
        return False
    return any(
        tok in _TECHNICAL_CONCEPT_TOKENS or re.fullmatch(r"[A-Z0-9]{2,}", tok)
        for tok in tokens
    )


def _edit_distance_at_most_one(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) <= 1
    if len(a) > len(b):
        a, b = b, a
    i = j = edits = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        j += 1
    return True


def canonicalize_known_preference_query_object(
    raw: str, active_candidates: list[str]
) -> str | None:
    """Return a known active preference object for a near-typo query, if unique.

    P0-7K-FIX5B keeps this memory-backed and conservative: only active preference/
    dislike objects are candidates, acronyms/concepts are excluded, and only one-edit
    matches are accepted. No person-name or global fuzzy search is performed.
    """
    raw_clean = canonicalize_known_preference_value(
        re.sub(r"\s+", " ", raw.strip()).strip()
    )
    raw_key = _norm_cmp(raw_clean)
    if not raw_key or len(raw_key) < 5 or _looks_like_technical_concept(raw_clean):
        return None
    exact_matches: list[str] = []
    for candidate in active_candidates:
        candidate_clean = re.sub(r"\s+", " ", candidate.strip()).strip()
        if _norm_cmp(candidate_clean) == raw_key:
            exact_matches.append(candidate_clean)
    exact_deduped: list[str] = []
    for match in exact_matches:
        if _norm_cmp(match) not in {_norm_cmp(v) for v in exact_deduped}:
            exact_deduped.append(match)
    if len(exact_deduped) == 1:
        return exact_deduped[0]
    if len(exact_deduped) > 1:
        return raw_clean
    matches: list[str] = []
    for candidate in active_candidates:
        candidate_clean = re.sub(r"\s+", " ", candidate.strip()).strip()
        candidate_key = _norm_cmp(candidate_clean)
        if (
            not candidate_key
            or candidate_key == raw_key
            or len(candidate_key) < 5
            or _looks_like_technical_concept(candidate_clean)
        ):
            continue
        if _edit_distance_at_most_one(raw_key, candidate_key):
            matches.append(candidate_clean)
    deduped: list[str] = []
    for match in matches:
        if _norm_cmp(match) not in {_norm_cmp(v) for v in deduped}:
            deduped.append(match)
    return deduped[0] if len(deduped) == 1 else None


def _canonicalize_preference_query_object(value: str, snap: ProfileSnapshot) -> str:
    value = canonicalize_known_preference_value(value)
    return (
        canonicalize_known_preference_query_object(
            value, _active_preference_query_candidates(snap)
        )
        or value
    )


def _preference_item_state(item: str, snap: ProfileSnapshot) -> str:
    """Return positive / negative / unknown for one preference query object."""
    target = _norm_cmp(item)
    pref_values = snap.preferences_personal + snap.preferences_professional
    # P0-7K-FIX5C-LITE C: a person object ("tôi có thích quý và may không?") resolves
    # against outgoing self-affection state, keeping positive/negative/unknown distinct.
    if any(_norm_cmp(v) == target for v in snap.negative_affections):
        return "negative"
    if any(_norm_cmp(v) == target for v in snap.affections):
        return "positive"
    if target in {_norm_cmp(v) for v in snap.dislikes} or any(
        _matches_preference_query(v, item) for v in snap.dislikes
    ):
        return "negative"
    if target in {_norm_cmp(v) for v in pref_values} or any(
        _matches_preference_query(v, item) for v in pref_values
    ):
        return "positive"
    if any(_matches_preference_query(winner, item) for winner, _loser in snap.comparatives):
        return "positive"
    if snap.favorite_food and _matches_preference_query(snap.favorite_food, item):
        return "positive"
    if snap.favorite_general and _matches_preference_query(snap.favorite_general, item):
        return "positive"
    return "unknown"


def _answer_batch_preference_yesno(items: list[str], snap: ProfileSnapshot) -> str:
    items = [_canonicalize_preference_query_object(item, snap) for item in items]
    positive: list[str] = []
    negative: list[str] = []
    unknown: list[str] = []
    for item in items:
        state = _preference_item_state(item, snap)
        if state == "positive":
            positive.append(item)
        elif state == "negative":
            negative.append(item)
        else:
            unknown.append(item)

    parts: list[str] = []
    if positive:
        if not negative and not unknown:
            return f"Có, bạn thích {_join_vietnamese_items(positive)}."
        parts.append(f"Bạn thích {_join_vietnamese_items(positive)}")
    if negative:
        if not positive and not unknown:
            return f"Không, bạn không thích {_join_vietnamese_items(negative)}."
        neg_text = f"không thích {_join_vietnamese_items(negative)}"
        parts.append(("nhưng " if positive else "Bạn ") + neg_text)
    if unknown:
        unknown_text = f"còn {_join_vietnamese_items(unknown)} thì mình chưa có thông tin"
        if positive or negative:
            return ", ".join(parts) + f"; {unknown_text}."
        return f"Mình chưa có thông tin về {_join_vietnamese_items(unknown)}."
    return ", ".join(parts) + "."


# P0-7K-FIX1 E: lightweight AI taxonomy — terms that count as "AI" for goal yes/no.
# Bounded allowlist, NOT a full ontology. Matched as substrings on the normalized value.
_AI_TAXONOMY_TERMS: tuple[str, ...] = (
    "ai", "llm", "slm", "agent ai", "ai agent", "ai agent coder",
    "machine learning", "ml", "deep learning", "học máy", "học sâu",
)


def _value_relates_to_ai(value: str) -> bool:
    """True if value names an AI-related goal/skill (lightweight taxonomy match)."""
    v = _norm_cmp(value)
    if not v:
        return False
    tokens = set(v.split())
    if "ai" in tokens or "ml" in tokens or "llm" in tokens or "slm" in tokens:
        return True
    return any(term in v for term in _AI_TAXONOMY_TERMS if " " in term)


def _value_answers_explicit_ai_yesno(value: str) -> bool:
    """AI yes/no query match that keeps plain ML as its own goal."""
    v = _norm_cmp(value)
    if not v:
        return False
    tokens = set(v.split())
    if "ai" in tokens or "llm" in tokens or "slm" in tokens:
        return True
    return any(term in v for term in ("agent ai", "ai agent", "ai agent coder", "deep learning", "học sâu"))


_GOAL_STOPWORDS: frozenset[str] = frozenset({
    "làm", "build", "dự", "án", "và", "cả", "xây", "dựng", "muốn", "sẽ", "định",
})


def _goal_challenge_terms(value: str) -> frozenset[str]:
    """Content tokens of a goal value, for challenge-query matching (verbs dropped)."""
    return frozenset(
        t for t in _norm_cmp(value).split() if t not in _GOAL_STOPWORDS
    )


def _positive_preference_terms(value: str) -> frozenset[str]:
    """Return bounded terms that a stored positive preference entails for yes/no queries.

    This is intentionally small and deterministic: it handles common food/drink prefixes,
    simple multi-item "cả A và B", and comparative "A hơn B" without implying the losing
    side B is liked.
    """
    v = _norm_cmp(value)
    if not v:
        return frozenset()
    terms: set[str] = {v}
    for prefix in ("uống ", "ăn "):
        if v.startswith(prefix):
            rest = v[len(prefix):].strip()
            if rest:
                terms.add(rest)
    if v.startswith("cả "):
        v = v[3:].strip()
        terms.add(v)
    if " hơn " in v:
        left = v.split(" hơn ", 1)[0].strip()
        if left:
            terms.add(left)
        return frozenset(terms)
    if " và " in v:
        for part in v.split(" và "):
            part = part.strip()
            if part:
                terms.add(part)
    if v.endswith(" không đường"):
        head = v[: -len(" không đường")].strip()
        if head:
            terms.add(head)
    return frozenset(terms)


def _preference_query_terms(value: str) -> frozenset[str]:
    v = _norm_cmp(value)
    if not v:
        return frozenset()
    terms = {v}
    for prefix in ("uống ", "ăn "):
        if v.startswith(prefix):
            rest = v[len(prefix):].strip()
            if rest:
                terms.add(rest)
    return frozenset(terms)


def _matches_preference_query(stored_value: str, query_value: str) -> bool:
    return bool(_positive_preference_terms(stored_value) & _preference_query_terms(query_value))


def collect_profile_snapshot(store: "MemoryStoreProtocol") -> ProfileSnapshot:
    """Aggregate all confirmed profile records into a categorized snapshot.

    Deterministic insertion-order ordering (by created_at) so query answers are stable.
    Reads FACT + PREFERENCE user_profile records; accepts v1 and v2 schemas.
    """
    records = list(store.search(MemoryQuery(
        text="", types=[MemoryType.FACT], tags=["user_profile"], limit=200,
    ))) + list(store.search(MemoryQuery(
        text="", types=[MemoryType.PREFERENCE], tags=["user_profile"], limit=200,
    )))
    confirmed = [
        r for r in records
        if r.metadata.get("confirmed")
        and r.metadata.get("profile_schema") in ("user_profile_fact_v1", "user_profile_fact_v2")
    ]
    confirmed.sort(key=lambda r: r.created_at)

    def _add(bucket: list[str], val: str) -> None:
        # Dedupe case-insensitively, preserving first-seen display form + insertion order.
        if _norm_cmp(val) not in {_norm_cmp(x) for x in bucket}:
            bucket.append(val)

    snap = ProfileSnapshot()
    for rec in confirmed:
        md = rec.metadata
        subject = md.get("subject", "")
        rel = md.get("relation", "")
        val = md.get("value", "")
        if not val:
            continue
        # P0-7K-FIX3 L: never surface a dirty object value (leftover reminder/predicate
        # pollution) in the snapshot, so summary and queries stay clean.
        if rel not in ("comparative",) and _is_dirty_value(val):
            continue
        if subject == "self" and rel == "name":
            # P0-7G: latest name wins (records are sorted ascending by created_at), so a
            # name update supersedes older values instead of keeping the first.
            # P0-7J: superseded names are kept as previous_names for old-name queries.
            if snap.name and _norm_cmp(snap.name) != _norm_cmp(val):
                _add(snap.previous_names, snap.name)
            snap.name = val
        elif subject == "self" and rel == "negative_preference":
            _add(snap.dislikes, val)
        elif subject == "self" and rel == "affection":
            _add(snap.affections, val)
        elif subject == "self" and rel == "negative_affection":
            _add(snap.negative_affections, val)
        elif subject == "external" and rel == "affection_to_user":
            _add(snap.external_affections, val)
        elif subject == "external" and rel == "affection_to_user_negative":
            _add(snap.negative_external_affections, val)
        elif subject == "self" and rel == "occupation":
            _add(snap.occupation, val)
        elif subject == "self" and rel == "skill":
            _add(snap.skills, val)
        elif subject == "self" and rel == "negative_skill":
            _add(snap.negative_skills, val)
        elif subject == "self" and rel == "learning_focus":
            _add(snap.learning, val)
        elif subject == "self" and rel == "goal":
            _add(snap.goals, val)
        elif subject == "self" and rel == "wants_to_marry":
            _add(snap.marry_targets, val)
        elif subject == "self" and rel == "goal_focus":
            # P0-7K-FIX1: latest focus wins; also recorded as an active goal.
            snap.current_focus = val
            _add(snap.goals, val)
        elif subject == "self" and rel == "favorite":
            # P0-7K-FIX2: latest favorite wins, per domain (food vs general).
            if md.get("favorite_domain") == "food":
                snap.favorite_food = val
            else:
                snap.favorite_general = val
        elif subject == "self" and rel == "comparative":
            loser = md.get("compared_to", "")
            pair = (val, loser)
            if pair not in snap.comparatives:
                snap.comparatives.append(pair)
        elif subject == "self" and rel == "preference":
            if _is_polluted_preference(val):
                continue
            if md.get("preference_kind") == "professional":
                _add(snap.preferences_professional, val)
            else:
                _add(snap.preferences_personal, val)
        elif subject == "self" and rel == "habit":
            _add(snap.habits, val)
        elif subject == "self" and rel == "household_pet":
            _add(snap.pets, val)
        elif subject == "relation" and rel == "name":
            label = md.get("relation_label", "người liên quan")
            if (label, val) not in snap.relations:
                snap.relations.append((label, val))
    # P0-7J: a re-adopted name is current again, not a previous name.
    if snap.name:
        current = _norm_cmp(snap.name)
        snap.previous_names = [n for n in snap.previous_names if _norm_cmp(n) != current]
    # P0-7K-FIX1/FIX4: a negated skill is never a known skill; latest-polarity wins so a
    # positive skill also removes it from the negative list (no contradiction in snapshot).
    if snap.negative_skills:
        pos = {_norm_cmp(s) for s in snap.skills}
        snap.negative_skills = [s for s in snap.negative_skills if _norm_cmp(s) not in pos]
        neg = {_norm_cmp(s) for s in snap.negative_skills}
        snap.skills = [s for s in snap.skills if _norm_cmp(s) not in neg]
    # P0-7K-FIX1: if the current focus was later removed as a goal, drop the stale focus.
    if snap.current_focus and _norm_cmp(snap.current_focus) not in {
        _norm_cmp(g) for g in snap.goals
    }:
        snap.current_focus = None
    # P0-7K-FIX4 A: a comparative winner ("thích A hơn B") is an active positive
    # preference — project it into the preference snapshot so "tôi thích gì?" answers it.
    for winner, _loser in snap.comparatives:
        _add(snap.preferences_personal, winner)
    return snap


def _answer_entity_lookup(name: str, store: "MemoryStoreProtocol") -> str | None:
    """Resolve "Quý là ai?" / "ai là Quý?" against known entities (P0-7G).

    Prefers explicit relationship labels over weaker affection labels, then external
    affection, then the user's own name. Returns None when the entity is unknown so the
    caller can fall through to the router (unchanged for unknown inverse lookups).
    """
    lookup = _norm_cmp(name)
    if not lookup:
        return None
    snap = collect_profile_snapshot(store)
    for label, val in snap.relations:
        if _norm_cmp(val) == lookup:
            return f"{val} là {label} của bạn."
    for val in snap.affections:
        if _norm_cmp(val) == lookup:
            return f"{val} là người bạn thích/quan tâm."
    for val in snap.external_affections:
        if _norm_cmp(val) == lookup:
            return f"{val} là người có tình cảm với bạn (theo thông tin bạn cung cấp)."
    if snap.name and _norm_cmp(snap.name) == lookup:
        return f"{snap.name} là tên của bạn."
    # P0-7J: old-name lookup ("Bắc là ai?" after the user renamed to bb).
    for val in snap.previous_names:
        if _norm_cmp(val) == lookup:
            suffix = (
                f" Hiện tại mình đang nhớ tên bạn là {snap.name}." if snap.name else ""
            )
            return f"{val} là tên cũ/tên trước đây của bạn.{suffix}"
    return None


# P0-7K-HOTFIX1 B: a self-name alias resolver used in every user-memory query path.
def _resolves_to_user(token: str, snap: "ProfileSnapshot") -> bool:
    """True if token refers to the current user: a self-word, the current name, or an
    old/previous self-name alias."""
    low = token.strip().lower()
    if low in _SELF_WORDS:
        return True
    tnorm = _norm_cmp(token)
    if snap.name and _norm_cmp(snap.name) == tnorm:
        return True
    return any(_norm_cmp(n) == tnorm for n in snap.previous_names)


def _self_alias_prefix(token: str, snap: "ProfileSnapshot") -> str:
    """Return a short clarifying prefix when a self-name alias was used as the subject."""
    low = token.strip().lower()
    if low in _SELF_WORDS:
        return ""
    tnorm = _norm_cmp(token)
    if snap.name and _norm_cmp(snap.name) == tnorm:
        return f"{token} là bạn."
    if any(_norm_cmp(n) == tnorm for n in snap.previous_names):
        return f"{token} là tên cũ của bạn."
    return ""


def _answer_named_affection_yesno(
    subject: str, obj: str, store: "MemoryStoreProtocol"
) -> str:
    """Answer "Bắc có thích Quý không?" by mapping the saved self-name to the user (P0-7G).

    - subject == user  → "do I like OBJ?"   → answer from affection memory.
    - object  == user  → "does SUBJ like me?" → answer from external affection memory.
    - neither is the user → unrelated third parties; do not infer.
    """
    snap = collect_profile_snapshot(store)

    subj_user = _resolves_to_user(subject, snap)
    obj_user = _resolves_to_user(obj, snap)

    if subj_user and not obj_user:
        # "do I (the user, possibly named by an alias) like OBJ?" — delegate to the full
        # preference/affection resolver so batch objects and retracted affections resolve.
        prefix = _self_alias_prefix(subject, snap)
        answer = answer_yes_no_memory_query("preference", obj, store)
        return (prefix + " " + answer).strip() if prefix else answer
    if obj_user and not subj_user:
        # "does SUBJ like me?" — external affection (positive/negative/unknown).
        if any(_norm_cmp(subject) == _norm_cmp(v) for v in snap.external_affections):
            return f"Có, theo thông tin bạn cung cấp thì {subject} thích bạn."
        if any(_norm_cmp(subject) == _norm_cmp(v) for v in snap.negative_external_affections):
            return f"Không, theo thông tin bạn cung cấp thì {subject} không thích bạn."
        return (
            f"Mình không biết {subject} có thích bạn hay không nếu bạn chưa cung cấp "
            "thông tin đó."
        )
    # Neither side is the current user → do not infer for unrelated third parties.
    return "Mình chưa có thông tin về việc này."


def answer_profile_query(
    query: ProfileQuery,
    store: "MemoryStoreProtocol",
) -> str | None:
    """Return an answer string if a confirmed fact satisfies the query.

    Returns None only for profile_summary when the store has no confirmed facts
    (caller gates profile_summary on session count before calling).
    For all other query kinds: returns either the found value or a category-specific
    unknown-state message so the caller always gets a non-None response.
    """
    # Always fetch FACTs (covers v1 and v2 non-preference kinds)
    fact_records = list(store.search(MemoryQuery(
        text="",
        types=[MemoryType.FACT],
        tags=["user_profile"],
        limit=100,
    )))

    # Fetch PREFERENCEs only for kinds that need them
    pref_records: list = []
    if query.kind in ("self_preference", "profile_summary"):
        pref_records = list(store.search(MemoryQuery(
            text="",
            types=[MemoryType.PREFERENCE],
            tags=["user_profile"],
            limit=100,
        )))

    all_records = fact_records + pref_records
    # Backward-compatible: accept both v1 (confirmed) and v2 (auto_safe) schemas.
    confirmed = [
        r for r in all_records
        if r.metadata.get("confirmed")
        and r.metadata.get("profile_schema") in ("user_profile_fact_v1", "user_profile_fact_v2")
    ]

    # --- self_name / self_identity ---
    if query.kind in ("self_name", "self_identity"):
        # P0-7G: use the snapshot so the LATEST name (after any update) is returned.
        name = collect_profile_snapshot(store).name
        if name:
            return f"Bạn tên là {name}."
        return "Tôi chưa biết tên bạn."

    # --- relation_name ---
    elif query.kind == "relation_name":
        lookup_labels = _get_lookup_labels(query.relation_label)
        for rec in confirmed:
            stored_label = rec.metadata.get("relation_label", "")
            if (
                rec.metadata.get("subject") == "relation"
                and rec.metadata.get("relation") == "name"
                and stored_label in lookup_labels
            ):
                name = rec.metadata.get("value", "")
                display_label = stored_label or query.relation_label or ""
                return f"{display_label.capitalize()} của bạn tên là {name}."
        # P0-7F: no relation fact → specific unknown-state answer (was: fall through to a
        # generic user-memory fallback, which read as "I don't support memory").
        label = query.relation_label or "người yêu/bạn gái"
        return f"Tôi chưa có thông tin về {label} của bạn."

    # --- inverse_value / reverse_entity (P0-7G): "Quý là ai?" / "ai là Quý?" ---
    elif query.kind in ("inverse_value", "reverse_entity"):
        return _answer_entity_lookup(query.value or "", store)

    # --- profile_summary (P0-7F: grouped, stable-order snapshot) ---
    elif query.kind == "profile_summary":
        snap = collect_profile_snapshot(store)
        lines: list[str] = []
        if snap.name:
            lines.append(f"- Bạn tên là {snap.name}.")
        if snap.occupation:
            lines.append(f"- Công việc/lĩnh vực của bạn là {', '.join(snap.occupation)}.")
        if snap.skills:
            lines.append(f"- Bạn biết {', '.join(snap.skills)}.")
        if snap.learning:
            lines.append(f"- Bạn đang học {', '.join(snap.learning)}.")
        if snap.goals:
            lines.append(f"- Mục tiêu của bạn là {', '.join(snap.goals)}.")
        if snap.preferences_personal:
            lines.append(f"- Bạn thích {', '.join(snap.preferences_personal)}.")
        if snap.preferences_professional:
            lines.append(
                f"- Bạn quan tâm đến {', '.join(snap.preferences_professional)} "
                "ở mảng công việc/kỹ thuật."
            )
        if snap.habits:
            lines.append(f"- Bạn hay {', '.join(snap.habits)}.")
        if snap.pets:
            lines.append(f"- Nhà bạn có nuôi {', '.join(snap.pets)}.")
        # P0-7K-FIX1/FIX2: negative skills and favorites/comparatives shown distinctly.
        if snap.negative_skills:
            lines.append(f"- Bạn không biết {', '.join(snap.negative_skills)}.")
        if snap.favorite_food:
            lines.append(f"- Món bạn thích ăn nhất là {snap.favorite_food}.")
        if snap.favorite_general:
            lines.append(f"- Điều bạn thích nhất là {snap.favorite_general}.")
        for winner, loser in snap.comparatives:
            lines.append(f"- Bạn thích {winner} hơn {loser}.")
        # P0-7G: dislikes shown separately from positive likes.
        if snap.dislikes:
            for item in snap.dislikes:
                lines.append(f"- Bạn không thích {item}.")
        if snap.affections:
            lines.append(f"- Bạn thích/quan tâm đến {', '.join(snap.affections)}.")
        if snap.external_affections:
            lines.append(
                f"- Theo thông tin bạn cung cấp, {', '.join(snap.external_affections)} "
                "thích bạn."
            )
        for label, name in snap.relations:
            lines.append(f"- {label.capitalize()} của bạn tên là {name}.")
        if not lines:
            return "Tôi chưa nhớ thông tin hồ sơ nào đã được xác nhận về bạn."
        return "Tôi đang nhớ những thông tin sau về bạn:\n" + "\n".join(lines)

    # --- P0-7D: self_occupation — aggregate all confirmed occupation records (P0-7H-FIX3) ---
    elif query.kind == "self_occupation":
        snap = collect_profile_snapshot(store)
        if not snap.occupation:
            return "Tôi chưa có thông tin về nghề nghiệp/vai trò của bạn."
        return "Mình đang nhớ công việc/lĩnh vực của bạn là " + ", ".join(snap.occupation) + "."

    # --- P0-7I: self_occupation_yesno ("tôi có phải là AI không?") ---
    elif query.kind == "self_occupation_yesno":
        snap = collect_profile_snapshot(store)
        target = _norm_cmp(query.value or "")
        occ_norm = [_norm_cmp(o) for o in snap.occupation]
        if target and target in occ_norm:
            return f"Có, mình đang nhớ bạn là {query.value}."
        return f"Không, hiện mình không có thông tin bạn là {query.value}."

    # --- P0-7K-FIX1 J / P0-7K-FIX2 B: self_preference_ranking ("tôi thích gì nhất") ---
    elif query.kind == "self_preference_ranking":
        snap = collect_profile_snapshot(store)
        # A stored general (or food) favorite answers directly.
        fav = snap.favorite_general or snap.favorite_food
        if fav:
            return f"Mình đang nhớ bạn thích {fav} nhất."
        likes = snap.preferences_personal + snap.preferences_professional
        if likes:
            return (
                "Mình chưa đủ thông tin để biết bạn thích gì NHẤT, nhưng mình đang nhớ "
                "bạn thích: " + ", ".join(likes) + "."
            )
        return "Mình chưa đủ thông tin để biết bạn thích gì nhất."

    # --- P0-7K-FIX2 A/B: self_food_favorite ("tôi thích ăn gì nhất?") ---
    elif query.kind == "self_food_favorite":
        snap = collect_profile_snapshot(store)
        if snap.favorite_food:
            return f"Mình đang nhớ món bạn thích ăn nhất là {snap.favorite_food}."
        return "Mình chưa đủ thông tin để biết bạn thích ăn gì nhất."

    # --- P0-7K-FIX2 C: self_comparative ("tôi thích A hay B hơn?") ---
    elif query.kind == "self_comparative":
        snap = collect_profile_snapshot(store)
        a_value = _canonicalize_preference_query_object(query.value or "", snap)
        b_value = _canonicalize_preference_query_object(query.object_value or "", snap)
        a = _norm_cmp(a_value)
        b = _norm_cmp(b_value)
        for winner, loser in snap.comparatives:
            w, l = _norm_cmp(winner), _norm_cmp(loser)
            if {a, b} == {w, l}:
                return f"Bạn thích {winner} hơn {loser}."
        return (
            f"Mình chưa đủ thông tin để so sánh {a_value} và {b_value}."
        )

    # --- P0-7K-FIX2 H: self_food_preference ("tôi thích ăn gì?") ---
    elif query.kind == "self_food_preference":
        snap = collect_profile_snapshot(store)
        foods = [
            v for v in (snap.preferences_personal + snap.preferences_professional)
            if _norm_cmp(v).startswith(("ăn ", "uống "))
        ]
        if snap.favorite_food and snap.favorite_food not in foods:
            foods = [snap.favorite_food] + foods
        if foods:
            return "Bạn thích " + ", ".join(foods) + "."
        return "Mình chưa có thông tin về món ăn bạn thích."

    # --- P0-7K-FIX2 H: self_food_dislike ("tôi không thích ăn gì?") ---
    elif query.kind == "self_food_dislike":
        snap = collect_profile_snapshot(store)
        foods = [d for d in snap.dislikes if _norm_cmp(d).startswith(("ăn ", "uống "))]
        if foods:
            return "Bạn không thích " + ", ".join(foods) + "."
        return "Mình chưa có thông tin về món ăn bạn không thích."

    # --- P0-7K-FIX1 E: self_ai_yesno ("tôi có làm AI không?") — via AI taxonomy ---
    elif query.kind == "self_ai_yesno":
        snap = collect_profile_snapshot(store)
        ai_goals = [g for g in snap.goals if _value_answers_explicit_ai_yesno(g)]
        ai_occ = [o for o in snap.occupation if _value_answers_explicit_ai_yesno(o)]
        related = ai_goals + ai_occ
        if related:
            return (
                "Có, vì bạn có mục tiêu/công việc liên quan đến AI: "
                + ", ".join(related) + "."
            )
        return "Không, hiện mình chưa thấy bạn có mục tiêu hay công việc liên quan đến AI."

    # --- P0-7K-FIX1 G: goal_challenge ("bạn không nhớ tôi sẽ làm X à?") ---
    elif query.kind == "goal_challenge":
        snap = collect_profile_snapshot(store)
        target_terms = _goal_challenge_terms(query.value or "")
        matched = [
            g for g in snap.goals
            if target_terms & _goal_challenge_terms(g)
        ]
        if matched:
            others = [g for g in snap.goals if g not in matched]
            reply = "Có, mình đang nhớ bạn muốn " + ", ".join(matched) + "."
            if others:
                reply += " Mình cũng đang nhớ bạn muốn " + ", ".join(others) + "."
            return reply
        if snap.goals:
            return (
                f"Mình chưa thấy mục tiêu {query.value} trong hồ sơ, nhưng mình đang nhớ "
                "bạn muốn " + ", ".join(snap.goals) + "."
            )
        return f"Mình chưa lưu mục tiêu nào về {query.value}."

    # --- P0-7K-FIX1 H: goal_followup ("và gì nữa?") — runtime supplies remaining goals ---
    elif query.kind == "goal_followup":
        snap = collect_profile_snapshot(store)
        if snap.goals:
            return "Mình đang nhớ bạn muốn " + ", ".join(snap.goals) + "."
        return "Hiện mình không nhớ thêm mục tiêu nào khác của bạn."

    # --- P0-7D/7F: self_preference — aggregate ALL preferences (personal + professional) ---
    elif query.kind == "self_preference":
        snap = collect_profile_snapshot(store)
        if not snap.preferences_personal and not snap.preferences_professional:
            return "Mình chưa có thông tin về sở thích của bạn."
        parts: list[str] = []
        if snap.preferences_personal:
            parts.append(
                "Tôi đang nhớ bạn thích:\n"
                + "\n".join(f"- {v}" for v in snap.preferences_personal)
            )
        if snap.preferences_professional:
            parts.append(
                "Bạn cũng quan tâm đến mảng công việc/kỹ thuật:\n"
                + "\n".join(f"- {v}" for v in snap.preferences_professional)
            )
        return "\n\n".join(parts)

    # --- P0-7F: self_skill ---
    elif query.kind == "self_skill":
        snap = collect_profile_snapshot(store)
        if not snap.skills:
            return "Tôi chưa có thông tin về kỹ năng của bạn."
        return "Bạn biết " + ", ".join(snap.skills) + "."

    # --- P0-7K-FIX2 E: self_negative_skill ("tôi không biết gì?") ---
    elif query.kind == "self_negative_skill":
        snap = collect_profile_snapshot(store)
        if not snap.negative_skills:
            return "Mình chưa có thông tin về những việc bạn không biết làm."
        return "Bạn không biết " + ", ".join(snap.negative_skills) + "."

    # --- P0-7D: self_learning_focus ---
    elif query.kind == "self_learning_focus":
        for rec in confirmed:
            if rec.metadata.get("subject") == "self" and rec.metadata.get("relation") == "learning_focus":
                val = rec.metadata.get("value", "")
                return f"Bạn đang học {val}."
        return "Tôi chưa có thông tin về nội dung bạn đang học."

    # --- P0-7D: self_goal ---
    elif query.kind == "self_goal":
        for rec in confirmed:
            if rec.metadata.get("subject") == "self" and rec.metadata.get("relation") == "goal":
                val = rec.metadata.get("value", "")
                return f"Mục tiêu của bạn là {val}."
        return "Tôi chưa có thông tin về mục tiêu của bạn."

    # --- P0-7J / P0-7K-FIX1: self_current_goal ("tôi đang muốn làm gì?") ---
    # P0-7K-FIX1: goal memory is an active MULTI-goal set — list all active goals.
    # If a current focus is set, mention it first while still listing the rest.
    elif query.kind == "self_current_goal":
        snap = collect_profile_snapshot(store)
        if not snap.goals:
            return "Mình chưa có thông tin về dự định hiện tại của bạn."
        if snap.current_focus:
            others = [g for g in snap.goals if _norm_cmp(g) != _norm_cmp(snap.current_focus)]
            reply = f"Mục tiêu chính hiện tại của bạn là {snap.current_focus}."
            if others:
                reply += " Bạn cũng đang muốn làm " + ", ".join(others) + "."
            return reply
        return "Mình đang nhớ bạn đang muốn " + ", ".join(snap.goals) + "."

    # --- P0-7K-FIX6-LITE: wants_to_marry_query ("tôi muốn cưới ai?") ---
    elif query.kind == "wants_to_marry_query":
        snap = collect_profile_snapshot(store)
        if snap.marry_targets:
            return "Bạn từng nói muốn cưới " + _join_vietnamese_items(snap.marry_targets) + "."
        return "Mình chưa thấy bạn nói rõ muốn cưới ai."

    # --- P0-7K-FIX6-LITE: wants_to_learn_query ("tôi muốn học gì?") ---
    elif query.kind == "wants_to_learn_query":
        snap = collect_profile_snapshot(store)
        topics = [_strip_goal_verb(g, "học") for g in snap.goals if _goal_has_verb(g, "học")]
        if topics:
            return "Bạn muốn học " + _join_vietnamese_items(topics) + "."
        return "Mình chưa thấy bạn nói rõ muốn học gì."

    # --- P0-7K-FIX6-LITE: wants_to_build_query ("tôi muốn build gì?") ---
    elif query.kind == "wants_to_build_query":
        snap = collect_profile_snapshot(store)
        targets = [_strip_goal_verb(g, "build") for g in snap.goals if _goal_has_verb(g, "build")]
        if targets:
            return "Bạn muốn build " + _join_vietnamese_items(targets) + "."
        return "Mình chưa thấy bạn nói rõ muốn build gì."

    # --- P0-7J-FIX1: self_do_yesno ("tôi có làm LLM nữa không?") ---
    elif query.kind == "self_do_yesno":
        snap = collect_profile_snapshot(store)
        target = _norm_cmp(query.value or "")
        target_tokens = set(target.split())
        if target_tokens:
            for occ in snap.occupation:
                occ_tokens = set(_norm_cmp(occ).split())
                if target_tokens <= occ_tokens or occ_tokens <= target_tokens:
                    return f"Có, mình đang nhớ bạn đang làm {occ}."
            for goal in snap.goals:
                goal_key = _norm_cmp(goal)
                for verb in ("làm ", "build "):
                    if goal_key.startswith(verb):
                        goal_key = goal_key[len(verb):].strip()
                goal_tokens = set(goal_key.split())
                if target_tokens <= goal_tokens or goal_tokens <= target_tokens:
                    return f"Có, mình đang nhớ bạn đang muốn {goal}."
        return (
            f"Không, hiện tại mình không thấy bạn còn làm hay dự định làm {query.value}."
        )

    # --- P0-7J: old_name_confirm ("Bắc là tên cũ của tôi, bạn còn nhớ không?") ---
    elif query.kind == "old_name_confirm":
        snap = collect_profile_snapshot(store)
        target = _norm_cmp(query.value or "")
        if any(_norm_cmp(n) == target for n in snap.previous_names):
            suffix = (
                f" Hiện tại mình đang nhớ tên bạn là {snap.name}." if snap.name else ""
            )
            return f"Đúng, mình còn nhớ: {query.value} là tên cũ của bạn.{suffix}"
        if snap.name and _norm_cmp(snap.name) == target:
            return (
                f"Mình đang nhớ {query.value} là tên hiện tại của bạn, "
                "không phải tên cũ."
            )
        return f"Mình chưa có thông tin {query.value} từng là tên của bạn."

    # --- P0-7E: self_habit ---
    elif query.kind == "self_habit":
        for rec in confirmed:
            if rec.metadata.get("subject") == "self" and rec.metadata.get("relation") == "habit":
                val = rec.metadata.get("value", "")
                return f"Bạn hay {val}."
        return "Tôi chưa có thông tin về thói quen/lifestyle của bạn."

    # --- P0-7D: relation_existence ---
    elif query.kind == "relation_existence":
        lookup_labels = _get_lookup_labels(query.relation_label) or frozenset({query.relation_label or ""})
        for rec in confirmed:
            stored_label = rec.metadata.get("relation_label", "")
            if (
                rec.metadata.get("subject") == "relation"
                and rec.metadata.get("relation") == "name"
                and stored_label in lookup_labels
            ):
                name = rec.metadata.get("value", "")
                return f"Bạn có {stored_label} tên là {name}."
        return "Tôi chưa có thông tin về việc này."

    # --- P0-7H: relation_yesno ("Quý có phải là bạn gái của tôi không?") ---
    elif query.kind == "relation_yesno":
        lookup_labels = _get_lookup_labels(query.relation_label) or frozenset({query.relation_label or ""})
        for rec in confirmed:
            stored_label = rec.metadata.get("relation_label", "")
            if (
                rec.metadata.get("subject") == "relation"
                and rec.metadata.get("relation") == "name"
                and stored_label in lookup_labels
            ):
                stored_name = rec.metadata.get("value", "")
                label = stored_label or query.relation_label or ""
                if _norm_cmp(stored_name) == _norm_cmp(query.value or ""):
                    return f"Có, {label} của bạn tên là {stored_name}."
                return f"Không, {label} của bạn là {stored_name}, không phải {query.value}."
        return "Tôi chưa có thông tin về việc này."

    # --- P0-7F-FIX2 / P0-7G: self_affection ("tôi thích ai?") ---
    elif query.kind == "self_affection":
        snap = collect_profile_snapshot(store)
        # P0-7G: prefer a first-class affection fact, then affection-type relationships.
        # P0-7J-FIX1: ALL active affection targets are returned, not only the first.
        if snap.affections:
            if len(snap.affections) == 1:
                return f"Mình đang nhớ {snap.affections[0]} là người bạn thích/quan tâm."
            return (
                "Mình đang nhớ những người bạn thích/quan tâm: "
                + ", ".join(snap.affections) + "."
            )
        _AFFECTION_LABELS = frozenset({"người yêu", "bạn gái", "bạn trai", "partner", "vợ", "chồng"})
        affection_vals = [name for label, name in snap.relations if label in _AFFECTION_LABELS]
        if affection_vals:
            return f"Mình đang nhớ {affection_vals[0]} là người bạn thích/quan tâm."
        return "Mình chưa có thông tin về người bạn thích."

    # --- P0-7F-FIX3 / P0-7G: third_party_affection ("quý có thích tôi không?") ---
    elif query.kind == "third_party_affection":
        subject = query.value or "người đó"
        snap = collect_profile_snapshot(store)
        # P0-7G: answer from a user-reported external affection fact if one exists.
        if any(_norm_cmp(subject) == _norm_cmp(v) for v in snap.external_affections):
            return f"Có, theo thông tin bạn cung cấp thì {subject} thích bạn."
        # P0-7K-HOTFIX1 D: negative external affection ("Quý không thích tôi").
        if any(_norm_cmp(subject) == _norm_cmp(v) for v in snap.negative_external_affections):
            return f"Không, theo thông tin bạn cung cấp thì {subject} không thích bạn."
        return (
            f"Mình không biết {subject} có thích bạn hay không nếu bạn chưa cung cấp "
            "thông tin đó."
        )

    # --- P0-7G: named_affection_yesno ("Bắc có thích Quý không?") ---
    elif query.kind == "named_affection_yesno":
        return _answer_named_affection_yesno(
            query.value or "", query.object_value or "", store
        )

    # --- P0-7K-FIX5C-LITE A: incoming_affection_set ("ai đang thích tôi?") ---
    elif query.kind == "incoming_affection_set":
        snap = collect_profile_snapshot(store)
        positives = list(snap.external_affections)
        negatives = list(snap.negative_external_affections)
        if positives:
            answer = (
                f"{_join_vietnamese_items(positives)} đang thích bạn theo thông tin "
                "bạn cung cấp."
            )
            if negatives:
                answer += (
                    f" {_join_vietnamese_items(negatives)} thì theo thông tin bạn "
                    "cung cấp là không thích bạn."
                )
            return answer
        if negatives:
            return (
                f"Theo thông tin bạn cung cấp, {_join_vietnamese_items(negatives)} "
                "không thích bạn. Ngoài ra mình chưa có thông tin về ai đang thích bạn."
            )
        return "Mình chưa có thông tin về người đang thích bạn."

    # --- P0-7K-FIX5C-LITE B: batch_incoming_affection ("Quý và May có thích tôi không?") ---
    elif query.kind == "batch_incoming_affection":
        snap = collect_profile_snapshot(store)
        if not _resolves_to_user(query.object_value or "", snap):
            # Object is not the user → person↔person, out of this lite core's scope.
            return "Mình chưa có thông tin về việc này."
        subjects = _split_person_subjects(query.value or "")
        pos, neg, unknown = [], [], []
        for subj in subjects:
            if any(_norm_cmp(subj) == _norm_cmp(v) for v in snap.external_affections):
                pos.append(subj)
            elif any(_norm_cmp(subj) == _norm_cmp(v) for v in snap.negative_external_affections):
                neg.append(subj)
            else:
                unknown.append(subj)
        if pos and not neg and not unknown:
            return (
                f"Có, theo thông tin bạn cung cấp thì {_join_vietnamese_items(pos)} "
                "thích bạn."
            )
        parts: list[str] = []
        if pos:
            parts.append(f"{_join_vietnamese_items(pos)} thích bạn")
        if neg:
            parts.append(f"{_join_vietnamese_items(neg)} không thích bạn")
        if unknown:
            parts.append(f"còn {_join_vietnamese_items(unknown)} thì mình chưa có thông tin")
        return "; ".join(parts) + "."

    # --- P0-7K-FIX5C-LITE F: person_affection_target ("May thích ai?") ---
    elif query.kind == "person_affection_target":
        subject = query.value or "người đó"
        snap = collect_profile_snapshot(store)
        # An old/current self alias as the subject ("bắc thích ai?") asks the self lane.
        if _resolves_to_user(subject, snap):
            if snap.affections:
                return (
                    "Bạn đang thích " + _join_vietnamese_items(snap.affections) + "."
                )
            return "Mình chưa có thông tin về người bạn thích."
        if any(_norm_cmp(subject) == _norm_cmp(v) for v in snap.external_affections):
            return f"Theo thông tin bạn cung cấp, {subject} thích bạn."
        if any(_norm_cmp(subject) == _norm_cmp(v) for v in snap.negative_external_affections):
            return f"Theo thông tin bạn cung cấp, {subject} không thích bạn."
        return f"Mình chưa có thông tin về người mà {subject} thích."

    # --- P0-7F-FIX4 Part C: friend_name ("bạn của tôi tên là gì?") ---
    elif query.kind == "friend_name":
        # P0-7G-FIX3A: return the LATEST friend name (by created_at) so a newer friend
        # assertion supersedes an older one, mirroring self-name last-write-wins.
        friends = [
            rec for rec in confirmed
            if rec.metadata.get("subject") == "relation"
            and rec.metadata.get("relation") == "name"
            and rec.metadata.get("relation_label") == "bạn"
        ]
        if friends:
            latest = sorted(friends, key=lambda r: r.created_at)[-1]
            return f"Bạn của bạn tên là {latest.metadata.get('value', '')}."
        return "Mình chưa có thông tin về tên bạn của bạn."

    # --- P0-7G-FIX3 A3: self_dislike ("tôi không thích gì?") ---
    elif query.kind == "self_dislike":
        snap = collect_profile_snapshot(store)
        if snap.dislikes:
            return "Bạn không thích " + ", ".join(snap.dislikes) + "."
        return "Mình chưa có thông tin về những thứ bạn không thích."

    # --- P0-7F-FIX4 Part D: self_pet ("nhà tôi nuôi con gì?") ---
    elif query.kind == "self_pet":
        snap = collect_profile_snapshot(store)
        if snap.pets:
            return f"Nhà bạn có nuôi {', '.join(snap.pets)}."
        return "Mình chưa có thông tin về vật nuôi trong nhà bạn."

    # --- P0-7F-FIX5 Part C: self_pet_yesno ("tôi có nuôi mèo không?") ---
    elif query.kind == "self_pet_yesno":
        snap = collect_profile_snapshot(store)
        target = _norm_cmp(query.value or "")
        pets_norm = [_norm_cmp(p) for p in snap.pets]
        matched = bool(target) and any(
            target == p or target in p.split() or p in target.split()
            for p in pets_norm
        )
        if matched:
            return f"Có, mình đang nhớ nhà bạn có nuôi {query.value}."
        return f"Mình chưa thấy thông tin rằng nhà bạn có nuôi {query.value}."

    # --- P0-7F-FIX2: self_drink_preference ("tôi thích uống gì?") ---
    elif query.kind == "self_drink_preference":
        snap = collect_profile_snapshot(store)
        drink_prefs = [
            v for v in snap.preferences_personal
            if v.lower().startswith("uống ") or v.lower().startswith("ăn ")
        ]
        if drink_prefs:
            return "Bạn thích " + ", ".join(drink_prefs) + "."
        return "Mình chưa có thông tin về đồ uống/ăn bạn thích."

    return None

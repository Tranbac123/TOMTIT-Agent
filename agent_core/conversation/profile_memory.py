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
    "kỹ sư", "lập trình", "bác sĩ", "giáo viên", "chuyên gia",
    "nhà nghiên cứu", "nhà thiết kế", "giám đốc", "kế toán", "nhà báo",
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


def _has_role_keyword(value: str) -> bool:
    """True if value contains a known role/profession keyword.

    Single-word keywords are matched against whole ASCII tokens (so "ai enginer" matches
    but "con trai" does not); multi-word phrases are matched as substrings.
    """
    value_lower = value.lower()
    if any(phrase in value_lower for phrase in _ROLE_KEYWORD_PHRASES):
        return True
    tokens = _RE_ASCII_TOKEN.findall(value_lower)
    return any(tok in _ROLE_KEYWORD_TOKENS for tok in tokens)


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


def _is_valid_auto_value_shape(value: str) -> bool:
    """True if value has a meaningful, non-vague, bounded SHAPE (ignores safety).

    P0-7E splits shape from safety so the runtime can distinguish "not a profile claim"
    (shape invalid) from "a profile claim carrying an unsafe value" (shape valid but
    blocked) — the latter gets a specific safety response instead of a generic fallback.
    """
    v = value.strip()
    if not v or len(v) < 3 or len(v) > 80:
        return False
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
_RE_SKILL_Q = re.compile(
    (
        r'^(?:'
        r'(?:tôi|mình)\s+biết\s+(?:làm\s+)?gì'
        r'|(?:tôi|mình)\s+có\s+(?:những\s+)?kỹ\s+năng\s+gì'
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
_RE_AFFECTION_Q = re.compile(
    r'^(?:tôi|mình)\s+(?:thích|yêu|crush)\s+(?-i:ai)\s*[?？]?\s*$',
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
_RE_NAMED_AFFECTION_YESNO_Q = re.compile(
    r'^(\S+)\s+có\s+(?:thích|yêu|thương|quý)\s+(\S+)\s+'
    r'(?:không|ko|hông|hong|chưa)\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7G: reverse entity lookup — "ai là Quý?" (the mirror of "Quý là ai?").
_RE_REVERSE_ENTITY_Q = re.compile(
    r'^ai\s+là\s+([^\s?？]+)\s*[?？]?\s*$',
    re.IGNORECASE,
)

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

    # 7. P0-7F-FIX2: affection query ("tôi thích ai?") — before general preference query.
    #    P0-7F-FIX5 Part D adds the "người tôi thích là ai?" alias to the same lane.
    if _RE_AFFECTION_Q.match(stripped) or _RE_AFFECTION_ALIAS_Q.match(stripped):
        return ProfileQuery(kind="self_affection")

    # 7b. P0-7F-FIX2: drink/food preference query ("tôi thích uống gì?")
    if _RE_DRINK_PREF_Q.match(stripped):
        return ProfileQuery(kind="self_drink_preference")

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

    # 9. P0-7D: goal query
    if _RE_GOAL_Q.match(stripped):
        return ProfileQuery(kind="self_goal")

    # 9b. P0-7E: habit query
    if _RE_HABIT_Q.match(stripped):
        return ProfileQuery(kind="self_habit")

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
            if _is_valid_auto_value_shape(value):
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
    return (
        f"Đã nhớ là bạn không thích {value}. Mình sẽ tính đến điều này khi gợi ý "
        "những việc liên quan."
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
        if raw_target == "ai":
            # P0-7G: lowercase "ai" is the person question word — route to affection state.
            if snap.affections:
                return f"Có, mình đang nhớ là bạn thích {snap.affections[0]}."
            return "Mình chưa có thông tin về người bạn thích."
        # P0-7G: person affection ("tôi có thích Quý không?") answers from affection memory.
        if target in affections:
            return f"Có, mình đang nhớ là bạn thích {value}."
        # P0-7G: durable dislike ("tôi có thích ăn cá không?" after "tôi không thích ăn cá").
        if target in dislikes or any(_matches_preference_query(v, value) for v in snap.dislikes):
            return f"Không, bạn từng nói là không thích {value}."
        if target in prefs or any(_matches_preference_query(v, value) for v in pref_values):
            return f"Có, mình đang nhớ bạn thích {value}."
        if target in skills:
            return (
                f'Mình đang nhớ bạn biết {value}, nhưng chưa lưu "{value}" như một sở thích.'
            )
        return f"Mình chưa thấy thông tin rằng bạn thích {value}."

    if category == "skill":
        if target in skills:
            return f"Đúng, mình đang nhớ bạn biết {value}."
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

    tags = ["user_profile", "self", candidate.relation]
    if candidate.relation == "preference":
        tags.append("interest")

    metadata: dict = {
        "profile_schema": "user_profile_fact_v2",
        "subject": "self",
        "relation": candidate.relation,
        "value": candidate.value,
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
        "occupation": f"bạn là {candidate.value}",
        "preference": f"bạn thích {candidate.value}",
        "goal": f"mục tiêu của bạn là {candidate.value}",
        "learning_focus": f"bạn đang học {candidate.value}",
        "habit": f"bạn hay {candidate.value}",
        "skill": f"bạn biết {candidate.value}",
        "household_pet": f"nhà bạn có nuôi {candidate.value}",
        "negative_preference": f"bạn không thích {candidate.value}",
    }
    content = _content_map.get(candidate.relation, f"{candidate.relation}: {candidate.value}")

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
    return _save_profile_v2_fact(
        store, session_id,
        subject="self", relation="affection", value=value,
        content=f"bạn có tình cảm/thích {value}",
        tags=["user_profile", "self", "affection"],
        original_text=original_text,
    )


def save_external_affection_fact(
    admirer: str, store: "MemoryStoreProtocol", session_id: str, *, original_text: str = ""
) -> bool:
    """P0-7G: save a user-reported external affection fact ("Quý thích tôi").

    Recorded as reported information (admirer → the user), never as objective truth.
    """
    return _save_profile_v2_fact(
        store, session_id,
        subject="external", relation="affection_to_user", value=admirer,
        content=f"{admirer} thích bạn (theo thông tin bạn cung cấp)",
        tags=["user_profile", "external", "affection"],
        original_text=original_text,
    )


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
    preferences_personal: list[str] = field(default_factory=list)
    preferences_professional: list[str] = field(default_factory=list)
    habits: list[str] = field(default_factory=list)
    pets: list[str] = field(default_factory=list)  # P0-7F-FIX4: household pets
    relations: list[tuple[str, str]] = field(default_factory=list)  # (label, name)
    # P0-7G
    dislikes: list[str] = field(default_factory=list)          # negative preferences
    affections: list[str] = field(default_factory=list)        # people the user likes
    external_affections: list[str] = field(default_factory=list)  # people who like the user


def _norm_cmp(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


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
        if subject == "self" and rel == "name":
            # P0-7G: latest name wins (records are sorted ascending by created_at), so a
            # name update supersedes older values instead of keeping the first.
            snap.name = val
        elif subject == "self" and rel == "negative_preference":
            _add(snap.dislikes, val)
        elif subject == "self" and rel == "affection":
            _add(snap.affections, val)
        elif subject == "external" and rel == "affection_to_user":
            _add(snap.external_affections, val)
        elif subject == "self" and rel == "occupation":
            _add(snap.occupation, val)
        elif subject == "self" and rel == "skill":
            _add(snap.skills, val)
        elif subject == "self" and rel == "learning_focus":
            _add(snap.learning, val)
        elif subject == "self" and rel == "goal":
            _add(snap.goals, val)
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
    return None


def _answer_named_affection_yesno(
    subject: str, obj: str, store: "MemoryStoreProtocol"
) -> str:
    """Answer "Bắc có thích Quý không?" by mapping the saved self-name to the user (P0-7G).

    - subject == user  → "do I like OBJ?"   → answer from affection memory.
    - object  == user  → "does SUBJ like me?" → answer from external affection memory.
    - neither is the user → unrelated third parties; do not infer.
    """
    snap = collect_profile_snapshot(store)
    self_name = _norm_cmp(snap.name or "")

    def _is_user(tok: str) -> bool:
        low = tok.strip().lower()
        return low in _SELF_WORDS or (bool(self_name) and _norm_cmp(tok) == self_name)

    subj_user = _is_user(subject)
    obj_user = _is_user(obj)

    if subj_user and not obj_user:
        # "do I like OBJ?"
        if any(_norm_cmp(obj) == _norm_cmp(v) for v in snap.affections):
            return f"Có, mình đang nhớ là bạn thích {obj}."
        return f"Mình chưa có thông tin về việc bạn thích {obj}."
    if obj_user and not subj_user:
        # "does SUBJ like me?"
        if any(_norm_cmp(subject) == _norm_cmp(v) for v in snap.external_affections):
            return f"Có, theo thông tin bạn cung cấp thì {subject} thích bạn."
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
        # P0-7G: dislikes shown separately from positive likes.
        if snap.dislikes:
            lines.append(f"- Bạn không thích {', '.join(snap.dislikes)}.")
        if snap.affections:
            lines.append(f"- Bạn có tình cảm/quan tâm đến {', '.join(snap.affections)}.")
        if snap.external_affections:
            lines.append(
                f"- Theo thông tin bạn cung cấp, {', '.join(snap.external_affections)} "
                "thích bạn."
            )
        for label, name in snap.relations:
            lines.append(f"- {label.capitalize()} của bạn tên là {name}.")
        if not lines:
            return "Tôi chưa có thông tin hồ sơ nào đã được xác nhận về bạn."
        return "Tôi đang nhớ những thông tin sau về bạn:\n" + "\n".join(lines)

    # --- P0-7D: self_occupation ---
    elif query.kind == "self_occupation":
        for rec in confirmed:
            if rec.metadata.get("subject") == "self" and rec.metadata.get("relation") == "occupation":
                val = rec.metadata.get("value", "")
                return f"Mình đang nhớ công việc/lĩnh vực của bạn là {val}."
        return "Tôi chưa có thông tin về nghề nghiệp/vai trò của bạn."

    # --- P0-7D/7F: self_preference — aggregate ALL preferences (personal + professional) ---
    elif query.kind == "self_preference":
        snap = collect_profile_snapshot(store)
        if not snap.preferences_personal and not snap.preferences_professional:
            return "Tôi chưa có thông tin về sở thích của bạn."
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

    # --- P0-7F-FIX2 / P0-7G: self_affection ("tôi thích ai?") ---
    elif query.kind == "self_affection":
        snap = collect_profile_snapshot(store)
        # P0-7G: prefer a first-class affection fact, then affection-type relationships.
        if snap.affections:
            return f"Mình đang nhớ {snap.affections[0]} là người bạn thích/quan tâm."
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
        return (
            f"Mình không biết {subject} có thích bạn hay không nếu bạn chưa cung cấp "
            "thông tin đó."
        )

    # --- P0-7G: named_affection_yesno ("Bắc có thích Quý không?") ---
    elif query.kind == "named_affection_yesno":
        return _answer_named_affection_yesno(
            query.value or "", query.object_value or "", store
        )

    # --- P0-7F-FIX4 Part C: friend_name ("bạn của tôi tên là gì?") ---
    elif query.kind == "friend_name":
        for rec in confirmed:
            if (
                rec.metadata.get("subject") == "relation"
                and rec.metadata.get("relation") == "name"
                and rec.metadata.get("relation_label") == "bạn"
            ):
                name = rec.metadata.get("value", "")
                return f"Bạn của bạn tên là {name}."
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

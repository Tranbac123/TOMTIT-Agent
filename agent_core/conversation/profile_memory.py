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
    relation: Literal["occupation", "preference", "goal", "learning_focus"] = "occupation"
    value: str = ""
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
    ]
    value: str | None = None          # for inverse_value: the name to look up
    relation_label: str | None = None  # for relation_name / relation_existence


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


def _is_valid_auto_value(value: str) -> bool:
    """True if value is a meaningful, non-vague, bounded string for auto-save."""
    v = value.strip()
    if not v or len(v) < 3 or len(v) > 80:
        return False
    if v.lower() in _VAGUE_REFS:
        return False
    return True


# ---------------------------------------------------------------------------
# Candidate detection patterns
# ---------------------------------------------------------------------------

# "tôi tên là Bắc", "mình tên là Bắc"
_RE_SELF_TEN_LA = re.compile(
    r'^(?:tôi|mình)\s+tên\s+là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# "tên tôi là Bắc", "tên mình là Bắc"
_RE_TEN_TOI_LA = re.compile(
    r'^tên\s+(?:tôi|mình)\s+là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
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
    r'|bạn\s+nhớ\s+(?:tôi|mình)\s+tên\s+g[ìi]',
    re.IGNORECASE,
)

# P0-7C FIX: fully anchored
_RE_SELF_IDENTITY_Q = re.compile(
    r'^\s*(?:tôi|mình)\s+là\s+ai\s*[?？]?\s*$',
    re.IGNORECASE,
)

# Relation name query "tên gì?" — includes P0-7C synonyms + optional "của"
_RE_RELATION_NAME_Q = re.compile(
    r'^' + _RELATIONS_QUERY_PATTERN
    + r'(?:\s+của)?\s+(?:tôi|mình)\s+tên\s+(?:là\s+)?g[ìi]\s*[?？]?\s*$',
    re.IGNORECASE,
)

# P0-7C: relation "là ai?" form
_RE_RELATION_LA_AI_Q = re.compile(
    r'^' + _RELATIONS_QUERY_PATTERN
    + r'(?:\s+của)?\s+(?:tôi|mình)\s+là\s+ai\s*[?？]?\s*$',
    re.IGNORECASE,
)

# P0-7C: profile summary queries
_RE_PROFILE_SUMMARY_Q = re.compile(
    r'^\s*bạn\s+(?:biết|nhớ|lưu|đang\s+nhớ)\s+(?:gì\s+)?về\s+(?:tôi|mình)\s*[?？]?\s*$',
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
    r'^(?:'
    r'(?:tôi|mình)\s+làm\s+nghề\s+gì'
    r'|nghề\s+(?:của\s+)?(?:tôi|mình)\s+là\s+gì'
    r'|công\s+việc\s+(?:của\s+)?(?:tôi|mình)\s+là\s+gì'
    r'|vai\s+trò\s+(?:của\s+)?(?:tôi|mình)\s+là\s+gì'
    r')\s*[?？]?\s*$',
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
_RE_LEARNING_Q = re.compile(
    r'^(?:tôi|mình)\s+(?:đang\s+)?học\s+gì\s*[?？]?\s*$',
    re.IGNORECASE,
)
_RE_GOAL_Q = re.compile(
    r'^(?:mục\s+tiêu|goal)\s+(?:của\s+)?(?:tôi|mình)\s+là\s+gì\s*[?？]?\s*$',
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


def _normalize_relation_label(raw: str) -> str:
    return re.sub(r'\s+', ' ', raw.strip().lower())


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

    # Self-is — riskier, require proper name (uppercase first char), single token
    m = _RE_SELF_IS.match(stripped)
    if m:
        value = m.group(1).rstrip('.!?').strip()
        if value and _is_proper_name(value) and value.lower() not in _QUESTION_WORDS:
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

    # 1. Relation name "tên gì?" form
    m = _RE_RELATION_NAME_Q.match(stripped)
    if m:
        label = _normalize_relation_label(m.group(1))
        return ProfileQuery(kind="relation_name", relation_label=label)

    # 2. P0-7C: relation "là ai?" form
    m = _RE_RELATION_LA_AI_Q.match(stripped)
    if m:
        label = _normalize_relation_label(m.group(1))
        return ProfileQuery(kind="relation_name", relation_label=label)

    # 3. P0-7C: profile summary
    if _RE_PROFILE_SUMMARY_Q.match(stripped):
        return ProfileQuery(kind="profile_summary")

    # 4. Self-name (unanchored)
    if _RE_SELF_NAME_Q.search(stripped):
        return ProfileQuery(kind="self_name")

    # 5. Self-identity — P0-7C FIX: fully anchored
    if _RE_SELF_IDENTITY_Q.match(stripped):
        return ProfileQuery(kind="self_identity")

    # 6. P0-7D: occupation query
    if _RE_OCCUPATION_Q.match(stripped):
        return ProfileQuery(kind="self_occupation")

    # 7. P0-7D: preference query
    if _RE_PREFERENCE_Q.match(stripped):
        return ProfileQuery(kind="self_preference")

    # 8. P0-7D: learning focus query
    if _RE_LEARNING_Q.match(stripped):
        return ProfileQuery(kind="self_learning_focus")

    # 9. P0-7D: goal query
    if _RE_GOAL_Q.match(stripped):
        return ProfileQuery(kind="self_goal")

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

    return None


# ---------------------------------------------------------------------------
# Detection — AUTO_SAFE extraction
# ---------------------------------------------------------------------------

def detect_auto_profile_candidate(text: str) -> AutoProfileCandidate | None:
    """Return an AutoProfileCandidate for AUTO_SAFE extraction, or None.

    Never fires for questions, note/command/correction prefixes, or vague values.
    """
    stripped = text.strip()

    # Reject questions (check BEFORE rstrip — rstrip would remove the '?' itself)
    if '?' in stripped or '？' in stripped:
        return None

    # Reject note/command/correction prefixes
    if not _is_safe_for_auto_save(stripped):
        return None

    # --- Goal (checked first: unambiguous keyword "mục tiêu"/"goal") ---
    m = _RE_GOAL.match(stripped)
    if m:
        value = m.group(1).strip().rstrip('.!')
        if _is_valid_auto_value(value):
            return AutoProfileCandidate(
                subject="self", relation="goal",
                value=value, original_text=stripped,
            )

    # --- Learning focus ---
    m = _RE_LEARNING.match(stripped)
    if m:
        value = m.group(1).strip().rstrip('.!')
        if _is_valid_auto_value(value):
            return AutoProfileCandidate(
                subject="self", relation="learning_focus",
                value=value, original_text=stripped,
            )

    # --- Preference (explicit "thích"/"quan tâm đến"/"sở thích") ---
    for pat in (_RE_PREFERENCE_SO_THICH, _RE_PREFERENCE_QUAN_TAM, _RE_PREFERENCE_THICH):
        m = pat.match(stripped)
        if m:
            value = m.group(1).strip().rstrip('.!')
            if _is_valid_auto_value(value):
                return AutoProfileCandidate(
                    subject="self", relation="preference",
                    value=value, original_text=stripped,
                )

    # --- Occupation (explicit context: "nghề/công việc/vai trò của tôi là") ---
    m = _RE_OCCUPATION_CONTEXT.match(stripped)
    if m:
        value = m.group(1).strip().rstrip('.!')
        if _is_valid_auto_value(value):
            return AutoProfileCandidate(
                subject="self", relation="occupation",
                value=value, original_text=stripped,
            )

    # --- Occupation ("tôi làm VALUE") ---
    m = _RE_OCCUPATION_TOI_LAM.match(stripped)
    if m:
        value = m.group(1).strip().rstrip('.!')
        if _is_valid_auto_value(value):
            return AutoProfileCandidate(
                subject="self", relation="occupation",
                value=value, original_text=stripped,
            )

    # --- Occupation ("tôi là VALUE") — requires role keyword to avoid description clash ---
    m = _RE_OCCUPATION_TOI_LA.match(stripped)
    if m:
        value = m.group(1).strip().rstrip('.!')
        tokens = value.split()
        if (
            _is_valid_auto_value(value)
            and len(tokens) >= 2              # multi-word: "AI engineer", not "Bắc"
            and _has_role_keyword(value)      # contains known role term
        ):
            return AutoProfileCandidate(
                subject="self", relation="occupation",
                value=value, original_text=stripped,
            )

    return None


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


def build_auto_ack_message(candidate: AutoProfileCandidate) -> str:
    _desc_map = {
        "occupation": "nghề nghiệp/vai trò",
        "preference": "sở thích",
        "goal": "mục tiêu",
        "learning_focus": "nội dung đang học",
    }
    desc = _desc_map.get(candidate.relation, candidate.relation)
    return f"Đã lưu vào hồ sơ của bạn: {desc} là {candidate.value}."


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def save_confirmed_profile_fact(
    candidate: ProfileFactCandidate,
    store: "MemoryStoreProtocol",
    session_id: str,
) -> bool:
    """Write confirmed profile fact to store. Returns True on success."""
    from agent_core.memory.memory_agent import MemoryAgent

    tags = ["user_profile"]
    metadata: dict = {
        "profile_schema": "user_profile_fact_v1",
        "subject": candidate.subject,
        "relation": candidate.relation,
        "value": candidate.value,
        "confirmed": True,
        "confirmation_source": "explicit_user_confirmation",
        "original_text": candidate.original_text,
    }

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

    _content_map = {
        "occupation": f"bạn là {candidate.value}",
        "preference": f"bạn thích {candidate.value}",
        "goal": f"mục tiêu của bạn là {candidate.value}",
        "learning_focus": f"bạn đang học {candidate.value}",
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


# ---------------------------------------------------------------------------
# Retrieval / answering
# ---------------------------------------------------------------------------

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
        for rec in confirmed:
            if rec.metadata.get("subject") == "self" and rec.metadata.get("relation") == "name":
                name = rec.metadata.get("value", "")
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
        # No relation fact found: return None to fall through to router
        # (relation_name unknown state is handled by router CLARIFICATION)
        return None

    # --- inverse_value ---
    elif query.kind == "inverse_value":
        lookup = (query.value or "").lower()
        for rec in confirmed:
            stored_val = rec.metadata.get("value", "").lower()
            if stored_val == lookup:
                subject = rec.metadata.get("subject", "")
                val_display = rec.metadata.get("value", query.value or "")
                if subject == "self":
                    return f"{val_display} là tên của bạn."
                elif subject == "relation":
                    rel = rec.metadata.get("relation_label", "người liên quan")
                    return f"{val_display} là {rel} của bạn."
        return None

    # --- profile_summary ---
    elif query.kind == "profile_summary":
        lines: list[str] = []
        for rec in confirmed:
            subject = rec.metadata.get("subject", "")
            rel = rec.metadata.get("relation", "")
            val = rec.metadata.get("value", "")
            if subject == "self" and rel == "name":
                lines.append(f"- Bạn tên là {val}.")
            elif subject == "self" and rel == "occupation":
                lines.append(f"- Bạn là {val}.")
            elif subject == "self" and rel == "preference":
                lines.append(f"- Bạn thích {val}.")
            elif subject == "self" and rel == "goal":
                lines.append(f"- Mục tiêu của bạn là {val}.")
            elif subject == "self" and rel == "learning_focus":
                lines.append(f"- Bạn đang học {val}.")
            elif subject == "relation" and rel == "name":
                rel_label = rec.metadata.get("relation_label", "người liên quan")
                lines.append(f"- {rel_label.capitalize()} của bạn tên là {val}.")
        if not lines:
            return "Tôi chưa có thông tin hồ sơ nào đã được xác nhận về bạn."
        return "Tôi đang nhớ những thông tin sau về bạn:\n" + "\n".join(lines)

    # --- P0-7D: self_occupation ---
    elif query.kind == "self_occupation":
        for rec in confirmed:
            if rec.metadata.get("subject") == "self" and rec.metadata.get("relation") == "occupation":
                val = rec.metadata.get("value", "")
                return f"Bạn là {val}."
        return "Tôi chưa có thông tin đã lưu về nghề nghiệp/vai trò của bạn."

    # --- P0-7D: self_preference ---
    elif query.kind == "self_preference":
        for rec in confirmed:
            if rec.metadata.get("subject") == "self" and rec.metadata.get("relation") == "preference":
                val = rec.metadata.get("value", "")
                return f"Bạn thích {val}."
        return "Tôi chưa có thông tin đã lưu về sở thích của bạn."

    # --- P0-7D: self_learning_focus ---
    elif query.kind == "self_learning_focus":
        for rec in confirmed:
            if rec.metadata.get("subject") == "self" and rec.metadata.get("relation") == "learning_focus":
                val = rec.metadata.get("value", "")
                return f"Bạn đang học {val}."
        return "Tôi chưa có thông tin đã lưu về nội dung bạn đang học."

    # --- P0-7D: self_goal ---
    elif query.kind == "self_goal":
        for rec in confirmed:
            if rec.metadata.get("subject") == "self" and rec.metadata.get("relation") == "goal":
                val = rec.metadata.get("value", "")
                return f"Mục tiêu của bạn là {val}."
        return "Tôi chưa có thông tin đã lưu về mục tiêu của bạn."

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
        return "Tôi chưa có thông tin đã lưu về việc này."

    return None

"""CONV-P0 P0-7F: bounded rule-based semantic layer for user profile conversation.

Turns raw user text into a structured ``SemanticProfileIntent`` covering the profile
coverage gaps P0-7E left open: skill/ability writes, occupation shorthand ("tôi làm AI"),
"muốn" desires (goal vs travel-interest vs near-miss), personal/professional preference
split, person-affinity guarding ("tôi thích Quý" is not a hobby), relationship "của tôi"
variants, and yes/no memory queries.

Provider-free. No LLM, no network, no vector/RAG, no external libraries. Storage and
retrieval stay in ``profile_memory`` — this module only classifies. Values shown back to
the user are captured from the original text (case preserved); matching is done on a
lightly normalized copy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from agent_core.conversation.profile_memory import (
    _RE_PROFILE_SUMMARY_Q,
    _is_unsafe_or_sensitive_auto_value,
    _is_valid_auto_value_shape,
)

# Category taxonomy (compact, per audit §6). Stored as plain strings on the intent.
ProfileCategory = str


@dataclass(frozen=True)
class SemanticProfileIntent:
    """A classified profile conversation turn.

    ``write_policy`` drives runtime behavior: ``auto_safe`` → save + natural ack;
    ``clarify`` → non-destructive clarification (person-affinity, near-miss desire);
    ``block`` → safety response, never saved; ``none`` → pure query, nothing written.
    """
    kind: Literal[
        "profile_write",
        "profile_query",
        "profile_summary_query",
        "yes_no_memory_query",
        "clarification_followup",
    ]
    category: ProfileCategory | None
    value: str | None
    relation_label: str | None = None
    confidence: Literal["high", "medium", "low"] = "high"
    sensitivity: Literal["safe", "person_affinity", "sensitive", "unsafe"] = "safe"
    write_policy: Literal["auto_safe", "clarify", "block", "none"] = "none"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Lowercase, trim, collapse internal whitespace, drop trailing punctuation.

    Used only for matching/dispatch — never for values displayed back to the user.
    """
    norm = text.strip().lower()
    norm = re.sub(r"\s+", " ", norm)
    norm = re.sub(r"[.!?？\s]+$", "", norm)
    return norm


# ---------------------------------------------------------------------------
# Cue vocabularies
# ---------------------------------------------------------------------------

# Professional / technical tokens → preference.professional, occupation shorthand, goal.
_PROFESSIONAL_TOKENS: frozenset[str] = frozenset({
    "ai", "ml", "llm", "build", "code", "coding", "lập", "trình", "lập trình",
    "backend", "frontend", "fullstack", "devops", "agent", "startup", "web",
    "data", "research", "model", "app", "software", "engineer", "engineering",
    "python", "java", "golang", "rust", "react", "sql", "cloud", "api",
})

# Personal activity cues → preference.personal.
_PERSONAL_TOKENS: frozenset[str] = frozenset({
    "uống", "ăn", "chơi", "du", "lịch", "du lịch", "phượt", "thể", "thao",
    "thể thao", "bơi", "cafe", "cà", "phê", "cà phê", "đọc", "sách", "guitar",
    "nhạc", "phim", "game", "bóng", "đá bóng", "chạy", "gym", "yoga",
})

_VAGUE_VALUE_TOKENS: frozenset[str] = frozenset({
    "cái này", "cái đó", "cái kia", "việc này", "việc đó", "nó", "đó", "này",
    "gì", "gi",
})

_RE_ASCII_WORD = re.compile(r"[a-z0-9+#]+")


def _has_professional_token(value: str) -> bool:
    v = value.lower()
    if any(phrase in v for phrase in _PROFESSIONAL_TOKENS if " " in phrase):
        return True
    words = _RE_ASCII_WORD.findall(v)
    single = {t for t in _PROFESSIONAL_TOKENS if " " not in t}
    return any(w in single for w in words)


def _has_personal_token(value: str) -> bool:
    v = value.lower()
    if any(phrase in v for phrase in _PERSONAL_TOKENS if " " in phrase):
        return True
    words = re.findall(r"\w+", v, re.UNICODE)
    single = {t for t in _PERSONAL_TOKENS if " " not in t}
    return any(w in single for w in words)


def _is_person_affinity_value(value: str) -> bool:
    """True if value looks like a single human name (not an activity/professional thing).

    Conservative on purpose (audit §20): a single capitalized alphabetic token, not a
    known professional/personal cue and not an activity phrase. "Quý"/"Nam" → True,
    "AI"/"cafe"/"build AI"/"uống cafe" → False.
    """
    v = value.strip()
    if not v or " " in v:
        return False
    if any(ch.isdigit() for ch in v):
        return False
    if not v[0].isupper():
        return False
    if len(v) > 15:
        return False
    low = v.lower()
    if low in _PROFESSIONAL_TOKENS or low in _PERSONAL_TOKENS:
        return False
    if _has_professional_token(v) or _has_personal_token(v):
        return False
    return v.replace("-", "").isalpha()


def _classify_preference_kind(value: str) -> str:
    """Return "professional" if value reads as work/tech, else "personal"."""
    if _has_professional_token(value) and not _has_personal_token(value):
        return "professional"
    return "personal"


def _valid_value(value: str, *, min_len: int = 2) -> bool:
    v = value.strip()
    if len(v) < min_len or len(v) > 80:
        return False
    if v.lower() in _VAGUE_VALUE_TOKENS:
        return False
    return True


# ---------------------------------------------------------------------------
# Write patterns
# ---------------------------------------------------------------------------

_RE_PREF = re.compile(
    r'^(?:tôi|mình)\s+(?:thích|yêu\s+thích|mê|có\s+sở\s+thích)\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
_RE_AFFECTION = re.compile(
    r'^(?:tôi|mình)\s+(?:thích|yêu|nhớ|crush)\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
_RE_SKILL = re.compile(
    r'^(?:tôi|mình)\s+(?:biết\s+làm|biết|có\s+thể|làm\s+được|giỏi|từng\s+học)\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
_RE_OCC_LAM = re.compile(
    r'^(?:tôi|mình)\s+(?:đang\s+)?làm\s+(?:nghề\s+)?(.+)$',
    re.IGNORECASE | re.DOTALL,
)
_RE_WANT = re.compile(
    r'^(?:tôi|mình)\s+(?:muốn|định)\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
_RE_RELATIONSHIP = re.compile(
    r'^(bạn\s+gái|bạn\s+trai|người\s+yêu|vợ|chồng|partner)\s+'
    r'(?:của\s+)?(?:tôi|mình)\s+(?:tên\s+)?là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE,
)

# Query patterns handled by the semantic layer (skill/summary variants live in
# profile_memory; here we own yes/no + follow-up).
_RE_YESNO_PREF = re.compile(
    r'^(?:tôi|mình)\s+(?:có\s+)?thích\s+(.+?)\s+(?:đúng\s+không|không)\s*[?？]?\s*$',
    re.IGNORECASE,
)
_RE_YESNO_SKILL = re.compile(
    r'^(?:tôi|mình)\s+(?:có\s+)?biết\s+(.+?)\s+(?:đúng\s+không|không)\s*[?？]?\s*$',
    re.IGNORECASE,
)
_RE_FOLLOWUP = re.compile(
    r'^(?:gì\s+nữa|còn\s+gì\s+nữa|còn\s+không|thêm\s+gì\s+nữa)\s*[?？]?\s*$',
    re.IGNORECASE,
)

_RELATION_LABEL_NORM = {
    "bạn gái": "bạn gái",
    "bạn trai": "bạn trai",
    "người yêu": "người yêu",
    "vợ": "vợ",
    "chồng": "chồng",
    "partner": "partner",
}


def _clean_value(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.strip().rstrip(".!?？ ")).strip()


def classify_profile_semantic_intent(text: str) -> SemanticProfileIntent | None:
    """Classify a profile-related turn, or return None to fall through to legacy handlers.

    Ownership split (keeps legacy P0-7B..7E paths intact):
      - preference (thích/mê/yêu thích) writes incl. personal/professional + person-affinity
      - skill/ability writes
      - occupation shorthand "tôi làm X" (professional-token gated)
      - "muốn/định" desires → goal / travel-interest / near-miss clarification
      - relationship "của tôi" partner-name writes
      - yes/no memory queries and the "gì nữa" follow-up
    Legacy handlers still own: self-name, "tôi là X" occupation, habit, note/command
    prefixes, and the existing profile summary / category queries.
    """
    stripped = text.strip()
    if not stripped:
        return None

    # Follow-up marker (must precede any write interpretation).
    if _RE_FOLLOWUP.match(stripped):
        return SemanticProfileIntent(
            kind="clarification_followup", category=None, value=None, write_policy="none"
        )

    is_question = stripped.endswith("?") or stripped.endswith("？")

    # --- profile summary + yes/no memory queries (questions) ---
    if is_question or _RE_PROFILE_SUMMARY_Q.match(stripped):
        if _RE_PROFILE_SUMMARY_Q.match(stripped):
            return SemanticProfileIntent(
                kind="profile_summary_query", category=None, value=None, write_policy="none"
            )
        m = _RE_YESNO_PREF.match(stripped)
        if m:
            value = _clean_value(m.group(1))
            if value:
                return SemanticProfileIntent(
                    kind="yes_no_memory_query", category="preference",
                    value=value, write_policy="none",
                )
        m = _RE_YESNO_SKILL.match(stripped)
        if m:
            value = _clean_value(m.group(1))
            if value:
                return SemanticProfileIntent(
                    kind="yes_no_memory_query", category="skill",
                    value=value, write_policy="none",
                )
        # A question we do not specifically own → let legacy query handlers try.
        return None

    # Relationship partner-name ("bạn gái của tôi là Quý", "... tên là Quý").
    m = _RE_RELATIONSHIP.match(stripped)
    if m:
        label = _RELATION_LABEL_NORM.get(
            re.sub(r"\s+", " ", m.group(1).strip().lower()), m.group(1).strip().lower()
        )
        value = _clean_value(m.group(2))
        if value and not _is_unsafe_or_sensitive_auto_value(value):
            return SemanticProfileIntent(
                kind="profile_write", category="relationship.partner_name",
                value=value, relation_label=label, write_policy="auto_safe",
            )

    # Preference ("tôi thích/mê/yêu thích/có sở thích X").
    m = _RE_PREF.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if not _valid_value(value):
            return None
        if _is_unsafe_or_sensitive_auto_value(value):
            return SemanticProfileIntent(
                kind="profile_write", category="sensitive", value=value,
                sensitivity="unsafe", write_policy="block",
            )
        if _is_person_affinity_value(value):
            return SemanticProfileIntent(
                kind="profile_write", category="relationship.affection_candidate",
                value=value, sensitivity="person_affinity", write_policy="clarify",
            )
        kind_pref = _classify_preference_kind(value)
        return SemanticProfileIntent(
            kind="profile_write", category=f"preference.{kind_pref}",
            value=value, write_policy="auto_safe",
        )

    # Bare affection verbs ("tôi yêu Quý", "tôi nhớ Quý", "tôi crush X") — person only.
    m = _RE_AFFECTION.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if value and _is_person_affinity_value(value):
            return SemanticProfileIntent(
                kind="profile_write", category="relationship.affection_candidate",
                value=value, sensitivity="person_affinity", write_policy="clarify",
            )

    # Skill / ability.
    m = _RE_SKILL.match(stripped)
    if m:
        # Preserve "làm X" when the verb was "biết làm".
        prefix = "làm " if re.match(r'^(?:tôi|mình)\s+biết\s+làm\b', stripped, re.IGNORECASE) else ""
        value = _clean_value(prefix + m.group(1))
        if _valid_value(value) and not _is_unsafe_or_sensitive_auto_value(value):
            return SemanticProfileIntent(
                kind="profile_write", category="skill", value=value, write_policy="auto_safe",
            )

    # Occupation shorthand "tôi làm X" — require a professional token to avoid
    # "tôi làm bài tập" / "tôi làm việc này" false positives.
    m = _RE_OCC_LAM.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if (
            _valid_value(value)
            and _has_professional_token(value)
            and not _is_unsafe_or_sensitive_auto_value(value)
        ):
            return SemanticProfileIntent(
                kind="profile_write", category="occupation", value=value, write_policy="auto_safe",
            )

    # "muốn/định X" desires.
    m = _RE_WANT.match(stripped)
    if m:
        rest = _clean_value(m.group(1))
        low = rest.lower()
        if not rest:
            return None
        if _is_unsafe_or_sensitive_auto_value(rest):
            return SemanticProfileIntent(
                kind="profile_write", category="sensitive", value=rest,
                sensitivity="unsafe", write_policy="block",
            )
        if low.startswith("học "):
            return SemanticProfileIntent(
                kind="profile_write", category="learning_topic",
                value=_clean_value(rest[4:]), write_policy="auto_safe",
            )
        if low.startswith("trở thành ") or low.startswith("build ") or _has_professional_token(rest):
            return SemanticProfileIntent(
                kind="profile_write", category="goal", value=rest, write_policy="auto_safe",
            )
        if "du lịch" in low:
            return SemanticProfileIntent(
                kind="profile_write", category="preference.personal",
                value=rest, write_policy="auto_safe",
            )
        # Short-term / ambiguous desire ("đi chơi") → near-miss clarification, no save.
        return SemanticProfileIntent(
            kind="profile_write", category="near_miss", value=rest, write_policy="clarify",
        )

    return None

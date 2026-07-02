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

# P0-7F-FIX4 Part B: common object/food/activity nouns that are ordinary preferences,
# not person names. Guards the person-affinity heuristic (which otherwise over-fires on
# short lowercase tokens like "kem"/"trà"/"phở", treating a dessert as someone the user
# has feelings for). Bounded allowlist — deliberately NOT a general NER.
_COMMON_OBJECT_TOKENS: frozenset[str] = frozenset({
    "kem", "trà", "tra", "cafe", "cà phê", "ca phe", "bánh", "banh",
    "phở", "pho", "bún", "bun", "cơm", "com", "game", "sách", "sach",
    "nhạc", "nhac", "phim", "bóng đá", "bong da",
})

_VAGUE_VALUE_TOKENS: frozenset[str] = frozenset({
    "cái này", "cái đó", "cái kia", "việc này", "việc đó", "nó", "đó", "này",
    "gì", "gi",
})

# Bare Vietnamese interrogative words that must never be saved as profile values.
_INTERROGATIVE_VALUES: frozenset[str] = frozenset({
    "ai", "gì", "gi", "đâu", "nào", "sao", "vì sao", "bao nhiêu",
    "khi nào", "thế nào", "làm gì", "lam gi",
})
# Suffixes that make a phrase interrogative (e.g. "uống gì", "ăn gì").
_INTERROGATIVE_ENDINGS: tuple[str, ...] = (" gì", " gi", " đâu", " nào")

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


def _is_interrogative_value(value: str) -> bool:
    """True if value is (or ends with) a Vietnamese question word.

    Guards against bare question words ("ai", "gì") or question-ended phrases
    ("uống gì", "ăn gì") being saved as profile preferences.

    Bare check is case-sensitive so that "ai" (question word) is blocked while
    "AI" (uppercase technology token) is allowed through.
    Suffix check is case-insensitive (endings like " gì" are always lowercase).
    """
    v = value.strip()
    # Case-sensitive bare check: "ai" is interrogative, "AI" is not.
    if v in _INTERROGATIVE_VALUES:
        return True
    return any(v.lower().endswith(end) for end in _INTERROGATIVE_ENDINGS)


def _is_person_affinity_value(value: str) -> bool:
    """True if value looks like a single human name (not an activity/professional thing).

    Catches both capitalized ("Quý") and lowercase ("quý") Vietnamese single-word names.
    Lowercase tokens shorter than 3 chars are excluded to avoid 2-letter filler words.
    Known professional/personal tokens are always excluded.
    "AI"/"cafe"/"build AI"/"uống cafe" → False; "Quý"/"quý"/"Nam" → True.
    """
    v = value.strip()
    if not v or " " in v:
        return False
    if any(ch.isdigit() for ch in v):
        return False
    # Lowercase single tokens need ≥ 3 chars to avoid short filler words ("ok", "ờ").
    if not v[0].isupper() and len(v) < 3:
        return False
    if len(v) > 15:
        return False
    low = v.lower()
    if low in _PROFESSIONAL_TOKENS or low in _PERSONAL_TOKENS:
        return False
    # P0-7F-FIX4 Part B: common object/food token → ordinary preference, not a person.
    if low in _COMMON_OBJECT_TOKENS:
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
# P0-7F-FIX4 Part C: friend relation write — "bạn (của) tôi tên là meo". The bare label
# "bạn" (friend) is distinct from "bạn gái/trai" (partner) handled by _RE_RELATIONSHIP, and
# from "bạn" meaning the assistant. Requires an explicit "tôi/mình" possessor + "tên là".
_RE_FRIEND_NAME = re.compile(
    r'^bạn\s+(?:của\s+)?(?:tôi|mình)\s+tên\s+là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE,
)
# P0-7F-FIX4 Part A: affection relation phrase — "tôi có tình cảm/cảm tình với X",
# "tôi crush X". Person target is group(1); never a hobby, always a clarify (no save).
_RE_AFFECTION_RELATION = re.compile(
    r'^(?:tôi|mình)\s+(?:có\s+(?:tình\s+cảm|cảm\s+tình)\s+với|crush)\s+(\S+)',
    re.IGNORECASE,
)
# P0-7F-FIX5 Part B: one-sided ("đơn phương") affection phrase — "tôi thích đơn phương X",
# "tôi (đang) đơn phương X". The literal "đơn phương" precedes the person target (group 1),
# which distinguishes it from _RE_AFFECTION_EXPLANATION ("tôi thích X đơn phương", target
# BEFORE "đơn phương"). Person-affinity context → clarify, never an ordinary preference.
_RE_ONE_SIDED_AFFECTION = re.compile(
    r'^(?:tôi|mình)\s+(?:đang\s+)?(?:thích\s+)?đơn\s+phương\s+(.+)$',
    re.IGNORECASE,
)
# P0-7F-FIX4 Part D: household pet fact — "nhà tôi (có) nuôi (1 con) mèo", "tôi nuôi mèo".
# Optional "nhà", optional quantifier, optional "con"; group(1) is the animal.
_RE_HOUSEHOLD_PET = re.compile(
    r'^(?:nhà\s+)?(?:tôi|mình)\s+(?:có\s+)?nuôi\s+'
    r'(?:(?:\d+|một|hai|ba|vài|nhiều)\s+)?(?:con\s+)?(.+?)\s*[.!?]*\s*$',
    re.IGNORECASE,
)

# Query patterns handled by the semantic layer (skill/summary variants live in
# profile_memory; here we own yes/no + follow-up).
#
# P0-7F-FIX3 Part A: sentence-final question particles turn a "tôi thích X <particle>"
# turn into a yes/no query even without a trailing "?". The particle must be the LAST
# token so that content phrases like "cafe không đường" (no-sugar) are still preference
# writes — the non-greedy value group cannot leave trailing content after the particle.
_YESNO_SUFFIX = r'(?:đúng\s+không|phải\s+không|không|chưa|à|hả|nhỉ)'
_RE_YESNO_PREF = re.compile(
    r'^(?:tôi|mình)\s+(?:có\s+)?thích\s+(.+?)\s+' + _YESNO_SUFFIX + r'\s*[?？]?\s*$',
    re.IGNORECASE,
)
_RE_YESNO_SKILL = re.compile(
    r'^(?:tôi|mình)\s+(?:có\s+)?biết\s+(.+?)\s+' + _YESNO_SUFFIX + r'\s*[?？]?\s*$',
    re.IGNORECASE,
)
# P0-7F-FIX3 Part C: affection explanation ("tôi thích quý có nghĩa là ...",
# "tôi thích quý đơn phương", "tôi thích quý nhưng chúng tôi chưa là người yêu").
# The person target is group(1); everything after is an explanation, never a hobby value.
_RE_AFFECTION_EXPLANATION = re.compile(
    r'^(?:tôi|mình)\s+thích\s+(\S+)\s+'
    r'(?:(?:có\s+)?nghĩa\s+là|tức\s+là|đơn\s+phương|nhưng\s+chúng\s+(?:tôi|mình))',
    re.IGNORECASE,
)
_RE_FOLLOWUP = re.compile(
    r'^(?:gì\s+nữa|còn\s+gì\s+nữa|còn\s+không|thêm\s+gì\s+nữa)\s*[?？]?\s*$',
    re.IGNORECASE,
)
# "người tôi thích tên là Quý" / "người mình thích là Nam" — person-affection phrase.
_RE_PERSON_AFFECTION_PHRASE = re.compile(
    r'^người\s+(?:mà\s+)?(?:tôi|mình)\s+thích\s+(?:(?:tên\s+)?là\s+)?(.+)$',
    re.IGNORECASE,
)
# "tôi không thích ai" — negation of person affection; never save.
_RE_NEGATION_NO_AFFECTION = re.compile(
    r'^(?:tôi|mình)\s+không\s+thích\s+ai(?:\s+cả)?\s*[.!?]*\s*$',
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

    # Yes/no memory queries — self-identifying via a sentence-final question particle
    # (P0-7F-FIX3 Part A), so they are checked BEFORE any write interpretation and do not
    # require a trailing "?". "tôi thích cafe không" → query, "tôi thích cafe không đường"
    # → falls through to a preference write.
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

    is_question = stripped.endswith("?") or stripped.endswith("？")

    # --- profile summary query ---
    if is_question or _RE_PROFILE_SUMMARY_Q.match(stripped):
        if _RE_PROFILE_SUMMARY_Q.match(stripped):
            return SemanticProfileIntent(
                kind="profile_summary_query", category=None, value=None, write_policy="none"
            )
        # A question we do not specifically own → let legacy query handlers try.
        return None

    # Negation: "tôi không thích ai" — acknowledge, never save.
    if _RE_NEGATION_NO_AFFECTION.match(stripped):
        return SemanticProfileIntent(
            kind="profile_write", category="negation_no_affection", value=None,
            sensitivity="safe", write_policy="clarify",
        )

    # Affection explanation ("tôi thích quý có nghĩa là ...") — clarify, never save as
    # a hobby/preference (P0-7F-FIX3 Part C). Person target captured for the response.
    m = _RE_AFFECTION_EXPLANATION.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if value:
            return SemanticProfileIntent(
                kind="profile_write", category="affection_explanation",
                value=value, sensitivity="person_affinity", write_policy="clarify",
            )

    # Affection relation phrase ("tôi có tình cảm với quý", "tôi crush quý") — clarify,
    # never save as a hobby (P0-7F-FIX4 Part A). Person target captured for the response.
    m = _RE_AFFECTION_RELATION.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if value:
            return SemanticProfileIntent(
                kind="profile_write", category="affection_relation",
                value=value, sensitivity="person_affinity", write_policy="clarify",
            )

    # One-sided affection phrase ("tôi thích đơn phương Quý", "tôi đơn phương Quý") —
    # clarify, never an ordinary preference (P0-7F-FIX5 Part B). Checked before _RE_PREF so
    # "đơn phương Quý" is not stored as a hobby value.
    m = _RE_ONE_SIDED_AFFECTION.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if value:
            return SemanticProfileIntent(
                kind="profile_write", category="one_sided_affection",
                value=value, sensitivity="person_affinity", write_policy="clarify",
            )

    # Friend relation write ("bạn của tôi tên là meo") — stored as a relation named
    # under the "bạn" (friend) label, distinct from partner labels (P0-7F-FIX4 Part C).
    m = _RE_FRIEND_NAME.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if value and not _is_unsafe_or_sensitive_auto_value(value):
            return SemanticProfileIntent(
                kind="profile_write", category="relationship.partner_name",
                value=value, relation_label="bạn", write_policy="auto_safe",
            )

    # Person-affection phrase: "người tôi thích tên là Quý".
    m = _RE_PERSON_AFFECTION_PHRASE.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if value:
            return SemanticProfileIntent(
                kind="profile_write", category="relationship.affection_candidate",
                value=value, sensitivity="person_affinity", write_policy="clarify",
            )

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

    # Household pet fact ("nhà tôi có nuôi 1 con mèo", "tôi nuôi mèo") — low-risk profile
    # fact, saved without confirmation (P0-7F-FIX4 Part D). Only pet/animal possession.
    m = _RE_HOUSEHOLD_PET.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if _valid_value(value) and not _is_unsafe_or_sensitive_auto_value(value):
            return SemanticProfileIntent(
                kind="profile_write", category="household_pet",
                value=value, write_policy="auto_safe",
            )

    # Preference ("tôi thích/mê/yêu thích/có sở thích X").
    m = _RE_PREF.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if not _valid_value(value):
            return None
        if _is_interrogative_value(value):
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

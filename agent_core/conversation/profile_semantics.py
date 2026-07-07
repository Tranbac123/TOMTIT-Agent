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
    # P0-7K-FIX5B-FIX3: technical concepts are work/topic preferences, not people.
    "planner", "runtime", "tool", "memory", "rag", "mcp", "a2a", "docker", "git",
    "blogger", "bloger",  # P0-7H: occupation variants
    "founder",
    # P0-7J: short role terms — "tôi làm IT" / "tôi là DEV/developer/developper".
    "it", "dev", "developer", "developper",
})

# P0-7H: Vietnamese single-word occupation terms whose diacritics prevent ASCII-word matching.
_VN_PROFESSIONAL_SINGLE: frozenset[str] = frozenset({"nông"})

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
    # P0-7I: common weather/condition adjective — otherwise misread as a lowercase
    # person name by the bounded person-affinity heuristic ("tôi không thích lạnh").
    "lạnh", "lanh",
})

_KNOWN_NON_PERSON_CONCEPTS: frozenset[str] = frozenset({
    "planner", "runtime", "tool", "memory", "ai", "ml", "llm", "agent",
    "api", "rag", "mcp", "a2a", "python", "docker", "git",
})

# P0-7I: trailing Vietnamese discourse particles that can follow an affection/person
# target ("tôi thích quý mà"). Stripped only for the person-affinity check so the object
# is recognized as "quý" (a person), not saved verbatim as an ordinary preference "quý mà".
_DISCOURSE_MARKER_SUFFIXES: frozenset[str] = frozenset({"mà", "đó", "nhé", "nha", "nữa"})

# P0-7J-FIX1: leading additive markers that can precede an affection/person target
# ("tôi thích cả may", "tôi thích thêm may"). Stripped for the person check so "may" is
# recognized as a person; ordinary objects ("cả kem") stay ordinary preferences.
_ADDITIVE_TARGET_PREFIXES: frozenset[str] = frozenset({"cả", "cũng", "còn", "thêm"})


def _strip_discourse_marker(value: str) -> str:
    tokens = value.split()
    while len(tokens) >= 2 and tokens[-1].lower() in _DISCOURSE_MARKER_SUFFIXES:
        tokens = tokens[:-1]
    return " ".join(tokens).strip()


# P0-7K-FIX3: terminal discourse markers to strip from any saved profile value
# ("đánh đàn nữa" → "đánh đàn"). Single-token markers plus the 2-token "mới đúng".
_TERMINAL_DISCOURSE_TOKENS: frozenset[str] = frozenset({
    "nữa", "rồi", "mà", "đó", "đấy", "nhé", "nha", "chứ",
})


def strip_terminal_discourse_markers(value: str) -> str:
    """Strip trailing discourse markers from a memory value; never empties it.

    "đánh đàn nữa" → "đánh đàn"; "ăn kẹo nữa" → "ăn kẹo"; "tên là Bắc mới đúng" →
    "tên là Bắc". Only terminal tokens are removed — internal tokens stay intact.
    """
    v = re.sub(r"\s+", " ", value.strip())
    # 2-token "mới đúng" first.
    v = re.sub(r"\s+mới\s+đúng\s*$", "", v, flags=re.IGNORECASE).strip()
    tokens = v.split()
    while len(tokens) >= 2 and tokens[-1].lower() in _TERMINAL_DISCOURSE_TOKENS:
        tokens = tokens[:-1]
    return " ".join(tokens).strip()


# P0-7K-FIX1 A/J: bare question words that must never be written as a memory value.
# P0-7K-FIX2: a value CONTAINING any of these tokens ("ăn gì nhất" → has "gì") is a
# misclassified query and must not be saved. NOTE: "nhất" is NOT here — "thích X nhất"
# is a valid favorite statement (handled by the favorite marker), not a query.
_QUERY_MARKER_WORDS: frozenset[str] = frozenset({
    "gì", "gi", "nào", "đâu",
})
# Question words allowed as a tech token when uppercase ("AI"); blocked when lowercase.
_QUERY_LEADING_WORDS: frozenset[str] = frozenset({"ai", "sao"})


def _value_is_query_polluted(value: str) -> bool:
    """True if value looks like a query phrase, not a storable fact.

    Guards every write path: a value containing a bare question-word token ("gì", "nào"),
    or LEADING with a lowercase question word ("ai"/"sao"), is a misclassified query.
    "nhất" alone is a favorite marker (valid) and never blocks here.
    """
    orig_tokens = re.sub(r"\s+", " ", value.strip()).split()
    if not orig_tokens:
        return True
    tokens = [t.lower() for t in orig_tokens]
    if any(t in _QUERY_MARKER_WORDS for t in tokens):
        return True
    first = tokens[0]
    if first in _QUERY_LEADING_WORDS and not (first == "ai" and orig_tokens[0].isupper()):
        return True
    return False


def strip_additive_target_marker(value: str) -> str:
    """Strip leading additive markers + trailing discourse markers from a target.

    "cả may" → "may"; "cả may nữa" → "may"; "may" → "may". Never empties the value.
    """
    tokens = value.split()
    while len(tokens) >= 2 and tokens[0].lower() in _ADDITIVE_TARGET_PREFIXES:
        tokens = tokens[1:]
    return _strip_discourse_marker(" ".join(tokens).strip())

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
    if any(w in single for w in words):
        return True
    # P0-7H: Vietnamese single-word occupation terms matched as whole Unicode words
    return any(w in _VN_PROFESSIONAL_SINGLE for w in v.split())


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
    if low in _KNOWN_NON_PERSON_CONCEPTS:
        return False
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


# P0-7K-FIX2: food-context prefixes that mark a preference/favorite value as food.
_FOOD_CONTEXT_PREFIXES: tuple[str, ...] = ("ăn ", "uống ")


def _is_food_value(value: str) -> bool:
    return value.strip().lower().startswith(_FOOD_CONTEXT_PREFIXES)


# ---------------------------------------------------------------------------
# Write patterns
# ---------------------------------------------------------------------------

# P0-7K-FIX2: favorite marker — "tôi thích X nhất" (X clean, no query word).
_RE_FAVORITE = re.compile(
    r'^(?:tôi|mình)\s+thích\s+(.+?)\s+nhất\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7K-FIX2: comparative — "tôi thích A hơn (là) B".
_RE_COMPARATIVE = re.compile(
    r'^(?:tôi|mình)\s+thích\s+(.+?)\s+hơn(?:\s+là)?\s+(.+?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)

# P0-7J-FIX1: optional pre-verb additive markers cover "tôi cũng thích may" /
# "tôi còn thích X" (the marker never enters the captured value).
_RE_PREF = re.compile(
    r'^(?:tôi|mình)\s+(?:cũng\s+|còn\s+|vẫn\s+)?'
    r'(?:thích|yêu\s+thích|mê|có\s+sở\s+thích)\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7J: quan tâm is an affection-domain verb ("tôi quan tâm quý" saves affection when
# the target is a person; "tôi quan tâm đến AI" still falls through to the legacy
# professional-preference path because "AI" is not person-shaped).
# P0-7J-FIX1: optional pre-verb additive markers ("tôi cũng yêu may").
_RE_AFFECTION = re.compile(
    r'^(?:tôi|mình)\s+(?:đang\s+)?(?:cũng\s+|còn\s+|vẫn\s+)?'
    r'(?:thích|yêu|nhớ|crush|quan\s+tâm(?:\s+(?:đến|tới))?)\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
_RE_RELATION_ADJACENT_AFFECTION = re.compile(
    r'^(?:tôi|mình)\s+thích\s+(\S+)\s+và\s+\1\s+cũng\s+thích\s+(?:tôi|mình)\s*[.!]*\s*$',
    re.IGNORECASE,
)
_RE_SKILL = re.compile(
    r'^(?:tôi|mình)\s+(?:biết\s+làm|biết|có\s+thể|làm\s+được|giỏi|từng\s+học)\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
_RE_OCC_LAM = re.compile(
    r'^(?:tôi|mình)\s+(?:đang\s+)?làm\s+(?:nghề\s+)?(.+)$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7H: "ngoài AI tôi còn làm blogger" — occupation alongside existing role.
# Group 1 is the new/additional occupation (after "còn làm").
_RE_OCC_NGOAI = re.compile(
    r'^ngoài\s+\S+\s+(?:tôi|mình)\s+còn\s+làm\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7H-FIX3: "tôi còn làm nông nữa" — additive occupation without "ngoài X" prefix.
# Group 1 is the occupation value (before optional trailing "nữa").
_RE_OCC_CON_LAM = re.compile(
    r'^(?:tôi|mình)\s+còn\s+làm\s+(.+?)(?:\s+nữa)?\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7H: "tôi ghét hút thuốc" — durable negative preference (same storage as "không thích").
_RE_GHET = re.compile(
    r'^(?:tôi|mình)\s+ghét\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7J: optional "đang" covers "tôi đang muốn làm AI LLM".
# P0-7J-FIX1: optional additive marker covers "tôi còn muốn làm AI Agent" (the marker
# stays out of the captured value; the runtime reads it from the raw text to decide
# additive-vs-supersede goal semantics).
_RE_WANT = re.compile(
    r'^(?:tôi|mình)\s+(?:đang\s+)?(?:còn\s+|cũng\s+|vẫn\s+)?(?:muốn|định)\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
_RE_RELATIONSHIP = re.compile(
    r'^(bạn\s+gái|bạn\s+trai|người\s+yêu|vợ|chồng|partner)\s+'
    r'(?:của\s+)?(?:tôi|mình)\s+(?:tên\s+)?là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE,
)
# P0-7G-FIX3 A4: reverse partner assertion — "Quý là người yêu của tôi". Subject (group 1)
# is the partner's name; label (group 2) is the relationship. Equivalent to the forward
# "người yêu của tôi là Quý". The runtime saves it under the same partner-name storage.
_RE_REVERSE_PARTNER = re.compile(
    r'^([^\s.!?,]+)\s+là\s+(bạn\s+gái|bạn\s+trai|người\s+yêu)\s+'
    r'(?:của\s+)?(?:tôi|mình)\s*[.!?]*\s*$',
    re.IGNORECASE,
)
# P0-7F-FIX4 Part C: friend relation write — "bạn (của) tôi tên là meo". The bare label
# "bạn" (friend) is distinct from "bạn gái/trai" (partner) handled by _RE_RELATIONSHIP, and
# from "bạn" meaning the assistant. Requires an explicit "tôi/mình" possessor + "tên là".
_RE_FRIEND_NAME = re.compile(
    r'^bạn(?:\s+thân)?\s+(?:của\s+)?(?:tôi|mình)\s+tên\s+là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
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
# P0-7K: preference yes/no WITHOUT a final particle or question mark
# ("tôi có thích ăn cá"). The leading "có" marks it as a query, never a write.
_RE_YESNO_PREF_BARE = re.compile(
    r'^(?:tôi|mình)\s+có\s+thích\s+(.+?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7K-FIX1 C: negative skill — "tôi không biết bơi", "mình không biết nấu ăn".
_RE_NEGATIVE_SKILL = re.compile(
    r'^(?:tôi|mình)\s+không\s+biết\s+(?:làm\s+)?(.+)$',
    re.IGNORECASE | re.DOTALL,
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
# P0-7G: durable negative preference — "tôi không thích ăn cá", "mình không thích chơi game".
# Person target ("tôi không thích Quý") is excluded (handled as clarify), and the bare
# "tôi không thích ai" is owned by _RE_NEGATION_NO_AFFECTION above.
_RE_NEGATIVE_PREFERENCE = re.compile(
    r'^(?:tôi|mình)\s+không\s+thích\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7G: short-term negative desire — "tôi không muốn đi học". Clarify, never saved.
_RE_NEGATIVE_DESIRE = re.compile(
    r'^(?:tôi|mình)\s+không\s+muốn\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7G: user-reported external affection — "Quý thích tôi", "Quý thích Bắc". Subject
# (group 1) is a non-self name; object (group 2) is decided against the saved self-name in
# the runtime (only saved when the object is the current user).
# P0-7G-FIX4A: object uses \S+(?:\s+\S+)? (1–2 tokens) so "Bắc Trần" is captured;
# the 1-token cap prevents over-matching long non-name phrases like "cho tôi về AI".
# P0-7K-HOTFIX1 D: optional modifiers ("cũng/vẫn/đang") and negation ("không") — the
# negation group (2) carries polarity so "Quý không thích tôi" becomes a negative edge.
_RE_EXTERNAL_AFFECTION = re.compile(
    r'^(\S+)\s+(?:cũng\s+|vẫn\s+|đang\s+)?(không\s+)?'
    r'(?:thích|yêu|thương|crush|quý\s+mến|quan\s+tâm(?:\s+(?:đến|tới))?)\s+'
    r'(\S+(?:\s+\S+)?)\s*[.!]*\s*$',
    re.IGNORECASE,
)
_SELF_WORD_SET: frozenset[str] = frozenset({"tôi", "mình", "tao", "ta"})
_RELATION_PREFIX_WORDS: frozenset[str] = frozenset({
    "bạn", "người", "vợ", "chồng", "anh", "chị", "em", "bố", "mẹ", "ba", "má",
})

_RELATION_LABEL_NORM = {
    "bạn gái": "bạn gái",
    "bạn trai": "bạn trai",
    "người yêu": "người yêu",
    "vợ": "vợ",
    "chồng": "chồng",
    "partner": "partner",
}


def _clean_value(raw: str) -> str:
    value = re.sub(r"\s+", " ", raw.strip().rstrip(".!?？ ")).strip()
    value = re.sub(
        r'\s+(?:bạn\s+)?không\s+nhớ\s+(?:à|a)\s*$',
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    return strip_terminal_discourse_markers(value)


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
    # P0-7K: preference yes/no without a final particle ("tôi có thích ăn cá").
    # Checked after the particle form so "tôi có thích cafe không" keeps its lane.
    m = _RE_YESNO_PREF_BARE.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if value and not _is_interrogative_value(value):
            return SemanticProfileIntent(
                kind="yes_no_memory_query", category="preference",
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

    # P0-7K-FIX1 C: negative skill ("tôi không biết bơi") — durable negative ability.
    # Checked before negative-desire so "không biết X" is not mistaken for a desire.
    m = _RE_NEGATIVE_SKILL.match(stripped)
    if m:
        # P0-7K-FIX3: strip terminal discourse markers ("đánh đàn nữa" → "đánh đàn").
        value = strip_terminal_discourse_markers(_clean_value(m.group(1)))
        if (
            value
            and not _is_interrogative_value(value)
            and not _value_is_query_polluted(value)
            and not _is_unsafe_or_sensitive_auto_value(value)
        ):
            return SemanticProfileIntent(
                kind="profile_write", category="negative_skill",
                value=value, write_policy="auto_safe",
            )

    # P0-7G: short-term negative desire ("tôi không muốn đi học") — clarify, never saved.
    m = _RE_NEGATIVE_DESIRE.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if value:
            return SemanticProfileIntent(
                kind="profile_write", category="negative_desire",
                value=value, write_policy="clarify",
            )

    # P0-7G: durable negative preference ("tôi không thích ăn cá"). A person target
    # ("tôi không thích Quý") is routed to clarify instead of a dislike write.
    m = _RE_NEGATIVE_PREFERENCE.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        # P0-7J: "tôi không thích X nữa" means "no longer" — "nữa" is never part of the
        # value, so "quý nữa" cannot leak into memory as a stored object.
        value = re.sub(r'\s+nữa$', '', value, flags=re.IGNORECASE)
        if value and not _is_interrogative_value(value) and not _value_is_query_polluted(value):
            if _is_person_affinity_value(value):
                return SemanticProfileIntent(
                    kind="profile_write", category="negation_no_affection", value=None,
                    sensitivity="safe", write_policy="clarify",
                )
            if not _is_unsafe_or_sensitive_auto_value(value):
                return SemanticProfileIntent(
                    kind="profile_write", category="negative_preference",
                    value=value, write_policy="auto_safe",
                )

    # P0-7H: "tôi ghét X" — durable negative preference (same category as "không thích X").
    m = _RE_GHET.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if value and not _is_interrogative_value(value):
            if _is_person_affinity_value(value):
                return SemanticProfileIntent(
                    kind="profile_write", category="negation_no_affection", value=None,
                    sensitivity="safe", write_policy="clarify",
                )
            if not _is_unsafe_or_sensitive_auto_value(value):
                return SemanticProfileIntent(
                    kind="profile_write", category="negative_preference",
                    value=value, write_policy="auto_safe",
                )

    # P0-7G: user-reported external affection ("Quý thích tôi"). Subject must not be a
    # self word or a relation prefix; the runtime decides (against the saved self-name)
    # whether the object is the current user before saving.
    m = _RE_EXTERNAL_AFFECTION.match(stripped)
    if m:
        subj = _clean_value(m.group(1))
        negated = bool(m.group(2))
        obj = _clean_value(m.group(3))
        subj_low = subj.lower()
        if (
            subj
            and obj
            and subj_low not in _SELF_WORD_SET
            and subj_low not in _RELATION_PREFIX_WORDS
            and _is_person_affinity_value(subj)
        ):
            category = "external_affection_negative" if negated else "external_affection"
            return SemanticProfileIntent(
                kind="profile_write", category=category,
                value=subj, relation_label=obj, write_policy="auto_safe",
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

    # Affection relation phrase ("tôi có tình cảm với quý", "tôi crush quý"). P0-7G now
    # SAVES this as affection/person memory (was clarify in P0-7F-FIX4). Person target
    # captured; sensitivity stays person_affinity so it is never an ordinary hobby.
    m = _RE_AFFECTION_RELATION.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if value:
            return SemanticProfileIntent(
                kind="profile_write", category="affection_relation",
                value=value, sensitivity="person_affinity", write_policy="auto_safe",
            )

    # One-sided affection phrase ("tôi thích đơn phương Quý", "tôi đơn phương Quý") —
    # categorized distinctly so runtime can save it as affection without making it an
    # ordinary preference or relationship. Checked before _RE_PREF so "đơn phương Quý"
    # is not stored as a hobby value.
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

    # Person-affection phrase: "người tôi thích tên là Quý". P0-7G saves it as affection.
    m = _RE_PERSON_AFFECTION_PHRASE.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if value:
            return SemanticProfileIntent(
                kind="profile_write", category="relationship.affection_candidate",
                value=value, sensitivity="person_affinity", write_policy="auto_safe",
            )

    # P0-7G-FIX3 A4: reverse partner assertion ("Quý là người yêu của tôi") — mirror of the
    # forward partner-name write. Subject must be a person-affinity name, not a self word.
    m = _RE_REVERSE_PARTNER.match(stripped)
    if m:
        subj = _clean_value(m.group(1))
        label = _RELATION_LABEL_NORM.get(
            re.sub(r"\s+", " ", m.group(2).strip().lower()), m.group(2).strip().lower()
        )
        subj_low = subj.lower()
        if (
            subj
            and subj_low not in _SELF_WORD_SET
            and subj_low not in _RELATION_PREFIX_WORDS
            and _is_person_affinity_value(subj)
            and not _is_unsafe_or_sensitive_auto_value(subj)
        ):
            return SemanticProfileIntent(
                kind="profile_write", category="relationship.partner_name",
                value=subj, relation_label=label, write_policy="auto_safe",
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

    # P0-7K-FIX2: comparative preference ("tôi thích A hơn (là) B") — before ordinary
    # preference so the raw "A hơn B" is never stored as one value. Query forms
    # ("A hay B hơn?") are handled earlier by detect_profile_query.
    m = _RE_COMPARATIVE.match(stripped)
    if m:
        winner = _clean_value(m.group(1))
        loser = _clean_value(m.group(2))
        if (
            winner and loser
            and not _value_is_query_polluted(winner)
            and not _value_is_query_polluted(loser)
            and not _is_person_affinity_value(winner)
            and not _is_unsafe_or_sensitive_auto_value(winner)
            and not _is_unsafe_or_sensitive_auto_value(loser)
        ):
            domain = "food" if (_is_food_value(winner) or _is_food_value(loser)) else "general"
            return SemanticProfileIntent(
                kind="profile_write", category=f"comparative.{domain}",
                value=winner, relation_label=loser, write_policy="auto_safe",
            )

    # P0-7K-FIX2: favorite marker ("tôi thích X nhất") — before ordinary preference so
    # "X nhất" is never stored raw. A query value ("ăn gì nhất") is blocked here and is
    # answered as a ranking query earlier.
    m = _RE_FAVORITE.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if (
            value
            and _valid_value(value)
            and not _value_is_query_polluted(value)
            and not _is_person_affinity_value(value)
            and not _is_unsafe_or_sensitive_auto_value(value)
        ):
            domain = "food" if _is_food_value(value) else "general"
            return SemanticProfileIntent(
                kind="profile_write", category=f"favorite.{domain}",
                value=value, write_policy="auto_safe",
            )

    # P0-7K-FIX5B: no-pollution guard for "tôi thích X và X cũng thích tôi".
    # Save only the user's affection target; do not store "X, tôi" / "tôi" as ordinary
    # preferences. Querying whether X likes the user remains a later FIX5C concern.
    m = _RE_RELATION_ADJACENT_AFFECTION.match(stripped)
    if m:
        value = strip_additive_target_marker(_clean_value(m.group(1)))
        if value and _is_person_affinity_value(value):
            return SemanticProfileIntent(
                kind="profile_write", category="relationship.affection_candidate",
                value=value, sensitivity="person_affinity", write_policy="auto_safe",
            )

    # Preference ("tôi thích/mê/yêu thích/có sở thích X").
    m = _RE_PREF.match(stripped)
    if m:
        value = _clean_value(m.group(1))
        if not _valid_value(value):
            return None
        if _is_interrogative_value(value):
            return None
        # P0-7K-FIX1 A/J: never save a query/ranking phrase ("gì nhata", "gì nhất").
        if _value_is_query_polluted(value):
            return None
        if _is_unsafe_or_sensitive_auto_value(value):
            return SemanticProfileIntent(
                kind="profile_write", category="sensitive", value=value,
                sensitivity="unsafe", write_policy="block",
            )
        # P0-7I/P0-7J-FIX1: check the marker-stripped form too, so "quý mà" and
        # "cả may" are recognized as the persons "quý"/"may" (never saved verbatim
        # as ordinary preferences). Non-person objects ("cả kem") stay preferences.
        stripped_value = strip_additive_target_marker(value)
        if _is_person_affinity_value(value) or (
            stripped_value != value and _is_person_affinity_value(stripped_value)
        ):
            # P0-7G: "tôi thích Quý" now SAVES affection/person memory (was clarify).
            affection_value = (
                stripped_value if _is_person_affinity_value(stripped_value) else value
            )
            return SemanticProfileIntent(
                kind="profile_write", category="relationship.affection_candidate",
                value=affection_value, sensitivity="person_affinity", write_policy="auto_safe",
            )
        kind_pref = _classify_preference_kind(value)
        return SemanticProfileIntent(
            kind="profile_write", category=f"preference.{kind_pref}",
            value=value, write_policy="auto_safe",
        )

    # Bare affection verbs ("tôi yêu Quý", "tôi nhớ Quý", "tôi crush X") — person only.
    # P0-7G saves this as affection/person memory (was clarify).
    # P0-7J-FIX1: additive/discourse markers stripped ("tôi yêu cả may" → target "may").
    m = _RE_AFFECTION.match(stripped)
    if m:
        value = strip_additive_target_marker(_clean_value(m.group(1)))
        if value and _is_person_affinity_value(value):
            return SemanticProfileIntent(
                kind="profile_write", category="relationship.affection_candidate",
                value=value, sensitivity="person_affinity", write_policy="auto_safe",
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

    # P0-7H: "ngoài AI tôi còn làm blogger" — occupation alongside existing role.
    m = _RE_OCC_NGOAI.match(stripped)
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

    # P0-7H-FIX3: "tôi còn làm nông nữa" — additive occupation without "ngoài X" prefix.
    m = _RE_OCC_CON_LAM.match(stripped)
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
        # P0-7G-FIX3 A1: "tôi muốn đổi tên thành X" is a self-name update, not a desire —
        # defer to the dedicated name-update path instead of a near-miss clarification.
        if (
            low.startswith("đổi tên")
            or low.startswith("thay đổi tên")
            or low.startswith("đổi lại tên")
            or low.startswith("đặt lại tên")
        ):
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

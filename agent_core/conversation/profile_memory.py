"""CONV-P0 P0-7B/7C: Rule-based user profile fact detection and retrieval.

Provider-free. Covers self-name and four close-relation-name facts.
No LLM, no network, no TOMTIT-Memory changes.

P0-7C adds:
- anchored self-identity query (prevents "tôi là AI engineer" from triggering recall)
- relation synonym queries: người yêu, partner → match bạn gái/bạn trai records
- profile summary query: bạn biết/nhớ gì về tôi?
"""
from __future__ import annotations

import re
from dataclasses import dataclass
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
    relation_label: str | None = None   # "bạn gái", "vợ", etc.
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
    ]
    value: str | None = None          # for inverse_value: the name to look up
    relation_label: str | None = None  # for relation_name


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_QUESTION_WORDS = frozenset({"ai", "gì", "đây", "đó", "thế", "sao", "vậy", "như_thế_nào"})

# Storage-level relation labels (used in candidate detection and save).
_RELATIONS_CANDIDATE_PATTERN = r'(bạn\s+gái|bạn\s+trai|vợ|chồng)'

# Query-level relation labels: storage labels + P0-7C synonyms (người yêu, partner).
# Order: longer matches first to avoid partial overlap.
_RELATIONS_QUERY_PATTERN = r'(bạn\s+gái|bạn\s+trai|người\s+yêu|vợ|chồng|partner)'

_RELATION_TAG_MAP: dict[str, str] = {
    "bạn gái": "ban_gai",
    "bạn trai": "ban_trai",
    "vợ": "vo",
    "chồng": "chong",
}

# P0-7C: synonym expansion for relation queries. Keys are query labels that should
# match stored facts with any of the listed relation_label values.
_RELATION_SYNONYM_MAP: dict[str, frozenset[str]] = {
    "người yêu": frozenset({"bạn gái", "bạn trai", "người yêu", "partner"}),
    "partner": frozenset({"bạn gái", "bạn trai", "người yêu", "partner"}),
}


def _get_lookup_labels(query_label: str | None) -> frozenset[str]:
    """Expand a query relation label to the set of stored labels to search."""
    if query_label is None:
        return frozenset()
    return _RELATION_SYNONYM_MAP.get(query_label, frozenset({query_label}))


# --- Candidate detection ---

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
# "tôi là Bắc" / "mình là Bắc" — riskier, require capitalized name
_RE_SELF_IS = re.compile(
    r'^(?:tôi|mình)\s+là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.DOTALL,
)
# Relation-name candidate: "bạn gái tôi tên là Quý"
_RE_RELATION_NAME = re.compile(
    r'^' + _RELATIONS_CANDIDATE_PATTERN + r'\s+(?:tôi|mình)\s+tên\s+là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE | re.DOTALL,
)

# --- Query detection ---

# Self-name queries — unanchored (.search) intentional for "bạn nhớ tôi tên gì không?"
_RE_SELF_NAME_Q = re.compile(
    r'(?:tôi|mình|bạn)\s+tên\s+(?:là\s+)?g[ìi]\s*\??'
    r'|tên\s+(?:tôi|mình|bạn)\s+(?:là\s+)?g[ìi]\s*\??'
    r'|bạn\s+nhớ\s+(?:tôi|mình)\s+tên\s+g[ìi]',
    re.IGNORECASE,
)

# P0-7C FIX: fully anchored — prevents substring match inside
# "tôi là AI engineer", "note tôi là AI engineer", "người yêu của tôi là ai".
_RE_SELF_IDENTITY_Q = re.compile(
    r'^\s*(?:tôi|mình)\s+là\s+ai\s*[?？]?\s*$',
    re.IGNORECASE,
)

# Relation name query — "tên gì?" form. Includes P0-7C synonyms and optional "của".
# Anchored to prevent substring matches; uses extended query pattern.
_RE_RELATION_NAME_Q = re.compile(
    r'^' + _RELATIONS_QUERY_PATTERN
    + r'(?:\s+của)?\s+(?:tôi|mình)\s+tên\s+(?:là\s+)?g[ìi]\s*[?？]?\s*$',
    re.IGNORECASE,
)

# P0-7C NEW: relation "là ai?" form — "người yêu của tôi là ai?", "bạn gái của tôi là ai?"
_RE_RELATION_LA_AI_Q = re.compile(
    r'^' + _RELATIONS_QUERY_PATTERN
    + r'(?:\s+của)?\s+(?:tôi|mình)\s+là\s+ai\s*[?？]?\s*$',
    re.IGNORECASE,
)

# P0-7C NEW: profile summary queries — "bạn biết/nhớ/lưu gì về tôi?"
_RE_PROFILE_SUMMARY_Q = re.compile(
    r'^\s*bạn\s+(?:biết|nhớ|lưu|đang\s+nhớ)\s+(?:gì\s+)?về\s+(?:tôi|mình)\s*[?？]?\s*$',
    re.IGNORECASE,
)

# "Bắc là ai?" / "Quý là ai?" — subject must NOT be self-words
_RE_INVERSE_Q = re.compile(
    r'^([^\s.!?,]+)\s+là\s+ai\s*[?？]?\s*$',
    re.IGNORECASE,
)
_SELF_WORDS = frozenset({"tôi", "mình", "bạn", "tao", "ta"})

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
# Detection
# ---------------------------------------------------------------------------

def _is_proper_name(s: str) -> bool:
    """True if s looks like a proper noun (first char uppercase in Unicode)."""
    return bool(s) and s[0].isupper()


def _normalize_relation_label(raw: str) -> str:
    return re.sub(r'\s+', ' ', raw.strip().lower())


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

    # Self-is — riskier, require proper name (uppercase first char)
    m = _RE_SELF_IS.match(stripped)
    if m:
        value = m.group(1).rstrip('.!?').strip()
        if value and _is_proper_name(value) and value.lower() not in _QUESTION_WORDS:
            return ProfileFactCandidate(
                subject="self", relation="name",
                value=value, original_text=stripped,
            )

    # Relation-name (storage labels only — synonym capture is out of P0-7C scope)
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

    return None


def detect_profile_query(text: str) -> ProfileQuery | None:
    """Return a ProfileQuery if text is a profile question, else None.

    Priority order (P0-7C):
    1. Relation name "tên gì?" — anchored, extended with synonyms
    2. Relation "là ai?" — new form, anchored
    3. Profile summary — new
    4. Self-name — unanchored (.search) for "bạn nhớ tôi tên gì không?"
    5. Self-identity — FIXED: fully anchored to prevent substring match
    6. Inverse value lookup
    """
    stripped = text.strip()

    # 1. Relation name "tên gì?" form (includes synonyms + optional "của")
    m = _RE_RELATION_NAME_Q.match(stripped)
    if m:
        label = _normalize_relation_label(m.group(1))
        return ProfileQuery(kind="relation_name", relation_label=label)

    # 2. P0-7C: relation "là ai?" form — "người yêu của tôi là ai?"
    m = _RE_RELATION_LA_AI_Q.match(stripped)
    if m:
        label = _normalize_relation_label(m.group(1))
        return ProfileQuery(kind="relation_name", relation_label=label)

    # 3. P0-7C: profile summary — "bạn biết/nhớ gì về tôi?"
    if _RE_PROFILE_SUMMARY_Q.match(stripped):
        return ProfileQuery(kind="profile_summary")

    # 4. Self-name query (unanchored search; relation checks above guard against overlap)
    if _RE_SELF_NAME_Q.search(stripped):
        return ProfileQuery(kind="self_name")

    # 5. Self-identity — P0-7C FIX: fully anchored, use .match() not .search().
    # Prevents "tôi là AI engineer", "note tôi là AI...", "người yêu của tôi là ai"
    # from triggering self-identity recall via substring match.
    if _RE_SELF_IDENTITY_Q.match(stripped):
        return ProfileQuery(kind="self_identity")

    # 6. Inverse lookup: "Bắc là ai?" — exclude self-words as subject
    m = _RE_INVERSE_Q.match(stripped)
    if m:
        subject_word = m.group(1).strip().lower().rstrip('?')
        if subject_word not in _SELF_WORDS:
            return ProfileQuery(kind="inverse_value", value=m.group(1).strip().rstrip('?'))

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


# ---------------------------------------------------------------------------
# Retrieval / answering
# ---------------------------------------------------------------------------

def answer_profile_query(
    query: ProfileQuery,
    store: "MemoryStoreProtocol",
) -> str | None:
    """Return an answer string if a confirmed fact satisfies the query, else None."""
    records = store.search(MemoryQuery(
        text="",
        types=[MemoryType.FACT],
        tags=["user_profile"],
        limit=100,
    ))
    confirmed = [
        r for r in records
        if r.metadata.get("confirmed")
        and r.metadata.get("profile_schema") == "user_profile_fact_v1"
    ]

    if query.kind in ("self_name", "self_identity"):
        for rec in confirmed:
            if rec.metadata.get("subject") == "self" and rec.metadata.get("relation") == "name":
                name = rec.metadata.get("value", "")
                return f"Bạn tên là {name}."

    elif query.kind == "relation_name":
        # P0-7C: expand query label via synonym map so "người yêu" matches "bạn gái" records.
        lookup_labels = _get_lookup_labels(query.relation_label)
        for rec in confirmed:
            stored_label = rec.metadata.get("relation_label", "")
            if (
                rec.metadata.get("subject") == "relation"
                and rec.metadata.get("relation") == "name"
                and stored_label in lookup_labels
            ):
                name = rec.metadata.get("value", "")
                # Use stored label for display accuracy.
                display_label = stored_label or query.relation_label or ""
                return f"{display_label.capitalize()} của bạn tên là {name}."

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

    elif query.kind == "profile_summary":
        # P0-7C: list all confirmed profile facts; exclude notes.
        lines: list[str] = []
        for rec in confirmed:
            subject = rec.metadata.get("subject", "")
            rel = rec.metadata.get("relation", "")
            val = rec.metadata.get("value", "")
            if subject == "self" and rel == "name":
                lines.append(f"- Bạn tên là {val}.")
            elif subject == "relation" and rel == "name":
                rel_label = rec.metadata.get("relation_label", "người liên quan")
                lines.append(f"- {rel_label.capitalize()} của bạn tên là {val}.")
        if not lines:
            return "Tôi chưa có thông tin hồ sơ nào đã được xác nhận về bạn."
        return "Tôi đang nhớ những thông tin sau về bạn:\n" + "\n".join(lines)

    return None

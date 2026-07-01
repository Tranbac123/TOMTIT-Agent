"""CONV-P0 P0-7B: Rule-based user profile fact detection and retrieval.

Provider-free. Covers self-name and four close-relation-name facts.
No LLM, no network, no TOMTIT-Memory changes.
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
    kind: Literal["self_name", "self_identity", "relation_name", "inverse_value"]
    value: str | None = None          # for inverse_value: the name to look up
    relation_label: str | None = None  # for relation_name


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_QUESTION_WORDS = frozenset({"ai", "gì", "đây", "đó", "thế", "sao", "vậy", "như_thế_nào"})

_RELATIONS_PATTERN = r'(bạn\s+gái|bạn\s+trai|vợ|chồng)'

_RELATION_TAG_MAP: dict[str, str] = {
    "bạn gái": "ban_gai",
    "bạn trai": "ban_trai",
    "vợ": "vo",
    "chồng": "chong",
}

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
# "lưu tên tôi là Bắc", "(lưu) tên tôi là Bắc"
_RE_LUU_TEN_LA = re.compile(
    r'^lưu\s+tên\s+(?:tôi|mình)\s+là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# "tôi là Bắc" / "mình là Bắc" — riskier, require capitalized name
_RE_SELF_IS = re.compile(
    r'^(?:tôi|mình)\s+là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.DOTALL,
)
# Relation-name: "bạn gái tôi tên là Quý"
_RE_RELATION_NAME = re.compile(
    r'^' + _RELATIONS_PATTERN + r'\s+(?:tôi|mình)\s+tên\s+là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE | re.DOTALL,
)

# --- Query detection ---

_RE_SELF_NAME_Q = re.compile(
    r'(?:tôi|mình|bạn)\s+tên\s+(?:là\s+)?g[ìi]\s*\??'
    r'|tên\s+(?:tôi|mình|bạn)\s+(?:là\s+)?g[ìi]\s*\??'
    r'|bạn\s+nhớ\s+(?:tôi|mình)\s+tên\s+g[ìi]',
    re.IGNORECASE,
)
_RE_SELF_IDENTITY_Q = re.compile(
    r'(?:tôi|mình)\s+là\s+ai\s*\??',
    re.IGNORECASE,
)
_RE_RELATION_NAME_Q = re.compile(
    r'^' + _RELATIONS_PATTERN + r'\s+(?:tôi|mình)\s+tên\s+(?:là\s+)?g[ìi]\s*\??',
    re.IGNORECASE,
)
# "Bắc là ai?" / "Quý là ai?" — subject must NOT be tôi/mình/bạn
_RE_INVERSE_Q = re.compile(
    r'^([^\s.!?,]+)\s+là\s+ai\s*\??',
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

    # Relation-name
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
    """Return a ProfileQuery if text is a profile question, else None."""
    stripped = text.strip()

    # Relation-name query (check before self-name to avoid partial overlap)
    m = _RE_RELATION_NAME_Q.match(stripped)
    if m:
        label = _normalize_relation_label(m.group(1))
        return ProfileQuery(kind="relation_name", relation_label=label)

    # Self-name query
    if _RE_SELF_NAME_Q.search(stripped):
        return ProfileQuery(kind="self_name")

    # Self-identity query
    if _RE_SELF_IDENTITY_Q.search(stripped):
        return ProfileQuery(kind="self_identity")

    # Inverse lookup: "Bắc là ai?" — exclude self-words as subject
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
        for rec in confirmed:
            if (
                rec.metadata.get("subject") == "relation"
                and rec.metadata.get("relation") == "name"
                and rec.metadata.get("relation_label") == query.relation_label
            ):
                name = rec.metadata.get("value", "")
                label = query.relation_label or ""
                return f"{label.capitalize()} của bạn tên là {name}."

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

"""CONV-P0 P0-7J: TOMTIT Memory Kernel v1 — bounded structured memory update semantics.

Turns a narrow set of memory-update utterances into a structured ``MemoryOperation``,
validates it, resolves conflicts against the current store state, and applies it as a
small transaction. This replaces scattered one-off regex handling for update/removal
semantics with one explicit pipeline:

    text → parse_memory_operation → MemoryOperation
         → validate_memory_operation (policy)
         → apply_memory_operation   (conflict resolve + transaction → response)

Boundaries (kernel contract):
- The parser never writes memory.
- The conflict resolver never parses text.
- The store never infers semantics (only narrow delete/save calls).
- Response builders never invent memory facts (they only echo the applied operation).

Provider-free. No LLM, no network, no vector/RAG. Storage primitives are reused from
``profile_memory`` (same delete-then-save supersede style as relation updates).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from agent_core.conversation.profile_memory import (
    AutoProfileCandidate,
    _is_unsafe_or_sensitive_auto_value,
    _is_valid_auto_value_shape,
    _norm_cmp,
    _normalize_relation_label,
    build_name_update_ack,
    build_relation_update_ack,
    collect_profile_snapshot,
    delete_occupation_fact,
    resolve_preference_conflicts,
    save_affection_fact,
    save_auto_profile_fact,
    save_relation_update,
    save_self_name_update,
)
from agent_core.conversation.profile_semantics import (
    _classify_preference_kind,
    _has_professional_token,
    strip_additive_target_marker,
)
from agent_core.memory.memory_records import MemoryQuery
from agent_core.state.enums import MemoryType

if TYPE_CHECKING:
    from agent_core.memory.base import MemoryStoreProtocol


MemoryOpType = Literal[
    "ADD",
    "UPDATE_CURRENT",
    "REMOVE",
    "NEGATE",
    "QUERY",
    "CORRECT",
    "SWITCH",
    # P0-7K: partial removal (compound goals) and whole-domain removal (affection).
    "REMOVE_PART",
    "REMOVE_ALL",
]

MemoryDomain = Literal[
    "name",
    "occupation",
    "preference",
    "negative_preference",
    "affection",
    "relationship",
    "goal",
]


@dataclass(frozen=True)
class MemoryOperation:
    """One structured memory update parsed from a user utterance.

    ``canonical_key`` is the normalized matching key for conflict resolution. For
    SWITCH operations, ``value`` is the NEW value and ``canonical_key`` is the key of
    the OLD value being replaced (the thing to resolve away).
    """
    op: MemoryOpType
    domain: MemoryDomain
    subject: str
    value: str
    canonical_key: str
    polarity: str | None = None
    relation: str | None = None
    source: str = "user_explicit"
    confidence: float = 1.0
    raw_text: str = ""


@dataclass(frozen=True)
class MemoryOperationOutcome:
    """Result of applying a MemoryOperation: user-facing text + runtime trace marker."""
    response_text: str
    trace_marker: str
    saved: bool = False


# ---------------------------------------------------------------------------
# Canonicalization helpers
# ---------------------------------------------------------------------------

# Trailing Vietnamese discourse particles that never belong in a stored value.
_TERMINAL_DISCOURSE_MARKERS: frozenset[str] = frozenset({"mà", "đó", "nhé", "nha"})

# Current-state update markers ("bây giờ người yêu của tôi là quý"). P0-7J-FIX1 adds
# no-diacritic/typo variants (bay giờ / hien tai / tu nay / gio) and inline positions
# ("người yêu bây giờ của tôi là X", "người yêu của tôi bây giờ là X").
_TEMPORAL_MARKER_CORE = (
    r'(?:(?:bây|bay)\s+(?:giờ|gio)'
    r'|(?:hiện|hien)\s+(?:tại|tai)'
    r'|(?:từ|tu)\s+(?:nay|giờ|gio)'
    r'|(?:giờ|gio)(?:\s+thì)?)'
)
_RE_TEMPORAL_MARKER = re.compile(
    r'^' + _TEMPORAL_MARKER_CORE + r'\s*,?\s+',
    re.IGNORECASE,
)
_RE_INLINE_TEMPORAL_MARKER = re.compile(
    r'\s+' + _TEMPORAL_MARKER_CORE + r'(?=\s)',
    re.IGNORECASE,
)

# Leading intent verbs stripped when building a goal conflict key, so "build LLM" and
# "làm LLM" resolve to the same key "llm".
_GOAL_KEY_VERB_PREFIXES: tuple[str, ...] = ("làm ", "build ", "xây dựng ")


def canonicalize_memory_value(value: str) -> str:
    """Normalize a value for conflict matching (whitespace, case, edge punctuation)."""
    return re.sub(r"\s+", " ", value.strip().rstrip(".!?？,")).strip().lower()


def strip_temporal_update_marker(text: str) -> tuple[str, bool]:
    """Strip a leading current-state marker; return (remainder, had_marker)."""
    stripped = text.strip()
    m = _RE_TEMPORAL_MARKER.match(stripped)
    if m:
        return stripped[m.end():].strip(), True
    return stripped, False


def strip_terminal_discourse_marker(value: str) -> str:
    """Strip one trailing discourse particle ("quý mà" → "quý"); never empties the value."""
    tokens = value.split()
    if len(tokens) >= 2 and tokens[-1].lower() in _TERMINAL_DISCOURSE_MARKERS:
        return " ".join(tokens[:-1]).strip()
    return value


def _goal_conflict_key(value: str) -> str:
    """Conflict key for goal values: canonical form minus leading intent verbs."""
    key = canonicalize_memory_value(value)
    changed = True
    while changed:
        changed = False
        for prefix in _GOAL_KEY_VERB_PREFIXES:
            if key.startswith(prefix):
                key = key[len(prefix):].strip()
                changed = True
    return key


def _goal_keys_match(stored_key: str, query_key: str) -> bool:
    """Token-containment goal matching: "llm" negates the stored goal "ai llm".

    Either key's token set may contain the other's — bounded to the goal domain, so a
    partial mention ("không làm LLM nữa") still resolves the fuller stored goal.
    """
    stored_tokens = set(stored_key.split())
    query_tokens = set(query_key.split())
    if not stored_tokens or not query_tokens:
        return False
    return stored_tokens <= query_tokens or query_tokens <= stored_tokens


# P0-7J-FIX1: additive markers that make a goal write ADD alongside existing goals
# instead of superseding them ("tôi còn muốn làm AI Agent"). "không còn" is negation,
# not additive, hence the fixed-width lookbehind.
_RE_ADDITIVE_GOAL_MARKER = re.compile(
    r'(?:ngoài\s+ra|\bcũng\b|\bthêm\b|(?<!không)\s+còn\s+)',
    re.IGNORECASE,
)


def _has_additive_goal_marker(text: str) -> bool:
    return bool(_RE_ADDITIVE_GOAL_MARKER.search(" " + re.sub(r"\s+", " ", text.strip()) + " "))


# ---------------------------------------------------------------------------
# Parser (DomainParser) — text in, MemoryOperation out; never touches the store
# ---------------------------------------------------------------------------

# Goal switch: "tôi không muốn build LLM nữa tôi muốn build AI Agent".
_RE_OP_GOAL_SWITCH = re.compile(
    r'^(?:tôi|mình)\s+không\s+muốn\s+(.+?)\s+nữa\s*,?\s+'
    r'(?:mà\s+)?(?:tôi\s+|mình\s+)?muốn\s+(.+?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# Occupation stop: "tôi không làm blogger nữa", "tôi không còn làm X", "tôi nghỉ làm X".
_RE_OP_OCC_REMOVE = re.compile(
    r'^(?:tôi|mình)\s+(?:không\s+(?:còn\s+)?làm|nghỉ\s+làm)\s+(?:nghề\s+)?'
    r'(.+?)(?:\s+nữa)?\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# Affection removal: "tôi không thích quý nữa", "tôi không yêu may",
# "tôi không quan tâm X nữa". Applied only when the target is an ACTIVE affection.
_RE_OP_AFFECTION_REMOVE = re.compile(
    r'^(?:tôi|mình)\s+không\s+(?:còn\s+)?'
    r'(?:thích|yêu|thương|crush|quan\s+tâm(?:\s+(?:đến|tới))?)\s+'
    r'(.+?)(?:\s+nữa)?\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# Relationship assertion (checked only AFTER a temporal marker was stripped).
_RE_OP_REL_ASSERT = re.compile(
    r'^(bạn\s+gái|bạn\s+trai|người\s+yêu|vợ|chồng|partner)\s+'
    r'(?:của\s+)?(?:tôi|mình)\s+(?:tên\s+)?là\s+([^\s.!?,]+)\s*[.!?]*\s*$',
    re.IGNORECASE,
)
# Future intent: "tôi sẽ build AI model LLM" — goal ADD (professional-token gated).
_RE_OP_GOAL_WILL = re.compile(
    r'^(?:tôi|mình)\s+sẽ\s+(.+?)\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
# P0-7J-FIX1 goal negation. The "sẽ không" form is an explicit future negation (gets a
# deterministic no-op reply even when nothing is stored); the "không muốn làm/build"
# form falls through when nothing matches so the P0-7G negative-desire clarify keeps
# owning non-goal desires ("tôi không muốn đi học").
_RE_OP_GOAL_NEGATE_SE = re.compile(
    r'^(?:tôi|mình)\s+(?:sẽ|se)\s+không\s+(?:còn\s+)?(?:làm|build)\s+'
    r'(.+?)(?:\s+nữa)?\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)
_RE_OP_GOAL_NEGATE_WANT = re.compile(
    r'^(?:tôi|mình)\s+không\s+(?:còn\s+)?(?:muốn\s+(?:làm|build)|build)\s+'
    r'(.+?)(?:\s+nữa)?\s*[.!]*\s*$',
    re.IGNORECASE | re.DOTALL,
)

_INTERROGATIVE_TAILS: tuple[str, ...] = (" gì", " gi", " ai", " đâu", " nào")


def _looks_interrogative(value: str) -> bool:
    v = canonicalize_memory_value(value)
    return v in {"gì", "gi", "ai", "đâu", "nào"} or any(
        v.endswith(t) for t in _INTERROGATIVE_TAILS
    )


def _clean_op_value(raw: str) -> str:
    value = re.sub(r"\s+", " ", raw.strip().rstrip(".!?？,")).strip()
    return strip_terminal_discourse_marker(value)


def parse_memory_operation(text: str) -> MemoryOperation | None:
    """Parse a bounded memory-update utterance into a MemoryOperation, else None.

    Question-like turns never parse (queries stay with detect_profile_query).
    """
    stripped = text.strip()
    if not stripped or '?' in stripped or '？' in stripped:
        return None

    # 1. Goal switch — most specific ("không muốn X nữa ... muốn Y").
    m = _RE_OP_GOAL_SWITCH.match(stripped)
    if m:
        old = _clean_op_value(m.group(1))
        new = _clean_op_value(m.group(2))
        if old and new and not _looks_interrogative(new):
            return MemoryOperation(
                op="SWITCH", domain="goal", subject="self", value=new,
                canonical_key=_goal_conflict_key(old), polarity="positive",
                raw_text=stripped,
            )

    # 2. P0-7J-FIX1: standalone goal negation ("tôi sẽ không làm LLM nữa",
    #    "tôi không muốn build X nữa"). Never saved as a positive goal.
    for pat, source in (
        (_RE_OP_GOAL_NEGATE_SE, "goal_negation_se"),
        (_RE_OP_GOAL_NEGATE_WANT, "user_explicit"),
    ):
        m = pat.match(stripped)
        if m:
            value = _clean_op_value(m.group(1))
            if value and not _looks_interrogative(value):
                return MemoryOperation(
                    op="REMOVE", domain="goal", subject="self", value=value,
                    canonical_key=_goal_conflict_key(value), polarity="negative",
                    source=source, raw_text=stripped,
                )

    # 3. Occupation stop ("không làm X nữa", "không còn làm X", "nghỉ làm X").
    m = _RE_OP_OCC_REMOVE.match(stripped)
    if m:
        value = _clean_op_value(m.group(1))
        if value and not _looks_interrogative(value):
            return MemoryOperation(
                op="REMOVE", domain="occupation", subject="self", value=value,
                canonical_key=canonicalize_memory_value(value), polarity="negative",
                raw_text=stripped,
            )

    # 4. Affection removal ("không thích/yêu/quan tâm X (nữa)"). The resolver applies
    #    this only when X is an active affection; otherwise the turn falls through to
    #    the ordinary negative-preference path unchanged.
    m = _RE_OP_AFFECTION_REMOVE.match(stripped)
    if m:
        value = _clean_op_value(m.group(1))
        if value and not _looks_interrogative(value):
            return MemoryOperation(
                op="REMOVE", domain="affection", subject="self", value=value,
                canonical_key=canonicalize_memory_value(value), polarity="negative",
                raw_text=stripped,
            )

    # 5. Relationship current-update: leading marker ("bây giờ người yêu của tôi là X")
    #    or inline marker ("người yêu bây giờ của tôi là X" / "... của tôi bây giờ là X").
    #    P0-7J-FIX1 also accepts no-diacritic marker typos ("bay giờ", "hien tai").
    remainder, had_marker = strip_temporal_update_marker(stripped)
    if not had_marker:
        cleaned, n_subs = _RE_INLINE_TEMPORAL_MARKER.subn(" ", remainder, count=1)
        if n_subs:
            remainder = re.sub(r"\s+", " ", cleaned).strip()
            had_marker = True
    if had_marker:
        m = _RE_OP_REL_ASSERT.match(remainder)
        if m:
            label = _normalize_relation_label(m.group(1))
            name = _clean_op_value(m.group(2))
            if name and not _looks_interrogative(name):
                return MemoryOperation(
                    op="UPDATE_CURRENT", domain="relationship", subject="relation",
                    value=name, canonical_key=canonicalize_memory_value(name),
                    relation=label, raw_text=stripped,
                )

    # 6. Future intent ("tôi sẽ build X") — goal ADD, professional-token gated so
    #    everyday plans ("tôi sẽ đi ngủ") keep flowing to the router.
    m = _RE_OP_GOAL_WILL.match(stripped)
    if m:
        value = _clean_op_value(m.group(1))
        if value and not _looks_interrogative(value) and _has_professional_token(value):
            return MemoryOperation(
                op="ADD", domain="goal", subject="self", value=value,
                canonical_key=_goal_conflict_key(value), polarity="positive",
                raw_text=stripped,
            )

    return None


# ---------------------------------------------------------------------------
# Policy validator
# ---------------------------------------------------------------------------

def validate_memory_operation(op: MemoryOperation) -> bool:
    """Reject operations whose value is empty, malformed, or unsafe/sensitive."""
    if not op.value.strip():
        return False
    if _is_unsafe_or_sensitive_auto_value(op.value):
        return False
    # Writes must carry a meaningfully-shaped value; removals may be short ("IT").
    if op.op in ("ADD", "SWITCH") and not _is_valid_auto_value_shape(op.value):
        return False
    return True


# ---------------------------------------------------------------------------
# Conflict resolver (store-facing; never parses text)
# ---------------------------------------------------------------------------

def _confirmed_profile_facts(store: "MemoryStoreProtocol") -> list:
    records = list(store.search(MemoryQuery(
        text="", types=[MemoryType.FACT], tags=["user_profile"], limit=200,
    )))
    return [
        r for r in records
        if r.metadata.get("confirmed")
        and r.metadata.get("profile_schema") in ("user_profile_fact_v1", "user_profile_fact_v2")
    ]


def delete_affection_fact(value: str, store: "MemoryStoreProtocol") -> str | None:
    """Delete active affection records matching value; return matched display value."""
    target = canonicalize_memory_value(value)
    matched: str | None = None
    for rec in _confirmed_profile_facts(store):
        md = rec.metadata
        if md.get("subject") != "self" or md.get("relation") != "affection":
            continue
        stored = md.get("value", "")
        if _norm_cmp(stored) == target:
            store.delete(rec.id, reason="user_removal")
            matched = matched or stored
    return matched


def delete_all_affection_facts(store: "MemoryStoreProtocol") -> int:
    """P0-7K: delete ALL active affection records ("bây giờ tôi không thích ai nữa")."""
    removed = 0
    for rec in _confirmed_profile_facts(store):
        md = rec.metadata
        if md.get("subject") == "self" and md.get("relation") == "affection":
            store.delete(rec.id, reason="user_removal")
            removed += 1
    return removed


def delete_goal_facts(conflict_key: str, store: "MemoryStoreProtocol") -> str | None:
    """Delete goal records whose conflict key matches (token containment).

    Returns the matched display value, or None. "llm" matches the stored goal
    "làm AI LLM" so a partial negation still resolves the fuller goal (P0-7J-FIX1).
    """
    matched: str | None = None
    for rec in _confirmed_profile_facts(store):
        md = rec.metadata
        if md.get("subject") != "self" or md.get("relation") != "goal":
            continue
        stored = md.get("value", "")
        if stored and _goal_keys_match(_goal_conflict_key(stored), conflict_key):
            store.delete(rec.id, reason="goal_superseded")
            matched = matched or stored
    return matched


def resolve_goal_current_state(raw_text: str, store: "MemoryStoreProtocol") -> None:
    """P0-7J-FIX1: goal memory is current-state by default — a new explicit goal
    supersedes ALL previous goals unless the utterance carries an additive marker
    (ngoài ra / còn / cũng / thêm), which keeps existing goals alongside the new one.
    """
    if _has_additive_goal_marker(raw_text):
        return
    for rec in _confirmed_profile_facts(store):
        md = rec.metadata
        if md.get("subject") == "self" and md.get("relation") == "goal":
            store.delete(rec.id, reason="goal_superseded")


# ---------------------------------------------------------------------------
# Response builders (echo the applied operation; never invent facts)
# ---------------------------------------------------------------------------

def build_occupation_stop_ack(value: str) -> str:
    return (
        f"Đã ghi nhận bạn không còn làm {value} nữa. "
        "Mình đã cập nhật lại thông tin nghề nghiệp của bạn."
    )


def build_affection_removed_ack(value: str) -> str:
    return (
        f"Đã ghi nhận bạn không còn thích/quan tâm {value} nữa. "
        "Mình đã cập nhật lại thông tin này."
    )


def build_goal_saved_ack(value: str) -> str:
    return (
        f"Đã nhớ dự định hiện tại của bạn: {value}. "
        "Mình sẽ tính đến điều này khi hỗ trợ bạn."
    )


def build_goal_switched_ack(new_value: str) -> str:
    return (
        f"Đã cập nhật dự định của bạn: hiện tại bạn muốn {new_value}. "
        "Mình không còn giữ dự định cũ như mục tiêu hiện tại nữa."
    )


def build_goal_removed_ack(value: str) -> str:
    return (
        f"Đã ghi nhận: bạn không còn theo đuổi mục tiêu '{value}' nữa. "
        "Mình đã bỏ mục tiêu này khỏi hồ sơ của bạn."
    )


def build_goal_negation_noop_response(value: str) -> str:
    return (
        f"Đã ghi nhận: bạn không làm {value} nữa. Hiện mình cũng không thấy "
        f"mục tiêu hay công việc nào về {value} đang được lưu."
    )


# ---------------------------------------------------------------------------
# Transaction — apply one validated operation against the store
# ---------------------------------------------------------------------------

def apply_memory_operation(
    op: MemoryOperation,
    store: "MemoryStoreProtocol",
    session_id: str,
) -> MemoryOperationOutcome | None:
    """Resolve conflicts and apply the operation. Returns None to fall through.

    A None return means the operation does not apply to current memory state (e.g. an
    affection removal whose target is not an active affection) — the caller lets the
    turn continue through the normal handler chain.
    """
    if not validate_memory_operation(op):
        return None

    if op.op == "REMOVE" and op.domain == "occupation":
        removed = delete_occupation_fact(op.value, store)
        if removed is not None:
            return MemoryOperationOutcome(
                build_occupation_stop_ack(removed), "conv:memop_occupation_removed"
            )
        # P0-7J-FIX1: "tôi không làm X nữa" may negate a GOAL rather than an occupation.
        removed_goal = delete_goal_facts(_goal_conflict_key(op.value), store)
        if removed_goal is not None:
            return MemoryOperationOutcome(
                build_goal_removed_ack(removed_goal), "conv:memop_goal_removed"
            )
        return None

    if op.op == "REMOVE" and op.domain == "goal":
        # P0-7J-FIX1: "tôi sẽ không làm X nữa" / "tôi không muốn build X nữa".
        removed_goal = delete_goal_facts(op.canonical_key, store)
        if removed_goal is not None:
            return MemoryOperationOutcome(
                build_goal_removed_ack(removed_goal), "conv:memop_goal_removed"
            )
        removed_occ = delete_occupation_fact(op.value, store)
        if removed_occ is not None:
            return MemoryOperationOutcome(
                build_occupation_stop_ack(removed_occ), "conv:memop_occupation_removed"
            )
        # The explicit future-negation form gets an honest deterministic reply even
        # when nothing matches; other forms fall through (negative-desire clarify).
        if op.source == "goal_negation_se":
            return MemoryOperationOutcome(
                build_goal_negation_noop_response(op.value), "conv:memop_goal_negation_noop"
            )
        return None

    if op.op == "REMOVE" and op.domain == "affection":
        snap = collect_profile_snapshot(store)
        if not any(_norm_cmp(a) == op.canonical_key for a in snap.affections):
            return None
        removed = delete_affection_fact(op.value, store)
        if removed is None:
            return None
        return MemoryOperationOutcome(
            build_affection_removed_ack(removed), "conv:memop_affection_removed"
        )

    if op.op == "UPDATE_CURRENT" and op.domain == "relationship":
        label = op.relation or ""
        if not label:
            return None
        if not save_relation_update(
            label, op.value, store, session_id, original_text=op.raw_text
        ):
            return None
        return MemoryOperationOutcome(
            build_relation_update_ack(label, op.value),
            "conv:memop_relation_updated", saved=True,
        )

    if op.op == "SWITCH" and op.domain == "goal":
        delete_goal_facts(op.canonical_key, store)  # absent old goal is not an error
        # P0-7J-FIX1: a switch names the new CURRENT goal — supersede remaining goals.
        resolve_goal_current_state(op.raw_text, store)
        candidate = AutoProfileCandidate(
            subject="self", relation="goal", value=op.value, original_text=op.raw_text,
        )
        if not save_auto_profile_fact(candidate, store, session_id):
            return None
        return MemoryOperationOutcome(
            build_goal_switched_ack(op.value), "conv:memop_goal_switched", saved=True,
        )

    if op.op == "ADD" and op.domain == "goal":
        # P0-7J-FIX1: goal memory is current-state — non-additive writes supersede.
        resolve_goal_current_state(op.raw_text, store)
        candidate = AutoProfileCandidate(
            subject="self", relation="goal", value=op.value, original_text=op.raw_text,
        )
        if not save_auto_profile_fact(candidate, store, session_id):
            return None
        return MemoryOperationOutcome(
            build_goal_saved_ack(op.value), "conv:memop_goal_saved", saved=True,
        )

    return None

# ---------------------------------------------------------------------------
# P0-7K: MemoryOperation batch application (semantic extractor transaction)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BatchApplyResult:
    """Result of applying an extracted MemoryOperation batch.

    Operations that fail validation are skipped and counted in ``failed`` —
    partial failure is reported, never silently absorbed.
    """
    applied: int
    failed: int
    saved_count: int
    response_text: str | None


def apply_memory_operations(
    ops: tuple[MemoryOperation, ...] | list[MemoryOperation],
    store: "MemoryStoreProtocol",
    session_id: str,
    *,
    raw_text: str = "",
) -> BatchApplyResult:
    """Validate, conflict-resolve, and apply a batch of extracted operations.

    Within one batch, goal ADDs supersede PRE-EXISTING goals exactly once, so a
    decomposed compound goal ("build LLM" + "build SLM") keeps all of its own parts.
    """
    applied = 0
    failed = 0
    saved = 0
    pos_prefs: list[str] = []
    neg_prefs: list[str] = []
    goals_added: list[str] = []
    affections_added: list[str] = []
    ack_parts: list[str] = []
    goal_supersede_done = False

    snap = collect_profile_snapshot(store)
    current_name = snap.name
    active_affections = {_norm_cmp(a) for a in snap.affections}

    for op in ops:
        if op.op == "REMOVE_ALL" and op.domain == "affection":
            removed = delete_all_affection_facts(store)
            applied += 1
            if removed:
                ack_parts.append(
                    "Đã ghi nhận: hiện tại bạn không thích ai nữa. "
                    "Mình đã xóa thông tin về người bạn thích."
                )
            else:
                ack_parts.append(
                    "Đã ghi nhận: hiện tại bạn không thích ai. "
                    "Mình cũng không thấy thông tin nào về người bạn thích đang được lưu."
                )
            continue

        if not validate_memory_operation(op):
            failed += 1
            continue

        if op.domain == "preference" and op.op in ("ADD", "NEGATE"):
            if op.polarity == "negative" or op.op == "NEGATE":
                resolve_preference_conflicts(op.value, "negative_preference", store)
                candidate = AutoProfileCandidate(
                    relation="negative_preference", value=op.value,
                    original_text=raw_text or op.raw_text,
                )
                if save_auto_profile_fact(candidate, store, session_id):
                    applied += 1
                    saved += 1
                    neg_prefs.append(op.value)
                else:
                    failed += 1
            else:
                resolve_preference_conflicts(op.value, "preference", store)
                candidate = AutoProfileCandidate(
                    relation="preference", value=op.value,
                    original_text=raw_text or op.raw_text,
                    preference_kind=_classify_preference_kind(op.value),
                )
                if save_auto_profile_fact(candidate, store, session_id):
                    applied += 1
                    saved += 1
                    pos_prefs.append(op.value)
                else:
                    failed += 1
            continue

        if op.domain == "affection" and op.op == "ADD":
            if _norm_cmp(op.value) in active_affections:
                applied += 1
                affections_added.append(op.value)
                continue
            if save_affection_fact(
                op.value, store, session_id, original_text=raw_text or op.raw_text
            ):
                applied += 1
                saved += 1
                active_affections.add(_norm_cmp(op.value))
                affections_added.append(op.value)
            else:
                failed += 1
            continue

        if op.domain == "affection" and op.op in ("REMOVE", "REMOVE_PART"):
            if delete_affection_fact(op.value, store) is not None:
                applied += 1
                ack_parts.append(
                    f"Đã ghi nhận bạn không còn thích/quan tâm {op.value} nữa."
                )
            else:
                failed += 1
            continue

        if op.domain == "name" and op.op in ("CORRECT", "UPDATE_CURRENT", "ADD"):
            if save_self_name_update(
                op.value, store, session_id, original_text=raw_text or op.raw_text
            ):
                applied += 1
                saved += 1
                if current_name:
                    ack_parts.append(build_name_update_ack(current_name, op.value))
                else:
                    ack_parts.append(f"Đã nhớ tên bạn là {op.value}.")
                current_name = op.value
            else:
                failed += 1
            continue

        if op.domain == "relationship" and op.op in ("UPDATE_CURRENT", "CORRECT", "ADD"):
            label = op.relation or ""
            if label and save_relation_update(
                label, op.value, store, session_id, original_text=raw_text or op.raw_text
            ):
                applied += 1
                saved += 1
                ack_parts.append(build_relation_update_ack(label, op.value))
            else:
                failed += 1
            continue

        if op.domain == "goal" and op.op == "ADD":
            if not goal_supersede_done:
                resolve_goal_current_state(raw_text or op.raw_text, store)
                goal_supersede_done = True
            candidate = AutoProfileCandidate(
                subject="self", relation="goal", value=op.value,
                original_text=raw_text or op.raw_text,
            )
            if save_auto_profile_fact(candidate, store, session_id):
                applied += 1
                saved += 1
                goals_added.append(op.value)
            else:
                failed += 1
            continue

        if op.domain == "goal" and op.op in ("REMOVE", "REMOVE_PART"):
            if delete_goal_facts(op.canonical_key, store) is not None:
                applied += 1
                ack_parts.append(build_goal_removed_ack(op.value))
            else:
                failed += 1
            continue

        failed += 1

    if pos_prefs and neg_prefs:
        ack_parts.insert(0, (
            "Đã nhớ: bạn thích " + ", ".join(pos_prefs)
            + "; bạn không thích " + ", ".join(neg_prefs) + "."
        ))
    elif pos_prefs:
        ack_parts.insert(0, "Đã nhớ là bạn thích " + ", ".join(pos_prefs) + ".")
    elif neg_prefs:
        ack_parts.insert(0, "Đã nhớ là bạn không thích " + ", ".join(neg_prefs) + ".")
    if goals_added:
        ack_parts.append(
            "Đã nhớ dự định hiện tại của bạn: " + ", ".join(goals_added) + "."
        )
    if affections_added:
        ack_parts.append(
            "Đã nhớ là bạn có tình cảm/thích " + ", ".join(affections_added)
            + ". Mình sẽ không xếp thông tin này vào sở thích thông thường."
        )

    response = " ".join(ack_parts) if (applied and ack_parts) else None
    return BatchApplyResult(
        applied=applied, failed=failed, saved_count=saved, response_text=response,
    )

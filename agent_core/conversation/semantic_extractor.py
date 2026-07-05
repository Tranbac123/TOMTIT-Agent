"""CONV-P0 P0-7K: hybrid semantic memory extractor.

Bounded hybrid architecture for natural multi-fact memory utterances:

    user text
    → deterministic parser first (existing handlers; simple/high-confidence)
    → if complex/ambiguous/multi-fact/correction: semantic operation extractor
    → MemoryOperation[]  (structured proposals — NEVER direct writes)
    → policy validation (memory_operations.validate_memory_operation)
    → conflict resolution + transaction (memory_operations.apply_memory_operations)
    → snapshot/response

Extractor backends implement ``SemanticOperationExtractorProtocol``:

- ``RuleBasedSemanticOperationExtractor`` — deterministic, provider-free default.
  Handles the bounded complex patterns real manual Web testing surfaced (multi-fact
  mixed-polarity preference lists, "mới đúng" name corrections, "đã đổi ... rồi"
  relationship corrections, compound goals "cả LLM và SLM", remove-all affection,
  inverse affection assertions).
- ``FakeSemanticOperationExtractor`` — canned fixture extractor for tests/probes.
- A real LLM provider adapter is NOT included in P0-7K; the strict JSON contract
  (``parse_semantic_operations_json``) is the integration seam for one. An LLM may
  only ever PROPOSE operations through this contract — every operation still passes
  the policy validator and conflict resolver before any store write.

Provider-free by default. No LLM, no network, no vector/RAG.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from agent_core.conversation.memory_operations import (
    MemoryOperation,
    _goal_conflict_key,
    canonicalize_memory_value,
)
from agent_core.conversation.profile_memory import (
    _is_unsafe_or_sensitive_auto_value,
    _normalize_relation_label,
    detect_profile_fact_candidate,
)
from agent_core.conversation.profile_semantics import (
    _is_person_affinity_value,
    strip_additive_target_marker,
    strip_terminal_discourse_markers,
)

# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

ALLOWED_OPS: frozenset[str] = frozenset({
    "ADD", "UPDATE_CURRENT", "REMOVE", "NEGATE", "QUERY", "CORRECT", "SWITCH",
    "REMOVE_PART", "REMOVE_ALL",
})
ALLOWED_DOMAINS: frozenset[str] = frozenset({
    "name", "preference", "affection", "relationship", "goal",
    # P0-7K-FIX2: multi-item skill decomposition ("tôi biết đọc sách và hát").
    "skill",
})
MAX_OPERATIONS_PER_UTTERANCE = 12
MIN_EXTRACTION_CONFIDENCE = 0.5

# Operations that require a non-empty value (REMOVE_ALL clears a whole domain).
_VALUE_REQUIRED_OPS: frozenset[str] = frozenset({
    "ADD", "UPDATE_CURRENT", "REMOVE", "NEGATE", "CORRECT", "SWITCH", "REMOVE_PART",
})


@dataclass(frozen=True)
class SemanticExtractionRequest:
    raw_text: str
    locale: str = "vi"
    available_domains: tuple[str, ...] = (
        "name", "preference", "affection", "relationship", "goal",
    )


@dataclass(frozen=True)
class SemanticExtractionResult:
    operations: tuple[MemoryOperation, ...]
    unsupported_domains: tuple[str, ...] = ()
    confidence: float = 0.0
    source: str = "llm_semantic_extractor"
    raw_json: str | None = None
    error: str | None = None


class SemanticOperationExtractorProtocol(Protocol):
    def extract(self, request: SemanticExtractionRequest) -> SemanticExtractionResult:
        ...


_EMPTY_RESULT = SemanticExtractionResult(operations=(), confidence=0.0)


# ---------------------------------------------------------------------------
# Strict JSON contract validation (the seam a real LLM adapter must pass through)
# ---------------------------------------------------------------------------

def parse_semantic_operations_json(raw: str) -> SemanticExtractionResult:
    """Parse extractor JSON into validated MemoryOperations, or an error result.

    Structural violations (invalid JSON, unknown op/domain, too many operations)
    reject the WHOLE batch — a partially-understood proposal must not write memory.
    Per-operation value violations (empty/unsafe) drop only that operation.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return SemanticExtractionResult(
            operations=(), raw_json=raw, error="invalid_json",
        )
    if not isinstance(data, dict) or not isinstance(data.get("operations"), list):
        return SemanticExtractionResult(
            operations=(), raw_json=raw, error="invalid_structure",
        )
    ops_raw = data["operations"]
    if len(ops_raw) > MAX_OPERATIONS_PER_UTTERANCE:
        return SemanticExtractionResult(
            operations=(), raw_json=raw, error="too_many_operations",
        )

    operations: list[MemoryOperation] = []
    dropped: list[str] = []
    for entry in ops_raw:
        if not isinstance(entry, dict):
            return SemanticExtractionResult(
                operations=(), raw_json=raw, error="invalid_operation_entry",
            )
        op_type = entry.get("op", "")
        domain = entry.get("domain", "")
        if op_type not in ALLOWED_OPS:
            return SemanticExtractionResult(
                operations=(), raw_json=raw, error=f"unknown_op:{op_type}",
            )
        if domain not in ALLOWED_DOMAINS:
            return SemanticExtractionResult(
                operations=(), raw_json=raw, error=f"unknown_domain:{domain}",
            )
        value = str(entry.get("value") or "").strip()
        if op_type in _VALUE_REQUIRED_OPS and not value:
            dropped.append("empty_value")
            continue
        if value and _is_unsafe_or_sensitive_auto_value(value):
            dropped.append("unsafe_value")
            continue
        operations.append(MemoryOperation(
            op=op_type, domain=domain,  # type: ignore[arg-type]
            subject="relation" if domain == "relationship" else "self",
            value=value,
            canonical_key=str(
                entry.get("canonical_key") or canonicalize_memory_value(value)
            ),
            polarity=entry.get("polarity"),
            relation=entry.get("relation"),
            source="llm_semantic_extractor",
            confidence=float(entry.get("confidence", 0.0)),
        ))

    unsupported = tuple(
        str(d) for d in data.get("unsupported_domains", []) if isinstance(d, str)
    )
    confidence = float(data.get(
        "confidence",
        max((op.confidence for op in operations), default=0.0),
    ))
    return SemanticExtractionResult(
        operations=tuple(operations),
        unsupported_domains=unsupported,
        confidence=confidence,
        raw_json=raw,
        error="; ".join(sorted(set(dropped))) if dropped and not operations else None,
    )


# ---------------------------------------------------------------------------
# Complexity detector — deterministic parser stays first for simple cases
# ---------------------------------------------------------------------------

# Affection-explanation sentences stay with the P0-7F clarify lane, never split.
_EXPLANATION_GUARDS: tuple[str, ...] = (
    "có nghĩa là", "nghĩa là", "tức là", "đơn phương", "chúng tôi",
)

_RE_CX_CORRECTION_NAME = re.compile(r'\bmới\s+đúng\b', re.IGNORECASE)
_RE_CX_CORRECTION_REL = re.compile(
    r'đã\s+đổi\s+.+?\s+(?:thành|sang)\s+\S+', re.IGNORECASE,
)
_RE_CX_REMOVE_ALL_AFFECTION = re.compile(
    r'không\s+(?:còn\s+)?thích\s+ai(?:\s+nữa|\s+cả)?\s*[.!]*\s*$', re.IGNORECASE,
)
_RE_CX_INVERSE_AFFECTION = re.compile(
    r'^(\S+(?:\s+\S+)?)\s+là\s+người\s+(?:mà\s+)?(?:tôi|mình)\s+thích\s*[.!]*\s*$',
    re.IGNORECASE,
)
_RE_CX_RELATION_ADJACENT_AFFECTION = re.compile(
    r'^(?:tôi|mình)\s+thích\s+(\S+)\s+và\s+\1\s+cũng\s+thích\s+(?:tôi|mình)\s*[.!]*\s*$',
    re.IGNORECASE,
)
_RE_CX_GOAL_VERB = re.compile(
    r'(?:muốn|định|sẽ)\s+(?:làm|build)|(?:muốn|định|sẽ)\s+.*\bbuild\b',
    re.IGNORECASE,
)
# P0-7K-FIX4 E: contrast skill clause — "tôi biết A nhưng/mà/còn (tôi) không biết B".
_RE_CX_CONTRAST_SKILL = re.compile(
    r'^(?:tôi|mình)\s+biết\s+.+\s+(?:nhưng|mà|còn)\s+(?:tôi\s+|mình\s+)?không\s+biết\s+.+$',
    re.IGNORECASE,
)


def detect_memory_complexity(text: str) -> str | None:
    """Return a complexity reason if text needs semantic extraction, else None.

    Questions and affection-explanation sentences always stay deterministic.
    """
    stripped = re.sub(r"\s+", " ", text.strip())
    if not stripped or "?" in stripped or "？" in stripped:
        return None
    low = stripped.lower()
    if any(guard in low for guard in _EXPLANATION_GUARDS):
        return None

    if _RE_CX_CORRECTION_NAME.search(low):
        return "correction_name"
    if _RE_CX_CORRECTION_REL.search(low):
        return "correction_relationship"
    if _RE_CX_REMOVE_ALL_AFFECTION.search(low) and not re.search(r'\bAI\b', stripped) and (
        "nữa" in low or "không còn" in low
        or low.startswith(("bây giờ", "hiện tại", "giờ"))
    ):
        return "remove_all_affection"
    if _RE_CX_INVERSE_AFFECTION.match(stripped):
        return "inverse_affection"
    if _RE_CX_RELATION_ADJACENT_AFFECTION.match(stripped):
        return None

    # P0-7K-FIX4 E: contrast skill clause ("tôi biết A nhưng không biết B") — before the
    # multi-item skill lane since it carries a polarity switch, not a plain list.
    if _RE_CX_CONTRAST_SKILL.match(low):
        return "contrast_skill"
    has_list = ("," in low) or (" và " in low)
    # P0-7K-FIX2: multi-item skill ("tôi biết đọc sách và hát"), before the goal/
    # preference lanes since "biết" is skill-specific.
    if has_list and re.match(r'^(?:tôi|mình)\s+(?:không\s+)?biết\b', low):
        return "multi_skill"
    if "thích" in low:
        mixed = "không thích" in low and "thích" in low.replace("không thích", "")
        if mixed:
            return "mixed_polarity_preference"
        if has_list:
            return "multi_fact_preference"
    if has_list and _RE_CX_GOAL_VERB.search(low):
        return "compound_goal"
    return None


# ---------------------------------------------------------------------------
# Unsupported/future memory domains — classified, never written
# ---------------------------------------------------------------------------

# (domain_tag, detection regex, honest deterministic response)
_UNSUPPORTED_DOMAIN_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "schedule",
        re.compile(
            r'(?<!du )lịch\s+(?:hôm\s+nay|ngày\s+mai|tuần|của\s+tôi)'
            r'|(?:hôm\s+nay|ngày\s+mai|mai)\s+(?:tôi\s+)?có\s+lịch',
            re.IGNORECASE,
        ),
        "Hiện tại mình chưa hỗ trợ ghi nhớ hay tra cứu lịch/agenda, nên chưa thể "
        "trả lời câu này. Mình chưa lưu gì từ câu này.",
    ),
    (
        "historical_query",
        re.compile(r'đã\s+từng\s+(?:thích|yêu|làm|học|ở)', re.IGNORECASE),
        "Hiện tại mình chỉ nhớ trạng thái hiện tại, chưa hỗ trợ tra cứu lịch sử "
        "những gì bạn từng thích/làm trước đây. Mình chưa lưu gì từ câu này.",
    ),
    (
        "assistant_nickname",
        re.compile(r'đặt\s+tên\s+(?:cho\s+)?bạn', re.IGNORECASE),
        "Hiện tại mình chưa hỗ trợ đặt tên/biệt danh riêng cho trợ lý. "
        "Mình chưa lưu gì từ câu này.",
    ),
)


def detect_unsupported_memory_domain(text: str) -> tuple[str, str] | None:
    """Return (domain_tag, response) for a known unsupported/future memory domain.

    These are classified honestly and must never corrupt profile memory:
    schedule/agenda → P0-7L, historical memory query → P0-7M,
    assistant nickname/personalization → P0-7N.
    """
    stripped = re.sub(r"\s+", " ", text.strip())
    for domain, pattern, response in _UNSUPPORTED_DOMAIN_RULES:
        if pattern.search(stripped):
            return domain, response
    return None


# ---------------------------------------------------------------------------
# Rule-based extractor — deterministic, provider-free default backend
# ---------------------------------------------------------------------------

_RULE_BASED_SOURCE = "rule_based_semantic_extractor"
_RULE_BASED_CONFIDENCE = 0.9

# Clause heads inside a multi-fact preference sentence.
_RE_PREF_CLAUSE_HEAD = re.compile(
    r'(?:(?:nhưng|và|,)\s+)?(?:(?:tôi|mình)\s+)?(?:(?:cũng|còn|vẫn)\s+)?'
    r'(không\s+)?thích\s+',
    re.IGNORECASE,
)
_RE_REL_CORRECTION = re.compile(
    r'đã\s+đổi\s+(bạn\s+gái|bạn\s+trai|người\s+yêu|vợ|chồng|partner)\s+'
    r'(?:của\s+(?:tôi|mình)\s+)?(?:thành|sang)\s+(\S+?)(?:\s+rồi)?\s*[.!]*\s*$',
    re.IGNORECASE,
)
_RE_COMPOUND_GOAL = re.compile(
    r'(?:muốn|định|sẽ)\s+(làm|build)\s+(.+)$',
    re.IGNORECASE,
)
_RE_MOI_DUNG_TAIL = re.compile(r'\s+mới\s+đúng\s*[.!]*\s*$', re.IGNORECASE)
# P0-7K-FIX3: skill clause predicate ("tôi biết ", "tôi không biết ", "mình biết làm ").
_RE_SKILL_CLAUSE_PREFIX = re.compile(
    r'^(?:tôi|mình)\s+(không\s+)?biết\s+(?:làm\s+)?',
    re.IGNORECASE,
)


_FOOD_VERB_PREFIXES: tuple[str, ...] = ("ăn ", "uống ")


def _split_items(raw: str) -> list[str]:
    """Split a Vietnamese object list: "ăn cay, bơi, tắm biển và thể dục" → 4 items.

    P0-7K-FIX2: if the FIRST item carries a food verb ("ăn kem, me và dâu tây"), the
    verb distributes over subsequent bare items ("ăn kem", "ăn me", "ăn dâu tây") so a
    short food name like "me" survives the shape check and food queries find it.
    """
    parts: list[str] = []
    for chunk in raw.split(","):
        for item in re.split(r'\s+và\s+', chunk):
            item = re.sub(r"\s+", " ", item.strip().rstrip(".!,")).strip()
            item = strip_additive_target_marker(item) if item else item
            item = re.sub(
                r'\s+(?:tôi|mình)\s+cũng\s+vậy\s*$',
                "",
                item,
                flags=re.IGNORECASE,
            ).strip()
            if item:
                parts.append(item)
    if not parts:
        return parts
    first_low = parts[0].lower()
    for prefix in _FOOD_VERB_PREFIXES:
        if first_low.startswith(prefix):
            return [
                p if p.lower().startswith(_FOOD_VERB_PREFIXES) else f"{prefix}{p}"
                for p in parts
            ]
    return parts


def _valid_item(item: str) -> bool:
    if not item or len(item) < 2 or len(item) > 60:
        return False
    return not _is_unsafe_or_sensitive_auto_value(item)


class RuleBasedSemanticOperationExtractor:
    """Deterministic bounded extractor for complexity-detected utterances.

    Fills the extractor slot without any provider; a future LLM adapter can replace
    it behind the same protocol + JSON contract.
    """

    def extract(self, request: SemanticExtractionRequest) -> SemanticExtractionResult:
        text = re.sub(r"\s+", " ", request.raw_text.strip())
        reason = detect_memory_complexity(text)
        if reason is None:
            return _EMPTY_RESULT
        if reason == "correction_name":
            ops = self._extract_name_correction(text)
        elif reason == "correction_relationship":
            ops = self._extract_relationship_correction(text)
        elif reason == "remove_all_affection":
            ops = (MemoryOperation(
                op="REMOVE_ALL", domain="affection", subject="self", value="*",
                canonical_key="*", polarity="negative",
                source=_RULE_BASED_SOURCE, confidence=_RULE_BASED_CONFIDENCE,
                raw_text=text,
            ),)
        elif reason == "inverse_affection":
            ops = self._extract_inverse_affection(text)
        elif reason in ("mixed_polarity_preference", "multi_fact_preference"):
            ops = self._extract_preference_clauses(text)
        elif reason == "contrast_skill":
            ops = self._extract_contrast_skill(text)
        elif reason == "multi_skill":
            ops = self._extract_skill_items(text)
        elif reason == "compound_goal":
            ops = self._extract_compound_goal(text)
        else:
            ops = ()
        if not ops:
            return _EMPTY_RESULT
        if len(ops) > MAX_OPERATIONS_PER_UTTERANCE:
            ops = ops[:MAX_OPERATIONS_PER_UTTERANCE]
        return SemanticExtractionResult(
            operations=tuple(ops),
            confidence=_RULE_BASED_CONFIDENCE,
            source=_RULE_BASED_SOURCE,
        )

    def _extract_name_correction(self, text: str) -> tuple[MemoryOperation, ...]:
        remainder = _RE_MOI_DUNG_TAIL.sub("", text).strip()
        candidate = detect_profile_fact_candidate(remainder)
        if candidate is None or candidate.subject != "self" or candidate.relation != "name":
            return ()
        return (MemoryOperation(
            op="CORRECT", domain="name", subject="self", value=candidate.value,
            canonical_key=canonicalize_memory_value(candidate.value),
            source="user_correction", confidence=_RULE_BASED_CONFIDENCE, raw_text=text,
        ),)

    def _extract_relationship_correction(self, text: str) -> tuple[MemoryOperation, ...]:
        m = _RE_REL_CORRECTION.search(text)
        if not m:
            return ()
        label = _normalize_relation_label(m.group(1))
        name = re.sub(r"\s+", " ", m.group(2).strip().rstrip(".!,")).strip()
        if not name:
            return ()
        return (MemoryOperation(
            op="UPDATE_CURRENT", domain="relationship", subject="relation", value=name,
            canonical_key=canonicalize_memory_value(name), relation=label,
            source="user_correction", confidence=_RULE_BASED_CONFIDENCE, raw_text=text,
        ),)

    def _extract_inverse_affection(self, text: str) -> tuple[MemoryOperation, ...]:
        m = _RE_CX_INVERSE_AFFECTION.match(text)
        if not m:
            return ()
        target = strip_additive_target_marker(
            re.sub(r"\s+", " ", m.group(1).strip()).strip()
        )
        if not target or not _is_person_affinity_value(target):
            return ()
        return (MemoryOperation(
            op="ADD", domain="affection", subject="self", value=target,
            canonical_key=canonicalize_memory_value(target), polarity="positive",
            source=_RULE_BASED_SOURCE, confidence=_RULE_BASED_CONFIDENCE, raw_text=text,
        ),)

    def _extract_preference_clauses(self, text: str) -> tuple[MemoryOperation, ...]:
        matches = list(_RE_PREF_CLAUSE_HEAD.finditer(text))
        if not matches:
            return ()
        ops: list[MemoryOperation] = []
        for idx, m in enumerate(matches):
            seg_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            segment = text[m.end():seg_end].strip().rstrip(",")
            polarity = "negative" if m.group(1) else "positive"
            for item in _split_items(segment):
                if not _valid_item(item):
                    continue
                ops.append(MemoryOperation(
                    op="ADD", domain="preference", subject="self", value=item,
                    canonical_key=canonicalize_memory_value(item), polarity=polarity,
                    source=_RULE_BASED_SOURCE, confidence=_RULE_BASED_CONFIDENCE,
                    raw_text=text,
                ))
        # A single extracted item is not a multi-fact sentence — leave it to the
        # deterministic path (person-affection routing, acks, etc.).
        return tuple(ops) if len(ops) >= 2 else ()

    _RE_CONTRAST_SKILL = re.compile(
        r'^(?:tôi|mình)\s+biết\s+(.+?)\s+(?:nhưng|mà|còn)\s+'
        r'(?:tôi\s+|mình\s+)?không\s+biết\s+(.+)$',
        re.IGNORECASE,
    )

    def _extract_contrast_skill(self, text: str) -> tuple[MemoryOperation, ...]:
        # P0-7K-FIX4 E: "tôi biết A nhưng không biết B" → ADD skill A + negative skill B.
        m = self._RE_CONTRAST_SKILL.match(text)
        if not m:
            return ()
        ops: list[MemoryOperation] = []
        for raw, polarity in ((m.group(1), "positive"), (m.group(2), "negative")):
            item = strip_terminal_discourse_markers(
                strip_additive_target_marker(
                    re.sub(r"\s+", " ", raw.strip().rstrip(".!,")).strip()
                )
            )
            if _valid_item(item):
                ops.append(MemoryOperation(
                    op="ADD", domain="skill", subject="self", value=item,
                    canonical_key=canonicalize_memory_value(item), polarity=polarity,
                    source=_RULE_BASED_SOURCE, confidence=_RULE_BASED_CONFIDENCE,
                    raw_text=text,
                ))
        return tuple(ops) if len(ops) >= 2 else ()

    def _extract_skill_items(self, text: str) -> tuple[MemoryOperation, ...]:
        # P0-7K-FIX3: multi-clause skill list with repeated predicates
        # ("tôi biết nấu ăn, tôi biết đọc sách và hát",
        #  "tôi không biết đọc sách và tôi không biết hát"). Each item's predicate is
        # stripped so only the clean skill value is stored.
        if not _RE_SKILL_CLAUSE_PREFIX.match(text):
            return ()
        ops: list[MemoryOperation] = []
        last_polarity = "positive"
        # Split into clauses on comma AND on "và <predicate>" boundaries.
        raw_parts = re.split(
            r'\s*,\s*|\s+và\s+(?=(?:tôi|mình)\s+(?:không\s+)?biết\b)',
            text, flags=re.IGNORECASE,
        )
        for part in raw_parts:
            part = part.strip()
            if not part:
                continue
            pm = _RE_SKILL_CLAUSE_PREFIX.match(part)
            if pm:
                last_polarity = "negative" if pm.group(1) else "positive"
                rest = part[pm.end():].strip()
            else:
                rest = part
            for item in re.split(r'\s+và\s+', rest):
                item = strip_terminal_discourse_markers(
                    strip_additive_target_marker(
                        re.sub(r"\s+", " ", item.strip().rstrip(".!,")).strip()
                    )
                )
                if _valid_item(item):
                    ops.append(MemoryOperation(
                        op="ADD", domain="skill", subject="self", value=item,
                        canonical_key=canonicalize_memory_value(item),
                        polarity=last_polarity,
                        source=_RULE_BASED_SOURCE, confidence=_RULE_BASED_CONFIDENCE,
                        raw_text=text,
                    ))
        return tuple(ops) if len(ops) >= 2 else ()

    def _extract_compound_goal(self, text: str) -> tuple[MemoryOperation, ...]:
        m = _RE_COMPOUND_GOAL.search(text)
        if not m:
            return ()
        verb = m.group(1).lower()
        tail = re.sub(r'^cả\s+', '', m.group(2).strip(), flags=re.IGNORECASE)
        items = _split_items(tail)
        if len(items) < 2:
            return ()
        ops = []
        for item in items:
            if not _valid_item(item):
                continue
            value = f"{verb} {item}"
            ops.append(MemoryOperation(
                op="ADD", domain="goal", subject="self", value=value,
                canonical_key=_goal_conflict_key(value), polarity="positive",
                source=_RULE_BASED_SOURCE, confidence=_RULE_BASED_CONFIDENCE,
                raw_text=text,
            ))
        return tuple(ops)


# ---------------------------------------------------------------------------
# Fake extractor — deterministic fixtures for tests/probes only
# ---------------------------------------------------------------------------

class FakeSemanticOperationExtractor:
    """Canned-fixture extractor: maps exact raw_text to a raw JSON proposal.

    Used only in tests/probes. Fixture JSON goes through the same strict contract
    validation a real LLM adapter would, so tests exercise the full pipeline.
    """

    def __init__(self, fixtures: dict[str, str] | None = None) -> None:
        self._fixtures = dict(fixtures or {})

    def extract(self, request: SemanticExtractionRequest) -> SemanticExtractionResult:
        raw_json = self._fixtures.get(request.raw_text.strip())
        if raw_json is None:
            return _EMPTY_RESULT
        return parse_semantic_operations_json(raw_json)

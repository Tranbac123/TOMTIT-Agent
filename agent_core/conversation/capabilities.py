"""CONV-P0 P0-8A — deterministic capability router.

Classifies a user turn into a capability class for the bounded response layer. This is
NOT an LLM intent parser and NOT a planner: pure anchored regexes over the raw text, no
network, no memory access. The deterministic memory lanes in SessionRuntime always run
FIRST — this router only sees turns those lanes declined, and it must never steal them.

Routing contract (SessionRuntime ordering):
  1. existing deterministic memory/runtime handlers;
  2. external tool-action requests → safety gate (no execution in MVP);
  3. this router for response-only capabilities (translation/explanation/checklist/
     prioritization/rewrite/summary) → bounded LLMResponder;
  4. existing current-limitation / clarification fallbacks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Capability(StrEnum):
    MEMORY_QUERY = "memory_query"
    MEMORY_WRITE = "memory_write"
    MEMORY_DELETE = "memory_delete"
    TRANSLATION = "translation"
    EXPLANATION = "explanation"
    CHECKLIST = "checklist"
    PRIORITIZATION = "prioritization"
    REWRITE = "rewrite"
    SUMMARY = "summary"
    TOOL_ACTION_REQUEST = "tool_action_request"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CapabilityMatch:
    """One classified turn: the capability, an optional extracted payload (the text after
    a ``:`` separator), and — for tool-action requests — the requested tool name."""

    capability: Capability
    payload: str | None = None
    tool_name: str | None = None


# --- response-only capabilities -------------------------------------------------
# Payload is the text after ":". Payload-less forms are also classified (the caller
# decides whether to answer or defer to the existing clarification lanes).
_RE_TRANSLATION = re.compile(
    r'^(?:d[ịi]ch\s+đoạn\s+này\s+sang\s+tiếng\s+anh|translate\s+this\s+to\s+english)'
    r'\s*(?::\s*(?P<payload>.+?))?\s*[.!?]*\s*$',
    re.IGNORECASE,
)
_RE_CHECKLIST = re.compile(
    r'^chia\s+(?:việc\s+này\s+)?thành\s+checklist\s*(?::\s*(?P<payload>.+?))?\s*[.!?]*\s*$',
    re.IGNORECASE,
)
_RE_PRIORITIZATION = re.compile(
    r'^(?:'
    r'ưu\s+tiên\s+các\s+task\s+này(?:\s+giúp\s+(?:tôi|mình))?'
    r'|(?:tôi|mình)\s+nên\s+làm\s+task\s+nào\s+trước'
    r')\s*(?::\s*(?P<payload>.+?))?\s*[.!?？]*\s*$',
    re.IGNORECASE,
)
_RE_REWRITE = re.compile(
    r'^viết\s+lại\s+đoạn\s+này\s*:\s*(?P<payload>.+?)\s*[.!?]*\s*$',
    re.IGNORECASE,
)
_RE_SUMMARY = re.compile(
    r'^tóm\s+tắt\s+đoạn\s+này\s*:\s*(?P<payload>.+?)\s*[.!?]*\s*$',
    re.IGNORECASE,
)

# Technical explain/compare naming the internal runtime components. Same shape as the P4
# limitation detector in session_runtime (kept local here to avoid an import cycle —
# session_runtime imports this module): all four components with an explain/compare verb,
# or a comparison of at least two. "giải thích AI là gì?" and single-component questions
# stay on their existing lanes.
_EXPLANATION_COMPONENTS = ("planner", "runtime", "tool", "memory")
_EXPLANATION_COMPARE_CUES = ("phân biệt", "so sánh", "khác gì", "khác nhau")


def is_technical_components_request(text: str) -> bool:
    low = text.lower()
    present = sum(1 for c in _EXPLANATION_COMPONENTS if c in low)
    if any(v in low for v in ("giải thích", "phân biệt", "so sánh")) and present == 4:
        return True
    if any(cue in low for cue in _EXPLANATION_COMPARE_CUES) and present >= 2:
        return True
    return False


def technical_components_in(text: str) -> list[str]:
    """The internal components actually named in the request (display order fixed)."""
    low = text.lower()
    return [c for c in _EXPLANATION_COMPONENTS if c in low]


# --- external tool-action requests -----------------------------------------------
# Imperative external actions only. Queries about existing schedule/history stay with the
# unsupported-memory-domain lane; memory deletion stays with the pending-confirmation flow.
_ACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r'^gửi\s+(?:email|e-mail|mail)\b', re.IGNORECASE), "send_email"),
    (re.compile(r'^gửi\s+tin\s+nhắn\b', re.IGNORECASE), "send_message"),
    (re.compile(r'^đặt\s+(?:lịch|hẹn)\b', re.IGNORECASE), "create_calendar_event"),
    (re.compile(r'^x[oó][áa]\s+(?:file|tập\s+tin)\b', re.IGNORECASE), "delete_file"),
)


class CapabilityRouter:
    """Deterministic, anchored classification. Returns UNKNOWN rather than guessing —
    memory capabilities are owned by the deterministic lanes upstream and are never
    classified here."""

    def classify(self, text: str) -> CapabilityMatch:
        stripped = text.strip()
        for pattern, tool_name in _ACTION_PATTERNS:
            if pattern.match(stripped):
                return CapabilityMatch(
                    Capability.TOOL_ACTION_REQUEST, payload=None, tool_name=tool_name
                )
        m = _RE_TRANSLATION.match(stripped)
        if m:
            return CapabilityMatch(Capability.TRANSLATION, payload=m.group("payload"))
        if is_technical_components_request(stripped):
            return CapabilityMatch(Capability.EXPLANATION, payload=stripped)
        m = _RE_CHECKLIST.match(stripped)
        if m:
            return CapabilityMatch(Capability.CHECKLIST, payload=m.group("payload"))
        m = _RE_PRIORITIZATION.match(stripped)
        if m:
            return CapabilityMatch(Capability.PRIORITIZATION, payload=m.group("payload"))
        m = _RE_REWRITE.match(stripped)
        if m:
            return CapabilityMatch(Capability.REWRITE, payload=m.group("payload"))
        m = _RE_SUMMARY.match(stripped)
        if m:
            return CapabilityMatch(Capability.SUMMARY, payload=m.group("payload"))
        return CapabilityMatch(Capability.UNKNOWN)

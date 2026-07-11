"""Safe text-only LLM responder boundary for CONV-P0 P0-5B / P0-8A.

This module defines narrow protocols and bounded default implementations only. It does
not configure providers, read environment variables, perform network I/O, or expose
tools/memory/runtime state to the responder request.

P0-8A adds the bounded capability responder: response-only text transforms (translation/
explanation/checklist/prioritization/rewrite/summary) behind one interface. The default
``RuleBasedLLMResponder`` is deterministic and provider-free; a real provider would slot in
behind the same ``respond()`` boundary and STILL could not write/delete memory, call tools,
or override deterministic memory answers — SessionRuntime never routes those lanes here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_core.conversation.capabilities import (
    Capability,
    technical_components_in,
)


@dataclass(frozen=True)
class LLMResponderRequest:
    user_text: str
    intent: str
    route: str
    session_id: str | None = None
    task_id: str | None = None


@dataclass(frozen=True)
class LLMResponderResult:
    text: str
    provider_name: str | None = None
    model_name: str | None = None


class TextLLMResponder(Protocol):
    def generate(self, request: LLMResponderRequest) -> LLMResponderResult:
        """Generate a text answer from the safe request boundary."""


# ---------------------------------------------------------------------------
# P0-8A — bounded capability responder
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LLMResponseRequest:
    """One response-only capability request. ``context`` may carry the extracted payload
    (``context["payload"]``); nothing else — no memory, no tools, no state."""

    capability: Capability
    user_text: str
    context: dict[str, Any] | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str
    used_provider: str
    safety_notes: list[str] = field(default_factory=list)


class BoundedLLMResponder(Protocol):
    def respond(self, request: LLMResponseRequest) -> LLMResponse:
        """Produce a bounded, response-only answer for one capability request."""


def _split_items(payload: str) -> list[str]:
    """Split a task/content list on commas (the payload contract is comma-separated)."""
    return [item.strip() for item in re.split(r'\s*,\s*|\s*;\s*', payload) if item.strip()]


# Bounded, generic component explanations — public agent-architecture concepts only, no
# project-specific internals beyond what the user's own request names.
_COMPONENT_EXPLANATIONS: dict[str, str] = {
    "planner": "Planner: nhận intent đã parse và sinh danh sách bước (steps) — không thực thi gì.",
    "runtime": "Runtime: vòng lặp thực thi các bước theo thứ tự, cập nhật trạng thái của task.",
    "tool": "Tool: một hành động cụ thể (tính toán, ghi chú, tìm kiếm) chạy qua cổng thực thi có kiểm soát.",
    "memory": "Memory: nơi lưu và truy hồi thông tin đã xác nhận, tách khỏi trạng thái tạm của một lượt chạy.",
}

_PROVIDER_NAME = "rule_based_bounded"


class RuleBasedLLMResponder:
    """Deterministic bounded responder (default runtime backend, provider-free).

    Every branch is a fixed transform of the request payload. Missing payload → ask for
    the input. No branch fabricates facts, reads memory, or performs actions.
    """

    def respond(self, request: LLMResponseRequest) -> LLMResponse:
        payload = (request.context or {}).get("payload")
        payload = payload.strip() if isinstance(payload, str) else None
        capability = request.capability
        notes = ["response_only", "no_memory_access", "no_tool_access"]

        if capability is Capability.TRANSLATION:
            if not payload:
                return LLMResponse(
                    'Bạn hãy gửi đoạn văn bản cần dịch sang tiếng Anh (ví dụ: "Dịch đoạn '
                    'này sang tiếng Anh: <nội dung>"). Trong MVP này mình chỉ xử lý dịch ở '
                    "mức giới hạn.",
                    _PROVIDER_NAME, notes,
                )
            return LLMResponse(
                "Yêu cầu dịch sang tiếng Anh (English) đã được ghi nhận. Bản dịch đầy đủ "
                "cần LLM provider — chưa cấu hình trong MVP này, nên đây là phản hồi giới "
                f'hạn cho đoạn bạn gửi: "{payload}".',
                _PROVIDER_NAME, notes,
            )

        if capability is Capability.EXPLANATION:
            components = technical_components_in(request.user_text)
            lines = [_COMPONENT_EXPLANATIONS[c] for c in components]
            return LLMResponse(
                "Giải thích ngắn gọn (bounded, MVP rule-based):\n- "
                + "\n- ".join(lines)
                + "\nĐây là mô tả khái niệm chung; phân tích sâu theo project cần thêm "
                "ngữ cảnh bạn cung cấp.",
                _PROVIDER_NAME, notes,
            )

        if capability is Capability.CHECKLIST:
            if not payload:
                return LLMResponse(
                    "Bạn hãy gửi nội dung việc cần làm (ví dụ: \"Chia việc này thành "
                    'checklist: việc A, việc B") để mình chia thành checklist.',
                    _PROVIDER_NAME, notes,
                )
            items = _split_items(payload)
            return LLMResponse(
                "Checklist (MVP rule-based):\n" + "\n".join(f"- [ ] {i}" for i in items),
                _PROVIDER_NAME, notes,
            )

        if capability is Capability.PRIORITIZATION:
            if not payload:
                return LLMResponse(
                    "Bạn hãy gửi danh sách task (ví dụ: \"Ưu tiên các task này giúp tôi: "
                    'task A, task B") để mình sắp xếp thứ tự ưu tiên.',
                    _PROVIDER_NAME, notes,
                )
            items = _split_items(payload)
            ordered = "\n".join(f"{n}. {i}" for n, i in enumerate(items, start=1))
            return LLMResponse(
                "Thứ tự ưu tiên đề xuất (MVP rule-based, theo thứ tự bạn liệt kê — chưa "
                "có phân tích ngữ nghĩa sâu):\n" + ordered,
                _PROVIDER_NAME, notes,
            )

        if capability is Capability.REWRITE:
            if not payload:
                return LLMResponse(
                    "Bạn hãy gửi đoạn văn bản cần viết lại (ví dụ: \"Viết lại đoạn này: "
                    '<nội dung>").',
                    _PROVIDER_NAME, notes,
                )
            return LLMResponse(
                "Bản viết lại đầy đủ cần LLM provider — chưa cấu hình trong MVP này. "
                f'Mình đã nhận đoạn cần viết lại: "{payload}".',
                _PROVIDER_NAME, notes,
            )

        if capability is Capability.SUMMARY:
            if not payload:
                return LLMResponse(
                    "Bạn hãy gửi đoạn văn bản cần tóm tắt (ví dụ: \"Tóm tắt đoạn này: "
                    '<nội dung>").',
                    _PROVIDER_NAME, notes,
                )
            items = _split_items(payload)
            head = items[:3] if items else [payload]
            return LLMResponse(
                "Tóm tắt (MVP rule-based, tối đa 3 ý đầu):\n"
                + "\n".join(f"- {i}" for i in head),
                _PROVIDER_NAME, notes,
            )

        return LLMResponse(
            "Mình chưa hỗ trợ loại yêu cầu này trong bản bounded responder hiện tại.",
            _PROVIDER_NAME, notes,
        )


class FakeLLMResponder:
    """Test double: records every request and returns a canned, tagged response."""

    def __init__(self, canned_text: str = "FAKE_RESPONSE") -> None:
        self.canned_text = canned_text
        self.requests: list[LLMResponseRequest] = []

    def respond(self, request: LLMResponseRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            f"{self.canned_text}[{request.capability.value}]",
            "fake", ["response_only"],
        )

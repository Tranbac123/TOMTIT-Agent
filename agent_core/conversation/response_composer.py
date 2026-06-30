"""CONV-P0 P0-3 deterministic response text for direct/clarification routes.

No LLM, no memory, no tools. Text is safe and non-overclaiming per the P0-3 content
rules: never says it saved/remembered anything, never claims autonomy or full capability.
"""
from __future__ import annotations

from agent_core.planning.intents import IntentName

_GREETING = (
    "Chào bạn! Tôi là TomTit Agent. "
    "Bạn có thể thử: \"Tính 1 + 1\", \"calculate 2 + 2\", "
    "\"Tìm Python tutorials\", \"Lưu ghi chú [tên] [nội dung]\", "
    "hoặc \"Đọc ghi chú [tên]\"."
)

_IDENTITY = (
    "Tôi là TomTit Agent — một AI agent local-first, state-first (runtime/trợ lý). "
    "Tôi giúp định tuyến hội thoại và một số tác vụ, nhưng năng lực vẫn đang được xây "
    "dựng theo từng giai đoạn. Tôi không tự động làm mọi thứ và chỉ làm trong phạm vi "
    "đã được hiện thực."
)

_CAPABILITY = (
    "Hiện tại tôi có thể: trò chuyện cơ bản (chào hỏi, giới thiệu, hỏi năng lực), "
    "tính toán, và một số tác vụ runtime/ghi chú đã được hiện thực. Tôi hoạt động theo "
    "hướng state-first với trace/safety. Giới hạn: nhiều tính năng (lập kế hoạch, viết, "
    "review code, memory hội thoại) vẫn đang phát triển và chưa hoàn chỉnh."
)

_CLARIFICATION = (
    "Tôi chưa đủ ngữ cảnh để xử lý chính xác yêu cầu này. Bạn muốn tôi giải thích, "
    "lập kế hoạch, tính toán, viết lại, review code, hay tiếp tục một task cụ thể? "
    "Bạn có thể nói rõ hơn giúp tôi."
)

_DIRECT_TEXT: dict[IntentName, str] = {
    IntentName.GREETING: _GREETING,
    IntentName.IDENTITY_QUERY: _IDENTITY,
    IntentName.CAPABILITY_QUERY: _CAPABILITY,
}


class ResponseComposer:
    def compose_direct(self, intent: IntentName) -> str:
        try:
            return _DIRECT_TEXT[intent]
        except KeyError as exc:  # pragma: no cover - router guarantees a direct intent
            raise ValueError(f"no direct response for intent {intent!r}") from exc

    def compose_clarification(self, intent: IntentName) -> str:
        return _CLARIFICATION

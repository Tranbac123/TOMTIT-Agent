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

# P0-4A: honest unsupported-utility response for date/time/weather. Never fakes a
# date/time/weather answer, never claims a tool/memory was called or that it executed.
_UNSUPPORTED_UTILITY = (
    "Hiện tại trong runtime này tôi chưa hỗ trợ trả lời thời gian/ngày/thời tiết trực tiếp, "
    "nên chưa thể trả lời chính xác yêu cầu này. Tôi chưa gọi tool hay tra cứu dữ liệu nào cho việc này. "
    "Bạn có thể thử các năng lực hiện có: \"Tính 1 + 1\", \"calculate 2 + 2\", "
    "\"Lưu ghi chú [tên] [nội dung]\", hoặc \"Đọc ghi chú [tên]\"."
)

# P0-4B: honest response for user-memory / user-self-identity queries. Never fakes memory,
# never claims a memory/tool call was made, never pretends to know the user's name/identity.
_USER_MEMORY_UNSUPPORTED = (
    "Hiện tại trong runtime này tôi chưa hỗ trợ memory hội thoại/user profile trực tiếp, "
    "nên tôi chưa biết hoặc chưa nhớ bạn là ai hay tên bạn là gì. "
    "Tôi cũng chưa gọi memory/tool nào cho việc này. "
    "Bạn có thể dùng chức năng ghi chú nếu muốn lưu thông tin cụ thể."
)

# P0-4B: response for ambiguous user-self capability question ("tôi có thể làm gì?").
# Clarifies that the user needs to specify what they want, not claiming TomTit's capability.
_USER_SELF_ACTION = (
    "Bạn đang hỏi bạn có thể làm gì với TomTit, hay muốn tôi gợi ý việc bạn nên làm tiếp? "
    "Hiện tại tôi chưa đủ ngữ cảnh để trả lời chính xác. "
    "Bạn có thể thử: \"bạn làm được gì?\", \"calculate 2 + 2\", \"Lưu ghi chú [tên] [nội dung]\"."
)

# P0-4B: honest response for open-ended explanation requests (AI, ML, etc.) that the
# rule-based runtime cannot fulfil. Never claims LLMResponder exists or fakes an answer.
_EXPLANATION_UNSUPPORTED = (
    "Hiện tại trong runtime này tôi chưa hỗ trợ chế độ giải thích nội dung mở như một chatbot đầy đủ, "
    "nên chưa thể trả lời tốt yêu cầu này. "
    "Tôi có thể xử lý các năng lực đã được hiện thực như chào hỏi, giới thiệu năng lực, "
    "tính toán cơ bản và một số tác vụ ghi chú/runtime."
)

# P0-7K xfail-burndown P2: bounded task-shaped clarifications. Each asks for the missing
# concrete input instead of inventing an artifact/analysis, and names the requested
# dimension so the reply is obviously on-topic (not the generic catch-all clarification).

_PLANNING_TASK_CLARIFICATION = (
    "Mình cần thêm mục tiêu hoặc danh sách task cụ thể (bạn có thể gửi danh sách hoặc gửi "
    "nội dung việc cần làm) để chia thành checklist hay sắp xếp ưu tiên chính xác. Bạn muốn "
    "ưu tiên việc nào trước, hay có task nào cụ thể chưa?"
)

_PRODUCT_ANALYSIS_CLARIFICATION = (
    "Mình cần thêm mô tả về ý tưởng/sản phẩm (vấn đề đang giải quyết, user mục tiêu, bối "
    "cảnh, MVP hiện tại) để đánh giá rủi ro, validate, hay xác định user đầu tiên nên phỏng "
    "vấn chính xác hơn."
)

_WRITING_TASK_CLARIFICATION = (
    "Bạn gửi đoạn văn bản/nội dung cụ thể giúp mình (kèm mục đích, người nhận nếu là email, "
    "hoặc tên project nếu là README) để mình viết lại tự nhiên hơn, tóm tắt thành 3 ý, soạn "
    "email, hay viết README chính xác."
)

_CODE_TASK_CLARIFICATION = (
    "Bạn gửi đoạn code, function, hoặc mô tả lỗi/bug cụ thể giúp mình để mình review, tìm "
    "bug, hoặc viết test chính xác hơn."
)

_CONTINUE_CLARIFICATION = (
    "Bạn muốn mình tiếp tục việc nào? Hiện tại mình chưa có ngữ cảnh trước đó để biết chính "
    "xác bạn muốn tiếp tục phần nào, bạn có thể nói rõ hơn giúp mình."
)

# P0-7K xfail-burndown P3: bounded memory-edge responses. Deterministic, never delete
# arbitrary memory, never fabricate a provenance/assumption audit that does not exist.

# memory_004: a vague "quên thông tin đó" with no resolvable target → ask which memory,
# never delete blindly.
_VAGUE_FORGET_CLARIFICATION = (
    "Bạn muốn mình quên thông tin nào cụ thể? Mình cần bạn chỉ rõ (ví dụ: một sở thích, "
    "một mục tiêu, hay một ghi chú) để không xoá nhầm — mình sẽ không tự ý quên thông tin "
    "khi chưa rõ."
)

# memory_005: honest per-turn memory suppression. No global disable, no delete, not stored
# as a preference.
_DISABLE_MEMORY_FOR_TURN = (
    "Được, trong câu trả lời này mình sẽ không dùng memory/các thông tin đã nhớ về bạn. "
    "Mình không xoá gì cả, chỉ tạm không dựa vào chúng cho câu trả lời này. Bạn muốn hỏi gì "
    "tiếp?"
)

# memory_006: honest current-MVP limitation on assumption/provenance auditing.
_ASSUMPTION_QUERY_LIMITATION = (
    "Hiện tại MVP chủ yếu lưu các thông tin bạn tự cung cấp (confirmed/đã xác nhận), và "
    "chưa có cơ chế đánh dấu đầy đủ thông tin nào là assumption/giả định suy ra. Vì vậy mình "
    "chưa thể liệt kê chính xác phần nào là giả định — mình chỉ chắc về những gì bạn đã nói rõ."
)

_LLM_RESPONSE_UNCONFIGURED = (
    "Hiện tại trong runtime này LLMResponder chưa được cấu hình, nên tôi chưa thể trả lời yêu cầu mở này. "
    "Tôi chưa gọi tool, memory hay thực hiện hành động nào."
)

_LLM_RESPONSE_FAILED = (
    "Tôi chưa thể tạo câu trả lời LLM cho yêu cầu này lúc này. "
    "Tôi chưa gọi tool, memory hay thực hiện hành động nào."
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

    def compose_unsupported_utility(self) -> str:
        return _UNSUPPORTED_UTILITY

    def compose_user_memory_unsupported(self) -> str:
        return _USER_MEMORY_UNSUPPORTED

    def compose_user_self_action(self) -> str:
        return _USER_SELF_ACTION

    def compose_explanation_unsupported(self) -> str:
        return _EXPLANATION_UNSUPPORTED

    def compose_planning_task_clarification(self) -> str:
        return _PLANNING_TASK_CLARIFICATION

    def compose_product_analysis_clarification(self) -> str:
        return _PRODUCT_ANALYSIS_CLARIFICATION

    def compose_writing_task_clarification(self) -> str:
        return _WRITING_TASK_CLARIFICATION

    def compose_code_task_clarification(self) -> str:
        return _CODE_TASK_CLARIFICATION

    def compose_continue_clarification(self) -> str:
        return _CONTINUE_CLARIFICATION

    def compose_vague_forget_clarification(self) -> str:
        return _VAGUE_FORGET_CLARIFICATION

    def compose_disable_memory_for_turn(self) -> str:
        return _DISABLE_MEMORY_FOR_TURN

    def compose_assumption_query_limitation(self) -> str:
        return _ASSUMPTION_QUERY_LIMITATION

    def compose_llm_unconfigured(self) -> str:
        return _LLM_RESPONSE_UNCONFIGURED

    def compose_llm_failed(self) -> str:
        return _LLM_RESPONSE_FAILED

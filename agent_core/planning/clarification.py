from __future__ import annotations

from agent_core.planning.intents import ParsedIntent


class ClarificationComposer:
    def compose(self, parsed: ParsedIntent) -> str:
        missing_slots = set(parsed.missing_slots)

        if "intent" in missing_slots:
            return "Bạn muốn tôi làm việc gì?"

        if "expression" in missing_slots:
            return "Bạn muốn tôi tính biểu thức nào?"

        if "note_name" in missing_slots:
            return "Bạn muốn dùng tên ghi chú là gì?"

        if "content" in missing_slots:
            return "Bạn muốn lưu nội dung gì?"

        if "query" in missing_slots:
            return "Bạn muốn tôi tìm thông tin gì?"

        return "Bạn hãy mô tả rõ hơn việc bạn muốn tôi làm."

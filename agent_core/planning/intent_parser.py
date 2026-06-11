from __future__ import annotations

from agent_core.planning.clarification import ClarificationComposer
from agent_core.planning.intents import IntentName, ParsedIntent
from agent_core.state.agent_state import Step
from agent_core.state.enums import ToolName


class IntentPlanner:
    def __init__(
        self,
        clarification_composer: ClarificationComposer | None = None,
    ):
        self.clarification_composer = clarification_composer or ClarificationComposer()

    def make_plan(self, parsed: ParsedIntent) -> list[Step]:
        if parsed.missing_slots:
            return self._clarification_plan(parsed)

        if parsed.intent == IntentName.CALCULATE:
            return self._calculate_plan(parsed)

        if parsed.intent == IntentName.CALCULATE_THEN_SAVE_NOTE:
            return self._calculate_then_save_note_plan(parsed)

        if parsed.intent == IntentName.READ_NOTE:
            return self._read_note_plan(parsed)

        if parsed.intent == IntentName.READ_NOTE_THEN_SUMMARIZE:
            return self._read_note_then_summarize_plan(parsed)

        if parsed.intent == IntentName.WRITE_NOTE:
            return self._write_note_plan(parsed)

        if parsed.intent == IntentName.WEB_SEARCH:
            return self._web_search_plan(parsed)

        if parsed.intent == IntentName.WEB_SEARCH_THEN_SAVE_NOTE:
            return self._web_search_then_save_note_plan(parsed)

        return self._unknown_plan()

    def _clarification_plan(self, parsed: ParsedIntent) -> list[Step]:
        return [
            Step(
                thought="Intent rõ nhưng thiếu slot; hỏi lại user",
                action=ToolName.FINISH,
                args={"answer": self.clarification_composer.compose(parsed)},
            )
        ]

    def _calculate_plan(self, parsed: ParsedIntent) -> list[Step]:
        return [
            Step(
                thought="Cần tính toán biểu thức",
                action=ToolName.CALCULATE,
                args={"expression": parsed.expression},
            ),
            Step(
                thought="Trả kết quả tính toán cho user",
                action=ToolName.FINISH,
                args={"answer": "Kết quả: ${last.output.value}"},
            ),
        ]

    def _calculate_then_save_note_plan(self, parsed: ParsedIntent) -> list[Step]:
        return [
            Step(
                thought="Cần tính toán biểu thức trước",
                action=ToolName.CALCULATE,
                args={"expression": parsed.expression},
            ),
            Step(
                thought="Lưu kết quả vào ghi chú",
                action=ToolName.WRITE_NOTE,
                args={"name": parsed.note_name, "content": "$last_text"},
            ),
            Step(
                thought="Thông báo hoàn tất cho user",
                action=ToolName.FINISH,
                args={
                    "answer": (
                        f"Đã tính xong và lưu vào ghi chú "
                        f"'{parsed.note_name}'. Kết quả: ${{slot.calc_result}}"
                    )
                },
            ),
        ]

    def _read_note_plan(self, parsed: ParsedIntent) -> list[Step]:
        return [
            Step(
                thought="Đọc nội dung ghi chú",
                action=ToolName.READ_NOTE,
                args={"name": parsed.note_name},
            ),
            Step(
                thought="Trả nội dung ghi chú cho user",
                action=ToolName.FINISH,
                args={"answer": "$last_text"},
            ),
        ]

    def _read_note_then_summarize_plan(self, parsed: ParsedIntent) -> list[Step]:
        return [
            Step(
                thought="Đọc nội dung ghi chú",
                action=ToolName.READ_NOTE,
                args={"name": parsed.note_name},
            ),
            Step(
                thought="Tóm tắt nội dung ghi chú",
                action=ToolName.SUMMARIZE,
                args={"text": "$last.output.content"},
            ),
            Step(
                thought="Trả summary cho user",
                action=ToolName.FINISH,
                args={"answer": "Tóm tắt: ${last.output.summary}"},
            ),
        ]

    def _write_note_plan(self, parsed: ParsedIntent) -> list[Step]:
        return [
            Step(
                thought="Lưu nội dung vào ghi chú",
                action=ToolName.WRITE_NOTE,
                args={"name": parsed.note_name, "content": parsed.content},
            ),
            Step(
                thought="Thông báo đã lưu ghi chú",
                action=ToolName.FINISH,
                args={"answer": f"Đã lưu vào ghi chú '{parsed.note_name}'."},
            ),
        ]

    def _web_search_plan(self, parsed: ParsedIntent) -> list[Step]:
        return [
            Step(
                thought="Tìm thông tin trên web",
                action=ToolName.WEB_SEARCH,
                args={"query": parsed.query, "max_results": 3},
            ),
            Step(
                thought="Trả kết quả search cho user",
                action=ToolName.FINISH,
                args={"answer": "$last_text"},
            ),
        ]

    def _web_search_then_save_note_plan(self, parsed: ParsedIntent) -> list[Step]:
        return [
            Step(
                thought="Tìm thông tin trên web",
                action=ToolName.WEB_SEARCH,
                args={"query": parsed.query, "max_results": 3},
            ),
            Step(
                thought="Lưu kết quả tìm kiếm vào ghi chú",
                action=ToolName.WRITE_NOTE,
                args={"name": parsed.note_name, "content": "$last_text"},
            ),
            Step(
                thought="Thông báo đã tìm và lưu kết quả",
                action=ToolName.FINISH,
                args={
                    "answer": (
                        f"Đã tìm thông tin và lưu kết quả vào ghi chú "
                        f"'{parsed.note_name}'."
                    )
                },
            ),
        ]

    def _unknown_plan(self) -> list[Step]:
        return [
            Step(
                thought="Không hiểu rõ task nên kết thúc an toàn",
                action=ToolName.FINISH,
                args={
                    "answer": (
                        "Tôi chưa biết xử lý task này trong bản agent đơn giản này."
                    )
                },
            )
        ]

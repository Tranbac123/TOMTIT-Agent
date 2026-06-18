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

        if parsed.intent == IntentName.READ_NOTE:
            return self._read_note_plan(parsed)

        if parsed.intent == IntentName.WRITE_NOTE:
            return self._write_note_plan(parsed)

        if parsed.intent == IntentName.PROJECT_CONTEXT_QUERY:
            return self._project_context_query_plan(parsed)

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

    def _project_context_query_plan(self, parsed: ParsedIntent) -> list[Step]:
        return [
            Step(
                thought="Đọc project context từ ContextPack để trả lời",
                action=ToolName.ANSWER_FROM_CONTEXT,
                args={"query": parsed.query},
            ),
            Step(
                thought="Trả câu trả lời dựa trên project context",
                action=ToolName.FINISH,
                args={"answer": "$last.output.answer"},  # nested path — NOT $last_text (avoids leaking used_item_count)
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

from __future__ import annotations

from dataclasses import dataclass

from agent_core.state.agent_state import Step
from agent_core.state.enums import ToolName


@dataclass
class ReadAndSummarizeSkill:
    note_name: str

    def make_steps(self) -> list[Step]:
        return [
            Step("Đọc nội dung ghi chú", ToolName.READ_NOTE, {"name": self.note_name}),
            Step("Tóm tắt nội dung ghi chú", ToolName.SUMMARIZE, {"text": "$last.output.content"}),
            Step("Trả summary cho user", ToolName.FINISH, {"answer": "Tóm tắt: ${last.output.summary}"}),
        ]

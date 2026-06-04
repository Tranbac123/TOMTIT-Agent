from __future__ import annotations

from dataclasses import dataclass

from agent_core.state.agent_state import Step
from agent_core.state.enums import ToolName


@dataclass
class CalculateAndSaveSkill:
    expression: str
    note_name: str

    def make_steps(self) -> list[Step]:
        return [
            Step("Cần tính toán biểu thức trước", ToolName.CALCULATE, {"expression": self.expression}),
            Step("Lưu kết quả vào ghi chú", ToolName.WRITE_NOTE, {"name": self.note_name, "content": "$last_text"}),
            Step("Thông báo hoàn tất cho user", ToolName.FINISH, {"answer": f"Đã tính xong và lưu vào ghi chú '{self.note_name}'. Kết quả: ${{slot.calc_result}}"}),
        ]

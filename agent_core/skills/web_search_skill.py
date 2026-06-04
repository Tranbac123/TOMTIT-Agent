from __future__ import annotations

from dataclasses import dataclass

from agent_core.state.agent_state import Step
from agent_core.state.enums import ToolName


@dataclass
class WebSearchSkill:
    query: str
    max_results: int = 3

    def make_steps(self) -> list[Step]:
        return [
            Step("Tìm thông tin trên web", ToolName.WEB_SEARCH, {"query": self.query, "max_results": self.max_results}),
            Step("Trả kết quả search cho user", ToolName.FINISH, {"answer": "$last_text"}),
        ]

from __future__ import annotations

from typing import Protocol

from agent_core.state.agent_state import AgentState
from agent_core.tools.arg_resolver import stringify_output


class FinalComposer(Protocol):
    def compose(self, state: AgentState) -> str: ...


class DefaultFinalComposer:
    def compose(self, state: AgentState) -> str:
        if state.final_answer:
            return state.final_answer
        return stringify_output(state.last_result)

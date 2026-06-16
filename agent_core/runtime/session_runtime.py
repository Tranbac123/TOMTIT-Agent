from __future__ import annotations

from uuid import uuid4

from agent_core.memory.base import MemoryStoreProtocol
from agent_core.runtime.runtime_agent import RuntimeAgent
from agent_core.state.agent_state import AgentState


class SessionRuntime:
    """Manages a multi-turn session over a shared store.

    Precondition: agent + store must come from the same composition root (QĐ-2).
    SessionRuntime does NOT enforce this via reflection — caller's responsibility.
    """

    def __init__(self, agent: RuntimeAgent, store: MemoryStoreProtocol) -> None:
        self._agent = agent
        self._store = store
        self._session_id = str(uuid4())

    @property
    def session_id(self) -> str:
        return self._session_id

    def handle_turn(self, user_message: str) -> AgentState:
        state = AgentState(
            goal=user_message,
            memory=self._store,
            session_id=self._session_id,
        )
        return self._agent.run(state)

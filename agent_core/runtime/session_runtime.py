from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from agent_core.memory.base import MemoryStoreProtocol
from agent_core.runtime.runtime_agent import RuntimeAgent
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus
from agent_core.state.session_state import SessionState, SessionStatusView, TurnRecord


class SessionRuntime:
    """Manages a multi-turn session over a shared store.

    Precondition: agent + store must come from the same composition root (QĐ-2).
    SessionRuntime does NOT enforce this via reflection — caller's responsibility.
    """

    def __init__(self, agent: RuntimeAgent, store: MemoryStoreProtocol) -> None:
        self._agent = agent
        self._store = store
        now = datetime.now(timezone.utc)
        self._session = SessionState(
            session_id=str(uuid4()),
            created_at=now,
            updated_at=now,
        )

    @property
    def session_id(self) -> str:
        return self._session.session_id

    def handle_turn(self, user_message: str) -> AgentState:
        state = AgentState(
            goal=user_message,
            memory=self._store,
            session_id=self._session.session_id,
        )
        state = self._agent.run(state)              # raise → không tới append (QĐ-SR2-E case 2)
        if not state.is_terminal():                 # bug-guard (QĐ-SR2-E case 3)
            raise RuntimeError(
                f"run() returned non-terminal state: {state.status}"
            )
        record = TurnRecord(
            task_id=state.task_id,
            goal=state.goal,
            # FAILED → None: chống rò raw exception text qua final_answer (QĐ-SR2-C)
            final_answer=(
                state.final_answer if state.status == AgentStatus.COMPLETED else None
            ),
            status=state.status,
            planned_actions=tuple(s.action.value for s in state.plan),
            memory_degraded=state.memory_degraded,
            memory_write_failed=state.memory_write_failed,
            disclosure_reasons=tuple(state.disclosure_reasons),
            completed_at=datetime.now(timezone.utc),
        )
        self._session.append_turn(record)
        return state

    def get_status(self) -> SessionStatusView:
        return self._session.status_view()

    def get_history(self, *, limit: int = 10) -> tuple[TurnRecord, ...]:
        return self._session.history_view(limit)

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from agent_core.memory.base import MemoryStoreProtocol
from agent_core.runtime.runtime_agent import RuntimeAgent
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus
from agent_core.state.session_state import SessionState, SessionStatusView, TurnRecord

if TYPE_CHECKING:
    from agent_core.confirmation.models import ConfirmedSaveOperation
    from agent_core.session_persistence.base import SessionStoreProtocol

# Real recall (CLI) enables the bounded same-tick FTS stabilization (SPEC_M7B §10): at most
# 5 attempts, stop on first hit, never retry a remote failure. Tests override this.
_RECALL_MAX_ATTEMPTS = 5


class SessionRuntime:
    """Manages a multi-turn session over a shared store.

    Precondition: agent + store must come from the same composition root (QĐ-2).
    SessionRuntime does NOT enforce this via reflection — caller's responsibility.

    Persistence contract:
      - Without session_store: turns accumulate in-memory only (SR1/SR2 behaviour).
      - With session_store: caller MUST pass an explicit session object.
        Violation → ValueError (programming error, caught at startup, not at runtime).
      - handle_turn persists a candidate session BEFORE mutating the live session.
        If save() raises, the live session is NOT mutated (fail-closed for history).
    """

    def __init__(
        self,
        agent: RuntimeAgent,
        store: MemoryStoreProtocol,
        *,
        session: SessionState | None = None,
        session_store: SessionStoreProtocol | None = None,
        user_id: str | None = None,
    ) -> None:
        if session is None and session_store is not None:
            raise ValueError(
                "session_store requires an explicit session object. "
                "Pass session= when constructing SessionRuntime with a store."
            )
        # Application-owned identity for M7-A confirmed saves. Optional (defaults None) so
        # existing natural-language callers stay compatible; blank non-None is rejected.
        if user_id is not None:
            if not isinstance(user_id, str) or not user_id.strip():
                raise ValueError("user_id must be None or a nonblank string")
            user_id = user_id.strip()
        self._user_id = user_id
        self._agent = agent
        self._store = store
        self._session_store = session_store
        if session is not None:
            self._session = session
        else:
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
        self._record_terminal_state(state)          # SR2/SR3 persist-before-mutate
        return state

    def run_confirmed_decision_save(
        self,
        operation: "ConfirmedSaveOperation",
    ) -> AgentState:
        """M7-A dedicated structured save run (SPEC §15.2). Not a natural-language turn.

        Builds a run-only AgentState carrying the frozen operation and delegates the
        required write to ``RuntimeAgent.run_confirmed_save``. Identity is application-owned;
        it is never recovered from decision text, evidence metadata or a hidden client default.
        """
        if not self._user_id:
            raise ValueError(
                "run_confirmed_decision_save requires an application-owned user_id"
            )
        session_id = self._session.session_id
        if (
            operation.session_id is None
            or not operation.session_id.strip()
            or operation.session_id != session_id
        ):
            raise ValueError(
                "operation session_id must be nonblank and equal the current session id"
            )

        state = AgentState(
            goal="Persist confirmed project decision",
            task_id=operation.task_id,
            user_id=self._user_id,
            session_id=session_id,
            memory=self._store,
            confirmed_save_operation=operation,
        )
        state = self._agent.run_confirmed_save(state)  # raise → no append (fail-closed history)
        if not state.is_terminal():
            raise RuntimeError(
                f"run_confirmed_save returned non-terminal state: {state.status}"
            )
        self._record_terminal_state(state)
        return state

    def run_memory_recall(
        self,
        query: str,
        *,
        max_attempts: int = _RECALL_MAX_ATTEMPTS,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> AgentState:
        """M7-B dedicated cross-process recall run (SPEC_M7B §11). Not a natural-language turn.

        Builds a run-only AgentState for THIS session (a fresh session_id relative to the
        writing session does not block recall — retrieval is scoped by project_id + user_id,
        not session_id) and delegates to ``RuntimeAgent.run_memory_recall``. Identity is the
        application-owned ``user_id`` (same source as M7-A); it is never recovered from the
        query. The recall never reads ``confirmed_save_operation`` and never uses a local store.
        """
        if not query or not query.strip():
            raise ValueError("recall query must be a nonblank string")

        state = AgentState(
            goal=query.strip(),
            user_id=self._user_id,
            session_id=self._session.session_id,
            memory=self._store,
        )
        state = self._agent.run_memory_recall(
            state, max_attempts=max_attempts, sleep_fn=sleep_fn
        )
        if not state.is_terminal():
            raise RuntimeError(
                f"run_memory_recall returned non-terminal state: {state.status}"
            )
        self._record_terminal_state(state)
        return state

    def _record_terminal_state(self, state: AgentState) -> None:
        """Build a TurnRecord and persist-before-mutate. Shared by NL and confirmed-save paths.

        FAILED → final_answer masked to None (anti-leak, QĐ-SR2-C). The confirmed operation,
        evidence object, decision content and request payload are never serialized as fields.
        """
        record = TurnRecord(
            task_id=state.task_id,
            goal=state.goal,
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

        if self._session_store is not None:
            # Build candidate WITHOUT mutating live session (persist-before-mutate)
            candidate = dataclasses.replace(
                self._session,
                turns=self._session.turns + [record],
                updated_at=record.completed_at,
            )
            self._session_store.save(candidate)  # SessionPersistenceError → propagate

        self._session.append_turn(record)          # only after successful save

    def get_status(self) -> SessionStatusView:
        return self._session.status_view()

    def get_history(self, *, limit: int = 10) -> tuple[TurnRecord, ...]:
        return self._session.history_view(limit)

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from agent_core.state.enums import AgentStatus


@dataclass(frozen=True)
class TurnRecord:
    task_id: str
    goal: str
    final_answer: str | None
    status: AgentStatus
    planned_actions: tuple[str, ...]
    memory_degraded: bool
    memory_write_failed: bool
    disclosure_reasons: tuple[str, ...]
    completed_at: datetime


@dataclass(frozen=True)
class SessionStatusView:
    session_id: str
    turn_count: int
    last_status: AgentStatus | None
    last_goal: str | None


@dataclass
class SessionState:
    session_id: str
    created_at: datetime
    updated_at: datetime
    turns: list[TurnRecord] = field(default_factory=list)

    def append_turn(self, record: TurnRecord) -> None:
        self.turns.append(record)
        self.updated_at = record.completed_at   # KHÔNG now() lần 2 — dùng timestamp của record

    def status_view(self) -> SessionStatusView:
        return SessionStatusView(
            session_id=self.session_id,
            turn_count=len(self.turns),
            last_status=self.turns[-1].status if self.turns else None,
            last_goal=self.turns[-1].goal if self.turns else None,
        )

    def history_view(self, limit: int) -> tuple[TurnRecord, ...]:
        if limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit}")
        return tuple(self.turns[-limit:])

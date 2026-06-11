from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus


@dataclass(frozen=True)
class RuntimeEvent:
    name: str
    task_id: str
    status: AgentStatus
    step_index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RuntimeLifecycle:
    def emit_event(
        self,
        state: AgentState,
        name: str,
        *,
        step_index: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        event = RuntimeEvent(
            name=name,
            task_id=state.task_id,
            status=state.status,
            step_index=step_index,
            metadata=metadata or {},
        )

        state.history.append(
            f"[event] {event.name} status={event.status.value} step={event.step_index}"
        )
        return event


__all__ = ["RuntimeEvent", "RuntimeLifecycle"]
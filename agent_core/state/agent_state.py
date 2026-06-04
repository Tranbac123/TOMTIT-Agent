from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_core.memory.in_memory_store import InMemoryMemoryStore
from agent_core.state.enums import AgentStatus, RiskLevel, StepStatus, ToolName
from agent_core.state.observation import Observation
from agent_core.tools.schemas import Source


@dataclass
class Step:
    thought: str
    action: ToolName
    args: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    status: StepStatus = StepStatus.PENDING
    risk_level: RiskLevel = RiskLevel.LOW
    depends_on: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentState:
    goal: str
    task_id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str | None = None
    session_id: str | None = None
    status: AgentStatus = AgentStatus.CREATED
    plan: list[Step] = field(default_factory=list)
    current_step: int = 0
    done: bool = False
    final_answer: str | None = None
    last_result: Any = None
    slots: dict[str, Any] = field(default_factory=dict)
    memory: InMemoryMemoryStore = field(default_factory=InMemoryMemoryStore)
    history: list[str] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    max_steps: int = 5

    def add_observation(self, obs: Observation) -> None:
        self.observations.append(obs)
        if obs.sources:
            self.sources.extend(obs.sources)

    def set_slot(self, key: str, value: Any) -> Any:
        self.slots[key] = value
        return value

    def get_slot(self, key: str, default: Any = None) -> Any:
        return self.slots.get(key, default)

    def fail(self, error: str) -> None:
        self.status = AgentStatus.FAILED
        self.done = True
        self.final_answer = error
        self.errors.append(error)

    def complete(self, answer: str) -> None:
        self.status = AgentStatus.COMPLETED
        self.done = True
        self.final_answer = answer

    def debug_dump(self) -> dict[str, Any]:
        return asdict(self)

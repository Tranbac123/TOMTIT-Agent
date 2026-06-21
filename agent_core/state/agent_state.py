from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_core.confirmation.models import ConfirmedSaveOperation
    from agent_core.memory.contracts import ContextPack
from uuid import uuid4

from agent_core.memory.base import MemoryStoreProtocol
from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.state.enums import AgentStatus, RiskLevel, SourceType, StepStatus, ToolName
from agent_core.state.observation import Observation
from agent_core.tools.schemas import Source, ToolResult


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

    def mark_running(self) -> None:
        self.status = StepStatus.RUNNING

    def mark_completed(self) -> None:
        self.status = StepStatus.COMPLETED

    def mark_failed(self) -> None:
        self.status = StepStatus.FAILED


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

    last_result: ToolResult | None = None
    slots: dict[str, Any] = field(default_factory=dict)

    # deprecated-but-shared (QĐ-2 §7 SPEC_memory_client): built-in tools read/write here;
    # composition root passes the SAME reference into LocalMemoryClient → no split-brain.
    # Do NOT add new code using this field. Migration to MemoryClientProtocol-only: post-P4.
    memory: MemoryStoreProtocol = field(default_factory=InMemoryStore)

    history: list[str] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # Memory client state — P3 wiring (SPEC_P3, SPEC_memory_client §5, §7b)
    context_pack: "ContextPack | None" = None  # first-class: affects planning/degraded/disclosure/replay (QĐ-3)
    memory_degraded: bool = False              # monotonic — only rises, never resets in one run (§5)
    memory_write_failed: bool = False          # §5b: write best-effort fail
    disclosure_reasons: list[str] = field(default_factory=list)  # §7b: policy appends, composer reads
    context_consumed: bool = False             # P4: tool_answer_from_context sets True when exactly 1 item used

    max_steps: int = 5

    approved_tools: set[ToolName] = field(default_factory=set)
    read_only: bool = False

    # M7-A run-only input: one confirmed-decision save operation. Additive, default None.
    # Not placed in slots; not serialized into TurnRecord/SessionState; not restored on resume.
    confirmed_save_operation: "ConfirmedSaveOperation | None" = None

    def add_observation(self, obs: Observation) -> None:
        self.observations.append(obs)
        if obs.sources:
            self._add_sources(obs.sources)

    def _add_sources(self, sources: list[Source]) -> None:
        seen = {self._source_key(source) for source in self.sources}
        for source in sources:
            key = self._source_key(source)
            if key not in seen:
                self.sources.append(source)
                seen.add(key)

    def _source_key(self, source: Source) -> str:
        url = getattr(source, "url", None)
        title = getattr(source, "title", None)
        return str(url or title or source)

    def set_slot(self, key: str, value: Any) -> Any:
        self.slots[key] = value
        return value

    def get_slot(self, key: str, default: Any = None) -> Any:
        return self.slots.get(key, default)

    def approve_tool(self, tool_name: ToolName) -> None:
        self.approved_tools.add(tool_name)

    def revoke_tool_approval(self, tool_name: ToolName) -> None:
        self.approved_tools.discard(tool_name)

    def fail(self, error: str) -> None:
        self.status = AgentStatus.FAILED
        self.done = True
        self.final_answer = error
        self.errors.append(error)

    def complete(self, answer: str) -> None:
        self.status = AgentStatus.COMPLETED
        self.done = True
        self.final_answer = answer

    def is_terminal(self) -> bool:
        return self.done or self.status in {
            AgentStatus.COMPLETED,
            AgentStatus.FAILED,
        }

    def can_continue(self) -> bool:
        return not self.is_terminal() and self.current_step < self.max_steps

    def debug_dump(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "task_id": self.task_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "status": self.status.value,
            "current_step": self.current_step,
            "done": self.done,
            "final_answer": self.final_answer,
            "slots": self.slots,
            "errors": self.errors,
            "max_steps": self.max_steps,
            "read_only": self.read_only,
            "approved_tools": [tool.value for tool in self.approved_tools],
            "plan": [
                {
                    "id": step.id,
                    "thought": step.thought,
                    "action": step.action.value,
                    "args": step.args,
                    "status": step.status.value,
                    "risk_level": step.risk_level.value,
                    "depends_on": step.depends_on,
                    "created_at": step.created_at.isoformat(),
                    "metadata": step.metadata,
                }
                for step in self.plan
            ],
            "observations_count": len(self.observations),
            "sources_count": len(self.sources),
            "last_result_success": (
                self.last_result.success if self.last_result is not None else None
            ),
            "last_result_error": (
                self.last_result.error if self.last_result is not None else None
            ),
        }
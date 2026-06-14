from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from agent_core.memory.client import MemoryClientProtocol
from agent_core.memory.contracts import MemoryCandidate
from agent_core.output.final_composer import DefaultFinalComposer, FinalComposer
from agent_core.planning.plan_validator import validate_plan
from agent_core.planning.rule_based_planner import RuleBasedPlanner
from agent_core.runtime.lifecycle import RuntimeLifecycle
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import AgentStatus, ToolName
from agent_core.tools.arg_resolver import ArgResolver, stringify_output
from agent_core.tools.base import ToolSpec
from agent_core.tools.executor import ToolExecutor

_logger = logging.getLogger(__name__)

# Actions that indicate the user expects durable persistence.
_MEMORY_ACTIONS = frozenset({
    ToolName.WRITE_NOTE,
    ToolName.SAVE_FACT,
    ToolName.SAVE_PREFERENCE,
    ToolName.SAVE_DECISION,
})

_DISCLOSURE_TEXT: dict[str, str] = {
    "memory_degraded": (
        "(Lưu ý: đang chạy ở chế độ memory rút gọn — ngữ cảnh dự án dài hạn có thể thiếu.)"
    ),
    "memory_write_failed": (
        "(Lưu ý: lưu memory không thành công cho lần này.)"
    ),
}


def append_disclosures(draft: str, reasons: list[str]) -> str:
    """Pure helper — NOT a method of FinalComposer (SPEC §3e). Deterministic: map each
    reason to a fixed sentence. Empty reasons → draft unchanged."""
    if not reasons:
        return draft
    lines = [_DISCLOSURE_TEXT[r] for r in reasons if r in _DISCLOSURE_TEXT]
    return draft + ("\n\n" + "\n".join(lines) if lines else "")


class RuntimeAgent:
    def __init__(
        self,
        planner: Any,
        tools: Mapping[ToolName, ToolSpec],
        executor: ToolExecutor | None = None,
        final_composer: FinalComposer | None = None,
        lifecycle: RuntimeLifecycle | None = None,
        debug: bool = False,
        *,
        memory_client: MemoryClientProtocol | None = None,
    ):
        self.planner = planner
        self.tools = tools
        self.debug = debug
        self.executor = executor or ToolExecutor(
            tools=tools,
            resolver=ArgResolver(),
        )
        self.final_composer = final_composer or DefaultFinalComposer()
        self.lifecycle = lifecycle or RuntimeLifecycle()
        self.memory_client = memory_client  # None → retrieve/write no-op

    def run(self, state: AgentState) -> AgentState:
        self._retrieve_memory(state)      # before plan (SPEC §3b)
        if state.is_terminal():
            self._finalize_run(state)     # idempotency guard handles fail-case
            return state

        self._plan(state)
        if state.is_terminal():
            self._finalize_run(state)
            return state

        self._execute_plan(state)
        self._finalize_run(state)         # ONE finalize point (QĐ-1)
        return state

    # ------------------------------------------------------------------
    # Memory retrieve
    # ------------------------------------------------------------------

    def _retrieve_memory(self, state: AgentState) -> None:
        if self.memory_client is None:
            return
        try:
            pack = self.memory_client.retrieve_context_pack(
                state.goal,
                user_id=state.user_id,
                session_id=state.session_id,
                token_budget=1500,
                max_items=20,
            )
        except Exception as exc:
            state.fail(f"memory retrieve failed: {exc}")   # fail before plan (§3b)
            return
        state.context_pack = pack                          # first-class field (QĐ-3)
        if pack.degraded:
            state.memory_degraded = True                   # monotonic — only set True

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def _plan(self, state: AgentState) -> None:
        state.status = AgentStatus.PLANNING
        self.lifecycle.emit_event(state, "planning_started")

        try:
            state.plan = self.planner.make_plan(state)
            validate_plan(state.plan, self.tools)
        except Exception as exc:
            state.fail(f"Plan validation failed: {exc}")
            self.lifecycle.emit_event(
                state,
                "planning_failed",
                metadata={"error": str(exc)},
            )
            return

        state.history.append(f"Goal: {state.goal}")
        state.history.append(f"Plan length: {len(state.plan)}")
        self.lifecycle.emit_event(
            state,
            "planning_completed",
            metadata={"plan_length": len(state.plan)},
        )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute_plan(self, state: AgentState) -> None:
        state.status = AgentStatus.RUNNING
        self.lifecycle.emit_event(state, "running_started")

        for step_index, step in enumerate(state.plan, start=1):
            if state.is_terminal():
                break

            if step_index > state.max_steps:
                state.fail(f"Max steps exceeded: {state.max_steps}")
                self.lifecycle.emit_event(
                    state,
                    "run_failed",
                    step_index=step_index,
                    metadata={"reason": "max_steps_exceeded"},
                )
                break

            state.current_step = step_index
            state.history.append(f"[Step {step_index}] thought={step.thought}")
            state.history.append(f"[Step {step_index}] action={step.action.value}")

            self.lifecycle.emit_event(
                state,
                "step_started",
                step_index=step_index,
                metadata={"step_id": step.id, "action": step.action.value},
            )

            result = self.executor.execute(step, state)

            if result.success:
                state.history.append(
                    f"[Step {step_index}] output={stringify_output(result)}"
                )
                self.lifecycle.emit_event(
                    state,
                    "step_completed",
                    step_index=step_index,
                    metadata={
                        "step_id": step.id,
                        "action": step.action.value,
                        "tool_name": result.tool_name,
                    },
                )
            else:
                state.fail(f"Tool error: {result.error}")
                self.lifecycle.emit_event(
                    state,
                    "step_failed",
                    step_index=step_index,
                    metadata={
                        "step_id": step.id,
                        "action": step.action.value,
                        "tool_name": result.tool_name,
                        "error": result.error,
                        "error_type": result.metadata.get("error_type"),
                    },
                )
                break

            if step.action == ToolName.FINISH:
                # KHÔNG gọi state.complete() ở đây (QĐ-1) — _finalize_run lo phần complete.
                # state.last_result đã được set bởi executor._record_result().
                self.lifecycle.emit_event(
                    state,
                    "finish_reached",
                    step_index=step_index,
                    metadata={"step_id": step.id, "action": step.action.value},
                )
                break

    # ------------------------------------------------------------------
    # Finalize — ONE completion authority (QĐ-1)
    # ------------------------------------------------------------------

    def _finalize_run(self, state: AgentState) -> None:
        if state.done:      # idempotency guard: fail() already set done=True → skip
            return

        # 1. compose draft (before complete so we can append disclosures)
        draft = self.final_composer.compose(state)

        # 2. write memory best-effort sync (§3f, §5b)
        self._write_memory(state)

        # 3. disclosure deterministic policy (§7b)
        self._apply_disclosure(state)
        draft = append_disclosures(draft, state.disclosure_reasons)

        # 4. terminal state transition — must be last
        state.complete(draft)
        self.lifecycle.emit_event(state, "run_completed", metadata={"reason": "finalize"})

    # ------------------------------------------------------------------
    # Memory write
    # ------------------------------------------------------------------

    def _write_memory(self, state: AgentState) -> None:
        if self.memory_client is None:
            return
        candidates = self._collect_candidates(state)
        if not candidates:
            return
        try:
            # P3: sync best-effort. No thread/timeout for local — InMemoryStore never blocks.
            # MEMORY_WRITE_TIMEOUT_SECONDS is reserved for RemoteMemoryClient httpx timeout (P6).
            self.memory_client.write_memory_candidates(
                candidates,
                user_id=state.user_id,
                session_id=state.session_id,
                task_id=state.task_id,
            )
        except Exception as exc:
            state.memory_write_failed = True
            state.errors.append(f"memory write failed: {exc}")
            _logger.warning("memory write failed for task %s: %s", state.task_id, exc)

    def _collect_candidates(self, state: AgentState) -> list[MemoryCandidate]:
        # MVP: returns [] — auto-extraction (memory mining) is post-MVP (CLAUDE.md §7).
        # Write path exists and is tested via subclass injection; not via auto-extraction.
        return []

    # ------------------------------------------------------------------
    # Disclosure
    # ------------------------------------------------------------------

    def _apply_disclosure(self, state: AgentState) -> None:
        if state.memory_degraded and self._task_touches_memory(state):
            if "memory_degraded" not in state.disclosure_reasons:
                state.disclosure_reasons.append("memory_degraded")
        if state.memory_write_failed and self._user_expected_persistence(state):
            if "memory_write_failed" not in state.disclosure_reasons:
                state.disclosure_reasons.append("memory_write_failed")

    def _task_touches_memory(self, state: AgentState) -> bool:
        """True if context_pack has items (agent actually used retrieved context)."""
        return state.context_pack is not None and bool(state.context_pack.items)

    def _user_expected_persistence(self, state: AgentState) -> bool:
        """True if plan contains a memory-writing step (user expected data to be saved)."""
        return any(step.action in _MEMORY_ACTIONS for step in state.plan)


# ------------------------------------------------------------------
# Composition root (QĐ-2, §3h) — one store, shared reference
# ------------------------------------------------------------------

def build_local_agent(
    *,
    planner: Any = None,
    tools: Any = None,
) -> tuple[RuntimeAgent, Any]:
    """Create RuntimeAgent + shared InMemoryStore for MVP-local demo.

    Returns (agent, store). Caller must pass `store` as `memory=store` when
    constructing AgentState so built-in tools and LocalMemoryClient share one source.
    """
    from agent_core.memory.in_memory_store import InMemoryStore
    from agent_core.memory.local_client import LocalMemoryClient
    from agent_core.tools.builtin_tools import FakeWebSearchClient
    from agent_core.tools.registry import build_tool_registry

    store = InMemoryStore()
    memory_client = LocalMemoryClient(store)
    agent = RuntimeAgent(
        planner=planner or RuleBasedPlanner(),
        tools=tools or build_tool_registry(FakeWebSearchClient()),
        memory_client=memory_client,
    )
    return agent, store


def build_test_agent() -> RuntimeAgent:
    from agent_core.tools.builtin_tools import FakeWebSearchClient
    from agent_core.tools.registry import build_tool_registry

    return RuntimeAgent(
        planner=RuleBasedPlanner(),
        tools=build_tool_registry(FakeWebSearchClient()),
    )

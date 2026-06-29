from __future__ import annotations

from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.memory.in_memory_store import InMemoryStore as MemoryStore
from agent_core.memory.memory_agent import MemoryAgent
from agent_core.memory.memory_records import MemoryQuery, MemoryRecord
from agent_core.planning.plan_validator import validate_plan
from agent_core.planning.extractors import GoalExtractor, normalize_vi
from agent_core.planning.rule_based_planner import RuleBasedPlanner
from agent_core.runtime.runtime_agent import RuntimeAgent, build_test_agent
from agent_core.state.agent_state import AgentState, Step
from agent_core.state.enums import (
    AgentStatus,
    Language,
    MemoryType,
    MessageRole,
    RiskLevel,
    SourceType,
    StepStatus,
    ToolName,
    ToolResultKind,
)
from agent_core.state.observation import Observation
from agent_core.tools.arg_resolver import ArgResolver, stringify_output
from agent_core.tools.base import RetryPolicy, ToolFn, ToolSpec
from agent_core.tools.builtin_tools import (
    FakeWebSearchClient,
    WebSearchClient,
    make_web_search_tool,
    safe_eval,
    tool_calculate,
    tool_finish,
    tool_list_notes,
    tool_read_note,
    tool_save_decision,
    tool_save_fact,
    tool_save_preference,
    tool_search_memory,
    tool_summarize,
    tool_summarize_memory,
    tool_write_note,
)
from agent_core.tools.executor import ToolExecutor
from agent_core.tools.registry import build_tool_registry
from agent_core.tools.schemas import (
    CalculateOutput,
    DeleteFileOutput,
    DeleteMailOutput,
    FinishOutput,
    ListNotesOutput,
    MemoryWriteOutput,
    ReadNoteOutput,
    SearchMemoryOutput,
    Source,
    SummarizeOutput,
    ToolResult,
    WebSearchOutput,
    WriteNoteOutput,
)

__all__ = [name for name in globals() if not name.startswith("_")] + ["HybridPlanner"]


def __getattr__(name: str):
    # PEP 562 lazy export. Keep ``agent_core.HybridPlanner`` importable on demand
    # without eagerly loading the dormant ``agent_core.planning.hybrid_planner`` at
    # package import (so importing agent_core stays free of the dormant planner).
    if name == "HybridPlanner":
        from agent_core.planning.hybrid_planner import HybridPlanner

        return HybridPlanner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

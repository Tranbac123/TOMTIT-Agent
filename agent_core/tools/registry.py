from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from agent_core.state.enums import RiskLevel, ToolName
from agent_core.tools.base import RetryPolicy, ToolFn, ToolSpec
from agent_core.tools.builtin_tools import (
    FakeWebSearchClient,
    WebSearchClient,
    make_web_search_tool,
    tool_answer_from_context,
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


@dataclass
class ToolRegistry:
    tools: dict[ToolName, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        self.tools[spec.name] = spec

    def get(self, name: ToolName) -> ToolSpec | None:
        return self.tools.get(name)

    def all(self) -> Mapping[ToolName, ToolSpec]:
        return dict(self.tools)


def build_tool_registry(
    web_search_client: WebSearchClient | None = None,
) -> dict[ToolName, ToolSpec]:
    web_search_client = web_search_client or FakeWebSearchClient()

    def spec(
        *,
        name: ToolName,
        fn: ToolFn,
        description: str,
        required_args: set[str] | None = None,
        allowed_args: set[str] | None = None,
        mutates_state: bool = False,
        risk_level: RiskLevel = RiskLevel.LOW,
        side_effects: tuple[str, ...] | list[str] | None = None,
        requires_approval: bool = False,
        timeout_seconds: float | None = None,
        retry_policy: RetryPolicy | None = None,
        idempotent: bool = True,
        args_schema: type | None = None,
    ) -> ToolSpec:
        required = required_args or set()
        allowed = allowed_args if allowed_args is not None else set(required)

        return ToolSpec(
            name=name,
            fn=fn,
            description=description,
            required_args=required,
            allowed_args=allowed,
            mutates_state=mutates_state,
            risk_level=risk_level,
            side_effects=side_effects or (),
            requires_approval=requires_approval,
            timeout_seconds=timeout_seconds,
            retry_policy=retry_policy or RetryPolicy(),
            idempotent=idempotent,
            args_schema=args_schema,
        )

    registry: dict[ToolName, ToolSpec] = {
        ToolName.CALCULATE: spec(
            name=ToolName.CALCULATE,
            fn=tool_calculate,
            description="Evaluate a basic arithmetic expression.",
            required_args={"expression"},
            allowed_args={"expression"},
        ),
        ToolName.WRITE_NOTE: spec(
            name=ToolName.WRITE_NOTE,
            fn=tool_write_note,
            description="Write content into agent memory notes.",
            required_args={"name", "content"},
            allowed_args={"name", "content"},
            mutates_state=True,
            risk_level=RiskLevel.LOW,
            side_effects=("memory_write",),
        ),
        ToolName.READ_NOTE: spec(
            name=ToolName.READ_NOTE,
            fn=tool_read_note,
            description="Read a note from agent memory.",
            required_args={"name"},
            allowed_args={"name"},
        ),
        ToolName.LIST_NOTES: spec(
            name=ToolName.LIST_NOTES,
            fn=tool_list_notes,
            description="List note names.",
            required_args=set(),
            allowed_args=set(),
        ),
        ToolName.SAVE_FACT: spec(
            name=ToolName.SAVE_FACT,
            fn=tool_save_fact,
            description="Save a durable fact into memory.",
            required_args={"content"},
            allowed_args={"content", "tags"},
            mutates_state=True,
            risk_level=RiskLevel.LOW,
            side_effects=("memory_write",),
            idempotent=False,
        ),
        ToolName.SAVE_PREFERENCE: spec(
            name=ToolName.SAVE_PREFERENCE,
            fn=tool_save_preference,
            description="Save a durable user preference into memory.",
            required_args={"content"},
            allowed_args={"content", "tags"},
            mutates_state=True,
            risk_level=RiskLevel.LOW,
            side_effects=("memory_write",),
            idempotent=False,
        ),
        ToolName.SAVE_DECISION: spec(
            name=ToolName.SAVE_DECISION,
            fn=tool_save_decision,
            description="Save a durable decision into memory.",
            required_args={"content"},
            allowed_args={"content", "tags"},
            mutates_state=True,
            risk_level=RiskLevel.LOW,
            side_effects=("memory_write",),
            idempotent=False,
        ),
        ToolName.SEARCH_MEMORY: spec(
            name=ToolName.SEARCH_MEMORY,
            fn=tool_search_memory,
            description="Search durable memory records.",
            required_args={"query"},
            allowed_args={"query", "limit"},
        ),
        ToolName.SUMMARIZE_MEMORY: spec(
            name=ToolName.SUMMARIZE_MEMORY,
            fn=tool_summarize_memory,
            description="Summarize durable memory records.",
            required_args=set(),
            allowed_args={"query", "limit"},
        ),
        ToolName.SUMMARIZE: spec(
            name=ToolName.SUMMARIZE,
            fn=tool_summarize,
            description="Summarize text using a simple rule-based strategy.",
            required_args={"text"},
            allowed_args={"text"},
        ),
        ToolName.WEB_SEARCH: spec(
            name=ToolName.WEB_SEARCH,
            fn=make_web_search_tool(web_search_client),
            description="Search the web and return summarized snippets with sources.",
            required_args={"query"},
            allowed_args={"query", "max_results"},
            timeout_seconds=15.0,
        ),
        ToolName.FINISH: spec(
            name=ToolName.FINISH,
            fn=tool_finish,
            description="Finish the task and return the final answer.",
            required_args={"answer"},
            allowed_args={"answer"},
        ),
        ToolName.ANSWER_FROM_CONTEXT: spec(
            name=ToolName.ANSWER_FROM_CONTEXT,
            fn=tool_answer_from_context,
            description="Answer a project-context question by reading the ContextPack (read-only, does not touch store).",
            required_args={"query"},
            allowed_args={"query"},
            mutates_state=False,
        ),
    }

    for tool_name, tool_spec in registry.items():
        if tool_name != tool_spec.name:
            raise ValueError(
                f"Registry key {tool_name.value} does not match ToolSpec.name "
                f"{tool_spec.name.value}."
            )

    # Guard: every ToolName member must be registered. Catches future enum additions that
    # forget a registry entry — fails at build time, not silently at runtime.
    registered = set(registry.keys())
    declared = set(ToolName)
    if registered != declared:
        raise ValueError(
            f"Registry mismatch — missing: {declared - registered}, "
            f"extra: {registered - declared}"
        )

    return registry
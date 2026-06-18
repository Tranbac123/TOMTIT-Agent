from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from agent_core.state.enums import RiskLevel, ToolName
from agent_core.tools.base import ToolSpec
from agent_core.tools.errors import DuplicateToolError, UnknownToolError


# ---------------------------------------------------------------------------
# Planner-safe manifest entry (no fn, no runtime state)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolManifestEntry:
    name: ToolName
    description: str
    required_args: tuple[str, ...]
    allowed_args: tuple[str, ...]
    input_schema: Mapping[str, object]
    mutates_state: bool
    risk_level: RiskLevel
    side_effects: tuple[str, ...]
    requires_approval: bool
    idempotent: bool


# ---------------------------------------------------------------------------
# Immutable tool registry — implements Mapping[ToolName, ToolSpec]
# ---------------------------------------------------------------------------

class ToolRegistry(Mapping[ToolName, ToolSpec]):
    """Immutable catalog of tool specifications.

    Constructed via ``from_specs()``.  Implements ``Mapping[ToolName, ToolSpec]``
    so existing consumers that accept a mapping need no changes.
    """

    def __init__(self, data: dict[ToolName, ToolSpec]) -> None:
        self._data: Mapping[ToolName, ToolSpec] = MappingProxyType(data)

    # -- Mapping protocol ---------------------------------------------------

    def __getitem__(self, name: ToolName) -> ToolSpec:
        try:
            return self._data[name]
        except KeyError:
            raise KeyError(name) from None

    def __iter__(self) -> Iterator[ToolName]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def get(  # type: ignore[override]
        self,
        name: ToolName,
        default: ToolSpec | None = None,
    ) -> ToolSpec | None:
        return self._data.get(name, default)

    # -- Extended API -------------------------------------------------------

    def require(self, name: ToolName) -> ToolSpec:
        """Return spec for *name* or raise ``UnknownToolError``."""
        spec = self._data.get(name)
        if spec is None:
            raise UnknownToolError(f"Unknown tool: {name.value!r}")
        return spec

    def all(self) -> Mapping[ToolName, ToolSpec]:
        """Return a read-only detached view of the registry."""
        return MappingProxyType(dict(self._data))

    def manifest(self) -> tuple[ToolManifestEntry, ...]:
        """Return a deterministic planner-safe descriptor tuple.

        Each call returns freshly constructed entries — mutations to one call's
        result do not affect subsequent calls or the registry itself.
        """
        entries = []
        for name, spec in self._data.items():
            schema_dict: dict[str, object] = (
                spec.args_schema.model_json_schema() if spec.args_schema else {}
            )
            entries.append(ToolManifestEntry(
                name=spec.name,
                description=spec.description,
                required_args=tuple(sorted(spec.required_args)),
                allowed_args=tuple(sorted(spec.allowed_args)),
                input_schema=MappingProxyType(schema_dict),
                mutates_state=spec.mutates_state,
                risk_level=spec.risk_level,
                side_effects=spec.side_effects,
                requires_approval=spec.requires_approval,
                idempotent=spec.idempotent,
            ))
        return tuple(entries)

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_specs(cls, specs: Iterable[ToolSpec]) -> ToolRegistry:
        """Build an immutable registry from an iterable of specs.

        Raises ``DuplicateToolError`` if the same ``ToolName`` appears more than once.
        """
        data: dict[ToolName, ToolSpec] = {}
        for spec in specs:
            if spec.name in data:
                raise DuplicateToolError(
                    f"Duplicate tool name: {spec.name.value!r}"
                )
            data[spec.name] = spec
        return cls(data)


# ---------------------------------------------------------------------------
# Static built-in provider
# ---------------------------------------------------------------------------

from agent_core.tools.builtin_tools import (  # noqa: E402
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
from agent_core.tools.input_schemas import (  # noqa: E402
    AnswerFromContextArgs,
    CalculateArgs,
    FinishArgs,
    ListNotesArgs,
    ReadNoteArgs,
    SaveDecisionArgs,
    SaveFactArgs,
    SavePreferenceArgs,
    SearchMemoryArgs,
    SummarizeArgs,
    SummarizeMemoryArgs,
    WebSearchArgs,
    WriteNoteArgs,
)


@dataclass(frozen=True)
class BuiltinToolDependencies:
    web_search_client: WebSearchClient


def builtin_tool_specs(
    dependencies: BuiltinToolDependencies,
) -> tuple[ToolSpec, ...]:
    """Return the 13 built-in ToolSpec instances in insertion order."""
    return (
        ToolSpec(
            name=ToolName.CALCULATE,
            fn=tool_calculate,
            description="Evaluate a basic arithmetic expression.",
            required_args=frozenset({"expression"}),
            allowed_args=frozenset({"expression"}),
            args_schema=CalculateArgs,
        ),
        ToolSpec(
            name=ToolName.WRITE_NOTE,
            fn=tool_write_note,
            description="Write content into agent memory notes.",
            required_args=frozenset({"name", "content"}),
            allowed_args=frozenset({"name", "content"}),
            mutates_state=True,
            risk_level=RiskLevel.LOW,
            side_effects=("memory_write",),
            args_schema=WriteNoteArgs,
        ),
        ToolSpec(
            name=ToolName.READ_NOTE,
            fn=tool_read_note,
            description="Read a note from agent memory.",
            required_args=frozenset({"name"}),
            allowed_args=frozenset({"name"}),
            args_schema=ReadNoteArgs,
        ),
        ToolSpec(
            name=ToolName.LIST_NOTES,
            fn=tool_list_notes,
            description="List note names.",
            required_args=frozenset(),
            allowed_args=frozenset(),
            args_schema=ListNotesArgs,
        ),
        ToolSpec(
            name=ToolName.SAVE_FACT,
            fn=tool_save_fact,
            description="Save a durable fact into memory.",
            required_args=frozenset({"content"}),
            allowed_args=frozenset({"content", "tags"}),
            mutates_state=True,
            risk_level=RiskLevel.LOW,
            side_effects=("memory_write",),
            idempotent=False,
            args_schema=SaveFactArgs,
        ),
        ToolSpec(
            name=ToolName.SAVE_PREFERENCE,
            fn=tool_save_preference,
            description="Save a durable user preference into memory.",
            required_args=frozenset({"content"}),
            allowed_args=frozenset({"content", "tags"}),
            mutates_state=True,
            risk_level=RiskLevel.LOW,
            side_effects=("memory_write",),
            idempotent=False,
            args_schema=SavePreferenceArgs,
        ),
        ToolSpec(
            name=ToolName.SAVE_DECISION,
            fn=tool_save_decision,
            description="Save a durable decision into memory.",
            required_args=frozenset({"content"}),
            allowed_args=frozenset({"content", "tags"}),
            mutates_state=True,
            risk_level=RiskLevel.LOW,
            side_effects=("memory_write",),
            idempotent=False,
            args_schema=SaveDecisionArgs,
        ),
        ToolSpec(
            name=ToolName.SEARCH_MEMORY,
            fn=tool_search_memory,
            description="Search durable memory records.",
            required_args=frozenset({"query"}),
            allowed_args=frozenset({"query", "limit"}),
            args_schema=SearchMemoryArgs,
        ),
        ToolSpec(
            name=ToolName.SUMMARIZE_MEMORY,
            fn=tool_summarize_memory,
            description="Summarize durable memory records.",
            required_args=frozenset(),
            allowed_args=frozenset({"query", "limit"}),
            args_schema=SummarizeMemoryArgs,
        ),
        ToolSpec(
            name=ToolName.SUMMARIZE,
            fn=tool_summarize,
            description="Summarize text using a simple rule-based strategy.",
            required_args=frozenset({"text"}),
            allowed_args=frozenset({"text"}),
            args_schema=SummarizeArgs,
        ),
        ToolSpec(
            name=ToolName.WEB_SEARCH,
            fn=make_web_search_tool(dependencies.web_search_client),
            description="Search the web and return summarized snippets with sources.",
            required_args=frozenset({"query"}),
            allowed_args=frozenset({"query", "max_results"}),
            # timeout_seconds=None: executor does not enforce timeout (EX1-I7).
            # Prior value 15.0 was dead metadata — corrected here.
            args_schema=WebSearchArgs,
        ),
        ToolSpec(
            name=ToolName.FINISH,
            fn=tool_finish,
            description="Finish the task and return the final answer.",
            required_args=frozenset({"answer"}),
            allowed_args=frozenset({"answer"}),
            args_schema=FinishArgs,
        ),
        ToolSpec(
            name=ToolName.ANSWER_FROM_CONTEXT,
            fn=tool_answer_from_context,
            description=(
                "Answer a project-context question by reading the ContextPack "
                "(read-only, does not touch store)."
            ),
            required_args=frozenset({"query"}),
            allowed_args=frozenset({"query"}),
            args_schema=AnswerFromContextArgs,
        ),
    )


def build_tool_registry(
    web_search_client: WebSearchClient | None = None,
) -> ToolRegistry:
    """Build and return the production immutable tool registry."""
    dependencies = BuiltinToolDependencies(
        web_search_client=web_search_client or FakeWebSearchClient(),
    )
    specs = builtin_tool_specs(dependencies)

    # Completeness guard: every ToolName member must appear exactly once.
    registered = {s.name for s in specs}
    declared = set(ToolName)
    if registered != declared:
        raise RuntimeError(
            f"Built-in registry mismatch — missing: {declared - registered}, "
            f"extra: {registered - declared}"
        )

    return ToolRegistry.from_specs(specs)

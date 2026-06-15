from __future__ import annotations

import ast
import operator
from typing import Any

from agent_core.memory.memory_agent import MemoryAgent
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import MemoryType, ToolName, ToolResultKind
from agent_core.tools.arg_resolver import stringify_output
from agent_core.tools.base import ToolFn
from agent_core.tools.schemas import (
    AnswerFromContextOutput,
    CalculateOutput,
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


_ALLOWED_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}

_ALLOWED_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def safe_eval(expr: str) -> float:
    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)

        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Only numbers are allowed")

        if isinstance(node, ast.Num):
            return float(node.n)

        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in _ALLOWED_BIN_OPS:
                raise ValueError(f"Unsupported operator: {op_type.__name__}")
            return _ALLOWED_BIN_OPS[op_type](
                _eval(node.left),
                _eval(node.right),
            )

        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in _ALLOWED_UNARY_OPS:
                raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
            return _ALLOWED_UNARY_OPS[op_type](_eval(node.operand))

        raise ValueError(f"Unsupported expression: {type(node).__name__}")

    return _eval(ast.parse(expr, mode="eval"))


def tool_calculate(state: AgentState, expression: str) -> ToolResult:
    tool_name = ToolName.CALCULATE.value

    try:
        value = safe_eval(expression)
        return ToolResult(
            success=True,
            output=CalculateOutput(expression, value),
            tool_name=tool_name,
            kind=ToolResultKind.NUMBER,
            metadata={"expression": expression},
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            error=f"calculate failed: {exc}",
            tool_name=tool_name,
            kind=ToolResultKind.NUMBER,
            metadata={
                "expression": expression,
                "error_type": type(exc).__name__,
            },
        )


def tool_write_note(
    state: AgentState,
    name: str,
    content: Any,
) -> ToolResult:
    tool_name = ToolName.WRITE_NOTE.value
    content_text = stringify_output(content)

    try:
        record = _memory_agent(state).write_note(
            name=name,
            content=content_text,
            task_id=state.task_id,
        )
        return ToolResult(
            success=True,
            output=WriteNoteOutput(
                name=name,
                saved=True,
                message=f"saved note '{name}'",
                memory_id=record.id,
            ),
            tool_name=tool_name,
            kind=ToolResultKind.ACTION,
            metadata={
                "memory_id": record.id,
                "note_name": name,
                "content_length": len(content_text),
                "mutates_state": True,
            },
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            error=f"write_note failed: {exc}",
            tool_name=tool_name,
            kind=ToolResultKind.ACTION,
            metadata={
                "note_name": name,
                "content_length": len(content_text),
                "mutates_state": True,
                "error_type": type(exc).__name__,
            },
        )


def tool_read_note(state: AgentState, name: str) -> ToolResult:
    tool_name = ToolName.READ_NOTE.value

    try:
        value = _memory_agent(state).read_note(name)

        if value is None:
            return ToolResult(
                success=False,
                error=f"note '{name}' not found",
                tool_name=tool_name,
                kind=ToolResultKind.TEXT,
                metadata={
                    "note_name": name,
                    "reason": "not_found",
                },
            )

        return ToolResult(
            success=True,
            output=ReadNoteOutput(name, value),
            tool_name=tool_name,
            kind=ToolResultKind.TEXT,
            metadata={
                "note_name": name,
                "content_length": len(value),
            },
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            error=f"read_note failed: {exc}",
            tool_name=tool_name,
            kind=ToolResultKind.TEXT,
            metadata={
                "note_name": name,
                "error_type": type(exc).__name__,
            },
        )


def tool_list_notes(state: AgentState) -> ToolResult:
    tool_name = ToolName.LIST_NOTES.value

    try:
        names = _memory_agent(state).list_notes()
        return ToolResult(
            success=True,
            output=ListNotesOutput(names),
            tool_name=tool_name,
            kind=ToolResultKind.JSON,
            metadata={"count": len(names)},
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            error=f"list_notes failed: {exc}",
            tool_name=tool_name,
            kind=ToolResultKind.JSON,
            metadata={"error_type": type(exc).__name__},
        )


def tool_save_fact(
    state: AgentState,
    content: str,
    tags: list[str] | None = None,
) -> ToolResult:
    return _save_memory(
        state=state,
        content=content,
        memory_type=MemoryType.FACT,
        tags=tags,
    )


def tool_save_preference(
    state: AgentState,
    content: str,
    tags: list[str] | None = None,
) -> ToolResult:
    return _save_memory(
        state=state,
        content=content,
        memory_type=MemoryType.PREFERENCE,
        tags=tags,
    )


def tool_save_decision(
    state: AgentState,
    content: str,
    tags: list[str] | None = None,
) -> ToolResult:
    return _save_memory(
        state=state,
        content=content,
        memory_type=MemoryType.DECISION,
        tags=tags,
    )


def tool_search_memory(
    state: AgentState,
    query: str,
    limit: int = 10,
) -> ToolResult:
    tool_name = ToolName.SEARCH_MEMORY.value

    try:
        records = _memory_agent(state).search_memory(
            query=query,
            limit=limit,
        )
        return ToolResult(
            success=True,
            output=SearchMemoryOutput(
                records=[record.to_dict() for record in records],
                query=query,
                count=len(records),
            ),
            tool_name=tool_name,
            kind=ToolResultKind.JSON,
            metadata={
                "query": query,
                "count": len(records),
                "limit": limit,
            },
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            error=f"search_memory failed: {exc}",
            tool_name=tool_name,
            kind=ToolResultKind.JSON,
            metadata={
                "query": query,
                "limit": limit,
                "error_type": type(exc).__name__,
            },
        )


def tool_summarize_memory(
    state: AgentState,
    query: str = "",
    limit: int = 10,
) -> ToolResult:
    tool_name = ToolName.SUMMARIZE_MEMORY.value

    try:
        summary = _memory_agent(state).summarize_memory(
            query=query,
            limit=limit,
        )
        return ToolResult(
            success=True,
            output=SummarizeOutput(
                summary=summary,
                original_length=len(summary),
                summary_length=len(summary),
                sentence_count=len(summary.splitlines()),
            ),
            tool_name=tool_name,
            kind=ToolResultKind.TEXT,
            metadata={
                "query": query,
                "limit": limit,
            },
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            error=f"summarize_memory failed: {exc}",
            tool_name=tool_name,
            kind=ToolResultKind.TEXT,
            metadata={
                "query": query,
                "limit": limit,
                "error_type": type(exc).__name__,
            },
        )


def tool_summarize(state: AgentState, text: str) -> ToolResult:
    tool_name = ToolName.SUMMARIZE.value
    normalized_text = " ".join(text.strip().split())

    if not normalized_text:
        return ToolResult(
            success=False,
            error="empty text",
            tool_name=tool_name,
            kind=ToolResultKind.TEXT,
            metadata={
                "reason": "empty_text",
                "original_length": len(text),
            },
        )

    sentences = [
        sentence.strip()
        for sentence in normalized_text.replace("!", ".").replace("?", ".").split(".")
        if sentence.strip()
    ]
    summary = normalized_text[:120] if not sentences else ". ".join(sentences[:2])

    return ToolResult(
        success=True,
        output=SummarizeOutput(
            summary=summary,
            original_length=len(normalized_text),
            summary_length=len(summary),
            sentence_count=len(sentences),
        ),
        tool_name=tool_name,
        kind=ToolResultKind.TEXT,
        metadata={
            "strategy": "first_2_sentences",
            "max_sentences": 2,
        },
    )


def tool_finish(state: AgentState, answer: Any) -> ToolResult:
    tool_name = ToolName.FINISH.value
    final_answer = stringify_output(answer).strip()

    if not final_answer:
        return ToolResult(
            success=False,
            error="empty final answer",
            tool_name=tool_name,
            kind=ToolResultKind.EMPTY,
            metadata={"reason": "empty_answer"},
        )

    return ToolResult(
        success=True,
        output=FinishOutput(final_answer),
        tool_name=tool_name,
        kind=ToolResultKind.TEXT,
        metadata={
            "answer_length": len(final_answer),
            "terminal": True,
        },
    )


# MemoryType values that represent project-level context.
# Relevance-matching is NOT done (LocalMemoryClient ignores goal) — filter by type only.
_PROJECT_CONTEXT_TYPES = (MemoryType.DECISION, MemoryType.PROJECT_CONTEXT)


def tool_answer_from_context(state: AgentState, query: str) -> ToolResult:
    """Read project context from state.context_pack (NOT state.memory). Read-only."""
    tool_name = ToolName.ANSWER_FROM_CONTEXT.value
    pack = state.context_pack
    items = [i for i in pack.items if i.type in _PROJECT_CONTEXT_TYPES] if pack else []

    # 0 matching items — not enough context. context_consumed stays False.
    if len(items) == 0:
        return ToolResult(
            success=True,
            output=AnswerFromContextOutput(
                answer="Tôi không có đủ project context để trả lời câu hỏi này.",
                used_item_count=0,
            ),
            tool_name=tool_name,
            kind=ToolResultKind.TEXT,
            metadata={"reason": "no_context", "matched": 0},
        )

    # >1 matching items — no relevance ranking available, cannot choose. context_consumed stays False.
    if len(items) > 1:
        return ToolResult(
            success=True,
            output=AnswerFromContextOutput(
                answer="Project context chưa đủ rõ (có nhiều mục liên quan).",
                used_item_count=0,
            ),
            tool_name=tool_name,
            kind=ToolResultKind.TEXT,
            metadata={"reason": "ambiguous_context", "matched": len(items)},
        )

    # Exactly 1 item — use its content. Set context_consumed=True (real consumer signal).
    item = items[0]
    state.context_consumed = True
    return ToolResult(
        success=True,
        output=AnswerFromContextOutput(
            answer=f"Theo project context đã lưu: {item.content}",
            used_item_count=1,
        ),
        tool_name=tool_name,
        kind=ToolResultKind.TEXT,
        metadata={
            "reason": "used_context",
            "matched": 1,
            "memory_id": item.metadata.get("memory_id"),
        },
    )


def _memory_agent(state: AgentState) -> MemoryAgent:
    return MemoryAgent(
        state.memory,
        user_id=state.user_id,
        session_id=state.session_id,
    )


def _save_memory(
    *,
    state: AgentState,
    content: str,
    memory_type: MemoryType,
    tags: list[str] | None = None,
) -> ToolResult:
    tool_name = _memory_tool_name(memory_type)

    try:
        agent = _memory_agent(state)

        if memory_type == MemoryType.FACT:
            record = agent.save_fact(
                content=content,
                tags=tags,
                task_id=state.task_id,
            )
        elif memory_type == MemoryType.PREFERENCE:
            record = agent.save_preference(
                content=content,
                tags=tags,
                task_id=state.task_id,
            )
        elif memory_type == MemoryType.DECISION:
            record = agent.save_decision(
                content=content,
                tags=tags,
                task_id=state.task_id,
            )
        else:
            record = agent.save_memory(
                content=content,
                memory_type=memory_type,
                tags=tags,
                task_id=state.task_id,
            )

        return ToolResult(
            success=True,
            output=MemoryWriteOutput(
                id=record.id,
                type=record.type.value,
                content=record.content,
                tags=record.tags,
                importance=record.importance,
                confidence=record.confidence,
            ),
            tool_name=tool_name,
            kind=ToolResultKind.ACTION,
            metadata={
                "memory_id": record.id,
                "memory_type": record.type.value,
                "tags": record.tags,
                "importance": record.importance,
                "confidence": record.confidence,
                "mutates_state": True,
            },
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            error=f"{tool_name} failed: {exc}",
            tool_name=tool_name,
            kind=ToolResultKind.ACTION,
            metadata={
                "memory_type": memory_type.value,
                "tags": tags or [],
                "mutates_state": True,
                "error_type": type(exc).__name__,
            },
        )


def _memory_tool_name(memory_type: MemoryType) -> str:
    if memory_type == MemoryType.FACT:
        return ToolName.SAVE_FACT.value

    if memory_type == MemoryType.PREFERENCE:
        return ToolName.SAVE_PREFERENCE.value

    if memory_type == MemoryType.DECISION:
        return ToolName.SAVE_DECISION.value

    return f"save_{memory_type.value}"


class WebSearchClient:
    def search(self, query: str, max_results: int = 5) -> list[Source]:
        raise NotImplementedError


class FakeWebSearchClient(WebSearchClient):
    def search(self, query: str, max_results: int = 5) -> list[Source]:
        query = query.strip()
        return [
            Source(
                title=f"Fake result for {query}",
                url="https://example.com",
                snippet=f"Fake snippet about {query}",
                metadata={"provider": "fake"},
            )
        ][:max_results]


def make_web_search_tool(client: WebSearchClient) -> ToolFn:
    def tool_web_search(
        state: AgentState,
        query: str,
        max_results: int = 3,
    ) -> ToolResult:
        tool_name = ToolName.WEB_SEARCH.value

        try:
            query = query.strip()

            if not query:
                return ToolResult(
                    success=False,
                    error="web_search failed: empty query",
                    tool_name=tool_name,
                    kind=ToolResultKind.SEARCH,
                    metadata={"reason": "empty_query"},
                )

            sources = client.search(
                query=query,
                max_results=max_results,
            )
            snippets = [source.snippet or "" for source in sources]

            return ToolResult(
                success=True,
                output=WebSearchOutput(
                    answer="\n".join(snippets[:3]),
                    snippets=snippets,
                    sources=[source.url or source.title for source in sources],
                ),
                tool_name=tool_name,
                kind=ToolResultKind.SEARCH,
                sources=sources,
                metadata={
                    "query": query,
                    "max_results": max_results,
                    "provider": type(client).__name__,
                },
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"web_search failed: {exc}",
                tool_name=tool_name,
                kind=ToolResultKind.SEARCH,
                metadata={
                    "query": query,
                    "max_results": max_results,
                    "provider": type(client).__name__,
                    "error_type": type(exc).__name__,
                },
            )

    return tool_web_search
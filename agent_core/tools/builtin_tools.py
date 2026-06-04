from __future__ import annotations

from dataclasses import asdict
from typing import Any
import ast
import operator

from agent_core.memory.memory_agent import MemoryAgent
from agent_core.memory.memory_records import MemoryQuery
from agent_core.state.agent_state import AgentState
from agent_core.state.enums import MemoryType, RiskLevel, ToolName, ToolResultKind
from agent_core.tools.arg_resolver import stringify_output
from agent_core.tools.base import ToolFn, ToolSpec
from agent_core.tools.schemas import (
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
_ALLOWED_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


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
            return _ALLOWED_BIN_OPS[op_type](_eval(node.left), _eval(node.right))
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
        return ToolResult(True, CalculateOutput(expression, value), tool_name=tool_name, kind=ToolResultKind.NUMBER, metadata={"expression": expression})
    except Exception as exc:
        return ToolResult(False, error=f"calculate failed: {exc}", tool_name=tool_name, kind=ToolResultKind.NUMBER, metadata={"expression": expression, "error_type": type(exc).__name__})


def tool_write_note(state: AgentState, name: str, content: Any) -> ToolResult:
    tool_name = ToolName.WRITE_NOTE.value
    content_text = stringify_output(content)
    try:
        state.memory.write_note(name, content_text)
        return ToolResult(True, WriteNoteOutput(name, True, f"saved note '{name}'"), tool_name=tool_name, kind=ToolResultKind.ACTION, metadata={"note_name": name, "content_length": len(content_text), "mutates_state": True})
    except Exception as exc:
        return ToolResult(False, error=f"write_note failed: {exc}", tool_name=tool_name, kind=ToolResultKind.ACTION, metadata={"note_name": name, "content_length": len(content_text), "mutates_state": True, "error_type": type(exc).__name__})


def tool_read_note(state: AgentState, name: str) -> ToolResult:
    tool_name = ToolName.READ_NOTE.value
    try:
        value = state.memory.read_note(name)
        if value is None:
            return ToolResult(False, error=f"note '{name}' not found", tool_name=tool_name, kind=ToolResultKind.TEXT, metadata={"note_name": name, "reason": "not_found"})
        return ToolResult(True, ReadNoteOutput(name, value), tool_name=tool_name, kind=ToolResultKind.TEXT, metadata={"note_name": name, "content_length": len(value)})
    except Exception as exc:
        return ToolResult(False, error=f"read_note failed: {exc}", tool_name=tool_name, kind=ToolResultKind.TEXT, metadata={"note_name": name, "error_type": type(exc).__name__})


def tool_list_notes(state: AgentState) -> ToolResult:
    return ToolResult(True, ListNotesOutput(state.memory.list_notes()), tool_name=ToolName.LIST_NOTES.value, kind=ToolResultKind.JSON)


def _memory_agent(state: AgentState) -> MemoryAgent:
    return MemoryAgent(state.memory, user_id=state.user_id, session_id=state.session_id)


def _save_memory(state: AgentState, content: str, memory_type: MemoryType, tags: list[str] | None = None) -> ToolResult:
    agent = _memory_agent(state)
    if memory_type == MemoryType.FACT:
        record = agent.save_fact(content, tags)
    elif memory_type == MemoryType.PREFERENCE:
        record = agent.save_preference(content, tags)
    else:
        record = agent.save_decision(content, tags)
    return ToolResult(True, MemoryWriteOutput(record.id, record.type.value, record.content), tool_name=f"save_{record.type.value}", kind=ToolResultKind.ACTION, metadata={"memory_id": record.id})


def tool_save_fact(state: AgentState, content: str, tags: list[str] | None = None) -> ToolResult:
    return _save_memory(state, content, MemoryType.FACT, tags)


def tool_save_preference(state: AgentState, content: str, tags: list[str] | None = None) -> ToolResult:
    return _save_memory(state, content, MemoryType.PREFERENCE, tags)


def tool_save_decision(state: AgentState, content: str, tags: list[str] | None = None) -> ToolResult:
    return _save_memory(state, content, MemoryType.DECISION, tags)


def tool_search_memory(state: AgentState, query: str, limit: int = 10) -> ToolResult:
    records = state.memory.search(MemoryQuery(text=query, user_id=state.user_id, limit=limit))
    return ToolResult(True, SearchMemoryOutput([asdict(record) for record in records]), tool_name=ToolName.SEARCH_MEMORY.value, kind=ToolResultKind.JSON, metadata={"count": len(records)})


def tool_summarize_memory(state: AgentState, query: str = "", limit: int = 10) -> ToolResult:
    summary = _memory_agent(state).summarize_memory(query=query, limit=limit)
    return ToolResult(True, SummarizeOutput(summary, len(summary), len(summary), len(summary.splitlines())), tool_name=ToolName.SUMMARIZE_MEMORY.value, kind=ToolResultKind.TEXT)


def tool_summarize(state: AgentState, text: str) -> ToolResult:
    tool_name = ToolName.SUMMARIZE.value
    normalized_text = " ".join(text.strip().split())
    if not normalized_text:
        return ToolResult(False, error="empty text", tool_name=tool_name, kind=ToolResultKind.TEXT, metadata={"reason": "empty_text", "original_length": len(text)})
    sentences = [sentence.strip() for sentence in normalized_text.replace("!", ".").replace("?", ".").split(".") if sentence.strip()]
    summary = normalized_text[:120] if not sentences else ". ".join(sentences[:2])
    return ToolResult(True, SummarizeOutput(summary, len(normalized_text), len(summary), len(sentences)), tool_name=tool_name, kind=ToolResultKind.TEXT, metadata={"strategy": "first_2_sentences", "max_sentences": 2})


def tool_finish(state: AgentState, answer: Any) -> ToolResult:
    tool_name = ToolName.FINISH.value
    final_answer = stringify_output(answer).strip()
    if not final_answer:
        return ToolResult(False, error="empty final answer", tool_name=tool_name, kind=ToolResultKind.EMPTY, metadata={"reason": "empty_answer"})
    return ToolResult(True, FinishOutput(final_answer), tool_name=tool_name, kind=ToolResultKind.TEXT, metadata={"answer_length": len(final_answer), "terminal": True})


class WebSearchClient:
    def search(self, query: str, max_results: int = 5) -> list[Source]:
        raise NotImplementedError


class FakeWebSearchClient(WebSearchClient):
    def search(self, query: str, max_results: int = 5) -> list[Source]:
        query = query.strip()
        return [Source(title=f"Fake result for {query}", url="https://example.com", snippet=f"Fake snippet about {query}", metadata={"provider": "fake"})][:max_results]


def make_web_search_tool(client: WebSearchClient) -> ToolFn:
    def tool_web_search(state: AgentState, query: str, max_results: int = 3) -> ToolResult:
        tool_name = ToolName.WEB_SEARCH.value
        try:
            query = query.strip()
            if not query:
                return ToolResult(False, error="web_search failed: empty query", tool_name=tool_name, kind=ToolResultKind.SEARCH, metadata={"reason": "empty_query"})
            sources = client.search(query=query, max_results=max_results)
            snippets = [source.snippet or "" for source in sources]
            return ToolResult(True, WebSearchOutput("\n".join(snippets[:3]), snippets, [source.url or source.title for source in sources]), tool_name=tool_name, kind=ToolResultKind.SEARCH, sources=sources, metadata={"query": query, "max_results": max_results, "provider": type(client).__name__})
        except Exception as exc:
            return ToolResult(False, error=f"web_search failed: {exc}", tool_name=tool_name, kind=ToolResultKind.SEARCH, metadata={"query": query, "max_results": max_results, "provider": type(client).__name__, "error_type": type(exc).__name__})

    return tool_web_search


def build_tool_registry(web_search_client: WebSearchClient | None = None) -> dict[ToolName, ToolSpec]:
    web_search_client = web_search_client or FakeWebSearchClient()
    return {
        ToolName.CALCULATE: ToolSpec(ToolName.CALCULATE, tool_calculate, "Evaluate a basic arithmetic expression.", {"expression"}, {"expression"}),
        ToolName.WRITE_NOTE: ToolSpec(ToolName.WRITE_NOTE, tool_write_note, "Write content into agent memory notes.", {"name", "content"}, {"name", "content"}, mutates_state=True, risk_level=RiskLevel.LOW, side_effects=["memory_write"]),
        ToolName.READ_NOTE: ToolSpec(ToolName.READ_NOTE, tool_read_note, "Read a note from agent memory.", {"name"}, {"name"}),
        ToolName.LIST_NOTES: ToolSpec(ToolName.LIST_NOTES, tool_list_notes, "List note names.", set(), set()),
        ToolName.SAVE_FACT: ToolSpec(ToolName.SAVE_FACT, tool_save_fact, "Save a durable fact.", {"content"}, {"content", "tags"}, mutates_state=True, side_effects=["memory_write"]),
        ToolName.SAVE_PREFERENCE: ToolSpec(ToolName.SAVE_PREFERENCE, tool_save_preference, "Save a durable user preference.", {"content"}, {"content", "tags"}, mutates_state=True, side_effects=["memory_write"]),
        ToolName.SAVE_DECISION: ToolSpec(ToolName.SAVE_DECISION, tool_save_decision, "Save a durable decision.", {"content"}, {"content", "tags"}, mutates_state=True, side_effects=["memory_write"]),
        ToolName.SEARCH_MEMORY: ToolSpec(ToolName.SEARCH_MEMORY, tool_search_memory, "Search durable memory.", {"query"}, {"query", "limit"}),
        ToolName.SUMMARIZE_MEMORY: ToolSpec(ToolName.SUMMARIZE_MEMORY, tool_summarize_memory, "Summarize durable memory.", set(), {"query", "limit"}),
        ToolName.SUMMARIZE: ToolSpec(ToolName.SUMMARIZE, tool_summarize, "Summarize text using a simple rule.", {"text"}, {"text"}),
        ToolName.WEB_SEARCH: ToolSpec(ToolName.WEB_SEARCH, make_web_search_tool(web_search_client), "Search the web and return summarized snippets with sources.", {"query"}, {"query", "max_results"}),
        ToolName.FINISH: ToolSpec(ToolName.FINISH, tool_finish, "Finish the task and return final answer.", {"answer"}, {"answer"}),
    }

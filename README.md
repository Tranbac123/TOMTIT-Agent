# TOM TIT

# A State-First Runtime AI Agent

A minimal, extensible AI Agent runtime built around explicit state, validated tool execution, and memory-aware workflows.

This project is an MVP foundation for building a production-ready AI Agent framework with clear separation between planning, runtime execution, tools, memory, and final response composition.

## Overview

The Agent follows a **state-first architecture**:

```text
User Goal
  → AgentState
  → Planner
  → Plan Validator
  → ToolExecutor
  → ToolResult / Observation
  → Final Answer
```

The core idea is simple:

- `AgentState` is the source of truth for each run.
- `Planner` creates a plan but does not execute tools.
- `ToolExecutor` is the only layer that calls tools.
- Tools return structured `ToolResult`.
- Memory starts simple and can later evolve into file, database, or vector-based storage.

## Current Capabilities

The current MVP supports:

- Safe arithmetic calculation
- Writing notes to memory
- Reading notes from memory
- Summarizing note content
- Basic web search through a pluggable search client
- Structured tool results
- Runtime observations and execution history
- Rule-based planning for simple Vietnamese commands
- Placeholder resolution with `$last`, `$last_text`, `$slot.*`, and `${...}` templates

Example supported commands:

```text
Tính (15 + 5) * 3 rồi lưu vào ghi chú
Tính (15 + 5) * 3 nhưng không lưu ghi chú
Đọc ghi chú project rồi tóm tắt
Tìm thông tin về Ducati Monster 795
List thông tin cá nhân của tôi mà bạn biết ra đây
Hãy list những task mà tôi đang làm chưa xong
Lịch trình của tôi hôm nay có gì?
```

## Architecture

### Core Components

| Component          | Responsibility                                                                             |
| ------------------ | ------------------------------------------------------------------------------------------ |
| `AgentState`       | Stores goal, plan, runtime status, memory, observations, sources, errors, and final answer |
| `RuleBasedPlanner` | Converts user goals into executable steps                                                  |
| `Step`             | Represents one planned action                                                              |
| `ToolSpec`         | Defines tool metadata, required args, allowed args, and execution function                 |
| `ToolExecutor`     | Resolves args, validates tool calls, executes tools, and records observations              |
| `ArgResolver`      | Resolves runtime placeholders such as `$last_text` and `${slot.name}`                      |
| `MemoryStore`      | Stores and retrieves agent notes                                                           |
| `ToolResult`       | Standard output contract for every tool                                                    |
| `RuntimeAgent`     | Controls the full lifecycle: plan → validate → execute → finish                            |

## Tools

Current built-in tools:

| Tool         | Description                                   |
| ------------ | --------------------------------------------- |
| `calculate`  | Safely evaluates basic arithmetic expressions |
| `write_note` | Saves content into memory                     |
| `read_note`  | Reads a note from memory                      |
| `summarize`  | Summarizes text using a simple rule           |
| `web_search` | Searches the web through a pluggable client   |
| `finish`     | Ends the run and returns the final answer     |

## Memory

The current memory implementation is intentionally simple:

```text
MemoryStore
  └── notes: dict[str, str]
```

This is enough for MVP learning and testing.

Future memory direction:

```text
MemoryStoreProtocol
  ├── InMemoryStore
  ├── FileMemoryStore
  ├── SQLiteMemoryStore
  ├── VectorMemoryStore
  └── HybridMemoryStore
```

Recommended next memory upgrade:

```text
.agent/
  memory/
    records.jsonl
    index.json
    PROJECT_CONTEXT.md
    DECISIONS.md
    PREFERENCES.md
    LESSONS.md
```

Use `records.jsonl` as the source of truth and Markdown files as human-readable summaries.

## Running the Agent

Run the demo:

```bash
python mini_agent.py
```

Expected behavior:

- Build a tool registry
- Create a `RuntimeAgent`
- Run a sample user goal
- Print the final answer, sources, and execution history

## Running Tests

Run tests with:

```bash
pytest mini_agent.py
```

The current tests cover:

- Placeholder resolution
- Calculation
- Calculation with note saving
- Calculation without note saving when negated
- Reading and summarizing notes
- Fake web search flow

## Design Principles

- Keep runtime state explicit.
- Keep tools small and structured.
- Validate plans before execution.
- Centralize all tool calls in `ToolExecutor`.
- Treat memory as a replaceable layer.
- Prefer simple MVP interfaces before adding databases or vector search.
- Add safety and policy checks before high-risk side-effect tools.
- Keep the architecture easy to refactor into modules.

## Roadmap

Planned improvements:

- Split the single-file MVP into a package structure
- Add `MemoryStoreProtocol`
- Add local file-based memory
- Add `MemoryRecord` schema
- Add `PolicyEngine`
- Add `FinalComposer`
- Add hybrid `RuleBasedPlanner + LLMPlanner`
- Add stronger tool schemas with Pydantic
- Add structured runtime references to replace loose string placeholders
- Add skills/workflows for reusable task patterns
- Add long-term memory extraction after each run

## Suggested Package Structure

```text
agent_core/
  state/
  planning/
  runtime/
  tools/
  memory/
  skills/
  safety/
  output/

tests/
  test_arg_resolver.py
  test_tools.py
  test_memory.py
  test_planner.py
  test_runtime_agent.py
```

## Project Status

This project is currently an MVP learning and architecture prototype.

The goal is not to build a large framework immediately, but to create a clean foundation for a reliable AI Agent with:

- state-first execution
- tool-based action
- memory-aware behavior
- clear runtime lifecycle
- future support for long-term learning

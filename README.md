# TOMTIT-Agent

## A State-First Runtime for Controlled AI Agents

TOMTIT-Agent is a local-first, state-first AI Agent runtime focused on explicit execution state, deterministic planning, validated tool calls, memory-aware workflows, and clear safety boundaries.

It is not a general-purpose chatbot and is not yet a production-ready autonomous co-worker.

The current MVP proves that an Agent can:

- receive a goal;
- retrieve structured memory context;
- create a validated plan;
- execute tools through one controlled gateway;
- track observations and failures;
- use project context to change its final answer;
- disclose when memory is operating in a reduced mode.

---

## Current Status

TOMTIT-Agent has completed its local MVP through P4.

| Phase | Description                                 | Status      |
| ----- | ------------------------------------------- | ----------- |
| P0    | Codebase recovery and import sanity         | Closed      |
| P1    | Memory contracts and `MemoryClientProtocol` | Closed      |
| P2    | `LocalMemoryClient`                         | Closed      |
| P3    | Runtime memory wiring and disclosure        | Closed      |
| P4    | Real `ContextPack` consumer                 | Closed      |
| P5    | TOMTIT-Memory HTTP server                   | Not started |
| P6    | `RemoteMemoryClient` and backend factory    | Not started |

Current test suite:

```text
102 passed
```

Feature development is currently paused for user validation. P5 and P6 are not automatic next steps.

---

## What Has Been Proven

The local MVP has demonstrated the following behavior:

```text
Memory context is retrieved
→ stored in AgentState.context_pack
→ consumed by a real tool
→ changes the final answer
```

The P4 project-context workflow proves that `ANSWER_FROM_CONTEXT` reads from `ContextPack`, not directly from the underlying memory store.

This is a proof of the **memory-consumption path**.

It does not yet prove:

- durable recall after process restart;
- save-then-recall across independent runs;
- semantic relevance retrieval;
- remote or shared memory;
- automatic memory extraction;
- long-term self-improvement.

---

## Architecture

TOMTIT-Agent follows a state-first architecture.

```text
User Goal
  → AgentState
  → Memory Retrieval
  → Intent Parser
  → Slot Validator
  → Intent Planner
  → Plan Validator
  → ToolExecutor
      → Argument Resolution
      → PolicyEngine
      → ApprovalGate
      → Tool Function
      → ToolResult / Observation
  → Finalization
      → FinalComposer
      → Best-effort Memory Write
      → Deterministic Disclosure
      → AgentState.complete()
```

### Core Invariants

- `AgentState` is the source of truth for one task run.
- The planner creates steps but never executes tools.
- `ToolExecutor` is the only layer allowed to call tool functions.
- Tool functions return structured `ToolResult` objects.
- Only `_finalize_run()` may call `AgentState.complete()`.
- `ContextPack` is first-class runtime state.
- Memory degradation and execution safety are separate concerns.
- High-risk and critical-risk tools are denied by policy.
- External or irreversible tools must eventually require explicit approval.

---

## Core Components

| Component               | Responsibility                                               |
| ----------------------- | ------------------------------------------------------------ |
| `AgentState`            | Stores the current truth of a task run                       |
| `RuleBasedIntentParser` | Recognizes a limited set of Vietnamese commands              |
| `SlotValidator`         | Detects missing structured input                             |
| `IntentPlanner`         | Converts parsed intent into `Step` objects                   |
| `PlanValidator`         | Rejects invalid plans before execution                       |
| `ToolExecutor`          | Resolves, validates, authorizes, executes, and records tools |
| `PolicyEngine`          | Applies execution policy before tool invocation              |
| `ApprovalGate`          | Blocks tools that explicitly require user approval           |
| `MemoryClientProtocol`  | Runtime boundary for retrieving and writing memory           |
| `ContextPack`           | Structured memory context for the current task               |
| `FinalComposer`         | Produces the user-facing final result                        |
| `RuntimeAgent`          | Coordinates the complete task lifecycle                      |

---

## Current Capabilities

### 1. Arithmetic

Example:

```text
Tính (15 + 5) * 3
```

Plan:

```text
CALCULATE
→ FINISH
```

---

### 2. Calculate and save a note

Example:

```text
Tính (15 + 5) * 3 rồi lưu vào ghi chú ketqua
```

Plan:

```text
CALCULATE
→ WRITE_NOTE
→ FINISH
```

---

### 3. Write a note

Example:

```text
Ghi ghi chú project Dùng FTS5 cho MVP
```

Plan:

```text
WRITE_NOTE
→ FINISH
```

---

### 4. Read a note

Example:

```text
Đọc ghi chú project
```

Plan:

```text
READ_NOTE
→ FINISH
```

Note lookup currently requires an exact note name.

---

### 5. Read and summarize a note

Example:

```text
Đọc ghi chú project rồi tóm tắt
```

Plan:

```text
READ_NOTE
→ SUMMARIZE
→ FINISH
```

The current summarizer is deterministic and is not powered by an LLM.

---

### 6. Basic web-search workflow

Example:

```text
Tìm thông tin về FastAPI
```

Plan:

```text
WEB_SEARCH
→ FINISH
```

The MVP currently uses a fake or injected search client. This is not production Internet search.

The following flow is recognized by the parser but is not yet supported by the planner:

```text
Tìm thông tin về FastAPI rồi lưu vào ghi chú research
```

This is tracked as technical debt.

---

### 7. Project-context question

Example:

```text
Dự án đã chốt dùng cơ chế search nào cho MVP?
```

Plan:

```text
ANSWER_FROM_CONTEXT
→ FINISH
```

Behavior:

| Matching context   | Result                                                    |
| ------------------ | --------------------------------------------------------- |
| No matching item   | Reports insufficient project context                      |
| Exactly one item   | Uses the item and sets `context_consumed=True`            |
| More than one item | Reports ambiguous context and does not choose arbitrarily |

This workflow is intentionally narrow. It does not yet perform semantic relevance matching.

---

## Unsupported Requests

The current rule-based Agent does not reliably support:

```text
List thông tin cá nhân của tôi
Hãy list những task tôi đang làm
Lịch trình hôm nay của tôi
Phân tích kiến trúc project này
Viết một FastAPI application
Gửi email cho khách hàng
Xóa hoặc sửa file
Chạy shell commands
```

Unsupported goals fall back to a safe `UNKNOWN` plan rather than guessing and executing an unintended action.

---

## Tools

The registry currently contains 13 tool names.

The main active tools include:

| Tool                  | Purpose                                |
| --------------------- | -------------------------------------- |
| `calculate`           | Evaluate basic arithmetic              |
| `write_note`          | Write a note to local memory           |
| `read_note`           | Read a named note                      |
| `list_notes`          | List notes at the tool layer           |
| `save_fact`           | Store a fact                           |
| `save_preference`     | Store a preference                     |
| `save_decision`       | Store a project decision               |
| `search_memory`       | Search the local memory store          |
| `summarize_memory`    | Summarize memory content               |
| `summarize`           | Summarize text deterministically       |
| `web_search`          | Run an injected web-search client      |
| `answer_from_context` | Answer using `AgentState.context_pack` |
| `finish`              | Produce the terminal tool result       |

Not every registered tool is currently reachable from a user command. Some tools exist at the execution layer but do not yet have a corresponding parser and planner path.

---

## Memory Architecture

TOMTIT-Agent currently has two memory access paths.

### Runtime orchestration path

```text
RuntimeAgent
→ MemoryClientProtocol
→ LocalMemoryClient
→ MemoryStoreProtocol
```

This path is used for:

- retrieving a `ContextPack`;
- best-effort memory candidate writing;
- tracking degraded memory mode.

### Compatibility tool path

```text
Built-in memory tool
→ AgentState.memory
→ MemoryStoreProtocol
```

Older built-in tools still access the store directly.

The local composition root injects the same store instance into both paths to prevent split-brain behavior.

TOMTIT-Agent has not yet fully migrated every memory tool to `MemoryClientProtocol`.

### Implementations

- `InMemoryStore`: active local MVP backend.
- `FileStore`: implemented and tested, but not wired into the runtime.
- `LocalMemoryClient`: active memory client.
- TOMTIT-Memory remote service: not integrated.

Because the active backend is in-memory, data is not guaranteed to survive process restart.

---

## Memory Degradation

`LocalMemoryClient` currently operates in degraded mode.

Degraded memory means:

> The available context may be incomplete or have reduced retrieval capability.

It does not mean:

> Tool execution is automatically unsafe.

Disclosure is plan-based. A pure calculation does not display a memory warning merely because the store contains items.

Memory-dependent tasks can append a deterministic disclosure to the final answer.

---

## Safety

All tool calls pass through:

```text
ToolExecutor
→ PolicyEngine
→ ApprovalGate
→ tool function
```

Current policy behavior includes:

- denying `HIGH` risk tools;
- denying `CRITICAL` risk tools;
- denying mutating tools when the Agent is in read-only mode.

`ApprovalGate` is implemented and tested, but no current production tool has:

```python
requires_approval = True
```

The system is not yet production-safe for:

- sending email;
- calendar writes;
- file deletion;
- shell execution;
- irreversible API calls;
- external side effects.

These capabilities require exact-action approval, authorization, audit logging, and stronger execution isolation.

---

## Skills and Extensibility

The repository contains a small skill abstraction and example composite workflows.

However, skills are not yet first-class runtime plugins.

The Agent does not currently support:

- dynamic skill discovery;
- loading skills from external folders or packages;
- `SKILL.md` interpretation;
- a runtime `SkillRegistry`;
- install, enable, disable, or version lifecycle;
- external skill permission manifests.

New capabilities can be added manually through code:

```text
Intent
→ Parser rule
→ Slot validation
→ Plan
→ Tool registry
→ ToolExecutor
→ Tests
```

External plug-and-play skills are not yet supported.

---

## Running the Demo

Requirements:

```text
Python 3.11
```

Run:

```bash
python3.11 main.py
```

The demo currently includes scenarios such as:

- arithmetic;
- calculate and save;
- memory-aware compound execution;
- project-context answering.

---

## Running Tests

Run the full suite:

```bash
pytest -q
```

Expected current result:

```text
102 passed
```

Import sanity check:

```bash
python3.11 -c "import agent_core"
```

---

## Project Structure

```text
agent_core/
├── state/
├── planning/
├── runtime/
├── tools/
├── memory/
├── safety/
├── output/
└── skills/

tests/
docs/
main.py
```

See `docs/` for detailed architecture, phase history, technical debt, and validation plans.

---

## Current Technical Debt

Known issues include:

1. `WEB_SEARCH_THEN_SAVE_NOTE` is parsed but has no planner branch.
2. Project-context parsing can match some declarative sentences incorrectly.
3. `LIST_NOTES` and `SUMMARIZE_MEMORY` are not directly reachable through user intents.
4. Some built-in memory tools still access `AgentState.memory` directly.
5. Durable local and remote memory are not integrated.

---

## Current Direction

The current phase is user validation, not infrastructure expansion.

The main hypothesis is:

> Developers using coding agents across long-running projects experience meaningful pain when the Agent forgets project context and technical decisions.

The next technical step depends on observed user pain:

| Validated need                           | Likely next step                          |
| ---------------------------------------- | ----------------------------------------- |
| Memory across runs in the same process   | Two-run local proof                       |
| Memory after restart on the same machine | Wire `FileStore`                          |
| Shared memory across machines or teams   | Cross-repo contract alignment, then P5/P6 |
| Memory is not a significant pain         | Stop or revise the product wedge          |

Do not start P5, P6, an LLM planner, multi-agent orchestration, vector memory, or an external skill platform without a validated requirement.

---

## Documentation

Recommended reading order:

1. `docs/CURRENT_PROJECT_STATUS.md`
2. `docs/ARCHITECTURE.md`
3. `docs/MVP_MASTER_PLAN.md`
4. `docs/VALIDATION_PLAN.md`
5. `docs/TECH_DEBT.md`
6. `docs/SECURITY_DEBT.md`
7. Active contract specs

Historical phase specifications should not be used as the source of truth for current runtime behavior.

---

## Project Definition

TOMTIT-Agent can currently be described as:

> A deterministic, state-first Agent runtime that executes a limited set of local workflows and has proven one controlled path for consuming structured project memory.

It should not yet be described as:

> A production-ready autonomous co-worker with complete long-term memory.

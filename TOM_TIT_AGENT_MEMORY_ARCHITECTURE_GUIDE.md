# TOM-TIT Agent & Memory Agent Architecture Guide

**Version:** MVP architecture guide 0.1  
**Scope:** TOM-TIT-Agent + TOM-TIT-Memory / Memory & Context Pipeline  
**Architecture style:** state-first, local-first, memory-integrated, production-upgradable

---

## 1. Product Goal

TOM-TIT has two tightly connected systems:

1. **TOM-TIT-Agent**  
   A state-first AI co-worker that can understand user intent, plan tasks, use tools, remember work, execute multi-step flows, and improve over time.

2. **TOM-TIT-Memory / Memory Agent**  
   A local-first memory and context layer that stores durable facts, preferences, decisions, notes, task traces, source context, and later retrieves the right context for the Agent.

The short-term goal is not to build a giant multi-agent platform immediately. The short-term goal is to build a clean local MVP that proves:

```text
User gives task
↓
Agent understands task
↓
Agent builds state
↓
Agent plans steps
↓
Agent validates plan
↓
Agent executes tools safely
↓
Agent writes/reads memory when needed
↓
Agent returns grounded final answer
↓
Agent logs observations for later improvement
```

The long-term goal is to turn the memory layer into an external **Memory & Context Pipeline** that other agents, coding agents, and AI co-workers can call through an API.

---

## 2. Core Design Principles

### 2.1 State-first

`AgentState` is the source of truth. The planner proposes what should happen, but the runtime state records what actually happened.

The Agent should not rely only on raw conversation text. It should maintain structured state:

```text
goal
plan
current_step
done
final_answer
last_result
slots
memory
history
observations
sources
errors
max_steps
```

### 2.2 Planner proposes, Executor executes

The planner should not directly mutate memory or call tools. It should create structured `PlanStep` objects.

```text
Planner = decides what to do
ToolExecutor = performs the action
Policy = decides whether action is allowed
MemoryAgent = stores/retrieves long-term context
FinalComposer = turns state into user-facing answer
```

### 2.3 Tools are reusable primitives

A tool should be small, typed, testable, and side-effect-aware.

Examples:

```text
CALCULATE
WRITE_NOTE
READ_NOTE
LIST_NOTES
SAVE_FACT
SAVE_PREFERENCE
SAVE_DECISION
SEARCH_MEMORY
SUMMARIZE_MEMORY
SUMMARIZE
WEB_SEARCH
FINISH
```

Each tool should have a `ToolSpec`:

```text
name
fn
description
required_args
allowed_args
mutates_state
risk_level
side_effects
requires_approval
timeout_seconds
retry_policy
idempotent
args_schema
```

### 2.4 Skills compose tools

A skill is a reusable workflow that may call one or more tools.

Example:

```text
CalculateAndSaveSkill
ReadAndSummarizeSkill
WebSearchSkill
ResearchScoutSkill later
MemoryIntegratedResearchSkill later
```

Tools are primitives. Skills are recipes. The Agent runtime coordinates skills and tools.

### 2.5 Local-first, cloud-ready later

MVP should run locally first:

```text
TOM-TIT-Agent process
↓ direct Python call
Local MemoryStore
↓
Local files / SQLite / lightweight vector index later
```

Later production version:

```text
TOM-TIT-Agent
↓ HTTP/gRPC/MCP-like protocol
TOM-TIT-Memory service
↓
SQLite/Postgres + vector DB + BM25 + reranker + graph layer
```

Do not split into microservices too early. First make the local architecture correct.

---

## 3. Current Recommended File Structure

Current project root:

```text
TOM_TIT/
├── agent_core/
│   ├── memory/
│   │   ├── base.py
│   │   ├── in_memory_store.py
│   │   ├── memory_agent.py
│   │   └── memory_records.py
│   ├── output/
│   │   └── final_composer.py
│   ├── planning/
│   │   ├── base.py
│   │   ├── hybrid_planner.py
│   │   ├── plan_validator.py
│   │   └── rule_based_planner.py
│   ├── runtime/
│   │   ├── lifecycle.py
│   │   └── runtime_agent.py
│   ├── safety/
│   │   ├── policy.py
│   │   └── risk.py
│   ├── skills/
│   │   ├── base.py
│   │   ├── calculate_and_save_skill.py
│   │   ├── read_and_summarize_skill.py
│   │   └── web_search_skill.py
│   ├── state/
│   │   ├── agent_state.py
│   │   ├── enums.py
│   │   └── observation.py
│   ├── tools/
│   │   ├── arg_resolver.py
│   │   ├── base.py
│   │   ├── builtin_tools.py
│   │   ├── executor.py
│   │   ├── registry.py
│   │   └── schemas.py
│   └── __init__.py
├── tests/
│   ├── test_arg_resolver.py
│   ├── test_memory.py
│   ├── test_planner.py
│   ├── test_runtime_agent.py
│   ├── test_skills.py
│   └── test_tools.py
├── main.py
├── MEMORY.md
├── README.md
└── pytest.ini
```

Recommended docs/instruction folder:

```text
.agent/
└── instructions/
    ├── SYSTEM.md
    ├── MEMORY_POLICY.md
    ├── TOOL_POLICY.md
    └── SAFETY_POLICY.md
```

These `.md` files are soft instructions for human/LLM/code-agent context. Runtime rules must still be enforced in code through schema, policy, validation, and tests.

---

## 4. High-Level Architecture

```text
┌───────────────────────────────────────────────────────────────┐
│                        User / Client                          │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│                       RuntimeAgent                            │
│  - owns lifecycle                                              │
│  - owns AgentState                                             │
│  - loops through planning / validation / execution / output    │
└───────────────┬───────────────────────────────┬───────────────┘
                │                               │
                ▼                               ▼
┌───────────────────────────────┐   ┌───────────────────────────┐
│ Planner Layer                 │   │ Memory Agent               │
│ - RuleBasedPlanner MVP        │   │ - write/read notes         │
│ - HybridPlanner later         │   │ - save facts/preferences   │
│ - LLMPlanner later            │   │ - search memory            │
│ - PlanValidator               │   │ - summarize memory         │
└───────────────┬───────────────┘   └─────────────┬─────────────┘
                │                                 │
                ▼                                 ▼
┌───────────────────────────────┐   ┌───────────────────────────┐
│ Tool System                   │   │ MemoryStore                │
│ - ToolRegistry                │   │ - InMemoryStore MVP        │
│ - ToolSpec                    │   │ - SQLite later             │
│ - ToolExecutor                │   │ - Vector/Hybrid later      │
│ - ArgResolver                 │   │                           │
└───────────────┬───────────────┘   └───────────────────────────┘
                │
                ▼
┌───────────────────────────────┐
│ Safety / Policy Layer         │
│ - risk level                  │
│ - approval gate               │
│ - mutates_state check         │
│ - side effect rules           │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│ FinalComposer                 │
│ - builds final answer          │
│ - uses state/history/sources   │
│ - does not invent actions      │
└───────────────────────────────┘
```

---

## 5. Main Runtime Flow

This is the most important loop.

```text
User input
↓
Create AgentState(goal=user_input, task_id=...)
↓
RuntimeAgent starts lifecycle
↓
Planner creates plan steps
↓
PlanValidator validates plan
↓
RuntimeAgent selects current step
↓
ToolExecutor executes step
↓
ToolResult returned
↓
RuntimeAgent records Observation
↓
RuntimeAgent updates state.last_result / slots / history / sources / errors
↓
If task finished → FinalComposer builds final answer
↓
Return final answer
```

### 5.1 RuntimeAgent responsibility

`RuntimeAgent` should coordinate, not contain all logic.

It should do:

```text
- initialize AgentState
- ask planner for plan
- validate plan
- execute steps one by one
- update state after each step
- stop when done or max_steps reached
- call FinalComposer
```

It should not do:

```text
- manually parse all user intent forever
- directly call memory internals
- directly validate every tool argument
- directly decide all safety rules
```

---

## 6. Planner Flow

### 6.1 Current MVP planner

Current MVP can keep `RuleBasedPlanner`, but it should not keep growing into a giant `if/else` file.

Current flow:

```text
RuleBasedPlanner.make_plan(state)
↓
Read state.goal
↓
Detect simple intent
↓
Create PlanStep[]
↓
Return plan
```

Example:

```text
Goal: "Tính (15 + 5) * 3 rồi lưu vào ghi chú budget"
↓
Plan:
1. CALCULATE(expression="(15 + 5) * 3")
2. WRITE_NOTE(name="budget", content="$last_text")
3. FINISH(answer="Đã tính và lưu kết quả vào ghi chú budget")
```

### 6.2 Better planner design

Refactor target:

```text
IntentParser
↓
ParsedIntent
↓
IntentPlanner
↓
PlanStep[]
↓
PlanValidator
```

Recommended contracts:

```text
ParsedIntent:
- intent_name
- confidence
- source: rule | llm | hybrid
- entities
- missing_fields
- ambiguity
- negations
```

Example:

```text
User: "Tính 1+1 nhưng đừng lưu"
↓
IntentParser detects:
- intent: calculate
- expression: "1+1"
- negation: no_memory_write=True
↓
IntentPlanner creates:
1. CALCULATE(expression="1+1")
2. FINISH(answer="$last_text")
```

### 6.3 Ambiguous input flow

For vague input such as:

```text
"ok"
"làm tiếp đi"
"làm cho tôi cái này"
```

The Agent should not guess blindly.

Recommended flow:

```text
Input is ambiguous
↓
Check current state / previous task
↓
If active task exists → continue safely
↓
If no active task → ask one clarification question
↓
Do not mutate memory or call risky tools
```

---

## 7. PlanValidator Flow

`PlanValidator` protects the runtime before execution.

```text
PlanStep[]
↓
For each step:
    check action exists in ToolRegistry
    check required_args are present
    check unknown args are not present
    check references are syntactically valid
    check risk/approval metadata is consistent
↓
If valid → return ValidPlan
If invalid → return error / safe fallback plan
```

Validation should catch:

```text
- unknown tool name
- missing required args
- unknown args
- invalid arg references
- forbidden mutation when user said no
- plan with no FINISH when task needs final response
```

---

## 8. Tool Execution Flow

This is the flow you gave, expanded into production-ready MVP form.

```text
Planner creates PlanStep
↓
RuntimeAgent passes PlanStep + AgentState to ToolExecutor
↓
ToolExecutor gets ToolSpec from ToolRegistry
↓
Check tool exists
↓
Resolve dynamic args with ArgResolver
↓
Check allowed_args
↓
Check required_args
↓
Validate args with args_schema if available
↓
Policy check
↓
Approval check if required
↓
Apply timeout / retry policy
↓
Execute tool function
↓
Normalize raw output into ToolResult
↓
Record Observation
↓
Return ToolResult to RuntimeAgent
```

### 8.1 ToolSpec should be the control contract

Recommended MVP `ToolSpec`:

```python
@dataclass(frozen=True)
class ToolSpec:
    name: ToolName
    fn: ToolFn
    description: str
    required_args: frozenset[str] | set[str]
    allowed_args: frozenset[str] | set[str]
    mutates_state: bool = False
    risk_level: RiskLevel = RiskLevel.LOW
    side_effects: tuple[str, ...] | list[str] = field(default_factory=tuple)
    requires_approval: bool = False
    timeout_seconds: float | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    idempotent: bool = True
    args_schema: type | None = None
```

For MVP, keep `args_schema`; remove manual `input_schema` and `output_schema` unless you are exposing tools externally.

### 8.2 ToolResult should be normalized

Every tool should return a `ToolResult`.

Recommended shape:

```text
ToolResult:
- ok: bool
- kind: ToolResultKind
- value: Any
- error: str | None
- metadata: dict
- sources: list | None
```

Rules:

```text
- Tool should not raise normal business errors upward if it can return ToolResult(ok=False)
- Unexpected exceptions should be caught by ToolExecutor
- Every failed tool should produce an Observation
- Every source-bearing tool should attach sources
```

---

## 9. ArgResolver Flow

`ArgResolver` lets a later step use output from previous steps.

Current useful patterns:

```text
$last
$last_text
$last.output.value
$slot.calc_result
${slot.calc_result}
```

Flow:

```text
Raw step args
↓
For each arg value:
    if literal → keep literal
    if runtime reference → resolve from AgentState
    if missing reference → return validation/execution error
↓
Resolved args
↓
ToolExecutor validates and executes
```

MVP rule:

```text
Keep $last_text for now.
Later replace loose string refs with RuntimeRef objects.
```

Future production version:

```python
RuntimeRef(source="last_result", field="value", as_text=True)
```

This is safer and easier to type-check than loose strings.

---

## 10. Memory Agent Architecture

### 10.1 Memory Agent role

The Memory Agent is not just a vector database wrapper. It is the layer that decides what should be remembered, how it should be stored, and how it should be retrieved.

```text
MemoryAgent:
- write_note
- read_note
- list_notes
- save_fact
- save_preference
- save_decision
- search_memory
- summarize_memory
- later: detect duplicates
- later: detect conflicts
- later: extract durable lessons
- later: build context packs
```

### 10.2 MemoryStore role

`MemoryStore` is storage abstraction. It should not decide product logic.

```text
MemoryAgent = memory logic
MemoryStore = persistence backend
Retriever = search/retrieval strategy
ContextPackBuilder = context assembly for Agent
```

Recommended protocol:

```python
class MemoryStoreProtocol(Protocol):
    def write(self, record: MemoryRecord) -> None: ...
    def search(self, query: MemoryQuery) -> list[MemoryRecord]: ...
    def get(self, memory_id: str) -> MemoryRecord | None: ...
    def write_note(self, name: str, content: str) -> None: ...
    def read_note(self, name: str) -> str | None: ...
    def list_notes(self) -> list[str]: ...
    def delete(self, memory_id: str) -> bool: ...
```

### 10.3 Memory types

MVP should support:

```text
Note memory        = user-named notes, easy to debug
Fact memory        = durable facts worth remembering
Preference memory  = user preferences
Decision memory    = architecture/product decisions
Source memory      = source links or research evidence later
Task trace memory  = what the agent tried and whether it worked later
```

Do not overbuild episodic/semantic/procedural memory yet. Model them later after the basic records are stable.

---

## 11. Memory Write Flow

Example: user asks Agent to remember something.

```text
User: "Nhớ rằng project của tôi dùng state-first architecture"
↓
RuntimeAgent creates AgentState
↓
Planner detects memory write intent
↓
Plan:
1. SAVE_FACT(content="Project uses state-first architecture", tags=["architecture"])
2. FINISH(answer="Đã lưu thông tin này")
↓
PlanValidator validates SAVE_FACT args
↓
ToolExecutor gets SAVE_FACT ToolSpec
↓
Check required_args / allowed_args
↓
Policy check: mutates_state=True, side_effects=["memory_write"]
↓
Approval check if policy requires it
↓
Execute tool_save_fact
↓
MemoryAgent.save_fact
↓
MemoryStore.write(MemoryRecord)
↓
ToolResult(ok=True)
↓
RuntimeAgent records Observation
↓
FinalComposer returns answer
```

### 11.1 Memory write policy

Memory write should be allowed when:

```text
- user explicitly asks to remember/save/note/store
- memory is clearly useful for future project work
- content is not unsafe or forbidden by policy
```

Memory write should be blocked or clarified when:

```text
- user did not ask to remember and the info is trivial
- content is sensitive and user did not explicitly request saving
- extracted memory is uncertain
- task intent says "do not save" or "đừng lưu"
```

---

## 12. Memory Read / Retrieval Flow

Example: user asks something that benefits from previous context.

```text
User asks project-specific question
↓
RuntimeAgent detects memory may help
↓
Planner creates SEARCH_MEMORY or READ_NOTE step
↓
ToolExecutor validates and executes memory search
↓
MemoryAgent.search_memory(query, limit)
↓
MemoryStore.search(query)
↓
Return relevant MemoryRecord[]
↓
Context is inserted into AgentState.memory / observations
↓
Planner or FinalComposer uses retrieved memory
↓
Answer is grounded in retrieved project context
```

### 12.1 Retrieval layers by maturity

MVP:

```text
InMemoryStore
↓
keyword/simple search
↓
small result list
```

Next local version:

```text
SQLiteMemoryStore
↓
BM25 or simple full-text search
↓
optional local embeddings
```

Advanced local/cloud version:

```text
HybridMemoryStore
↓
BM25 + vector search + reranker
↓
context pack builder
↓
citation/source tracking
```

Later research version:

```text
Graph memory
↓
entity/relation extraction
↓
conflict detection
↓
memory validator
↓
self-improvement loop
```

---

## 13. RAG / Context Pipeline Flow

RAG should live inside the Memory/Context layer, not directly inside every Agent component.

MVP local RAG:

```text
Document / note / source
↓
Ingest
↓
Clean text
↓
Chunk
↓
Store chunks
↓
Retrieve chunks by query
↓
Rerank later
↓
Build context pack
↓
Pass context pack to Agent
```

Recommended boundary:

```text
Agent asks: "Give me relevant context for this task"
Memory Pipeline returns: ContextPack
```

`ContextPack` should include:

```text
- relevant memories
- relevant notes
- relevant decisions
- relevant source snippets
- confidence
- timestamps
- why this context was selected
- source ids
```

The Agent should not know whether the Memory Pipeline used BM25, vector search, reranking, graph search, or a hybrid method.

---

## 14. Skill Flow

Skills are higher-level routines that compose tools.

Example: `CalculateAndSaveSkill`

```text
Skill receives state/input
↓
Extract expression and note name
↓
Create internal plan or call tools directly through ToolExecutor
↓
CALCULATE
↓
WRITE_NOTE
↓
FINISH
↓
Return skill result
```

Recommended rule:

```text
For MVP, RuntimeAgent can execute PlanStep directly.
For repeated multi-step patterns, extract them into Skill classes.
```

Skill should not bypass policy if it calls tools. A skill must still use the same tool execution path.

```text
Skill
↓
ToolExecutor
↓
ToolRegistry / ToolSpec
↓
Policy
↓
Tool
```

---

## 15. Safety and Policy Flow

Safety is not just prompt instructions. It must be runtime-enforced.

```text
PlanStep
↓
ToolSpec metadata
↓
Risk classification
↓
PolicyEngine check
↓
ApprovalGate if required
↓
Execute or block
```

Policy should use:

```text
- risk_level
- mutates_state
- side_effects
- requires_approval
- idempotent
- user intent
- current state
- tenant/user permissions later
```

MVP examples:

```text
READ_NOTE       → allowed by default
SEARCH_MEMORY   → allowed by default
WRITE_NOTE      → allowed if user asked to write/save or active task requires it
SAVE_FACT       → allowed if user asked to remember or strong future usefulness
WEB_SEARCH      → allowed if task requires external info
SEND_EMAIL      → future: requires explicit approval
PAYMENT         → future: always requires explicit approval
```

---

## 16. Tool Retry, Timeout, and Idempotency

Retries are dangerous for side-effect tools.

Recommended rule:

```text
If tool is not idempotent, max_attempts must be 1 unless idempotency key exists.
```

Examples:

```text
CALCULATE       idempotent=True
READ_NOTE       idempotent=True
SEARCH_MEMORY   idempotent=True
WEB_SEARCH      idempotent=True enough for MVP
WRITE_NOTE      depends on overwrite vs append
SAVE_FACT       idempotent=False unless dedupe exists
SEND_EMAIL      idempotent=False
PAYMENT         idempotent=False
```

Execution rule:

```text
ToolExecutor
↓
If timeout_seconds configured → execute with timeout
↓
If retry_policy.max_attempts > 1 → retry only when safe
↓
If non-idempotent and no idempotency key → no retry
```

---

## 17. Observation and Trace Flow

Every step should produce an observation.

```text
Observation:
- step_id
- tool_name
- input_args
- result_kind
- ok
- error
- sources
- latency_ms later
- risk_level
- side_effects
- timestamp
```

Why observations matter:

```text
- debugging
- replay
- evaluation
- self-improvement
- memory extraction
- audit log later
```

Future self-improvement flow:

```text
Task trace
↓
Reflection / Critic
↓
Extract lesson
↓
MemoryValidator checks if useful
↓
Save lesson to memory
↓
Planner retrieves lesson for similar task later
```

Do not implement heavy reflection too early. First make trace logging clean.

---

## 18. Final Answer Flow

`FinalComposer` should produce the final user-facing answer from state.

```text
AgentState
↓
Check final_answer from FINISH step
↓
Check last_result / errors / sources
↓
Compose response
↓
Return to user
```

Rules:

```text
- Do not claim a tool succeeded if ToolResult.ok=False
- Mention errors clearly when execution failed
- Include source summary when web/search tools were used
- Use memory context only if retrieved
- Do not invent memory writes
```

---

## 19. End-to-End Example Flows

### 19.1 Calculate and save note

```text
User: "Tính (15 + 5) * 3 rồi lưu vào ghi chú budget"
↓
RuntimeAgent creates AgentState
↓
Planner creates plan:
    1. CALCULATE(expression="(15 + 5) * 3")
    2. WRITE_NOTE(name="budget", content="$last_text")
    3. FINISH(answer="Đã tính và lưu vào ghi chú budget")
↓
PlanValidator checks tool names and args
↓
ToolExecutor executes CALCULATE
↓
ToolResult(value=60)
↓
RuntimeAgent updates last_result and slot
↓
ToolExecutor resolves "$last_text" → "60"
↓
ToolExecutor executes WRITE_NOTE
↓
MemoryAgent writes note
↓
ToolExecutor executes FINISH
↓
FinalComposer returns answer
```

### 19.2 Read and summarize note

```text
User: "Đọc ghi chú budget và tóm tắt cho tôi"
↓
Planner:
    1. READ_NOTE(name="budget")
    2. SUMMARIZE(text="$last_text")
    3. FINISH(answer="$last_text")
↓
Executor reads note
↓
Executor summarizes
↓
FinalComposer returns summary
```

### 19.3 Web search with sources

```text
User: "Tìm thông tin mới nhất về X"
↓
Planner:
    1. WEB_SEARCH(query="X", max_results=5)
    2. FINISH(answer="$last_text")
↓
ToolExecutor executes WEB_SEARCH
↓
ToolResult contains snippets + sources
↓
RuntimeAgent stores sources in state.sources
↓
FinalComposer returns answer with sources
```

### 19.4 Memory-informed project answer

```text
User: "Theo kiến trúc Agent của tôi thì bước tiếp theo nên làm gì?"
↓
RuntimeAgent detects project-specific question
↓
Planner:
    1. SEARCH_MEMORY(query="TOM-TIT Agent architecture next step", limit=5)
    2. FINISH(answer="...")
↓
MemoryAgent returns relevant records:
    - state-first architecture
    - ToolExecutor needs validation
    - MemoryStore should stay local-first
↓
FinalComposer answers based on memory context
```

---

## 20. Local MVP Build Order

Build in this order:

### Phase 1 — Runtime correctness

```text
1. AgentState stable
2. PlanStep stable
3. ToolSpec stable
4. ToolResult stable
5. ToolRegistry stable
6. ToolExecutor validates args and executes tools
7. RuntimeAgent loop stable
8. FinalComposer stable
```

### Phase 2 — Planner cleanup

```text
1. Extract IntentParser
2. Create ParsedIntent
3. Create IntentPlanner
4. Keep RuleBasedPlanner as deterministic backend
5. Add PlanValidator tests
6. Add ambiguous-input handling
```

### Phase 3 — Memory MVP

```text
1. MemoryRecord and MemoryQuery stable
2. MemoryStoreProtocol stable
3. InMemoryStore stable
4. MemoryAgent methods stable
5. SAVE_FACT / SAVE_PREFERENCE / SAVE_DECISION tools stable
6. SEARCH_MEMORY and SUMMARIZE_MEMORY stable
```

### Phase 4 — Lightweight local retrieval

```text
1. Add SQLiteMemoryStore
2. Add simple full-text search / BM25
3. Add chunk records for documents
4. Add ContextPackBuilder
5. Add retrieval evaluation tests
```

### Phase 5 — Production hardening later

```text
1. HTTP API for Memory service
2. Postgres/pgvector or hybrid vector store
3. Reranker
4. Source/citation tracking
5. Audit log
6. Multi-tenant isolation
7. Observability
8. Evaluation harness
```

---

## 21. Future Platform Architecture

When local MVP is stable, TOM-TIT can evolve into a larger service architecture:

```text
Frontend / Client
↓
API Gateway
↓
Orchestrator / Runtime Agent
↓
Router / Model Gateway
↓
Tool Service / Skill Service
↓
Memory & Context Pipeline
↓
Storage: Postgres + Redis + Vector DB + Object Store
↓
Observability: logs + metrics + traces + eval replay
```

Production services later:

```text
api-gateway
orchestrator
router-service / model-gateway
memory-service
retrieval-service
ingestion-service
tools-service
realtime-service
analytics-service
billing-service later
control-plane later
```

But for the current MVP, keep the core inside `agent_core/` and avoid premature microservice splitting.

---

## 22. What Not To Build Too Early

Do not build these too early:

```text
- full graph database memory
- multi-agent debate system
- complex self-training loop
- payment/booking side-effect tools
- enterprise billing
- Kubernetes deployment
- separate cloud memory service
- heavy vector DB infra
- complex YAML workflow engine for every small MVP task
```

Build these first:

```text
- clean AgentState
- clean ToolSpec
- clean ToolExecutor
- clean MemoryAgent
- clean MemoryStoreProtocol
- clean runtime observations
- clean planner decomposition
- tests for every runtime path
```

---

## 23. Testing Strategy

Minimum tests:

```text
test_tools.py
- tool returns ToolResult
- invalid input returns error
- memory-write tools mutate expected store

test_arg_resolver.py
- resolves $last_text
- resolves slot refs
- fails cleanly for missing refs

test_planner.py
- calculate only
- calculate + save
- no-save negation
- read note
- summarize
- web search
- ambiguous input

test_runtime_agent.py
- full run success
- max_steps stop
- tool failure handled
- final answer generated

test_memory.py
- write/read note
- save/search fact
- save/search preference
- save/search decision

test_skills.py
- skill uses ToolExecutor path
- skill does not bypass policy
```

Later eval tests:

```text
- golden tasks
- episode replay
- planner misroute rate
- memory retrieval precision
- context pack usefulness
- hallucination/error rate
```

---

## 24. Recommended Next Code Changes

### 24.1 `agent_core/tools/base.py`

Keep MVP `ToolSpec` lean:

```text
Remove:
- input_schema
- output_schema

Keep:
- args_schema
```

Reason:

```text
args_schema validates runtime input.
input_schema/output_schema are mainly useful when exporting tools externally.
```

### 24.2 `agent_core/tools/executor.py`

Implement the full execution contract:

```text
get ToolSpec
resolve args
check allowed_args
check required_args
validate args_schema
policy check
approval check
timeout/retry
execute
return ToolResult
record observation
```

### 24.3 `agent_core/planning/rule_based_planner.py`

Start extracting:

```text
IntentParser
ParsedIntent
IntentPlanner
```

Do not let `RuleBasedPlanner.make_plan()` become the entire Agent brain.

### 24.4 `agent_core/memory/`

Keep memory local-first:

```text
MemoryStoreProtocol
InMemoryStore
MemoryAgent
MemoryRecord
MemoryQuery
```

Add SQLite only when in-memory becomes limiting.

---

## 25. Summary Mental Model

The whole system should be remembered like this:

```text
User gives goal
↓
RuntimeAgent creates AgentState
↓
ContextBuilder / MemoryAgent retrieves useful context when needed
↓
Planner creates structured PlanStep[]
↓
PlanValidator checks the plan
↓
ToolExecutor executes each step through ToolRegistry
↓
PolicyEngine blocks unsafe or unauthorized actions
↓
Tools return ToolResult
↓
RuntimeAgent records Observation and updates AgentState
↓
MemoryAgent stores durable facts/decisions/preferences when appropriate
↓
FinalComposer returns answer
↓
Trace can later be used for evaluation and self-improvement
```

The clean separation is:

```text
State = what is true now
Planner = what should happen next
Validator = whether the plan is structurally valid
Policy = whether the action is allowed
Executor = how the action is performed
Tool = the primitive capability
Skill = reusable workflow using tools
MemoryAgent = what to remember and retrieve
MemoryStore = where memory is stored
FinalComposer = how to answer the user
Observation = what actually happened
```

This architecture is small enough for MVP but strong enough to grow into a production AI co-worker platform with external memory, retrieval, evaluation, and self-improvement.

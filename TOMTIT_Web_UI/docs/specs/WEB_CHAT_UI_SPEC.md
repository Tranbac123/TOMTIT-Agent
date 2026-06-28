# WEB_CHAT_UI_SPEC.md

Repository Decision: Web UI lives inside TOMTIT-Agent repo for this phase; do not create a separate TOMTIT-WEBUI repo.

Status: Active
Version: 1.0.0
Scope: TOMTIT-Agent Web UI + HTTP API Adapter
Owner: Human / TOMTIT-Agent project

## 0. Instruction Priority

This spec must be read together with:

```text
CLAUDE.md
.claude/rules/01-tomtit-architecture-contract.md
.claude/rules/02-current-task-web-chat-ui.md
.claude/rules/03-runtime-adapter-contract.md
.claude/rules/04-scope-guard.md
.claude/rules/05-testing-verification-gate.md
```

If this file conflicts with higher-priority rule files, stop and report the conflict.

Priority order:

```text
1. Human latest explicit instruction
2. CLAUDE.md
3. .claude/rules/*.md
4. This spec
5. Existing repo conventions
```

Do not guess when architecture safety is affected.

---

## 1. Goal

Build a local developer web interface for TOMTIT-Agent.

The web must provide:

```text
ChatGPT-like interaction layout
TomTit branding
HTTP API adapter over existing TOMTIT-Agent runtime
basic session/conversation management
memory recall UI/API
provenance/source display
safe loading and error states
tests
documentation
verification report
```

The web app must be a real UI over TOMTIT-Agent runtime.

It must not become:

```text
a fake chatbot
a standalone demo
a second agent runtime
a second memory system
a planner implementation
a retrieval implementation
```

---

## 2. Current Baseline Context

Current TOMTIT-Agent phase context:

```text
M7-A: CLOSED
M7-B: CLOSED
M7-B closeout: CLOSED ON origin/main
```

Current capability already proven before this task:

```text
confirmed decision write
→ durable memory write
→ fresh session/process recall
→ provenance preserved
→ recall works after TOMTIT-Memory restart
```

This task does not reopen M7.

This task does not start SF2.

This task does not start M8.

This task only exposes existing TOMTIT-Agent capability through a browser UI and HTTP API adapter.

---

## 3. Non-Goals

Do not implement:

```text
SF2
M8
vector search
vector DB
Qdrant
embeddings
semantic retrieval
hybrid retrieval
RAG rewrite
LLMPlanner production mode
self-improvement loop
training loop
TOMTIT-Memory edits
Memory Contract edits
core runtime refactor
production authentication
multi-tenant SaaS billing
production deployment hardening
Kubernetes
distributed job queue
monitoring stack
marketplace
plugin store
mobile app
desktop app
```

If any of these are required to finish the task, stop and report:

```text
WEB CHAT UI: BLOCKED
Reason: <specific blocker>
```

---

## 4. Required Architecture

Required flow:

```text
Browser
→ TOMTIT-Agent Web API
→ existing SessionRuntime / RuntimeAgent
→ existing memory client
→ TOMTIT-Memory
```

Rules:

```text
Frontend must not call TOMTIT-Memory directly.
Frontend must not call LLM provider APIs directly.
Frontend must not call tool execution APIs directly.
Backend API must not bypass TOMTIT-Agent runtime.
Backend API must not call tools directly from route handlers.
Backend API must not reimplement memory retrieval.
Backend API must not create a new planner.
Backend API must not fabricate provenance.
```

AgentState remains the runtime source of truth.

Web session state is display/session metadata only.

---

## 5. Approved Product Design Direction

Approved UI direction:

```text
Dark modern app UI
ChatGPT-like sidebar + chat interaction structure
TomTit visible top-left brand
TomTit wordmark in red-orange
Small stylized mantis-shrimp-inspired logo beside wordmark
Logo should be horizontal side-profile, simple, unique, compact
Sidebar shows TOMTIT features instead of ChatGPT features
```

Do not copy:

```text
ChatGPT logo
OpenAI logo
OpenAI proprietary icons
OpenAI brand assets
ChatGPT-specific names
proprietary sidebar graphics
```

Use the reference only as broad UX inspiration.

The final UI must visibly be TomTit.

---

## 6. Required Sidebar

Top-level sidebar items:

```text
New chat
Search
Memory
Skills
Projects
Sessions
Provenance
More
```

Pinned seed items:

```text
Build TOMTIT web UI
Kiến trúc TOMTIT-Agent
Kiến trúc TOMTIT-Memory
Kiến trúc TOMTIT-Memory 2
AI tự tiến hoá
```

Pinned items are display seeds only.

Do not treat these as durable backend data unless explicitly implemented as session metadata.

---

## 7. Preferred Stack

Use existing repo convention first.

If no convention exists, use:

```text
Frontend: React + TypeScript + Vite
Styling: plain CSS or CSS Modules
Backend: FastAPI + Pydantic + Uvicorn
Transport: REST JSON first
Session MVP: backend in-memory store + browser localStorage
Testing: pytest for backend, npm build/typecheck for frontend
```

Do not add unless explicitly required:

```text
Next.js
GraphQL
WebSocket-first architecture
Postgres session persistence
Redis session persistence
large UI framework
production auth framework
billing/payment framework
vector/embedding dependencies
deployment/monitoring stack
```

---

## 8. Repository Structure

Inspect the repo before creating files.

If repo already has canonical frontend/backend locations, use them.

If no convention exists, preferred frontend structure:

```text
web/
  package.json
  index.html
  src/
    main.tsx
    App.tsx
    api/
      client.ts
      types.ts
    components/
      ChatLayout.tsx
      Sidebar.tsx
      ConversationList.tsx
      ChatWindow.tsx
      MessageBubble.tsx
      Composer.tsx
      MemoryRecallPanel.tsx
      ProvenancePanel.tsx
      SettingsPanel.tsx
      LoadingIndicator.tsx
      ErrorBanner.tsx
    styles/
      globals.css
```

If no convention exists and `agent_core/` is canonical, preferred backend structure:

```text
agent_core/
  web_api/
    __init__.py
    app.py
    models.py
    routes.py
    session_manager.py
    runtime_adapter.py
    errors.py
    stores.py
```

Do not create parallel app structures if the repo already has a canonical API or frontend app.

If the actual repo structure conflicts with this spec, stop and report:

```text
BLOCKED: repository structure mismatch

Observed structure:
- ...

Conflicting instruction:
- ...

Recommended narrow path:
- ...
```

---

## 9. Backend API Requirements

### 9.1 Health

```http
GET /api/health
```

Response:

```json
{
  "ok": true,
  "service": "tomtit-agent-web-api",
  "version": "dev"
}
```

---

### 9.2 Create Session

```http
POST /api/sessions
```

Request:

```json
{
  "user_id": "local-user",
  "project_id": "local-project",
  "title": "Optional title"
}
```

Response:

```json
{
  "session_id": "uuid",
  "user_id": "local-user",
  "project_id": "local-project",
  "title": "Optional title",
  "created_at": "iso timestamp",
  "updated_at": "iso timestamp"
}
```

---

### 9.3 List Sessions

```http
GET /api/sessions
```

Response:

```json
{
  "sessions": [
    {
      "session_id": "uuid",
      "user_id": "local-user",
      "project_id": "local-project",
      "title": "Conversation title",
      "created_at": "iso timestamp",
      "updated_at": "iso timestamp"
    }
  ]
}
```

MVP storage may be in-memory.

Do not add database persistence unless existing repo convention requires it.

---

### 9.4 Get Session Messages

```http
GET /api/sessions/{session_id}/messages
```

Response:

```json
{
  "session_id": "uuid",
  "messages": [
    {
      "id": "uuid",
      "role": "user",
      "content": "text",
      "created_at": "iso timestamp"
    },
    {
      "id": "uuid",
      "role": "assistant",
      "content": "Agent answer",
      "created_at": "iso timestamp",
      "provenance": [],
      "sources": []
    }
  ]
}
```

---

### 9.5 Send Chat Message

```http
POST /api/chat
```

Request:

```json
{
  "session_id": "uuid",
  "message": "User message",
  "user_id": "local-user",
  "project_id": "local-project"
}
```

Response:

```json
{
  "session_id": "uuid",
  "assistant_message": {
    "id": "uuid",
    "role": "assistant",
    "content": "Agent answer",
    "created_at": "iso timestamp",
    "provenance": [],
    "sources": [],
    "status": "completed"
  }
}
```

Required behavior:

```text
Reject blank message.
Pass session_id explicitly.
Pass user_id explicitly.
Pass project_id explicitly.
Call RuntimeAdapter.
RuntimeAdapter must call existing TOMTIT-Agent runtime.
Do not return static demo response.
Do not expose raw Python stack trace.
```

---

### 9.6 Memory Recall

```http
POST /api/memory/recall
```

Request:

```json
{
  "session_id": "uuid",
  "query": "decision about database",
  "user_id": "local-user",
  "project_id": "local-project"
}
```

Response:

```json
{
  "session_id": "uuid",
  "result": {
    "content": "Recall output",
    "status": "completed",
    "provenance": [
      {
        "memory_id": "mem_xxx",
        "evidence_ref": "user-explicit:...",
        "source_task_id": "task_id"
      }
    ],
    "sources": []
  }
}
```

Required behavior:

```text
Reject blank query.
Call RuntimeAdapter.recall_memory.
RuntimeAdapter must use existing runtime/session memory recall path if available.
Do not reimplement retrieval.
Do not add vector search.
Do not call TOMTIT-Memory directly from frontend.
Handle no-result safely.
Handle remote failure safely.
Do not fabricate provenance.
```

---

### 9.7 Optional Streaming

Streaming is optional.

Default MVP:

```text
POST /api/chat returns non-streaming JSON
```

If streaming is implemented later:

```text
POST /api/chat/stream with fetch ReadableStream
```

or:

```text
GET /api/chat/stream with native EventSource
```

Do not implement native EventSource over POST.

Do not fake token streaming if runtime does not support it.

---

## 10. Runtime Adapter Requirements

Before coding backend routes, inspect the existing CLI/runtime entrypoint.

Document in final report:

```text
CLI entrypoint inspected:
runtime module path:
runtime class/function:
chat invocation method:
memory recall method:
input object/schema:
output object/schema:
sync or async:
required config/env:
user_id handling:
project_id handling:
session_id handling:
provenance field/source:
known limitations:
```

Recommended adapter interface:

```python
class RuntimeAdapter:
    async def send_chat(
        self,
        *,
        session_id: str,
        user_id: str,
        project_id: str,
        message: str,
    ) -> RuntimeChatResult:
        ...

    async def recall_memory(
        self,
        *,
        session_id: str,
        user_id: str,
        project_id: str,
        query: str,
    ) -> RuntimeRecallResult:
        ...
```

Recommended route flow:

```text
routes.py
→ session_manager.py
→ runtime_adapter.py
→ existing SessionRuntime / RuntimeAgent
```

Forbidden route flow:

```text
routes.py
→ hardcoded assistant string

routes.py
→ direct tool call

routes.py
→ direct TOMTIT-Memory retrieval

routes.py
→ new planner
```

---

## 11. Session Management

Create a thin `AgentSessionManager` or equivalent.

Responsibilities:

```text
create session
store session metadata
store display transcript cache for MVP
get session messages
call RuntimeAdapter for chat
call RuntimeAdapter for memory recall
append normalized user/assistant messages
return normalized API responses
```

MVP storage:

```text
in-memory Python dict is acceptable
```

Design should allow future replacement with:

```text
SessionStore interface
InMemorySessionStore
future SQLiteSessionStore
future PostgresSessionStore
```

Do not implement future stores now.

---

## 12. Frontend Requirements

Required layout:

```text
Left sidebar:
- TomTit brand
- stylized mantis-shrimp logo
- New chat
- Search
- Memory
- Skills
- Projects
- Sessions
- Provenance
- More
- Pinned list

Main area:
- current conversation title/status
- scrollable message list
- composer at bottom

Optional/right area:
- memory recall panel
- provenance/source details
- settings/debug panel in dev mode
```

Required message features:

```text
user messages
assistant messages
loading state
safe error state
copy button optional
markdown rendering optional
```

Required composer behavior:

```text
multiline input
Enter sends message
Shift+Enter inserts newline
disabled while sending
safe empty-message handling
```

Required settings:

```text
user_id
project_id
backend API base URL
selected session_id
```

Settings should persist in localStorage.

Do not store secrets in localStorage.

---

## 13. Memory Recall UI

Implement at least one:

```text
Option A: /memory recall command in chat input
Option B: side panel with recall query input
```

Preferred if simple:

```text
Support both.
```

Recall result display must show:

```text
content
status
memory_id if available
evidence_ref if available
source_task_id if available
sources if available
safe no-result state
safe failure state
```

Do not fabricate recall results.

---

## 14. Provenance / Source Display

Display provenance only when returned by backend.

Allowed:

```text
show empty provenance state
show “No provenance returned”
show memory_id/evidence_ref/source_task_id when present
normalize display labels
```

Forbidden:

```text
invent memory_id
invent evidence_ref
invent source_task_id
invent source documents
invent confidence claims
```

---

## 15. Local Settings

Allowed localStorage fields:

```text
user_id
project_id
backend_api_base_url
selected_session_id
theme
sidebar_collapsed
```

Forbidden localStorage fields:

```text
provider API keys
memory backend credentials
raw runtime internal state
authoritative memory records
confirmed decisions
retrieval index
```

---

## 16. Error Handling

Backend safe error response should prefer:

```json
{
  "status": "error",
  "error_code": "SAFE_ERROR_CODE",
  "message": "Safe user-facing message",
  "request_id": "optional",
  "session_id": "optional"
}
```

Do not expose:

```text
Python stack traces
raw exception repr
environment variables
API keys
memory backend credentials
internal absolute paths unless safe and needed for local diagnostics
```

Frontend must display safe errors without crashing.

No broken blank screens.

---

## 17. Observability Minimum

Where practical, include:

```text
request_id
session_id
user_id
project_id
run_id if runtime provides it
status
error_code
```

Do not add a monitoring stack.

Do not add OpenTelemetry/Prometheus/Grafana for this task unless the repo already requires it.

---

## 18. Dependency Rules

Do not modify dependency files unless necessary.

Allowed dependency files:

```text
requirements.txt
pyproject.toml
package.json
package-lock.json
pnpm-lock.yaml
yarn.lock
```

Before adding a dependency:

```text
check existing stack
prefer existing dependency
avoid unrelated upgrades
document why the dependency is needed
```

Forbidden dependency additions:

```text
Qdrant client
embedding libraries
vector DB clients
new LLM orchestration framework
production auth framework
billing/payment libraries
monitoring stack
Kubernetes/deployment tooling
```

---

## 19. Required Tests

Backend tests must cover:

```text
GET /api/health returns ok
POST /api/sessions creates session
GET /api/sessions lists sessions
GET /api/sessions/{session_id}/messages returns messages
POST /api/chat rejects blank message
POST /api/chat calls RuntimeAdapter.send_chat
POST /api/chat passes session_id/user_id/project_id/message correctly
POST /api/chat returns normalized assistant message
POST /api/chat maps runtime exception to safe API error
POST /api/chat does not expose raw stack trace
POST /api/memory/recall rejects blank query
POST /api/memory/recall calls RuntimeAdapter.recall_memory
POST /api/memory/recall passes session_id/user_id/project_id/query correctly
POST /api/memory/recall returns normalized recall result
POST /api/memory/recall maps runtime exception to safe API error
POST /api/memory/recall does not expose raw stack trace
```

Tests may mock RuntimeAdapter boundary.

But route-level mocks alone do not prove WEB-06.

WEB-06 requires evidence that production adapter calls existing TOMTIT-Agent runtime path.

---

## 20. Required Commands

Python import check:

```bash
python -c "import agent_core; print('import_ok')"
```

Backend tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider -q
```

Frontend build:

```bash
cd web
npm install
npm run build
```

If configured, also run:

```bash
npm run typecheck
npm run lint
npm test
```

Final hygiene:

```bash
git diff --check
git status --short --untracked-files=all
```

If a command cannot run, mark it:

```text
UNVERIFIED
Reason: <specific reason>
```

Do not mark PASS without evidence.

---

## 21. Dev Run Commands

Document actual commands after implementation.

Expected backend command if using FastAPI:

```bash
uvicorn agent_core.web_api.app:app --reload --port 8000
```

or:

```bash
python -m agent_core.web_api.app
```

Expected frontend command:

```bash
cd web
npm install
npm run dev
```

Expected local URLs:

```text
Frontend: http://localhost:5173
Backend:  http://localhost:8000
```

Document actual env vars.

Expected env vars if applicable:

```text
TOMTIT_MEMORY_BASE_URL
TOMTIT_PROJECT_ID
TOMTIT_USER_ID
```

If the repo uses different names, inspect and document actual names.

---

## 22. Documentation Requirements

Update README with a short Web Chat UI section:

```text
Web Chat UI
- what it is
- how to run backend
- how to run frontend
- how to configure user_id/project_id
- current limitations
```

Do not rewrite unrelated README sections.

Create or update:

```text
docs/reports/REPORT_WEB_CHAT_UI_VERIFIED.md
```

Do not commit the report unless explicitly instructed.

---

## 23. Acceptance Criteria

Evaluate every criterion in the final report.

```text
WEB-01 frontend app exists and builds
WEB-02 backend API starts locally
WEB-03 /api/health works
WEB-04 session create/list works
WEB-05 chat message can be sent from frontend to backend
WEB-06 backend calls TOMTIT-Agent runtime, not mock-only path
WEB-07 assistant response displays in UI
WEB-08 memory recall works from UI or recall panel
WEB-09 provenance is displayed when returned
WEB-10 no-result and failure are safe
WEB-11 raw stack traces are not exposed
WEB-12 project_id/user_id are configurable
WEB-13 session_id persists per conversation
WEB-14 frontend does not call TOMTIT-Memory directly
WEB-15 no TOMTIT-Memory code changes
WEB-16 no vector/M8/SF2/self-improvement work
WEB-17 backend tests pass
WEB-18 full Python regression passes
WEB-19 frontend build passes
WEB-20 README run instructions are clear
```

Each criterion must be marked:

```text
PASS
FAIL
UNVERIFIED
WAIVED
```

---

## 24. Scope Audit

Final report must include:

```text
Area | Changed? | Status | Notes
TOMTIT-Memory | Yes/No | PASS/FAIL | ...
Memory Contract files | Yes/No | PASS/FAIL | ...
agent_core/runtime | Yes/No | PASS/FAIL | ...
agent_core/memory | Yes/No | PASS/FAIL | ...
agent_core/tools | Yes/No | PASS/FAIL | ...
agent_core/skills | Yes/No | PASS/FAIL | ...
agent_core/planning | Yes/No | PASS/FAIL | ...
vector/M8/SF2/self-improvement | Yes/No | PASS/FAIL | ...
frontend | Yes/No | PASS/FAIL | ...
web API | Yes/No | PASS/FAIL | ...
tests | Yes/No | PASS/FAIL | ...
docs | Yes/No | PASS/FAIL | ...
```

Forbidden areas changed without approval must be marked FAIL.

---

## 25. Required Final Report Structure

Create:

```text
docs/reports/REPORT_WEB_CHAT_UI_VERIFIED.md
```

Structure:

```text
# REPORT_WEB_CHAT_UI_VERIFIED

## 0. Baseline Custody
## 1. Implementation Summary
## 2. Backend API
## 3. Runtime Integration
## 4. Frontend UI
## 5. Memory Recall / Provenance Behavior
## 6. Config and Run Commands
## 7. Tests and Build Results
## 8. Scope Audit
## 9. Acceptance WEB-01 through WEB-20
## 10. Limitations
## 11. Final Verdict
```

Final verdict must be exactly one of:

```text
WEB CHAT UI: PASS
READY FOR HUMAN RUN/REVIEW
```

or:

```text
WEB CHAT UI: BLOCKED
Reason: <specific blocker>
```

---

## 26. Stop Conditions

Stop and report BLOCKED if:

```text
TOMTIT-Agent runtime cannot be invoked from backend without core runtime changes
SessionRuntime API is incompatible and needs runtime refactor
RuntimeAgent API is incompatible and needs runtime refactor
memory recall requires TOMTIT-Memory contract changes
frontend requires direct TOMTIT-Memory access
tests cannot run due to missing dependency lock decision
FastAPI/React stack conflicts with repo constraints
repository structure conflicts with this task
the only possible implementation is a fake chatbot
```

Use:

```text
WEB CHAT UI: BLOCKED
Reason: <specific blocker>

Evidence:
- <file/path inspected>
- <function/class/config inspected>
- <command output if relevant>
- <why this blocks the task>

Recommended next step:
- <narrow human decision or implementation path>
```

Do not continue implementation after BLOCKED.

---

## 27. Final Rule

The successful output is:

```text
a small, real, verifiable TomTit Web UI over TOMTIT-Agent runtime
```

The failed output is:

```text
a good-looking but fake chatbot
a second runtime hidden in the web layer
a duplicated memory system
a scope-crept production platform
a UI that bypasses TOMTIT-Agent
```

Choose the small, real, verifiable path.

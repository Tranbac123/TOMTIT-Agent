# AGENTS.md — TOMTIT-Agent Web UI Agent Instructions

## 0. Purpose

This file defines shared instructions for AI coding agents working on the TOMTIT-Agent Web UI task.

These instructions apply to Claude Code, Codex, and any other coding agent used in this repository.

This file is intentionally agent-agnostic.

Agent-specific instructions may live in:

```text
CLAUDE.md
.codex/
.claude/
```

But this file defines the common project contract.

## 1. Project Identity

TOMTIT-Agent is a **local-first, state-first agent runtime**.

The current task is to build a local developer web interface over TOMTIT-Agent.

The web app must be:

```text
a real UI over TOMTIT-Agent runtime
```

not:

```text
a fake chatbot
a standalone demo
a second runtime
a second memory system
a planner implementation
a retrieval implementation
```

Core principle:

```text
AgentState is the runtime source of truth.
```

The web layer must not reconstruct or replace AgentState.

## 2. Current Approved Task

Current task:

```text
Build TOMTIT-Agent Web UI + HTTP API adapter.
```

The web UI should provide:

```text
TomTit-branded ChatGPT-like interaction layout
local developer web frontend
backend HTTP API adapter
basic session/conversation management
chat message send/receive
memory recall UI/API
provenance/source display
safe loading/error states
tests
README/docs/report updates
```

The task must expose existing TOMTIT-Agent capability through browser UI.

It must not create new agent capability.

## 3. Required Architecture Flow

The required flow is:

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

## 4. Mandatory Reading Order

Before making code changes, read:

```text
CLAUDE.md
.claude/rules/01-tomtit-architecture-contract.md
.claude/rules/02-current-task-web-chat-ui.md
.claude/rules/03-runtime-adapter-contract.md
.claude/rules/04-scope-guard.md
.claude/rules/05-testing-verification-gate.md
docs/specs/WEB_CHAT_UI_SPEC.md
```

If any required file is missing, stop and report:

```text
BLOCKED: required instruction file missing
Missing file: <path>
```

Do not guess missing instructions.

## 5. Non-Goals

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
TOMTIT-Memory code changes
Memory Contract changes
core runtime refactor
production authentication
multi-tenant SaaS billing
production deployment hardening
Kubernetes
distributed task queue
monitoring stack
marketplace
plugin store
mobile app
desktop app
```

If any non-goal appears required, stop and report BLOCKED.

## 6. Approved Product Direction

The approved product direction is:

```text
Dark modern local developer web app
ChatGPT-like UX structure as inspiration
TomTit brand identity
TOMTIT-specific sidebar features
real backend integration over TOMTIT-Agent runtime
```

Branding:

```text
Brand name: TomTit
Wordmark color: red-orange
Logo: small stylized mantis-shrimp-inspired mark
Logo posture: horizontal side-profile
Logo style: simple, distinctive, modern, app-icon suitable
```

Do not copy:

```text
ChatGPT logo
OpenAI logo
OpenAI proprietary icons
OpenAI brand-specific assets
ChatGPT-specific names
proprietary sidebar graphics
```

The final product must visibly be TomTit, not ChatGPT.

## 7. Required Sidebar Labels

Use these TOMTIT-specific sidebar labels:

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

Pinned seed examples:

```text
Build TOMTIT web UI
Kiến trúc TOMTIT-Agent
Kiến trúc TOMTIT-Memory
Kiến trúc TOMTIT-Memory 2
AI tự tiến hoá
```

Pinned examples are display seeds only.

Do not treat them as durable backend data unless explicitly implemented as session metadata.

## 8. Preferred Stack

Use existing repository convention first.

If no convention exists, prefer:

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

## 9. Repository Structure Rule

Inspect the repository before creating files.

Follow existing conventions for:

```text
frontend app
backend API
runtime adapter
tests
docs
reports
configuration
dependency management
```

If no convention exists, preferred backend structure is:

```text
agent_core/web_api/
  __init__.py
  app.py
  models.py
  routes.py
  session_manager.py
  runtime_adapter.py
  errors.py
  stores.py
```

Preferred frontend structure is:

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
    styles/
```

Do not create a parallel API app or frontend app if the repository already has a canonical structure.

If repo structure conflicts with the task spec, stop and report:

```text
BLOCKED: repository structure mismatch

Observed structure:
- ...

Conflicting instruction:
- ...

Recommended narrow path:
- ...
```

## 10. Runtime Adapter Rule

Before implementing backend routes, inspect the existing TOMTIT-Agent CLI/runtime path.

Document:

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

Required route path:

```text
routes.py
→ session_manager.py
→ runtime_adapter.py
→ existing SessionRuntime / RuntimeAgent
```

Forbidden route path:

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

WEB-06 can pass only if the production adapter calls an existing TOMTIT-Agent runtime path.

Route-level mocks alone are not enough.

## 11. Memory Boundary

Frontend must never call TOMTIT-Memory directly.

Backend must not reimplement memory retrieval.

Memory recall must use existing runtime/session/memory-client path when available.

Do not add:

```text
vector search
embeddings
Qdrant
semantic retrieval
new memory write path
new retrieval implementation
```

Do not modify:

```text
TOMTIT-Memory/**
Memory Contract files
```

If memory recall requires TOMTIT-Memory changes, stop and report BLOCKED.

## 12. Provenance Boundary

Provenance must only be displayed if returned by runtime or memory result.

Allowed:

```text
normalize existing provenance fields
display empty provenance state
display “No provenance returned”
show memory_id/evidence_ref/source_task_id when present
```

Forbidden:

```text
fabricate memory_id
fabricate evidence_ref
fabricate source_task_id
fabricate source documents
fabricate confidence claims
frontend-generated provenance
```

## 13. Allowed File Areas

Allowed likely areas:

```text
web/**
agent_core/web_api/**
tests/test_web_api.py
tests/**/test_web_api*.py
README.md
docs/specs/WEB_CHAT_UI_SPEC.md
docs/reports/REPORT_WEB_CHAT_UI_VERIFIED.md
```

Dependency files may be edited only when necessary and justified:

```text
requirements.txt
pyproject.toml
package.json
package-lock.json
pnpm-lock.yaml
yarn.lock
```

## 14. Forbidden File Areas Without Explicit Approval

Do not edit:

```text
TOMTIT-Memory/**
agent_core/runtime/**
agent_core/memory/**
agent_core/tools/**
agent_core/skills/**
agent_core/planning/**
docs/standards/**
docs/specs/** other than WEB_CHAT_UI_SPEC.md
Memory Contract files
```

Do not edit generated/system directories:

```text
.git/**
.venv/**
venv/**
node_modules/**
dist/**
build/**
coverage/**
.pytest_cache/**
__pycache__/**
```

If completing the task requires forbidden file edits, stop and report BLOCKED.

## 15. Required API Endpoints

Required endpoints:

```http
GET /api/health
POST /api/sessions
GET /api/sessions
GET /api/sessions/{session_id}/messages
POST /api/chat
POST /api/memory/recall
```

Optional:

```http
POST /api/chat/stream
```

Streaming is optional. REST JSON is the default MVP.

If streaming is added later:

```text
POST /api/chat/stream with fetch ReadableStream
or GET /api/chat/stream with native EventSource
```

Do not implement native EventSource over POST.

Do not fake token streaming.

## 16. Required Backend Tests

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

Tests may mock the RuntimeAdapter boundary.

Mocks must not become production behavior.

## 17. Required Commands

Run these before final report when applicable.

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

## 18. Required Acceptance Criteria

Evaluate every criterion in the final report:

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

Do not use vague status words.

## 19. Required Final Report

Create or update:

```text
docs/reports/REPORT_WEB_CHAT_UI_VERIFIED.md
```

Report sections:

```text
0. Baseline custody
1. Implementation summary
2. Backend API
3. Runtime integration
4. Frontend UI
5. Memory recall / provenance behavior
6. Config and run commands
7. Tests and build results
8. Scope audit
9. Acceptance WEB-01 through WEB-20
10. Limitations
11. Final verdict
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

## 20. Scope Audit Requirement

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
dependency files | Yes/No | PASS/FAIL | ...
```

Forbidden areas changed without approval must be marked FAIL.

## 21. Block Conditions

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

## 22. Git / Delivery Rules

Do not:

```text
merge
push
tag release
deploy
rewrite history
delete unrelated files
rename unrelated directories
format entire repository
commit unless explicitly instructed
```

Allowed:

```text
inspect git status
inspect git diff
run git diff --check
report changed files
```

Final response must include:

```text
files changed
tests run
frontend build result
backend run command
frontend run command
known limitations
blocked or unverified items
final verdict
```

## 23. Final Rule

The safe outcome is:

```text
small, real, verifiable TomTit Web UI over TOMTIT-Agent runtime
```

The unsafe outcome is:

```text
large, fake, overbuilt, or scope-crept app that only looks like TOMTIT
```

Choose the safe outcome.

When uncertain, stop and report instead of inventing architecture.

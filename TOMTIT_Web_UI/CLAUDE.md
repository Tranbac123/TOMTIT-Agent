# CLAUDE.md — TOMTIT Web UI Build Instructions

Repository Decision: Web UI lives inside TOMTIT-Agent repo for this phase; do not create a separate TOMTIT-WEBUI repo.

## 0. Project Identity

This repository is for **TOMTIT-Agent Web UI**, a local developer web interface over the existing TOMTIT-Agent runtime.

TOMTIT-Agent is a **local-first, state-first agent runtime**.

Core principle:

```text
AgentState is the runtime source of truth.
```

The web app is not a new agent runtime.
The web app is not a new memory system.
The web app is not a planner.
The web app is not a standalone chatbot demo.

The web app is only:

```text
Frontend UI
+ HTTP API adapter
+ session/display state
+ runtime integration surface
```

## 1. Mandatory Reading Order

Before making any code change, read these files in order:

```text
AGENTS.md
.claude/rules/01-tomtit-architecture-contract.md
.claude/rules/02-current-task-web-chat-ui.md
.claude/rules/03-runtime-adapter-contract.md
.claude/rules/04-scope-guard.md
.claude/rules/05-testing-verification-gate.md
docs/specs/WEB_CHAT_UI_SPEC.md
```

If any file is missing, stop and report:

```text
BLOCKED: required instruction file missing
Missing file: <path>
```

Do not guess the missing instruction.

## 2. Current Task

Build the approved **TomTit Web UI baseline**.

The approved product direction is:

```text
A ChatGPT-like local developer web interface,
adapted for TOMTIT-Agent,
with TomTit branding and TOMTIT-specific features.
```

Approved visual direction:

```text
Dark modern sidebar UI
TomTit brand name in red-orange
Small stylized mantis-shrimp-inspired logo beside TomTit
Logo posture: simple horizontal side-profile shrimp form
Sidebar contains TOMTIT features, not generic ChatGPT features
```

Important UI rule:

```text
Use ChatGPT-like UX structure as inspiration only.
Do not copy proprietary ChatGPT assets, icons, logos, names, or brand-specific visuals.
The visible product brand must be TomTit.
```

## 3. Required Architecture Flow

The required runtime flow is:

```text
Browser
→ TOMTIT-Agent Web API
→ existing SessionRuntime / RuntimeAgent
→ existing memory client
→ TOMTIT-Memory
```

The frontend must never call TOMTIT-Memory directly.

The backend API must not bypass TOMTIT-Agent runtime.

The web API must not reimplement memory retrieval.

The web API must not call tools directly from route handlers.

## 4. Non-Negotiable Scope Rules

Do not implement or modify anything related to:

```text
SF2
M8
vector search
vector DB
Qdrant
embeddings
semantic retrieval
RAG rewrite
LLMPlanner production mode
self-improvement loop
TOMTIT-Memory code
Memory Contract files
core runtime refactor
production authentication
multi-tenant SaaS billing
production deployment hardening
```

If completing the current web UI task appears to require any of the above, stop and report:

```text
WEB CHAT UI: BLOCKED
Reason: <specific blocker>
```

Do not silently work around the blocker.

## 5. Repository Truth Rule

Before creating any new directory or changing project structure, inspect the current repository.

Follow existing conventions when present.

If the repository already has a canonical location for:

```text
frontend app
API app
runtime adapter
tests
docs
reports
```

then use the existing convention.

Do not create a parallel app structure unless the spec explicitly allows it and the repo has no existing convention.

If the observed repo structure conflicts with the task spec, stop and report:

```text
BLOCKED: repository structure mismatch

Observed structure:
- ...

Conflicting instruction:
- ...

Recommended narrow path:
- ...
```

## 6. State Contract

AgentState remains the runtime source of truth.

Allowed web-layer state:

```text
selected session id
session metadata
UI transcript cache
loading/error state
user_id setting
project_id setting
backend API base URL
provenance display data returned by backend
```

Forbidden web-layer state:

```text
authoritative memory records
confirmed decision store
planner state
tool execution state
reconstructed AgentState
fabricated provenance
duplicated retrieval index
```

The frontend may display runtime output.
The frontend must not invent runtime facts.

## 7. Runtime Adapter Contract

Before implementing backend routes, inspect the existing CLI/runtime path.

Document the discovered runtime path in the implementation report:

```text
CLI entrypoint inspected:
module path:
class/function:
required input schema:
output schema:
sync/async behavior:
how user_id is passed:
how project_id is passed:
how session_id is passed:
memory recall method:
```

The API layer must call the existing TOMTIT-Agent runtime path through a thin adapter.

Allowed:

```text
thin RuntimeAdapter
safe response normalization
safe error mapping
request/session metadata wrapper
tests using mocks around RuntimeAdapter boundary
```

Forbidden:

```text
mock assistant response as final implementation
hardcoded chatbot response
direct TOMTIT-Memory call from frontend
direct retrieval implementation in web API
tool calls from API routes
core runtime edits to make the web easier
```

If no safe runtime entrypoint exists, stop and report:

```text
WEB CHAT UI: BLOCKED
Reason: existing runtime cannot be invoked safely from backend without core runtime changes.
```

## 8. Build Gates

Work in gated order.

### Gate A — Backend API Adapter

Implement and verify backend first.

Required endpoints:

```text
GET  /api/health
POST /api/sessions
GET  /api/sessions
GET  /api/sessions/{session_id}/messages
POST /api/chat
POST /api/memory/recall
```

Gate A must prove:

```text
backend starts locally
chat route calls existing runtime adapter
memory recall route calls existing runtime adapter
blank message is rejected
blank recall query is rejected
runtime errors return safe API errors
raw Python stack traces are not exposed
frontend does not exist as a workaround for missing backend
```

Do not start frontend implementation until Gate A passes or is explicitly approved to proceed.

### Gate B — Frontend UI

Implement frontend only after Gate A.

Required UI:

```text
TomTit branded sidebar
New chat
Search
Memory
Skills
Projects
Sessions
Provenance
More
Pinned conversations/items
Chat message list
Composer
Loading state
Safe error state
Memory recall panel or command
Provenance/source display
Settings for user_id, project_id, backend API base URL
```

Frontend constraints:

```text
Do not call TOMTIT-Memory directly.
Do not fabricate provenance.
Do not duplicate retrieval logic.
Do not hardcode fake assistant behavior.
Use backend API contract only.
```

### Gate C — Verification

After implementation, run verification and create the final report.

Do not declare completion without evidence.

## 9. Preferred Stack

Use the existing repo convention first.

If no convention exists, prefer:

```text
Frontend: React + TypeScript + Vite
Styling: plain CSS or CSS Modules
Backend: FastAPI + Pydantic + Uvicorn
Transport: REST JSON first
Session MVP: backend in-memory store + browser localStorage
Testing: pytest for backend, npm build/typecheck for frontend
```

Do not add these unless required by existing repo convention or explicitly approved:

```text
Next.js
GraphQL
WebSocket-first architecture
Postgres session persistence
Redis session persistence
heavy UI framework
production Docker/Kubernetes setup
```

## 10. Streaming Rule

Do not implement streaming unless it is simple and does not disturb Gate A.

REST JSON is the default for this MVP.

If streaming is added later:

```text
Use POST /api/chat/stream with fetch ReadableStream
or GET /api/chat/stream with native EventSource
```

Do not implement native EventSource with POST.

Do not fake token streaming if TOMTIT-Agent runtime does not support token streaming.

## 11. Approved Feature Labels

The left sidebar should use TOMTIT-specific feature labels:

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

Pinned examples:

```text
Build TOMTIT web UI
Kiến trúc TOMTIT-Agent
Kiến trúc TOMTIT-Memory
Kiến trúc TOMTIT-Memory 2
AI tự tiến hoá
```

These are UI seed examples only.
Do not treat pinned examples as persistent backend data unless the spec explicitly requires it.

## 12. Branding Rules

Visible brand:

```text
TomTit
```

Brand direction:

```text
red-orange wordmark
small stylized mantis-shrimp-inspired logo
horizontal shrimp posture
simple, distinctive, modern, app-icon suitable
dark UI background
```

Do not use:

```text
ChatGPT logo
OpenAI logo
OpenAI brand colors as identity
copied proprietary icons
copied proprietary sidebar assets
```

Use original line icons or open-source icons already allowed by the repo.

## 13. Error Handling Requirements

Backend API errors must be safe.

Do not expose:

```text
Python stack traces
environment variables
secrets
raw internal exception repr
memory backend credentials
provider API keys
```

API errors should include safe fields only:

```text
status
error_code
message
request_id if available
session_id if available
```

## 14. Observability Minimum

Where practical, include these identifiers in backend responses or logs:

```text
request_id
session_id
user_id
project_id
run_id if runtime provides it
status
error_code
```

Do not overbuild observability.
Do not add a monitoring stack in this task.

## 15. Dependency Rule

Do not modify dependency files unless necessary.

Allowed dependency files only when justified:

```text
requirements.txt
pyproject.toml
package.json
package-lock.json
```

Before adding a dependency, check whether the repo already has an equivalent.

Prefer minimal dependencies.

Do not upgrade unrelated dependencies.

## 16. Forbidden File Areas Without Explicit Approval

Do not edit these unless explicitly authorized:

```text
TOMTIT-Memory/**
agent_core/runtime/**
agent_core/memory/**
agent_core/tools/**
agent_core/skills/**
agent_core/planning/**
docs/standards/**
Memory Contract files
```

If a runtime change is required, stop and report BLOCKED before editing.

## 17. Required Tests

Backend tests should cover:

```text
GET /api/health returns ok
POST /api/sessions creates session
GET /api/sessions lists session
GET /api/sessions/{session_id}/messages returns messages
POST /api/chat rejects blank message
POST /api/chat calls RuntimeAdapter
POST /api/memory/recall rejects blank query
POST /api/memory/recall calls RuntimeAdapter
runtime error returns safe API error
raw stack trace is not exposed
```

Frontend verification should cover at minimum:

```text
npm install
npm run build
```

If typecheck/lint/test scripts exist, run them too.

Do not add a frontend test framework unless the repo already has one or the task spec explicitly requires it.

## 18. Required Verification Commands

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

Final hygiene:

```bash
git diff --check
git status --short --untracked-files=all
```

If a command cannot run, report:

```text
UNVERIFIED
Reason: <specific reason>
```

Do not mark it PASS.

## 19. Final Report Requirement

Create or update:

```text
docs/reports/REPORT_WEB_CHAT_UI_VERIFIED.md
```

Do not commit it unless explicitly instructed.

The report must include:

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

## 20. Work Style

Before editing code:

```text
inspect repo
identify existing conventions
identify runtime entrypoint
write a short implementation plan
then patch narrowly
```

During implementation:

```text
prefer small cohesive changes
avoid broad refactors
do not rename unrelated files
do not rewrite unrelated README sections
do not beautify unrelated code
do not add future-phase features
```

Before final response:

```text
summarize changed files
summarize tests run
summarize frontend build result
summarize backend run command
summarize known limitations
summarize blocked/unverified items
```

## 21. Stop Conditions

Stop and report BLOCKED if:

```text
TOMTIT-Agent runtime cannot be invoked from backend without core runtime changes
SessionRuntime API is incompatible and needs runtime refactor
memory recall requires TOMTIT-Memory contract changes
frontend would need direct TOMTIT-Memory access
tests cannot run due to missing dependency lock decision
FastAPI/React stack conflicts with repo constraints
repository structure conflicts with this task spec
```

Do not silently bypass TOMTIT-Agent with a fake chatbot.

The web must be a real UI over TOMTIT-Agent.

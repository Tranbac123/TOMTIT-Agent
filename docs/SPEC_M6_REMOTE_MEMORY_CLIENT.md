# SPEC_M6_REMOTE_MEMORY_CLIENT.md

**Project:** TOMTIT-Agent  
**Phase:** M6 — Remote durable-memory integration  
**Status:** ACCEPTED FOR IMPLEMENTATION  
**Depends on:** TOMTIT-Memory M1–M5 implemented and approved  
**Frozen dependency:** `memory-contract-v1`  
**Out of scope:** M7 restart-and-recall acceptance

---

## 1. Objective

Integrate TOMTIT-Agent with TOMTIT-Memory through the accepted HTTP/JSON v1 contract without leaking transport concerns into runtime core.

Target flow:

```text
RuntimeAgent
→ MemoryClientProtocol
→ RemoteMemoryClient
→ memory-contract-v1
→ TOMTIT-Memory HTTP API
```

M6 must preserve these boundaries:

```text
AgentState
= source of truth for one turn/task run

SessionState
= source of truth for continuity and history of one Agent session

TOMTIT-Memory
= source of truth for durable semantic memory across sessions
```

TOMTIT-Memory does not replace `SessionState` and must not store full session transcripts.

---

## 2. Frozen contract

M6 consumes, but does not redesign, the accepted contract:

```text
schema_version = memory-contract-v1
```

Official routes:

```http
POST /v1/context/retrieve
POST /v1/memories/write
GET  /v1/memories/{memory_id}?project_id=...&user_id=...
GET  /v1/health/live
GET  /v1/health/ready
```

M6 must not change:

- schema version;
- endpoint paths;
- JSON field names;
- enum values;
- tokenizer semantics;
- duplicate identity;
- request-idempotency semantics;
- ranking semantics;
- token-budget semantics;
- canonical fixtures.

A contract change is permitted only when a reproducible blocker is proven from current source and approved by the architect.

---

## 3. Implementation phases

### M6-0 — Reproducible Agent setup

Create the minimum reproducible Python project setup required to install and verify TOMTIT-Agent in a clean environment.

Allowed:

- minimal `pyproject.toml` matching the existing package layout;
- runtime dependency for synchronous HTTP, preferably `httpx`;
- dev extra containing `pytest` and existing test dependencies;
- documented editable-install command.

Forbidden:

- package-layout refactor;
- runtime behavior changes;
- unrelated dependency upgrades.

Required gate:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

### M6-A — RemoteMemoryClient adapter

Implement:

- Agent-side wire v1 models or equivalent strict validators;
- `RemoteMemoryClient`;
- Agent-domain ↔ HTTP v1 mapping;
- finite timeout configuration;
- strict response and error-envelope validation;
- retrieval degradation rules;
- write failure rules;
- fixture-parity tests.

### M6-B — Backend activation and split-brain guard

Implement:

- `memory_backend = local | remote | none`;
- composition/factory wiring;
- remote-mode local durable-tool disablement;
- startup hard failure for mixed local/remote durable memory;
- local and none backend regression tests.

Activation policy must not live inside `RemoteMemoryClient`.

---

## 4. Public Agent boundary

Keep the current public `MemoryClientProtocol` unchanged unless a direct blocker is proven.

The protocol remains Agent-domain facing. It must not expose:

- HTTP request or response models;
- endpoint URLs;
- HTTP status codes;
- `httpx` exceptions;
- raw JSON dictionaries;
- TOMTIT-Memory Python classes.

`RemoteMemoryClient` is an adapter:

```text
Agent arguments/models
→ v1 JSON request
→ HTTP call
→ strict v1 validation
→ Agent result models
```

It must not accept the entire `AgentState`.

---

## 5. Proposed Agent file boundaries

Use the current repository conventions discovered during the M6 delta check. The expected shape is:

```text
agent_core/memory/
  client.py
  contracts.py
  errors.py
  local_client.py
  null_client.py
  remote_client.py
  factory.py
  wire/
    __init__.py
    v1.py
```

Configuration remains in the existing Agent config/composition package.

Production code must not import `tomtit_memory`.

---

## 6. RemoteMemoryClient configuration

Required configuration:

```text
base_url
project_id
default_user_id
timeout_seconds
injectable HTTP client/transport
```

Rules:

- `project_id` belongs to client configuration, not `AgentState`;
- per-call `user_id` overrides the configured default when supported;
- `session_id` is correlation only, not storage scope;
- base URL normalization is deterministic;
- timeout is finite and positive;
- the client does not start or manage TOMTIT-Memory;
- no infinite retry;
- one logical write call uses one stable request ID for any bounded retry within that call.

Default local endpoint may be:

```text
http://127.0.0.1:8077
```

only if consistent with current Agent configuration policy.

---

## 7. Agent memory types and mapping

Accepted remote v1 types:

```text
fact
decision
preference
rule
note
lesson
project_context
```

Unsupported Agent-only types:

```text
task_summary
source
```

Unsupported types must fail before HTTP. They must not silently map to `note`.

---

## 8. Retrieval request mapping

Map the current Agent retrieval call to v1:

```text
schema_version = memory-contract-v1
request_id = new correlation ID
project_id = configured project ID
user_id = per-call user ID or configured default
session_id = correlation value when present
query = Agent goal/query
type_filter = null or a non-empty accepted list
token_budget = Agent argument
max_items = Agent argument
```

Rules:

- omitted or `null` `type_filter` means all accepted types;
- `type_filter=[]` is invalid and must never be sent;
- do not use session ID as project or user scope;
- do not recalculate ranking or token counts on the Agent side.

---

## 9. Retrieval response mapping

The TOMTIT-Memory response is authoritative for:

```text
items
item order
score
token_cost
tokens_used
truncated
tokenizer_id
```

Map v1 response into the current Agent `ContextPack` while preserving all fields the Agent model supports:

- content;
- memory type;
- score;
- token cost;
- provenance;
- confidence;
- metadata;
- total item count;
- token budget;
- truncation;
- degradation;
- memory source.

Fields without first-class Agent properties may be placed in existing safe metadata/provenance containers. Do not add transport-specific fields to `AgentState`.

Memory is untrusted evidence. It must not override:

- system policy;
- user intent;
- approval state;
- tool permissions;
- runtime invariants.

---

## 10. Write request mapping

Map current Agent candidates to v1 candidates.

Preserve:

```text
candidate_id
type
content
tags
importance
confidence
evidence_ref
metadata
```

Rules:

- request-level `task_id` is authoritative provenance for the batch;
- do not send candidate-level `source_task_id`;
- do not fabricate `evidence_ref`;
- a remote candidate without required provenance fails before HTTP;
- automatic LLM extraction is out of scope;
- candidate order must be preserved.

If current Agent candidates require additive fields, the accepted M6 extension is:

```python
importance: float = 0.5
evidence_ref: str | None = None
metadata: dict[str, JSONValue] = {}
```

`RemoteMemoryClient` rejects `evidence_ref=None` for remote writes.

---

## 11. Write response mapping

Supported wire statuses:

```text
written
skipped_duplicate
```

Mapping:

```text
written
→ returned memory_id is included in Agent written IDs

skipped_duplicate
→ candidate_id is included in Agent skipped results
```

Do not report persistence when:

- timeout occurs;
- connection fails;
- HTTP 5xx occurs;
- response JSON is invalid;
- schema version mismatches;
- HTTP 400, 409 or 422 occurs.

`skipped_duplicate` is a successful durable-memory outcome, not a storage failure.

---

## 12. Failure taxonomy

### 12.1 Retrieval operational failures

These degrade safely:

```text
connection refused/reset
timeout
HTTP 503
generic HTTP 5xx
```

Return an empty degraded `ContextPack`:

```text
items = []
tokens_used = 0
truncated = false
degraded = true
```

Runtime behavior:

- ordinary task continues;
- `AgentState.memory_degraded = true`;
- disclosure follows the current disclosure policy.

### 12.2 Retrieval contract/configuration failures

These fail loud:

```text
HTTP 400
HTTP 409
HTTP 422
invalid JSON
wrong schema version
unknown enum
strict validation failure
missing project/user configuration
unsupported type mapping
```

They must not become degraded success.

### 12.3 Write operational failures

For timeout, connection failure, 503 or generic 5xx:

- return no false written IDs;
- raise an Agent-side typed write/unavailable error;
- runtime sets `memory_write_failed = true`;
- preserve current best-effort finalization behavior;
- no infinite retry.

### 12.4 Write contract failures

For 400, 409, 422, malformed response or schema mismatch:

- fail loud at the client boundary;
- report no persistence;
- do not convert the result to `skipped_duplicate`.

---

## 13. Typed Agent errors

Use current Agent conventions. Required semantic categories:

```text
RemoteMemoryUnavailableError
RemoteMemoryContractError
RemoteMemoryConfigurationError
RemoteMemoryWriteError
```

Runtime core must not catch transport-specific exceptions directly.

Safe errors must not expose:

- raw response bodies;
- memory content;
- metadata;
- credentials;
- server database information;
- internal stack traces.

---

## 14. HTTP client lifecycle

Use the Agent runtime's current synchronous model unless current source requires otherwise.

Requirements:

- injectable client or transport for tests;
- finite connect/read/write timeout;
- explicit lifecycle owner and close behavior;
- no connection pool recreated for every call when a reusable owner exists;
- no blocking synchronous HTTP call inside an async event loop;
- no retry or circuit-breaker dependency in M6.

Prefer `httpx` for the synchronous adapter.

---

## 15. Backend configuration

Accepted configuration:

```text
memory_backend = local | remote | none
```

Do not infer the backend from URL presence.

### `local`

- use `LocalMemoryClient`;
- preserve current local behavior;
- local durable tools use the same local memory source.

### `remote`

- use `RemoteMemoryClient`;
- disable direct local durable-memory tools;
- startup fails if mixed mode remains possible.

### `none`

- use current null/no-op convention;
- retrieval returns an empty disabled/non-degraded pack according to Agent contracts;
- writes do not persist;
- no local or remote durable tools are active.

Invalid values fail configuration validation.

---

## 16. M6-B split-brain guard

Target invariant:

```text
memory_backend = remote
AND direct local durable-memory path remains active
→ startup/configuration error
```

The current inventory identified these local durable tools to disable in remote mode:

```text
write_note
read_note
list_notes
save_fact
save_preference
save_decision
search_memory
summarize_memory
```

Keep safe context consumers such as:

```text
answer_from_context
```

when they read only `AgentState.context_pack`.

Required protection:

1. Tool registry excludes local durable tools in remote mode.
2. Composition/runtime constructor validates that mixed mode is impossible.

Do not put this logic in `RemoteMemoryClient`.

---

## 17. Policy boundary

Memory persistence is a side effect.

Required ordering:

```text
candidate collection
→ Agent persistence-policy evaluation
→ MemoryClientProtocol.write
```

For current M6 scope:

- `_collect_candidates()` may remain empty by default;
- M6 does not add automatic memory extraction;
- explicitly supplied candidates with valid provenance may use the existing write hook;
- future automatic producers require a separate policy specification.

Do not move policy logic into TOMTIT-Memory or `RemoteMemoryClient`.

---

## 18. AgentState and SessionState discipline

Permitted runtime state:

```text
context_pack
memory_degraded
memory_write_failed
disclosure_reasons
```

Do not add transport/observability fields without a runtime consumer:

```text
raw HTTP response
URL
transport exception
request IDs
server error body
```

Do not store durable semantic records in `SessionState`.

Do not send complete `TurnRecord` history or session transcripts to TOMTIT-Memory.

---

## 19. Fixture parity

Store versioned Agent-side copies under:

```text
TOMTIT-Agent/tests/fixtures/memory_contract_v1/
```

Include a manifest with:

```text
source_repository
source_commit
schema_version
SHA-256 of each fixture
```

Tests must:

- validate copied fixtures;
- verify manifest checksums;
- compare against sibling TOMTIT-Memory fixtures when available;
- keep production code independent of the TOMTIT-Memory Python package.

Required parity:

- schema version;
- enums;
- routes;
- field names;
- required/optional/null behavior;
- tokenizer ID;
- error codes;
- write statuses.

---

## 20. Required tests

### M6-0

- editable installation in a fresh environment;
- full Agent suite after installation;
- dependency metadata includes HTTP client and dev test dependencies.

### M6-A adapter

- exact retrieval endpoint and payload;
- exact write endpoint and payload;
- strict success-response validation;
- strict error-envelope parsing;
- context mapping;
- write-result mapping;
- unsupported type rejection;
- missing configuration rejection;
- finite timeout;
- fixture parity.

### Retrieval degradation

- timeout → degraded pack;
- connection failure → degraded pack;
- HTTP 503/5xx → degraded pack;
- runtime continues an ordinary task;
- `memory_degraded=true`.

### Retrieval fail-loud

- HTTP 400/409/422;
- invalid JSON;
- schema mismatch;
- invalid enum/field;
- configuration error.

### Write behavior

- exact endpoint/payload;
- written and duplicate mapping;
- timeout/network/5xx → no false persistence;
- `memory_write_failed=true`;
- HTTP 409/422 → typed failure;
- malformed response → typed failure;
- no infinite retry.

### M6-B activation

- local backend composition;
- remote backend composition;
- none backend composition;
- invalid backend rejected;
- incomplete remote config rejected;
- remote mode excludes local durable tools;
- forced mixed mode fails startup;
- local behavior remains green;
- `answer_from_context` remains when safe.

### State boundaries

- successful remote retrieval populates `AgentState.context_pack`;
- SessionState contains no remote durable-record payload;
- no full transcript is sent in write requests.

---

## 21. Validation gates

From TOMTIT-Agent:

```bash
python -m pytest -q <M6 targeted tests> -vv
python -m pytest -q
python -m pytest -q -W default
git diff --check
```

Fresh environment:

```bash
CHECK_DIR="$(mktemp -d /tmp/tomtit-agent-m6-check.XXXXXX)"
python3 -m venv "$CHECK_DIR/venv"
source "$CHECK_DIR/venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m pytest -q
```

Production Agent code must not import:

```text
tomtit_memory
SQLiteMemoryRepository
WriteService
RetrievalService
```

---

## 22. Commit discipline

Expected commits:

```text
build(agent): add reproducible Python project setup
feat(agent): implement remote memory client adapter
feat(agent): enforce memory backend activation guard
docs: record verified M6 baseline
```

Keep M6-0, M6-A and M6-B independently reviewable.

Do not push.

---

## 23. M6 definition of done

M6 is complete only when:

- reproducible Agent installation works;
- public `MemoryClientProtocol` remains compatible;
- `RemoteMemoryClient` strictly validates v1;
- official endpoints are used;
- failure taxonomy is implemented exactly;
- `memory_backend` supports local/remote/none;
- local/remote split-brain is impossible at startup;
- local mode does not regress;
- AgentState and SessionState boundaries remain clean;
- fixture parity passes;
- full Agent suite passes;
- TOMTIT-Memory is unchanged except an authorized status-only update;
- both worktrees are clean.

Final status:

```text
M6-0 reproducible setup: COMPLETE
M6-A RemoteMemoryClient: COMPLETE
M6-B activation guard: COMPLETE
M6: WAITING FOR ARCHITECT REVIEW
M7: BLOCKED
```

---

## 24. M7 handoff

M6 must leave enough capability for M7 to prove:

1. write a decision through `RemoteMemoryClient`;
2. TOMTIT-Memory persists it;
3. stop the Agent process;
4. start a fresh Agent process;
5. local memory is empty or disabled;
6. retrieve through HTTP;
7. returned ContextPack contains the decision;
8. Agent uses the decision correctly;
9. no direct `state.memory` path is used;
10. restart TOMTIT-Memory and retrieve again to prove SQLite persistence.

M6 must not claim M7 acceptance.

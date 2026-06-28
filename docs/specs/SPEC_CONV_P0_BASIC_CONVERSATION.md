# SPEC_CONV_P0_BASIC_CONVERSATION

**Status:** `DRAFT — IMPLEMENTATION NOT AUTHORIZED`
**Baseline:** `origin/main @ 92adb97fc139def9e02d497cc05dff629be9a3cc`
**Supersedes:** the earlier (greenfield) CONV-P0 draft attempt, which was baseline-blocked.

---

## 0. Status

This is a **draft specification** for CONV-P0 (Basic Conversation Experience). It authorizes nothing. Implementation may begin only after: (1) architect review and acceptance of every §18 acceptance criterion and §21 stop condition; (2) the spec is frozen at a committed revision with a recorded SHA-256; (3) a separate implementation instruction cites the frozen revision; (4) the candidate later passes `docs/standards/VERIFICATION_GATE.md`.

Unlike the prior draft, CONV-P0 is **not greenfield**: the baseline `92adb97` already ships a rule-based first pass for GREETING, calculation, and a recoverable UNKNOWN fallback (§4). This spec **reconciles** with that code.

This document does not authorize: production code, LLMPlanner, SF2 guardrails, M8/vector/RAG, self-improvement, TOMTIT-Memory changes, Web UI/Web API changes, autonomous tool execution, or external actions.

---

## 1. Problem

TOMTIT-Agent has a state-first runtime, durable memory recall (M7-A/M7-B), a FastAPI Web API, and a React chat UI — but it does not yet present a coherent **basic conversation experience**. A user typing everyday inputs (greetings, "who are you?", "what can you do?", "what do you remember about me?", "rewrite this", "review this code", "1+1") should get safe, useful, non-hallucinated responses without a redesign or a model upgrade. Today only a thin slice (greeting/calculation/recoverable-unknown) exists; most everyday intents either fall into the generic unknown path or are unhandled.

---

## 2. Goal

Define the minimum viable **Conversation Experience Layer** above/alongside the existing runtime so TOMTIT can route everyday inputs to the right handler (direct answer, memory flow, simple calculation, clarification, or — later — a generative LLM responder), with safe fallbacks and no fabricated capabilities or provenance. CONV-P0 is the spec + acceptance dataset; implementation is incremental and separately authorized.

Allowed product claim (target):

> TOMTIT-Agent can hold a basic, safe, useful conversation for everyday inputs — greetings, identity/capability questions, simple calculation, memory read/write/forget UX, and clarification for under-specified generative requests — using rule-based routing plus a constrained LLMResponder, without LLMPlanner, vector retrieval, or autonomous actions.

---

## 3. Current baseline

`origin/main @ 92adb97` contains:
- `agent_core/planning/` rule-based parser/planner with `IntentName.{CALCULATE, …, PROJECT_CONTEXT_QUERY, GREETING, UNKNOWN}`.
- M7-A confirmed write + M7-B cross-process recall (`run_memory_recall` in `runtime_agent.py`, `session_runtime.py`, `cli.py`).
- `agent_core/web_api/` FastAPI surface: `GET /api/health`, `POST/GET /api/sessions`, `GET /api/sessions/{id}/messages`, `POST /api/chat`, `POST /api/memory/recall` (adapter reuses `handle_turn`/`run_memory_recall`, preserves `user_id`/`project_id`/`session_id`).
- `web/` Vite/React chat UI with memory-recall + provenance panels.
- `pyproject.toml` declares `httpx`, `pydantic`, `fastapi`, `uvicorn[standard]`; dev `pytest`.
- Tests at baseline: Python **633 passed**; frontend typecheck/build pass.

---

## 4. What is already implemented (first pass)

`[VERIFIED_FROM_CODE @ 92adb97]`:

1. **GREETING** — `IntentName.GREETING`; `RuleBasedIntentParser._GREETING_WORDS` matches `hi|hello|hey|xin chào|chào`; `IntentPlanner._greeting_plan` returns a FINISH step with a capability blurb.
2. **CALCULATION_REQUEST** — `RuleBasedIntentParser` recognizes existing `Tính …`, English `calculate/calc …`, Vietnamese math suffix (`bằng mấy`/`là bao nhiêu`), and bare arithmetic; routed to `IntentName.CALCULATE` via `_parse_as_calculate`.
3. **UNKNOWN_RECOVERABLE** — there is no separate enum; `IntentName.UNKNOWN` + `IntentPlanner._unknown_plan` now emit a **recoverable, helpful** fallback (suggests example commands) instead of a dead-end.

These are **first pass**: they are FINISH-step canned responses from the rule planner, not a dedicated ConversationRouter/DirectResponder, and they do not yet cover identity/capability/memory-UX/generative intents.

---

## 5. Non-goals

CONV-P0 does **not** implement or authorize:
- LLMPlanner / autonomous multi-step planning;
- vector DB / semantic retrieval / RAG platform;
- self-improvement loop;
- SF2 trust/prompt-injection boundary;
- whole-project resume; M8;
- TOMTIT-Memory contract/wire changes or a new memory backend;
- tool-execution refactor or autonomous/external actions;
- Web UI/Web API redesign;
- production auth/deployment hardening;
- dependency or `.gitignore` changes.

---

## 6. Design principle

TOMTIT does not need a redesign for basic conversation. It needs a thin **Conversation Experience Layer** that classifies intent and routes to existing or constrained handlers, preserving the repo's invariants: `AgentState` is source of truth; the planner never executes tools; `ToolExecutor` is the only tool gateway; policy/approval gate before execution; memory only via `MemoryClientProtocol`; LLM understands language, code controls behavior. The LLMResponder (future) generates content but never executes tools, never decides irreversible actions, never bypasses policy.

---

## 7. Proposed conversation pipeline

```text
UserMessage
→ ConversationRouter            (classify intent; intercept meta/command turns before planner)
→ IntentParser                  (rule-based now; LLM-assisted classification is post-P0, optional)
→ one of:
    DirectResponder             (greeting/identity/capability/clarification/feedback-style)
    MemoryRuntime               (read/write/forget/disable — reuses M7-A write + M7-B recall)
    ToolRuntime                 (simple calculation via existing CALCULATE plan)
    LLMResponder                (writing/planning/summarization/translation/explanation/review)
→ SafetyGate / PermissionGate   (PolicyEngine + ApprovalGate; unsupported/unsafe short-circuit)
→ ResponseComposer              (deterministic shaping; provenance only when present)
→ FinalAnswer
→ Trace/Audit hook              (future; not P0)
```

Distinction (normative):
- **LLMResponder** — generates user-facing content for writing/planning/explanation/review; does **not** execute tools, decide irreversible actions, or bypass policy.
- **LLMPlanner** — multi-step planner affecting tool choice/execution; **NOT part of CONV-P0**.

---

## 8. Intent taxonomy

```text
GREETING
IDENTITY_QUERY
CAPABILITY_QUERY
MEMORY_READ
MEMORY_WRITE_REQUEST
MEMORY_DELETE_REQUEST
MEMORY_DISABLE_FOR_TURN
PLANNING_REQUEST
WRITING_REQUEST
SUMMARIZATION_REQUEST
TRANSLATION_REQUEST
CALCULATION_REQUEST
CODE_REVIEW_REQUEST
TECHNICAL_EXPLANATION_REQUEST
PRODUCT_ANALYSIS_REQUEST
CLARIFICATION_REQUEST
CONTINUE_REQUEST
FEEDBACK_STYLE_REQUEST
UNKNOWN_RECOVERABLE
UNSUPPORTED_OR_UNSAFE
```

Note: CONV-P0's `CALCULATION_REQUEST` maps to the existing `IntentName.CALCULATE`; `UNKNOWN_RECOVERABLE` maps to the existing `IntentName.UNKNOWN` + recoverable `_unknown_plan`. New CONV-P0 intents would be added incrementally (taxonomy reconciliation, §20 P0-2) without breaking the existing enum.

---

## 9. Intent implementation status

| Intent | Current status | Handling mode | Required next work | Risk |
|---|---|---|---|---|
| GREETING | ALREADY_IMPLEMENTED_FIRST_PASS | DIRECT_RESPONSE | move from planner FINISH blurb to DirectResponder; keep behavior | LOW |
| CALCULATION_REQUEST | ALREADY_IMPLEMENTED_FIRST_PASS | SIMPLE_TOOL_OR_CALCULATION | none for P0 (reconcile messages) | LOW |
| UNKNOWN_RECOVERABLE | ALREADY_IMPLEMENTED_FIRST_PASS | CLARIFICATION / DIRECT_RESPONSE | keep recoverable; refine menu | LOW |
| IDENTITY_QUERY | SPEC_REQUIRED_NOT_IMPLEMENTED | DIRECT_RESPONSE | add parser cue + DirectResponder text (no over-claim) | LOW |
| CAPABILITY_QUERY | SPEC_REQUIRED_NOT_IMPLEMENTED | DIRECT_RESPONSE | capability menu + limitations | LOW |
| MEMORY_READ | SPEC_REQUIRED_NOT_IMPLEMENTED | MEMORY_FLOW | UX over `run_memory_recall`; confirmed vs assumption vs none | MEDIUM |
| MEMORY_WRITE_REQUEST | SPEC_REQUIRED_NOT_IMPLEMENTED | MEMORY_FLOW | reuse M7-A confirmed-write w/ confirmation UX | MEDIUM |
| MEMORY_DELETE_REQUEST | SPEC_REQUIRED_NOT_IMPLEMENTED | MEMORY_FLOW | clarify target if ambiguous; no delete contract exists yet | MEDIUM |
| MEMORY_DISABLE_FOR_TURN | SPEC_REQUIRED_NOT_IMPLEMENTED | DIRECT_RESPONSE / memory-policy | per-turn memory suppression flag | LOW |
| PLANNING_REQUEST | SPEC_REQUIRED_NOT_IMPLEMENTED | LLM_RESPONDER / CLARIFICATION | constrained LLMResponder; clarify when content missing | MEDIUM |
| WRITING_REQUEST | SPEC_REQUIRED_NOT_IMPLEMENTED | CLARIFICATION / LLM_RESPONDER | clarify missing content | MEDIUM |
| SUMMARIZATION_REQUEST | SPEC_REQUIRED_NOT_IMPLEMENTED | CLARIFICATION / LLM_RESPONDER | clarify missing content | MEDIUM |
| TRANSLATION_REQUEST | SPEC_REQUIRED_NOT_IMPLEMENTED | CLARIFICATION / LLM_RESPONDER | clarify missing content | MEDIUM |
| PRODUCT_ANALYSIS_REQUEST | SPEC_REQUIRED_NOT_IMPLEMENTED | CLARIFICATION / LLM_RESPONDER | clarify missing context | MEDIUM |
| TECHNICAL_EXPLANATION_REQUEST | SPEC_REQUIRED_NOT_IMPLEMENTED | LLM_RESPONDER | generic explanation allowed | MEDIUM |
| CODE_REVIEW_REQUEST | SPEC_REQUIRED_NOT_IMPLEMENTED | CLARIFICATION / LLM_RESPONDER | clarify when code missing | MEDIUM |
| CLARIFICATION_REQUEST | SPEC_REQUIRED_NOT_IMPLEMENTED | CLARIFICATION | ambiguous-reference handling | LOW |
| CONTINUE_REQUEST | SPEC_REQUIRED_NOT_IMPLEMENTED | CLARIFICATION | needs session/prior-task context | MEDIUM |
| FEEDBACK_STYLE_REQUEST | SPEC_REQUIRED_NOT_IMPLEMENTED | DIRECT_RESPONSE | acknowledge style preference (no durable store in P0) | LOW |
| UNSUPPORTED_OR_UNSAFE | SPEC_REQUIRED_NOT_IMPLEMENTED | SAFETY_GATE / UNSUPPORTED | safe refusal | MEDIUM |

---

## 10. Routing behavior

Handling modes:

```text
DIRECT_RESPONSE
MEMORY_FLOW
SIMPLE_TOOL_OR_CALCULATION
LLM_RESPONDER
CLARIFICATION
SAFETY_GATE
UNSUPPORTED
```

Examples:

```text
"Xin chào"                         → GREETING               → DIRECT_RESPONSE              → already first-pass
"1 + 1 ="                          → CALCULATION_REQUEST    → SIMPLE_TOOL_OR_CALCULATION   → already first-pass
"???"                              → UNKNOWN_RECOVERABLE    → CLARIFICATION/DIRECT_RESPONSE → already first-pass
"Bạn là ai?"                       → IDENTITY_QUERY         → DIRECT_RESPONSE              → not implemented
"Bạn làm được gì?"                 → CAPABILITY_QUERY       → DIRECT_RESPONSE              → not implemented
"Bạn đang nhớ gì về tôi?"          → MEMORY_READ            → MEMORY_FLOW                  → not implemented
"Hãy nhớ rằng..."                  → MEMORY_WRITE_REQUEST   → MEMORY_FLOW (confirm)        → not implemented
"Đừng dùng memory trong câu này"   → MEMORY_DISABLE_FOR_TURN→ DIRECT_RESPONSE/memory-policy→ not implemented
"Viết lại đoạn này"                → WRITING_REQUEST        → CLARIFICATION (content missing)→ not implemented
"Review đoạn code này"             → CODE_REVIEW_REQUEST    → CLARIFICATION (code missing) → not implemented
```

Routing is intercepted **before** the planner for command/meta/memory turns (mirrors the existing `/memory save-decision` and `/memory recall` interception in `cli.py`). It must never enter the planner for direct/clarification responses and must never invoke the LLMPlanner.

---

## 11. DirectResponder / ResponseComposer behavior

DirectResponder eventually handles: GREETING, IDENTITY_QUERY, CAPABILITY_QUERY, UNKNOWN_RECOVERABLE, CLARIFICATION_REQUEST, FEEDBACK_STYLE_REQUEST, CONTINUE_REQUEST (when prior context exists). It must:
- not hallucinate capabilities; state limitations plainly; not claim full autonomy or "no limits";
- give concrete usage examples for capability questions;
- produce deterministic, safe text (ResponseComposer shapes output; no raw stack/backend text).

---

## 12. Memory intent behavior

Memory responses must distinguish: **confirmed memory**, **assumption**, **unknown/missing**, **sensitive**, **forgotten/deleted**, **memory disabled for this turn**. Rules:
- Memory read uses the existing remote `run_memory_recall` (M7-B) — scoped by `project_id` + `user_id`; never fabricate provenance; surface `memory_id`/`evidence_ref`/`source_task_id` only when present.
- Memory write reuses the M7-A confirmed-write path with explicit confirmation UX; never silently persist.
- Memory delete/forget must require an exact target if ambiguous; **no delete contract exists in the Memory v1 wire today** — if delete requires a Memory contract change, that is a stop condition (§21), not a CONV-P0 action.
- `MEMORY_DISABLE_FOR_TURN` suppresses memory use for the current turn only and says so.

---

## 13. Generative LLMResponder behavior

LLMResponder (future, separate authorization) may serve: PLANNING_REQUEST, WRITING_REQUEST, SUMMARIZATION_REQUEST, TRANSLATION_REQUEST, PRODUCT_ANALYSIS_REQUEST, TECHNICAL_EXPLANATION_REQUEST, CODE_REVIEW_REQUEST. It must **not**: execute tools; write memory directly; change policy; change runtime state except through the approved output path; replace SafetyGate or MemoryRuntime; act as an LLMPlanner. When required content is missing (e.g. "review this code" with no code), the route is CLARIFICATION, not fabricated output.

---

## 14. Unknown / fallback behavior

Unknown input must not dead-end. Required style (already first-pass in `_unknown_plan`):

```text
Tôi chưa đủ ngữ cảnh để xử lý chính xác. Bạn muốn tôi giải thích, lập kế hoạch, tính toán, viết lại, review code, hay tiếp tục task trước?
```

Stabilization must never convert a genuine no-result/failure into a fabricated answer.

---

## 15. Safety and permission behavior

- All tool-bearing routes still pass `PolicyEngine` + `ApprovalGate`; CONV-P0 adds no new tool and no bypass.
- HIGH/CRITICAL-risk tools remain denied by policy; external/irreversible tools require approval.
- `UNSUPPORTED_OR_UNSAFE` → safe refusal (SAFETY_GATE/UNSUPPORTED), no raw error text.
- CONV-P0 does **not** implement SF2 (prompt-injection/trust boundary); a constrained LLMResponder must still treat retrieved memory/content as untrusted evidence per existing contracts.

---

## 16. Web UI considerations

The baseline Web API (`/api/chat`, `/api/memory/recall`) and React UI already expose chat + memory recall + provenance. CONV-P0 routing should be reachable through `/api/chat` (the adapter calls `handle_turn`); a P0 Web UI smoke path (§20 P0-8) should confirm greeting/identity/capability/calculation/memory-read render correctly. No Web UI/Web API code changes are authorized by this spec.

---

## 17. Acceptance dataset

The dataset lives at `tests/acceptance/conversation_p0_cases.yaml` (40 cases, DRAFT, `implementation_authorized: false`). Each case carries `current_status` ∈ {ALREADY_IMPLEMENTED_FIRST_PASS, SPEC_REQUIRED_NOT_IMPLEMENTED, SPEC_REQUIRED_PARTIAL, OUT_OF_SCOPE_FOR_CONV_P0}. The dataset is data-only in this task; a runner is future work (§20 P0-1). `must_include_any`/`must_not_include` are explicit string groups for P0; a future runner may add semantic groups.

---

## 18. Acceptance criteria

```text
AC-CONV-P0-01 baseline custody verified at 92adb97
AC-CONV-P0-02 spec created with DRAFT status
AC-CONV-P0-03 acceptance YAML created with 40 cases
AC-CONV-P0-04 already-implemented intents documented
AC-CONV-P0-05 intent taxonomy complete
AC-CONV-P0-06 routing modes defined
AC-CONV-P0-07 DirectResponder behavior specified
AC-CONV-P0-08 Memory intent behavior specified
AC-CONV-P0-09 LLMResponder vs LLMPlanner boundary specified
AC-CONV-P0-10 fallback is recoverable, not dead-end
AC-CONV-P0-11 calculation behavior reconciled with current implementation
AC-CONV-P0-12 safety/permission expectations specified
AC-CONV-P0-13 implementation phases defined
AC-CONV-P0-14 non-goals exclude SF2/M8/vector/RAG/self-improvement
AC-CONV-P0-15 regression passes
AC-CONV-P0-16 frontend typecheck/build passes or is explicitly skipped
AC-CONV-P0-17 forbidden-path audit zero
AC-CONV-P0-18 no merge/push
AC-CONV-P0-19 final report created
```

All AC must be PASS for CONV-P0 closure; each maps to a §17 dataset case or a structural/source inspection.

---

## 19. Test strategy

- **Acceptance dataset** (`conversation_p0_cases.yaml`) — data now; a future runner maps each case input → parser intent → handling mode and asserts `must_include_any`/`must_not_include`.
- **Unit** — parser/router/DirectResponder/memory-UX (rule-based; no real LLM in unit).
- **Integration** — memory intents against the M7-B recall path (mock transport; real in smoke).
- **Web smoke** — `/api/chat` round-trips for P0 intents.
- **Regression** — existing 633 Python suite + frontend typecheck/build must stay green.

---

## 20. Implementation phases

```text
P0-1 Acceptance dataset + runner
P0-2 Intent taxonomy reconciliation (extend IntentName without breaking existing)
P0-3 ConversationRouter + DirectResponder + ResponseComposer
P0-4 Identity + capability responses
P0-5 Memory UX intents (read/write/forget/disable) over M7-A/M7-B
P0-6 Clarification behavior for missing content (writing/summarize/translate/code-review/product)
P0-7 LLMResponder interface for generative tasks (constrained; not LLMPlanner)
P0-8 Web UI smoke path for P0 conversation
P0-9 Regression gate and closeout
```

Incremental order (first → later):

```text
First pass (already on main): GREETING, CALCULATION_REQUEST, UNKNOWN_RECOVERABLE
Second pass: IDENTITY_QUERY, CAPABILITY_QUERY, CLARIFICATION_REQUEST
Third pass: MEMORY_READ, MEMORY_WRITE_REQUEST, MEMORY_DELETE_REQUEST, MEMORY_DISABLE_FOR_TURN
Fourth pass: PLANNING/WRITING/SUMMARIZATION/TRANSLATION/TECHNICAL_EXPLANATION/PRODUCT_ANALYSIS/CODE_REVIEW (LLMResponder)
```

No phase may be implemented in this task. No later phase may weaken an earlier contract.

---

## 21. Stop conditions

Implementation must STOP and request architect review if any occurs:
1. CONV-P0 requires LLMPlanner.
2. CONV-P0 requires vector/semantic/RAG.
3. memory delete/forget requires a Memory Contract/wire change (no v1 delete contract exists).
4. a memory intent requires a TOMTIT-Memory code change.
5. routing requires bypassing PolicyEngine/ApprovalGate.
6. a generative response would execute tools or take external/irreversible action.
7. CONV-P0 would require SF2 to be safe.
8. CONV-P0 would require changing the M7-A/M7-B memory contracts or breaking existing tests.
9. CONV-P0 scope expands toward project resume / general long-term memory / autonomy.
10. CONV-P0 requires `.gitignore`/dependency/Web-API/Web-UI contract changes beyond additive intent code.

---

## 22. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Over-claiming capabilities in identity/capability answers | MEDIUM | DirectResponder must state limits; `must_not_include` guards in dataset |
| Memory answers fabricating provenance | MEDIUM | reuse M7-B output contract; surface only present fields |
| Scope creep into LLMPlanner / autonomy | HIGH | hard non-goals (§5) + stop conditions (§21) |
| Memory delete with no v1 contract | MEDIUM | clarify target; treat contract gap as stop condition |
| LLMResponder bypassing policy/safety | HIGH | LLMResponder cannot execute tools / change state except approved output |
| Clarification turning into hallucination | MEDIUM | missing content → CLARIFICATION, never fabricated output |
| Rule-parser ambiguity (e.g. greeting vs bare-math) | LOW | ordering already handled in `intent_parser` (greeting before bare-math) |
| README/doc drift vs baseline | LOW | recorded as documentation debt (§23); not fixed here |

No CRITICAL. The two HIGH risks (LLMPlanner/autonomy creep; LLMResponder bypassing safety) are bounded by non-goals + stop conditions.

---

## 23. Documentation debt

`[OBSERVED @ 92adb97, not fixed in this task]`:
- `README.md` still reports `586 passed` (current suite is **633 passed**) and references the M7-B closeout commit `41c2d92` rather than the current baseline `92adb97`. The README is otherwise current for the Web Chat UI.
- This is recorded as documentation debt for a later docs-only update; CONV-P0 spec-reissue does not modify README.

---

## 24. Final expected outcome

```text
SPEC WRITTEN (reissued against 92adb97)
IMPLEMENTATION NOT AUTHORIZED
```

CONV-P0, when implemented incrementally per §20, gives TOMTIT a safe, useful basic conversation experience: greetings, identity/capability answers, simple calculation, memory read/write/forget UX over M7-A/M7-B, clarification for under-specified generative requests, and a recoverable unknown fallback — all rule-routed, policy-gated, with a constrained LLMResponder for generative content and **no** LLMPlanner, vector retrieval, SF2, or autonomous actions. The next workflow step is architect spec review → (optional patch) → freeze → separate implementation instruction.

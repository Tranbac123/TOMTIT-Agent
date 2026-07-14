# ChangeGate Vertical MVP Slice 1 — Merge Eligibility Policy

Title: ChangeGate Vertical MVP Slice 1 — Merge Eligibility Policy
Status: DRAFT_FOR_OWNER_REVIEW
Owner: TranBac
Technical Author: Claude Code Fable 5
Independent Verification: PENDING
Baseline: 3e72e93bfac8da2ecdb7960a55ae0357135eb61e
Production Implementation: NOT_STARTED

> This document is a specification-and-contract artifact only. It defines the deterministic
> merge-eligibility policy contract for ChangeGate Slice 1. It implements nothing. It remains
> `DRAFT_FOR_OWNER_REVIEW` until TranBac explicitly accepts it; no model is an acceptance
> authority. Every semantic that the owner has not yet decided is marked
> `PENDING_OWNER_DECISION` in §25 and is NOT silently resolved here.

---

## 1. Context

ADR-001 (accepted) establishes ChangeGate as the first commercial wedge and records two
durable obligations:

- **FOLLOWUP-P0-9B1-002 / ADR-001 §7** — structural evidence verification
  (`EvidenceVerificationResult.accepted == True`, `VerificationStatus.VERIFIED`) is **not**
  authorization to merge. Merge eligibility is a separate policy decision.
- **FOLLOWUP-P0-9B1-001 / ADR-001 §8** — a schema-valid **empty** verification bundle is
  **not** evidence completeness. When evidence is required, the policy layer must enforce
  `required evidence ⊆ verified evidence`.

The current repository has two evidence generations inside `agent_core.build_harness`:

- **Slice 0 (P0-9A "ChangeGate Lite")** — `evaluate_change_gate()` over legacy
  `CommandEvidence` (command-string matching, commit-bound, exit-0). Its `PASS` is a
  structural scope/evidence check, not merge authority.
- **P0-9B1 domain layer** — `CandidateBinding`, `RepositorySnapshot`, `CommandRequirement`,
  `EvidenceProvenance`, `CollectedCommandEvidence`, `EvidenceVerificationResult`,
  `VerifiedCommandEvidence`, `EvidenceVerificationBundle`, `EvidenceRunRecord`, plus pure
  ports. The coupling audit confirms this vertical is represented but not yet executable
  end-to-end (no adapter from verified bundles into an eligibility decision).

This slice (1A) defines the **policy contract** that will sit on top of the P0-9B1 layer:
what `ELIGIBLE_TO_MERGE_UNDER_POLICY` means, exactly which facts it requires, its
deterministic reason-code precedence, its evaluation trace, its product event schema, and
its golden evaluation matrix. Slice 1-A2 (a later, separately approved task) implements the
pure evaluator.

## 2. Goals

1. Separate **structural evidence verification** from **merge eligibility under policy**,
   permanently and testably.
2. Define the narrowest deterministic **policy input** built from existing P0-9B1 contracts.
3. Define a typed **eligibility facts** layer between raw evidence and policy evaluation.
4. Define the authoritative **output contract** (disposition + reason codes + digests).
5. Define a stable, machine-readable **reason-code taxonomy** with deterministic precedence.
6. Define **required-evidence completeness** semantics (`required ⊆ verified`, stable
   requirement identifiers, never inferred from prose or display text).
7. Define **authority and override boundaries**: facts cannot be voted away by an approval.
8. Define a replayable **EvaluationTrace** returned as pure data.
9. Define the **product event schema** linking decisions to real user/CI/merge outcomes.
10. Define **privacy and redaction** rules for everything the policy emits.
11. Provide **golden evaluation cases** executable against the future evaluator.

## 3. Non-Goals

- No production eligibility evaluator is implemented in Slice 1A.
- No Git/subprocess/filesystem/network adapters; no GitHub App; no auto-merge.
- No Coordinator, Project Control, LLM integration, notification, dashboard, or vector DB.
- No change to any `agent_core/**` production file, contract, or schema version.
- No resolution of deferred owner decisions OD-G1-001 … OD-G1-007 (§24).
- No canonical kernel models (`ActorIdentity`, `ApprovalRecord`, `DecisionRecord`,
  `AuditEvent` remain `FUTURE_CONCEPT_NOT_IMPLEMENTED` per ADR-003).
- No self-improvement implementation; §20 records the controlled boundary only.

## 4. Existing Contract Inventory

Inventory taken against baseline `3e72e93` (all statuses verified by reading the modules):

| Symbol | Module | Semantic meaning | Authority level | Slice 1 reuse |
| --- | --- | --- | --- | --- |
| `TaskContract` | `build_harness/contracts.py` | What may change, what must be proven, what needs a human | Declarative source of requirements | REUSED as policy input (referenced by `contract_digest`) |
| `ContractValidationError` | `contracts.py` | Fail-loud contract validation | — | reused indirectly |
| `CommandEvidence` | `build_harness/change_gate.py` | Legacy Slice-0 evidence claim (command string + exit code + commit) | None (claim) | NOT reused for Slice 1 policy input; superseded by the P0-9B1 bundle. Remains for ChangeGate Lite |
| `ChangeGateInput` / `ChangeGateDecision` / `Finding` | `change_gate.py` | Structural scope/evidence gate; PASS/REVIEW_REQUIRED/BLOCK | Structural gate only — its `PASS` is NOT merge authority (ADR-001 §7) | Reused as an upstream structural check; its finding vocabulary informs scope facts. Not the eligibility output |
| `validate_change_gate_decision` | `change_gate.py` | Independent integrity re-check of a claimed PASS | Anti-forgery precedent | Pattern reused for decision-digest verification |
| `ProcessGuardInput` / `ProcessGuardDecision` / `IntendedAction` | `build_harness/process_guard.py` | Workflow-completeness guard; `human_approved: bool` | Process authority (ship states, hard approval gates) | Adjacent, unchanged. Slice 1 does not replace ProcessGuard; eligibility is a distinct decision |
| `TaskState` / `TaskEvent` / `transition` | `build_harness/state.py` | Deterministic task state machine | Workflow authority | Unchanged; referenced by outcome linkage only |
| `AgentReport` / `parse_agent_report` | `build_harness/reports.py` | Fail-closed report ingestion | None | Not a policy input (report prose can never satisfy evidence, §11) |
| `CandidateBinding` | `build_harness/repository_models.py` | Immutable candidate identity (repo, format, base, commit, tree, contract digest, changed-files digest) | Identity fact | REUSED verbatim |
| `RepositorySnapshot` | `repository_models.py` | Immutable observed repository state incl. `is_release_clean` | Observed fact | REUSED verbatim |
| `CommandRequirement` | `repository_models.py` | One required command with **stable `requirement_id`** and canonical `command_digest` | Requirement declaration | REUSED verbatim — the stable requirement identifier of §11 |
| `candidate_snapshot_mismatches` | `repository_models.py` | Single coherent-context rule | — | REUSED as the freshness primitive (§12) |
| `EvidenceProvenance` / `CollectedCommandEvidence` | `build_harness/provenance.py` | Collected command evidence bound to task/run/candidate/snapshots | Collected fact | REUSED verbatim |
| `EvidenceVerificationResult` / `VerificationStatus` | `provenance.py` | Structural verification result; `accepted ⇔ VERIFIED`; exclusive rejected-context matrix | Structural verification only | REUSED verbatim; source of invalid-evidence facts |
| `VerifiedCommandEvidence` | `provenance.py` | Digest-bound proof that one requirement was structurally verified for one candidate | Structural verification only | REUSED verbatim; source of verified-evidence facts |
| `EvidenceVerificationBundle` | `provenance.py` | One coherent verified/rejected set for one task+candidate, digest-sealed | Structural verification only | REUSED verbatim as the policy input's verification bundle |
| `EvidenceVerificationRequest` / `EvidenceRunRecord` | `build_harness/ports.py` | Pure verifier request; immutable run membership record | — | REUSED upstream of policy; run membership backs `EVIDENCE_RUN_MISMATCH` facts |
| `Outcome` / `Unit` / `StorageError` | `ports.py` | Typed success/failure | — | REUSED by future A2 application layer |
| `canonical_digest` / canonical validators | `build_harness/canonical.py` | Deterministic canonical JSON digests | — | REUSED for input/decision/trace digests |
| `NextAction` / `recommend_next_action` | `build_harness/next_action.py` | Operator recommendation | None | Unchanged consumer |
| CLI | `build_harness/cli.py` | Standalone JSON path (ADR-002 §8) | — | Unchanged in 1A; A2 proposes a subcommand |
| Approval / actor identity | NOT_FOUND in `build_harness` (searched; `agent_core/safety/approval.py` is runtime tool-gating, a different domain per ADR-003) | — | — | MISSING → new application facts (§5, §14) |
| Policy version / policy digest | NOT_FOUND (searched `policy_version`, `reason_code`, `ActorIdentity`, `ApprovalRecord` across `agent_core`) | — | — | MISSING → new `PolicyContextFact` (§5) |
| Event / trace / evaluation / audit models | NOT_FOUND (`AuditEvent`, `DecisionRecord` are `FUTURE_CONCEPT_NOT_IMPLEMENTED` per ADR-003 §5) | — | — | MISSING → schema artifact + trace contract (§18, §19), no kernel model minted |

**Duplicate-model rule honored:** no concept above gets a second canonical model. Every new
concept in §5 is a ChangeGate-local application DTO, explicitly non-canonical, and is
adapter-suppliable without modifying any existing domain model.

## 5. Policy Input

The future pure evaluator consumes exactly one immutable input,
**`MergeEligibilityPolicyInput`** (application DTO, ChangeGate-scoped, to be defined in A2 —
named here as a contract, not created as code). It embeds no Git execution, filesystem,
network, clock, or model call; every field is an explicit fact supplied by the caller.

| Field | Type (existing unless marked NEW) | Binds |
| --- | --- | --- |
| `task_id` | validated task id | task identity |
| `contract` | `TaskContract` | the governing contract |
| `contract_digest` | sha256 over `contract_to_dict` canonical payload | contract version identity; must equal `candidate_binding.contract_digest` |
| `candidate_binding` | `CandidateBinding` | candidate identity |
| `current_snapshot` | `RepositorySnapshot` | current repository state at evaluation time |
| `required_evidence` | `tuple[CommandRequirement, ...]` | required evidence declarations with stable `requirement_id`s |
| `verification_bundle` | `EvidenceVerificationBundle` | structural verification facts |
| `run_id` | validated generated id | the evidence run the bundle claims (cross-checked against `EvidenceRunRecord` by the application layer) |
| `scope_facts` | NEW `ScopeFacts` | scope evaluation facts (§13): status + violating/uncertain paths |
| `approval_fact` | NEW `ApprovalFact \| None` | approval facts (§14) |
| `authority_fact` | NEW `AuthorityFact` | caller authority facts (§14) |
| `verifier_fact` | NEW `VerifierIndependenceFact` | verifier identity + independence facts (§15) |
| `policy_context` | NEW `PolicyContextFact` | policy id, version, digest, currency |
| `evaluation_mode` | NEW enum `ENFORCE \| SHADOW` | SHADOW evaluations never authorize anything and must be marked in trace and events |

For every proposed NEW concept:

| New concept | Why existing contracts are insufficient | ChangeGate-specific? | Temporary application DTO? | Adapter-suppliable without touching canonical models? |
| --- | --- | --- | --- | --- |
| `ScopeFacts` | `ChangeGateDecision` mixes scope findings with legacy evidence findings and is an output, not a typed input fact | Yes | Yes — until a kernel policy vocabulary exists | Yes — derived from `evaluate_change_gate` findings + contract paths |
| `ApprovalFact` | No approval record exists anywhere; `ProcessGuardInput.human_approved` is an unattributed bool with no target binding or freshness; `ApprovalRecord` is kernel-future (ADR-003) and may not be minted here (OD-G1-004 adjacent) | Yes (binds to candidate digests) | Yes — explicitly NOT the canonical `ApprovalRecord` | Yes — application layer records approvals and supplies the fact |
| `AuthorityFact` | No `ActorIdentity` exists; `Capability` ownership is unresolved (OD-G1-003) — so authority is expressed as opaque actor/role references + validity status, never as a capability model | Yes | Yes | Yes |
| `VerifierIndependenceFact` | `EvidenceVerificationResult.verifier_version` identifies software, not actor independence | Yes | Yes | Yes |
| `PolicyContextFact` | No policy-version concept exists in the repository | Yes | Yes | Yes |
| `EligibilityFacts` (§6) | Nothing maps raw contracts to policy-consumable facts | Yes | Yes | Yes — pure derivation |
| `MergeEligibilityDecision` (§7) | `ChangeGateDecision` is structural and its vocabulary (`PASS`) is explicitly not merge authority | Yes | Yes | n/a (evaluator output) |
| `EvaluationTrace` (§18) | No trace/audit model exists | Yes (v1) | Yes — `AuditEvent` remains kernel-future | n/a (evaluator output) |

Deferred-decision guard: none of these DTOs generalizes `TaskContract` (OD-G1-001), creates
a second `TaskState` or overloads execution status with eligibility (OD-G1-002 — eligibility
is a separate decision object, exactly the three-axis separation of ADR-003 §9), claims the
canonical `Capability` (OD-G1-003), or mints a canonical `DecisionRecord` (OD-G1-004).

## 6. Eligibility Facts

A typed conceptual layer, **`EligibilityFacts`**, sits between raw contracts and policy
evaluation. The A2 application vertical derives these facts deterministically from the
policy input; the evaluator consumes only facts. **Facts grant no authority by themselves**
— they are observations; only the policy maps facts to a disposition.

| Fact | Values | Derived from |
| --- | --- | --- |
| `task_context_current` | `CURRENT \| STALE \| UNKNOWN` | contract digest vs candidate `contract_digest`; task id consistency across input |
| `candidate_binding_current` | `CURRENT \| STALE \| UNKNOWN` | `candidate_snapshot_mismatches(candidate, current_snapshot)` restricted to commit/tree/changed-files divergence in the same repository (§12) |
| `repository_snapshot_current` | `CURRENT \| MISMATCH \| UNKNOWN` | repository/object-format/base divergence (§12) |
| `repository_release_clean` | `CLEAN \| DIRTY \| UNKNOWN` | `current_snapshot.is_release_clean` |
| `required_evidence_ids` | sorted unique tuple of `requirement_id` | `required_evidence` declarations |
| `verified_evidence_ids` | sorted unique tuple of `requirement_id` | bundle `verified` entries bound to this task/run/candidate |
| `missing_evidence_ids` | sorted unique tuple | `required − verified` (§11) |
| `invalid_evidence_ids` | sorted unique tuple | required ids whose only matching records were rejected (§11) |
| `unexpected_evidence_ids` | sorted unique tuple | `verified − required` (§11; treatment PENDING_OWNER_DECISION OD-S1A-006) |
| `evidence_context_coherent` | `true \| false \| UNKNOWN` + violation tags `TASK_MISMATCH, RUN_MISMATCH, CANDIDATE_MISMATCH, PROVENANCE_INVALID, DUPLICATE_IDENTITY` | bundle/run-record identity checks (the P0-9B1 models make most incoherence unrepresentable; the facts layer records any presented incoherence instead of trusting the caller) |
| `scope_status` | `IN_SCOPE \| VIOLATION \| UNCERTAIN \| UNKNOWN` | `ScopeFacts` (§13) |
| `approval_status` | `VALID \| MISSING \| STALE \| UNKNOWN` | `ApprovalFact` (§14) |
| `authority_status` | `VALID \| INVALID \| UNKNOWN` | `AuthorityFact` (§14) |
| `verifier_independence_status` | `INDEPENDENT \| NOT_INDEPENDENT \| UNKNOWN` | `VerifierIndependenceFact` (§15) |
| `policy_context_current` | `CURRENT \| STALE \| UNKNOWN` | `PolicyContextFact` |

**Mandatory-context rule (explicit, per golden case 19):** every fact above is mandatory.
`UNKNOWN` never defaults toward eligibility. `UNKNOWN` on an integrity fact
(`task_context_current`, `candidate_binding_current`, `repository_snapshot_current`,
`repository_release_clean`, `evidence_context_coherent`, `authority_status`,
`policy_context_current`, or any evidence id set underivable) emits
`REQUIRED_CONTEXT_INCOMPLETE` → BLOCK. `UNKNOWN` on the two policy-designated semantic facts
maps to their dedicated reviewable codes: `scope_status = UNKNOWN` → `SCOPE_UNCERTAIN`
(REVIEW_REQUIRED) and `verifier_independence_status = UNKNOWN` →
`VERIFIER_INDEPENDENCE_UNKNOWN` (REVIEW_REQUIRED, boundary PENDING_OWNER_DECISION
OD-S1A-003). `approval_status = UNKNOWN` is treated as `MISSING` (recommended; disposition
of missing approval itself is PENDING_OWNER_DECISION OD-S1A-001).

## 7. Policy Output

The evaluator returns exactly one immutable **`MergeEligibilityDecision`**:

| Field | Authoritative? | Meaning |
| --- | --- | --- |
| `disposition` | **AUTHORITATIVE** | exactly one of §8's three values |
| `primary_reason_code` | **AUTHORITATIVE** | deterministic primary reason (`null` only when eligible) |
| `complete_reason_codes` | **AUTHORITATIVE** | every independently confirmed reason, sorted lexicographically |
| `blocking_reason_codes` | **AUTHORITATIVE** | subset of complete set with effective disposition BLOCK |
| `review_reason_codes` | **AUTHORITATIVE** | subset with effective disposition REVIEW_REQUIRED |
| `required_evidence_ids` | **AUTHORITATIVE** | requirement ids the policy demanded |
| `verified_evidence_ids` | **AUTHORITATIVE** | requirement ids satisfied by verified evidence |
| `missing_evidence_ids` | **AUTHORITATIVE** | required ids with no verified record |
| `invalid_evidence_ids` | **AUTHORITATIVE** | required ids whose only matching records were rejected |
| `task_id`, `candidate_binding` | **AUTHORITATIVE** | what this decision is about |
| `policy_id`, `policy_version`, `policy_digest` | **AUTHORITATIVE** | which policy decided |
| `evaluation_trace_id` | **AUTHORITATIVE** | link to the trace (§18) |
| `evaluator_version` | **AUTHORITATIVE** | evaluator software identity |
| `evaluation_mode` | **AUTHORITATIVE** | ENFORCE or SHADOW; SHADOW never authorizes |
| `input_digest` | **AUTHORITATIVE** | canonical digest of the full policy input |
| `decision_digest` | **AUTHORITATIVE** | canonical digest over all authoritative fields excluding itself (same self-excluding pattern as `VerifiedCommandEvidence`) |
| `unexpected_evidence_ids` | diagnostic | never blocks alone in v1 (OD-S1A-006) |
| `explanations` | diagnostic | user-facing prose per reason code; NEVER the reason identity (§9) |
| `fact_summary` | diagnostic | the `EligibilityFacts` values used |

**Authority boundary:** only the pure evaluator may author a `MergeEligibilityDecision`
whose `decision_digest` verifies. Any consumer (ProcessGuard-equivalent, CLI, CI adapter)
must recompute and verify `decision_digest` and reject a decision that fails, exactly as
`validate_change_gate_decision` refuses a hand-constructed PASS today (golden case 24).
A caller-authored "eligible" object without a verifying digest is `AUTHORITY_INVALID`.

## 8. Disposition Semantics

The authoritative disposition is exactly one of:

- `ELIGIBLE_TO_MERGE_UNDER_POLICY` — every mandatory fact is present and green, required
  evidence is complete under §11, and the complete reason set is empty. Eligibility is a
  policy statement, not a safety guarantee, and it does not itself merge anything; merge
  execution remains a human-approved action (ProcessGuard path unchanged).
- `REVIEW_REQUIRED` — no blocking reason exists, but at least one policy-defined semantic
  uncertainty requires a human review to resolve (§17).
- `BLOCK` — at least one blocking reason exists. Fail-closed.

Forbidden output terms (ADR-001 §5): `SAFE_TO_MERGE` and `VERIFIED_AND_MERGE` must never
appear as output values; structural `PASS` is never an authority result; `accepted=True` is
never merge authorization. A genuinely eligible decision has an **empty** complete reason
set — mirroring today's rule that a genuine ChangeGate `PASS` has no findings.

Decision rule (total, deterministic):

```
if blocking_reason_codes non-empty        → BLOCK
elif review_reason_codes non-empty        → REVIEW_REQUIRED
else                                      → ELIGIBLE_TO_MERGE_UNDER_POLICY
```

## 9. Reason-Code Taxonomy

Reason codes are stable machine-readable identifiers matching `^[A-Z][A-Z0-9_]*$`. The code
IS the canonical identity; user-facing prose lives only in diagnostic `explanations` and may
change without a policy version bump. Codes are never renamed in place — a semantic change
requires a new code and a policy version bump.

Legend — Category: INTEGRITY (identity/authority/provenance facts), FRESHNESS,
EVIDENCE, REPO_STATE, SCOPE, APPROVAL, INDEPENDENCE, CONTEXT. Kind: FACTUAL (observable,
binary given the input) or SEMANTIC (policy-interpreted). Override: per §17 classes.

| Rank | Code | Category | Kind | Default disposition | Overrideable | Minimum evidence to emit | Explanation intent |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | `AUTHORITY_INVALID` | INTEGRITY | FACTUAL | BLOCK | NOT_OVERRIDEABLE | `authority_status = INVALID`, or a presented decision whose digest fails verification | "The caller or presented decision does not carry valid authority." |
| 20 | `REQUIRED_CONTEXT_INCOMPLETE` | CONTEXT | FACTUAL | BLOCK | NOT_OVERRIDEABLE | any integrity-mandatory fact of §6 UNKNOWN/underivable | "The policy could not obtain a mandatory fact; eligibility cannot be evaluated." |
| 30 | `EVIDENCE_TASK_MISMATCH` | INTEGRITY | FACTUAL | BLOCK | NOT_OVERRIDEABLE | an evidence/bundle element whose `task_id` ≠ input `task_id` | "Evidence belongs to a different task." |
| 40 | `EVIDENCE_RUN_MISMATCH` | INTEGRITY | FACTUAL | BLOCK | NOT_OVERRIDEABLE | evidence whose `run_id` ≠ the input run | "Evidence belongs to a different evidence run." |
| 50 | `EVIDENCE_CANDIDATE_MISMATCH` | INTEGRITY | FACTUAL | BLOCK | NOT_OVERRIDEABLE | evidence bound to a different `CandidateBinding` | "Evidence was produced for a different candidate." |
| 60 | `REPOSITORY_CONTEXT_MISMATCH` | INTEGRITY | FACTUAL | BLOCK | NOT_OVERRIDEABLE | `repository_snapshot_current = MISMATCH` (repository id / object format / base divergence) | "The current repository is not the one the candidate belongs to." |
| 70 | `EVIDENCE_PROVENANCE_INVALID` | INTEGRITY | FACTUAL | BLOCK | NOT_OVERRIDEABLE | a rejected result with status `INVALID_PROVENANCE`/`UNSUPPORTED_SCHEMA`/`UNSUPPORTED_COLLECTOR`, or coherence tag `PROVENANCE_INVALID` | "Evidence provenance is invalid or unsupported." |
| 80 | `EVIDENCE_DUPLICATE_IDENTITY` | INTEGRITY | FACTUAL | BLOCK | NOT_OVERRIDEABLE | duplicate evidence identity presented (`DUPLICATE_IDENTITY` status or tag) | "Evidence identity is ambiguous." |
| 90 | `REQUIRED_EVIDENCE_INVALID` | EVIDENCE | FACTUAL | BLOCK | POLICY_EXCEPTION_REQUIRED | a required id in `invalid_evidence_ids` | "A required proof exists but failed structural verification." |
| 100 | `CANDIDATE_STALE` | FRESHNESS | FACTUAL | BLOCK | POLICY_EXCEPTION_REQUIRED | `candidate_binding_current = STALE` | "The repository moved past this candidate; re-run against the current head." |
| 110 | `POLICY_CONTEXT_STALE` | FRESHNESS | FACTUAL | BLOCK | POLICY_EXCEPTION_REQUIRED | `policy_context_current = STALE` | "The decision would be made under an outdated policy." |
| 120 | `REQUIRED_EVIDENCE_MISSING` | EVIDENCE | FACTUAL | BLOCK | POLICY_EXCEPTION_REQUIRED | a required id in `missing_evidence_ids` (includes the empty-bundle-with-requirements case, ADR-001 §8) | "A required proof was never verified for this candidate." |
| 130 | `RELEASE_STATE_NOT_CLEAN` | REPO_STATE | FACTUAL | BLOCK | POLICY_EXCEPTION_REQUIRED | `repository_release_clean = DIRTY` | "The working tree is not release-clean." |
| 140 | `SCOPE_VIOLATION` | SCOPE | FACTUAL | BLOCK | POLICY_EXCEPTION_REQUIRED (contract amendment path) | `scope_status = VIOLATION` (forbidden path touched or explicit out-of-contract change) | "The change touches paths the contract forbids or does not allow." |
| 150 | `APPROVAL_MISSING` | APPROVAL | FACTUAL | BLOCK (recommended; PENDING_OWNER_DECISION OD-S1A-001) | HUMAN_REVIEW_RESOLVABLE (by granting the approval itself) | `approval_status = MISSING` while the contract requires approval for merge | "The required human approval has not been granted." |
| 160 | `APPROVAL_STALE` | APPROVAL | FACTUAL | BLOCK (recommended; PENDING_OWNER_DECISION OD-S1A-002) | HUMAN_REVIEW_RESOLVABLE (by re-approving the current candidate) | `approval_status = STALE` (approval bound to a different candidate/contract/policy digest) | "The approval was for a different version of this change." |
| 170 | `VERIFIER_NOT_INDEPENDENT` | INDEPENDENCE | FACTUAL | BLOCK | NOT_OVERRIDEABLE | `verifier_independence_status = NOT_INDEPENDENT` (verifier actor == implementer actor, or attested dependence) | "The change was verified by its own author." |
| 180 | `SCOPE_UNCERTAIN` | SCOPE | SEMANTIC | REVIEW_REQUIRED | HUMAN_REVIEW_RESOLVABLE | `scope_status = UNCERTAIN` (§13) | "A human must judge whether this change is within the contract's intent." |
| 190 | `VERIFIER_INDEPENDENCE_UNKNOWN` | INDEPENDENCE | SEMANTIC | REVIEW_REQUIRED (boundary PENDING_OWNER_DECISION OD-S1A-003) | HUMAN_REVIEW_RESOLVABLE | `verifier_independence_status = UNKNOWN` with verifier identity present | "Independence could not be established automatically; a human must confirm it." |

Exactly 19 codes. The set is closed for policy v1: an evaluator may not invent codes, and an
unknown code in a presented decision fails digest verification.

## 10. Deterministic Precedence

- The **primary reason** is the emitted code with the **lowest rank** in §9's table. Ranks
  are unique per code, so the primary reason is total and deterministic.
- The **complete reason set** contains every independently confirmed failure, sorted
  **lexicographically by code** (set semantics; independent of input ordering, dictionary
  or set iteration order, and evidence arrival order).
- A code appears at most once regardless of how many facts triggered it; per-instance
  detail (which ids, which paths) lives in the trace and diagnostics.
- The rank table refines the required general ordering as follows, with rationale:
  1. invalid authority / incoherent identity → ranks 10–20 (`AUTHORITY_INVALID`,
     `REQUIRED_CONTEXT_INCOMPLETE`: an evaluation whose own inputs or caller cannot be
     trusted outranks everything else);
  2. task/candidate/repository context mismatch → ranks 30–60;
  3. invalid or foreign evidence provenance → ranks 70–90 (duplicate identity ranked with
     provenance because it is an evidence-identity integrity failure);
  4. stale candidate or policy context → ranks 100–110;
  5. missing mandatory evidence → rank 120;
  6. non-release-clean repository → rank 130;
  7. explicit scope violation → rank 140;
  8. approval missing or stale → ranks 150–160;
  9. verifier independence failure → rank 170;
  10. reviewable semantic uncertainty → ranks 180–190 (`SCOPE_UNCERTAIN` before
      `VERIFIER_INDEPENDENCE_UNKNOWN`, mirroring the scope-before-independence order of
      the factual groups).
- Within group 2 the order task → run → candidate → repository is the narrowing order of
  identity (most specific foreign-ness first); within group 3, provenance invalidity
  precedes duplicate identity precedes invalid-but-matching evidence because it moves from
  "cannot trust the record" to "cannot trust its result". These refinements are explicit
  policy choices; changing them requires a policy version bump. The exact precedence when
  two *integrity* failures coexist is additionally listed as OD-S1A-007 for owner
  confirmation.
- **Unknown mandatory facts never default to eligible** (§6 mandatory-context rule).

## 11. Required Evidence Completeness

Normative rule (ADR-001 §8):

```
required evidence  ⊆  valid verified evidence bound to the current task, run and candidate
```

- **Matching key:** the stable `requirement_id` — `CommandRequirement.requirement_id` on the
  declaration side, `VerifiedCommandEvidence.requirement_id` on the proof side. A verified
  record counts only when its task/run/candidate bindings equal the policy input's (the
  bundle and run-record models already seal this; the policy re-checks rather than trusts).
- Completeness is **never** inferred from: command display text, command order, report
  prose, `tests_run` strings, filenames, or `accepted=True` alone.
- A **schema-valid empty bundle** is not inherently invalid; it simply verifies nothing.
  With a non-empty requirement set it yields `REQUIRED_EVIDENCE_MISSING` for every required
  id. With an empty requirement set, emptiness alone contributes no reason code (golden
  case 20) — eligibility then depends only on the other policy conditions.

Defined behaviors:

| Situation | Behavior |
| --- | --- |
| Duplicate evidence identities | `EVIDENCE_DUPLICATE_IDENTITY` (BLOCK); ambiguous identity satisfies nothing (same rule as ChangeGate Lite and `VerificationStatus.DUPLICATE_IDENTITY`) |
| Multiple verified records satisfying one requirement | Requirement is satisfied (≥ 1 rule); surplus is recorded in the trace, not a failure |
| One evidence record claiming multiple requirements | Unrepresentable at the domain layer (`EvidenceProvenance.requirement_id` is single-valued); if presented through any adapter it is `EVIDENCE_PROVENANCE_INVALID` |
| Unexpected evidence (verified id ∉ required set) | Recorded in `unexpected_evidence_ids` (diagnostic); never satisfies anything and, recommended, never blocks alone — treatment PENDING_OWNER_DECISION OD-S1A-006 |
| Partially verified bundle (rejected entries present) | Rejected entries satisfy nothing. A required id with at least one matching rejected record and no verified record → `REQUIRED_EVIDENCE_INVALID`; with no record at all → `REQUIRED_EVIDENCE_MISSING` |
| Evidence from another task / run / candidate | `EVIDENCE_TASK_MISMATCH` / `EVIDENCE_RUN_MISMATCH` / `EVIDENCE_CANDIDATE_MISMATCH` (BLOCK); it also never satisfies a requirement |

## 12. Candidate and Repository Freshness

Freshness is evaluated with the existing single-source rule
`candidate_snapshot_mismatches(candidate_binding, current_snapshot)`:

- `repository_id` or `object_format` or `base_commit_sha` divergence →
  `repository_snapshot_current = MISMATCH` → `REPOSITORY_CONTEXT_MISMATCH` (the evaluation
  is happening against the wrong repository lineage);
- same repository lineage but `head_commit_sha` ≠ `candidate_commit_sha`, or tree, or
  changed-files digest divergence → `candidate_binding_current = STALE` → `CANDIDATE_STALE`
  (the repository moved past the candidate; evidence and eligibility must be re-established
  against the new head);
- `current_snapshot.is_release_clean == False` → `RELEASE_STATE_NOT_CLEAN`, even when every
  structural verification is `VERIFIED` (golden case 22; ADR-001 §7);
- `policy_context.current == False` → `POLICY_CONTEXT_STALE` — a decision may not be issued
  under a policy version the deployment no longer considers current.

The policy never calls Git to check freshness; the caller supplies the current snapshot,
and the decision is valid only for the snapshot identity recorded in its trace.

## 13. Scope Semantics

`ScopeFacts` carries the outcome of deterministic scope evaluation (the existing
canonicalized-path, forbidden-before-allowed rules of `evaluate_change_gate` remain the
mechanism; ChangeGate Lite findings map into facts):

- `VIOLATION` (→ `SCOPE_VIOLATION`, BLOCK): a changed path matches a forbidden pattern, is
  an invalid/traversal path, or falls outside `allowed_paths` when the contract does not
  allow broad scope. Factual: the paths and patterns are explicit.
- `UNCERTAIN` (→ `SCOPE_UNCERTAIN`, REVIEW_REQUIRED): policy-defined semantic uncertainty —
  e.g. dependency-file changes the contract routes to a human, an empty change set, or a
  contract marked `broad_scope_allowed` where breadth itself demands human judgment.
- `IN_SCOPE`: neither of the above.
- `UNKNOWN` → treated as `UNCERTAIN` is **not** allowed for the violation check itself: if
  changed files could not be determined at all, that is `REQUIRED_CONTEXT_INCOMPLETE`
  (integrity), not a semantic review.

Scope facts must be derived from the same canonical path normalization as ChangeGate Lite
(no second path grammar).

## 14. Approval and Authority

No canonical `ApprovalRecord` or `ActorIdentity` exists (ADR-003), and Slice 1 does not
create one. The application-level facts are:

- **`ApprovalFact`** — an explicit, attributable approval statement: opaque
  `approver_actor_ref`, `approved_at` (caller-supplied timestamp), `approval_digest`, and
  the **binding target**: `task_id`, `candidate_commit_sha`/`candidate_tree_sha` (or the
  full `CandidateBinding` digest), `contract_digest`, `policy_digest`. An approval is:
  - `VALID` — binds exactly to the input task/candidate/contract/policy;
  - `STALE` — exists but binds to a different candidate, contract digest, or policy digest
    (approving commit A never approves commit B);
  - `MISSING` — absent while `"merge" ∈ contract.requires_human_approval_for`.
  When the contract does **not** require approval for merge, `approval_status = VALID`
  vacuously and no approval code is emitted (the ProcessGuard `READY_FOR_MERGE` path is
  unchanged).
- **`AuthorityFact`** — who requests evaluation and who may consume the decision: opaque
  `actor_ref`, `role_ref`, and a validity status computed by the application layer. The
  policy consumes only the status; it never interprets role semantics (that is a future
  kernel concern, OD-G1-003).

Dispositions for `APPROVAL_MISSING` and `APPROVAL_STALE` are recommended BLOCK but are
**PENDING_OWNER_DECISION** (OD-S1A-001, OD-S1A-002; §25). The golden fixture encodes the
recommended default and marks both cases `owner_decision_pending`.

## 15. Verifier Independence

`VerifierIndependenceFact` records: opaque `verifier_actor_ref`, opaque
`implementer_actor_ref`, verifier software identity (`verifier_version`), and an
independence status:

- `INDEPENDENT` — attested distinct actors (and, when configured, distinct execution
  environments);
- `NOT_INDEPENDENT` — verifier and implementer are the same actor, or dependence is
  attested → `VERIFIER_NOT_INDEPENDENT`, BLOCK, non-overrideable by ordinary approval
  (self-verification is a protected root-of-trust rule, ADR-001 §9);
- `UNKNOWN` — identity present but independence not attested →
  `VERIFIER_INDEPENDENCE_UNKNOWN`, REVIEW_REQUIRED (recommended; exact reviewability
  boundary PENDING_OWNER_DECISION OD-S1A-003). If even the verifier identity is absent,
  that is `REQUIRED_CONTEXT_INCOMPLETE`, not reviewable uncertainty.

The structural verifier (`EvidenceVerifier` port) remains independent of the policy
evaluator: the policy consumes its bundle output and never re-implements structural
verification, and the evaluator must not be the component that produced the evidence.

## 16. Multiple-Failure Behavior

When multiple failures coexist:

- every independently confirmed failure appears in `complete_reason_codes` (lexicographic
  order);
- exactly one `primary_reason_code` is selected by rank (§10);
- `blocking_reason_codes` / `review_reason_codes` partition the complete set by each code's
  effective disposition under the active policy version;
- the disposition is computed from the partition (§8) — a reviewable code never dilutes a
  blocking code;
- determinism guarantees: no dependence on dict/set iteration order; set-typed inputs are
  canonically sorted before evaluation; two runs over the same input digest must produce
  byte-identical decisions (same `decision_digest`).

Golden case 21 pins this behavior.

## 17. Human Override Boundaries

**Factual integrity failures cannot be overridden by an ordinary approval action.** Wrong
candidate, invalid provenance, foreign task/run evidence, invalid authority, corrupt
identity binding, duplicate evidence identity, repository mismatch — no approval, review, or
feedback changes these facts (override class NOT_OVERRIDEABLE in §9).

A policy **requirement** (e.g. which evidence is required, whether a dirty tree may ever
ship) may change only through:

- a separately authorized **policy exception** — explicit, versioned, attributable to an
  authorized actor, time-bounded where applicable, bound to a specific task+candidate, and
  recorded in the evaluation trace and events (exception authority and expiry are
  PENDING_OWNER_DECISION OD-S1A-005);
- a **new policy version**; or
- an explicit **owner-approved contract amendment**.

A human review may resolve **policy-defined semantic uncertainty** (`SCOPE_UNCERTAIN`,
`VERIFIER_INDEPENDENCE_UNKNOWN`, and the approval-granting acts themselves) — it resolves
the question, it does not rewrite facts, and the resolution is recorded as a
`CHANGEGATE_REVIEW_OVERRIDDEN` event referencing the original decision. The original
decision and trace are immutable; an override produces a new decision context, never an
edit.

## 18. EvaluationTrace

Every future policy evaluation produces a structured, immutable **EvaluationTrace**. The
pure evaluator **returns the trace as data**; it never writes to SQLite, JSONL, network
telemetry, or a global logger — persistence is an application-layer duty behind a port.
Whether strict deployments must require successful trace persistence **before** a decision
may authorize eligibility is PENDING_OWNER_DECISION OD-S1A-004.

Minimum trace fields:

| Field | Content |
| --- | --- |
| `trace_id`, `evaluation_id`, `request_id` | identities (caller-supplied or application-generated; never generated inside the pure evaluator) |
| `timestamp` | caller-supplied (the evaluator has no clock) |
| `task_id`, `task_contract_digest` | task binding |
| `candidate_digest` | canonical digest of `CandidateBinding` |
| `repository_snapshot_digest` | canonical digest of the current snapshot |
| `verification_bundle_digest` | `EvidenceVerificationBundle.bundle_digest` |
| `policy_id` / `policy_version` / `policy_digest` | policy binding |
| `approval_digest` | present when an approval fact was supplied |
| `actor_ref`, `verifier_ref` | opaque identity references (never emails/names) |
| `disposition`, `primary_reason_code`, `complete_reason_codes` | outcome |
| `required/verified/missing/invalid_evidence_ids` | evidence accounting |
| `evaluation_mode` | ENFORCE / SHADOW |
| `evaluator_version`, `input_digest`, `decision_digest` | replay identity |
| `evaluation_latency_ms` | supplied by the application layer (pure evaluator cannot time itself) |
| `redaction_classification` | privacy class of the trace payload (§21) |

Three layers are distinguished and must not be conflated:

1. **deterministic policy trace** (this contract) — replayable from digests and reason
   codes without raw source code, command output, or secrets;
2. **application telemetry** (latency, sink health, retries) — owned by the application
   layer, references `trace_id`;
3. **raw debug logs** — never part of the contract, never required for replay, and subject
   to §21 redaction.

Replay property: given the same `input_digest` and `policy_digest`, an evaluator of the
same `evaluator_version` must reproduce the same `decision_digest`.

## 19. Product Event Schema

Artifact: `data/schemas/changegate_evaluation_event_v1.schema.json` (JSON Schema, fixed
`schema_version` const `changegate-evaluation-event.v1`). The envelope is sink-agnostic
(later JSONL, SQLite, or remote sinks consume the same shape).

Event types (closed set for v1):

`CHANGEGATE_EVALUATION_COMPLETED`, `CHANGEGATE_REVIEW_OVERRIDDEN`,
`CHANGEGATE_MERGE_ATTEMPTED`, `CHANGEGATE_MERGE_COMPLETED`,
`CHANGEGATE_POST_MERGE_VALIDATION`, `CHANGEGATE_ROLLBACK_RECORDED`,
`CHANGEGATE_USER_FEEDBACK_RECORDED`.

Envelope fields: `event_id`, `event_type`, `occurred_at`, `schema_version`, `product`
(const `"changegate"`), `project_ref`/`task_ref`/`run_ref`, `subject_ref` (namespace/kind/
value/digest — shaped after ADR-003 §8 `SubjectRef` as a JSON reference; this does NOT
implement the kernel `SubjectRef` model), `context_digest`, `policy_version` +
`evaluator_version`, `decision_ref` (evaluation id, decision digest, disposition,
primary reason), `evidence_refs` (ids + digests only), `outcome`, `feedback`, `provenance`
(emitter + emitter version + trace linkage), `privacy_classification`.

The schema **must not require** and does not define fields for: raw prompts, source file
contents, secrets, credentials, or entire command output. Digest-and-reference only.

## 20. Outcome and Feedback Linkage

Every decision is linkable to reality through the event chain, keyed by `evaluation_id` /
`decision_digest`:

```
CHANGEGATE_EVALUATION_COMPLETED
  → CHANGEGATE_REVIEW_OVERRIDDEN            (human resolves reviewable uncertainty)
  → CHANGEGATE_MERGE_ATTEMPTED / _COMPLETED (what actually happened at the VCS)
  → CHANGEGATE_POST_MERGE_VALIDATION        (CI on the merged result)
  → CHANGEGATE_ROLLBACK_RECORDED            (rework/rollback attribution)
  → CHANGEGATE_USER_FEEDBACK_RECORDED       (human judgment about the decision)
```

**Feedback is a signal, not ground truth.** The future improvement pipeline is:

```
interaction → structured event → outcome → feedback → episode labeling → evaluation
→ root-cause hypothesis → bounded improvement proposal → candidate implementation or policy
→ held-in evaluation → held-out regression → ChangeGate → owner approval
→ promotion or rollback
```

Explicitly forbidden (protected roots of trust, ADR-001 §9):

- `user dislike → automatic policy weakening`;
- `negative feedback → direct active-policy mutation`.

A feedback event about a valid BLOCK records the disagreement and feeds episode labeling;
the active policy version is unchanged until a proposal passes the full pipeline including
owner approval (golden case 25). Slice 1 artifacts support controlled improvement
proposals, not autonomous self-modification.

## 21. Privacy, Security and Redaction

- Traces and events carry **digests and identifiers only**: no raw stdout/stderr (the
  provenance layer already stores `stdout_digest`/`stderr_digest`), no file contents, no
  prompts, no secrets, no credentials, no private keys.
- Actor references are **opaque ids** (`actor_ref`), never emails or display names, in both
  traces and events.
- `privacy_classification` (event) and `redaction_classification` (trace) are mandatory,
  from the closed set `PUBLIC`, `INTERNAL`, `SENSITIVE`; sinks must refuse an event without
  a classification.
- Command `argv` may appear in diagnostics only after the application layer's redaction
  pass; the policy trace itself references commands by `requirement_id`/`command_digest`.
- Golden fixtures and schemas in this slice must contain no real secrets, credentials, or
  private keys (executably enforced by the Slice 1A artifact tests).
- Raw debug logs are outside the policy contract and must never be required to replay a
  decision (§18).

## 22. Golden Evaluation Matrix

Artifact: `data/evals/changegate_merge_eligibility_golden_cases.json` (deterministic,
versioned; 25 cases GC-S1-001 … GC-S1-025). Summary:

| Case | Scenario | Expected disposition | Expected primary reason |
| --- | --- | --- | --- |
| GC-S1-001 | complete / current / clean / authorized | ELIGIBLE_TO_MERGE_UNDER_POLICY | — |
| GC-S1-002 | empty bundle, mandatory evidence required | BLOCK | REQUIRED_EVIDENCE_MISSING |
| GC-S1-003 | partial mandatory evidence | BLOCK | REQUIRED_EVIDENCE_MISSING |
| GC-S1-004 | evidence from another task | BLOCK | EVIDENCE_TASK_MISMATCH |
| GC-S1-005 | evidence from another run | BLOCK | EVIDENCE_RUN_MISMATCH |
| GC-S1-006 | evidence from another candidate | BLOCK | EVIDENCE_CANDIDATE_MISMATCH |
| GC-S1-007 | duplicate evidence identity | BLOCK | EVIDENCE_DUPLICATE_IDENTITY |
| GC-S1-008 | candidate stale | BLOCK | CANDIDATE_STALE |
| GC-S1-009 | repository context mismatch | BLOCK | REPOSITORY_CONTEXT_MISMATCH |
| GC-S1-010 | repository dirty | BLOCK | RELEASE_STATE_NOT_CLEAN |
| GC-S1-011 | explicit scope violation | BLOCK | SCOPE_VIOLATION |
| GC-S1-012 | semantic scope uncertainty | REVIEW_REQUIRED | SCOPE_UNCERTAIN |
| GC-S1-013 | approval missing (recommended default; OD-S1A-001) | BLOCK | APPROVAL_MISSING |
| GC-S1-014 | approval stale (recommended default; OD-S1A-002) | BLOCK | APPROVAL_STALE |
| GC-S1-015 | authority invalid | BLOCK | AUTHORITY_INVALID |
| GC-S1-016 | verifier not independent | BLOCK | VERIFIER_NOT_INDEPENDENT |
| GC-S1-017 | verifier independence unknown | REVIEW_REQUIRED | VERIFIER_INDEPENDENCE_UNKNOWN |
| GC-S1-018 | stale policy context | BLOCK | POLICY_CONTEXT_STALE |
| GC-S1-019 | required context unknown (mandatory-context rule §6) | BLOCK | REQUIRED_CONTEXT_INCOMPLETE |
| GC-S1-020 | no evidence requirement + empty explicit-context bundle | ELIGIBLE_TO_MERGE_UNDER_POLICY | — |
| GC-S1-021 | multiple failures (task-mismatch + dirty + approval missing) | BLOCK | EVIDENCE_TASK_MISMATCH |
| GC-S1-022 | structural VERIFIED but release state dirty | BLOCK | RELEASE_STATE_NOT_CLEAN |
| GC-S1-023 | structural VERIFIED but approval stale (non-eligible) | BLOCK | APPROVAL_STALE |
| GC-S1-024 | caller authors an "eligible" decision directly | BLOCK | AUTHORITY_INVALID |
| GC-S1-025 | feedback claims a valid block was wrong | BLOCK (unchanged) | SCOPE_VIOLATION (original) |

Each fixture case carries: `case_id`, `summary`, `policy_input_facts` (the §6 vocabulary),
`expected_disposition`, `expected_primary_reason`, `expected_complete_reason_codes`,
`override_class`, `expected_event_assertions`, and `owner_decision_pending` where a
PENDING_OWNER_DECISION default is encoded (GC-S1-013/014/023). If the owner decides
differently in §25, the fixture and this table are updated in the same owner-reviewed
change.

## 23. Proposed A2 Implementation Scope

Proposed (NOT executed in 1A; requires owner approval of this spec first):

- `agent_core/build_harness/eligibility_facts.py` — `EligibilityFacts` + the §5 application
  fact DTOs + pure derivation from existing contracts;
- `agent_core/build_harness/merge_eligibility.py` — `MergeEligibilityPolicyInput`,
  `MergeEligibilityDecision`, `EvaluationTrace`, reason-code table, pure
  `evaluate_merge_eligibility()` returning `(decision, trace)` as data;
- `tests/build_harness/test_merge_eligibility_policy.py` — unit tests + golden-case runner
  over `data/evals/changegate_merge_eligibility_golden_cases.json`;
- a read-only CLI subcommand (`merge-eligibility`) consuming explicit JSON inputs,
  preserving the standalone path (ADR-002 §8);
- no adapters, no persistence, no event emission in A2 (those are A3+ behind ports).

## 24. Deferred Decisions

This spec cites and does **not** resolve (register:
`docs/architecture/GATE_1_DEFERRED_OWNER_DECISIONS.md`):

- **OD-G1-001** — TaskContract generalization: the policy input references the existing
  software-delivery `TaskContract` by digest; no generalized or duplicate contract is
  introduced.
- **OD-G1-002** — TaskState generalization: eligibility is a separate decision object;
  execution status is not overloaded with authorization (matches ADR-003 §9 axes).
- **OD-G1-003** — Capability ownership: authority facts use opaque actor/role references
  and a validity status; no Capability model is created or claimed.
- **OD-G1-004** — Decision model disposition: `MergeEligibilityDecision` is a
  ChangeGate-local application decision, explicitly not the canonical cross-domain
  `DecisionRecord`; the six existing `*Decision` types are untouched.
- **OD-G1-005/006/007** — untouched (no package migration, no composition layer, no track
  allocation change).

## 25. Owner Decision Points

Each item below is **PENDING_OWNER_DECISION**. A recommended default with rationale is
given so review is concrete; the recommendation is not a resolution, and the golden fixture
marks the affected cases.

| ID | Question | Recommended default | Rationale |
| --- | --- | --- | --- |
| OD-S1A-001 | Is missing approval BLOCK or REVIEW_REQUIRED? | BLOCK | ProcessGuard already hard-blocks push/deploy without approval; a wedge whose default leaks unapproved merges is unsellable. REVIEW_REQUIRED would be tolerable UX-wise but weakens the fail-closed story |
| OD-S1A-002 | Is stale approval always BLOCK? | Always BLOCK | An approval for commit A must never carry to commit B; "mostly the same change" is exactly the judgment a re-approval exists to capture |
| OD-S1A-003 | When is verifier-independence UNKNOWN reviewable (vs BLOCK)? | REVIEW_REQUIRED only when verifier identity is present and attested but the independence attestation is absent; missing identity is REQUIRED_CONTEXT_INCOMPLETE (BLOCK) | Keeps early deployments usable (independence attestation infra may lag) without ever reviewing an anonymous verifier |
| OD-S1A-004 | Do strict deployments require successful trace persistence before eligibility may be consumed? | Yes in strict mode: the application layer must persist the trace and only then release the decision; the pure evaluator stays side-effect free | An unauditable authorization is a liability; keeping it in the application layer preserves evaluator purity |
| OD-S1A-005 | Policy exception authority and expiry | Only the owner (or an owner-designated role) may authorize exceptions; every exception has a mandatory expiry and binds to one task+candidate | Unbounded exceptions become the de-facto policy |
| OD-S1A-006 | Treatment of unexpected but valid evidence | Diagnostic only (`unexpected_evidence_ids`); never satisfies requirements, never blocks alone | Punishing extra proof discourages evidence; ignoring it silently hides drift — recording it is the middle path |
| OD-S1A-007 | Exact precedence where two integrity failures coexist | The §9/§10 rank table as written (authority > context-incomplete > task > run > candidate > repository > provenance > duplicate) | Most-specific-foreign-identity-first gives the operator the most actionable primary reason; any total order is acceptable as long as it is fixed |

Nothing in this table is chosen merely to finish the document; every recommended default is
reversible before A2 begins.

## 26. Exit Criteria

Slice 1A exits when:

1. the Slice 1A artifact tests pass (spec present and DRAFT_FOR_OWNER_REVIEW, schema valid,
   fixture valid, 25+ cases, all dispositions covered, forbidden terms absent);
2. the full existing suite, architecture tests, and conversation eval remain green with
   zero production files changed;
3. Codex Sol High independent verification completes;
4. TranBac either accepts this spec (flipping Status in a separate owner-reviewed change)
   or returns decisions for OD-S1A-001 … OD-S1A-007;
5. only then may Slice 1-A2 (pure evaluator implementation) be scheduled.

The forbidden output terms remain forbidden after acceptance: `SAFE_TO_MERGE` and
`VERIFIED_AND_MERGE` must never appear as output values of any ChangeGate component.

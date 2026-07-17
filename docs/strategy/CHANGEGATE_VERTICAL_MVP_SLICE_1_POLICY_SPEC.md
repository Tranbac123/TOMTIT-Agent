# ChangeGate Vertical MVP Slice 1 — Merge Eligibility Policy

Title: ChangeGate Vertical MVP Slice 1 — Merge Eligibility Policy
Status: DRAFT_FOR_OWNER_REVIEW
Owner: TranBac
Technical Author: Claude Code Fable 5
Independent Verification: PENDING
Baseline: 3e72e93bfac8da2ecdb7960a55ae0357135eb61e
Production Implementation: NOT_STARTED
Revision: R7-NC1 (narrow normative runtime and authority-boundary clarification under
owner decision OWNER-SCOPE-R7-03: adds §7.5 runtime/authority boundary, portable RFC 8259
input domain, current Python implementation profile, representation-guard permission,
expected-invalid-versus-internal-fault distinction, diagnostic scope, and abstract
audit-history/re-review rules; fingerprint changes, validator and event-schema behavior
unchanged; supersedes R7 bounded structural-contract closure → R6 → R5 → R4 → R3 → R2 →
R1 → 07bc5b7be43a275c8484cdc633579ecfda657ffd)

> This document is a specification-and-contract artifact only. It defines the deterministic
> merge-eligibility policy contract for ChangeGate Slice 1. It implements nothing. It remains
> `DRAFT_FOR_OWNER_REVIEW` until TranBac explicitly accepts it; no model is an acceptance
> authority. Every semantic that the owner has not yet decided is marked
> `PENDING_OWNER_DECISION` in §25 and is NOT silently resolved here. Exactly one owner
> decision is ACCEPTED: **OD-S1A-009** (§25.2), the Slice 1A deterministic-evaluation
> boundary, which this revision implements.

---

## 1. Context

ADR-001 (accepted) establishes ChangeGate as the first commercial wedge and records two
durable obligations:

- **FOLLOWUP-P0-9B1-002 / ADR-001 §7** — structural evidence verification
  (`EvidenceVerificationResult.accepted == True`, `VerificationStatus.VERIFIED`) is
  never authorization to merge. Merge eligibility is a separate policy decision.
- **FOLLOWUP-P0-9B1-001 / ADR-001 §8** — a schema-valid **empty** verification bundle is
  never evidence completeness. When evidence is required, the policy layer must enforce
  `required evidence ⊆ verified evidence`.

The current repository has two evidence generations inside `agent_core.build_harness`:

- **Slice 0 (P0-9A "ChangeGate Lite")** — `evaluate_change_gate()` over legacy
  `CommandEvidence` (command-string matching, commit-bound, exit-0). Its `PASS` is a
  structural scope/evidence check, never merge authority.
- **P0-9B1 domain layer** — `CandidateBinding`, `RepositorySnapshot`, `CommandRequirement`,
  `EvidenceProvenance`, `CollectedCommandEvidence`, `EvidenceVerificationResult`,
  `VerifiedCommandEvidence`, `EvidenceVerificationBundle`, `EvidenceRunRecord`, plus pure
  ports. The coupling audit confirms this vertical is represented but not yet executable
  end-to-end (no adapter from verified bundles into an eligibility decision).

This slice (1A) defines the **policy contract** that will sit on top of the P0-9B1 layer:
what `ELIGIBLE_TO_MERGE_UNDER_POLICY` means, exactly which facts it requires, how those
facts are derivable from existing contracts, its deterministic reason-code precedence, its
evaluation trace and replay identity, its product event schema, and its golden evaluation
matrix. Slice 1-A2 (a later, separately approved task) implements the pure evaluator;
Slice 1-A3 implements fact derivation and adapters.

R1 incorporates the independent Sol High review findings (H-01 … H-04, M-01 … M-03): the
fact contract is now total and derivable through an explicit derivation seam, evidence
accounting is disjoint, decision identity is separated from trace identity, the event
schema enforces per-event linkage, and the golden matrix covers every closed reason code.

## 2. Goals

1. Separate **structural evidence verification** from **merge eligibility under policy**,
   permanently and testably.
2. Define two explicit application seams: **fact derivation** (A3) over existing
   contracts, and a **pure evaluator** (A2) over validated facts only.
3. Define a typed, **total** eligibility-facts layer: every declared fact state maps to
   exactly one reason (or none) and one disposition class.
4. Define the authoritative **output contract** (disposition + decision authority +
   reason codes + digests) with replay-stable decision identity.
5. Define a stable, machine-readable **reason-code taxonomy** with deterministic
   precedence.
6. Define **disjoint required-evidence accounting** (`satisfied ∪ invalid ∪ missing`,
   pairwise disjoint) with stable requirement identifiers, never inferred from prose.
7. Define **authority and override boundaries**: facts cannot be voted away by an
   approval.
8. Define a replayable **EvaluationTrace** returned as pure data, with `decision_digest`
   independent of trace/request identity and a separate `trace_digest`.
9. Define the **product event schema** with per-event-type conditional linkage from
   decisions to real user/CI/merge outcomes.
10. Define **privacy and redaction** rules, including bounded reference grammars.
11. Provide **golden evaluation cases** covering every closed reason code and every
    owner-decision-controlled boundary, validated by an independent test-only oracle.

## 3. Non-Goals

- No production eligibility evaluator is implemented in Slice 1A/R1.
- No Git/subprocess/filesystem/network adapters; no GitHub App; no auto-merge.
- No Coordinator, Project Control, LLM integration, notification, dashboard, or vector DB.
- No change to any `agent_core/**` production file, contract, or schema version.
- No resolution of deferred owner decisions OD-G1-001 … OD-G1-007 (§24) or
  OD-S1A-001 … OD-S1A-007 (§25).
- No canonical kernel models (`ActorIdentity`, `ApprovalRecord`, `DecisionRecord`,
  `AuditEvent` remain `FUTURE_CONCEPT_NOT_IMPLEMENTED` per ADR-003).
- No self-improvement implementation; §20 records the controlled boundary only.

## 4. Existing Contract Inventory

Inventory taken against baseline `3e72e93` (all statuses verified by reading the modules):

| Symbol | Module | Semantic meaning | Authority level | Slice 1 reuse |
| --- | --- | --- | --- | --- |
| `TaskContract` | `build_harness/contracts.py` | What may change, what must be proven, what needs a human | Declarative source of requirements | REUSED as derivation input (referenced by `contract_digest`) |
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
| `EvidenceProvenance` / `CollectedCommandEvidence` | `build_harness/provenance.py` | Collected command evidence bound to task/run/candidate/snapshots; **carries `requirement_id` for every record, including records later rejected** | Collected fact | REUSED verbatim — the requirement binding for rejected records (§5, §6) |
| `EvidenceVerificationResult` / `VerificationStatus` | `provenance.py` | Structural verification result; `accepted ⇔ VERIFIED`; a REJECTED result must carry `matched_requirement_id=None` (`provenance.py` §rejected rules) | Structural verification only | REUSED verbatim; source of rejected/invalid record facts. Its requirement binding for rejected records comes from collected provenance, never from the result |
| `VerifiedCommandEvidence` | `provenance.py` | Digest-bound proof that one requirement was structurally verified for one candidate | Structural verification only | REUSED verbatim; source of satisfied-requirement facts |
| `EvidenceVerificationBundle` | `provenance.py` | One coherent verified/rejected set for one task+candidate, digest-sealed | Structural verification only | REUSED verbatim inside the derivation input |
| `EvidenceRunRecord` | `build_harness/ports.py` | Immutable link binding one task/run/candidate to its collected evidence (with provenance) and optional bundle | — | REUSED verbatim as a **derivation input** (§5): it is the only place a rejected record's `requirement_id` remains reachable |
| `EvidenceVerificationRequest` | `ports.py` | Pure verifier request | — | REUSED upstream of policy |
| `Outcome` / `Unit` / `StorageError` | `ports.py` | Typed success/failure | — | REUSED by future A3 application layer |
| `canonical_digest` / canonical validators | `build_harness/canonical.py` | Deterministic canonical JSON digests | — | REUSED for input/decision/trace digests |
| `NextAction` / `recommend_next_action` | `build_harness/next_action.py` | Operator recommendation | None | Unchanged consumer |
| CLI | `build_harness/cli.py` | Standalone JSON path (ADR-002 §8) | — | Unchanged in 1A; A2 proposes a subcommand |
| Approval / actor identity | NOT_FOUND in ChangeGate scope (`agent_core/safety/approval.py` is runtime tool-gating, a different domain per ADR-003; `ProcessGuardInput.human_approved` is an unattributed bool) | — | — | MISSING → new application facts (§5, §14) |
| Policy version / policy digest | NOT_FOUND (searched `policy_version`, `reason_code`, `ActorIdentity`, `ApprovalRecord` across `agent_core`) | — | — | MISSING → new `PolicyContextFact` (§5) |
| Event / trace / evaluation / audit models | NOT_FOUND (`AuditEvent`, `DecisionRecord` are `FUTURE_CONCEPT_NOT_IMPLEMENTED` per ADR-003 §5) | — | — | MISSING → schema artifact + trace contract (§18, §19), no kernel model minted |

**Load-bearing integration constraint (Sol High H-01):** a rejected
`EvidenceVerificationResult` is required by existing code to have
`matched_requirement_id is None`. The only stable requirement binding for a rejected
record is `EvidenceProvenance.requirement_id`, reachable through the run's
`CollectedCommandEvidence` inside `EvidenceRunRecord`. Therefore fact derivation (A3)
consumes the run record; the pure evaluator (A2) consumes only derived facts. Neither
existing model is modified.

**Duplicate-model rule honored:** no concept above gets a second canonical model. Every
new concept in §5 is a ChangeGate-local application DTO, explicitly non-canonical, and is
adapter-suppliable without modifying any existing domain model.

## 5. Policy Input

R1 separates two application seams so every declared fact is derivable from declared
input, and the pure evaluator never touches storage or raw evidence:

```
existing contracts
→ A3 fact derivation   (EligibilityFactDerivationInput → EligibilityFacts)
→ validated EligibilityFacts
→ A2 pure evaluator    (MergeEligibilityPolicyInput → decision + trace data)
→ decision + deterministic policy trace data
```

### 5.1 EligibilityFactDerivationInput (A3)

An immutable application DTO referencing the existing raw contracts needed to derive
every fact in §6. Pure derivation: no Git, filesystem, network, clock, or model call.

| Field | Type (existing unless marked NEW) | Supplies |
| --- | --- | --- |
| `contract` | `TaskContract` | requirement declarations, approval-required actions, scope patterns |
| `contract_digest` | sha256 over the canonical `contract_to_dict` payload | task-contract version identity; compared with `candidate_binding.contract_digest` for `task_context_current` |
| `candidate_binding` | `CandidateBinding` | candidate identity |
| `current_snapshot` | `RepositorySnapshot` | freshness + release cleanliness |
| `evidence_run_record` | `EvidenceRunRecord` | collected evidence with `EvidenceProvenance.requirement_id` for EVERY record — the requirement binding for rejected/invalid records that the verification result itself must not carry |
| `verification_bundle` | `EvidenceVerificationBundle` | verified/rejected structural results; must be the run record's bundle (identity-checked during derivation) |
| `required_evidence` | `tuple[CommandRequirement, ...]` | required requirement ids |
| `scope_inputs` | NEW `ScopeInputs` (changed files + contract patterns, or the ChangeGate Lite decision they produced) | `scope_status` |
| `approval_inputs` | NEW `ApprovalFact \| None` | `approval_status` |
| `authority_inputs` | NEW `AuthorityFact` | `authority_status` |
| `verifier_identity_inputs` | NEW `VerifierIdentityFact` | `verifier_identity_status` + `verifier_independence_status` |
| `policy_context` | NEW `PolicyContextFact` | `policy_context_current`, policy id/version/digest |

### 5.2 MergeEligibilityPolicyInput (A2)

The pure evaluator's only input. It must not require A2 to inspect storage, raw collected
evidence, the filesystem, or any external system.

| Field | Content |
| --- | --- |
| `task_id` | validated task id |
| `task_contract_digest` | exact task-contract binding |
| `candidate_digest` | canonical digest of the `CandidateBinding` |
| `repository_snapshot_digest` | canonical digest of the current `RepositorySnapshot` the facts were derived from |
| `verification_bundle_digest` | `EvidenceVerificationBundle.bundle_digest` the facts were derived from |
| `approval_digest_or_sentinel` | canonical digest of the `ApprovalFact`, **or** the explicit sentinel `NO_APPROVAL_SUPPLIED` — the absence of an approval is an explicit deterministic input value, never a missing field. This is the ONE canonical field name (§7.3); `approval_digest` is not used as a field name anywhere in the contract |
| `authority_binding_digest` | canonical digest of the `AuthorityFact` (actor/role refs + validity status) |
| `verifier_binding_digest` | canonical digest of the `VerifierIdentityFact` (verifier/implementer refs + identity/independence statuses) |
| `policy_digest`, `policy_version` | which policy decides |
| `facts` | validated `EligibilityFacts` (§6) — the complete typed fact set, which does NOT include `evaluation_mode` |
| `evaluation_mode` | `ENFORCE \| SHADOW` — the **single source** of evaluation mode (A2 execution configuration, digest-covered). It is NOT an `EligibilityFact` (§6.3), so no second, conflicting copy is representable |
| `evaluator_version` | evaluator software identity |

Every field above is deterministic and caller-supplied. **A2 must not inspect the
filesystem, storage, raw evidence, clocks, or request metadata**, and the input carries no
`trace_id`, `evaluation_id`, `request_id`, timestamp, or latency (§18).

`input_digest` = `canonical_digest(MergeEligibilityPolicyInput)`. Because the input binds
every **source digest** (snapshot, bundle, approval, authority, verifier, contract,
candidate, policy), a change in any source that could change the meaning of the decision
necessarily changes `input_digest` and therefore `decision_digest` (§7, §18.3). A source
digest is **not** excluded from the decision merely because it also appears in the
application's trace envelope.

All digest fields use the repository's single canonical representation (§7.1).

For every proposed NEW concept:

| New concept | Why existing contracts are insufficient | ChangeGate-specific? | Temporary application DTO? | Adapter-suppliable without touching canonical models? |
| --- | --- | --- | --- | --- |
| `EligibilityFactDerivationInput` | No existing type aggregates contract + candidate + run record + bundle + approval/authority/policy context for derivation | Yes | Yes | Yes — composed from existing contracts |
| `ScopeInputs` / `ScopeFacts` | `ChangeGateDecision` mixes scope findings with legacy evidence findings and is an output, not a typed input fact | Yes | Yes — until a kernel policy vocabulary exists | Yes — derived from `evaluate_change_gate` findings + contract paths |
| `ApprovalFact` | No approval record exists anywhere; `ProcessGuardInput.human_approved` is an unattributed bool with no target binding or freshness; `ApprovalRecord` is kernel-future (ADR-003) and may not be minted here (OD-G1-004 adjacent) | Yes (binds to candidate digests) | Yes — explicitly NOT the canonical `ApprovalRecord` | Yes |
| `AuthorityFact` | No `ActorIdentity` exists; `Capability` ownership is unresolved (OD-G1-003) — authority is expressed as opaque actor/role references + validity status, never as a capability model | Yes | Yes | Yes |
| `VerifierIdentityFact` | `EvidenceVerificationResult.verifier_version` identifies software, not actor identity/attestation/independence; OD-S1A-003 needs identity presence as a fact | Yes | Yes | Yes |
| `PolicyContextFact` | No policy-version concept exists in the repository | Yes | Yes | Yes |
| `EligibilityFacts` (§6) | Nothing maps raw contracts to policy-consumable facts | Yes | Yes | Yes — pure derivation |
| `MergeEligibilityDecision` (§7) | `ChangeGateDecision` is structural and its vocabulary (`PASS`) is explicitly not merge authority | Yes | Yes | n/a (evaluator output) |
| `PolicyEvaluationRecord` (§7.3) | Nothing carries a deterministic, replayable policy record separate from application trace metadata | Yes | Yes | n/a (evaluator output) |
| `EvaluationTraceEnvelope` (§18) | No trace/audit model exists | Yes (v1) | Yes — `AuditEvent` remains kernel-future | n/a (application-layer output) |
| `RequirementDeclarationSet` (§25, OD-S1A-008) | `TaskContract.required_evidence` holds display strings; `CommandRequirement.requirement_id` is the stable key, and nothing declares the mapping | Yes | Yes | Yes — an A3 declaration bound to the exact contract digest; **PENDING_OWNER_DECISION OD-S1A-008** |

Deferred-decision guard: none of these DTOs generalizes `TaskContract` (OD-G1-001),
creates a second `TaskState` or overloads execution status with eligibility (OD-G1-002 —
eligibility is a separate decision object, exactly the three-axis separation of ADR-003
§9), claims the canonical `Capability` (OD-G1-003), or mints a canonical `DecisionRecord`
(OD-G1-004).

## 6. Eligibility Facts

A typed conceptual layer, **`EligibilityFacts`**, sits between raw contracts and policy
evaluation. A3 derives these facts deterministically from `EligibilityFactDerivationInput`;
the evaluator consumes only facts. **Facts grant no authority by themselves** — they are
observations; only the policy maps facts to a disposition.

### 6.1 Requirement accounting facts (requirement identifiers — disjoint)

Matching key: `CommandRequirement.requirement_id` on the declaration side;
`VerifiedCommandEvidence.requirement_id` (satisfied) or the rejected record's
`EvidenceProvenance.requirement_id` reachable via the run record (invalid).

| Fact | Definition |
| --- | --- |
| `required_requirement_ids` | sorted unique requirement ids declared required |
| `satisfied_requirement_ids` | required ids with ≥ 1 valid verified record bound to the current task, run and candidate |
| `invalid_requirement_ids` | required ids with NO valid verified record but ≥ 1 **bound** rejected/invalid record (bound = the record's provenance identifies this task, run, candidate, and this requirement id) |
| `missing_requirement_ids` | required ids with neither a valid verified record nor a bound rejected/invalid record |

**Partition invariant (normative, executably checked):**

```
required_requirement_ids = satisfied ∪ invalid ∪ missing        (pairwise disjoint)
```

`missing` explicitly EXCLUDES `invalid`: a required id with a bound rejected record is
invalid, not missing; a foreign or unbound record leaves the requirement missing.

### 6.2 Evidence record diagnostics (evidence-record identifiers — never requirement ids)

| Fact | Definition |
| --- | --- |
| `rejected_evidence_ids` | record ids of bound rejected results (any rejection status) |
| `invalid_provenance_evidence_ids` | ⊆ rejected: record ids whose rejection is a provenance/schema/collector integrity failure (`INVALID_PROVENANCE`, `UNSUPPORTED_SCHEMA`, `UNSUPPORTED_COLLECTOR`) |
| `unexpected_evidence_ids` | record ids of VALID verified records whose `requirement_id` is not in `required_requirement_ids` |

**Identifier namespaces (normative).** Requirement ids and evidence-record ids inhabit two
**disjoint universes** and are never interchangeable: `*_requirement_ids` sets hold only
requirement ids, `*_evidence_ids` sets hold only evidence-record ids, and no identifier may
appear in both universes. A3's typed sources make this structural (`CommandRequirement`
vs. `EvidenceProvenance`), and every golden case declares its two universes explicitly
(`identifier_universes`) so the boundary is executably enforced rather than merely
asserted in prose:

```
required/satisfied/invalid/missing_requirement_ids  ⊆ requirement_id_universe
rejected/invalid_provenance/unexpected_evidence_ids ⊆ evidence_record_id_universe
requirement_id_universe ∩ evidence_record_id_universe = ∅
```

No production identifier prefix is mandated — the existing contracts do not require one;
only disjointness is required.

### 6.3 Context, scope, approval, authority and verifier facts

| Fact | Values |
| --- | --- |
| `task_context_current` | `CURRENT \| STALE \| UNKNOWN` (contract digest vs candidate `contract_digest`) |
| `candidate_binding_current` | `CURRENT \| STALE \| UNKNOWN` (§12) |
| `repository_snapshot_current` | `CURRENT \| MISMATCH \| UNKNOWN` (§12) |
| `repository_release_clean` | `CLEAN \| DIRTY \| UNKNOWN` |
| `policy_context_current` | `CURRENT \| STALE \| UNKNOWN` |
| `evidence_context_status` | `COHERENT \| INCOHERENT \| UNKNOWN`, with `evidence_context_violations` tags (`TASK_MISMATCH, RUN_MISMATCH, CANDIDATE_MISMATCH, PROVENANCE_INVALID, DUPLICATE_IDENTITY`); violations non-empty ⇔ INCOHERENT |
| `scope_status` | `COMPLIANT \| VIOLATION \| SEMANTIC_UNCERTAIN \| NOT_EVALUATED` (§13) |
| `approval_status` | `VALID \| MISSING \| STALE \| UNKNOWN` (§14) |
| `authority_status` | `VALID \| INVALID \| UNKNOWN` (§14) |
| `verifier_identity_status` | `ATTESTED \| PRESENT_UNATTESTED \| ABSENT \| INVALID` (§15) |
| `verifier_independence_status` | `INDEPENDENT \| NOT_INDEPENDENT \| UNKNOWN` (§15) |

**`evaluation_mode` is NOT an eligibility fact.** It is A2 **execution configuration** and
lives exactly once, at `MergeEligibilityPolicyInput.evaluation_mode` (§5.2). It is not
derived by A3, is absent from `EligibilityFacts` and from `fact_state_mapping.enum_facts`,
and cannot be represented a second time. It selects `decision_authority` (§8) and never
changes the reason set. Any input carrying a facts-level evaluation mode is malformed by
construction (there is no such field), so the top-level/facts conflict of the prior
revision is unrepresentable.

### 6.4 Total fact-state mapping (normative)

Every declared fact state maps to **no reason or exactly one reason code**, and through
the taxonomy (§9) to exactly one disposition class. No state is
left to the A2 implementer. The machine-readable normative form of this table is
`fact_state_mapping` in `data/evals/changegate_merge_eligibility_golden_cases.json`;
artifact tests prove there is no unmapped fact state and that the independent oracle
reproduces every golden expectation from it.

| Fact | Value → reason |
| --- | --- |
| `task_context_current` | CURRENT → none; STALE → `TASK_CONTEXT_STALE`; UNKNOWN → `REQUIRED_CONTEXT_INCOMPLETE` |
| `candidate_binding_current` | CURRENT → none; STALE → `CANDIDATE_STALE`; UNKNOWN → `REQUIRED_CONTEXT_INCOMPLETE` |
| `repository_snapshot_current` | CURRENT → none; MISMATCH → `REPOSITORY_CONTEXT_MISMATCH`; UNKNOWN → `REQUIRED_CONTEXT_INCOMPLETE` |
| `repository_release_clean` | CLEAN → none; DIRTY → `RELEASE_STATE_NOT_CLEAN`; UNKNOWN → `REQUIRED_CONTEXT_INCOMPLETE` |
| `policy_context_current` | CURRENT → none; STALE → `POLICY_CONTEXT_STALE`; UNKNOWN → `REQUIRED_CONTEXT_INCOMPLETE` |
| `evidence_context_status` | COHERENT → none; INCOHERENT → none directly (each violation tag emits its exact integrity code); UNKNOWN → `REQUIRED_CONTEXT_INCOMPLETE` |
| violation tag | TASK_MISMATCH → `EVIDENCE_TASK_MISMATCH`; RUN_MISMATCH → `EVIDENCE_RUN_MISMATCH`; CANDIDATE_MISMATCH → `EVIDENCE_CANDIDATE_MISMATCH`; PROVENANCE_INVALID → `EVIDENCE_PROVENANCE_INVALID`; DUPLICATE_IDENTITY → `EVIDENCE_DUPLICATE_IDENTITY` |
| `scope_status` | COMPLIANT → none; VIOLATION → `SCOPE_VIOLATION`; SEMANTIC_UNCERTAIN → `SCOPE_UNCERTAIN`; NOT_EVALUATED → `REQUIRED_CONTEXT_INCOMPLETE` |
| `approval_status` | VALID → none; MISSING → `APPROVAL_MISSING`; STALE → `APPROVAL_STALE`; UNKNOWN → `APPROVAL_MISSING` (treated as missing; disposition pending OD-S1A-001) |
| `authority_status` | VALID → none; INVALID → `AUTHORITY_INVALID`; UNKNOWN → `REQUIRED_CONTEXT_INCOMPLETE` |
| verifier pair | governed by the ordered first-match rule in §15 (total over all 12 combinations) |
| `missing_requirement_ids` non-empty | → `REQUIRED_EVIDENCE_MISSING` |
| `invalid_requirement_ids` non-empty | → `REQUIRED_EVIDENCE_INVALID` |
| `invalid_provenance_evidence_ids` non-empty | → `EVIDENCE_PROVENANCE_INVALID` |
| `rejected_evidence_ids` non-empty | → no reason (diagnostic; a benign rejection such as a failed earlier attempt does not taint a satisfied requirement) |
| `unexpected_evidence_ids` non-empty | → no reason (diagnostic; recommended treatment PENDING_OWNER_DECISION OD-S1A-006) |

The complete reason set of an evaluation is exactly the deduplicated union of the codes
emitted by this mapping over the supplied facts. `UNKNOWN` never defaults toward
eligibility.

## 7. Policy Output

The pure evaluator returns exactly two immutable values, **both deterministic data**:

```
evaluate_merge_eligibility(MergeEligibilityPolicyInput)
    -> (MergeEligibilityDecision, PolicyEvaluationRecord)
```

It returns **no** trace envelope. Trace/request/evaluation identities, timestamps, latency
and event ids are **constructed by the application layer afterwards** (§18). The evaluator
generates no nondeterministic metadata of any kind.

### 7.1 Canonical digest representation (one representation, everywhere)

The sole canonical digest representation across this spec, the fixture, the event schema,
decision/source references and the test helpers is:

```
sha256:<64 lowercase hexadecimal characters>
```

This is exactly what `agent_core.build_harness.canonical.canonical_digest()` already
emits and what `validate_sha256_digest()` already accepts. **Bare 64-hex digests are not a
valid representation.** No component may strip, add back, or otherwise reconstruct the
`sha256:` prefix; a digest that crosses any boundary crosses it prefixed. Invalid forms
include bare hex, uppercase `SHA256:` prefixes, uppercase hex, another algorithm prefix,
wrong length, and any value carrying whitespace or a newline.

### 7.2 MergeEligibilityDecision (deterministic authoritative policy output)

| Field | Authoritative? | Digest-covered? | Meaning |
| --- | --- | --- | --- |
| `disposition` | **AUTHORITATIVE** | yes | exactly one of §8's three values |
| `decision_authority` | **AUTHORITATIVE** | yes | `AUTHORITATIVE \| ADVISORY_ONLY` (§8) |
| `primary_reason_code` | **AUTHORITATIVE** | yes | deterministic primary reason (`null` only when the complete set is empty) |
| `complete_reason_codes` | **AUTHORITATIVE** | yes | every independently confirmed reason, sorted lexicographically |
| `blocking_reason_codes` / `review_reason_codes` | **AUTHORITATIVE** | yes | partition of the complete set by effective disposition |
| `required_requirement_ids` / `satisfied_requirement_ids` / `invalid_requirement_ids` / `missing_requirement_ids` | **AUTHORITATIVE** | yes | disjoint requirement accounting (§6.1) |
| `rejected_evidence_ids` / `invalid_provenance_evidence_ids` / `unexpected_evidence_ids` | diagnostic (deterministic) | yes | record-id diagnostics (§6.2); deterministic and policy-meaningful, therefore digest-covered |
| `task_id` | **AUTHORITATIVE** | yes | what this decision is about |
| **source bindings**: `task_contract_digest`, `candidate_digest`, `repository_snapshot_digest`, `verification_bundle_digest`, `approval_digest_or_sentinel` (a canonical digest or `NO_APPROVAL_SUPPLIED`), `authority_binding_digest`, `verifier_binding_digest` | **AUTHORITATIVE** | yes | every deterministic source the facts were derived from (§5.2) |
| `policy_version`, `policy_digest` | **AUTHORITATIVE** | yes | which policy decided |
| `evaluation_mode` | **AUTHORITATIVE** | yes | ENFORCE or SHADOW |
| `evaluator_version` | **AUTHORITATIVE** | yes | evaluator software identity |
| `input_digest` | **AUTHORITATIVE** | yes | `canonical_digest(MergeEligibilityPolicyInput)` |
| `decision_digest` | **AUTHORITATIVE** | self-excluding | canonical digest over every digest-covered field above, excluding itself (same self-excluding pattern as `VerifiedCommandEvidence`) |
| `explanations` | diagnostic | **no** | user-facing prose per reason code; NEVER the reason identity (§9); excluded so prose can improve without a policy bump |

The decision **contains no trace, evaluation, or request identifier**, no timestamp, no
latency, no event id and no storage location. Linkage runs one way only: the trace
envelope points at the decision through `decision_digest`, never the reverse.

### 7.3 PolicyEvaluationRecord (deterministic replayable policy record)

A deterministic, replayable record of the evaluation, returned by the pure evaluator
alongside the decision. It is reproducible from `MergeEligibilityPolicyInput` **alone** —
it contains no application/storage metadata and no privacy classification.

**Exact `PolicyEvaluationRecordPayload` (the digested payload), field order fixed:**

```
PolicyEvaluationRecordPayload
- schema_version                 "changegate.policy-evaluation-record.v1"
- task_id
- task_contract_digest
- candidate_digest
- repository_snapshot_digest
- verification_bundle_digest
- approval_digest_or_sentinel    (a canonical digest, or the exact sentinel
                                  NO_APPROVAL_SUPPLIED)
- authority_binding_digest
- verifier_binding_digest
- policy_digest
- policy_version
- evaluator_version
- evaluation_mode                (ENFORCE | SHADOW, from the A2 input — the single source)
- input_digest                   (= canonical_digest(MergeEligibilityPolicyInput))
- disposition
- decision_authority
- primary_reason_code
- complete_reason_codes          (lexicographically sorted)
- blocking_reason_codes          (lexicographically sorted)
- review_reason_codes            (lexicographically sorted)
- required_requirement_ids       (sorted)
- satisfied_requirement_ids      (sorted)
- invalid_requirement_ids        (sorted)
- missing_requirement_ids        (sorted)
- rejected_evidence_ids          (sorted)
- invalid_provenance_evidence_ids (sorted)
- unexpected_evidence_ids        (sorted)
- decision_digest                (= the decision object's decision_digest)
```

The record object then adds exactly one derived field:

```
policy_record_digest = canonical_digest(PolicyEvaluationRecordPayload)
```

using the production `canonical_digest()` (`sha256:<64 lowercase hex>`, §7.1).

**Portable typed field contract (normative, R6).** The record payload is defined by an
**exact field SET with typed values**, not by JSON insertion order. The field list above
is displayed in `NON_SEMANTIC_DOCUMENTATION_ORDER`: the production canonical serializer
sorts object keys, JSON objects are unordered on every transport, and therefore key
insertion order carries no identity or integrity meaning. The same valid object presented
with any key insertion order is accepted and has the same canonical identity. The
machine-readable typed contract is `deterministic_identity.typed_field_contract` in the
golden fixture, digested as `policy_record_schema_digest`. The validator enforces, in
order:

1. **exact field set** — no unknown, missing, renamed, or duplicate-under-another-key
   field; the one canonical approval field is `approval_digest_or_sentinel`, no alias;
2. **typed values** — strings are strings (booleans are never integers), enums contain
   only allowed values, `task_id` matches the task grammar, every digest field matches
   `sha256:<64 lowercase hex>` (`approval_digest_or_sentinel` may instead be the exact
   sentinel `NO_APPROVAL_SUPPLIED`), versions match the version grammar, reason codes
   exist in the declared taxonomy, requirement ids belong to the requirement universe,
   evidence ids belong to the evidence-record universe;
3. **canonical collection form** — every set-like list is sorted and deduplicated;
   `blocking ∪ review == complete` with `blocking ∩ review == ∅`;
   `required == satisfied ∪ invalid ∪ missing`, pairwise disjoint. A validator rejects a
   non-normalized issued record; it never silently normalizes it;
4. **decision self-derivation** — `record.decision_digest ==
   canonical_digest(normative decision payload derived from the record's own fields)`, so
   an arbitrary payload can never be made valid merely by recomputing
   `policy_record_digest`;
5. **record digest recompute** — `record.policy_record_digest == canonical_digest(payload)`.

An invalid type, malformed digest, non-normalized collection, or forged decision digest
remains invalid **after the caller rehashes the record**.

The payload **must not contain**: `policy_record_digest` (a payload never digests
itself), `redaction_classification` (application/trace metadata, §18/§21), `request_id`,
`trace_id`, an application-generated `evaluation_id`, a timestamp, a latency, an event id,
or a storage location. Two evaluations of the same complete replay key (§18.5) produce
byte-identical records and identical `policy_record_digest`.

**Validation levels (normative, R7 — Slice 1A structural boundary).**

Slice 1A validation is **structural only**. Its classifications are:

- `STRUCTURALLY_VALIDATED` — the record satisfies checks 1–5 above and, when the
  canonical input is supplied, every binding already present in both artifacts is equal
  (task identity, all eight source bindings, policy/evaluator versions, evaluation mode,
  record-schema version/digest, canonicalization version/digest) and
  `record.input_digest == canonical_digest(canonical input)`. Binding equality proves the
  record is bound to that input — never that the disposition or reasons are the
  production evaluator's semantic result for it.
- `IDENTITY_RECOMPUTED` — `decision_digest` recomputes from the record's own
  deterministic decision fields and `policy_record_digest` recomputes from the canonical
  payload. This proves identity consistency only; it does not recompute the semantic
  decision from facts.
- `SEMANTIC_REPLAY_NOT_PERFORMED` — always, for every Slice 1A validation result. No
  Slice 1A artifact, helper, manifest control, or test replays a decision through a
  production evaluator, so none may prove or claim that the disposition, reason
  selection, or precedence application is semantically correct for the input. A
  semantically forged but internally consistent policy result can be
  `STRUCTURALLY_VALIDATED` and `IDENTITY_RECOMPUTED`; it must never be reported as
  semantically replay verified.
- `SEMANTICALLY_REPLAY_VERIFIED` — **Slice 1B protocol requirement only**: it requires
  re-executing the production pure evaluator over the canonical input and obtaining a
  byte-identical decision and record. No Slice 1A artifact or helper may return this
  status for a policy result.

**Record ↔ decision consistency (normative, executably tested):**

- `record.input_digest == decision.input_digest == canonical_digest(A2 input)`;
- `record.decision_digest == decision.decision_digest` and both self-derive from the
  deterministic decision fields;
- every source binding in the record equals the A2-input source binding;
- `record.disposition / decision_authority / primary_reason_code / complete_reason_codes`
  and the requirement/diagnostic sets equal the decision's.

### 7.4 Semantic producer, persistence writer, audit journal (OD-S1A-009)

Three roles are distinguished and must never be conflated:

- **Semantic producer** — the **pure evaluator is the sole semantic producer** of
  `MergeEligibilityDecision` and the deterministic `PolicyEvaluationRecord` payload. No
  human, event, review, or authority component may produce, amend, or replace a policy
  result.
- **Persistence writer** — only the **designated ChangeGate evaluation-record writer**
  may persist the evaluator-produced payload. Persistence must not alter, replace,
  supplement, or reinterpret any semantic field; must not author a second decision; and
  must not convert human review metadata into a policy result.
- **Append-only audit journal** — human review activity may be recorded only as
  **non-authoritative audit metadata** referencing the immutable policy result. A review
  record must not change disposition, change decision identity, authorize an action,
  establish an exception, or switch policy lineage.

Human actors cannot produce or persist a policy decision payload.

**Authority boundary:** only the pure evaluator may author a `MergeEligibilityDecision`
whose `decision_digest` verifies. Any consumer (ProcessGuard-equivalent, CLI, CI adapter)
must recompute and verify `decision_digest` and reject a decision that fails, exactly as
`validate_change_gate_decision` refuses a hand-constructed PASS today (golden case
GC-S1-024). A caller-authored "eligible" object without a verifying digest is
`AUTHORITY_INVALID`.

### 7.5 Runtime and authority boundary (normative, R7-NC1 / OD OWNER-SCOPE-R7-03)

This section is normative. It is a narrow clarification (owner decision
`OWNER_SCOPE_R7_03: NARROW_NORMATIVE_RUNTIME-BOUNDARY CLARIFICATION — ACCEPTED`),
not final Slice 1A acceptance. Its machine-readable form is
`slice_1a_semantic_manifest.runtime_authority_boundary`, which is
fingerprint-bearing; the concrete candidate audit data and owner disposition
live separately in the fingerprint-neutral `acceptance_governance` container.

**Authority separation (three layers).**

- **Local structural eligibility** is owned solely by the committed event
  schema (`LOCAL_STRUCTURAL_AUTHORITY=EVENT_SCHEMA`): envelope shape, field
  shape/types, requiredness, nullability, event-type-specific applicability,
  additional-property restrictions, local identifier/reference grammar, and
  `decision_ref` structure. The schema does **not** own cross-event evaluation
  identity, lineage, reachability, multi-parent, or cycle semantics.
- **Cross-event and causal eligibility** is owned solely by the relational and
  causal contract and its test-level validator
  (`CROSS_EVENT_CAUSAL_AUTHORITY=RELATIONAL_CAUSAL_CONTRACT`): duplicate event
  and evaluation identity, evaluation-identity consistency and drift,
  predecessor existence and type, reachability, task/candidate lineage,
  multi-root and multi-parent consistency, cross-root references, cycle
  detection, and feedback-target consistency.
- A runtime **representation guard** is authoritative for neither layer
  (`REPRESENTATION_GUARD_AUTHORITY=NONE`).

**Portable admitted runtime domain (RFC 8259 JSON value model).** The portable,
cross-language normative input domain is the RFC 8259 JSON value model — object,
array, string, finite number, boolean, and null — with these controls: object
member names must be strings; JSON numbers must be finite (NaN, +∞, and −∞ are
not admitted); boolean is a distinct JSON type and is never a number; non-JSON
application objects must be normalized before this boundary; custom-model or
proxy semantics are not implicitly admitted.

**Current Python implementation profile (implementation-bound, not portable
policy).** The current implementation represents JSON object → built-in `dict`
with string keys, array → `list`, string → `str`, number → finite `int`/`float`
excluding `bool`, boolean → `bool`, null → `None`. Non-built-in
`collections.abc.Mapping`s, Pydantic models, dataclasses, proxy objects, custom
domain objects, and partially adapted objects are **not** admitted directly and
must be normalized first. This Python profile is fingerprint-bearing for the
current implementation, lives in a separate manifest namespace from the portable
RFC 8259 domain, and is **not** portable ChangeGate policy semantics; changing
it triggers fresh equivalence review.

**Representation-guard permission.** A guard may run before full local
event-schema validation only if it is rejection-only, can never mark a value
eligible, performs representation-safety checks only, rejects only values the
authoritative schema rejects within the current implementation profile, and
contains no field, grammar, requiredness/nullability, event-type, identity,
policy, or relational/causal semantics; schema validation remains the sole
source of local structural eligibility for admitted event objects, and the
relational/causal validator remains the sole source of cross-event eligibility;
executable guard/schema equivalence checks protect the representation
assumption, and any divergence must fail closed and block acceptance. The
current `if not isinstance(item, dict): return ["EVENT_MALFORMED"]` guard is
permitted under the current Python profile; `isinstance(item, dict)` is not a
portable ChangeGate semantic rule.

**Expected invalid input versus unexpected internal validator fault.** For every
value in the admitted runtime domain, an expected validation failure returns a
structured invalid result, fails closed, quarantines the invalid event, prevents
graph-state mutation, and does not escape as an uncaught expected-validation
exception. An unexpected internal validator fault (corrupted validator state,
missing/broken dependency, invalid schema compilation, programming defect,
impossible internal invariant) must fail closed, remain observable through normal
internal-failure/test-failure mechanisms, prevent event entry into graph state,
and must **not** be silently converted into a malformed-input diagnostic or
misclassified as `EVENT_MALFORMED` (or any user-caused result) merely to keep
execution green. This clarifies the contract only; it does not add broad
`try/except`, a new exception framework, or any validator-logic change.

**Diagnostic contract.** Normative diagnostics are: reject structurally invalid
input, return a structured failure for expected invalidity, quarantine invalid
events, prevent graph-state mutation, pass schema-valid events to relational and
causal validation, and keep unexpected internal faults fail-closed and
observable. The exact diagnostic code, native JSON Schema message, keyword,
schema error path, and diagnostic ordering are non-normative implementation
diagnostics.

**Audit-history governance (abstract, fingerprint-bound).** Verifier findings and
their original severities are immutable audit history; owner disposition must be
recorded separately; acceptance must not rewrite, erase, or retroactively reduce
verifier history. Concrete candidate audit data (finding ids, counts, report
paths, candidate SHAs, timestamps, owner dispositions, detailed reopen-trigger
examples) is fingerprint-neutral and is recorded only in the existing designated
`acceptance_governance` container, never in the semantic manifest.

**Boundary re-review (abstract, fingerprint-bound).** The representation boundary
must be reviewed when an assumption required for representation-guard and schema
equivalence ceases to hold. Detailed operational reopen examples are
fingerprint-neutral governance metadata.

## 8. Disposition Semantics

The authoritative disposition is exactly one of:

- `ELIGIBLE_TO_MERGE_UNDER_POLICY` — every mandatory fact is present and green, required
  evidence is complete under §11, and the complete reason set is empty. Eligibility is a
  policy statement, not a safety guarantee, and it does not itself merge anything; merge
  execution remains a human-approved action (ProcessGuard path unchanged).
- `REVIEW_REQUIRED` — no blocking reason exists, but at least one policy-defined semantic
  uncertainty requires a human review to resolve (§17).
- `BLOCK` — at least one blocking reason exists. Fail-closed.

### Decision authority (SHADOW semantics)

A separate authoritative field, `decision_authority`, carries whether the decision can
authorize anything:

```
ENFORCE mode → decision_authority = AUTHORITATIVE
SHADOW  mode → decision_authority = ADVISORY_ONLY
```

SHADOW computes the same counterfactual disposition and complete reason set as ENFORCE
over the same facts — but it **never grants merge authorization**. A consumer must not
infer authorization from an eligible disposition when
`decision_authority = ADVISORY_ONLY`; any downstream gate must check BOTH
`disposition == ELIGIBLE_TO_MERGE_UNDER_POLICY` AND
`decision_authority == AUTHORITATIVE`. Golden cases GC-S1-031/032 pin both counterfactual
directions.

Forbidden output terms (ADR-001 §5): `SAFE_TO_MERGE` and `VERIFIED_AND_MERGE` must never
appear as output values; structural `PASS` is never an authority result; `accepted=True`
is never merge authorization. A genuinely eligible decision has an **empty** complete
reason set — mirroring today's rule that a genuine ChangeGate `PASS` has no findings.

Decision rule (total, deterministic):

```
if blocking_reason_codes non-empty        → BLOCK
elif review_reason_codes non-empty        → REVIEW_REQUIRED
else                                      → ELIGIBLE_TO_MERGE_UNDER_POLICY
decision_authority = AUTHORITATIVE iff evaluation_mode == ENFORCE else ADVISORY_ONLY
```

## 9. Reason-Code Taxonomy

Reason codes are stable machine-readable identifiers matching `^[A-Z][A-Z0-9_]*$`. The
code IS the canonical identity; user-facing prose lives only in diagnostic `explanations`
and may change without a policy version bump. Codes are never renamed in place — a
semantic change requires a new code and a policy version bump.

Legend — Category: INTEGRITY (identity/authority/provenance facts), FRESHNESS, EVIDENCE,
REPO_STATE, SCOPE, APPROVAL, INDEPENDENCE, CONTEXT. Kind: FACTUAL (observable, binary
given the input) or SEMANTIC (policy-interpreted). The taxonomy carries **no
override or exception classification**: per accepted OD-S1A-009 all
post-verdict authority semantics remain pending under OD-S1A-005 and are not
represented in Slice 1A machine artifacts (§17).

| Rank | Code | Category | Kind | Default disposition | Minimum evidence to emit | Explanation intent |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | `AUTHORITY_INVALID` | INTEGRITY | FACTUAL | BLOCK | `authority_status = INVALID`, `verifier_identity_status = INVALID`, or a presented decision whose digest fails verification | "The caller, verifier identity, or presented decision does not carry valid authority." |
| 20 | `REQUIRED_CONTEXT_INCOMPLETE` | CONTEXT | FACTUAL | BLOCK | any integrity-mandatory fact of §6 UNKNOWN / `scope_status = NOT_EVALUATED` / `verifier_identity_status = ABSENT` | "The policy could not obtain a mandatory fact; eligibility cannot be evaluated." |
| 30 | `EVIDENCE_TASK_MISMATCH` | INTEGRITY | FACTUAL | BLOCK | violation tag TASK_MISMATCH | "Evidence belongs to a different task." |
| 40 | `EVIDENCE_RUN_MISMATCH` | INTEGRITY | FACTUAL | BLOCK | violation tag RUN_MISMATCH | "Evidence belongs to a different evidence run." |
| 50 | `EVIDENCE_CANDIDATE_MISMATCH` | INTEGRITY | FACTUAL | BLOCK | violation tag CANDIDATE_MISMATCH | "Evidence was produced for a different candidate." |
| 60 | `REPOSITORY_CONTEXT_MISMATCH` | INTEGRITY | FACTUAL | BLOCK | `repository_snapshot_current = MISMATCH` | "The current repository is not the one the candidate belongs to." |
| 70 | `EVIDENCE_PROVENANCE_INVALID` | INTEGRITY | FACTUAL | BLOCK | `invalid_provenance_evidence_ids` non-empty, or violation tag PROVENANCE_INVALID | "Evidence provenance is invalid or unsupported." |
| 80 | `EVIDENCE_DUPLICATE_IDENTITY` | INTEGRITY | FACTUAL | BLOCK | violation tag DUPLICATE_IDENTITY | "Evidence identity is ambiguous." |
| 90 | `REQUIRED_EVIDENCE_INVALID` | EVIDENCE | FACTUAL | BLOCK | `invalid_requirement_ids` non-empty (§6.1) | "A required proof exists but failed structural verification." |
| 95 | `TASK_CONTEXT_STALE` | FRESHNESS | FACTUAL | BLOCK | `task_context_current = STALE` (contract digest no longer matches the candidate's bound contract digest) | "The governing task contract changed after this candidate was produced." |
| 100 | `CANDIDATE_STALE` | FRESHNESS | FACTUAL | BLOCK | `candidate_binding_current = STALE` | "The repository moved past this candidate; re-run against the current head." |
| 110 | `POLICY_CONTEXT_STALE` | FRESHNESS | FACTUAL | BLOCK | `policy_context_current = STALE` | "The decision would be made under an outdated policy." |
| 120 | `REQUIRED_EVIDENCE_MISSING` | EVIDENCE | FACTUAL | BLOCK | `missing_requirement_ids` non-empty (includes the empty-bundle-with-requirements case, ADR-001 §8) | "A required proof was never verified for this candidate." |
| 130 | `RELEASE_STATE_NOT_CLEAN` | REPO_STATE | FACTUAL | BLOCK | `repository_release_clean = DIRTY` | "The working tree is not release-clean." |
| 140 | `SCOPE_VIOLATION` | SCOPE | FACTUAL | BLOCK | `scope_status = VIOLATION` | "The change touches paths the contract forbids or does not allow." |
| 150 | `APPROVAL_MISSING` | APPROVAL | FACTUAL | BLOCK (recommended; PENDING_OWNER_DECISION OD-S1A-001) | `approval_status ∈ {MISSING, UNKNOWN}` while the contract requires approval for merge | "The required human approval has not been granted." |
| 160 | `APPROVAL_STALE` | APPROVAL | FACTUAL | BLOCK (recommended; PENDING_OWNER_DECISION OD-S1A-002) | `approval_status = STALE` | "The approval was for a different version of this change." |
| 170 | `VERIFIER_NOT_INDEPENDENT` | INDEPENDENCE | FACTUAL | BLOCK | `verifier_independence_status = NOT_INDEPENDENT` with identity present | "The change was verified by its own author." |
| 180 | `SCOPE_UNCERTAIN` | SCOPE | SEMANTIC | REVIEW_REQUIRED | `scope_status = SEMANTIC_UNCERTAIN` | "A human must judge whether this change is within the contract's intent." |
| 190 | `VERIFIER_INDEPENDENCE_UNKNOWN` | INDEPENDENCE | SEMANTIC | REVIEW_REQUIRED (boundary PENDING_OWNER_DECISION OD-S1A-003) | verifier rule §15 (identity present, independence not established) | "Independence could not be established automatically; a human must confirm it." |

Exactly 20 codes. The set is closed for policy v1: an evaluator may not invent codes, and
an unknown code in a presented decision fails digest verification.

**No overloading (Sol High H-01):** a stale task contract is `TASK_CONTEXT_STALE` and
nothing else — `POLICY_CONTEXT_STALE` (policy version), `REPOSITORY_CONTEXT_MISMATCH`
(wrong repository lineage) and `EVIDENCE_TASK_MISMATCH` (foreign evidence) must not be
reused to represent it.

## 10. Deterministic Precedence

> **Status of the rank table: DRAFT PROPOSAL, PENDING_OWNER_DECISION OD-S1A-007.** The
> ranks in §9 are the currently proposed draft. Owner acceptance may change them, but **a
> precedence change is a SEMANTIC change, not a metadata acceptance patch** (§27): it
> updates the spec, the fixture taxonomy AND the independently pinned rank table in the
> artifact tests together, it **alters the semantic fingerprint**, it **invalidates the
> current independent verification**, and it therefore **requires a new implementation
> candidate and fresh independent adversarial reverification** before merge. The tests pin
> their own copy of the complete table precisely so a rank change made in the fixture alone
> (even with expectations recomputed consistently) fails, and the semantic-fingerprint test
> fails on any precedence change.

- The **primary reason** is the emitted code with the **lowest rank** in §9's table.
  Ranks are unique per code, so the primary reason is total and deterministic.
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
     provenance because it is an evidence-identity integrity failure; requirement-level
     invalidity ranks last in the group because it presupposes an intact record);
  4. stale task/candidate/policy context → ranks 95–110 (`TASK_CONTEXT_STALE` before
     `CANDIDATE_STALE`: a stale governing contract invalidates the very requirements the
     candidate was evaluated against);
  5. missing mandatory evidence → rank 120;
  6. non-release-clean repository → rank 130;
  7. explicit scope violation → rank 140;
  8. approval missing or stale → ranks 150–160;
  9. verifier independence failure → rank 170;
  10. reviewable semantic uncertainty → ranks 180–190 (`SCOPE_UNCERTAIN` before
      `VERIFIER_INDEPENDENCE_UNKNOWN`, mirroring the scope-before-independence order of
      the factual groups).
- These refinements are explicit policy choices; changing them requires a policy version
  bump. The exact precedence when two *integrity* failures coexist is additionally listed
  as OD-S1A-007 for owner confirmation (golden cases GC-S1-021 and GC-S1-040 encode the
  recommended table and are marked pending).
- **Unknown mandatory facts never default to eligible** (§6.4 mapping).

## 11. Required Evidence Completeness

Normative rule (ADR-001 §8):

```
required evidence  ⊆  valid verified evidence bound to the current task, run and candidate
```

expressed exactly as `missing_requirement_ids = ∅ ∧ invalid_requirement_ids = ∅` under
the disjoint accounting of §6.1.

- **Matching key:** the stable `requirement_id` — `CommandRequirement.requirement_id` on
  the declaration side; `VerifiedCommandEvidence.requirement_id` on the satisfied side;
  the rejected record's `EvidenceProvenance.requirement_id` (via `EvidenceRunRecord`) on
  the invalid side. A verified record counts only when its task/run/candidate bindings
  equal the policy context's (the bundle and run-record models already seal this; the
  derivation layer re-checks rather than trusts).
- Completeness is **never** inferred from: command display text, command order, report
  prose, `tests_run` strings, filenames, or `accepted=True` alone.
- A **schema-valid empty bundle** is not inherently invalid; it simply verifies nothing.
  With a non-empty requirement set it yields `REQUIRED_EVIDENCE_MISSING` for every
  required id. With an empty requirement set, emptiness alone contributes no reason code
  (golden case GC-S1-020) — eligibility then depends only on the other policy conditions.

Reason-emission rules (normative):

| Code | Emitted iff |
| --- | --- |
| `REQUIRED_EVIDENCE_MISSING` | `missing_requirement_ids` non-empty |
| `REQUIRED_EVIDENCE_INVALID` | `invalid_requirement_ids` non-empty |
| `EVIDENCE_PROVENANCE_INVALID` | `invalid_provenance_evidence_ids` non-empty (record-level), or violation tag PROVENANCE_INVALID (context-level) — regardless of whether the affected requirement is otherwise satisfied |

Defined behaviors:

| Situation | Behavior |
| --- | --- |
| Duplicate evidence identities | `EVIDENCE_DUPLICATE_IDENTITY` (BLOCK); ambiguous identity satisfies nothing (same rule as ChangeGate Lite and `VerificationStatus.DUPLICATE_IDENTITY`) |
| Multiple verified records satisfying one requirement | Requirement is satisfied (≥ 1 rule); surplus is recorded in the trace, not a failure |
| One evidence record claiming multiple requirements | Unrepresentable at the domain layer (`EvidenceProvenance.requirement_id` is single-valued); if presented through any adapter it is `EVIDENCE_PROVENANCE_INVALID` |
| Unexpected evidence (valid record, requirement_id ∉ required set) | Recorded in `unexpected_evidence_ids` (record ids, diagnostic); never satisfies anything and, recommended, never blocks alone — treatment PENDING_OWNER_DECISION OD-S1A-006 (GC-S1-030) |
| Rejected-only requirement | `REQUIRED_EVIDENCE_INVALID` (GC-S1-026); NOT also missing (disjoint sets) |
| Valid AND rejected records for the same requirement | The valid record satisfies the requirement. A benign rejection (e.g. a failed earlier attempt) is diagnostic only (GC-S1-034). Independently confirmed provenance or identity corruption still emits its factual integrity reason even though the requirement is satisfied (GC-S1-035) |
| Evidence from another task / run / candidate | `EVIDENCE_TASK_MISMATCH` / `EVIDENCE_RUN_MISMATCH` / `EVIDENCE_CANDIDATE_MISMATCH` (BLOCK); such records are unbound and never satisfy or invalidate a requirement (the requirement stays missing) |

## 12. Candidate and Repository Freshness

Freshness is evaluated with the existing single-source rule
`candidate_snapshot_mismatches(candidate_binding, current_snapshot)`:

- `repository_id` or `object_format` or `base_commit_sha` divergence →
  `repository_snapshot_current = MISMATCH` → `REPOSITORY_CONTEXT_MISMATCH` (the
  evaluation is happening against the wrong repository lineage);
- same repository lineage but `head_commit_sha` ≠ `candidate_commit_sha`, or tree, or
  changed-files digest divergence → `candidate_binding_current = STALE` →
  `CANDIDATE_STALE` (the repository moved past the candidate; evidence and eligibility
  must be re-established against the new head);
- contract digest divergence (`contract_digest` ≠ `candidate_binding.contract_digest`) →
  `task_context_current = STALE` → `TASK_CONTEXT_STALE`;
- `current_snapshot.is_release_clean == False` → `RELEASE_STATE_NOT_CLEAN`, even when
  every structural verification is `VERIFIED` (golden case GC-S1-022; ADR-001 §7);
- `policy_context.current == False` → `POLICY_CONTEXT_STALE` — a decision may not be
  issued under a policy version the deployment no longer considers current.

The policy never calls Git to check freshness; the caller supplies the current snapshot,
and the decision is valid only for the snapshot identity recorded in its trace.

## 13. Scope Semantics

`scope_status` carries the outcome of deterministic scope evaluation (the existing
canonicalized-path, forbidden-before-allowed rules of `evaluate_change_gate` remain the
mechanism; ChangeGate Lite findings map into facts). The four values are exact and total:

| Value | Meaning | Mapping |
| --- | --- | --- |
| `COMPLIANT` | scope was evaluated; no violation, no reviewable question | no reason |
| `VIOLATION` | a changed path matches a forbidden pattern, is an invalid/traversal path, or falls outside `allowed_paths` without broad scope | BLOCK / `SCOPE_VIOLATION` |
| `SEMANTIC_UNCERTAIN` | scope was evaluated and a policy-designated reviewable question remains (e.g. dependency-file changes the contract routes to a human, an empty change set, or contract-sanctioned broad scope whose breadth demands judgment) | REVIEW_REQUIRED / `SCOPE_UNCERTAIN` |
| `NOT_EVALUATED` | the changed-file set or scope check could not be performed at all | BLOCK / `REQUIRED_CONTEXT_INCOMPLETE` |

There is no scope `UNKNOWN` state: an unevaluated scope is missing mandatory context
(`NOT_EVALUATED`), never reviewable uncertainty. This removes the former §6/§13
ambiguity (Sol High H-01.4). Scope facts must be derived from the same canonical path
normalization as ChangeGate Lite (no second path grammar).

## 14. Approval and Authority

No canonical `ApprovalRecord` or `ActorIdentity` exists (ADR-003), and Slice 1 does not
create one. The application-level facts are:

- **`ApprovalFact`** — an explicit, attributable approval statement: opaque
  `approver_actor_ref`, `approved_at` (caller-supplied timestamp), an internal
  `approval_fact_digest`, and the **binding target**: `task_id`,
  `candidate_commit_sha`/`candidate_tree_sha` (or the full `CandidateBinding` digest),
  `contract_digest`, `policy_digest`. The A2 input carries the canonical digest of this
  fact (or the sentinel) in the single field `approval_digest_or_sentinel` (§5.2/§7.3). An
  approval is:
  - `VALID` — binds exactly to the input task/candidate/contract/policy;
  - `STALE` — exists but binds to a different candidate, contract digest, or policy
    digest (approving commit A never approves commit B);
  - `MISSING` — absent while `"merge" ∈ contract.requires_human_approval_for`;
  - `UNKNOWN` — the approval state could not be established; treated as `MISSING`
    (recommended; the disposition itself is PENDING_OWNER_DECISION OD-S1A-001).
  When the contract does **not** require approval for merge, `approval_status = VALID`
  vacuously and no approval code is emitted (the ProcessGuard `READY_FOR_MERGE` path is
  unchanged).
- **`AuthorityFact`** — who requests evaluation and who may consume the decision: opaque
  `actor_ref`, `role_ref`, and a validity status computed by the application layer. The
  policy consumes only the status; it never interprets role semantics (that is a future
  kernel concern, OD-G1-003).

Dispositions for `APPROVAL_MISSING` and `APPROVAL_STALE` are recommended BLOCK but are
**PENDING_OWNER_DECISION** (OD-S1A-001, OD-S1A-002; §25). The golden fixture encodes the
recommended default and marks the affected cases in `owner_decisions_pending`.

## 15. Verifier Independence

**`VerifierIdentityFact`** records: opaque `verifier_actor_ref`, opaque
`implementer_actor_ref`, verifier software identity (`verifier_version`), an identity
status, and an independence status. Two facts are derived — both required so the future
owner-approved OD-S1A-003 rule can be implemented without inventing a new fact:

- `verifier_identity_status`: `ATTESTED` (identity present and attested) |
  `PRESENT_UNATTESTED` (identity reference present, attestation absent) | `ABSENT`
  (no identity reference at all) | `INVALID` (identity reference fails validation);
- `verifier_independence_status`: `INDEPENDENT` | `NOT_INDEPENDENT` | `UNKNOWN`.

**Ordered first-match combination rule (total over all 12 combinations; normative,
machine-readable in the fixture's `fact_state_mapping.verifier_rule`):**

1. identity `INVALID` → `AUTHORITY_INVALID` (a corrupt identity is an authority
   integrity failure);
2. identity `ABSENT` → `REQUIRED_CONTEXT_INCOMPLETE` (an anonymous verifier is missing
   mandatory context, never reviewable uncertainty);
3. independence `NOT_INDEPENDENT` (identity present, attested or not) →
   `VERIFIER_NOT_INDEPENDENT` (self-verification is a protected root-of-trust rule,
   ADR-001 §9; an admission does not need attestation);
4. identity `ATTESTED` + independence `INDEPENDENT` → no reason;
5. identity `ATTESTED` + independence `UNKNOWN` → `VERIFIER_INDEPENDENCE_UNKNOWN`
   (REVIEW_REQUIRED recommended; boundary PENDING_OWNER_DECISION OD-S1A-003);
6. identity `PRESENT_UNATTESTED` + independence `INDEPENDENT` or `UNKNOWN` →
   `VERIFIER_INDEPENDENCE_UNKNOWN` (an unattested identity cannot ground an independence
   claim; recommended reviewable, same OD-S1A-003 boundary).

The structural verifier (`EvidenceVerifier` port) remains independent of the policy
evaluator: the policy consumes its bundle output and never re-implements structural
verification, and the evaluator must not be the component that produced the evidence.

## 16. Multiple-Failure Behavior

When multiple failures coexist:

- every independently confirmed failure appears in `complete_reason_codes`
  (lexicographic order);
- exactly one `primary_reason_code` is selected by rank (§10);
- `blocking_reason_codes` / `review_reason_codes` partition the complete set by each
  code's effective disposition under the active policy version;
- the disposition is computed from the partition (§8) — a reviewable code never dilutes a
  blocking code (golden case GC-S1-033 pins simultaneous BLOCK + REVIEW_REQUIRED
  reasons);
- determinism guarantees: no dependence on dict/set iteration order; set-typed inputs are
  canonically sorted before evaluation; two runs over the same input digest must produce
  byte-identical decisions (same `decision_digest`, §18).

Golden cases GC-S1-021 (mixed factual failures), GC-S1-033 (block + review) and
GC-S1-040 (dual integrity failures, OD-S1A-007) pin this behavior.

## 17. Human Override Boundaries

**Factual integrity failures cannot be overridden by an ordinary approval action.** Wrong
candidate, invalid provenance, foreign task/run evidence, invalid authority, corrupt
identity binding, duplicate evidence identity, repository mismatch — no approval, review,
or feedback changes these facts. This is a prohibition only: Slice 1A defines **no
machine classification** of any reason by overrideability, exception eligibility, or
human resolvability — every such classification is OD-S1A-005 subject matter.

A policy **requirement** (e.g. which evidence is required, whether a dirty tree may ever
ship) may change only through:

- a **new policy version**; or
- an explicit **owner-approved contract amendment**; or
- in the future, a separately authorized **policy exception** — whose authority, scope,
  expiry, revocation and consumption semantics are ALL PENDING_OWNER_DECISION OD-S1A-005
  and belong to a separate future governance slice. **Slice 1A defines no exception claim,
  no exception authorization, no expiry, no revocation, no consumption state, and no
  authority binding for exceptions** (accepted OD-S1A-009). The future design must use a
  separate authority artifact referencing the immutable policy verdict; OD-S1A-009 does
  not decide that artifact's name or schema.

A `REVIEW_REQUIRED` disposition asks for human judgment (§8). How any review,
approval, or exception activity may act on a verdict is entirely OD-S1A-005 subject
matter: Slice 1A classifies no reason by what a human may later do about it. In Slice 1A
the recording of review activity is **non-authoritative audit metadata only** (§7.4): it
must not change the disposition, change decision identity, authorize an action, establish
an exception, or switch policy lineage. Slice 1A defines **no review/override event** —
review and approval events belong to the future governance slice. The original decision
and trace are immutable; when governance exists, a new *authority* context is produced —
never a second policy result and never an edit.

## 18. EvaluationTraceEnvelope

The **application layer** — not the pure evaluator — constructs the trace envelope, after
policy evaluation has returned. The evaluator never writes to SQLite, JSONL, network
telemetry, or a global logger, and it never mints a trace/request/evaluation identity, a
timestamp, or a latency. Whether strict deployments must require successful trace
persistence **before** a decision may be released to consumers is PENDING_OWNER_DECISION
OD-S1A-004 (GC-S1-038).

### 18.1 Construction boundary (normative)

```
A3-derived validated facts and source bindings
→ A2 pure evaluator
→ MergeEligibilityDecision + PolicyEvaluationRecord      (deterministic, no clock, no ids)
→ application EvaluationTraceEnvelope                    (ids, timestamp, latency)
→ event sink                                             (§19)
```

Any statement that the pure evaluator produces request ids, timestamps, latency, or a
trace envelope is superseded by this section.

### 18.2 EvaluationTraceEnvelope contents (exact)

| Field | Content | Source |
| --- | --- | --- |
| `schema_version` | `"changegate.evaluation-trace-envelope.v1"` | application layer |
| `trace_id`, `evaluation_id`, `request_id` | trace identities | application layer |
| `occurred_at` | RFC 3339 UTC | application layer (caller clock) |
| `evaluation_latency_ms` | measured duration | application layer |
| `redaction_classification` | privacy class (§21), from `PUBLIC \| INTERNAL \| SENSITIVE` | application layer |
| `policy_record` | the deterministic `PolicyEvaluationRecord` (§7.3), embedded verbatim | pure evaluator |
| `policy_record_digest` | `= canonical_digest(policy_record payload)` | pure evaluator |
| `input_digest` | `= policy_record.input_digest` | pure evaluator |
| `decision_digest` | `= policy_record.decision_digest` | pure evaluator |
| `trace_digest` | `= canonical_digest(trace_payload)` | application layer |

Digest definitions:

```
trace_payload = all trace-envelope fields EXCEPT trace_digest
trace_digest  = canonical_digest(trace_payload)
```

### 18.3 Trace consistency (normative, executably tested)

The envelope embeds the exact deterministic record and never edits it. These equalities
must hold and are checked by an independent trace validator (§10 negative controls
enumerate the mismatches it must reject):

```
trace.policy_record_digest == canonical_digest(trace.policy_record payload)
trace.input_digest         == trace.policy_record.input_digest
trace.decision_digest      == trace.policy_record.decision_digest
```

Changing any embedded record field without recomputing all dependent digests
(`policy_record_digest`, and — because the record is inside the trace payload —
`trace_digest`) must fail validation. Changing application metadata
(`trace_id`/`occurred_at`/`evaluation_latency_ms`/`redaction_classification`) changes
`trace_digest` only, never `policy_record_digest` or `decision_digest`. Because
`redaction_classification` lives only here and never in the record payload, a privacy
reclassification can never alter deterministic decision or policy-record identity.

### 18.4 Trace negative controls (all must be detected)

An independent trace validator must reject: (1) mismatched top-level decision digest;
(2) mismatched input digest; (3) mismatched policy-record digest; (4) a changed source
digest inside the record without a record-digest update; (5) a changed disposition;
(6) a changed complete reason set; (7) a changed authority; (8) a `trace_digest` not
recomputed after a metadata change; (9) an embedded record from another task;
(10) an embedded record from another candidate.

### 18.5 Complete determinism key and replay invariants (normative; executably pinned)

The **complete deterministic replay key** is:

```
canonical MergeEligibilityPolicyInput
policy_version (and policy_digest)
evaluator_version
evaluation_mode
policy_record_schema_version
canonicalization_version
canonicalization_contract_digest
```

The record-schema and canonicalization bindings reside as follows (no per-record
duplication beyond what already exists): `policy_record_schema_version` is the record's
own `schema_version` field; `policy_record_schema_digest` (the digest of the typed field
contract), `canonicalization_version`, and `canonicalization_contract_digest` are declared
in the semantic manifest (`deterministic_identity`) and are bound into the canonical A2
input payload, so changing any of them changes `input_digest` and therefore every
downstream identity. Canonicalization behavior is **explicit**, not implicit: the
canonicalization contract (UTF-8, NFC, sorted keys, compact separators, no non-finite
numbers, `sha256:`-prefixed digest over canonical bytes — the production
`canonical_json_bytes`/`canonical_digest`) is recorded in the manifest and digested as
`canonicalization_contract_digest`.

Required invariant:

```
same complete deterministic replay key
→ same semantic decision
→ same canonical decision payload → same decision_digest
→ same canonical PolicyEvaluationRecord → same policy_record_digest
```

**Version-bump rules (normative):** a semantic policy change requires a
`policy_version`/`policy_digest` change; an evaluator semantic change requires an
`evaluator_version` change; a record-schema change requires a
`policy_record_schema_version` change; a canonicalization change requires a
`canonicalization_version` **and** `canonicalization_contract_digest` change.

| # | Invariant |
| --- | --- |
| 1 | same complete replay key → same `input_digest` |
| 2 | same complete replay key → same `decision_digest` and `policy_record_digest` |
| 3 | `request_id` / `trace_id` / `evaluation_id` change → `decision_digest` and `policy_record_digest` unchanged |
| 4 | timestamp, latency or `redaction_classification` change → `decision_digest` and `policy_record_digest` unchanged (`trace_digest` changes) |
| 5 | `repository_snapshot_digest` change → `decision_digest` and `policy_record_digest` change |
| 6 | `verification_bundle_digest` change → `decision_digest` and `policy_record_digest` change |
| 7 | `approval_digest_or_sentinel` change (including to/from `NO_APPROVAL_SUPPLIED`) → `decision_digest` and `policy_record_digest` change |
| 8 | `authority_binding_digest` or `verifier_binding_digest` change → `decision_digest` and `policy_record_digest` change |
| 9 | `policy_version`/`policy_digest`, `evaluator_version`, or `evaluation_mode` change → `decision_digest` and `policy_record_digest` change |
| 10 | application trace metadata change → `trace_digest` changes; `decision_digest` and `policy_record_digest` unchanged |
| 11 | `policy_record_schema_version` or `policy_record_schema_digest` change → deterministic identity changes |
| 12 | `canonicalization_version` or `canonicalization_contract_digest` change → deterministic identity changes |

A deterministic source digest is **never** excluded from decision or policy-record
identity merely because it also appears in the trace envelope (invariants 5–8).

**Replay contract versus Slice 1A verification boundary.** The invariants above define
the deterministic contract the future Slice 1B pure evaluator must satisfy: the record
and decision are reproducible from the complete replay key alone (single-sourced
`evaluation_mode`, no `redaction_classification` in the record), every digest above is
computed with the production `canonical_digest()`, and — per accepted OD-S1A-009 — **no
Slice 1A mechanism can produce a second decision or record for the same replay key**.
Slice 1A artifact tests verify only the *identity consequences* of this contract
(digest recomputation, binding equality, mutation sensitivity) through a test-only
oracle; they perform no semantic replay (`SEMANTIC_REPLAY_NOT_PERFORMED`, §7.3).
Proving that a supplied policy result was reproduced by the real evaluator
(`SEMANTICALLY_REPLAY_VERIFIED`) is a Slice 1B protocol obligation.

Three layers are distinguished and must not be conflated:

1. **deterministic policy record** (§7.3) — replayable from digests and reason codes
   without raw source code, command output, or secrets;
2. **application telemetry** (latency, sink health, retries) — owned by the application
   layer, carried in the trace envelope, referenced by `trace_id`;
3. **raw debug logs** — never part of the contract, never required for replay, and
   subject to §21 redaction.

## 19. Product Event Schema

Artifact: `data/schemas/changegate_evaluation_event_v1.schema.json` (JSON Schema Draft
2020-12, fixed `schema_version` const `changegate-evaluation-event.v1`). The envelope is
sink-agnostic (later JSONL, SQLite, or remote sinks consume the same shape).

Event types (closed set for v1 — **six** types):

`CHANGEGATE_EVALUATION_COMPLETED`, `CHANGEGATE_MERGE_ATTEMPTED`,
`CHANGEGATE_MERGE_COMPLETED`, `CHANGEGATE_POST_MERGE_VALIDATION`,
`CHANGEGATE_ROLLBACK_RECORDED`, `CHANGEGATE_USER_FEEDBACK_RECORDED`.

Review/approval/exception events are **not** part of Slice 1A (accepted OD-S1A-009): they
belong to a future governance slice gated on OD-S1A-005, and no Slice 1A event may carry
a second policy-decision identity.

### 19.1 Causal chain (deterministically reconstructable)

Every event after the evaluation names the **exact** earlier event it descends from,
through a bounded `eventRef` grammar that is distinct from content-bearing values (an
event reference may only ever name an event):

```
CHANGEGATE_EVALUATION_COMPLETED
        ↓ evaluation_event_ref
CHANGEGATE_MERGE_ATTEMPTED
        ↓ attempt_event_ref
CHANGEGATE_MERGE_COMPLETED
        ↓ merge_event_ref
CHANGEGATE_POST_MERGE_VALIDATION
        ↓ merge_event_ref (+ validation_event_ref where applicable)
CHANGEGATE_ROLLBACK_RECORDED          optional
        ↓ target_event_ref (+ target_event_type)
CHANGEGATE_USER_FEEDBACK_RECORDED
```

**Per-event conditional linkage.** The schema enforces with Draft 2020-12
`allOf`/`if`/`then` constraints, minimally:

| Event type | Additionally required (non-null) |
| --- | --- |
| `CHANGEGATE_EVALUATION_COMPLETED` | `decision_ref` (with `disposition` **and** `decision_authority`), `context_digest` (= A2 `input_digest`), `policy_version`, `evaluator_version`, `outcome` |
| `CHANGEGATE_MERGE_ATTEMPTED` | `decision_ref` (decision digest), `evaluation_event_ref` (originating evaluation), `outcome` (attempt status); candidate/subject via envelope-required `subject_ref` |
| `CHANGEGATE_MERGE_COMPLETED` | `decision_ref`, **`attempt_event_ref`** (the exact attempt this resolves — this is what makes multiple attempts deterministically pairable with their result), `outcome` with **`resulting_commit_sha`** (dedicated lowercase-hex field) |
| `CHANGEGATE_POST_MERGE_VALIDATION` | `decision_ref`, `merge_event_ref` (exact completion), validation `outcome` |
| `CHANGEGATE_ROLLBACK_RECORDED` | `decision_ref`, `merge_event_ref` (exact completion), `outcome` with machine-readable `detail_code`; `validation_event_ref` where a validation motivated it |
| `CHANGEGATE_USER_FEEDBACK_RECORDED` | `decision_ref`, **`target_event_ref`** (the exact prior event being judged), **`target_event_type`** (eligibility decision / merge outcome / validation / rollback), structured `feedback` with a mandatory **`feedback.actor_ref`** (the human/source identity — `provenance.emitter` identifies the emitting application and is never the feedback actor); no policy-mutation field exists |

**Full decision identity on every `decision_ref` (§11).** For all six event types the
`decision_ref` is required to carry the complete decision identity, not just the decision
digest: `evaluation_id`, `decision_digest`, `input_digest`, `policy_record_digest`,
`task_ref`, and `candidate_digest`. This lets the causal validator check the SIX-field
lineage across every edge (§19.3) rather than trusting the decision digest alone.

A minimal common-envelope-only instance is invalid for **every** event type (executably
tested, positive and negative), and a full valid chain is reconstructable end to end:
every reference resolves to an earlier event of the correct type, the decision identity
stays consistent across the chain, task/candidate lineage matches the root, and
attempt/result/validation/feedback pair deterministically (executably tested by a
test-only cross-event chain validator; JSON Schema itself validates local shape only).

### 19.3 Graph-based multi-root lineage (END_TO_END_RECONSTRUCTABLE)

Lineage is a **graph keyed by causal event references**, not a single global "active
lineage" over list order. The canonical active lineage is the **six-field tuple**:

```
evaluation_id · task_ref · candidate_digest · decision_digest · input_digest · policy_record_digest
```

`evaluation_id` is not optional metadata — it identifies the evaluation root producing
the immutable decision identity. Each
`CHANGEGATE_EVALUATION_COMPLETED` event establishes an **independent root**, keyed by its
own evaluation event id, registering its complete six-field lineage.

**Evaluation identity registry (§11, R5).** The validator maintains
`evaluation_id → complete lineage`. Every `evaluation_id` is globally unique within the
event graph; a root registers one complete lineage; the same `evaluation_id` may never map
to two identities; a downstream event preserves the root `evaluation_id`. **Duplicate root
evaluation IDs are rejected even when the event IDs differ.**

Each downstream event derives its lineage from the **causal event it references** (its
`evaluation_event_ref` / `attempt_event_ref` / `merge_event_ref` / `validation_event_ref` /
`target_event_ref`), not from list position. The validator supports multiple independent
tasks, candidates, evaluation roots, and interleaved event streams. No event inherits
lineage merely because it appears later in the list. A new candidate starts a new evaluation
root and never mutates an existing root.

Every downstream causal event must match its **referenced root's** six-field lineage. The
test-level causal validator (JSON Schema cannot
express cross-event equality) rejects, at minimum:

1. nonexistent event reference; 2. forward reference; 3. wrong referenced event type;
4. duplicate event id; 5. decision-digest drift; 6. input-digest drift;
7. policy-record-digest drift; 8. feedback target-type mismatch; 9. merge completion
referencing another task's attempt; 10. merge completion referencing another candidate's
attempt; 11. rollback referencing another task/candidate's merge; 12. feedback referencing
another task; 13. feedback referencing another candidate; 14. a locally valid but
causally disconnected event; 15. a changed candidate continuing the old chain without a
new evaluation event; 16. a **duplicate evaluation ID** (even with different event IDs);
17. **downstream evaluation-ID drift**; 18. an event referencing a valid predecessor but
carrying another evaluation ID; 19. a **causal cycle**; 20. **ambiguous predecessor
lineage** (§19.6).

### 19.6 Multi-parent lineage consistency (normative, R5)

For every event with **more than one** explicit causal reference — e.g. a rollback's
`merge_event_ref` and `validation_event_ref` — the validator validates **every**
predecessor, not one "primary" and the rest merely type-checked. Each predecessor must
exist, be of the required type, be reachable from an evaluation root, and carry the **same**
active six-field lineage. The event's lineage is defined as the one identical lineage shared
by every explicit predecessor:

```
event lineage = the single lineage shared by all explicit predecessors
```

If predecessor lineages disagree (e.g. a merge from root A and a validation from root B),
the event is rejected as `AMBIGUOUS_PREDECESSOR_LINEAGE`. This rule applies to every event
type carrying more than one causal/source reference.

**Immutable policy lineage (normative, R6).** The six-field lineage is established only
by `CHANGEGATE_EVALUATION_COMPLETED` and every descendant repeats it exactly. No Slice 1A
event can replace, amend, reinterpret, or switch policy lineage. A changed candidate must
start a new evaluation root. Review, approval, exception, and action-authorization events
are absent from Slice 1A and remain future governance work pending OD-S1A-005.

### 19.2 Envelope fields

`event_id`, `event_type`, `occurred_at`, `schema_version`, `product` (const
`"changegate"`), `project_ref`/`task_ref`/`run_ref`, `subject_ref` (namespace + closed
machine-readable `kind` enum + opaque `value` + dedicated `commit_sha` + canonical
`digest` — shaped after ADR-003 §8 `SubjectRef` as a JSON reference; this does NOT
implement the kernel `SubjectRef` model), `context_digest`, `policy_version` +
`evaluator_version`, `decision_ref` (evaluation id, canonical `decision_digest`,
**required** `input_digest`, `policy_record_digest`, `task_ref` and `candidate_digest`,
plus optional disposition, decision authority, primary reason, evaluation mode), the causal
references `evaluation_event_ref` / `attempt_event_ref` /
`merge_event_ref` / `validation_event_ref` / `target_event_ref` + `target_event_type`,
`evidence_refs` (ids + canonical digests only), `outcome` (status + machine-readable
`detail_code` + optional `resulting_commit_sha`; empty objects are invalid), `feedback`
(structured: actor ref + verdict + category code + optional reason code + optional opaque
redacted-comment digest; no raw text), `provenance` (emitter + emitter version
+ trace linkage), `privacy_classification`.

Every digest field uses the canonical `sha256:<64 lowercase hex>` representation of §7.1,
so a real `canonical_digest()` value is directly carriable with no conversion.

The schema **must not require** and does not define fields for: raw prompts, source file
contents, secrets, credentials, or entire command output.

### 19.5 Task identity consistency (normative)

`event.task_ref` and `event.decision_ref.task_ref` use the **one** shared `taskRef`
grammar (`$defs/taskRef`: bounded, no-whitespace, no path separators, no URLs) — there is
no weaker nested grammar, so a trailing newline, tab, or Unicode whitespace is rejected in
`decision_ref.task_ref` exactly as at the envelope level. For **every** event the
test-level validators additionally enforce:

```
event.task_ref == event.decision_ref.task_ref
```

and, when the event's `subject_ref` represents the candidate (`kind = git_candidate` with a
`digest`),

```
event.subject_ref.digest == event.decision_ref.candidate_digest.
```

A locally schema-valid but identity-inconsistent event (envelope task A / decision task B,
or a candidate-subject digest differing from the decision candidate digest) is rejected.

## 20. Outcome and Feedback Linkage

Every decision is linkable to reality through the event chain, keyed by `evaluation_id` /
`decision_digest`:

```
CHANGEGATE_EVALUATION_COMPLETED
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
the active policy version is unchanged until a proposal passes the full pipeline
including owner approval (golden case GC-S1-025). Slice 1 artifacts support controlled
improvement proposals, not autonomous self-modification.

## 21. Privacy, Security and Redaction

### 21.1 Division of responsibility (what the schema can and cannot do)

```
Schema-level controls:
    shape, grammar, length and forbidden content-bearing structures.

Application sink controls:
    redaction, secret scanning, allowlist validation and access policy.
```

**The schema does not, and cannot, identify every possible secret value.** A bounded
identifier grammar plus a deny-list of the most common credential shapes rejects the
obvious cases; it is not a secret scanner. Any claim that the event contract alone
guarantees the absence of secrets or source-like content is out of scope and must not be
made. Sinks remain responsible for redaction, scanning and access control.

### 21.2 Schema-level controls (enforced, executably tested)

- Traces and events carry **digests and identifiers only**: no raw stdout/stderr (the
  provenance layer already stores `stdout_digest`/`stderr_digest`), no file contents, no
  prompts, no command output. No field for such content exists.
- **Narrow reference grammar:** every opaque identifier/reference field (`event_id`,
  `project_ref`, `run_ref`, `subject_ref.namespace`/`value`, actor refs, exception refs,
  emitter, and every `*_event_ref`) permits only letters, digits, `_`, `-` and `.`, with
  bounded length. This rejects whitespace and newlines, path separators, `..` traversal,
  URLs and URL schemes, diff/code fragments, and overlong values. `task_ref` keeps the
  existing `TaskContract.task_id` grammar so current TOMTIT task ids stay representable;
  generated ids (`[a-z0-9][a-z0-9-]{0,63}`) are representable unchanged.
- A defensive **deny-list** additionally rejects the most common credential shapes
  (`ghp_`, `github_pat_`, `xox*-`, `sk-`, `AKIA`, `AIza`, JWT prefixes) in opaque
  references. This is a guard, not a guarantee (§21.1).
- **Structured values get dedicated fields** instead of being packed into an opaque
  string: a Git commit uses the lowercase-hex `commit_sha` / `resulting_commit_sha`
  fields; a canonical digest uses a `sha256:<hex>` digest field; an event id uses the
  bounded `eventRef` grammar; `subject_ref.kind` is a closed machine-readable enum.
- `privacy_classification` (event) and `redaction_classification` (policy record / trace)
  are mandatory, from the closed set `PUBLIC`, `INTERNAL`, `SENSITIVE`; sinks must refuse
  an event without a classification.
- Feedback is structured (actor ref + verdict + category code + optional reason code +
  optional opaque redacted-comment digest); unrestricted raw feedback text is not
  representable in the envelope.
- Outcome objects cannot be empty: each required outcome carries at least a `status` and
  a machine-readable `detail_code`.
- Actor references are **opaque ids**, never emails or display names, in both records and
  events.

### 21.3 Application sink controls (not enforced by this schema)

- Redaction of any free text before it is stored anywhere outside the envelope;
- secret scanning of values that are grammatically valid but semantically sensitive;
- allowlist validation of actor/project/run references against real identity systems;
- access policy and retention per `privacy_classification`.

Command `argv` may appear in diagnostics only after the application layer's redaction
pass; the policy record itself references commands by `requirement_id`/`command_digest`.
Golden fixtures and schemas in this slice contain no real secrets, credentials, or private
keys (executably enforced by the artifact tests). Raw debug logs are outside the policy
contract and must never be required to replay a decision (§18).

## 22. Golden Evaluation Matrix

Artifact: `data/evals/changegate_merge_eligibility_golden_cases.json` (deterministic,
versioned `changegate-merge-eligibility-golden.v8`; 41 cases GC-S1-001 … GC-S1-041). The
fixture embeds the normative `fact_state_mapping`, and the artifact tests derive every
case's complete reason set independently from its facts via a test-only oracle (never
from the case's own expectations). Every closed reason code appears as an expected reason
in at least one case; every OD-S1A decision that controls an expected result has at least
one case marked in `owner_decisions_pending`.

Authority column: AUTH. = AUTHORITATIVE (ENFORCE), ADVISORY_ONLY = SHADOW.

| Case | Scenario | Disposition | Primary reason | Authority | Pending ODs |
| --- | --- | --- | --- | --- | --- |
| GC-S1-001 | Complete, current, clean, authorized | ELIGIBLE_TO_MERGE_UNDER_POLICY | — | AUTH. | — |
| GC-S1-002 | Empty bundle with mandatory evidence | BLOCK | REQUIRED_EVIDENCE_MISSING | AUTH. | — |
| GC-S1-003 | Partial mandatory evidence | BLOCK | REQUIRED_EVIDENCE_MISSING | AUTH. | — |
| GC-S1-004 | Evidence from another task | BLOCK | EVIDENCE_TASK_MISMATCH | AUTH. | — |
| GC-S1-005 | Evidence from another run | BLOCK | EVIDENCE_RUN_MISMATCH | AUTH. | — |
| GC-S1-006 | Evidence from another candidate | BLOCK | EVIDENCE_CANDIDATE_MISMATCH | AUTH. | — |
| GC-S1-007 | Duplicate evidence identity | BLOCK | EVIDENCE_DUPLICATE_IDENTITY | AUTH. | — |
| GC-S1-008 | Candidate stale | BLOCK | CANDIDATE_STALE | AUTH. | — |
| GC-S1-009 | Repository context mismatch | BLOCK | REPOSITORY_CONTEXT_MISMATCH | AUTH. | — |
| GC-S1-010 | Repository dirty | BLOCK | RELEASE_STATE_NOT_CLEAN | AUTH. | — |
| GC-S1-011 | Explicit scope violation | BLOCK | SCOPE_VIOLATION | AUTH. | — |
| GC-S1-012 | Semantic scope uncertainty | REVIEW_REQUIRED | SCOPE_UNCERTAIN | AUTH. | — |
| GC-S1-013 | Approval missing (recommended default) | BLOCK | APPROVAL_MISSING | AUTH. | OD-S1A-001 |
| GC-S1-014 | Approval stale (recommended default) | BLOCK | APPROVAL_STALE | AUTH. | OD-S1A-002 |
| GC-S1-015 | Caller authority invalid | BLOCK | AUTHORITY_INVALID | AUTH. | — |
| GC-S1-016 | Verifier not independent | BLOCK | VERIFIER_NOT_INDEPENDENT | AUTH. | — |
| GC-S1-017 | Independence unknown, identity ATTESTED | REVIEW_REQUIRED | VERIFIER_INDEPENDENCE_UNKNOWN | AUTH. | OD-S1A-003 |
| GC-S1-018 | Stale policy context | BLOCK | POLICY_CONTEXT_STALE | AUTH. | — |
| GC-S1-019 | Required context unknown (mandatory-context rule) | BLOCK | REQUIRED_CONTEXT_INCOMPLETE | AUTH. | — |
| GC-S1-020 | No requirement + empty explicit-context bundle | ELIGIBLE_TO_MERGE_UNDER_POLICY | — | AUTH. | — |
| GC-S1-021 | Multiple failures (foreign task + dirty + no approval) | BLOCK | EVIDENCE_TASK_MISMATCH | AUTH. | OD-S1A-001, OD-S1A-007 |
| GC-S1-022 | Structural VERIFIED but release state dirty | BLOCK | RELEASE_STATE_NOT_CLEAN | AUTH. | — |
| GC-S1-023 | Structural VERIFIED but approval stale | BLOCK | APPROVAL_STALE | AUTH. | OD-S1A-002 |
| GC-S1-024 | Caller authors an "eligible" decision directly | BLOCK | AUTHORITY_INVALID | AUTH. | — |
| GC-S1-025 | Feedback claims a valid block was wrong | BLOCK (unchanged) | SCOPE_VIOLATION | AUTH. | — |
| GC-S1-026 | Rejected-only requirement | BLOCK | REQUIRED_EVIDENCE_INVALID | AUTH. | — |
| GC-S1-027 | Invalid-provenance record on a required id, no valid record | BLOCK | EVIDENCE_PROVENANCE_INVALID | AUTH. | — |
| GC-S1-028 | Task context stale | BLOCK | TASK_CONTEXT_STALE | AUTH. | — |
| GC-S1-029 | Scope not evaluated | BLOCK | REQUIRED_CONTEXT_INCOMPLETE | AUTH. | — |
| GC-S1-030 | Unexpected but valid evidence (diagnostic only) | ELIGIBLE_TO_MERGE_UNDER_POLICY | — | AUTH. | OD-S1A-006 |
| GC-S1-031 | SHADOW eligible counterfactual | ELIGIBLE_TO_MERGE_UNDER_POLICY | — | ADVISORY_ONLY | — |
| GC-S1-032 | SHADOW block counterfactual | BLOCK | RELEASE_STATE_NOT_CLEAN | ADVISORY_ONLY | — |
| GC-S1-033 | Simultaneous BLOCK + REVIEW_REQUIRED reasons | BLOCK | RELEASE_STATE_NOT_CLEAN | AUTH. | — |
| GC-S1-034 | Valid + benign-rejected records, same requirement | ELIGIBLE_TO_MERGE_UNDER_POLICY | — | AUTH. | — |
| GC-S1-035 | Satisfied requirement + invalid-provenance record | BLOCK | EVIDENCE_PROVENANCE_INVALID | AUTH. | — |
| GC-S1-036 | Verifier identity absent | BLOCK | REQUIRED_CONTEXT_INCOMPLETE | AUTH. | OD-S1A-003 |
| GC-S1-037 | Verifier identity present-unattested | REVIEW_REQUIRED | VERIFIER_INDEPENDENCE_UNKNOWN | AUTH. | OD-S1A-003 |
| GC-S1-038 | Strict-mode trace persistence gating | ELIGIBLE_TO_MERGE_UNDER_POLICY | — | AUTH. | OD-S1A-004 |
| GC-S1-039 | Deterministic boundary: future exception handling is deferred | BLOCK | SCOPE_VIOLATION | AUTH. | OD-S1A-005 |
| GC-S1-040 | Dual integrity failure (authority + foreign task) | BLOCK | AUTHORITY_INVALID | AUTH. | OD-S1A-007 |
| GC-S1-041 | Requirement declarations are external to A2 (OD-S1A-008) | ELIGIBLE_TO_MERGE_UNDER_POLICY | — | AUTH. | OD-S1A-008 |

Each fixture case carries: `case_id`, `summary`, `identifier_universes` (disjoint
requirement-id and evidence-record-id universes, §6.2), `policy_input_bindings` (the
deterministic source digests of §5.2 **plus the single-sourced `evaluation_mode`**, in the
canonical `sha256:<hex>` representation), the `policy_input_facts` (§6, which no longer
contains `evaluation_mode`), `expected_disposition`,
`expected_decision_authority`, `expected_primary_reason`,
`expected_complete_reason_codes`, `expected_event_assertions`, `tags`,
and `owner_decisions_pending`. If the owner decides differently in §25, the fixture, this
table AND the independently pinned test tables are updated in the same owner-reviewed
change.

## 23. Proposed A2 Implementation Scope

Proposed (NOT executed in 1A/R1/R2; requires owner approval of this spec first):

- `agent_core/build_harness/merge_eligibility.py` (**A2**) — `MergeEligibilityPolicyInput`,
  `MergeEligibilityDecision`, `PolicyEvaluationRecord`, the reason-code table, and the
  pure `evaluate_merge_eligibility()` returning `(decision, record)` as data with the §7.1
  canonical digests and the §18.5 replay invariants. A2 consumes **validated facts +
  source bindings only** — no storage, filesystem, raw evidence, clock, or request
  metadata — and is therefore **not blocked** by OD-S1A-008.
- `agent_core/build_harness/eligibility_facts.py` (**A3**) — `EligibilityFacts`, the §5
  application fact DTOs, and the pure derivation `EligibilityFactDerivationInput →
  EligibilityFacts`, including the run-record-based requirement binding for rejected
  records. **A3 is BLOCKED UNTIL OD-S1A-008 IS ACCEPTED**, because it needs the declared
  `RequirementDeclarationSet` mapping (§25) rather than an inferred one.
- application layer (A3+) — `EvaluationTraceEnvelope` construction, trace persistence
  behind a port, and event emission against
  `data/schemas/changegate_evaluation_event_v1.schema.json`.
- `tests/build_harness/test_merge_eligibility_policy.py` — unit tests + golden-case
  runner over `data/evals/changegate_merge_eligibility_golden_cases.json`;
- a read-only CLI subcommand (`merge-eligibility`) consuming explicit JSON inputs,
  preserving the standalone path (ADR-002 §8);
- no adapters, no persistence, no event emission in A2.

## 24. Deferred Decisions

This spec cites and does **not** resolve (register:
`docs/architecture/GATE_1_DEFERRED_OWNER_DECISIONS.md`):

- **OD-G1-001** — TaskContract generalization: the derivation input references the
  existing software-delivery `TaskContract` by digest; no generalized or duplicate
  contract is introduced.
- **OD-G1-002** — TaskState generalization: eligibility is a separate decision object;
  execution status is not overloaded with authorization (matches ADR-003 §9 axes;
  `decision_authority` is a property of the decision, not a task state).
- **OD-G1-003** — Capability ownership: authority facts use opaque actor/role references
  and a validity status; no Capability model is created or claimed.
- **OD-G1-004** — Decision model disposition: `MergeEligibilityDecision` is a
  ChangeGate-local application decision, explicitly not the canonical cross-domain
  `DecisionRecord`; the six existing `*Decision` types are untouched.
- **OD-G1-005/006/007** — untouched (no package migration, no composition layer, no
  track allocation change).

## 25. Owner Decision Points

Each item below is **PENDING_OWNER_DECISION**. A recommended default with rationale is
given so review is concrete; the recommendation is not a resolution, and the golden
fixture marks every case whose expected result depends on one of these decisions
(`owner_decisions_pending`).

| ID | Question | Recommended default | Rationale | Golden cases |
| --- | --- | --- | --- | --- |
| OD-S1A-001 | Is missing approval BLOCK or REVIEW_REQUIRED? | BLOCK | ProcessGuard already hard-blocks push/deploy without approval; a wedge whose default leaks unapproved merges is unsellable. REVIEW_REQUIRED would be tolerable UX-wise but weakens the fail-closed story | GC-S1-013, GC-S1-021 |
| OD-S1A-002 | Is stale approval always BLOCK? | Always BLOCK | An approval for commit A must never carry to commit B; "mostly the same change" is exactly the judgment a re-approval exists to capture | GC-S1-014, GC-S1-023 |
| OD-S1A-003 | When is verifier-independence UNKNOWN reviewable (vs BLOCK)? | REVIEW_REQUIRED only when a verifier identity is present (`ATTESTED` or `PRESENT_UNATTESTED`); `ABSENT` identity is `REQUIRED_CONTEXT_INCOMPLETE` (BLOCK); `INVALID` identity is `AUTHORITY_INVALID` (BLOCK) | Keeps early deployments usable (independence attestation infra may lag) without ever reviewing an anonymous verifier; the `verifier_identity_status` fact carries exactly the information the final rule needs | GC-S1-017, GC-S1-036, GC-S1-037 |
| OD-S1A-004 | Do strict deployments require successful trace persistence before a decision may be released to consumers? | Yes in strict mode: the application layer must persist the trace and only then release the decision; the pure evaluator stays side-effect free | An unauditable authorization is a liability; keeping it in the application layer preserves evaluator purity | GC-S1-038 |
| OD-S1A-005 | Future approval, exception, and action-authorization governance | Pending outside Slice 1A; the separate authority artifact, issuer, scope, expiry, revocation, and consumption semantics are intentionally undecided | Implementing any authority behavior before its owner decision would silently resolve it | GC-S1-039 |
| OD-S1A-006 | Treatment of unexpected but valid evidence | Diagnostic only (`unexpected_evidence_ids`); never satisfies requirements, never blocks alone | Punishing extra proof discourages evidence; ignoring it silently hides drift — recording it is the middle path | GC-S1-030 |
| OD-S1A-007 | Exact precedence where two integrity failures coexist | The §9/§10 rank table as written (authority > context-incomplete > task > run > candidate > repository > provenance > duplicate) | Most-specific-foreign-identity-first gives the operator the most actionable primary reason; any total order is acceptable as long as it is fixed | GC-S1-021, GC-S1-040 |
| OD-S1A-008 | Stable Requirement Declaration Mapping (§25.1) | A ChangeGate-local `RequirementDeclarationSet` bound to the exact TaskContract digest; requirement ids are **declared**, never hashed/normalized/inferred from `TaskContract.required_evidence` display strings | Inferring an authority-bearing identity from a display string makes evidence completeness silently renameable; declaring it keeps the mapping reviewable and keeps `TaskContract` unmodified (OD-G1-001) | GC-S1-041 |

Nothing in this table is chosen merely to finish the document; every recommended default
is reversible before A2 begins.

### 25.1 OD-S1A-008 — Stable Requirement Declaration Mapping

```
OD-S1A-008 — Stable Requirement Declaration Mapping
Status: PENDING_OWNER_DECISION
```

**Decision question.** How does ChangeGate derive stable
`CommandRequirement.requirement_id` declarations from the governing `TaskContract`, whose
current `required_evidence` field contains display strings?

**Recommended draft:**

- do **not** hash, normalize or infer requirement ids from display strings;
- do **not** generalize or modify `TaskContract` in Slice 1 (OD-G1-001 stays deferred);
- define a ChangeGate-local **`RequirementDeclarationSet`**;
- bind the declaration set to the **exact TaskContract digest** (a different contract
  digest is a different declaration set — and `TASK_CONTEXT_STALE` if it no longer matches
  the candidate, §12);
- each declaration carries the stable `requirement_id` plus display/command metadata
  (argv, working directory, timeout — i.e. the existing `CommandRequirement` shape);
- **A3 requires this explicit declaration set** and may not synthesize it;
- **A2 remains independent**, because it consumes validated requirement *facts*
  (`required/satisfied/invalid/missing_requirement_ids`), never
  `TaskContract.required_evidence`.

**Owner must decide (the complete pending decision record — R3 makes this exhaustive so an
A3 implementer inherits no undefined boundary).** Status stays `PENDING_OWNER_DECISION`;
none of these is answered here:

1. the stable `requirement_id` **namespace**;
2. the **declaration-set schema version**;
3. the **mapping version**;
4. behavior for **unknown display strings** (no matching declaration);
5. behavior for **duplicate declarations**;
6. **aliases** (multiple display strings → one requirement id);
7. **deprecated aliases**;
8. **alias conflicts** (one display string claimed by two requirement ids);
9. **mapping migration / compatibility** across contract or declaration-set versions;
10. whether **unknown or deprecated values** BLOCK, REVIEW_REQUIRED, or require an explicit
    migration step.

**Required pre-1C-1 declaration fields** (each `RequirementDeclaration` must carry these
before A3 mapping is implemented):

```
requirement_id
display_label
source_contract_version
declaration_set_version
mapping_version
aliases
deprecated_aliases
unknown_value_policy
duplicate_policy
conflict_policy
```

The machine-readable form of this record is `od_s1a_008_decision_record` in the golden
fixture (owner questions + pre-1C-1 fields + block classification).

**Classification:**

```
Slice 1A owner review:   NOT BLOCKED
Slice 1B / A2:           NOT BLOCKED
Slice 1C-1 / A3:         BLOCKED UNTIL ACCEPTED
```

Golden case **GC-S1-041** demonstrates that the mapping is external to A2: the same
validated facts produce the same decision regardless of how the declarations were
produced, and the case asserts
`requirement_ids_derived_from_display_strings = false`.

## 26. Exit Criteria

Slice 1A (as revised by R1–R5) exits when:

1. the artifact tests pass (spec present and DRAFT_FOR_OWNER_REVIEW; schema
   meta-validated with per-event positive and negative instances and a full valid causal
   chain; canonical `canonical_digest()` output accepted by every digest field; fixture
   valid with full reason-code coverage, disjoint accounting, disjoint identifier
   universes, total fact-state mapping, independently pinned precedence, independent
   oracle agreement, mutation-negative detection, and the ten replay invariants);
2. the full existing suite, architecture tests, and conversation eval remain green with
   zero production files changed;
3. fresh Codex Sol High independent re-verification completes;
4. TranBac either accepts this spec (flipping Status in a separate owner-reviewed change)
   or returns decisions for OD-S1A-001 … OD-S1A-008;
5. only then may Slice 1-A2 (pure evaluator implementation) be scheduled. Slice 1-A3
   additionally requires OD-S1A-008 to be accepted.

The forbidden output terms remain forbidden after acceptance: `SAFE_TO_MERGE` and
`VERIFIED_AND_MERGE` must never appear as output values of any ChangeGate component.

## 27. Acceptance Governance

This section is normative. It draws the line between an **owner-acceptance metadata patch**
(mergeable after a no-semantic-change verification) and a **semantic change** (which
invalidates the current independent verification and requires a fresh implementation +
adversarial reverification cycle). The machine-readable form is `acceptance_governance` in
the golden fixture.

### 27.1 Metadata-only acceptance patch

A metadata-only acceptance patch may change **only**:

- owner-decision status;
- the acceptance record;
- the accepted candidate SHA;
- artifact digests;
- verification-report references;
- the deferred-decision register;
- audit metadata;
- document status (e.g. `DRAFT_FOR_OWNER_REVIEW` → `ACCEPTED_BY_OWNER`).

It **must not** change:

- disposition semantics;
- the reason-code taxonomy;
- reason precedence;
- golden expected results;
- replay / source-binding rules;
- the policy-record payload;
- event-schema behavior;
- oracle or validation logic;
- production code.

Rule:

```
metadata-only acceptance patch
→ no-semantic-change verification (the semantic fingerprint, §27.3, is preserved)
→ merge allowed after PASS
```

### 27.2 Semantic change

```
owner decision changes any contract or behavior
→ current verifier result invalidated
→ new implementation candidate required
→ fresh independent adversarial verification required
```

A precedence change is the canonical example: it is a **semantic patch, not an acceptance
metadata patch** (correcting the earlier §10 wording). Changing any of the forbidden set
above follows the same rule.

### 27.3 Semantic manifest and complete fingerprint

The load-bearing semantics are consolidated into ONE machine-readable block,
`slice_1a_semantic_manifest` (fixture-level), and:

```
semantic_fingerprint = canonical_digest(slice_1a_semantic_manifest)
```

The manifest binds **every** area forbidden from changing in a metadata-only acceptance
patch (R3's fingerprint was incomplete — R4 makes it total):

- **Policy semantics** — reason-code taxonomy, exact precedence ranks, default
  dispositions, fact-state mappings, violation-tag mappings, decision-authority-by-mode,
  identifier-namespace rules, canonical digest representation.
- **Deterministic identity** — the exact source-binding field set, the complete
  `MergeEligibilityPolicyInput` deterministic field set, the portable typed
  `PolicyEvaluationRecordPayload` field set (documentation order is non-semantic), schema
  and canonicalization version/digest bindings, the contract identifiers, approval
  sentinel, and set-normalization rule.
- **Replay** — replay contract version, complete replay-invariant ids, the fields included
  in decision identity, the fields excluded as runtime metadata, the trace equality
  invariants.
- **Event semantics** — the canonical digest of the complete event JSON Schema, the event
  type set, the `decision_ref` required-field set, and the causal-reference requirements.
- **Causal semantics** — causal contract version, the **six-field immutable** lineage set
  (including `evaluation_id`), root creation, changed-candidate-new-root, multi-root and
  cycle rules, and the complete set of **named semantic controls** (see below).
- **Golden semantics** — per case: expected disposition, decision authority, primary
  reason, complete reasons, blocking/review partitions, and owner-decision markers.

**Named semantic controls (R7).** The prior opaque
control-id lists are replaced by `causal_semantics.semantic_controls`, a list where each
control is a machine-readable definition:

```
{ id, subject, required_fields, predicate, failure_code }
```

covering portable typed records, normalization, decision self-derivation, record-schema
digest derivation, total fail-closed validation, record/input binding consistency, the
`SEMANTIC_REPLAY_NOT_PERFORMED` boundary (§7.3), evaluator-only semantic production,
writer non-mutation, absence of active override/exception classifications, the explicit
event identity equality matrix (task, candidate, input-digest reference), immutable
lineage, changed-candidate-new-root, every-predecessor-same-lineage,
duplicate-evaluation-ID rejection, downstream-evaluation-drift rejection, multi-root, and
cycle rejection. The manifest additionally embeds the machine-readable
`contract_to_test_coverage` matrix binding every retained invariant to its independent
test oracles and every Model-B-removed surface to a reintroduction attack, and the
`runtime_authority_boundary` block (§7.5) binding the three-layer authority separation,
the portable RFC 8259 input domain, the current Python implementation profile, the
representation-guard permission, the expected-invalid-versus-internal-fault distinction,
the diagnostic scope, and the abstract audit-history and boundary re-review rules. The
artifact tests assert every named predicate has an executable check and that removing or
changing any predicate changes the fingerprint.

The manifest **excludes** all metadata (document status, acceptance record,
verification-report path, accepted candidate SHA, audit notes) — including the concrete
candidate audit history and detailed reopen-trigger examples recorded in the
`acceptance_governance` container (§7.5) — so an allowed metadata
change preserves the fingerprint.

The artifact tests cross-bind the manifest to the executable artifacts — the schema digest,
the record-payload field order, the `decision_ref` required set, the six-field lineage, and
the named semantic controls — so a semantic change to any of them forces a manifest change,
which changes the fingerprint. Fourteen independent manifest-area mutation tests plus the
per-predicate removal test prove the fingerprint changes for precedence, default
dispositions, golden outcomes, the source-binding set, the `MergeEligibilityPolicyInput`
field set, the `PolicyEvaluationRecordPayload` field set, replay invariants, event-schema
behavior, the `decision_ref` required fields, the lineage field set, the immutable-lineage
rule, the multi-root rule, the decision-authority mapping, the canonical digest
representation, and every named semantic control. Each mutation test is independent
of any expected-fingerprint value stored in the same mutated object.

### 27.4 Exact-artifact no-semantic-change controls

Because the record-payload builder and the causal validator live in the test file and the
event contract lives in the schema file, final **no-semantic-change verification
additionally compares the verified-candidate hashes** of:

- `data/schemas/changegate_evaluation_event_v1.schema.json`;
- `tests/build_harness/test_changegate_slice_1_spec_artifacts.py`.

The fresh independent verifier records these two file hashes at the accepted candidate. A
metadata-only acceptance patch must preserve them **exactly** (and preserve the semantic
fingerprint for the spec and fixture). This document defines the **comparison contract**
only; it does not hard-code any future verifier hash. The machine form is
`acceptance_governance.exact_artifact_hash_contract` in the fixture.

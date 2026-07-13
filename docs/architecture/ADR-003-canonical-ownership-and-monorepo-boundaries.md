# ADR-003: Canonical Model Ownership and Incremental Monorepo Boundaries

Title: Canonical Model Ownership and Incremental Monorepo Boundaries
Status: ACCEPTED_BY_OWNER
Owner: TranBac
Technical Review: PASS
Owner Acceptance: ACCEPTED
Accepted Candidate: 7bd3d7e86dc23af544325d228723c067f9f34200
Owner Decision: ACCEPT_ALL_THREE_ADRS_WITH_DEFERRED_OWNER_DECISIONS
Acceptance Date: 2026-07-13
Date: 2026-07-13
Supersedes: None

> This ADR passed technical review and was accepted by the human owner, TranBac.
> No model is an acceptance authority.

---

## 1. Context

ADR-001 splits platform from wedge; ADR-002 fixes dependency direction. Neither answers: **who
owns each contract, and what do we do with the contracts that already exist in the wrong
place?**

Repository inventory (2026-07-13) found that `TaskContract`, `TaskState` and `CandidateBinding`
already exist **inside** the ChangeGate-oriented boundary, and `Capability` exists inside the
conversation package. Most target governance concepts do not exist at all. Pretending otherwise
— writing the target architecture as if it were current code — would be the most damaging thing
this ADR could do.

## 2. Decision

1. TOMTIT remains a **modular monolith**. No repository split, no big-bang migration.
2. Every canonical concept gets an **explicit inventory status**. Future concepts are labeled
   as future, not described as existing.
3. Where an existing type is not general enough to be canonical, it **stays where it is**, and
   a later canonical-model specification decides migration/adaptation/supersession. **No
   duplicate canonical replacement is introduced.**
4. Gate 1 performs **zero** production package migration and creates **zero** production
   packages.

## 3. Current Architecture Inventory

Existing `agent_core` packages (2026-07-13): `build_harness`, `confirmation`, `conversation`,
`eval`, `memory`, `output`, `planning`, `runtime`, `safety`, `session_persistence`, `skills`,
`state`, `tools`, `web_api`.

Not found: `kernel`, `changegate`, `project_control`, `coordinator`, `adapters`, `workflows`,
`software_delivery_workflow`.

`agent_core.build_harness` is **self-contained**: it imports no other `agent_core` package.
No vendor SDK (`anthropic`, `openai`, `github`, `gitlab`, `boto3`) is imported anywhere in
`agent_core`, nor declared in `pyproject.toml`.

## 4. Inventory Status Definitions

| Status | Meaning |
| --- | --- |
| `EXISTS` | The symbol exists and is already in (or acceptable for) its canonical home |
| `NOT_FOUND` | No such symbol in the repository |
| `DOMAIN_SPECIFIC_EXISTING` | Exists, but scoped to one domain; may or may not generalize |
| `FUTURE_CONCEPT_NOT_IMPLEMENTED` | Target concept; no code today; design only |
| `OWNERSHIP_UNRESOLVED` | Exists (or is needed) but canonical owner is genuinely undecided |

## 5. Canonical Contract Ownership

| Concept | Inventory status | Current symbol/module | Canonical owner | Cross-domain or domain-specific | Current action | Future migration / decision note |
| --- | --- | --- | --- | --- | --- | --- |
| ActorIdentity | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | cross-domain | future design only | outside Gate 1 |
| Capability | DOMAIN_SPECIFIC_EXISTING | `agent_core/conversation/capabilities.py::Capability` (StrEnum) | OWNERSHIP_UNRESOLVED | conversation-scoped today | keep in place now | not asserted to be the governance Capability; canonical-model spec decides |
| SubjectRef | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | cross-domain | future design only | outside Gate 1 |
| TaskContract | DOMAIN_SPECIFIC_EXISTING | `agent_core/build_harness/contracts.py::TaskContract` | OWNERSHIP_UNRESOLVED | software-delivery-shaped today | keep in place now | canonical-model spec decides generalize / adapt / supersede |
| TaskState | DOMAIN_SPECIFIC_EXISTING | `agent_core/build_harness/state.py::TaskState` (StrEnum) | OWNERSHIP_UNRESOLVED | software-delivery-shaped today | keep in place now | canonical-model spec decides |
| AgentState | DOMAIN_SPECIFIC_EXISTING | `agent_core/state/agent_state.py::AgentState` | Runtime (existing) | runtime state of one task/session | keep in place now | **not** durable memory, **not** an AgentRunRecord |
| Decision | DOMAIN_SPECIFIC_EXISTING | `agent_core/build_harness/change_gate.py::ChangeGateDecision`, `agent_core/build_harness/process_guard.py::ProcessGuardDecision`, `agent_core/safety/policy.py::PolicyDecision`, `agent_core/safety/approval.py::ApprovalDecision`, `agent_core/safety/capability_gate.py::SafetyDecision`, `agent_core/confirmation/models.py::ConfirmedDecision` | OWNERSHIP_UNRESOLVED | ChangeGate-oriented (`ChangeGateDecision`, `ProcessGuardDecision`), safety (`PolicyDecision`, `ApprovalDecision`, `SafetyDecision`), and confirmation (`ConfirmedDecision`) | keep all six in their current domains now | none is the canonical cross-domain governance `DecisionRecord`; canonical generalization, adaptation, or supersession remains unresolved |
| DecisionRecord | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | cross-domain | future design only | outside Gate 1 |
| Approval | DOMAIN_SPECIFIC_EXISTING | `agent_core/safety/approval.py` (`ApprovalDecision`, `ApprovalGate`) | OWNERSHIP_UNRESOLVED | runtime tool-gating | keep in place now | not a durable ApprovalRecord |
| ApprovalRecord | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | cross-domain | future design only | outside Gate 1 |
| Evidence | DOMAIN_SPECIFIC_EXISTING | `agent_core/build_harness/provenance.py` (`EvidenceProvenance`, `CollectedCommandEvidence`, `VerifiedCommandEvidence`), `agent_core/safety/evidence.py::EvidenceEnvelope` | ChangeGate (build_harness) / Safety | software-delivery-specific | keep in place now | command evidence stays ChangeGate-owned |
| EvidenceRef | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | cross-domain | future design only | outside Gate 1 |
| AuditEvent | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | cross-domain | future design only | outside Gate 1 |
| AuthorizedTransition | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | cross-domain | future design only | `build_harness/state.py` has a domain transition guard, not a canonical contract |
| ProjectRecord | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Project Control | application aggregate | future design only | outside Gate 1 |
| MissionRecord | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Project Control | application aggregate | future design only | outside Gate 1 |
| TaskExecutionRecord | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Project Control | application aggregate | future design only | outside Gate 1 |
| AgentRunRecord | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Project Control | application aggregate | future design only | see §9 three run-state axes |
| CandidateBinding | EXISTS | `agent_core/build_harness/repository_models.py::CandidateBinding` | **ChangeGate** | software-delivery-specific | keep in place now | remains ChangeGate-owned; never embedded in generic records |

Inventory status counts derived from these 19 concept rows:

- `EXISTS`: 1
- `DOMAIN_SPECIFIC_EXISTING`: 7
- `FUTURE_CONCEPT_NOT_IMPLEMENTED`: 11

Canonical ownership is a separate dimension: 5 concept rows currently identify
`OWNERSHIP_UNRESOLVED` (`Capability`, `TaskContract`, `TaskState`, `Decision`, and `Approval`).
These counts do not settle any owner decision.

### Ownership rules

- Cross-domain contracts belong to **TOMTIT kernel/core**.
- Software-delivery candidate identity belongs to **ChangeGate**.
- Project execution aggregates and application services belong to **Project Control**.
- Coordinator owns **domain-neutral orchestration and supervision** behavior.

**No contradictory dual ownership.** Where kernel/core and Project Control could both plausibly
own an equivalent `DecisionRecord`, `ApprovalRecord` or `AuditEvent`: the canonical record is
**kernel-owned**, and Project Control **consumes** it. Project Control must not create
near-duplicate authority records for convenience.

Where an existing type is **not general enough** to become canonical (`TaskContract`,
`TaskState`, `Capability`, the six semantic `*Decision` types):

- it **remains in its current module**;
- **no duplicate canonical replacement is introduced in Gate 1**;
- a later **canonical-model specification** must decide migration, adaptation or supersession.

## 6. ChangeGate Ownership

ChangeGate (currently `agent_core.build_harness`) owns: repository identity, Git object format,
base/head/tree identity, changed files, command evidence, candidate freshness, scope checking,
stale approvals, verifier independence, required-evidence completeness, and merge eligibility
under policy. `CandidateBinding` is ChangeGate-owned and stays so.

## 7. Coordinator Ownership

Coordinator owns domain-neutral orchestration and supervision. It owns **no** Git, repository,
commit, tree, merge or ChangeGate contract (ADR-002 §4).

## 8. SubjectRef

A domain-neutral future reference (**not implemented in Gate 1**; inventory status
`FUTURE_CONCEPT_NOT_IMPLEMENTED`, no existing equivalent found):

```python
@dataclass(frozen=True)
class SubjectRef:
    namespace: str
    kind: str
    value: str
    digest: str | None
```

Examples:

```python
namespace = "changegate"; kind = "git_candidate";   value = "<candidate-id>"
namespace = "document";   kind = "draft_version";   value = "<document-version>"
```

Project Control and Coordinator **must use `SubjectRef`** (or an equivalent neutral
abstraction). They **must not** embed repository SHA, commit, tree, or Git-specific candidate
semantics directly inside a generic `AgentRunRecord`. `CandidateBinding` remains
ChangeGate-owned.

## 9. Agent Run State Axes

A future `AgentRunRecord` **must not overload one status field** with process outcome, context
validity and result authorization. Three **independent axes** (not implemented in Gate 1):

```
execution_status:   PENDING | RUNNING | COMPLETED | FAILED | CANCELLED | NEEDS_RECONCILIATION
context_validity:   CURRENT | STALE | UNKNOWN
result_eligibility: ELIGIBLE | REVIEW_REQUIRED | INELIGIBLE
```

The combination that a single field cannot express:

```
execution_status  = COMPLETED
context_validity  = STALE
result_eligibility = INELIGIBLE
```

The run finished perfectly; its context went stale; its result is therefore not usable. This is
the run-level analogue of ADR-001 §7 (structural success ≠ authorization).

## 10. Effective Decision Context

A future `ContextPack` **must not** use a digest of *every* approved project decision. It must
select **effective decisions** relevant to: project, task, role, domain, subject, and paths or
capabilities where applicable. The digest must cover **only the exact decision set included in
that ContextPack**.

Future persisted metadata should include: `decision_ids`, `decision_versions`,
`effective_decision_set_digest`, `context_schema_version`, `context_builder_version`,
`task_contract_version`, `SubjectRef`, and agent role.

**An unrelated approved decision must not automatically invalidate every running task.** That
is the failure mode a global decision digest guarantees.

Decision Store and ContextPack are **not implemented in Gate 1**.

## 11. Controlled Improvement Record Reuse

Future episode, evaluation, diagnosis, experiment, promotion and rollback records for controlled
self-improvement **must reuse the same canonical** identity, `SubjectRef`, evidence, decision,
approval, authorized-transition, audit and policy-version contracts.

**TOMTIT must not create a parallel unrestricted self-improvement runtime with separate
authority or audit semantics.** Implementation is outside Gate 1. (See ADR-001 §9 protected
roots of trust.)

## 12. SQLite Persistence Constraints

Future constraints for the Project Control track (**not implemented in Gate 1**):

- `PRAGMA foreign_keys = ON`;
- `PRAGMA journal_mode = WAL`;
- configured `busy_timeout`;
- schema-version or migration table;
- unique identifiers;
- unique idempotency keys where applicable;
- append-only audit events;
- a transaction around state transition **and** audit append;
- compare-and-set transitions;
- deterministic serialization for digests;
- repository methods must not bypass `DecisionService` invariants.

Prefer **narrow** persistence methods:

```
insert_proposed_decision()
compare_and_set_decision_status()
append_agent_run_result()
compare_and_set_task_state()
```

Avoid **broad unrestricted** mutation methods:

```
save_decision()
complete_agent_run()
```

unless equivalent invariants are enforced by contract. A broad `save_decision()` lets any caller
write any status, which silently deletes the state machine.

## 13. Incremental Package Evolution

- TOMTIT remains a **modular monolith**.
- **Do not split repositories.**
- **Do not move current modules merely to make the directory tree look cleaner.**
- New modules must follow the accepted dependency directions (ADR-002).
- Existing modules may migrate **incrementally**, under separately reviewed changes.
- **Gate 1 performs no production package migration.**

Possible future namespaces (**target boundaries, not mandatory Gate 1 filesystem changes**):

```
agent_core.kernel
agent_core.changegate
agent_core.project_control
agent_core.coordinator
agent_core.workflows.software_delivery
agent_core.adapters
```

**Do not create empty production packages to satisfy a diagram.** Gate 1 creates none.

## 14. Forbidden Duplication

- No duplicate canonical contract may be introduced while an equivalent type exists.
- Project Control must not mint near-duplicate authority records (`DecisionRecord`,
  `ApprovalRecord`, `AuditEvent`) that shadow kernel contracts.
- No second `CandidateBinding`-like type outside ChangeGate.
- No parallel self-improvement authority/audit model.

## 15. Gate 2 Entry Criteria

The later Project Control track may start **only after**:

- these ADRs are technically reviewed;
- the owner explicitly accepts or revises them;
- architecture boundary tests pass;
- canonical ownership conflicts are documented (they are: `TaskContract`, `TaskState`,
  `Capability`, the six semantic `*Decision` types);
- direct-import boundary status is explicit (active vs. reserved);
- no production behavior was changed in Gate 1.

Gate 3 (single-agent supervised execution) remains **HOLD** until Project Control exit criteria
are met.

## 16. Consequences

- A canonical-model specification is now a prerequisite for kernel extraction.
- The repository is honest about the 19-row concept inventory: 1 row is `EXISTS`, 7 are
  `DOMAIN_SPECIFIC_EXISTING`, and 11 are `FUTURE_CONCEPT_NOT_IMPLEMENTED`. Inventory state is
  not conflated with the separate unresolved-ownership dimension.
- No churn, no empty packages, no duplicate models, zero production risk in Gate 1.

## 17. Rejected Alternatives

- **Extract the kernel now and move `TaskContract`/`TaskState` into it.** Rejected: both are
  software-delivery-shaped; promoting them unexamined would enshrine Git semantics as the
  platform vocabulary — the exact failure ADR-001 prevents.
- **Create the six target packages as empty stubs.** Rejected: architecture theater; makes
  reserved rules look exercised when they are not.
- **Let Project Control define its own DecisionRecord.** Rejected: produces two authority models
  and an unauditable system.
- **One `status` field on `AgentRunRecord`.** Rejected: cannot express COMPLETED + STALE +
  INELIGIBLE (§9).
- **Global decision digest in ContextPack.** Rejected: any unrelated approved decision would
  invalidate every running task (§10).

## 18. Deferred Owner Decisions

This ADR is accepted. The unresolved decisions are maintained in
`docs/architecture/GATE_1_DEFERRED_OWNER_DECISIONS.md`.

Acceptance does not authorize coding agents to choose those deferred semantics. Only an
implementation that directly depends on a deferred decision is blocked by it.

## 19. Owner Decision

**Status: ACCEPTED_BY_OWNER. Technical Review: PASS. Owner Acceptance: ACCEPTED.**

TranBac accepted this ADR through owner decision
`ACCEPT_ALL_THREE_ADRS_WITH_DEFERRED_OWNER_DECISIONS` for accepted candidate
`7bd3d7e86dc23af544325d228723c067f9f34200`. The seven registered owner decisions remain
deferred and may be resolved only through a new owner-reviewed decision or ADR amendment.

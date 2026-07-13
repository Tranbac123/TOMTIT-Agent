# ADR-001: TOMTIT Core Platform and ChangeGate Commercial Wedge

Title: TOMTIT Core Platform and ChangeGate Commercial Wedge
Status: DRAFT
Owner: TranBac
Technical Review: PENDING
Owner Acceptance: PENDING
Date: 2026-07-13
Supersedes: None

> This ADR is a DRAFT authored by the implementer (Claude Code). It is **not** accepted.
> Only the human owner (TranBac) may move it to `ACCEPTED_BY_OWNER`.
> Lifecycle: `DRAFT → TECHNICALLY_REVIEWED → ACCEPTED_BY_OWNER → SUPERSEDED`.

---

## 1. Context

P0-9B1 landed an evidence-gated software-delivery core (`agent_core.build_harness`) with
immutable domain schemas, canonical digests, an exclusive rejected-context status matrix, and
run-record evidence membership. The full suite is green (2434 passed) and the merge is
verified.

That work exposed a strategy question the code cannot answer by itself: **what is TOMTIT, and
what is the first thing we sell?** Without an explicit answer, the natural gravity of the
repository is to let the software-delivery domain silently become the platform — Git, commits,
trees and merge semantics leaking into every generic contract. That is the failure mode this
ADR exists to prevent.

Two P0-9B1 follow-ups must also be given a permanent home rather than living in a report:

- **FOLLOWUP-P0-9B1-001** — empty explicit-context bundle workflow policy.
- **FOLLOWUP-P0-9B1-002** — structural `VERIFIED` is not merge eligibility.

## 2. Decision

1. **TOMTIT is a governed, state-first, vendor-neutral runtime for autonomous agents.** The
   long-term platform is domain-neutral.
2. **TOMTIT ChangeGate is the first commercial wedge** — a software-change authorization
   product built *on* the platform, not *as* the platform.
3. Cross-domain governance contracts belong to a domain-neutral **TOMTIT Core / kernel**.
   Software-delivery-specific contracts belong to **ChangeGate**.
4. Structural evidence verification is **not** authorization to merge.
5. A schema-valid empty evidence bundle is **not** evidence completeness.
6. Controlled self-improvement is a protected long-term capability, governed by the same
   evidence/decision/approval/audit model as every other change.
7. After technical review and owner acceptance, work splits into two **independent** tracks
   (Track A ChangeGate Vertical MVP, Track B Project Control Bootstrap).

Gate 1 implements **none** of the above as production code. It records the decision and adds
executable architecture guards.

## 3. Product Positioning

TOMTIT is a governed, state-first, vendor-neutral runtime for autonomous agents.

TOMTIT is **not merely**:

- a coding-agent wrapper;
- a GitHub application;
- a prompt framework;
- an LLM routing layer;
- a ChangeGate-only product.

ChangeGate is the **first commercial wedge**: the narrowest valuable slice that a buyer will
pay for, and the proving ground for the platform's governance primitives.

## 4. TOMTIT Core Responsibilities

The domain-neutral TOMTIT Core (future `agent_core.kernel`, name not binding) owns
**cross-domain governance contracts and semantics** — the vocabulary every domain shares.

Target cross-domain concepts: `ActorIdentity`, `Capability`, `SubjectRef`, `TaskContract`,
`TaskState` / `AuthorizedTransition`, `DecisionRecord`, `ApprovalRecord`, `EvidenceRef`,
`AuditEvent`, and policy/authority contracts.

### Canonical ownership table (from actual repository inventory, 2026-07-13)

Inventory statuses: `EXISTS`, `NOT_FOUND`, `DOMAIN_SPECIFIC_EXISTING`,
`FUTURE_CONCEPT_NOT_IMPLEMENTED`, `OWNERSHIP_UNRESOLVED`.

| Concept | Inventory status | Current module | Intended canonical owner | Current action |
| --- | --- | --- | --- | --- |
| ActorIdentity | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | future design only |
| Capability | DOMAIN_SPECIFIC_EXISTING | `agent_core/conversation/capabilities.py` (`Capability` StrEnum) | OWNERSHIP_UNRESOLVED | keep in place now |
| SubjectRef | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | future design only |
| TaskContract | DOMAIN_SPECIFIC_EXISTING | `agent_core/build_harness/contracts.py` | OWNERSHIP_UNRESOLVED | keep in place now |
| TaskState | DOMAIN_SPECIFIC_EXISTING | `agent_core/build_harness/state.py` (StrEnum) | OWNERSHIP_UNRESOLVED | keep in place now |
| AuthorizedTransition | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | future design only |
| DecisionRecord | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | future design only |
| ApprovalRecord | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | future design only |
| EvidenceRef | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | future design only |
| AuditEvent | FUTURE_CONCEPT_NOT_IMPLEMENTED | NOT_FOUND | Kernel/Core | future design only |
| CandidateBinding | EXISTS | `agent_core/build_harness/repository_models.py` | **ChangeGate** | keep in place now |

`TaskContract` and `TaskState` exist today **inside the ChangeGate-oriented boundary** and are
software-delivery-shaped. Whether either can be generalized into a canonical cross-domain
contract, or must be adapted/superseded by a new kernel contract, is **OWNERSHIP_UNRESOLVED**
and is deferred to a later canonical-model specification. Gate 1 introduces **no duplicate
canonical replacement** and performs **no migration**.

`Capability` exists in the conversation package as a conversation-scoped StrEnum. It is *not*
asserted to be the cross-domain governance `Capability`; ownership is unresolved.

## 5. ChangeGate Responsibilities

ChangeGate owns **software-delivery-specific** concepts:

- repository identity;
- Git object format;
- base / head / tree identity;
- changed files;
- command evidence;
- candidate freshness;
- scope checking;
- stale approvals;
- verifier independence;
- required evidence completeness;
- merge eligibility under policy.

`agent_core.build_harness` is the **current ChangeGate-oriented implementation boundary**.
Repository inventory found no clearer current owner. It is **not moved or renamed** in Gate 1.

ChangeGate authorizes a software change only when **all** of the following hold:

- the approved TaskContract is current;
- candidate identity is current and coherent;
- scope is valid;
- required evidence is complete;
- evidence belongs to the correct task, run and candidate;
- verifier identity and independence are valid;
- repository state is release-clean;
- approvals are fresh;
- policy version is current;
- caller authority is valid.

The authorization output term is:

```
ELIGIBLE_TO_MERGE_UNDER_POLICY
```

The term `SAFE_TO_MERGE` is **forbidden**: it over-claims a safety property the system does not
and cannot establish.

## 6. Explicit Non-Responsibilities

TOMTIT Core does **not** own repository, commit, tree, or merge semantics.
ChangeGate does **not** own generic orchestration, supervision, or project execution.
Neither owns vendor SDK integration; that belongs to adapters.
Gate 1 owns **no** production behavior at all.

## 7. Verified Evidence Versus Authorized Change

**This section incorporates FOLLOWUP-P0-9B1-002.**

```
EvidenceVerificationResult.accepted == True
VerificationStatus.VERIFIED
```

mean exactly one thing: **structural evidence and provenance verification succeeded**. The
evidence is well-formed, internally coherent, and bound to the claimed task/run/candidate.

They do **not** mean:

```
ELIGIBLE_TO_MERGE_UNDER_POLICY
```

Structural `VERIFIED` says nothing about release cleanliness, approval freshness, policy
version currency, scope validity, verifier independence, or caller authority. **No future
implementation may map structural `VERIFIED` directly to merge eligibility.** Merge eligibility
is a separate policy decision that consumes verified evidence as one of several inputs.

## 8. Empty Evidence Bundle Policy

**This section incorporates FOLLOWUP-P0-9B1-001.**

A **schema-valid empty verification bundle** does **not** mean **required evidence satisfied**.
P0-9B1 permits an empty bundle because emptiness alone produced no contradictory state; that is
a *schema* property, not a *policy* property.

When a TaskContract or ChangeGate policy requires evidence, the policy layer must enforce:

```
required evidence  ⊆  verified evidence present in the bundle
```

Missing mandatory evidence must **block** with a policy decision such as:

```
REQUIRED_EVIDENCE_MISSING
```

The P0-9B1 schema is **not altered** by this ADR. This is a policy-layer obligation for the
ChangeGate Vertical MVP track.

## 9. Controlled Self-Improvement Direction

Controlled self-improvement is a **protected long-term TOMTIT capability**. It is **not part of
Gate 1 implementation**.

Intended loop:

```
observe → evaluate → diagnose → propose → sandbox experiment
       → independent verification → gated promotion → monitor or rollback
```

**Self-improvement does not mean unrestricted self-modification.**

The following remain **protected roots of trust** and cannot be modified, replaced, bypassed,
or promoted autonomously without explicit valid authority:

- canonical state stores;
- canonical audit stores;
- ChangeGate authority rules;
- ProcessGuard authority rules;
- evaluation policy;
- promotion policy;
- approval policy;
- rollback mechanisms;
- protected evaluation datasets;
- verifier-independence rules.

Future self-improvement changes must use the **same** evidence, decision, approval,
authorized-transition and audit model as any other governed change. **No separate unrestricted
authority path for self-improvement may be created.**

## 10. Product Development Tracks

After (a) Sol High technical review **and** (b) explicit owner acceptance, the roadmap splits
into two **independent** tracks:

**Track A — ChangeGate Vertical MVP** — market and commercial wedge validation.
Recommended priority: **60–70%**.

**Track B — Project Control Bootstrap** — internal dogfood and future Coordinator foundation.
Recommended priority: **30–40%**.

Rules:

- ChangeGate **must not wait** for all Project Control or Coordinator work to finish.
- ChangeGate **must retain a standalone CLI/API path**.
- Coordinator **must not be on ChangeGate's critical path**.
- Neither track begins automatically in this task.

## 11. Consequences

- The platform vocabulary is protected from Git-shaped leakage.
- ChangeGate can be sold and shipped without a Coordinator.
- Two follow-ups are now durable architectural obligations, not report footnotes.
- A canonical-model specification is now *required* before kernel extraction, because
  `TaskContract`, `TaskState` and `Capability` ownership is explicitly unresolved.
- Gate 1 costs zero production risk: 0 production files changed.

## 12. Rejected Alternatives

- **Ship ChangeGate as the whole product.** Rejected: forecloses the platform and hard-codes
  Git semantics into every future domain.
- **Build the domain-neutral kernel first, sell later.** Rejected: no revenue, no real
  requirements pressure, high risk of designing the wrong abstractions.
- **Let Coordinator orchestrate ChangeGate directly.** Rejected: inverts the dependency and
  makes the wedge un-shippable standalone (see ADR-002).
- **Treat `VERIFIED` as merge-eligible.** Rejected: conflates structural integrity with policy
  authorization; this is precisely FOLLOWUP-P0-9B1-002.
- **Migrate packages now to match the target diagram.** Rejected: big-bang churn with no
  behavioral benefit (see ADR-003).

## 13. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| ChangeGate semantics leak into the kernel | Executable direct-import boundary tests (Gate 1B) + ADR-002 dependency rules |
| Duplicate canonical models (kernel vs. Project Control) | ADR-003 forbids duplication; ownership conflicts recorded as OWNERSHIP_UNRESOLVED |
| `VERIFIED` silently used as merge authorization | §7 is normative; the policy layer must add an explicit eligibility decision |
| Empty bundle accepted as "all evidence present" | §8 requires `required ⊆ verified` at the policy layer |
| Self-improvement becomes an authority bypass | §9 protected roots of trust; same governance model as any change |
| Architecture tests give false confidence | ADR-002 §Known Test Limitations: direct static imports only |

## 14. Exit and Review Criteria

This ADR is exited when:

- Sol High technical review is complete;
- the owner explicitly accepts or revises it;
- architecture boundary tests pass;
- canonical ownership conflicts are documented (they are: `TaskContract`, `TaskState`,
  `Capability`).

## 15. Owner Decision

**Status: DRAFT. Technical Review: PENDING. Owner Acceptance: PENDING.**

The implementer (Claude Code) does **not** have authority to accept this ADR. Awaiting Sol High
technical review and explicit acceptance by TranBac.

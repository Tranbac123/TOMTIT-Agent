# Gate 1 Deferred Owner Decisions

Title: Gate 1 Deferred Owner Decisions
Status: ACTIVE
Owner: TranBac
Source ADRs:

- ADR-001
- ADR-002
- ADR-003

Accepted Gate 1 Candidate: 7bd3d7e86dc23af544325d228723c067f9f34200

Deferred does not mean forgotten. Coding agents may not silently resolve deferred decisions.
Each affected implementation must cite the relevant decision ID. An implementation blocked by
a deferred decision must return a specific blocked verdict identifying that decision. Decisions
may be resolved only through a new owner-reviewed decision or ADR amendment.

## OD-G1-001 — TaskContract Generalization

Status: DEFERRED

Decision needed:
How the current TaskContract should become or map to a domain-neutral canonical contract.

Implementation gate:
No new duplicate canonical TaskContract may be introduced. Existing contracts may remain in
place. Any generalization or migration requires a separate reviewed model-spec decision.

Affected work:
Project Control canonical-model freeze and future kernel migration.

Does not block:
ChangeGate vertical MVP using the currently approved software-delivery contract.

Resolution trigger:
Before a second non-software domain requires the same TaskContract semantics, or before a
kernel-level TaskContract replacement is implemented.

## OD-G1-002 — TaskState Generalization

Status: DEFERRED

Decision needed:
How software-task state, agent runtime state, and domain-neutral authorized transitions relate.

Implementation gate:
Do not create a second competing canonical TaskState. Do not overload execution status with
context validity or authorization eligibility.

Affected work:
Project Control state-model freeze and future cross-domain runtime state.

Does not block:
Software-delivery-specific ChangeGate states or minimal Project Control persistence using
explicitly scoped records.

Resolution trigger:
Before introducing a cross-domain TaskState or AuthorizedTransition implementation.

## OD-G1-003 — Capability Canonical Ownership

Status: DEFERRED

Decision needed:
Which current or future module owns the canonical Capability contract.

Implementation gate:
No product package may create an incompatible Capability model. Adapters and products must not
embed vendor-specific permission semantics into the future canonical contract.

Affected work:
Kernel capability model and authorization integration.

Resolution trigger:
Before Capability is required by both ChangeGate and Coordinator/Project Control.

## OD-G1-004 — Existing Decision Model Disposition

Status: DEFERRED

Decision needed:
How the six existing Decision-related models are classified, reused, migrated, or superseded.

Implementation gate:
Project Control must not introduce a near-duplicate canonical DecisionRecord without a separate
reviewed model inventory and ownership decision.

Affected work:
Project Control Decision Service model freeze.

Resolution trigger:
Before Gate 2 freezes DecisionRecord persistence or public APIs.

This decision may block only the DecisionRecord freeze portion of Gate 2. It must not block
unrelated SQLite infrastructure, ProjectRecord, MissionRecord, or audit journal prototyping when
those can remain isolated and noncanonical.

## OD-G1-005 — Kernel/Core Package Name

Status: DEFERRED

Decision needed:
Whether the future domain-neutral namespace is named kernel, core, or another owner-approved
name.

Implementation gate:
Do not perform a package migration or create empty production packages solely to settle naming.

Affected work:
Future package migration only.

Does not block:
ChangeGate vertical MVP or Project Control Bootstrap in existing approved namespaces.

Resolution trigger:
Before the first production package migration.

## OD-G1-006 — Software Delivery Composition Namespace

Status: DEFERRED

Decision needed:
The final namespace for the layer allowed to compose Coordinator and ChangeGate.

Implementation gate:
Coordinator must not directly import ChangeGate. ChangeGate must not import Coordinator. No
composition package may be created until its actual runtime use case exists.

Affected work:
Future software-delivery workflow composition.

Resolution trigger:
Before implementing the first production workflow that invokes both Coordinator and ChangeGate.

## OD-G1-007 — Exact Track Allocation

Status: DEFERRED

Decision needed:
The exact operational allocation within the accepted range:

- Track A — ChangeGate Vertical MVP: 60–70%
- Track B — Project Control Bootstrap: 30–40%

Implementation gate:
None.

Affected work:
Planning and scheduling only.

Resolution trigger:
At the beginning of each implementation cycle based on current blockers and market-validation
needs.

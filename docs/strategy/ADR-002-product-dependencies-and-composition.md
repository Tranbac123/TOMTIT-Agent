# ADR-002: Product Dependency and Composition Boundaries

Title: Product Dependency and Composition Boundaries
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

ADR-001 establishes a domain-neutral platform with ChangeGate as the first wedge. That
separation is only real if the **dependency direction** is enforced. Prose alone does not stop
an `import`. This ADR fixes the canonical dependency graph and makes the load-bearing rules
executable (Gate 1B, `tests/architecture/test_product_boundaries.py`).

Repository inventory (2026-07-13): `agent_core.build_harness` exists and is **self-contained** —
it imports no other `agent_core` package. No kernel, changegate, project_control, coordinator,
adapters, or workflows package exists yet.

## 2. Decision

Adopt the dependency graph in §3 as normative. Enforce the load-bearing directions with
executable direct-static-import tests. Permit exactly one production layer to know both
Coordinator and ChangeGate: the explicit software-delivery composition layer.

## 3. Dependency Direction

```
                         TOMTIT Kernel/Core
                                 ▲
                 ┌───────────────┼───────────────┐
                 │               │               │
         Project Control     Coordinator      ChangeGate
                 ▲               ▲               ▲
                 │               │               │
                 └──── Software Delivery Workflow ┘
                         / Composition Root
```

Arrows point **toward** the dependency (the thing depended upon). Explicitly:

```
project_control                   → depends on domain-neutral kernel/core contracts and ports
coordinator                       → depends on kernel/core plus Project Control ports
changegate                        → depends on kernel/core
software_delivery_workflow        → may depend on coordinator and changegate
  (composition root)
adapters                          → implement inward-facing ports
```

### Forbidden directions

| Forbidden | Rationale |
| --- | --- |
| `coordinator → changegate` | Coordinator must stay domain-neutral (§4) |
| `changegate → coordinator` | ChangeGate must ship standalone (§8) |
| `kernel/core → product packages` | The kernel is the stable base; it must not depend on its consumers |
| `kernel/core → vendor adapters` | Contracts must not depend on integrations |
| `kernel/core → vendor SDKs` | Vendor neutrality |
| `project_control → changegate` | Project Control is domain-neutral |
| `project_control → coordinator` | Coordinator depends on Project Control, not the reverse |
| `project_control → vendor adapters` | Application services depend on ports, not integrations |
| `project_control → vendor SDKs` | Vendor neutrality |
| `coordinator → vendor adapters` | Orchestration depends on ports, not integrations |
| `coordinator → vendor SDKs` | Vendor neutrality |

These hold **unless a later owner-accepted ADR explicitly supersedes the rule.**

## 4. Coordinator Neutrality

Coordinator must remain capable of supervising:

- coding workflows;
- document workflows;
- data operations;
- deployment workflows;
- research workflows;
- future domain agents.

It must **not** import software-delivery-specific:

- Git contracts;
- repository contracts;
- commit/tree identities;
- merge contracts;
- ChangeGate contracts;
- `CandidateBinding`.

The moment Coordinator imports `CandidateBinding`, it stops being an orchestrator and becomes a
Git tool. That is the specific regression this rule exists to prevent.

## 5. Transition Authorization Port

To let Coordinator request authorization **without** knowing about software delivery, a
domain-neutral port is documented here (**not implemented in Gate 1**):

```python
class TransitionAuthorizationPort(Protocol):
    def evaluate(
        self,
        request: TransitionAuthorizationRequest,
    ) -> AuthorizationDecision:
        ...
```

- Coordinator **may call** a general authorization port.
- ChangeGate **may provide** a software-change authorization implementation, supplied through
  dependency injection or the composition layer.
- The port definition and its implementation are **outside Gate 1**.

This is how the forbidden `coordinator → changegate` edge is avoided without losing the
capability: the dependency is inverted through a neutral port.

## 6. Software Delivery Composition

The **only** production layer permitted to know both Coordinator and ChangeGate is the explicit
software-delivery composition layer.

Preferred future namespace:

```
agent_core.workflows.software_delivery
```

An equivalent owner-accepted namespace may be selected later. The architecture test also
recognizes `agent_core.software_delivery_workflow` as a composition prefix.

**The production package is NOT created in Gate 1.** The composition boundary is currently
`RESERVED_BOUNDARY_NOT_YET_INSTANTIATED`. It is not created merely to make a test non-vacuous.

## 7. Adapter Direction

Adapters (`agent_core.adapters`, reserved) **implement inward-facing ports**. Dependency flows
inward: adapters depend on core contracts; core contracts never depend on adapters. Vendor SDKs
live behind adapters and nowhere else.

## 8. Standalone ChangeGate Path

ChangeGate must remain independently usable through:

- CLI;
- JSON input/output;
- Markdown report;
- CI required status check or equivalent adapter.

**ChangeGate must not require Coordinator to evaluate a software change.** This is a commercial
requirement (the wedge must ship alone) *and* an architectural one (it forces the dependency
direction to stay honest).

Consistent with ADR-001 §10: ChangeGate does **not** wait for all Project Control or Coordinator
work to finish; Track A and Track B are independent.

## 9. Runtime Composition

Wiring happens at the composition root, not inside product packages. Products declare ports;
the composition layer supplies implementations. A product package must never reach sideways to
construct another product's concrete type.

## 10. Static Boundary-Test Coverage

`tests/architecture/test_product_boundaries.py` enforces, by AST inspection of direct static
imports under `agent_core/**/*.py`:

- kernel has no outward product dependencies;
- kernel does not import vendor SDKs;
- project_control does not import changegate;
- project_control does not import coordinator;
- project_control does not import vendor adapters;
- project_control does not import vendor SDKs;
- coordinator does not import changegate (both `agent_core.changegate` and the current
  `agent_core.build_harness`);
- coordinator does not import vendor adapters;
- coordinator does not import vendor SDKs;
- changegate does not import coordinator;
- only the software-delivery composition layer may import both coordinator and changegate;
- product prefixes do not overlap;
- every boundary group is explicitly ACTIVE_AND_EXERCISED or
  RESERVED_BOUNDARY_NOT_YET_INSTANTIATED;
- the current ChangeGate boundary is non-vacuous (files under `agent_core.build_harness` are
  actually scanned).

Vendor SDK imports and imports from `agent_core.adapters` are **different categories** and are
tested separately.

## 11. Known Test Limitations

**Gate 1 architecture tests inspect direct static Python imports only.**

They do **not** fully prove runtime dependency safety against:

- `importlib.import_module`;
- `__import__`;
- string-based plugin loading;
- dependency-injection misconfiguration;
- runtime adapter registration;
- service-locator behavior;
- arbitrary registration side effects.

Runtime composition and adapter wiring must be covered by **integration tests in later gates**.

**These tests must not be represented as complete runtime or authority isolation proof.**

Additionally, most boundaries are currently **reserved** (the packages do not exist yet), so
those rules are presently **vacuous** — they constrain future code, they do not certify current
code. Only the ChangeGate boundary is actively exercised today.

## 12. Consequences

- New product packages must be created in the right place or the boundary tests fail.
- Coordinator gains authorization capability only via a neutral port, never a direct import.
- ChangeGate stays shippable alone.
- Reserved rules are pre-armed: the day `agent_core/coordinator` appears, the guard is already
  live.

## 13. Rejected Alternatives

- **Coordinator imports ChangeGate directly.** Rejected: destroys domain neutrality and couples
  the wedge to the orchestrator.
- **ChangeGate calls Coordinator for orchestration.** Rejected: makes the wedge un-shippable
  standalone.
- **Documentation-only boundaries.** Rejected: prose does not stop an `import`; that is why
  Gate 1B is executable.
- **Create empty production packages now so every rule is non-vacuous.** Rejected: empty
  packages to satisfy a diagram are architecture theater; ADR-003 forbids it.
- **A large vendor denylist.** Rejected: unmaintainable; a narrow documented root set is used.

## 14. Deferred Owner Decisions

This ADR is accepted. The unresolved decisions are maintained in
`docs/architecture/GATE_1_DEFERRED_OWNER_DECISIONS.md`.

Acceptance does not authorize coding agents to choose those deferred semantics. Only an
implementation that directly depends on a deferred decision is blocked by it.

## 15. Owner Decision

**Status: ACCEPTED_BY_OWNER. Technical Review: PASS. Owner Acceptance: ACCEPTED.**

TranBac accepted this ADR through owner decision
`ACCEPT_ALL_THREE_ADRS_WITH_DEFERRED_OWNER_DECISIONS` for accepted candidate
`7bd3d7e86dc23af544325d228723c067f9f34200`. The seven registered owner decisions remain
deferred and may be resolved only through a new owner-reviewed decision or ADR amendment.

"""P0-9A — role prompts generated from a TaskContract.

Deterministic templates. Every generated prompt embeds the contract's scope, evidence
requirements, and the non-negotiable rails for that role, and ends with the
machine_summary contract so report ingestion is reliable.
"""
from __future__ import annotations

from enum import StrEnum

from agent_core.build_harness.contracts import TaskContract


class AgentRole(StrEnum):
    ARCHITECT = "architect"
    IMPLEMENTER = "implementer"
    VERIFIER = "verifier"
    GATEKEEPER = "gatekeeper"
    RELEASE_OPERATOR = "release_operator"


def _bullets(items: list[str], empty: str = "(none)") -> str:
    return "\n".join(f"- {item}" for item in items) if items else f"- {empty}"


def _machine_summary_block(contract: TaskContract, role: AgentRole, statuses: str) -> str:
    return f"""## Required output — machine_summary

End your report with this fenced JSON block (exact key names):

```json
{{
  "machine_summary": {{
    "task_id": "{contract.task_id}",
    "role": "{role.value}",
    "status": "{statuses}",
    "result": "PASS | NEEDS_FIX | BLOCKED",
    "files_changed": [],
    "tests_run": [],
    "blockers": [],
    "next_recommended_action": null
  }}
}}
```"""


def _contract_header(contract: TaskContract) -> str:
    return f"""# Task {contract.task_id} — {contract.title}

## Goal
{contract.goal}

## Allowed paths (scope)
{_bullets(contract.allowed_paths, "broad scope explicitly allowed" if contract.broad_scope_allowed else "(none)")}

## Forbidden paths
{_bullets(contract.forbidden_paths)}

## Acceptance criteria
{_bullets(contract.acceptance_criteria)}

## Required evidence
{_bullets(contract.required_evidence)}

## Risk level
{contract.risk_level}

## Human approval required for
{_bullets(contract.requires_human_approval_for)}"""


def generate_prompt(contract: TaskContract, role: AgentRole) -> str:
    header = _contract_header(contract)

    if role is AgentRole.IMPLEMENTER:
        return f"""{header}

## Role: IMPLEMENTER

Rules (non-negotiable):
- Implement ONLY within the allowed paths above.
- Do not merge.
- Do not push.
- Do not edit forbidden files.
- Do not add dependencies unless approved by a human first.
- Run and record the required evidence commands exactly as listed.
- Commit on a feature branch; report the exact commit SHA.

{_machine_summary_block(contract, role, "IMPLEMENTED | BLOCKED")}"""

    if role is AgentRole.VERIFIER:
        return f"""{header}

## Role: VERIFIER

Rules (non-negotiable):
- Verify only. Do not edit code.
- Do not commit. Do not merge. Do not push.
- Check scope: every changed file must be within the allowed paths.
- Check forbidden paths were not touched.
- Check dependency files were not changed without approval.
- Check the required tests/evidence were actually run and passed.
- Return exactly one verdict: PASS / NEEDS_FIX / BLOCKED.

{_machine_summary_block(contract, role, "VERIFIED | BLOCKED")}"""

    if role is AgentRole.RELEASE_OPERATOR:
        return f"""{header}

## Role: RELEASE_OPERATOR

Rules (non-negotiable):
- Merge/push ONLY after every gate has passed and human approval is recorded.
- Do not force push. Never rewrite remote history.
- Verify the exact commit identity (SHA) being merged matches the approved candidate.
- Verify clean tracked/staged state before and after the merge.
- Report the final remote SHA after the push.

{_machine_summary_block(contract, role, "MERGED | BLOCKED")}"""

    if role is AgentRole.ARCHITECT:
        return f"""{header}

## Role: ARCHITECT

Rules:
- Refine the contract: scope, acceptance criteria, risks, evidence requirements.
- Do not implement. Do not merge. Do not push.

{_machine_summary_block(contract, role, "CONTRACT_READY | BLOCKED")}"""

    # GATEKEEPER
    return f"""{header}

## Role: GATEKEEPER

Rules:
- Evaluate the change against the contract: scope, forbidden paths, dependencies, evidence.
- Do not edit code. Do not merge. Do not push.
- Return exactly one decision: PASS / REVIEW_REQUIRED / BLOCK.

{_machine_summary_block(contract, role, "GATED | BLOCKED")}"""

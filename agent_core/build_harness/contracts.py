"""P0-9A — TaskContract schema: the single source of truth for one governed task.

A contract states WHAT may change (allowed/forbidden paths), WHAT must be proven
(acceptance criteria, required evidence), and WHICH actions need a human (merge/push/
deploy/dependency changes). Malformed contracts fail loudly — a silent bad contract
would poison every downstream gate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_VALID_RISK_LEVELS = ("low", "medium", "high")
_DEFAULT_HUMAN_APPROVAL_ACTIONS = ["merge", "push", "deploy", "dependency_change"]


class ContractValidationError(ValueError):
    """Raised when a task contract is structurally invalid. Message names every problem."""


@dataclass(frozen=True)
class TaskContract:
    task_id: str
    title: str
    goal: str
    allowed_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    risk_level: str = "medium"
    requires_human_approval_for: list[str] = field(
        default_factory=lambda: list(_DEFAULT_HUMAN_APPROVAL_ACTIONS)
    )
    broad_scope_allowed: bool = False


def _as_str_list(value: Any, field_name: str, errors: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        errors.append(f"{field_name} must be a list of strings")
        return []
    return [v.strip() for v in value if v.strip()]


def validate_contract_dict(data: dict[str, Any]) -> TaskContract:
    """Build a TaskContract from a plain dict, collecting ALL validation errors."""
    if not isinstance(data, dict):
        raise ContractValidationError("contract must be a JSON object")

    errors: list[str] = []

    def _req_str(name: str) -> str:
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{name} is required and must be a non-empty string")
            return ""
        return value.strip()

    task_id = _req_str("task_id")
    title = _req_str("title")
    goal = _req_str("goal")

    allowed_paths = _as_str_list(data.get("allowed_paths"), "allowed_paths", errors)
    forbidden_paths = _as_str_list(data.get("forbidden_paths"), "forbidden_paths", errors)
    acceptance = _as_str_list(
        data.get("acceptance_criteria"), "acceptance_criteria", errors
    )
    if not acceptance and not any(e.startswith("acceptance_criteria") for e in errors):
        errors.append("acceptance_criteria requires at least one criterion")
    required_evidence = _as_str_list(
        data.get("required_evidence"), "required_evidence", errors
    )

    risk_level = data.get("risk_level", "medium")
    if not isinstance(risk_level, str) or risk_level not in _VALID_RISK_LEVELS:
        errors.append(f"risk_level must be one of {_VALID_RISK_LEVELS}")
        risk_level = "medium"

    broad_scope_allowed = bool(data.get("broad_scope_allowed", False))
    if not allowed_paths and not broad_scope_allowed:
        errors.append(
            "allowed_paths may be empty only when broad_scope_allowed is true"
        )

    approval_raw = data.get("requires_human_approval_for")
    if approval_raw is None:
        approval = list(_DEFAULT_HUMAN_APPROVAL_ACTIONS)
    else:
        approval = _as_str_list(approval_raw, "requires_human_approval_for", errors)

    if errors:
        raise ContractValidationError(
            "invalid task contract: " + "; ".join(errors)
        )

    return TaskContract(
        task_id=task_id,
        title=title,
        goal=goal,
        allowed_paths=allowed_paths,
        forbidden_paths=forbidden_paths,
        acceptance_criteria=acceptance,
        required_evidence=required_evidence,
        risk_level=risk_level,
        requires_human_approval_for=approval,
        broad_scope_allowed=broad_scope_allowed,
    )


def load_task_contract(path: str | Path) -> TaskContract:
    """Load and validate a contract from a JSON file."""
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractValidationError(f"contract file is not valid JSON: {exc}") from exc
    return validate_contract_dict(data)


def contract_to_dict(contract: TaskContract) -> dict[str, Any]:
    """JSON-safe dict view (used by the evidence store and CLI)."""
    return {
        "task_id": contract.task_id,
        "title": contract.title,
        "goal": contract.goal,
        "allowed_paths": contract.allowed_paths,
        "forbidden_paths": contract.forbidden_paths,
        "acceptance_criteria": contract.acceptance_criteria,
        "required_evidence": contract.required_evidence,
        "risk_level": contract.risk_level,
        "requires_human_approval_for": contract.requires_human_approval_for,
        "broad_scope_allowed": contract.broad_scope_allowed,
    }

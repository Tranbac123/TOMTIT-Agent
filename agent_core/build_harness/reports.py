"""P0-9A — agent report models + machine_summary ingestion.

Agents (Claude Code, Codex, ...) end their reports with a ``machine_summary`` block —
either a fenced JSON block or a simple YAML-ish block. The parser is deliberately
conservative (stdlib-only, no PyYAML) and fails CLOSED.

P0-9A-R2 strictness:
- reports larger than 1 MiB are rejected;
- EXACTLY one machine_summary block is allowed — multiple JSON blocks, multiple YAML
  blocks, or a JSON+YAML mix are rejected (never "pick the first");
- duplicate keys (JSON and YAML-ish) are rejected;
- the schema is validated exactly: required fields present, scalars are real strings
  (no booleans/numbers/objects), lists are lists of strings;
- role/status/result come from closed vocabularies and the (role, status, result)
  combination must be one of the explicitly allowed pairs — contradictions such as
  ``status=BLOCKED, result=PASS`` are rejected.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from agent_core.build_harness.validation import is_valid_task_id

MAX_REPORT_BYTES = 1024 * 1024  # 1 MiB fail-closed boundary

ALLOWED_ROLES = frozenset({
    "architect", "implementer", "verifier", "gatekeeper", "release_operator",
})
ALLOWED_RESULTS = frozenset({"PASS", "NEEDS_FIX", "BLOCKED"})

# Closed (status, result) vocabulary per role. Anything else is a contradiction.
ALLOWED_STATUS_RESULT_BY_ROLE: dict[str, frozenset[tuple[str, str]]] = {
    "implementer": frozenset({("IMPLEMENTED", "PASS"), ("BLOCKED", "BLOCKED")}),
    "verifier": frozenset({
        ("VERIFIED_PASS", "PASS"), ("NEEDS_FIX", "NEEDS_FIX"), ("BLOCKED", "BLOCKED"),
    }),
    "architect": frozenset({("CONTRACT_READY", "PASS"), ("BLOCKED", "BLOCKED")}),
    "gatekeeper": frozenset({
        ("GATED", "PASS"), ("GATED", "NEEDS_FIX"), ("BLOCKED", "BLOCKED"),
    }),
    "release_operator": frozenset({("MERGED", "PASS"), ("BLOCKED", "BLOCKED")}),
}

_REQUIRED_FIELDS = (
    "task_id", "role", "status", "result", "files_changed", "tests_run", "blockers",
)
_OPTIONAL_FIELDS = ("next_recommended_action", "commit_sha")
# P0-9A-R3: the machine_summary schema is exact — unknown keys are rejected.
_ALLOWED_FIELDS = frozenset(_REQUIRED_FIELDS) | frozenset(_OPTIONAL_FIELDS)


@dataclass(frozen=True)
class AgentReport:
    task_id: str
    role: str
    status: str
    result: str
    files_changed: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_recommended_action: str | None = None
    commit_sha: str | None = None
    raw_text: str = ""
    parse_ok: bool = True
    parse_error: str | None = None


@dataclass(frozen=True)
class AgentRun:
    """One invocation of an agent for a task: which role ran, and what it reported."""
    task_id: str
    role: str
    agent_name: str
    report: AgentReport


def is_allowed_status_result(role: str, status: str, result: str) -> bool:
    """Shared with ProcessGuard so identity revalidation uses the same vocabulary."""
    return (status, result) in ALLOWED_STATUS_RESULT_BY_ROLE.get(role, frozenset())


_RE_JSON_FENCE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL)
_RE_YAMLISH_START = re.compile(r"^machine_summary:\s*$", re.MULTILINE)


class _SummaryError(ValueError):
    """Internal: a machine_summary failed strict validation."""


def _failed(raw_text: str, reason: str) -> AgentReport:
    return AgentReport(
        task_id="", role="", status="BLOCKED", result="BLOCKED",
        raw_text=raw_text, parse_ok=False, parse_error=reason,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _SummaryError(f"duplicate key {key!r} in machine_summary JSON")
        result[key] = value
    return result


def _require_str(summary: dict[str, Any], key: str) -> str:
    value = summary.get(key)
    # bool is an int subclass — reject explicitly.
    if not isinstance(value, str) or isinstance(value, bool) or not value.strip():
        raise _SummaryError(
            f"machine_summary field {key!r} must be a non-empty string, got {value!r}"
        )
    return value.strip()


def _require_str_list(summary: dict[str, Any], key: str) -> list[str]:
    value = summary.get(key)
    if not isinstance(value, list):
        raise _SummaryError(
            f"machine_summary field {key!r} must be a list of strings, got {value!r}"
        )
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or isinstance(item, bool):
            raise _SummaryError(
                f"machine_summary field {key!r} contains a non-string item: {item!r}"
            )
        items.append(item)
    return items


def _optional_str(summary: dict[str, Any], key: str) -> str | None:
    value = summary.get(key)
    if value is None or (isinstance(value, str) and value.lower() == "null"):
        return None
    if not isinstance(value, str) or isinstance(value, bool):
        raise _SummaryError(
            f"machine_summary field {key!r} must be a string or null, got {value!r}"
        )
    return value.strip() or None


def _from_summary_dict(summary: dict[str, Any], raw_text: str) -> AgentReport:
    for key in _REQUIRED_FIELDS:
        if key not in summary:
            raise _SummaryError(f"machine_summary is missing required field {key!r}")
    # R3: exact schema — reject any key outside the allowed set.
    unknown = sorted(set(summary) - _ALLOWED_FIELDS)
    if unknown:
        raise _SummaryError(f"machine_summary has unknown field(s): {unknown}")

    task_id = _require_str(summary, "task_id")
    if not is_valid_task_id(task_id):
        raise _SummaryError(f"machine_summary task_id {task_id!r} is not a valid task id")
    role = _require_str(summary, "role")
    if role not in ALLOWED_ROLES:
        raise _SummaryError(f"unknown role {role!r} (allowed: {sorted(ALLOWED_ROLES)})")
    status = _require_str(summary, "status")
    result = _require_str(summary, "result")
    if result not in ALLOWED_RESULTS:
        raise _SummaryError(
            f"unknown result {result!r} (allowed: {sorted(ALLOWED_RESULTS)})"
        )
    if not is_allowed_status_result(role, status, result):
        raise _SummaryError(
            f"contradictory or unknown status/result for role {role!r}: "
            f"status={status!r}, result={result!r}"
        )

    return AgentReport(
        task_id=task_id,
        role=role,
        status=status,
        result=result,
        files_changed=_require_str_list(summary, "files_changed"),
        tests_run=_require_str_list(summary, "tests_run"),
        blockers=_require_str_list(summary, "blockers"),
        next_recommended_action=_optional_str(summary, "next_recommended_action"),
        commit_sha=_optional_str(summary, "commit_sha"),
        raw_text=raw_text,
        parse_ok=True,
    )


def _parse_yamlish_block(text: str, start: int) -> dict[str, Any]:
    """Parse the simple indented block after ``machine_summary:``.

    Supported shapes only: ``  key: value``, ``  key: []``, and ``  key:`` followed by
    ``    - item`` lines. Duplicate keys are rejected. Anything else ends the block.
    """
    summary: dict[str, Any] = {}
    lines = text[start:].splitlines()[1:]  # skip the "machine_summary:" line itself
    current_list_key: str | None = None
    for line in lines:
        if not line.strip():
            break
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent >= 4 and stripped.startswith("- ") and current_list_key:
            summary.setdefault(current_list_key, []).append(stripped[2:].strip())
            continue
        if indent >= 2 and ":" in stripped and not stripped.startswith("- "):
            key, _, value = stripped.partition(":")
            key, value = key.strip(), value.strip()
            if key in summary:
                raise _SummaryError(
                    f"duplicate key {key!r} in machine_summary YAML block"
                )
            if value == "":
                current_list_key = key
                summary[key] = []
            elif value == "[]":
                current_list_key = None
                summary[key] = []
            else:
                current_list_key = None
                summary[key] = value
            continue
        break  # dedent or unsupported shape → end of block
    return summary


def parse_agent_report(text: str) -> AgentReport:
    """Extract exactly ONE machine_summary from an agent report, fail-closed."""
    if len(text.encode("utf-8", errors="replace")) > MAX_REPORT_BYTES:
        return _failed(
            "<oversized report omitted>",
            f"report exceeds the {MAX_REPORT_BYTES} byte limit",
        )

    # Count every candidate summary block FIRST — more than one is always rejected,
    # regardless of which of them would parse.
    json_candidates = [
        match for match in _RE_JSON_FENCE.finditer(text)
        if "machine_summary" in match.group(1)
    ]
    yaml_candidates = list(_RE_YAMLISH_START.finditer(text))
    total = len(json_candidates) + len(yaml_candidates)
    if total == 0:
        return _failed(text, "no machine_summary block found in report")
    if total > 1:
        return _failed(
            text,
            f"multiple/conflicting machine_summary blocks found "
            f"({len(json_candidates)} JSON, {len(yaml_candidates)} YAML); exactly one "
            "is required",
        )

    try:
        if json_candidates:
            try:
                payload = json.loads(
                    json_candidates[0].group(1),
                    object_pairs_hook=_reject_duplicate_keys,
                )
            except json.JSONDecodeError as exc:
                return _failed(text, f"machine_summary JSON block is invalid: {exc}")
            if not isinstance(payload, dict) or not isinstance(
                payload.get("machine_summary"), dict
            ):
                return _failed(
                    text, "JSON block does not contain a machine_summary object"
                )
            return _from_summary_dict(payload["machine_summary"], text)

        summary = _parse_yamlish_block(text, yaml_candidates[0].start())
        return _from_summary_dict(summary, text)
    except _SummaryError as exc:
        return _failed(text, str(exc))

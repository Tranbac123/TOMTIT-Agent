"""P0-9A — agent report models + machine_summary ingestion.

Agents (Claude Code, Codex, ...) end their reports with a ``machine_summary`` block —
either a fenced JSON block or a simple YAML-ish block. The parser is deliberately
conservative (stdlib-only, no PyYAML): it handles exactly the documented shapes and
fails CLOSED — a report without a parseable machine_summary ingests as
``parse_ok=False / result=BLOCKED`` so no gate downstream can treat it as a pass.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


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


_RE_JSON_FENCE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL)
_RE_YAMLISH_START = re.compile(r"^machine_summary:\s*$", re.MULTILINE)


def _failed(raw_text: str, reason: str) -> AgentReport:
    return AgentReport(
        task_id="", role="", status="BLOCKED", result="BLOCKED",
        raw_text=raw_text, parse_ok=False, parse_error=reason,
    )


def _from_summary_dict(summary: dict[str, Any], raw_text: str) -> AgentReport:
    def _strs(key: str) -> list[str]:
        value = summary.get(key) or []
        return [str(v) for v in value] if isinstance(value, list) else [str(value)]

    next_action = summary.get("next_recommended_action")
    return AgentReport(
        task_id=str(summary.get("task_id", "")),
        role=str(summary.get("role", "")),
        status=str(summary.get("status", "")),
        result=str(summary.get("result", "")),
        files_changed=_strs("files_changed"),
        tests_run=_strs("tests_run"),
        blockers=_strs("blockers"),
        next_recommended_action=str(next_action) if next_action else None,
        raw_text=raw_text,
        parse_ok=True,
    )


def _parse_yamlish_block(text: str, start: int) -> dict[str, Any]:
    """Parse the simple indented block after ``machine_summary:``.

    Supported shapes only: ``  key: value``, ``  key: []``, and ``  key:`` followed by
    ``    - item`` lines. Anything else ends the block. Not a YAML parser by design.
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
        if indent >= 2 and ":" in stripped:
            key, _, value = stripped.partition(":")
            key, value = key.strip(), value.strip()
            if value == "":
                current_list_key = key
                summary.setdefault(key, [])
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
    """Extract the machine_summary from an agent report (JSON fence first, then YAML-ish)."""
    for match in _RE_JSON_FENCE.finditer(text):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("machine_summary"), dict):
            return _from_summary_dict(payload["machine_summary"], text)

    yamlish = _RE_YAMLISH_START.search(text)
    if yamlish:
        summary = _parse_yamlish_block(text, yamlish.start())
        if summary.get("task_id"):
            return _from_summary_dict(summary, text)
        return _failed(text, "machine_summary block found but no task_id could be parsed")

    return _failed(text, "no machine_summary block found in report")

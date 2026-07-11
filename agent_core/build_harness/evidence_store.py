"""P0-9A — local JSON/JSONL evidence store. No database, no network, no secrets.

P0-9A-R2 hardening (fail-closed):
- every identifier used in a path passes the strict grammar (rejected, never sanitized);
- every resolved write target must stay under the resolved task directory (symlink
  escapes rejected);
- artifact writes are atomic (temp file + fsync + os.replace) and never silently
  overwrite: an existing artifact with different bytes raises EvidenceConflictError
  (byte-identical rewrites are idempotent no-ops);
- corrupt JSON surfaces as EvidenceCorruptionError, never as empty/PASS evidence.

Layout under the store root:
    <task_id>/contract.json
    <task_id>/prompts/<role>.md
    <task_id>/reports/<role>.md
    <task_id>/gate/<name>.json
    <task_id>/events.jsonl
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from agent_core.build_harness.contracts import TaskContract, contract_to_dict
from agent_core.build_harness.validation import (
    InvalidEvidenceIdentifierError,
    validate_artifact_name,
    validate_task_id,
)

__all__ = [
    "DEFAULT_EVIDENCE_ROOT",
    "EvidenceStore",
    "EvidenceConflictError",
    "EvidenceCorruptionError",
    "EvidenceStructureError",
    "EvidencePathEscapeError",
    "InvalidEvidenceIdentifierError",
]

DEFAULT_EVIDENCE_ROOT = Path(".artifacts/build_harness")


class EvidencePathEscapeError(ValueError):
    """A resolved write target escaped the task directory (traversal/symlink)."""


class EvidenceConflictError(RuntimeError):
    """An authoritative artifact already exists with different content."""


class EvidenceCorruptionError(RuntimeError):
    """A stored JSON artifact could not be parsed; evidence must not be trusted."""


class EvidenceStructureError(EvidenceCorruptionError):
    """A stored artifact is syntactically valid JSON but structurally invalid.

    Subclasses EvidenceCorruptionError so callers catching corruption also catch structural
    problems — both mean the artifact must not be trusted as authoritative evidence.
    """


class EvidenceStore:
    def __init__(self, root: Path | str = DEFAULT_EVIDENCE_ROOT) -> None:
        self._root = Path(root)

    def _task_dir(self, task_id: str) -> Path:
        validate_task_id(task_id)
        path = self._root / task_id
        path.mkdir(parents=True, exist_ok=True)
        resolved_root = self._root.resolve()
        resolved = path.resolve()
        if resolved != resolved_root / task_id or not resolved.is_relative_to(resolved_root):
            raise EvidencePathEscapeError(
                f"task directory escaped the store root: {task_id!r} -> {resolved}"
            )
        return path

    def _target(self, task_id: str, *parts: str) -> Path:
        """Build and containment-check a write target under the task directory."""
        task_dir = self._task_dir(task_id)
        target = task_dir.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        resolved_task_dir = task_dir.resolve()
        resolved_parent = target.parent.resolve()
        if not resolved_parent.is_relative_to(resolved_task_dir):
            raise EvidencePathEscapeError(
                f"artifact parent escaped the task directory: {target}"
            )
        if target.is_symlink():
            raise EvidencePathEscapeError(f"artifact target is a symlink: {target}")
        return target

    @staticmethod
    def _write_atomic(target: Path, data: str) -> Path:
        """Atomic create: temp file in the same directory, fsync, os.replace.

        No silent overwrite: an existing target with identical bytes is an idempotent
        no-op; different bytes raise EvidenceConflictError.
        """
        encoded = data.encode("utf-8")
        if target.exists():
            existing = target.read_bytes()
            if existing == encoded:
                return target  # idempotent rewrite of identical content
            raise EvidenceConflictError(
                f"artifact already exists with different content: {target}"
            )
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-evidence-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return target

    def _write_json(self, target: Path, payload: dict) -> Path:
        return self._write_atomic(
            target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )

    def save_contract(self, contract: TaskContract) -> Path:
        target = self._target(contract.task_id, "contract.json")
        return self._write_json(target, contract_to_dict(contract))

    def save_prompt(self, task_id: str, role: str, prompt: str) -> Path:
        validate_artifact_name(role, kind="prompt role")
        target = self._target(task_id, "prompts", f"{role}.md")
        return self._write_atomic(target, prompt)

    def save_report(self, task_id: str, role: str, text: str) -> Path:
        validate_artifact_name(role, kind="report role")
        target = self._target(task_id, "reports", f"{role}.md")
        return self._write_atomic(target, text)

    def save_gate_result(self, task_id: str, name: str, payload: dict) -> Path:
        validate_artifact_name(name, kind="gate name")
        target = self._target(task_id, "gate", f"{name}.json")
        return self._write_json(target, payload)

    def append_event(self, task_id: str, event_type: str, payload: dict) -> Path:
        validate_artifact_name(event_type, kind="event type")
        path = self._target(task_id, "events.jsonl")
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "event_type": event_type,
            "payload": payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return path

    def _read_json(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EvidenceCorruptionError(
                f"corrupt evidence artifact {path}: {exc}"
            ) from exc

    def load_task_summary(self, task_id: str) -> dict:
        task_dir = self._task_dir(task_id)
        summary: dict = {"task_id": task_id, "contract": None, "prompts": {},
                         "reports": {}, "gates": {}, "events": []}
        contract_path = task_dir / "contract.json"
        if contract_path.exists():
            contract = self._read_json(contract_path)
            if not isinstance(contract, dict):
                raise EvidenceStructureError(
                    f"contract.json must be a JSON object, got {type(contract).__name__}"
                )
            stored_task_id = contract.get("task_id")
            if stored_task_id != task_id:
                raise EvidenceStructureError(
                    f"contract.json task_id {stored_task_id!r} does not match the "
                    f"requested namespace {task_id!r}"
                )
            summary["contract"] = contract
        for prompt_path in sorted((task_dir / "prompts").glob("*.md")):
            summary["prompts"][prompt_path.stem] = prompt_path.read_text(encoding="utf-8")
        for report_path in sorted((task_dir / "reports").glob("*.md")):
            summary["reports"][report_path.stem] = report_path.read_text(encoding="utf-8")
        for gate_path in sorted((task_dir / "gate").glob("*.json")):
            gate_payload = self._read_json(gate_path)
            if not isinstance(gate_payload, dict):
                raise EvidenceStructureError(
                    f"{gate_path.name} must be a JSON object, got "
                    f"{type(gate_payload).__name__}"
                )
            summary["gates"][gate_path.stem] = gate_payload
        events_path = task_dir / "events.jsonl"
        if events_path.exists():
            events = []
            for line_number, line in enumerate(
                events_path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise EvidenceCorruptionError(
                        f"corrupt event at {events_path}:{line_number}: {exc}"
                    ) from exc
                self._validate_event_structure(event, events_path, line_number, task_id)
                events.append(event)
            summary["events"] = events
        return summary

    @staticmethod
    def _validate_event_structure(
        event: object, path: Path, line_number: int, task_id: str
    ) -> None:
        loc = f"{path}:{line_number}"
        if not isinstance(event, dict):
            raise EvidenceStructureError(
                f"event at {loc} must be a JSON object, got {type(event).__name__}"
            )
        for key in ("task_id", "event_type", "timestamp"):
            value = event.get(key)
            if not isinstance(value, str) or not value.strip():
                raise EvidenceStructureError(
                    f"event at {loc} field {key!r} must be a non-empty string"
                )
        if event["task_id"] != task_id:
            raise EvidenceStructureError(
                f"event at {loc} task_id {event['task_id']!r} does not match the "
                f"requested namespace {task_id!r}"
            )
        if not isinstance(event.get("payload"), dict):
            raise EvidenceStructureError(
                f"event at {loc} payload must be a JSON object"
            )

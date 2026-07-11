"""P0-9A — local JSON/JSONL evidence store. No database, no network, no secrets.

Layout under the store root:
    <task_id>/contract.json
    <task_id>/prompts/<role>.md
    <task_id>/reports/<role>.md
    <task_id>/gate/<name>.json
    <task_id>/events.jsonl
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent_core.build_harness.contracts import TaskContract, contract_to_dict

DEFAULT_EVIDENCE_ROOT = Path(".artifacts/build_harness")


class EvidenceStore:
    def __init__(self, root: Path | str = DEFAULT_EVIDENCE_ROOT) -> None:
        self._root = Path(root)

    def _task_dir(self, task_id: str) -> Path:
        safe = task_id.strip().replace("/", "_")
        if not safe:
            raise ValueError("task_id must be non-empty")
        path = self._root / safe
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_json(self, path: Path, payload: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return path

    def save_contract(self, contract: TaskContract) -> Path:
        return self._write_json(
            self._task_dir(contract.task_id) / "contract.json",
            contract_to_dict(contract),
        )

    def save_prompt(self, task_id: str, role: str, prompt: str) -> Path:
        path = self._task_dir(task_id) / "prompts" / f"{role}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prompt, encoding="utf-8")
        return path

    def save_report(self, task_id: str, role: str, text: str) -> Path:
        path = self._task_dir(task_id) / "reports" / f"{role}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def save_gate_result(self, task_id: str, name: str, payload: dict) -> Path:
        return self._write_json(self._task_dir(task_id) / "gate" / f"{name}.json", payload)

    def append_event(self, task_id: str, event_type: str, payload: dict) -> Path:
        path = self._task_dir(task_id) / "events.jsonl"
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "event_type": event_type,
            "payload": payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return path

    def load_task_summary(self, task_id: str) -> dict:
        task_dir = self._task_dir(task_id)
        summary: dict = {"task_id": task_id, "contract": None, "prompts": {},
                         "reports": {}, "gates": {}, "events": []}
        contract_path = task_dir / "contract.json"
        if contract_path.exists():
            summary["contract"] = json.loads(contract_path.read_text(encoding="utf-8"))
        for prompt_path in sorted((task_dir / "prompts").glob("*.md")):
            summary["prompts"][prompt_path.stem] = prompt_path.read_text(encoding="utf-8")
        for report_path in sorted((task_dir / "reports").glob("*.md")):
            summary["reports"][report_path.stem] = report_path.read_text(encoding="utf-8")
        for gate_path in sorted((task_dir / "gate").glob("*.json")):
            summary["gates"][gate_path.stem] = json.loads(
                gate_path.read_text(encoding="utf-8")
            )
        events_path = task_dir / "events.jsonl"
        if events_path.exists():
            summary["events"] = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        return summary

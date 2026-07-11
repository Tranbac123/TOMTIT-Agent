"""P0-9A — Build Harness CLI (stdlib argparse; JSON output for machine readability).

Commands:
    validate-contract --contract <path>
    generate-prompt   --contract <path> --role <role>            (prints raw prompt text)
    ingest-report     --contract <path> --report <path> --role <role>
    changegate        --contract <path> --changed-files F [F...] --tests-run T [T...]
    next-action       --contract <path> [--implementer-report P] [--verifier-report P]

The CLI never runs git or shell commands: changed files and test evidence are explicit
arguments supplied by the operator.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_core.build_harness.change_gate import (
    ChangeGateInput,
    CommandEvidence,
    InvalidCommandEvidenceError,
    evaluate_change_gate,
)
from agent_core.build_harness.contracts import (
    ContractValidationError,
    contract_to_dict,
    load_task_contract,
)
from agent_core.build_harness.next_action import recommend_next_action
from agent_core.build_harness.prompt_generator import AgentRole, generate_prompt
from agent_core.build_harness.reports import parse_agent_report


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _load_contract_or_exit(path: str):
    try:
        return load_task_contract(path)
    except (ContractValidationError, OSError) as exc:
        _print_json({"ok": False, "error": str(exc)})
        raise SystemExit(1)


_EVIDENCE_REQUIRED_KEYS = frozenset({
    "evidence_id", "command", "exit_code", "completed", "commit_sha",
})
_EVIDENCE_ALLOWED_KEYS = _EVIDENCE_REQUIRED_KEYS | {"completed_at", "artifact_digest"}


def _load_evidence_file(path: str) -> tuple[list[CommandEvidence], list[str]]:
    """Strictly parse a changegate evidence file.

    Returns ``(evidence, errors)``. When ``errors`` is non-empty the evidence must not be
    trusted. NO coercion: each field must already have the exact JSON type CommandEvidence
    requires (its ``__post_init__`` enforces this; we surface a clean error, not a
    traceback).
    """
    errors: list[str] = []
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        return [], [f"cannot read evidence file: {exc}"]
    except json.JSONDecodeError as exc:
        return [], [f"evidence file is not valid JSON: {exc}"]

    if not isinstance(raw, dict):
        return [], ["evidence file root must be a JSON object"]
    unknown_root = sorted(set(raw) - {"evidence"})
    if unknown_root:
        errors.append(f"unknown root key(s): {unknown_root}")
    entries = raw.get("evidence")
    if not isinstance(entries, list):
        errors.append('"evidence" must be a list')
        return [], errors

    evidence: list[CommandEvidence] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"evidence[{index}] must be a JSON object")
            continue
        missing = sorted(_EVIDENCE_REQUIRED_KEYS - set(entry))
        if missing:
            errors.append(f"evidence[{index}] missing field(s): {missing}")
        unknown = sorted(set(entry) - _EVIDENCE_ALLOWED_KEYS)
        if unknown:
            errors.append(f"evidence[{index}] has unknown field(s): {unknown}")
        if missing or unknown:
            continue
        try:
            evidence.append(CommandEvidence(
                command=entry["command"],
                exit_code=entry["exit_code"],
                completed=entry["completed"],
                commit_sha=entry["commit_sha"],
                evidence_id=entry["evidence_id"],
                completed_at=entry.get("completed_at"),
                artifact_digest=entry.get("artifact_digest"),
            ))
        except InvalidCommandEvidenceError as exc:
            errors.append(f"evidence[{index}] invalid: {exc}")
    return evidence, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_harness", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate-contract")
    p_validate.add_argument("--contract", required=True)

    p_prompt = sub.add_parser("generate-prompt")
    p_prompt.add_argument("--contract", required=True)
    p_prompt.add_argument("--role", required=True,
                          choices=[r.value for r in AgentRole])

    p_ingest = sub.add_parser("ingest-report")
    p_ingest.add_argument("--contract", required=True)
    p_ingest.add_argument("--report", required=True)
    p_ingest.add_argument("--role", required=True)

    p_gate = sub.add_parser("changegate")
    p_gate.add_argument("--contract", required=True)
    p_gate.add_argument("--changed-files", nargs="+", default=[])
    p_gate.add_argument("--tests-run", nargs="+", default=[],
                        help="legacy display-only command strings (unverified)")
    p_gate.add_argument("--expected-commit", default="",
                        help="commit SHA the structured evidence must be bound to")
    p_gate.add_argument("--evidence-file", default=None,
                        help='JSON file: {"evidence": [{evidence_id, command, exit_code, '
                             "completed, commit_sha}, ...]}")

    p_next = sub.add_parser("next-action")
    p_next.add_argument("--contract", required=True)
    p_next.add_argument("--implementer-report", default=None)
    p_next.add_argument("--verifier-report", default=None)

    args = parser.parse_args(argv)

    if args.command == "validate-contract":
        contract = _load_contract_or_exit(args.contract)
        _print_json({"ok": True, "contract": contract_to_dict(contract)})
        return 0

    if args.command == "generate-prompt":
        contract = _load_contract_or_exit(args.contract)
        # Raw prompt text on stdout so it can be piped straight to an agent.
        print(generate_prompt(contract, AgentRole(args.role)))
        return 0

    if args.command == "ingest-report":
        contract = _load_contract_or_exit(args.contract)
        report = parse_agent_report(Path(args.report).read_text(encoding="utf-8"))
        # P0-9A-R1 fail-closed ingestion: a report is accepted (exit 0) ONLY when it
        # parsed, is not BLOCKED, and matches both the contract's task and the requested
        # role. NEEDS_FIX still ingests fine — ProcessGuard/NextAction own that verdict.
        task_matches = report.parse_ok and report.task_id == contract.task_id
        role_matches = report.parse_ok and report.role == args.role
        blocked = report.result.upper() == "BLOCKED"
        accepted = report.parse_ok and not blocked and task_matches and role_matches
        rejection_reasons = []
        if not report.parse_ok:
            rejection_reasons.append(f"unparseable report: {report.parse_error}")
        if blocked:
            rejection_reasons.append("report result is BLOCKED")
        if report.parse_ok and not task_matches:
            rejection_reasons.append(
                f"task mismatch: report={report.task_id!r} contract={contract.task_id!r}"
            )
        if report.parse_ok and not role_matches:
            rejection_reasons.append(
                f"role mismatch: report={report.role!r} requested={args.role!r}"
            )
        payload = {
            "ok": accepted,
            "parse_ok": report.parse_ok,
            "result": report.result,
            "task_matches": task_matches,
            "role_matches": role_matches,
            "task_id": report.task_id,
            "role": report.role,
            "requested_role": args.role,
            "rejection_reasons": rejection_reasons,
            "report": {
                "status": report.status,
                "files_changed": report.files_changed,
                "tests_run": report.tests_run,
                "blockers": report.blockers,
                "next_recommended_action": report.next_recommended_action,
                "parse_error": report.parse_error,
            },
        }
        _print_json(payload)
        return 0 if accepted else 1

    if args.command == "changegate":
        contract = _load_contract_or_exit(args.contract)
        evidence: list[CommandEvidence] = []
        if args.evidence_file:
            evidence, load_errors = _load_evidence_file(args.evidence_file)
            if load_errors:
                # R3: input validation errors are machine-readable, never a traceback.
                _print_json({
                    "accepted": False,
                    "decision": "BLOCK",
                    "rejected_evidence": [],
                    "validation_errors": load_errors,
                    "error": "; ".join(load_errors),
                })
                return 1
        decision = evaluate_change_gate(ChangeGateInput(
            contract=contract,
            changed_files=list(args.changed_files),
            tests_run=list(args.tests_run),
            expected_commit_sha=args.expected_commit,
            test_evidence=evidence,
        ))
        out = decision.to_dict()
        out["accepted"] = decision.decision == "PASS"
        _print_json(out)
        # P0-9A-R2/R3 fail-closed exit semantics: only PASS is a success.
        return 0 if decision.decision == "PASS" else 1

    if args.command == "next-action":
        contract = _load_contract_or_exit(args.contract)
        implementer = None
        verifier = None
        if args.implementer_report:
            implementer = parse_agent_report(
                Path(args.implementer_report).read_text(encoding="utf-8")
            )
        if args.verifier_report:
            verifier = parse_agent_report(
                Path(args.verifier_report).read_text(encoding="utf-8")
            )
        action = recommend_next_action(contract, implementer, verifier, None, None)
        _print_json(action.to_dict())
        return 0

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

"""P0-9A — ChangeGate Lite: deterministic scope/evidence gate over a reported change.

Pure function over explicit inputs — the gate NEVER runs git or shell commands; the
caller supplies changed files and evidence.

P0-9A-R2 hardening:
- every changed path is canonicalized (backslashes normalized, "./" stripped) and any
  traversal/absolute/drive/control path is a BLOCK finding (``invalid_changed_path``);
- forbidden rules are checked BEFORE allowed rules and always win;
- normalized paths are deduplicated; an empty change set is REVIEW_REQUIRED;
- required evidence is satisfied ONLY by structured ``CommandEvidence`` that completed
  with exit code 0 at exactly the expected commit SHA — a bare command string in the
  legacy ``tests_run`` list is unverified and can never produce PASS.

Decision precedence: any ``block`` finding → BLOCK; else any ``warning`` →
REVIEW_REQUIRED; else PASS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import PurePosixPath

from agent_core.build_harness.contracts import TaskContract
from agent_core.build_harness.validation import (
    InvalidRepoPathError,
    normalize_repo_path,
)

DEPENDENCY_FILES = frozenset({
    "requirements.txt", "pyproject.toml", "poetry.lock",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
})


@dataclass(frozen=True)
class Finding:
    type: str
    severity: str  # info / warning / block
    file: str | None
    reason: str
    evidence: str | None = None


@dataclass(frozen=True)
class CommandEvidence:
    """Proof that one evidence command actually ran to completion at a known commit."""
    command: str
    exit_code: int
    completed: bool
    commit_sha: str
    evidence_id: str
    completed_at: str | None = None
    artifact_digest: str | None = None


@dataclass(frozen=True)
class ChangeGateInput:
    contract: TaskContract
    changed_files: list[str]
    tests_run: list[str] = field(default_factory=list)  # legacy display-only, unverified
    dependency_files_changed: list[str] = field(default_factory=list)
    expected_commit_sha: str = ""
    test_evidence: list[CommandEvidence] = field(default_factory=list)


@dataclass(frozen=True)
class ChangeGateDecision:
    decision: str  # PASS / REVIEW_REQUIRED / BLOCK
    findings: list[Finding]
    matched_required_evidence: list[str]
    missing_required_evidence: list[str]
    rejected_evidence: list[dict] = field(default_factory=list)
    expected_commit_sha: str = ""

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "findings": [vars(f) for f in self.findings],
            "matched_required_evidence": self.matched_required_evidence,
            "missing_required_evidence": self.missing_required_evidence,
            "rejected_evidence": self.rejected_evidence,
            "expected_commit_sha": self.expected_commit_sha,
        }


def _path_matches(file: str, pattern: str) -> bool:
    """fnmatch plus explicit ``dir/**`` prefix semantics (fnmatch has no ** notion)."""
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return file == prefix or file.startswith(prefix + "/")
    return fnmatch(file, pattern)


def _matches_any(file: str, patterns: list[str]) -> bool:
    return any(_path_matches(file, p) for p in patterns)


def _normalize_command(command: str) -> str:
    return " ".join(command.split())


def _evidence_verdict(
    ev: CommandEvidence, expected_commit_sha: str
) -> str | None:
    """None when the evidence is trustworthy, else the rejection reason."""
    if not ev.completed:
        return "evidence did not complete"
    if ev.exit_code != 0:
        return f"evidence exit_code={ev.exit_code} (must be 0)"
    if not ev.evidence_id or not ev.evidence_id.strip():
        return "evidence_id is empty"
    if not expected_commit_sha:
        return "expected_commit_sha is not set; commit-bound evidence cannot be verified"
    if ev.commit_sha != expected_commit_sha:
        return (
            f"commit_sha mismatch: evidence={ev.commit_sha!r} "
            f"expected={expected_commit_sha!r}"
        )
    return None


def evaluate_change_gate(gate_input: ChangeGateInput) -> ChangeGateDecision:
    contract = gate_input.contract
    findings: list[Finding] = []

    # 0. Canonicalize + validate every changed path; dedupe while preserving order.
    normalized_files: list[str] = []
    seen: set[str] = set()
    for raw in gate_input.changed_files:
        try:
            normalized = normalize_repo_path(raw)
        except InvalidRepoPathError as exc:
            findings.append(Finding(
                type="invalid_changed_path", severity="block", file=str(raw),
                reason=str(exc),
            ))
            continue
        if normalized not in seen:
            seen.add(normalized)
            normalized_files.append(normalized)

    if not gate_input.changed_files:
        findings.append(Finding(
            type="no_changed_files", severity="warning", file=None,
            reason="no changed files were reported for this task",
        ))

    # 1./2. Forbidden rules FIRST and they win; scope check only for non-forbidden files.
    for file in normalized_files:
        if _matches_any(file, contract.forbidden_paths):
            findings.append(Finding(
                type="forbidden_path", severity="block", file=file,
                reason=f"{file} matches a forbidden path pattern",
            ))
            continue
        if contract.allowed_paths and not contract.broad_scope_allowed:
            if not _matches_any(file, contract.allowed_paths):
                findings.append(Finding(
                    type="out_of_scope", severity="warning", file=file,
                    reason=f"{file} is outside the contract's allowed paths",
                ))

    # 3. Dependency files changed without explicit human approval.
    dependency_touched = list(gate_input.dependency_files_changed) + [
        f for f in normalized_files if PurePosixPath(f).name in DEPENDENCY_FILES
    ]
    if dependency_touched and "dependency_change" in contract.requires_human_approval_for:
        for file in sorted(set(dependency_touched)):
            findings.append(Finding(
                type="dependency_change", severity="warning", file=file,
                reason=f"{file} is a dependency file; contract requires human approval "
                       "for dependency changes",
            ))

    # 4./5. Required evidence: ONLY structured, completed, exit-0, commit-bound evidence
    # counts. Legacy tests_run strings are unverified and never satisfy a requirement.
    matched: list[str] = []
    missing: list[str] = []
    rejected: list[dict] = []
    for required in contract.required_evidence:
        required_norm = _normalize_command(required)
        satisfied = False
        for ev in gate_input.test_evidence:
            if _normalize_command(ev.command) != required_norm:
                continue
            reason = _evidence_verdict(ev, gate_input.expected_commit_sha)
            if reason is None:
                satisfied = True
                break
            rejected.append({
                "evidence_id": ev.evidence_id,
                "command": ev.command,
                "reason": reason,
            })
        if satisfied:
            matched.append(required)
        else:
            missing.append(required)
            legacy_hit = any(
                required in entry for entry in gate_input.tests_run
            )
            reason = f"required evidence not proven by structured evidence: {required}"
            if legacy_hit:
                reason += (
                    " (a matching legacy tests_run string exists but is unverified "
                    "and cannot satisfy evidence)"
                )
            findings.append(Finding(
                type="missing_evidence", severity="warning", file=None,
                reason=reason, evidence=required,
            ))
    if not gate_input.test_evidence and not contract.required_evidence:
        findings.append(Finding(
            type="no_evidence", severity="warning", file=None,
            reason="no structured evidence was provided for this change",
        ))

    if any(f.severity == "block" for f in findings):
        decision = "BLOCK"
    elif any(f.severity == "warning" for f in findings):
        decision = "REVIEW_REQUIRED"
    else:
        decision = "PASS"

    return ChangeGateDecision(
        decision=decision,
        findings=findings,
        matched_required_evidence=matched,
        missing_required_evidence=missing,
        rejected_evidence=rejected,
        expected_commit_sha=gate_input.expected_commit_sha,
    )

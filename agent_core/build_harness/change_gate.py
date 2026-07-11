"""P0-9A — ChangeGate Lite: deterministic scope/evidence gate over a reported change.

Pure function over explicit inputs — the gate NEVER runs git or shell commands; the
caller supplies changed files and test evidence. Decision precedence: any ``block``
finding → BLOCK; else any ``warning`` → REVIEW_REQUIRED; else PASS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import PurePosixPath

from agent_core.build_harness.contracts import TaskContract

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
class ChangeGateInput:
    contract: TaskContract
    changed_files: list[str]
    tests_run: list[str]
    dependency_files_changed: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChangeGateDecision:
    decision: str  # PASS / REVIEW_REQUIRED / BLOCK
    findings: list[Finding]
    matched_required_evidence: list[str]
    missing_required_evidence: list[str]

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "findings": [vars(f) for f in self.findings],
            "matched_required_evidence": self.matched_required_evidence,
            "missing_required_evidence": self.missing_required_evidence,
        }


def _path_matches(file: str, pattern: str) -> bool:
    """fnmatch plus explicit ``dir/**`` prefix semantics (fnmatch has no ** notion)."""
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return file == prefix or file.startswith(prefix + "/")
    return fnmatch(file, pattern)


def _matches_any(file: str, patterns: list[str]) -> bool:
    return any(_path_matches(file, p) for p in patterns)


def evaluate_change_gate(gate_input: ChangeGateInput) -> ChangeGateDecision:
    contract = gate_input.contract
    findings: list[Finding] = []

    # 1. Forbidden paths → BLOCK.
    for file in gate_input.changed_files:
        if _matches_any(file, contract.forbidden_paths):
            findings.append(Finding(
                type="forbidden_path", severity="block", file=file,
                reason=f"{file} matches a forbidden path pattern",
            ))

    # 2. Outside allowed scope → REVIEW_REQUIRED (unless broad scope was granted).
    if contract.allowed_paths and not contract.broad_scope_allowed:
        for file in gate_input.changed_files:
            if not _matches_any(file, contract.allowed_paths):
                findings.append(Finding(
                    type="out_of_scope", severity="warning", file=file,
                    reason=f"{file} is outside the contract's allowed paths",
                ))

    # 3. Dependency files changed without explicit human approval.
    dependency_touched = list(gate_input.dependency_files_changed) + [
        f for f in gate_input.changed_files
        if PurePosixPath(f).name in DEPENDENCY_FILES
    ]
    if dependency_touched and "dependency_change" in contract.requires_human_approval_for:
        for file in sorted(set(dependency_touched)):
            findings.append(Finding(
                type="dependency_change", severity="warning", file=file,
                reason=f"{file} is a dependency file; contract requires human approval "
                       "for dependency changes",
            ))

    # 4./5. Required evidence coverage (substring match against tests_run entries).
    matched: list[str] = []
    missing: list[str] = []
    for evidence in contract.required_evidence:
        if any(evidence in entry for entry in gate_input.tests_run):
            matched.append(evidence)
        else:
            missing.append(evidence)
            findings.append(Finding(
                type="missing_evidence", severity="warning", file=None,
                reason=f"required evidence not found in tests_run: {evidence}",
                evidence=evidence,
            ))
    if not gate_input.tests_run and not contract.required_evidence:
        findings.append(Finding(
            type="no_evidence", severity="warning", file=None,
            reason="no tests or evidence were provided for this change",
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
    )

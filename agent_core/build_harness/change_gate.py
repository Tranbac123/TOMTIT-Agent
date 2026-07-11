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
    is_valid_evidence_id,
    normalize_repo_path,
)

DEPENDENCY_FILES = frozenset({
    "requirements.txt", "pyproject.toml", "poetry.lock",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
})

# P0-9A-R4 — closed finding vocabulary. Exactly the finding types emitted by
# evaluate_change_gate(), each classified into exactly one bucket. The severity a producer
# assigns to a type is fixed by its bucket; a decision claiming otherwise (e.g. a
# forbidden_path relabeled "info") is internally inconsistent and cannot authorize release.
_VALID_SEVERITIES = frozenset({"info", "warning", "block"})

# Findings compatible with a PASS. The producer currently emits NONE — a genuine PASS has
# no findings. This set is intentionally empty (do not add fake info types).
INFO_FINDING_TYPES: frozenset[str] = frozenset()

# Findings that force REVIEW_REQUIRED (never PASS). Emitted at severity "warning".
REVIEW_FINDING_TYPES = frozenset({
    "no_changed_files", "out_of_scope", "dependency_change",
    "missing_evidence", "no_evidence",
})

# Findings that force BLOCK. Emitted at severity "block".
BLOCK_FINDING_TYPES = frozenset({
    "invalid_changed_path", "forbidden_path", "invalid_evidence", "duplicate_evidence_id",
})

# The single severity each known finding type is allowed to carry.
_EXPECTED_SEVERITY_BY_TYPE: dict[str, str] = {
    **{t: "info" for t in INFO_FINDING_TYPES},
    **{t: "warning" for t in REVIEW_FINDING_TYPES},
    **{t: "block" for t in BLOCK_FINDING_TYPES},
}
_CLASSIFIED_FINDING_TYPES = (
    INFO_FINDING_TYPES | REVIEW_FINDING_TYPES | BLOCK_FINDING_TYPES
)


class InvalidCommandEvidenceError(ValueError):
    """A CommandEvidence field failed strict type/value validation (no coercion)."""


class InvalidCommandEvidenceError(ValueError):
    """A CommandEvidence field failed strict type/value validation (no coercion)."""


@dataclass(frozen=True)
class Finding:
    type: str
    severity: str  # info / warning / block
    file: str | None
    reason: str
    evidence: str | None = None


def _command_evidence_error(obj: object) -> str | None:
    """Return a rejection reason if ``obj`` is not a well-formed evidence record, else None.

    Strict types with NO coercion: bool is not an int; "0"/"false" are not accepted.
    Used by both ``CommandEvidence.__post_init__`` (fail at construction) and the gate
    (defensive re-check so a bypass-constructed object can never crash or PASS).
    """
    command = getattr(obj, "command", None)
    if type(command) is not str or not command.strip():
        return f"command must be a non-empty string, got {command!r}"
    exit_code = getattr(obj, "exit_code", None)
    if type(exit_code) is not int:  # bool is a subclass — type() is exactly int only
        return f"exit_code must be an int (not bool/str/float), got {exit_code!r}"
    completed = getattr(obj, "completed", None)
    if type(completed) is not bool:
        return f"completed must be a bool, got {completed!r}"
    commit_sha = getattr(obj, "commit_sha", None)
    if type(commit_sha) is not str or not commit_sha.strip():
        return f"commit_sha must be a non-empty string, got {commit_sha!r}"
    evidence_id = getattr(obj, "evidence_id", None)
    if type(evidence_id) is not str or not evidence_id.strip():
        return f"evidence_id must be a non-empty string, got {evidence_id!r}"
    if not is_valid_evidence_id(evidence_id):
        return f"evidence_id {evidence_id!r} is not a valid identifier"
    for opt_name in ("completed_at", "artifact_digest"):
        opt = getattr(obj, opt_name, None)
        if opt is not None and (type(opt) is not str or not opt.strip()):
            return f"{opt_name} must be None or a non-empty string, got {opt!r}"
    return None


@dataclass(frozen=True)
class CommandEvidence:
    """Proof that one evidence command actually ran to completion at a known commit.

    Fields are validated strictly on construction (P0-9A-R3): no bool/str/float is
    coerced into exit_code/completed, and the evidence_id must be a real identifier.
    """
    command: str
    exit_code: int
    completed: bool
    commit_sha: str
    evidence_id: str
    completed_at: str | None = None
    artifact_digest: str | None = None

    def __post_init__(self) -> None:
        error = _command_evidence_error(self)
        if error is not None:
            raise InvalidCommandEvidenceError(error)


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

    # R4 pass 1 — reserve identities BEFORE body validation. Read evidence_id defensively
    # (do not trust the other fields); count it only when it is an exactly-valid identifier
    # string. This is done even when another field on the same record is malformed, so a
    # malformed record sharing a valid id with a good record is still seen as a duplicate.
    id_counts: dict[str, int] = {}
    for ev in gate_input.test_evidence:
        eid = getattr(ev, "evidence_id", None)
        if is_valid_evidence_id(eid):
            id_counts[eid] = id_counts.get(eid, 0) + 1
    # R4 pass 2 — any valid identity counted more than once is a duplicate.
    duplicate_ids = {eid for eid, count in id_counts.items() if count > 1}

    # R4 pass 3 — validate every record body (bypass-constructed malformed objects still
    # cannot crash or match). Malformed → invalid_evidence + rejected + excluded.
    usable_evidence: list[CommandEvidence] = []
    for index, ev in enumerate(gate_input.test_evidence):
        malformed = _command_evidence_error(ev)
        if malformed is not None:
            rejected.append({
                "evidence_id": getattr(ev, "evidence_id", f"<index {index}>"),
                "command": str(getattr(ev, "command", "<unknown>"))[:200],
                "reason": f"malformed evidence: {malformed}",
            })
            findings.append(Finding(
                type="invalid_evidence", severity="block", file=None,
                reason=f"malformed evidence at index {index}: {malformed}",
            ))
            continue
        usable_evidence.append(ev)

    # R4: emit a duplicate finding for every ambiguous identity (counted in pass 1, so it
    # fires even if one of the sharing records was later rejected as malformed).
    for eid in sorted(duplicate_ids):
        findings.append(Finding(
            type="duplicate_evidence_id", severity="block", file=None,
            reason=f"evidence_id {eid!r} appears {id_counts[eid]} times; evidence "
                   "identity is ambiguous",
            evidence=eid,
        ))
        rejected.append({
            "evidence_id": eid, "command": "<multiple>",
            "reason": f"duplicate evidence_id used {id_counts[eid]} times",
        })

    # R4 pass 4 — matching. Exclude any record whose valid id is duplicated.
    for required in contract.required_evidence:
        required_norm = _normalize_command(required)
        satisfied = False
        for ev in usable_evidence:
            if ev.evidence_id in duplicate_ids:
                continue  # ambiguous identity can never satisfy a requirement
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


def _finding_shape_error(finding: object) -> str | None:
    """P0-9A-R4: None if ``finding`` is a well-formed Finding-shaped object, else why not.

    Defensive: never trusts the entry to be a real Finding. type/severity/reason are
    non-empty exact strings; file/evidence are str or None; severity is an allowed value.
    """
    ftype = getattr(finding, "type", "__missing__")
    if type(ftype) is not str or not ftype.strip():
        return f"finding.type must be a non-empty string, got {ftype!r}"
    severity = getattr(finding, "severity", "__missing__")
    if type(severity) is not str or severity not in _VALID_SEVERITIES:
        return f"finding.severity must be one of {sorted(_VALID_SEVERITIES)}, got {severity!r}"
    reason = getattr(finding, "reason", "__missing__")
    if type(reason) is not str or not reason.strip():
        return f"finding.reason must be a non-empty string, got {reason!r}"
    file = getattr(finding, "file", None)
    if file is not None and type(file) is not str:
        return f"finding.file must be a string or None, got {file!r}"
    evidence = getattr(finding, "evidence", None)
    if evidence is not None and type(evidence) is not str:
        return f"finding.evidence must be a string or None, got {evidence!r}"
    return None


def validate_change_gate_decision(
    contract: TaskContract, decision: object
) -> list[str]:
    """Independently verify a PASS ChangeGateDecision is internally consistent (R3/R4).

    A hand-constructed decision marked ``PASS`` must not authorize release unless it is
    exactly what a genuine PASS from ``evaluate_change_gate`` looks like: every required
    evidence item matched, nothing missing, and NO finding that is not an explicitly
    allowed informational finding. Because the producer emits no informational findings,
    a real PASS has an empty findings list. Any warning/block finding, any known non-PASS
    finding type relabeled ``info``, any unknown type, any unknown severity, and any
    malformed finding object all invalidate the PASS. Returns a list of integrity errors
    (empty ⇒ the decision may be trusted).
    """
    errors: list[str] = []

    dec = getattr(decision, "decision", None)
    if dec not in ("PASS", "REVIEW_REQUIRED", "BLOCK"):
        return [f"unknown decision value {dec!r}"]
    if dec != "PASS":
        return [f"decision is {dec}, not PASS"]

    findings = getattr(decision, "findings", None)
    matched = getattr(decision, "matched_required_evidence", None)
    missing = getattr(decision, "missing_required_evidence", None)

    # Collection type sanity — malformed shapes fail closed.
    if not isinstance(findings, list):
        errors.append(f"findings is not a list: {findings!r}")
        findings = []
    if not isinstance(matched, list):
        errors.append("matched_required_evidence is not a list")
        matched = []
    if not isinstance(missing, list):
        errors.append("missing_required_evidence is not a list")
        missing = ["<unknown>"]

    # Every required evidence item must be covered; nothing may be missing.
    if missing:
        errors.append(f"missing_required_evidence is non-empty: {missing}")
    for required in contract.required_evidence:
        if required not in matched:
            errors.append(f"required evidence not in matched set: {required}")
    if contract.required_evidence and not matched:
        errors.append("contract has required evidence but matched set is empty")

    # The fundamental PASS finding rule (R4): every finding must be a well-formed,
    # info-severity, explicitly-allowed informational finding — otherwise PASS is invalid.
    for finding in findings:
        shape_error = _finding_shape_error(finding)
        if shape_error is not None:
            errors.append(f"malformed finding in PASS decision: {shape_error}")
            continue
        ftype = finding.type
        severity = finding.severity
        if severity == "block":
            errors.append(f"PASS decision contains a block-severity finding: {ftype!r}")
            continue
        if severity == "warning":
            errors.append(f"PASS decision contains a warning-severity finding: {ftype!r}")
            continue
        # severity == "info": only explicitly-allowed informational types may pass.
        if ftype not in INFO_FINDING_TYPES:
            if ftype in BLOCK_FINDING_TYPES:
                errors.append(
                    f"PASS decision contains a block finding type relabeled 'info': {ftype!r}"
                )
            elif ftype in REVIEW_FINDING_TYPES:
                errors.append(
                    f"PASS decision contains a review finding type relabeled 'info': {ftype!r}"
                )
            else:
                errors.append(
                    f"PASS decision contains an unknown finding type at 'info': {ftype!r}"
                )
        elif _EXPECTED_SEVERITY_BY_TYPE.get(ftype) != severity:
            errors.append(
                f"finding {ftype!r} has severity {severity!r} inconsistent with its "
                f"classification ({_EXPECTED_SEVERITY_BY_TYPE.get(ftype)!r})"
            )

    return errors


def producer_finding_types() -> frozenset[str]:
    """The exact finding types evaluate_change_gate() can emit (for classification tests)."""
    return frozenset({
        "invalid_changed_path", "no_changed_files", "forbidden_path", "out_of_scope",
        "dependency_change", "invalid_evidence", "duplicate_evidence_id",
        "missing_evidence", "no_evidence",
    })

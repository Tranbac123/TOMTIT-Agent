"""P0-9B1-R3 - dirty rejected-context exclusivity (R2-SOL-001).

A non-context rejected result may carry a candidate+snapshot pair ONLY when no primary context
status applies. A coherent-but-DIRTY snapshot has primary status DIRTY_WORKTREE, so every
non-context status must reject it. Primary-context precedence itself is unchanged.
"""
from __future__ import annotations

import pytest

from agent_core.build_harness.canonical import changed_files_digest
from agent_core.build_harness.repository_models import (
    CandidateBinding,
    GitObjectFormat,
    RepositorySnapshot,
    VerificationStatus,
)
from agent_core.build_harness.provenance import (
    EvidenceVerificationBundle,
    EvidenceVerificationResult,
    VerifiedCommandEvidence,
    expected_context_mismatch_status,
)

D = "sha256:" + "a" * 64
D2 = "sha256:" + "b" * 64
SA, SB, SC, SD, SE = "a" * 40, "b" * 40, "c" * 40, "d" * 40, "e" * 40
H256_A, H256_B, H256_C = "1" * 64, "2" * 64, "3" * 64
TS0 = "2026-07-11T00:00:00.000000Z"
CH = ("src/a.py", "src/b.py")

NON_CONTEXT_STATUSES = [
    VerificationStatus.COMMAND_MISMATCH,
    VerificationStatus.EXECUTION_FAILED,
    VerificationStatus.DUPLICATE_IDENTITY,
    VerificationStatus.INVALID_PROVENANCE,
    VerificationStatus.UNSUPPORTED_SCHEMA,
    VerificationStatus.UNSUPPORTED_COLLECTOR,
    VerificationStatus.INSPECTION_FAILED,
]


def _snapshot(commit=SA, tree=SB, base=SC, repository_id=D, changed=CH,
              object_format=GitObjectFormat.SHA1, release_clean=True, snapshot_id="snap-1"):
    return RepositorySnapshot(
        schema_version="p0-9b.repository-snapshot.v1", snapshot_id=snapshot_id,
        repository_id=repository_id, repository_root_hint="/repo", object_format=object_format,
        head_commit_sha=commit, head_tree_sha=tree, base_commit_sha=base, branch_name="main",
        detached_head=False, staged_changes=() if release_clean else ("wip.py",),
        unstaged_changes=(), untracked_files=(), submodule_changes=(),
        changed_files=tuple(changed), changed_files_digest=changed_files_digest(tuple(changed)),
        is_release_clean=release_clean, captured_at=TS0, inspector_version="i-1")


def _snapshot256(**kw):
    return _snapshot(object_format=GitObjectFormat.SHA256, commit=H256_A, tree=H256_B,
                     base=H256_C, **kw)


def _candidate(commit=SA, tree=SB, base=SC, repository_id=D, changed=CH):
    return CandidateBinding(
        schema_version="p0-9b.candidate-binding.v1", repository_id=repository_id,
        object_format=GitObjectFormat.SHA1, base_commit_sha=base, candidate_commit_sha=commit,
        candidate_tree_sha=tree, contract_digest=D2,
        changed_files_digest=changed_files_digest(tuple(changed)))


def _result(status, candidate=None, snapshot=None, accepted=False, evidence_id="ev-1",
            task_id="BH-P0-B", matched=None, reason_codes=("X",)):
    return EvidenceVerificationResult(
        schema_version="p0-9b.verification.v1", accepted=accepted, status=status,
        reason_codes=reason_codes, evidence_id=evidence_id, run_id="run-1", task_id=task_id,
        candidate_binding=candidate, repository_snapshot=snapshot,
        matched_requirement_id=matched, claim_digest=D, verified_at=TS0,
        verifier_version="verifier-1", warnings=(), errors=())


def _verified(evidence_id="ev-1", candidate=None):
    c = candidate or _candidate()
    return VerifiedCommandEvidence(
        schema_version="p0-9b.verified-evidence.v1", evidence_id=evidence_id, run_id="run-1",
        task_id="BH-P0-B", requirement_id="req-1", candidate_binding=c,
        verification_digest=VerifiedCommandEvidence.compute_verification_digest(
            evidence_id, "run-1", "BH-P0-B", "req-1", c))


def _bundle(verified=None, rejected=(), candidate=None, task_id="BH-P0-B"):
    c = candidate or _candidate()
    verified = (_verified(candidate=c),) if verified is None else verified
    snap = _snapshot()
    return EvidenceVerificationBundle(
        schema_version="p0-9b.verification-bundle.v1", task_id=task_id, candidate_binding=c,
        verified=tuple(verified), rejected=tuple(rejected), verified_at_snapshot=snap,
        bundle_digest=EvidenceVerificationBundle.compute_bundle_digest(
            task_id, c, tuple(verified), tuple(rejected), snap))


# ---------------------------------------------------------------------------
# 1. Baseline blocker
# ---------------------------------------------------------------------------

def test_command_mismatch_with_coherent_dirty_snapshot_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(VerificationStatus.COMMAND_MISMATCH, _candidate(),
                _snapshot(release_clean=False))


# ---------------------------------------------------------------------------
# 2-6. Every non-context status: context shapes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", NON_CONTEXT_STATUSES)
def test_non_context_coherent_dirty_rejected(status):
    with pytest.raises(Exception):  # noqa: B017
        _result(status, _candidate(), _snapshot(release_clean=False))


@pytest.mark.parametrize("status", NON_CONTEXT_STATUSES)
def test_non_context_coherent_clean_passes(status):
    assert _result(status, _candidate(), _snapshot(release_clean=True)).status is status


@pytest.mark.parametrize("status", NON_CONTEXT_STATUSES)
def test_non_context_candidate_only_passes(status):
    assert _result(status, _candidate(), None).status is status


@pytest.mark.parametrize("status", NON_CONTEXT_STATUSES)
def test_non_context_both_absent_passes(status):
    assert _result(status, None, None).status is status


@pytest.mark.parametrize("status", NON_CONTEXT_STATUSES)
def test_non_context_snapshot_only_rejected(status):
    with pytest.raises(Exception):  # noqa: B017
        _result(status, None, _snapshot())


# ---------------------------------------------------------------------------
# 7-12. Every non-context status rejects every higher-precedence context
# ---------------------------------------------------------------------------

_HIGHER_PRECEDENCE_CONTEXTS = {
    "repository": (_candidate(), _snapshot(repository_id=D2)),
    "object_format": (_candidate(), _snapshot256()),
    "base_commit": (_candidate(base=SC), _snapshot(base=SD)),
    "commit": (_candidate(commit=SA), _snapshot(commit=SD)),
    "tree": (_candidate(tree=SB), _snapshot(tree=SD)),
    "changed_files": (_candidate(changed=CH), _snapshot(changed=("src/a.py",))),
}


@pytest.mark.parametrize("status", NON_CONTEXT_STATUSES)
@pytest.mark.parametrize("dimension", sorted(_HIGHER_PRECEDENCE_CONTEXTS))
def test_non_context_rejects_every_higher_precedence_context(status, dimension):
    candidate, snapshot = _HIGHER_PRECEDENCE_CONTEXTS[dimension]
    with pytest.raises(Exception):  # noqa: B017
        _result(status, candidate, snapshot)


# ---------------------------------------------------------------------------
# 13-21. Primary-context precedence controls (unchanged behavior)
# ---------------------------------------------------------------------------

def test_truthful_dirty_worktree_passes():
    r = _result(VerificationStatus.DIRTY_WORKTREE, _candidate(), _snapshot(release_clean=False))
    assert r.status is VerificationStatus.DIRTY_WORKTREE


def test_dirty_worktree_with_clean_snapshot_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(VerificationStatus.DIRTY_WORKTREE, _candidate(), _snapshot(release_clean=True))


def test_dirty_worktree_with_repository_mismatch_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(VerificationStatus.DIRTY_WORKTREE, _candidate(),
                _snapshot(repository_id=D2, release_clean=False))


def test_dirty_worktree_with_commit_mismatch_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(VerificationStatus.DIRTY_WORKTREE, _candidate(commit=SA),
                _snapshot(commit=SD, release_clean=False))


@pytest.mark.parametrize("candidate,snapshot,expected", [
    # a dirty snapshot never outranks a real binding mismatch
    (_candidate(changed=CH), _snapshot(changed=("src/a.py",), release_clean=False),
     VerificationStatus.SNAPSHOT_CHANGED),
    (_candidate(tree=SB), _snapshot(tree=SD, release_clean=False),
     VerificationStatus.TREE_MISMATCH),
    (_candidate(commit=SA), _snapshot(commit=SD, release_clean=False),
     VerificationStatus.COMMIT_MISMATCH),
    (_candidate(base=SC), _snapshot(base=SD, release_clean=False),
     VerificationStatus.STALE),
    (_candidate(), _snapshot256(release_clean=False),
     VerificationStatus.STALE),
    (_candidate(), _snapshot(repository_id=D2, release_clean=False),
     VerificationStatus.REPOSITORY_MISMATCH),
])
def test_dirty_snapshot_does_not_outrank_primary_context(candidate, snapshot, expected):
    assert expected_context_mismatch_status(candidate, snapshot) is expected
    # the truthful primary status constructs...
    assert _result(expected, candidate, snapshot).status is expected
    # ...and DIRTY_WORKTREE does not.
    with pytest.raises(Exception):  # noqa: B017
        _result(VerificationStatus.DIRTY_WORKTREE, candidate, snapshot)


# ---------------------------------------------------------------------------
# 22-23. Accepted behavior unchanged
# ---------------------------------------------------------------------------

def test_accepted_verified_remains_valid():
    r = _result(VerificationStatus.VERIFIED, _candidate(), _snapshot(), accepted=True,
                matched="req-1", reason_codes=("OK",))
    assert r.accepted and r.matched_requirement_id == "req-1"


def test_accepted_verified_with_dirty_snapshot_unchanged_policy():
    # R3 adds NO new accepted-result policy: a dirty but binding-coherent snapshot is still
    # accepted for VERIFIED exactly as in P0-9B1 (accepted validation is untouched).
    r = _result(VerificationStatus.VERIFIED, _candidate(), _snapshot(release_clean=False),
                accepted=True, matched="req-1", reason_codes=("OK",))
    assert r.accepted


# ---------------------------------------------------------------------------
# 24-27. Bundle controls
# ---------------------------------------------------------------------------

def test_bundle_rejects_non_context_dirty_rejected_result():
    # the dirty non-context result cannot even be constructed, so it can never reach a bundle
    with pytest.raises(Exception):  # noqa: B017
        _result(VerificationStatus.COMMAND_MISMATCH, _candidate(),
                _snapshot(release_clean=False), evidence_id="ev-9")


def test_bundle_accepts_truthful_dirty_worktree():
    cand = _candidate()
    rej = _result(VerificationStatus.DIRTY_WORKTREE, cand, _snapshot(release_clean=False),
                  evidence_id="ev-9")
    b = _bundle(verified=(), rejected=(rej,), candidate=cand)
    assert b.rejected[0].status is VerificationStatus.DIRTY_WORKTREE


def test_bundle_accepts_clean_coherent_non_context_result():
    cand = _candidate()
    rej = _result(VerificationStatus.COMMAND_MISMATCH, cand, _snapshot(), evidence_id="ev-9")
    b = _bundle(verified=(), rejected=(rej,), candidate=cand)
    assert b.rejected[0].status is VerificationStatus.COMMAND_MISMATCH


def test_bundle_foreign_expected_candidate_still_rejected():
    foreign = _candidate(commit=SD, tree=SE)
    rej = _result(VerificationStatus.COMMAND_MISMATCH, foreign, None, evidence_id="ev-9")
    with pytest.raises(Exception):  # noqa: B017
        _bundle(rejected=(rej,))

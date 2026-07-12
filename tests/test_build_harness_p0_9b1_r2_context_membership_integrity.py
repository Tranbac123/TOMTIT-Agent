"""P0-9B1-R2 - context and membership integrity (R1-SOL-001/002/003).

Adversarial + control tests for: exact executable-environment tuples with a fresh canonical
copy; the exclusive rejected-context status matrix; and run-record bundle membership. No git,
subprocess, clock, or filesystem is used.
"""
from __future__ import annotations

import pytest

from agent_core.build_harness.canonical import canonical_digest, changed_files_digest
from agent_core.build_harness.repository_models import (
    CandidateBinding,
    DirtyState,
    EvidenceSource,
    GitObjectFormat,
    RepositorySnapshot,
    VerificationStatus,
    command_requirement_payload,
)
from agent_core.build_harness.provenance import (
    CollectedCommandEvidence,
    EvidenceProvenance,
    EvidenceVerificationBundle,
    EvidenceVerificationResult,
    VerifiedCommandEvidence,
    expected_context_mismatch_status,
)
from agent_core.build_harness.ports import (
    CommandExecutionSpec,
    EvidenceRunRecord,
)

D = "sha256:" + "a" * 64
D2 = "sha256:" + "b" * 64
SA, SB, SC, SD, SE = "a" * 40, "b" * 40, "c" * 40, "d" * 40, "e" * 40
H256_A, H256_B, H256_C = "1" * 64, "2" * 64, "3" * 64
TS0, TS1 = "2026-07-11T00:00:00.000000Z", "2026-07-11T00:00:01.500000Z"
CHANGED = ("src/a.py", "src/b.py")


# ---------------------------------------------------------------------------
# factories
# ---------------------------------------------------------------------------

def _snapshot(commit=SA, tree=SB, base=SC, repository_id=D, changed=CHANGED,
              object_format=GitObjectFormat.SHA1, release_clean=True, **kw):
    dirty = {} if release_clean else dict(staged_changes=("wip.py",))
    fields = dict(
        schema_version="p0-9b.repository-snapshot.v1", snapshot_id="snap-1",
        repository_id=repository_id, repository_root_hint="/repo", object_format=object_format,
        head_commit_sha=commit, head_tree_sha=tree, base_commit_sha=base,
        branch_name="main", detached_head=False,
        staged_changes=(), unstaged_changes=(), untracked_files=(), submodule_changes=(),
        changed_files=tuple(changed), changed_files_digest=changed_files_digest(tuple(changed)),
        is_release_clean=release_clean, captured_at=TS0, inspector_version="i-1",
    )
    fields.update(dirty)
    fields.update(kw)
    return RepositorySnapshot(**fields)


def _snapshot256(**kw):
    return _snapshot(object_format=GitObjectFormat.SHA256, commit=H256_A, tree=H256_B,
                     base=H256_C, **kw)


def _candidate(commit=SA, tree=SB, base=SC, repository_id=D, changed=CHANGED):
    return CandidateBinding(
        schema_version="p0-9b.candidate-binding.v1", repository_id=repository_id,
        object_format=GitObjectFormat.SHA1, base_commit_sha=base,
        candidate_commit_sha=commit, candidate_tree_sha=tree, contract_digest=D2,
        changed_files_digest=changed_files_digest(tuple(changed)),
    )


def _provenance(evidence_id="ev-1", run_id="run-1", task_id="BH-P0-B", **kw):
    fields = dict(
        schema_version="p0-9b.provenance.v1", evidence_id=evidence_id, task_id=task_id,
        run_id=run_id, collector_id="collector-1", collector_version="1.0",
        requirement_id="req-1", argv=("pytest",), working_directory=".",
        command_digest=canonical_digest(command_requirement_payload(("pytest",), ".", 600)),
        exit_code=0, completed=True, started_at=TS0, completed_at=TS1, duration_ms=1500,
        repository_id=D, object_format=GitObjectFormat.SHA1, base_commit_sha=SC,
        commit_sha=SA, tree_sha=SB, pre_snapshot_id="snap-pre", post_snapshot_id="snap-post",
        dirty_state=DirtyState.CLEAN, changed_files_digest=D, stdout_digest=D,
        stderr_digest=D2, artifact_digest=None, source=EvidenceSource.LOCAL_CONTROLLED_COLLECTOR,
    )
    fields.update(kw)
    return EvidenceProvenance(**fields)


def _collected(evidence_id="ev-1", run_id="run-1", task_id="BH-P0-B"):
    p = _provenance(evidence_id=evidence_id, run_id=run_id, task_id=task_id)
    pre = _snapshot(snapshot_id=p.pre_snapshot_id)
    post = _snapshot(snapshot_id=p.post_snapshot_id)
    return CollectedCommandEvidence(schema_version="p0-9b.collected-evidence.v1",
                                    provenance=p, pre_snapshot=pre, post_snapshot=post)


def _verified(evidence_id="ev-1", req_id="req-1", run_id="run-1", task_id="BH-P0-B", candidate=None):
    c = candidate or _candidate()
    return VerifiedCommandEvidence(
        schema_version="p0-9b.verified-evidence.v1", evidence_id=evidence_id, run_id=run_id,
        task_id=task_id, requirement_id=req_id, candidate_binding=c,
        verification_digest=VerifiedCommandEvidence.compute_verification_digest(
            evidence_id, run_id, task_id, req_id, c),
    )


def _result(accepted=False, status=VerificationStatus.COMMAND_MISMATCH, candidate=None,
            snapshot=None, evidence_id="ev-1", run_id="run-1", task_id="BH-P0-B",
            matched="__auto__", reason_codes=("X",)):
    if matched == "__auto__":
        matched = "req-1" if accepted else None
    return EvidenceVerificationResult(
        schema_version="p0-9b.verification.v1", accepted=accepted, status=status,
        reason_codes=reason_codes, evidence_id=evidence_id, run_id=run_id, task_id=task_id,
        candidate_binding=candidate, repository_snapshot=snapshot, matched_requirement_id=matched,
        claim_digest=D, verified_at=TS0, verifier_version="verifier-1", warnings=(), errors=(),
    )


def _bundle(task_id="BH-P0-B", verified=None, rejected=(), candidate=None, snapshot=None):
    c = candidate or _candidate()
    verified = (_verified(candidate=c),) if verified is None else verified
    snap = snapshot or _snapshot()
    return EvidenceVerificationBundle(
        schema_version="p0-9b.verification-bundle.v1", task_id=task_id, candidate_binding=c,
        verified=tuple(verified), rejected=tuple(rejected), verified_at_snapshot=snap,
        bundle_digest=EvidenceVerificationBundle.compute_bundle_digest(
            task_id, c, tuple(verified), tuple(rejected), snap),
    )


def _run_record(task_id="BH-P0-B", run_id="run-1", candidate=None, collected=None,
                final_snapshot=None, bundle="default"):
    c = candidate or _candidate()
    collected = (_collected(),) if collected is None else collected
    final = final_snapshot or _snapshot()
    if bundle == "default":
        bundle = _bundle(task_id=task_id, candidate=c)
    return EvidenceRunRecord(
        schema_version="p0-9b.evidence-run-record.v1", task_id=task_id, run_id=run_id,
        candidate_binding=c, collected_evidence=tuple(collected), final_snapshot=final,
        verification_bundle=bundle)


def _spec(environment):
    return CommandExecutionSpec(
        argv=("pytest",), repository_root="/repo", working_directory=".",
        timeout_seconds=60, max_stdout_bytes=1024, max_stderr_bytes=1024,
        environment=environment)


# subclasses used to prove exact-type rejection happens before custom behavior runs
class _ChangingOuter(tuple):
    iter_calls = 0

    def __iter__(self):
        type(self).iter_calls += 1
        # would expose different content on the second pass if ever iterated
        return iter((("A", "1"),) if type(self).iter_calls == 1 else (("EVIL", "2"),))


class _WeirdPair(tuple):
    len_calls = 0

    def __len__(self):
        type(self).len_calls += 1
        return 2

    def __iter__(self):
        type(self).len_calls += 1
        return super().__iter__()


class _EvilStr(str):
    pass


# ---------------------------------------------------------------------------
# R1-SOL-001 - environment exactness and copying (1-13)
# ---------------------------------------------------------------------------

def test_env_outer_tuple_subclass_rejected_before_iteration():
    _ChangingOuter.iter_calls = 0
    with pytest.raises(Exception):  # noqa: B017 - construction must not succeed
        _spec(_ChangingOuter([("A", "1")]))
    assert _ChangingOuter.iter_calls == 0


def test_env_pair_tuple_subclass_rejected_before_sequence_ops():
    _WeirdPair.len_calls = 0
    with pytest.raises(Exception):  # noqa: B017
        _spec((_WeirdPair(("A", "1")),))
    assert _WeirdPair.len_calls == 0


def test_env_string_subclass_key_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _spec(((_EvilStr("A"), "1"),))


def test_env_string_subclass_value_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _spec(((_EvilStr("A"), _EvilStr("1")),))


def test_env_valid_stored_outer_is_exact_tuple():
    s = _spec((("A", "1"), ("B", "2")))
    assert type(s.environment) is tuple


def test_env_valid_stored_outer_is_fresh_object():
    caller = (("A", "1"),)
    s = _spec(caller)
    assert s.environment is not caller


def test_env_stored_pairs_are_exact_tuples():
    s = _spec((("A", "1"), ("B", "2")))
    assert all(type(pair) is tuple for pair in s.environment)


def test_env_stored_pairs_are_fresh_objects():
    p0, p1 = ("A", "1"), ("B", "2")
    s = _spec((p0, p1))
    assert s.environment[0] is not p0 and s.environment[1] is not p1


def test_env_repeated_observation_is_stable():
    s = _spec((("A", "1"), ("B", "2")))
    assert tuple(s.environment) == tuple(s.environment) == (("A", "1"), ("B", "2"))


def test_env_repeated_serialization_is_stable():
    s = _spec((("A", "1"),))
    assert canonical_digest(list(map(list, s.environment))) == \
        canonical_digest(list(map(list, s.environment)))


def test_env_duplicate_key_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _spec((("A", "1"), ("A", "2")))


def test_env_unsorted_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _spec((("B", "2"), ("A", "1")))


def test_env_empty_environment_ok():
    s = _spec(())
    assert s.environment == () and type(s.environment) is tuple


# ---------------------------------------------------------------------------
# R1-SOL-002 - rejected-context presence (14-19)
# ---------------------------------------------------------------------------

def test_rejected_snapshot_without_candidate_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.COMMAND_MISMATCH, candidate=None, snapshot=_snapshot())


def test_rejected_candidate_only_non_context_ok():
    r = _result(status=VerificationStatus.COMMAND_MISMATCH, candidate=_candidate(), snapshot=None)
    assert r.status is VerificationStatus.COMMAND_MISMATCH


def test_rejected_candidate_only_context_status_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.STALE, candidate=_candidate(), snapshot=None)


def test_rejected_both_absent_non_context_ok():
    r = _result(status=VerificationStatus.EXECUTION_FAILED, candidate=None, snapshot=None)
    assert not r.accepted


def test_rejected_both_absent_context_status_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.REPOSITORY_MISMATCH, candidate=None, snapshot=None)


def test_accepted_verified_unchanged():
    r = _result(accepted=True, status=VerificationStatus.VERIFIED, candidate=_candidate(),
                snapshot=_snapshot(), reason_codes=("OK",))
    assert r.accepted and r.matched_requirement_id == "req-1"


# ---------------------------------------------------------------------------
# Repository mismatch (20-22)
# ---------------------------------------------------------------------------

def test_repository_mismatch_coherent_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.REPOSITORY_MISMATCH,
                candidate=_candidate(repository_id=D), snapshot=_snapshot(repository_id=D))


def test_repository_mismatch_truthful_ok():
    r = _result(status=VerificationStatus.REPOSITORY_MISMATCH,
                candidate=_candidate(repository_id=D), snapshot=_snapshot(repository_id=D2))
    assert r.status is VerificationStatus.REPOSITORY_MISMATCH


def test_repository_difference_forbids_lower_status():
    # repo differs but status claims COMMIT_MISMATCH -> precedence selects REPOSITORY_MISMATCH
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.COMMIT_MISMATCH,
                candidate=_candidate(repository_id=D), snapshot=_snapshot(repository_id=D2))


# ---------------------------------------------------------------------------
# STALE exclusivity (23-29)
# ---------------------------------------------------------------------------

def test_stale_object_format_mismatch_ok():
    r = _result(status=VerificationStatus.STALE, candidate=_candidate(), snapshot=_snapshot256())
    assert r.status is VerificationStatus.STALE


def test_stale_base_mismatch_ok():
    r = _result(status=VerificationStatus.STALE, candidate=_candidate(base=SC),
                snapshot=_snapshot(base=SD))
    assert r.status is VerificationStatus.STALE


def test_stale_with_repository_mismatch_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.STALE, candidate=_candidate(repository_id=D),
                snapshot=_snapshot(repository_id=D2, base=SD))


def test_stale_with_only_commit_mismatch_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.STALE, candidate=_candidate(commit=SA),
                snapshot=_snapshot(commit=SD))


def test_stale_with_only_tree_mismatch_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.STALE, candidate=_candidate(tree=SB),
                snapshot=_snapshot(tree=SD))


def test_stale_with_only_changed_files_mismatch_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.STALE, candidate=_candidate(changed=CHANGED),
                snapshot=_snapshot(changed=("src/a.py",)))


def test_stale_with_coherent_context_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.STALE, candidate=_candidate(), snapshot=_snapshot())


# ---------------------------------------------------------------------------
# Commit mismatch (30-33)
# ---------------------------------------------------------------------------

def test_commit_mismatch_truthful_ok():
    r = _result(status=VerificationStatus.COMMIT_MISMATCH, candidate=_candidate(commit=SA),
                snapshot=_snapshot(commit=SD))
    assert r.status is VerificationStatus.COMMIT_MISMATCH


def test_commit_mismatch_with_matching_commit_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.COMMIT_MISMATCH, candidate=_candidate(),
                snapshot=_snapshot())


def test_commit_mismatch_with_object_format_mismatch_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.COMMIT_MISMATCH, candidate=_candidate(),
                snapshot=_snapshot256())


def test_commit_mismatch_with_base_mismatch_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.COMMIT_MISMATCH, candidate=_candidate(base=SC),
                snapshot=_snapshot(base=SD, commit=SD))


# ---------------------------------------------------------------------------
# Tree mismatch (34-36)
# ---------------------------------------------------------------------------

def test_tree_mismatch_truthful_ok():
    r = _result(status=VerificationStatus.TREE_MISMATCH, candidate=_candidate(commit=SA, tree=SB),
                snapshot=_snapshot(commit=SA, tree=SD))
    assert r.status is VerificationStatus.TREE_MISMATCH


def test_tree_mismatch_with_matching_tree_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.TREE_MISMATCH, candidate=_candidate(),
                snapshot=_snapshot())


def test_tree_mismatch_with_commit_mismatch_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.TREE_MISMATCH, candidate=_candidate(commit=SA),
                snapshot=_snapshot(commit=SD, tree=SD))


# ---------------------------------------------------------------------------
# Snapshot changed (37-39)
# ---------------------------------------------------------------------------

def test_snapshot_changed_truthful_ok():
    r = _result(status=VerificationStatus.SNAPSHOT_CHANGED, candidate=_candidate(changed=CHANGED),
                snapshot=_snapshot(changed=("src/a.py",)))
    assert r.status is VerificationStatus.SNAPSHOT_CHANGED


def test_snapshot_changed_with_matching_digest_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.SNAPSHOT_CHANGED, candidate=_candidate(),
                snapshot=_snapshot())


def test_snapshot_changed_with_tree_mismatch_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.SNAPSHOT_CHANGED, candidate=_candidate(tree=SB),
                snapshot=_snapshot(tree=SD, changed=("src/a.py",)))


# ---------------------------------------------------------------------------
# Dirty worktree (40-42)
# ---------------------------------------------------------------------------

def test_dirty_worktree_coherent_ok():
    r = _result(status=VerificationStatus.DIRTY_WORKTREE, candidate=_candidate(),
                snapshot=_snapshot(release_clean=False))
    assert r.status is VerificationStatus.DIRTY_WORKTREE


def test_dirty_worktree_clean_snapshot_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.DIRTY_WORKTREE, candidate=_candidate(),
                snapshot=_snapshot(release_clean=True))


def test_dirty_worktree_with_binding_mismatch_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.DIRTY_WORKTREE, candidate=_candidate(commit=SA),
                snapshot=_snapshot(commit=SD, release_clean=False))


# ---------------------------------------------------------------------------
# Non-context rejection (43-48)
# ---------------------------------------------------------------------------

def test_command_mismatch_no_context_ok():
    assert not _result(status=VerificationStatus.COMMAND_MISMATCH).accepted


def test_command_mismatch_candidate_only_ok():
    r = _result(status=VerificationStatus.COMMAND_MISMATCH, candidate=_candidate())
    assert r.candidate_binding is not None


def test_command_mismatch_coherent_context_ok():
    r = _result(status=VerificationStatus.COMMAND_MISMATCH, candidate=_candidate(),
                snapshot=_snapshot())
    assert r.repository_snapshot is not None


def test_command_mismatch_foreign_repository_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.COMMAND_MISMATCH, candidate=_candidate(repository_id=D),
                snapshot=_snapshot(repository_id=D2))


def test_execution_failed_coherent_context_ok():
    r = _result(status=VerificationStatus.EXECUTION_FAILED, candidate=_candidate(),
                snapshot=_snapshot())
    assert r.status is VerificationStatus.EXECUTION_FAILED


def test_non_context_with_changed_files_mismatch_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.INVALID_PROVENANCE, candidate=_candidate(changed=CHANGED),
                snapshot=_snapshot(changed=("src/a.py",)))


# ---------------------------------------------------------------------------
# Bundle rejected-context handling (49-53)
# ---------------------------------------------------------------------------

def test_bundle_foreign_rejected_candidate_rejected():
    foreign = _candidate(commit=SD, tree=SE)
    rej = _result(status=VerificationStatus.COMMAND_MISMATCH, candidate=foreign, evidence_id="ev-9")
    with pytest.raises(Exception):  # noqa: B017
        _bundle(rejected=(rej,))


def test_bundle_truthful_repository_mismatch_observed_ok():
    cand = _candidate(repository_id=D)
    rej = _result(status=VerificationStatus.REPOSITORY_MISMATCH, candidate=cand,
                  snapshot=_snapshot(repository_id=D2), evidence_id="ev-9")
    b = _bundle(candidate=cand, verified=(), rejected=(rej,))
    assert b.rejected[0].status is VerificationStatus.REPOSITORY_MISMATCH


def test_bundle_false_mismatch_status_rejected_at_result_construction():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.REPOSITORY_MISMATCH, candidate=_candidate(repository_id=D),
                snapshot=_snapshot(repository_id=D), evidence_id="ev-9")


def test_bundle_non_context_foreign_snapshot_rejected_at_result_construction():
    with pytest.raises(Exception):  # noqa: B017
        _result(status=VerificationStatus.COMMAND_MISMATCH, candidate=_candidate(repository_id=D),
                snapshot=_snapshot(repository_id=D2), evidence_id="ev-9")


def test_bundle_mixed_task_rejected():
    rej = _result(status=VerificationStatus.COMMAND_MISMATCH, task_id="BH-P0-A", evidence_id="ev-9")
    with pytest.raises(Exception):  # noqa: B017
        _bundle(task_id="BH-P0-B", rejected=(rej,))


# ---------------------------------------------------------------------------
# R1-SOL-003 - run-record membership (54-64)
# ---------------------------------------------------------------------------

def test_run_record_unknown_verified_evidence_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _run_record(collected=(_collected(evidence_id="ev-1"),),
                    bundle=_bundle(verified=(_verified(evidence_id="ev-9"),)))


def test_run_record_cross_run_verified_evidence_rejected():
    with pytest.raises(Exception):  # noqa: B017
        _run_record(collected=(_collected(evidence_id="ev-1", run_id="run-1"),),
                    bundle=_bundle(verified=(_verified(evidence_id="ev-1", run_id="run-2"),)))


def test_run_record_cross_task_verified_rejected():
    # verified task pins bundle task; a bundle task != record task is rejected.
    with pytest.raises(Exception):  # noqa: B017
        _run_record(task_id="BH-P0-B",
                    bundle=_bundle(task_id="BH-P0-A",
                                   verified=(_verified(task_id="BH-P0-A"),)))


def test_run_record_unknown_rejected_evidence_rejected():
    rej = _result(status=VerificationStatus.COMMAND_MISMATCH, evidence_id="ev-9")
    with pytest.raises(Exception):  # noqa: B017
        _run_record(collected=(_collected(evidence_id="ev-1"),),
                    bundle=_bundle(verified=(), rejected=(rej,)))


def test_run_record_cross_run_rejected_evidence_rejected():
    rej = _result(status=VerificationStatus.COMMAND_MISMATCH, evidence_id="ev-1", run_id="run-2")
    with pytest.raises(Exception):  # noqa: B017
        _run_record(collected=(_collected(evidence_id="ev-1", run_id="run-1"),),
                    bundle=_bundle(verified=(), rejected=(rej,)))


def test_run_record_same_evidence_run_other_task_rejected():
    # collected ev-1/run-1/BH-P0-B; bundle (task BH-P0-A) verifies ev-1/run-1/BH-P0-A -> reject.
    with pytest.raises(Exception):  # noqa: B017
        _run_record(task_id="BH-P0-A",
                    collected=(_collected(evidence_id="ev-1", run_id="run-1", task_id="BH-P0-B"),),
                    bundle=_bundle(task_id="BH-P0-A",
                                   verified=(_verified(evidence_id="ev-1", task_id="BH-P0-A"),)))


def test_run_record_verified_identity_read_from_entry_not_record():
    # everything says run-1 except the verified entry itself (run-2) -> membership catches it.
    with pytest.raises(Exception):  # noqa: B017
        _run_record(run_id="run-1", collected=(_collected(run_id="run-1"),),
                    bundle=_bundle(verified=(_verified(run_id="run-2"),)))


def test_run_record_rejected_identity_read_from_entry_not_bundle():
    rej = _result(status=VerificationStatus.COMMAND_MISMATCH, evidence_id="ev-1", run_id="run-2")
    with pytest.raises(Exception):  # noqa: B017
        _run_record(run_id="run-1", collected=(_collected(evidence_id="ev-1", run_id="run-1"),),
                    bundle=_bundle(verified=(), rejected=(rej,)))


def test_run_record_valid_subset_ok():
    coll = (_collected(evidence_id="ev-1"), _collected(evidence_id="ev-2"))
    rec = _run_record(collected=coll,
                      bundle=_bundle(verified=(_verified(evidence_id="ev-1"),)))
    assert len(rec.collected_evidence) == 2


def test_run_record_all_evidence_bundle_ok():
    coll = (_collected(evidence_id="ev-1"), _collected(evidence_id="ev-2"))
    rec = _run_record(collected=coll, bundle=_bundle(
        verified=(_verified(evidence_id="ev-1"), _verified(evidence_id="ev-2"))))
    assert len(rec.verification_bundle.verified) == 2


def test_run_record_empty_explicit_context_bundle_ok():
    rec = _run_record(bundle=_bundle(verified=(), rejected=()))
    assert rec.verification_bundle.verified == ()


# ---------------------------------------------------------------------------
# Direct precedence-helper coverage (supporting the matrix)
# ---------------------------------------------------------------------------

def test_expected_status_precedence_is_exclusive():
    cand = _candidate()
    assert expected_context_mismatch_status(cand, _snapshot(repository_id=D2, base=SD, commit=SD)) \
        is VerificationStatus.REPOSITORY_MISMATCH
    assert expected_context_mismatch_status(cand, _snapshot(base=SD, commit=SD)) \
        is VerificationStatus.STALE
    assert expected_context_mismatch_status(cand, _snapshot(commit=SD, tree=SD)) \
        is VerificationStatus.COMMIT_MISMATCH
    assert expected_context_mismatch_status(cand, _snapshot(tree=SD, changed=("src/a.py",))) \
        is VerificationStatus.TREE_MISMATCH
    assert expected_context_mismatch_status(cand, _snapshot(changed=("src/a.py",))) \
        is VerificationStatus.SNAPSHOT_CHANGED
    assert expected_context_mismatch_status(cand, _snapshot(release_clean=False)) \
        is VerificationStatus.DIRTY_WORKTREE
    assert expected_context_mismatch_status(cand, _snapshot()) is None

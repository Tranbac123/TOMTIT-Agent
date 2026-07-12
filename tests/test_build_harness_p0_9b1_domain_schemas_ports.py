"""P0-9B1 — domain schemas + ports: exact validation and canonical serialization.

Pure-domain tests: no git, no subprocess, no clock. Every model validates explicit inputs
with NO coercion (bool != int), immutable tuples, self-referential digest checks, and exact
mapping deserialization with round-trip canonical-byte stability.
"""
from __future__ import annotations

import importlib
import pathlib

import pytest

from agent_core.build_harness.canonical import (
    P09BValidationError,
    canonical_digest,
    canonical_json_bytes,
    changed_files_digest,
    validate_generated_id,
    validate_git_object_sha,
    validate_sha256_digest,
    validate_task_id,
)
from agent_core.build_harness.repository_models import (
    CandidateBinding,
    CommandExecutionErrorCode,
    CommandRequirement,
    DirtyState,
    EvidenceSource,
    GitObjectFormat,
    RepositoryInspectionErrorCode,
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
)
from agent_core.build_harness.ports import (
    Clock,
    CommandExecutionError,
    CommandExecutionResult,
    CommandExecutionSpec,
    CommandRunner,
    EvidenceRunRecord,
    EvidenceVerificationRequest,
    Outcome,
    RepositoryInspectionError,
    RepositoryInspectionRequest,
    RepositoryInspector,
    RunIdGenerator,
)

D = "sha256:" + "a" * 64          # a valid sha256 digest
D2 = "sha256:" + "b" * 64
SHA1_A = "a" * 40
SHA1_B = "b" * 40
SHA1_C = "c" * 40
TS0 = "2026-07-11T00:00:00.000000Z"
TS1 = "2026-07-11T00:00:01.500000Z"


# ---------------------------------------------------------------------------
# factories
# ---------------------------------------------------------------------------

def _snapshot(snapshot_id="snap-1", commit=SHA1_A, tree=SHA1_B, base=SHA1_C,
              changed=("src/a.py", "src/b.py"), **kw):
    fields = dict(
        schema_version="p0-9b.repository-snapshot.v1", snapshot_id=snapshot_id,
        repository_id=D, repository_root_hint="/repo", object_format=GitObjectFormat.SHA1,
        head_commit_sha=commit, head_tree_sha=tree, base_commit_sha=base,
        branch_name="main", detached_head=False,
        staged_changes=(), unstaged_changes=(), untracked_files=(), submodule_changes=(),
        changed_files=tuple(changed), changed_files_digest=changed_files_digest(tuple(changed)),
        is_release_clean=True, captured_at=TS0, inspector_version="git-inspector-1",
    )
    fields.update(kw)
    return RepositorySnapshot(**fields)


def _candidate(commit=SHA1_A, tree=SHA1_B, base=SHA1_C, changed=("src/a.py", "src/b.py")):
    return CandidateBinding(
        schema_version="p0-9b.candidate-binding.v1", repository_id=D,
        object_format=GitObjectFormat.SHA1, base_commit_sha=base,
        candidate_commit_sha=commit, candidate_tree_sha=tree, contract_digest=D2,
        changed_files_digest=changed_files_digest(tuple(changed)),
    )


def _requirement(argv=("pytest", "-q"), cwd=".", timeout=600, req_id="req-1"):
    # Pass argv through unchanged when it is not already a list/tuple, so a scalar string
    # is rejected by the model (not silently exploded into a char tuple).
    argv_value = tuple(argv) if isinstance(argv, (list, tuple)) else argv
    digest_argv = argv_value if isinstance(argv_value, tuple) else ("pytest", "-q")
    return CommandRequirement(
        schema_version="p0-9b.command-requirement.v1", requirement_id=req_id,
        argv=argv_value, working_directory=cwd, timeout_seconds=timeout,
        command_digest=canonical_digest(command_requirement_payload(digest_argv, cwd, timeout)),
    )


def _provenance(evidence_id="ev-1", **kw):
    fields = dict(
        schema_version="p0-9b.provenance.v1", evidence_id=evidence_id, task_id="BH-P0-B",
        run_id="run-1", collector_id="collector-1", collector_version="1.0",
        requirement_id="req-1", argv=("pytest", "-q"), working_directory=".",
        command_digest=canonical_digest(command_requirement_payload(("pytest", "-q"), ".", 600)),
        exit_code=0, completed=True, started_at=TS0, completed_at=TS1, duration_ms=1500,
        repository_id=D, object_format=GitObjectFormat.SHA1, base_commit_sha=SHA1_C,
        commit_sha=SHA1_A, tree_sha=SHA1_B, pre_snapshot_id="snap-pre",
        post_snapshot_id="snap-post", dirty_state=DirtyState.CLEAN,
        changed_files_digest=changed_files_digest(("src/a.py",)),
        stdout_digest=D, stderr_digest=D2, artifact_digest=None,
        source=EvidenceSource.LOCAL_CONTROLLED_COLLECTOR,
    )
    fields.update(kw)
    return EvidenceProvenance(**fields)


def _verified(evidence_id="ev-1", req_id="req-1", candidate=None):
    cand = candidate or _candidate()
    return VerifiedCommandEvidence(
        schema_version="p0-9b.verified-evidence.v1", evidence_id=evidence_id,
        run_id="run-1", task_id="BH-P0-B", requirement_id=req_id, candidate_binding=cand,
        verification_digest=VerifiedCommandEvidence.compute_verification_digest(
            evidence_id, "run-1", "BH-P0-B", req_id, cand),
    )


def _rejected_result(evidence_id="ev-9"):
    return EvidenceVerificationResult(
        schema_version="p0-9b.verification.v1", accepted=False,
        status=VerificationStatus.COMMAND_MISMATCH, reason_codes=("COMMAND_MISMATCH",),
        evidence_id=evidence_id, run_id="run-1", task_id="BH-P0-B",
        candidate_binding=None, repository_snapshot=None, matched_requirement_id=None,
        claim_digest=D, verified_at=TS0, verifier_version="verifier-1",
        warnings=(), errors=("mismatch",),
    )


def _bundle(verified=None, rejected=(), candidate=None, snapshot=None):
    cand = candidate or _candidate()
    verified = verified if verified is not None else (_verified(candidate=cand),)
    snap = snapshot or _snapshot(commit=cand.candidate_commit_sha, tree=cand.candidate_tree_sha,
                                 base=cand.base_commit_sha)
    return EvidenceVerificationBundle(
        schema_version="p0-9b.verification-bundle.v1", candidate_binding=cand,
        verified=tuple(verified), rejected=tuple(rejected), verified_at_snapshot=snap,
        bundle_digest=EvidenceVerificationBundle.compute_bundle_digest(
            cand, tuple(verified), tuple(rejected), snap),
    )


# ---------------------------------------------------------------------------
# Identifier validation (1-6)
# ---------------------------------------------------------------------------

def test_existing_uppercase_task_id_accepted():
    for tid in ("BH-P0-B", "task-1", "task_alpha", "task.v2"):
        assert validate_task_id(tid) == tid


@pytest.mark.parametrize("bad", ["", " ", "a/b", "../x", "a\nb", "x" * 129])
def test_invalid_task_id_rejected(bad):
    with pytest.raises(P09BValidationError):
        validate_task_id(bad)


def test_lowercase_generated_ids_accepted():
    for gid in ("run-1", "evidence-abc", "snap-9", "req-collector-2", "a"):
        assert validate_generated_id(gid, field="id") == gid


@pytest.mark.parametrize("bad", ["Run-1", "RUN", "CamelCase"])
def test_uppercase_generated_id_rejected(bad):
    with pytest.raises(P09BValidationError):
        validate_generated_id(bad, field="id")


@pytest.mark.parametrize("bad", ["run_1", "run.1", "a/b", "../x", "a b", "a\x00b", ""])
def test_separator_traversal_control_ids_rejected(bad):
    with pytest.raises(P09BValidationError):
        validate_generated_id(bad, field="id")


def test_overlength_ids_rejected():
    with pytest.raises(P09BValidationError):
        validate_generated_id("a" * 65, field="id")
    with pytest.raises(P09BValidationError):
        validate_task_id("a" * 129)


# ---------------------------------------------------------------------------
# Digest and Git SHA (7-13)
# ---------------------------------------------------------------------------

def test_valid_sha256_digest_accepted():
    assert validate_sha256_digest(D, field="d") == D


@pytest.mark.parametrize("bad", [
    "sha256:" + "A" * 64, "sha256:" + "a" * 63, "sha256:" + "a" * 65,
    "a" * 64, "sha1:" + "a" * 40, "sha256:", "SHA256:" + "a" * 64,
])
def test_invalid_sha256_digest_rejected(bad):
    with pytest.raises(P09BValidationError):
        validate_sha256_digest(bad, field="d")


def test_git_object_sha_validation():
    assert validate_git_object_sha("a" * 40, "sha1", field="s") == "a" * 40
    assert validate_git_object_sha("a" * 64, "sha256", field="s") == "a" * 64


@pytest.mark.parametrize("sha, fmt", [
    ("a" * 64, "sha1"), ("a" * 40, "sha256"),      # format/length mismatch
    ("A" * 40, "sha1"), ("a" * 7, "sha1"), ("", "sha1"),  # uppercase / abbreviated / empty
])
def test_git_object_sha_mismatch_rejected(sha, fmt):
    with pytest.raises(P09BValidationError):
        validate_git_object_sha(sha, fmt, field="s")


# ---------------------------------------------------------------------------
# Canonical JSON (14-22)
# ---------------------------------------------------------------------------

def test_canonical_json_stable_key_ordering():
    assert canonical_json_bytes({"b": 1, "a": 2}) == canonical_json_bytes({"a": 2, "b": 1})


def test_canonical_json_nfc_normalization():
    decomposed = "é"   # e + combining acute
    composed = "é"       # é
    assert canonical_json_bytes({"k": decomposed}) == canonical_json_bytes({"k": composed})


def test_canonical_json_tuples_as_arrays():
    assert canonical_json_bytes(("a", "b")) == canonical_json_bytes(["a", "b"])


def test_canonical_json_enums_by_value():
    assert canonical_json_bytes(GitObjectFormat.SHA1) == canonical_json_bytes("sha1")


def test_canonical_json_unsupported_object_rejected():
    with pytest.raises(P09BValidationError):
        canonical_json_bytes({"k": object()})


def test_canonical_json_nan_infinity_rejected():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(P09BValidationError):
            canonical_json_bytes({"k": bad})


def test_canonical_digest_stable():
    assert canonical_digest({"a": 1, "b": [1, 2]}) == canonical_digest({"b": [1, 2], "a": 1})
    assert canonical_digest({"a": 1}).startswith("sha256:")


def test_changed_files_digest_stable():
    assert changed_files_digest(("a", "b")) == changed_files_digest(("a", "b"))
    assert changed_files_digest(("a", "b")) != changed_files_digest(("b", "a"))


def test_command_digest_changes_with_inputs():
    base = canonical_digest(command_requirement_payload(("pytest",), ".", 600))
    assert base != canonical_digest(command_requirement_payload(("pytest", "-q"), ".", 600))
    assert base != canonical_digest(command_requirement_payload(("pytest",), "sub", 600))
    assert base != canonical_digest(command_requirement_payload(("pytest",), ".", 601))


# ---------------------------------------------------------------------------
# CandidateBinding (23-27)
# ---------------------------------------------------------------------------

def test_candidate_binding_valid():
    assert _candidate().candidate_commit_sha == SHA1_A


def test_candidate_binding_unknown_field_rejected():
    d = _candidate().to_json_dict()
    d["surprise"] = 1
    with pytest.raises(P09BValidationError):
        CandidateBinding.from_json_dict(d)


def test_candidate_binding_wrong_candidate_sha_rejected():
    with pytest.raises(P09BValidationError):
        _candidate(commit="A" * 40)


def test_candidate_binding_wrong_digest_rejected():
    d = _candidate().to_json_dict()
    d["contract_digest"] = "not-a-digest"
    with pytest.raises(P09BValidationError):
        CandidateBinding.from_json_dict(d)


def test_candidate_binding_round_trip_bytes():
    cb = _candidate()
    again = CandidateBinding.from_json_dict(cb.to_json_dict())
    assert canonical_json_bytes(again.to_json_dict()) == canonical_json_bytes(cb.to_json_dict())


# ---------------------------------------------------------------------------
# RepositorySnapshot (28-38)
# ---------------------------------------------------------------------------

def test_snapshot_valid_clean():
    assert _snapshot().is_release_clean is True


def test_snapshot_dirty_staged():
    s = _snapshot(staged_changes=("src/x.py",), is_release_clean=False)
    assert s.is_release_clean is False


def test_snapshot_dirty_untracked():
    assert _snapshot(untracked_files=("t.txt",), is_release_clean=False).is_release_clean is False


def test_snapshot_dirty_submodule():
    assert _snapshot(submodule_changes=("sub",), is_release_clean=False).is_release_clean is False


def test_snapshot_incorrect_release_clean_rejected():
    with pytest.raises(P09BValidationError):
        _snapshot(staged_changes=("src/x.py",), is_release_clean=True)


def test_snapshot_unsorted_paths_rejected():
    with pytest.raises(P09BValidationError):
        _snapshot(changed_files=("src/b.py", "src/a.py"),
                  changed_files_digest=changed_files_digest(("src/b.py", "src/a.py")))


def test_snapshot_duplicate_paths_rejected():
    with pytest.raises(P09BValidationError):
        _snapshot(changed_files=("src/a.py", "src/a.py"),
                  changed_files_digest=changed_files_digest(("src/a.py", "src/a.py")))


def test_snapshot_invalid_path_rejected():
    with pytest.raises(P09BValidationError):
        _snapshot(changed_files=("../evil.py",),
                  changed_files_digest=changed_files_digest(("../evil.py",)))


def test_snapshot_wrong_changed_files_digest_rejected():
    with pytest.raises(P09BValidationError):
        _snapshot(changed_files_digest=D)


def test_snapshot_detached_head_branch_inconsistency_rejected():
    with pytest.raises(P09BValidationError):
        _snapshot(detached_head=True, branch_name="main")
    with pytest.raises(P09BValidationError):
        _snapshot(detached_head=False, branch_name=None)
    # detached head with branch_name=None is valid.
    assert _snapshot(detached_head=True, branch_name=None).detached_head is True


def test_snapshot_round_trip_stable():
    s = _snapshot()
    again = RepositorySnapshot.from_json_dict(s.to_json_dict())
    assert canonical_json_bytes(again.to_json_dict()) == canonical_json_bytes(s.to_json_dict())


# ---------------------------------------------------------------------------
# CommandRequirement (39-46)
# ---------------------------------------------------------------------------

def test_requirement_valid_structured_argv():
    assert _requirement().argv == ("pytest", "-q")


def test_requirement_empty_argv_rejected():
    with pytest.raises(P09BValidationError):
        _requirement(argv=())


def test_requirement_boolean_timeout_rejected():
    with pytest.raises(P09BValidationError):
        _requirement(timeout=True)


@pytest.mark.parametrize("bad", [0, 3601, -1])
def test_requirement_timeout_out_of_range_rejected(bad):
    with pytest.raises(P09BValidationError):
        _requirement(timeout=bad)


def test_requirement_shell_scalar_command_rejected():
    with pytest.raises(P09BValidationError):
        _requirement(argv="pytest -q && rm -rf /")  # a scalar, not a tuple


def test_requirement_invalid_cwd_rejected():
    with pytest.raises(P09BValidationError):
        _requirement(cwd="/abs")
    with pytest.raises(P09BValidationError):
        _requirement(cwd="../up")


def test_requirement_dot_cwd_accepted():
    assert _requirement(cwd=".").working_directory == "."


def test_requirement_wrong_command_digest_rejected():
    d = _requirement().to_json_dict()
    d["command_digest"] = D
    with pytest.raises(P09BValidationError):
        CommandRequirement.from_json_dict(d)


# ---------------------------------------------------------------------------
# EvidenceProvenance (47-55)
# ---------------------------------------------------------------------------

def test_provenance_valid_completed():
    assert _provenance().completed is True


def test_provenance_completed_non_int_exit_rejected():
    with pytest.raises(P09BValidationError):
        _provenance(completed=True, exit_code=None)


def test_provenance_bool_exit_code_rejected():
    with pytest.raises(P09BValidationError):
        _provenance(exit_code=True)


def test_provenance_invalid_timestamp_rejected():
    with pytest.raises(P09BValidationError):
        _provenance(started_at="2026-07-11 00:00:00Z")


def test_provenance_end_before_start_rejected():
    with pytest.raises(P09BValidationError):
        _provenance(started_at=TS1, completed_at=TS0, duration_ms=0)


def test_provenance_duration_mismatch_rejected():
    with pytest.raises(P09BValidationError):
        _provenance(duration_ms=99999)


def test_provenance_task_id_grammar_preserved():
    assert _provenance(task_id="BH-P0-B").task_id == "BH-P0-B"
    with pytest.raises(P09BValidationError):
        _provenance(task_id="bad id")


def test_provenance_wrong_command_digest_rejected():
    with pytest.raises(P09BValidationError):
        _provenance(command_digest="not-a-digest")


def test_provenance_invalid_artifact_digest_rejected():
    with pytest.raises(P09BValidationError):
        _provenance(artifact_digest="nope")
    assert _provenance(artifact_digest=D).artifact_digest == D


# ---------------------------------------------------------------------------
# CollectedCommandEvidence (56-60)
# ---------------------------------------------------------------------------

def _collected(**kw):
    prov = _provenance()
    pre = _snapshot(snapshot_id=prov.pre_snapshot_id, commit=prov.commit_sha,
                    tree=prov.tree_sha, base=prov.base_commit_sha)
    post = _snapshot(snapshot_id=prov.post_snapshot_id, commit=prov.commit_sha,
                     tree=prov.tree_sha, base=prov.base_commit_sha)
    fields = dict(schema_version="p0-9b.collected-evidence.v1", provenance=prov,
                  pre_snapshot=pre, post_snapshot=post)
    fields.update(kw)
    return CollectedCommandEvidence(**fields)


def test_collected_valid_linkage():
    assert _collected().provenance.evidence_id == "ev-1"


def test_collected_pre_snapshot_id_mismatch_rejected():
    with pytest.raises(P09BValidationError):
        _collected(pre_snapshot=_snapshot(snapshot_id="wrong-pre"))


def test_collected_post_snapshot_id_mismatch_rejected():
    with pytest.raises(P09BValidationError):
        _collected(post_snapshot=_snapshot(snapshot_id="wrong-post"))


def test_collected_repository_mismatch_rejected():
    bad_post = _snapshot(snapshot_id="snap-post", repository_id=D2)
    with pytest.raises(P09BValidationError):
        _collected(post_snapshot=bad_post)


def test_collected_commit_tree_mismatch_rejected():
    bad_post = _snapshot(snapshot_id="snap-post", commit="d" * 40,
                         changed=("src/a.py",))
    with pytest.raises(P09BValidationError):
        _collected(post_snapshot=bad_post)


# ---------------------------------------------------------------------------
# Verification result (61-66)
# ---------------------------------------------------------------------------

def _accepted_result():
    return EvidenceVerificationResult(
        schema_version="p0-9b.verification.v1", accepted=True,
        status=VerificationStatus.VERIFIED, reason_codes=("OK",), evidence_id="ev-1",
        run_id="run-1", task_id="BH-P0-B", candidate_binding=_candidate(),
        repository_snapshot=_snapshot(), matched_requirement_id="req-1", claim_digest=D,
        verified_at=TS0, verifier_version="verifier-1", warnings=(), errors=(),
    )


def test_accepted_verified_result_valid():
    assert _accepted_result().accepted is True


def test_accepted_non_verified_status_rejected():
    with pytest.raises(P09BValidationError):
        EvidenceVerificationResult(
            schema_version="p0-9b.verification.v1", accepted=True,
            status=VerificationStatus.STALE, reason_codes=("x",), evidence_id="ev-1",
            run_id="run-1", task_id="BH-P0-B", candidate_binding=_candidate(),
            repository_snapshot=_snapshot(), matched_requirement_id="req-1", claim_digest=D,
            verified_at=TS0, verifier_version="v", warnings=(), errors=())


def test_rejected_result_claiming_requirement_rejected():
    with pytest.raises(P09BValidationError):
        EvidenceVerificationResult(
            schema_version="p0-9b.verification.v1", accepted=False,
            status=VerificationStatus.STALE, reason_codes=("x",), evidence_id="ev-1",
            run_id="run-1", task_id="BH-P0-B", candidate_binding=None,
            repository_snapshot=None, matched_requirement_id="req-1", claim_digest=D,
            verified_at=TS0, verifier_version="v", warnings=(), errors=())


def test_accepted_result_missing_binding_rejected():
    with pytest.raises(P09BValidationError):
        EvidenceVerificationResult(
            schema_version="p0-9b.verification.v1", accepted=True,
            status=VerificationStatus.VERIFIED, reason_codes=("x",), evidence_id="ev-1",
            run_id="run-1", task_id="BH-P0-B", candidate_binding=None,
            repository_snapshot=None, matched_requirement_id="req-1", claim_digest=D,
            verified_at=TS0, verifier_version="v", warnings=(), errors=())


def test_unknown_status_rejected():
    d = _accepted_result().to_json_dict()
    d["status"] = "NONSENSE"
    with pytest.raises(P09BValidationError):
        EvidenceVerificationResult.from_json_dict(d)


def test_verification_result_round_trip_stable():
    r = _accepted_result()
    again = EvidenceVerificationResult.from_json_dict(r.to_json_dict())
    assert canonical_json_bytes(again.to_json_dict()) == canonical_json_bytes(r.to_json_dict())


# ---------------------------------------------------------------------------
# Verified evidence and bundle (67-76)
# ---------------------------------------------------------------------------

def test_verified_evidence_valid():
    assert _verified().evidence_id == "ev-1"


def test_verified_evidence_incorrect_digest_rejected():
    d = _verified().to_json_dict()
    d["verification_digest"] = D
    with pytest.raises(P09BValidationError):
        VerifiedCommandEvidence.from_json_dict(d)


def test_verified_tuple_rejects_raw_object():
    with pytest.raises(P09BValidationError):
        EvidenceVerificationBundle(
            schema_version="p0-9b.verification-bundle.v1", candidate_binding=_candidate(),
            verified=("not-verified-evidence",), rejected=(),
            verified_at_snapshot=_snapshot(), bundle_digest=D)


def test_bundle_duplicate_evidence_id_rejected():
    cand = _candidate()
    with pytest.raises(P09BValidationError):
        _bundle(verified=(_verified("ev-1", candidate=cand), _verified("ev-1", candidate=cand)),
                candidate=cand)


def test_bundle_rejected_tuple_cannot_contain_accepted():
    with pytest.raises(P09BValidationError):
        _bundle(rejected=(_accepted_result(),))


def test_bundle_candidate_mismatch_rejected():
    other = _candidate(commit="d" * 40, tree="e" * 40)
    with pytest.raises(P09BValidationError):
        _bundle(verified=(_verified(candidate=other),))


def test_bundle_snapshot_mismatch_rejected():
    cand = _candidate()
    with pytest.raises(P09BValidationError):
        _bundle(candidate=cand, snapshot=_snapshot(commit="d" * 40, changed=("src/a.py",)))


def test_bundle_valid_same_run_multi_command():
    cand = _candidate()
    bundle = _bundle(candidate=cand, verified=(
        _verified("ev-1", req_id="req-1", candidate=cand),
        _verified("ev-2", req_id="req-2", candidate=cand),
    ))
    assert len(bundle.verified) == 2
    assert bundle.verified[0].run_id == bundle.verified[1].run_id == "run-1"


def test_bundle_incorrect_digest_rejected():
    d = _bundle().to_json_dict()
    d["bundle_digest"] = D
    with pytest.raises(P09BValidationError):
        EvidenceVerificationBundle.from_json_dict(d)


def test_bundle_round_trip_stable():
    b = _bundle()
    again = EvidenceVerificationBundle.from_json_dict(b.to_json_dict())
    assert canonical_json_bytes(again.to_json_dict()) == canonical_json_bytes(b.to_json_dict())


# ---------------------------------------------------------------------------
# Outcome and ports (77-85)
# ---------------------------------------------------------------------------

def test_outcome_success():
    o = Outcome.success("value")
    assert o.is_success and o.value == "value" and o.error is None


def test_outcome_failure():
    o = Outcome.failure("boom")
    assert not o.is_success and o.error == "boom" and o.value is None


def test_outcome_both_rejected():
    with pytest.raises(P09BValidationError):
        Outcome(value="v", error="e")


def test_outcome_neither_rejected():
    with pytest.raises(P09BValidationError):
        Outcome(value=None, error=None)


class _FakeInspector:
    def inspect(self, request):
        return Outcome.success(_snapshot())


class _FakeRunner:
    def run(self, spec):
        return Outcome.failure(CommandExecutionError(
            code=CommandExecutionErrorCode.EXECUTABLE_UNAVAILABLE, message="no exec"))


class _FakeClock:
    def now_utc(self):
        from datetime import datetime, timezone
        return datetime(2026, 7, 11, tzinfo=timezone.utc)


class _FakeIds:
    def new_run_id(self):
        return "run-1"

    def new_evidence_id(self):
        return "ev-1"


def test_fake_repository_inspector_satisfies_protocol():
    inspector = _FakeInspector()
    assert isinstance(inspector, RepositoryInspector)
    result = inspector.inspect(RepositoryInspectionRequest(
        repository_path="/repo", candidate_commit_sha=SHA1_A, base_commit_sha=SHA1_C))
    assert result.is_success


def test_fake_command_runner_satisfies_protocol():
    runner = _FakeRunner()
    assert isinstance(runner, CommandRunner)
    out = runner.run(CommandExecutionSpec(
        argv=("pytest",), repository_root="/repo", working_directory=".",
        timeout_seconds=60, max_stdout_bytes=1024, max_stderr_bytes=1024))
    assert not out.is_success


def test_fake_clock_and_id_generator_usable():
    assert isinstance(_FakeClock(), Clock)
    assert isinstance(_FakeIds(), RunIdGenerator)
    assert _FakeClock().now_utc().year == 2026
    assert _FakeIds().new_run_id() == "run-1"


def test_no_git_or_subprocess_needed(monkeypatch):
    # Purely constructing/validating models never touches git or subprocess.
    import sys
    assert "git" not in sys.modules  # nothing imported git
    _bundle()  # constructs a full graph of validated models with no external dependency


def test_verification_request_and_inspection_error_models():
    req = EvidenceVerificationRequest(
        task_id="BH-P0-B", requirements=(_requirement(),), candidate_binding=_candidate(),
        collected_evidence=(_collected(),), current_snapshot=_snapshot(),
        verifier_version="verifier-1", verified_at=TS0)
    assert req.task_id == "BH-P0-B" and len(req.requirements) == 1
    # A verification request must reject a non-CommandRequirement in requirements.
    with pytest.raises(P09BValidationError):
        EvidenceVerificationRequest(
            task_id="BH-P0-B", requirements=("not-a-requirement",),
            candidate_binding=_candidate(), collected_evidence=(), current_snapshot=_snapshot(),
            verifier_version="v", verified_at=TS0)
    err = RepositoryInspectionError(
        code=RepositoryInspectionErrorCode.NOT_A_REPOSITORY, message="not a repo",
        command=("git", "rev-parse"), stderr_excerpt="fatal: not a git repository")
    assert err.code is RepositoryInspectionErrorCode.NOT_A_REPOSITORY
    with pytest.raises(P09BValidationError):
        RepositoryInspectionError(code="not-an-enum", message="x")


def test_command_execution_result_and_run_record():
    result = CommandExecutionResult(
        argv=("pytest",), exit_code=0, completed=True, timed_out=False, interrupted=False,
        started_at=TS0, completed_at=TS1, duration_ms=1500, stdout=b"ok", stderr=b"")
    assert result.completed and result.stdout == b"ok"
    record = EvidenceRunRecord(
        schema_version="p0-9b.evidence-run-record.v1", task_id="BH-P0-B", run_id="run-1",
        collected_evidence=(_collected(),), final_snapshot=_snapshot(),
        verification_bundle=_bundle())
    assert record.run_id == "run-1"


# ---------------------------------------------------------------------------
# Defensive type cases (86-90)
# ---------------------------------------------------------------------------

def test_bool_rejected_where_int_expected():
    with pytest.raises(P09BValidationError):
        _requirement(timeout=True)


def test_number_rejected_where_string_expected():
    d = _candidate().to_json_dict()
    d["repository_id"] = 12345
    with pytest.raises(P09BValidationError):
        CandidateBinding.from_json_dict(d)


def test_scalar_rejected_where_tuple_expected():
    d = _snapshot().to_json_dict()
    d["staged_changes"] = "not-a-list"
    with pytest.raises(P09BValidationError):
        RepositorySnapshot.from_json_dict(d)


def test_unknown_nested_field_rejected():
    d = _collected().to_json_dict()
    d["provenance"]["surprise"] = 1
    with pytest.raises(P09BValidationError):
        CollectedCommandEvidence.from_json_dict(d)


def test_caller_list_mutation_cannot_alter_model():
    paths = ["src/a.py", "src/b.py"]
    snap = _snapshot(changed=tuple(paths))
    paths.append("src/c.py")           # mutating the caller's list
    assert snap.changed_files == ("src/a.py", "src/b.py")  # model unaffected (tuple)


# ---------------------------------------------------------------------------
# Architecture boundary (28)
# ---------------------------------------------------------------------------

_PURE_MODULES = [
    "agent_core.build_harness.canonical",
    "agent_core.build_harness.repository_models",
    "agent_core.build_harness.provenance",
    "agent_core.build_harness.ports",
]
_FORBIDDEN_TOKENS = (
    "import subprocess", "import shlex", "import socket", "import requests",
    "import httpx", "import git", "GitPython", "os.system", "os.popen",
)


@pytest.mark.parametrize("module_name", _PURE_MODULES)
def test_pure_modules_have_no_forbidden_imports(module_name):
    module = importlib.import_module(module_name)
    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    for token in _FORBIDDEN_TOKENS:
        assert token not in source, f"{module_name} must not reference {token!r}"

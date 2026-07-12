"""P0-9B1-R1 - adversarial regression tests for the ten confirmed domain-integrity defects.

Each test group maps to one B1-CODEX finding and asserts the NARROW fail-closed behavior:
canonical NFC-key collisions, exact built-in types at trust boundaries, canonical paths,
the command-execution state matrix, dirty-state derivation, candidate/snapshot context
binding, verification-request/run-record graph consistency, set-like diagnostics, and the
typed storage port. No git, subprocess, clock, or filesystem is used.

Unicode is written with explicit escapes at every CODE position so a would-be collision or
non-NFC alias is a guaranteed distinct byte sequence (a composed source literal would
otherwise silently collapse and vacuously pass).
"""
from __future__ import annotations

import pytest

from agent_core.build_harness.canonical import (
    P09BValidationError,
    canonical_digest,
    canonical_json_bytes,
    changed_files_digest,
    is_exact_tuple,
    require_int,
    require_sorted_unique_str_tuple,
    require_str,
    validate_repo_path,
    validate_task_id,
)
from agent_core.build_harness.repository_models import (
    CandidateBinding,
    CommandRequirement,
    DirtyState,
    EvidenceSource,
    GitObjectFormat,
    RepositorySnapshot,
    VerificationStatus,
    candidate_snapshot_mismatches,
    command_requirement_payload,
)
from agent_core.build_harness.provenance import (
    CollectedCommandEvidence,
    EvidenceProvenance,
    EvidenceVerificationBundle,
    EvidenceVerificationResult,
    VerifiedCommandEvidence,
    collected_candidate_mismatches,
)
from agent_core.build_harness.ports import (
    CommandExecutionResult,
    EvidenceRepository,
    EvidenceRunRecord,
    EvidenceVerificationRequest,
    Outcome,
    StorageError,
    StorageErrorCode,
    Unit,
)

D = "sha256:" + "a" * 64
D2 = "sha256:" + "b" * 64
SHA1_A = "a" * 40
SHA1_B = "b" * 40
SHA1_C = "c" * 40
SHA1_D = "d" * 40
SHA1_E = "e" * 40
TS0 = "2026-07-11T00:00:00.000000Z"
TS1 = "2026-07-11T00:00:01.500000Z"
TS_1S = "2026-07-11T00:00:01.000000Z"

# NFC-equal but byte-distinct keys/paths (composed vs. decomposed).
E_COMPOSED = "é"        # LATIN SMALL LETTER E WITH ACUTE
E_DECOMPOSED = "é"     # 'e' + COMBINING ACUTE ACCENT
A_COMPOSED = "Å"        # LATIN CAPITAL LETTER A WITH RING ABOVE
A_DECOMPOSED = "Å"     # 'A' + COMBINING RING ABOVE


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


def _candidate(commit=SHA1_A, tree=SHA1_B, base=SHA1_C, repository_id=D,
               changed=("src/a.py", "src/b.py")):
    return CandidateBinding(
        schema_version="p0-9b.candidate-binding.v1", repository_id=repository_id,
        object_format=GitObjectFormat.SHA1, base_commit_sha=base,
        candidate_commit_sha=commit, candidate_tree_sha=tree, contract_digest=D2,
        changed_files_digest=changed_files_digest(tuple(changed)),
    )


def _requirement(argv=("pytest", "-q"), cwd=".", timeout=600, req_id="req-1"):
    return CommandRequirement(
        schema_version="p0-9b.command-requirement.v1", requirement_id=req_id,
        argv=tuple(argv), working_directory=cwd, timeout_seconds=timeout,
        command_digest=canonical_digest(command_requirement_payload(tuple(argv), cwd, timeout)),
    )


def _provenance(evidence_id="ev-1", task_id="BH-P0-B", run_id="run-1", req_id="req-1",
                dirty_state=DirtyState.CLEAN, **kw):
    fields = dict(
        schema_version="p0-9b.provenance.v1", evidence_id=evidence_id, task_id=task_id,
        run_id=run_id, collector_id="collector-1", collector_version="1.0",
        requirement_id=req_id, argv=("pytest", "-q"), working_directory=".",
        command_digest=canonical_digest(command_requirement_payload(("pytest", "-q"), ".", 600)),
        exit_code=0, completed=True, started_at=TS0, completed_at=TS1, duration_ms=1500,
        repository_id=D, object_format=GitObjectFormat.SHA1, base_commit_sha=SHA1_C,
        commit_sha=SHA1_A, tree_sha=SHA1_B, pre_snapshot_id="snap-pre",
        post_snapshot_id="snap-post", dirty_state=dirty_state,
        changed_files_digest=changed_files_digest(("src/a.py",)),
        stdout_digest=D, stderr_digest=D2, artifact_digest=None,
        source=EvidenceSource.LOCAL_CONTROLLED_COLLECTOR,
    )
    fields.update(kw)
    return EvidenceProvenance(**fields)


def _collected(prov=None, pre_clean=True, post_clean=True, **kw):
    prov = prov or _provenance()

    def _dirty_kwargs(clean):
        if clean:
            return {}
        return dict(staged_changes=("dirty.py",), is_release_clean=False,
                    changed_files=("dirty.py",),
                    changed_files_digest=changed_files_digest(("dirty.py",)))

    pre = _snapshot(snapshot_id=prov.pre_snapshot_id, commit=prov.commit_sha,
                    tree=prov.tree_sha, base=prov.base_commit_sha, **_dirty_kwargs(pre_clean))
    post = _snapshot(snapshot_id=prov.post_snapshot_id, commit=prov.commit_sha,
                     tree=prov.tree_sha, base=prov.base_commit_sha, **_dirty_kwargs(post_clean))
    fields = dict(schema_version="p0-9b.collected-evidence.v1", provenance=prov,
                  pre_snapshot=pre, post_snapshot=post)
    fields.update(kw)
    return CollectedCommandEvidence(**fields)


def _verified(evidence_id="ev-1", req_id="req-1", task_id="BH-P0-B", candidate=None):
    cand = candidate or _candidate()
    return VerifiedCommandEvidence(
        schema_version="p0-9b.verified-evidence.v1", evidence_id=evidence_id,
        run_id="run-1", task_id=task_id, requirement_id=req_id, candidate_binding=cand,
        verification_digest=VerifiedCommandEvidence.compute_verification_digest(
            evidence_id, "run-1", task_id, req_id, cand),
    )


def _accepted_result(candidate=None, snapshot=None):
    cand = candidate or _candidate()
    snap = snapshot or _snapshot(commit=cand.candidate_commit_sha, tree=cand.candidate_tree_sha,
                                 base=cand.base_commit_sha)
    return EvidenceVerificationResult(
        schema_version="p0-9b.verification.v1", accepted=True,
        status=VerificationStatus.VERIFIED, reason_codes=("OK",), evidence_id="ev-1",
        run_id="run-1", task_id="BH-P0-B", candidate_binding=cand,
        repository_snapshot=snap, matched_requirement_id="req-1", claim_digest=D,
        verified_at=TS0, verifier_version="verifier-1", warnings=(), errors=(),
    )


def _rejected_result(evidence_id="ev-9", task_id="BH-P0-B"):
    return EvidenceVerificationResult(
        schema_version="p0-9b.verification.v1", accepted=False,
        status=VerificationStatus.COMMAND_MISMATCH, reason_codes=("COMMAND_MISMATCH",),
        evidence_id=evidence_id, run_id="run-1", task_id=task_id,
        candidate_binding=None, repository_snapshot=None, matched_requirement_id=None,
        claim_digest=D, verified_at=TS0, verifier_version="verifier-1",
        warnings=(), errors=("mismatch",),
    )


def _bundle(verified=None, rejected=(), candidate=None, snapshot=None, task_id="BH-P0-B"):
    cand = candidate or _candidate()
    verified = verified if verified is not None else (_verified(candidate=cand),)
    snap = snapshot or _snapshot(commit=cand.candidate_commit_sha, tree=cand.candidate_tree_sha,
                                 base=cand.base_commit_sha)
    return EvidenceVerificationBundle(
        schema_version="p0-9b.verification-bundle.v1", task_id=task_id, candidate_binding=cand,
        verified=tuple(verified), rejected=tuple(rejected), verified_at_snapshot=snap,
        bundle_digest=EvidenceVerificationBundle.compute_bundle_digest(
            task_id, cand, tuple(verified), tuple(rejected), snap),
    )


def _run_record(task_id="BH-P0-B", run_id="run-1", candidate=None, collected=None,
                final_snapshot=None, bundle="default"):
    cand = candidate or _candidate()
    collected = collected if collected is not None else (_collected(),)
    final = final_snapshot or _snapshot(commit=cand.candidate_commit_sha,
                                        tree=cand.candidate_tree_sha, base=cand.base_commit_sha)
    if bundle == "default":
        bundle = _bundle(candidate=cand, task_id=task_id)
    return EvidenceRunRecord(
        schema_version="p0-9b.evidence-run-record.v1", task_id=task_id, run_id=run_id,
        candidate_binding=cand, collected_evidence=tuple(collected),
        final_snapshot=final, verification_bundle=bundle)


# ---------------------------------------------------------------------------
# B1-CODEX-001 - canonical NFC key collision
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    {E_COMPOSED: 1, E_DECOMPOSED: 2},            # composed then decomposed
    {E_DECOMPOSED: 2, E_COMPOSED: 1},            # reversed insertion order
    {A_COMPOSED: 1, A_DECOMPOSED: 2},            # A-ring composed / A + ring
    {"outer": {A_COMPOSED: 1, A_DECOMPOSED: 2}},  # nested collision at depth
])
def test_nfc_key_collision_rejected(payload):
    # Guard: the two keys really are distinct in the built dict (collision appears only
    # after NFC normalization inside canonicalization, never at dict-literal parse time).
    inner = next(iter(payload.values()))
    assert (len(inner) if isinstance(inner, dict) else len(payload)) == 2
    with pytest.raises(P09BValidationError):
        canonical_json_bytes(payload)


def test_nfc_distinct_keys_still_accepted():
    # Two genuinely different keys that are NOT NFC-equal must still serialize.
    assert canonical_json_bytes({"a": 1, "b": 2})


# ---------------------------------------------------------------------------
# B1-CODEX-002 - exact built-in types at trust boundaries (no subclass replay)
# ---------------------------------------------------------------------------

class _AltTuple(tuple):
    """A tuple subclass whose iteration would alternate - proving it is rejected BEFORE
    anything iterates it (the count stays zero)."""
    iter_calls = 0

    def __iter__(self):
        type(self).iter_calls += 1
        return iter(("safe",) if type(self).iter_calls % 2 else ("evil",))


class _EvilDict(dict):
    pass


class _EvilList(list):
    pass


class _EvilStr(str):
    pass


class _EvilInt(int):
    pass


def test_tuple_subclass_rejected_before_iteration():
    _AltTuple.iter_calls = 0
    with pytest.raises(P09BValidationError):
        canonical_json_bytes({"argv": _AltTuple(("pytest",))})
    assert _AltTuple.iter_calls == 0  # rejected without ever consuming the lying iterator


def test_dict_subclass_rejected_in_canonical():
    with pytest.raises(P09BValidationError):
        canonical_json_bytes(_EvilDict({"a": 1}))


def test_str_and_int_subclasses_rejected_at_boundary():
    with pytest.raises(P09BValidationError):
        require_str(_EvilStr("x"), field="f")
    with pytest.raises(P09BValidationError):
        require_int(_EvilInt(5), field="f")
    with pytest.raises(P09BValidationError):
        validate_task_id(_EvilStr("BH-P0-B"))


def test_bool_still_rejected_where_int_expected():
    with pytest.raises(P09BValidationError):
        require_int(True, field="f")


def test_argv_tuple_subclass_rejected_by_command_requirement():
    with pytest.raises(P09BValidationError):
        CommandRequirement(
            schema_version="p0-9b.command-requirement.v1", requirement_id="req-1",
            argv=_AltTuple(("pytest",)), working_directory=".", timeout_seconds=600,
            command_digest=D)


def test_deserializer_rejects_list_subclass_and_allocates_exact_tuple():
    # A list subclass at the deserialization boundary is rejected...
    d = _snapshot().to_json_dict()
    d["staged_changes"] = _EvilList([])
    with pytest.raises(P09BValidationError):
        RepositorySnapshot.from_json_dict(d)
    # ...and a genuine exact JSON list round-trips into a NEW exact tuple.
    snap = RepositorySnapshot.from_json_dict(_snapshot().to_json_dict())
    assert is_exact_tuple(snap.changed_files)


def test_requirement_serialization_is_stable_across_calls():
    req = _requirement()
    assert canonical_json_bytes(req.to_json_dict()) == canonical_json_bytes(req.to_json_dict())


# ---------------------------------------------------------------------------
# B1-CODEX-003 - canonical repository paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "a\\b",                  # backslash is not a separator
    "a/./b",                 # '.' segment
    "a//b",                  # empty segment
    "./a",                   # leading '.'
    "/abs/path",             # absolute
    "é/file.py",       # non-NFC (decomposed 'e' + combining acute)
    "..",                    # parent
])
def test_repo_path_noncanonical_rejected(bad):
    with pytest.raises(P09BValidationError):
        validate_repo_path(bad, field="p")


def test_repo_path_canonical_returned_unchanged():
    assert validate_repo_path("src/a.py", field="p") == "src/a.py"


def test_slash_backslash_aliases_cannot_both_survive_in_collection():
    # ("a/b", "a\\b") must reject rather than survive as two distinct paths.
    with pytest.raises(P09BValidationError):
        _snapshot(changed=("a/b", "a\\b"))


def test_nfc_equivalent_path_alias_rejected_in_collection():
    with pytest.raises(P09BValidationError):
        _snapshot(changed=("src/é.py",))  # decomposed 'e' + combining acute


# ---------------------------------------------------------------------------
# B1-CODEX-004 - command-execution terminal-state matrix
# ---------------------------------------------------------------------------

def _exec(**kw):
    fields = dict(argv=("pytest",), exit_code=0, completed=True, timed_out=False,
                  interrupted=False, started_at=TS0, completed_at=TS1, duration_ms=1500,
                  stdout=b"ok", stderr=b"")
    fields.update(kw)
    return CommandExecutionResult(**fields)


def test_exec_valid_completed():
    assert _exec().completed is True


def test_exec_valid_timed_out():
    r = _exec(completed=False, timed_out=True, interrupted=False, exit_code=None)
    assert r.timed_out is True


def test_exec_valid_interrupted():
    r = _exec(completed=False, timed_out=False, interrupted=True, exit_code=None)
    assert r.interrupted is True


@pytest.mark.parametrize("flags,exit_code", [
    ((True, True, False), 0),     # completed AND timed_out
    ((True, False, True), 0),     # completed AND interrupted
    ((True, True, True), 0),      # all three
    ((False, True, True), None),  # timed_out AND interrupted
    ((False, False, False), 0),   # incomplete but exit code present
    ((False, False, False), None),  # no terminal state at all
    ((True, False, False), None),  # completed but no exit code
    ((False, True, False), 0),    # timed_out but exit code present
    ((False, False, True), 0),    # interrupted but exit code present
])
def test_exec_invalid_state_matrix_rejected(flags, exit_code):
    completed, timed_out, interrupted = flags
    with pytest.raises(P09BValidationError):
        _exec(completed=completed, timed_out=timed_out, interrupted=interrupted,
              exit_code=exit_code)


def test_exec_duration_must_match_timestamps():
    with pytest.raises(P09BValidationError):
        _exec(completed_at=TS_1S, duration_ms=7)  # 1000ms elapsed, 7ms claimed


def test_exec_bool_exit_code_rejected():
    with pytest.raises(P09BValidationError):
        _exec(exit_code=True)


# ---------------------------------------------------------------------------
# B1-CODEX-005 - dirty-state derived from snapshots
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pre_clean,post_clean,declared,ok", [
    (True, True, DirtyState.CLEAN, True),
    (True, True, DirtyState.DIRTY, False),
    (False, True, DirtyState.CLEAN, False),
    (False, True, DirtyState.DIRTY, True),
    (True, False, DirtyState.CLEAN, False),
    (True, False, DirtyState.DIRTY, True),
    (False, False, DirtyState.CLEAN, False),
    (False, False, DirtyState.DIRTY, True),
])
def test_collected_dirty_state_consistency(pre_clean, post_clean, declared, ok):
    def build():
        return _collected(prov=_provenance(dirty_state=declared),
                          pre_clean=pre_clean, post_clean=post_clean)
    if ok:
        assert build().provenance.dirty_state is declared
    else:
        with pytest.raises(P09BValidationError):
            build()


# ---------------------------------------------------------------------------
# B1-CODEX-006 - accepted result / bundle context binding
# ---------------------------------------------------------------------------

def test_accepted_result_candidate_snapshot_repo_mismatch_rejected():
    cand = _candidate(repository_id=D)     # repo D1
    snap = _snapshot(commit=cand.candidate_commit_sha, tree=cand.candidate_tree_sha,
                     base=cand.base_commit_sha, repository_id=D2)  # repo D2
    with pytest.raises(P09BValidationError):
        _accepted_result(candidate=cand, snapshot=snap)


def test_accepted_result_changed_files_mismatch_rejected():
    cand = _candidate(changed=("src/a.py", "src/b.py"))
    snap = _snapshot(commit=cand.candidate_commit_sha, tree=cand.candidate_tree_sha,
                     base=cand.base_commit_sha, changed=("src/a.py",))
    with pytest.raises(P09BValidationError):
        _accepted_result(candidate=cand, snapshot=snap)


def test_bundle_cross_task_rejected_in_rejected_entries():
    cand = _candidate()
    with pytest.raises(P09BValidationError):
        _bundle(task_id="BH-P0-A",
                verified=(_verified(task_id="BH-P0-A", candidate=cand),),
                rejected=(_rejected_result(evidence_id="ev-9", task_id="BH-P0-B"),),
                candidate=cand)


def test_bundle_verified_task_mismatch_rejected():
    cand = _candidate()
    with pytest.raises(P09BValidationError):
        _bundle(task_id="BH-P0-A", verified=(_verified(task_id="BH-P0-B", candidate=cand),),
                candidate=cand)


def test_binding_helper_reports_each_mismatched_field():
    cand = _candidate()
    snap = _snapshot(commit=SHA1_D, tree=SHA1_E, base=SHA1_C)
    mismatches = candidate_snapshot_mismatches(cand, snap)
    assert "candidate_commit_sha" in mismatches and "candidate_tree_sha" in mismatches


# ---------------------------------------------------------------------------
# B1-CODEX-007 - verification request graph consistency
# ---------------------------------------------------------------------------

def _request(**kw):
    fields = dict(
        task_id="BH-P0-B", requirements=(_requirement(),), candidate_binding=_candidate(),
        collected_evidence=(_collected(),), current_snapshot=_snapshot(),
        verifier_version="verifier-1", verified_at=TS0)
    fields.update(kw)
    return EvidenceVerificationRequest(**fields)


def test_request_valid_graph():
    assert _request().task_id == "BH-P0-B"


def test_request_duplicate_requirement_object_rejected():
    req = _requirement(req_id="req-1")
    with pytest.raises(P09BValidationError):
        _request(requirements=(req, req))


def test_request_cross_task_evidence_rejected():
    with pytest.raises(P09BValidationError):
        _request(task_id="BH-P0-A",
                 collected_evidence=(_collected(prov=_provenance(task_id="BH-P0-B")),))


def test_request_evidence_requirement_not_declared_rejected():
    with pytest.raises(P09BValidationError):
        _request(requirements=(_requirement(req_id="req-2"),),
                 collected_evidence=(_collected(prov=_provenance(req_id="req-1")),))


def test_request_candidate_current_snapshot_mismatch_rejected():
    with pytest.raises(P09BValidationError):
        _request(collected_evidence=(), current_snapshot=_snapshot(repository_id=D2))


def test_request_duplicate_evidence_id_rejected():
    ev = _collected(prov=_provenance(evidence_id="ev-1"))
    with pytest.raises(P09BValidationError):
        _request(collected_evidence=(ev, ev))


# ---------------------------------------------------------------------------
# B1-CODEX-008 - run record single-context binding + bundle linkage
# ---------------------------------------------------------------------------

def test_run_record_valid():
    assert _run_record().run_id == "run-1"


def test_run_record_cross_task_evidence_rejected():
    with pytest.raises(P09BValidationError):
        _run_record(task_id="BH-P0-A",
                    collected=(_collected(prov=_provenance(task_id="BH-P0-B")),),
                    bundle=None)


def test_run_record_cross_run_evidence_rejected():
    with pytest.raises(P09BValidationError):
        _run_record(run_id="run-2",
                    collected=(_collected(prov=_provenance(run_id="run-1")),),
                    bundle=None)


def test_run_record_cross_repo_final_snapshot_rejected():
    cand = _candidate()
    with pytest.raises(P09BValidationError):
        _run_record(candidate=cand, collected=(),
                    final_snapshot=_snapshot(commit=cand.candidate_commit_sha,
                                             tree=cand.candidate_tree_sha,
                                             base=cand.base_commit_sha, repository_id=D2),
                    bundle=None)


def test_run_record_bundle_task_mismatch_rejected():
    cand = _candidate()
    with pytest.raises(P09BValidationError):
        _run_record(task_id="BH-P0-B", candidate=cand, collected=(),
                    bundle=_bundle(candidate=cand, task_id="BH-P0-A"))


def test_bundle_round_trip_preserves_task_id():
    b = _bundle()
    again = EvidenceVerificationBundle.from_json_dict(b.to_json_dict())
    assert again.task_id == b.task_id == "BH-P0-B"
    assert canonical_json_bytes(again.to_json_dict()) == canonical_json_bytes(b.to_json_dict())


# ---------------------------------------------------------------------------
# B1-CODEX-009 - set-like diagnostics
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    ("STALE", "STALE"),       # duplicate
    ("B", "A"),               # unsorted
    ("",),                    # empty entry
    ("has\tcontrol",),        # control char
    ("has\x00nul",),          # NUL
])
def test_diagnostic_tuple_malformed_rejected(bad):
    with pytest.raises(P09BValidationError):
        require_sorted_unique_str_tuple(bad, field="reason_codes")


def test_diagnostic_tuple_sorted_unique_accepted():
    assert require_sorted_unique_str_tuple(("A", "B", "C"), field="reason_codes")


def test_result_rejects_duplicate_reason_codes():
    with pytest.raises(P09BValidationError):
        EvidenceVerificationResult(
            schema_version="p0-9b.verification.v1", accepted=False,
            status=VerificationStatus.STALE, reason_codes=("STALE", "STALE"),
            evidence_id="ev-1", run_id="run-1", task_id="BH-P0-B", candidate_binding=None,
            repository_snapshot=None, matched_requirement_id=None, claim_digest=D,
            verified_at=TS0, verifier_version="v", warnings=(), errors=())


def test_result_rejects_unsorted_errors():
    with pytest.raises(P09BValidationError):
        EvidenceVerificationResult(
            schema_version="p0-9b.verification.v1", accepted=False,
            status=VerificationStatus.STALE, reason_codes=("STALE",),
            evidence_id="ev-1", run_id="run-1", task_id="BH-P0-B", candidate_binding=None,
            repository_snapshot=None, matched_requirement_id=None, claim_digest=D,
            verified_at=TS0, verifier_version="v", warnings=(), errors=("b", "a"))


# ---------------------------------------------------------------------------
# B1-CODEX-010 - typed storage port
# ---------------------------------------------------------------------------

class _FakeRepository:
    def __init__(self):
        self._store: dict[tuple[str, str], EvidenceRunRecord] = {}

    def save_run(self, record: EvidenceRunRecord) -> Outcome[Unit, StorageError]:
        self._store[(record.task_id, record.run_id)] = record
        return Outcome.success(Unit())

    def load_run(self, task_id: str, run_id: str) -> Outcome[EvidenceRunRecord, StorageError]:
        record = self._store.get((task_id, run_id))
        if record is None:
            return Outcome.failure(StorageError(
                code=StorageErrorCode.NOT_FOUND, message="no such run"))
        return Outcome.success(record)


def test_fake_repository_satisfies_typed_protocol():
    repo = _FakeRepository()
    assert isinstance(repo, EvidenceRepository)


def test_storage_save_returns_unit_success():
    repo = _FakeRepository()
    saved = repo.save_run(_run_record())
    assert saved.is_success and type(saved.value) is Unit


def test_storage_missing_record_is_typed_not_found_not_exception():
    repo = _FakeRepository()
    result = repo.load_run("BH-P0-B", "run-404")
    assert not result.is_success
    assert result.error.code is StorageErrorCode.NOT_FOUND


def test_storage_round_trip_load_success():
    repo = _FakeRepository()
    record = _run_record()
    repo.save_run(record)
    loaded = repo.load_run(record.task_id, record.run_id)
    assert loaded.is_success and loaded.value is record


def test_storage_error_validates_code_and_message():
    with pytest.raises(P09BValidationError):
        StorageError(code="NOT_AN_ENUM", message="x")
    with pytest.raises(P09BValidationError):
        StorageError(code=StorageErrorCode.IO_ERROR, message="")


def test_unit_is_immutable_value():
    assert Unit() == Unit()  # frozen dataclass equality
    with pytest.raises(Exception):
        Unit().anything = 1  # type: ignore[attr-defined]  # frozen: no attributes settable


def test_outcome_allows_falsey_non_none_value():
    # A falsey-but-not-None success value stays representable (success is slot-based).
    assert Outcome.success(0).is_success
    assert Outcome.success(Unit()).is_success


def test_collected_candidate_helper_reports_mismatch():
    cand = _candidate()
    collected = _collected(prov=_provenance(commit_sha=SHA1_D, tree_sha=SHA1_E))
    mismatches = collected_candidate_mismatches(cand, collected)
    assert "candidate_commit_sha" in mismatches

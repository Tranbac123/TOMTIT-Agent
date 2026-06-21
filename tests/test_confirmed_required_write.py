from __future__ import annotations

import pytest

from agent_core.confirmation.errors import RequiredWriteConsistencyError
from agent_core.confirmation.required_write import (
    RequiredWriteOutcome,
    RequiredWriteStatus,
    validate_required_write_response,
)
from agent_core.memory.contracts import WriteResponse


def test_one_written_accepted():
    resp = WriteResponse(written_ids=["mem_1"], skipped=[])
    out = validate_required_write_response(resp, expected_candidate_id="conf-1")
    assert out == RequiredWriteOutcome(status=RequiredWriteStatus.WRITTEN, memory_id="mem_1")


def test_one_skipped_accepted():
    resp = WriteResponse(written_ids=[], skipped=["conf-1"])
    out = validate_required_write_response(resp, expected_candidate_id="conf-1")
    assert out.status is RequiredWriteStatus.SKIPPED_DUPLICATE
    assert out.memory_id is None


def test_empty_result_rejected():
    resp = WriteResponse(written_ids=[], skipped=[])
    with pytest.raises(RequiredWriteConsistencyError):
        validate_required_write_response(resp, expected_candidate_id="conf-1")


def test_written_and_skipped_together_rejected():
    resp = WriteResponse(written_ids=["mem_1"], skipped=["conf-1"])
    with pytest.raises(RequiredWriteConsistencyError):
        validate_required_write_response(resp, expected_candidate_id="conf-1")


def test_multiple_written_rejected():
    resp = WriteResponse(written_ids=["mem_1", "mem_2"], skipped=[])
    with pytest.raises(RequiredWriteConsistencyError):
        validate_required_write_response(resp, expected_candidate_id="conf-1")


def test_multiple_skipped_rejected():
    resp = WriteResponse(written_ids=[], skipped=["conf-1", "conf-2"])
    with pytest.raises(RequiredWriteConsistencyError):
        validate_required_write_response(resp, expected_candidate_id="conf-1")


def test_skipped_candidate_mismatch_rejected():
    resp = WriteResponse(written_ids=[], skipped=["other"])
    with pytest.raises(RequiredWriteConsistencyError):
        validate_required_write_response(resp, expected_candidate_id="conf-1")


def test_blank_written_memory_id_rejected():
    resp = WriteResponse(written_ids=["   "], skipped=[])
    with pytest.raises(RequiredWriteConsistencyError):
        validate_required_write_response(resp, expected_candidate_id="conf-1")


def test_blank_expected_candidate_id_rejected():
    resp = WriteResponse(written_ids=["mem_1"], skipped=[])
    with pytest.raises(RequiredWriteConsistencyError):
        validate_required_write_response(resp, expected_candidate_id="   ")

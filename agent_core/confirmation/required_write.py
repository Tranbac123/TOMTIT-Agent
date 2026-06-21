from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent_core.confirmation.errors import RequiredWriteConsistencyError
from agent_core.memory.contracts import WriteResponse


class RequiredWriteStatus(StrEnum):
    WRITTEN = "written"
    SKIPPED_DUPLICATE = "skipped_duplicate"


@dataclass(frozen=True)
class RequiredWriteOutcome:
    status: RequiredWriteStatus
    memory_id: str | None = None


def validate_required_write_response(
    response: WriteResponse,
    *,
    expected_candidate_id: str,
) -> RequiredWriteOutcome:
    """Reduce a one-candidate required-write response to a single domain outcome.

    Wire-level candidate correlation for written results is already proven by
    ``RemoteMemoryClient`` (frozen spec §10.2); this checker enforces the one-decision
    domain shape only.
    """
    written_ids = list(response.written_ids)
    skipped = list(response.skipped)

    if not isinstance(expected_candidate_id, str) or not expected_candidate_id.strip():
        raise RequiredWriteConsistencyError("expected_candidate_id must be nonblank")

    written_count = len(written_ids)
    skipped_count = len(skipped)

    if written_count and skipped_count:
        raise RequiredWriteConsistencyError(
            "response has both written and skipped results"
        )

    if written_count == 1 and skipped_count == 0:
        memory_id = written_ids[0]
        if not isinstance(memory_id, str) or not memory_id.strip():
            raise RequiredWriteConsistencyError("written memory_id is blank")
        return RequiredWriteOutcome(
            status=RequiredWriteStatus.WRITTEN,
            memory_id=memory_id,
        )

    if skipped_count == 1 and written_count == 0:
        if skipped[0] != expected_candidate_id:
            raise RequiredWriteConsistencyError(
                "skipped candidate_id differs from expected candidate_id"
            )
        return RequiredWriteOutcome(status=RequiredWriteStatus.SKIPPED_DUPLICATE)

    raise RequiredWriteConsistencyError(
        "required write response did not contain exactly one decision outcome"
    )

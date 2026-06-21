from __future__ import annotations

from dataclasses import dataclass

from agent_core.safety.evidence import EvidenceEnvelope


def confirmed_memory_request_id(confirmation_id: str) -> str:
    """Return the deterministic request ID for a confirmed-decision write.

    Format: ``memory-write:<confirmation_id>``. The formula intentionally does
    not include task_id or session_id (frozen spec §6.3).
    """
    if not isinstance(confirmation_id, str):
        raise ValueError("confirmation_id must be a string")
    normalized = confirmation_id.strip()
    if not normalized:
        raise ValueError("confirmation_id must be nonblank")
    return f"memory-write:{normalized}"


@dataclass(frozen=True)
class ConfirmedDecision:
    """One explicitly user-confirmed project decision (domain/run input, not a wire DTO).

    Trust/source/reference consistency of ``confirmation_evidence`` is validated by
    ``ConfirmedMemoryWritePolicy``; this model only enforces basic type/nonblank rules.
    """

    confirmation_id: str
    content: str
    confirmation_evidence: EvidenceEnvelope

    def __post_init__(self) -> None:
        if not isinstance(self.confirmation_id, str):
            raise ValueError("confirmation_id must be a string")
        confirmation_id = self.confirmation_id.strip()
        if not confirmation_id:
            raise ValueError("confirmation_id must be nonblank")

        if not isinstance(self.content, str):
            raise ValueError("content must be a string")
        # Strip leading/trailing whitespace; internal whitespace is preserved.
        content = self.content.strip()
        if not content:
            raise ValueError("content must be nonblank")

        if not isinstance(self.confirmation_evidence, EvidenceEnvelope):
            raise ValueError("confirmation_evidence must be an EvidenceEnvelope")

        object.__setattr__(self, "confirmation_id", confirmation_id)
        object.__setattr__(self, "content", content)


@dataclass(frozen=True)
class ConfirmedSaveOperation:
    """Immutable run-only envelope carrying exactly one confirmed decision.

    It carries neither ``project_id`` nor ``user_id`` and no planner/tool/Memory-wire/HTTP
    object. The same frozen instance is reused for any in-process retry, producing an
    identical request_id and candidate payload (replay-stable construction).
    """

    request_id: str
    task_id: str
    session_id: str | None
    decision: ConfirmedDecision

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str):
            raise ValueError("request_id must be a string")
        request_id = self.request_id.strip()
        if not request_id:
            raise ValueError("request_id must be nonblank")

        if not isinstance(self.task_id, str):
            raise ValueError("task_id must be a string")
        task_id = self.task_id.strip()
        if not task_id:
            raise ValueError("task_id must be nonblank")

        session_id = self.session_id
        if session_id is not None:
            if not isinstance(session_id, str):
                raise ValueError("session_id must be a string or None")
            session_id = session_id.strip()
            if not session_id:
                raise ValueError("session_id must be None or a nonblank string")

        if not isinstance(self.decision, ConfirmedDecision):
            raise ValueError("decision must be a ConfirmedDecision")

        expected_request_id = confirmed_memory_request_id(self.decision.confirmation_id)
        if request_id != expected_request_id:
            raise ValueError(
                "request_id must equal memory-write:<decision.confirmation_id>"
            )

        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "session_id", session_id)

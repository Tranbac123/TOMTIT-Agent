from __future__ import annotations

from agent_core.safety.evidence import EvidenceEnvelope
from agent_core.state.enums import SourceType, TrustLevel


def make_confirmation_evidence(
    *,
    task_id: str,
    confirmation_id: str,
    content: str,
) -> EvidenceEnvelope:
    """Build the trusted SF1 confirmation evidence for an explicit user decision.

    This is the only application-facing constructor for trusted confirmation evidence
    in M7-A. Callers may not supply trust/source enums or a raw source_ref; those are
    fixed here. The source reference is rendered from normalized identities.
    """
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a nonblank string")
    if not isinstance(confirmation_id, str) or not confirmation_id.strip():
        raise ValueError("confirmation_id must be a nonblank string")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a nonblank string")

    normalized_task_id = task_id.strip()
    normalized_confirmation_id = confirmation_id.strip()
    normalized_content = content.strip()

    return EvidenceEnvelope(
        content=normalized_content,
        source_type=SourceType.USER,
        trust_level=TrustLevel.TRUSTED_INSTRUCTION,
        source_ref=f"user-explicit:{normalized_task_id}:{normalized_confirmation_id}",
        metadata={"confirmation_id": normalized_confirmation_id},
    )

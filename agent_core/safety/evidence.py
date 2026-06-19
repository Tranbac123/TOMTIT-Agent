from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Union

from agent_core.state.enums import SourceType, TrustLevel

MetadataScalar = Union[str, int, float, bool, None]
MetadataValue = Union[MetadataScalar, "tuple[MetadataScalar, ...]"]


def _validate_metadata_value(value: object, key: str) -> MetadataValue:
    if value is None:
        return value
    # bool must be checked before int because bool is a subclass of int
    if type(value) in {bool, str, float}:
        return value  # type: ignore[return-value]
    if type(value) is int:
        return value
    if isinstance(value, tuple):
        validated: list[MetadataScalar] = []
        for i, elem in enumerate(value):
            if elem is None or type(elem) in {bool, str, float}:
                validated.append(elem)
            elif type(elem) is int:
                validated.append(elem)
            else:
                raise TypeError(
                    f"metadata[{key!r}][{i}]: tuple element must be a MetadataScalar, "
                    f"got {type(elem).__name__!r}"
                )
        return tuple(validated)
    raise TypeError(
        f"metadata[{key!r}]: value must be a MetadataScalar or tuple of MetadataScalar, "
        f"got {type(value).__name__!r}"
    )


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Immutable wrapper carrying a text payload with explicit trust and provenance."""

    content: str
    source_type: SourceType
    trust_level: TrustLevel
    source_ref: str | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise TypeError(f"content must be str, got {type(self.content).__name__!r}")
        if not isinstance(self.source_type, SourceType):
            raise TypeError(
                f"source_type must be SourceType, got {type(self.source_type).__name__!r}"
            )
        if not isinstance(self.trust_level, TrustLevel):
            raise TypeError(
                f"trust_level must be TrustLevel, got {type(self.trust_level).__name__!r}"
            )
        if self.source_ref is not None:
            if not isinstance(self.source_ref, str) or not self.source_ref.strip():
                raise ValueError("source_ref must be None or a non-blank string")

        # Validate and defensively copy metadata
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a Mapping")
        validated: dict[str, MetadataValue] = {}
        for k, v in self.metadata.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError(f"metadata key must be a non-blank string, got {k!r}")
            validated[k] = _validate_metadata_value(v, k)

        # Replace metadata with a read-only proxy of the validated copy
        object.__setattr__(self, "metadata", MappingProxyType(validated))


def tool_observation_ref(
    *,
    task_id: str,
    step_id: str,
    tool_name: str,
) -> str:
    """Return a stable source reference for a ToolExecutor observation.

    Format: task:<task_id>/step:<step_id>/tool:<tool_name>
    """
    parts = {"task_id": task_id, "step_id": step_id, "tool_name": tool_name}
    normalized: dict[str, str] = {}
    for name, value in parts.items():
        if not isinstance(value, str):
            raise TypeError(f"{name} must be str, got {type(value).__name__!r}")
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{name} must be a non-blank string")
        normalized[name] = stripped
    return (
        f"task:{normalized['task_id']}"
        f"/step:{normalized['step_id']}"
        f"/tool:{normalized['tool_name']}"
    )

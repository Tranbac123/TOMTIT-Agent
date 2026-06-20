from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.state.enums import SourceType, TrustLevel
from agent_core.tools.schemas import Source


@dataclass
class Observation:
    step_index: int
    action: str
    args: dict[str, Any]
    success: bool
    trust_level: TrustLevel
    source_type: SourceType
    source_ref: str | None
    output: Any = None
    error: str | None = None
    sources: list[Source] = field(default_factory=list)

from __future__ import annotations

from typing import Protocol

from agent_core.state.agent_state import Step


class Skill(Protocol):
    def make_steps(self) -> list[Step]: ...

from __future__ import annotations

from agent_core.runtime.runtime_agent import build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime
from agent_core.cli import run_interactive


def main() -> None:
    agent, store = build_local_agent()
    session = SessionRuntime(agent, store)
    run_interactive(session)


if __name__ == "__main__":
    main()

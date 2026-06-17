from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from uuid import uuid4

from agent_core.cli import run_interactive
from agent_core.runtime.runtime_agent import build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime
from agent_core.session_persistence import (
    FileSessionStore,
    SessionDataCorruptionError,
    SessionNotFoundError,
    SessionPersistenceError,
)
from agent_core.state.session_state import SessionState


def main() -> None:
    parser = argparse.ArgumentParser(description="TOMTIT Agent — interactive session")
    parser.add_argument(
        "--session-id",
        default=None,
        metavar="UUID",
        help="resume an existing session by ID",
    )
    parser.add_argument(
        "--session-db",
        default=".agent/sessions",
        metavar="PATH",
        help="directory for session files (default: .agent/sessions)",
    )
    args = parser.parse_args()

    agent, store = build_local_agent()
    session_store = FileSessionStore(args.session_db)

    # BOUNDARY 1 — create or load session (before task)
    try:
        if args.session_id is not None:
            loaded = session_store.load(args.session_id)
            if loaded is None:
                raise SessionNotFoundError(
                    f"Session '{args.session_id}' not found in {args.session_db!r}"
                )
            session_state = loaded
        else:
            now = datetime.now(timezone.utc)
            session_state = SessionState(
                session_id=str(uuid4()),
                created_at=now,
                updated_at=now,
            )
    except SessionNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    except SessionDataCorruptionError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    except SessionPersistenceError:
        print("Unable to create or load durable session", file=sys.stderr)
        sys.exit(1)

    sr = SessionRuntime(agent, store, session=session_state, session_store=session_store)

    # BOUNDARY 2 — run interactive session (after task)
    try:
        run_interactive(sr)
    except (SessionPersistenceError, SessionDataCorruptionError):
        print(
            "Task may have executed, but turn was not persisted. "
            "Do not retry automatically.",
            file=sys.stderr,
        )
        sys.exit(1)
    # Unexpected exceptions propagate


if __name__ == "__main__":
    main()

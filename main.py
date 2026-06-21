from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from uuid import UUID, uuid4

from agent_core.cli import run_interactive
from agent_core.memory.errors import RemoteMemoryConfigurationError
from agent_core.memory.factory import MemoryBackendConfig
from agent_core.runtime.runtime_agent import build_agent_with_memory_backend, build_local_agent
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
        "--session-dir",
        default=".agent/sessions",
        metavar="PATH",
        help="directory for session files (default: .agent/sessions)",
    )
    parser.add_argument(
        "--memory-backend",
        default=os.environ.get("TOMTIT_MEMORY_BACKEND", "local"),
        choices=("local", "remote", "none"),
        help="memory backend: local, remote, or none",
    )
    parser.add_argument(
        "--memory-base-url",
        default=os.environ.get("TOMTIT_MEMORY_BASE_URL"),
        help="TOMTIT-Memory base URL for remote backend",
    )
    parser.add_argument(
        "--memory-project-id",
        default=os.environ.get("TOMTIT_MEMORY_PROJECT_ID"),
        help="TOMTIT-Memory project_id for remote backend",
    )
    parser.add_argument(
        "--memory-user-id",
        default=os.environ.get("TOMTIT_MEMORY_USER_ID"),
        help="default TOMTIT-Memory user_id for remote backend",
    )
    parser.add_argument(
        "--memory-timeout-seconds",
        type=float,
        default=float(os.environ.get("TOMTIT_MEMORY_TIMEOUT_SECONDS", "5.0")),
        help="remote memory HTTP timeout in seconds",
    )
    args = parser.parse_args()

    # Validate session_id format before expensive composition
    if args.session_id is not None:
        try:
            UUID(args.session_id)
        except ValueError:
            print(f"Invalid session ID: {args.session_id!r}", file=sys.stderr)
            sys.exit(2)

    try:
        if args.memory_backend == "local":
            agent, store = build_local_agent()
        else:
            memory_config = MemoryBackendConfig.from_values(
                backend=args.memory_backend,
                base_url=args.memory_base_url,
                project_id=args.memory_project_id,
                default_user_id=args.memory_user_id,
                timeout_seconds=args.memory_timeout_seconds,
            )
            agent, store = build_agent_with_memory_backend(memory_config=memory_config)
    except RemoteMemoryConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    session_store = FileSessionStore(args.session_dir)

    # BOUNDARY 1 — create or load session (before task)
    try:
        if args.session_id is not None:
            loaded = session_store.load(args.session_id)
            if loaded is None:
                raise SessionNotFoundError(
                    f"Session '{args.session_id}' not found in {args.session_dir!r}"
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

    # Pass the application-owned memory user identity (remote backend) into SessionRuntime
    # so M7-A confirmed saves use an explicit identity, never one inferred at runtime.
    sr = SessionRuntime(
        agent,
        store,
        session=session_state,
        session_store=session_store,
        user_id=args.memory_user_id,
    )

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

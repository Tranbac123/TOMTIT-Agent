from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from agent_core.confirmation.evidence_factory import make_confirmation_evidence
from agent_core.confirmation.models import (
    ConfirmedDecision,
    ConfirmedSaveOperation,
    confirmed_memory_request_id,
)

_SAVE_DECISION_COMMAND = "/memory save-decision"
_SAVE_FAILED_MESSAGE = "Decision was not saved."
_RECALL_COMMAND = "/memory recall"
_RECALL_FAILED_MESSAGE = "Decision recall failed."


def should_exit(user_input: str) -> bool:
    return user_input.strip() in ("/exit", "quit", "")


def handle_save_decision(
    session,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> None:
    """Structured confirmed-decision save boundary (SPEC §16).

    Application-owned: the model/planner never see this path. Collects explicit content,
    requires a positive confirmation, then constructs the trusted evidence/operation here
    and delegates to the dedicated SessionRuntime save method. ``user_id`` is supplied by
    composition (not generated here)."""
    try:
        content = input_fn("Decision: ")
        confirm = None
        if content and content.strip():
            confirm = input_fn("Confirm save? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        output_fn("Đã hủy lưu quyết định.")
        return

    if not content or not content.strip():
        output_fn("Đã hủy lưu quyết định: nội dung trống.")
        return
    if confirm is None or confirm.strip().lower() not in ("y", "yes"):
        output_fn("Đã hủy lưu quyết định.")
        return

    confirmation_id = str(uuid4())
    task_id = str(uuid4())
    evidence = make_confirmation_evidence(
        task_id=task_id, confirmation_id=confirmation_id, content=content
    )
    decision = ConfirmedDecision(
        confirmation_id=confirmation_id,
        content=content,
        confirmation_evidence=evidence,
    )
    operation = ConfirmedSaveOperation(
        request_id=confirmed_memory_request_id(confirmation_id),
        task_id=task_id,
        session_id=session.session_id,
        decision=decision,
    )

    try:
        state = session.run_confirmed_decision_save(operation)
    except ValueError:
        # e.g. no application-owned user_id (confirmed save is remote-only); fail safely.
        output_fn(_SAVE_FAILED_MESSAGE)
        return

    output_fn(state.final_answer if state.final_answer else _SAVE_FAILED_MESSAGE)


def handle_recall(
    session,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    *,
    inline_query: str | None = None,
) -> None:
    """Structured cross-process recall boundary (SPEC_M7B §11.1).

    Read-only and application-owned: intercepted before ``handle_turn`` so it never enters
    the planner/tools/skills. Prompts for one nonblank query (interactive primary shape) or
    uses an inline query; a blank query cancels with zero remote call. Only the deterministic
    safe message is shown — never raw backend text."""
    query = inline_query
    if query is None or not query.strip():
        try:
            query = input_fn("Recall query: ")
        except (EOFError, KeyboardInterrupt):
            output_fn("Đã hủy recall.")
            return

    if not query or not query.strip():
        output_fn("Đã hủy recall: truy vấn trống.")
        return

    state = session.run_memory_recall(query.strip())
    output_fn(state.final_answer if state.final_answer else _RECALL_FAILED_MESSAGE)


def run_interactive(
    session,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> None:
    output_fn(f"Session: {session.session_id}")
    while True:
        try:
            user_input = input_fn("You: ")
        except (EOFError, KeyboardInterrupt):
            output_fn("\nPhiên kết thúc.")
            break
        if should_exit(user_input):
            output_fn("Phiên kết thúc.")
            break
        stripped = user_input.strip()
        if stripped == _SAVE_DECISION_COMMAND:       # structured save — never enters planner
            handle_save_decision(session, input_fn, output_fn)
            continue
        if stripped == _RECALL_COMMAND:              # structured recall — never enters planner
            handle_recall(session, input_fn, output_fn)
            continue
        if stripped.startswith(_RECALL_COMMAND + " "):  # inline convenience form
            inline = stripped[len(_RECALL_COMMAND):].strip()
            handle_recall(session, input_fn, output_fn, inline_query=inline)
            continue
        if stripped == "/status":                   # meta-command — chặn trước handle_turn
            view = session.get_status()
            output_fn(f"[status] turns={view.turn_count} last={view.last_status}")
            continue
        if stripped == "/history":
            history = session.get_history()
            if not history:
                output_fn("[history] no turns")
            else:
                for rec in history:
                    output_fn(
                        f"[{rec.completed_at.isoformat()}] {rec.goal} -> {rec.status.value}"
                    )
            continue
        result = session.handle_turn(user_input)
        output_fn(result.final_answer)
    # unexpected exceptions from handle_turn propagate — NOT caught here

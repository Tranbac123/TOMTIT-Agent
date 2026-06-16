from __future__ import annotations

from collections.abc import Callable


def should_exit(user_input: str) -> bool:
    return user_input.strip() in ("/exit", "quit", "")


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

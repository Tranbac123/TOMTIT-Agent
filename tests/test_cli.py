from __future__ import annotations

from types import SimpleNamespace

from agent_core.cli import handle_save_decision, run_interactive


class _FakeSession:
    def __init__(self):
        self.session_id = "sess-1"
        self.saved_ops = []
        self.handled_turns = []

    def handle_turn(self, message):
        self.handled_turns.append(message)
        return SimpleNamespace(final_answer=f"turn:{message}")

    def run_confirmed_decision_save(self, operation):
        self.saved_ops.append(operation)
        ref = operation.decision.confirmation_evidence.source_ref
        return SimpleNamespace(
            final_answer=f"Decision saved.\nMemory ID: mem_1\nProvenance: {ref}",
            status=None,
        )

    def get_status(self):  # pragma: no cover - not used here
        return SimpleNamespace(turn_count=0, last_status=None)

    def get_history(self):  # pragma: no cover
        return ()


def _scripted(lines):
    it = iter(lines)

    def _input(_prompt: str) -> str:
        return next(it)

    return _input


def _collector():
    out = []
    return out, (lambda s: out.append(s))


def test_save_decision_positive_confirmation_creates_operation():
    session = _FakeSession()
    out, output_fn = _collector()
    run_interactive(
        session,
        input_fn=_scripted(["/memory save-decision", "use postgres", "y", "/exit"]),
        output_fn=output_fn,
    )
    assert len(session.saved_ops) == 1
    op = session.saved_ops[0]
    assert op.decision.content == "use postgres"
    assert op.session_id == "sess-1"
    assert op.request_id == f"memory-write:{op.decision.confirmation_id}"
    assert op.task_id  # app-generated, nonblank
    assert op.decision.confirmation_id  # app-generated, nonblank
    # handle_turn (natural-language planner route) must NOT have run
    assert session.handled_turns == []
    assert any("Decision saved." in line for line in out)


def test_save_decision_negative_confirmation_zero_write():
    session = _FakeSession()
    out, output_fn = _collector()
    run_interactive(
        session,
        input_fn=_scripted(["/memory save-decision", "use postgres", "n", "/exit"]),
        output_fn=output_fn,
    )
    assert session.saved_ops == []
    assert session.handled_turns == []


def test_save_decision_blank_content_zero_write():
    session = _FakeSession()
    out, output_fn = _collector()
    run_interactive(
        session,
        input_fn=_scripted(["/memory save-decision", "   ", "/exit"]),
        output_fn=output_fn,
    )
    assert session.saved_ops == []


def test_natural_language_remember_does_not_trigger_save():
    session = _FakeSession()
    out, output_fn = _collector()
    run_interactive(
        session,
        input_fn=_scripted(["Remember that we use PostgreSQL.", "/exit"]),
        output_fn=output_fn,
    )
    assert session.saved_ops == []
    assert session.handled_turns == ["Remember that we use PostgreSQL."]


def test_handle_save_decision_only_yes_proceeds():
    session = _FakeSession()
    out, output_fn = _collector()
    handle_save_decision(session, _scripted(["use postgres", "yes"]), output_fn)
    assert len(session.saved_ops) == 1


def test_handle_save_decision_missing_user_id_fails_safely():
    class _NoUserSession(_FakeSession):
        def run_confirmed_decision_save(self, operation):
            raise ValueError("requires an application-owned user_id")

    session = _NoUserSession()
    out, output_fn = _collector()
    handle_save_decision(session, _scripted(["use postgres", "y"]), output_fn)
    assert out[-1] == "Decision was not saved."

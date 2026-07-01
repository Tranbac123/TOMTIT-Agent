"""CONV-P0 P0-6B — pending note slot continuation tests.

Covers:
  - pending state creation for "ghi chú về tôi: <content>"
  - two-turn flow: ask note_name → write note → read back
  - parser false positive fix: note_name != "về"
  - cancellation (hủy / bỏ qua / không / thôi / cancel)
  - ambiguous ack reprompt (ok / có) without writing
  - unrelated high-confidence commands clear pending
  - new full note command clears old pending
  - session isolation (independent per SessionRuntime instance)
  - user-profile memory non-goal: no fake memory for "lưu tên tôi là Bắc"
  - existing note commands still work
"""
from __future__ import annotations

import pytest

from agent_core.memory.in_memory_store import InMemoryStore
from agent_core.planning.intent_parser import RuleBasedIntentParser
from agent_core.planning.slot_validator import SlotValidator
from agent_core.planning.intents import IntentName
from agent_core.runtime.runtime_agent import build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime
from agent_core.state.enums import AgentStatus


def _make_sr() -> SessionRuntime:
    agent, store = build_local_agent()
    return SessionRuntime(agent, store)


# ---------------------------------------------------------------------------
# 1. Pending state created for "ghi chú về tôi: <content>"
# ---------------------------------------------------------------------------

def test_pending_note_slot_created_for_about_me_note():
    sr = _make_sr()
    state = sr.handle_turn("Lưu ghi chú về tôi: tôi tên là Bắc")

    assert state.status == AgentStatus.COMPLETED
    # Should ask for note name, NOT write yet
    assert "tên ghi chú" in state.final_answer.lower() or "ghi chú" in state.final_answer.lower()
    # Pending state must be set
    pending = sr._pending_conversation_state
    assert pending is not None
    assert pending.kind == "write_note_missing_note_name"
    assert pending.collected_slots["content"] == "tôi tên là Bắc"
    assert "note_name" in pending.missing_slots


# ---------------------------------------------------------------------------
# 2. Short slot answer writes note and clears pending
# ---------------------------------------------------------------------------

def test_pending_note_short_answer_writes_note_and_clears_pending():
    sr = _make_sr()
    sr.handle_turn("Lưu ghi chú về tôi: tôi tên là Bắc")

    state = sr.handle_turn("Bắc")

    assert state.status == AgentStatus.COMPLETED
    assert sr._pending_conversation_state is None
    # Answer should mention the note name and content
    answer = state.final_answer
    assert "Bắc" in answer
    assert "tôi tên là Bắc" in answer


# ---------------------------------------------------------------------------
# 3. Parser fix: note NOT named "về"
# ---------------------------------------------------------------------------

def test_corrected_about_me_note_does_not_write_note_named_ve():
    parser = RuleBasedIntentParser()
    validator = SlotValidator()

    parsed = validator.validate(
        parser.parse("Lưu ghi chú về tôi: tôi tên là Bắc")
    )
    assert parsed.intent == IntentName.WRITE_NOTE
    assert parsed.note_name is None, (
        f"Expected note_name=None, got {parsed.note_name!r}; "
        "'về' must not be captured as note_name"
    )
    assert parsed.content == "tôi tên là Bắc"
    assert "note_name" in parsed.missing_slots

    # Typo variant "ghi chứ"
    parsed_typo = validator.validate(
        parser.parse("Lưu ghi chứ về tôi: tôi tên là Bắc")
    )
    assert parsed_typo.note_name is None
    assert parsed_typo.content == "tôi tên là Bắc"


# ---------------------------------------------------------------------------
# 4. Read-back after two-turn flow returns original content
# ---------------------------------------------------------------------------

def test_pending_note_read_back_returns_original_content():
    sr = _make_sr()
    sr.handle_turn("Lưu ghi chú về tôi: tôi tên là Bắc")
    sr.handle_turn("Bắc")

    # Read back
    state = sr.handle_turn("Đọc ghi chú Bắc")
    assert state.status == AgentStatus.COMPLETED
    assert "tôi tên là Bắc" in state.final_answer


# ---------------------------------------------------------------------------
# 5. Cancellation clears pending without writing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cancel_text", ["hủy", "bỏ qua", "không", "thôi", "cancel"])
def test_pending_cancel_clears_without_writing(cancel_text):
    sr = _make_sr()
    sr.handle_turn("Lưu ghi chú về tôi: tôi tên là Bắc")

    state = sr.handle_turn(cancel_text)

    assert state.status == AgentStatus.COMPLETED
    assert sr._pending_conversation_state is None
    # Cancellation message must not claim a note was written
    answer = state.final_answer.lower()
    assert "hủy" in answer or "cancel" in answer.lower()
    assert "đã lưu" not in answer

    # Verify no note was written under any likely key
    read_state = sr.handle_turn("Đọc ghi chú Bắc")
    assert "not found" in read_state.final_answer.lower() or "không tìm" in read_state.final_answer.lower()


# ---------------------------------------------------------------------------
# 6. Ambiguous ack (ok / có) reprompts without writing note
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ack_text", ["ok", "có"])
def test_pending_ok_or_co_reprompts_without_writing(ack_text):
    sr = _make_sr()
    sr.handle_turn("Lưu ghi chú về tôi: tôi tên là Bắc")

    state = sr.handle_turn(ack_text)

    assert state.status == AgentStatus.COMPLETED
    # Pending must still be set (not cleared by ambiguous ack)
    assert sr._pending_conversation_state is not None
    # Answer should be a reprompt, not a write confirmation
    assert "đã lưu" not in state.final_answer.lower()

    # No note written
    read_state = sr.handle_turn("Đọc ghi chú Bắc")
    assert "tôi tên là Bắc" not in read_state.final_answer


# ---------------------------------------------------------------------------
# 7. Unrelated high-confidence identity command clears pending and answers identity
# ---------------------------------------------------------------------------

def test_pending_unrelated_identity_clears_and_answers_identity():
    sr = _make_sr()
    sr.handle_turn("Lưu ghi chú về tôi: tôi tên là Bắc")

    state = sr.handle_turn("bạn là ai?")

    assert state.status == AgentStatus.COMPLETED
    assert sr._pending_conversation_state is None
    assert "TomTit" in state.final_answer or "TOMTIT" in state.final_answer
    # No note written
    read_state = sr.handle_turn("Đọc ghi chú Bắc")
    assert "tôi tên là Bắc" not in read_state.final_answer


# ---------------------------------------------------------------------------
# 8. Unrelated calculator command clears pending and calculates
# ---------------------------------------------------------------------------

def test_pending_unrelated_calculator_clears_and_calculates():
    sr = _make_sr()
    sr.handle_turn("Lưu ghi chú về tôi: tôi tên là Bắc")

    state = sr.handle_turn("calculate 2 + 2")

    assert state.status == AgentStatus.COMPLETED
    assert sr._pending_conversation_state is None
    assert "4" in state.final_answer
    # No note written under pending content
    read_state = sr.handle_turn("Đọc ghi chú Bắc")
    assert "tôi tên là Bắc" not in read_state.final_answer


# ---------------------------------------------------------------------------
# 9. New full note command replaces / clears old pending
# ---------------------------------------------------------------------------

def test_new_full_note_command_replaces_or_clears_old_pending():
    sr = _make_sr()
    sr.handle_turn("Lưu ghi chú về tôi: tôi tên là Bắc")
    assert sr._pending_conversation_state is not None

    # New complete note command — should NOT write old pending content
    sr.handle_turn("Lưu ghi chú project hôm nay test P0")
    assert sr._pending_conversation_state is None

    # The old pending content must NOT appear under any note
    read_old = sr.handle_turn("Đọc ghi chú Bắc")
    assert "tôi tên là Bắc" not in read_old.final_answer


# ---------------------------------------------------------------------------
# 10. Pending state isolated between SessionRuntime instances
# ---------------------------------------------------------------------------

def test_pending_state_isolated_between_session_runtime_instances():
    sr1 = _make_sr()
    sr2 = _make_sr()

    # Only sr1 receives the about-me note command
    sr1.handle_turn("Lưu ghi chú về tôi: tôi tên là Bắc")

    assert sr1._pending_conversation_state is not None, "sr1 should have pending state"
    assert sr2._pending_conversation_state is None, "sr2 must be isolated — no pending"

    # Resolving sr1 does NOT affect sr2
    sr1.handle_turn("Bắc")
    assert sr1._pending_conversation_state is None
    assert sr2._pending_conversation_state is None


# ---------------------------------------------------------------------------
# 11. No user-profile memory is faked for "lưu tên tôi là Bắc"
# ---------------------------------------------------------------------------

def test_no_user_profile_memory_is_faked_for_luu_ten_toi_la_bac():
    sr = _make_sr()

    # "lưu tên tôi là Bắc" — content is unknown (no "ghi chú" keyword with colon content)
    # Should NOT create pending with content="tên tôi là Bắc" because content is not parsed.
    sr.handle_turn("lưu tên tôi là Bắc")
    # Even if pending was created (for a partial note), it must NOT claim profile memory.
    # The key invariant: any subsequent read-back for user identity must NOT fabricate memory.

    state = sr.handle_turn("bạn nhớ tôi tên gì không?")
    answer = state.final_answer.lower()
    # Must NOT claim it saved or knows user identity
    assert "bắc" not in answer or "chưa" in answer or "không" in answer, (
        f"Must not fabricate user-profile memory. Got: {state.final_answer!r}"
    )
    assert "đã lưu tên" not in answer
    assert "tên bạn là bắc" not in answer


# ---------------------------------------------------------------------------
# 12. Existing note commands (without "về tôi") still work correctly
# ---------------------------------------------------------------------------

def test_existing_note_commands_still_work():
    sr = _make_sr()

    # Normal write_note with explicit note_name and content (no colon/about-me guard)
    write_state = sr.handle_turn("Lưu ghi chú project hôm nay test P0")
    assert write_state.status == AgentStatus.COMPLETED
    # No pending state (all slots known)
    assert sr._pending_conversation_state is None

    # Read back the note — the parser for "Lưu ghi chú project <content>" uses
    # the existing regex where note_name may include the trailing colon or not.
    # We verify the read path using the full list_notes / read_note tool.
    list_state = sr.handle_turn("Đọc ghi chú project")
    # The note was written with key "project" (no colon variant — space-separated)
    assert list_state.status == AgentStatus.COMPLETED
    assert "hôm nay test P0" in list_state.final_answer

    # A different normal session: write with explicit slots, read back
    sr2 = _make_sr()
    sr2.handle_turn("Lưu ghi chú budget 1000")
    read = sr2.handle_turn("Đọc ghi chú budget")
    assert "1000" in read.final_answer

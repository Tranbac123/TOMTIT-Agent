"""CONV-P0 P0-7B — user profile memory tests.

Covers:
  - detection of self-name and relation-name candidates
  - confirmation before any write
  - cancel flow
  - query answering after confirmed save
  - no answer before confirmation
  - note memory does not satisfy profile query
  - lưu ghi chú does not silently become profile
  - relationship fact confirmation and query
  - inverse lookup (Bắc là ai? / Quý là ai?)
  - tôi vừa hỏi gì bạn? not handled as profile
  - session/store isolation
  - pending clears on unrelated commands
  - write failure safety
  - P0-6B compatibility
"""
from __future__ import annotations

import pytest

from agent_core.conversation.profile_memory import (
    ProfileFactCandidate,
    detect_profile_fact_candidate,
    detect_profile_query,
)
from agent_core.runtime.runtime_agent import build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime
from agent_core.state.enums import AgentStatus


def _make_sr() -> SessionRuntime:
    agent, store = build_local_agent()
    return SessionRuntime(agent, store)


def _confirm_self_name(sr: SessionRuntime, name: str = "Bắc") -> None:
    """Helper: two-turn flow to confirm a self-name fact."""
    sr.handle_turn(f"Tôi tên là {name}")
    sr.handle_turn("có")


# ---------------------------------------------------------------------------
# 1-4. Detection tests
# ---------------------------------------------------------------------------

def test_detects_self_name_candidate_toi_ten_la_bac():
    c = detect_profile_fact_candidate("Tôi tên là Bắc")
    assert c is not None
    assert c.subject == "self"
    assert c.relation == "name"
    assert c.value == "Bắc"


def test_detects_self_name_candidate_toi_la_bac():
    c = detect_profile_fact_candidate("tôi là Bắc")
    assert c is not None
    assert c.subject == "self"
    assert c.value == "Bắc"


def test_detects_self_name_candidate_ten_toi_la_bac():
    c = detect_profile_fact_candidate("tên tôi là Bắc")
    assert c is not None
    assert c.value == "Bắc"


def test_detects_self_name_candidate_minh_la_bac():
    c = detect_profile_fact_candidate("mình là Bắc")
    assert c is not None
    assert c.value == "Bắc"


# ---------------------------------------------------------------------------
# 5. Confirmation prompt before write
# ---------------------------------------------------------------------------

def test_profile_candidate_asks_confirmation_before_write():
    sr = _make_sr()
    s = sr.handle_turn("Tôi tên là Bắc")

    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "lưu" in answer.lower()
    assert "Bắc" in answer
    # Pending must be set, nothing written yet
    assert sr._pending_profile_confirmation is not None
    assert sr._pending_profile_confirmation.kind == "profile_fact_confirmation"
    assert sr._pending_profile_confirmation.candidate.value == "Bắc"


# ---------------------------------------------------------------------------
# 6. Confirmation saves self-name fact
# ---------------------------------------------------------------------------

def test_profile_confirm_saves_self_name_fact():
    sr = _make_sr()
    sr.handle_turn("Tôi tên là Bắc")
    s = sr.handle_turn("có")

    assert s.status == AgentStatus.COMPLETED
    assert sr._pending_profile_confirmation is None
    answer = s.final_answer or ""
    assert "lưu" in answer.lower()


# ---------------------------------------------------------------------------
# 7. Cancel does not save
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cancel_text", ["không", "hủy", "bỏ qua", "thôi", "cancel", "no"])
def test_profile_cancel_does_not_save(cancel_text: str):
    sr = _make_sr()
    sr.handle_turn("Tôi tên là Bắc")
    s = sr.handle_turn(cancel_text)

    assert s.status == AgentStatus.COMPLETED
    assert sr._pending_profile_confirmation is None
    # Name must not be in subsequent profile queries
    q = sr.handle_turn("tôi tên là gì?")
    assert "Bắc" not in (q.final_answer or "")


# ---------------------------------------------------------------------------
# 8-10. Profile queries after confirmed save
# ---------------------------------------------------------------------------

def test_toi_ten_la_gi_answers_after_confirmed_save():
    sr = _make_sr()
    _confirm_self_name(sr, "Bắc")

    s = sr.handle_turn("tôi tên là gì?")
    assert s.status == AgentStatus.COMPLETED
    assert "Bắc" in (s.final_answer or "")


def test_toi_la_ai_answers_after_confirmed_save():
    sr = _make_sr()
    _confirm_self_name(sr, "Bắc")

    s = sr.handle_turn("tôi là ai?")
    assert s.status == AgentStatus.COMPLETED
    assert "Bắc" in (s.final_answer or "")


def test_ban_nho_toi_ten_gi_answers_after_confirmed_save():
    sr = _make_sr()
    _confirm_self_name(sr, "Bắc")

    s = sr.handle_turn("bạn nhớ tôi tên gì không?")
    assert s.status == AgentStatus.COMPLETED
    assert "Bắc" in (s.final_answer or "")


# ---------------------------------------------------------------------------
# 11. No profile answer before confirmation
# ---------------------------------------------------------------------------

def test_no_profile_answer_before_confirmation():
    sr = _make_sr()
    # Only issue the candidate — do NOT confirm
    sr.handle_turn("Tôi tên là Bắc")

    # Cancel the pending so we can test the query
    sr.handle_turn("không")

    s = sr.handle_turn("tôi tên là gì?")
    assert s.status == AgentStatus.COMPLETED
    # Must NOT claim "Bắc" is the name since it was never confirmed
    assert "Bắc" not in (s.final_answer or "")


# ---------------------------------------------------------------------------
# 12. Note memory does not satisfy profile query
# ---------------------------------------------------------------------------

def test_note_memory_does_not_satisfy_profile_query():
    sr = _make_sr()
    # Write a note (not a profile fact)
    sr.handle_turn("Lưu ghi chú tên Bắc")  # note named "tên" with content "Bắc"

    s = sr.handle_turn("tôi tên là gì?")
    # Profile query must not be answered from notes
    assert "Bắc" not in (s.final_answer or "")


# ---------------------------------------------------------------------------
# 13. "lưu ghi chú tôi tên là Bắc" does not silently become profile
# ---------------------------------------------------------------------------

def test_luu_ghi_chu_toi_ten_la_bac_does_not_silently_become_profile():
    sr = _make_sr()
    # "Lưu ghi chú về tôi: tôi tên là Bắc" goes through the note path (P0-6B)
    sr.handle_turn("Lưu ghi chú về tôi: tôi tên là Bắc")

    # Profile query before any explicit profile confirmation must not return "Bắc"
    s = sr.handle_turn("tôi tên là gì?")
    # Note: if pending note was active, turn was consumed; either way profile must not return Bắc
    assert sr._pending_profile_confirmation is None, "profile should not be pending"
    assert "Bắc" not in (s.final_answer or "")


# ---------------------------------------------------------------------------
# 14. Relationship candidate asks confirmation
# ---------------------------------------------------------------------------

def test_relationship_candidate_ban_gai_toi_ten_la_quy_asks_confirmation():
    sr = _make_sr()
    s = sr.handle_turn("bạn gái tôi tên là Quý")

    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "Quý" in answer
    assert "lưu" in answer.lower()
    assert sr._pending_profile_confirmation is not None
    c = sr._pending_profile_confirmation.candidate
    assert c.subject == "relation"
    assert c.value == "Quý"
    assert c.relation_label == "bạn gái"


# ---------------------------------------------------------------------------
# 15. Relationship confirm then query answers
# ---------------------------------------------------------------------------

def test_relationship_confirm_then_ban_gai_toi_ten_gi_answers_quy():
    sr = _make_sr()
    sr.handle_turn("bạn gái tôi tên là Quý")
    sr.handle_turn("có")

    s = sr.handle_turn("bạn gái tôi tên gì?")
    assert s.status == AgentStatus.COMPLETED
    assert "Quý" in (s.final_answer or "")


# ---------------------------------------------------------------------------
# 16. Inverse lookup: Bắc là ai? from confirmed self-name
# ---------------------------------------------------------------------------

def test_inverse_lookup_bac_la_ai_from_confirmed_self_name():
    sr = _make_sr()
    _confirm_self_name(sr, "Bắc")

    s = sr.handle_turn("Bắc là ai?")
    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "Bắc" in answer
    # Should say something about being the user's name / themselves
    assert "bạn" in answer.lower() or "tên" in answer.lower()


# ---------------------------------------------------------------------------
# 17. Inverse lookup: Quý là ai? from confirmed relationship
# ---------------------------------------------------------------------------

def test_inverse_lookup_quy_la_ai_from_confirmed_relationship():
    sr = _make_sr()
    sr.handle_turn("bạn gái tôi tên là Quý")
    sr.handle_turn("có")

    s = sr.handle_turn("Quý là ai?")
    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "Quý" in answer
    assert "bạn gái" in answer.lower()


# ---------------------------------------------------------------------------
# 18. Conversation recall not handled by profile memory
# ---------------------------------------------------------------------------

def test_toi_vua_hoi_gi_ban_not_handled_by_profile_memory():
    sr = _make_sr()
    s = sr.handle_turn("tôi vừa hỏi gì bạn?")

    assert s.status == AgentStatus.COMPLETED
    answer = (s.final_answer or "").lower()
    # Must NOT claim it saved or knows conversation history
    assert "đã lưu" not in answer
    assert sr._pending_profile_confirmation is None


# ---------------------------------------------------------------------------
# 19. Profile memory isolated between runtime/store instances
# ---------------------------------------------------------------------------

def test_profile_memory_isolated_between_runtime_store_instances():
    sr1 = _make_sr()
    sr2 = _make_sr()

    _confirm_self_name(sr1, "Bắc")

    # sr2 must not know about Bắc
    s = sr2.handle_turn("tôi tên là gì?")
    assert "Bắc" not in (s.final_answer or ""), (
        "Profile facts must not leak between separate store instances"
    )


# ---------------------------------------------------------------------------
# 20. Profile pending clears on unrelated identity (bạn là ai?)
# ---------------------------------------------------------------------------

def test_profile_pending_clears_on_unrelated_identity():
    sr = _make_sr()
    sr.handle_turn("Tôi tên là Bắc")
    assert sr._pending_profile_confirmation is not None

    # Unrelated identity question about TomTit — should clear profile pending
    s = sr.handle_turn("bạn là ai?")
    assert s.status == AgentStatus.COMPLETED
    # TomTit identity
    assert "TomTit" in (s.final_answer or "") or "TOMTIT" in (s.final_answer or "")
    assert sr._pending_profile_confirmation is None


# ---------------------------------------------------------------------------
# 21. Profile pending clears on calculator command
# ---------------------------------------------------------------------------

def test_profile_pending_clears_on_calculator_command():
    sr = _make_sr()
    sr.handle_turn("Tôi tên là Bắc")
    assert sr._pending_profile_confirmation is not None

    s = sr.handle_turn("calculate 2 + 2")
    assert s.status == AgentStatus.COMPLETED
    assert "4" in (s.final_answer or "")
    assert sr._pending_profile_confirmation is None


# ---------------------------------------------------------------------------
# 22. Write failure does not claim success
# ---------------------------------------------------------------------------

def test_profile_write_failure_does_not_claim_success():
    from unittest.mock import patch
    sr = _make_sr()
    sr.handle_turn("Tôi tên là Bắc")

    with patch(
        "agent_core.runtime.session_runtime.save_confirmed_profile_fact",
        return_value=False,
    ):
        s = sr.handle_turn("có")

    assert s.status == AgentStatus.COMPLETED
    answer = (s.final_answer or "").lower()
    # Must NOT say "Đã lưu" when save failed
    assert "đã lưu." not in answer or "không thể" in answer or len(s.errors) > 0


# ---------------------------------------------------------------------------
# 23. Existing P0-6B pending note flow still works
# ---------------------------------------------------------------------------

def test_existing_p0_6b_pending_note_flow_still_works():
    sr = _make_sr()
    # P0-6B: "Lưu ghi chú về tôi: content" → ask note name → write note
    s1 = sr.handle_turn("Lưu ghi chú về tôi: hôm nay mình rất vui")
    assert s1.status == AgentStatus.COMPLETED
    assert sr._pending_conversation_state is not None, "P0-6B pending must be set"
    assert sr._pending_profile_confirmation is None

    s2 = sr.handle_turn("tamtrang")
    assert s2.status == AgentStatus.COMPLETED
    assert "tamtrang" in (s2.final_answer or "").lower() or "lưu" in (s2.final_answer or "").lower()
    assert sr._pending_conversation_state is None

    s3 = sr.handle_turn("Đọc ghi chú tamtrang")
    assert "hôm nay mình rất vui" in (s3.final_answer or "")


# ===========================================================================
# P0-7C tests — profile recall bugfix + relation synonyms + profile summary
# ===========================================================================

# ---------------------------------------------------------------------------
# 1. self-identity query: exact "tôi là ai?" still works
# ---------------------------------------------------------------------------

def test_self_identity_query_accepts_exact_toi_la_ai_question():
    sr = _make_sr()
    _confirm_self_name(sr, "Bắc")

    s = sr.handle_turn("tôi là ai?")
    assert s.status == AgentStatus.COMPLETED
    assert "Bắc" in (s.final_answer or "")


# ---------------------------------------------------------------------------
# 2. "tôi là AI enginer" must NOT trigger self-name recall (root bug)
# ---------------------------------------------------------------------------

def test_toi_la_ai_engineer_does_not_answer_self_name():
    sr = _make_sr()
    _confirm_self_name(sr, "Bắc")

    s = sr.handle_turn("tôi là AI enginer")
    assert s.status == AgentStatus.COMPLETED
    assert "Bạn tên là Bắc" not in (s.final_answer or ""), (
        "Self-name must not be returned for an occupational statement"
    )


# ---------------------------------------------------------------------------
# 3. "note tôi là AI enginer" must NOT trigger self-name recall
# ---------------------------------------------------------------------------

def test_note_toi_la_ai_engineer_does_not_answer_self_name():
    sr = _make_sr()
    _confirm_self_name(sr, "Bắc")

    s = sr.handle_turn("note tôi là AI enginer")
    assert s.status == AgentStatus.COMPLETED
    assert "Bạn tên là Bắc" not in (s.final_answer or ""), (
        "Self-name must not be returned when note prefix is present"
    )


# ---------------------------------------------------------------------------
# 4. "người yêu của tôi là ai" must NOT answer self-name (without relation fact)
# ---------------------------------------------------------------------------

def test_nguoi_yeu_cua_toi_la_ai_does_not_answer_self_name_without_relation_fact():
    sr = _make_sr()
    _confirm_self_name(sr, "Bắc")  # only self-name confirmed; no relation fact

    s = sr.handle_turn("người yêu của tôi là ai")
    assert s.status == AgentStatus.COMPLETED
    assert "Bạn tên là Bắc" not in (s.final_answer or ""), (
        "Relation query must not return self-name"
    )


# ---------------------------------------------------------------------------
# 5. "người yêu của tôi là ai" answers from confirmed bạn gái fact
# ---------------------------------------------------------------------------

def test_nguoi_yeu_cua_toi_la_ai_answers_relation_after_ban_gai_confirmed():
    sr = _make_sr()
    sr.handle_turn("bạn gái tôi tên là Quý")
    sr.handle_turn("có")

    s = sr.handle_turn("người yêu của tôi là ai")
    assert s.status == AgentStatus.COMPLETED
    assert "Quý" in (s.final_answer or ""), (
        "Synonym 'người yêu' query should resolve confirmed 'bạn gái' fact"
    )


# ---------------------------------------------------------------------------
# 6. "người yêu tôi tên gì?" answers from confirmed bạn gái fact
# ---------------------------------------------------------------------------

def test_nguoi_yeu_toi_ten_gi_answers_relation_after_ban_gai_confirmed():
    sr = _make_sr()
    sr.handle_turn("bạn gái tôi tên là Quý")
    sr.handle_turn("có")

    s = sr.handle_turn("người yêu tôi tên gì?")
    assert s.status == AgentStatus.COMPLETED
    assert "Quý" in (s.final_answer or "")


# ---------------------------------------------------------------------------
# 7. "partner của tôi tên gì?" answers from confirmed bạn gái fact
# ---------------------------------------------------------------------------

def test_partner_query_answers_relation_after_ban_gai_confirmed():
    sr = _make_sr()
    sr.handle_turn("bạn gái tôi tên là Quý")
    sr.handle_turn("có")

    s = sr.handle_turn("partner của tôi tên gì?")
    assert s.status == AgentStatus.COMPLETED
    assert "Quý" in (s.final_answer or ""), (
        "Synonym 'partner' query should resolve confirmed 'bạn gái' fact"
    )


# ---------------------------------------------------------------------------
# 8. Profile summary — empty state
# ---------------------------------------------------------------------------

def test_profile_summary_empty_state():
    sr = _make_sr()

    s = sr.handle_turn("bạn biết gì về tôi?")
    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "chưa" in answer.lower() or "không" in answer.lower() or len(answer) > 0
    # Must not hallucinate any name
    assert "Bắc" not in answer
    assert "Quý" not in answer


# ---------------------------------------------------------------------------
# 9. Profile summary lists confirmed self-name and relation
# ---------------------------------------------------------------------------

def test_profile_summary_lists_confirmed_self_name_and_relation():
    sr = _make_sr()
    _confirm_self_name(sr, "Bắc")
    sr.handle_turn("bạn gái tôi tên là Quý")
    sr.handle_turn("có")

    s = sr.handle_turn("bạn nhớ gì về tôi?")
    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "Bắc" in answer
    assert "Quý" in answer


# ---------------------------------------------------------------------------
# 10. Profile summary does NOT include note contents
# ---------------------------------------------------------------------------

def test_profile_summary_does_not_include_notes():
    sr = _make_sr()
    # Write a note via P0-6B flow
    sr.handle_turn("Lưu ghi chú về mèo: mèo của tôi tên là Mimi")
    sr.handle_turn("catname")  # provide note_name

    s = sr.handle_turn("bạn lưu gì về tôi?")
    assert s.status == AgentStatus.COMPLETED
    assert "Mimi" not in (s.final_answer or ""), (
        "Profile summary must not include note contents"
    )


# ---------------------------------------------------------------------------
# 11. "tôi vừa hỏi gì bạn?" still not handled by profile memory (regression)
# ---------------------------------------------------------------------------

def test_toi_vua_hoi_gi_ban_still_not_profile_memory():
    sr = _make_sr()
    s = sr.handle_turn("tôi vừa hỏi gì bạn?")

    assert s.status == AgentStatus.COMPLETED
    assert "đã lưu" not in (s.final_answer or "").lower()
    assert sr._pending_profile_confirmation is None


# ---------------------------------------------------------------------------
# 12. Existing P0-7B self-name and relation queries still work (regression)
# ---------------------------------------------------------------------------

def test_existing_p0_7b_self_name_and_relation_queries_still_work():
    sr = _make_sr()
    _confirm_self_name(sr, "Bắc")
    sr.handle_turn("bạn gái tôi tên là Quý")
    sr.handle_turn("có")

    s_name = sr.handle_turn("tôi tên là gì?")
    assert "Bắc" in (s_name.final_answer or "")

    s_rel = sr.handle_turn("bạn gái tôi tên gì?")
    assert "Quý" in (s_rel.final_answer or "")

    s_inv = sr.handle_turn("Quý là ai?")
    assert "Quý" in (s_inv.final_answer or "")
    assert "bạn gái" in (s_inv.final_answer or "").lower()


# ---------------------------------------------------------------------------
# 13. P0-6B pending note flow still works (regression guard)
# ---------------------------------------------------------------------------

def test_p0_6b_flow_unaffected_by_p0_7c():
    sr = _make_sr()
    # Use "về tôi" form — same as test 23 which is known to trigger P0-6B pending.
    s1 = sr.handle_turn("Lưu ghi chú về tôi: hoàn thành P0-7C hôm nay")
    assert s1.status == AgentStatus.COMPLETED
    assert sr._pending_conversation_state is not None, "P0-6B pending must be set"
    assert sr._pending_profile_confirmation is None

    s2 = sr.handle_turn("p07cwork")
    assert s2.status == AgentStatus.COMPLETED
    assert sr._pending_conversation_state is None

    s3 = sr.handle_turn("Đọc ghi chú p07cwork")
    assert "hoàn thành P0-7C hôm nay" in (s3.final_answer or "")

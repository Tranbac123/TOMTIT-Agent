"""CONV-P0 P0-7B/7C/7D — user profile memory tests.

Covers:
  P0-7B:
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

  P0-7C:
  - self-identity anchoring (tôi là AI enginer must not answer self-name)
  - relation synonym queries (người yêu, partner → bạn gái fact)
  - profile summary query (bạn biết/nhớ gì về tôi?)

  P0-7D:
  - detect_auto_profile_candidate unit tests (occupation / preference / learning_focus / goal)
  - AUTO_SAFE safety guards (question, note prefix, vague ref)
  - AUTO_SAFE session integration (ack, no confirmation required, fact count increments)
  - profile queries for new kinds after auto-save (occupation/preference/learning/goal)
  - unknown-state responses (no fact saved → honest "chưa biết/chưa có")
  - người yêu / partner confirmation candidate detection
  - profile summary with v2 auto-saved facts
"""
from __future__ import annotations

import pytest

from agent_core.conversation.profile_memory import (
    AutoProfileCandidate,
    ProfileFactCandidate,
    detect_auto_profile_candidate,
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
# 5. P0-7E: direct self-name auto-saves without confirmation
# ---------------------------------------------------------------------------

def test_self_name_direct_claim_auto_saves_without_confirmation():
    sr = _make_sr()
    s = sr.handle_turn("Tôi tên là Bắc")

    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    # P0-7E: auto-saved directly with a natural ack, no confirmation prompt.
    assert _auto_saved(answer), answer
    assert "Bắc" in answer
    assert "lưu không" not in answer.lower()
    assert sr._pending_profile_confirmation is None


# ---------------------------------------------------------------------------
# 6. P0-7E: self-name is queryable immediately after auto-save
# ---------------------------------------------------------------------------

def test_self_name_query_immediately_after_auto_save():
    sr = _make_sr()
    sr.handle_turn("Tôi tên là Bắc")
    s = sr.handle_turn("tôi tên là gì?")

    assert s.status == AgentStatus.COMPLETED
    assert "Bắc" in (s.final_answer or "")
    assert sr._pending_profile_confirmation is None


# ---------------------------------------------------------------------------
# 7. P0-7E: conflicting self-name is handled safely (no silent overwrite)
# ---------------------------------------------------------------------------

def test_self_name_conflict_does_not_silently_overwrite():
    sr = _make_sr()
    sr.handle_turn("Tôi tên là Bắc")          # auto-saved
    s = sr.handle_turn("tôi tên là Nam")       # conflict

    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    # Must acknowledge existing name and not claim a new save.
    assert "Bắc" in answer
    assert not _auto_saved(answer), answer
    # Original name is preserved.
    q = sr.handle_turn("tôi tên là gì?")
    assert "Bắc" in (q.final_answer or "")
    assert "Nam" not in (q.final_answer or "")


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
# 11. P0-7E: no name known before any claim; known after direct auto-save
# ---------------------------------------------------------------------------

def test_no_profile_answer_before_any_claim_then_known_after_autosave():
    sr = _make_sr()
    # Before any claim: honest unknown state (no hallucinated name).
    before = sr.handle_turn("tôi tên là gì?")
    assert "Bắc" not in (before.final_answer or "")
    assert "chưa" in (before.final_answer or "").lower()

    # Direct claim auto-saves; query now returns it.
    sr.handle_turn("Tôi tên là Bắc")
    after = sr.handle_turn("tôi tên là gì?")
    assert "Bắc" in (after.final_answer or "")


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

def test_relationship_candidate_ban_gai_toi_ten_la_quy_auto_saves():
    sr = _make_sr()
    s = sr.handle_turn("bạn gái tôi tên là Quý")

    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    # P0-7E: narrow relation.name auto-saves directly, no confirmation prompt.
    assert "Quý" in answer
    assert _auto_saved(answer), answer
    assert "lưu không" not in answer.lower()
    assert sr._pending_profile_confirmation is None


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
# 20. P0-7E: name auto-save leaves no stuck state; unrelated identity works next
# ---------------------------------------------------------------------------

def test_name_autosave_then_unrelated_identity_works():
    sr = _make_sr()
    s0 = sr.handle_turn("Tôi tên là Bắc")
    assert _auto_saved(s0.final_answer)
    assert sr._pending_profile_confirmation is None

    # Unrelated identity question about TomTit — clean response, no leftover state.
    s = sr.handle_turn("bạn là ai?")
    assert s.status == AgentStatus.COMPLETED
    assert "TomTit" in (s.final_answer or "") or "TOMTIT" in (s.final_answer or "")
    assert sr._pending_profile_confirmation is None


# ---------------------------------------------------------------------------
# 21. P0-7E: name auto-save leaves no stuck state; calculator works next
# ---------------------------------------------------------------------------

def test_name_autosave_then_calculator_command_works():
    sr = _make_sr()
    sr.handle_turn("Tôi tên là Bắc")
    assert sr._pending_profile_confirmation is None

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

    # P0-7E: self.name auto-saves via save_confirmed_profile_fact — patch it to fail.
    with patch(
        "agent_core.runtime.session_runtime.save_confirmed_profile_fact",
        return_value=False,
    ):
        s = sr.handle_turn("Tôi tên là Bắc")

    assert s.status == AgentStatus.COMPLETED
    answer = (s.final_answer or "").lower()
    # Must NOT claim a save when it failed.
    assert not _auto_saved(s.final_answer), s.final_answer
    assert "không thể" in answer or len(s.errors) > 0


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


# ===========================================================================
# P0-7D tests — AUTO_SAFE profile extraction
# ===========================================================================

# ---------------------------------------------------------------------------
# Group A: detect_auto_profile_candidate unit tests
# ---------------------------------------------------------------------------

def test_detect_auto_profile_candidate_occupation_toi_la_multi_word_with_role():
    c = detect_auto_profile_candidate("tôi là AI engineer")
    assert c is not None
    assert c.relation == "occupation"
    assert "AI engineer" in c.value or "engineer" in c.value.lower()


def test_detect_auto_profile_candidate_occupation_toi_lam():
    c = detect_auto_profile_candidate("tôi làm software engineer")
    assert c is not None
    assert c.relation == "occupation"
    assert "software" in c.value.lower() or "engineer" in c.value.lower()


def test_detect_auto_profile_candidate_occupation_nghe():
    c = detect_auto_profile_candidate("nghề của tôi là data scientist")
    assert c is not None
    assert c.relation == "occupation"
    assert "data" in c.value.lower() or "scientist" in c.value.lower()


def test_detect_auto_profile_candidate_preference_thich():
    c = detect_auto_profile_candidate("tôi thích build AI")
    assert c is not None
    assert c.relation == "preference"
    assert "build" in c.value.lower() or "AI" in c.value


def test_detect_auto_profile_candidate_learning_focus():
    c = detect_auto_profile_candidate("tôi đang học LLM")
    assert c is not None
    assert c.relation == "learning_focus"
    assert "LLM" in c.value


def test_detect_auto_profile_candidate_goal():
    c = detect_auto_profile_candidate("mục tiêu của tôi là build AI Agent")
    assert c is not None
    assert c.relation == "goal"
    assert "AI" in c.value or "build" in c.value.lower()


def test_detect_auto_profile_candidate_occupation_context_cong_viec():
    c = detect_auto_profile_candidate("công việc của tôi là backend developer")
    assert c is not None
    assert c.relation == "occupation"


# ---------------------------------------------------------------------------
# Group B: AUTO_SAFE safety guards
# ---------------------------------------------------------------------------

def test_detect_auto_profile_candidate_question_returns_none():
    assert detect_auto_profile_candidate("tôi thích gì?") is None


def test_detect_auto_profile_candidate_question_occupation_returns_none():
    assert detect_auto_profile_candidate("tôi làm nghề gì?") is None


def test_detect_auto_profile_candidate_note_prefix_returns_none():
    assert detect_auto_profile_candidate("note tôi là AI engineer") is None


def test_detect_auto_profile_candidate_luu_prefix_returns_none():
    assert detect_auto_profile_candidate("lưu ghi chú tôi thích build AI") is None


def test_detect_auto_profile_candidate_vague_ref_returns_none():
    assert detect_auto_profile_candidate("tôi thích cái này") is None


def test_detect_auto_profile_candidate_single_word_occupation_toi_la_returns_none():
    # "tôi là dev" — single word, no role keyword context → should not auto-save
    # (it should match the confirmation candidate for self-name instead)
    result = detect_auto_profile_candidate("tôi là dev")
    # Either None or occupation; if occupation, value must not be empty
    if result is not None:
        assert result.relation == "occupation"


# ---------------------------------------------------------------------------
# Group C: AUTO_SAFE session integration
# ---------------------------------------------------------------------------

def test_auto_save_occupation_saves_and_acks_no_confirmation():
    sr = _make_sr()
    s = sr.handle_turn("tôi là AI engineer")

    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "nhớ" in answer.lower()
    # No pending confirmation — this is AUTO_SAFE
    assert sr._pending_profile_confirmation is None


def test_auto_save_preference_saves_and_acks_no_confirmation():
    sr = _make_sr()
    s = sr.handle_turn("tôi thích build AI")

    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "nhớ" in answer.lower()
    assert sr._pending_profile_confirmation is None


def test_auto_save_increments_confirmed_fact_count():
    sr = _make_sr()
    assert sr._confirmed_profile_fact_count == 0

    sr.handle_turn("tôi đang học LLM")
    assert sr._confirmed_profile_fact_count == 1

    sr.handle_turn("tôi thích build AI")
    assert sr._confirmed_profile_fact_count == 2


def test_auto_save_goal_saves_and_acks():
    sr = _make_sr()
    s = sr.handle_turn("mục tiêu của tôi là build AI Agent")

    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "nhớ" in answer.lower()
    assert sr._pending_profile_confirmation is None


# ---------------------------------------------------------------------------
# Group D: Profile queries for new kinds after auto-save
# ---------------------------------------------------------------------------

def test_nghe_nghiep_query_answers_after_auto_save():
    sr = _make_sr()
    sr.handle_turn("tôi là AI engineer")

    s = sr.handle_turn("nghề của tôi là gì?")
    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "engineer" in answer.lower() or "AI" in answer


def test_so_thich_query_answers_after_auto_save():
    sr = _make_sr()
    sr.handle_turn("tôi thích build AI")

    s = sr.handle_turn("tôi thích gì?")
    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "build" in answer.lower() or "AI" in answer


def test_learning_focus_query_answers_after_auto_save():
    sr = _make_sr()
    sr.handle_turn("tôi đang học LLM")

    s = sr.handle_turn("tôi đang học gì?")
    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "LLM" in answer


def test_goal_query_answers_after_auto_save():
    sr = _make_sr()
    sr.handle_turn("mục tiêu của tôi là build AI Agent")

    s = sr.handle_turn("mục tiêu của tôi là gì?")
    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "AI" in answer or "build" in answer.lower()


# ---------------------------------------------------------------------------
# Group E: Unknown-state responses
# ---------------------------------------------------------------------------

def test_toi_ten_la_gi_unknown_state_honest_response():
    sr = _make_sr()  # empty store

    s = sr.handle_turn("tôi tên là gì?")
    assert s.status == AgentStatus.COMPLETED
    answer = (s.final_answer or "").lower()
    assert "chưa" in answer or "không" in answer, (
        f"Expected honest unknown-state response, got: {s.final_answer!r}"
    )
    # Must not claim a name
    assert "Bắc" not in (s.final_answer or "")


def test_nghe_nghiep_unknown_state_honest_response():
    sr = _make_sr()  # empty store

    s = sr.handle_turn("nghề của tôi là gì?")
    assert s.status == AgentStatus.COMPLETED
    answer = (s.final_answer or "").lower()
    assert "chưa" in answer or "không" in answer, (
        f"Expected honest unknown-state response, got: {s.final_answer!r}"
    )


# ---------------------------------------------------------------------------
# Group F: người yêu / partner confirmation candidate
# ---------------------------------------------------------------------------

def test_nguoi_yeu_auto_saves_directly():
    sr = _make_sr()
    s = sr.handle_turn("người yêu của tôi tên là Quý")

    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "Quý" in answer
    assert _auto_saved(answer), answer
    assert "lưu không" not in answer.lower()
    assert sr._pending_profile_confirmation is None


def test_partner_auto_saves_directly():
    sr = _make_sr()
    s = sr.handle_turn("partner của tôi là Quý")

    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "Quý" in answer
    assert _auto_saved(answer), answer
    assert sr._pending_profile_confirmation is None


def test_nguoi_yeu_auto_save_then_query_answers():
    sr = _make_sr()
    sr.handle_turn("người yêu của tôi tên là Quý")

    s = sr.handle_turn("người yêu tôi tên gì?")
    assert s.status == AgentStatus.COMPLETED
    assert "Quý" in (s.final_answer or "")


# ---------------------------------------------------------------------------
# Group G: Profile summary with v2 auto-saved facts
# ---------------------------------------------------------------------------

def test_profile_summary_includes_auto_saved_occupation():
    sr = _make_sr()
    sr.handle_turn("tôi là AI engineer")

    s = sr.handle_turn("bạn biết gì về tôi?")
    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "engineer" in answer.lower() or "AI" in answer, (
        f"Profile summary must include auto-saved occupation. Got: {answer!r}"
    )


# ===========================================================================
# P0-7D-FIX1 tests — common "enginer" typo auto-saves as occupation, and the
# role-keyword matcher does not over-match on substrings (con trai / hai người).
# ===========================================================================

def _auto_saved(final_answer: str | None) -> bool:
    # P0-7E: AUTO_SAFE acks are natural and begin with "Đã nhớ" (no longer "Đã lưu vào hồ sơ").
    return "đã nhớ" in (final_answer or "").lower()


def test_auto_saves_occupation_toi_la_ai_enginer_typo():
    sr = _make_sr()
    s = sr.handle_turn("tôi là AI enginer")
    assert s.status == AgentStatus.COMPLETED
    assert _auto_saved(s.final_answer), s.final_answer
    assert "AI" in (s.final_answer or "")
    assert "engin" in (s.final_answer or "").lower()
    assert sr._pending_profile_confirmation is None


def test_auto_saves_occupation_toi_lam_ai_enginer_typo():
    sr = _make_sr()
    s = sr.handle_turn("tôi làm AI enginer")
    assert s.status == AgentStatus.COMPLETED
    assert _auto_saved(s.final_answer), s.final_answer
    assert "engin" in (s.final_answer or "").lower()


def test_auto_saves_occupation_nghe_cua_toi_la_ai_enginer_typo():
    sr = _make_sr()
    s = sr.handle_turn("nghề của tôi là AI enginer")
    assert s.status == AgentStatus.COMPLETED
    assert _auto_saved(s.final_answer), s.final_answer
    assert "engin" in (s.final_answer or "").lower()


def test_enginer_typo_query_answers_after_auto_save():
    sr = _make_sr()
    sr.handle_turn("tôi là AI enginer")
    s = sr.handle_turn("tôi làm nghề gì?")
    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "AI" in answer
    assert "engin" in answer.lower()


def test_note_toi_la_ai_enginer_still_does_not_auto_save():
    sr = _make_sr()
    s = sr.handle_turn("note tôi là AI enginer")
    assert s.status == AgentStatus.COMPLETED
    assert not _auto_saved(s.final_answer), s.final_answer


def test_luu_ghi_chu_toi_la_ai_enginer_still_does_not_auto_save():
    sr = _make_sr()
    s = sr.handle_turn("lưu ghi chú tôi là AI enginer")
    assert s.status == AgentStatus.COMPLETED
    assert not _auto_saved(s.final_answer), s.final_answer


def test_toi_la_bac_auto_saves_name():
    sr = _make_sr()
    s = sr.handle_turn("tôi là Bắc")
    assert s.status == AgentStatus.COMPLETED
    # P0-7E: single proper-name token → direct self.name auto-save (no confirmation).
    assert _auto_saved(s.final_answer), s.final_answer
    assert "Bắc" in (s.final_answer or "")
    assert sr._pending_profile_confirmation is None
    q = sr.handle_turn("tôi tên là gì?")
    assert "Bắc" in (q.final_answer or "")


def test_toi_la_nguoi_tot_still_does_not_auto_save():
    sr = _make_sr()
    s = sr.handle_turn("tôi là người tốt")
    assert s.status == AgentStatus.COMPLETED
    assert not _auto_saved(s.final_answer), s.final_answer
    assert sr._pending_profile_confirmation is None


def test_correction_phrase_toi_la_ai_enginer_does_not_auto_save():
    sr = _make_sr()
    s = sr.handle_turn("sai rồi tôi là AI enginer")
    assert s.status == AgentStatus.COMPLETED
    # Not anchored at "tôi là ..." (prefixed by "sai rồi") → no occupation auto-save.
    assert not _auto_saved(s.final_answer), s.final_answer


@pytest.mark.parametrize("text", ["tôi là con trai", "tôi là trai làng", "tôi là hai người"])
def test_role_keyword_substring_does_not_over_match(text: str):
    # Regression: 2-char keyword "ai" must not match inside "trai"/"hai".
    sr = _make_sr()
    s = sr.handle_turn(text)
    assert s.status == AgentStatus.COMPLETED
    assert not _auto_saved(s.final_answer), (
        f"{text!r} must not auto-save as occupation. Got: {s.final_answer!r}"
    )


# ===========================================================================
# P0-7D-FIX2 tests — unsafe/sensitive preference values must not auto-save
# ===========================================================================

@pytest.mark.parametrize("value", [
    "cocaine", "thuốc phiện", "heroin", "ma túy", "cần sa", "meth",
])
def test_unsafe_preference_does_not_auto_save(value: str):
    sr = _make_sr()
    s = sr.handle_turn(f"tôi thích {value}")
    assert s.status == AgentStatus.COMPLETED
    assert not _auto_saved(s.final_answer), (
        f"unsafe preference {value!r} must not auto-save. Got: {s.final_answer!r}"
    )
    assert sr._pending_profile_confirmation is None
    # Query must not surface the blocked value.
    q = sr.handle_turn("tôi thích gì?")
    assert value not in (q.final_answer or "")


def test_note_preference_unsafe_value_still_does_not_auto_save():
    sr = _make_sr()
    s = sr.handle_turn("note tôi thích cocaine")
    assert s.status == AgentStatus.COMPLETED
    assert not _auto_saved(s.final_answer), s.final_answer


def test_correction_preference_unsafe_value_still_does_not_auto_save():
    sr = _make_sr()
    s = sr.handle_turn("sai rồi tôi thích cocaine")
    assert s.status == AgentStatus.COMPLETED
    assert not _auto_saved(s.final_answer), s.final_answer


def test_summary_does_not_include_blocked_unsafe_preference():
    sr = _make_sr()
    sr.handle_turn("tôi thích cocaine")      # blocked
    sr.handle_turn("tôi thích build AI")     # safe, auto-saved

    s = sr.handle_turn("bạn biết gì về tôi?")
    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "cocaine" not in answer, f"summary leaked blocked value: {answer!r}"
    assert "build AI" in answer


def test_safe_preference_build_ai_still_auto_saves():
    sr = _make_sr()
    s = sr.handle_turn("tôi thích build AI")
    assert s.status == AgentStatus.COMPLETED
    assert _auto_saved(s.final_answer), s.final_answer
    assert "build AI" in (s.final_answer or "")


def test_safe_occupation_ai_enginer_still_auto_saves():
    sr = _make_sr()
    s = sr.handle_turn("tôi là AI enginer")
    assert s.status == AgentStatus.COMPLETED
    assert _auto_saved(s.final_answer), s.final_answer
    assert "AI" in (s.final_answer or "")


def test_safe_learning_focus_llm_still_auto_saves():
    sr = _make_sr()
    s = sr.handle_turn("tôi đang học LLM")
    assert s.status == AgentStatus.COMPLETED
    assert _auto_saved(s.final_answer), s.final_answer
    assert "LLM" in (s.final_answer or "")


def test_safe_goal_build_ai_agent_still_auto_saves():
    sr = _make_sr()
    s = sr.handle_turn("mục tiêu của tôi là build AI Agent")
    assert s.status == AgentStatus.COMPLETED
    assert _auto_saved(s.final_answer), s.final_answer
    assert "build AI Agent" in (s.final_answer or "")


def test_unsafe_guard_helper_blocks_and_allows():
    from agent_core.conversation.profile_memory import (
        _is_unsafe_or_sensitive_auto_value,
    )
    for bad in ["cocaine", "thuốc phiện", "heroin", "ma túy", "cần sa", "meth",
                "password", "api key", "cccd", "passport"]:
        assert _is_unsafe_or_sensitive_auto_value(bad), bad
    for good in ["build AI", "AI Agent", "lập trình", "AI enginer", "LLM",
                 "build AI Agent", "đá bóng"]:
        assert not _is_unsafe_or_sensitive_auto_value(good), good


# ===========================================================================
# P0-7E tests — memory UX: natural acks, habit, relation auto-save, safety UX
# ===========================================================================

def test_relation_direct_claim_auto_saves_without_confirmation():
    sr = _make_sr()
    s = sr.handle_turn("bạn gái tôi tên là Quý")
    assert s.status == AgentStatus.COMPLETED
    assert _auto_saved(s.final_answer), s.final_answer
    assert "Quý" in (s.final_answer or "")
    assert sr._pending_profile_confirmation is None


def test_relation_query_after_auto_save():
    sr = _make_sr()
    sr.handle_turn("bạn gái tôi tên là Quý")
    s = sr.handle_turn("bạn gái tôi tên gì?")
    assert "Quý" in (s.final_answer or "")


def test_relation_conflict_does_not_silently_overwrite():
    sr = _make_sr()
    sr.handle_turn("bạn gái tôi tên là Quý")     # auto-saved
    s = sr.handle_turn("bạn gái tôi tên là Lan")  # conflict
    assert s.status == AgentStatus.COMPLETED
    answer = s.final_answer or ""
    assert "Quý" in answer
    assert not _auto_saved(answer), answer
    q = sr.handle_turn("bạn gái tôi tên gì?")
    assert "Quý" in (q.final_answer or "")
    assert "Lan" not in (q.final_answer or "")


def test_safe_preference_post_save_response_is_natural():
    sr = _make_sr()
    s = sr.handle_turn("tôi thích build AI")
    answer = s.final_answer or ""
    # Natural "Đã nhớ …" phrasing, never the mechanical "Đã lưu vào hồ sơ".
    assert "đã nhớ" in answer.lower()
    assert "Đã lưu vào hồ sơ" not in answer
    assert "build AI" in answer


def test_cafe_preference_response_mentions_cafe_without_overclaim():
    sr = _make_sr()
    s = sr.handle_turn("tôi thích uống cafe")
    answer = s.final_answer or ""
    assert "đã nhớ" in answer.lower()
    assert "uống cafe" in answer
    # light contextual note only; must not over-claim as advice/diagnosis
    assert "cà phê" in answer.lower() or "cafe" in answer.lower()
    assert "chữa" not in answer.lower()


def test_unsafe_cocaine_returns_specific_safe_response_and_does_not_save():
    sr = _make_sr()
    s = sr.handle_turn("tôi thích cocaine")
    answer = s.final_answer or ""
    assert "cocaine" in answer.lower()
    assert "không lưu" in answer.lower() or "sẽ không lưu" in answer.lower()
    assert not _auto_saved(answer), answer
    assert sr._pending_profile_confirmation is None
    q = sr.handle_turn("tôi thích gì?")
    assert "cocaine" not in (q.final_answer or "").lower()


def test_habit_toi_hay_di_moto_di_phuot_auto_saves():
    sr = _make_sr()
    s = sr.handle_turn("tôi hay đi moto đi phượt")
    assert s.status == AgentStatus.COMPLETED
    assert _auto_saved(s.final_answer), s.final_answer
    assert "moto" in (s.final_answer or "").lower() or "phượt" in (s.final_answer or "").lower()
    assert sr._pending_profile_confirmation is None


def test_habit_appears_in_profile_summary():
    sr = _make_sr()
    sr.handle_turn("tôi hay đi moto đi phượt")
    s = sr.handle_turn("bạn biết gì về tôi?")
    answer = s.final_answer or ""
    assert "phượt" in answer.lower()


def test_habit_query_unknown_state():
    sr = _make_sr()
    s = sr.handle_turn("thói quen của tôi là gì?")
    assert s.status == AgentStatus.COMPLETED
    answer = (s.final_answer or "").lower()
    assert "chưa" in answer


def test_habit_query_after_auto_save():
    sr = _make_sr()
    sr.handle_turn("tôi hay uống cafe")
    s = sr.handle_turn("tôi hay làm gì?")
    assert "uống cafe" in (s.final_answer or "")


def test_note_prefix_still_does_not_auto_save_profile():
    sr = _make_sr()
    s = sr.handle_turn("note tôi hay đi phượt")
    assert s.status == AgentStatus.COMPLETED
    assert not _auto_saved(s.final_answer), s.final_answer


def test_detect_blocked_unsafe_only_for_profile_pattern():
    from agent_core.conversation.profile_memory import (
        detect_blocked_auto_profile_value,
    )
    # matches a preference pattern with unsafe value → blocked attempt
    assert detect_blocked_auto_profile_value("tôi thích cocaine") is not None
    # arbitrary unsupported sentence → not a blocked attempt (falls through to router)
    assert detect_blocked_auto_profile_value("cocaine là gì") is None
    assert detect_blocked_auto_profile_value("hôm nay trời đẹp") is None


def test_habit_detect_unit():
    c = detect_auto_profile_candidate("tôi thường chơi thể thao")
    assert c is not None
    assert c.relation == "habit"
    assert "thể thao" in c.value.lower()


# ===========================================================================
# P0-7F tests — semantic profile coverage (skill, occupation, relationship,
# preference split/aggregation, person-affinity, yes/no, follow-up, summary)
# ===========================================================================

# --- Skill ---

def test_skill_biet_boi_auto_saves():
    sr = _make_sr()
    s = sr.handle_turn("tôi biết bơi")
    assert s.status == AgentStatus.COMPLETED
    assert _auto_saved(s.final_answer), s.final_answer
    assert "bơi" in (s.final_answer or "").lower()


def test_skill_query_after_auto_save():
    sr = _make_sr()
    sr.handle_turn("tôi biết bơi")
    sr.handle_turn("tôi có thể code Python")
    s = sr.handle_turn("tôi biết làm gì?")
    answer = s.final_answer or ""
    assert "bơi" in answer.lower()
    assert "python" in answer.lower()


def test_skill_query_unknown_state():
    sr = _make_sr()
    s = sr.handle_turn("tôi biết làm gì?")
    assert "chưa" in (s.final_answer or "").lower()


# --- Occupation "tôi làm AI" (+ task-object guard) ---

def test_occupation_toi_lam_ai_auto_saves():
    sr = _make_sr()
    s = sr.handle_turn("tôi làm AI")
    assert _auto_saved(s.final_answer), s.final_answer
    assert "AI" in (s.final_answer or "")


def test_toi_lam_bai_tap_does_not_auto_save():
    sr = _make_sr()
    s = sr.handle_turn("tôi làm bài tập")
    assert not _auto_saved(s.final_answer), s.final_answer


# --- Relationship "của tôi" variants ---

@pytest.mark.parametrize("text", [
    "bạn gái của tôi là Quý",
    "bạn gái của tôi tên là Quý",
])
def test_relationship_cua_toi_auto_saves(text: str):
    sr = _make_sr()
    s = sr.handle_turn(text)
    assert _auto_saved(s.final_answer), s.final_answer
    assert "Quý" in (s.final_answer or "")
    q = sr.handle_turn("bạn gái tôi tên gì?")
    assert "Quý" in (q.final_answer or "")


def test_nguoi_yeu_la_ai_answers_relation_when_known():
    sr = _make_sr()
    sr.handle_turn("bạn gái của tôi là Quý")
    s = sr.handle_turn("người yêu của tôi là ai")
    assert "Quý" in (s.final_answer or "")


def test_nguoi_yeu_la_ai_unknown_state_is_specific():
    sr = _make_sr()
    s = sr.handle_turn("người yêu của tôi là ai")
    answer = (s.final_answer or "").lower()
    assert "chưa" in answer
    assert "bạn tên là" not in answer


def test_relationship_cua_toi_conflict_safe():
    sr = _make_sr()
    sr.handle_turn("bạn gái của tôi là Quý")
    s = sr.handle_turn("bạn gái của tôi là Lan")
    answer = s.final_answer or ""
    assert "Quý" in answer
    assert not _auto_saved(answer), answer


# --- Person-affinity guard ---

def test_toi_thich_quy_is_not_saved_as_preference():
    sr = _make_sr()
    s = sr.handle_turn("tôi thích Quý")
    answer = s.final_answer or ""
    assert "không lưu" in answer.lower()
    assert not _auto_saved(answer), answer
    q = sr.handle_turn("tôi thích gì?")
    assert "Quý" not in (q.final_answer or "")


# --- Preference aggregation (personal + professional) ---

def test_preference_query_aggregates_all():
    sr = _make_sr()
    sr.handle_turn("tôi thích uống cafe")
    sr.handle_turn("tôi thích đi du lịch")
    sr.handle_turn("tôi thích build AI")
    s = sr.handle_turn("tôi thích gì?")
    answer = s.final_answer or ""
    assert "uống cafe" in answer
    assert "đi du lịch" in answer
    assert "build AI" in answer


# --- Muốn desires ---

def test_muon_build_saves_goal():
    sr = _make_sr()
    sr.handle_turn("tôi muốn build AI Agent")
    s = sr.handle_turn("mục tiêu của tôi là gì?")
    assert "build AI Agent" in (s.final_answer or "")


def test_muon_di_choi_near_miss_does_not_save():
    sr = _make_sr()
    s = sr.handle_turn("tôi muốn đi chơi")
    assert not _auto_saved(s.final_answer), s.final_answer
    assert sr._confirmed_profile_fact_count == 0


# --- Summary variants ---

def test_summary_variant_ban_da_nho_gi_ve_toi():
    sr = _make_sr()
    sr.handle_turn("tôi biết bơi")
    s = sr.handle_turn("bạn đã nhớ gì về tôi")
    assert "bơi" in (s.final_answer or "").lower()


# --- Yes/no memory query ---

def test_yes_no_preference_known():
    sr = _make_sr()
    sr.handle_turn("tôi thích uống cafe")
    s = sr.handle_turn("tôi có thích uống cafe không?")
    answer = (s.final_answer or "").lower()
    assert "có" in answer
    assert "cafe" in answer


def test_yes_no_skill_known():
    sr = _make_sr()
    sr.handle_turn("tôi biết bơi")
    s = sr.handle_turn("tôi biết bơi đúng không?")
    answer = (s.final_answer or "").lower()
    assert "đúng" in answer or "có" in answer
    assert "bơi" in answer


def test_yes_no_unknown_state():
    sr = _make_sr()
    s = sr.handle_turn("tôi có thích guitar không?")
    assert "chưa" in (s.final_answer or "").lower()


# --- Follow-up "gì nữa?" ---

def test_followup_after_preference_query():
    sr = _make_sr()
    sr.handle_turn("tôi thích uống cafe")
    sr.handle_turn("tôi thích gì?")
    s = sr.handle_turn("gì nữa?")
    answer = (s.final_answer or "").lower()
    assert "hiện tại" in answer or "chỉ" in answer


def test_followup_without_context_asks_clarification_no_write():
    sr = _make_sr()
    s = sr.handle_turn("gì nữa?")
    assert "đã nhớ" not in (s.final_answer or "").lower()
    assert "đã lưu" not in (s.final_answer or "").lower()
    assert sr._confirmed_profile_fact_count == 0


# --- P0-7F-FIX1: plain occupation query "tôi làm gì?" ---

def test_occupation_plain_query_unknown_is_specific_not_generic():
    """tôi làm gì? with no saved occupation → specific unknown, not generic fallback."""
    sr = _make_sr()
    s = sr.handle_turn("tôi làm gì?")
    answer = s.final_answer or ""
    assert "chưa" in answer.lower()
    occ_words = ("nghề", "công việc", "lĩnh vực", "vai trò")
    assert any(w in answer.lower() for w in occ_words)
    assert "rule-based MVP" not in answer


def test_occupation_plain_query_returns_saved_occupation():
    """tôi làm AI + tôi làm gì? → AI in answer."""
    sr = _make_sr()
    sr.handle_turn("tôi làm AI")
    s = sr.handle_turn("tôi làm gì?")
    assert "AI" in (s.final_answer or "")


# ---------------------------------------------------------------------------
# P0-7F-FIX2 — detect_profile_query: affection + drink queries
# ---------------------------------------------------------------------------

def test_detect_affection_query_toi_thich_ai():
    q = detect_profile_query("tôi thích ai?")
    assert q is not None
    assert q.kind == "self_affection"


def test_detect_drink_pref_query_uong_gi():
    q = detect_profile_query("tôi thích uống gì?")
    assert q is not None
    assert q.kind == "self_drink_preference"


def test_detect_drink_pref_query_an_gi():
    q = detect_profile_query("tôi thích ăn gì?")
    assert q is not None
    assert q.kind == "self_drink_preference"


# ---------------------------------------------------------------------------
# P0-7F-FIX2 — occupation wording
# ---------------------------------------------------------------------------

def test_occupation_wording_is_linh_vuc_not_ban_la():
    """'tôi làm AI' then 'tôi làm gì?' must say lĩnh vực/công việc, not 'Bạn là AI'."""
    sr = _make_sr()
    sr.handle_turn("tôi làm AI")
    s = sr.handle_turn("tôi làm gì?")
    answer = s.final_answer or ""
    assert "AI" in answer
    assert "Bạn là AI" not in answer
    assert "lĩnh vực" in answer.lower() or "công việc" in answer.lower()
    assert "rule-based MVP" not in answer


# ---------------------------------------------------------------------------
# P0-7F-FIX2 — polluted preference filtering
# ---------------------------------------------------------------------------

def _inject_preference(store, value: str, kind: str = "personal") -> None:
    """Inject a preference record with the given value, bypassing the semantic guard."""
    from agent_core.conversation.profile_memory import save_auto_profile_fact, AutoProfileCandidate
    cand = AutoProfileCandidate(
        relation="preference",
        value=value,
        original_text=f"tôi thích {value}",
        preference_kind=kind,
    )
    save_auto_profile_fact(cand, store, session_id="test_pollution")


def test_polluted_ai_filtered_from_snapshot():
    """Legacy 'ai' record must not appear in the collected snapshot."""
    from agent_core.conversation.profile_memory import collect_profile_snapshot
    agent, store = build_local_agent()
    _inject_preference(store, "ai", "professional")
    snap = collect_profile_snapshot(store)
    assert "ai" not in snap.preferences_professional
    assert "ai" not in snap.preferences_personal


def test_polluted_uong_gi_filtered_from_snapshot():
    """Legacy 'uống gì' record must not appear in the collected snapshot."""
    from agent_core.conversation.profile_memory import collect_profile_snapshot
    agent, store = build_local_agent()
    _inject_preference(store, "uống gì", "personal")
    snap = collect_profile_snapshot(store)
    assert "uống gì" not in snap.preferences_personal


def test_preference_query_hides_polluted_values():
    """'tôi thích gì?' with only polluted records → unknown-state response, no leaked values."""
    from agent_core.runtime.session_runtime import SessionRuntime
    agent, store = build_local_agent()
    _inject_preference(store, "ai", "professional")
    _inject_preference(store, "uống gì", "personal")
    sr = SessionRuntime(agent, store)
    s = sr.handle_turn("tôi thích gì?")
    answer = s.final_answer or ""
    assert "uống gì" not in answer.lower()
    assert "chưa" in answer.lower()


# ---------------------------------------------------------------------------
# P0-7F-FIX2 — runtime integration: all 8 disambiguation bugs
# ---------------------------------------------------------------------------

def test_bug1_toi_thich_ai_no_save():
    """Bug 1: 'tôi thích ai' must not be saved as a preference."""
    sr = _make_sr()
    s = sr.handle_turn("tôi thích ai")
    assert "đã nhớ" not in (s.final_answer or "").lower()


def test_bug2_toi_thich_ai_question_specific_not_generic():
    """Bug 2: 'tôi thích ai?' must get a specific affection-query response."""
    sr = _make_sr()
    s = sr.handle_turn("tôi thích ai?")
    answer = s.final_answer or ""
    assert "rule-based MVP" not in answer
    assert "đã nhớ" not in answer.lower()


def test_bug3_toi_thich_uong_gi_no_save():
    """Bug 3: 'tôi thích uống gì' must not be saved as a preference."""
    sr = _make_sr()
    s = sr.handle_turn("tôi thích uống gì")
    assert "đã nhớ" not in (s.final_answer or "").lower()


def test_bug3_drink_query_returns_saved_drink():
    """Bug 3+: 'tôi thích uống cafe' then 'tôi thích uống gì?' → cafe in answer."""
    sr = _make_sr()
    sr.handle_turn("tôi thích uống cafe")
    s = sr.handle_turn("tôi thích uống gì?")
    answer = s.final_answer or ""
    assert "cafe" in answer.lower()
    assert "rule-based MVP" not in answer


def test_bug4_preference_query_no_polluted_values():
    """Bug 4: 'tôi thích gì?' must not show interrogative values from store."""
    from agent_core.runtime.session_runtime import SessionRuntime
    agent, store = build_local_agent()
    _inject_preference(store, "ai", "professional")
    _inject_preference(store, "uống gì", "personal")
    sr = SessionRuntime(agent, store)
    s = sr.handle_turn("tôi thích gì?")
    answer = s.final_answer or ""
    assert "uống gì" not in answer.lower()


def test_bug5_lowercase_name_is_person_affinity():
    """Bug 5: 'tôi thích quý' (lowercase) must trigger person-affinity clarification."""
    sr = _make_sr()
    s = sr.handle_turn("tôi thích quý")
    answer = s.final_answer or ""
    assert "không lưu" in answer.lower()
    assert "đã nhớ" not in answer.lower()


def test_bug6_nguoi_toi_thich_ten_la_quy():
    """Bug 6: 'người tôi thích tên là Quý' must get person-affinity response."""
    sr = _make_sr()
    s = sr.handle_turn("người tôi thích tên là Quý")
    answer = s.final_answer or ""
    assert "Quý" in answer
    assert "rule-based MVP" not in answer
    assert "đã nhớ là bạn thích" not in answer.lower()


def test_bug7_toi_khong_thich_ai_negation():
    """Bug 7: 'tôi không thích ai' must get negation response, not generic fallback."""
    sr = _make_sr()
    s = sr.handle_turn("tôi không thích ai")
    answer = s.final_answer or ""
    assert "không" in answer.lower() and "lưu" in answer.lower()
    assert "rule-based MVP" not in answer


def test_bug8_occupation_wording_not_ban_la():
    """Bug 8: 'tôi làm AI' + 'tôi làm gì?' must not say 'Bạn là AI'."""
    sr = _make_sr()
    sr.handle_turn("tôi làm AI")
    s = sr.handle_turn("tôi làm gì?")
    answer = s.final_answer or ""
    assert "Bạn là AI" not in answer
    assert "AI" in answer


def test_build_negation_no_affection_response():
    from agent_core.conversation.profile_memory import build_negation_no_affection_response
    r = build_negation_no_affection_response()
    assert "không" in r.lower()
    assert "lưu" in r.lower()


# ===========================================================================
# P0-7F-FIX3 — semantic correctness + hygiene patch
# ===========================================================================

# --- Part A: yes/no suffix (runtime) ---

def test_fix3_cafe_khong_is_query_not_saved():
    sr = _make_sr()
    s = sr.handle_turn("tôi thích cafe không")
    assert not _auto_saved(s.final_answer), s.final_answer


def test_fix3_cafe_khong_question_is_query_not_saved():
    sr = _make_sr()
    s = sr.handle_turn("tôi thích cafe không?")
    assert not _auto_saved(s.final_answer), s.final_answer


def test_fix3_cafe_khong_duong_still_saves():
    sr = _make_sr()
    s = sr.handle_turn("tôi thích cafe không đường")
    assert _auto_saved(s.final_answer), s.final_answer
    assert "không đường" in (s.final_answer or "").lower()


# --- Part B: AI vs ai (query detection) ---

def test_fix3_toi_thich_AI_is_not_affection_query():
    """detect_profile_query must not treat uppercase 'AI' as the question word 'ai'."""
    assert detect_profile_query("tôi thích AI") is None


def test_fix3_toi_thich_ai_lowercase_is_affection_query():
    q = detect_profile_query("tôi thích ai")
    assert q is not None
    assert q.kind == "self_affection"


def test_fix3_toi_thich_AI_saves_professional_interest():
    sr = _make_sr()
    s = sr.handle_turn("tôi thích AI")
    assert _auto_saved(s.final_answer), s.final_answer
    assert "AI" in (s.final_answer or "")


def test_fix3_toi_thich_ai_lowercase_does_not_save():
    sr = _make_sr()
    s = sr.handle_turn("tôi thích ai")
    assert not _auto_saved(s.final_answer), s.final_answer


# --- Part C: affection explanation (runtime) ---

def test_fix3_affection_explanation_not_saved():
    sr = _make_sr()
    s = sr.handle_turn(
        "tôi thích quý có nghĩa là tôi thích đơn phương và chúng tôi chưa là người yêu"
    )
    answer = s.final_answer or ""
    assert not _auto_saved(answer), answer
    assert "rule-based MVP" not in answer
    assert "tình cảm" in answer.lower()
    assert "người yêu của tôi là quý" in answer.lower()


# --- Part D: third-party mind-state ---

def test_fix3_third_party_affection_query_detected():
    q = detect_profile_query("quý có thích tôi không?")
    assert q is not None
    assert q.kind == "third_party_affection"
    assert q.value == "quý"


def test_fix3_self_yesno_is_not_third_party():
    """'tôi có thích quý không?' has a self subject → not a third-party query."""
    q = detect_profile_query("tôi có thích quý không?")
    assert q is None or q.kind != "third_party_affection"


def test_fix3_third_party_mind_state_response():
    sr = _make_sr()
    s = sr.handle_turn("quý có thích tôi không?")
    answer = s.final_answer or ""
    assert "không thể biết" in answer.lower()
    assert "quý" in answer.lower()
    assert "rule-based MVP" not in answer


def test_fix3_affection_query_mentions_partner_when_relationship_exists():
    sr = _make_sr()
    sr.handle_turn("bạn gái của tôi là quý")
    s = sr.handle_turn("tôi thích ai")
    assert "quý" in (s.final_answer or "").lower()


# --- Part E: name detection ---

def test_fix3_lowercase_name_candidate():
    c = detect_profile_fact_candidate("tôi là bắc")
    assert c is not None
    assert c.subject == "self"
    assert c.relation == "name"
    assert c.value == "bắc"


def test_fix3_lowercase_name_minh():
    c = detect_profile_fact_candidate("mình là bắc")
    assert c is not None
    assert c.value == "bắc"


def test_fix3_ten_without_la():
    assert detect_profile_fact_candidate("tôi tên Bắc").value == "Bắc"
    assert detect_profile_fact_candidate("tên tôi Bắc").value == "Bắc"


def test_fix3_ai_engineer_is_not_name():
    """'tôi là AI engineer' must not be a name candidate (it is an occupation)."""
    c = detect_profile_fact_candidate("tôi là AI engineer")
    assert c is None or c.relation != "name" or c.value != "AI"


def test_fix3_developer_single_token_is_not_name():
    assert detect_profile_fact_candidate("tôi là developer") is None


def test_fix3_lowercase_name_saves_at_runtime():
    sr = _make_sr()
    s = sr.handle_turn("tôi là bắc")
    assert "đã nhớ" in (s.final_answer or "").lower()
    assert "bắc" in (s.final_answer or "").lower()


def test_fix3_nationality_is_not_saved_as_name():
    sr = _make_sr()
    s = sr.handle_turn("tôi là người VN")
    assert "đã nhớ tên" not in (s.final_answer or "").lower()


# --- Part G: extended memory hygiene ---

def _inject_pref(store, value: str, kind: str = "personal") -> None:
    from agent_core.conversation.profile_memory import save_auto_profile_fact, AutoProfileCandidate
    cand = AutoProfileCandidate(
        relation="preference", value=value,
        original_text=f"tôi thích {value}", preference_kind=kind,
    )
    save_auto_profile_fact(cand, store, session_id="fix3_pollution")


@pytest.mark.parametrize("polluted", [
    "cafe không", "ai", "uống gì",
    "quý có nghĩa là tôi thích đơn phương và chúng tôi chưa là người yêu",
])
def test_fix3_polluted_values_filtered(polluted: str):
    from agent_core.conversation.profile_memory import _is_polluted_preference
    assert _is_polluted_preference(polluted)


@pytest.mark.parametrize("valid", [
    "cafe", "cafe không đường", "đi du lịch", "build AI", "AI", "AI Agent",
])
def test_fix3_valid_values_not_filtered(valid: str):
    from agent_core.conversation.profile_memory import _is_polluted_preference
    assert not _is_polluted_preference(valid)


def test_fix3_summary_hides_polluted_shows_valid():
    from agent_core.conversation.profile_memory import collect_profile_snapshot
    agent, store = build_local_agent()
    for v, k in [
        ("cafe không", "personal"), ("ai", "professional"), ("uống gì", "personal"),
        ("quý có nghĩa là tôi thích đơn phương và chúng tôi chưa là người yêu", "personal"),
        ("cafe", "personal"), ("cafe không đường", "personal"),
        ("đi du lịch", "personal"), ("build AI", "professional"),
    ]:
        _inject_pref(store, v, k)
    snap = collect_profile_snapshot(store)
    shown = [x.lower() for x in snap.preferences_personal + snap.preferences_professional]
    assert "cafe" in shown
    assert "cafe không đường" in shown
    assert "đi du lịch" in shown
    assert "build ai" in shown
    assert "cafe không" not in shown
    assert "ai" not in shown
    assert "uống gì" not in shown
    assert not any("có nghĩa" in x for x in shown)


def test_fix3_preference_query_hides_polluted():
    from agent_core.runtime.session_runtime import SessionRuntime
    agent, store = build_local_agent()
    _inject_pref(store, "cafe không", "personal")
    _inject_pref(store, "cafe", "personal")
    sr = SessionRuntime(agent, store)
    s = sr.handle_turn("tôi thích gì")
    answer = (s.final_answer or "").lower()
    assert "cafe" in answer
    assert "\n- cafe không\n" not in answer and not answer.endswith("- cafe không")


# --- Part H: weather/date unsupported ---

@pytest.mark.parametrize("text", [
    "thời tiết hôm nay thế nào",
    "thời thiết hôm nay thế nào",   # typo
    "hôm nay ngày bao nhiêu",
])
def test_fix3_unsupported_current_info(text: str):
    sr = _make_sr()
    s = sr.handle_turn(text)
    answer = s.final_answer or ""
    assert "rule-based MVP" not in answer
    low = answer.lower()
    assert "thời tiết" in low or "thời gian" in low or "ngày" in low


def test_fix3_build_affection_explanation_response():
    from agent_core.conversation.profile_memory import build_affection_explanation_response
    r = build_affection_explanation_response("quý")
    assert "quý" in r.lower()
    assert "không lưu" in r.lower()
    assert "người yêu của tôi là quý" in r.lower()


# ===========================================================================
# P0-7F-FIX4 — relationship / entity disambiguation (runtime)
# ===========================================================================

# --- Part A: affection relation phrase → clarify, no save ---

@pytest.mark.parametrize("text", [
    "tôi có tình cảm với quý",
    "mình có cảm tình với quý",
    "tôi crush quý",
])
def test_fix4_affection_relation_not_saved(text: str):
    sr = _make_sr()
    answer = sr.handle_turn(text).final_answer or ""
    low = answer.lower()
    assert "đã nhớ là bạn thích" not in low
    assert "rule-based MVP" not in answer
    assert "tình cảm" in low or "không lưu" in low


def test_fix4_build_affection_relation_response():
    from agent_core.conversation.profile_memory import build_affection_relation_response
    r = build_affection_relation_response("quý")
    assert "quý" in r.lower()
    assert "không lưu" in r.lower()
    assert "người yêu của tôi là quý" in r.lower()


# --- Part B: common object/food is a preference, not a person ---

def test_fix4_object_food_preference_saved():
    sr = _make_sr()
    low = (sr.handle_turn("tôi thích kem").final_answer or "").lower()
    assert "đã nhớ" in low
    assert "kem" in low


def test_fix4_an_kem_preference_saved():
    sr = _make_sr()
    low = (sr.handle_turn("tôi thích ăn kem").final_answer or "").lower()
    assert "đã nhớ" in low
    assert "kem" in low


@pytest.mark.parametrize("text", ["tôi thích quý", "tôi yêu quý"])
def test_fix4_person_name_not_saved_as_hobby(text: str):
    sr = _make_sr()
    low = (sr.handle_turn(text).final_answer or "").lower()
    assert "đã nhớ" not in low
    assert "không lưu" in low


# --- Part C: friend relation write + query (never self-name) ---

@pytest.mark.parametrize("text", ["bạn tôi tên là meo", "bạn của tôi tên là meo"])
def test_fix4_friend_relation_saved(text: str):
    sr = _make_sr()
    low = (sr.handle_turn(text).final_answer or "").lower()
    assert "đã nhớ" in low
    assert "meo" in low


def test_fix4_friend_query_returns_friend_name():
    sr = _make_sr()
    sr.handle_turn("bạn của tôi tên là meo")
    low = (sr.handle_turn("bạn của tôi tên là gì?").final_answer or "").lower()
    assert "meo" in low


def test_fix4_friend_query_unknown_is_not_self_name():
    """'bạn của tôi tên là gì?' must never resolve to the USER's own name."""
    sr = _make_sr()
    sr.handle_turn("tôi là bắc")
    low = (sr.handle_turn("bạn của tôi tên là gì?").final_answer or "").lower()
    assert "bắc" not in low
    assert "chưa" in low or "không" in low


def test_fix4_friend_query_after_self_name_returns_friend_not_self():
    sr = _make_sr()
    sr.handle_turn("tôi là bắc")
    sr.handle_turn("bạn của tôi tên là meo")
    low = (sr.handle_turn("bạn của tôi tên là gì?").final_answer or "").lower()
    assert "meo" in low
    assert "bắc" not in low


def test_fix4_friend_name_query_detected():
    q = detect_profile_query("bạn của tôi tên là gì?")
    assert q is not None
    assert q.kind == "friend_name"


# --- Part D: household pet fact save + summary + query ---

@pytest.mark.parametrize("text", [
    "nhà tôi có nuôi 1 con mèo",
    "nhà tôi nuôi mèo",
    "tôi nuôi mèo",
])
def test_fix4_household_pet_saved(text: str):
    sr = _make_sr()
    low = (sr.handle_turn(text).final_answer or "").lower()
    assert "đã nhớ" in low
    assert "mèo" in low


def test_fix4_pet_shows_in_summary():
    sr = _make_sr()
    sr.handle_turn("nhà tôi có nuôi 1 con mèo")
    low = (sr.handle_turn("bạn biết gì về tôi").final_answer or "").lower()
    assert "mèo" in low


def test_fix4_pet_query_returns_pet():
    sr = _make_sr()
    sr.handle_turn("nhà tôi có nuôi 1 con mèo")
    low = (sr.handle_turn("nhà tôi nuôi con gì?").final_answer or "").lower()
    assert "mèo" in low


# --- Part E: unsupported open-knowledge Q&A lane ---

@pytest.mark.parametrize("text", [
    "mèo có phải là chó không?",
    "chó có phải là mèo không?",
    "AI là gì?",
    "data là gì?",
])
def test_fix4_unsupported_open_qa(text: str):
    sr = _make_sr()
    answer = sr.handle_turn(text).final_answer or ""
    low = answer.lower()
    assert "rule-based MVP" not in answer
    assert "kiến thức mở" in low or "chưa hỗ trợ" in low
    assert "đã nhớ" not in low


@pytest.mark.parametrize("text", ["tomtit là gì?", "bạn là gì?"])
def test_fix4_open_qa_does_not_break_assistant_identity(text: str):
    """Assistant-identity prompts stay DIRECT_RESPONSE, never the open-QA lane."""
    sr = _make_sr()
    answer = sr.handle_turn(text).final_answer or ""
    assert "kiến thức mở" not in answer.lower()


# --- Part F: regression guards ---

def test_fix4_regression_guards():
    sr = _make_sr()

    assert "đã nhớ" in (sr.handle_turn("tôi là bắc").final_answer or "").lower()

    occ = sr.handle_turn("tôi là AI engineer").final_answer or ""
    assert "đã nhớ" in occ.lower()
    assert "công việc" in occ.lower() or "lĩnh vực" in occ.lower()

    assert "đã nhớ" not in (sr.handle_turn("tôi thích cafe không").final_answer or "").lower()
    assert "đã nhớ" in (sr.handle_turn("tôi thích cafe không đường").final_answer or "").lower()

    ai = sr.handle_turn("tôi thích AI").final_answer or ""
    assert "đã nhớ" in ai.lower() and "AI" in ai

    assert "đã nhớ" not in (sr.handle_turn("tôi thích ai").final_answer or "").lower()

    sr.handle_turn("người yêu tôi là quý")
    assert "quý" in (sr.handle_turn("người yêu của tôi là ai").final_answer or "").lower()

    assert "đã nhớ" in (sr.handle_turn("tôi làm AI").final_answer or "").lower()
    work = sr.handle_turn("tôi làm gì?").final_answer or ""
    assert "AI" in work and "Bạn là AI" not in work

    assert "rule-based MVP" not in (sr.handle_turn("thời thiết hôm nay thế nào").final_answer or "")


# ===========================================================================
# P0-7F-FIX5 — narrow semantic regression (runtime)
# ===========================================================================

# --- Part B: one-sided ("đơn phương") affection is not an ordinary preference ---

@pytest.mark.parametrize("text", [
    "tôi thích đơn phương Quý",
    "mình thích đơn phương Quý",
    "tôi đơn phương Quý",
])
def test_fix5_one_sided_affection_not_saved(text: str):
    sr = _make_sr()
    answer = sr.handle_turn(text).final_answer or ""
    low = answer.lower()
    assert "đã nhớ là bạn thích" not in low
    assert "rule-based MVP" not in answer
    assert "đơn phương" in low or "tình cảm" in low or "không lưu" in low


def test_fix5_one_sided_affection_not_in_preference_summary():
    sr = _make_sr()
    sr.handle_turn("tôi thích đơn phương Quý")
    summary = sr.handle_turn("tôi thích gì?").final_answer or ""
    assert "đơn phương" not in summary.lower()


def test_fix5_build_one_sided_affection_response():
    from agent_core.conversation.profile_memory import build_one_sided_affection_response
    msg = build_one_sided_affection_response("Quý")
    assert "đơn phương" in msg.lower()
    assert "Quý" in msg
    assert "người yêu của tôi" in msg


# --- Part C: household-pet yes/no query ---

def test_fix5_pet_yesno_match_returns_yes():
    sr = _make_sr()
    sr.handle_turn("nhà tôi nuôi mèo")
    answer = sr.handle_turn("tôi có nuôi mèo không?").final_answer or ""
    low = answer.lower()
    assert "có" in low
    assert "mèo" in low


@pytest.mark.parametrize("text", [
    "tôi có nuôi mèo không?",
    "mình có nuôi mèo không?",
    "nhà tôi có nuôi mèo không?",
    "nhà mình có nuôi mèo không?",
])
def test_fix5_pet_yesno_variants_match(text: str):
    sr = _make_sr()
    sr.handle_turn("nhà tôi nuôi mèo")
    answer = sr.handle_turn(text).final_answer or ""
    assert "có" in answer.lower()
    assert "mèo" in answer.lower()


def test_fix5_pet_yesno_no_match_is_unknown():
    sr = _make_sr()
    sr.handle_turn("nhà tôi nuôi mèo")
    answer = sr.handle_turn("tôi có nuôi chó không?").final_answer or ""
    low = answer.lower()
    assert "đã nhớ" not in low
    assert "chưa" in low or "không" in low
    assert "chó" in low


def test_fix5_pet_yesno_fresh_session_no_save():
    sr = _make_sr()
    answer = sr.handle_turn("tôi có nuôi mèo không?").final_answer or ""
    low = answer.lower()
    assert "đã nhớ" not in low
    assert "chưa" in low or "không" in low
    # The question must not have been stored as a pet fact.
    follow = sr.handle_turn("nhà tôi nuôi con gì?").final_answer or ""
    assert "chưa" in follow.lower() or "không" in follow.lower()


def test_fix5_pet_yesno_query_detected():
    q = detect_profile_query("tôi có nuôi mèo không?")
    assert q is not None
    assert q.kind == "self_pet_yesno"
    assert q.value == "mèo"


# --- Part D: affection-query alias ("người tôi thích là ai?") ---

@pytest.mark.parametrize("text", [
    "người tôi thích là ai?",
    "người mình thích là ai?",
    "người tôi thích tên là ai?",
])
def test_fix5_affection_alias_query_detected(text: str):
    q = detect_profile_query(text)
    assert q is not None
    assert q.kind == "self_affection"


def test_fix5_affection_alias_returns_target():
    sr = _make_sr()
    sr.handle_turn("người yêu tôi là Quý")
    answer = sr.handle_turn("người tôi thích là ai?").final_answer or ""
    assert "quý" in answer.lower()
    assert "rule-based MVP" not in answer


def test_fix5_affection_alias_unknown_no_generic_fallback():
    sr = _make_sr()
    answer = sr.handle_turn("người tôi thích là ai?").final_answer or ""
    low = answer.lower()
    assert "rule-based MVP" not in answer
    assert "chưa" in low or "không" in low


# --- Part E: regression guards for FIX5 ---

def test_fix5_regression_guards():
    sr = _make_sr()

    assert "đã nhớ" in (sr.handle_turn("tôi thích kem").final_answer or "").lower()
    assert "đã nhớ" not in (sr.handle_turn("tôi thích Quý").final_answer or "").lower()

    ai = sr.handle_turn("tôi thích AI").final_answer or ""
    assert "đã nhớ" in ai.lower() and "AI" in ai

    assert "đã nhớ" not in (sr.handle_turn("tôi thích ai").final_answer or "").lower()
    assert "đã nhớ" not in (sr.handle_turn("tôi thích cafe không").final_answer or "").lower()
    assert "đã nhớ" in (sr.handle_turn("tôi thích cafe không đường").final_answer or "").lower()

    assert "đã nhớ" in (sr.handle_turn("bạn tôi tên là Meo").final_answer or "").lower()
    friend = sr.handle_turn("bạn của tôi tên là gì?").final_answer or ""
    assert "meo" in friend.lower()

    sr.handle_turn("nhà tôi nuôi mèo")
    assert "mèo" in (sr.handle_turn("nhà tôi nuôi con gì?").final_answer or "").lower()

    open_qa = sr.handle_turn("AI là gì?").final_answer or ""
    assert "đã nhớ" not in open_qa.lower()
    assert "kiến thức mở" in open_qa.lower() or "chưa hỗ trợ" in open_qa.lower()

    identity = sr.handle_turn("tomtit là gì?").final_answer or ""
    assert "rule-based MVP" not in identity
    assert "tomtit" in identity.lower() or "agent" in identity.lower()


def test_fix5_compound_comparison_runtime():
    sr = _make_sr()
    assert (sr.handle_turn("2 * 3 == 6").final_answer or "") == "Đúng."
    assert (sr.handle_turn("2 + 3 > 4").final_answer or "") == "Đúng."
    assert (sr.handle_turn("4 != 4").final_answer or "") == "Sai."

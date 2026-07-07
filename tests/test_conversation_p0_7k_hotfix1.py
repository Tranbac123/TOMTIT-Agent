"""CONV-P0 P0-7K-FIX5B-FIX3-FIX2-FIX1-HOTFIX1 regression tests.

Manual Web testing after the FIX5B-FIX3-FIX2-FIX1 merge surfaced six regression
groups. These tests lock the repaired behaviour:

A. Natural current-name update ("bây giờ tôi tên là BB").
B. Self-name alias resolution inside memory queries.
C. Negative affection evidence answers "no" (not "unknown").
D. Third-party relation modifiers with USER as object ("quý cũng thích tôi").
E. Reminder-embedded negative affection.
F. Answer feedback/repair with last-question context.

No external provider, LLM, or network is ever exercised.
"""
from __future__ import annotations

from agent_core.runtime.runtime_agent import build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime


def _make_session() -> SessionRuntime:
    agent, store = build_local_agent()
    return SessionRuntime(agent, store)


def _reply(session: SessionRuntime, text: str) -> str:
    return session.handle_turn(text).final_answer or ""


def _is_write(ans: str) -> bool:
    low = ans.lower()
    return any(k in low for k in ("đã nhớ", "đã lưu", "đã ghi nhận", "đã cập nhật"))


def _is_generic(ans: str) -> bool:
    low = ans.lower()
    return "rule-based mvp" in low or "chưa xử lý được" in low


def _is_unknown(ans: str) -> bool:
    low = ans.lower()
    return any(k in low for k in ("chưa", "không biết", "không có thông tin"))


# ---------------------------------------------------------------------------
# A — natural current-name update
# ---------------------------------------------------------------------------

def test_p0_7k_hotfix1_natural_name_update_bay_gio_toi_ten():
    s = _make_session()
    _reply(s, "tôi là bắc")
    ans = _reply(s, "bây giờ tôi tên là BB")
    assert not _is_generic(ans) and _is_write(ans)
    assert "bb" in ans.lower() and "bắc" in ans.lower()
    assert "bb" in _reply(s, "tôi tên là gì?").lower()


def test_p0_7k_hotfix1_natural_name_update_ten_toi_bay_gio():
    s = _make_session()
    _reply(s, "tôi là bắc")
    ans = _reply(s, "tên tôi bây giờ là BB")
    assert not _is_generic(ans) and _is_write(ans) and "bb" in ans.lower()
    assert "bb" in _reply(s, "tôi tên là gì?").lower()


def test_p0_7k_hotfix1_existing_name_assertion_updates_without_requiring_sua_ten():
    s = _make_session()
    _reply(s, "tôi là bắc")
    ans = _reply(s, "tôi tên là BB")
    assert not _is_generic(ans) and _is_write(ans) and "bb" in ans.lower()
    assert "bb" in _reply(s, "tôi tên là gì?").lower()


def test_p0_7k_hotfix1_role_shape_does_not_corrupt_name():
    for role in ("tôi là DEV", "tôi là developer", "tôi là nông dân"):
        s = _make_session()
        _reply(s, "tôi là bắc")
        _reply(s, role)
        assert "bắc" in _reply(s, "tôi tên là gì?").lower()


# ---------------------------------------------------------------------------
# B — self-name alias in memory queries
# ---------------------------------------------------------------------------

def test_p0_7k_hotfix1_self_alias_batch_preference_query_current_name():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "tôi thích ăn cam nhưng không thích ăn cóc")
    ans = _reply(s, "bắc có thích ăn cam và cóc không?")
    low = ans.lower()
    assert "cam" in low and "cóc" in low and "không" in low and not _is_unknown(ans)


def test_p0_7k_hotfix1_self_alias_batch_preference_query_old_name_after_update():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "tôi thích ăn cam nhưng không thích ăn cóc")
    _reply(s, "bây giờ tôi tên là BB")
    ans = _reply(s, "bắc có thích ăn cam và cóc không?")
    low = ans.lower()
    assert "cam" in low and "cóc" in low and "không" in low and not _is_unknown(ans)
    ans_new = _reply(s, "bb có thích ăn cam và cóc không?")
    low_new = ans_new.lower()
    assert "cam" in low_new and "cóc" in low_new and not _is_unknown(ans_new)


# ---------------------------------------------------------------------------
# C — negative affection evidence answers "no", not "unknown"
# ---------------------------------------------------------------------------

def test_p0_7k_hotfix1_negative_affection_answers_no_not_unknown():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "tôi thích quý")
    _reply(s, "tôi không thích quý nữa")
    ans = _reply(s, "tôi có thích quý không?")
    assert "quý" in ans.lower() and "không" in ans.lower() and not _is_unknown(ans)


def test_p0_7k_hotfix1_named_self_negative_affection_answers_no():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "tôi thích quý")
    _reply(s, "tôi không thích quý nữa")
    ans = _reply(s, "bắc có thích quý không?")
    assert "quý" in ans.lower() and "không" in ans.lower() and not _is_unknown(ans)


# ---------------------------------------------------------------------------
# D — third-party relation modifiers (USER as object)
# ---------------------------------------------------------------------------

def test_p0_7k_hotfix1_third_party_relation_cung_thich_toi():
    s = _make_session()
    _reply(s, "tôi là bắc")
    ans = _reply(s, "quý cũng thích tôi")
    assert not _is_generic(ans) and _is_write(ans) and "quý" in ans.lower()
    q_self = _reply(s, "quý có thích tôi không?")
    assert "quý" in q_self.lower() and "có" in q_self.lower()
    q_alias = _reply(s, "quý có thích bắc không?")
    assert "quý" in q_alias.lower() and "có" in q_alias.lower()


def test_p0_7k_hotfix1_third_party_relation_negative_toi():
    s = _make_session()
    _reply(s, "tôi là bắc")
    ans = _reply(s, "quý không thích tôi")
    assert not _is_generic(ans) and _is_write(ans) and "quý" in ans.lower()
    q = _reply(s, "quý có thích tôi không?")
    assert "quý" in q.lower() and "không" in q.lower() and not _is_unknown(q)


# ---------------------------------------------------------------------------
# E — reminder-embedded negative affection
# ---------------------------------------------------------------------------

def test_p0_7k_hotfix1_reminder_embedded_negative_affection():
    s = _make_session()
    _reply(s, "tôi thích quý")
    ans = _reply(s, "tôi đã nói là tôi không thích quý nữa")
    assert not _is_generic(ans) and "quý" in ans.lower() and "không" in ans.lower()
    q = _reply(s, "tôi có thích quý không?")
    assert "quý" in q.lower() and "không" in q.lower() and not _is_unknown(q)


# ---------------------------------------------------------------------------
# F — answer feedback / repair with last-question context
# ---------------------------------------------------------------------------

def test_p0_7k_hotfix1_feedback_repair_uses_last_question_context():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "tôi thích quý")
    _reply(s, "tôi không thích quý nữa")
    _reply(s, "bắc có thích quý không?")
    ans = _reply(s, "bạn phải trả lời là không vì tôi đã cung cấp thông tin cho bạn rồi")
    assert not _is_generic(ans) and not _is_write(ans)
    low = ans.lower()
    assert "không" in low or "đúng" in low or "chưa đúng" in low


def test_p0_7k_hotfix1_feedback_no_write_no_fallback():
    s = _make_session()
    ans = _reply(s, "bạn trả lời sai rồi")
    assert not _is_generic(ans) and not _is_write(ans)


# ---------------------------------------------------------------------------
# Web manual regression sequence (FastAPI TestClient, in-process)
# ---------------------------------------------------------------------------

def test_p0_7k_hotfix1_web_manual_regression_sequence():
    from fastapi.testclient import TestClient

    from agent_core.web_api.app import create_app

    with TestClient(create_app()) as client:
        def new_session() -> str:
            r = client.post("/api/sessions", json={"user_id": "u1"})
            r.raise_for_status()
            return r.json()["session_id"]

        def chat(sid: str, text: str) -> str:
            r = client.post(
                "/api/chat",
                json={"session_id": sid, "message": text, "user_id": "u1"},
            )
            r.raise_for_status()
            am = r.json().get("assistant_message") or {}
            return am.get("content", "") if isinstance(am, dict) else str(am)

        sid = new_session()
        chat(sid, "tôi là bắc")
        ans = chat(sid, "bây giờ tôi tên là BB")
        assert _is_write(ans) and "bb" in ans.lower()
        assert "bb" in chat(sid, "tôi tên là gì?").lower()

        sid = new_session()
        chat(sid, "tôi là bắc")
        chat(sid, "tôi thích ăn cam nhưng không thích ăn cóc")
        ans = chat(sid, "bắc có thích ăn cam và cóc không?")
        low = ans.lower()
        assert "cam" in low and "cóc" in low and "không" in low and not _is_unknown(ans)

        sid = new_session()
        chat(sid, "tôi là bắc")
        chat(sid, "tôi thích quý")
        chat(sid, "tôi không thích quý nữa")
        ans = chat(sid, "tôi có thích quý không?")
        assert "quý" in ans.lower() and "không" in ans.lower() and not _is_unknown(ans)


# ===========================================================================
# CONV-P0 P0-7K-HOTFIX1-FIX1 — repair the two Codex-blocked reminder cases
# ===========================================================================
#
# FIX1.A: embedded negative-affection reminder must record negative evidence even
#         when no active positive affection exists (was hitting a "don't save person
#         affection" guard → follow-up answered "unknown").
# FIX1.B: a generic "bạn không nhớ à/sao?" reminder must not fall to the generic MVP
#         response and must not write memory — while a goal challenge that merely ends
#         with "bạn không nhớ à" ("tôi vẫn muốn làm ML bạn không nhớ à") still saves.


def test_p0_7k_hotfix1_fix1_embedded_negative_affection_reminder_mentions_target_and_answers_no():
    # Standalone (no prior "tôi thích quý") — the Codex-failing case.
    s = _make_session()
    _reply(s, "tôi là bắc")
    ans = _reply(s, "tôi đã nói là tôi không thích quý nữa")
    assert not _is_generic(ans) and "quý" in ans.lower() and "không" in ans.lower()
    q = _reply(s, "tôi có thích quý không?")
    assert "quý" in q.lower() and "không" in q.lower() and not _is_unknown(q)


def test_p0_7k_hotfix1_fix1_embedded_negative_affection_reminder_variants():
    variants = [
        "tôi đã nói tôi không thích quý nữa",
        "tôi nói rồi mà tôi không thích quý nữa",
        "tôi bảo rồi mà tôi không thích quý nữa",
        "mình đã nói là mình không thích quý nữa",
    ]
    for text in variants:
        s = _make_session()
        _reply(s, "tôi thích quý")
        ans = _reply(s, text)
        assert not _is_generic(ans) and "quý" in ans.lower() and "không" in ans.lower(), text
        q = _reply(s, "tôi có thích quý không?")
        assert "quý" in q.lower() and "không" in q.lower() and not _is_unknown(q), text


def test_p0_7k_hotfix1_fix1_generic_reminder_no_fallback_no_write():
    for text in [
        "tôi đã nói rồi bạn không nhớ sao?",
        "tôi nói rồi mà bạn không nhớ à?",
        "tôi đã nói rồi mà",
        "bạn không nhớ à?",
        "bạn không nhớ sao?",
        "tôi bảo rồi mà",
    ]:
        s = _make_session()
        ans = _reply(s, text)
        assert not _is_generic(ans) and not _is_write(ans), text


def test_p0_7k_hotfix1_fix1_generic_reminder_does_not_pollute_summary():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "tôi đã nói rồi bạn không nhớ sao?")
    summary = _reply(s, "bạn nhớ gì về tôi").lower()
    for bad in ("tôi đã nói rồi", "không nhớ sao", "bạn không nhớ"):
        assert bad not in summary, summary


def test_p0_7k_hotfix1_fix1_generic_reminder_does_not_steal_goal_challenge():
    s = _make_session()
    ans = _reply(s, "tôi vẫn muốn làm ML bạn không nhớ à")
    assert not _is_generic(ans) and _is_write(ans) and "ml" in ans.lower()
    recall = _reply(s, "tôi muốn làm gì?").lower()
    assert "ml" in recall and "không nhớ" not in recall


def test_p0_7k_hotfix1_fix1_web_failed_codex_cases():
    from fastapi.testclient import TestClient

    from agent_core.web_api.app import create_app

    with TestClient(create_app()) as client:
        def new_session() -> str:
            r = client.post("/api/sessions", json={"user_id": "u1"})
            r.raise_for_status()
            return r.json()["session_id"]

        def chat(sid: str, text: str) -> str:
            r = client.post(
                "/api/chat",
                json={"session_id": sid, "message": text, "user_id": "u1"},
            )
            r.raise_for_status()
            am = r.json().get("assistant_message") or {}
            return am.get("content", "") if isinstance(am, dict) else str(am)

        # Embedded negative affection reminder (standalone).
        sid = new_session()
        chat(sid, "tôi là bắc")
        chat(sid, "tôi thích quý")
        ans = chat(sid, "tôi đã nói là tôi không thích quý nữa")
        assert "quý" in ans.lower() and "không" in ans.lower()
        q = chat(sid, "tôi có thích quý không?")
        assert "quý" in q.lower() and "không" in q.lower() and not _is_unknown(q)

        # Generic reminder — no fallback, no write, no summary pollution.
        sid = new_session()
        chat(sid, "tôi là bắc")
        ans = chat(sid, "tôi đã nói rồi bạn không nhớ sao?")
        assert not _is_generic(ans) and not _is_write(ans)
        summary = chat(sid, "bạn nhớ gì về tôi").lower()
        for bad in ("tôi đã nói rồi", "không nhớ sao", "bạn không nhớ"):
            assert bad not in summary, summary


# ===========================================================================
# CONV-P0 P0-7K-FIX5C-LITE — minimal person relation query core
# ===========================================================================
#
# USER -> likes -> person (outgoing) and person -> likes -> USER (incoming) are
# distinct edges and must never be inferred into each other.


def test_p0_7k_fix5c_lite_incoming_affection_set_query():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "quý thích tôi")
    _reply(s, "may thích tôi")
    _reply(s, "linh cũng thích tôi")
    ans = _reply(s, "ai đang thích tôi?")
    low = ans.lower()
    assert not _is_generic(ans) and all(n in low for n in ("quý", "may", "linh"))


def test_p0_7k_fix5c_lite_incoming_affection_typo_tich():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "quý thích tôi")
    _reply(s, "may thích tôi")
    ans = _reply(s, "ai đang tích tôi?")
    low = ans.lower()
    assert not _is_generic(ans) and "quý" in low and "may" in low


def test_p0_7k_fix5c_lite_batch_third_party_relation_query_all_positive():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "quý thích tôi")
    _reply(s, "may thích tôi")
    ans = _reply(s, "quý và may có thích tôi không?")
    low = ans.lower()
    assert not _is_generic(ans) and "quý" in low and "may" in low and "có" in low
    # Old/current self alias as the object resolves to USER too.
    ans_alias = _reply(s, "quý và may có thích bắc không?")
    assert "quý" in ans_alias.lower() and "may" in ans_alias.lower()


def test_p0_7k_fix5c_lite_batch_third_party_relation_query_mixed_state():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "quý thích tôi")
    _reply(s, "may không thích tôi")
    ans = _reply(s, "quý, may và linh có thích tôi không?")
    low = ans.lower()
    assert not _is_generic(ans)
    assert "quý" in low and "may" in low and "linh" in low
    assert "không" in low and _is_unknown(ans)


def test_p0_7k_fix5c_lite_outgoing_self_affection_batch_query():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "tôi thích quý")
    _reply(s, "tôi cũng thích may")
    ans = _reply(s, "tôi có thích quý và may không?")
    low = ans.lower()
    assert not _is_generic(ans) and "quý" in low and "may" in low and "có" in low
    _reply(s, "tôi không thích quý nữa")
    mixed = _reply(s, "tôi có thích quý và may không?").lower()
    assert "quý" in mixed and "may" in mixed and "không" in mixed


def test_p0_7k_fix5c_lite_outgoing_self_affection_set_query_after_retraction():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "tôi thích quý")
    _reply(s, "tôi cũng thích may")
    assert "quý" in _reply(s, "tôi đang thích ai?").lower()
    _reply(s, "tôi không thích quý nữa")
    ans = _reply(s, "tôi đang thích ai?").lower()
    assert "may" in ans and "quý" not in ans


def test_p0_7k_fix5c_lite_embedded_self_affection_reminder():
    s = _make_session()
    _reply(s, "tôi thích quý")
    _reply(s, "tôi không thích quý nữa")
    ans = _reply(s, "tôi đã nói là tôi cũng thích may rồi")
    assert not _is_generic(ans) and _is_write(ans) and "may" in ans.lower()
    recall = _reply(s, "tôi đang thích ai?").lower()
    assert "may" in recall and "quý" not in recall


def test_p0_7k_fix5c_lite_person_likes_who_query():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "may thích tôi")
    ans = _reply(s, "may thích ai?")
    low = ans.lower()
    assert not _is_generic(ans) and "may" in low and ("bạn" in low or "bắc" in low)


def test_p0_7k_fix5c_lite_old_self_alias_subject_statement():
    s = _make_session()
    _reply(s, "tôi là bắc")
    _reply(s, "bây giờ tôi tên là BB")
    ans = _reply(s, "bây giờ bắc thích quý")
    assert not _is_generic(ans) and _is_write(ans) and "quý" in ans.lower()
    recall = _reply(s, "tôi có thích quý không?").lower()
    assert "quý" in recall and "có" in recall


def test_p0_7k_fix5c_lite_no_inverse_hallucination():
    # incoming edge does not imply outgoing
    s = _make_session()
    _reply(s, "may thích tôi")
    ans = _reply(s, "tôi có thích may không?")
    assert "may" in ans.lower() and _is_unknown(ans)
    # outgoing edge does not imply incoming
    s2 = _make_session()
    _reply(s2, "tôi thích may")
    ans2 = _reply(s2, "may có thích tôi không?")
    assert "may" in ans2.lower() and _is_unknown(ans2)


def test_p0_7k_fix5c_lite_person_likes_who_excludes_object_facts():
    # "may thích ai?" must not surface a would-be object fact; with no person->USER edge
    # it stays unknown (never generic fallback).
    s = _make_session()
    _reply(s, "tôi là bắc")
    ans = _reply(s, "may thích ai?")
    assert not _is_generic(ans) and _is_unknown(ans)


def test_p0_7k_fix5c_lite_web_manual_relation_sequence():
    from fastapi.testclient import TestClient

    from agent_core.web_api.app import create_app

    with TestClient(create_app()) as client:
        def new_session() -> str:
            r = client.post("/api/sessions", json={"user_id": "u1"})
            r.raise_for_status()
            return r.json()["session_id"]

        def chat(sid: str, text: str) -> str:
            r = client.post(
                "/api/chat",
                json={"session_id": sid, "message": text, "user_id": "u1"},
            )
            r.raise_for_status()
            am = r.json().get("assistant_message") or {}
            return am.get("content", "") if isinstance(am, dict) else str(am)

        sid = new_session()
        chat(sid, "tôi là bắc")
        chat(sid, "quý thích tôi")
        chat(sid, "may thích tôi")
        chat(sid, "linh cũng thích tôi")
        incoming = chat(sid, "ai đang thích tôi?").lower()
        assert all(n in incoming for n in ("quý", "may", "linh"))
        batch = chat(sid, "quý và may có thích tôi không?").lower()
        assert "quý" in batch and "may" in batch and "có" in batch
        who = chat(sid, "may thích ai?").lower()
        assert "may" in who and ("bạn" in who or "bắc" in who)


# ===========================================================================
# CONV-P0 P0-7K-FIX6-LITE — minimal predicate/action fact core
# ===========================================================================
#
# "muốn <action> <object>" splits into distinct predicates. A trailing question
# pronoun ("cưới ai", "học gì") is a QUERY and must never be written. wants_to_marry
# is kept out of the general "muốn làm gì?" goal set; wants_to_learn/build are in it.


def test_p0_7k_fix6_lite_question_pronoun_not_written_wants_to_marry_ai():
    for text in ("tôi muốn cưới ai", "tôi muốn cưới ai?"):
        s = _make_session()
        ans = _reply(s, text)
        assert not _is_generic(ans) and not _is_write(ans), text
        summary = _reply(s, "bạn nhớ gì về tôi").lower()
        assert "cưới ai" not in summary


def test_p0_7k_fix6_lite_question_pronoun_not_written_wants_to_learn_gi():
    s = _make_session()
    ans = _reply(s, "tôi muốn học gì?")
    assert not _is_generic(ans) and not _is_write(ans)
    assert "học gì" not in _reply(s, "bạn nhớ gì về tôi").lower()


def test_p0_7k_fix6_lite_question_pronoun_not_written_wants_to_build_gi():
    s = _make_session()
    ans = _reply(s, "tôi muốn build gì?")
    assert not _is_generic(ans) and not _is_write(ans)
    assert "build gì" not in _reply(s, "bạn nhớ gì về tôi").lower()


def test_p0_7k_fix6_lite_wants_to_marry_store_and_query():
    s = _make_session()
    ans = _reply(s, "tôi muốn cưới quý")
    assert _is_write(ans) and "quý" in ans.lower() and "cưới" in ans.lower()
    recall = _reply(s, "tôi muốn cưới ai?").lower()
    assert "quý" in recall and not _is_unknown(recall)


def test_p0_7k_fix6_lite_wants_to_marry_excluded_from_general_do_query():
    s = _make_session()
    _reply(s, "tôi muốn cưới quý")
    do = _reply(s, "tôi muốn làm gì?").lower()
    assert "cưới" not in do and "quý" not in do


def test_p0_7k_fix6_lite_wants_to_learn_store_and_query():
    s = _make_session()
    ans = _reply(s, "tôi muốn học AI")
    assert _is_write(ans) and "ai" in ans.lower()
    learn = _reply(s, "tôi muốn học gì?").lower()
    assert "ai" in learn and not _is_unknown(learn)
    do = _reply(s, "tôi muốn làm gì?").lower()
    assert "ai" in do


def test_p0_7k_fix6_lite_wants_to_learn_not_current_learning():
    s = _make_session()
    ans = _reply(s, "tôi muốn học AI").lower()
    assert "muốn học" in ans and "đang học" not in ans


def test_p0_7k_fix6_lite_mixed_wants_to_actions_query():
    s = _make_session()
    _reply(s, "tôi muốn cưới quý")
    _reply(s, "tôi muốn học AI")
    _reply(s, "tôi muốn build Agent")
    assert "quý" in _reply(s, "tôi muốn cưới ai?").lower()
    assert "ai" in _reply(s, "tôi muốn học gì?").lower()
    assert "agent" in _reply(s, "tôi muốn build gì?").lower()
    do = _reply(s, "tôi muốn làm gì?").lower()
    assert "ai" in do and "agent" in do and "cưới" not in do and "quý" not in do


def test_p0_7k_fix6_lite_dirty_query_not_in_summary():
    s = _make_session()
    _reply(s, "tôi muốn cưới ai")
    _reply(s, "tôi muốn học AI")
    do = _reply(s, "tôi muốn làm gì?").lower()
    assert "cưới ai" not in do and "ai" in do
    assert "cưới ai" not in _reply(s, "bạn nhớ gì về tôi").lower()


def test_p0_7k_fix6_lite_coordinated_incoming_affection_write():
    s = _make_session()
    _reply(s, "tôi là bắc")
    ans = _reply(s, "may và quý đều thích tôi")
    assert not _is_generic(ans) and _is_write(ans)
    assert "may" in ans.lower() and "quý" in ans.lower()
    incoming = _reply(s, "ai đang thích tôi?").lower()
    assert "may" in incoming and "quý" in incoming
    # 3-way coordination
    s2 = _make_session()
    _reply(s2, "tôi là bắc")
    _reply(s2, "may, quý và linh đều thích tôi")
    inc = _reply(s2, "ai đang thích tôi?").lower()
    assert all(n in inc for n in ("may", "quý", "linh"))


def test_p0_7k_fix6_lite_preserve_no_inverse_affection():
    s = _make_session()
    _reply(s, "may thích tôi")
    assert _is_unknown(_reply(s, "tôi có thích may không?"))
    s2 = _make_session()
    _reply(s2, "tôi thích may")
    assert _is_unknown(_reply(s2, "may có thích tôi không?"))


def test_p0_7k_fix6_lite_web_manual_predicate_sequence():
    from fastapi.testclient import TestClient

    from agent_core.web_api.app import create_app

    with TestClient(create_app()) as client:
        def new_session() -> str:
            r = client.post("/api/sessions", json={"user_id": "u1"})
            r.raise_for_status()
            return r.json()["session_id"]

        def chat(sid: str, text: str) -> str:
            r = client.post(
                "/api/chat",
                json={"session_id": sid, "message": text, "user_id": "u1"},
            )
            r.raise_for_status()
            am = r.json().get("assistant_message") or {}
            return am.get("content", "") if isinstance(am, dict) else str(am)

        sid = new_session()
        chat(sid, "tôi là bắc")
        marry_ai = chat(sid, "tôi muốn cưới ai")
        assert not _is_write(marry_ai)
        assert "cưới ai" not in chat(sid, "bạn nhớ gì về tôi").lower()
        assert _is_write(chat(sid, "tôi muốn cưới quý"))
        assert "quý" in chat(sid, "tôi muốn cưới ai?").lower()
        learn = chat(sid, "tôi muốn học AI")
        assert _is_write(learn) and "đang học" not in learn.lower()
        assert "ai" in chat(sid, "tôi muốn học gì?").lower()
        do = chat(sid, "tôi muốn làm gì?").lower()
        assert "ai" in do and "cưới ai" not in do

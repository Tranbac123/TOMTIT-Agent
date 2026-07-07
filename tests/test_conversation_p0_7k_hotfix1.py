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

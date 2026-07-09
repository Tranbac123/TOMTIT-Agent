"""CONV-P0 P0-7K-FIX8 — temporal v2 + mutual/compound relation + query-splitter regressions.

Focused regression coverage for real-chat memory/runtime failures observed after the
CONV-P0 xfail burndown. Each test exercises the shipped ``SessionRuntime.handle_turn`` path
(local rule-based runtime — no LLM, no network) and asserts BEHAVIOR: no generic fallback,
required domain tokens, that dirty objects are never stored, and that unknown is not treated
as a negative answer.
"""
from __future__ import annotations

from agent_core.runtime.runtime_agent import build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime

_GENERIC_FALLBACK = "tôi chưa xử lý được yêu cầu này trong bản rule-based mvp hiện tại"


def _make_sr() -> SessionRuntime:
    agent, store = build_local_agent()
    return SessionRuntime(agent, store)


def _ans(sr: SessionRuntime, text: str) -> str:
    return (sr.handle_turn(text).final_answer or "")


def _low(sr: SessionRuntime, text: str) -> str:
    return _ans(sr, text).lower()


def _no_generic(answer: str) -> bool:
    return _GENERIC_FALLBACK not in answer.lower()


# ---------------------------------------------------------------------------
# 1. Temporal suffix + query (A)
# ---------------------------------------------------------------------------

def test_fix8_temporal_suffix_write_and_query():
    sr = _make_sr()
    ack = _ans(sr, "tôi muốn làm LLM hôm nay")
    assert _no_generic(ack) and "hôm nay" in ack.lower() and "llm" in ack.lower(), ack
    # The stored plan is clean ("làm LLM"), never the dirty "làm LLM hôm nay".
    q = _low(sr, "hôm nay tôi muốn làm gì?")
    assert "llm" in q and "làm llm hôm nay" not in q, q


def test_fix8_temporal_prefix_still_works():
    sr = _make_sr()
    ack = _low(sr, "hôm nay tôi định làm SLM")
    assert _no_generic(ack) and "slm" in ack, ack
    assert "slm" in _low(sr, "hôm nay tôi muốn làm gì?")


# ---------------------------------------------------------------------------
# 2. Temporal retraction + generic-summary contamination guard (B)
# ---------------------------------------------------------------------------

def test_fix8_temporal_retraction_clears_active_and_generic_summary():
    sr = _make_sr()
    _ans(sr, "tôi muốn làm LLM hôm nay")
    retract = _low(sr, "hôm nay tôi không muốn làm LLM nữa")
    assert _no_generic(retract) and "bỏ" in retract and "llm" in retract, retract
    today = _low(sr, "hôm nay tôi muốn làm gì?")
    assert "llm" not in today and ("chưa" in today or "không" in today), today
    # No dirty terminal-"hôm nay" goal leaks into the generic dự-định summary.
    generic = _low(sr, "tôi sẽ làm gì?")
    assert "llm hôm nay" not in generic and "làm llm hôm nay" not in generic, generic


# ---------------------------------------------------------------------------
# 3. Intention alias "định làm" == "muốn làm" (C)
# ---------------------------------------------------------------------------

def test_fix8_intention_alias_dinh_lam():
    sr = _make_sr()
    ack = _low(sr, "tôi định làm Chatbox")
    assert _no_generic(ack) and "chatbox" in ack, ack
    intend_q = _low(sr, "tôi có định làm ChatBox không?")
    assert _no_generic(intend_q) and "có" in intend_q and "chatbox" in intend_q, intend_q
    # "muốn làm" aliases the same intention family.
    want_q = _low(sr, "tôi có muốn làm ChatBox không?")
    assert _no_generic(want_q) and "có" in want_q and "chatbox" in want_q, want_q


# ---------------------------------------------------------------------------
# 4. Unknown != negative (D)
# ---------------------------------------------------------------------------

def test_fix8_unknown_intention_is_not_negative():
    sr = _make_sr()
    ans = _low(sr, "tôi có muốn làm Agent không?")
    assert _no_generic(ans) and not ans.startswith("không,"), ans
    assert "chưa" in ans or "không thấy" in ans, ans


def test_fix8_negative_intention_answers_no_with_evidence():
    sr = _make_sr()
    _ans(sr, "tôi định làm Agent")
    _ans(sr, "tôi không muốn làm Agent nữa")
    ans = _low(sr, "tôi có muốn làm Agent không?")
    assert _no_generic(ans) and "không" in ans and "agent" in ans, ans


# ---------------------------------------------------------------------------
# 5. "cps" typo yes/no query (E)
# ---------------------------------------------------------------------------

def test_fix8_cps_typo_today_yesno():
    sr = _make_sr()
    _ans(sr, "hôm nay tôi muốn làm LLM")
    ans = _low(sr, "tôi cps muốn làm LLM hôm nay không?")
    assert _no_generic(ans) and "có" in ans and "llm" in ans, ans


# ---------------------------------------------------------------------------
# 6. Embedded correction "tôi nói là ..." (F)
# ---------------------------------------------------------------------------

def test_fix8_embedded_correction_extracts_inner_fact():
    sr = _make_sr()
    ack = _low(sr, "tôi nói là tôi định làm có nghĩa là tôi muốn làm Chatbox")
    assert _no_generic(ack) and "chatbox" in ack, ack
    # The meta wrapper is never stored as the object.
    assert "làm có nghĩa" not in ack, ack
    q = _low(sr, "tôi có muốn làm Chatbox không?")
    assert _no_generic(q) and "có" in q and "chatbox" in q, q


# ---------------------------------------------------------------------------
# 7. Historical like query (G)
# ---------------------------------------------------------------------------

def test_fix8_historical_like_retracted():
    sr = _make_sr()
    _ans(sr, "tôi thích ăn kem")
    _ans(sr, "tôi không thích ăn kem nữa")
    ans = _low(sr, "tôi có từng thích ăn kem không?")
    assert _no_generic(ans) and "có" in ans and "từng" in ans and "kem" in ans, ans
    assert "hiện tại" in ans or "nhưng" in ans, ans


def test_fix8_historical_like_still_active():
    sr = _make_sr()
    _ans(sr, "tôi thích ăn kem")
    ans = _low(sr, "tôi có từng thích ăn kem không?")
    assert _no_generic(ans) and "có" in ans and "kem" in ans, ans


def test_fix8_historical_like_never_seen():
    sr = _make_sr()
    ans = _low(sr, "tôi có từng thích ăn kem không?")
    assert _no_generic(ans) and "chưa" in ans and "kem" in ans, ans


# ---------------------------------------------------------------------------
# 8. Mutual relation query (H)
# ---------------------------------------------------------------------------

def test_fix8_mutual_relation_both_sides():
    sr = _make_sr()
    _ans(sr, "tôi thích Quý")
    _ans(sr, "quý cũng thích tôi")
    ans = _low(sr, "tôi và quý có thích nhau không?")
    assert _no_generic(ans) and "có" in ans and "quý" in ans, ans
    assert "thích bạn" in ans or "bạn thích" in ans, ans


def test_fix8_mutual_relation_one_side_only():
    sr = _make_sr()
    _ans(sr, "tôi thích Quý")
    ans = _low(sr, "tôi và quý có thích nhau không?")
    assert _no_generic(ans) and "quý" in ans and "chưa thấy" in ans, ans


# ---------------------------------------------------------------------------
# 9. Compound relation write (I)
# ---------------------------------------------------------------------------

def test_fix8_compound_relation_write_both_edges():
    sr = _make_sr()
    _ans(sr, "tôi thích Quý")
    _ans(sr, "quý cũng thích tôi")
    ack = _low(sr, "may cũng thích tôi và tôi cũng thích may")
    assert _no_generic(ack) and "may" in ack, ack
    assert "thích bạn" in ack and "bạn cũng thích" in ack, ack
    incoming = _low(sr, "ai đang thích tôi?")
    assert "quý" in incoming and "may" in incoming, incoming
    outgoing = _low(sr, "tôi đang thích ai?")
    assert "quý" in outgoing and "may" in outgoing, outgoing
    # "tôi" is never stored as a person the user likes.
    assert " tôi" not in outgoing.replace("tôi đang", ""), outgoing


# ---------------------------------------------------------------------------
# 10. Continuation "cả may nữa" after incoming query (J)
# ---------------------------------------------------------------------------

def test_fix8_continuation_incoming_admirer():
    sr = _make_sr()
    _ans(sr, "quý cũng thích tôi")
    _ans(sr, "ai đang thích tôi")
    ack = _low(sr, "cả may nữa")
    assert _no_generic(ack) and "may" in ack and "thích bạn" in ack, ack
    incoming = _low(sr, "ai đang thích tôi")
    assert "quý" in incoming and "may" in incoming, incoming


def test_fix8_continuation_without_incoming_context_asks_named_clarification():
    sr = _make_sr()
    # No incoming-affection query preceded this bare continuation → must not store an
    # admirer; must ask a named, context-specific clarification (not the generic prompt).
    ans = _low(sr, "cả may nữa")
    assert _no_generic(ans), ans
    assert "đã nhớ thêm: may cũng thích bạn" not in ans, ans
    assert any(tok in ans for tok in ("ý", "ngữ cảnh", "cụ thể", "may")), ans
    incoming = _low(sr, "ai đang thích tôi")
    assert "may" not in incoming, incoming


# ---------------------------------------------------------------------------
# 11. Double query split (K)
# ---------------------------------------------------------------------------

def test_fix8_double_affection_query_split():
    sr = _make_sr()
    _ans(sr, "tôi thích Quý")
    _ans(sr, "quý cũng thích tôi")
    _ans(sr, "may cũng thích tôi và tôi cũng thích may")
    ans = _low(sr, "ai đang thích tôi và tôi đang thích ai?")
    assert _no_generic(ans) and "quý" in ans and "may" in ans, ans
    assert "người đang thích bạn" in ans and "người bạn đang thích" in ans, ans


# ---------------------------------------------------------------------------
# 12. Pending repair "quan hệ" (L)
# ---------------------------------------------------------------------------

def test_fix8_pending_repair_relation_choice():
    sr = _make_sr()
    prompt = _low(
        sr,
        "tôi đã nói rồi mà, tôi thích quý và quý cũng thích tôi thì chúng tôi thích nhau",
    )
    assert "sửa phần nào" in prompt and "quan hệ" in prompt, prompt
    ans = _low(sr, "quan hệ")
    assert _no_generic(ans) and ("quan hệ" in ans or "ví dụ" in ans), ans


# ---------------------------------------------------------------------------
# 13. Relationship advice → bounded limitation (M)
# ---------------------------------------------------------------------------

def test_fix8_relationship_advice_limitation():
    sr = _make_sr()
    _ans(sr, "tôi thích Quý")
    _ans(sr, "quý cũng thích tôi")
    ans = _low(sr, "tôi với quý có nên yêu nhau không?")
    assert _no_generic(ans) and "quý" in ans, ans
    assert "tư vấn" in ans or "mvp" in ans or "chưa có" in ans, ans


# ---------------------------------------------------------------------------
# 14. Future date "ngày mai" → bounded limitation (N)
# ---------------------------------------------------------------------------

def test_fix8_future_date_limitation():
    sr = _make_sr()
    ans = _low(sr, "ngày mai tôi muốn làm gì?")
    assert _no_generic(ans) and "ngày mai" in ans, ans
    assert "hôm nay" in ans or "chưa hỗ trợ" in ans, ans

"""CONV-P0 P0-7K-FIX8-R1 — relation symmetry + person-entity cleanup + delete synonyms.

Focused regression coverage for web manual-test failures:
  A. mutual relation query symmetry ("X và/với tôi" == "tôi và/với X");
  B. discourse modifiers ("cũng"/"cả"/"nữa"/"đều") never become part of a person entity;
  C. relation edges/displays are deduped (repeated "cả may nữa" → one May);
  D. a broader confirmation set ("ok"/"yes"/…) confirms a pending memory wipe.

All tests drive the shipped ``SessionRuntime.handle_turn`` path (local rule-based runtime —
no LLM, no network) and assert behavior, not just wording.
"""
from __future__ import annotations

from agent_core.runtime.runtime_agent import build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime

_GENERIC_FALLBACK = "tôi chưa xử lý được yêu cầu này trong bản rule-based mvp hiện tại"


def _make_sr() -> SessionRuntime:
    agent, store = build_local_agent()
    return SessionRuntime(agent, store)


def _low(sr: SessionRuntime, text: str) -> str:
    return (sr.handle_turn(text).final_answer or "").lower()


def _no_generic(answer: str) -> bool:
    return _GENERIC_FALLBACK not in answer.lower()


# ---------------------------------------------------------------------------
# A. Mutual relation query symmetry
# ---------------------------------------------------------------------------

def test_r1_mutual_query_symmetry_va():
    sr = _make_sr()
    _low(sr, "tôi thích Quý")
    _low(sr, "quý cũng thích tôi")
    ans = _low(sr, "quý và tôi có thích nhau không?")
    assert _no_generic(ans) and "có" in ans and "quý" in ans, ans
    assert "thích bạn" in ans and ("bạn thích" in ans or "thích quý" in ans), ans


def test_r1_mutual_query_symmetry_voi():
    sr = _make_sr()
    _low(sr, "tôi thích Quý")
    _low(sr, "quý cũng thích tôi")
    ans = _low(sr, "quý với tôi có thích nhau không?")
    assert _no_generic(ans) and "có" in ans and "quý" in ans and "thích bạn" in ans, ans


def test_r1_mutual_query_one_side_only_reversed_order():
    sr = _make_sr()
    _low(sr, "tôi thích Quý")  # only USER->Quý; no Quý->USER
    ans = _low(sr, "quý và tôi có thích nhau không?")
    assert _no_generic(ans) and "quý" in ans and "chưa thấy" in ans, ans


# ---------------------------------------------------------------------------
# B. Discourse modifiers stripped from person entities
# ---------------------------------------------------------------------------

def test_r1_compound_relation_strips_modifier():
    sr = _make_sr()
    ack = _low(sr, "may cũng thích tôi và tôi cũng thích may")
    assert _no_generic(ack) and "may" in ack, ack
    incoming = _low(sr, "ai đang thích tôi")
    assert "may" in incoming and "may cũng" not in incoming, incoming


def test_r1_compound_relation_does_not_store_toi_as_liked():
    sr = _make_sr()
    _low(sr, "may cũng thích tôi và tôi cũng thích may")
    outgoing = _low(sr, "tôi đang thích ai")
    assert "may" in outgoing, outgoing
    # "tôi" is never listed as a person the user likes.
    assert "tôi" not in outgoing.replace("tôi đang", ""), outgoing


def test_r1_canonical_person_name_unit():
    from agent_core.conversation.profile_memory import canonical_person_name
    assert canonical_person_name("may cũng") == "may"
    assert canonical_person_name("cả may nữa") == "may"
    assert canonical_person_name("thêm linh nữa") == "linh"
    assert canonical_person_name("linh cũng đang") == "linh"
    # A genuine multi-word name is preserved.
    assert canonical_person_name("Quỳnh Anh") == "Quỳnh Anh"


# ---------------------------------------------------------------------------
# C. Relation edge / display dedupe
# ---------------------------------------------------------------------------

def test_r1_continuation_dedupe_repeated_name():
    sr = _make_sr()
    _low(sr, "quý cũng thích tôi")
    _low(sr, "ai đang thích tôi")
    _low(sr, "cả may nữa")
    _low(sr, "cả may nữa")
    ans = _low(sr, "ai đang thích tôi")
    assert "quý" in ans and "may" in ans, ans
    assert "may cũng" not in ans, ans
    assert ans.count("may") == 1, ans


def test_r1_multiple_continuation_names():
    sr = _make_sr()
    _low(sr, "quý cũng thích tôi")
    _low(sr, "ai đang thích tôi")
    _low(sr, "cả may nữa")
    _low(sr, "cả linh nữa")
    ans = _low(sr, "ai đang thích tôi")
    assert "quý" in ans and "may" in ans and "linh" in ans, ans
    assert "may cũng" not in ans, ans


def test_r1_profile_summary_relation_cleanup():
    sr = _make_sr()
    _low(sr, "may cũng thích tôi và tôi cũng thích may")
    _low(sr, "ai đang thích tôi")
    _low(sr, "cả linh nữa")
    summary = _low(sr, "bạn đã nhớ gì về tôi")
    assert "may" in summary and "linh" in summary, summary
    assert "may cũng" not in summary, summary


# ---------------------------------------------------------------------------
# D. Delete-memory confirmation synonyms
# ---------------------------------------------------------------------------

def test_r1_delete_confirmation_ok():
    sr = _make_sr()
    _low(sr, "tôi thích ăn kem")
    prompt = _low(sr, "xoá hết ký ức")
    assert _no_generic(prompt) and ("xác nhận" in prompt or "chắc" in prompt), prompt
    done = _low(sr, "ok")
    assert _no_generic(done) and ("đã xoá" in done or "đã xóa" in done), done
    summary = _low(sr, "bạn nhớ gì về tôi")
    assert "chưa nhớ" in summary or "chưa có" in summary, summary


def test_r1_delete_confirmation_exact_still_works():
    sr = _make_sr()
    _low(sr, "tôi thích ăn kem")
    _low(sr, "xoá hết ký ức")
    done = _low(sr, "xác nhận xoá ký ức")
    assert _no_generic(done) and ("đã xoá" in done or "đã xóa" in done), done
    summary = _low(sr, "bạn nhớ gì về tôi")
    assert "chưa nhớ" in summary or "chưa có" in summary, summary


def test_r1_bare_ok_without_pending_does_not_wipe():
    sr = _make_sr()
    _low(sr, "tôi thích ăn kem")
    # No delete pending → a bare "ok" must NOT claim a wipe and must NOT clear memory.
    ans = _low(sr, "ok")
    assert "đã xoá" not in ans and "đã xóa" not in ans, ans
    summary = _low(sr, "tôi thích gì?")
    assert "kem" in summary, summary

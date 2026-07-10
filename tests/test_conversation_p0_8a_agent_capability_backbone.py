"""CONV-P0 P0-8A — agent capability backbone.

Covers the five backbone pieces end-to-end through ``SessionRuntime.handle_turn``:
capability router, bounded LLMResponder, safety/permission gate, tool-runtime scaffold,
and the per-turn trace — while proving every existing deterministic memory lane is
preserved and that no external action ever executes.
"""
from __future__ import annotations

from agent_core.conversation.capabilities import (
    Capability,
    CapabilityRouter,
)
from agent_core.conversation.llm_responder import (
    FakeLLMResponder,
    LLMResponseRequest,
    RuleBasedLLMResponder,
)
from agent_core.runtime.runtime_agent import build_local_agent
from agent_core.runtime.session_runtime import SessionRuntime
from agent_core.safety.capability_gate import ActionRisk, CapabilitySafetyGate
from agent_core.tools.runtime import ToolRuntime, ToolRuntimeRequest

_GENERIC_FALLBACK = "tôi chưa xử lý được yêu cầu này trong bản rule-based mvp hiện tại"


def _make_sr(**kwargs) -> SessionRuntime:
    agent, store = build_local_agent()
    return SessionRuntime(agent, store, **kwargs)


def _low(sr: SessionRuntime, text: str) -> str:
    return (sr.handle_turn(text).final_answer or "").lower()


def _no_generic(answer: str) -> bool:
    return _GENERIC_FALLBACK not in answer.lower()


# ---------------------------------------------------------------------------
# Existing memory behavior preserved
# ---------------------------------------------------------------------------

def test_p8a_memory_food_preference_preserved():
    sr = _make_sr()
    _low(sr, "tôi thích ăn kem")
    ans = _low(sr, "tôi thích ăn gì?")
    assert "kem" in ans, ans


def test_p8a_mutual_relation_preserved():
    sr = _make_sr()
    _low(sr, "tôi thích Quý")
    _low(sr, "quý cũng thích tôi")
    ans = _low(sr, "quý và tôi có thích nhau không?")
    assert "có" in ans and "quý" in ans and "thích bạn" in ans, ans


def test_p8a_relation_entity_cleanup_preserved():
    sr = _make_sr()
    _low(sr, "may cũng thích tôi và tôi cũng thích may")
    ans = _low(sr, "ai đang thích tôi")
    assert "may" in ans and "may cũng" not in ans, ans


def test_p8a_delete_memory_confirmation_flow_preserved():
    sr = _make_sr()
    _low(sr, "tôi thích ăn kem")
    _low(sr, "xoá hết ký ức")
    done = _low(sr, "ok")
    assert "đã xoá" in done or "đã xóa" in done, done
    summary = _low(sr, "bạn nhớ gì về tôi")
    assert "chưa nhớ" in summary or "chưa có" in summary, summary


# ---------------------------------------------------------------------------
# Bounded LLMResponder routes
# ---------------------------------------------------------------------------

def test_p8a_translation_missing_text_asks():
    sr = _make_sr()
    ans = _low(sr, "Dịch đoạn này sang tiếng Anh")
    assert _no_generic(ans), ans
    assert "gửi" in ans or "đoạn" in ans or "văn bản" in ans, ans


def test_p8a_translation_with_payload_responds():
    sr = _make_sr()
    ans = _low(sr, "Dịch đoạn này sang tiếng Anh: tôi thích học AI")
    assert _no_generic(ans), ans
    # Bounded response acknowledges the source and the target language.
    assert "tôi thích học ai" in ans and ("english" in ans or "tiếng anh" in ans), ans


def test_p8a_explanation_bounded_components():
    sr = _make_sr()
    ans = _low(sr, "Giải thích Planner/Runtime/Tool/Memory")
    assert _no_generic(ans), ans
    for component in ("planner", "runtime", "tool", "memory"):
        assert component in ans, (component, ans)


def test_p8a_checklist_with_payload():
    sr = _make_sr()
    ans = sr.handle_turn(
        "Chia việc này thành checklist: build web, test API, deploy"
    ).final_answer or ""
    assert _no_generic(ans), ans
    assert "-" in ans and "build web" in ans.lower() and "deploy" in ans.lower(), ans


def test_p8a_checklist_without_payload_stays_on_clarification_lane():
    sr = _make_sr()
    ans = _low(sr, "Chia việc này thành checklist")
    # Existing P2 clarification contract preserved (asks for the task content).
    assert _no_generic(ans) and ("việc" in ans or "checklist" in ans or "task" in ans), ans
    assert sr.last_trace is not None and sr.last_trace.capability is None, sr.last_trace


def test_p8a_prioritization_with_payload():
    sr = _make_sr()
    ans = sr.handle_turn(
        "Ưu tiên các task này giúp tôi: fix bug, write tests, deploy"
    ).final_answer or ""
    assert _no_generic(ans), ans
    assert "1." in ans and "fix bug" in ans.lower(), ans


def test_p8a_which_task_first_with_payload():
    sr = _make_sr()
    ans = sr.handle_turn(
        "Tôi nên làm task nào trước: fix bug, write tests, deploy"
    ).final_answer or ""
    assert _no_generic(ans), ans
    assert "1." in ans and "fix bug" in ans.lower(), ans


def test_p8a_which_task_first_without_payload_asks_for_tasks():
    sr = _make_sr()
    ans = _low(sr, "Tôi nên làm task nào trước?")
    assert _no_generic(ans) and ("danh sách" in ans or "task" in ans), ans


def test_p8a_rewrite_and_summary_with_payload():
    sr = _make_sr()
    rewrite = _low(sr, "Viết lại đoạn này: hello world")
    assert _no_generic(rewrite) and "hello world" in rewrite, rewrite
    summary = _low(sr, "Tóm tắt đoạn này: ý một, ý hai, ý ba, ý bốn")
    assert _no_generic(summary) and "ý một" in summary, summary


# ---------------------------------------------------------------------------
# Safety / no side effects
# ---------------------------------------------------------------------------

def test_p8a_send_email_not_executed():
    sr = _make_sr()
    ans = _low(sr, "gửi email cho Nam là hello")
    assert _no_generic(ans), ans
    assert "chưa hỗ trợ" in ans and "xác nhận" in ans, ans
    trace = sr.last_trace
    assert trace is not None
    assert trace.capability == Capability.TOOL_ACTION_REQUEST.value
    assert trace.tool_name == "send_email"
    assert trace.tool_ok is None  # requested, never executed
    assert trace.safety_decision is not None and "blocked" in trace.safety_decision


def test_p8a_calendar_not_executed():
    sr = _make_sr()
    ans = _low(sr, "đặt lịch ngày mai 9h")
    assert _no_generic(ans), ans
    assert "chưa hỗ trợ" in ans and "lịch" in ans, ans
    trace = sr.last_trace
    assert trace is not None and trace.tool_name == "create_calendar_event"
    assert trace.tool_ok is None


def test_p8a_delete_file_refused():
    sr = _make_sr()
    ans = _low(sr, "xoá file README.md")
    assert _no_generic(ans), ans
    assert "không" in ans, ans
    trace = sr.last_trace
    assert trace is not None and trace.tool_name == "delete_file"
    assert trace.tool_ok is None
    assert trace.safety_decision is not None and "irreversible" in trace.safety_decision
    # No memory was written by the refused action.
    assert trace.memory_diff == [], trace.memory_diff


def test_p8a_delete_file_does_not_trigger_memory_delete_flow():
    sr = _make_sr()
    _low(sr, "tôi thích ăn kem")
    _low(sr, "xoá file README.md")
    # The file-delete refusal must not have set a pending memory-wipe: "ok" is inert.
    _low(sr, "ok")
    ans = _low(sr, "tôi thích ăn gì?")
    assert "kem" in ans, ans


# ---------------------------------------------------------------------------
# Trace observability
# ---------------------------------------------------------------------------

def test_p8a_trace_translation_capability_and_route():
    sr = _make_sr()
    sr.handle_turn("Dịch đoạn này sang tiếng Anh: tôi thích học AI")
    trace = sr.last_trace
    assert trace is not None
    assert trace.capability == Capability.TRANSLATION.value
    assert trace.route == "bounded_responder"
    assert trace.tool_name is None and trace.tool_ok is None
    assert trace.final_answer


def test_p8a_trace_explanation_and_checklist_and_prioritization():
    sr = _make_sr()
    sr.handle_turn("Giải thích Planner/Runtime/Tool/Memory")
    assert sr.last_trace.capability == Capability.EXPLANATION.value
    assert sr.last_trace.route == "bounded_responder"
    sr.handle_turn("Chia việc này thành checklist: a, b")
    assert sr.last_trace.capability == Capability.CHECKLIST.value
    sr.handle_turn("Ưu tiên các task này giúp tôi: a, b")
    assert sr.last_trace.capability == Capability.PRIORITIZATION.value
    assert sr.last_trace.tool_name is None


def test_p8a_trace_memory_turn_has_no_capability_and_records_write():
    sr = _make_sr()
    sr.handle_turn("tôi thích ăn kem")
    trace = sr.last_trace
    assert trace is not None
    assert trace.capability is None  # deterministic memory lane, not capability router
    assert any("confirmed_profile_facts:+" in d for d in trace.memory_diff), trace.memory_diff


def test_p8a_trace_backward_compatible_return():
    sr = _make_sr()
    state = sr.handle_turn("tôi thích ăn kem")
    assert state.final_answer  # handle_turn still returns the AgentState


# ---------------------------------------------------------------------------
# Capability router units
# ---------------------------------------------------------------------------

def test_p8a_router_classifies_supported_shapes():
    r = CapabilityRouter()
    assert r.classify("Dịch đoạn này sang tiếng Anh").capability is Capability.TRANSLATION
    assert r.classify("Translate this to English").capability is Capability.TRANSLATION
    assert r.classify("Giải thích Planner/Runtime/Tool/Memory").capability is Capability.EXPLANATION
    assert r.classify("Chia việc này thành checklist").capability is Capability.CHECKLIST
    assert r.classify("Ưu tiên các task này giúp tôi").capability is Capability.PRIORITIZATION
    assert r.classify("Tôi nên làm task nào trước?").capability is Capability.PRIORITIZATION
    assert r.classify("Viết lại đoạn này: x").capability is Capability.REWRITE
    assert r.classify("Tóm tắt đoạn này: x").capability is Capability.SUMMARY
    m = r.classify("gửi email cho Nam là hello")
    assert m.capability is Capability.TOOL_ACTION_REQUEST and m.tool_name == "send_email"


def test_p8a_router_does_not_steal_memory_or_llm_lanes():
    r = CapabilityRouter()
    for text in (
        "tôi thích ăn kem",
        "tôi thích ăn gì?",
        "xoá hết ký ức",
        'dịch "hello" sang tiếng Việt',
        "giải thích AI là gì?",
        "giải thích Planner là gì",
    ):
        assert r.classify(text).capability is Capability.UNKNOWN, text


def test_p8a_router_extracts_payload():
    r = CapabilityRouter()
    m = r.classify("Chia việc này thành checklist: build web, test API")
    assert m.payload == "build web, test API"
    assert r.classify("Chia việc này thành checklist").payload is None


# ---------------------------------------------------------------------------
# Safety gate units
# ---------------------------------------------------------------------------

def test_p8a_safety_gate_policy_table():
    gate = CapabilitySafetyGate()
    assert gate.evaluate(ActionRisk.READ_ONLY).allowed
    assert not gate.evaluate(ActionRisk.READ_ONLY).requires_confirmation
    memory_delete = gate.evaluate(ActionRisk.MEMORY_DELETE)
    assert memory_delete.allowed and memory_delete.requires_confirmation
    external = gate.evaluate(ActionRisk.EXTERNAL_ACTION)
    assert not external.allowed and external.requires_confirmation
    irreversible = gate.evaluate(ActionRisk.IRREVERSIBLE_ACTION)
    assert not irreversible.allowed and irreversible.requires_confirmation
    assert not gate.evaluate(ActionRisk.HIGH_RISK).allowed


# ---------------------------------------------------------------------------
# Tool runtime scaffold units
# ---------------------------------------------------------------------------

def test_p8a_tool_runtime_toy_tools_execute():
    rt = ToolRuntime()
    echo = rt.run(ToolRuntimeRequest("echo", {"text": "xin chào"}))
    assert echo.ok and echo.executed and echo.content == "xin chào"
    calc = rt.run(ToolRuntimeRequest("calculator", {"expression": "2 + 3"}))
    assert calc.ok and calc.content == "5"
    div = rt.run(ToolRuntimeRequest("calculator", {"expression": "1 / 0"}))
    assert not div.ok and not div.executed


def test_p8a_tool_runtime_blocks_external_tools():
    rt = ToolRuntime()
    for tool in ("send_email", "create_calendar_event", "delete_file", "send_message"):
        result = rt.run(ToolRuntimeRequest(tool, {}))
        assert not result.ok and not result.executed, tool
        assert result.error and "blocked_by_safety" in result.error, result.error


def test_p8a_tool_runtime_unknown_tool():
    rt = ToolRuntime()
    result = rt.run(ToolRuntimeRequest("browser", {}))
    assert not result.ok and "unknown tool" in (result.error or "")


# ---------------------------------------------------------------------------
# Bounded responder units + injection
# ---------------------------------------------------------------------------

def test_p8a_rule_based_responder_missing_payload_asks():
    responder = RuleBasedLLMResponder()
    for capability in (
        Capability.TRANSLATION, Capability.CHECKLIST, Capability.PRIORITIZATION,
        Capability.REWRITE, Capability.SUMMARY,
    ):
        response = responder.respond(
            LLMResponseRequest(capability=capability, user_text="x")
        )
        assert "gửi" in response.text.lower(), (capability, response.text)
        assert response.used_provider == "rule_based_bounded"
        assert "response_only" in response.safety_notes


def test_p8a_fake_responder_injection_and_recording():
    fake = FakeLLMResponder()
    sr = _make_sr(bounded_responder=fake)
    ans = sr.handle_turn("Chia việc này thành checklist: a, b").final_answer or ""
    assert ans.startswith("FAKE_RESPONSE[checklist]"), ans
    assert len(fake.requests) == 1
    assert fake.requests[0].capability is Capability.CHECKLIST
    assert fake.requests[0].context == {"payload": "a, b"}
    # Injected responder still cannot touch memory: nothing was written.
    assert sr.last_trace.memory_diff == []

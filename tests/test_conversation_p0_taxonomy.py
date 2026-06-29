"""CONV-P0 P0-2 — intent taxonomy reconciliation (parser classification only).

Asserts the rule-based parser classifies the new CONV-P0 conversational intents from
the frozen acceptance dataset inputs, WITHOUT regressing existing intents. P0-2 is
classification only: no ConversationRouter / DirectResponder / response handling, no
tools/memory/LLM. The planner is exercised only to confirm new intents fall through to
a safe FINISH plan (no crash, no clarification slot path).
"""
from __future__ import annotations

import pytest

from agent_core.planning.intent_parser import RuleBasedIntentParser
from agent_core.planning.intent_planner import IntentPlanner
from agent_core.planning.intents import IntentName
from agent_core.state.enums import ToolName


def _intent(text: str) -> IntentName:
    return RuleBasedIntentParser().parse(text).intent


# ---------------------------------------------------------------------------
# Existing behavior must stay green (no regression)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("Xin chào", IntentName.GREETING),
        ("Hi", IntentName.GREETING),
        ("Chào buổi sáng", IntentName.GREETING),          # was UNKNOWN before P0-2
        ("1 + 1 =", IntentName.CALCULATE),
        ("calculate 2 + 2", IntentName.CALCULATE),
        ("???", IntentName.UNKNOWN),
        ("Tính (15 + 5) * 3", IntentName.CALCULATE),
        ("Tính (15 + 5) * 3 rồi lưu vào ghi chú budget", IntentName.CALCULATE_THEN_SAVE_NOTE),
        ("Đọc ghi chú project", IntentName.READ_NOTE),
        ("Đọc ghi chú project rồi tóm tắt", IntentName.READ_NOTE_THEN_SUMMARIZE),
        ("Lưu ghi chú budget 1000", IntentName.WRITE_NOTE),
        ("Ghi ghi chú project Dùng FTS5", IntentName.WRITE_NOTE),
        ("Tìm thông tin về FastAPI", IntentName.WEB_SEARCH),
        ("Tìm thông tin về FastAPI rồi lưu vào ghi chú research", IntentName.WEB_SEARCH_THEN_SAVE_NOTE),
        ("Dự án đã chốt dùng cơ chế search nào cho MVP?", IntentName.PROJECT_CONTEXT_QUERY),
    ],
)
def test_existing_intents_preserved(text, expected):
    assert _intent(text) == expected


# ---------------------------------------------------------------------------
# New CONV-P0 P0-2 taxonomy (dataset inputs)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("Bạn là ai?", IntentName.IDENTITY_QUERY),
        ("Bạn làm được gì?", IntentName.CAPABILITY_QUERY),
        ("Bạn khác chatbot thường ở đâu?", IntentName.CAPABILITY_QUERY),
        ("Tôi nên dùng bạn như thế nào?", IntentName.CAPABILITY_QUERY),
        ("Bạn có giới hạn gì?", IntentName.CAPABILITY_QUERY),
        ("Bạn đang nhớ gì về tôi?", IntentName.MEMORY_READ),
        ("Bạn biết mục tiêu hiện tại của tôi không?", IntentName.MEMORY_READ),
        ("Thông tin nào về tôi là assumption?", IntentName.MEMORY_READ),
        ("Hãy nhớ rằng tôi đang build TOMTIT Agent", IntentName.MEMORY_WRITE_REQUEST),
        ("Lên kế hoạch cho tôi để học AI Agent", IntentName.PLANNING_REQUEST),
        ("Tôi có 2 tiếng hôm nay, nên làm gì?", IntentName.PLANNING_REQUEST),
        ("Chia việc này thành checklist", IntentName.PLANNING_REQUEST),
        ("Ưu tiên các task này giúp tôi", IntentName.PLANNING_REQUEST),
        ("Tạo roadmap 30 ngày", IntentName.PLANNING_REQUEST),
        ("Tôi đang bị quá tải, hãy giúp tôi focus", IntentName.PLANNING_REQUEST),
        ("Viết lại đoạn này tự nhiên hơn", IntentName.WRITING_REQUEST),
        ("Viết email ngắn cho tôi", IntentName.WRITING_REQUEST),
        ("Viết README cho project này", IntentName.WRITING_REQUEST),
        ("Tóm tắt đoạn này thành 3 ý", IntentName.SUMMARIZATION_REQUEST),
        ("Dịch đoạn này sang tiếng Anh", IntentName.TRANSLATION_REQUEST),
        ("Thiết kế architecture cho AI Agent đơn giản", IntentName.TECHNICAL_EXPLANATION_REQUEST),
        ("Giải thích Planner, Runtime, Tool, Memory khác nhau thế nào", IntentName.TECHNICAL_EXPLANATION_REQUEST),
        ("Review đoạn code này", IntentName.CODE_REVIEW_REQUEST),
        ("Tìm bug trong code này", IntentName.CODE_REVIEW_REQUEST),
        ("Viết test cho function này", IntentName.CODE_REVIEW_REQUEST),
        ("làm cái đó đi", IntentName.CLARIFICATION_REQUEST),
        ("Bạn cần thêm thông tin gì?", IntentName.CLARIFICATION_REQUEST),
    ],
)
def test_new_conversation_intents_classified(text, expected):
    assert _intent(text) == expected


# ---------------------------------------------------------------------------
# Precedence safety: code-review beats Tìm/writing; memory-write beats Lưu|Ghi;
# Đọc-ghi-chú beats summarization.
# ---------------------------------------------------------------------------

def test_code_review_beats_tim_websearch():
    assert _intent("Tìm bug trong code này") == IntentName.CODE_REVIEW_REQUEST
    assert _intent("Tìm thông tin về FastAPI") == IntentName.WEB_SEARCH  # unaffected


def test_code_review_beats_writing():
    assert _intent("Viết test cho function này") == IntentName.CODE_REVIEW_REQUEST
    assert _intent("Viết email ngắn cho tôi") == IntentName.WRITING_REQUEST  # unaffected


def test_memory_write_does_not_steal_write_note():
    assert _intent("Hãy nhớ rằng X") == IntentName.MEMORY_WRITE_REQUEST
    assert _intent("Lưu ghi chú budget 1000") == IntentName.WRITE_NOTE  # unaffected


def test_read_note_summarize_beats_standalone_summarization():
    assert _intent("Đọc ghi chú project rồi tóm tắt") == IntentName.READ_NOTE_THEN_SUMMARIZE
    assert _intent("Tóm tắt đoạn này thành 3 ý") == IntentName.SUMMARIZATION_REQUEST


# ---------------------------------------------------------------------------
# Planner safety: new intents fall through to a safe FINISH plan (no crash, no slots)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "Bạn là ai?",
        "Bạn làm được gì?",
        "Bạn đang nhớ gì về tôi?",
        "Hãy nhớ rằng X",
        "Lên kế hoạch cho tôi để học AI Agent",
        "Viết email ngắn cho tôi",
        "Tóm tắt đoạn này thành 3 ý",
        "Dịch đoạn này sang tiếng Anh",
        "Giải thích AgentState là gì",
        "Review đoạn code này",
        "làm cái đó đi",
    ],
)
def test_new_intents_produce_safe_finish_plan(text):
    parsed = RuleBasedIntentParser().parse(text)
    assert parsed.missing_slots == ()  # no clarification-slot path in P0-2
    steps = IntentPlanner().make_plan(parsed)
    assert steps, f"{text!r}: empty plan"
    assert steps[-1].action == ToolName.FINISH

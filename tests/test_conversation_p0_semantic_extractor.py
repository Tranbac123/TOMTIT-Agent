"""CONV-P0 P0-7K — hybrid semantic memory extractor unit tests.

Covers the complexity detector, the strict JSON operation contract, the fake fixture
extractor, and batch application. No external providers are ever called.
"""
from __future__ import annotations

import json

from agent_core.conversation.memory_operations import (
    MemoryOperation,
    apply_memory_operations,
)
from agent_core.conversation.semantic_extractor import (
    FakeSemanticOperationExtractor,
    RuleBasedSemanticOperationExtractor,
    SemanticExtractionRequest,
    detect_memory_complexity,
    detect_unsupported_memory_domain,
    is_technical_explanation_request,
    parse_semantic_operations_json,
)
from agent_core.memory.in_memory_store import InMemoryStore


# ---------------------------------------------------------------------------
# Complexity detector
# ---------------------------------------------------------------------------

def test_p0_7k_complexity_detector_detects_multifact_mixed_polarity():
    reason = detect_memory_complexity(
        "tôi không thích ăn cay, bơi, tắm biển và thể dục, "
        "tôi thích ăn chối, ăn cam nhưng không thích ăn ổi"
    )
    assert reason == "mixed_polarity_preference"
    # Simple single-fact utterances stay deterministic.
    assert detect_memory_complexity("tôi thích ăn kem") is None
    assert detect_memory_complexity("tôi không thích ăn kem") is None
    assert detect_memory_complexity("tôi thích cả may") is None
    # Questions and affection explanations never route to the extractor.
    assert detect_memory_complexity("tôi thích gì?") is None
    assert detect_memory_complexity(
        "tôi thích quý có nghĩa là tôi thích đơn phương và chúng tôi chưa là người yêu"
    ) is None


def test_p0_7k_complexity_detector_detects_moi_dung_correction():
    assert detect_memory_complexity("tôi tên là Â mới đúng") == "correction_name"


def test_p0_7k_complexity_detector_detects_da_doi_relationship_correction():
    reason = detect_memory_complexity("tôi đã đổi người yêu thành may rồi")
    assert reason == "correction_relationship"


def test_p0_7k_complexity_detector_detects_compound_goal():
    assert detect_memory_complexity("tôi muốn build cả LLM và SLM") == "compound_goal"
    # A single goal stays deterministic.
    assert detect_memory_complexity("tôi muốn build LLM") is None


def test_p0_7k_fix5b_fix2_technical_explanation_patterns_do_not_trigger_extraction():
    examples = [
        "Giải thích Planner, Runtime, Tool, Memory khác nhau thế nào",
        "giải thích Planner là gì",
        "Planner và Runtime khác nhau thế nào",
        "phân biệt Planner và Runtime",
        "so sánh Tool và Memory",
        "Planner, Runtime, Tool, Memory khác nhau thế nào",
    ]
    for text in examples:
        assert is_technical_explanation_request(text), text
        assert detect_memory_complexity(text) is None


def test_p0_7k_fix5b_fix2_explicit_preference_not_technical_explanation_request():
    assert not is_technical_explanation_request("tôi thích Planner")
    assert not is_technical_explanation_request("tôi thích Tool")


# ---------------------------------------------------------------------------
# Strict JSON contract
# ---------------------------------------------------------------------------

def test_p0_7k_semantic_extractor_rejects_invalid_json():
    result = parse_semantic_operations_json("not json at all {{{")
    assert result.error == "invalid_json"
    assert result.operations == ()


def test_p0_7k_semantic_extractor_rejects_unknown_domain():
    raw = json.dumps({"operations": [
        {"op": "ADD", "domain": "bank_account", "value": "123", "confidence": 0.9},
    ]})
    result = parse_semantic_operations_json(raw)
    assert result.operations == ()
    assert result.error is not None and "unknown_domain" in result.error


def test_p0_7k_semantic_extractor_rejects_too_many_operations():
    ops = [
        {"op": "ADD", "domain": "preference", "value": f"item {i}", "confidence": 0.9}
        for i in range(13)
    ]
    result = parse_semantic_operations_json(json.dumps({"operations": ops}))
    assert result.operations == ()
    assert result.error == "too_many_operations"


def test_p0_7k_semantic_extractor_rejects_unknown_op():
    raw = json.dumps({"operations": [
        {"op": "DROP_TABLE", "domain": "preference", "value": "x", "confidence": 0.9},
    ]})
    result = parse_semantic_operations_json(raw)
    assert result.operations == ()
    assert result.error is not None and "unknown_op" in result.error


# ---------------------------------------------------------------------------
# Fake extractor (offline fixtures)
# ---------------------------------------------------------------------------

def test_p0_7k_fake_extractor_returns_memory_operations():
    fixtures = {
        "tôi thích ăn cam": json.dumps({
            "operations": [{
                "op": "ADD", "domain": "preference", "value": "ăn cam",
                "polarity": "positive", "confidence": 0.9,
            }],
            "confidence": 0.9,
        }),
    }
    extractor = FakeSemanticOperationExtractor(fixtures)
    result = extractor.extract(SemanticExtractionRequest(raw_text="tôi thích ăn cam"))
    assert result.error is None
    assert len(result.operations) == 1
    op = result.operations[0]
    assert isinstance(op, MemoryOperation)
    assert (op.op, op.domain, op.value) == ("ADD", "preference", "ăn cam")
    assert op.source == "llm_semantic_extractor"
    # Unknown input → empty result, no error, no operations.
    miss = extractor.extract(SemanticExtractionRequest(raw_text="xin chào"))
    assert miss.operations == () and miss.error is None


def test_p0_7k_rule_based_extractor_decomposes_compound_goal():
    extractor = RuleBasedSemanticOperationExtractor()
    result = extractor.extract(
        SemanticExtractionRequest(raw_text="tôi muốn build cả LLM và SLM")
    )
    assert result.error is None
    values = [op.value for op in result.operations]
    assert values == ["build LLM", "build SLM"]
    assert all(op.domain == "goal" and op.op == "ADD" for op in result.operations)


def test_p0_7k_fix5b_rule_based_extractor_cleans_toi_cung_vay_tail():
    extractor = RuleBasedSemanticOperationExtractor()
    result = extractor.extract(
        SemanticExtractionRequest(
            raw_text="tôi không thích ăn cơm và ăn cá, cả ăn mỳ tôi cũng vậy"
        )
    )
    values = [(op.value, op.polarity) for op in result.operations]
    assert values == [
        ("ăn cơm", "negative"),
        ("ăn cá", "negative"),
        ("ăn mỳ", "negative"),
    ]


def test_p0_7k_fix5b_relation_adjacent_affection_not_extracted_as_preferences():
    extractor = RuleBasedSemanticOperationExtractor()
    result = extractor.extract(
        SemanticExtractionRequest(raw_text="tôi thích quý và quý cũng thích tôi")
    )
    assert result.operations == ()


# ---------------------------------------------------------------------------
# Batch application
# ---------------------------------------------------------------------------

def test_p0_7k_batch_apply_applies_multiple_operations_atomically_or_reports_partial_failure():
    store = InMemoryStore()
    ops = [
        MemoryOperation(
            op="ADD", domain="preference", subject="self", value="ăn cam",
            canonical_key="ăn cam", polarity="positive",
        ),
        # Unsafe value → validator rejects → reported as partial failure.
        MemoryOperation(
            op="ADD", domain="preference", subject="self", value="ma túy",
            canonical_key="ma túy", polarity="positive",
        ),
    ]
    result = apply_memory_operations(ops, store, "session-1", raw_text="probe")
    assert result.applied == 1
    assert result.failed == 1
    assert result.saved_count == 1
    assert result.response_text is not None and "ăn cam" in result.response_text
    from agent_core.conversation.profile_memory import collect_profile_snapshot
    snap = collect_profile_snapshot(store)
    assert "ăn cam" in snap.preferences_personal
    assert all("ma túy" not in v for v in snap.preferences_personal)


# ---------------------------------------------------------------------------
# Unsupported/future domains
# ---------------------------------------------------------------------------

def test_p0_7k_unsupported_domain_detection():
    assert detect_unsupported_memory_domain("lịch hôm nay là gì?")[0] == "schedule"
    assert detect_unsupported_memory_domain("tôi đã từng thích ai?")[0] == "historical_query"
    assert detect_unsupported_memory_domain(
        "tôt đặt tên bạn là tèo được không?"
    )[0] == "assistant_nickname"
    # Ordinary preference/travel sentences never classify as schedule.
    assert detect_unsupported_memory_domain("tôi thích đi du lịch") is None
    assert detect_unsupported_memory_domain("tôi thích ăn kem") is None

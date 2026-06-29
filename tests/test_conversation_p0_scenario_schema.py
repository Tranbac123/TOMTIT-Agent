from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.scenarios.conversation_p0.schema import Scenario, load_scenario


FIXTURES_DIR = Path("tests/scenarios/conversation_p0/fixtures")


def test_valid_greeting_fixture_loads() -> None:
    scenario = load_scenario(FIXTURES_DIR / "conv_p0_direct_greeting.yaml")

    assert scenario.id == "conv_p0_direct_greeting"
    assert len(scenario.turns) == 1
    turn = scenario.turns[0]
    assert turn.user == "Xin chào"
    assert turn.expect.intent == "GREETING"
    assert turn.expect.route == "DIRECT_RESPONSE"
    assert turn.expect.state_status_any == ["completed", "waiting_user"]
    assert turn.expect.side_effects.planner_calls == 0
    assert turn.expect.side_effects.tool_calls == 0
    assert turn.expect.side_effects.memory_reads == 0
    assert turn.expect.side_effects.memory_writes == 0
    assert turn.expect.response.must_include_any == ["chào"]
    assert turn.expect.response.must_not_include_any == [
        "đã lưu",
        "tôi nhớ",
        "đang gọi tool",
    ]
    assert turn.expect.trace.must_include_meanings == [
        "request_received",
        "intent_classified",
        "route_selected",
        "response_generated",
        "state_finalized",
    ]
    assert turn.expect.trace.must_not_include_meanings == [
        "planner_called",
        "tool_called",
        "memory_read_called",
        "memory_write_called",
    ]


def test_valid_identity_fixture_loads() -> None:
    scenario = load_scenario(FIXTURES_DIR / "conv_p0_identity_query.yaml")

    assert scenario.id == "conv_p0_identity_query"
    assert len(scenario.turns) == 1
    turn = scenario.turns[0]
    assert turn.user == "Bạn là ai?"
    assert turn.expect.intent == "IDENTITY_QUERY"
    assert turn.expect.route == "DIRECT_RESPONSE"
    assert turn.expect.side_effects.planner_calls == 0
    assert turn.expect.side_effects.tool_calls == 0
    assert turn.expect.side_effects.memory_reads == 0
    assert turn.expect.side_effects.memory_writes == 0
    assert turn.expect.response.must_include_any == ["TOMTIT", "trợ lý", "Agent"]
    assert turn.expect.response.must_not_include_any == [
        "tôi đã lưu",
        "tôi nhớ bạn",
        "API key",
    ]
    assert turn.expect.trace.must_include_meanings == [
        "request_received",
        "intent_classified",
        "route_selected",
        "response_generated",
        "state_finalized",
    ]
    assert turn.expect.trace.must_not_include_meanings == [
        "planner_called",
        "tool_called",
        "memory_read_called",
        "memory_write_called",
    ]


def test_valid_unknown_recoverable_fixture_loads() -> None:
    scenario = load_scenario(FIXTURES_DIR / "conv_p0_unknown_recoverable.yaml")

    assert scenario.id == "conv_p0_unknown_recoverable"
    assert len(scenario.turns) == 1
    turn = scenario.turns[0]
    assert turn.user == "Làm cái đó đi"
    assert turn.expect.intent == "UNKNOWN"
    assert turn.expect.route == "CLARIFICATION"
    assert turn.expect.side_effects.planner_calls == 0
    assert turn.expect.side_effects.tool_calls == 0
    assert turn.expect.side_effects.memory_reads == 0
    assert turn.expect.side_effects.memory_writes == 0
    assert turn.expect.response.must_include_any == [
        "bạn muốn",
        "ý bạn",
        "thông tin",
    ]
    assert turn.expect.response.must_not_include_any == [
        "đã thực hiện",
        "đã lưu",
        "đang gọi tool",
    ]
    assert turn.expect.trace.must_include_meanings == [
        "request_received",
        "intent_classified",
        "route_selected",
        "response_generated",
        "state_finalized",
    ]
    assert turn.expect.trace.must_not_include_meanings == [
        "planner_called",
        "tool_called",
        "memory_read_called",
        "memory_write_called",
    ]


def test_invalid_missing_expected_route_fixture_fails() -> None:
    with pytest.raises(ValidationError):
        load_scenario(FIXTURES_DIR / "invalid_missing_expected_route.yaml")


def test_route_literals_are_minimal_and_strict() -> None:
    def scenario_with_route(route: str) -> dict:
        return {
            "id": "route_literal_check",
            "description": "Route literal contract check.",
            "turns": [
                {
                    "user": "Xin chào",
                    "expect": {
                        "intent": "GREETING",
                        "route": route,
                        "state_status_any": ["completed"],
                        "side_effects": {
                            "planner_calls": 0,
                            "tool_calls": 0,
                            "memory_reads": 0,
                            "memory_writes": 0,
                        },
                        "response": {
                            "must_include_any": ["chào"],
                            "must_not_include_any": [],
                        },
                        "trace": {
                            "must_include_meanings": ["request_received"],
                            "must_not_include_meanings": [],
                        },
                    },
                }
            ],
        }

    for route in ["DIRECT_RESPONSE", "CLARIFICATION", "RUNTIME_FALLBACK"]:
        scenario = Scenario.model_validate(scenario_with_route(route))
        assert scenario.turns[0].expect.route == route

    for route in [
        "MEMORY_FLOW",
        "LLM_RESPONSE",
        "TOOL_FLOW",
        "RUNTIME",
        "UNKNOWN_RECOVERABLE",
    ]:
        with pytest.raises(ValidationError):
            Scenario.model_validate(scenario_with_route(route))


def test_unknown_side_effect_key_is_rejected() -> None:
    invalid_scenario = {
        "id": "invalid_unknown_side_effect_key",
        "description": "Wrong nested side effect key must not false-green.",
        "turns": [
            {
                "user": "Xin chào",
                "expect": {
                    "intent": "GREETING",
                    "route": "DIRECT_RESPONSE",
                    "side_effects": {
                        "planner_calls": 0,
                        "tool_calls": 0,
                        "tool_call_count": 0,
                        "memory_reads": 0,
                        "memory_writes": 0,
                    },
                    "response": {
                        "must_include_any": ["chào"],
                        "must_not_include_any": [],
                    },
                    "trace": {
                        "must_include_meanings": ["request_received"],
                        "must_not_include_meanings": [],
                    },
                },
            }
        ],
    }

    with pytest.raises(ValidationError):
        Scenario.model_validate(invalid_scenario)

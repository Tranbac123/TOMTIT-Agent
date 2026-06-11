from __future__ import annotations


def test_package_imports():
    import agent_core  # noqa: F401


def test_planning_public_api():
    from agent_core.planning import (
        HybridPlanner,
        IntentPlanner,
        RuleBasedIntentParser,
        RuleBasedPlanner,
        SlotValidator,
    )
    assert all(
        cls is not None
        for cls in (
            RuleBasedIntentParser,
            IntentPlanner,
            RuleBasedPlanner,
            HybridPlanner,
            SlotValidator,
        )
    )


def test_sourcetype_single():
    from agent_core.state.enums import SourceType as A
    from agent_core.state.agent_state import SourceType as B

    assert A is B


def test_main_constructs():
    from agent_core.planning.rule_based_planner import RuleBasedPlanner
    from agent_core.runtime.runtime_agent import RuntimeAgent
    from agent_core.tools.registry import build_tool_registry

    agent = RuntimeAgent(planner=RuleBasedPlanner(), tools=build_tool_registry())
    assert agent is not None


def test_intentplanner_defined_once():
    import ast
    import pathlib

    count = 0
    for f in pathlib.Path("agent_core").rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        count += sum(
            isinstance(n, ast.ClassDef) and n.name == "IntentPlanner"
            for n in ast.walk(tree)
        )
    assert count == 1, f"IntentPlanner defined {count} times, expected 1"

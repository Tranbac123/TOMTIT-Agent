from agent_core.planning.base import IntentParser, Planner
from agent_core.planning.intent_parser import RuleBasedIntentParser
from agent_core.planning.intent_planner import IntentPlanner
from agent_core.planning.intents import IntentName, ParsedIntent
from agent_core.planning.rule_based_planner import RuleBasedPlanner
from agent_core.planning.slot_validator import SlotValidator

__all__ = [
    "Planner",
    "IntentParser",
    "IntentName",
    "ParsedIntent",
    "RuleBasedIntentParser",
    "IntentPlanner",
    "SlotValidator",
    "RuleBasedPlanner",
    "HybridPlanner",
]


def __getattr__(name: str):
    # PEP 562 lazy export. ``HybridPlanner`` is dormant (not part of the active
    # rule-based path); importing this package or any submodule must NOT eagerly load
    # ``agent_core.planning.hybrid_planner``. It remains importable on demand via
    # ``from agent_core.planning import HybridPlanner``.
    if name == "HybridPlanner":
        from agent_core.planning.hybrid_planner import HybridPlanner

        return HybridPlanner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

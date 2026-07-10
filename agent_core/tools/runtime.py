"""CONV-P0 P0-8A — capability tool-runtime scaffold.

A minimal, safety-gated runtime for capability-level tool requests. This is a SCAFFOLD:
the only executable tools are safe, pure, read-only toys (``echo``, ``calculator``).
External-action tools (email/calendar/file deletion) are registered as UNIMPLEMENTED specs
whose risk class the safety gate blocks BEFORE any execution — registering them lets the
runtime answer "what would happen" deterministically without ever doing it.

Class names are deliberately distinct from ``agent_core.tools.base`` (``ToolSpec``/
``ToolResult``): those belong to the ToolExecutor contract, which remains the single
execution gate for real agent tools. Nothing here calls a ``ToolSpec.fn``.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent_core.safety.capability_gate import (
    ActionRisk,
    CapabilitySafetyGate,
    SafetyDecision,
)


@dataclass(frozen=True)
class ToolRuntimeSpec:
    name: str
    description: str
    risk: ActionRisk
    fn: Callable[[dict[str, Any]], str] | None = None  # None → not implemented in MVP


@dataclass(frozen=True)
class ToolRuntimeRequest:
    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolRuntimeResult:
    ok: bool
    content: str
    error: str | None = None
    executed: bool = False
    decision: SafetyDecision | None = None


def _tool_echo(args: dict[str, Any]) -> str:
    return str(args.get("text", ""))


_RE_ARITHMETIC = re.compile(
    r'^\s*(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)\s*$'
)


def _tool_calculator(args: dict[str, Any]) -> str:
    """Two-operand arithmetic via an anchored regex — deliberately NOT eval()."""
    expression = str(args.get("expression", ""))
    m = _RE_ARITHMETIC.match(expression)
    if m is None:
        raise ValueError(f"unsupported expression: {expression!r}")
    a, op, b = float(m.group(1)), m.group(2), float(m.group(3))
    if op == "/" and b == 0:
        raise ValueError("division by zero")
    value = {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else 0.0}[op]
    return str(int(value)) if value == int(value) else str(value)


def default_tool_specs() -> dict[str, ToolRuntimeSpec]:
    return {
        "echo": ToolRuntimeSpec(
            name="echo", description="Echo the provided text back (safe toy tool).",
            risk=ActionRisk.READ_ONLY, fn=_tool_echo,
        ),
        "calculator": ToolRuntimeSpec(
            name="calculator", description="Two-operand arithmetic (safe toy tool).",
            risk=ActionRisk.READ_ONLY, fn=_tool_calculator,
        ),
        # Unimplemented external-action stubs: blocked by the safety gate, never executed.
        "send_email": ToolRuntimeSpec(
            name="send_email", description="Send an email (NOT implemented in MVP).",
            risk=ActionRisk.EXTERNAL_ACTION,
        ),
        "send_message": ToolRuntimeSpec(
            name="send_message", description="Send a message (NOT implemented in MVP).",
            risk=ActionRisk.EXTERNAL_ACTION,
        ),
        "create_calendar_event": ToolRuntimeSpec(
            name="create_calendar_event",
            description="Create a calendar event (NOT implemented in MVP).",
            risk=ActionRisk.EXTERNAL_ACTION,
        ),
        "delete_file": ToolRuntimeSpec(
            name="delete_file", description="Delete a file (NOT implemented in MVP).",
            risk=ActionRisk.IRREVERSIBLE_ACTION,
        ),
    }


class ToolRuntime:
    """Safety-gated scaffold runtime. Every ``run()`` consults the gate first; a blocked
    decision returns without executing anything (and unimplemented tools cannot execute
    even if the gate were misconfigured — there is no ``fn``)."""

    def __init__(
        self,
        specs: dict[str, ToolRuntimeSpec] | None = None,
        gate: CapabilitySafetyGate | None = None,
    ) -> None:
        self._specs = specs if specs is not None else default_tool_specs()
        self._gate = gate or CapabilitySafetyGate()

    def get_spec(self, tool_name: str) -> ToolRuntimeSpec | None:
        return self._specs.get(tool_name)

    def run(self, request: ToolRuntimeRequest) -> ToolRuntimeResult:
        spec = self._specs.get(request.tool_name)
        if spec is None:
            return ToolRuntimeResult(
                ok=False, content="", error=f"unknown tool: {request.tool_name}",
            )
        decision = self._gate.evaluate(spec.risk)
        if not decision.allowed or decision.requires_confirmation:
            # Blocked or confirmation-gated → never execute in MVP.
            return ToolRuntimeResult(
                ok=False, content="",
                error=f"blocked_by_safety: {decision.reason}",
                executed=False, decision=decision,
            )
        if spec.fn is None:
            return ToolRuntimeResult(
                ok=False, content="",
                error=f"tool not implemented: {spec.name}",
                executed=False, decision=decision,
            )
        try:
            content = spec.fn(request.args)
        except Exception as exc:  # deterministic toy tools: surface, never crash the turn
            return ToolRuntimeResult(
                ok=False, content="", error=str(exc), executed=False, decision=decision,
            )
        return ToolRuntimeResult(ok=True, content=content, executed=True, decision=decision)

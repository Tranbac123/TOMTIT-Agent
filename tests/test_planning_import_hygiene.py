"""Import-hygiene gate for CONV-P0 P0-1.

Importing the acceptance runner (and the active rule-based parser/planner) must NOT
eagerly load the dormant planner modules. A cold subprocess is used so the result is
deterministic regardless of pytest collection order (other test modules in the same
session may legitimately import those modules on demand).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DORMANT = (
    "agent_core.planning.hybrid_planner",
    "agent_core.planning.LLMIntentParser",
    "agent_core.planning.skill_aware_intent_planner",
)


def _cold_import_loaded_modules(target: str) -> set[str]:
    code = (
        "import importlib, sys\n"
        f"importlib.import_module({target!r})\n"
        "print('\\n'.join(m for m in sys.modules if 'agent_core.planning' in m))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_REPO_ROOT),
        env={"PYTHONPATH": str(_REPO_ROOT), "PYTHONDONTWRITEBYTECODE": "1", "PATH": ""},
        capture_output=True,
        text=True,
    )
    # PATH="" can break some interpreters; fall back to inherited env if needed.
    if result.returncode != 0:
        import os

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(_REPO_ROOT),
            env={**os.environ, "PYTHONPATH": str(_REPO_ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
        )
    assert result.returncode == 0, f"cold import of {target} failed:\n{result.stdout}\n{result.stderr}"
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def test_acceptance_runner_does_not_eager_load_dormant_planners():
    loaded = _cold_import_loaded_modules("tests.test_conversation_p0_acceptance")
    offenders = [m for m in _DORMANT if m in loaded]
    assert offenders == [], f"acceptance runner eagerly loaded dormant planners: {offenders}"


def test_rule_based_parser_import_does_not_eager_load_dormant_planners():
    loaded = _cold_import_loaded_modules("agent_core.planning.intent_parser")
    offenders = [m for m in _DORMANT if m in loaded]
    assert offenders == [], f"intent_parser import eagerly loaded dormant planners: {offenders}"

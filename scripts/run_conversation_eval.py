#!/usr/bin/env python3
"""CONV-P0 P0-8B — golden-conversation eval CLI.

Usage:
    PYTHONPATH=. python scripts/run_conversation_eval.py --suite data/evals/p0_8b_golden_conversations.json
    PYTHONPATH=. python scripts/run_conversation_eval.py --suite <path> --json

Exit code 0 when every turn passes; 1 otherwise. Stdlib-only (argparse/json) — no pytest,
no network, no provider.
"""
from __future__ import annotations

import argparse
import json
import sys

from agent_core.eval.conversation_eval import (
    format_text_report,
    load_suite,
    run_suite,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a golden conversation eval suite.")
    parser.add_argument("--suite", required=True, help="Path to the suite JSON file.")
    parser.add_argument(
        "--json", action="store_true", help="Emit the summary as JSON instead of text."
    )
    args = parser.parse_args(argv)

    suite = load_suite(args.suite)
    result = run_suite(suite)

    if args.json:
        print(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_text_report(result))
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

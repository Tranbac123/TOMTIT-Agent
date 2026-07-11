"""P0-9A — Build Harness core: evidence-gated software delivery for AI coding agents.

A separate namespace from the conversation runtime. Stdlib-only, deterministic, and
side-effect free at the core: no git/shell execution, no network, no provider calls.
The harness consumes explicit inputs (contracts, agent reports, changed-file lists) and
produces structured evidence artifacts, gate decisions, and next-action recommendations.
"""

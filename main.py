from __future__ import annotations

from agent_core import *
from agent_core.runtime.runtime_agent import build_local_agent


def run_scenario(label: str, goal: str) -> None:
    agent, store = build_local_agent()
    state = AgentState(goal=goal, memory=store)   # shared store (QĐ-2)
    result = agent.run(state)

    print(f"\n{'=' * 60}")
    print(f"Scenario : {label}")
    print(f"Goal     : {goal}")
    print(f"Status   : {result.status.value}")
    print(f"Degraded : {result.memory_degraded}")
    if result.disclosure_reasons:
        print(f"Disclose : {result.disclosure_reasons}")
    print(f"Answer   : {result.final_answer}")
    print("History  :")
    for item in result.history:
        print(f"  - {item}")


def main() -> None:
    run_scenario(
        "1 — Web search",
        "tìm thông tin về Ducati Monster 795 và ghi vào memory cho tôi",
    )
    run_scenario(
        "2 — Calculate",
        "Tính (15+5)*3",
    )
    run_scenario(
        "3 — Compound: calculate then save note",
        "Tính (15+5)*3 rồi lưu vào ghi chú budget",
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

from agent_core import *
from agent_core.memory.memory_records import MemoryRecord
from agent_core.runtime.runtime_agent import build_local_agent
from agent_core.state.enums import MemoryType


def run_scenario(label: str, goal: str, seed_store=None) -> None:
    agent, store = build_local_agent()
    if seed_store:
        seed_store(store)
    state = AgentState(goal=goal, memory=store)   # shared store (QĐ-2)
    result = agent.run(state)

    print(f"\n{'=' * 60}")
    print(f"Scenario         : {label}")
    print(f"Goal             : {goal}")
    print(f"Status           : {result.status.value}")
    print(f"Degraded         : {result.memory_degraded}")
    print(f"Context consumed : {result.context_consumed}")
    if result.disclosure_reasons:
        print(f"Disclose         : {result.disclosure_reasons}")
    print(f"Answer           : {result.final_answer}")
    print(f"Plan             : {[s.action.value for s in result.plan]}")


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
    run_scenario(
        "4 — Project context query (P4 DoD)",
        "Dự án đã chốt dùng cơ chế search nào cho MVP?",
        seed_store=lambda store: store.write(
            MemoryRecord(
                content="MVP đã chốt dùng FTS5, chưa dùng vector database",
                type=MemoryType.DECISION,
            )
        ),
    )


if __name__ == "__main__":
    main()

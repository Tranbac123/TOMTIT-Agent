from __future__ import annotations

from agent_core import *


def main() -> None:
    tools = build_tool_registry(web_search_client=FakeWebSearchClient())
    agent = RuntimeAgent(planner=RuleBasedPlanner(), tools=tools)
    state = AgentState(goal="tìm thông tin về Ducati Monster 795 và ghi vào memory cho tôi")
    result = agent.run(state)

    print("Final answer:", result.final_answer)
    print("Sources:")
    for source in result.sources:
        print("-", source.title, source.url)
    print("History:")
    for item in result.history:
        print(" -", item)


if __name__ == "__main__":
    main()

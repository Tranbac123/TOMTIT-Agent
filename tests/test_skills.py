from agent_core.skills.calculate_and_save_skill import CalculateAndSaveSkill
from agent_core.skills.read_and_summarize_skill import ReadAndSummarizeSkill
from agent_core.skills.web_search_skill import WebSearchSkill
from agent_core.state.enums import ToolName


def test_calculate_and_save_skill_composes_tools():
    steps = CalculateAndSaveSkill("(1 + 2)", "budget").make_steps()

    assert [step.action for step in steps] == [ToolName.CALCULATE, ToolName.WRITE_NOTE, ToolName.FINISH]


def test_read_and_summarize_skill_composes_tools():
    steps = ReadAndSummarizeSkill("project").make_steps()

    assert [step.action for step in steps] == [ToolName.READ_NOTE, ToolName.SUMMARIZE, ToolName.FINISH]


def test_web_search_skill_composes_tools():
    steps = WebSearchSkill("Ducati").make_steps()

    assert [step.action for step in steps] == [ToolName.WEB_SEARCH, ToolName.FINISH]

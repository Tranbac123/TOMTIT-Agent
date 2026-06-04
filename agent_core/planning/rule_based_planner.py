from __future__ import annotations

import unicodedata

from agent_core.planning.base import Intent, IntentClassifier
from agent_core.state.agent_state import AgentState, Step
from agent_core.state.enums import ToolName


def normalize_vi(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d")


class RuleBasedIntentClassifier(IntentClassifier):
    def classify(self, text: str) -> Intent:
        goal = normalize_vi(text)
        if "tinh" in goal:
            return Intent("calculate", 0.9)
        if "doc ghi chu" in goal:
            return Intent("read_note", 0.9)
        if any(keyword in goal for keyword in ["tim", "search", "tra cuu", "google", "web"]):
            return Intent("web_search", 0.85)
        return Intent("unknown", 0.1)


class GoalExtractor:
    def has_save_negation(self, goal_norm: str) -> bool:
        negations = ["khong luu", "dung luu", "khong ghi chu", "dung ghi chu", "khong note", "dung note"]
        return any(phrase in goal_norm for phrase in negations)

    def wants_search(self, goal_norm: str) -> bool:
        keywords = ["tim", "tim kiem", "search", "tra cuu", "web", "google", "thong tin moi", "moi nhat", "latest"]
        return any(keyword in goal_norm for keyword in keywords)

    def extract_search_query(self, goal: str) -> str:
        text = goal.strip()
        normalized = normalize_vi(text)
        prefixes = ["tim tren web", "search web", "tim kiem", "tra cuu", "google", "search", "tim"]
        for prefix in sorted(prefixes, key=len, reverse=True):
            if normalized.startswith(prefix):
                return text[len(prefix) :].strip(" :,-")
        return text

    def extract_expression(self, goal: str) -> str | None:
        raw = goal.strip()
        normalized = normalize_vi(raw)
        idx = normalized.find("tinh")
        if idx == -1:
            return None
        start = idx + len("tinh")
        after_raw = raw[start:].strip()
        after_norm = normalized[start:].strip()
        stop_markers = ["roi luu", "va luu", "vao ghi chu", "ghi chu", "nhung khong", "khong luu"]
        cut_pos = len(after_raw)
        for marker in stop_markers:
            pos = after_norm.find(marker)
            if pos != -1:
                cut_pos = min(cut_pos, pos)
        expr = after_raw[:cut_pos].strip(" :,-")
        return expr or None

    def extract_note_name(self, goal: str) -> str | None:
        raw = goal.strip()
        normalized = normalize_vi(raw)
        key = "ghi chu"
        idx = normalized.find(key)
        if idx == -1:
            return None
        start = idx + len(key)
        name = raw[start:].strip(" :,-")
        name_norm = normalize_vi(name)
        cut_pos = len(name)
        for marker in ["roi", "va", "sau do"]:
            pos = name_norm.find(marker)
            if pos != -1:
                cut_pos = min(cut_pos, pos)
        name = name[:cut_pos].strip(" :,-")
        return name or None

    def extract_note_name_after_read(self, goal: str) -> str | None:
        raw = goal.strip()
        normalized = normalize_vi(raw)
        key = "doc ghi chu"
        idx = normalized.find(key)
        if idx == -1:
            return None
        start = idx + len(key)
        after_raw = raw[start:].strip()
        after_norm = normalized[start:].strip()
        cut_pos = len(after_raw)
        for marker in ["roi tom tat", "va tom tat", "tom tat"]:
            pos = after_norm.find(marker)
            if pos != -1:
                cut_pos = min(cut_pos, pos)
        name = after_raw[:cut_pos].strip(" :,-")
        return name or None


class RuleBasedPlanner:
    def __init__(self, extractor: GoalExtractor | None = None):
        self.extractor = extractor or GoalExtractor()

    def make_plan(self, state: AgentState) -> list[Step]:
        raw_goal = state.goal.strip()
        goal = normalize_vi(raw_goal)
        wants_save_note = "ghi chu" in goal and not self.extractor.has_save_negation(goal)

        if "tinh" in goal and wants_save_note:
            exp = self.extractor.extract_expression(raw_goal)
            note_name = self.extractor.extract_note_name(raw_goal)
            if exp and note_name:
                return [
                    Step("Cần tính toán biểu thức trước", ToolName.CALCULATE, {"expression": exp}),
                    Step("Lưu kết quả vào ghi chú", ToolName.WRITE_NOTE, {"name": note_name, "content": "$last_text"}),
                    Step("Thông báo hoàn tất cho user", ToolName.FINISH, {"answer": f"Đã tính xong và lưu vào ghi chú '{note_name}'. Kết quả: ${{slot.calc_result}}"}),
                ]

        if "tinh" in goal:
            exp = self.extractor.extract_expression(raw_goal)
            if exp:
                return [
                    Step("Cần tính toán biểu thức", ToolName.CALCULATE, {"expression": exp}),
                    Step("Trả kết quả tính toán cho user", ToolName.FINISH, {"answer": "Kết quả: ${last.output.value}"}),
                ]

        if "doc ghi chu" in goal and "tom tat" in goal:
            note_name = self.extractor.extract_note_name_after_read(raw_goal)
            if note_name:
                return [
                    Step("Đọc nội dung ghi chú", ToolName.READ_NOTE, {"name": note_name}),
                    Step("Tóm tắt nội dung ghi chú", ToolName.SUMMARIZE, {"text": "$last.output.content"}),
                    Step("Trả summary cho user", ToolName.FINISH, {"answer": "Tóm tắt: ${last.output.summary}"}),
                ]

        if self.extractor.wants_search(goal):
            return [
                Step("Tìm thông tin trên web", ToolName.WEB_SEARCH, {"query": self.extractor.extract_search_query(raw_goal), "max_results": 3}),
                Step("Trả kết quả search cho user", ToolName.FINISH, {"answer": "$last_text"}),
            ]

        return [Step("Không hiểu rõ task nên kết thúc an toàn", ToolName.FINISH, {"answer": "Tôi chưa biết xử lý task này trong bản agent đơn giản này."})]

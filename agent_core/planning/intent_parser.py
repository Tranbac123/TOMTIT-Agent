from __future__ import annotations

import re

from agent_core.planning.intents import IntentName, ParsedIntent


_SAVE_SUFFIX = re.compile(r'\s+rồi\s+lưu\s+vào\s+ghi\s+chú(?:\s+(\S+))?', re.IGNORECASE)
_SUMMARIZE_SUFFIX = re.compile(r'\s+rồi\s+tóm\s+tắt', re.IGNORECASE)
_MATH_EXPR = re.compile(r'[\d(][0-9()\s+\-*/. ]*')
# P4: project-context cue — narrow AND with ^Dự án to avoid false positives.
_PROJECT_QUERY_CUE = re.compile(
    r'(đã\s+chốt|đã\s+quyết\s+định|quyết\s+định\s+nào|dùng\s+gì|'
    r'dùng\s+cơ\s+chế\s+nào|context|ngữ\s+cảnh)',
    re.IGNORECASE,
)
# B.8: English calc prefix — "calculate 2+2", "calc 3*4"
_CALC_PREFIX = re.compile(r'^calc(?:ulate)?\s+', re.IGNORECASE)
# B.8: Vietnamese natural-language math suffix — "1+1 bằng mấy", "2*3 là bao nhiêu"
_VIET_MATH_SUFFIX = re.compile(
    r'\s+(?:bằng\s+(?:mấy|bao\s+nhiêu)|là\s+bao\s+nhiêu)\s*\??\s*$',
    re.IGNORECASE,
)
# B.8: Bare math — starts with digit or '(', contains only safe arithmetic chars
_BARE_MATH_ONLY = re.compile(r'^[0-9(][0-9\s.()+\-*/%=]*$')
# B.8 / CONV-P0 P0-2: greeting — full-string hi/hello/chào, optionally with a
# time-of-day or addressee tail ("Chào buổi sáng", "Chào bạn").
_GREETING_WORDS = re.compile(
    r'^(?:hi|hello|hey|xin\s+chào|chào)'
    r'(?:\s+(?:bạn|mọi\s+người|anh|chị|em|buổi\s+(?:sáng|trưa|chiều|tối)))?'
    r'\s*[!?.]*\s*$',
    re.IGNORECASE,
)

# CONV-P0 P0-2 conversational cues (rule-based classification only). Order of use in
# parse() matters; see the dispatch comments there.
_IDENTITY_CUE = re.compile(
    r'^(?:bạn\s+là\s+ai|bạn\s+tên\s+(?:là\s+)?gì|who\s+are\s+you|what\s+are\s+you)\b',
    re.IGNORECASE,
)
_CAPABILITY_CUE = re.compile(
    r'(?:làm\s+được\s+gì|làm\s+gì\s+được|có\s+thể\s+làm\s+(?:được\s+)?gì|'
    r'khác\s+(?:gì\s+)?(?:so\s+với\s+)?chatbot|dùng\s+bạn|giới\s+hạn|'
    r'what\s+can\s+you\s+do|^help\b)',
    re.IGNORECASE,
)
_MEMORY_READ_CUE = re.compile(
    r'(?:(?:đang\s+)?nhớ\s+gì|bạn\s+biết\s+.+\s+của\s+tôi|'
    r'thông\s+tin\s+nào.*(?:assumption|giả\s+định)|'
    r'what\s+do\s+you\s+remember|remember\s+about)',
    re.IGNORECASE,
)
_MEMORY_WRITE_CUE = re.compile(
    r'^(?:hãy\s+)?(?:nhớ|ghi\s+nhớ)\s+(?:rằng|là|giùm|giúp|cho)\b'
    r'|^remember\s+that\b'
    r'|(?:lưu|ghi)\s+[^\n]*?(?:vào\s+)?(?:memory|bộ\s+nhớ)\b'
    r'|save\s+this\s+to\s+memory',
    re.IGNORECASE,
)
_CODE_REVIEW_CUE = re.compile(
    r'(?:review\s+.*code|review\s+đoạn\s+code|kiểm\s+tra\s+code|đoạn\s+code|'
    r'tìm\s+bug|bug\s+trong\s+code|tìm\s+lỗi.*code|fix\s+bug|debug\b|'
    r'test\s+cho\s+function|cho\s+function\s+này)',
    re.IGNORECASE,
)
_PLANNING_CUE = re.compile(
    r'(?:lên\s+kế\s+hoạch|lập\s+kế\s+hoạch|kế\s+hoạch|roadmap|checklist|'
    r'ưu\s+tiên|nên\s+làm\s+gì|giúp\s+(?:tôi\s+)?focus|quá\s+tải|'
    r'plan\s+for|create\s+a\s+plan|chia\s+.*\s+thành)',
    re.IGNORECASE,
)
_SUMMARIZE_CUE = re.compile(r'(?:tóm\s+tắt|summari[sz]e)', re.IGNORECASE)
_TRANSLATE_CUE = re.compile(r'(?:(?:^|\b)dịch\b|translate)', re.IGNORECASE)
_TECHNICAL_CUE = re.compile(
    r'(?:giải\s+thích|explain|phân\s+tích|analy[sz]e|'
    r'thiết\s+kế\s+architecture|architecture)',
    re.IGNORECASE,
)
_WRITING_CUE = re.compile(r'(?:^|\b)(?:viết|soạn|draft|write)\b', re.IGNORECASE)
_CLARIFICATION_CUE = re.compile(
    r'(?:^làm\s+cái\s+(?:đó|này)|cái\s+(?:đó|này)\s+đi|'
    r'cần\s+thêm\s+thông\s+tin)',
    re.IGNORECASE,
)


class RuleBasedIntentParser:
    """Dispatch theo tiền tố động từ đầu câu (Tính/Đọc ghi chú/Lưu|Ghi/Tìm). Câu không mở
    đầu bằng các tiền tố này → UNKNOWN. Đây là giới hạn có chủ đích của rule-based MVP;
    LLM/Hybrid parser là post-MVP (CLAUDE.md §7)."""

    def parse(self, goal: str) -> ParsedIntent:
        text = goal.strip()

        # --- CONV-P0 P0-2 conversational taxonomy (classification only) ---
        # Greeting first (also guards bare-math from grabbing "hi"); broadened to
        # accept time-of-day tails like "Chào buổi sáng".
        if _GREETING_WORDS.match(text):
            return self._parse_greeting(text)
        if _IDENTITY_CUE.search(text):
            return self._conv_intent(IntentName.IDENTITY_QUERY, text)
        if _CAPABILITY_CUE.search(text):
            return self._conv_intent(IntentName.CAPABILITY_QUERY, text)
        if _MEMORY_READ_CUE.search(text):
            return self._conv_intent(IntentName.MEMORY_READ, text)
        # memory-write must precede the ^Lưu|Ghi write-note dispatch ("ghi nhớ rằng",
        # "lưu ... vào memory"); its cue requires nhớ/memory so it never steals "ghi chú".
        if _MEMORY_WRITE_CUE.search(text):
            return self._conv_intent(IntentName.MEMORY_WRITE_REQUEST, text)

        # --- existing rule-based verb-prefix dispatch (precedence preserved) ---
        if re.match(r'^Tính\b', text, re.IGNORECASE):
            return self._parse_calculate(text)

        # ^Đọc ghi chú must precede summarization so "...rồi tóm tắt" stays READ_NOTE_THEN_SUMMARIZE.
        if re.match(r'^Đọc\s+ghi\s+chú\b', text, re.IGNORECASE):
            return self._parse_read_note(text)

        if re.match(r'^(?:Lưu|Ghi)\s+', text, re.IGNORECASE):
            return self._parse_write_note(text)

        # code-review must precede ^Tìm ("Tìm bug trong code này") and writing ("Viết test
        # cho function này"), per the frozen acceptance dataset.
        if _CODE_REVIEW_CUE.search(text):
            return self._conv_intent(IntentName.CODE_REVIEW_REQUEST, text)

        if re.match(r'^Tìm\b', text, re.IGNORECASE):
            return self._parse_web_search(text)

        # P4: project-context query — hẹp: ^Dự án AND cue hỏi-quyết-định.
        if re.match(r'^Dự\s+án\b', text, re.IGNORECASE) and _PROJECT_QUERY_CUE.search(text):
            return self._parse_project_context_query(text)

        # --- remaining CONV-P0 P0-2 conversational intents ---
        if _PLANNING_CUE.search(text):
            return self._conv_intent(IntentName.PLANNING_REQUEST, text)
        if _SUMMARIZE_CUE.search(text):   # after ^Đọc ghi chú dispatch above
            return self._conv_intent(IntentName.SUMMARIZATION_REQUEST, text)
        if _TRANSLATE_CUE.search(text):
            return self._conv_intent(IntentName.TRANSLATION_REQUEST, text)
        if _TECHNICAL_CUE.search(text):
            return self._conv_intent(IntentName.TECHNICAL_EXPLANATION_REQUEST, text)
        if _WRITING_CUE.search(text):     # after code-review so "Viết test ..." → CODE_REVIEW
            return self._conv_intent(IntentName.WRITING_REQUEST, text)
        if _CLARIFICATION_CUE.search(text):
            return self._conv_intent(IntentName.CLARIFICATION_REQUEST, text)

        # B.8: English "calculate ..." / "calc ..." prefix
        if _CALC_PREFIX.match(text):
            rest = _CALC_PREFIX.sub('', text)
            return self._parse_as_calculate(text, rest)

        # B.8: Vietnamese natural-language math suffix ("bằng mấy", "là bao nhiêu")
        if _VIET_MATH_SUFFIX.search(text):
            expr_text = _VIET_MATH_SUFFIX.sub('', text).strip()
            return self._parse_as_calculate(text, expr_text)

        # B.8: bare arithmetic expression (safe chars only, must start with digit or '(')
        if _BARE_MATH_ONLY.match(text):
            return self._parse_as_calculate(text, text.rstrip('= '))

        return self._unknown(text)

    def _conv_intent(self, intent: IntentName, text: str) -> ParsedIntent:
        """CONV-P0 P0-2 conversational classification result. No slots (avoids the
        planner clarification branch); user-facing responses are P0-3/P0-5/P0-6."""
        return ParsedIntent(
            intent=intent,
            confidence=0.8,
            source="rule",
            raw_text=text,
        )

    def _parse_calculate(self, text: str) -> ParsedIntent:
        rest = re.sub(r'^Tính\s+', '', text, flags=re.IGNORECASE)
        save_m = _SAVE_SUFFIX.search(rest)

        if save_m:
            expr_text = rest[:save_m.start()]
            note_name = save_m.group(1)
            expression = self._extract_expr(expr_text)
            missing: list[str] = []
            if expression is None:
                missing.append("expression")
            if not note_name:
                missing.append("note_name")
            return ParsedIntent(
                intent=IntentName.CALCULATE_THEN_SAVE_NOTE,
                confidence=0.9,
                source="rule",
                raw_text=text,
                expression=expression,
                note_name=note_name,
                missing_slots=tuple(missing),
            )

        expression = self._extract_expr(rest)
        missing = []
        if expression is None:
            missing.append("expression")
        return ParsedIntent(
            intent=IntentName.CALCULATE,
            confidence=0.9,
            source="rule",
            raw_text=text,
            expression=expression,
            missing_slots=tuple(missing),
        )

    def _parse_read_note(self, text: str) -> ParsedIntent:
        rest = re.sub(r'^Đọc\s+ghi\s+chú\s+', '', text, flags=re.IGNORECASE)
        has_summarize = _SUMMARIZE_SUFFIX.search(rest)

        if has_summarize:
            note_text = rest[:has_summarize.start()].strip()
        else:
            note_text = rest.strip()

        note_name = note_text if note_text else None
        missing: list[str] = []
        if not note_name:
            missing.append("note_name")

        intent = IntentName.READ_NOTE_THEN_SUMMARIZE if has_summarize else IntentName.READ_NOTE
        return ParsedIntent(
            intent=intent,
            confidence=0.9,
            source="rule",
            raw_text=text,
            note_name=note_name,
            missing_slots=tuple(missing),
        )

    def _parse_write_note(self, text: str) -> ParsedIntent:
        m = re.match(
            r'^(?:Lưu|Ghi)\s+(?:vào\s+)?ghi\s+chú\s+(\S+)(?:\s+(.+))?',
            text,
            re.IGNORECASE,
        )
        note_name = m.group(1) if m else None
        content = m.group(2) if m and m.group(2) else None
        missing: list[str] = []
        if not note_name:
            missing.append("note_name")
        if not content:
            missing.append("content")
        return ParsedIntent(
            intent=IntentName.WRITE_NOTE,
            confidence=0.9,
            source="rule",
            raw_text=text,
            note_name=note_name,
            content=content,
            missing_slots=tuple(missing),
        )

    def _parse_web_search(self, text: str) -> ParsedIntent:
        rest = re.sub(r'^Tìm\s+', '', text, flags=re.IGNORECASE)
        save_m = _SAVE_SUFFIX.search(rest)

        if save_m:
            query_text = rest[:save_m.start()].strip()
            note_name = save_m.group(1)
            missing: list[str] = []
            if not query_text:
                missing.append("query")
            if not note_name:
                missing.append("note_name")
            return ParsedIntent(
                intent=IntentName.WEB_SEARCH_THEN_SAVE_NOTE,
                confidence=0.9,
                source="rule",
                raw_text=text,
                query=query_text or None,
                note_name=note_name,
                missing_slots=tuple(missing),
            )

        query = rest.strip() or None
        missing = []
        if not query:
            missing.append("query")
        return ParsedIntent(
            intent=IntentName.WEB_SEARCH,
            confidence=0.9,
            source="rule",
            raw_text=text,
            query=query,
            missing_slots=tuple(missing),
        )

    def _parse_project_context_query(self, text: str) -> ParsedIntent:
        # query = nguyên câu (LocalMemoryClient bỏ qua goal — query chỉ để trace/log).
        # Không có slot bắt buộc trong parser (query luôn = text, không rỗng).
        return ParsedIntent(
            intent=IntentName.PROJECT_CONTEXT_QUERY,
            confidence=0.8,
            source="rule",
            raw_text=text,
            query=text,
        )

    def _unknown(self, text: str) -> ParsedIntent:
        return ParsedIntent(
            intent=IntentName.UNKNOWN,
            confidence=0.0,
            source="rule",
            raw_text=text,
        )

    def _parse_as_calculate(self, original: str, expr_text: str) -> ParsedIntent:
        """Shared helper for English-calc, bare-math, and Vietnamese-suffix branches."""
        expression = self._extract_expr(expr_text)
        missing: list[str] = []
        if expression is None:
            missing.append("expression")
        return ParsedIntent(
            intent=IntentName.CALCULATE,
            confidence=0.9,
            source="rule",
            raw_text=original,
            expression=expression,
            missing_slots=tuple(missing),
        )

    def _parse_greeting(self, text: str) -> ParsedIntent:
        return ParsedIntent(
            intent=IntentName.GREETING,
            confidence=0.85,
            source="rule",
            raw_text=text,
        )

    def _extract_expr(self, text: str) -> str | None:
        m = _MATH_EXPR.search(text.strip())
        if not m:
            return None
        raw = m.group().strip()
        if not any(c.isdigit() for c in raw):
            return None
        return re.sub(r'\s+', '', raw)

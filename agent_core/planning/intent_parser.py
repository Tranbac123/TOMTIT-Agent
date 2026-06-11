from __future__ import annotations

import re

from agent_core.planning.intents import IntentName, ParsedIntent


_SAVE_SUFFIX = re.compile(r'\s+rồi\s+lưu\s+vào\s+ghi\s+chú(?:\s+(\S+))?', re.IGNORECASE)
_SUMMARIZE_SUFFIX = re.compile(r'\s+rồi\s+tóm\s+tắt', re.IGNORECASE)
_MATH_EXPR = re.compile(r'[\d(][0-9()\s+\-*/. ]*')


class RuleBasedIntentParser:
    def parse(self, goal: str) -> ParsedIntent:
        text = goal.strip()

        if re.match(r'^Tính\b', text, re.IGNORECASE):
            return self._parse_calculate(text)

        if re.match(r'^Đọc\s+ghi\s+chú\b', text, re.IGNORECASE):
            return self._parse_read_note(text)

        if re.match(r'^(?:Lưu|Ghi)\s+', text, re.IGNORECASE):
            return self._parse_write_note(text)

        if re.match(r'^Tìm\b', text, re.IGNORECASE):
            return self._parse_web_search(text)

        return self._unknown(text)

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

    def _unknown(self, text: str) -> ParsedIntent:
        return ParsedIntent(
            intent=IntentName.UNKNOWN,
            confidence=0.0,
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

from __future__ import annotations

import re
import unicodedata


def normalize_vi(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"\s+", " ", text)


class GoalExtractor:
    def wants_calculate(self, goal_norm: str) -> bool:
        return self._has_any(goal_norm, ("tinh", "calculate", "calc"))

    def wants_search(self, goal_norm: str) -> bool:
        return self._has_any(
            goal_norm,
            (
                "tim thong tin",
                "tim kiem",
                "tra cuu",
                "search",
                "web search",
                "google",
                "moi nhat",
                "latest",
            ),
        )

    def wants_read_note(self, goal_norm: str) -> bool:
        return self._has_any(
            goal_norm,
            (
                "doc ghi chu",
                "doc note",
                "xem ghi chu",
                "xem note",
                "read note",
            ),
        )

    def wants_summary(self, goal_norm: str) -> bool:
        return self._has_any(
            goal_norm,
            (
                "tom tat",
                "summary",
                "summarize",
            ),
        )

    def wants_write_note(self, goal_norm: str) -> bool:
        if self.has_save_negation(goal_norm):
            return False

        has_write_action = self._has_any(
            goal_norm,
            (
                "luu",
                "ghi",
                "note lai",
                "save",
            ),
        )
        has_note_target = "ghi chu" in goal_norm or "note" in goal_norm
        return has_write_action and has_note_target

    def wants_save_note_after_action(self, goal_norm: str) -> bool:
        if self.has_save_negation(goal_norm):
            return False

        return self._has_any(
            goal_norm,
            (
                "luu vao ghi chu",
                "luu vao note",
                "ghi chu",
                "note",
                "save note",
                "note lai",
            ),
        )

    def has_save_negation(self, goal_norm: str) -> bool:
        patterns = (
            r"\bkhong\s+(can\s+)?(luu|ghi|note)",
            r"\bko\s+(can\s+)?(luu|ghi|note)",
            r"\bk\s+(can\s+)?(luu|ghi|note)",
            r"\bdung\s+(luu|ghi|note)",
            r"\bkhong\s+luu\s+ghi\s+chu",
            r"\bkhong\s+luu\s+note",
        )
        return any(re.search(pattern, goal_norm) for pattern in patterns)

    def extract_expression(self, text: str) -> str | None:
        normalized_math = self._normalize_math_words(text)

        keyword_match = re.search(
            r"(?:tính|tinh|calculate|calc)\s+(?P<body>.+)",
            normalized_math,
            flags=re.IGNORECASE,
        )
        candidate = keyword_match.group("body") if keyword_match else normalized_math

        candidate = re.split(
            r"\b(?:rồi|roi|then|sau đó|sau do|và lưu|va luu|nhưng|nhung)\b",
            candidate,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        parts = re.findall(r"[0-9\.\+\-\*\/\(\)%\s]+", candidate)
        if not parts:
            return None

        expression = max(parts, key=len).strip()
        expression = re.sub(r"\s+", "", expression)

        if not expression or not re.search(r"\d", expression):
            return None

        return expression

    def extract_search_query(self, text: str) -> str | None:
        candidate = re.split(
            r"\b(?:rồi|roi|then|sau đó|sau do|và lưu|va luu)\b",
            text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        candidate = re.sub(
            r"^\s*(hãy|hay|giúp tôi|giup toi|cho tôi|cho toi)?\s*"
            r"(tìm thông tin|tim thong tin|tìm kiếm|tim kiem|tra cứu|tra cuu|google|search|web search|tìm|tim)\s+",
            "",
            candidate,
            flags=re.IGNORECASE,
        )

        candidate = candidate.strip(" .,:;-")
        return candidate or None

    def extract_note_name(self, text: str) -> str | None:
        patterns = (
            r"(?:vào|vao)\s+(?:ghi chú|ghi chu|note)\s+(?P<name>[^:,.]+)",
            r"(?:ghi chú|ghi chu|note)\s+(?:tên|ten)\s+(?P<name>[^:,.]+)",
            r"(?:lưu|luu)\s+(?:ghi chú|ghi chu|note)\s+(?P<name>[^:,.]+)",
            r"(?:note)\s+(?P<name>[^:,.]+)",
            r"(?:ghi chú|ghi chu)\s+(?P<name>[^:,.]+)",
        )

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue

            name = match.group("name").strip()
            name = self._cut_after_markers(
                name,
                (
                    "nội dung",
                    "noi dung",
                    "là",
                    "la",
                    "rằng",
                    "rang",
                    "rồi",
                    "roi",
                    "và",
                    "va",
                    "then",
                ),
            )

            if self._looks_like_note_name(name):
                return name

        return None

    def extract_note_name_after_read(self, text: str) -> str | None:
        match = re.search(
            r"(?:đọc ghi chú|doc ghi chu|đọc note|doc note|xem ghi chú|xem ghi chu|xem note|read note)\s+(?P<name>.+)",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None

        name = match.group("name").strip()
        name = self._cut_after_markers(
            name,
            (
                "rồi tóm tắt",
                "roi tom tat",
                "và tóm tắt",
                "va tom tat",
                "tóm tắt",
                "tom tat",
                "summary",
                "summarize",
            ),
        )

        if self._looks_like_note_name(name):
            return name

        return None

    def extract_write_note_content(self, text: str) -> str | None:
        colon_match = re.search(r":\s*(?P<content>.+)$", text)
        if colon_match:
            content = colon_match.group("content").strip()
            return content or None

        content_match = re.search(
            r"(?:nội dung|noi dung|là|la|rằng|rang)\s+(?P<content>.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if content_match:
            content = content_match.group("content").strip()
            return content or None

        raw = text.strip()
        normalized = normalize_vi(raw)

        note_markers = (
            "vao ghi chu",
            "vao note",
            "ghi chu",
            "note",
        )
        note_index = self._last_marker_index(normalized, note_markers)
        if note_index is None:
            return None

        content_start = 0
        write_markers = (
            "luu",
            "ghi",
            "note lai",
            "save",
        )
        first_write_index = self._first_marker_index(normalized, write_markers)
        if first_write_index is not None:
            marker = self._marker_at(normalized, first_write_index, write_markers)
            content_start = first_write_index + len(marker)

        if note_index <= content_start:
            return None

        content = raw[content_start:note_index].strip(" .,:;-")
        return content or None

    def _normalize_math_words(self, text: str) -> str:
        normalized = normalize_vi(text)
        replacements = {
            " cong ": " + ",
            " tru ": " - ",
            " nhan ": " * ",
            " chia ": " / ",
            " x ": " * ",
        }

        padded = f" {normalized} "
        for source, target in replacements.items():
            padded = padded.replace(source, target)

        return padded.strip()

    def _cut_after_markers(self, text: str, markers: tuple[str, ...]) -> str:
        normalized = normalize_vi(text)
        cut_pos = len(text)

        for marker in markers:
            pos = normalized.find(normalize_vi(marker))
            if pos != -1:
                cut_pos = min(cut_pos, pos)

        return text[:cut_pos].strip(" .,:;-")

    def _looks_like_note_name(self, name: str) -> bool:
        normalized = normalize_vi(name)

        bad_values = {
            "",
            "ghi chu",
            "note",
            "lai",
            "rồi",
            "roi",
            "nay",
            "này",
            "do",
            "đó",
        }

        if normalized in bad_values:
            return False

        if len(normalized.split()) > 8:
            return False

        return True

    def _has_any(self, text: str, phrases: tuple[str, ...]) -> bool:
        return any(phrase in text for phrase in phrases)

    def _first_marker_index(
        self,
        text: str,
        markers: tuple[str, ...],
    ) -> int | None:
        positions = [text.find(marker) for marker in markers if text.find(marker) != -1]
        if not positions:
            return None
        return min(positions)

    def _last_marker_index(
        self,
        text: str,
        markers: tuple[str, ...],
    ) -> int | None:
        positions = [
            text.rfind(marker) for marker in markers if text.rfind(marker) != -1
        ]
        if not positions:
            return None
        return max(positions)

    def _marker_at(
        self,
        text: str,
        index: int,
        markers: tuple[str, ...],
    ) -> str:
        for marker in markers:
            if text.startswith(marker, index):
                return marker
        return ""

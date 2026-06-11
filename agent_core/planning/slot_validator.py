from __future__ import annotations

from agent_core.planning.intents import IntentName, ParsedIntent


REQUIRED_SLOTS: dict[IntentName, tuple[str, ...]] = {
    IntentName.CALCULATE: ("expression",),
    IntentName.CALCULATE_THEN_SAVE_NOTE: ("expression", "note_name"),
    IntentName.READ_NOTE: ("note_name",),
    IntentName.READ_NOTE_THEN_SUMMARIZE: ("note_name",),
    IntentName.WRITE_NOTE: ("note_name", "content"),
    IntentName.WEB_SEARCH: ("query",),
    IntentName.WEB_SEARCH_THEN_SAVE_NOTE: ("query", "note_name"),
}


class SlotValidator:
    def validate(self, parsed: ParsedIntent) -> ParsedIntent:
        required_slots = REQUIRED_SLOTS.get(parsed.intent, ())
        missing_slots = set(parsed.missing_slots)

        for slot in required_slots:
            value = getattr(parsed, slot)
            if self._is_missing(value):
                missing_slots.add(slot)

        return parsed.with_missing_slots(tuple(sorted(missing_slots)))

    def _is_missing(self, value: object) -> bool:
        if value is None:
            return True

        if isinstance(value, str) and not value.strip():
            return True

        return False

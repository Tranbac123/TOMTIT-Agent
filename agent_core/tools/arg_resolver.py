from __future__ import annotations

from dataclasses import asdict, is_dataclass

from agent_core.tools.schemas import (
    ListNotesOutput,
    MemoryWriteOutput,
    SearchMemoryOutput,
    CalculateOutput,
    FinishOutput,
    ReadNoteOutput,
    SummarizeOutput,
    ToolResult,
    WebSearchOutput,
)

from typing import Any
import re


def stringify_output(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, ToolResult):
        return stringify_output(output.output)
    if isinstance(output, CalculateOutput):
        return str(output.value)
    if isinstance(output, ReadNoteOutput):
        return output.content
    if isinstance(output, SummarizeOutput):
        return output.summary
    if isinstance(output, WebSearchOutput):
        return output.answer
    if isinstance(output, FinishOutput):
        return output.answer
    if isinstance(output, ListNotesOutput):
        return "\n".join(output.names)
    if isinstance(output, MemoryWriteOutput):
        return output.content
    if isinstance(output, SearchMemoryOutput):
        return "\n".join(str(record) for record in output.records)
    if is_dataclass(output):
        return str(asdict(output))
    return str(output)


class ArgResolver:
    def resolve_args(self, args: dict[str, Any], state: Any) -> dict[str, Any]:
        return {key: self.resolve_value(value, state) for key, value in args.items()}

    def resolve_value(self, value: Any, state: Any) -> Any:
        if isinstance(value, dict):
            return {key: self.resolve_value(item, state) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve_value(item, state) for item in value]
        if not isinstance(value, str):
            return value
        if value == "$last":
            return state.last_result
        if value == "$last_text":
            return stringify_output(state.last_result)
        if value.startswith("$last."):
            return self.resolve_path(state.last_result, value.removeprefix("$last."), "$last")
        if value.startswith("$slot."):
            return self.resolve_path(state.slots, value.removeprefix("$slot."), "$slot")
        if "${" in value:
            return self.resolve_template(value, state)
        return value

    def resolve_template(self, text: str, state: Any) -> str:
        pattern = re.compile(r"\$\{([^}]+)\}")

        def replace(match: re.Match) -> str:
            expr = match.group(1).strip()
            if expr in {"last", "last_text"}:
                return stringify_output(state.last_result)
            if expr.startswith("last."):
                value = self.resolve_path(state.last_result, expr.removeprefix("last."), "$last")
                return stringify_output(value)
            if expr.startswith("slot."):
                value = self.resolve_path(state.slots, expr.removeprefix("slot."), "$slot")
                return stringify_output(value)
            raise ValueError(f"Unknown template expression: {expr}")

        return pattern.sub(replace, text)

    def resolve_path(self, root: Any, path: str, label: str) -> Any:
        if root is None:
            raise ValueError(f"Cannot resolve {label}.{path}: root is None")
        current = root
        for part in path.split("."):
            if not part:
                raise ValueError(f"Invalid placeholder path: {label}.{path}")
            current = self.get_field(current, part, f"{label}.{path}")
        return current

    def get_field(self, obj: Any, field_name: str, full_path: str) -> Any:
        if obj is None:
            raise ValueError(f"Cannot resolve {full_path}: '{field_name}' on None")
        if isinstance(obj, dict):
            if field_name in obj:
                return obj[field_name]
            raise ValueError(f"Cannot resolve {full_path}: key '{field_name}' not found")
        if isinstance(obj, list):
            if not field_name.isdigit():
                raise ValueError(f"Cannot resolve {full_path}: list index must be numeric, got '{field_name}'")
            index = int(field_name)
            try:
                return obj[index]
            except IndexError as exc:
                raise ValueError(f"Cannot resolve {full_path}: list index {index} out of range") from exc
        if is_dataclass(obj) and hasattr(obj, field_name):
            return getattr(obj, field_name)
        if hasattr(obj, field_name):
            return getattr(obj, field_name)
        raise ValueError(f"Cannot resolve {full_path}: field '{field_name}' not found on {type(obj).__name__}")

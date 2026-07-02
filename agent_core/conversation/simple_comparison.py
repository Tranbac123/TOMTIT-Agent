"""CONV-P0 P0-7F: safe numeric comparison parser.

Deterministic, bounded-grammar only. Parses ``NUMBER COMPARATOR NUMBER`` and answers
"Đúng." / "Sai." — never uses eval/exec. Kept independent of profile semantics so it can
run early in the conversation seam, before an equality expression like ``2 == 2`` is
misrouted into the arithmetic calculator (which would otherwise return a numeric result).

``1 + 1 =`` (a trailing-equals arithmetic request) is intentionally NOT matched here — it
has an operator between the operands and stays on the arithmetic path.
"""
from __future__ import annotations

import operator
import re
from decimal import Decimal, InvalidOperation

# NUMBER COMPARATOR NUMBER, optional trailing '?'. A single '=' is accepted as equality,
# but only in this strict two-operand shape — "1 + 1 =" has an operator between operands
# and never matches (so it stays arithmetic). "==" must precede "=" in the alternation.
_RE_COMPARISON = re.compile(
    r'^\s*(-?\d+(?:\.\d+)?)\s*(==|!=|>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)\s*[?？]?\s*$'
)

_COMPARATORS = {
    "==": operator.eq,
    "=": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
}


def try_answer_comparison(text: str) -> str | None:
    """Return "Đúng." / "Sai." for a bare numeric comparison, else None.

    None means the text is not a two-operand comparison and should flow to the normal
    router/arithmetic path.
    """
    m = _RE_COMPARISON.match(text.strip())
    if m is None:
        return None
    left_raw, comparator, right_raw = m.group(1), m.group(2), m.group(3)
    try:
        left = Decimal(left_raw)
        right = Decimal(right_raw)
    except InvalidOperation:  # pragma: no cover - regex guarantees numeric tokens
        return None
    op = _COMPARATORS.get(comparator)
    if op is None:  # pragma: no cover - regex only yields known comparators
        return None
    return "Đúng." if op(left, right) else "Sai."

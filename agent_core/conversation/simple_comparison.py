"""CONV-P0 P0-7F: safe numeric comparison parser.

Deterministic, bounded-grammar only. Parses ``EXPR COMPARATOR EXPR`` and answers
"Đúng." / "Sai." — never uses eval/exec. Kept independent of profile semantics so it can
run early in the conversation seam, before an equality expression like ``2 == 2`` is
misrouted into the arithmetic calculator (which would otherwise return a numeric result).

Each side may be a bare number or a bounded arithmetic expression over ``+ - * /``
(P0-7F-FIX5 Part A): ``2 * 3 == 6`` and ``2 + 3 > 4`` are comparison truth questions,
not arithmetic. Operator precedence (``*``/``/`` before ``+``/``-``) is honored; there are
no parentheses. Evaluation is a small hand-rolled two-pass over tokenized operands — no
Python ``eval``.

``1 + 1 =`` (a trailing-equals arithmetic request) is intentionally NOT matched here — it
has no right-hand operand after the comparator and stays on the arithmetic path.
"""
from __future__ import annotations

import operator
import re
from decimal import Decimal, InvalidOperation

# A side of the comparison: a number, optionally followed by (op number) groups. Operators
# inside a side are the four arithmetic ops only; comparator characters (= ! > <) are never
# part of a side, so the greedy match always stops at the comparator.
_SIDE = r'-?\d+(?:\.\d+)?(?:\s*[+\-*/]\s*-?\d+(?:\.\d+)?)*'

# EXPR COMPARATOR EXPR, optional trailing '?'. A single '=' is accepted as equality, but
# only with a real right-hand expression — "1 + 1 =" has none and never matches (so it stays
# arithmetic). "==" must precede "=" in the alternation.
_RE_COMPARISON = re.compile(
    r'^\s*(' + _SIDE + r')\s*(==|!=|>=|<=|>|<|=)\s*(' + _SIDE + r')\s*[?？]?\s*$'
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


def _tokenize(expr: str) -> list[str] | None:
    """Split a validated arithmetic side into an alternating operand/operator token list.

    Returns tokens like ``["2", "*", "3"]`` or ``["-1"]``, or None if the shape is
    unexpected (defensive — the side regex should guarantee a valid shape). A leading '-'
    or a '-' right after an operator is folded into the following number literal.
    """
    tokens: list[str] = []
    i = 0
    n = len(expr)
    expect_number = True
    num_re = re.compile(r'\d+(?:\.\d+)?')
    while i < n:
        c = expr[i]
        if c.isspace():
            i += 1
            continue
        if expect_number:
            neg = False
            if c == '-':
                neg = True
                i += 1
                while i < n and expr[i].isspace():
                    i += 1
            m = num_re.match(expr, i)
            if m is None:
                return None
            tokens.append(("-" if neg else "") + m.group(0))
            i = m.end()
            expect_number = False
        else:
            if c in "+-*/":
                tokens.append(c)
                i += 1
                expect_number = True
            else:
                return None
    if expect_number:  # trailing operator with no operand
        return None
    return tokens


def _eval_side(expr: str) -> Decimal | None:
    """Evaluate a bounded arithmetic side to a Decimal, honoring * / over + -. No Python eval."""
    tokens = _tokenize(expr)
    if not tokens:
        return None
    try:
        # Pass 1: fold * and / into running terms; + / - start a new signed term.
        terms: list[Decimal] = [Decimal(tokens[0])]
        i = 1
        while i < len(tokens):
            op = tokens[i]
            num = Decimal(tokens[i + 1])
            if op == "*":
                terms[-1] *= num
            elif op == "/":
                if num == 0:
                    return None
                terms[-1] /= num
            elif op == "+":
                terms.append(num)
            else:  # "-"
                terms.append(-num)
            i += 2
    except (InvalidOperation, IndexError):  # pragma: no cover - regex guards shape
        return None
    return sum(terms, Decimal(0))


def try_answer_comparison(text: str) -> str | None:
    """Return "Đúng." / "Sai." for a numeric comparison, else None.

    Each side may be a bare number or a bounded arithmetic expression. None means the text
    is not a two-sided comparison and should flow to the normal router/arithmetic path.
    """
    m = _RE_COMPARISON.match(text.strip())
    if m is None:
        return None
    left = _eval_side(m.group(1))
    right = _eval_side(m.group(3))
    if left is None or right is None:
        return None
    op = _COMPARATORS.get(m.group(2))
    if op is None:  # pragma: no cover - regex only yields known comparators
        return None
    return "Đúng." if op(left, right) else "Sai."

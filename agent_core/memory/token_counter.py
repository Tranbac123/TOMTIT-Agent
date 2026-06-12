from __future__ import annotations

from typing import Protocol, runtime_checkable

MEMORY_WRITE_TIMEOUT_SECONDS = 2.0


@runtime_checkable
class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class ApproxTokenCounter:
    """MVP token counter. Word-based, deterministic. KHÔNG chính xác như tokenizer LLM —
    mục tiêu là CÙNG-MỘT-CÁCH-ĐẾM hai bên (local + remote sau này) để token_budget
    reproduce được. Thay bằng tokenizer thật là [deferred], qua cùng Protocol nên không vỡ."""

    def count(self, text: str) -> int:
        return max(1, len(text.split()))

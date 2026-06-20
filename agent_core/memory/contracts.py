from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_core.state.enums import MemoryType, SourceType, TrustLevel

SCHEMA_VERSION = "1"

# Literal types khóa giá trị — tránh typo "fallback"/"fall_back"/"localFallback"
MemorySource = Literal["remote_memory", "local_memory", "file", "user", "prompt"]
Provenance   = Literal["remote", "fallback", "user", "file", "prompt"]
Confidence   = Literal["normal", "limited", "unknown"]
Freshness    = Literal["fresh", "stale", "unknown"]


class ContextItem(BaseModel):
    """Một mẩu context trả về cho agent. Per-item provenance để biết item nào đáng tin."""
    # strict=True: ép MemoryType enum, từ chối coerce string "note" → enum (Pydantic v2 default
    # sẽ coerce; strict ngăn điều đó, đúng với intent §1a "Enum bắt lỗi tại biên").
    model_config = ConfigDict(strict=True)

    content: str
    type: MemoryType
    score: float = 0.0
    tokens: int = 0
    source: MemorySource = "remote_memory"
    provenance: Provenance = "remote"
    confidence: Confidence = "normal"
    freshness: Freshness = "unknown"
    metadata: dict = Field(default_factory=dict)
    source_type: SourceType = SourceType.MEMORY
    trust_level: TrustLevel = TrustLevel.UNTRUSTED_EVIDENCE
    source_ref: str | None = None


# NOTE: chỉ ContextItem dùng strict=True (ép MemoryType tại biên — điểm typo rủi ro nhất).
# ContextPack/MemoryCandidate/WriteResponse cố ý để lax: phần lớn primitive, coercion
# Pydantic v2 vô hại. KHÔNG thêm strict vào các model này nếu chưa kiểm caller — strict
# toàn cục có thể làm vỡ caller truyền cross-type hợp lệ.
class ContextPack(BaseModel):
    """Kết quả retrieve, token-budgeted. Local lẫn remote backend trả CÙNG kiểu này."""
    schema_version: str = SCHEMA_VERSION
    items: list[ContextItem] = Field(default_factory=list)
    total_items: int = 0
    tokens_used: int = 0
    token_budget: int = 0
    truncated: bool = False
    degraded: bool = False
    memory_source: Literal["remote", "local"] = "remote"


class MemoryCandidate(BaseModel):
    """Ứng viên memory để ghi sau khi task xong."""
    type: MemoryType
    content: str
    tags: list[str] = Field(default_factory=list)
    importance: float = 0.5
    confidence: float = 1.0
    evidence_ref: str | None = None
    metadata: dict = Field(default_factory=dict)


class WriteResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    written_ids: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)

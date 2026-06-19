"""SF1 — EvidenceEnvelope and tool_observation_ref contract tests."""
from __future__ import annotations

import pytest
from types import MappingProxyType

from agent_core.safety.evidence import (
    EvidenceEnvelope,
    MetadataScalar,
    MetadataValue,
    tool_observation_ref,
)
from agent_core.state.enums import SourceType, TrustLevel


# ---------------------------------------------------------------------------
# TrustLevel values
# ---------------------------------------------------------------------------

def test_trust_level_values():
    assert TrustLevel.TRUSTED_INSTRUCTION == "trusted_instruction"
    assert TrustLevel.TRUSTED_CONFIGURATION == "trusted_configuration"
    assert TrustLevel.UNTRUSTED_EVIDENCE == "untrusted_evidence"
    assert len(TrustLevel) == 3


# ---------------------------------------------------------------------------
# SourceType final values (SF1 adds SESSION, WORKSPACE, SKILL)
# ---------------------------------------------------------------------------

def test_source_type_sf1_additions():
    values = {e.value for e in SourceType}
    assert "session" in values
    assert "workspace" in values
    assert "skill" in values


def test_source_type_total_count():
    assert len(SourceType) == 9


def test_source_type_original_values_preserved():
    for v in ("web", "memory", "tool", "user", "agent", "system"):
        assert SourceType(v)


# ---------------------------------------------------------------------------
# EvidenceEnvelope — basic construction
# ---------------------------------------------------------------------------

def test_envelope_basic_construction():
    e = EvidenceEnvelope(
        content="hello",
        source_type=SourceType.TOOL,
        trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
    )
    assert e.content == "hello"
    assert e.source_type is SourceType.TOOL
    assert e.trust_level is TrustLevel.UNTRUSTED_EVIDENCE
    assert e.source_ref is None
    assert isinstance(e.metadata, MappingProxyType)
    assert len(e.metadata) == 0


def test_envelope_with_source_ref():
    e = EvidenceEnvelope(
        content="x",
        source_type=SourceType.MEMORY,
        trust_level=TrustLevel.TRUSTED_CONFIGURATION,
        source_ref="task:abc/step:1/tool:calculate",
    )
    assert e.source_ref == "task:abc/step:1/tool:calculate"


def test_envelope_with_metadata():
    e = EvidenceEnvelope(
        content="x",
        source_type=SourceType.USER,
        trust_level=TrustLevel.TRUSTED_INSTRUCTION,
        metadata={"score": 0.9, "tag": "test", "flag": True, "count": 3},
    )
    assert e.metadata["score"] == 0.9
    assert e.metadata["tag"] == "test"
    assert e.metadata["flag"] is True
    assert e.metadata["count"] == 3


# ---------------------------------------------------------------------------
# EvidenceEnvelope — frozen (immutable)
# ---------------------------------------------------------------------------

def test_envelope_is_frozen():
    e = EvidenceEnvelope(
        content="x",
        source_type=SourceType.TOOL,
        trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
    )
    with pytest.raises((AttributeError, TypeError)):
        e.content = "mutated"  # type: ignore[misc]


def test_envelope_metadata_is_read_only():
    e = EvidenceEnvelope(
        content="x",
        source_type=SourceType.TOOL,
        trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
        metadata={"k": "v"},
    )
    with pytest.raises(TypeError):
        e.metadata["k"] = "mutated"  # type: ignore[index]


def test_envelope_metadata_is_defensive_copy():
    original = {"k": "v"}
    e = EvidenceEnvelope(
        content="x",
        source_type=SourceType.TOOL,
        trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
        metadata=original,
    )
    original["k"] = "mutated"
    assert e.metadata["k"] == "v"


# ---------------------------------------------------------------------------
# EvidenceEnvelope — source_ref normalization
# ---------------------------------------------------------------------------

def test_envelope_source_ref_none_accepted():
    e = EvidenceEnvelope(
        content="x",
        source_type=SourceType.TOOL,
        trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
        source_ref=None,
    )
    assert e.source_ref is None


def test_envelope_source_ref_blank_rejected():
    with pytest.raises(ValueError):
        EvidenceEnvelope(
            content="x",
            source_type=SourceType.TOOL,
            trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
            source_ref="   ",
        )


def test_envelope_source_ref_empty_rejected():
    with pytest.raises(ValueError):
        EvidenceEnvelope(
            content="x",
            source_type=SourceType.TOOL,
            trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
            source_ref="",
        )


# ---------------------------------------------------------------------------
# EvidenceEnvelope — metadata scalar/tuple allowlist
# ---------------------------------------------------------------------------

def test_metadata_str_allowed():
    e = EvidenceEnvelope(
        content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
        metadata={"k": "v"},
    )
    assert e.metadata["k"] == "v"


def test_metadata_int_allowed():
    e = EvidenceEnvelope(
        content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
        metadata={"k": 42},
    )
    assert e.metadata["k"] == 42


def test_metadata_float_allowed():
    e = EvidenceEnvelope(
        content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
        metadata={"k": 3.14},
    )
    assert e.metadata["k"] == 3.14


def test_metadata_bool_allowed():
    e = EvidenceEnvelope(
        content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
        metadata={"k": False},
    )
    assert e.metadata["k"] is False


def test_metadata_none_allowed():
    e = EvidenceEnvelope(
        content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
        metadata={"k": None},
    )
    assert e.metadata["k"] is None


def test_metadata_tuple_of_scalars_allowed():
    e = EvidenceEnvelope(
        content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
        metadata={"k": ("a", 1, True, None)},
    )
    assert e.metadata["k"] == ("a", 1, True, None)


def test_metadata_list_rejected():
    with pytest.raises(TypeError):
        EvidenceEnvelope(
            content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
            metadata={"k": [1, 2]},
        )


def test_metadata_dict_rejected():
    with pytest.raises(TypeError):
        EvidenceEnvelope(
            content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
            metadata={"k": {"nested": True}},
        )


def test_metadata_set_rejected():
    with pytest.raises(TypeError):
        EvidenceEnvelope(
            content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
            metadata={"k": {1, 2}},
        )


def test_metadata_bytes_rejected():
    with pytest.raises(TypeError):
        EvidenceEnvelope(
            content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
            metadata={"k": b"bytes"},
        )


def test_metadata_str_enum_rejected():
    """StrEnum is a subclass of str but must be rejected (exact-type check)."""
    from agent_core.state.enums import SourceType as ST
    with pytest.raises(TypeError):
        EvidenceEnvelope(
            content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
            metadata={"k": ST.MEMORY},
        )


def test_metadata_bool_not_treated_as_int():
    """bool isinstance int but exact-type check must preserve it as bool, not coerce."""
    e = EvidenceEnvelope(
        content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
        metadata={"flag": True},
    )
    assert type(e.metadata["flag"]) is bool


def test_metadata_tuple_with_invalid_element_rejected():
    with pytest.raises(TypeError):
        EvidenceEnvelope(
            content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
            metadata={"k": ("ok", [1, 2])},
        )


def test_metadata_object_rejected():
    with pytest.raises(TypeError):
        EvidenceEnvelope(
            content="x", source_type=SourceType.TOOL, trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
            metadata={"k": object()},
        )


# ---------------------------------------------------------------------------
# EvidenceEnvelope — type validation
# ---------------------------------------------------------------------------

def test_envelope_non_str_content_rejected():
    with pytest.raises(TypeError):
        EvidenceEnvelope(
            content=42,  # type: ignore[arg-type]
            source_type=SourceType.TOOL,
            trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
        )


def test_envelope_invalid_source_type_rejected():
    with pytest.raises(TypeError):
        EvidenceEnvelope(
            content="x",
            source_type="tool",  # type: ignore[arg-type]
            trust_level=TrustLevel.UNTRUSTED_EVIDENCE,
        )


def test_envelope_invalid_trust_level_rejected():
    with pytest.raises(TypeError):
        EvidenceEnvelope(
            content="x",
            source_type=SourceType.TOOL,
            trust_level="untrusted_evidence",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# tool_observation_ref
# ---------------------------------------------------------------------------

def test_tool_observation_ref_format():
    ref = tool_observation_ref(task_id="task-1", step_id="step-2", tool_name="calculate")
    assert ref == "task:task-1/step:step-2/tool:calculate"


def test_tool_observation_ref_strips_whitespace():
    ref = tool_observation_ref(task_id=" t1 ", step_id=" s1 ", tool_name=" calc ")
    assert ref == "task:t1/step:s1/tool:calc"


def test_tool_observation_ref_blank_task_id_rejected():
    with pytest.raises(ValueError):
        tool_observation_ref(task_id="", step_id="s", tool_name="calc")


def test_tool_observation_ref_blank_step_id_rejected():
    with pytest.raises(ValueError):
        tool_observation_ref(task_id="t", step_id="   ", tool_name="calc")


def test_tool_observation_ref_blank_tool_name_rejected():
    with pytest.raises(ValueError):
        tool_observation_ref(task_id="t", step_id="s", tool_name="")

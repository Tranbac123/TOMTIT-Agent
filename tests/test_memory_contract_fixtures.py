from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_core.memory.wire.v1 import (
    ContextRequestV1,
    ContextResponseV1,
    ErrorEnvelopeV1,
    SCHEMA_VERSION,
    WriteRequestV1,
    WriteResponseV1,
)

FIXTURES = Path(__file__).parent / "fixtures" / "memory_contract_v1"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_manifest_hashes_match_fixture_bytes():
    manifest = _load("manifest.json")
    for name, expected_hash in manifest["fixtures"].items():
        actual_hash = hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
        assert actual_hash == expected_hash


def test_fixture_schema_version_and_models_validate():
    assert _load("manifest.json")["schema_version"] == SCHEMA_VERSION
    assert ContextRequestV1.model_validate(_load("context_request.json")).schema_version == SCHEMA_VERSION
    assert ContextResponseV1.model_validate(_load("context_response.json")).schema_version == SCHEMA_VERSION
    assert WriteRequestV1.model_validate(_load("write_request.json")).schema_version == SCHEMA_VERSION
    assert WriteResponseV1.model_validate(_load("write_response.json")).schema_version == SCHEMA_VERSION
    assert ErrorEnvelopeV1.model_validate(_load("error_response.json")).schema_version == SCHEMA_VERSION


def test_fixture_enums_statuses_and_routes_are_v1():
    context_request = ContextRequestV1.model_validate(_load("context_request.json"))
    context_response = ContextResponseV1.model_validate(_load("context_response.json"))
    write_request = WriteRequestV1.model_validate(_load("write_request.json"))
    write_response = WriteResponseV1.model_validate(_load("write_response.json"))
    error_response = ErrorEnvelopeV1.model_validate(_load("error_response.json"))

    assert set(context_request.type_filter or []) == {"decision", "rule", "project_context"}
    assert {item.type for item in context_response.items} == {"decision"}
    assert {candidate.type for candidate in write_request.candidates} == {"decision", "rule"}
    assert {result.status for result in write_response.results} == {"written", "skipped_duplicate"}
    assert error_response.error.code == "IDEMPOTENCY_CONFLICT"
    assert _load("manifest.json")["routes"] == [
        "POST /v1/context/retrieve",
        "POST /v1/memories/write",
        "GET /v1/memories/{memory_id}",
        "GET /v1/health/live",
        "GET /v1/health/ready",
    ]


def test_optional_sibling_memory_fixtures_match_when_present():
    sibling = Path(__file__).parents[2] / "TOMTIT-Memory" / "contracts" / "v1"
    if not sibling.exists():
        return
    for name in _load("manifest.json")["fixtures"]:
        assert (FIXTURES / name).read_bytes() == (sibling / name).read_bytes()


# ---------------------------------------------------------------------------
# SF1 — field-set snapshot assertions (wire must not change)
# ---------------------------------------------------------------------------

def test_context_item_v1_field_set_unchanged():
    """ContextItemV1 wire field set must match the SF1 preflight snapshot."""
    import dataclasses, json as _json, hashlib
    from agent_core.memory.wire.v1 import ContextItemV1
    fields = tuple(ContextItemV1.model_fields.keys())
    fp = hashlib.sha256(
        _json.dumps({"f": list(fields)}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    assert fp == "0b17c5b1b21e543d", f"ContextItemV1 wire fields changed: {fields}"


def test_context_request_v1_field_set_unchanged():
    from agent_core.memory.wire.v1 import ContextRequestV1
    import json as _json, hashlib
    fields = tuple(ContextRequestV1.model_fields.keys())
    fp = hashlib.sha256(
        _json.dumps({"f": list(fields)}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    assert fp == "1831bb7212c144e3", f"ContextRequestV1 wire fields changed: {fields}"


def test_context_response_v1_field_set_unchanged():
    from agent_core.memory.wire.v1 import ContextResponseV1
    import json as _json, hashlib
    fields = tuple(ContextResponseV1.model_fields.keys())
    fp = hashlib.sha256(
        _json.dumps({"f": list(fields)}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    assert fp == "c0e001b250230d92", f"ContextResponseV1 wire fields changed: {fields}"


def test_canonical_fixture_sha256_hashes():
    """All six wire fixtures must match their SF1-implementation-baseline SHA-256 hashes."""
    expected = {
        "context_request.json":  "06be91cd6ddb827607e6106aba1faddcbcb085649747b6bcc50c6cc877019c85",
        "context_response.json": "9f7ab7e561cf43b0dd5399a31d0f12072448a849a3f6235bf59a16ebabe73186",
        "error_response.json":   "3f87aca2e2d9355dab743f592aa586bb4e3d09e1ca81ded12ca2ac3f16b44fcb",
        "manifest.json":         "5a439f07adc9922394a8bb05512174a3c42f132c7c14234ffbe21f3202228450",
        "write_request.json":    "efc2f6ab490d8eb6728d119ace37ee334fef5c94009a376e07bc83248b4e2771",
        "write_response.json":   "3939158e4b0026fa8fedc99491ff5c2206c50f6cd2bef2af568e5f1c387b7a96",
    }
    for name, sha in expected.items():
        actual = hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
        assert actual == sha, f"Wire fixture {name!r} hash mismatch: {actual}"

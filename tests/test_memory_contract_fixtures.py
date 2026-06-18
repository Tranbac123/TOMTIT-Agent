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

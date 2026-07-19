"""Gate 1B-C conformance tests for canonical decision and record identity."""
from __future__ import annotations

import dataclasses
import inspect
import json
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from agent_core.build_harness.canonical import canonical_digest, canonical_json_bytes
from agent_core.build_harness.merge_eligibility import (
    CANONICALIZATION_CONTRACT_DIGEST,
    CANONICALIZATION_VERSION,
    MERGE_ELIGIBILITY_POLICY_V1,
    POLICY_RECORD_SCHEMA_DIGEST,
    POLICY_RECORD_SCHEMA_VERSION,
    DecisionAuthority,
    MergeEligibilityPolicyInput,
    evaluate_decision_core,
)
from agent_core.build_harness.merge_eligibility_facade import (
    _PRODUCTION_POLICY,
    evaluate_merge_eligibility,
)
from agent_core.build_harness.merge_eligibility_record import (
    RecordConstructionError,
    build_policy_evaluation_record,
    finalize_decision,
    validate_policy_evaluation_record,
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = json.loads(
    (_ROOT / "data/evals/changegate_merge_eligibility_golden_cases.json").read_text()
)
_CASES = _FIXTURE["cases"]
_IDENTITY_FIELDS = _FIXTURE["slice_1a_semantic_manifest"]["replay"][
    "decision_identity_fields"
]


def _input(case: dict) -> MergeEligibilityPolicyInput:
    return MergeEligibilityPolicyInput.from_json_dict(
        {
            **case["policy_input_bindings"],
            "facts": case["policy_input_facts"],
            "policy_record_schema_version": POLICY_RECORD_SCHEMA_VERSION,
            "policy_record_schema_digest": POLICY_RECORD_SCHEMA_DIGEST,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "canonicalization_contract_digest": CANONICALIZATION_CONTRACT_DIGEST,
        }
    )


def _outputs(case: dict):
    policy_input = _input(case)
    core = evaluate_decision_core(policy_input, MERGE_ELIGIBILITY_POLICY_V1)
    decision = finalize_decision(policy_input, core)
    return policy_input, core, decision, build_policy_evaluation_record(policy_input, decision)


def _oracle(case: dict, policy_input: MergeEligibilityPolicyInput) -> tuple[str, str]:
    """Fixture/manifest-only oracle; it does not call record production helpers."""
    facts = case["policy_input_facts"]
    bindings = case["policy_input_bindings"]
    input_payload = {
        "kind": "changegate.merge-eligibility-policy-input.test-oracle.v1",
        "task_id": bindings["task_id"],
        **{key: bindings[key] for key in _IDENTITY_FIELDS[1:9]},
        "policy_version": bindings["policy_version"],
        "evaluator_version": bindings["evaluator_version"],
        "evaluation_mode": bindings["evaluation_mode"],
        "policy_record_schema_version": POLICY_RECORD_SCHEMA_VERSION,
        "policy_record_schema_digest": POLICY_RECORD_SCHEMA_DIGEST,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "canonicalization_contract_digest": CANONICALIZATION_CONTRACT_DIGEST,
        "facts": {key: facts[key] for key in sorted(facts)},
    }
    complete = case["expected_complete_reason_codes"]
    blocking = [
        code
        for code in complete
        if code not in {"SCOPE_UNCERTAIN", "VERIFIER_INDEPENDENCE_UNKNOWN"}
    ]
    review = [code for code in complete if code not in blocking]
    values = {
        "task_id": bindings["task_id"],
        **{key: bindings[key] for key in _IDENTITY_FIELDS[1:9]},
        "policy_version": bindings["policy_version"],
        "evaluator_version": bindings["evaluator_version"],
        "evaluation_mode": bindings["evaluation_mode"],
        "input_digest": canonical_digest(input_payload),
        "disposition": case["expected_disposition"],
        "decision_authority": case["expected_decision_authority"],
        "primary_reason_code": case["expected_primary_reason"],
        "complete_reason_codes": complete,
        "blocking_reason_codes": blocking,
        "review_reason_codes": review,
        **{
            field: sorted(facts[field])
            for field in (
                "required_requirement_ids",
                "satisfied_requirement_ids",
                "invalid_requirement_ids",
                "missing_requirement_ids",
                "rejected_evidence_ids",
                "invalid_provenance_evidence_ids",
                "unexpected_evidence_ids",
            )
        },
    }
    assert values["input_digest"] == policy_input.input_digest()
    decision_digest = canonical_digest(
        {"kind": "changegate.merge-eligibility-decision.test-oracle.v1", **values}
    )
    record_payload = {
        "schema_version": "changegate.policy-evaluation-record.v1",
        **values,
        "decision_digest": decision_digest,
    }
    return decision_digest, canonical_digest(record_payload)


@pytest.mark.parametrize("case", _CASES, ids=lambda item: item["case_id"])
def test_all_golden_decision_and_record_digests_match_independent_oracle(case: dict) -> None:
    policy_input, _core, decision, record = _outputs(case)
    expected_decision, expected_record = _oracle(case, policy_input)
    assert decision.decision_digest == expected_decision
    assert record.policy_record_digest == expected_record
    assert validate_policy_evaluation_record(record)["errors"] == []
    assert validate_policy_evaluation_record(record, policy_input)["errors"] == []


@pytest.mark.parametrize("case", _CASES, ids=lambda item: item["case_id"])
def test_facade_is_exact_fixed_policy_composition(case: dict) -> None:
    policy_input, core, decision, record = _outputs(case)
    assert inspect.signature(evaluate_merge_eligibility).parameters.keys() == {"policy_input"}
    assert _PRODUCTION_POLICY is MERGE_ELIGIBILITY_POLICY_V1
    assert evaluate_merge_eligibility(policy_input) == (decision, record)
    if case["case_id"] == "GC-S1-018":
        facade_decision, _facade_record = evaluate_merge_eligibility(policy_input)
        assert facade_decision.disposition.value == "BLOCK"
        assert facade_decision.primary_reason_code == "POLICY_CONTEXT_STALE"
    assert core == evaluate_decision_core(policy_input, _PRODUCTION_POLICY)


def test_finalizer_copies_core_and_changes_only_corresponding_identity_digest() -> None:
    policy_input, core, decision, _record = _outputs(_CASES[0])
    changed_core = dataclasses.replace(
        core,
        decision_authority=(
            DecisionAuthority.ADVISORY_ONLY
            if core.decision_authority is DecisionAuthority.AUTHORITATIVE
            else DecisionAuthority.AUTHORITATIVE
        ),
    )
    changed = finalize_decision(policy_input, changed_core)
    for field in (
        "disposition", "primary_reason_code",
        "complete_reason_codes", "blocking_reason_codes", "review_reason_codes",
        "required_requirement_ids", "satisfied_requirement_ids",
        "invalid_requirement_ids", "missing_requirement_ids", "rejected_evidence_ids",
        "invalid_provenance_evidence_ids", "unexpected_evidence_ids",
    ):
        assert getattr(changed, field) == getattr(decision, field)
    assert changed.decision_authority is changed_core.decision_authority
    assert changed.decision_digest != decision.decision_digest


def test_builder_rejects_input_echo_and_digest_inconsistency() -> None:
    policy_input, _core, decision, _record = _outputs(_CASES[0])
    object.__setattr__(decision, "task_id", "different-task")
    with pytest.raises(RecordConstructionError):
        build_policy_evaluation_record(policy_input, decision)


@pytest.mark.parametrize("malformed", [None, 1, "record", [], {}, {1: "mixed"}])
def test_validator_is_total_for_malformed_candidates(malformed: object) -> None:
    result = validate_policy_evaluation_record(malformed)
    assert result["errors"]
    assert result["classifications"] == []


def test_validator_rejects_inner_and_outer_digest_tampering() -> None:
    policy_input, _core, _decision, record = _outputs(_CASES[0])
    object.__setattr__(record, "decision_digest", canonical_digest({"tamper": 1}))
    object.__setattr__(record, "policy_record_digest", canonical_digest(record.to_canonical_payload()))
    assert "DECISION_DIGEST_NOT_DERIVED" in validate_policy_evaluation_record(record)["errors"]
    assert validate_policy_evaluation_record(record, policy_input)["classifications"] == []


def test_identifier_universes_are_optional_and_enforced_when_supplied() -> None:
    case = _CASES[0]
    policy_input, _core, _decision, record = _outputs(case)
    universes = case["identifier_universes"]
    assert validate_policy_evaluation_record(record, policy_input, universes)["errors"] == []
    rejected_universe = {**universes, "requirement_id_universe": ()}
    assert "IDENTIFIER_UNIVERSE_MISMATCH" in validate_policy_evaluation_record(record, identifier_universes=rejected_universe)["errors"]


# OS3: adversarial matrices for the typed and raw JSON record representations.
_BINDING_FIELDS = (
    "task_contract_digest", "candidate_digest", "repository_snapshot_digest",
    "verification_bundle_digest", "approval_digest_or_sentinel",
    "authority_binding_digest", "verifier_binding_digest", "policy_digest",
)
_SEMANTIC_FIELDS = (
    "disposition", "decision_authority", "primary_reason_code",
    "complete_reason_codes", "blocking_reason_codes", "review_reason_codes",
    "required_requirement_ids", "satisfied_requirement_ids",
    "invalid_requirement_ids", "missing_requirement_ids", "rejected_evidence_ids",
    "invalid_provenance_evidence_ids", "unexpected_evidence_ids",
)


def _mutate_frozen(value: object, field: str, replacement: object) -> object:
    object.__setattr__(value, field, replacement)
    return value


def _raw_record(case: dict) -> tuple[MergeEligibilityPolicyInput, dict]:
    policy_input, _core, _decision, record = _outputs(case)
    raw = record.to_canonical_payload()
    raw["policy_record_digest"] = record.policy_record_digest
    assert len(raw) == 29
    return policy_input, raw


def _independent_decision_digest(raw: dict) -> str:
    return canonical_digest(
        {
            "kind": "changegate.merge-eligibility-decision.test-oracle.v1",
            **{field: raw[field] for field in _IDENTITY_FIELDS},
        }
    )


def _independent_record_digest(raw: dict) -> str:
    return canonical_digest(
        {key: value for key, value in raw.items() if key != "policy_record_digest"}
    )


def _independent_rehash(raw: dict, *, decision: bool = True) -> dict:
    if decision:
        raw["decision_digest"] = _independent_decision_digest(raw)
    raw["policy_record_digest"] = _independent_record_digest(raw)
    return raw


_RAW_RECORD_FIELDS = frozenset(
    {"schema_version", *_IDENTITY_FIELDS, "decision_digest", "policy_record_digest"}
)
_RAW_INPUT_FIELDS = frozenset(
    {
        "kind", "task_id", *_BINDING_FIELDS, "policy_version", "evaluator_version",
        "evaluation_mode", "policy_record_schema_version",
        "policy_record_schema_digest", "canonicalization_version",
        "canonicalization_contract_digest", "facts",
    }
)
_ORACLE_REASON_CODES = frozenset(item["code"] for item in _FIXTURE["reason_codes"])
_HEX = frozenset("0123456789abcdef")
_TOKEN_HEAD = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
)


def _is_exact(value: object, expected: type) -> bool:
    return type(value) is expected  # noqa: E721 - exact boundary type is normative


def _oracle_digest(value: object) -> bool:
    return (
        _is_exact(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and set(value[7:]) <= _HEX
    )


def _oracle_token(value: object) -> bool:
    return (
        _is_exact(value, str)
        and 1 <= len(value) <= 128
        and value[0] in _TOKEN_HEAD
        and all(character in _TOKEN_HEAD or character in "._-" for character in value)
    )


def _independent_validate_raw(
    candidate: object,
    canonical_input: object = None,
    universes: object = None,
) -> dict[str, list[str]]:
    """Spec/manifest oracle; production validation helpers are never called."""
    if not _is_exact(candidate, dict) or not all(_is_exact(key, str) for key in candidate):
        return {"errors": ["RECORD_NOT_AN_OBJECT"], "classifications": []}
    raw = candidate
    if set(raw) != _RAW_RECORD_FIELDS:
        return {"errors": ["RECORD_FIELD_SET_DRIFT"], "classifications": []}

    errors: list[str] = []
    if raw["schema_version"] != POLICY_RECORD_SCHEMA_VERSION:
        errors.append("RECORD_TYPE_INVALID")
    if not _oracle_token(raw["task_id"]):
        errors.append("RECORD_TYPE_INVALID")
    if not _oracle_token(raw["policy_version"]) or not _oracle_token(raw["evaluator_version"]):
        errors.append("RECORD_TYPE_INVALID")
    for field in (*_BINDING_FIELDS, "input_digest", "decision_digest", "policy_record_digest"):
        value = raw[field]
        if field == "approval_digest_or_sentinel" and value == "NO_APPROVAL_SUPPLIED":
            continue
        if not _oracle_digest(value):
            errors.append("RECORD_TYPE_INVALID")
    enums = {
        "evaluation_mode": {"ENFORCE", "SHADOW"},
        "disposition": {"ELIGIBLE_TO_MERGE_UNDER_POLICY", "REVIEW_REQUIRED", "BLOCK"},
        "decision_authority": {"AUTHORITATIVE", "ADVISORY_ONLY"},
    }
    if any(not _is_exact(raw[field], str) or raw[field] not in allowed for field, allowed in enums.items()):
        errors.append("RECORD_TYPE_INVALID")
    collection_fields = _SEMANTIC_FIELDS[3:]
    for field in collection_fields:
        value = raw[field]
        if not _is_exact(value, list) or any(not _is_exact(item, str) for item in value):
            errors.append("RECORD_TYPE_INVALID")
        elif value != sorted(value) or len(value) != len(set(value)):
            errors.append("RECORD_NOT_NORMALIZED")
    primary = raw["primary_reason_code"]
    if primary is not None and (not _is_exact(primary, str) or primary not in _ORACLE_REASON_CODES):
        errors.append("RECORD_TYPE_INVALID")
    for field in ("complete_reason_codes", "blocking_reason_codes", "review_reason_codes"):
        value = raw[field]
        if _is_exact(value, list) and all(_is_exact(item, str) for item in value):
            if any(item not in _ORACLE_REASON_CODES for item in value):
                errors.append("RECORD_TYPE_INVALID")
    if all(_is_exact(raw[field], list) and all(_is_exact(item, str) for item in raw[field]) for field in _SEMANTIC_FIELDS[3:6]):
        complete = set(raw["complete_reason_codes"])
        blocking = set(raw["blocking_reason_codes"])
        review = set(raw["review_reason_codes"])
        if blocking & review or blocking | review != complete:
            errors.append("RECORD_NOT_NORMALIZED")
        if (primary is None) != (not complete) or primary is not None and primary not in complete:
            errors.append("RECORD_NOT_NORMALIZED")
        expected = "BLOCK" if blocking else "REVIEW_REQUIRED" if review else "ELIGIBLE_TO_MERGE_UNDER_POLICY"
        if raw["disposition"] != expected:
            errors.append("RECORD_NOT_NORMALIZED")
    requirement_fields = _SEMANTIC_FIELDS[6:10]
    if all(_is_exact(raw[field], list) and all(_is_exact(item, str) for item in raw[field]) for field in requirement_fields):
        parts = [set(raw[field]) for field in requirement_fields[1:]]
        if set().union(*parts) != set(raw[requirement_fields[0]]) or any(
            left & right for index, left in enumerate(parts) for right in parts[index + 1:]
        ):
            errors.append("RECORD_NOT_NORMALIZED")
    if errors:
        return {"errors": sorted(set(errors)), "classifications": []}
    if raw["decision_digest"] != _independent_decision_digest(raw):
        return {"errors": ["DECISION_DIGEST_NOT_DERIVED"], "classifications": []}
    if raw["policy_record_digest"] != _independent_record_digest(raw):
        return {"errors": ["RECORD_DIGEST_MISMATCH"], "classifications": []}

    errors = []
    if canonical_input is not None:
        if not _is_exact(canonical_input, dict) or not all(_is_exact(key, str) for key in canonical_input):
            errors.append("INPUT_NOT_AN_OBJECT")
        else:
            input_fields = ("task_id", *_BINDING_FIELDS, "policy_version", "evaluator_version", "evaluation_mode")
            if any(raw[field] != canonical_input.get(field) for field in input_fields):
                errors.append("SOURCE_BINDING_MISMATCH")
            if canonical_input.get("policy_record_schema_version") != raw["schema_version"] or canonical_input.get("policy_record_schema_digest") != POLICY_RECORD_SCHEMA_DIGEST:
                errors.append("SCHEMA_BINDING_MISMATCH")
            if canonical_input.get("canonicalization_version") != CANONICALIZATION_VERSION or canonical_input.get("canonicalization_contract_digest") != CANONICALIZATION_CONTRACT_DIGEST:
                errors.append("CANONICALIZATION_BINDING_MISMATCH")
            try:
                input_digest = canonical_digest(canonical_input)
            except (TypeError, ValueError):
                errors.append("INPUT_NOT_CANONICALIZABLE")
            else:
                if set(canonical_input) != _RAW_INPUT_FIELDS or input_digest != raw["input_digest"]:
                    errors.append("INPUT_DIGEST_MISMATCH")
    if universes is not None:
        if not _is_exact(universes, dict):
            errors.append("IDENTIFIER_UNIVERSES_INVALID")
        else:
            for fields, key in (
                (_SEMANTIC_FIELDS[6:10], "requirement_id_universe"),
                (_SEMANTIC_FIELDS[10:13], "evidence_record_id_universe"),
            ):
                universe = universes.get(key)
                if not (_is_exact(universe, list) or _is_exact(universe, tuple)) or any(not _is_exact(item, str) for item in universe):
                    errors.append("IDENTIFIER_UNIVERSES_INVALID")
                elif any(item not in universe for field in fields for item in raw[field]):
                    errors.append("IDENTIFIER_UNIVERSE_MISMATCH")
    return {
        "errors": sorted(set(errors)),
        "classifications": [] if errors else [
            "STRUCTURALLY_VALIDATED", "IDENTITY_RECOMPUTED",
            "SEMANTIC_REPLAY_NOT_PERFORMED",
        ],
    }


_BUILDER_CASES = [
    ("task", "field", "task_id", "other-task"),
    *[
        (f"binding-{field}", "field", field, "sha256:" + "0" * 64)
        for field in _BINDING_FIELDS
    ],
    ("policy", "field", "policy_version", "other-policy"),
    ("evaluator", "field", "evaluator_version", "other-evaluator"),
    ("mode", "field", "evaluation_mode", "SHADOW"),
    ("input-digest", "field", "input_digest", "sha256:" + "0" * 64),
    ("semantic-stale-digest", "field", "primary_reason_code", "AUTHORITY_INVALID"),
    ("input-echo-rehashed", "rehashed", "task_id", "other-task"),
    ("malformed-decision", "malformed", "", None),
]
assert len(_BUILDER_CASES) == 16


@pytest.mark.parametrize(
    "label,kind,field,replacement",
    _BUILDER_CASES,
    ids=[item[0] for item in _BUILDER_CASES],
)
def test_builder_inconsistency_matrix(
    label: str, kind: str, field: str, replacement: object
) -> None:
    policy_input, _core, decision, _record = _outputs(_CASES[0])
    candidate: object = decision
    if kind == "malformed":
        candidate = object()
    else:
        _mutate_frozen(decision, field, replacement)
        if kind == "rehashed":
            identity = {
                name: (
                    getattr(decision, name).value
                    if hasattr(getattr(decision, name), "value")
                    else getattr(decision, name)
                )
                for name in _IDENTITY_FIELDS
            }
            object.__setattr__(decision, "decision_digest", _independent_decision_digest(identity))
    with pytest.raises(RecordConstructionError) as caught:
        build_policy_evaluation_record(policy_input, candidate)  # type: ignore[arg-type]
    assert _is_exact(caught.value, RecordConstructionError)


_TAMPERS = [
    ("shape-wrong-schema", "schema_version", "wrong-schema"),
    ("shape-malformed-top", "task_id", 1),
    *[
        (f"identity-{field}", field, "sha256:" + "f" * 64)
        for field in (
            "task_id", *_BINDING_FIELDS, "policy_version", "evaluator_version",
            "input_digest",
        )
    ],
    ("identity-mode", "evaluation_mode", "SHADOW"),
    ("semantic-disposition", "disposition", "REVIEW_REQUIRED"),
    ("semantic-authority", "decision_authority", "ADVISORY_ONLY"),
    ("semantic-primary", "primary_reason_code", "AUTHORITY_INVALID"),
    *[
        (f"semantic-{field}", field, ["AUTHORITY_INVALID"])
        for field in _SEMANTIC_FIELDS[3:]
    ],
    ("canonical-wrong-container", "complete_reason_codes", ()),
    ("canonical-unsorted", "complete_reason_codes", ["SCOPE_UNCERTAIN", "AUTHORITY_INVALID"]),
    ("canonical-duplicate", "complete_reason_codes", ["AUTHORITY_INVALID", "AUTHORITY_INVALID"]),
    ("canonical-element", "complete_reason_codes", [1]),
    ("partition-overlap", "blocking_reason_codes", ["AUTHORITY_INVALID"]),
    ("partition-incomplete", "review_reason_codes", ["SCOPE_UNCERTAIN"]),
    ("primary-absent", "primary_reason_code", "AUTHORITY_INVALID"),
    ("digest-decision", "decision_digest", "sha256:" + "0" * 64),
    ("digest-record", "policy_record_digest", "sha256:" + "0" * 64),
    ("canonical-wrong-required-element", "required_requirement_ids", [1]),
    ("canonical-wrong-evidence-element", "unexpected_evidence_ids", [1]),
]


@pytest.mark.parametrize("label,field,replacement", _TAMPERS)
def test_complete_tamper_matrix(label: str, field: str, replacement: object) -> None:
    policy_input, candidate = _raw_record(_CASES[0])
    candidate[field] = replacement
    canonical_input = policy_input.to_canonical_payload()
    for result, expected in (
        (
            validate_policy_evaluation_record(candidate),
            _independent_validate_raw(candidate),
        ),
        (
            validate_policy_evaluation_record(candidate, canonical_input=canonical_input),
            _independent_validate_raw(candidate, canonical_input),
        ),
    ):
        assert result == expected, label
        assert result["errors"], label
        assert result["classifications"] == [], label


class _DictSubclass(dict):
    pass


class _CustomMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


class _RecordLike:
    pass


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("missing", "RECORD_FIELD_SET_DRIFT"),
        ("extra", "RECORD_FIELD_SET_DRIFT"),
        ("non-string-key", "RECORD_NOT_AN_OBJECT"),
        ("wrong-schema", "RECORD_TYPE_INVALID"),
    ],
)
def test_raw_shape_errors_are_real_dictionary_mutations(kind: str, expected: str) -> None:
    _policy_input, raw = _raw_record(_CASES[0])
    if kind == "missing":
        raw.pop("task_id")
    elif kind == "extra":
        raw["extra"] = "field"
    elif kind == "non-string-key":
        raw[1] = "mixed"
    else:
        raw["schema_version"] = "wrong-schema"
    result = validate_policy_evaluation_record(raw)
    assert result == _independent_validate_raw(raw)
    assert result["errors"] == [expected]
    assert result["classifications"] == []


@pytest.mark.parametrize(
    "candidate",
    [
        [],
        _DictSubclass(),
        _CustomMapping(),
        _RecordLike(),
        dataclasses.make_dataclass("RecordDataclass", [])(),
    ],
    ids=["list", "dict-subclass", "custom-mapping", "record-like", "dataclass"],
)
def test_only_exact_builtin_dict_is_the_raw_record_representation(candidate: object) -> None:
    result = validate_policy_evaluation_record(candidate)
    assert result == _independent_validate_raw(candidate)
    assert result["errors"] == ["RECORD_NOT_AN_OBJECT"]
    assert result["classifications"] == []


def test_raw_record_and_typed_record_share_the_same_validation_result() -> None:
    policy_input, _core, _decision, record = _outputs(_CASES[0])
    _ignored, raw = _raw_record(_CASES[0])
    universes = _CASES[0]["identifier_universes"]
    typed = validate_policy_evaluation_record(record, policy_input, universes)
    untyped = validate_policy_evaluation_record(raw, policy_input, universes)
    assert typed == untyped
    assert typed["errors"] == []
    assert validate_policy_evaluation_record(
        raw, policy_input.to_canonical_payload(), universes
    ) == _independent_validate_raw(raw, policy_input.to_canonical_payload(), universes)


def test_inner_tamper_with_only_outer_rehash_still_fails_inner_digest() -> None:
    _policy_input, raw = _raw_record(_CASES[0])
    raw["task_id"] = "other-task"
    raw["policy_record_digest"] = _independent_record_digest(raw)
    result = validate_policy_evaluation_record(raw)
    assert result["errors"] == ["DECISION_DIGEST_NOT_DERIVED"]
    assert result == _independent_validate_raw(raw)


def test_structurally_valid_double_rehash_fails_original_input_binding() -> None:
    policy_input, raw = _raw_record(_CASES[0])
    raw["task_id"] = "other-task"
    _independent_rehash(raw)
    assert validate_policy_evaluation_record(raw) == _independent_validate_raw(raw)
    canonical_input = policy_input.to_canonical_payload()
    result = validate_policy_evaluation_record(raw, canonical_input)
    assert result == _independent_validate_raw(raw, canonical_input)
    assert result["errors"] == ["SOURCE_BINDING_MISMATCH"]


def test_mixed_identity_and_digest_material_is_rejected() -> None:
    _first_input, first = _raw_record(_CASES[0])
    _second_input, second = _raw_record(_CASES[1])
    first["decision_digest"] = second["decision_digest"]
    first["policy_record_digest"] = second["policy_record_digest"]
    result = validate_policy_evaluation_record(first)
    assert result == _independent_validate_raw(first)
    assert result["errors"]
    assert result["classifications"] == []


def test_schema_mutation_with_actual_outer_rehash_remains_invalid() -> None:
    _policy_input, raw = _raw_record(_CASES[0])
    raw["schema_version"] = "changegate.policy-evaluation-record.v2"
    raw["policy_record_digest"] = _independent_record_digest(raw)
    result = validate_policy_evaluation_record(raw)
    assert result == _independent_validate_raw(raw)
    assert result["errors"] == ["RECORD_TYPE_INVALID"]


def test_raw_canonical_input_checks_all_contract_bindings() -> None:
    policy_input, raw = _raw_record(_CASES[0])
    canonical_input = policy_input.to_canonical_payload()
    assert validate_policy_evaluation_record(raw, canonical_input)["errors"] == []

    schema_drift = dict(canonical_input)
    schema_drift["policy_record_schema_digest"] = "sha256:" + "0" * 64
    assert "SCHEMA_BINDING_MISMATCH" in validate_policy_evaluation_record(
        raw, schema_drift
    )["errors"]

    canonicalization_drift = dict(canonical_input)
    canonicalization_drift["canonicalization_version"] = "wrong-version"
    assert "CANONICALIZATION_BINDING_MISMATCH" in validate_policy_evaluation_record(
        raw, canonicalization_drift
    )["errors"]

    extra_field = {**canonical_input, "extra": "field"}
    assert "INPUT_DIGEST_MISMATCH" in validate_policy_evaluation_record(
        raw, extra_field
    )["errors"]

    non_string_key = {**canonical_input, 1: "field"}
    assert validate_policy_evaluation_record(raw, non_string_key)["errors"] == [
        "INPUT_NOT_AN_OBJECT"
    ]


def _malformed_raw(kind: str) -> object:
    _policy_input, raw = _raw_record(_CASES[0])
    if kind == "enum":
        raw["disposition"] = "UNKNOWN"
    elif kind == "version":
        raw["schema_version"] = 1
    elif kind == "digest":
        raw["decision_digest"] = "SHA256:" + "0" * 64
    elif kind == "tuple":
        raw["complete_reason_codes"] = ()
    elif kind == "unsorted":
        raw["complete_reason_codes"] = ["SCOPE_UNCERTAIN", "AUTHORITY_INVALID"]
    elif kind == "duplicate":
        raw["complete_reason_codes"] = ["AUTHORITY_INVALID", "AUTHORITY_INVALID"]
    elif kind == "element":
        raw["complete_reason_codes"] = [1]
    elif kind == "unhashable-dict":
        raw["complete_reason_codes"] = [{}]
    elif kind == "unhashable-list":
        raw["complete_reason_codes"] = [[]]
    elif kind == "identity":
        raw["task_id"] = ""
    else:
        raise AssertionError(kind)
    return raw


_TOTALITY_TOP_LEVEL = [
    None, True, 1, 1.0, "x", b"x", [], (), set(), {}, {1: "mixed"}, object(),
]
_TOTALITY_RAW_KINDS = [
    "enum", "version", "digest", "tuple", "unsorted", "duplicate", "element",
    "unhashable-dict", "unhashable-list", "identity",
]


@pytest.mark.parametrize(
    "malformed",
    [*_TOTALITY_TOP_LEVEL, *[_malformed_raw(kind) for kind in _TOTALITY_RAW_KINDS]],
)
def test_validator_totality_matrix(malformed: object) -> None:
    try:
        result = validate_policy_evaluation_record(malformed)
    except (TypeError, KeyError, AttributeError, ValueError, AssertionError) as exc:
        pytest.fail(f"raw validator exception: {type(exc).__name__}")
    assert result["errors"]
    assert result["classifications"] == []


@pytest.mark.parametrize(
    "field,universe_key,partition",
    [
        ("required_requirement_ids", "requirement_id_universe", "satisfied_requirement_ids"),
        ("satisfied_requirement_ids", "requirement_id_universe", "satisfied_requirement_ids"),
        ("invalid_requirement_ids", "requirement_id_universe", "invalid_requirement_ids"),
        ("missing_requirement_ids", "requirement_id_universe", "missing_requirement_ids"),
        ("rejected_evidence_ids", "evidence_record_id_universe", None),
        ("invalid_provenance_evidence_ids", "evidence_record_id_universe", None),
        ("unexpected_evidence_ids", "evidence_record_id_universe", None),
    ],
)
def test_each_accounting_category_has_an_independent_universe_negative(
    field: str, universe_key: str, partition: str | None
) -> None:
    policy_input, raw = _raw_record(_CASES[0])
    if field in _SEMANTIC_FIELDS[6:10]:
        raw["required_requirement_ids"] = ["unknown-id"]
        for name in (
            "satisfied_requirement_ids", "invalid_requirement_ids", "missing_requirement_ids"
        ):
            raw[name] = ["unknown-id"] if name == partition else []
    else:
        raw[field] = ["unknown-id"]
    canonical_input = policy_input.to_canonical_payload()
    for accounting_field in _SEMANTIC_FIELDS[6:13]:
        canonical_input["facts"][accounting_field] = list(raw[accounting_field])
    raw["input_digest"] = canonical_digest(canonical_input)
    _independent_rehash(raw)
    universes = {
        "requirement_id_universe": [],
        "evidence_record_id_universe": [],
    }
    result = validate_policy_evaluation_record(
        raw, canonical_input=canonical_input, identifier_universes=universes
    )
    assert result == _independent_validate_raw(raw, canonical_input, universes)
    assert result["errors"] == ["IDENTIFIER_UNIVERSE_MISMATCH"]
    assert universe_key in universes


@pytest.mark.parametrize("case", _CASES, ids=lambda item: item["case_id"])
def test_universe_and_determinism_matrices(case: dict) -> None:
    policy_input, core, decision, record = _outputs(case)
    universes = case["identifier_universes"]
    before = json.dumps(universes, sort_keys=True)
    assert validate_policy_evaluation_record(record, policy_input, universes)["errors"] == []
    assert json.dumps(universes, sort_keys=True) == before
    assert validate_policy_evaluation_record(record)["errors"] == []
    assert finalize_decision(policy_input, core) == decision
    assert build_policy_evaluation_record(policy_input, decision) == record
    assert evaluate_merge_eligibility(policy_input) == (decision, record)
    reversed_input = MergeEligibilityPolicyInput.from_json_dict(
        dict(reversed(list({**case["policy_input_bindings"], "facts": case["policy_input_facts"], "policy_record_schema_version": POLICY_RECORD_SCHEMA_VERSION, "policy_record_schema_digest": POLICY_RECORD_SCHEMA_DIGEST, "canonicalization_version": CANONICALIZATION_VERSION, "canonicalization_contract_digest": CANONICALIZATION_CONTRACT_DIGEST}.items())))
    )
    assert evaluate_merge_eligibility(reversed_input) == (decision, record)


@pytest.mark.parametrize("case", _CASES, ids=lambda item: item["case_id"])
def test_equivalent_distinct_core_reconstruction_is_byte_identical(case: dict) -> None:
    policy_input, core, decision, record = _outputs(case)
    rebuilt_core = type(core)(
        **{field.name: getattr(core, field.name) for field in dataclasses.fields(core)}
    )
    assert rebuilt_core is not core
    assert rebuilt_core == core
    rebuilt_decision = finalize_decision(policy_input, rebuilt_core)
    rebuilt_record = build_policy_evaluation_record(policy_input, rebuilt_decision)
    assert rebuilt_decision == decision
    assert rebuilt_record == record
    original_identity = {
        field: (
            list(value) if type(value) is tuple else value.value if hasattr(value, "value") else value
        )
        for field in _IDENTITY_FIELDS
        for value in (getattr(decision, field),)
    }
    rebuilt_identity = {
        field: (
            list(value) if type(value) is tuple else value.value if hasattr(value, "value") else value
        )
        for field in _IDENTITY_FIELDS
        for value in (getattr(rebuilt_decision, field),)
    }
    assert canonical_json_bytes(
        {"kind": "changegate.merge-eligibility-decision.test-oracle.v1", **original_identity}
    ) == canonical_json_bytes(
        {"kind": "changegate.merge-eligibility-decision.test-oracle.v1", **rebuilt_identity}
    )
    assert canonical_json_bytes(rebuilt_record.to_canonical_payload()) == canonical_json_bytes(
        record.to_canonical_payload()
    )

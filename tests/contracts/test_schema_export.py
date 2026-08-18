import json
from pathlib import Path

import pytest
from jsonschema import FormatChecker
from jsonschema.validators import Draft202012Validator
from pydantic import ValidationError

from financial_agent.contracts.answer import EvaluationApiResponse
from financial_agent.contracts.evidence import ClaimSupport, EvidenceRecord
from financial_agent.contracts.request import RequestContext
from financial_agent.contracts.schema_export import check_schemas, export_schemas

EXPECTED_SCHEMA_FILES = {
    "request-context.schema.json",
    "query-plan.schema.json",
    "execution-graph.schema.json",
    "tool-result.schema.json",
    "source-record.schema.json",
    "evidence-record.schema.json",
    "calculation-record.schema.json",
    "atomic-claim.schema.json",
    "claim-support.schema.json",
    "evidence-bundle.schema.json",
    "verification-report.schema.json",
    "answer-plan.schema.json",
    "released-answer.schema.json",
    "evaluation-api-response.schema.json",
}


def test_schema_export_is_complete_and_current(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    assert {path.name for path in tmp_path.iterdir()} == EXPECTED_SCHEMA_FILES
    for path in tmp_path.iterdir():
        Draft202012Validator.check_schema(json.loads(path.read_text("utf-8")))


def test_committed_schemas_match_fresh_export(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    committed = Path("schemas/contracts/v1")
    for expected in EXPECTED_SCHEMA_FILES:
        assert (tmp_path / expected).read_bytes() == (committed / expected).read_bytes()


def test_schema_freshness_accepts_exact_export(tmp_path: Path) -> None:
    export_schemas(tmp_path)

    check_schemas(tmp_path)


def test_schema_freshness_rejects_modified_file(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    target = tmp_path / "query-plan.schema.json"
    target.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError):
        check_schemas(tmp_path)


def test_schema_freshness_rejects_missing_file(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    (tmp_path / "query-plan.schema.json").unlink()

    with pytest.raises(ValueError):
        check_schemas(tmp_path)


def test_schema_freshness_rejects_extra_file(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    (tmp_path / "extra.schema.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError):
        check_schemas(tmp_path)


def test_schema_and_runtime_both_reject_noncanonical_tagged_decimal(
    load_fixture, dump_json
) -> None:
    payload = load_fixture("evidence_record.json")
    payload["value_or_object_id"] = {"type": "decimal", "value": "1.0"}
    schema = EvidenceRecord.model_json_schema(mode="validation")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    assert list(validator.iter_errors(payload))
    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate_json(dump_json(payload))


def test_schema_accepts_but_runtime_rejects_support_target_mismatch(
    dump_json,
) -> None:
    payload = {
        "claim_id": "claim-1",
        "support_kind": "calculation",
        "evidence_id": "evidence-1",
        "calculation_id": None,
        "support_role": "value",
        "ordinal": 0,
    }
    schema = ClaimSupport.model_json_schema(mode="validation")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    assert not list(validator.iter_errors(payload))
    with pytest.raises(ValidationError):
        ClaimSupport.model_validate_json(dump_json(payload))


def test_schema_accepts_but_runtime_rejects_wrong_cutoff(
    load_fixture, dump_json
) -> None:
    payload = load_fixture("request_context.json")
    payload["cutoff_date"] = "2026-07-12"
    schema = RequestContext.model_json_schema(mode="validation")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    assert not list(validator.iter_errors(payload))
    with pytest.raises(ValidationError):
        RequestContext.model_validate_json(dump_json(payload))


def test_evaluation_response_schema_keeps_exact_five_string_fields() -> None:
    schema = EvaluationApiResponse.model_json_schema(mode="validation")
    expected = {
        "question_id",
        "question",
        "retrieved_context",
        "think_trace",
        "answer",
    }

    assert set(schema["properties"]) == expected
    assert set(schema["required"]) == expected
    assert all(
        definition["type"] == "string"
        for definition in schema["properties"].values()
    )
    assert schema["additionalProperties"] is False

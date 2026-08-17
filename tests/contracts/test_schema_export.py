import json
from pathlib import Path

from jsonschema.validators import Draft202012Validator

from financial_agent.contracts.schema_export import export_schemas

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

import json

import pytest
from pydantic import ValidationError

from financial_agent.contracts.enums import ReferenceMentionType, ReferenceTargetKind
from financial_agent.contracts.query import QueryPlan


def test_query_plan_binds_ellipsis_to_preceding_output(load_fixture_json) -> None:
    plan = QueryPlan.model_validate_json(load_fixture_json("query_plan.json"))
    binding = plan.resolved_references[0]
    assert binding.mention_type is ReferenceMentionType.ELLIPSIS
    assert binding.target_kind is ReferenceTargetKind.BINDING
    assert binding.target_id == "s1.top5_products"
    assert plan.filters[0].value.type == "string"


def test_query_plan_rejects_untagged_filter_value(load_fixture, dump_json) -> None:
    payload = load_fixture("query_plan.json")
    payload["filters"][0]["value"] = "security-syn-company"

    with pytest.raises(ValidationError):
        QueryPlan.model_validate_json(dump_json(payload))


def test_query_plan_rejects_cycle(load_fixture, dump_json) -> None:
    payload = load_fixture("query_plan.json")
    payload["dependency_edges"].append(
        {"upstream_subtask_id": "q2", "downstream_subtask_id": "q1"}
    )
    with pytest.raises(ValidationError):
        QueryPlan.model_validate_json(dump_json(payload))


def test_query_plan_contains_no_executable_query_fields() -> None:
    schema_text = json.dumps(QueryPlan.model_json_schema())
    for forbidden in ("sql", "sparql", "python_expression", "formula_text"):
        assert forbidden not in schema_text.lower()

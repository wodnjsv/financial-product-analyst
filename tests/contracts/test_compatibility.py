import pytest

from financial_agent.contracts.compatibility import (
    validate_execution_graph_compatibility,
    validate_tool_result_compatibility,
)
from financial_agent.contracts.execution import ExecutionGraph, ToolResult
from financial_agent.contracts.query import QueryPlan


def test_query_plan_and_execution_graph_are_compatible(load_fixture_json) -> None:
    plan = QueryPlan.model_validate_json(load_fixture_json("query_plan.json"))
    graph = ExecutionGraph.model_validate_json(
        load_fixture_json("execution_graph.json")
    )

    validate_execution_graph_compatibility(plan, graph)


def test_binding_spec_order_does_not_change_compatibility(
    load_fixture, load_fixture_json, dump_json
) -> None:
    plan = QueryPlan.model_validate_json(load_fixture_json("query_plan.json"))
    payload = load_fixture("execution_graph.json")
    payload["binding_specs"].reverse()
    graph = ExecutionGraph.model_validate_json(dump_json(payload))

    validate_execution_graph_compatibility(plan, graph)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(run_id="other-run"),
        lambda payload: payload["binding_specs"][0].update(
            value_type="wrong-type"
        ),
        lambda payload: payload["tasks"][3].update(
            subtask_id="missing-subtask"
        ),
        lambda payload: payload["tasks"][0].update(
            operation_id="op-rank-return"
        ),
        lambda payload: payload["tasks"][0].update(
            operation_id="missing-operation"
        ),
        lambda payload: payload["tasks"][0].update(
            capability="vector_search"
        ),
    ],
)
def test_query_plan_and_execution_graph_reject_mismatches(
    load_fixture, load_fixture_json, dump_json, mutation
) -> None:
    plan = QueryPlan.model_validate_json(load_fixture_json("query_plan.json"))
    payload = load_fixture("execution_graph.json")
    mutation(payload)
    graph = ExecutionGraph.model_validate_json(dump_json(payload))

    with pytest.raises(ValueError):
        validate_execution_graph_compatibility(plan, graph)


def test_execution_graph_and_tool_result_are_compatible(load_fixture_json) -> None:
    graph = ExecutionGraph.model_validate_json(
        load_fixture_json("execution_graph.json")
    )
    result = ToolResult.model_validate_json(load_fixture_json("tool_result.json"))

    validate_tool_result_compatibility(graph, result)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(run_id="other-run"),
        lambda payload: payload.update(task_id="missing-task"),
        lambda payload: payload.update(result_type="scalar"),
        lambda payload: payload["binding_values"][0].update(
            binding_name="s1.company"
        ),
        lambda payload: payload["binding_values"][0].update(
            value_type="wrong-type"
        ),
        lambda payload: payload["binding_values"][0].update(
            value={"type": "string", "value": "product-syn-etf-a"}
        ),
    ],
)
def test_execution_graph_and_tool_result_reject_mismatches(
    load_fixture, load_fixture_json, dump_json, mutation
) -> None:
    graph = ExecutionGraph.model_validate_json(
        load_fixture_json("execution_graph.json")
    )
    payload = load_fixture("tool_result.json")
    mutation(payload)
    result = ToolResult.model_validate_json(dump_json(payload))

    with pytest.raises(ValueError):
        validate_tool_result_compatibility(graph, result)


def test_single_binding_rejects_tuple_value(
    load_fixture, load_fixture_json, dump_json
) -> None:
    graph = ExecutionGraph.model_validate_json(
        load_fixture_json("execution_graph.json")
    )
    payload = load_fixture("tool_result.json")
    payload.update(task_id="t1", result_type="entity_ref", result_rows=[])
    payload["binding_values"] = [
        {
            "binding_name": "s1.company",
            "value_type": "entity_ref",
            "value": {
                "type": "tuple",
                "items": [
                    {"type": "string", "value": "security-syn-company"}
                ],
            },
        }
    ]
    result = ToolResult.model_validate_json(dump_json(payload))

    with pytest.raises(ValueError):
        validate_tool_result_compatibility(graph, result)


def test_many_binding_rejects_scalar_value(
    load_fixture, load_fixture_json, dump_json
) -> None:
    graph = ExecutionGraph.model_validate_json(
        load_fixture_json("execution_graph.json")
    )
    payload = load_fixture("tool_result.json")
    payload["binding_values"][0]["value"] = {
        "type": "string",
        "value": "product-syn-etf-a",
    }
    result = ToolResult.model_validate_json(dump_json(payload))

    with pytest.raises(ValueError, match="many binding must contain a tuple"):
        validate_tool_result_compatibility(graph, result)

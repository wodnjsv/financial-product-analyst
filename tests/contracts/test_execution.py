from copy import deepcopy

import pytest
from pydantic import ValidationError

from financial_agent.contracts.enums import ToolStatus
from financial_agent.contracts.execution import ExecutionGraph, ToolResult
from financial_agent.contracts.values import TupleValue


def test_execution_graph_preserves_dependencies_and_budget(load_fixture_json) -> None:
    graph = ExecutionGraph.model_validate_json(
        load_fixture_json("execution_graph.json")
    )

    assert graph.total_budget_ms == 20_000
    assert graph.tasks[-1].depends_on == ("t3",)
    assert isinstance(graph.tasks, tuple)
    assert graph.tasks[0].literal_inputs[0].value.type == "string"
    assert graph.tasks[2].literal_inputs[0].value.type == "integer"


@pytest.mark.parametrize(
    ("task_index", "old_value"),
    [(0, "합성전자"), (2, 5)],
)
def test_execution_graph_rejects_untagged_literal_inputs(
    load_fixture, dump_json, task_index: int, old_value: object
) -> None:
    payload = load_fixture("execution_graph.json")
    payload["tasks"][task_index]["literal_inputs"][0]["value"] = old_value

    with pytest.raises(ValidationError):
        ExecutionGraph.model_validate_json(dump_json(payload))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["tasks"][1].update(
            binding_inputs=["missing.binding"]
        ),
        lambda payload: payload["tasks"][1].update(
            produces_bindings=["missing.binding"]
        ),
        lambda payload: payload["tasks"][1].update(
            binding_inputs=["s1.company"],
            produces_bindings=["s1.company"],
        ),
        lambda payload: payload["tasks"][1].update(depends_on=[]),
        lambda payload: payload["tasks"][2].update(
            produces_bindings=["s1.company", "s1.top5_products"]
        ),
        lambda payload: payload["tasks"][0].update(produces_bindings=[]),
        lambda payload: payload["binding_specs"].append(
            deepcopy(payload["binding_specs"][0])
        ),
        lambda payload: payload["tasks"][0].update(subtask_id="q2"),
        lambda payload: payload.update(critical_path=["t1", "t3"]),
        lambda payload: payload.update(critical_path=["t1", "t2", "t2"]),
        lambda payload: payload["tasks"][3].update(budget_ms=7_001),
    ],
)
def test_execution_graph_rejects_binding_and_path_inconsistencies(
    load_fixture, dump_json, mutation
) -> None:
    payload = load_fixture("execution_graph.json")
    mutation(payload)

    with pytest.raises(ValidationError):
        ExecutionGraph.model_validate_json(dump_json(payload))


def test_execution_graph_rejects_task_beyond_total_budget(
    load_fixture, dump_json
) -> None:
    payload = load_fixture("execution_graph.json")
    payload["tasks"][0]["budget_ms"] = 20_001

    with pytest.raises(ValidationError):
        ExecutionGraph.model_validate_json(dump_json(payload))


@pytest.mark.parametrize(
    ("mutation", "description"),
    [
        (
            lambda payload: payload["tasks"].append(deepcopy(payload["tasks"][0])),
            "duplicate task IDs",
        ),
        (
            lambda payload: payload["tasks"][1].update(depends_on=["missing-task"]),
            "unknown dependencies",
        ),
        (
            lambda payload: payload["tasks"][0].update(depends_on=["t1"]),
            "self dependencies",
        ),
        (
            lambda payload: payload["tasks"][0].update(depends_on=["t3"]),
            "cycles",
        ),
        (
            lambda payload: payload.update(critical_path=["missing-task"]),
            "unknown critical path IDs",
        ),
        (
            lambda payload: payload.update(total_budget_ms=55_001),
            "total budget above the hard deadline",
        ),
        (
            lambda payload: payload["tasks"][0].update(budget_ms=0),
            "zero task budgets",
        ),
    ],
)
def test_execution_graph_rejects_invalid_structure(
    load_fixture, dump_json, mutation, description: str
) -> None:
    payload = load_fixture("execution_graph.json")
    mutation(payload)

    with pytest.raises(ValidationError):
        ExecutionGraph.model_validate_json(dump_json(payload))


def test_tool_result_empty_is_a_valid_non_error_status(
    load_fixture, dump_json
) -> None:
    payload = load_fixture("tool_result.json") | {
        "status": "empty",
        "result_rows": [],
        "binding_values": [],
    }

    result = ToolResult.model_validate_json(dump_json(payload))
    assert result.status is ToolStatus.EMPTY


def test_tool_result_preserves_tagged_field_and_binding_values(
    load_fixture_json,
) -> None:
    result = ToolResult.model_validate_json(load_fixture_json("tool_result.json"))

    assert result.result_rows[0].fields[1].value.type == "decimal"
    assert isinstance(result.binding_values[0].value, TupleValue)


@pytest.mark.parametrize(
    ("path", "old_value"),
    [
        (("result_rows", 0, "fields", 0, "value"), "product-syn-etf-a"),
        (("result_rows", 0, "fields", 1, "value"), 125000000),
        (("binding_values", 0, "value"), ["product-syn-etf-a"]),
    ],
)
def test_tool_result_rejects_untagged_values(
    load_fixture, dump_json, path: tuple[object, ...], old_value: object
) -> None:
    payload = load_fixture("tool_result.json")
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = old_value

    with pytest.raises(ValidationError):
        ToolResult.model_validate_json(dump_json(payload))


@pytest.mark.parametrize(
    "status",
    [
        "empty",
        "unsupported",
        "invalid_input",
        "timeout",
        "transient_error",
        "permanent_error",
    ],
)
def test_non_success_tool_result_rejects_success_payload(
    load_fixture, dump_json, status: str
) -> None:
    payload = load_fixture("tool_result.json")
    payload["status"] = status

    with pytest.raises(ValidationError):
        ToolResult.model_validate_json(dump_json(payload))


@pytest.mark.parametrize(
    ("mutation", "description"),
    [
        (
            lambda payload: payload["result_rows"][0]["fields"].append(
                deepcopy(payload["result_rows"][0]["fields"][0])
            ),
            "duplicate field IDs in a result row",
        ),
        (
            lambda payload: payload["binding_values"].append(
                deepcopy(payload["binding_values"][0])
            ),
            "duplicate binding names",
        ),
        (
            lambda payload: payload.update(latency_ms=-1),
            "negative latency",
        ),
    ],
)
def test_tool_result_rejects_invalid_values(
    load_fixture, dump_json, mutation, description: str
) -> None:
    payload = load_fixture("tool_result.json")
    mutation(payload)

    with pytest.raises(ValidationError):
        ToolResult.model_validate_json(dump_json(payload))

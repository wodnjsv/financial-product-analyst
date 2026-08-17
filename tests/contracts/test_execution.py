from copy import deepcopy

import pytest
from pydantic import ValidationError

from financial_agent.contracts.enums import ToolStatus
from financial_agent.contracts.execution import ExecutionGraph, ToolResult


def test_execution_graph_preserves_dependencies_and_budget(load_fixture) -> None:
    graph = ExecutionGraph.model_validate(load_fixture("execution_graph.json"))

    assert graph.total_budget_ms == 20_000
    assert graph.tasks[-1].depends_on == ("t2",)
    assert isinstance(graph.tasks, tuple)


def test_execution_graph_rejects_task_beyond_total_budget(load_fixture) -> None:
    payload = load_fixture("execution_graph.json")
    payload["tasks"][0]["budget_ms"] = 20_001

    with pytest.raises(ValidationError):
        ExecutionGraph.model_validate(payload)


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
    load_fixture, mutation, description: str
) -> None:
    payload = load_fixture("execution_graph.json")
    mutation(payload)

    with pytest.raises(ValidationError):
        ExecutionGraph.model_validate(payload)


def test_tool_result_empty_is_a_valid_non_error_status(load_fixture) -> None:
    payload = load_fixture("tool_result.json") | {
        "status": "empty",
        "result_rows": [],
        "binding_values": [],
    }

    assert ToolResult.model_validate(payload).status is ToolStatus.EMPTY


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
    load_fixture, mutation, description: str
) -> None:
    payload = load_fixture("tool_result.json")
    mutation(payload)

    with pytest.raises(ValidationError):
        ToolResult.model_validate(payload)

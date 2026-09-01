from pathlib import Path

import pytest

from financial_agent.contracts.enums import Capability, ResultType, ToolStatus
from financial_agent.contracts.execution import BindingValue
from financial_agent.contracts.values import encode_contract_value
from financial_agent.orchestration.executors import (
    BindingTypeInput,
    ExecutorRegistry,
    TaskExecutionInput,
    build_tool_result,
)
from financial_agent.orchestration.graph import ExecutionGraphCompiler
from financial_agent.orchestration.validation import ToolResultContractError, validate_tool_result
from financial_agent.planning.registry import load_planning_registry

from .test_service import RecordingExecutor, compilation


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def task_request() -> TaskExecutionInput:
    compiled = compilation()
    graph = ExecutionGraphCompiler(load_planning_registry(PROJECT_ROOT)).compile(compiled)
    assert compiled.query_plan is not None
    return TaskExecutionInput(
        request_key=graph.request_key,
        run_id=graph.run_id,
        dataset_version=graph.dataset_version,
        cutoff_date=graph.cutoff_date,
        created_at=graph.created_at,
        task=graph.tasks[0],
        query_plan=compiled.query_plan,
        dependency_results=(),
        binding_values=(),
        binding_types=(),
    )


def test_execution_input_rejects_a_plan_from_another_request() -> None:
    """Catches an executor receiving semantic scope from a stale plan."""
    request = task_request()
    mismatched = request.query_plan.model_copy(update={"request_key": "b" * 64})

    with pytest.raises(ValueError, match="execution input pins must match"):
        request.model_copy(update={"query_plan": mismatched}).model_validate(
            request.model_copy(update={"query_plan": mismatched}).model_dump()
        )


def test_binding_type_input_is_immutable_and_exact() -> None:
    item = BindingTypeInput(binding_name="binding:one", value_type="products")

    with pytest.raises(Exception):
        item.value_type = "changed"


def test_executor_registry_rejects_duplicate_capabilities() -> None:
    """Catches nondeterministic executor selection for one capability."""
    executor = RecordingExecutor()
    with pytest.raises(ValueError, match="duplicate executor"):
        ExecutorRegistry(
            (
                (Capability.RDB_LOOKUP, executor),
                (Capability.RDB_LOOKUP, executor),
            )
        )


def test_executor_registry_rejects_a_missing_required_capability() -> None:
    registry = ExecutorRegistry(((Capability.RDB_LOOKUP, RecordingExecutor()),))

    with pytest.raises(ValueError, match="ranking"):
        registry.require({Capability.RDB_LOOKUP, Capability.RANKING})


def test_result_validator_rejects_wrong_task_and_hash() -> None:
    """Catches a stale or tampered ToolResult entering downstream bindings."""
    request = task_request()
    valid = build_tool_result(
        request,
        status=ToolStatus.SUCCESS,
        evidence_refs=("evidence-1",),
        latency_ms=1,
    )
    wrong_task = valid.model_copy(update={"task_id": "another-task"})
    with pytest.raises(ToolResultContractError, match="TOOL_RESULT_TASK_MISMATCH"):
        validate_tool_result(request, wrong_task)

    wrong_hash = valid.model_copy(update={"result_hash": "0" * 64})
    with pytest.raises(ToolResultContractError, match="TOOL_RESULT_HASH_MISMATCH"):
        validate_tool_result(request, wrong_hash)


def test_result_validator_rejects_wrong_pin_type_and_binding_shape() -> None:
    """Catches semantically incompatible output being published downstream."""
    request = task_request()
    valid = build_tool_result(
        request,
        status=ToolStatus.SUCCESS,
        evidence_refs=("evidence-1",),
        latency_ms=1,
    )
    wrong_pin = valid.model_copy(update={"dataset_version": "dataset-v2"})
    with pytest.raises(ToolResultContractError, match="TOOL_RESULT_PIN_MISMATCH"):
        validate_tool_result(request, wrong_pin)

    wrong_type = valid.model_copy(update={"result_type": ResultType.SCALAR})
    with pytest.raises(ToolResultContractError, match="TOOL_RESULT_TYPE_MISMATCH"):
        validate_tool_result(request, wrong_type)

    extra_binding = build_tool_result(
        request,
        status=ToolStatus.SUCCESS,
        binding_values=(
            BindingValue(
                binding_name="binding:unexpected",
                value_type="products",
                value=encode_contract_value(("product-1",)),
            ),
        ),
        evidence_refs=("evidence-1",),
        latency_ms=1,
    )
    with pytest.raises(ToolResultContractError, match="TOOL_RESULT_BINDING_MISMATCH"):
        validate_tool_result(request, extra_binding)


def test_success_result_requires_evidence_when_task_declares_evidence_fields() -> None:
    """Catches factual success without any evidence reference."""
    request = task_request()
    no_evidence = build_tool_result(
        request,
        status=ToolStatus.SUCCESS,
        evidence_refs=(),
        latency_ms=1,
    )

    with pytest.raises(ToolResultContractError, match="TOOL_RESULT_EVIDENCE_REQUIRED"):
        validate_tool_result(request, no_evidence)

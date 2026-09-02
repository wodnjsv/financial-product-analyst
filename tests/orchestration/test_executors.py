from pathlib import Path

import pytest

from financial_agent.contracts.enums import Capability, ResultType, ToolStatus
from financial_agent.contracts.execution import (
    BindingTypeInput,
    BindingValue,
    ExecutionTask,
    ResultRow,
)
from financial_agent.contracts.values import decode_contract_value, encode_contract_value
from financial_agent.orchestration.executors import (
    BindingTypeInput,
    ExecutorRegistry,
    SqlCapabilityExecutor,
    TaskExecutionInput,
    build_tool_result,
    expected_result_hash,
)
from financial_agent.orchestration.semantic_execution import (
    SemanticSqlTaskExecutionInput,
    SemanticToolTaskExecutionInput,
)
from financial_agent.orchestration.semantic_graph import SemanticExecutionGraphCompiler
from financial_agent.orchestration.graph import ExecutionGraphCompiler
from financial_agent.orchestration.validation import ToolResultContractError, validate_tool_result
from financial_agent.planning.registry import load_planning_registry
from financial_agent.sql.result_mapping import MappedSqlResult

from .test_service import RecordingExecutor, compilation
from .test_semantic_graph import (
    SQL_COMPILER,
    sql_compilation,
    sql_dependency_compilation,
    sql_request,
    tool_compilation,
    tool_dependency_compilation,
)


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


@pytest.mark.asyncio
async def test_sql_capability_executor_accepts_only_semantic_sql_and_calls_runner_once() -> None:
    class Runner:
        def __init__(self, mapped=None):
            self.calls = []
            self.mapped = mapped or MappedSqlResult(
                result_rows=(), evidence_refs=(), exclusions=(), warnings=()
            )

        async def execute(self, request, logical_plan, *, readiness_facts=None):
            self.calls.append((request, logical_plan, readiness_facts))
            return self.mapped

    semantic = sql_compilation()
    compiled = sql_request(semantic)
    graph_result = SemanticExecutionGraphCompiler(
        load_planning_registry(PROJECT_ROOT),
        compiled_request_provider=lambda *_: compiled,
    ).compile(semantic)
    graph = graph_result.graph
    assert semantic.logical_query_plan is not None
    request = SemanticSqlTaskExecutionInput(
        request_key=graph.request_key,
        run_id=graph.run_id,
        dataset_version=graph.dataset_version,
        cutoff_date=graph.cutoff_date,
        created_at=graph.created_at,
        task=graph.tasks[0],
        logical_query_plan=semantic.logical_query_plan,
        dependency_results=(),
        binding_values=(),
        binding_types=(),
        compiled_request=compiled,
    )
    runner = Runner()
    executor = SqlCapabilityExecutor(runner)

    result = await executor.execute(request)

    assert result.status is ToolStatus.EMPTY
    assert len(runner.calls) == 1
    assert runner.calls[0][0] == compiled
    assert runner.calls[0][1] == semantic.logical_query_plan

    tampered = request.model_copy(
        update={"task": request.task.model_copy(update={"subtask_id": "foreign-frame"})}
    )
    with pytest.raises(ValueError, match="SEMANTIC_EXECUTION_TASK_OWNERSHIP_MISMATCH"):
        await executor.execute(tampered)
    assert len(runner.calls) == 1

    with pytest.raises(ValueError, match="SEMANTIC_SQL_REQUEST_REQUIRED"):
        await executor.execute(task_request())

    tool = tool_compilation()
    tool_graph = SemanticExecutionGraphCompiler(
        load_planning_registry(PROJECT_ROOT),
        compiled_request_provider=lambda *_: None,
    ).compile(tool).graph
    assert tool.logical_query_plan is not None
    tool_request = SemanticToolTaskExecutionInput(
        request_key=tool_graph.request_key,
        run_id=tool_graph.run_id,
        dataset_version=tool_graph.dataset_version,
        cutoff_date=tool_graph.cutoff_date,
        created_at=tool_graph.created_at,
        task=tool_graph.tasks[0],
        logical_query_plan=tool.logical_query_plan,
        dependency_results=(),
        binding_values=(),
        binding_types=(),
    )
    with pytest.raises(ValueError, match="SEMANTIC_SQL_REQUEST_REQUIRED"):
        await executor.execute(tool_request)

    dependent = sql_dependency_compilation()
    dependent_plan = dependent.logical_query_plan
    assert dependent_plan is not None
    logical_producer = dependent_plan.tasks[0]
    compiled_producer = SQL_COMPILER.compile_task(
        dependent_plan, logical_producer.task_id
    ).request
    assert compiled_producer is not None
    semantic_task = ExecutionTask(
        task_id=f"semantic-execution:{logical_producer.task_id}",
        subtask_id=logical_producer.frame_id,
        capability=Capability.RDB_LOOKUP,
        operation_id=logical_producer.task_id,
        produces_bindings=("result-set-1",),
        expected_output_type=ResultType.ROW_SET,
        required_evidence_fields=logical_producer.evidence_requirements,
        budget_ms=5_500,
    )
    binding_type = BindingTypeInput(
        binding_name="result-set-1", value_type="semantic-result:many"
    )
    producer_input = SemanticSqlTaskExecutionInput(
        request_key=dependent_plan.request_key,
        run_id=dependent_plan.run_id,
        dataset_version=dependent_plan.dataset_version,
        cutoff_date=dependent_plan.cutoff_date,
        created_at=dependent_plan.created_at,
        task=semantic_task,
        logical_query_plan=dependent_plan,
        dependency_results=(),
        binding_values=(),
        binding_types=(binding_type,),
        compiled_request=compiled_producer,
    )
    mapped = MappedSqlResult(
        result_rows=(ResultRow(row_id="row-1", entity_ids=("product-1",), fields=()),),
        evidence_refs=("evidence-1",),
        exclusions=(),
        warnings=(),
    )
    producer_executor = SqlCapabilityExecutor(Runner(mapped))

    producer_result = await producer_executor.execute(producer_input)

    assert producer_result.status is ToolStatus.SUCCESS
    assert producer_result.result_rows == mapped.result_rows
    assert producer_result.binding_values[0].binding_name == "result-set-1"
    assert producer_result.binding_values[0].value_type == "semantic-result:many"
    assert decode_contract_value(producer_result.binding_values[0].value) == (
        "product-1",
    )


def test_semantic_dependency_rejects_forged_upstream_contract_and_payload_shape() -> None:
    compilation = tool_dependency_compilation()
    bundle = SemanticExecutionGraphCompiler(
        load_planning_registry(PROJECT_ROOT),
        compiled_request_provider=lambda *_: None,
    ).compile(compilation)
    producer, consumer = bundle.graph.tasks
    binding_type = BindingTypeInput(
        binding_name="result-set-1", value_type="semantic-result:many"
    )
    producer_request = SemanticToolTaskExecutionInput(
        request_key=bundle.graph.request_key,
        run_id=bundle.graph.run_id,
        dataset_version=bundle.graph.dataset_version,
        cutoff_date=bundle.graph.cutoff_date,
        created_at=bundle.graph.created_at,
        task=producer,
        logical_query_plan=bundle.logical_query_plan,
        dependency_results=(),
        binding_values=(),
        binding_types=(binding_type,),
    )
    produced = BindingValue(
        binding_name="result-set-1",
        value_type="semantic-result:many",
        value=encode_contract_value(("product-1",)),
    )
    producer_result = build_tool_result(
        producer_request,
        status=ToolStatus.SUCCESS,
        binding_values=(produced,),
        latency_ms=1,
    )

    def consumer_payload(result, value=produced):
        return dict(
            request_key=bundle.graph.request_key,
            run_id=bundle.graph.run_id,
            dataset_version=bundle.graph.dataset_version,
            cutoff_date=bundle.graph.cutoff_date,
            created_at=bundle.graph.created_at,
            task=consumer,
            logical_query_plan=bundle.logical_query_plan,
            dependency_results=(result,),
            binding_values=(value,),
            binding_types=(binding_type,),
        )

    wrong_producer = producer_result.model_copy(
        update={"producer": "executor:graph_traversal"}
    )
    wrong_producer = wrong_producer.model_copy(
        update={"result_hash": expected_result_hash(wrong_producer)}
    )
    with pytest.raises(ValueError, match="SEMANTIC_DEPENDENCY_RESULT_INVALID"):
        SemanticToolTaskExecutionInput(**consumer_payload(wrong_producer))

    wrong_result_type = producer_result.model_copy(
        update={"result_type": ResultType.SCALAR}
    )
    wrong_result_type = wrong_result_type.model_copy(
        update={"result_hash": expected_result_hash(wrong_result_type)}
    )
    with pytest.raises(ValueError, match="SEMANTIC_DEPENDENCY_RESULT_INVALID"):
        SemanticToolTaskExecutionInput(**consumer_payload(wrong_result_type))

    scalar_many = produced.model_copy(
        update={"value": encode_contract_value("product-1")}
    )
    malformed_result = build_tool_result(
        producer_request,
        status=ToolStatus.SUCCESS,
        binding_values=(scalar_many,),
        latency_ms=1,
    )
    with pytest.raises(ValueError, match="SEMANTIC_DEPENDENCY_BINDING_MISMATCH"):
        SemanticToolTaskExecutionInput(
            **consumer_payload(malformed_result, scalar_many)
        )


def test_semantic_scalar_dependency_rejects_tuple_payload() -> None:
    compilation = tool_dependency_compilation("one")
    bundle = SemanticExecutionGraphCompiler(
        load_planning_registry(PROJECT_ROOT),
        compiled_request_provider=lambda *_: None,
    ).compile(compilation)
    producer, consumer = bundle.graph.tasks
    binding_type = BindingTypeInput(
        binding_name="result-set-1", value_type="semantic-result:one"
    )
    producer_request = SemanticToolTaskExecutionInput(
        request_key=bundle.graph.request_key,
        run_id=bundle.graph.run_id,
        dataset_version=bundle.graph.dataset_version,
        cutoff_date=bundle.graph.cutoff_date,
        created_at=bundle.graph.created_at,
        task=producer,
        logical_query_plan=bundle.logical_query_plan,
        dependency_results=(),
        binding_values=(),
        binding_types=(binding_type,),
    )
    malformed = BindingValue(
        binding_name="result-set-1",
        value_type="semantic-result:one",
        value=encode_contract_value(("product-1",)),
    )
    result = build_tool_result(
        producer_request,
        status=ToolStatus.SUCCESS,
        binding_values=(malformed,),
        latency_ms=1,
    )

    with pytest.raises(ValueError, match="SEMANTIC_DEPENDENCY_BINDING_MISMATCH"):
        SemanticToolTaskExecutionInput(
            request_key=bundle.graph.request_key,
            run_id=bundle.graph.run_id,
            dataset_version=bundle.graph.dataset_version,
            cutoff_date=bundle.graph.cutoff_date,
            created_at=bundle.graph.created_at,
            task=consumer,
            logical_query_plan=bundle.logical_query_plan,
            dependency_results=(result,),
            binding_values=(malformed,),
            binding_types=(binding_type,),
        )

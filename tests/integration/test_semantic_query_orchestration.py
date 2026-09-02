from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from financial_agent.contracts.enums import Capability, ExecutionOutcome, ToolStatus
from financial_agent.contracts.execution import ToolResult
from financial_agent.contracts.values import decode_contract_value
from financial_agent.orchestration.executors import (
    CapabilityExecutor,
    ExecutorRegistry,
    SqlCapabilityExecutor,
    build_tool_result,
)
from financial_agent.orchestration.graph import ExecutionGraphCompiler
from financial_agent.orchestration.semantic_execution import SemanticExecutorRequest
from financial_agent.orchestration.semantic_graph import SemanticExecutionGraphCompiler
from financial_agent.orchestration.service import Orchestrator
from financial_agent.planning.registry import load_planning_registry
from financial_agent.sql.result_mapping import MappedSqlResult
from financial_agent.sql.compiler import SemanticSqlRuntimeBinder
from financial_agent.sql.contracts import DeferredSqlParameter, SqlParameter
from financial_agent.sql.executor import ReadOnlySqlRunner

from tests.orchestration.test_semantic_graph import (
    sql_compilation,
    sql_request,
    sql_dependency_compilation,
    tool_compilation,
    tool_dependency_compilation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLANNING = load_planning_registry(PROJECT_ROOT)


class EmptyRunner:
    def __init__(self):
        self.calls = []

    async def execute(self, request, logical_plan, *, readiness_facts=None):
        self.calls.append((request, logical_plan, readiness_facts))
        return MappedSqlResult(result_rows=(), evidence_refs=(), exclusions=(), warnings=())


@dataclass
class SemanticRecordingExecutor(CapabilityExecutor):
    statuses: list[ToolStatus] = field(default_factory=list)
    delay_seconds: float = 0.0
    calls: list[SemanticExecutorRequest] = field(default_factory=list)

    async def execute(self, request: SemanticExecutorRequest) -> ToolResult:
        self.calls.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        status = self.statuses.pop(0) if self.statuses else ToolStatus.SUCCESS
        binding_values = ()
        if status is ToolStatus.SUCCESS:
            from financial_agent.contracts.execution import BindingValue
            from financial_agent.contracts.values import encode_contract_value

            binding_values = tuple(
                BindingValue(
                    binding_name=name,
                    value_type=request.binding_type(name),
                    value=encode_contract_value(("product-1",)),
                )
                for name in request.task.produces_bindings
            )
        return build_tool_result(
            request,
            status=status,
            binding_values=binding_values,
            latency_ms=1,
        )


def orchestrator(executors, provider, *, deadline_ms=5_000):
    return Orchestrator(
        graph_compiler=ExecutionGraphCompiler(PLANNING),
        semantic_graph_compiler=SemanticExecutionGraphCompiler(
            PLANNING, compiled_request_provider=provider
        ),
        executors=executors,
        hard_deadline_ms=deadline_ms,
    )


@pytest.mark.asyncio
async def test_semantic_sql_runs_through_the_existing_orchestrator_scheduler() -> None:
    compilation = sql_compilation()
    compiled = sql_request(compilation)
    runner = EmptyRunner()
    service = orchestrator(
        ExecutorRegistry(((Capability.RDB_LOOKUP, SqlCapabilityExecutor(runner)),)),
        lambda *_: compiled,
    )

    result = await service.execute_semantic(compilation)

    assert result.execution_outcome is ExecutionOutcome.COMPLETED
    assert len(runner.calls) == 1
    assert result.tool_results[0].status is ToolStatus.EMPTY


@pytest.mark.asyncio
async def test_sql_producer_result_is_bound_into_dependent_sql_request() -> None:
    from financial_agent.contracts.execution import ResultRow
    from tests.orchestration.test_semantic_graph import SQL_COMPILER
    from tests.sql.test_executor import FakeEngine

    compilation = sql_dependency_compilation()
    plan = compilation.logical_query_plan
    assert plan is not None
    requests = {}
    for task in plan.tasks:
        outcome = SQL_COMPILER.compile_task(plan, task.task_id)
        assert outcome.request is not None
        requests[task.task_id] = outcome.request
    assert any(
        isinstance(item, DeferredSqlParameter)
        for item in requests[plan.tasks[1].task_id].parameters
    )

    class DependencyRunner:
        def __init__(self, consumer_runner):
            self.calls = []
            self.consumer_runner = consumer_runner

        async def execute(self, request, logical_plan, *, readiness_facts=None):
            self.calls.append(request)
            if len(self.calls) == 1:
                return MappedSqlResult(
                    result_rows=(
                        ResultRow(
                            row_id="row-2",
                            entity_ids=("product-2",),
                            fields=(),
                        ),
                        ResultRow(
                            row_id="row-1",
                            entity_ids=("product-1",),
                            fields=(),
                        ),
                    ),
                    evidence_refs=("evidence-1",),
                    exclusions=(),
                    warnings=(),
                )
            return await self.consumer_runner.execute(
                request,
                logical_plan,
                readiness_facts=readiness_facts,
            )

    engine = FakeEngine([])
    runner = DependencyRunner(ReadOnlySqlRunner(engine, SQL_COMPILER))
    executor = SqlCapabilityExecutor(
        runner,
        runtime_binder=SemanticSqlRuntimeBinder(SQL_COMPILER),
    )
    result = await orchestrator(
        ExecutorRegistry(((Capability.RDB_LOOKUP, executor),)),
        lambda _, task: requests[task.task_id],
    ).execute_semantic(compilation)

    assert result.execution_outcome is ExecutionOutcome.COMPLETED
    assert len(runner.calls) == 2
    consumer_request = runner.calls[1]
    assert all(isinstance(item, SqlParameter) for item in consumer_request.parameters)
    bound_values = [
        decode_contract_value(item.value)
        for item in consumer_request.parameters
        if decode_contract_value(item.value) == ("product-1", "product-2")
    ]
    assert bound_values == [("product-1", "product-2")]
    assert engine.connect_count == 1
    business_parameters = engine.connection.executions[1][1]
    assert ("product-1", "product-2") in business_parameters.values()


@pytest.mark.asyncio
async def test_semantic_tool_reuses_retry_and_deadline_rules() -> None:
    compilation = tool_compilation()
    retried = SemanticRecordingExecutor(
        statuses=[ToolStatus.TRANSIENT_ERROR, ToolStatus.SUCCESS]
    )
    service = orchestrator(
        ExecutorRegistry(((Capability.KEYWORD_SEARCH, retried),)),
        lambda *_: None,
    )

    result = await service.execute_semantic(compilation)

    assert result.execution_outcome is ExecutionOutcome.COMPLETED
    assert len(retried.calls) == 2
    assert tuple(item.attempt_number for item in result.attempts) == (1, 2)

    slow = SemanticRecordingExecutor(delay_seconds=0.05)
    timed_out = await orchestrator(
        ExecutorRegistry(((Capability.KEYWORD_SEARCH, slow),)),
        lambda *_: None,
        deadline_ms=5,
    ).execute_semantic(compilation)
    assert timed_out.execution_outcome is ExecutionOutcome.FAILED
    assert timed_out.failures[0].code == "TASK_TIMEOUT"


@pytest.mark.asyncio
async def test_semantic_dependency_empty_result_skips_consumer() -> None:
    compilation = tool_dependency_compilation()
    executor = SemanticRecordingExecutor(statuses=[ToolStatus.EMPTY])
    result = await orchestrator(
        ExecutorRegistry(((Capability.KEYWORD_SEARCH, executor),)),
        lambda *_: None,
    ).execute_semantic(compilation)

    graph_tasks = result.graph.tasks
    assert len(executor.calls) == 1
    assert result.completed_task_ids == (graph_tasks[0].task_id,)
    assert result.skipped_task_ids == (graph_tasks[1].task_id,)
    assert result.execution_outcome is ExecutionOutcome.COMPLETED


@pytest.mark.asyncio
async def test_semantic_dependency_publishes_typed_binding_before_consumer() -> None:
    compilation = tool_dependency_compilation()
    executor = SemanticRecordingExecutor()
    result = await orchestrator(
        ExecutorRegistry(((Capability.KEYWORD_SEARCH, executor),)),
        lambda *_: None,
    ).execute_semantic(compilation)

    assert result.execution_outcome is ExecutionOutcome.COMPLETED
    assert len(executor.calls) == 2
    assert executor.calls[1].dependency_results[0].task_id == executor.calls[0].task.task_id
    assert executor.calls[1].binding_values[0].binding_name == "result-set-1"
    assert executor.calls[1].binding_values[0].value_type == "semantic-result:many"


@pytest.mark.asyncio
async def test_v1_and_v2_entrypoints_delegate_to_one_scheduler() -> None:
    from tests.orchestration.test_service import compilation as v1_compilation

    semantic = tool_compilation()
    executor = SemanticRecordingExecutor()
    service = orchestrator(
        ExecutorRegistry(
            (
                (Capability.KEYWORD_SEARCH, executor),
                (Capability.RDB_LOOKUP, executor),
                (Capability.RANKING, executor),
            )
        ),
        lambda *_: None,
    )
    original = service._schedule
    calls = []

    async def recording_schedule(*args, **kwargs):
        calls.append(args[0].graph_id)
        return await original(*args, **kwargs)

    service._schedule = recording_schedule
    await service.execute(v1_compilation())
    await service.execute_semantic(semantic)

    assert len(calls) == 2


def test_v1_task_execution_input_serialization_is_unchanged() -> None:
    from tests.orchestration.test_executors import task_request

    request = task_request()
    assert "request_kind" not in request.model_dump(mode="json")
    assert "logical_query_plan" not in request.model_dump(mode="json")
    assert type(request).model_fields.keys() == {
        "request_key",
        "run_id",
        "dataset_version",
        "cutoff_date",
        "created_at",
        "task",
        "query_plan",
        "dependency_results",
        "binding_values",
        "binding_types",
    }

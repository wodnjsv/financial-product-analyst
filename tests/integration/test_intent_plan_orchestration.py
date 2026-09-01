import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from financial_agent.contracts.enums import Capability, ExecutionOutcome, ToolStatus
from financial_agent.contracts.execution import BindingValue, ToolResult
from financial_agent.contracts.values import encode_contract_value
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.types import (
    ResolutionStatus,
    SemanticCoverageState,
    SemanticTag,
)
from financial_agent.orchestration.executors import (
    CapabilityExecutor,
    ExecutorRegistry,
    TaskExecutionInput,
    build_tool_result,
)
from financial_agent.orchestration.graph import (
    ExecutionGraphCompiler,
    GraphCompilationError,
)
from financial_agent.orchestration.service import Orchestrator
from financial_agent.planning.compiler import QueryPlanCompiler
from financial_agent.planning.contracts import CompilationRoute
from financial_agent.planning.registry import load_planning_registry

from tests.planning.fixtures import (
    cross_family_resolution,
    resolution,
    view,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class SuccessfulExecutor(CapabilityExecutor):
    calls: list[TaskExecutionInput] = field(default_factory=list)

    async def execute(self, request: TaskExecutionInput) -> ToolResult:
        self.calls.append(request)
        bindings = tuple(
            BindingValue(
                binding_name=name,
                value_type=request.binding_type(name),
                value=encode_contract_value(("product-1", "product-2")),
            )
            for name in request.task.produces_bindings
        )
        return build_tool_result(
            request,
            status=ToolStatus.SUCCESS,
            binding_values=bindings,
            evidence_refs=(f"evidence:{request.task.task_id}",),
            latency_ms=1,
        )


def _compiler() -> QueryPlanCompiler:
    return QueryPlanCompiler(
        catalog=load_catalog(PROJECT_ROOT),
        registry=load_planning_registry(PROJECT_ROOT),
    )


def _orchestrator(*capabilities: Capability) -> tuple[Orchestrator, SuccessfulExecutor]:
    executor = SuccessfulExecutor()
    registry = load_planning_registry(PROJECT_ROOT)
    return (
        Orchestrator(
            graph_compiler=ExecutionGraphCompiler(registry),
            executors=ExecutorRegistry(
                tuple((capability, executor) for capability in capabilities)
            ),
        ),
        executor,
    )


def test_rank_resolution_compiles_and_executes_in_dependency_order() -> None:
    compilation = _compiler().compile(resolution(), view())
    service, executor = _orchestrator(Capability.RDB_LOOKUP, Capability.RANKING)

    result = asyncio.run(service.execute(compilation))

    assert compilation.route is CompilationRoute.FAST
    assert result.execution_outcome is ExecutionOutcome.COMPLETED
    assert [call.task.operation_id for call in executor.calls] == [
        "operation:frame-1:lookup-products",
        "operation:frame-1:rank-products",
    ]
    assert executor.calls[1].dependency_results[0].task_id == (
        "task:operation:frame-1:lookup-products"
    )


def test_one_request_context_rerank_propagates_the_exact_result_binding() -> None:
    compilation = _compiler().compile(
        resolution(context=True),
        view(context=True),
    )
    service, executor = _orchestrator(Capability.RDB_LOOKUP, Capability.RANKING)

    result = asyncio.run(service.execute(compilation))

    assert result.execution_outcome is ExecutionOutcome.COMPLETED
    consumer = executor.calls[-1]
    assert consumer.task.subtask_id == "frame-2"
    assert consumer.binding_values[0].binding_name == (
        "binding:frame-1:top_k_products"
    )
    assert consumer.binding_values[0].value == encode_contract_value(
        ("product-1", "product-2")
    )


def test_cross_family_rank_executes_comparability_and_normalization_before_rank() -> None:
    compilation = _compiler().compile(cross_family_resolution(), view())
    service, executor = _orchestrator(
        Capability.RDB_LOOKUP,
        Capability.COMPARISON,
        Capability.FINANCIAL_CALCULATION,
        Capability.RANKING,
    )

    result = asyncio.run(service.execute(compilation))

    assert result.execution_outcome is ExecutionOutcome.COMPLETED
    assert [call.task.capability for call in executor.calls] == [
        Capability.RDB_LOOKUP,
        Capability.COMPARISON,
        Capability.FINANCIAL_CALCULATION,
        Capability.RANKING,
    ]


def test_lexical_ood_executes_only_the_bounded_explore_primitive() -> None:
    source = resolution(
        status=ResolutionStatus.UNMAPPED,
        coverage=SemanticCoverageState.PARTIAL,
    )
    compilation = _compiler().compile(source, view())
    service, executor = _orchestrator(Capability.KEYWORD_SEARCH)

    result = asyncio.run(service.execute(compilation))

    assert compilation.route is CompilationRoute.EXPLORE
    assert result.execution_outcome is ExecutionOutcome.COMPLETED
    assert [call.task.operation_id for call in executor.calls] == [
        "operation:frame-1:explore-catalog"
    ]
    parameter_names = {
        item.name for item in executor.calls[0].task.literal_inputs
    }
    assert parameter_names >= {"family:domestic_etf", "evidence:e1"}


def test_policy_abstain_never_compiles_an_execution_graph() -> None:
    compilation = _compiler().compile(
        resolution(tags=(SemanticTag.PERSONALIZED_ADVICE,)),
        view(),
    )

    assert compilation.route is CompilationRoute.ABSTAIN
    with pytest.raises(GraphCompilationError, match="QUERY_PLAN_NOT_EXECUTABLE"):
        ExecutionGraphCompiler(load_planning_registry(PROJECT_ROOT)).compile(
            compilation
        )

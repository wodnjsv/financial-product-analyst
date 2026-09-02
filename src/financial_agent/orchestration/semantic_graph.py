"""Compile validated semantic plans into the existing bounded execution graph."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import model_validator

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.contracts.canonical import canonical_json_bytes
from financial_agent.contracts.enums import Capability
from financial_agent.contracts.execution import ExecutionGraph
from financial_agent.planning.logical_query import LogicalQueryPlanV2, LogicalQueryTaskV2
from financial_agent.planning.primitive_contracts import LogicalExecutionRoute
from financial_agent.planning.registry import PlanningRegistry
from financial_agent.planning.semantic_compiler import SemanticQueryPlanCompilation
from financial_agent.sql.contracts import CompiledSqlRequest, validate_compiled_request_ownership

from .semantic_derivation import (
    active_planning_registry,
    derive_semantic_execution_graph,
    semantic_execution_task_id,
)


CompiledRequestProvider = Callable[
    [LogicalQueryPlanV2, LogicalQueryTaskV2], CompiledSqlRequest
]


class SemanticGraphCompilationError(ValueError):
    pass


class SemanticCompiledRequest(ContractModel):
    execution_task_id: Identifier
    request: CompiledSqlRequest


class SemanticExecutionGraphCompilation(ContractModel):
    graph: ExecutionGraph
    logical_query_plan: LogicalQueryPlanV2
    compiled_requests: tuple[SemanticCompiledRequest, ...]

    @model_validator(mode="after")
    def validate_compilation(self):
        expected_graph = derive_semantic_execution_graph(
            self.logical_query_plan, active_planning_registry()
        )
        if canonical_json_bytes(self.graph) != canonical_json_bytes(expected_graph):
            raise ValueError("SEMANTIC_GRAPH_DERIVATION_MISMATCH")
        task_ids = tuple(item.execution_task_id for item in self.compiled_requests)
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("SEMANTIC_COMPILED_REQUEST_DUPLICATE")
        graph_tasks = {item.task_id: item for item in self.graph.tasks}
        if (
            self.graph.request_key != self.logical_query_plan.request_key
            or self.graph.run_id != self.logical_query_plan.run_id
            or self.graph.dataset_version != self.logical_query_plan.dataset_version
            or self.graph.cutoff_date != self.logical_query_plan.cutoff_date
            or self.graph.created_at != self.logical_query_plan.created_at
        ):
            raise ValueError("SEMANTIC_GRAPH_PLAN_PIN_MISMATCH")
        rdb_task_ids = {
            item.task_id
            for item in self.graph.tasks
            if item.capability is Capability.RDB_LOOKUP
        }
        if any(
            item_id not in graph_tasks
            or graph_tasks[item_id].capability is not Capability.RDB_LOOKUP
            for item_id in task_ids
        ) or set(task_ids) != rdb_task_ids or any(
            item.request.task_id != graph_tasks[item.execution_task_id].operation_id
            for item in self.compiled_requests
        ):
            raise ValueError("SEMANTIC_COMPILED_REQUEST_TASK_MISMATCH")
        try:
            for item in self.compiled_requests:
                validate_compiled_request_ownership(
                    item.request, self.logical_query_plan
                )
        except ValueError as error:
            raise ValueError("SEMANTIC_COMPILED_REQUEST_OWNERSHIP_MISMATCH") from error
        return self

    def compiled_request_for(self, task_id: str) -> CompiledSqlRequest:
        for item in self.compiled_requests:
            if item.execution_task_id == task_id:
                return item.request
        raise KeyError(task_id)


class SemanticExecutionGraphCompiler:
    def __init__(
        self,
        registry: PlanningRegistry,
        *,
        compiled_request_provider: CompiledRequestProvider,
    ) -> None:
        self._registry = registry
        self._compiled_request_provider = compiled_request_provider

    def compile(
        self, compilation: SemanticQueryPlanCompilation
    ) -> SemanticExecutionGraphCompilation:
        try:
            compilation = SemanticQueryPlanCompilation.model_validate_json(
                canonical_json_bytes(compilation)
            )
        except ValueError as error:
            raise SemanticGraphCompilationError(
                "SEMANTIC_COMPILATION_REVALIDATION_FAILED"
            ) from error
        plan = compilation.logical_query_plan
        if plan is None:
            raise SemanticGraphCompilationError("SEMANTIC_PLAN_NOT_EXECUTABLE")
        if (
            plan.planning_registry_version != self._registry.registry_version
            or plan.planning_registry_hash != self._registry.registry_hash
        ):
            raise SemanticGraphCompilationError("PLANNING_REGISTRY_PIN_MISMATCH")

        try:
            graph = derive_semantic_execution_graph(plan, self._registry)
        except ValueError as error:
            raise SemanticGraphCompilationError(str(error)) from error
        compiled_requests: list[SemanticCompiledRequest] = []
        for logical_task in plan.tasks:
            sql_route = all(
                step.execution_route is LogicalExecutionRoute.SEMANTIC_SQL
                for step in logical_task.execution_steps
            )
            execution_task_id = semantic_execution_task_id(logical_task.task_id)
            if sql_route:
                request = self._compiled_request_provider(plan, logical_task)
                if not isinstance(request, CompiledSqlRequest):
                    raise SemanticGraphCompilationError(
                        "COMPILED_SQL_REQUEST_REQUIRED"
                    )
                try:
                    validate_compiled_request_ownership(request, plan)
                except ValueError as error:
                    raise SemanticGraphCompilationError(
                        "COMPILED_SQL_REQUEST_OWNERSHIP_MISMATCH"
                    ) from error
                compiled_requests.append(
                    SemanticCompiledRequest(
                        execution_task_id=execution_task_id, request=request
                    )
                )
        return SemanticExecutionGraphCompilation(
            graph=graph,
            logical_query_plan=plan,
            compiled_requests=tuple(compiled_requests),
        )


__all__ = [
    "SemanticExecutionGraphCompilation",
    "SemanticExecutionGraphCompiler",
    "SemanticGraphCompilationError",
    "semantic_execution_task_id",
]

"""Compile validated semantic plans into the existing bounded execution graph."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import model_validator

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.contracts.canonical import canonical_json_bytes, canonical_sha256
from financial_agent.contracts.enums import Capability
from financial_agent.contracts.execution import ExecutionGraph, ExecutionTask
from financial_agent.contracts.query import BindingSpec
from financial_agent.planning.logical_query import LogicalQueryPlanV2, LogicalQueryTaskV2
from financial_agent.planning.primitive_contracts import LogicalExecutionRoute
from financial_agent.planning.registry import PlanningRegistry
from financial_agent.planning.semantic_compiler import SemanticQueryPlanCompilation
from financial_agent.sql.contracts import CompiledSqlRequest, validate_compiled_request_ownership

from .graph import _critical_path
from .semantic_execution import semantic_binding_value_type, semantic_execution_task_id


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

        dependencies_by_task = {
            task.task_id: tuple(
                semantic_execution_task_id(edge.upstream_task_id)
                for edge in plan.dependencies
                if edge.downstream_task_id == task.task_id
            )
            for task in plan.tasks
        }
        tasks: list[ExecutionTask] = []
        compiled_requests: list[SemanticCompiledRequest] = []
        for logical_task in plan.tasks:
            primitives = []
            for step in logical_task.execution_steps:
                primitive = self._registry.primitives_by_id.get(step.primitive_id)
                if (
                    primitive is None
                    or step.action_id not in primitive.action_ids
                    or step.capability is not primitive.capability
                ):
                    raise SemanticGraphCompilationError(
                        "SEMANTIC_PRIMITIVE_REGISTRY_MISMATCH"
                    )
                primitives.append(primitive)
            sql_route = all(
                step.execution_route is LogicalExecutionRoute.SEMANTIC_SQL
                for step in logical_task.execution_steps
            )
            capability = (
                Capability.RDB_LOOKUP
                if sql_route
                else logical_task.execution_steps[-1].capability
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
            final_primitive = primitives[-1]
            tasks.append(
                ExecutionTask(
                    task_id=execution_task_id,
                    subtask_id=logical_task.frame_id,
                    capability=capability,
                    operation_id=logical_task.task_id,
                    binding_inputs=tuple(
                        item.binding_id for item in logical_task.prior_result_inputs
                    ),
                    produces_bindings=tuple(
                        item.binding_id
                        for item in logical_task.produced_result_bindings
                    ),
                    depends_on=dependencies_by_task[logical_task.task_id],
                    expected_output_type=final_primitive.result_type,
                    required_evidence_fields=logical_task.evidence_requirements,
                    budget_ms=sum(item.budget_ms for item in primitives),
                )
            )
        task_tuple = tuple(tasks)
        critical_path = _critical_path(task_tuple)
        total_budget = sum(
            next(item.budget_ms for item in task_tuple if item.task_id == task_id)
            for task_id in critical_path
        )
        binding_specs = tuple(
            BindingSpec(
                binding_name=item.binding_id,
                value_type=semantic_binding_value_type(item.cardinality),
                producer_subtask_id=task.frame_id,
                cardinality=item.cardinality,
            )
            for task in plan.tasks
            for item in task.produced_result_bindings
        )
        graph_seed = canonical_sha256(
            {
                "compilation_id": compilation.compilation_id,
                "tasks": [item.model_dump(mode="json") for item in task_tuple],
                "compiled_request_ids": [
                    item.request.compiled_request_id for item in compiled_requests
                ],
                "registry_hash": self._registry.registry_hash,
            }
        )
        try:
            graph = ExecutionGraph(
                request_key=plan.request_key,
                run_id=plan.run_id,
                dataset_version=plan.dataset_version,
                cutoff_date=plan.cutoff_date,
                producer="semantic-execution-graph-compiler",
                created_at=plan.created_at,
                graph_id=f"semantic-graph-{graph_seed[:24]}",
                tasks=task_tuple,
                binding_specs=binding_specs,
                critical_path=critical_path,
                total_budget_ms=total_budget,
            )
        except ValueError as error:
            raise SemanticGraphCompilationError("SEMANTIC_GRAPH_INVALID") from error
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

"""Pure derivation of the bounded execution graph from an authoritative V2 plan."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import Capability
from financial_agent.contracts.execution import ExecutionGraph, ExecutionTask
from financial_agent.contracts.query import BindingSpec
from financial_agent.planning.logical_query import LogicalQueryPlanV2
from financial_agent.planning.primitive_contracts import LogicalExecutionRoute
from financial_agent.planning.registry import PlanningRegistry, load_planning_registry

from .graph import _critical_path


SEMANTIC_GRAPH_PRODUCER = "semantic-execution-graph-compiler"


def semantic_execution_task_id(logical_task_id: str) -> str:
    return f"semantic-execution:{logical_task_id}"


def semantic_binding_value_type(cardinality) -> str:
    return f"semantic-result:{cardinality.value}"


@lru_cache(maxsize=1)
def active_planning_registry() -> PlanningRegistry:
    return load_planning_registry(Path(__file__).resolve().parents[3])


def derive_semantic_execution_graph(
    plan: LogicalQueryPlanV2,
    registry: PlanningRegistry,
) -> ExecutionGraph:
    if (
        plan.planning_registry_version != registry.registry_version
        or plan.planning_registry_hash != registry.registry_hash
    ):
        raise ValueError("PLANNING_REGISTRY_PIN_MISMATCH")
    dependencies_by_task = {
        task.task_id: tuple(
            semantic_execution_task_id(edge.upstream_task_id)
            for edge in plan.dependencies
            if edge.downstream_task_id == task.task_id
        )
        for task in plan.tasks
    }
    tasks = []
    for logical_task in plan.tasks:
        primitives = []
        for step in logical_task.execution_steps:
            primitive = registry.primitives_by_id.get(step.primitive_id)
            if (
                primitive is None
                or step.action_id not in primitive.action_ids
                or step.capability is not primitive.capability
            ):
                raise ValueError("SEMANTIC_PRIMITIVE_REGISTRY_MISMATCH")
            primitives.append(primitive)
        sql_route = all(
            step.execution_route is LogicalExecutionRoute.SEMANTIC_SQL
            for step in logical_task.execution_steps
        )
        tasks.append(
            ExecutionTask(
                task_id=semantic_execution_task_id(logical_task.task_id),
                subtask_id=logical_task.frame_id,
                capability=(
                    Capability.RDB_LOOKUP
                    if sql_route
                    else logical_task.execution_steps[-1].capability
                ),
                operation_id=logical_task.task_id,
                literal_inputs=(),
                binding_inputs=tuple(
                    item.binding_id for item in logical_task.prior_result_inputs
                ),
                produces_bindings=tuple(
                    item.binding_id for item in logical_task.produced_result_bindings
                ),
                depends_on=dependencies_by_task[logical_task.task_id],
                expected_output_type=primitives[-1].result_type,
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
            "logical_plan_id": plan.logical_plan_id,
            "tasks": [item.model_dump(mode="json") for item in task_tuple],
            "binding_specs": [
                item.model_dump(mode="json") for item in binding_specs
            ],
            "registry_hash": registry.registry_hash,
        }
    )
    return ExecutionGraph(
        request_key=plan.request_key,
        run_id=plan.run_id,
        dataset_version=plan.dataset_version,
        cutoff_date=plan.cutoff_date,
        producer=SEMANTIC_GRAPH_PRODUCER,
        created_at=plan.created_at,
        graph_id=f"semantic-graph-{graph_seed[:24]}",
        tasks=task_tuple,
        binding_specs=binding_specs,
        critical_path=critical_path,
        total_budget_ms=total_budget,
    )

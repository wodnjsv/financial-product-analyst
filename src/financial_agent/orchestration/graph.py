from __future__ import annotations

from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import ResultType
from financial_agent.contracts.execution import ExecutionGraph, ExecutionTask, NamedValue
from financial_agent.contracts.values import encode_contract_value
from financial_agent.planning.contracts import CompilationRoute, QueryPlanCompilation
from financial_agent.planning.registry import PlanningRegistry


class GraphCompilationError(ValueError):
    pass


class ExecutionGraphCompiler:
    def __init__(self, registry: PlanningRegistry) -> None:
        self._registry = registry

    def compile(self, compilation: QueryPlanCompilation) -> ExecutionGraph:
        if (
            compilation.route is CompilationRoute.ABSTAIN
            or compilation.query_plan is None
        ):
            raise GraphCompilationError("QUERY_PLAN_NOT_EXECUTABLE")
        plan = compilation.query_plan
        operations_by_subtask = {
            subtask.subtask_id: tuple(
                operation
                for operation in plan.operations
                if operation.subtask_id == subtask.subtask_id
            )
            for subtask in plan.subtasks
        }
        task_ids_by_subtask: dict[str, list[str]] = {
            item.subtask_id: [] for item in plan.subtasks
        }
        task_payloads: list[dict[str, object]] = []
        bindings_by_producer: dict[str, tuple[str, ...]] = {
            subtask.subtask_id: tuple(
                binding.binding_name
                for binding in plan.binding_specs
                if binding.producer_subtask_id == subtask.subtask_id
            )
            for subtask in plan.subtasks
        }
        for subtask in plan.subtasks:
            operations = operations_by_subtask[subtask.subtask_id]
            if not operations:
                raise GraphCompilationError("SUBTASK_OPERATION_MISSING")
            for index, operation in enumerate(operations):
                primitive_id = self._primitive_id(operation.operation_id, subtask.subtask_id)
                primitive = self._registry.primitives_by_id[primitive_id]
                if primitive_id not in compilation.primitive_ids:
                    raise GraphCompilationError("OPERATION_NOT_IN_COMPILATION")
                task_id = f"task:{operation.operation_id}"
                dependencies = (
                    (task_ids_by_subtask[subtask.subtask_id][-1],)
                    if task_ids_by_subtask[subtask.subtask_id]
                    else ()
                )
                task_ids_by_subtask[subtask.subtask_id].append(task_id)
                task_payloads.append(
                    {
                        "task_id": task_id,
                        "subtask_id": subtask.subtask_id,
                        "capability": primitive.capability,
                        "operation_id": operation.operation_id,
                        "literal_inputs": _literal_inputs(plan, operation, primitive_id),
                        "binding_inputs": tuple(
                            item
                            for item in operation.parameter_ids
                            if item.startswith("binding:")
                        ),
                        "produces_bindings": (
                            bindings_by_producer[subtask.subtask_id]
                            if index == len(operations) - 1
                            else ()
                        ),
                        "depends_on": dependencies,
                        "expected_output_type": ResultType(primitive.result_type),
                        "required_evidence_fields": primitive.required_evidence_fields,
                        "budget_ms": primitive.budget_ms,
                    }
                )

        payload_by_task = {item["task_id"]: item for item in task_payloads}
        for edge in plan.dependency_edges:
            upstream = task_ids_by_subtask[edge.upstream_subtask_id][-1]
            downstream = task_ids_by_subtask[edge.downstream_subtask_id][0]
            payload = payload_by_task[downstream]
            payload["depends_on"] = _unique((*payload["depends_on"], upstream))

        tasks = tuple(ExecutionTask(**item) for item in task_payloads)
        used_primitive_ids = {
            self._primitive_id(item.operation_id, item.subtask_id) for item in tasks
        }
        if used_primitive_ids != set(compilation.primitive_ids):
            raise GraphCompilationError("COMPILATION_PRIMITIVE_SET_MISMATCH")
        if {item.capability for item in tasks} != set(plan.requested_capabilities):
            raise GraphCompilationError("PLAN_CAPABILITY_SET_MISMATCH")
        critical_path = _critical_path(tasks)
        total_budget_ms = sum(
            next(item.budget_ms for item in tasks if item.task_id == task_id)
            for task_id in critical_path
        )
        graph_seed = canonical_sha256(
            {
                "compilation_id": compilation.compilation_id,
                "tasks": [item.model_dump(mode="json") for item in tasks],
                "registry_hash": compilation.compiler_manifest.registry_hash,
            }
        )
        return ExecutionGraph(
            request_key=compilation.request_key,
            run_id=compilation.run_id,
            dataset_version=compilation.dataset_version,
            producer="execution-graph-compiler",
            created_at=compilation.created_at,
            graph_id=f"graph-{graph_seed[:24]}",
            tasks=tasks,
            binding_specs=plan.binding_specs,
            critical_path=critical_path,
            total_budget_ms=total_budget_ms,
        )

    def _primitive_id(self, operation_id: str, subtask_id: str) -> str:
        prefix = f"operation:{subtask_id}:"
        if not operation_id.startswith(prefix):
            raise GraphCompilationError("INVALID_OPERATION_ID")
        primitive_id = operation_id[len(prefix) :]
        if primitive_id not in self._registry.primitives_by_id:
            raise GraphCompilationError("UNKNOWN_PRIMITIVE")
        return primitive_id


def _literal_inputs(plan, operation, primitive_id: str) -> tuple[NamedValue, ...]:
    values: list[NamedValue] = []
    parameters = set(operation.parameter_ids)
    for item in plan.filters:
        if item.subtask_id != operation.subtask_id:
            continue
        is_screen_filter = (
            primitive_id == "screen-products"
            and item.field_id not in {"result_limit", "sort_direction", "date_scope"}
        )
        if item.field_id in parameters or is_screen_filter:
            values.append(NamedValue(name=item.field_id, value=item.value))
    semantic_values: dict[str, list[str]] = {}
    for parameter in operation.parameter_ids:
        if parameter.startswith("slot:"):
            _, slot_kind, value_id = parameter.split(":", 2)
            semantic_values.setdefault(slot_kind, []).append(value_id)
    for slot_kind, value_ids in semantic_values.items():
        value = value_ids[0] if len(value_ids) == 1 else tuple(value_ids)
        values.append(
            NamedValue(name=slot_kind, value=encode_contract_value(value))
        )
    for parameter in operation.parameter_ids:
        if parameter.startswith(
            (
                "selector:",
                "link:",
                "family:",
                "evidence:",
                "entity:",
                "entity_request:",
                "policy:",
                "target_slot:",
            )
        ):
            values.append(
                NamedValue(name=parameter, value=encode_contract_value(parameter))
            )
    return tuple(values)


def _critical_path(tasks: tuple[ExecutionTask, ...]) -> tuple[str, ...]:
    tasks_by_id = {item.task_id: item for item in tasks}
    paths: dict[str, tuple[int, tuple[str, ...]]] = {}
    visiting: set[str] = set()

    def path_for(task_id: str) -> tuple[int, tuple[str, ...]]:
        if task_id in paths:
            return paths[task_id]
        if task_id in visiting:
            raise GraphCompilationError("EXECUTION_GRAPH_CYCLE")
        task = tasks_by_id.get(task_id)
        if task is None:
            raise GraphCompilationError("EXECUTION_GRAPH_DEPENDENCY_MISSING")
        visiting.add(task_id)
        candidates = [path_for(item) for item in task.depends_on]
        if candidates:
            budget, prefix = max(candidates, key=lambda item: (item[0], item[1]))
        else:
            prefix = ()
            budget = 0
        visiting.remove(task_id)
        paths[task_id] = (budget + task.budget_ms, (*prefix, task_id))
        return paths[task_id]

    for task in tasks:
        path_for(task.task_id)
    return max(paths.values(), key=lambda item: (item[0], item[1]))[1] if paths else ()


def _unique(values):
    return tuple(dict.fromkeys(values))

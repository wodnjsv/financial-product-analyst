from .enums import Cardinality
from .execution import ExecutionGraph, ToolResult
from .query import QueryPlan


def validate_execution_graph_compatibility(
    query_plan: QueryPlan,
    execution_graph: ExecutionGraph,
) -> None:
    for field_name in ("request_key", "run_id", "dataset_version", "cutoff_date"):
        if getattr(query_plan, field_name) != getattr(execution_graph, field_name):
            raise ValueError(f"runtime metadata mismatch: {field_name}")

    plan_bindings = {
        binding.binding_name: binding for binding in query_plan.binding_specs
    }
    graph_bindings = {
        binding.binding_name: binding for binding in execution_graph.binding_specs
    }
    if plan_bindings != graph_bindings:
        raise ValueError("binding specs mismatch")

    subtask_ids = {subtask.subtask_id for subtask in query_plan.subtasks}
    operations_by_id = {
        operation.operation_id: operation for operation in query_plan.operations
    }
    requested_capabilities = set(query_plan.requested_capabilities)

    for task in execution_graph.tasks:
        if task.subtask_id not in subtask_ids:
            raise ValueError("execution task references unknown subtask")
        operation = operations_by_id.get(task.operation_id)
        if operation is None:
            raise ValueError("execution task references unknown operation")
        if operation.subtask_id != task.subtask_id:
            raise ValueError("execution task operation belongs to another subtask")
        if task.capability not in requested_capabilities:
            raise ValueError("execution task uses an unrequested capability")


def validate_tool_result_compatibility(
    execution_graph: ExecutionGraph,
    tool_result: ToolResult,
) -> None:
    for field_name in ("request_key", "run_id", "dataset_version", "cutoff_date"):
        if getattr(execution_graph, field_name) != getattr(tool_result, field_name):
            raise ValueError(f"runtime metadata mismatch: {field_name}")

    tasks_by_id = {task.task_id: task for task in execution_graph.tasks}
    task = tasks_by_id.get(tool_result.task_id)
    if task is None:
        raise ValueError("tool result references unknown task")
    if tool_result.result_type is not task.expected_output_type:
        raise ValueError("tool result type does not match task output type")

    binding_specs = {
        binding.binding_name: binding for binding in execution_graph.binding_specs
    }
    declared_outputs = set(task.produces_bindings)
    for binding_value in tool_result.binding_values:
        if binding_value.binding_name not in declared_outputs:
            raise ValueError("tool result contains undeclared binding output")
        binding_spec = binding_specs[binding_value.binding_name]
        if binding_value.value_type != binding_spec.value_type:
            raise ValueError("tool result binding value type mismatch")
        if (
            binding_spec.cardinality is Cardinality.ONE
            and isinstance(binding_value.value, tuple)
        ):
            raise ValueError("single binding cannot contain a tuple")
        if (
            binding_spec.cardinality is Cardinality.MANY
            and not isinstance(binding_value.value, tuple)
        ):
            raise ValueError("many binding must contain a tuple")

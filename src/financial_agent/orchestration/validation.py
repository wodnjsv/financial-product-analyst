from financial_agent.contracts.enums import ToolStatus
from financial_agent.contracts.execution import ToolResult

from .executors import ExecutorRequest, expected_result_hash


class ToolResultContractError(ValueError):
    pass


def validate_tool_result(
    request: ExecutorRequest,
    result: ToolResult,
) -> ToolResult:
    if result.task_id != request.task.task_id:
        raise ToolResultContractError("TOOL_RESULT_TASK_MISMATCH")
    if (
        result.request_key != request.request_key
        or result.run_id != request.run_id
        or result.dataset_version != request.dataset_version
        or result.cutoff_date != request.cutoff_date
        or result.created_at != request.created_at
    ):
        raise ToolResultContractError("TOOL_RESULT_PIN_MISMATCH")
    if result.result_type is not request.task.expected_output_type:
        raise ToolResultContractError("TOOL_RESULT_TYPE_MISMATCH")
    if result.result_hash != expected_result_hash(result):
        raise ToolResultContractError("TOOL_RESULT_HASH_MISMATCH")
    if result.status is ToolStatus.SUCCESS:
        actual = {item.binding_name for item in result.binding_values}
        expected = set(request.task.produces_bindings)
        if actual != expected:
            raise ToolResultContractError("TOOL_RESULT_BINDING_MISMATCH")
        if request.task.required_evidence_fields and not result.evidence_refs:
            raise ToolResultContractError("TOOL_RESULT_EVIDENCE_REQUIRED")
        for binding in result.binding_values:
            if binding.value_type != request.binding_type(binding.binding_name):
                raise ToolResultContractError("TOOL_RESULT_BINDING_TYPE_MISMATCH")
    return result

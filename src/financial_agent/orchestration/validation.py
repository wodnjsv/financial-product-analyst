from pydantic import TypeAdapter

from financial_agent.contracts.base import Identifier
from financial_agent.contracts.enums import ToolStatus
from financial_agent.contracts.execution import ToolResult
from financial_agent.contracts.values import decode_contract_value

from .executors import ExecutorRequest, expected_result_hash


class ToolResultContractError(ValueError):
    pass


_IDENTIFIER_ADAPTER = TypeAdapter(Identifier)


def validate_tool_result(
    request: ExecutorRequest,
    result: ToolResult,
) -> ToolResult:
    if result.task_id != request.task.task_id:
        raise ToolResultContractError("TOOL_RESULT_TASK_MISMATCH")
    if result.producer != f"executor:{request.task.capability.value}":
        raise ToolResultContractError("TOOL_RESULT_PRODUCER_MISMATCH")
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
            if binding.value_type.startswith("semantic-result:"):
                _validate_semantic_binding_value(binding.value_type, binding.value)
        if result.result_rows:
            for binding in result.binding_values:
                if (
                    binding.value_type == "semantic-result:many"
                    and not decode_contract_value(binding.value)
                ):
                    raise ToolResultContractError(
                        "TOOL_RESULT_BINDING_VALUE_INVALID"
                    )
    return result


def _validate_semantic_binding_value(value_type, value) -> None:
    try:
        decoded = decode_contract_value(value)
        if value_type == "semantic-result:many":
            if not isinstance(decoded, tuple):
                raise ValueError
            candidates = decoded
        elif value_type == "semantic-result:one":
            if not isinstance(decoded, str):
                raise ValueError
            candidates = (decoded,)
        else:
            raise ValueError
        for candidate in candidates:
            if not isinstance(candidate, str):
                raise ValueError
            _IDENTIFIER_ADAPTER.validate_python(candidate)
    except (KeyError, TypeError, ValueError) as error:
        raise ToolResultContractError(
            "TOOL_RESULT_BINDING_VALUE_INVALID"
        ) from error

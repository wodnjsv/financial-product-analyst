from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from types import MappingProxyType
from typing import Mapping

from pydantic import model_validator

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex, UtcDateTime
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import Capability, ToolStatus
from financial_agent.contracts.execution import (
    BindingValue,
    ExecutionTask,
    Exclusion,
    ResultRow,
    ResultWarning,
    ToolResult,
)
from financial_agent.contracts.query import QueryPlan


class BindingTypeInput(ContractModel):
    binding_name: Identifier
    value_type: Identifier


class TaskExecutionInput(ContractModel):
    request_key: Sha256Hex
    run_id: Identifier
    dataset_version: Identifier
    cutoff_date: date
    created_at: UtcDateTime
    task: ExecutionTask
    query_plan: QueryPlan
    dependency_results: tuple[ToolResult, ...]
    binding_values: tuple[BindingValue, ...]
    binding_types: tuple[BindingTypeInput, ...]

    @model_validator(mode="after")
    def validate_input(self) -> "TaskExecutionInput":
        if (
            self.query_plan.request_key != self.request_key
            or self.query_plan.run_id != self.run_id
            or self.query_plan.dataset_version != self.dataset_version
            or self.query_plan.cutoff_date != self.cutoff_date
        ):
            raise ValueError("execution input pins must match query plan")
        operation_ids = {item.operation_id for item in self.query_plan.operations}
        if self.task.operation_id not in operation_ids:
            raise ValueError("execution task operation must belong to query plan")
        dependency_ids = tuple(item.task_id for item in self.dependency_results)
        if set(dependency_ids) != set(self.task.depends_on):
            raise ValueError("dependency results must exactly match task dependencies")
        if len(dependency_ids) != len(set(dependency_ids)):
            raise ValueError("dependency results must be unique")
        if any(item.status is not ToolStatus.SUCCESS for item in self.dependency_results):
            raise ValueError("dependency results must be successful")
        if any(
            item.request_key != self.request_key
            or item.run_id != self.run_id
            or item.dataset_version != self.dataset_version
            or item.cutoff_date != self.cutoff_date
            or item.result_hash != expected_result_hash(item)
            for item in self.dependency_results
        ):
            raise ValueError("dependency result pins and hashes must be valid")
        names = tuple(item.binding_name for item in self.binding_types)
        if len(names) != len(set(names)):
            raise ValueError("binding input types must be unique")
        expected_types = {
            item.binding_name: item.value_type
            for item in self.query_plan.binding_specs
        }
        actual_types = {
            item.binding_name: item.value_type for item in self.binding_types
        }
        if actual_types != expected_types:
            raise ValueError("binding input types must match query plan")
        binding_names = tuple(item.binding_name for item in self.binding_values)
        if (
            len(binding_names) != len(set(binding_names))
            or set(binding_names) != set(self.task.binding_inputs)
            or any(
                item.value_type != actual_types[item.binding_name]
                for item in self.binding_values
            )
        ):
            raise ValueError("binding values must exactly match task inputs")
        return self

    def binding_type(self, binding_name: str) -> str:
        for item in self.binding_types:
            if item.binding_name == binding_name:
                return item.value_type
        raise KeyError(binding_name)


class CapabilityExecutor(ABC):
    @abstractmethod
    async def execute(self, request: TaskExecutionInput) -> ToolResult:
        raise NotImplementedError


class ExecutorRegistry:
    def __init__(
        self,
        registrations: tuple[tuple[Capability, CapabilityExecutor], ...],
    ) -> None:
        indexed: dict[Capability, CapabilityExecutor] = {}
        for capability, executor in registrations:
            if capability in indexed:
                raise ValueError(f"duplicate executor: {capability.value}")
            indexed[capability] = executor
        self._executors: Mapping[Capability, CapabilityExecutor] = MappingProxyType(
            indexed
        )

    def require(self, capabilities: set[Capability]) -> None:
        missing = sorted(
            (item.value for item in capabilities if item not in self._executors)
        )
        if missing:
            raise ValueError(f"missing executor: {missing}")

    def get(self, capability: Capability) -> CapabilityExecutor:
        return self._executors[capability]


def build_tool_result(
    request: TaskExecutionInput,
    *,
    status: ToolStatus,
    result_rows: tuple[ResultRow, ...] = (),
    binding_values: tuple[BindingValue, ...] = (),
    evidence_refs: tuple[Identifier, ...] = (),
    exclusions: tuple[Exclusion, ...] = (),
    warnings: tuple[ResultWarning, ...] = (),
    latency_ms: int,
) -> ToolResult:
    payload = _result_payload(
        request=request,
        status=status,
        result_rows=result_rows,
        binding_values=binding_values,
        evidence_refs=evidence_refs,
        exclusions=exclusions,
        warnings=warnings,
        latency_ms=latency_ms,
    )
    provisional = ToolResult(
        **payload,
        result_hash="0" * 64,
    )
    return provisional.model_copy(
        update={
            "result_hash": canonical_sha256(
                provisional,
                exclude_fields=("result_hash",),
            )
        }
    )


def expected_result_hash(result: ToolResult) -> str:
    return canonical_sha256(result, exclude_fields=("result_hash",))


def _result_payload(
    *,
    request: TaskExecutionInput,
    status: ToolStatus,
    result_rows,
    binding_values,
    evidence_refs,
    exclusions,
    warnings,
    latency_ms,
) -> dict[str, object]:
    return {
        "request_key": request.request_key,
        "run_id": request.run_id,
        "dataset_version": request.dataset_version,
        "producer": f"executor:{request.task.capability.value}",
        "created_at": request.created_at,
        "task_id": request.task.task_id,
        "status": status,
        "result_type": request.task.expected_output_type,
        "result_rows": result_rows,
        "binding_values": binding_values,
        "evidence_refs": evidence_refs,
        "exclusions": exclusions,
        "warnings": warnings,
        "latency_ms": latency_ms,
    }

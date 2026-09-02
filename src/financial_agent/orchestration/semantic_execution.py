"""Strict V2 executor inputs kept separate from the V1 request contract."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, model_validator

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex, UtcDateTime
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import Capability, ToolStatus
from financial_agent.contracts.execution import (
    BindingTypeInput,
    BindingValue,
    ExecutionTask,
    ToolResult,
)
from financial_agent.planning.logical_query import LogicalQueryPlanV2, LogicalQueryTaskV2
from financial_agent.planning.primitive_contracts import LogicalExecutionRoute
from financial_agent.sql.contracts import (
    CompiledSqlRequest,
    validate_compiled_request_ownership,
)


def semantic_execution_task_id(logical_task_id: str) -> str:
    return f"semantic-execution:{logical_task_id}"


def semantic_binding_value_type(cardinality) -> str:
    return f"semantic-result:{cardinality.value}"


class SemanticExecutionInputBase(ContractModel):
    request_key: Sha256Hex
    run_id: Identifier
    dataset_version: Identifier
    cutoff_date: date
    created_at: UtcDateTime
    task: ExecutionTask
    logical_query_plan: LogicalQueryPlanV2
    dependency_results: tuple[ToolResult, ...]
    binding_values: tuple[BindingValue, ...]
    binding_types: tuple[BindingTypeInput, ...]

    @model_validator(mode="after")
    def validate_semantic_input(self):
        plan = self.logical_query_plan
        if (
            plan.request_key != self.request_key
            or plan.run_id != self.run_id
            or plan.dataset_version != self.dataset_version
            or plan.cutoff_date != self.cutoff_date
            or plan.created_at != self.created_at
        ):
            raise ValueError("SEMANTIC_EXECUTION_PLAN_PIN_MISMATCH")
        logical_task = self.logical_task()
        expected_dependencies = tuple(
            semantic_execution_task_id(item.upstream_task_id)
            for item in plan.dependencies
            if item.downstream_task_id == logical_task.task_id
        )
        expected_inputs = tuple(
            item.binding_id for item in logical_task.prior_result_inputs
        )
        expected_outputs = tuple(
            item.binding_id for item in logical_task.produced_result_bindings
        )
        if (
            self.task.task_id != semantic_execution_task_id(logical_task.task_id)
            or self.task.subtask_id != logical_task.frame_id
            or self.task.depends_on != expected_dependencies
            or self.task.binding_inputs != expected_inputs
            or self.task.produces_bindings != expected_outputs
        ):
            raise ValueError("SEMANTIC_EXECUTION_TASK_OWNERSHIP_MISMATCH")

        expected_types = {
            item.binding_id: semantic_binding_value_type(item.cardinality)
            for task in plan.tasks
            for item in task.produced_result_bindings
        }
        actual_types = {
            item.binding_name: item.value_type for item in self.binding_types
        }
        names = tuple(item.binding_name for item in self.binding_types)
        if len(names) != len(set(names)) or actual_types != expected_types:
            raise ValueError("SEMANTIC_BINDING_TYPE_MISMATCH")

        dependency_ids = tuple(item.task_id for item in self.dependency_results)
        if (
            len(dependency_ids) != len(set(dependency_ids))
            or set(dependency_ids) != set(self.task.depends_on)
        ):
            raise ValueError("SEMANTIC_DEPENDENCY_RESULT_MISMATCH")
        if any(
            item.status is not ToolStatus.SUCCESS
            or item.request_key != self.request_key
            or item.run_id != self.run_id
            or item.dataset_version != self.dataset_version
            or item.cutoff_date != self.cutoff_date
            or item.created_at != self.created_at
            or item.result_hash
            != canonical_sha256(item, exclude_fields=("result_hash",))
            for item in self.dependency_results
        ):
            raise ValueError("SEMANTIC_DEPENDENCY_RESULT_INVALID")
        logical_by_execution_id = {
            semantic_execution_task_id(item.task_id): item for item in plan.tasks
        }
        for result in self.dependency_results:
            upstream = logical_by_execution_id.get(result.task_id)
            if upstream is None:
                raise ValueError("SEMANTIC_DEPENDENCY_RESULT_MISMATCH")
            expected_result_bindings = {
                item.binding_id: semantic_binding_value_type(item.cardinality)
                for item in upstream.produced_result_bindings
            }
            actual_result_bindings = {
                item.binding_name: item.value_type for item in result.binding_values
            }
            if expected_result_bindings != actual_result_bindings:
                raise ValueError("SEMANTIC_DEPENDENCY_BINDING_MISMATCH")
        values = {item.binding_name: item for item in self.binding_values}
        value_names = tuple(item.binding_name for item in self.binding_values)
        if (
            len(value_names) != len(set(value_names))
            or set(values) != set(expected_inputs)
            or any(
                item.value_type != actual_types[item.binding_name]
                for item in values.values()
            )
        ):
            raise ValueError("SEMANTIC_BINDING_VALUE_MISMATCH")
        produced = {
            item.binding_name: item
            for result in self.dependency_results
            for item in result.binding_values
        }
        if any(produced.get(name) != value for name, value in values.items()):
            raise ValueError("SEMANTIC_BINDING_ORIGIN_MISMATCH")
        return self

    def logical_task(self) -> LogicalQueryTaskV2:
        task = next(
            (
                item
                for item in self.logical_query_plan.tasks
                if item.task_id == self.task.operation_id
            ),
            None,
        )
        if task is None:
            raise ValueError("SEMANTIC_EXECUTION_TASK_OWNERSHIP_MISMATCH")
        return task

    def binding_type(self, binding_name: str) -> str:
        for item in self.binding_types:
            if item.binding_name == binding_name:
                return item.value_type
        raise KeyError(binding_name)


class SemanticSqlTaskExecutionInput(SemanticExecutionInputBase):
    request_kind: Literal["semantic_sql"] = "semantic_sql"
    compiled_request: CompiledSqlRequest

    @model_validator(mode="after")
    def validate_sql_input(self):
        logical_task = self.logical_task()
        if (
            self.task.capability is not Capability.RDB_LOOKUP
            or self.task.required_evidence_fields != logical_task.evidence_requirements
            or any(
                item.execution_route is not LogicalExecutionRoute.SEMANTIC_SQL
                for item in logical_task.execution_steps
            )
        ):
            raise ValueError("SEMANTIC_SQL_RDB_REQUIRED")
        try:
            validate_compiled_request_ownership(
                self.compiled_request, self.logical_query_plan
            )
        except ValueError as error:
            raise ValueError("SEMANTIC_SQL_REQUEST_OWNERSHIP_MISMATCH") from error
        if self.compiled_request.task_id != logical_task.task_id:
            raise ValueError("SEMANTIC_SQL_REQUEST_OWNERSHIP_MISMATCH")
        return self


class SemanticToolTaskExecutionInput(SemanticExecutionInputBase):
    request_kind: Literal["semantic_tool"] = "semantic_tool"

    @model_validator(mode="after")
    def validate_tool_input(self):
        logical_task = self.logical_task()
        if self.task.capability is Capability.RDB_LOOKUP:
            raise ValueError("SEMANTIC_TOOL_RDB_FORBIDDEN")
        if (
            all(
                item.execution_route is LogicalExecutionRoute.SEMANTIC_SQL
                for item in logical_task.execution_steps
            )
            or self.task.capability is not logical_task.execution_steps[-1].capability
            or self.task.required_evidence_fields != logical_task.evidence_requirements
        ):
            raise ValueError("SEMANTIC_TOOL_TASK_MISMATCH")
        return self


SemanticExecutorRequest = Annotated[
    SemanticSqlTaskExecutionInput | SemanticToolTaskExecutionInput,
    Field(discriminator="request_kind"),
]


__all__ = [
    "BindingTypeInput",
    "SemanticExecutionInputBase",
    "SemanticExecutorRequest",
    "SemanticSqlTaskExecutionInput",
    "SemanticToolTaskExecutionInput",
    "semantic_binding_value_type",
    "semantic_execution_task_id",
]

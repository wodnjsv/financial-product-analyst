from datetime import date

from pydantic import Field, model_validator

from .base import ContractModel, ContractValue, Identifier, RuntimeArtifact, Sha256Hex
from .enums import Capability, ResultType, ToolStatus
from .query import BindingSpec
from .validation import require_acyclic_edges, require_known_ids, require_unique_ids


class NamedValue(ContractModel):
    name: Identifier
    value: ContractValue


class ExecutionTask(ContractModel):
    task_id: Identifier
    capability: Capability
    operation_id: Identifier
    literal_inputs: tuple[NamedValue, ...] = ()
    binding_inputs: tuple[Identifier, ...] = ()
    depends_on: tuple[Identifier, ...] = ()
    expected_output_type: ResultType
    required_evidence_fields: tuple[Identifier, ...]
    budget_ms: int = Field(gt=0)


class ExecutionGraph(RuntimeArtifact):
    graph_id: Identifier
    tasks: tuple[ExecutionTask, ...]
    binding_specs: tuple[BindingSpec, ...] = ()
    critical_path: tuple[Identifier, ...]
    total_budget_ms: int = Field(ge=0, le=55_000)

    @model_validator(mode="after")
    def validate_graph(self) -> "ExecutionGraph":
        task_ids = tuple(task.task_id for task in self.tasks)
        require_unique_ids(task_ids, label="tasks")
        require_acyclic_edges(
            task_ids,
            (
                (dependency_id, task.task_id)
                for task in self.tasks
                for dependency_id in task.depends_on
            ),
        )
        require_known_ids(
            self.critical_path,
            task_ids,
            label="critical path",
        )
        if any(task.budget_ms > self.total_budget_ms for task in self.tasks):
            raise ValueError("task budget must not exceed total budget")
        return self


class ResultField(ContractModel):
    field_id: Identifier
    value: ContractValue
    unit_id: Identifier | None = None
    currency: str | None = None
    applicable_date: date | None = None


class ResultRow(ContractModel):
    row_id: Identifier
    entity_ids: tuple[Identifier, ...]
    fields: tuple[ResultField, ...]


class BindingValue(ContractModel):
    binding_name: Identifier
    value_type: Identifier
    value: ContractValue


class Exclusion(ContractModel):
    subject_id: Identifier
    rule_id: Identifier
    reason_code: Identifier


class ResultWarning(ContractModel):
    warning_code: Identifier
    related_ids: tuple[Identifier, ...] = ()


class ToolResult(RuntimeArtifact):
    task_id: Identifier
    status: ToolStatus
    result_type: ResultType
    result_rows: tuple[ResultRow, ...] = ()
    binding_values: tuple[BindingValue, ...] = ()
    evidence_refs: tuple[Identifier, ...] = ()
    exclusions: tuple[Exclusion, ...] = ()
    warnings: tuple[ResultWarning, ...] = ()
    result_hash: Sha256Hex
    latency_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_result(self) -> "ToolResult":
        for row in self.result_rows:
            require_unique_ids(
                (field.field_id for field in row.fields),
                label="result row fields",
            )
        require_unique_ids(
            (binding.binding_name for binding in self.binding_values),
            label="binding values",
        )
        return self

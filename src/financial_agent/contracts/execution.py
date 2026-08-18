from datetime import date

from pydantic import Field, model_validator

from .base import ContractModel, Identifier, RuntimeArtifact, Sha256Hex
from .enums import Capability, ResultType, ToolStatus
from .query import BindingSpec
from .validation import require_acyclic_edges, require_known_ids, require_unique_ids
from .values import ContractValue


class NamedValue(ContractModel):
    name: Identifier
    value: ContractValue


class ExecutionTask(ContractModel):
    task_id: Identifier
    subtask_id: Identifier
    capability: Capability
    operation_id: Identifier
    literal_inputs: tuple[NamedValue, ...] = ()
    binding_inputs: tuple[Identifier, ...] = ()
    produces_bindings: tuple[Identifier, ...] = ()
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
        binding_names = tuple(
            binding.binding_name for binding in self.binding_specs
        )
        require_unique_ids(task_ids, label="tasks")
        require_unique_ids(binding_names, label="bindings")
        require_acyclic_edges(
            task_ids,
            (
                (dependency_id, task.task_id)
                for task in self.tasks
                for dependency_id in task.depends_on
            ),
        )
        for task in self.tasks:
            require_unique_ids(task.binding_inputs, label="task binding inputs")
            require_unique_ids(
                task.produces_bindings,
                label="task binding outputs",
            )
            require_known_ids(
                task.binding_inputs,
                binding_names,
                label="task binding inputs",
            )
            require_known_ids(
                task.produces_bindings,
                binding_names,
                label="task binding outputs",
            )
            if set(task.binding_inputs) & set(task.produces_bindings):
                raise ValueError("task cannot consume and produce the same binding")

        produced_bindings = tuple(
            binding_name
            for task in self.tasks
            for binding_name in task.produces_bindings
        )
        require_unique_ids(produced_bindings, label="binding producers")
        missing_producers = sorted(set(binding_names) - set(produced_bindings))
        if missing_producers:
            raise ValueError(f"bindings have no producer: {missing_producers}")

        tasks_by_id = {task.task_id: task for task in self.tasks}
        binding_specs_by_name = {
            binding.binding_name: binding for binding in self.binding_specs
        }
        producer_by_binding = {
            binding_name: task
            for task in self.tasks
            for binding_name in task.produces_bindings
        }
        for binding_name, producer in producer_by_binding.items():
            if (
                producer.subtask_id
                != binding_specs_by_name[binding_name].producer_subtask_id
            ):
                raise ValueError("binding producer must belong to its subtask")

        def dependency_ancestors(task_id: str) -> set[str]:
            ancestors: set[str] = set()
            pending = list(tasks_by_id[task_id].depends_on)
            while pending:
                dependency_id = pending.pop()
                if dependency_id in ancestors:
                    continue
                ancestors.add(dependency_id)
                pending.extend(tasks_by_id[dependency_id].depends_on)
            return ancestors

        for task in self.tasks:
            ancestors = dependency_ancestors(task.task_id)
            for binding_name in task.binding_inputs:
                producer = producer_by_binding[binding_name]
                if producer.task_id not in ancestors:
                    raise ValueError(
                        "binding consumer must depend on its producer"
                    )

        require_unique_ids(self.critical_path, label="critical path")
        require_known_ids(
            self.critical_path,
            task_ids,
            label="critical path",
        )
        for upstream_id, downstream_id in zip(
            self.critical_path,
            self.critical_path[1:],
            strict=False,
        ):
            if upstream_id not in tasks_by_id[downstream_id].depends_on:
                raise ValueError("critical path must follow direct dependencies")
        critical_path_budget = sum(
            tasks_by_id[task_id].budget_ms for task_id in self.critical_path
        )
        if critical_path_budget > self.total_budget_ms:
            raise ValueError("critical path budget must not exceed total budget")
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
        if self.status is not ToolStatus.SUCCESS and (
            self.result_rows or self.binding_values
        ):
            raise ValueError("non-success result cannot carry successful payload")
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

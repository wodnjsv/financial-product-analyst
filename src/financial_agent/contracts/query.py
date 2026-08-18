from pydantic import model_validator

from .base import ContractModel, Identifier, RuntimeArtifact
from .enums import (
    Capability,
    Cardinality,
    InitialAnswerability,
    IntentType,
    ProductFamily,
    ReferenceMentionType,
    ReferenceTargetKind,
    ResultShape,
    SubtaskImportance,
)
from .validation import require_acyclic_edges, require_known_ids, require_unique_ids
from .values import ContractValue


class Subtask(ContractModel):
    subtask_id: Identifier
    intent_type: IntentType
    importance: SubtaskImportance
    operation_ids: tuple[Identifier, ...]


class EntityResolutionRequest(ContractModel):
    resolution_request_id: Identifier
    mention_id: Identifier
    expected_entity_types: tuple[Identifier, ...]


class ResolvedReference(ContractModel):
    reference_id: Identifier
    segment_id: Identifier
    mention_type: ReferenceMentionType
    target_kind: ReferenceTargetKind
    target_id: Identifier


class BindingSpec(ContractModel):
    binding_name: Identifier
    value_type: Identifier
    producer_subtask_id: Identifier
    cardinality: Cardinality


class DependencyEdge(ContractModel):
    upstream_subtask_id: Identifier
    downstream_subtask_id: Identifier


class FilterSpec(ContractModel):
    subtask_id: Identifier
    field_id: Identifier
    operator_id: Identifier
    value: ContractValue


class MetricSpec(ContractModel):
    subtask_id: Identifier
    metric_id: Identifier
    period_id: Identifier | None = None
    unit_id: Identifier | None = None
    currency: str | None = None
    return_type_id: Identifier | None = None


class OperationSpec(ContractModel):
    subtask_id: Identifier
    operation_id: Identifier
    parameter_ids: tuple[Identifier, ...] = ()


class AmbiguityDecision(ContractModel):
    issue_code: Identifier
    policy_id: Identifier
    outcome_id: Identifier
    disclosure_required: bool


class QueryPlan(RuntimeArtifact):
    intent_types: tuple[IntentType, ...]
    product_families: tuple[ProductFamily, ...]
    subtasks: tuple[Subtask, ...]
    entity_resolution_requests: tuple[EntityResolutionRequest, ...] = ()
    resolved_references: tuple[ResolvedReference, ...] = ()
    binding_specs: tuple[BindingSpec, ...] = ()
    dependency_edges: tuple[DependencyEdge, ...] = ()
    filters: tuple[FilterSpec, ...] = ()
    metrics: tuple[MetricSpec, ...] = ()
    operations: tuple[OperationSpec, ...]
    result_shape: ResultShape
    ambiguity_decisions: tuple[AmbiguityDecision, ...] = ()
    requested_capabilities: tuple[Capability, ...]
    initial_answerability: InitialAnswerability

    @model_validator(mode="after")
    def validate_plan(self) -> "QueryPlan":
        subtask_ids = tuple(subtask.subtask_id for subtask in self.subtasks)
        operation_ids = tuple(operation.operation_id for operation in self.operations)
        binding_names = tuple(binding.binding_name for binding in self.binding_specs)

        require_unique_ids(subtask_ids, label="subtasks")
        require_unique_ids(
            (
                request.resolution_request_id
                for request in self.entity_resolution_requests
            ),
            label="entity resolution requests",
        )
        require_unique_ids(
            (reference.reference_id for reference in self.resolved_references),
            label="resolved references",
        )
        require_unique_ids(binding_names, label="bindings")
        require_unique_ids(operation_ids, label="operations")

        nested_subtask_ids = (
            *(filter_spec.subtask_id for filter_spec in self.filters),
            *(metric.subtask_id for metric in self.metrics),
            *(operation.subtask_id for operation in self.operations),
        )
        require_known_ids(nested_subtask_ids, subtask_ids, label="nested subtasks")

        referenced_operation_ids = tuple(
            operation_id
            for subtask in self.subtasks
            for operation_id in subtask.operation_ids
        )
        require_unique_ids(referenced_operation_ids, label="subtask operation IDs")
        require_known_ids(
            referenced_operation_ids,
            operation_ids,
            label="subtask operation IDs",
        )
        require_known_ids(operation_ids, referenced_operation_ids, label="operations")
        operations_by_id = {
            operation.operation_id: operation for operation in self.operations
        }
        for subtask in self.subtasks:
            for operation_id in subtask.operation_ids:
                if operations_by_id[operation_id].subtask_id != subtask.subtask_id:
                    raise ValueError("subtask operation must belong to its subtask")

        require_known_ids(
            (binding.producer_subtask_id for binding in self.binding_specs),
            subtask_ids,
            label="binding producers",
        )
        require_known_ids(
            (
                reference.target_id
                for reference in self.resolved_references
                if reference.target_kind is ReferenceTargetKind.BINDING
            ),
            binding_names,
            label="resolved binding targets",
        )
        require_acyclic_edges(
            subtask_ids,
            (
                (edge.upstream_subtask_id, edge.downstream_subtask_id)
                for edge in self.dependency_edges
            ),
        )
        return self

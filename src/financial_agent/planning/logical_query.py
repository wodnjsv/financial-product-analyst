"""Strict, SQL-free logical artifacts for semantic query planning."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import ConfigDict, Field, model_validator

from financial_agent.contracts.base import (
    ContractModel,
    Identifier,
    RuntimeArtifact,
    Sha256Hex,
)
from financial_agent.contracts.enums import Capability, Cardinality, IntentType
from financial_agent.contracts.validation import (
    require_acyclic_edges,
    require_known_ids,
    require_unique_ids,
)
from financial_agent.intent.query_contracts import (
    AggregationSpecV2,
    CalculationSpecV2,
    ComparisonSpecV2,
    ExplanationSpecV2,
    OrderingSpecV2,
    PredicateNodeV2,
    ProjectionSpecV2,
    QueryQualifiersV2,
    QueryResultShape,
    QueryScopeV2,
    SimilaritySpecV2,
)

from .contracts import CompilationRoute


_ACTION_CAPABILITIES = {
    IntentType.LOOKUP: Capability.RDB_LOOKUP,
    IntentType.SCREEN: Capability.RDB_LOOKUP,
    IntentType.RANK: Capability.RDB_LOOKUP,
    IntentType.COMPARE: Capability.RDB_LOOKUP,
    IntentType.AGGREGATE: Capability.RDB_LOOKUP,
    IntentType.CALCULATE: Capability.FINANCIAL_CALCULATION,
    IntentType.SIMILAR: Capability.SIMILARITY,
    IntentType.EXPLAIN: Capability.RDB_LOOKUP,
}
_ACTION_RESULT_SHAPES = {
    IntentType.LOOKUP: {QueryResultShape.PRODUCT_LIST},
    IntentType.SCREEN: {QueryResultShape.PRODUCT_LIST},
    IntentType.RANK: {QueryResultShape.TOP_K},
    IntentType.COMPARE: {QueryResultShape.COMPARISON_TABLE},
    IntentType.AGGREGATE: {
        QueryResultShape.SINGLE_VALUE,
        QueryResultShape.GROUPED_TABLE,
        QueryResultShape.DISTRIBUTION,
    },
    IntentType.CALCULATE: {QueryResultShape.SINGLE_VALUE},
    IntentType.SIMILAR: {QueryResultShape.PRODUCT_LIST},
    IntentType.EXPLAIN: {QueryResultShape.EXPLANATION},
}


class _StrictModel(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class LogicalLookupOperationV2(_StrictModel):
    operation_type: Literal["lookup"] = "lookup"
    projections: ProjectionSpecV2


class LogicalScreenOperationV2(_StrictModel):
    operation_type: Literal["screen"] = "screen"
    predicate: PredicateNodeV2


class LogicalRankOperationV2(_StrictModel):
    operation_type: Literal["rank"] = "rank"
    ordering: tuple[OrderingSpecV2, ...] = Field(min_length=1, max_length=4)
    limit: int | None = Field(default=None, ge=1, le=100)
    limit_policy_id: Identifier | None = None
    predicate: PredicateNodeV2 | None = None

    @model_validator(mode="after")
    def validate_rank(self):
        if bool(self.limit) == bool(self.limit_policy_id):
            raise ValueError("RANK_LIMIT_OR_POLICY_REQUIRED")
        return self


class LogicalCompareOperationV2(_StrictModel):
    operation_type: Literal["compare"] = "compare"
    comparison: ComparisonSpecV2


class LogicalAggregateOperationV2(_StrictModel):
    operation_type: Literal["aggregate"] = "aggregate"
    aggregation: AggregationSpecV2
    predicate: PredicateNodeV2 | None = None


class LogicalCalculateOperationV2(_StrictModel):
    operation_type: Literal["calculate"] = "calculate"
    calculation: CalculationSpecV2


class LogicalSimilarOperationV2(_StrictModel):
    operation_type: Literal["similar"] = "similar"
    similarity: SimilaritySpecV2


class LogicalExplainOperationV2(_StrictModel):
    operation_type: Literal["explain"] = "explain"
    explanation: ExplanationSpecV2


LogicalQueryOperationV2: TypeAlias = Annotated[
    LogicalLookupOperationV2
    | LogicalScreenOperationV2
    | LogicalRankOperationV2
    | LogicalCompareOperationV2
    | LogicalAggregateOperationV2
    | LogicalCalculateOperationV2
    | LogicalSimilarOperationV2
    | LogicalExplainOperationV2,
    Field(discriminator="operation_type"),
]


class PriorResultInputV2(_StrictModel):
    binding_id: Identifier
    producer_task_id: Identifier
    cardinality: Cardinality = Field(strict=False)


class ProducedResultBindingV2(_StrictModel):
    binding_id: Identifier
    cardinality: Cardinality = Field(strict=False)


class LogicalQueryTaskV2(_StrictModel):
    task_id: Identifier
    frame_id: Identifier
    candidate_id: Identifier
    contract_hash: Sha256Hex
    contract_variant_id: Identifier
    action_id: IntentType = Field(strict=False)
    capability: Capability = Field(strict=False)
    scope: QueryScopeV2
    qualifiers: QueryQualifiersV2
    result_shape: QueryResultShape = Field(strict=False)
    operation: LogicalQueryOperationV2
    binding_ids: tuple[Identifier, ...]
    policy_ids: tuple[Identifier, ...]
    evidence_requirements: tuple[Identifier, ...]
    prior_result_inputs: tuple[PriorResultInputV2, ...]
    produced_result_bindings: tuple[ProducedResultBindingV2, ...]

    @model_validator(mode="after")
    def validate_task(self):
        if self.operation.operation_type != self.action_id.value:
            raise ValueError("LOGICAL_OPERATION_ACTION_MISMATCH")
        if self.capability is not _ACTION_CAPABILITIES[self.action_id]:
            raise ValueError("LOGICAL_ACTION_CAPABILITY_MISMATCH")
        if self.result_shape not in _ACTION_RESULT_SHAPES[self.action_id]:
            raise ValueError("LOGICAL_ACTION_RESULT_SHAPE_MISMATCH")
        if bool(self.scope.prior_result_binding) != bool(self.prior_result_inputs):
            raise ValueError("PRIOR_RESULT_INPUT_MISMATCH")
        if self.scope.prior_result_binding and (
            len(self.prior_result_inputs) != 1
            or self.prior_result_inputs[0].binding_id != self.scope.prior_result_binding
        ):
            raise ValueError("PRIOR_RESULT_INPUT_MISMATCH")
        require_unique_ids(self.binding_ids, label="logical binding IDs")
        require_unique_ids(self.policy_ids, label="logical policy IDs")
        require_unique_ids(self.evidence_requirements, label="evidence requirements")
        require_unique_ids(
            (item.binding_id for item in self.produced_result_bindings),
            label="produced result bindings",
        )
        return self


class LogicalDependencyV2(_StrictModel):
    upstream_task_id: Identifier
    downstream_task_id: Identifier
    binding_id: Identifier


class SemanticLoweringRecordV2(_StrictModel):
    candidate_id: Identifier
    task_id: Identifier
    preserved_semantic_paths: tuple[Identifier, ...]
    binding_ids: tuple[Identifier, ...]
    policy_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_record(self):
        require_unique_ids(self.preserved_semantic_paths, label="preserved semantic paths")
        require_unique_ids(self.binding_ids, label="lowering binding IDs")
        require_unique_ids(self.policy_ids, label="lowering policy IDs")
        return self


class LogicalQueryPlanV2(RuntimeArtifact):
    logical_plan_version: Literal["2.0"] = "2.0"
    logical_plan_id: Identifier
    query_contract_id: Identifier
    resolution_id: Identifier
    route: CompilationRoute = Field(strict=False)
    tasks: tuple[LogicalQueryTaskV2, ...] = Field(min_length=1, max_length=16)
    dependencies: tuple[LogicalDependencyV2, ...]
    applied_policy_ids: tuple[Identifier, ...]
    binding_registry_version: Identifier
    binding_registry_hash: Sha256Hex
    physical_policy_registry_version: Identifier
    physical_policy_registry_hash: Sha256Hex
    contract_registry_version: Identifier
    contract_registry_hash: Sha256Hex
    planning_registry_version: Identifier
    planning_registry_hash: Sha256Hex
    dataset_pin: Sha256Hex
    lowering_records: tuple[SemanticLoweringRecordV2, ...]

    @model_validator(mode="after")
    def validate_plan(self):
        if self.route not in {CompilationRoute.FAST, CompilationRoute.COMPOSE}:
            raise ValueError("LOGICAL_PLAN_REQUIRES_EXECUTABLE_ROUTE")
        task_ids = tuple(item.task_id for item in self.tasks)
        candidate_ids = tuple(item.candidate_id for item in self.tasks)
        require_unique_ids(task_ids, label="logical tasks")
        require_unique_ids(candidate_ids, label="logical candidates")
        require_unique_ids(self.applied_policy_ids, label="applied policy IDs")
        require_known_ids(
            (edge.upstream_task_id for edge in self.dependencies), task_ids,
            label="logical dependency upstream tasks",
        )
        require_known_ids(
            (edge.downstream_task_id for edge in self.dependencies), task_ids,
            label="logical dependency downstream tasks",
        )
        require_acyclic_edges(
            task_ids,
            ((edge.upstream_task_id, edge.downstream_task_id) for edge in self.dependencies),
        )
        dependency_keys = {
            (edge.upstream_task_id, edge.downstream_task_id, edge.binding_id)
            for edge in self.dependencies
        }
        required_keys = {
            (item.producer_task_id, task.task_id, item.binding_id)
            for task in self.tasks
            for item in task.prior_result_inputs
        }
        if dependency_keys != required_keys:
            raise ValueError("LOGICAL_DEPENDENCY_REQUIRED")
        produced_keys = {
            (task.task_id, item.binding_id, item.cardinality)
            for task in self.tasks
            for item in task.produced_result_bindings
        }
        consumed_keys = {
            (item.producer_task_id, item.binding_id, item.cardinality)
            for task in self.tasks
            for item in task.prior_result_inputs
        }
        if produced_keys != consumed_keys:
            raise ValueError("LOGICAL_RESULT_BINDING_OWNERSHIP_MISMATCH")
        if set(self.applied_policy_ids) != {
            policy_id for task in self.tasks for policy_id in task.policy_ids
        }:
            raise ValueError("APPLIED_POLICY_OWNERSHIP_MISMATCH")
        records_by_candidate = {item.candidate_id: item for item in self.lowering_records}
        if (
            len(records_by_candidate) != len(self.lowering_records)
            or set(records_by_candidate) != set(candidate_ids)
            or any(
                records_by_candidate[task.candidate_id].task_id != task.task_id
                for task in self.tasks
            )
        ):
            raise ValueError("LOWERING_RECORD_OWNERSHIP_MISMATCH")
        if any(
            records_by_candidate[task.candidate_id].binding_ids != task.binding_ids
            or records_by_candidate[task.candidate_id].policy_ids != task.policy_ids
            for task in self.tasks
        ):
            raise ValueError("LOWERING_RECORD_OWNERSHIP_MISMATCH")
        return self

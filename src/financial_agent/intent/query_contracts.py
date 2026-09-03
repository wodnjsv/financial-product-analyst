"""Strict action-specific semantic query contracts for the V2 query path."""

from __future__ import annotations

from datetime import date as DateValueType
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import ConfigDict, Field, model_validator

from financial_agent.contracts.base import (
    ContractModel,
    Identifier,
    RuntimeArtifact,
    Sha256Hex,
    UtcDateTime,
)
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.contracts.values import DECIMAL_PATTERN


MAX_FRAMES = 16
MAX_PREDICATE_ATOMS = 8
MAX_PREDICATE_DEPTH = 3
MAX_PROJECTIONS = 8
MAX_ORDER_TERMS = 4
CanonicalDecimalText = Annotated[str, Field(pattern=DECIMAL_PATTERN)]


class AxisReadiness(str, Enum):
    COMPLETE = "complete"
    AMBIGUOUS = "ambiguous"
    BLOCKED = "blocked"


class ContractReadiness(str, Enum):
    COMPLETE = "complete"
    AMBIGUOUS = "ambiguous"
    BLOCKED = "blocked"


class PlanReadiness(str, Enum):
    EXECUTABLE = "executable"
    EXPLORABLE = "explorable"
    LIMITED = "limited"
    BLOCKED = "blocked"


class SemanticValueKind(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    IDENTIFIER = "identifier"


class QueryOperatorId(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    BETWEEN = "between"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    IS_MISSING = "is_missing"
    IS_PRESENT = "is_present"


class OrderingDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class AggregationFunction(str, Enum):
    SUM = "sum"
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    DISTRIBUTION = "distribution"


def is_population_count(function_id: AggregationFunction) -> bool:
    return function_id in {
        AggregationFunction.COUNT,
        AggregationFunction.COUNT_DISTINCT,
    }


class AggregationBucketPolicyId(str, Enum):
    EQUAL_WIDTH_10 = "equal-width-10.v1"


class QueryResultShape(str, Enum):
    PRODUCT_LIST = "product_list"
    TOP_K = "top_k"
    COMPARISON_TABLE = "comparison_table"
    SINGLE_VALUE = "single_value"
    GROUPED_TABLE = "grouped_table"
    DISTRIBUTION = "distribution"
    EXPLANATION = "explanation"


class ProvenanceSourceKind(str, Enum):
    EXACT_LOCK = "exact_lock"
    MODEL_SEMANTIC_LINK = "model_semantic_link"
    AXIS_RESOLUTION = "axis_resolution"
    REGISTRY_DEFAULT = "registry_default"
    PRIOR_RESULT = "prior_result"


class _StrictContractModel(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class QueryScopeV2(_StrictContractModel):
    product_family_ids: tuple[ProductFamily, ...] = Field(default=(), max_length=4)
    entity_refs: tuple[Identifier, ...] = Field(default=(), max_length=16)
    prior_result_binding: Identifier | None = None

    @model_validator(mode="after")
    def require_one_unique_scope(self) -> Self:
        if not (self.product_family_ids or self.entity_refs or self.prior_result_binding):
            raise ValueError("QUERY_SCOPE_REQUIRED")
        _require_unique(self.product_family_ids, "DUPLICATE_PRODUCT_FAMILY_ID")
        _require_unique(self.entity_refs, "DUPLICATE_ENTITY_REF")
        return self


class ProjectionSpecV2(_StrictContractModel):
    field_concept_ids: tuple[Identifier, ...] = Field(default=(), max_length=MAX_PROJECTIONS)
    default_profile_id: Identifier | None = None

    @model_validator(mode="after")
    def require_one_projection_source(self) -> Self:
        _require_unique(self.field_concept_ids, "DUPLICATE_PROJECTION_ID")
        if bool(self.field_concept_ids) == bool(self.default_profile_id):
            raise ValueError("PROJECTION_OR_PROFILE_REQUIRED")
        return self


class TypedSemanticValue(_StrictContractModel):
    kind: SemanticValueKind = Field(strict=False)
    string: str | None = None
    integer: int | None = None
    decimal: CanonicalDecimalText | None = None
    boolean: bool | None = None
    date: DateValueType | None = None
    datetime: UtcDateTime | None = None
    identifier: Identifier | None = None
    unit_id: Identifier | None = None

    @model_validator(mode="after")
    def require_matching_value(self) -> Self:
        values = {
            SemanticValueKind.STRING: self.string,
            SemanticValueKind.INTEGER: self.integer,
            SemanticValueKind.DECIMAL: self.decimal,
            SemanticValueKind.BOOLEAN: self.boolean,
            SemanticValueKind.DATE: self.date,
            SemanticValueKind.DATETIME: self.datetime,
            SemanticValueKind.IDENTIFIER: self.identifier,
        }
        if values[self.kind] is None or sum(value is not None for value in values.values()) != 1:
            raise ValueError("TYPED_SEMANTIC_VALUE_MISMATCH")
        return self


class PredicateAtomV2(_StrictContractModel):
    node_type: Literal["atom"] = "atom"
    field_concept_id: Identifier
    operator_id: QueryOperatorId
    value: TypedSemanticValue | None = None
    values: tuple[TypedSemanticValue, ...] = Field(default=(), max_length=8)
    null_policy_id: Identifier

    @model_validator(mode="after")
    def validate_operator_arity(self) -> Self:
        if self.operator_id in {QueryOperatorId.IS_MISSING, QueryOperatorId.IS_PRESENT}:
            valid = self.value is None and not self.values
        elif self.operator_id is QueryOperatorId.BETWEEN:
            valid = self.value is None and len(self.values) == 2
        elif self.operator_id in {QueryOperatorId.IN, QueryOperatorId.NOT_IN}:
            valid = self.value is None and bool(self.values)
        else:
            valid = self.value is not None and not self.values
        if not valid:
            raise ValueError("PREDICATE_VALUE_ARITY_MISMATCH")
        ordered_kinds = {
            SemanticValueKind.INTEGER,
            SemanticValueKind.DECIMAL,
            SemanticValueKind.DATE,
            SemanticValueKind.DATETIME,
        }
        actual_values = (self.value,) if self.value is not None else self.values
        if self.operator_id in {
            QueryOperatorId.LT,
            QueryOperatorId.LTE,
            QueryOperatorId.GT,
            QueryOperatorId.GTE,
            QueryOperatorId.BETWEEN,
        } and any(item.kind not in ordered_kinds for item in actual_values):
            raise ValueError("PREDICATE_OPERATOR_VALUE_KIND_MISMATCH")
        if (
            self.operator_id is QueryOperatorId.CONTAINS
            and self.value is not None
            and self.value.kind is not SemanticValueKind.STRING
        ):
            raise ValueError("PREDICATE_OPERATOR_VALUE_KIND_MISMATCH")
        if self.values and len({(item.kind, item.unit_id) for item in self.values}) != 1:
            raise ValueError("PREDICATE_VALUE_SET_TYPE_MISMATCH")
        return self


class PredicateAllOfV2(_StrictContractModel):
    node_type: Literal["all_of"] = "all_of"
    children: tuple["PredicateNodeV2", ...] = Field(min_length=1)


class PredicateAnyOfV2(_StrictContractModel):
    node_type: Literal["any_of"] = "any_of"
    children: tuple["PredicateNodeV2", ...] = Field(min_length=1)


class PredicateNotV2(_StrictContractModel):
    node_type: Literal["not"] = "not"
    child: "PredicateNodeV2"


PredicateNodeV2: TypeAlias = Annotated[
    PredicateAtomV2 | PredicateAllOfV2 | PredicateAnyOfV2 | PredicateNotV2,
    Field(discriminator="node_type"),
]


class OrderingSpecV2(_StrictContractModel):
    field_concept_id: Identifier
    direction: OrderingDirection | None = None
    direction_policy_id: Identifier | None = None
    nulls_policy_id: Identifier
    tie_break_policy_id: Identifier

    @model_validator(mode="after")
    def require_direction_or_default(self) -> Self:
        if bool(self.direction) == bool(self.direction_policy_id):
            raise ValueError("ORDERING_DIRECTION_OR_POLICY_REQUIRED")
        return self


class AggregationSpecV2(_StrictContractModel):
    function_id: AggregationFunction
    target_field_concept_id: Identifier | None = None
    count_population_id: Identifier | None = None
    group_by_field_concept_ids: tuple[Identifier, ...] = Field(default=(), max_length=8)
    bucket_policy_id: AggregationBucketPolicyId | None = None
    population_grain_id: Identifier
    dedup_policy_id: Identifier

    @model_validator(mode="after")
    def require_complete_aggregation(self) -> Self:
        _require_unique(self.group_by_field_concept_ids, "DUPLICATE_GROUP_BY_ID")
        if bool(self.target_field_concept_id) == bool(self.count_population_id):
            raise ValueError("AGGREGATION_TARGET_OR_COUNT_POPULATION_REQUIRED")
        if is_population_count(self.function_id) and self.target_field_concept_id:
            raise ValueError("COUNT_POPULATION_REQUIRED")
        if not is_population_count(self.function_id) and self.count_population_id:
            raise ValueError("AGGREGATION_TARGET_REQUIRED")
        return self


class ComparisonSpecV2(_StrictContractModel):
    subject_refs: tuple[Identifier, ...] = Field(default=(), max_length=16)
    group_basis_id: Identifier | None = None
    metric_concept_ids: tuple[Identifier, ...] = Field(default=(), max_length=8)
    projection_profile_id: Identifier | None = None
    basis_policy_id: Identifier
    normalization_policy_id: Identifier | None = None

    @model_validator(mode="after")
    def require_complete_comparison(self) -> Self:
        _require_unique(self.subject_refs, "DUPLICATE_COMPARISON_SUBJECT")
        _require_unique(self.metric_concept_ids, "DUPLICATE_COMPARISON_METRIC")
        if not (len(self.subject_refs) >= 2 or self.group_basis_id):
            raise ValueError("COMPARISON_SUBJECTS_REQUIRED")
        if bool(self.metric_concept_ids) == bool(self.projection_profile_id):
            raise ValueError("COMPARISON_METRIC_OR_PROFILE_REQUIRED")
        return self


class CalculationOperandV2(_StrictContractModel):
    role_id: Identifier
    value_ref: Identifier | None = None
    field_concept_id: Identifier | None = None

    @model_validator(mode="after")
    def require_one_operand_source(self) -> Self:
        if bool(self.value_ref) == bool(self.field_concept_id):
            raise ValueError("CALCULATION_OPERAND_SOURCE_REQUIRED")
        return self


class CalculationSpecV2(_StrictContractModel):
    recipe_id: Identifier
    operands: tuple[CalculationOperandV2, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def require_unique_roles(self) -> Self:
        _require_unique(
            tuple(operand.role_id for operand in self.operands),
            "DUPLICATE_OPERAND_ROLE",
        )
        return self


class SimilaritySpecV2(_StrictContractModel):
    anchor_ref: Identifier
    policy_id: Identifier
    dimension_concept_ids: tuple[Identifier, ...] = Field(default=(), max_length=8)
    default_profile_id: Identifier | None = None
    coverage_threshold: CanonicalDecimalText
    limit: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def require_dimensions_and_valid_coverage(self) -> Self:
        _require_unique(self.dimension_concept_ids, "DUPLICATE_SIMILARITY_DIMENSION")
        if bool(self.dimension_concept_ids) == bool(self.default_profile_id):
            raise ValueError("SIMILARITY_DIMENSIONS_OR_PROFILE_REQUIRED")
        threshold = Decimal(self.coverage_threshold)
        if threshold < 0 or threshold > 1:
            raise ValueError("SIMILARITY_COVERAGE_OUT_OF_RANGE")
        return self


class ExplanationSpecV2(_StrictContractModel):
    topic_concept_id: Identifier | None = None
    profile_id: Identifier | None = None

    @model_validator(mode="after")
    def require_topic_or_profile(self) -> Self:
        if bool(self.topic_concept_id) == bool(self.profile_id):
            raise ValueError("EXPLANATION_TOPIC_OR_PROFILE_REQUIRED")
        return self


class QueryQualifiersV2(_StrictContractModel):
    period_id: Identifier | None = None
    currency_id: Identifier | None = None
    unit_id: Identifier | None = None
    as_of_date: DateValueType | None = None


class ResolvedInputProvenanceV2(_StrictContractModel):
    semantic_input_id: Identifier
    source_kind: ProvenanceSourceKind
    source_ref: Identifier


class QueryRegistryPinsV2(_StrictContractModel):
    contract_registry_version: Identifier
    contract_registry_hash: Sha256Hex
    operator_registry_version: Identifier
    operator_registry_hash: Sha256Hex
    policy_registry_version: Identifier
    policy_registry_hash: Sha256Hex


class AxisReadinessRecordV2(_StrictContractModel):
    readiness: AxisReadiness
    reason_codes: tuple[Identifier, ...]


class ContractReadinessRecordV2(_StrictContractModel):
    readiness: ContractReadiness
    reason_codes: tuple[Identifier, ...]


class PlanReadinessRecordV2(_StrictContractModel):
    readiness: PlanReadiness
    reason_codes: tuple[Identifier, ...]


class QueryContractSemanticBaseV2(_StrictContractModel):
    contract_schema_version: Literal["2.0"] = "2.0"
    contract_variant_id: Identifier
    frame_id: Identifier
    action_id: IntentType
    scope: QueryScopeV2
    qualifiers: QueryQualifiersV2
    result_shape: QueryResultShape
    provenance: tuple[ResolvedInputProvenanceV2, ...] = Field(min_length=1)
    registry_pins: QueryRegistryPinsV2

    @model_validator(mode="after")
    def require_unique_provenance(self) -> Self:
        _require_unique(
            tuple(item.semantic_input_id for item in self.provenance),
            "DUPLICATE_PROVENANCE_INPUT_ID",
        )
        return self


class _LookupQueryContractCandidateV2(QueryContractSemanticBaseV2):
    action_id: Literal[IntentType.LOOKUP]
    projections: ProjectionSpecV2

    @model_validator(mode="after")
    def require_lookup_shape(self) -> Self:
        _require_variant(self, {"lookup.projection.v2"}, {QueryResultShape.PRODUCT_LIST})
        return self


class _ScreenQueryContractCandidateV2(QueryContractSemanticBaseV2):
    action_id: Literal[IntentType.SCREEN]
    predicate: PredicateNodeV2

    @model_validator(mode="after")
    def require_complete_predicate(self) -> Self:
        _require_variant(self, {"screen.predicate.v2"}, {QueryResultShape.PRODUCT_LIST})
        _validate_predicate_bounds(self.predicate)
        return self


class _RankQueryContractCandidateV2(QueryContractSemanticBaseV2):
    action_id: Literal[IntentType.RANK]
    ordering: tuple[OrderingSpecV2, ...] = Field(min_length=1, max_length=MAX_ORDER_TERMS)
    limit: int | None = Field(default=None, ge=1, le=100)
    limit_policy_id: Identifier | None = None
    predicate: PredicateNodeV2 | None = None

    @model_validator(mode="after")
    def require_rank_shape(self) -> Self:
        _require_variant(self, {"rank.ordering.v2"}, {QueryResultShape.TOP_K})
        if bool(self.limit) == bool(self.limit_policy_id):
            raise ValueError("RANK_LIMIT_OR_POLICY_REQUIRED")
        if self.predicate is not None:
            _validate_predicate_bounds(self.predicate)
        return self


class _CompareQueryContractCandidateV2(QueryContractSemanticBaseV2):
    action_id: Literal[IntentType.COMPARE]
    comparison: ComparisonSpecV2

    @model_validator(mode="after")
    def require_compare_shape(self) -> Self:
        _require_variant(self, {"compare.subjects.v2"}, {QueryResultShape.COMPARISON_TABLE})
        return self


class _AggregateQueryContractCandidateV2(QueryContractSemanticBaseV2):
    action_id: Literal[IntentType.AGGREGATE]
    aggregation: AggregationSpecV2
    predicate: PredicateNodeV2 | None = None

    @model_validator(mode="after")
    def require_aggregate_shape(self) -> Self:
        allowed = {
            "aggregate.scalar.v2": {QueryResultShape.SINGLE_VALUE},
            "aggregate.grouped.v2": {QueryResultShape.GROUPED_TABLE},
            "aggregate.distribution.v2": {QueryResultShape.DISTRIBUTION},
        }
        if (
            self.contract_variant_id not in allowed
            or self.result_shape not in allowed[self.contract_variant_id]
        ):
            raise ValueError("CONTRACT_VARIANT_OR_RESULT_SHAPE_MISMATCH")
        if (
            self.contract_variant_id == "aggregate.grouped.v2"
            and not self.aggregation.group_by_field_concept_ids
        ):
            raise ValueError("GROUPED_AGGREGATION_GROUP_REQUIRED")
        if self.contract_variant_id == "aggregate.scalar.v2" and (
            self.aggregation.group_by_field_concept_ids
            or self.aggregation.bucket_policy_id
        ):
            raise ValueError("SCALAR_AGGREGATION_FIELDS_FORBIDDEN")
        if (
            self.contract_variant_id == "aggregate.grouped.v2"
            and self.aggregation.bucket_policy_id
        ):
            raise ValueError("GROUPED_BUCKET_POLICY_FORBIDDEN")
        if (
            self.contract_variant_id == "aggregate.distribution.v2"
            and self.aggregation.function_id is not AggregationFunction.DISTRIBUTION
        ):
            raise ValueError("DISTRIBUTION_FUNCTION_REQUIRED")
        if (
            self.contract_variant_id != "aggregate.distribution.v2"
            and self.aggregation.function_id is AggregationFunction.DISTRIBUTION
        ):
            raise ValueError("DISTRIBUTION_VARIANT_REQUIRED")
        if self.contract_variant_id == "aggregate.distribution.v2" and (
            bool(self.aggregation.group_by_field_concept_ids)
            == bool(self.aggregation.bucket_policy_id)
        ):
            raise ValueError("DISTRIBUTION_GROUP_OR_BUCKET_REQUIRED")
        if self.predicate is not None:
            _validate_predicate_bounds(self.predicate)
        return self


class _CalculateQueryContractCandidateV2(QueryContractSemanticBaseV2):
    action_id: Literal[IntentType.CALCULATE]
    calculation: CalculationSpecV2

    @model_validator(mode="after")
    def require_calculate_shape(self) -> Self:
        _require_variant(self, {"calculate.recipe.v2"}, {QueryResultShape.SINGLE_VALUE})
        return self


class _SimilarQueryContractCandidateV2(QueryContractSemanticBaseV2):
    action_id: Literal[IntentType.SIMILAR]
    similarity: SimilaritySpecV2

    @model_validator(mode="after")
    def require_similar_shape(self) -> Self:
        _require_variant(self, {"similar.policy.v2"}, {QueryResultShape.PRODUCT_LIST})
        return self


class _ExplainQueryContractCandidateV2(QueryContractSemanticBaseV2):
    action_id: Literal[IntentType.EXPLAIN]
    explanation: ExplanationSpecV2

    @model_validator(mode="after")
    def require_explain_shape(self) -> Self:
        _require_variant(self, {"explain.topic.v2"}, {QueryResultShape.EXPLANATION})
        return self


SolvedQueryContractCandidateV2: TypeAlias = Annotated[
    _LookupQueryContractCandidateV2
    | _ScreenQueryContractCandidateV2
    | _RankQueryContractCandidateV2
    | _CompareQueryContractCandidateV2
    | _AggregateQueryContractCandidateV2
    | _CalculateQueryContractCandidateV2
    | _SimilarQueryContractCandidateV2
    | _ExplainQueryContractCandidateV2,
    Field(discriminator="action_id"),
]


class _ReadinessMixin(_StrictContractModel):
    axis_readiness: AxisReadinessRecordV2
    contract_readiness: ContractReadinessRecordV2
    plan_readiness: PlanReadinessRecordV2


class LookupQueryContractV2(_LookupQueryContractCandidateV2, _ReadinessMixin):
    pass


class ScreenQueryContractV2(_ScreenQueryContractCandidateV2, _ReadinessMixin):
    pass


class RankQueryContractV2(_RankQueryContractCandidateV2, _ReadinessMixin):
    pass


class CompareQueryContractV2(_CompareQueryContractCandidateV2, _ReadinessMixin):
    pass


class AggregateQueryContractV2(_AggregateQueryContractCandidateV2, _ReadinessMixin):
    pass


class CalculateQueryContractV2(_CalculateQueryContractCandidateV2, _ReadinessMixin):
    pass


class SimilarQueryContractV2(_SimilarQueryContractCandidateV2, _ReadinessMixin):
    pass


class ExplainQueryContractV2(_ExplainQueryContractCandidateV2, _ReadinessMixin):
    pass


ResolvedQueryContractV2: TypeAlias = Annotated[
    LookupQueryContractV2
    | ScreenQueryContractV2
    | RankQueryContractV2
    | CompareQueryContractV2
    | AggregateQueryContractV2
    | CalculateQueryContractV2
    | SimilarQueryContractV2
    | ExplainQueryContractV2,
    Field(discriminator="action_id"),
]


class ResolvedQueryContractBundleV2(_StrictContractModel):
    contracts: tuple[ResolvedQueryContractV2, ...] = Field(min_length=1, max_length=MAX_FRAMES)

    @model_validator(mode="after")
    def require_unique_frames(self) -> Self:
        _require_unique(
            tuple(contract.frame_id for contract in self.contracts),
            "DUPLICATE_FRAME_ID",
        )
        return self


class QueryContractSelectionProvenanceV2(_StrictContractModel):
    frame_id: Identifier
    selected_candidate_id: Identifier
    selection_method: Literal[
        "unique", "deterministic_tie_break", "hcx_offered_id"
    ]
    judge_prompt_version: Identifier | None = None

    @model_validator(mode="after")
    def require_prompt_only_for_model_judge(self) -> Self:
        if (self.selection_method == "hcx_offered_id") != bool(
            self.judge_prompt_version
        ):
            raise ValueError("JUDGE_PROMPT_PROVENANCE_MISMATCH")
        return self


class QueryContractFrameReadinessV2(_StrictContractModel):
    frame_id: Identifier
    axis: AxisReadinessRecordV2
    contract: ContractReadinessRecordV2
    plan: PlanReadinessRecordV2


class ResolvedQueryContractSetV2(RuntimeArtifact):
    """Persistable, self-validating V2 semantic-query contract artifact."""

    query_contract_version: Literal["2.0"] = "2.0"
    query_contract_id: Identifier
    resolution_id: Identifier
    contracts: tuple[ResolvedQueryContractV2, ...] = Field(
        min_length=1, max_length=MAX_FRAMES
    )
    registry_pins: QueryRegistryPinsV2
    judge_provenance: tuple[QueryContractSelectionProvenanceV2, ...] = Field(
        min_length=1, max_length=MAX_FRAMES
    )
    readiness: tuple[QueryContractFrameReadinessV2, ...] = Field(
        min_length=1, max_length=MAX_FRAMES
    )

    @model_validator(mode="after")
    def validate_contract_set(self) -> Self:
        frame_ids = tuple(contract.frame_id for contract in self.contracts)
        _require_unique(frame_ids, "DUPLICATE_FRAME_ID")
        if tuple(item.frame_id for item in self.judge_provenance) != frame_ids:
            raise ValueError("CONTRACT_SELECTION_OWNERSHIP_MISMATCH")
        if any(
            provenance.selected_candidate_id
            != query_contract_candidate_id(contract)
            for contract, provenance in zip(
                self.contracts, self.judge_provenance, strict=True
            )
        ):
            raise ValueError("CONTRACT_SELECTION_CANDIDATE_MISMATCH")
        if tuple(item.frame_id for item in self.readiness) != frame_ids:
            raise ValueError("CONTRACT_READINESS_OWNERSHIP_MISMATCH")
        if any(
            contract.registry_pins != self.registry_pins
            for contract in self.contracts
        ):
            raise ValueError("CONTRACT_REGISTRY_PIN_MISMATCH")
        if any(
            contract.axis_readiness != readiness.axis
            or contract.contract_readiness != readiness.contract
            or contract.plan_readiness != readiness.plan
            for contract, readiness in zip(
                self.contracts, self.readiness, strict=True
            )
        ):
            raise ValueError("CONTRACT_READINESS_MISMATCH")
        expected_id = resolved_query_contract_set_id(self.contracts)
        if self.query_contract_id != expected_id:
            raise ValueError("QUERY_CONTRACT_ID_MISMATCH")
        return self


def resolved_query_contract_set_id(
    contracts: tuple[ResolvedQueryContractV2, ...],
) -> str:
    return "query-contract-bundle-" + canonical_sha256(
        ResolvedQueryContractBundleV2(contracts=contracts)
    )


def query_contract_candidate_id(contract: QueryContractSemanticBaseV2) -> str:
    """Return the canonical ID shared by solved and resolved contracts."""
    semantic_content = contract.model_dump(
        mode="json",
        exclude={
            "frame_id",
            "provenance",
            "registry_pins",
            "axis_readiness",
            "contract_readiness",
            "plan_readiness",
        },
    )
    return "query-contract-" + canonical_sha256(semantic_content)


def predicate_atom_count(predicate: PredicateNodeV2) -> int:
    if isinstance(predicate, PredicateAtomV2):
        return 1
    if isinstance(predicate, PredicateNotV2):
        return predicate_atom_count(predicate.child)
    return sum(predicate_atom_count(child) for child in predicate.children)


def predicate_depth(predicate: PredicateNodeV2) -> int:
    if isinstance(predicate, PredicateAtomV2):
        return 1
    if isinstance(predicate, PredicateNotV2):
        return 1 + predicate_depth(predicate.child)
    return 1 + max(predicate_depth(child) for child in predicate.children)


def _validate_predicate_bounds(predicate: PredicateNodeV2) -> None:
    if predicate_atom_count(predicate) > MAX_PREDICATE_ATOMS:
        raise ValueError("PREDICATE_ATOM_LIMIT_EXCEEDED")
    if predicate_depth(predicate) > MAX_PREDICATE_DEPTH:
        raise ValueError("PREDICATE_DEPTH_EXCEEDED")


def _require_unique(values: tuple[object, ...], reason: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(reason)


def _require_variant(
    contract: QueryContractSemanticBaseV2,
    variant_ids: set[str],
    result_shapes: set[QueryResultShape],
) -> None:
    if (
        contract.contract_variant_id not in variant_ids
        or contract.result_shape not in result_shapes
    ):
        raise ValueError("CONTRACT_VARIANT_OR_RESULT_SHAPE_MISMATCH")


for _predicate_model in (PredicateAllOfV2, PredicateAnyOfV2, PredicateNotV2):
    _predicate_model.model_rebuild(_types_namespace={"PredicateNodeV2": PredicateNodeV2})

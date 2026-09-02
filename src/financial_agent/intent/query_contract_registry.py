"""Closed, versioned registry loader for V2 semantic query contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from pydantic import Field, ValidationError

from financial_agent.contracts.base import Identifier, Sha256Hex
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import IntentType

from .query_contracts import (
    QueryOperatorId,
    QueryResultShape,
    SemanticValueKind,
    _StrictContractModel,
)


CONTRACT_REGISTRY_PATH = Path("config/intent/query-contract-registry.v2.json")
OPERATOR_REGISTRY_PATH = Path("config/intent/query-operator-registry.v1.json")
POLICY_REGISTRY_PATH = Path("config/intent/query-policy-registry.v1.json")
CONTRACT_REGISTRY_VERSION = "query-contract-registry.v2"
OPERATOR_REGISTRY_VERSION = "query-operator-registry.v1"
POLICY_REGISTRY_VERSION = "query-policy-registry.v1"
CONTRACT_VARIANT_ORDER = (
    "lookup.projection.v2",
    "screen.predicate.v2",
    "rank.ordering.v2",
    "compare.subjects.v2",
    "aggregate.scalar.v2",
    "aggregate.grouped.v2",
    "aggregate.distribution.v2",
    "calculate.recipe.v2",
    "similar.policy.v2",
    "explain.topic.v2",
)
OPERATOR_ORDER = (
    "eq",
    "neq",
    "lt",
    "lte",
    "gt",
    "gte",
    "between",
    "in",
    "not_in",
    "contains",
    "is_missing",
    "is_present",
)


class OperatorArity(str, Enum):
    ZERO = "zero"
    ONE = "one"
    TWO = "two"
    ONE_OR_MORE = "one_or_more"


class PolicyKind(str, Enum):
    BUCKETING = "bucketing"
    DEFAULT = "default"
    MISSINGNESS = "missingness"
    STABLE_TIE = "stable_tie"
    COMPARISON = "comparison"
    POPULATION_GRAIN = "population_grain"
    DEDUPLICATION = "deduplication"
    NORMALIZATION = "normalization"
    COVERAGE = "coverage"
    SIMILARITY = "similarity"


class OperatorDefinition(_StrictContractModel):
    id: QueryOperatorId
    allowed_value_kinds: tuple[SemanticValueKind, ...]
    arity: OperatorArity


class PolicyDefinition(_StrictContractModel):
    id: Identifier
    kind: PolicyKind


class ContractVariantDefinition(_StrictContractModel):
    id: Identifier
    action_id: IntentType
    required_components: tuple[Identifier, ...] = Field(min_length=1)
    operator_ids: tuple[QueryOperatorId, ...]
    policy_ids: tuple[Identifier, ...]
    result_shapes: tuple[QueryResultShape, ...] = Field(min_length=1)


class _OperatorRegistryPayload(_StrictContractModel):
    registry_version: Identifier
    operators: tuple[OperatorDefinition, ...] = Field(min_length=1)


class _PolicyRegistryPayload(_StrictContractModel):
    registry_version: Identifier
    policies: tuple[PolicyDefinition, ...] = Field(min_length=1)


class _ContractRegistryPayload(_StrictContractModel):
    registry_version: Identifier
    operator_registry_version: Identifier
    operator_registry_hash: Sha256Hex
    policy_registry_version: Identifier
    policy_registry_hash: Sha256Hex
    variants: tuple[ContractVariantDefinition, ...] = Field(min_length=1)


_ALL_VALUE_KINDS = tuple(SemanticValueKind)
_ORDERED_VALUE_KINDS = (
    SemanticValueKind.INTEGER,
    SemanticValueKind.DECIMAL,
    SemanticValueKind.DATE,
    SemanticValueKind.DATETIME,
)
EXPECTED_OPERATOR_DEFINITIONS = MappingProxyType(
    {
        "eq": (OperatorArity.ONE, _ALL_VALUE_KINDS),
        "neq": (OperatorArity.ONE, _ALL_VALUE_KINDS),
        "lt": (OperatorArity.ONE, _ORDERED_VALUE_KINDS),
        "lte": (OperatorArity.ONE, _ORDERED_VALUE_KINDS),
        "gt": (OperatorArity.ONE, _ORDERED_VALUE_KINDS),
        "gte": (OperatorArity.ONE, _ORDERED_VALUE_KINDS),
        "between": (OperatorArity.TWO, _ORDERED_VALUE_KINDS),
        "in": (OperatorArity.ONE_OR_MORE, _ALL_VALUE_KINDS),
        "not_in": (OperatorArity.ONE_OR_MORE, _ALL_VALUE_KINDS),
        "contains": (OperatorArity.ONE, (SemanticValueKind.STRING,)),
        "is_missing": (OperatorArity.ZERO, ()),
        "is_present": (OperatorArity.ZERO, ()),
    }
)
EXPECTED_POLICY_KINDS = MappingProxyType(
    {
        "approved-cross-family.v1": PolicyKind.NORMALIZATION,
        "cosine-complete-dimensions.v1": PolicyKind.SIMILARITY,
        "default-direction-descending.v1": PolicyKind.DEFAULT,
        "default-explanation-profile.v1": PolicyKind.DEFAULT,
        "default-limit-5.v1": PolicyKind.DEFAULT,
        "default-product-projection.v1": PolicyKind.DEFAULT,
        "distinct-entity.v1": PolicyKind.DEDUPLICATION,
        "equal-width-10.v1": PolicyKind.BUCKETING,
        "exclude_missing.v1": PolicyKind.MISSINGNESS,
        "minimum-dimension-coverage.v1": PolicyKind.COVERAGE,
        "no-dedup.v1": PolicyKind.DEDUPLICATION,
        "public-fund-representative-share.v1": PolicyKind.DEDUPLICATION,
        "representative-product.v1": PolicyKind.POPULATION_GRAIN,
        "same-definition-period-unit.v1": PolicyKind.COMPARISON,
        "source-product.v1": PolicyKind.POPULATION_GRAIN,
        "stable-product-id.v1": PolicyKind.STABLE_TIE,
    }
)
EXPECTED_VARIANT_SIGNATURES = MappingProxyType(
    {
        "lookup.projection.v2": (
            IntentType.LOOKUP,
            ("scope", "projection"),
            (),
            ("default-product-projection.v1",),
            (QueryResultShape.PRODUCT_LIST,),
        ),
        "screen.predicate.v2": (
            IntentType.SCREEN,
            ("scope", "predicate.field", "predicate.operator", "predicate.value"),
            tuple(QueryOperatorId),
            ("exclude_missing.v1",),
            (QueryResultShape.PRODUCT_LIST,),
        ),
        "rank.ordering.v2": (
            IntentType.RANK,
            ("scope", "ordering.field", "ordering.direction", "limit"),
            tuple(QueryOperatorId),
            (
                "default-direction-descending.v1",
                "default-limit-5.v1",
                "exclude_missing.v1",
                "stable-product-id.v1",
            ),
            (QueryResultShape.TOP_K,),
        ),
        "compare.subjects.v2": (
            IntentType.COMPARE,
            (
                "scope",
                "comparison.subjects",
                "comparison.metrics",
                "comparison.basis",
            ),
            (),
            ("approved-cross-family.v1", "same-definition-period-unit.v1"),
            (QueryResultShape.COMPARISON_TABLE,),
        ),
        "aggregate.scalar.v2": (
            IntentType.AGGREGATE,
            (
                "scope",
                "aggregation.function",
                "aggregation.target",
                "aggregation.population_grain",
                "aggregation.dedup_policy",
            ),
            tuple(QueryOperatorId),
            (
                "distinct-entity.v1",
                "exclude_missing.v1",
                "no-dedup.v1",
                "public-fund-representative-share.v1",
                "representative-product.v1",
                "source-product.v1",
            ),
            (QueryResultShape.SINGLE_VALUE,),
        ),
        "aggregate.grouped.v2": (
            IntentType.AGGREGATE,
            (
                "scope",
                "aggregation.function",
                "aggregation.target",
                "aggregation.population_grain",
                "aggregation.dedup_policy",
                "aggregation.grouping",
            ),
            tuple(QueryOperatorId),
            (
                "distinct-entity.v1",
                "exclude_missing.v1",
                "no-dedup.v1",
                "public-fund-representative-share.v1",
                "representative-product.v1",
                "source-product.v1",
            ),
            (QueryResultShape.GROUPED_TABLE,),
        ),
        "aggregate.distribution.v2": (
            IntentType.AGGREGATE,
            (
                "scope",
                "aggregation.function",
                "aggregation.target",
                "aggregation.population_grain",
                "aggregation.dedup_policy",
                "aggregation.grouping_or_bucket",
            ),
            tuple(QueryOperatorId),
            (
                "distinct-entity.v1",
                "equal-width-10.v1",
                "exclude_missing.v1",
                "no-dedup.v1",
                "public-fund-representative-share.v1",
                "representative-product.v1",
                "source-product.v1",
            ),
            (QueryResultShape.DISTRIBUTION,),
        ),
        "calculate.recipe.v2": (
            IntentType.CALCULATE,
            ("scope", "calculation.recipe", "calculation.operands"),
            (),
            (),
            (QueryResultShape.SINGLE_VALUE,),
        ),
        "similar.policy.v2": (
            IntentType.SIMILAR,
            (
                "scope",
                "similarity.anchor",
                "similarity.policy",
                "similarity.dimensions",
                "similarity.coverage_threshold",
                "limit",
            ),
            (),
            (
                "cosine-complete-dimensions.v1",
                "default-limit-5.v1",
                "minimum-dimension-coverage.v1",
            ),
            (QueryResultShape.PRODUCT_LIST,),
        ),
        "explain.topic.v2": (
            IntentType.EXPLAIN,
            ("scope", "explanation.topic_or_profile"),
            (),
            ("default-explanation-profile.v1",),
            (QueryResultShape.EXPLANATION,),
        ),
    }
)
NONREPRESENTABLE_REASON_CODES = frozenset(
    {
        "ENTITY_NOT_FOUND_IN_SNAPSHOT",
        "LEXICAL_OOD",
        "POLICY_PROHIBITED_FORECAST",
        "POLICY_PROHIBITED_ORDER_EXECUTION",
        "POLICY_PROHIBITED_PERSONALIZED_ADVICE",
        "REAL_TIME_DATA_OUT_OF_SCOPE",
        "SEMANTIC_CONCEPT_NOT_REGISTERED",
    }
)


@dataclass(frozen=True, slots=True)
class QueryContractRegistry:
    contract_registry_version: str
    contract_registry_hash: str
    operator_registry_version: str
    operator_registry_hash: str
    policy_registry_version: str
    policy_registry_hash: str
    pinned_operator_registry_hash: str
    pinned_policy_registry_hash: str
    variants_by_id: Mapping[str, ContractVariantDefinition]
    operators_by_id: Mapping[str, OperatorDefinition]
    policies_by_id: Mapping[str, PolicyDefinition]


@dataclass(frozen=True, slots=True)
class RequirementRepresentability:
    variant_id: str | None
    reason_code: str | None
    structural_variant_id: str | None


def load_query_contract_registry(project_root: Path) -> QueryContractRegistry:
    root = project_root.resolve()
    try:
        operators = _OperatorRegistryPayload.model_validate_json(
            (root / OPERATOR_REGISTRY_PATH).read_bytes()
        )
        policies = _PolicyRegistryPayload.model_validate_json(
            (root / POLICY_REGISTRY_PATH).read_bytes()
        )
        contracts = _ContractRegistryPayload.model_validate_json(
            (root / CONTRACT_REGISTRY_PATH).read_bytes()
        )
    except (OSError, ValidationError) as error:
        raise ValueError("invalid query contract registry") from error

    if (
        contracts.registry_version != CONTRACT_REGISTRY_VERSION
        or operators.registry_version != OPERATOR_REGISTRY_VERSION
        or policies.registry_version != POLICY_REGISTRY_VERSION
    ):
        raise ValueError("unsupported query registry version")

    operator_items = _unique_index(operators.operators)
    policy_items = _unique_index(policies.policies)
    variant_items = _unique_index(contracts.variants)
    if tuple(operator_items) != OPERATOR_ORDER:
        raise ValueError("non-canonical registry order")
    if tuple(policy_items) != tuple(sorted(policy_items)):
        raise ValueError("non-canonical registry order")
    if tuple(variant_items) != CONTRACT_VARIANT_ORDER:
        raise ValueError("non-canonical registry order")
    for operator_id, operator in operator_items.items():
        if (operator.arity, operator.allowed_value_kinds) != (
            EXPECTED_OPERATOR_DEFINITIONS[operator_id]
        ):
            raise ValueError("operator registry definition mismatch")
    if {
        policy_id: policy.kind for policy_id, policy in policy_items.items()
    } != dict(EXPECTED_POLICY_KINDS):
        raise ValueError("policy registry definition mismatch")
    operator_hash = canonical_sha256(operators)
    policy_hash = canonical_sha256(policies)
    if (
        contracts.operator_registry_version != operators.registry_version
        or contracts.operator_registry_hash != operator_hash
    ):
        raise ValueError("operator registry pin mismatch")
    if (
        contracts.policy_registry_version != policies.registry_version
        or contracts.policy_registry_hash != policy_hash
    ):
        raise ValueError("policy registry pin mismatch")

    operator_ids = set(operator_items)
    policy_ids = set(policy_items)
    for variant in contracts.variants:
        unknown_operators = {item.value for item in variant.operator_ids} - operator_ids
        if unknown_operators:
            raise ValueError(f"unknown operator reference: {sorted(unknown_operators)}")
        unknown_policies = set(variant.policy_ids) - policy_ids
        if unknown_policies:
            raise ValueError(f"unknown policy reference: {sorted(unknown_policies)}")
        _require_unique(variant.required_components)
        _require_unique(variant.operator_ids)
        _require_unique(variant.policy_ids)
        _require_unique(variant.result_shapes)
    for variant_id, variant in variant_items.items():
        signature = (
            variant.action_id,
            variant.required_components,
            variant.operator_ids,
            variant.policy_ids,
            variant.result_shapes,
        )
        if signature != EXPECTED_VARIANT_SIGNATURES[variant_id]:
            raise ValueError("contract variant definition mismatch")

    return QueryContractRegistry(
        contract_registry_version=contracts.registry_version,
        contract_registry_hash=canonical_sha256(contracts),
        operator_registry_version=operators.registry_version,
        operator_registry_hash=operator_hash,
        policy_registry_version=policies.registry_version,
        policy_registry_hash=policy_hash,
        pinned_operator_registry_hash=contracts.operator_registry_hash,
        pinned_policy_registry_hash=contracts.policy_registry_hash,
        variants_by_id=MappingProxyType(variant_items),
        operators_by_id=MappingProxyType(operator_items),
        policies_by_id=MappingProxyType(policy_items),
    )


def find_representing_variant(
    registry: QueryContractRegistry,
    action_id: str | IntentType | None,
    components: tuple[str, ...],
) -> ContractVariantDefinition | None:
    if action_id is None:
        return None
    try:
        action = IntentType(action_id)
    except ValueError:
        return None
    requested = set(components)
    return next(
        (
            variant
            for variant in registry.variants_by_id.values()
            if variant.action_id is action and requested <= set(variant.required_components)
        ),
        None,
    )


def assess_requirement_representability(
    registry: QueryContractRegistry,
    *,
    action_id: str | IntentType,
    components: tuple[str, ...],
    nonrepresentable_reason: str | None,
) -> RequirementRepresentability:
    structural_variant = find_representing_variant(registry, action_id, components)
    if nonrepresentable_reason is not None:
        if nonrepresentable_reason not in NONREPRESENTABLE_REASON_CODES:
            raise ValueError("unknown nonrepresentable reason")
        return RequirementRepresentability(
            variant_id=None,
            reason_code=nonrepresentable_reason,
            structural_variant_id=(
                structural_variant.id if structural_variant is not None else None
            ),
        )
    return RequirementRepresentability(
        variant_id=structural_variant.id if structural_variant is not None else None,
        reason_code=None,
        structural_variant_id=(
            structural_variant.id if structural_variant is not None else None
        ),
    )


def _unique_index(items: tuple[_StrictContractModel, ...]) -> dict[str, object]:
    indexed: dict[str, object] = {}
    for item in items:
        item_id = item.id.value if isinstance(item.id, Enum) else item.id
        if item_id in indexed:
            raise ValueError("invalid query contract registry")
        indexed[item_id] = item
    return indexed


def _require_unique(values: tuple[object, ...]) -> None:
    if len(set(values)) != len(values):
        raise ValueError("invalid query contract registry")

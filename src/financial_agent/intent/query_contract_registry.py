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

    operator_items = _unique_index(operators.operators)
    policy_items = _unique_index(policies.policies)
    variant_items = _unique_index(contracts.variants)
    if tuple(operator_items) != OPERATOR_ORDER:
        raise ValueError("non-canonical registry order")
    if tuple(policy_items) != tuple(sorted(policy_items)):
        raise ValueError("non-canonical registry order")
    if tuple(variant_items) != CONTRACT_VARIANT_ORDER:
        raise ValueError("non-canonical registry order")

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

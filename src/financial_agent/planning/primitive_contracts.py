"""Canonical primitive declarations shared by semantic planning artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from financial_agent.contracts.enums import Capability, IntentType


class LogicalExecutionRoute(str, Enum):
    SEMANTIC_SQL = "semantic_sql"
    GRAPH = "graph"
    SEARCH = "search"
    STAGE05 = "stage05"


def _route_for_capability(capability: Capability) -> LogicalExecutionRoute:
    if capability is Capability.GRAPH_TRAVERSAL:
        return LogicalExecutionRoute.GRAPH
    if capability is Capability.KEYWORD_SEARCH:
        return LogicalExecutionRoute.SEARCH
    if capability is Capability.SIMILARITY:
        return LogicalExecutionRoute.STAGE05
    return LogicalExecutionRoute.SEMANTIC_SQL


@dataclass(frozen=True, slots=True)
class CanonicalPrimitiveDefinition:
    primitive_id: str
    action_ids: frozenset[IntentType]
    capability: Capability
    execution_route: LogicalExecutionRoute


@dataclass(frozen=True, slots=True)
class CanonicalPrimitiveRole:
    primitive_id: str
    action_id: IntentType
    capability: Capability
    operation_kind: str
    execution_route: LogicalExecutionRoute


def _definition(
    primitive_id: str,
    action_ids: tuple[IntentType, ...],
    capability: Capability,
    execution_route: LogicalExecutionRoute | None = None,
) -> CanonicalPrimitiveDefinition:
    return CanonicalPrimitiveDefinition(
        primitive_id=primitive_id,
        action_ids=frozenset(action_ids),
        capability=capability,
        execution_route=execution_route or _route_for_capability(capability),
    )


_ALL_ACTIONS = tuple(IntentType)
CANONICAL_PRIMITIVES: Mapping[str, CanonicalPrimitiveDefinition] = MappingProxyType(
    {
        item.primitive_id: item
        for item in (
            _definition("lookup-products", _ALL_ACTIONS, Capability.RDB_LOOKUP),
            _definition("screen-products", (IntentType.SCREEN,), Capability.RDB_LOOKUP),
            _definition("rank-products", (IntentType.RANK,), Capability.RANKING),
            _definition(
                "check-comparability", (IntentType.RANK,), Capability.COMPARISON
            ),
            _definition(
                "normalize-values",
                (IntentType.RANK,),
                Capability.FINANCIAL_CALCULATION,
            ),
            _definition(
                "compare-products", (IntentType.COMPARE,), Capability.COMPARISON
            ),
            _definition(
                "aggregate-products",
                (IntentType.AGGREGATE,),
                Capability.FINANCIAL_CALCULATION,
            ),
            _definition(
                "calculate-products",
                (IntentType.CALCULATE,),
                Capability.FINANCIAL_CALCULATION,
                LogicalExecutionRoute.STAGE05,
            ),
            _definition(
                "similar-products",
                (IntentType.SIMILAR,),
                Capability.SIMILARITY,
                LogicalExecutionRoute.STAGE05,
            ),
            _definition(
                "traverse-relations",
                (
                    IntentType.LOOKUP,
                    IntentType.SCREEN,
                    IntentType.COMPARE,
                    IntentType.EXPLAIN,
                ),
                Capability.GRAPH_TRAVERSAL,
            ),
            _definition(
                "search-documents",
                (IntentType.LOOKUP, IntentType.EXPLAIN),
                Capability.KEYWORD_SEARCH,
            ),
            _definition("explore-catalog", _ALL_ACTIONS, Capability.KEYWORD_SEARCH),
        )
    }
)
RELATION_CONCEPT_IDS = frozenset(
    {
        "associatedWithTheme",
        "classifiedAsIndustry",
        "containsSecurity",
        "controlsCompany",
        "documentedBy",
        "hasRiskFactor",
        "hasShareClass",
        "holdsSecurity",
        "issuedBy",
        "listedOn",
        "managedBy",
        "securityOfCompany",
        "tracksIndex",
    }
)


_BASE_ROLES = {
    IntentType.LOOKUP: (
        ("lookup-products", "lookup"),
    ),
    IntentType.SCREEN: (
        ("lookup-products", "lookup"),
        ("screen-products", "screen"),
    ),
    IntentType.RANK: (
        ("lookup-products", "lookup"),
        ("rank-products", "rank"),
    ),
    IntentType.COMPARE: (
        ("lookup-products", "lookup"),
        ("compare-products", "compare"),
    ),
    IntentType.AGGREGATE: (
        ("lookup-products", "lookup"),
        ("aggregate-products", "aggregate"),
    ),
    IntentType.CALCULATE: (
        ("lookup-products", "lookup"),
        ("calculate-products", "calculate"),
    ),
    IntentType.SIMILAR: (
        ("lookup-products", "lookup"),
        ("similar-products", "similar"),
    ),
    IntentType.EXPLAIN: (
        ("lookup-products", "explanation_source_lookup"),
        ("search-documents", "search_explanation_source"),
    ),
}


def required_primitive_roles(
    action_id: IntentType,
    *,
    family_count: int,
    relation_required: bool,
) -> tuple[CanonicalPrimitiveRole, ...]:
    base = _BASE_ROLES.get(action_id)
    if base is None:
        return ()
    role_specs = list(base)
    if action_id is IntentType.RANK and family_count > 1:
        role_specs[1:1] = [
            ("check-comparability", "check_comparability"),
            ("normalize-values", "normalize_values"),
        ]
    if relation_required:
        role_specs.append(("traverse-relations", "traverse_relation"))
    return tuple(
        _role(primitive_id, action_id, operation_kind)
        for primitive_id, operation_kind in role_specs
    )


def validate_primitive_roles(
    roles: tuple[CanonicalPrimitiveRole, ...],
    *,
    action_id: IntentType,
    family_count: int,
    relation_required: bool,
) -> None:
    expected = required_primitive_roles(
        action_id,
        family_count=family_count,
        relation_required=relation_required,
    )
    if roles != expected:
        raise ValueError("LOGICAL_PRIMITIVE_CONTRACT_MISMATCH")


def validate_registry_primitive(
    primitive_id: str,
    *,
    action_ids: tuple[IntentType, ...],
    capability: Capability,
) -> None:
    canonical = CANONICAL_PRIMITIVES.get(primitive_id)
    if canonical is None:
        raise ValueError("EXECUTION_PRIMITIVE_NOT_REGISTERED")
    if canonical.action_ids != frozenset(action_ids) or canonical.capability is not capability:
        raise ValueError("EXECUTION_PRIMITIVE_DECLARATION_MISMATCH")


def _role(
    primitive_id: str,
    action_id: IntentType,
    operation_kind: str,
) -> CanonicalPrimitiveRole:
    definition = CANONICAL_PRIMITIVES[primitive_id]
    if action_id not in definition.action_ids:
        raise ValueError("EXECUTION_PRIMITIVE_ACTION_MISMATCH")
    return CanonicalPrimitiveRole(
        primitive_id=primitive_id,
        action_id=action_id,
        capability=definition.capability,
        operation_kind=operation_kind,
        execution_route=definition.execution_route,
    )

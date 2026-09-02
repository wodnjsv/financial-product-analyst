"""Closed physical bindings and execution-policy registries for semantic SQL."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from pydantic import ConfigDict, Field, ValidationError, model_validator

from financial_agent.contracts.base import ContractModel, Identifier
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import ProductFamily
from financial_agent.intent.catalog import SemanticCatalogSnapshot, load_catalog
from financial_agent.intent.query_contract_registry import EXPECTED_OPERATOR_DEFINITIONS
from financial_agent.intent.query_contracts import (
    AggregationFunction,
    QueryOperatorId,
    SemanticValueKind,
)


BINDING_REGISTRY_PATH = Path("config/planning/semantic-sql-bindings.v1.json")
POLICY_REGISTRY_PATH = Path("config/planning/semantic-sql-policies.v1.json")
BINDING_REGISTRY_VERSION = "semantic-sql-bindings.v1"
POLICY_REGISTRY_VERSION = "semantic-sql-policies.v1"


class ObservationValueColumn(str, Enum):
    """Logical typed value selector mapped to normalized columns by the compiler."""

    DECIMAL = "decimal_value"
    INTEGER = "integer_value"
    TEXT = "text_value"
    BOOLEAN = "boolean_value"
    DATE = "date_value"


class PhysicalSourceKind(str, Enum):
    OBSERVATION = "observation"
    CATALOG = "catalog"
    RELATION = "relation"
    DOCUMENT = "document"


class PhysicalBindingAvailability(str, Enum):
    VERIFIED = "verified"
    UNAVAILABLE = "unavailable"


class PeriodBehavior(str, Enum):
    STATIC = "static"
    POINT_IN_TIME = "point_in_time"
    PERIOD = "period"


class DateBehavior(str, Enum):
    NONE = "none"
    APPLICABLE_DATE = "applicable_date"
    PERIOD_BOUNDS = "period_bounds"


class SemanticQualifierId(str, Enum):
    AS_OF = "as_of"
    CURRENCY = "currency"
    PERIOD = "period"
    UNIT = "unit"


class EvidenceLocator(str, Enum):
    METRIC_DEFINITION = "metric_definition"
    OBSERVATION_RECORD = "observation_record"
    RELATION_RECORD = "relation_record"
    EVIDENCE_RECORD = "evidence_record"
    SOURCE_RECORD = "source_record"


class SemanticSqlPolicyKind(str, Enum):
    BUCKETING = "bucketing"
    COMPARISON = "comparison"
    COVERAGE = "coverage"
    DEDUPLICATION = "deduplication"
    DEFAULT = "default"
    MISSINGNESS = "missingness"
    NORMALIZATION = "normalization"
    POPULATION_GRAIN = "population_grain"
    RECIPE = "recipe"
    SIMILARITY = "similarity"
    STABLE_TIE = "stable_tie"
    UNIT_CONVERSION = "unit_conversion"


class _StrictModel(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PhysicalBindingDefinition(_StrictModel):
    id: Identifier
    semantic_concept_id: Identifier
    product_family_id: ProductFamily
    source_kind: PhysicalSourceKind
    availability: PhysicalBindingAvailability
    approved_metric_ids: tuple[Identifier, ...]
    value_column: ObservationValueColumn | None
    semantic_value_kind: SemanticValueKind
    storage_unit_id: Identifier | None
    unit_conversion_policy_id: Identifier | None
    period_behavior: PeriodBehavior
    date_behavior: DateBehavior
    missingness_policy_id: Identifier | None
    supported_operator_ids: tuple[QueryOperatorId, ...]
    supported_aggregate_ids: tuple[AggregationFunction, ...]
    supported_qualifier_ids: tuple[SemanticQualifierId, ...]
    required_qualifier_ids: tuple[SemanticQualifierId, ...]
    verified_population_grain_ids: tuple[Identifier, ...]
    required_evidence_locators: tuple[EvidenceLocator, ...]
    unavailable_reason_code: Identifier | None

    @model_validator(mode="after")
    def validate_availability_shape(self):
        if self.availability is PhysicalBindingAvailability.VERIFIED:
            if not self.approved_metric_ids or self.value_column is None:
                raise ValueError("verified binding requires physical fields")
            if not self.storage_unit_id or not self.unit_conversion_policy_id:
                raise ValueError("verified binding requires unit policy")
            if not self.missingness_policy_id:
                raise ValueError("verified binding requires missingness policy")
            if self.unavailable_reason_code is not None:
                raise ValueError("verified binding cannot have unavailable reason")
        elif any(
            (
                self.approved_metric_ids,
                self.value_column is not None,
                self.storage_unit_id is not None,
                self.unit_conversion_policy_id is not None,
                self.missingness_policy_id is not None,
                self.supported_operator_ids,
                self.supported_aggregate_ids,
                self.supported_qualifier_ids,
                self.required_qualifier_ids,
                self.verified_population_grain_ids,
                self.required_evidence_locators,
            )
        ):
            raise ValueError("unavailable binding must not expose physical fields")
        elif self.unavailable_reason_code is None:
            raise ValueError("unavailable binding requires reason")
        if self.availability is PhysicalBindingAvailability.VERIFIED and not self.required_evidence_locators:
            raise ValueError("missing evidence requirements")
        _require_unique(self.approved_metric_ids)
        _require_unique(self.supported_operator_ids)
        _require_unique(self.supported_aggregate_ids)
        _require_unique(self.supported_qualifier_ids)
        _require_unique(self.required_qualifier_ids)
        _require_unique(self.verified_population_grain_ids)
        _require_unique(self.required_evidence_locators)
        return self


class SemanticSqlPolicyDefinition(_StrictModel):
    id: Identifier
    kind: SemanticSqlPolicyKind
    applicable_product_family_ids: tuple[ProductFamily, ...] = ()
    verified: bool
    relation_predicate_id: Identifier | None = None
    relation_direction: str | None = Field(
        default=None, pattern=r"^(subject_to_object|object_to_subject)$"
    )
    population_grain_id: Identifier | None = None
    required_evidence_locators: tuple[EvidenceLocator, ...] = ()
    unavailable_reason_code: Identifier | None = None

    @model_validator(mode="after")
    def validate_verification_shape(self):
        if self.verified == (self.unavailable_reason_code is not None):
            raise ValueError("policy verification shape mismatch")
        if bool(self.relation_predicate_id) != bool(self.relation_direction):
            raise ValueError("policy relation shape mismatch")
        if self.relation_predicate_id is not None and not {
            EvidenceLocator.RELATION_RECORD,
            EvidenceLocator.EVIDENCE_RECORD,
            EvidenceLocator.SOURCE_RECORD,
        } <= set(self.required_evidence_locators):
            raise ValueError("policy relation evidence requirements missing")
        _require_unique(self.applicable_product_family_ids)
        _require_unique(self.required_evidence_locators)
        return self


class _BindingRegistryPayload(_StrictModel):
    registry_version: Identifier
    bindings: tuple[PhysicalBindingDefinition, ...] = Field(min_length=1)


class _PolicyRegistryPayload(_StrictModel):
    registry_version: Identifier
    policies: tuple[SemanticSqlPolicyDefinition, ...] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class PhysicalBindingRegistry:
    registry_version: str
    registry_hash: str
    catalog_version: str
    catalog_hash: str
    bindings_by_id: Mapping[str, PhysicalBindingDefinition]
    bindings_by_family_concept: Mapping[tuple[str, str], PhysicalBindingDefinition]
    catalog_concept_ids: frozenset[str]
    catalog_families_by_concept: Mapping[str, frozenset[str]]

    def binding_for(
        self, family_id: str | ProductFamily, concept_id: str
    ) -> PhysicalBindingDefinition | None:
        family = family_id.value if isinstance(family_id, ProductFamily) else family_id
        return self.bindings_by_family_concept.get((family, concept_id))


@dataclass(frozen=True, slots=True)
class SemanticSqlPolicyRegistry:
    registry_version: str
    registry_hash: str
    policies_by_id: Mapping[str, SemanticSqlPolicyDefinition]


def load_physical_binding_registry(
    project_root: Path,
    *,
    registry_path: Path | None = None,
) -> PhysicalBindingRegistry:
    root = project_root.resolve()
    path = registry_path or root / BINDING_REGISTRY_PATH
    try:
        payload = _BindingRegistryPayload.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise ValueError(f"invalid physical binding registry: {error}") from error
    if payload.registry_version != BINDING_REGISTRY_VERSION:
        raise ValueError("unsupported physical binding registry version")
    catalog = load_catalog(root)
    policies = load_semantic_sql_policy_registry(root)
    by_id: dict[str, PhysicalBindingDefinition] = {}
    by_pair: dict[tuple[str, str], PhysicalBindingDefinition] = {}
    for binding in payload.bindings:
        if binding.id in by_id:
            raise ValueError("duplicate physical binding ID")
        pair = (binding.product_family_id.value, binding.semantic_concept_id)
        if pair in by_pair:
            raise ValueError("duplicate family/concept binding")
        _validate_binding(binding, catalog, policies)
        by_id[binding.id] = binding
        by_pair[pair] = binding
    return PhysicalBindingRegistry(
        registry_version=payload.registry_version,
        registry_hash=canonical_sha256(payload),
        catalog_version=catalog.catalog_version,
        catalog_hash=catalog.catalog_hash,
        bindings_by_id=MappingProxyType(dict(sorted(by_id.items()))),
        bindings_by_family_concept=MappingProxyType(dict(sorted(by_pair.items()))),
        catalog_concept_ids=frozenset(catalog.concepts_by_id),
        catalog_families_by_concept=MappingProxyType(
            {
                concept_id: frozenset(concept.allowed_product_families)
                for concept_id, concept in sorted(catalog.concepts_by_id.items())
            }
        ),
    )


def load_semantic_sql_policy_registry(
    project_root: Path,
    *,
    registry_path: Path | None = None,
) -> SemanticSqlPolicyRegistry:
    root = project_root.resolve()
    path = registry_path or root / POLICY_REGISTRY_PATH
    try:
        payload = _PolicyRegistryPayload.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise ValueError(f"invalid semantic SQL policy registry: {error}") from error
    if payload.registry_version != POLICY_REGISTRY_VERSION:
        raise ValueError("unsupported semantic SQL policy registry version")
    catalog = load_catalog(root)
    indexed: dict[str, SemanticSqlPolicyDefinition] = {}
    for policy in payload.policies:
        if policy.id in indexed:
            raise ValueError("duplicate semantic SQL policy")
        if policy.relation_predicate_id is not None:
            concept = catalog.concepts_by_id.get(policy.relation_predicate_id)
            if concept is None or concept.kind != "relation":
                raise ValueError("unknown policy relation concept")
            if not set(item.value for item in policy.applicable_product_family_ids) <= set(
                concept.allowed_product_families
            ):
                raise ValueError("policy relation family mismatch")
        indexed[policy.id] = policy
    return SemanticSqlPolicyRegistry(
        registry_version=payload.registry_version,
        registry_hash=canonical_sha256(payload),
        policies_by_id=MappingProxyType(dict(sorted(indexed.items()))),
    )


def _validate_binding(
    binding: PhysicalBindingDefinition,
    catalog: SemanticCatalogSnapshot,
    policies: SemanticSqlPolicyRegistry,
) -> None:
    concept = catalog.concepts_by_id.get(binding.semantic_concept_id)
    if concept is None:
        raise ValueError("unknown semantic concept")
    if binding.product_family_id.value not in concept.allowed_product_families:
        raise ValueError("binding family not applicable")
    expected_kind = _catalog_value_kind(concept.value_kind)
    if binding.semantic_value_kind is not expected_kind:
        raise ValueError("binding value kind mismatch")
    if binding.availability is PhysicalBindingAvailability.UNAVAILABLE:
        return
    expected_column = {
        SemanticValueKind.DECIMAL: ObservationValueColumn.DECIMAL,
        SemanticValueKind.INTEGER: ObservationValueColumn.INTEGER,
        SemanticValueKind.STRING: ObservationValueColumn.TEXT,
        SemanticValueKind.BOOLEAN: ObservationValueColumn.BOOLEAN,
        SemanticValueKind.DATE: ObservationValueColumn.DATE,
    }.get(binding.semantic_value_kind)
    if binding.value_column is not expected_column:
        raise ValueError("binding value column mismatch")
    required_evidence = {
        PhysicalSourceKind.OBSERVATION: {
            EvidenceLocator.METRIC_DEFINITION,
            EvidenceLocator.OBSERVATION_RECORD,
            EvidenceLocator.EVIDENCE_RECORD,
            EvidenceLocator.SOURCE_RECORD,
        },
        PhysicalSourceKind.RELATION: {
            EvidenceLocator.RELATION_RECORD,
            EvidenceLocator.EVIDENCE_RECORD,
            EvidenceLocator.SOURCE_RECORD,
        },
    }.get(binding.source_kind, {EvidenceLocator.EVIDENCE_RECORD, EvidenceLocator.SOURCE_RECORD})
    if not required_evidence <= set(binding.required_evidence_locators):
        raise ValueError("missing evidence requirements")
    for operator in binding.supported_operator_ids:
        allowed = EXPECTED_OPERATOR_DEFINITIONS[operator.value][1]
        if allowed and binding.semantic_value_kind not in allowed:
            raise ValueError("operator/value kind mismatch")
    for policy_id in (binding.unit_conversion_policy_id, binding.missingness_policy_id):
        if policy_id not in policies.policies_by_id:
            raise ValueError("unknown binding policy")
    if policies.policies_by_id[binding.unit_conversion_policy_id].kind is not SemanticSqlPolicyKind.UNIT_CONVERSION:
        raise ValueError("binding unit policy kind mismatch")
    if policies.policies_by_id[binding.missingness_policy_id].kind is not SemanticSqlPolicyKind.MISSINGNESS:
        raise ValueError("binding missingness policy kind mismatch")
    expected_qualifiers = tuple(
        SemanticQualifierId(item) for item in concept.required_qualifiers
    )
    if set(binding.required_qualifier_ids) != set(expected_qualifiers):
        raise ValueError("binding required qualifier mismatch")
    if not set(binding.required_qualifier_ids) <= set(binding.supported_qualifier_ids):
        raise ValueError("required qualifier not supported")
    for grain_id in binding.verified_population_grain_ids:
        policy = policies.policies_by_id.get(grain_id)
        if policy is None or policy.kind is not SemanticSqlPolicyKind.POPULATION_GRAIN:
            raise ValueError("binding population grain policy mismatch")


def _catalog_value_kind(value_kind: str) -> SemanticValueKind:
    mapping = {
        "decimal": SemanticValueKind.DECIMAL,
        "integer": SemanticValueKind.INTEGER,
        "date": SemanticValueKind.DATE,
        "boolean": SemanticValueKind.BOOLEAN,
        "text": SemanticValueKind.STRING,
        "classification": SemanticValueKind.STRING,
        "status": SemanticValueKind.STRING,
        "identifier": SemanticValueKind.IDENTIFIER,
    }
    try:
        return mapping[value_kind]
    except KeyError as error:
        raise ValueError("semantic concept has no physical scalar kind") from error


def _require_unique(values: tuple[object, ...]) -> None:
    if len(set(values)) != len(values):
        raise ValueError("duplicate registry value")

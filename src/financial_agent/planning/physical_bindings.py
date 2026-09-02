"""Closed physical bindings and execution-policy registries for semantic SQL."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from pydantic import ConfigDict, Field, ValidationError, model_validator

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import ProductFamily
from financial_agent.intent.catalog import SemanticCatalogSnapshot, load_catalog
from financial_agent.intent.query_contract_registry import EXPECTED_OPERATOR_DEFINITIONS
from financial_agent.intent.query_contract_registry import load_query_contract_registry
from financial_agent.intent.query_contracts import (
    AggregationFunction,
    QueryOperatorId,
    SemanticValueKind,
    QueryRegistryPinsV2,
)
from financial_agent.ingestion.mapping.domestic_etp import (
    _METRIC_SPECS as DOMESTIC_ETP_METRIC_SPECS,
)
from financial_agent.ingestion.mapping.overseas_etp import (
    _METRIC_SPECS as OVERSEAS_ETP_METRIC_SPECS,
)
from financial_agent.ingestion.mapping.public_fund import (
    _METRIC_SPECS as PUBLIC_FUND_METRIC_SPECS,
)


BINDING_REGISTRY_PATH = Path("config/planning/semantic-sql-bindings.v1.json")
POLICY_REGISTRY_PATH = Path("config/planning/semantic-sql-policies.v1.json")
BINDING_REGISTRY_VERSION = "semantic-sql-bindings.v1"
POLICY_REGISTRY_VERSION = "semantic-sql-policies.v1"
EXPECTED_POLICY_REGISTRY_HASH = (
    "cf4f5065eb4fdae76902a1c0bd817700129ad077fe56795c05ab95d76937abf4"
)
EXPECTED_POLICY_IDS = frozenset(
    {
        "approved-cross-family.v1",
        "cosine-complete-dimensions.v1",
        "default-direction-descending.v1",
        "default-explanation-profile.v1",
        "default-limit-5.v1",
        "default-product-projection.v1",
        "distinct-entity.v1",
        "equal-width-10.v1",
        "exclude_missing.v1",
        "identity-unit.v1",
        "minimum-dimension-coverage.v1",
        "no-dedup.v1",
        "public-fund-representative-share.v1",
        "representative-product.v1",
        "same-definition-period-unit.v1",
        "semantic-percent-to-percentage-point.v1",
        "source-product.v1",
        "stable-product-id.v1",
    }
)
EXPECTED_SEMANTIC_REGISTRY_PINS = QueryRegistryPinsV2(
    contract_registry_version="query-contract-registry.v2",
    contract_registry_hash="06c2f97da35f07ccaa237e0a63a7d2d9a8a2c14040dd2e09e97d0bcb86d88baf",
    operator_registry_version="query-operator-registry.v1",
    operator_registry_hash="d9f1775b563cea24b0b8eaa1e79d9bd864df9defa483ad17aec0738af88f53ba",
    policy_registry_version="query-policy-registry.v1",
    policy_registry_hash="1dbb8eedf8340aae5b359692cd04c869d07d66681e3609a25623f7208513ce3a",
)
EXPECTED_CATALOG_VERSION = "semantic-query-catalog.v1"
EXPECTED_CATALOG_HASH = "c1e88ebd353e6306e8f61f4bef31d23fbed802adf4811a8ea287e40dbde73076"
EXPECTED_CATALOG_PROJECTION_HASH = (
    "86068f09df86b6dc982d6b721490982530ddceba575fe70881e0d57529ae3e94"
)
EXPECTED_BINDING_DEFINITION_HASHES = MappingProxyType(
    {
        "domestic-etf-aum.v1": "5ca7edfbf435b6aa493b046511dbf30f1156ac281278e82dba435daa0cf5a99a",
        "domestic-etf-fee-rate.v1": "5e30bdd1542023891255028254929dd8f13ede4fd922d2b2d73feaa752070a7c",
        "overseas-etf-aum.v1": "eab62e8bc8c99f757adb18d193b4710c382c03f75ae49ab1298ffbec91854adb",
        "overseas-etf-fee-rate.v1": "fd723bf049d800c724eca7c91ab182f685c415aa94698bbf0b9442d56513b90c",
        "public-fund-aum.v1": "0e0c593d46c74819efb7684ec64fe48774ec6632ec5214420a869d46e5678511",
        "public-fund-fee-rate.v1": "fbb846956c6a4b37c50c9842905bce28c229b75ca037a5fef7756e92986d34b0",
    }
)
EXPECTED_MAPPER_BINDINGS = MappingProxyType(
    {
        "domestic-etf-aum.v1": (
            DOMESTIC_ETP_METRIC_SPECS,
            "du_last_aum",
            "organizer.pref01n001.aum",
        ),
        "domestic-etf-fee-rate.v1": (
            DOMESTIC_ETP_METRIC_SPECS,
            "cu_charge_rt",
            "organizer.pref01n001.total_fee_rate",
        ),
        "overseas-etf-aum.v1": (
            OVERSEAS_ETP_METRIC_SPECS,
            "du_last_aum",
            "organizer.pref02n001.aum",
        ),
        "overseas-etf-fee-rate.v1": (
            OVERSEAS_ETP_METRIC_SPECS,
            "cu_charge_rt",
            "organizer.pref02n001.total_fee_rate",
        ),
        "public-fund-aum.v1": (
            PUBLIC_FUND_METRIC_SPECS,
            "fd_nast_suma",
            "organizer.prfd01n001.net_assets",
        ),
    }
)
TRUSTED_PUBLIC_FUND_MANIFEST_PINS = MappingProxyType(
    {
        "synthetic-public-fund-complete.v1": (
            "43138033043db74566a74023c18b83e01b9637c1041ae737758aef55aaa9b36f",
            "859d22464fe035c1cf0be0dd7fa048146b06167994c4133e2edf649c8963a001",
        )
    }
)


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
    approved_metric_definition_refs: tuple[Identifier, ...]
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
    accepted_semantic_unit_ids: tuple[Identifier, ...]
    currency_normalization_required: bool
    verified_population_grain_ids: tuple[Identifier, ...]
    required_evidence_locators: tuple[EvidenceLocator, ...]
    unavailable_reason_code: Identifier | None

    @model_validator(mode="after")
    def validate_availability_shape(self):
        if self.availability is PhysicalBindingAvailability.VERIFIED:
            if (
                not self.approved_metric_ids
                or not self.approved_metric_definition_refs
                or self.value_column is None
            ):
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
                self.approved_metric_definition_refs,
                self.value_column is not None,
                self.storage_unit_id is not None,
                self.unit_conversion_policy_id is not None,
                self.missingness_policy_id is not None,
                self.supported_operator_ids,
                self.supported_aggregate_ids,
                self.supported_qualifier_ids,
                self.required_qualifier_ids,
                self.accepted_semantic_unit_ids,
                self.currency_normalization_required,
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
        _require_unique(self.approved_metric_definition_refs)
        definition_metrics = []
        for reference in self.approved_metric_definition_refs:
            metric_id, separator, version = reference.rpartition(":")
            if not separator or not metric_id or not version:
                raise ValueError("invalid approved metric definition reference")
            definition_metrics.append(metric_id)
        if set(definition_metrics) != set(self.approved_metric_ids):
            raise ValueError("approved metric definition ownership mismatch")
        _require_unique(self.supported_operator_ids)
        _require_unique(self.supported_aggregate_ids)
        _require_unique(self.supported_qualifier_ids)
        _require_unique(self.required_qualifier_ids)
        _require_unique(self.accepted_semantic_unit_ids)
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
    semantic_registry_pins: QueryRegistryPinsV2
    physical_policy_registry_version: Identifier
    physical_policy_registry_hash: Sha256Hex
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
    semantic_registry_pins: QueryRegistryPinsV2
    physical_policy_registry_version: str
    physical_policy_registry_hash: str

    def __post_init__(self) -> None:
        catalog_concept_ids = frozenset(self.catalog_concept_ids)
        catalog_families = {
            concept_id: frozenset(families)
            for concept_id, families in self.catalog_families_by_concept.items()
        }
        if self.registry_version != BINDING_REGISTRY_VERSION:
            raise ValueError("registry definition mismatch")
        if (
            self.catalog_version != EXPECTED_CATALOG_VERSION
            or self.catalog_hash != EXPECTED_CATALOG_HASH
        ):
            raise ValueError("registry definition mismatch")
        if self.semantic_registry_pins != EXPECTED_SEMANTIC_REGISTRY_PINS:
            raise ValueError("registry definition mismatch")
        if (
            self.physical_policy_registry_version != POLICY_REGISTRY_VERSION
            or self.physical_policy_registry_hash != EXPECTED_POLICY_REGISTRY_HASH
        ):
            raise ValueError("registry definition mismatch")
        by_id = dict(self.bindings_by_id)
        if set(by_id) != set(EXPECTED_BINDING_DEFINITION_HASHES) or any(
            canonical_sha256(binding) != EXPECTED_BINDING_DEFINITION_HASHES[binding_id]
            for binding_id, binding in by_id.items()
        ):
            raise ValueError("registry definition mismatch")
        expected_pairs = {
            (binding.product_family_id.value, binding.semantic_concept_id): binding
            for binding in by_id.values()
        }
        if dict(self.bindings_by_family_concept) != expected_pairs:
            raise ValueError("registry definition mismatch")
        catalog_projection = {
            "concepts": {
                concept_id: sorted(families)
                for concept_id, families in sorted(catalog_families.items())
            }
        }
        if (
            frozenset(catalog_families) != catalog_concept_ids
            or canonical_sha256(catalog_projection) != EXPECTED_CATALOG_PROJECTION_HASH
        ):
            raise ValueError("registry definition mismatch")
        payload = _BindingRegistryPayload(
            registry_version=self.registry_version,
            semantic_registry_pins=self.semantic_registry_pins,
            physical_policy_registry_version=self.physical_policy_registry_version,
            physical_policy_registry_hash=self.physical_policy_registry_hash,
            bindings=tuple(by_id[item] for item in sorted(by_id)),
        )
        if canonical_sha256(payload) != self.registry_hash:
            raise ValueError("registry hash mismatch")
        object.__setattr__(
            self,
            "bindings_by_id",
            MappingProxyType(dict(sorted(by_id.items()))),
        )
        object.__setattr__(
            self,
            "bindings_by_family_concept",
            MappingProxyType(dict(self.bindings_by_family_concept)),
        )
        object.__setattr__(
            self,
            "catalog_families_by_concept",
            MappingProxyType(dict(catalog_families)),
        )
        object.__setattr__(self, "catalog_concept_ids", catalog_concept_ids)

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

    def __post_init__(self) -> None:
        policies = dict(self.policies_by_id)
        if set(policies) != EXPECTED_POLICY_IDS:
            raise ValueError("registry definition mismatch")
        payload = _PolicyRegistryPayload(
            registry_version=self.registry_version,
            policies=tuple(policies[item] for item in sorted(policies)),
        )
        if (
            self.registry_version != POLICY_REGISTRY_VERSION
            or canonical_sha256(payload) != EXPECTED_POLICY_REGISTRY_HASH
        ):
            raise ValueError("registry definition mismatch")
        if self.registry_hash != EXPECTED_POLICY_REGISTRY_HASH:
            raise ValueError("registry hash mismatch")
        object.__setattr__(
            self,
            "policies_by_id",
            MappingProxyType(dict(sorted(policies.items()))),
        )


class RepresentativeShareEdge(_StrictModel):
    dataset_pin: Sha256Hex
    representative_id: Identifier
    share_class_id: Identifier
    predicate_id: Identifier
    relation_id: Identifier
    evidence_id: Identifier
    source_id: Identifier


class PopulationMetricOwnership(_StrictModel):
    dataset_pin: Sha256Hex
    representative_id: Identifier
    metric_id: Identifier
    metric_definition_version: Identifier
    owner_entity_id: Identifier
    observation_id: Identifier
    evidence_id: Identifier
    source_id: Identifier


class DatasetSourceRecord(_StrictModel):
    dataset_pin: Sha256Hex
    source_id: Identifier


class DatasetEvidenceRecord(_StrictModel):
    dataset_pin: Sha256Hex
    evidence_id: Identifier
    source_id: Identifier


class PublicFundDatasetManifest(_StrictModel):
    manifest_id: Identifier
    dataset_pin: Sha256Hex
    physical_policy_registry_version: Identifier
    physical_policy_registry_hash: Sha256Hex
    population_grain_policy_id: Identifier
    dedup_policy_id: Identifier
    authoritative_share_class_ids: tuple[Identifier, ...] = Field(min_length=1)
    source_records: tuple[DatasetSourceRecord, ...] = Field(min_length=1)
    evidence_records: tuple[DatasetEvidenceRecord, ...] = Field(min_length=1)
    representative_share_edges: tuple[RepresentativeShareEdge, ...] = Field(
        min_length=1
    )
    population_metric_ownerships: tuple[PopulationMetricOwnership, ...] = Field(
        min_length=1
    )

    @model_validator(mode="after")
    def validate_manifest_shape(self):
        _require_unique(self.authoritative_share_class_ids)
        _require_unique(tuple(item.source_id for item in self.source_records))
        _require_unique(tuple(item.evidence_id for item in self.evidence_records))
        _require_unique(tuple(item.relation_id for item in self.representative_share_edges))
        _require_unique(
            tuple(item.observation_id for item in self.population_metric_ownerships)
        )
        return self


class PhysicalReadinessFacts(_StrictModel):
    known_entity_ids: frozenset[Identifier] = frozenset()
    known_group_basis_ids: frozenset[Identifier] = frozenset()
    known_prior_result_binding_ids: frozenset[Identifier] = frozenset()
    known_value_ref_ids: frozenset[Identifier] = frozenset()
    public_fund_manifest: PublicFundDatasetManifest | None = None
    public_fund_manifest_hash: Sha256Hex | None = None

    @model_validator(mode="after")
    def validate_manifest_pair(self):
        if bool(self.public_fund_manifest) != bool(self.public_fund_manifest_hash):
            raise ValueError("public fund manifest and hash must be supplied together")
        return self


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
    semantic = load_query_contract_registry(root)
    expected_semantic_pins = QueryRegistryPinsV2(
        contract_registry_version=semantic.contract_registry_version,
        contract_registry_hash=semantic.contract_registry_hash,
        operator_registry_version=semantic.operator_registry_version,
        operator_registry_hash=semantic.operator_registry_hash,
        policy_registry_version=semantic.policy_registry_version,
        policy_registry_hash=semantic.policy_registry_hash,
    )
    if payload.semantic_registry_pins != expected_semantic_pins:
        raise ValueError("semantic registry pin mismatch")
    if (
        payload.physical_policy_registry_version != policies.registry_version
        or payload.physical_policy_registry_hash != policies.registry_hash
    ):
        raise ValueError("physical policy registry pin mismatch")
    by_id: dict[str, PhysicalBindingDefinition] = {}
    by_pair: dict[tuple[str, str], PhysicalBindingDefinition] = {}
    for binding in payload.bindings:
        if binding.id in by_id:
            raise ValueError("duplicate physical binding ID")
        pair = (binding.product_family_id.value, binding.semantic_concept_id)
        if pair in by_pair:
            raise ValueError("duplicate family/concept binding")
        _validate_binding(binding, catalog, policies)
        _validate_mapper_binding(binding)
        expected_hash = EXPECTED_BINDING_DEFINITION_HASHES.get(binding.id)
        if expected_hash is None or canonical_sha256(binding) != expected_hash:
            raise ValueError("physical binding definition mismatch")
        by_id[binding.id] = binding
        by_pair[pair] = binding
    if set(by_id) != set(EXPECTED_BINDING_DEFINITION_HASHES):
        raise ValueError("physical binding definition mismatch")
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
        semantic_registry_pins=payload.semantic_registry_pins,
        physical_policy_registry_version=payload.physical_policy_registry_version,
        physical_policy_registry_hash=payload.physical_policy_registry_hash,
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
    if canonical_sha256(payload) != EXPECTED_POLICY_REGISTRY_HASH:
        raise ValueError("semantic SQL policy definition mismatch")
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
    actual_qualifiers = set(binding.required_qualifier_ids)
    expected_qualifier_set = set(expected_qualifiers)
    extra_qualifiers = actual_qualifiers - expected_qualifier_set
    if not expected_qualifier_set <= actual_qualifiers or (
        extra_qualifiers
        and not (
            binding.semantic_concept_id == "fee_rate"
            and extra_qualifiers == {SemanticQualifierId.UNIT}
        )
    ):
        raise ValueError("binding required qualifier mismatch")
    if not set(binding.required_qualifier_ids) <= set(binding.supported_qualifier_ids):
        raise ValueError("required qualifier not supported")
    for grain_id in binding.verified_population_grain_ids:
        policy = policies.policies_by_id.get(grain_id)
        if policy is None or policy.kind is not SemanticSqlPolicyKind.POPULATION_GRAIN:
            raise ValueError("binding population grain policy mismatch")


def _validate_mapper_binding(binding: PhysicalBindingDefinition) -> None:
    if binding.availability is PhysicalBindingAvailability.UNAVAILABLE:
        return
    expected = EXPECTED_MAPPER_BINDINGS.get(binding.id)
    if expected is None:
        raise ValueError("physical binding definition mismatch")
    mapper_specs, source_column, expected_metric_id = expected
    metric_suffix, mapper_value_kind, mapper_unit_id = mapper_specs[source_column]
    if (
        binding.approved_metric_ids != (expected_metric_id,)
        or binding.approved_metric_definition_refs != (f"{expected_metric_id}:2",)
        or expected_metric_id.rsplit(".", 1)[-1] != metric_suffix
        or mapper_value_kind != "numeric"
        or binding.semantic_value_kind is not SemanticValueKind.DECIMAL
        or binding.storage_unit_id != mapper_unit_id
    ):
        raise ValueError("physical binding definition mismatch")


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

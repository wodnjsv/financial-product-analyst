from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from rdflib import Namespace


ONTOLOGY_IRI = "urn:ontology:financial-product:v1"
FP = Namespace(f"{ONTOLOGY_IRI}#")

TBOX_RELATIVE_PATHS = (
    "ontology/common.ttl",
    "ontology/bond_kr.ttl",
    "ontology/etf_kr.ttl",
    "ontology/etf_gl.ttl",
    "ontology/fund_pub.ttl",
)
SHACL_RELATIVE_PATHS = (
    "ontology/shapes/common.shacl.ttl",
    "ontology/shapes/domain.shacl.ttl",
)
GRAPH_CONTRACT_RELATIVE_PATHS = TBOX_RELATIVE_PATHS + SHACL_RELATIVE_PATHS

APPROVED_PREDICATES = frozenset(
    {
        "managedBy",
        "issuedBy",
        "tracksIndex",
        "holdsSecurity",
        "containsSecurity",
        "securityOfCompany",
        "controlsCompany",
        "listedOn",
        "classifiedAsIndustry",
        "associatedWithTheme",
        "hasShareClass",
        "documentedBy",
        "hasRiskFactor",
    }
)

ENTITY_CLASS_BY_TYPE = MappingProxyType(
    {
        "product": "FinancialProduct",
        "security": "Security",
        "company": "Company",
        "institution": "Organization",
        "index": "Index",
        "theme": "Theme",
    }
)

PRODUCT_BASE_CLASSES_BY_FAMILY = MappingProxyType(
    {
        "domestic_bond": ("FinancialProduct", "Bond", "DomesticBond"),
        "domestic_etf": ("FinancialProduct",),
        "overseas_etf": ("FinancialProduct",),
        "public_fund": ("FinancialProduct", "PublicFund"),
    }
)

ETP_CLASSES_BY_FAMILY_AND_TYPE = MappingProxyType(
    {
        ("domestic_etf", "ETF"): ("ExchangeTradedProduct", "ETF", "DomesticETF"),
        ("domestic_etf", "ETN"): ("ExchangeTradedProduct", "ETN", "DomesticETN"),
        ("overseas_etf", "ETF"): ("ExchangeTradedProduct", "ETF", "OverseasETF"),
        ("overseas_etf", "ETN"): ("ExchangeTradedProduct", "ETN", "OverseasETN"),
    }
)

RELATION_METRIC_PROPERTY_BY_ID = MappingProxyType(
    {
        "krx_etf_holding_weight_pct": "holdingWeightPercentage",
        "official_holding_weight_pct": "holdingWeightPercentage",
    }
)

APPROVED_RDF_TYPES = frozenset(
    {
        "FinancialProduct",
        "ExchangeTradedProduct",
        "ETF",
        "ETN",
        "Bond",
        "DomesticBond",
        "FixedRateBond",
        "FloatingRateBond",
        "PublicFund",
        "PublicOfferingFund",
        "RepresentativeFund",
        "FundShareClass",
        "DomesticETF",
        "DomesticETN",
        "OverseasETF",
        "OverseasETN",
        "Organization",
        "AssetManager",
        "Issuer",
        "Company",
        "Security",
        "EquitySecurity",
        "DebtSecurity",
        "Index",
        "Theme",
        "Industry",
        "Market",
        "Region",
        "AssetClass",
        "ProductRiskGrade",
        "CreditGrade",
        "PolicyProgram",
        "OfficialDocument",
        "DocumentChunk",
        "RiskFactor",
    }
)


@dataclass(frozen=True, slots=True)
class EntityProjection:
    dataset_version: str
    entity_id: str
    rdf_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceProjection:
    dataset_version: str
    source_id: str
    publisher_id: str


@dataclass(frozen=True, slots=True)
class EvidenceProjection:
    dataset_version: str
    evidence_id: str
    source_id: str
    applicable_date: date | None
    valid_from: date | None
    valid_to: date | None
    published_at: datetime | None
    available_at: datetime | None
    cutoff_status: str


@dataclass(frozen=True, slots=True)
class RelationMetricProjection:
    dataset_version: str
    observation_id: str
    relation_id: str
    metric_id: str
    numeric_value: Decimal
    unit: str | None
    applicable_date: date | None


@dataclass(frozen=True, slots=True)
class RelationProjection:
    dataset_version: str
    relation_id: str
    subject_id: str
    predicate_id: str
    object_id: str
    valid_from: date | None
    valid_to: date | None
    evidence_ids: tuple[str, ...]
    metrics: tuple[RelationMetricProjection, ...] = ()


@dataclass(frozen=True, slots=True)
class GraphProjectionBatch:
    dataset_version: str
    cutoff_date: date
    entities: tuple[EntityProjection, ...]
    sources: tuple[SourceProjection, ...]
    evidences: tuple[EvidenceProjection, ...]
    relations: tuple[RelationProjection, ...]


@dataclass(frozen=True, slots=True)
class GraphArtifacts:
    data_nquads: bytes
    evidence_nquads: bytes
    entity_type_counts: Mapping[str, int]
    predicate_counts: Mapping[str, int]

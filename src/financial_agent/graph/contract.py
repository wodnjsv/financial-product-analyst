from __future__ import annotations

from types import MappingProxyType

from rdflib import Namespace


ONTOLOGY_IRI = "urn:ontology:financial-product:v1"
FP = Namespace(f"{ONTOLOGY_IRI}#")

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
        ("domestic_etf", "ETF"): ("ETF", "DomesticETF"),
        ("domestic_etf", "ETN"): ("ETN", "DomesticETN"),
        ("overseas_etf", "ETF"): ("ETF", "OverseasETF"),
        ("overseas_etf", "ETN"): ("ETN", "OverseasETN"),
    }
)

RELATION_METRIC_PROPERTY_BY_ID = MappingProxyType(
    {
        "krx_etf_holding_weight_pct": "holdingWeightPercentage",
        "official_holding_weight_pct": "holdingWeightPercentage",
    }
)

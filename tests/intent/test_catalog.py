from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import MappingProxyType

import pytest

from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.intent.catalog import compile_catalog, load_catalog
from financial_agent.graph.contract import (
    APPROVED_PREDICATES,
    SHACL_RELATIVE_PATHS,
    TBOX_RELATIVE_PATHS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_FAMILIES = {
    "domestic_bond",
    "domestic_etf",
    "overseas_etf",
    "public_fund",
}
EXPECTED_CONCEPT_IDS = {
    "asset_class",
    "availability_status",
    "credit_grade",
    "currency",
    "hedge_policy",
    "offering_type",
    "official_product_name",
    "pension_eligibility",
    "product_alias",
    "product_risk_grade",
    "rate_structure",
    "region",
    "sale_status",
    "aum",
    "fee_rate",
    "intraday_indicative_nav",
    "market_price",
    "maturity_date",
    "nav",
    "premium_discount_rate",
    "remaining_days",
    "remaining_maturity",
    "trailing_1y_historical_cumulative_return",
    "yield_rate",
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
    "investment_strategy",
    "official_update",
    "product_structure",
    "risk_factor",
    "supporting_document",
}
EXPECTED_FAMILIES_BY_CONCEPT = {
    "asset_class": EXPECTED_FAMILIES,
    "currency": EXPECTED_FAMILIES,
    "official_product_name": EXPECTED_FAMILIES,
    "product_alias": EXPECTED_FAMILIES,
    "region": EXPECTED_FAMILIES,
    "availability_status": {"domestic_bond"},
    "credit_grade": {"domestic_bond"},
    "rate_structure": {"domestic_bond"},
    "hedge_policy": {"domestic_etf", "overseas_etf", "public_fund"},
    "offering_type": {"public_fund"},
    "sale_status": {"public_fund"},
    "pension_eligibility": {"domestic_etf", "public_fund"},
    "product_risk_grade": {"domestic_etf", "overseas_etf", "public_fund"},
    "aum": {"domestic_etf", "overseas_etf", "public_fund"},
    "fee_rate": {"domestic_etf", "overseas_etf", "public_fund"},
    "nav": {"domestic_etf", "overseas_etf", "public_fund"},
    "trailing_1y_historical_cumulative_return": {
        "domestic_etf",
        "overseas_etf",
        "public_fund",
    },
    "intraday_indicative_nav": {"domestic_etf"},
    "market_price": {"domestic_etf", "overseas_etf"},
    "premium_discount_rate": {"domestic_etf", "overseas_etf"},
    "maturity_date": {"domestic_bond"},
    "remaining_days": {"domestic_bond"},
    "remaining_maturity": {"domestic_bond"},
    "yield_rate": {"domestic_bond"},
}


def copy_catalog_and_ontology_without_tests(destination: Path) -> Path:
    """Create the complete production catalog input set with no test tree."""
    for relative_path in (*TBOX_RELATIVE_PATHS, *SHACL_RELATIVE_PATHS):
        source = PROJECT_ROOT / relative_path
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for name in ("semantic-query-catalog.v1.json", "korean-nlu-overlay.v1.json"):
        source = PROJECT_ROOT / "config" / "intent" / name
        target = destination / "config" / "intent" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return destination


def test_catalog_build_does_not_read_gold(tmp_path: Path) -> None:
    """Catches a production dependency on the evaluation-only gold question file."""
    project = copy_catalog_and_ontology_without_tests(tmp_path)

    first = load_catalog(project)
    second = load_catalog(project)

    assert first.catalog_hash == second.catalog_hash
    assert first.overlay_hash == second.overlay_hash


def test_catalog_uses_frozen_runtime_axes() -> None:
    """Catches a resolver-owned copy or subset of ProductFamily or IntentType."""
    snapshot = load_catalog(PROJECT_ROOT)

    assert set(snapshot.product_family_ids) == {item.value for item in ProductFamily}
    assert set(snapshot.action_ids) == {item.value for item in IntentType}


def test_catalog_has_exact_initial_concepts_and_family_applicability() -> None:
    """Catches omitted concepts or broadened applicability that changes semantic scope."""
    snapshot = load_catalog(PROJECT_ROOT)

    assert set(snapshot.concepts_by_id) == EXPECTED_CONCEPT_IDS
    for concept_id, expected_families in EXPECTED_FAMILIES_BY_CONCEPT.items():
        assert set(snapshot.concepts_by_id[concept_id].allowed_product_families) == expected_families


def test_relation_concepts_are_the_approved_tbox_predicates() -> None:
    """Catches a relation registry drifting from the approved ontology predicates."""
    snapshot = load_catalog(PROJECT_ROOT)

    relation_ids = {
        concept.id
        for concept in snapshot.concepts_by_id.values()
        if concept.kind == "relation"
    }

    assert relation_ids == APPROVED_PREDICATES


def test_overlay_preserves_required_direct_ambiguous_and_group_aliases() -> None:
    """Catches Korean NLU aliases becoming entity data or losing collision semantics."""
    snapshot = load_catalog(PROJECT_ROOT)

    assert snapshot.alias_candidates["AUM"] == ("aum",)
    assert snapshot.alias_candidates["순자산"] == ("aum",)
    assert snapshot.alias_candidates["순자산총액"] == ("aum",)
    assert snapshot.alias_candidates["1년 수익률"] == (
        "trailing_1y_historical_cumulative_return",
    )
    assert snapshot.alias_candidates["연간 수익률"] == (
        "trailing_1y_historical_cumulative_return",
    )
    assert snapshot.alias_candidates["위험등급"] == ("credit_grade", "product_risk_grade")
    assert snapshot.alias_candidates["운용사"] == ("managedBy",)
    assert snapshot.alias_candidates["발행사"] == ("issuedBy",)
    assert snapshot.alias_candidates["구성종목"] == ("containsSecurity", "holdsSecurity")
    assert snapshot.alias_candidates["비슷한"] == ("similar",)
    assert snapshot.alias_kinds["ETF"] == "group"


def test_catalog_snapshot_mappings_are_immutable() -> None:
    """Catches callers mutating a loaded catalog after its reproducibility hash is fixed."""
    snapshot = load_catalog(PROJECT_ROOT)

    assert isinstance(snapshot.concepts_by_id, MappingProxyType)
    with pytest.raises(TypeError):
        snapshot.concepts_by_id["new"] = snapshot.concepts_by_id["aum"]  # type: ignore[index]


def test_catalog_exposes_pinned_tbox_transitive_class_ancestors() -> None:
    """Catches losing ontology ancestry needed for request-time type checks."""
    snapshot = load_catalog(PROJECT_ROOT)
    ancestors = getattr(snapshot, "class_ancestor_ids", {})

    assert {"ETF", "ExchangeTradedProduct", "FinancialProduct"} <= set(
        ancestors.get("DomesticETF", ())
    )
    assert "FinancialProduct" in ancestors.get("ETF", ())


def test_compile_catalog_rejects_direct_alias_collision() -> None:
    """Catches a direct Korean expression resolving to multiple semantic IDs."""
    catalog_payload = (PROJECT_ROOT / "config/intent/semantic-query-catalog.v1.json").read_bytes()
    overlay = json.loads(
        (PROJECT_ROOT / "config/intent/korean-nlu-overlay.v1.json").read_text("utf-8")
    )
    overlay["entries"].append(
        {
            "semantic_id": "fee_rate",
            "preferred_label": "수수료율",
            "aliases": ["순자산"],
            "alias_kind": "direct",
            "negative_semantic_ids": [],
        }
    )
    overlay_payload = json.dumps(overlay, ensure_ascii=False).encode("utf-8")

    with pytest.raises(ValueError, match="direct alias"):
        compile_catalog(
            catalog_payload,
            overlay_payload,
            ontology_paths=tuple(PROJECT_ROOT / path for path in TBOX_RELATIVE_PATHS),
            shacl_paths=tuple(PROJECT_ROOT / path for path in SHACL_RELATIVE_PATHS),
        )


def test_compile_catalog_rejects_unauthorized_relation_endpoint_type() -> None:
    """Catches a valid TBox class expanding a relation beyond its approved endpoints."""
    catalog = json.loads(
        (PROJECT_ROOT / "config/intent/semantic-query-catalog.v1.json").read_text("utf-8")
    )
    holds_security = next(
        concept for concept in catalog["concepts"] if concept["id"] == "holdsSecurity"
    )
    holds_security["allowed_ontology_types"].append("Company")
    overlay_payload = (PROJECT_ROOT / "config/intent/korean-nlu-overlay.v1.json").read_bytes()

    with pytest.raises(ValueError, match="relation ontology types"):
        compile_catalog(
            json.dumps(catalog, ensure_ascii=False).encode("utf-8"),
            overlay_payload,
            ontology_paths=tuple(PROJECT_ROOT / path for path in TBOX_RELATIVE_PATHS),
            shacl_paths=tuple(PROJECT_ROOT / path for path in SHACL_RELATIVE_PATHS),
        )


def test_catalog_preserves_tbox_derived_relation_roles() -> None:
    """Catches flattening relation endpoints so a later consumer can reverse roles."""
    holds_security = load_catalog(PROJECT_ROOT).concepts_by_id["holdsSecurity"]

    assert holds_security.subject_ontology_types == ("ETF", "PublicFund")
    assert holds_security.object_ontology_types == ("Security",)


def test_catalog_hash_canonicalizes_relation_endpoint_order() -> None:
    """Catches endpoint-order-only edits changing the catalog reproducibility hash."""
    catalog = json.loads(
        (PROJECT_ROOT / "config/intent/semantic-query-catalog.v1.json").read_text("utf-8")
    )
    reordered = json.loads(json.dumps(catalog))
    holds_security = next(
        concept for concept in reordered["concepts"] if concept["id"] == "holdsSecurity"
    )
    holds_security["subject_ontology_types"].reverse()
    overlay_payload = (PROJECT_ROOT / "config/intent/korean-nlu-overlay.v1.json").read_bytes()
    paths = tuple(PROJECT_ROOT / path for path in TBOX_RELATIVE_PATHS)
    shape_paths = tuple(PROJECT_ROOT / path for path in SHACL_RELATIVE_PATHS)

    original = compile_catalog(
        json.dumps(catalog, ensure_ascii=False).encode("utf-8"),
        overlay_payload,
        ontology_paths=paths,
        shacl_paths=shape_paths,
    )
    changed_order = compile_catalog(
        json.dumps(reordered, ensure_ascii=False).encode("utf-8"),
        overlay_payload,
        ontology_paths=paths,
        shacl_paths=shape_paths,
    )

    assert changed_order.catalog_hash == original.catalog_hash


def test_gold_question_semantics_are_consumers_of_the_catalog() -> None:
    """Catches a catalog that no longer covers semantics exercised by gold questions."""
    gold = json.loads((PROJECT_ROOT / "tests/gold/core_questions.json").read_text("utf-8"))
    snapshot = load_catalog(PROJECT_ROOT)
    gold_ids: set[str] = set()
    for case in gold["cases"]:
        requirements = case["requirements"]
        for key in ("attributes", "metrics", "relations", "document_topics"):
            for item in requirements.get(key, []):
                gold_ids.add(item.get("id", item.get("predicate")))

    assert gold_ids <= set(snapshot.concepts_by_id)

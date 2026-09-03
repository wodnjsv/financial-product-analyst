import pytest

from financial_agent.graph.entity_types import (
    EntityTypeProjectionError,
    ProductTypeFact,
    project_entity_ontology_type_ids,
)


def test_projection_preserves_independent_etf_and_share_class_roles() -> None:
    """Catches collapsing two valid, non-ancestor roles into one leaf type."""
    assert project_entity_ontology_type_ids(
        entity_id="product-one",
        storage_entity_type="product",
        product_family="domestic_etf",
        identifier_schemes=("PRFD_ITM_NO",),
        product_type_facts=(ProductTypeFact("present", "ETF", "text"),),
    ) == (
        "DomesticETF",
        "ETF",
        "ExchangeTradedProduct",
        "FinancialProduct",
        "FundShareClass",
    )


def test_projection_preserves_storage_subtype_and_relation_roles() -> None:
    assert project_entity_ontology_type_ids(
        entity_id="manager-one",
        storage_entity_type="institution",
        institution_kind="asset_manager",
    ) == ("AssetManager", "Organization")
    assert project_entity_ontology_type_ids(
        entity_id="representative-one",
        storage_entity_type="product",
        product_family="public_fund",
        is_share_class_subject=True,
    ) == ("FinancialProduct", "PublicFund", "RepresentativeFund")


@pytest.mark.parametrize("institution_kind", ["organizer", "regulator", "central_bank"])
def test_unmapped_institution_kinds_keep_the_organization_base_type(
    institution_kind: str,
) -> None:
    """Catches rejecting valid storage kinds that have no ontology refinement."""
    assert project_entity_ontology_type_ids(
        entity_id=f"institution-{institution_kind}",
        storage_entity_type="institution",
        institution_kind=institution_kind,
    ) == ("Organization",)


def test_unmapped_security_kind_keeps_the_security_base_type() -> None:
    """Catches treating an optional subtype refinement as a closed vocabulary."""
    assert project_entity_ontology_type_ids(
        entity_id="security-other",
        storage_entity_type="security",
        security_kind="other_security",
    ) == ("Security",)


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "storage_entity_type": "company",
            "product_family": "public_fund",
        },
        {
            "storage_entity_type": "product",
            "product_family": "domestic_etf",
            "product_type_facts": (
                ProductTypeFact("present", "ETF", "text"),
                ProductTypeFact("present", "ETN", "text"),
            ),
        },
        {
            "storage_entity_type": "product",
            "product_family": "domestic_etf",
            "product_type_facts": (ProductTypeFact("missing", "ETF", "text"),),
        },
    ],
)
def test_projection_fails_closed_on_inconsistent_source_facts(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(EntityTypeProjectionError):
        project_entity_ontology_type_ids(entity_id="bad-entity", **kwargs)

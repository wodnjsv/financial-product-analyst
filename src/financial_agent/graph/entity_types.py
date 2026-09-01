"""Canonical source-fact projection to ontology entity types."""

from __future__ import annotations

from dataclasses import dataclass

from .contract import (
    APPROVED_RDF_TYPES,
    ENTITY_CLASS_BY_TYPE,
    ETP_CLASSES_BY_FAMILY_AND_TYPE,
    PRODUCT_BASE_CLASSES_BY_FAMILY,
)


_INSTITUTION_CLASS_BY_KIND = {
    "asset_manager": "AssetManager",
    "issuer": "Issuer",
    "exchange": "Market",
}
_SECURITY_CLASS_BY_KIND = {"listed_equity": "EquitySecurity"}


class EntityTypeProjectionError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class ProductTypeFact:
    value_status: str
    text_value: str | None
    value_kind: str


def project_entity_ontology_type_ids(
    *,
    entity_id: str,
    storage_entity_type: str,
    product_family: str | None = None,
    security_kind: str | None = None,
    institution_kind: str | None = None,
    identifier_schemes: tuple[str, ...] = (),
    product_type_facts: tuple[ProductTypeFact, ...] = (),
    is_share_class_subject: bool = False,
    is_share_class_object: bool = False,
) -> tuple[str, ...]:
    """Project one catalog entity using the same source facts as the ABox."""

    base_type = ENTITY_CLASS_BY_TYPE.get(storage_entity_type)
    if base_type is None:
        _fail("unsupported_entity_type", f"{entity_id}:{storage_entity_type}")
    subtype_types = {
        subtype_type
        for subtype_type, subtype_value in (
            ("product", product_family),
            ("security", security_kind),
            ("institution", institution_kind),
        )
        if subtype_value is not None
    }
    if len(subtype_types) > 1 or (
        subtype_types and storage_entity_type not in subtype_types
    ):
        _fail(
            "inconsistent_entity_subtype",
            f"{entity_id}:{storage_entity_type}:{','.join(sorted(subtype_types))}",
        )

    ontology_types = {base_type}
    if product_family is not None:
        family_types = PRODUCT_BASE_CLASSES_BY_FAMILY.get(product_family)
        if family_types is None:
            _fail("unsupported_product_family", f"{entity_id}:{product_family}")
        ontology_types.update(family_types)
    if institution_kind is not None:
        institution_type = _INSTITUTION_CLASS_BY_KIND.get(institution_kind)
        if institution_type is not None:
            ontology_types.add(institution_type)
    if security_kind is not None:
        security_type = _SECURITY_CLASS_BY_KIND.get(security_kind)
        if security_type is not None:
            ontology_types.add(security_type)

    if "PRFD_ITM_NO" in identifier_schemes:
        if "FinancialProduct" not in ontology_types:
            _fail("invalid_share_class_type", entity_id)
        ontology_types.add("FundShareClass")

    product_types: set[str] = set()
    for fact in product_type_facts:
        if (
            fact.value_kind != "text"
            or fact.value_status != "present"
            or fact.text_value not in {"ETF", "ETN"}
        ):
            _fail("invalid_product_type_fact", entity_id)
        product_types.add(fact.text_value)
    if len(product_types) > 1:
        _fail("conflicting_product_type_facts", entity_id)
    if product_types:
        product_type = next(iter(product_types))
        classes = ETP_CLASSES_BY_FAMILY_AND_TYPE.get((product_family, product_type))
        if classes is None:
            _fail(
                "conflicting_product_type_fact",
                f"{entity_id}:{product_family}:{product_type}",
            )
        ontology_types.update(classes)

    if is_share_class_subject:
        if "PublicFund" not in ontology_types:
            _fail("missing_relation_type", f"{entity_id}:subject")
        ontology_types.add("RepresentativeFund")
    if is_share_class_object:
        if "FinancialProduct" not in ontology_types:
            _fail("missing_relation_type", f"{entity_id}:object")
        ontology_types.add("FundShareClass")
    if {"ETF", "ETN"} <= ontology_types:
        _fail("conflicting_entity_types", f"{entity_id}:ETF and ETN")
    if not ontology_types <= APPROVED_RDF_TYPES:
        _fail("unsupported_ontology_type", entity_id)
    return tuple(sorted(ontology_types))


def _fail(code: str, detail: str) -> None:
    raise EntityTypeProjectionError(code, detail)

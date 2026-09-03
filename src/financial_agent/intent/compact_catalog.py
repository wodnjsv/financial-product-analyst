"""Model-facing projection of the registered semantic catalog."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from financial_agent.contracts.base import ContractModel, Identifier, Sha256Hex

from .catalog import SemanticCatalogSnapshot


_CONCEPT_KINDS = Literal["attribute", "metric", "relation", "document_topic"]
_PHYSICAL_SCHEMA_TOKENS = (
    "SELECT ",
    "FROM ",
    "catalog.observation",
    "metric_id",
    "column_name",
)


class CompactSemanticConceptV1(ContractModel):
    semantic_id: Identifier
    preferred_label_ko: str = Field(min_length=1)
    definition_ko: str = Field(min_length=1)
    concept_kind: _CONCEPT_KINDS
    value_kind: str = Field(min_length=1)
    applicable_family_ids: tuple[Identifier, ...]
    required_qualifier_ids: tuple[Identifier, ...]
    disambiguation_ko: str | None = None


class CompactSemanticCatalogV1(ContractModel):
    projection_version: Literal["compact-semantic-catalog.v1"]
    source_catalog_hash: Sha256Hex
    source_overlay_hash: Sha256Hex
    concepts: tuple[CompactSemanticConceptV1, ...] = Field(min_length=1)


def build_compact_semantic_catalog(
    snapshot: SemanticCatalogSnapshot,
) -> CompactSemanticCatalogV1:
    """Generate deterministic semantic cards without exposing execution details."""
    cards = tuple(
        _build_card(snapshot, semantic_id)
        for semantic_id in sorted(snapshot.concepts_by_id)
    )
    if len({card.semantic_id for card in cards}) != len(cards):
        raise ValueError("compact semantic card IDs must be unique")
    if {card.semantic_id for card in cards} != set(snapshot.concepts_by_id):
        raise ValueError("compact semantic cards must cover every catalog concept")
    return CompactSemanticCatalogV1(
        projection_version="compact-semantic-catalog.v1",
        source_catalog_hash=snapshot.catalog_hash,
        source_overlay_hash=snapshot.overlay_hash,
        concepts=tuple(sorted(cards, key=lambda card: (card.concept_kind, card.semantic_id))),
    )


def _build_card(
    snapshot: SemanticCatalogSnapshot, semantic_id: str
) -> CompactSemanticConceptV1:
    concept = snapshot.concepts_by_id[semantic_id]
    if concept.id != semantic_id:
        raise ValueError("compact semantic card ID must match catalog key")
    if not concept.definition_ko.strip():
        raise ValueError(f"compact semantic card requires a definition: {semantic_id}")
    if not set(concept.allowed_product_families) <= set(snapshot.product_family_ids):
        raise ValueError(f"compact semantic card has an unknown family: {semantic_id}")
    preferred_label = snapshot.preferred_labels_by_semantic_id.get(
        semantic_id, concept.definition_ko
    )
    card = CompactSemanticConceptV1(
        semantic_id=semantic_id,
        preferred_label_ko=preferred_label,
        definition_ko=concept.definition_ko,
        concept_kind=concept.kind,
        value_kind=concept.value_kind,
        applicable_family_ids=tuple(sorted(concept.allowed_product_families)),
        required_qualifier_ids=tuple(sorted(concept.required_qualifiers)),
        disambiguation_ko=snapshot.disambiguation_by_semantic_id.get(semantic_id),
    )
    _reject_physical_schema_tokens(card)
    return card


def _reject_physical_schema_tokens(card: CompactSemanticConceptV1) -> None:
    payload = "\n".join(
        value
        for value in (
            card.preferred_label_ko,
            card.definition_ko,
            card.disambiguation_ko,
        )
        if value is not None
    )
    if any(token in payload for token in _PHYSICAL_SCHEMA_TOKENS):
        raise ValueError("compact semantic cards cannot contain physical-schema fields")

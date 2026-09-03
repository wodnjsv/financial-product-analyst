from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from financial_agent.contracts import canonical_json_bytes
from financial_agent.intent.compact_catalog import (
    CompactSemanticConceptV1,
    build_compact_semantic_catalog,
)
from financial_agent.intent.catalog import load_hybrid_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_compact_catalog_contains_every_registered_concept() -> None:
    snapshot = load_hybrid_catalog(PROJECT_ROOT)

    compact = build_compact_semantic_catalog(snapshot)

    assert {item.semantic_id for item in compact.concepts} == set(snapshot.concepts_by_id)
    assert len(compact.concepts) == 42


def test_compact_catalog_contains_no_physical_schema_tokens() -> None:
    payload = canonical_json_bytes(
        build_compact_semantic_catalog(load_hybrid_catalog(PROJECT_ROOT))
    ).decode("utf-8")

    for forbidden in (
        "SELECT ",
        "FROM ",
        "catalog.observation",
        "metric_id",
        "column_name",
    ):
        assert forbidden not in payload


def test_compact_catalog_sorts_cards_and_keeps_model_labels_out_of_alias_locks() -> None:
    snapshot = load_hybrid_catalog(PROJECT_ROOT)
    compact = build_compact_semantic_catalog(snapshot)

    assert [(item.concept_kind, item.semantic_id) for item in compact.concepts] == sorted(
        (item.concept_kind, item.semantic_id) for item in compact.concepts
    )
    assert snapshot.preferred_labels_by_semantic_id["nav"] == "순자산가치"
    assert "순자산가치" not in snapshot.alias_candidates


def test_compact_card_rejects_physical_schema_fields() -> None:
    with pytest.raises(ValidationError, match="metric_id"):
        CompactSemanticConceptV1.model_validate(
            {
                "semantic_id": "aum",
                "preferred_label_ko": "순자산총액",
                "definition_ko": "순자산총액",
                "concept_kind": "metric",
                "value_kind": "decimal",
                "applicable_family_ids": ["domestic_etf"],
                "required_qualifier_ids": ["as_of"],
                "metric_id": "not-allowed",
            }
        )


def test_compact_catalog_rejects_physical_schema_tokens_in_emitted_tuples() -> None:
    snapshot = load_hybrid_catalog(PROJECT_ROOT)
    unsafe_concept = snapshot.concepts_by_id["aum"].model_copy(
        update={"required_qualifiers": ("catalog.observation",)}
    )
    unsafe_snapshot = replace(
        snapshot,
        concepts_by_id={**snapshot.concepts_by_id, "aum": unsafe_concept},
    )

    with pytest.raises(ValueError, match="physical-schema"):
        build_compact_semantic_catalog(unsafe_snapshot)

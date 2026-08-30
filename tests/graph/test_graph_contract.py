from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import quote, unquote

import pytest

from financial_agent.graph.contract import (
    EntityProjection,
    EvidenceProjection,
    GraphProjectionBatch,
    RelationMetricProjection,
    RelationProjection,
    SourceProjection,
)
from financial_agent.graph.exporter import (
    entity_iri,
    evidence_iri,
    holding_weight_observation_iri,
    relation_iri,
    source_iri,
)


def test_entity_iri_percent_encodes_utf8_reversibly() -> None:
    """Catches unsafe or lossy dynamic entity-ID interpolation."""
    entity_id = "상품/α beta?#%"

    iri = entity_iri(entity_id)

    encoded = str(iri).removeprefix("urn:financial-agent:entity:")
    assert encoded == quote(entity_id, safe="")
    assert unquote(encoded) == entity_id


def test_entity_iri_is_stable_while_record_iris_are_versioned() -> None:
    """Catches adding a dataset version to canonical entities or omitting it from records."""
    assert entity_iri("entity/1") == entity_iri("entity/1")
    assert str(relation_iri("version/1", "relation/1")) == (
        "urn:financial-agent:relation:version%2F1:relation%2F1"
    )
    assert str(evidence_iri("version/1", "evidence/1")) == (
        "urn:financial-agent:evidence:version%2F1:evidence%2F1"
    )
    assert str(source_iri("version/1", "source/1")) == (
        "urn:financial-agent:source:version%2F1:source%2F1"
    )
    assert str(holding_weight_observation_iri("version/1", "observation/1")) == (
        "urn:financial-agent:holding-weight:version%2F1:observation%2F1"
    )
    assert relation_iri("version/1", "relation/1") != relation_iri(
        "version/2", "relation/1"
    )
    assert evidence_iri("version/1", "evidence/1") != evidence_iri(
        "version/2", "evidence/1"
    )
    assert source_iri("version/1", "source/1") != source_iri(
        "version/2", "source/1"
    )


@pytest.mark.parametrize(
    "build",
    [
        lambda value: entity_iri(value),
        lambda value: relation_iri(value, "relation-1"),
        lambda value: relation_iri("version-1", value),
        lambda value: evidence_iri(value, "evidence-1"),
        lambda value: evidence_iri("version-1", value),
        lambda value: source_iri(value, "source-1"),
        lambda value: source_iri("version-1", value),
        lambda value: holding_weight_observation_iri(value, "observation-1"),
        lambda value: holding_weight_observation_iri("version-1", value),
    ],
)
@pytest.mark.parametrize("value", ["", "   ", "contains\x00nul"])
def test_iri_helpers_reject_empty_and_nul_segments(build, value: str) -> None:
    """Catches ambiguous blank segments and NUL-bearing opaque identifiers."""
    with pytest.raises(ValueError, match="invalid_identifier"):
        build(value)


def test_projection_contract_is_frozen_and_preserves_exact_types() -> None:
    """Catches mutable boundary records or coercion of exact financial values."""
    metric = RelationMetricProjection(
        dataset_version="2026-08-24-v1",
        observation_id="weight-observation-1",
        relation_id="relation-1",
        metric_id="krx_etf_holding_weight_pct",
        numeric_value=Decimal("27.40"),
        unit="percentage_point",
        applicable_date=date(2026, 8, 24),
    )
    relation = RelationProjection(
        dataset_version="2026-08-24-v1",
        relation_id="relation-1",
        subject_id="product-1",
        predicate_id="holdsSecurity",
        object_id="security-1",
        valid_from=date(2026, 8, 1),
        valid_to=date(2026, 8, 24),
        evidence_ids=("evidence-1",),
        metrics=(metric,),
    )
    batch = GraphProjectionBatch(
        dataset_version="2026-08-24-v1",
        cutoff_date=date(2026, 8, 24),
        entities=(
            EntityProjection("2026-08-24-v1", "product-1", ("ETF",)),
            EntityProjection("2026-08-24-v1", "security-1", ("Security",)),
        ),
        sources=(SourceProjection("2026-08-24-v1", "source-1", "publisher-1"),),
        evidences=(
            EvidenceProjection(
                "2026-08-24-v1",
                "evidence-1",
                "source-1",
                date(2026, 8, 24),
                date(2026, 8, 1),
                date(2026, 8, 24),
                datetime(2026, 8, 24, 0, tzinfo=timezone.utc),
                datetime(2026, 8, 24, 1, tzinfo=timezone.utc),
                "eligible",
            ),
        ),
        relations=(relation,),
    )

    assert batch.relations[0].metrics[0].numeric_value == Decimal("27.40")
    with pytest.raises(AttributeError):
        batch.dataset_version = "changed"  # type: ignore[misc]


def test_source_projection_cannot_carry_raw_locator_fields() -> None:
    """Catches expansion of the pure ID-only Source projection boundary."""
    source = SourceProjection("2026-08-24-v1", "source-1", "publisher-1")

    assert not hasattr(source, "locator")
    assert not hasattr(source, "raw_value")
    assert not hasattr(source, "checksum")

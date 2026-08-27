from __future__ import annotations

import pytest

from financial_agent.ingestion.models import MappedRow
from financial_agent.ingestion.official.authority import (
    OfficialEnrichmentScopeError,
    validate_official_enrichment_scope,
)


def _mapped_row(
    *,
    observations: tuple[dict[str, object], ...] = (),
    relations: tuple[dict[str, object], ...] = (),
    evidence: tuple[dict[str, object], ...] = (),
) -> MappedRow:
    return MappedRow(
        row_number=1,
        disposition="accepted",
        records_by_table={
            "observation.observation_record": observations,
            "relation.relation_record": relations,
            "evidence.evidence_record": evidence,
        },
        issues=(),
    )


def test_external_product_metric_is_rejected_even_when_organizer_is_missing() -> None:
    row = _mapped_row(
        observations=(
            {
                "entity_id": "organizer-etf-1",
                "relation_id": None,
                "metric_id": "krx_etf_nav_per_share_krw",
            },
        )
    )

    with pytest.raises(OfficialEnrichmentScopeError) as captured:
        validate_official_enrichment_scope("KRX_ETF_DAILY", row)

    assert captured.value.code == "OFFICIAL_ENRICHMENT_SCOPE_VIOLATION"
    assert "krx_etf_nav_per_share_krw" not in str(captured.value)


def test_holding_relation_and_holding_metrics_are_allowed() -> None:
    row = _mapped_row(
        relations=(
            {
                "relation_id": "holding-1",
                "subject_id": "organizer-etf-1",
                "predicate_id": "holdsSecurity",
                "object_id": "security-1",
            },
        ),
        observations=(
            {
                "entity_id": None,
                "relation_id": "holding-1",
                "metric_id": "krx_etf_holding_weight_pct",
            },
        ),
        evidence=(
            {
                "evidence_kind": "relation",
                "predicate_id": "holdsSecurity",
            },
            {
                "evidence_kind": "observation",
                "predicate_id": "krx_etf_holding_weight_pct",
            },
            {
                "evidence_kind": "query_scope",
                "predicate_id": "holdsSecurityCoverage",
            },
        ),
    )

    validate_official_enrichment_scope("KRX_ETF_PDF", row)


@pytest.mark.parametrize(
    ("source_code", "row"),
    (
        (
            "KRX_ETF_PDF",
            _mapped_row(
                observations=(
                    {
                        "entity_id": "organizer-etf-1",
                        "relation_id": None,
                        "metric_id": "krx_etf_creation_cash_amount_krw",
                    },
                )
            ),
        ),
        (
            "SEC_NPORT_2026Q2",
            _mapped_row(
                relations=(
                    {
                        "relation_id": "manager-1",
                        "subject_id": "organizer-etf-1",
                        "predicate_id": "managedBy",
                        "object_id": "manager-1",
                    },
                )
            ),
        ),
    ),
)
def test_organizer_overlapping_product_facts_are_rejected(
    source_code: str,
    row: MappedRow,
) -> None:
    with pytest.raises(OfficialEnrichmentScopeError) as captured:
        validate_official_enrichment_scope(source_code, row)

    assert captured.value.code == "OFFICIAL_ENRICHMENT_SCOPE_VIOLATION"

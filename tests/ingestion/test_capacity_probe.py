from __future__ import annotations

from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.ingestion import capacity_probe
from financial_agent.ingestion.capacity_probe import (
    CapacityProbeError,
    count_nport_holding_relations,
    estimate_stage03b_capacity,
    measure_application_storage_bytes,
    require_capacity_probe_dataset_absent,
)
from financial_agent.ingestion.mapping.common import make_record_hash
from financial_agent.ingestion.models import BuildReport, MappedRow
from financial_agent.ingestion.writer import DatasetBuildWriter
from financial_agent.ingestion.pipeline import CUTOFF_DATE
from tests.ingestion.test_writer import _synthetic_row


GIB = 1024**3


def _acceptance_report(
    *,
    dataset_version: str = "current-build-a",
) -> capacity_probe.DatabaseAcceptanceReport:
    return capacity_probe.DatabaseAcceptanceReport(
        dataset_version=dataset_version,
        cutoff_date=date(2026, 8, 24),
        dataset_manifest_hash="a" * 64,
        dataset_status="building",
        active=False,
        build_passed=True,
        source_counts={
            "PRBD01N001": {
                "accepted": 21_882,
                "limited": 0,
                "quarantined": 0,
                "rows": 21_882,
            },
            "PREF01N001": {
                "accepted": 1_780,
                "limited": 0,
                "quarantined": 0,
                "rows": 1_780,
            },
            "PREF02N001": {
                "accepted": 403,
                "limited": 5_634,
                "quarantined": 0,
                "rows": 6_037,
            },
            "PRFD01N001": {
                "accepted": 23_676,
                "limited": 0,
                "quarantined": 0,
                "rows": 23_676,
            },
        },
        table_counts={"catalog.product": 53_095},
        issue_counts={"SOURCE_IDENTIFIER_AMBIGUOUS": 126},
        component_hashes={"evidence": "b" * 64, "postgresql": "c" * 64},
        canonical_product_count=53_095,
        observation_count=100_000,
        identifier_counts_by_scheme={"ISIN": 20_000},
        relation_counts_by_predicate={"managedBy": 10_000},
        evidence_origin_counts={
            "observation": 100_000,
            "relation": 10_000,
            "document": 0,
        },
        exact_reused_identity_count=217,
        ambiguous_identifier_counts_by_scheme={"ISIN": 63, "LIPPER": 63},
        aligned_ambiguous_pair_count=63,
    )


def test_database_acceptance_repeatability_ignores_only_dataset_version() -> None:
    first = _acceptance_report(dataset_version="current-build-a")
    second = _acceptance_report(dataset_version="current-build-b")

    capacity_probe.require_matching_database_acceptance(first, second)

    assert first.reproducibility_hash == second.reproducibility_hash
    assert "dataset_version" not in first.to_reproducibility_mapping()


def test_database_acceptance_reads_the_string_tagged_value_contract() -> None:
    assert capacity_probe._tagged_string_value(
        {"type": "string", "value": "  SAMPLE  "}
    ) == "SAMPLE"
    assert capacity_probe._tagged_string_value(
        {"type": "str", "value": "SAMPLE"}
    ) is None
    assert capacity_probe._tagged_string_value(
        {"type": "null", "value": None}
    ) is None


def test_database_acceptance_repeatability_rejects_count_drift() -> None:
    first = _acceptance_report()
    second = replace(
        first,
        dataset_version="current-build-b",
        observation_count=first.observation_count + 1,
    )

    with pytest.raises(CapacityProbeError) as captured:
        capacity_probe.require_matching_database_acceptance(first, second)

    assert captured.value.code == "DATABASE_ACCEPTANCE_MISMATCH"


def test_current_rebaseline_acceptance_enforces_organizer_authority_gates() -> None:
    report = _acceptance_report()

    capacity_probe.require_current_rebaseline_acceptance(report)

    source_counts = {
        source: dict(counts) for source, counts in report.source_counts.items()
    }
    source_counts["PRBD01N001"]["rows"] -= 1
    with pytest.raises(CapacityProbeError) as captured:
        capacity_probe.require_current_rebaseline_acceptance(
            replace(report, source_counts=source_counts)
        )

    assert captured.value.code == "DATABASE_ACCEPTANCE_GATE_FAILED"


def test_capacity_estimate_scales_the_measured_nport_increment_and_rounds_up() -> None:
    estimate = estimate_stage03b_capacity(
        base_bytes=16 * GIB,
        sampled_nport_bytes=2 * GIB,
        sampled_holding_count=100_000,
        full_holding_count=1_000_000,
        current_storage_gib=20,
    )

    assert estimate.projected_nport_bytes == 20 * GIB
    assert estimate.projected_total_bytes == 36 * GIB
    assert estimate.safety_adjusted_bytes == 50_251_117_364
    assert estimate.required_storage_gib == 50
    assert estimate.recommended_storage_gib == 50
    assert estimate.additional_storage_gib == 30


def test_capacity_estimate_never_recommends_less_than_current_allocation() -> None:
    estimate = estimate_stage03b_capacity(
        base_bytes=1 * GIB,
        sampled_nport_bytes=100 * 1024**2,
        sampled_holding_count=10,
        full_holding_count=100,
        current_storage_gib=20,
    )

    assert estimate.required_storage_gib == 10
    assert estimate.recommended_storage_gib == 20
    assert estimate.additional_storage_gib == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_application_storage_measurement_observes_real_table_and_index_growth(
    ingestion_build_engine: AsyncEngine,
) -> None:
    writer = DatasetBuildWriter(ingestion_build_engine)
    dataset = f"capacity-measure-{uuid4()}"
    before = await measure_application_storage_bytes(ingestion_build_engine)

    await writer.create_building_dataset(dataset, "a" * 64, CUTOFF_DATE)
    await writer.write_rows(
        dataset,
        tuple(
            MappedRow(
                row_number=index,
                disposition="accepted",
                records_by_table={
                    "catalog.entity": (
                        payload
                        | {"record_hash": make_record_hash(payload)},
                    )
                },
                issues=(),
            )
            for index in range(1, 1_025)
            for payload in (
                {
                    "entity_id": f"capacity-measure-entity-{index}",
                    "entity_type": "theme",
                    "canonical_name": f"Capacity Measurement {index}",
                    "normalized_name": f"Capacity Measurement {index}",
                },
            )
        ),
    )
    after = await measure_application_storage_bytes(ingestion_build_engine)

    assert after > before


def _as_holding_row(row: MappedRow, *, locator_section: str) -> MappedRow:
    records = dict(row.records_by_table)
    relation = dict(records["relation.relation_record"][0])
    relation["predicate_id"] = "holdsSecurity"
    relation["record_hash"] = make_record_hash(
        {key: value for key, value in relation.items() if key != "record_hash"}
    )
    evidence_rows = list(records["evidence.evidence_record"])
    evidence = dict(evidence_rows[0])
    evidence["predicate_id"] = "holdsSecurity"
    evidence["locator_section"] = locator_section
    evidence["record_hash"] = make_record_hash(
        {key: value for key, value in evidence.items() if key != "record_hash"}
    )
    evidence_rows[0] = evidence
    records["relation.relation_record"] = (relation,)
    records["evidence.evidence_record"] = tuple(evidence_rows)
    return MappedRow(
        row_number=row.row_number,
        disposition=row.disposition,
        records_by_table=records,
        issues=row.issues,
    )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_nport_holding_count_excludes_other_holds_security_sources(
    ingestion_build_engine: AsyncEngine,
) -> None:
    writer = DatasetBuildWriter(ingestion_build_engine)
    dataset = f"capacity-holdings-{uuid4()}"
    await writer.create_building_dataset(dataset, "b" * 64, CUTOFF_DATE)
    await writer.write_rows(
        dataset,
        (
            _as_holding_row(
                _synthetic_row(uuid4().hex),
                locator_section="FUND_REPORTED_HOLDING.tsv",
            ),
            _as_holding_row(
                _synthetic_row(uuid4().hex),
                locator_section="KRX_ETF_PDF.csv",
            ),
        ),
    )

    assert await count_nport_holding_relations(
        ingestion_build_engine, dataset
    ) == 1


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_capacity_probe_rejects_an_existing_dataset_before_measurement(
    ingestion_build_engine: AsyncEngine,
) -> None:
    writer = DatasetBuildWriter(ingestion_build_engine)
    dataset = f"capacity-existing-{uuid4()}"
    await writer.create_building_dataset(dataset, "c" * 64, CUTOFF_DATE)

    with pytest.raises(CapacityProbeError) as captured:
        await require_capacity_probe_dataset_absent(
            ingestion_build_engine, dataset
        )

    assert captured.value.code == "CAPACITY_PROBE_DATASET_EXISTS"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_database_acceptance_measures_repeatable_database_aggregates(
    ingestion_build_engine: AsyncEngine,
) -> None:
    writer = DatasetBuildWriter(ingestion_build_engine)
    reports: list[capacity_probe.DatabaseAcceptanceReport] = []
    for label in ("a", "b"):
        dataset = f"acceptance-repeat-{label}-{uuid4()}"
        await writer.create_building_dataset(dataset, "d" * 64, CUTOFF_DATE)
        await writer.write_rows(dataset, (_synthetic_row("repeatable"),))
        table_counts = await writer.table_counts(dataset)
        build_report = BuildReport(
            dataset_version=dataset,
            cutoff_date=CUTOFF_DATE,
            dataset_manifest_hash="d" * 64,
            source_counts={
                "SYNTHETIC": {
                    "accepted": 1,
                    "limited": 0,
                    "quarantined": 0,
                    "rows": 1,
                }
            },
            table_counts=table_counts,
            issue_counts={},
            component_hashes={
                "evidence": "e" * 64,
                "postgresql": "f" * 64,
            },
            passed=True,
        )
        reports.append(
            await capacity_probe.measure_database_acceptance(
                ingestion_build_engine,
                build_report,
            )
        )

    first, second = reports
    capacity_probe.require_matching_database_acceptance(first, second)

    assert first.dataset_status == "building"
    assert first.active is False
    assert first.canonical_product_count == 1
    assert first.observation_count == 1
    assert first.identifier_counts_by_scheme == {"SYNTHETIC_PRODUCT": 1}
    assert first.relation_counts_by_predicate == {"managedBy": 1}
    assert first.evidence_origin_counts == {
        "document": 0,
        "observation": 1,
        "relation": 1,
    }
    assert first.exact_reused_identity_count == 0
    assert first.ambiguous_identifier_counts_by_scheme == {
        "ISIN": 0,
        "LIPPER": 0,
    }
    assert first.aligned_ambiguous_pair_count == 0

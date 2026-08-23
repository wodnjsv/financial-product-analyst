from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.ingestion.capacity_probe import (
    CapacityProbeError,
    count_nport_holding_relations,
    estimate_stage03b_capacity,
    measure_application_storage_bytes,
    require_capacity_probe_dataset_absent,
)
from financial_agent.ingestion.mapping.common import make_record_hash
from financial_agent.ingestion.models import MappedRow
from financial_agent.ingestion.writer import DatasetBuildWriter
from financial_agent.ingestion.pipeline import CUTOFF_DATE
from tests.ingestion.test_writer import _synthetic_row


GIB = 1024**3


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
    payload = {
        "entity_id": "capacity-measure-entity",
        "entity_type": "theme",
        "canonical_name": "Capacity Measurement",
        "normalized_name": "Capacity Measurement",
    }
    before = await measure_application_storage_bytes(ingestion_build_engine)

    await writer.create_building_dataset(dataset, "a" * 64, CUTOFF_DATE)
    await writer.write_rows(
        dataset,
        (
            MappedRow(
                row_number=1,
                disposition="accepted",
                records_by_table={
                    "catalog.entity": (
                        payload | {"record_hash": make_record_hash(payload)},
                    )
                },
                issues=(),
            ),
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

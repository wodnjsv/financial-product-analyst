from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.ingestion.capacity_probe import (
    measure_database_acceptance,
    require_current_rebaseline_acceptance,
)
from financial_agent.ingestion.pipeline import SOURCE_SPECS, build_organizer_dataset
from financial_agent.ingestion.sources import (
    iter_workbook_rows,
    sha256_path,
    verify_schema_header,
)


RUN_REAL_DATA = os.getenv("RUN_ORGANIZER_DATA_TESTS") == "1"
SOURCE_ROOT = os.getenv("FINANCIAL_AGENT_SOURCE_ROOT")
HAS_DATABASE = os.getenv("FINANCIAL_AGENT_TEST_DATABASE_URL") is not None


@pytest.fixture(scope="session", autouse=True)
def _require_explicit_gate_configuration() -> None:
    if RUN_REAL_DATA and (SOURCE_ROOT is None or not HAS_DATABASE):
        pytest.fail("ORGANIZER_DATA_CONFIGURATION_MISSING", pytrace=False)


def _paths(root: Path):
    data_paths = {
        code: root / spec.data_file_name for code, spec in SOURCE_SPECS.items()
    }
    schema_paths = {
        code: root / spec.schema_file_name for code, spec in SOURCE_SPECS.items()
    }
    return data_paths, schema_paths


@pytest.mark.organizer_data
@pytest.mark.skipif(
    not RUN_REAL_DATA,
    reason="explicit organizer-data gate is disabled",
)
def test_real_organizer_workbooks_match_the_approved_safe_aggregates() -> None:
    data_paths, schema_paths = _paths(Path(SOURCE_ROOT or ""))
    rows_by_source: dict[str, int] = {}
    product_types: dict[str, Counter[str]] = {}
    public_items: set[str] = set()
    representatives: set[str] = set()
    representative_sentinels = {"", "NULL", "KR0000000000", "000000000000"}

    for source_code in sorted(SOURCE_SPECS):
        spec = SOURCE_SPECS[source_code]
        assert verify_schema_header(schema_paths[source_code], spec) == (
            spec.expected_columns
        )
        count = 0
        types: Counter[str] = Counter()
        for row in iter_workbook_rows(data_paths[source_code], spec):
            count += 1
            if source_code in {"PREF01N001", "PREF02N001"}:
                types[str(row.get("pd_grp_no") or "").strip()] += 1
            elif source_code == "PRFD01N001":
                item = str(row.get("itm_no") or "").strip()
                if item:
                    public_items.add(item)
                representative = str(
                    row.get("rptt_ksd_itm_no") or ""
                ).strip()
                if representative not in representative_sentinels:
                    representatives.add(representative)
        rows_by_source[source_code] = count
        product_types[source_code] = types

    assert rows_by_source == {
        "PRBD01N001": 21_882,
        "PRFD01N001": 23_676,
        "PREF01N001": 1_780,
        "PREF02N001": 6_037,
    }
    assert product_types["PREF01N001"] == Counter({"ETF": 1_235, "ETN": 545})
    assert product_types["PREF02N001"] == Counter({"ETF": 5_972, "ETN": 65})
    assert len(public_items) == 23_676
    assert len(representatives) == 6_883

    print("PRBD01N001 rows=21882 fields=58")
    print("PREF01N001 rows=1780 fields=98 etf=1235 etn=545")
    print("PREF02N001 rows=6037 fields=49 etf=5972 etn=65")
    print("PRFD01N001 rows=23676 fields=75 items=23676 representatives=6883")
    print("TOTAL rows=53375")


@pytest.mark.organizer_data
@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_REAL_DATA,
    reason="explicit organizer-data gate is disabled",
)
async def test_real_organizer_dataset_loads_but_never_activates(
    ingestion_build_engine: AsyncEngine,
    ingestion_admin_engine: AsyncEngine,
) -> None:
    data_paths, schema_paths = _paths(Path(SOURCE_ROOT or ""))
    data_hashes = {code: sha256_path(path) for code, path in data_paths.items()}
    schema_hashes = {
        code: sha256_path(path) for code, path in schema_paths.items()
    }
    dataset_version = f"organizer-acceptance-{uuid4().hex}"

    report = await build_organizer_dataset(
        ingestion_build_engine,
        dataset_version=dataset_version,
        data_paths=data_paths,
        schema_paths=schema_paths,
        data_sha256=data_hashes,
        schema_sha256=schema_hashes,
    )

    assert report.passed is True
    assert sum(counts["rows"] for counts in report.source_counts.values()) == 53_375
    assert report.table_counts["evidence.source_record"] == 4
    assert set(report.component_hashes) == {"evidence", "postgresql"}
    acceptance = await measure_database_acceptance(
        ingestion_build_engine,
        report,
    )
    require_current_rebaseline_acceptance(acceptance)
    assert acceptance.exact_reused_identity_count == 217
    assert acceptance.ambiguous_identifier_counts_by_scheme == {
        "ISIN": 63,
        "LIPPER": 63,
    }
    assert acceptance.aligned_ambiguous_pair_count == 63
    async with ingestion_admin_engine.connect() as connection:
        status = await connection.scalar(
            sa.text(
                "SELECT status FROM operations.dataset_version "
                "WHERE dataset_version = :dataset_version"
            ),
            {"dataset_version": dataset_version},
        )
        active = await connection.scalar(
            sa.text(
                "SELECT count(*) FROM operations.active_dataset "
                "WHERE dataset_version = :dataset_version"
            ),
            {"dataset_version": dataset_version},
        )
    assert status == "building"
    assert active == 0

from __future__ import annotations

import os
from collections import Counter
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.ingestion.capacity_probe import (
    measure_database_acceptance,
    require_current_rebaseline_acceptance,
)
from financial_agent.ingestion.identity import (
    AuthoritativeIdentityIndex,
    build_authoritative_identity_index,
    collect_organizer_identifier_candidates,
)
from financial_agent.ingestion.official.krx_holdings import (
    build_krx_etf_product_bindings,
    map_krx_holding_snapshot,
    parse_krx_etf_pdf_csv,
    validate_krx_etf_holding_inventory,
)
from financial_agent.ingestion.official.krx_identity import (
    map_krx_security_basic,
    parse_krx_security_basic,
)
from financial_agent.ingestion.official.capture import capture_local_krx_holdings
from financial_agent.ingestion.official.identity import (
    IdentityCandidate,
    OfficialIdentityIndex,
)
from financial_agent.ingestion.official_pipeline import (
    OrganizerInputs,
    build_stage03b_dataset,
    load_official_manifests,
    verify_official_snapshot_objects,
)
from financial_agent.ingestion.pipeline import SOURCE_SPECS
from financial_agent.ingestion.sources import iter_workbook_rows, sha256_path


RUN_CURRENT_KRX = os.getenv("RUN_CURRENT_KRX_HOLDINGS_TESTS") == "1"
ORGANIZER_PATH = os.getenv("FINANCIAL_AGENT_PREF01N001_DATA_PATH")
HOLDINGS_ROOT = os.getenv("FINANCIAL_AGENT_KRX_HOLDINGS_ROOT")
IDENTITY_CAPTURE_ROOT = os.getenv(
    "FINANCIAL_AGENT_CURRENT_KRX_IDENTITY_CAPTURE_ROOT"
)
RUN_CURRENT_KRX_POSTGRES = (
    os.getenv("RUN_CURRENT_KRX_POSTGRES_TESTS") == "1"
)
ORGANIZER_ROOT = os.getenv("FINANCIAL_AGENT_CURRENT_ORGANIZER_ROOT")
CAPTURE_ROOT = os.getenv("FINANCIAL_AGENT_CURRENT_KRX_CAPTURE_ROOT")
HAS_DATABASE = os.getenv("FINANCIAL_AGENT_TEST_DATABASE_URL") is not None


@pytest.fixture(scope="session", autouse=True)
def _require_explicit_current_krx_configuration() -> None:
    if RUN_CURRENT_KRX and (
        ORGANIZER_PATH is None
        or HOLDINGS_ROOT is None
        or IDENTITY_CAPTURE_ROOT is None
    ):
        pytest.fail("CURRENT_KRX_CONFIGURATION_MISSING", pytrace=False)
    if RUN_CURRENT_KRX_POSTGRES and (
        ORGANIZER_ROOT is None or CAPTURE_ROOT is None or not HAS_DATABASE
    ):
        pytest.fail("CURRENT_KRX_POSTGRES_CONFIGURATION_MISSING", pytrace=False)


def _organizer_inputs(root: Path) -> OrganizerInputs:
    data_paths = {
        code: root / spec.data_file_name for code, spec in SOURCE_SPECS.items()
    }
    schema_paths = {
        code: root / spec.schema_file_name for code, spec in SOURCE_SPECS.items()
    }
    return OrganizerInputs(
        data_paths=data_paths,
        schema_paths=schema_paths,
        data_sha256={
            code: sha256_path(path) for code, path in data_paths.items()
        },
        schema_sha256={
            code: sha256_path(path) for code, path in schema_paths.items()
        },
    )


def _current_krx_security_index(
    organizer_index: AuthoritativeIdentityIndex,
) -> tuple[OfficialIdentityIndex, dict[str, int]]:
    capture_root = Path(IDENTITY_CAPTURE_ROOT or "")
    manifests = load_official_manifests(capture_root / "manifests")
    assert {manifest.source_code for manifest in manifests} == {
        "KRX_KOSPI_BASIC",
        "KRX_KOSDAQ_BASIC",
    }
    verified = verify_official_snapshot_objects(
        manifests,
        capture_root / "objects",
    )
    entries: list[tuple[IdentityCandidate, str]] = []
    mapped_counts: dict[str, int] = {}
    for manifest in manifests:
        assert manifest.applicable_date == date(2026, 8, 22)
        assert manifest.cutoff_date == date(2026, 8, 24)
        item = manifest.objects[0]
        rows = parse_krx_security_basic(
            verified[(manifest.snapshot_id, item.object_key)].read_bytes(),
            market=(
                "KOSPI"
                if manifest.source_code == "KRX_KOSPI_BASIC"
                else "KOSDAQ"
            ),
        )
        mapped = tuple(
            map_krx_security_basic(
                manifest,
                rows,
                identity_index=organizer_index,
            )
        )
        assert all(row.disposition == "accepted" for row in mapped)
        mapped_counts[manifest.source_code] = len(mapped)
        for row in mapped:
            for identifier in row.records_by_table["catalog.identifier"]:
                scheme = str(identifier["scheme"])
                if scheme not in {
                    "KRX_STANDARD_ISSUE_CODE",
                    "KRX_SHORT_ISSUE_CODE",
                }:
                    continue
                entries.append(
                    (
                        IdentityCandidate(
                            scheme,
                            str(identifier["identifier_value"]),
                        ),
                        str(identifier["entity_id"]),
                    )
                )
    return (
        OfficialIdentityIndex(
            exact_entries=entries,
            organizer_index=organizer_index,
        ),
        mapped_counts,
    )


@pytest.mark.organizer_data
@pytest.mark.skipif(
    not RUN_CURRENT_KRX,
    reason="explicit current-KRX gate is disabled",
)
def test_current_organizer_and_krx_holdings_inventory_match_exactly(
    tmp_path: Path,
) -> None:
    organizer_rows = tuple(
        iter_workbook_rows(
            Path(ORGANIZER_PATH or ""),
            SOURCE_SPECS["PREF01N001"],
        )
    )
    identity_index = build_authoritative_identity_index(
        collect_organizer_identifier_candidates(
            "PREF01N001", organizer_rows
        )
    )
    bindings = build_krx_etf_product_bindings(
        organizer_rows=organizer_rows,
        daily_rows=(),
        applicable_date=date(2026, 8, 22),
        identity_index=identity_index,
    )
    paths = tuple(sorted(Path(HOLDINGS_ROOT or "").glob("*.csv")))
    inventory = validate_krx_etf_holding_inventory(
        bindings=bindings.bindings,
        object_names=(path.name for path in paths),
        applicable_date=date(2026, 8, 22),
    )

    holding_rows = 0
    summary_rows = 0
    for path in paths:
        rows = parse_krx_etf_pdf_csv(path.read_bytes())
        assert rows
        holding_rows += sum(
            row["종목코드"].strip().upper() != "CASH00000001"
            for row in rows
        )
        summary_rows += sum(
            row["종목코드"].strip().upper() == "CASH00000001"
            for row in rows
        )

    assert len(organizer_rows) == 1_780
    assert bindings.organizer_etf_count == 1_161
    assert bindings.invalid_identifier_count == 3
    assert bindings.unresolved_organizer_count == 0
    assert len(bindings.bindings) == 1_161
    assert inventory.binding_count == inventory.object_count == 1_161
    assert inventory.missing_codes == inventory.extra_codes == ()
    assert holding_rows == 75_216
    assert summary_rows == 653

    capture_root = tmp_path / "capture"
    capture_local_krx_holdings(
        holdings_root=Path(HOLDINGS_ROOT or ""),
        output_root=capture_root,
    )
    manifests = load_official_manifests(capture_root / "manifests")
    bindings_by_code = {
        binding.krx_short_code: binding for binding in bindings.bindings
    }
    security_index, krx_security_counts = _current_krx_security_index(
        identity_index
    )
    table_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    for manifest in manifests:
        short_code = manifest.objects[0].object_name.split("_", 1)[0]
        mapped = map_krx_holding_snapshot(
            manifest,
            parse_krx_etf_pdf_csv(
                (Path(HOLDINGS_ROOT or "") / manifest.objects[0].object_name)
                .read_bytes()
            ),
            binding=bindings_by_code[short_code],
            security_index=security_index,
        )
        table_counts.update(
            {
                table: len(records)
                for table, records in mapped.records_by_table.items()
            }
        )
        issue_counts.update(issue.code for issue in mapped.issues)

    assert len(manifests) == 1_161
    assert krx_security_counts == {
        "KRX_KOSPI_BASIC": 942,
        "KRX_KOSDAQ_BASIC": 1_822,
    }
    assert table_counts["evidence.source_record"] == 1_161
    assert table_counts["relation.relation_record"] == 75_216
    assert table_counts["observation.observation_record"] == 300_864
    assert table_counts["evidence.evidence_record"] == 377_241
    assert table_counts["evidence.evidence_relation_origin"] == 75_216
    assert table_counts["evidence.evidence_observation_origin"] == 300_864
    conflict_count = issue_counts["KRX_ETF_HOLDING_IDENTITY_CONFLICT"]
    source_local_count = issue_counts[
        "KRX_ETF_HOLDING_SOURCE_LOCAL_IDENTITY"
    ]
    exact_count = (
        table_counts["relation.relation_record"] - source_local_count
    )
    assert conflict_count == 0
    assert source_local_count == 41_648
    assert exact_count == 33_568
    print(
        "CURRENT_KRX_IDENTITY_COUNTS "
        f"exact={exact_count} "
        f"source_local={source_local_count} "
        f"conflict={conflict_count}"
    )


@pytest.mark.organizer_data
@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_CURRENT_KRX_POSTGRES,
    reason="explicit current-KRX PostgreSQL gate is disabled",
)
async def test_current_krx_holdings_load_and_samsung_query_are_inactive(
    ingestion_build_engine: AsyncEngine,
    ingestion_admin_engine: AsyncEngine,
) -> None:
    capture_root = Path(CAPTURE_ROOT or "")
    dataset_version = f"current-krx-acceptance-{uuid4().hex}"
    report = await build_stage03b_dataset(
        ingestion_build_engine,
        dataset_version=dataset_version,
        organizer_inputs=_organizer_inputs(Path(ORGANIZER_ROOT or "")),
        official_manifests=load_official_manifests(
            capture_root / "manifests"
        ),
        official_object_root=capture_root / "objects",
    )

    assert report.passed is True
    assert report.source_counts["KRX_ETF_PDF"]["rows"] == 1_161
    acceptance = await measure_database_acceptance(
        ingestion_build_engine,
        report,
    )
    require_current_rebaseline_acceptance(acceptance)
    assert acceptance.relation_counts_by_predicate["holdsSecurity"] == 75_216
    assert acceptance.dataset_status == "building"
    assert acceptance.active is False

    query = sa.text(
        """
        SELECT
            product.entity_id,
            product.canonical_name,
            aum.numeric_value,
            holding_evidence.locator_uri_or_object_key AS holding_locator,
            holding_evidence.applicable_date AS holding_date,
            aum_evidence.locator_uri_or_object_key AS aum_locator,
            aum_evidence.applicable_date AS aum_date
        FROM relation.relation_record AS holding
        JOIN catalog.entity AS security
          ON security.dataset_version = holding.dataset_version
         AND security.entity_id = holding.object_id
        JOIN catalog.entity AS product
          ON product.dataset_version = holding.dataset_version
         AND product.entity_id = holding.subject_id
        JOIN observation.observation_record AS aum
          ON aum.dataset_version = holding.dataset_version
         AND aum.entity_id = holding.subject_id
         AND aum.metric_id = 'organizer.pref01n001.aum'
         AND aum.value_status IN ('present', 'zero')
        JOIN evidence.evidence_relation_origin AS holding_origin
          ON holding_origin.dataset_version = holding.dataset_version
         AND holding_origin.relation_id = holding.relation_id
        JOIN evidence.evidence_record AS holding_evidence
          ON holding_evidence.dataset_version = holding_origin.dataset_version
         AND holding_evidence.evidence_id = holding_origin.evidence_id
        JOIN evidence.evidence_observation_origin AS aum_origin
          ON aum_origin.dataset_version = aum.dataset_version
         AND aum_origin.observation_id = aum.observation_id
        JOIN evidence.evidence_record AS aum_evidence
          ON aum_evidence.dataset_version = aum_origin.dataset_version
         AND aum_evidence.evidence_id = aum_origin.evidence_id
        WHERE holding.dataset_version = :dataset_version
          AND holding.predicate_id = 'holdsSecurity'
          AND security.normalized_name = '삼성전자'
        ORDER BY
            aum.numeric_value DESC,
            product.normalized_name,
            product.entity_id
        LIMIT 5
        """
    )
    async with ingestion_admin_engine.connect() as connection:
        rows = (
            await connection.execute(
                query,
                {"dataset_version": dataset_version},
            )
        ).mappings().all()
        active_count = await connection.scalar(
            sa.text(
                "SELECT count(*) FROM operations.active_dataset "
                "WHERE dataset_version = :dataset_version"
            ),
            {"dataset_version": dataset_version},
        )

    assert len(rows) == 5
    assert [row["numeric_value"] for row in rows] == sorted(
        (row["numeric_value"] for row in rows),
        reverse=True,
    )
    assert all(
        str(row["holding_locator"]).endswith("_20260822.csv")
        and row["holding_date"] == date(2026, 8, 22)
        and row["aum_locator"] == "pref01n001_data.xlsx"
        for row in rows
    )
    assert active_count == 0
    print(
        "CURRENT_KRX_POSTGRES_OK "
        f"dataset={dataset_version} "
        f"reproducibility={acceptance.reproducibility_hash} "
        f"postgresql={report.component_hashes['postgresql']} "
        f"evidence={report.component_hashes['evidence']} "
        f"top5={[(row['canonical_name'], str(row['numeric_value'])) for row in rows]}"
    )

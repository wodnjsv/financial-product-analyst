from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from financial_agent.ingestion.mapping.common import stable_id
from financial_agent.ingestion.official import (
    NportProductBinding,
    build_sec_series_class_index,
    iter_eligible_nport_funds,
    map_ecos_fx,
    map_krx_etf_daily,
    map_krx_holding_snapshot,
    parse_ecos_731y001,
    parse_krx_etf_daily,
    parse_krx_etf_pdf_csv,
    parse_sec_series_class,
)
from financial_agent.ingestion.official.identity import (
    IdentityCandidate,
    OfficialIdentityIndex,
)
from financial_agent.ingestion.official.krx_holdings import (
    KrxEtfProductBinding,
)
from tests.fixtures.official_ingestion import (
    ecos_731y001_payload,
    krx_etf_daily_payload,
    krx_etf_pdf_payload,
    official_manifest,
    sec_nport_tsv_files,
    sec_series_class_payload,
)


def _records(rows: object, table: str) -> tuple[dict[str, object], ...]:
    values = rows if isinstance(rows, tuple) else (rows,)
    return tuple(
        dict(record)
        for row in values
        for record in row.records_by_table[table]
    )


def _domestic_binding() -> KrxEtfProductBinding:
    return KrxEtfProductBinding(
        product_entity_id=stable_id(
            "product", "PREF01N001", "KR7305080004"
        ),
        organizer_isin="KR7305080004",
        krx_short_code="305080",
        organizer_name="TIGER 미국채10년선물",
        krx_name="TIGER 미국채10년선물",
        name_matches=True,
    )


def test_domestic_question_gate_joins_holding_price_nav_and_evidence() -> None:
    holding_payload = krx_etf_pdf_payload()
    holding_manifest = official_manifest(
        source_code="KRX_ETF_PDF",
        object_name="305080_20260710.csv",
        payload=holding_payload,
        applicable_date=date(2026, 7, 10),
        media_type="text/csv",
    )
    holding = map_krx_holding_snapshot(
        holding_manifest,
        parse_krx_etf_pdf_csv(holding_payload),
        binding=_domestic_binding(),
        security_index=OfficialIdentityIndex(
            exact_entries=(
                (
                    IdentityCandidate("KRX_SHORT_ISSUE_CODE", "005930"),
                    "security-samsung-electronics",
                ),
            )
        ),
    )
    market_payload = krx_etf_daily_payload()
    market = map_krx_etf_daily(
        official_manifest(
            source_code="KRX_ETF_DAILY",
            object_name="krx-etf-daily-20260710.json",
            payload=market_payload,
            applicable_date=date(2026, 7, 10),
        ),
        parse_krx_etf_daily(market_payload),
        bindings=(_domestic_binding(),),
    )

    holding_relation = next(
        record
        for record in _records(holding, "relation.relation_record")
        if record["object_id"] == "security-samsung-electronics"
    )
    market_observations = _records(
        market, "observation.observation_record"
    )

    assert holding_relation["predicate_id"] == "holdsSecurity"
    assert holding_relation["subject_id"] == _domestic_binding().product_entity_id
    assert {row["entity_id"] for row in market_observations} == {
        holding_relation["subject_id"]
    }
    assert {row["metric_id"] for row in market_observations} == {
        "krx_etf_market_close_krw",
        "krx_etf_nav_per_share_krw",
    }
    assert all(
        evidence["cutoff_status"] == "eligible"
        for evidence in (
            _records(holding, "evidence.evidence_record")
            + _records(market, "evidence.evidence_record")
        )
    )


def test_fx_question_gate_has_four_fixed_definitions_and_actual_date() -> None:
    payload = ecos_731y001_payload()
    mapped = map_ecos_fx(
        official_manifest(
            source_code="ECOS_731Y001",
            object_name="ecos-731y001-20260710.json",
            payload=payload,
            applicable_date=date(2026, 7, 10),
        ),
        parse_ecos_731y001(payload),
    )
    observations = _records(mapped, "observation.observation_record")

    assert len(observations) == 4
    assert {row["applicable_date"] for row in observations} == {
        date(2026, 7, 10)
    }
    assert {
        row["metric_id"] for row in observations
    } == {
        "ecos_731y001_krw_per_usd",
        "ecos_731y001_krw_per_100_jpy",
        "ecos_731y001_krw_per_eur",
        "ecos_731y001_krw_per_cny",
    }
    assert all(isinstance(row["numeric_value"], Decimal) for row in observations)


def test_overseas_question_gate_discloses_bounded_scope_and_manager(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files()
    file_paths: dict[str, Path] = {}
    for name, payload in files.items():
        path = tmp_path / name
        path.write_bytes(payload)
        file_paths[name] = path
    series_payload = sec_series_class_payload()
    series_manifest = official_manifest(
        source_code="SEC_SERIES_CLASS_20260601",
        object_name="investment-company-series-class-2026.csv",
        payload=series_payload,
        applicable_date=date(2026, 6, 1),
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        available_at=datetime(2026, 6, 1, tzinfo=UTC),
        media_type="text/csv",
    )
    package = b"".join(files[name] for name in sorted(files))
    nport_manifest = official_manifest(
        source_code="SEC_NPORT_2026Q2",
        object_name="2026q2_nport.zip",
        payload=package,
        applicable_date=date(2026, 3, 31),
        published_at=datetime(2026, 6, 30, tzinfo=UTC),
        available_at=datetime(2026, 7, 9, tzinfo=UTC),
        media_type="application/zip",
    )
    mapped = tuple(
        iter_eligible_nport_funds(
            file_paths,
            date(2026, 8, 24),
            manifest=nport_manifest,
            series_class_index=build_sec_series_class_index(
                series_manifest,
                parse_sec_series_class(series_payload),
            ),
            product_bindings=(
                NportProductBinding(
                    product_entity_id="organizer-overseas-etf-1",
                    cik="0000123456",
                    class_ticker="SYNX",
                ),
                NportProductBinding(
                    product_entity_id="organizer-overseas-etf-uncovered",
                    cik="0000123456",
                    class_ticker="NOPE",
                ),
            ),
        )
    )
    relations = _records(mapped, "relation.relation_record")
    evidence = _records(mapped, "evidence.evidence_record")
    scopes = tuple(
        row for row in evidence if row["evidence_kind"] == "query_scope"
    )

    assert {row["predicate_id"] for row in relations} == {
        "holdsSecurity",
        "managedBy",
    }
    assert {
        (row["scope_completeness"], row["normalized_value"]["value"])
        for row in scopes
    } == {
        ("closed_world", "COVERED"),
        ("bounded_unknown", "NOT_COVERED"),
    }

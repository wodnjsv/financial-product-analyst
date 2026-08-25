from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.ingestion.identity import (
    build_authoritative_identity_index,
    collect_organizer_identifier_candidates,
)
from financial_agent.ingestion.mapping.domestic_bond import (
    HANDLED_COLUMNS,
    IGNORED_COLUMNS,
    SPEC,
    analyze_bond_rows,
    map_row,
)
from financial_agent.ingestion.mapping.common import make_record_hash, stable_id
from financial_agent.ingestion.models import MappedRow
from financial_agent.ingestion.writer import DatasetBuildWriter


def synthetic_bond_row() -> dict[str, object]:
    return {
        "after_tax_yield": Decimal("2.75"),
        "applied_yield": Decimal("3.20"),
        "avg_annual_tax_yield": 0,
        "bdbns_abl_chnl_nm": "온라인",
        "bdbns_abl_chnl_tcd": "SYN-CHANNEL",
        "bd_inrt_tcd": "고정금리",
        "bd_intp_tcd": "이표채",
        "bd_knd": "회사채",
        "bd_ofr_tcd": "공모",
        "bd_tisu_a": Decimal("1000000"),
        "buyable_quantity": Decimal("100"),
        "buy_yield": Decimal("3.40"),
        "corp_after_tax_yield": Decimal("2.80"),
        "corp_pretax_yield": Decimal("3.30"),
        "cov": Decimal("0.30"),
        "crd_grd": "SYN-AA",
        "crd_grd_dt": "20260820",
        "curr_cd": "KRW",
        "depo_equiv_yield_154": Decimal("3.25"),
        "depo_equiv_yield_495": Decimal("3.10"),
        "dirty": Decimal("10100"),
        "dur": Decimal("2.10"),
        "eval_price": Decimal("10050"),
        "exg_close_price": Decimal("10020"),
        "exg_close_price_base_dt": "20260822",
        "exg_close_yield": Decimal("3.22"),
        "exrt_grte_ern_r": Decimal("3.00"),
        "exrt_grte_ern_r_tcd": "SYN-GUARANTEE",
        "exrt_rpy_r": Decimal("100"),
        "info_base_dt": "20260822",
        "info_seq": 1,
        "isu_bal_amt": Decimal("900000"),
        "isu_dt": "20250115",
        "mat_dt": "20300115",
        "ndy_applied_yield": Decimal("3.21"),
        "ndy_cov": Decimal("0.29"),
        "ndy_dirty": Decimal("10099"),
        "ndy_dur": Decimal("2.09"),
        "ndy_eval_price": Decimal("10048"),
        "pd_abrv_eng_nm": "SYN BOND 1",
        "pd_abrv_nm": "합성채1",
        "pd_ctry_cd": "SYN",
        "pd_eng_nm": "Synthetic Bond 1",
        "pd_exg_mkt": "장외",
        "pd_nm": "  합성\u3000채권 1 ",
        "pd_no": "SYN-BOND-001",
        "pd_pbcm": "  합성\u3000발행기관 ",
        "pd_pen_tr_yn": "Y",
        "pd_risk_gcd": "SYN-RISK",
        "pd_risk_nm": "낮은 위험",
        "pd_std_info_update": "20260822",
        "pref_tax_yield": Decimal("2.90"),
        "remaining_days": Decimal("1242"),
        "sale_yield_base_dt": "20260822",
        "srfc_irt": Decimal("3.25"),
        "std_pd_mcls_nm": "채권",
        "std_pd_scls_nm": "회사채",
        "trade_price": Decimal("10010"),
    }


def _records(mapped, table: str) -> tuple[Mapping[str, object], ...]:
    return mapped.records_by_table.get(table, ())


def _identity_index(*rows: Mapping[str, object]):
    return build_authoritative_identity_index(
        collect_organizer_identifier_candidates("PRBD01N001", rows)
    )


def _map(row_number: int, row: Mapping[str, object], *all_rows):
    population = all_rows or (row,)
    return map_row(
        row_number,
        row,
        analysis=analyze_bond_rows(population),
        identity_index=_identity_index(*population),
    )


def _observation(mapped, suffix: str) -> Mapping[str, object]:
    metric_id = f"organizer.prbd01n001.{suffix}"
    return next(
        item
        for item in _records(mapped, "observation.observation_record")
        if item["metric_id"] == metric_id
    )


def _evidence(mapped, column: str) -> Mapping[str, object]:
    return next(
        item
        for item in _records(mapped, "evidence.evidence_record")
        if item["locator_column"] == column
    )


def test_all_58_fields_are_exhaustively_classified() -> None:
    assert len(SPEC.expected_columns) == 58
    assert HANDLED_COLUMNS.isdisjoint(IGNORED_COLUMNS)
    assert HANDLED_COLUMNS | set(IGNORED_COLUMNS) == set(SPEC.expected_columns)
    assert IGNORED_COLUMNS == {
        "buyable_quantity": "INVALID_BY_ORGANIZER_NOTICE"
    }


def test_valid_row_creates_one_bond_product_and_issuer() -> None:
    mapped = _map(7, synthetic_bond_row())

    assert mapped.disposition == "accepted"
    entities = _records(mapped, "catalog.entity")
    product_entity = next(item for item in entities if item["entity_type"] == "product")
    issuer_entity = next(
        item for item in entities if item["entity_type"] == "institution"
    )
    assert product_entity["canonical_name"] == "합성 채권 1"
    assert issuer_entity["canonical_name"] == "합성 발행기관"
    assert _records(mapped, "catalog.product") == (
        {
            "entity_id": product_entity["entity_id"],
            "product_family": "domestic_bond",
            "primary_currency": "KRW",
        },
    )
    assert not _records(mapped, "catalog.security")
    identifier = _records(mapped, "catalog.identifier")[0]
    assert identifier["scheme"] == "PRBD_PD_NO"
    assert identifier["identifier_value"] == "SYN-BOND-001"
    assert identifier["entity_id"] == product_entity["entity_id"]
    relation = _records(mapped, "relation.relation_record")[0]
    assert relation["predicate_id"] == "issuedBy"
    assert relation["subject_id"] == product_entity["entity_id"]
    assert relation["object_id"] == issuer_entity["entity_id"]


def test_same_product_two_lots_share_catalog_but_keep_lot_values_separate() -> None:
    first_row = synthetic_bond_row()
    second_row = first_row | {
        "info_seq": 2,
        "trade_price": Decimal("10030"),
        "buy_yield": Decimal("3.50"),
    }
    analysis = analyze_bond_rows((first_row, second_row))
    identity_index = _identity_index(first_row, second_row)
    first = map_row(2, first_row, analysis=analysis, identity_index=identity_index)
    second = map_row(3, second_row, analysis=analysis, identity_index=identity_index)

    assert _records(first, "catalog.entity")[0] == _records(
        second, "catalog.entity"
    )[0]
    assert _records(first, "catalog.product") == _records(
        second, "catalog.product"
    )
    assert _observation(first, "trade_price")["observation_id"] != _observation(
        second, "trade_price"
    )["observation_id"]
    assert _observation(first, "trade_price")["numeric_value"] == Decimal(
        "10010"
    )
    assert _observation(second, "trade_price")["numeric_value"] == Decimal(
        "10030"
    )
    assert _observation(first, "buy_yield")["observation_id"] != _observation(
        second, "buy_yield"
    )["observation_id"]
    assert _observation(first, "coupon_rate")["observation_id"] == _observation(
        second, "coupon_rate"
    )["observation_id"]
    assert _evidence(first, "srfc_irt")["evidence_id"] != _evidence(
        second, "srfc_irt"
    )["evidence_id"]


def test_conflicting_static_name_is_not_selected_by_source_order() -> None:
    first_row = synthetic_bond_row() | {"pd_nm": "이름 A"}
    second_row = synthetic_bond_row() | {"pd_nm": "이름 B", "info_seq": 2}
    analysis = analyze_bond_rows((first_row, second_row))
    identity_index = _identity_index(first_row, second_row)

    first = map_row(2, first_row, analysis=analysis, identity_index=identity_index)
    second = map_row(3, second_row, analysis=analysis, identity_index=identity_index)

    assert first.disposition == second.disposition == "limited"
    assert _records(first, "catalog.entity")[0]["canonical_name"] == "SYN-BOND-001"
    assert _records(first, "catalog.entity")[0] == _records(
        second, "catalog.entity"
    )[0]
    assert _observation(first, "name")["value_status"] == "unknown"
    assert _observation(second, "name")["value_status"] == "unknown"
    assert _observation(first, "name")["reason_code"] == (
        "SOURCE_STATIC_VALUE_CONFLICT"
    )
    assert [(issue.column, issue.code) for issue in first.issues] == [
        ("pd_nm", "SOURCE_STATIC_VALUE_CONFLICT")
    ]


def test_dates_applicability_boolean_zero_and_missing_are_preserved() -> None:
    row = synthetic_bond_row() | {
        "avg_annual_tax_yield": 0,
        "pd_pen_tr_yn": "N",
        "exg_close_price": None,
    }
    mapped = _map(8, row)

    assert mapped.disposition == "limited"
    assert _observation(mapped, "average_annual_after_tax_yield")[
        "value_status"
    ] == "zero"
    assert _observation(mapped, "average_annual_after_tax_yield")[
        "numeric_value"
    ] == 0
    assert _observation(mapped, "pension_eligible")["boolean_value"] is False
    assert _observation(mapped, "issue_date")["date_value"] == date(2025, 1, 15)
    assert _observation(mapped, "maturity_date")["date_value"] == date(
        2030, 1, 15
    )
    assert _observation(mapped, "buy_yield")["applicable_date"] == date(
        2026, 8, 22
    )
    assert _observation(mapped, "exchange_close_price")[
        "value_status"
    ] == "missing"
    assert _observation(mapped, "exchange_close_price")[
        "applicable_date"
    ] == date(2026, 8, 22)


def test_evidence_uses_complete_composite_source_key_and_current_contract() -> None:
    mapped = _map(7, synthetic_bond_row())
    coupon = _evidence(mapped, "srfc_irt")
    locator = json.loads(str(coupon["locator_record_key"]))

    assert locator == {
        "info_base_dt": "20260822",
        "info_seq": "1",
        "pd_exg_mkt": "장외",
        "pd_no": "SYN-BOND-001",
    }
    assert coupon["locator_sheet"] == "data"
    assert coupon["locator_row"] == 7
    assert coupon["mapping_version"] == "2"
    assert coupon["vintage_date"] == date(2026, 8, 24)
    assert coupon["value_or_object_id"] == {
        "type": "decimal",
        "value": "3.25",
    }


def test_invalid_buyable_quantity_is_absent_from_facts_evidence_and_issues() -> None:
    mapped = _map(
        7,
        synthetic_bond_row() | {"buyable_quantity": "not-a-number"},
    )

    assert mapped.disposition == "accepted"
    assert all(
        "buyable_quantity" not in str(item.get("metric_id", ""))
        for item in _records(mapped, "observation.observation_record")
    )
    assert all(
        item["locator_column"] != "buyable_quantity"
        for item in _records(mapped, "evidence.evidence_record")
    )
    assert all(issue.column != "buyable_quantity" for issue in mapped.issues)


def test_after_cutoff_information_date_is_fatal_but_future_maturity_is_allowed() -> None:
    row = synthetic_bond_row() | {
        "info_base_dt": "20260825",
        "mat_dt": "20350101",
    }
    mapped = _map(12, row)

    assert mapped.disposition == "quarantined"
    assert not any(mapped.records_by_table.values())
    assert [(issue.column, issue.code, issue.severity) for issue in mapped.issues] == [
        ("info_base_dt", "AFTER_CUTOFF_SOURCE_VALUE", "fatal")
    ]


def test_missing_composite_natural_key_quarantines_without_records() -> None:
    mapped = _map(9, synthetic_bond_row() | {"info_seq": None})

    assert mapped.disposition == "quarantined"
    assert not any(mapped.records_by_table.values())
    assert [(issue.column, issue.code) for issue in mapped.issues] == [
        ("info_seq", "MISSING_NATURAL_KEY")
    ]


def test_double_precision_float_uses_stable_decimal_string_roundtrip() -> None:
    mapped = _map(10, synthetic_bond_row() | {"srfc_irt": 3.141592})

    assert mapped.disposition == "accepted"
    assert _observation(mapped, "coupon_rate")["numeric_value"] == Decimal(
        "3.141592"
    )


def test_invalid_numeric_value_quarantines_without_leaking_raw_value() -> None:
    mapped = _map(11, synthetic_bond_row() | {"srfc_irt": "PRIVATE-BAD-NUMBER"})

    assert mapped.disposition == "quarantined"
    assert not any(mapped.records_by_table.values())
    assert mapped.issues[0].column == "srfc_irt"
    assert mapped.issues[0].code == "INVALID_SOURCE_VALUE"
    assert "PRIVATE-BAD-NUMBER" not in repr(mapped.issues)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_two_lots_converge_in_the_database_without_payload_conflict(
    ingestion_build_engine: AsyncEngine,
) -> None:
    first_row = synthetic_bond_row()
    second_row = first_row | {
        "info_seq": 2,
        "trade_price": Decimal("10030"),
        "buy_yield": Decimal("3.50"),
    }
    analysis = analyze_bond_rows((first_row, second_row))
    identity_index = _identity_index(first_row, second_row)
    publisher_id = stable_id("institution", "organizer", "competition-organizer")
    source_id = stable_id("source", SPEC.source_code, SPEC.data_file_name)

    def hashed(payload: dict[str, object]) -> dict[str, object]:
        return payload | {"record_hash": make_record_hash(payload)}

    foundation = MappedRow(
        row_number=0,
        disposition="accepted",
        records_by_table={
            "catalog.entity": (
                hashed(
                    {
                        "entity_id": publisher_id,
                        "entity_type": "institution",
                        "canonical_name": "Competition Organizer",
                        "normalized_name": "Competition Organizer",
                    }
                ),
            ),
            "catalog.institution": (
                {"entity_id": publisher_id, "institution_kind": "organizer"},
            ),
            "evidence.source_record": (
                hashed(
                    {
                        "source_id": source_id,
                        "publisher": publisher_id,
                        "publisher_type": "organizer",
                        "source_title": "PRBD01N001 organizer product master",
                        "source_type": "dataset",
                        "authority_tier": "organizer",
                        "source_locator_root": SPEC.data_file_name,
                        "content_checksum": "a" * 64,
                        "license_or_usage_note": "synthetic test use",
                        "eligible_for_claim": True,
                    }
                ),
            ),
        },
        issues=(),
    )
    mapped_rows = (
        map_row(2, first_row, analysis=analysis, identity_index=identity_index),
        map_row(3, second_row, analysis=analysis, identity_index=identity_index),
    )
    writer = DatasetBuildWriter(ingestion_build_engine)
    dataset_version = f"bond-lots-{uuid4().hex}"
    await writer.create_building_dataset(
        dataset_version,
        "b" * 64,
        date(2026, 8, 24),
    )

    await writer.write_rows(dataset_version, (foundation, *mapped_rows))

    counts = await writer.table_counts(dataset_version)
    assert counts["catalog.product"] == 1
    assert counts["catalog.security"] == 0
    assert counts["relation.relation_record"] == 1
    assert counts["observation.observation_record"] == 90
    assert counts["evidence.evidence_record"] == 112

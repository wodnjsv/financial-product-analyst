from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from financial_agent.ingestion.identity import (
    build_authoritative_identity_index,
    collect_organizer_identifier_candidates,
)
from financial_agent.ingestion.mapping.common import stable_id
from financial_agent.ingestion.mapping.overseas_etp import (
    EVIDENCE_ONLY_COLUMNS,
    HANDLED_COLUMNS,
    IGNORED_COLUMNS,
    SPEC,
    collect_duplicate_identifier_values,
    map_row,
)


OVERSEAS_ISIN = "US0378331005"


def synthetic_overseas_row() -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(SPEC.expected_columns)
    row.update(
        {
            "cu_base_index": "SYN GLOBAL INDEX",
            "cu_charge_rt": Decimal("0.25"),
            "cu_etn_yn": "N",
            "cu_fund_mgmt_co": "Synthetic Asset Management",
            "cu_index_repl_mthd": "Physical",
            "cu_index_tracking_yn": "Y",
            "cu_inverse_short_yn": "N",
            "cu_lev_fector": Decimal("1"),
            "cu_strtegy": "Global equity index tracking",
            "cu_upt_dt": "20260821",
            "du_base_dt_match_yn": "Y",
            "du_bpr": Decimal("100.1"),
            "du_clpr": Decimal("101.2"),
            "du_clpr_base_dt": "20260821",
            "du_clpr_src": "OFFICIAL_CLOSE",
            "du_diff_rt": Decimal("-0.13"),
            "du_er_1d": Decimal("0"),
            "du_hpr": Decimal("102.3"),
            "du_last_aum": Decimal("2500000000"),
            "du_last_nav": Decimal("101.05"),
            "du_lpr": Decimal("99.8"),
            "du_nav_base_dt": "2026-08-21 00:00:00",
            "du_opr": Decimal("100.2"),
            "du_upt_dt": "20260822",
            "du_val_1d": Decimal("50000000"),
            "du_vol_1d": Decimal("500000"),
            "pd_abrv_nm": "SYN",
            "pd_curr_cd": "USD",
            "pd_exg_mkt_cd": "XNYS",
            "pd_grp_no": "ETF",
            "pd_isin_cd": OVERSEAS_ISIN,
            "pd_itm_no": "SYN.N",
            "pd_itm_no_ma": "SYN-MA-001",
            "pd_lipper_id": "LP-SYN-001",
            "pd_lstg_dt": "20200102",
            "pd_lst_price": Decimal("0"),
            "pd_lst_stk_cnt": Decimal("25000000"),
            "pd_mkt_id": "US",
            "pd_nm": "Synthetic Overseas ETF",
            "pd_sale_yn": "1",
            "pd_trd_ccy": "USD",
            "pd_tr_yn": "0",
            "pd_us_cik": "0000000001",
            "ru_mkt_price": Decimal("101.3"),
            "ru_mkt_volume": Decimal("510000"),
            "wu_core_yn": "N",
            "wu_inv_ast_type": "Equity",
            "wu_inv_rgn": "Global",
            "wu_upt_dt": "20260821",
        }
    )
    return row


def _map(
    row: Mapping[str, object],
    *,
    rows: tuple[Mapping[str, object], ...] | None = None,
):
    source_rows = rows or (row,)
    duplicates = collect_duplicate_identifier_values(source_rows)
    candidates = collect_organizer_identifier_candidates(
        "PREF02N001", source_rows
    )
    identity_index = build_authoritative_identity_index(candidates)
    return map_row(
        2,
        row,
        duplicate_identifier_values=duplicates,
        identity_index=identity_index,
    )


def records(mapped, table: str) -> tuple[Mapping[str, object], ...]:
    return mapped.records_by_table.get(table, ())


def observation(mapped, metric_suffix: str) -> Mapping[str, object]:
    metric_id = f"organizer.pref02n001.{metric_suffix}"
    return next(
        item
        for item in records(mapped, "observation.observation_record")
        if item["metric_id"] == metric_id
    )


def evidence(mapped, column: str) -> Mapping[str, object]:
    return next(
        item
        for item in records(mapped, "evidence.evidence_record")
        if item["locator_column"] == column
    )


def relations(mapped, predicate_id: str) -> tuple[Mapping[str, object], ...]:
    return tuple(
        item
        for item in records(mapped, "relation.relation_record")
        if item["predicate_id"] == predicate_id
    )


def test_all_49_fields_are_handled_and_none_are_silently_ignored() -> None:
    assert len(SPEC.expected_columns) == 49
    assert HANDLED_COLUMNS == frozenset(SPEC.expected_columns)
    assert IGNORED_COLUMNS == {}
    assert EVIDENCE_ONLY_COLUMNS == {
        "du_clpr_src",
        "pd_exg_mkt_cd",
        "pd_mkt_id",
        "pd_us_cik",
        "ru_mkt_price",
        "ru_mkt_volume",
    }


def test_etf_uses_authoritative_identity_and_eligible_unique_identifiers() -> None:
    mapped = _map(synthetic_overseas_row())

    product = records(mapped, "catalog.product")[0]
    assert product["entity_id"] == stable_id(
        "product", "PREF02N001", "SYN.N"
    )
    assert product["product_family"] == "overseas_etf"
    assert product["primary_currency"] == "USD"
    assert not records(mapped, "catalog.security")
    assert {
        (item["scheme"], item["identifier_value"], item["is_primary"])
        for item in records(mapped, "catalog.identifier")
    } == {
        ("PREF02_PD_ITM_NO", "SYN.N", True),
        ("PREF02_PD_ITM_NO_MA", "SYN-MA-001", False),
        ("ISIN", OVERSEAS_ISIN, False),
        ("LIPPER", "LP-SYN-001", False),
    }
    assert records(mapped, "catalog.alias")[0]["alias_text"] == "SYN"
    assert len(relations(mapped, "managedBy")) == 1
    assert len(relations(mapped, "tracksIndex")) == 1


def test_etn_provider_remains_text_and_is_not_inferred_as_issuer() -> None:
    row = synthetic_overseas_row() | {
        "pd_grp_no": "ETN",
        "pd_itm_no": "SYN-ETN.N",
        "pd_itm_no_ma": "SYN-ETN-MA-001",
        "pd_isin_cd": "US5949181045",
        "pd_lipper_id": "LP-SYN-ETN-001",
        "pd_nm": "Synthetic Overseas ETN",
        "cu_etn_yn": "Y",
    }

    mapped = _map(row)

    assert observation(mapped, "product_type")["text_value"] == "ETN"
    assert observation(mapped, "provider_name_raw")["text_value"] == (
        "Synthetic Asset Management"
    )
    assert not records(mapped, "catalog.institution")
    assert not relations(mapped, "managedBy")
    assert not relations(mapped, "issuedBy")
    assert len(relations(mapped, "tracksIndex")) == 1


def test_duplicate_isin_and_lipper_are_aligned_and_evidence_only() -> None:
    first = synthetic_overseas_row()
    second = synthetic_overseas_row() | {
        "pd_itm_no": "SYN-2.N",
        "pd_itm_no_ma": "SYN-MA-002",
        "pd_nm": "Synthetic Overseas ETF 2",
    }
    duplicates = collect_duplicate_identifier_values((first, second))

    assert duplicates["pd_isin_cd"] == frozenset({OVERSEAS_ISIN})
    assert duplicates["pd_lipper_id"] == frozenset({"LP-SYN-001"})
    assert duplicates["pd_itm_no_ma"] == frozenset()

    mapped = _map(first, rows=(first, second))
    schemes = {item["scheme"] for item in records(mapped, "catalog.identifier")}
    assert "ISIN" not in schemes
    assert "LIPPER" not in schemes
    assert observation(mapped, "isin_raw")["text_value"] == OVERSEAS_ISIN
    assert observation(mapped, "lipper_id")["text_value"] == "LP-SYN-001"
    assert sum(
        issue.code == "DUPLICATE_IDENTIFIER_NOT_PROMOTED"
        for issue in mapped.issues
    ) == 2


def test_duplicate_internal_identifier_is_not_promoted() -> None:
    first = synthetic_overseas_row()
    second = synthetic_overseas_row() | {
        "pd_itm_no": "SYN-2.N",
        "pd_itm_no_ma": "SYN-MA-001",
        "pd_isin_cd": "US5949181045",
        "pd_lipper_id": "LP-SYN-002",
        "pd_nm": "Synthetic Overseas ETF 2",
    }

    mapped = _map(first, rows=(first, second))

    assert "PREF02_PD_ITM_NO_MA" not in {
        item["scheme"] for item in records(mapped, "catalog.identifier")
    }
    assert observation(mapped, "internal_product_id")["text_value"] == "SYN-MA-001"


def test_zero_and_newly_answerable_fields_are_preserved_with_exact_dates() -> None:
    mapped = _map(synthetic_overseas_row())

    assert observation(mapped, "leverage_factor")["numeric_value"] == 1
    assert observation(mapped, "premium_discount_rate")["numeric_value"] == Decimal(
        "-0.13"
    )
    assert observation(mapped, "premium_discount_rate")["applicable_date"] == date(
        2026, 8, 21
    )
    assert observation(mapped, "cumulative_return_1d")["value_status"] == "zero"
    assert observation(mapped, "face_value")["value_status"] == "zero"
    assert observation(mapped, "runtime_market_price_raw")["numeric_value"] == Decimal(
        "101.3"
    )
    assert observation(mapped, "internal_core_flag")["boolean_value"] is False


def test_price_nav_date_mismatch_limits_divergence_without_fabricating_date() -> None:
    row = synthetic_overseas_row() | {
        "du_base_dt_match_yn": "N",
        "du_nav_base_dt": "2026-08-20 00:00:00",
    }

    mapped = _map(row)

    divergence = observation(mapped, "premium_discount_rate")
    assert divergence["numeric_value"] == Decimal("-0.13")
    assert divergence["applicable_date"] is None
    assert "PRICE_NAV_DATE_MISMATCH" in {issue.code for issue in mapped.issues}


def test_all_fields_have_one_evidence_locator_and_float_cells_are_normalized() -> None:
    row = synthetic_overseas_row() | {"du_clpr": 101.2, "du_last_aum": 2.5e9}
    mapped = _map(row)
    evidence_rows = records(mapped, "evidence.evidence_record")

    assert len(evidence_rows) == 49
    assert {item["locator_column"] for item in evidence_rows} == set(
        SPEC.expected_columns
    )
    assert all(item["locator_sheet"] == "data" for item in evidence_rows)
    assert all(item["mapping_version"] == "2" for item in evidence_rows)
    assert all(item["vintage_date"] == date(2026, 8, 24) for item in evidence_rows)
    assert evidence(mapped, "ru_mkt_price")["applicable_date"] is None
    assert observation(mapped, "close_price")["numeric_value"] == Decimal("101.2")


def test_missing_index_is_limited_and_future_source_date_is_fatal() -> None:
    missing_index = _map(
        synthetic_overseas_row()
        | {"cu_base_index": "N/A", "pd_lstg_dt": "00000000"}
    )
    future = _map(synthetic_overseas_row() | {"du_clpr_base_dt": "20260825"})

    assert not relations(missing_index, "tracksIndex")
    assert observation(missing_index, "base_index_raw")["value_status"] == (
        "placeholder"
    )
    assert observation(missing_index, "listing_date")["value_status"] == (
        "placeholder"
    )
    assert future.disposition == "quarantined"
    assert future.issues[0].column == "du_clpr_base_dt"
    assert future.issues[0].code == "AFTER_CUTOFF_SOURCE_VALUE"
    assert future.issues[0].severity == "fatal"

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from financial_agent.ingestion.mapping.domestic_etp import (
    HANDLED_COLUMNS,
    IGNORED_COLUMNS,
    SPEC,
    map_row,
)


EXPECTED_COLUMNS = (
    "cu_base_index",
    "cu_charge_etc_rt",
    "cu_charge_rt",
    "cu_fund_mgmt_co",
    "cu_lev_fector",
    "cu_strtegy",
    "cu_upt_dt",
    "du_bpr",
    "du_chas_errt",
    "du_clpr",
    "du_diff_rt",
    "du_er_1d",
    "du_er_1m",
    "du_er_1y",
    "du_er_3m",
    "du_er_6m",
    "du_er_ytd",
    "du_hpr",
    "du_last_aum",
    "du_last_nav",
    "du_lpr",
    "du_nav_rnf_amt",
    "du_nav_yday",
    "du_upt_dt",
    "du_val_1d",
    "du_val_1m",
    "du_val_5d",
    "du_vol_1d",
    "du_vol_avg_1m",
    "du_vol_avg_5d",
    "nru_mkt_diff_rt",
    "nru_mkt_inav",
    "pd_abrv_nm",
    "pd_circ_net_tamt",
    "pd_circ_stk_cnt",
    "pd_curr_cd",
    "pd_curr_nm",
    "pd_divd_amt_pshr",
    "pd_dvid_cycl",
    "pd_dvid_yield",
    "pd_exg_mkt_cd",
    "pd_exg_mkt_nm",
    "pd_grp_no",
    "pd_itm_no",
    "pd_itm_no_ma",
    "pd_lst_price",
    "pd_lst_stk_cnt",
    "pd_lste_dt",
    "pd_lstg_dt",
    "pd_mkt_id",
    "pd_mkt_nm",
    "pd_nav_pshr",
    "pd_net_ast_pshr",
    "pd_net_prft_pshr",
    "pd_net_rt_ast_pshr",
    "pd_net_tamt",
    "pd_nm",
    "pd_pen_risk_nm",
    "pd_pen_tr_yn",
    "pd_risk_cd",
    "pd_risk_nm",
    "pd_sale_yn",
    "pd_sect_cd",
    "pd_sect_nm",
    "pd_spac_yn",
    "pd_stk_cnt",
    "pd_tr_yn",
    "ru_mkt_price",
    "ru_mkt_volume",
    "wu_core_yn",
    "wu_inv_ast_type",
    "wu_inv_rgn",
    "wu_upt_dt",
)

EXPECTED_METRIC_IDS = {
    "cu_charge_rt": "organizer.pref01n001.total_fee_rate",
    "cu_lev_fector": "organizer.pref01n001.leverage_factor",
    "cu_strtegy": "organizer.pref01n001.strategy_raw",
    "cu_upt_dt": "organizer.pref01n001.structure_updated_on",
    "du_bpr": "organizer.pref01n001.base_price",
    "du_clpr": "organizer.pref01n001.close_price",
    "du_er_1d": "organizer.pref01n001.cumulative_return_1d",
    "du_er_1m": "organizer.pref01n001.cumulative_return_1m",
    "du_er_1y": "organizer.pref01n001.cumulative_return_1y",
    "du_er_3m": "organizer.pref01n001.cumulative_return_3m",
    "du_er_6m": "organizer.pref01n001.cumulative_return_6m",
    "du_er_ytd": "organizer.pref01n001.cumulative_return_ytd",
    "du_hpr": "organizer.pref01n001.high_price",
    "du_last_aum": "organizer.pref01n001.aum",
    "du_last_nav": "organizer.pref01n001.nav_per_share",
    "du_lpr": "organizer.pref01n001.lpr_raw",
    "du_nav_yday": "organizer.pref01n001.previous_nav_per_share",
    "du_upt_dt": "organizer.pref01n001.daily_updated_at",
    "du_val_1d": "organizer.pref01n001.trading_value_1d",
    "du_val_1m": "organizer.pref01n001.average_trading_value_1m",
    "du_val_5d": "organizer.pref01n001.average_trading_value_5d",
    "du_vol_1d": "organizer.pref01n001.trading_volume_1d",
    "du_vol_avg_1m": "organizer.pref01n001.average_trading_volume_1m",
    "du_vol_avg_5d": "organizer.pref01n001.average_trading_volume_5d",
    "pd_abrv_nm": "organizer.pref01n001.short_name",
    "pd_circ_net_tamt": "organizer.pref01n001.circulating_net_assets",
    "pd_circ_stk_cnt": "organizer.pref01n001.circulating_security_count",
    "pd_curr_cd": "organizer.pref01n001.product_currency",
    "pd_curr_nm": "organizer.pref01n001.product_currency_name",
    "pd_exg_mkt_cd": "organizer.pref01n001.exchange_code",
    "pd_exg_mkt_nm": "organizer.pref01n001.exchange_name",
    "pd_grp_no": "organizer.pref01n001.product_type",
    "pd_itm_no": "organizer.pref01n001.product_id",
    "pd_itm_no_ma": "organizer.pref01n001.internal_product_id",
    "pd_lst_stk_cnt": "organizer.pref01n001.listed_security_count",
    "pd_lste_dt": "organizer.pref01n001.trading_end_date",
    "pd_lstg_dt": "organizer.pref01n001.listing_date",
    "pd_mkt_id": "organizer.pref01n001.market_code",
    "pd_mkt_nm": "organizer.pref01n001.market_name",
    "pd_nav_pshr": "organizer.pref01n001.net_asset_value_per_share",
    "pd_net_tamt": "organizer.pref01n001.net_assets",
    "pd_nm": "organizer.pref01n001.name",
    "pd_pen_risk_nm": "organizer.pref01n001.pension_risk_class",
    "pd_pen_tr_yn": "organizer.pref01n001.pension_trade_eligible",
    "pd_risk_cd": "organizer.pref01n001.risk_grade_code",
    "pd_risk_nm": "organizer.pref01n001.risk_grade_name",
    "pd_sale_yn": "organizer.pref01n001.saleable_in_master",
    "pd_sect_cd": "organizer.pref01n001.sector_code_raw",
    "pd_stk_cnt": "organizer.pref01n001.stock_count_raw",
    "pd_tr_yn": "organizer.pref01n001.trading_suspended",
    "wu_core_yn": "organizer.pref01n001.internal_core_flag",
    "wu_inv_ast_type": "organizer.pref01n001.investment_asset_type",
    "wu_inv_rgn": "organizer.pref01n001.investment_region",
    "wu_upt_dt": "organizer.pref01n001.classification_updated_on",
}


def synthetic_etp_row() -> dict[str, object]:
    return {
        "cu_base_index": "SYN INDEX 100",
        "cu_charge_etc_rt": "0",
        "cu_charge_rt": "0.35",
        "cu_fund_mgmt_co": "  합성　자산운용 ",
        "cu_lev_fector": "1.5",
        "cu_strtegy": "SYN-REPLICATION",
        "cu_upt_dt": "20260614",
        "du_bpr": Decimal("10000"),
        "du_chas_errt": Decimal("0"),
        "du_clpr": Decimal("10100"),
        "du_diff_rt": Decimal("0"),
        "du_er_1d": Decimal("0.20"),
        "du_er_1m": Decimal("1.20"),
        "du_er_1y": Decimal("8.20"),
        "du_er_3m": Decimal("2.70"),
        "du_er_6m": Decimal("4.50"),
        "du_er_ytd": Decimal("6.10"),
        "du_hpr": Decimal("10200"),
        "du_last_aum": Decimal("2500000000"),
        "du_last_nav": Decimal("10080"),
        "du_lpr": Decimal("9950"),
        "du_nav_rnf_amt": Decimal("10"),
        "du_nav_yday": Decimal("10070"),
        "du_upt_dt": datetime(2026, 6, 15),
        "du_val_1d": Decimal("500000000"),
        "du_val_1m": Decimal("450000000"),
        "du_val_5d": Decimal("480000000"),
        "du_vol_1d": Decimal("50000"),
        "du_vol_avg_1m": Decimal("45000"),
        "du_vol_avg_5d": Decimal("48000"),
        "nru_mkt_diff_rt": None,
        "nru_mkt_inav": None,
        "pd_abrv_nm": "SYN-ETF",
        "pd_circ_net_tamt": Decimal("2000000000"),
        "pd_circ_stk_cnt": Decimal("200000"),
        "pd_curr_cd": "KRW",
        "pd_curr_nm": "Synthetic Won",
        "pd_divd_amt_pshr": Decimal("0"),
        "pd_dvid_cycl": None,
        "pd_dvid_yield": Decimal("0"),
        "pd_exg_mkt_cd": "SYN-EXG",
        "pd_exg_mkt_nm": "Synthetic Exchange",
        "pd_grp_no": "ETF",
        "pd_itm_no": "SYN-ETP-001",
        "pd_itm_no_ma": "SYN-ETP-MA-001",
        "pd_lst_price": Decimal("0"),
        "pd_lst_stk_cnt": Decimal("250000"),
        "pd_lste_dt": "20301231",
        "pd_lstg_dt": "20200102",
        "pd_mkt_id": "SYN-MKT",
        "pd_mkt_nm": "Synthetic Market",
        "pd_nav_pshr": Decimal("10080"),
        "pd_net_ast_pshr": Decimal("0"),
        "pd_net_prft_pshr": Decimal("0"),
        "pd_net_rt_ast_pshr": Decimal("0"),
        "pd_net_tamt": Decimal("2500000000"),
        "pd_nm": "  합성　국내 ETF 1 ",
        "pd_pen_risk_nm": "SYN-RISK-ASSET",
        "pd_pen_tr_yn": "Y",
        "pd_risk_cd": "SYN-RISK-2",
        "pd_risk_nm": "SYN-HIGH-RISK",
        "pd_sale_yn": "1",
        "pd_sect_cd": "SYN-SECTOR",
        "pd_sect_nm": None,
        "pd_spac_yn": "N",
        "pd_stk_cnt": Decimal("210000"),
        "pd_tr_yn": "0",
        "ru_mkt_price": None,
        "ru_mkt_volume": None,
        "wu_core_yn": "N",
        "wu_inv_ast_type": "SYN-EQUITY",
        "wu_inv_rgn": "SYN-GLOBAL",
        "wu_upt_dt": "20260615",
    }


def records(mapped, table: str) -> tuple[Mapping[str, object], ...]:
    return mapped.records_by_table.get(table, ())


def observation(mapped, column: str) -> Mapping[str, object]:
    metric_id = EXPECTED_METRIC_IDS[column]
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


def relation(mapped, predicate_id: str) -> Mapping[str, object]:
    return next(
        item
        for item in records(mapped, "relation.relation_record")
        if item["predicate_id"] == predicate_id
    )


def test_all_73_fields_are_handled_or_ignored_exactly_once() -> None:
    expected = set(EXPECTED_COLUMNS)

    assert SPEC.expected_columns == EXPECTED_COLUMNS
    assert HANDLED_COLUMNS.isdisjoint(IGNORED_COLUMNS)
    assert HANDLED_COLUMNS | set(IGNORED_COLUMNS) == expected
    assert len(HANDLED_COLUMNS) == 56
    assert IGNORED_COLUMNS == {
        "cu_charge_etc_rt": "UNUSABLE_ALL_ZERO_SERIES",
        "du_chas_errt": "UNUSABLE_ALL_ZERO_SERIES",
        "du_diff_rt": "UNUSABLE_ALL_ZERO_SERIES",
        "du_nav_rnf_amt": "FAILED_DERIVATION_CHECK",
        "nru_mkt_diff_rt": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
        "nru_mkt_inav": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
        "pd_divd_amt_pshr": "UNUSABLE_ALL_ZERO_SERIES",
        "pd_dvid_cycl": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
        "pd_dvid_yield": "UNUSABLE_ALL_ZERO_SERIES",
        "pd_lst_price": "UNUSABLE_ALL_ZERO_SERIES",
        "pd_net_ast_pshr": "UNUSABLE_ALL_ZERO_SERIES",
        "pd_net_prft_pshr": "UNUSABLE_ALL_ZERO_SERIES",
        "pd_net_rt_ast_pshr": "UNUSABLE_ALL_ZERO_SERIES",
        "pd_sect_nm": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
        "pd_spac_yn": "NOT_ANSWERABLE",
        "ru_mkt_price": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
        "ru_mkt_volume": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
    }


def test_etf_creates_product_security_identifiers_index_and_manager() -> None:
    mapped = map_row(7, synthetic_etp_row())

    assert mapped.disposition == "accepted"
    entities = records(mapped, "catalog.entity")
    product = next(item for item in entities if item["entity_type"] == "product")
    manager = next(
        item for item in entities if item["entity_type"] == "institution"
    )
    index = next(item for item in entities if item["entity_type"] == "index")
    assert product["canonical_name"] == "합성 국내 ETF 1"
    assert manager["canonical_name"] == "합성 자산운용"
    assert index["canonical_name"] == "SYN INDEX 100"
    assert records(mapped, "catalog.product") == (
        {
            "entity_id": product["entity_id"],
            "product_family": "domestic_etf",
            "primary_currency": "KRW",
        },
    )
    assert records(mapped, "catalog.security") == (
        {
            "entity_id": product["entity_id"],
            "security_kind": "etf",
            "ticker_display": "SYN-ETF",
            "isin_display": None,
        },
    )
    assert records(mapped, "catalog.institution") == (
        {"entity_id": manager["entity_id"], "institution_kind": "asset_manager"},
    )
    identifiers = records(mapped, "catalog.identifier")
    assert [
        (item["scheme"], item["identifier_value"], item["is_primary"])
        for item in identifiers
    ] == [
        ("PREF01_PD_ITM_NO", "SYN-ETP-001", True),
        ("PREF01_PD_ITM_NO_MA", "SYN-ETP-MA-001", False),
    ]
    assert records(mapped, "catalog.alias")[0]["alias_text"] == "SYN-ETF"
    assert relation(mapped, "managedBy")["object_id"] == manager["entity_id"]
    assert relation(mapped, "tracksIndex")["object_id"] == index["entity_id"]
    assert not any(
        item["predicate_id"] in {"listedOn", "availability"}
        for item in records(mapped, "relation.relation_record")
    )


def test_etn_uses_issuer_relation_without_changing_product_family() -> None:
    mapped = map_row(
        8,
        synthetic_etp_row()
        | {
            "pd_grp_no": "ETN",
            "pd_itm_no": "SYN-ETN-001",
            "pd_itm_no_ma": "SYN-ETN-MA-001",
            "pd_nm": "Synthetic ETN 1",
            "pd_abrv_nm": "SYN-ETN",
            "cu_fund_mgmt_co": "Synthetic Securities",
        },
    )

    assert mapped.disposition == "accepted"
    assert records(mapped, "catalog.product")[0]["product_family"] == "domestic_etf"
    assert records(mapped, "catalog.security")[0]["security_kind"] == "etn"
    assert records(mapped, "catalog.institution")[0]["institution_kind"] == "issuer"
    assert {item["predicate_id"] for item in records(
        mapped, "relation.relation_record"
    )} == {"issuedBy", "tracksIndex"}


def test_field_specific_dates_and_boolean_directions_are_preserved() -> None:
    mapped = map_row(9, synthetic_etp_row())

    assert observation(mapped, "cu_charge_rt")["applicable_date"] == date(
        2026, 6, 14
    )
    daily = observation(mapped, "du_upt_dt")
    assert daily["timestamp_value"] == datetime(2026, 6, 14, 15, tzinfo=UTC)
    assert daily["applicable_date"] == date(2026, 6, 15)
    close = observation(mapped, "du_clpr")
    assert close["applicable_date"] == date(2026, 6, 15)
    assert close["applicable_date"] != date(2026, 7, 11)
    one_year = observation(mapped, "du_er_1y")
    assert one_year["period_end"] == date(2026, 6, 15)
    assert one_year["period_start"] is None
    assert observation(mapped, "pd_tr_yn")["boolean_value"] is False
    assert observation(mapped, "pd_sale_yn")["boolean_value"] is True
    assert observation(mapped, "pd_pen_tr_yn")["boolean_value"] is True
    assert observation(mapped, "wu_inv_rgn")["applicable_date"] == date(
        2026, 6, 15
    )
    assert relation(mapped, "managedBy")["valid_from"] == date(2026, 6, 14)


def test_every_answerable_field_has_exact_evidence_and_one_origin() -> None:
    mapped = map_row(10, synthetic_etp_row())

    evidence_rows = records(mapped, "evidence.evidence_record")
    observation_origins = records(mapped, "evidence.evidence_observation_origin")
    relation_origins = records(mapped, "evidence.evidence_relation_origin")
    assert {item["locator_column"] for item in evidence_rows} == HANDLED_COLUMNS
    assert len(evidence_rows) == 56
    assert len(observation_origins) == 54
    assert len(relation_origins) == 2
    assert {item["evidence_id"] for item in evidence_rows} == {
        item["evidence_id"] for item in observation_origins + relation_origins
    }
    assert len(records(mapped, "observation.metric_definition")) == 54

    aum = evidence(mapped, "du_last_aum")
    assert aum["predicate_id"] == "organizer.pref01n001.aum"
    assert aum["normalized_value"] == {
        "type": "decimal",
        "value": "2500000000",
    }
    assert aum["currency"] == "KRW"
    assert aum["applicable_date"] == date(2026, 6, 15)
    assert aum["vintage_date"] == date(2026, 7, 11)
    assert aum["locator_type"] == "tabular"
    assert aum["locator_uri_or_object_key"] == SPEC.data_file_name
    assert aum["locator_record_key"] == "SYN-ETP-001"
    assert aum["locator_sheet"] == "datarows"
    assert aum["locator_row"] == 10
    assert aum["locator_column"] == "du_last_aum"
    assert aum["raw_value_repr"] == "2500000000"
    assert aum["parser_version"] == "1"
    assert aum["mapping_version"] == "1"
    assert aum["cutoff_status"] == "eligible"

    managed_by = relation(mapped, "managedBy")
    managed_by_evidence = evidence(mapped, "cu_fund_mgmt_co")
    assert managed_by_evidence["value_or_object_id"] == {
        "type": "string",
        "value": managed_by["object_id"],
    }
    assert managed_by_evidence["normalized_value"] == {
        "type": "string",
        "value": managed_by["object_id"],
    }


def test_text_encoded_numeric_zero_uses_zero_status() -> None:
    mapped = map_row(
        10,
        synthetic_etp_row() | {"cu_charge_rt": "0", "cu_lev_fector": "0"},
    )

    assert observation(mapped, "cu_charge_rt")["value_status"] == "zero"
    assert observation(mapped, "cu_charge_rt")["numeric_value"] == 0
    assert observation(mapped, "cu_lev_fector")["value_status"] == "zero"
    assert observation(mapped, "cu_lev_fector")["numeric_value"] == 0


def test_non_index_placeholder_does_not_create_index_or_relation() -> None:
    mapped = map_row(
        10,
        synthetic_etp_row() | {"cu_base_index": "제공되지 않음"},
    )

    assert mapped.disposition == "limited"
    assert not any(
        item["entity_type"] == "index"
        for item in records(mapped, "catalog.entity")
    )
    assert not any(
        item["predicate_id"] == "tracksIndex"
        for item in records(mapped, "relation.relation_record")
    )
    assert ("cu_base_index", "SOURCE_VALUE_PLACEHOLDER") in {
        (issue.column, issue.code) for issue in mapped.issues
    }


def test_sentinels_do_not_become_normal_leverage_returns_or_live_market_facts() -> None:
    mapped = map_row(
        11,
        synthetic_etp_row()
        | {
            "cu_base_index": " ",
            "cu_lev_fector": "",
            "cu_strtegy": "C",
            "du_er_1m": Decimal("-100"),
            "pd_curr_cd": "CURR_CD_000",
            "pd_lste_dt": "99991231",
            "pd_pen_risk_nm": "N",
            "pd_sale_yn": "0",
            "pd_tr_yn": "1",
            "ru_mkt_price": Decimal("0"),
            "ru_mkt_volume": "",
        },
    )

    assert mapped.disposition == "limited"
    assert records(mapped, "catalog.product")[0]["primary_currency"] is None
    assert observation(mapped, "cu_lev_fector")["value_status"] == "missing"
    assert observation(mapped, "cu_strtegy")["value_status"] == "unknown"
    assert observation(mapped, "du_er_1m")["value_status"] == "placeholder"
    assert observation(mapped, "pd_curr_cd")["value_status"] == "inapplicable"
    assert observation(mapped, "pd_lste_dt")["value_status"] == "placeholder"
    assert observation(mapped, "pd_pen_risk_nm")["value_status"] == "inapplicable"
    assert observation(mapped, "pd_sale_yn")["boolean_value"] is False
    assert observation(mapped, "pd_tr_yn")["boolean_value"] is True
    assert evidence(mapped, "du_er_1m")["normalized_value"] == {
        "type": "null",
        "value": None,
    }
    assert evidence(mapped, "du_er_1m")["raw_value_repr"] == "-100"
    assert not any(
        item["locator_column"] in {"ru_mkt_price", "ru_mkt_volume"}
        for item in records(mapped, "evidence.evidence_record")
    )
    assert not any(
        item["predicate_id"] == "tracksIndex"
        for item in records(mapped, "relation.relation_record")
    )


def test_product_ids_are_stable_and_distinct_by_primary_natural_key() -> None:
    first = map_row(1, synthetic_etp_row())
    repeated = map_row(99, synthetic_etp_row())
    changed = map_row(
        2,
        synthetic_etp_row()
        | {
            "pd_itm_no": "SYN-ETP-002",
            "pd_itm_no_ma": "SYN-ETP-MA-002",
        },
    )

    assert records(first, "catalog.product")[0]["entity_id"] == records(
        repeated, "catalog.product"
    )[0]["entity_id"]
    assert records(first, "catalog.product")[0]["entity_id"] != records(
        changed, "catalog.product"
    )[0]["entity_id"]


@pytest.mark.parametrize("column", ["pd_itm_no", "pd_itm_no_ma"])
def test_missing_required_identifier_quarantines_without_records(column: str) -> None:
    mapped = map_row(12, synthetic_etp_row() | {column: "  "})

    assert mapped.disposition == "quarantined"
    assert not any(mapped.records_by_table.values())
    assert len(mapped.issues) == 1
    assert mapped.issues[0].column == column
    assert mapped.issues[0].code == "MISSING_NATURAL_KEY"


def test_binary_float_failure_reports_the_exact_column_without_value_leak() -> None:
    mapped = map_row(13, synthetic_etp_row() | {"du_last_aum": 3.141592})

    assert mapped.disposition == "quarantined"
    assert not any(mapped.records_by_table.values())
    assert mapped.issues[0].column == "du_last_aum"
    assert mapped.issues[0].code == "INVALID_SOURCE_VALUE"
    assert "3.141592" not in repr(mapped.issues)


def test_after_cutoff_update_is_fatal_but_future_end_date_is_allowed() -> None:
    allowed = map_row(
        14,
        synthetic_etp_row() | {"pd_lste_dt": "20351231"},
    )
    blocked = map_row(
        15,
        synthetic_etp_row()
        | {
            "pd_lste_dt": "20351231",
            "wu_upt_dt": "20260712",
        },
    )

    assert allowed.disposition == "accepted"
    assert observation(allowed, "pd_lste_dt")["date_value"] == date(2035, 12, 31)
    assert evidence(allowed, "pd_lste_dt")["normalized_value"] == {
        "type": "date",
        "value": "2035-12-31",
    }
    assert evidence(allowed, "pd_lste_dt")["applicable_date"] is None
    assert evidence(allowed, "pd_lste_dt")["cutoff_status"] == "eligible"
    assert blocked.disposition == "quarantined"
    assert not any(blocked.records_by_table.values())
    assert blocked.issues[0].column == "wu_upt_dt"
    assert blocked.issues[0].code == "AFTER_CUTOFF_SOURCE_VALUE"
    assert blocked.issues[0].severity == "fatal"

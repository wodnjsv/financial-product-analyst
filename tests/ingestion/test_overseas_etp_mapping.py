from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal

import pytest

from financial_agent.ingestion.mapping.overseas_etp import (
    HANDLED_COLUMNS,
    IGNORED_COLUMNS,
    SPEC,
    collect_duplicate_identifier_values,
    map_row,
)


EXPECTED_COLUMNS = (
    "cu_base_index",
    "cu_charge_rt",
    "cu_etn_yn",
    "cu_fund_mgmt_co",
    "cu_index_repl_mthd",
    "cu_index_tracking_yn",
    "cu_inverse_short_yn",
    "cu_lev_fector",
    "cu_strtegy",
    "cu_upt_dt",
    "du_base_dt_match_yn",
    "du_bpr",
    "du_clpr",
    "du_clpr_base_dt",
    "du_clpr_src",
    "du_diff_rt",
    "du_er_1d",
    "du_hpr",
    "du_last_aum",
    "du_last_nav",
    "du_lpr",
    "du_nav_base_dt",
    "du_opr",
    "du_upt_dt",
    "du_val_1d",
    "du_vol_1d",
    "pd_abrv_nm",
    "pd_curr_cd",
    "pd_exg_mkt_cd",
    "pd_grp_no",
    "pd_isin_cd",
    "pd_itm_no",
    "pd_itm_no_ma",
    "pd_lipper_id",
    "pd_lstg_dt",
    "pd_lst_price",
    "pd_lst_stk_cnt",
    "pd_mkt_id",
    "pd_nm",
    "pd_sale_yn",
    "pd_trd_ccy",
    "pd_tr_yn",
    "pd_us_cik",
    "ru_mkt_price",
    "ru_mkt_volume",
    "wu_core_yn",
    "wu_inv_ast_type",
    "wu_inv_rgn",
    "wu_upt_dt",
)

EXPECTED_METRIC_IDS = {
    "cu_charge_rt": "organizer.pref02n001.total_fee_rate",
    "cu_etn_yn": "organizer.pref02n001.is_etn",
    "cu_fund_mgmt_co": "organizer.pref02n001.provider_name_raw",
    "cu_index_repl_mthd": (
        "organizer.pref02n001.index_replication_method"
    ),
    "cu_index_tracking_yn": "organizer.pref02n001.index_tracking_flag",
    "cu_inverse_short_yn": "organizer.pref02n001.inverse_short_flag",
    "cu_strtegy": "organizer.pref02n001.strategy_description",
    "cu_upt_dt": "organizer.pref02n001.structure_updated_on",
    "du_base_dt_match_yn": "organizer.pref02n001.price_nav_date_match",
    "du_bpr": "organizer.pref02n001.base_price_raw",
    "du_clpr": "organizer.pref02n001.close_price",
    "du_clpr_base_dt": "organizer.pref02n001.close_price_date",
    "du_clpr_src": "organizer.pref02n001.close_price_source_raw",
    "du_hpr": "organizer.pref02n001.high_price",
    "du_last_aum": "organizer.pref02n001.aum",
    "du_last_nav": "organizer.pref02n001.nav_per_share",
    "du_lpr": "organizer.pref02n001.low_price",
    "du_nav_base_dt": "organizer.pref02n001.nav_date",
    "du_opr": "organizer.pref02n001.open_price",
    "du_upt_dt": "organizer.pref02n001.daily_updated_on",
    "du_val_1d": "organizer.pref02n001.trading_value_1d",
    "du_vol_1d": "organizer.pref02n001.trading_volume_1d",
    "pd_abrv_nm": "organizer.pref02n001.ticker",
    "pd_curr_cd": "organizer.pref02n001.product_currency",
    "pd_exg_mkt_cd": "organizer.pref02n001.exchange_code",
    "pd_grp_no": "organizer.pref02n001.product_type",
    "pd_isin_cd": "organizer.pref02n001.isin",
    "pd_itm_no": "organizer.pref02n001.product_id",
    "pd_itm_no_ma": "organizer.pref02n001.internal_product_id",
    "pd_lipper_id": "organizer.pref02n001.lipper_id",
    "pd_lstg_dt": "organizer.pref02n001.listing_date",
    "pd_lst_stk_cnt": "organizer.pref02n001.listed_security_count",
    "pd_mkt_id": "organizer.pref02n001.market_country_id",
    "pd_nm": "organizer.pref02n001.name",
    "pd_sale_yn": "organizer.pref02n001.saleable_in_master",
    "pd_trd_ccy": "organizer.pref02n001.trading_currency",
    "pd_tr_yn": "organizer.pref02n001.trading_status_code_raw",
    "pd_us_cik": "organizer.pref02n001.us_cik_raw",
    "wu_inv_ast_type": "organizer.pref02n001.investment_asset_type",
    "wu_inv_rgn": "organizer.pref02n001.investment_region",
    "wu_upt_dt": "organizer.pref02n001.classification_updated_on",
}


def synthetic_overseas_etp_row() -> dict[str, object]:
    return {
        "cu_base_index": "SYN GLOBAL INDEX 100",
        "cu_charge_rt": Decimal("0.25"),
        "cu_etn_yn": None,
        "cu_fund_mgmt_co": "  Synthetic  Asset Manager ",
        "cu_index_repl_mthd": "Full",
        "cu_index_tracking_yn": "Y",
        "cu_inverse_short_yn": "Y",
        "cu_lev_fector": None,
        "cu_strtegy": "Synthetic physical replication",
        "cu_upt_dt": "20260610",
        "du_base_dt_match_yn": "Y",
        "du_bpr": Decimal("100.10"),
        "du_clpr": Decimal("101.25"),
        "du_clpr_base_dt": "20260612",
        "du_clpr_src": "SYN-SOURCE",
        "du_diff_rt": Decimal("999"),
        "du_er_1d": Decimal("0"),
        "du_hpr": Decimal("102.00"),
        "du_last_aum": Decimal("2500000000"),
        "du_last_nav": Decimal("100.90"),
        "du_lpr": Decimal("99.80"),
        "du_nav_base_dt": datetime(2026, 6, 12),
        "du_opr": Decimal("100.00"),
        "du_upt_dt": "20260613",
        "du_val_1d": Decimal("500000000"),
        "du_vol_1d": Decimal("50000"),
        "pd_abrv_nm": "SYNX",
        "pd_curr_cd": "USD",
        "pd_exg_mkt_cd": "SYN-EXG",
        "pd_grp_no": "ETF",
        "pd_isin_cd": "SYN-ISIN-001",
        "pd_itm_no": "SYN-OVR-001",
        "pd_itm_no_ma": "SYN-OVR-MA-001",
        "pd_lipper_id": "SYN-LIPPER-001",
        "pd_lstg_dt": "20200102",
        "pd_lst_price": Decimal("0"),
        "pd_lst_stk_cnt": Decimal("250000"),
        "pd_mkt_id": "US",
        "pd_nm": "  Synthetic  Overseas ETF 1 ",
        "pd_sale_yn": "1",
        "pd_trd_ccy": "EUR",
        "pd_tr_yn": "0",
        "pd_us_cik": "SYN-CIK-001",
        "ru_mkt_price": Decimal("101.25"),
        "ru_mkt_volume": Decimal("50000"),
        "wu_core_yn": None,
        "wu_inv_ast_type": "SYN-EQUITY",
        "wu_inv_rgn": "SYN-GLOBAL",
        "wu_upt_dt": "20260611",
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


def map_synthetic(
    row_number: int,
    row: Mapping[str, object] | None = None,
    *,
    duplicate_identifier_values: Mapping[str, frozenset[str]] | None = None,
):
    return map_row(
        row_number,
        row or synthetic_overseas_etp_row(),
        duplicate_identifier_values=duplicate_identifier_values or {},
    )


def test_all_49_fields_are_handled_or_ignored_exactly_once() -> None:
    expected = set(EXPECTED_COLUMNS)

    assert SPEC.expected_columns == EXPECTED_COLUMNS
    assert HANDLED_COLUMNS.isdisjoint(IGNORED_COLUMNS)
    assert HANDLED_COLUMNS | set(IGNORED_COLUMNS) == expected
    assert len(HANDLED_COLUMNS) == 42
    assert IGNORED_COLUMNS == {
        "cu_lev_fector": "NOT_AVAILABLE_CURRENT_SNAPSHOT",
        "du_diff_rt": "UNTRUSTED_SPARSE_SERIES",
        "du_er_1d": "UNUSABLE_ALL_ZERO_SERIES",
        "pd_lst_price": "UNUSABLE_ALL_ZERO_SERIES",
        "ru_mkt_price": "DUPLICATE_RUNTIME_VALUE_WITHOUT_TIME_BASIS",
        "ru_mkt_volume": "DUPLICATE_RUNTIME_VALUE",
        "wu_core_yn": "NOT_ANSWERABLE",
    }


def test_prescan_keeps_duplicate_external_ids_as_observations_only() -> None:
    first = synthetic_overseas_etp_row()
    second = first | {
        "pd_itm_no": "SYN-OVR-002",
        "pd_itm_no_ma": "SYN-OVR-MA-002",
        "pd_abrv_nm": "SYNX-B",
        "pd_nm": "Synthetic Overseas ETF 1 B",
        "du_last_aum": Decimal("2600000000"),
    }
    duplicate_values = collect_duplicate_identifier_values([first, second])

    assert duplicate_values == {
        "pd_isin_cd": frozenset({"SYN-ISIN-001"}),
        "pd_lipper_id": frozenset({"SYN-LIPPER-001"}),
    }
    mapped_first = map_synthetic(
        7,
        first,
        duplicate_identifier_values=duplicate_values,
    )
    mapped_second = map_synthetic(
        8,
        second,
        duplicate_identifier_values=duplicate_values,
    )
    schemes = {
        item["scheme"]
        for mapped in (mapped_first, mapped_second)
        for item in records(mapped, "catalog.identifier")
    }
    assert schemes == {"PREF02_PD_ITM_NO", "PREF02_PD_ITM_NO_MA"}
    assert not records(mapped_first, "catalog.security")
    assert observation(mapped_first, "pd_isin_cd")["text_value"] == (
        "SYN-ISIN-001"
    )
    assert observation(mapped_first, "pd_lipper_id")["text_value"] == (
        "SYN-LIPPER-001"
    )
    assert evidence(mapped_first, "pd_isin_cd")["raw_value_repr"] == (
        "SYN-ISIN-001"
    )
    assert records(mapped_first, "catalog.product")[0]["entity_id"] != records(
        mapped_second, "catalog.product"
    )[0]["entity_id"]
    assert mapped_first.disposition == "limited"
    assert {
        (issue.column, issue.code) for issue in mapped_first.issues
    } >= {
        ("pd_isin_cd", "DUPLICATE_SOURCE_IDENTIFIER"),
        ("pd_lipper_id", "DUPLICATE_SOURCE_IDENTIFIER"),
    }


def test_unique_ids_and_etf_relationships_are_materialized() -> None:
    mapped = map_synthetic(9)

    entities = records(mapped, "catalog.entity")
    product = next(item for item in entities if item["entity_type"] == "product")
    manager = next(
        item for item in entities if item["entity_type"] == "institution"
    )
    index = next(item for item in entities if item["entity_type"] == "index")
    assert product["canonical_name"] == "Synthetic Overseas ETF 1"
    assert records(mapped, "catalog.product") == (
        {
            "entity_id": product["entity_id"],
            "product_family": "overseas_etf",
            "primary_currency": "USD",
        },
    )
    assert not records(mapped, "catalog.security")
    assert records(mapped, "catalog.institution") == (
        {"entity_id": manager["entity_id"], "institution_kind": "asset_manager"},
    )
    assert [
        (item["scheme"], item["identifier_value"], item["is_primary"])
        for item in records(mapped, "catalog.identifier")
    ] == [
        ("PREF02_PD_ITM_NO", "SYN-OVR-001", True),
        ("PREF02_PD_ITM_NO_MA", "SYN-OVR-MA-001", False),
        ("ISIN", "SYN-ISIN-001", False),
        ("LIPPER", "SYN-LIPPER-001", False),
    ]
    assert records(mapped, "catalog.alias")[0]["alias_text"] == "SYNX"
    assert relation(mapped, "managedBy")["object_id"] == manager["entity_id"]
    assert relation(mapped, "tracksIndex")["object_id"] == index["entity_id"]


def test_etn_provider_stays_source_local_observation() -> None:
    mapped = map_synthetic(
        10,
        synthetic_overseas_etp_row()
        | {
            "pd_grp_no": "ETN",
            "pd_itm_no": "SYN-ETN-001",
            "pd_itm_no_ma": "SYN-ETN-MA-001",
            "pd_nm": "Synthetic Overseas ETN 1",
            "pd_abrv_nm": "SYN-ETN",
            "cu_etn_yn": "Y",
            "cu_fund_mgmt_co": "Synthetic Securities Provider",
        },
    )

    assert records(mapped, "catalog.product")[0]["product_family"] == (
        "overseas_etf"
    )
    assert not records(mapped, "catalog.security")
    assert not records(mapped, "catalog.institution")
    assert {item["predicate_id"] for item in records(
        mapped, "relation.relation_record"
    )} == {"tracksIndex"}
    assert observation(mapped, "cu_fund_mgmt_co")["text_value"] == (
        "Synthetic Securities Provider"
    )


def test_dates_currencies_asset_region_price_nav_and_volume_are_preserved() -> None:
    mapped = map_synthetic(11)

    assert observation(mapped, "cu_charge_rt")["unit"] == "source_defined_rate"
    assert observation(mapped, "cu_charge_rt")["applicable_date"] == date(
        2026, 6, 10
    )
    assert observation(mapped, "du_clpr")["applicable_date"] == date(
        2026, 6, 12
    )
    assert observation(mapped, "du_last_nav")["applicable_date"] == date(
        2026, 6, 12
    )
    assert observation(mapped, "du_last_aum")["applicable_date"] == date(
        2026, 6, 13
    )
    assert observation(mapped, "du_clpr")["currency"] == "EUR"
    assert observation(mapped, "du_last_nav")["currency"] == "USD"
    assert observation(mapped, "du_last_aum")["currency"] == "USD"
    assert observation(mapped, "du_vol_1d")["unit"] == "shares_or_notes"
    assert observation(mapped, "wu_inv_ast_type")["text_value"] == "SYN-EQUITY"
    assert observation(mapped, "wu_inv_rgn")["text_value"] == "SYN-GLOBAL"


def test_every_answerable_field_has_exact_evidence_and_one_origin() -> None:
    mapped = map_synthetic(12)

    evidence_rows = records(mapped, "evidence.evidence_record")
    observation_origins = records(mapped, "evidence.evidence_observation_origin")
    relation_origins = records(mapped, "evidence.evidence_relation_origin")
    assert {item["locator_column"] for item in evidence_rows} == HANDLED_COLUMNS
    assert len(evidence_rows) == 42
    assert len(observation_origins) == 40
    assert len(relation_origins) == 2
    assert {item["evidence_id"] for item in evidence_rows} == {
        item["evidence_id"] for item in observation_origins + relation_origins
    }
    assert len(records(mapped, "observation.metric_definition")) == 40

    aum = evidence(mapped, "du_last_aum")
    assert aum["predicate_id"] == "organizer.pref02n001.aum"
    assert aum["normalized_value"] == {
        "type": "decimal",
        "value": "2500000000",
    }
    assert aum["currency"] == "USD"
    assert aum["applicable_date"] == date(2026, 6, 13)
    assert aum["vintage_date"] == date(2026, 7, 11)
    assert aum["locator_uri_or_object_key"] == SPEC.data_file_name
    assert aum["locator_record_key"] == "SYN-OVR-001"
    assert aum["locator_sheet"] == "datarows"
    assert aum["locator_row"] == 12
    assert aum["locator_column"] == "du_last_aum"
    assert aum["raw_value_repr"] == "2500000000"
    assert aum["cutoff_status"] == "eligible"


def test_placeholder_and_untrusted_series_do_not_create_financial_facts() -> None:
    mapped = map_synthetic(
        13,
        synthetic_overseas_etp_row()
        | {
            "cu_base_index": (
                "Index information is not available from the Lipper database."
            ),
            "cu_inverse_short_yn": None,
            "du_er_1d": Decimal("0"),
            "ru_mkt_price": Decimal("999.99"),
            "ru_mkt_volume": Decimal("99999"),
        },
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
    assert observation(mapped, "cu_inverse_short_yn")["value_status"] == (
        "missing"
    )
    assert not any(
        item["locator_column"]
        in {"cu_lev_fector", "du_er_1d", "ru_mkt_price", "ru_mkt_volume"}
        for item in records(mapped, "evidence.evidence_record")
    )
    assert not any(
        "normal" in str(item["metric_id"])
        for item in records(mapped, "observation.observation_record")
    )


def test_missing_nav_and_mismatched_dates_do_not_derive_premium_discount() -> None:
    mapped = map_synthetic(
        14,
        synthetic_overseas_etp_row()
        | {
            "du_base_dt_match_yn": "N",
            "du_last_nav": None,
            "du_nav_base_dt": datetime(2026, 6, 11),
        },
    )

    assert observation(mapped, "du_last_nav")["value_status"] == "missing"
    assert observation(mapped, "du_last_nav")["numeric_value"] is None
    assert observation(mapped, "du_nav_base_dt")["date_value"] == date(
        2026, 6, 11
    )
    assert observation(mapped, "du_base_dt_match_yn")["boolean_value"] is False
    assert observation(mapped, "du_clpr")["applicable_date"] == date(
        2026, 6, 12
    )
    assert not any(
        "premium" in str(item["metric_id"])
        or "discount" in str(item["metric_id"])
        for item in records(mapped, "observation.observation_record")
    )


def test_missing_optional_ids_remain_missing_observations() -> None:
    mapped = map_synthetic(
        15,
        synthetic_overseas_etp_row()
        | {"pd_isin_cd": None, "pd_lipper_id": " "},
    )

    assert mapped.disposition == "limited"
    assert observation(mapped, "pd_isin_cd")["value_status"] == "missing"
    assert observation(mapped, "pd_lipper_id")["value_status"] == "missing"
    assert {
        item["scheme"] for item in records(mapped, "catalog.identifier")
    } == {"PREF02_PD_ITM_NO", "PREF02_PD_ITM_NO_MA"}


def test_product_identity_uses_only_the_source_record_key() -> None:
    first = map_synthetic(16)
    optional_ids_changed = map_synthetic(
        99,
        synthetic_overseas_etp_row()
        | {
            "pd_isin_cd": "SYN-ISIN-CHANGED",
            "pd_lipper_id": "SYN-LIPPER-CHANGED",
        },
    )
    primary_changed = map_synthetic(
        17,
        synthetic_overseas_etp_row()
        | {
            "pd_itm_no": "SYN-OVR-002",
            "pd_itm_no_ma": "SYN-OVR-MA-002",
        },
    )

    first_id = records(first, "catalog.product")[0]["entity_id"]
    assert first_id == records(optional_ids_changed, "catalog.product")[0][
        "entity_id"
    ]
    assert first_id != records(primary_changed, "catalog.product")[0]["entity_id"]


@pytest.mark.parametrize("column", ["pd_itm_no", "pd_itm_no_ma"])
def test_missing_required_identifier_quarantines_without_records(column: str) -> None:
    mapped = map_synthetic(
        18,
        synthetic_overseas_etp_row() | {column: "  "},
    )

    assert mapped.disposition == "quarantined"
    assert not any(mapped.records_by_table.values())
    assert mapped.issues[0].column == column
    assert mapped.issues[0].code == "MISSING_NATURAL_KEY"


def test_binary_float_failure_reports_column_without_value_leak() -> None:
    mapped = map_synthetic(
        19,
        synthetic_overseas_etp_row() | {"du_last_aum": 3.141592},
    )

    assert mapped.disposition == "quarantined"
    assert not any(mapped.records_by_table.values())
    assert mapped.issues[0].column == "du_last_aum"
    assert mapped.issues[0].code == "INVALID_SOURCE_VALUE"
    assert "3.141592" not in repr(mapped.issues)


def test_after_cutoff_update_is_fatal_but_future_listing_date_is_preserved() -> None:
    allowed = map_synthetic(
        20,
        synthetic_overseas_etp_row() | {"pd_lstg_dt": "20351231"},
    )
    blocked = map_synthetic(
        21,
        synthetic_overseas_etp_row() | {"du_upt_dt": "20260712"},
    )

    assert observation(allowed, "pd_lstg_dt")["date_value"] == date(2035, 12, 31)
    assert evidence(allowed, "pd_lstg_dt")["normalized_value"] == {
        "type": "date",
        "value": "2035-12-31",
    }
    assert evidence(allowed, "pd_lstg_dt")["applicable_date"] is None
    assert blocked.disposition == "quarantined"
    assert not any(blocked.records_by_table.values())
    assert blocked.issues[0].column == "du_upt_dt"
    assert blocked.issues[0].code == "AFTER_CUTOFF_SOURCE_VALUE"
    assert blocked.issues[0].severity == "fatal"

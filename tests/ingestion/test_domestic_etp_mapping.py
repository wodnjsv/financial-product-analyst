from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from financial_agent.ingestion.identity import (
    build_authoritative_identity_index,
    collect_organizer_identifier_candidates,
)
from financial_agent.ingestion.mapping.common import stable_id
from financial_agent.ingestion.mapping.domestic_etp import (
    EVIDENCE_ONLY_COLUMNS,
    HANDLED_COLUMNS,
    IGNORED_COLUMNS,
    SPEC,
    analyze_domestic_etp_rows,
    map_row,
)
from financial_agent.ingestion.models import IdentifierCandidate


DOMESTIC_ETF_ISIN = "KR7005930003"


def synthetic_etp_row() -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(SPEC.expected_columns)
    row.update(
        {
            "cu_base_index": "SYN INDEX 100",
            "cu_charge_etc_rt": "0.02",
            "cu_charge_rt": "0.35",
            "cu_fund_mgmt_co": "  합성　자산운용 ",
            "cu_lev_fector": "1.5",
            "cu_strtegy": "SYN-REPLICATION",
            "cu_upt_dt": "20260820",
            "du_bpr": Decimal("10000"),
            "du_chas_errt": Decimal("0.71"),
            "du_chas_errt_base_dt": "20260821",
            "du_clpr": Decimal("10100"),
            "du_diff_rt": Decimal("-0.19"),
            "du_diff_rt_base_dt": "20260821",
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
            "du_nav_base_dt": "20260821",
            "du_nav_rnf_amt": Decimal("10"),
            "du_nav_yday": Decimal("10070"),
            "du_upt_dt": "20260822",
            "du_val_1d": Decimal("500000000"),
            "du_val_1m": Decimal("450000000"),
            "du_val_5d": Decimal("480000000"),
            "du_vlty_1m": Decimal("12.1"),
            "du_vlty_1y": Decimal("18.4"),
            "du_vlty_3m": Decimal("14.2"),
            "du_vlty_6m": Decimal("16.3"),
            "du_vlty_base_dt": "20260822",
            "du_vol_1d": Decimal("50000"),
            "du_vol_avg_1m": Decimal("45000"),
            "du_vol_avg_5d": Decimal("48000"),
            "fn_average_coupon": Decimal("3.2"),
            "fn_average_maturity": Decimal("4.1"),
            "fn_average_quality": "AA",
            "fn_base_dt": "20260820",
            "fn_effective_duration": Decimal("3.4"),
            "fn_effective_maturity": Decimal("4.0"),
            "fn_modified_duration": Decimal("3.3"),
            "fn_nominal_maturity": Decimal("4.2"),
            "fn_portfolio_dt": "20260819",
            "pd_abrv_nm": "SYN-ETF",
            "pd_circ_net_tamt": Decimal("2000000000"),
            "pd_circ_stk_cnt": Decimal("200000"),
            "pd_curr_cd": "KRW",
            "pd_curr_nm": "대한민국 원",
            "pd_divd_amt_ann": Decimal("480"),
            "pd_divd_amt_pshr": Decimal("40"),
            "pd_dvid_base_dt": "20260821",
            "pd_dvid_cycl": "M",
            "pd_dvid_inc_dist": Decimal("40"),
            "pd_dvid_nav": Decimal("10050"),
            "pd_dvid_pay_cnt": Decimal("12"),
            "pd_dvid_pay_months": "1,2,3,4,5,6,7,8,9,10,11,12",
            "pd_dvid_prc_base_dt": "20260820",
            "pd_dvid_tax_basis": "과세기준가",
            "pd_dvid_yield": Decimal("4.8"),
            "pd_exg_mkt_cd": "KOSPI",
            "pd_exg_mkt_nm": "유가증권시장",
            "pd_grp_no": "ETF",
            "pd_isin_cd": DOMESTIC_ETF_ISIN,
            "pd_itm_no": DOMESTIC_ETF_ISIN,
            "pd_itm_no_ma": "SYN-ETP-MA-001",
            "pd_lst_stk_cnt": Decimal("250000"),
            "pd_lste_dt": "20301231",
            "pd_lstg_dt": "20200102",
            "pd_mkt_id": "INTERNAL-MKT",
            "pd_mkt_nm": "국내시장",
            "pd_net_tamt": Decimal("2500000000"),
            "pd_nm": "  합성　국내 ETF 1 ",
            "pd_pen_risk_nm": "고위험",
            "pd_pen_tr_yn": "Y",
            "pd_ric": "SYNETF.KS",
            "pd_risk_cd": "RISK-2",
            "pd_risk_nm": "높은위험",
            "pd_sale_yn": "1",
            "pd_sect_cd": "INTERNAL-SECTOR",
            "pd_spac_yn": "N",
            "pd_stk_cnt": Decimal("210000"),
            "pd_ticker": "SYNETF",
            "pd_tr_yn": "0",
            "ref_ast_type": "Equity ETF",
            "ref_base_dt": "20260821",
            "ref_base_index": "SYN INDEX 100",
            "ref_fund_mgmt_co": "합성 자산운용",
            "ref_geo_focus": "Korea",
            "ru_mkt_price": Decimal("10110"),
            "ru_mkt_volume": Decimal("51000"),
            "wu_core_yn": "N",
            "wu_inv_ast_type": "주식",
            "wu_inv_rgn": "한국",
            "wu_upt_dt": "20260821",
        }
    )
    return row


def _context(rows: tuple[Mapping[str, object], ...]):
    candidates = collect_organizer_identifier_candidates("PREF01N001", rows)
    return analyze_domestic_etp_rows(rows), build_authoritative_identity_index(
        candidates
    )


def _map(
    row: Mapping[str, object],
    *,
    rows: tuple[Mapping[str, object], ...] | None = None,
    extra_candidates: tuple[IdentifierCandidate, ...] = (),
):
    source_rows = rows or (row,)
    analysis = analyze_domestic_etp_rows(source_rows)
    candidates = collect_organizer_identifier_candidates(
        "PREF01N001", source_rows
    )
    identity_index = build_authoritative_identity_index(
        candidates + extra_candidates
    )
    return map_row(
        2,
        row,
        analysis=analysis,
        identity_index=identity_index,
    )


def records(mapped, table: str) -> tuple[Mapping[str, object], ...]:
    return mapped.records_by_table.get(table, ())


def observation(mapped, metric_suffix: str) -> Mapping[str, object]:
    metric_id = f"organizer.pref01n001.{metric_suffix}"
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


def test_all_98_fields_are_handled_and_none_are_silently_ignored() -> None:
    assert len(SPEC.expected_columns) == 98
    assert HANDLED_COLUMNS == frozenset(SPEC.expected_columns)
    assert IGNORED_COLUMNS == {}
    assert EVIDENCE_ONLY_COLUMNS == {
        "du_lpr",
        "fn_average_quality",
        "pd_mkt_id",
        "pd_risk_cd",
        "pd_sect_cd",
        "ru_mkt_price",
        "ru_mkt_volume",
    }


def test_etf_uses_canonical_identity_and_promotes_only_eligible_identifiers() -> None:
    row = synthetic_etp_row()
    mapped = _map(row)

    product = records(mapped, "catalog.product")[0]
    assert product["entity_id"] == stable_id(
        "product", "PREF01N001", DOMESTIC_ETF_ISIN
    )
    assert product["product_family"] == "domestic_etf"
    assert product["primary_currency"] == "KRW"
    assert not records(mapped, "catalog.security")
    assert {
        (item["scheme"], item["identifier_value"], item["is_primary"])
        for item in records(mapped, "catalog.identifier")
    } == {
        ("PREF01_PD_ITM_NO", DOMESTIC_ETF_ISIN, True),
        ("ISIN", DOMESTIC_ETF_ISIN, False),
        ("PREF01_PD_ITM_NO_MA", "SYN-ETP-MA-001", False),
        ("REFINITIV_RIC", "SYNETF.KS", False),
    }
    assert {item["alias_text"] for item in records(mapped, "catalog.alias")} == {
        "SYN-ETF",
        "SYNETF",
    }
    assert len(relations(mapped, "managedBy")) == 1
    assert len(relations(mapped, "issuedBy")) == 0
    assert len(relations(mapped, "tracksIndex")) == 1


def test_etn_uses_issued_by_and_never_managed_by() -> None:
    row = synthetic_etp_row() | {
        "pd_grp_no": "ETN",
        "pd_isin_cd": "KR7000880005",
        "pd_itm_no": "KR7000880005",
        "pd_nm": "합성 국내 ETN",
        "pd_itm_no_ma": "SYN-ETN-MA-001",
        "pd_ric": "SYNETN.KS",
        "cu_fund_mgmt_co": "합성 증권",
        "ref_fund_mgmt_co": "합성 증권",
    }

    mapped = _map(row)

    assert observation(mapped, "product_type")["text_value"] == "ETN"
    assert len(relations(mapped, "issuedBy")) == 1
    assert len(relations(mapped, "managedBy")) == 0
    assert records(mapped, "catalog.institution")[0]["institution_kind"] == "issuer"


def test_public_fund_overlap_reuses_etf_owned_canonical_identity() -> None:
    row = synthetic_etp_row()
    fund_candidates = (
        IdentifierCandidate(
            source_code="PRFD01N001",
            row_number=2,
            natural_key="FUND-SHARE-1",
            entity_role="FundShareClass",
            scheme="PRFD_ITM_NO",
            value="FUND-SHARE-1",
        ),
        IdentifierCandidate(
            source_code="PRFD01N001",
            row_number=2,
            natural_key="FUND-SHARE-1",
            entity_role="FundShareClass",
            scheme="ISIN",
            value=DOMESTIC_ETF_ISIN,
        ),
    )

    mapped = _map(row, extra_candidates=fund_candidates)

    assert records(mapped, "catalog.product")[0]["entity_id"] == stable_id(
        "product", "PREF01N001", DOMESTIC_ETF_ISIN
    )


def test_new_tracking_distribution_volatility_and_bond_metrics_keep_dates() -> None:
    mapped = _map(synthetic_etp_row())

    assert observation(mapped, "tracking_error")["numeric_value"] == Decimal(
        "0.71"
    )
    assert observation(mapped, "tracking_error")["applicable_date"] == date(
        2026, 8, 21
    )
    assert observation(mapped, "premium_discount_rate")["numeric_value"] == Decimal(
        "-0.19"
    )
    assert observation(mapped, "premium_discount_rate")["applicable_date"] == date(
        2026, 8, 21
    )
    for suffix, value in {
        "annualized_volatility_1m": "12.1",
        "annualized_volatility_3m": "14.2",
        "annualized_volatility_6m": "16.3",
        "annualized_volatility_1y": "18.4",
    }.items():
        item = observation(mapped, suffix)
        assert item["numeric_value"] == Decimal(value)
        assert item["applicable_date"] == date(2026, 8, 22)
    assert observation(mapped, "distribution_per_share")["numeric_value"] == 40
    assert observation(mapped, "distribution_cycle")["text_value"] == "M"
    assert observation(mapped, "annualized_distribution_yield")["numeric_value"] == Decimal(
        "4.8"
    )
    assert observation(mapped, "effective_duration")["numeric_value"] == Decimal(
        "3.4"
    )
    assert observation(mapped, "effective_duration")["applicable_date"] == date(
        2026, 8, 20
    )


def test_zero_is_preserved_and_blank_portfolio_value_is_missing() -> None:
    row = synthetic_etp_row() | {
        "du_chas_errt": Decimal("0"),
        "pd_divd_amt_pshr": Decimal("0"),
        "fn_effective_duration": None,
    }

    mapped = _map(row)

    assert observation(mapped, "tracking_error")["value_status"] == "zero"
    assert observation(mapped, "tracking_error")["numeric_value"] == 0
    assert observation(mapped, "distribution_per_share")["value_status"] == "zero"
    assert observation(mapped, "effective_duration")["value_status"] == "missing"
    assert mapped.disposition == "limited"


def test_conflicting_organizer_relation_sources_preserve_evidence_but_no_relation() -> None:
    row = synthetic_etp_row() | {
        "ref_base_index": "OTHER INDEX",
        "ref_fund_mgmt_co": "다른 자산운용",
    }

    mapped = _map(row)

    assert not relations(mapped, "tracksIndex")
    assert not relations(mapped, "managedBy")
    assert {evidence(mapped, column)["locator_column"] for column in {
        "cu_base_index",
        "ref_base_index",
        "cu_fund_mgmt_co",
        "ref_fund_mgmt_co",
    }} == {
        "cu_base_index",
        "ref_base_index",
        "cu_fund_mgmt_co",
        "ref_fund_mgmt_co",
    }
    assert sum(
        issue.code == "SOURCE_RELATION_VALUE_CONFLICT"
        for issue in mapped.issues
    ) == 4
    for suffix in (
        "base_index_raw",
        "refinitiv_base_index_raw",
        "fund_manager_raw",
        "refinitiv_fund_manager_raw",
    ):
        raw_observation = observation(mapped, suffix)
        assert raw_observation["value_status"] == "present"
        assert raw_observation["reason_code"] is None


def test_duplicate_optional_identifiers_are_evidence_only() -> None:
    first = synthetic_etp_row()
    second = synthetic_etp_row() | {
        "pd_isin_cd": "KR7000880005",
        "pd_itm_no": "KR7000880005",
        "pd_nm": "다른 ETF",
    }
    analysis, identity_index = _context((first, second))

    mapped = map_row(
        2,
        first,
        analysis=analysis,
        identity_index=identity_index,
    )

    schemes = {item["scheme"] for item in records(mapped, "catalog.identifier")}
    assert "PREF01_PD_ITM_NO_MA" not in schemes
    assert "REFINITIV_RIC" not in schemes
    assert observation(mapped, "internal_product_id")["text_value"] == "SYN-ETP-MA-001"
    assert observation(mapped, "refinitiv_ric")["text_value"] == "SYNETF.KS"
    assert sum(
        issue.code == "DUPLICATE_IDENTIFIER_NOT_PROMOTED"
        for issue in mapped.issues
    ) == 2


def test_all_source_fields_have_one_exact_evidence_locator() -> None:
    mapped = _map(synthetic_etp_row())
    evidence_rows = records(mapped, "evidence.evidence_record")

    assert len(evidence_rows) == 98
    assert {item["locator_column"] for item in evidence_rows} == set(
        SPEC.expected_columns
    )
    assert all(item["locator_sheet"] == "data" for item in evidence_rows)
    assert all(item["mapping_version"] == "2" for item in evidence_rows)
    assert all(item["vintage_date"] == date(2026, 8, 24) for item in evidence_rows)
    assert evidence(mapped, "ru_mkt_price")["applicable_date"] is None


def test_future_end_date_is_allowed_but_future_fact_date_is_fatal() -> None:
    allowed = _map(synthetic_etp_row() | {"pd_lste_dt": "20351231"})
    blocked = _map(synthetic_etp_row() | {"du_vlty_base_dt": "20260825"})

    assert observation(allowed, "trading_end_date")["date_value"] == date(
        2035, 12, 31
    )
    assert blocked.disposition == "quarantined"
    assert blocked.issues[0].column == "du_vlty_base_dt"
    assert blocked.issues[0].code == "AFTER_CUTOFF_SOURCE_VALUE"
    assert blocked.issues[0].severity == "fatal"

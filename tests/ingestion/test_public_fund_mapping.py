from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from financial_agent.ingestion.identity import (
    build_authoritative_identity_index,
    collect_organizer_identifier_candidates,
)
from financial_agent.ingestion.mapping.common import stable_id
from financial_agent.ingestion.mapping.public_fund import (
    EVIDENCE_ONLY_COLUMNS,
    HANDLED_COLUMNS,
    IGNORED_COLUMNS,
    SPEC,
    analyze_public_fund_rows,
    map_row,
)
from financial_agent.ingestion.models import IdentifierCandidate


FUND_ISIN = "KR7005930003"


def synthetic_public_fund_row() -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(SPEC.expected_columns)
    row.update(
        {
            "bmrk_eng_nm": "Synthetic Benchmark English",
            "bmrk_nm": "SYN FUND INDEX",
            "bns_bpr": Decimal("1000.1"),
            "curr_cd": "KRW",
            "exchdg_yn": "Y",
            "fd_daily_bas_dt": "20260822",
            "fd_estb_ctry_cd": "KR",
            "fd_ivst_rgn_desc": "글로벌",
            "fd_last_dstb_actg_bss_dt": "20260101",
            "fd_last_dstb_actg_eot_dt": "20260630",
            "fd_last_dstb_r": Decimal("2.5"),
            "fd_mm18_ern_r": Decimal("18"),
            "fd_mm1_ern_r": Decimal("1"),
            "fd_mm3_ern_r": Decimal("3"),
            "fd_mm6_ern_r": Decimal("6"),
            "fd_nast_suma": Decimal("50000000000"),
            "fd_price_bas_dt": "20260822",
            "fd_prsv_r": Decimal("95"),
            "fd_sbpr": Decimal("1001.2"),
            "fd_set_pcd": "PUBLIC",
            "fd_wk1_ern_r": Decimal("0.5"),
            "fd_yr1_ern_r": Decimal("12"),
            "fd_yr2_ern_r": Decimal("24"),
            "fd_yr3_ern_r": Decimal("36"),
            "fd_yr5_ern_r": Decimal("60"),
            "frc_bpr_itm_yn": "0",
            "fss_itm_no": "FSS-SYN-001",
            "han_clas_fee_type": "온라인",
            "han_clas_nm": "클래스 A",
            "han_clas_policies": "선취 없음",
            "han_clas_sales_channel": "온라인",
            "hdge_fd_yn": "0",
            "int_dvd_desc": "배당형",
            "itm_abrv_nm": "SYN 공모펀드",
            "itm_eabrv_nm": "SYN-PUBLIC-FUND",
            "itm_eng_nm": "Synthetic Public Fund Class A",
            "itm_nm": "합성 공모펀드 클래스 A",
            "itm_no": "SYN-FUND-001",
            "kofia_fd_ccd": "KOFIA-RAW",
            "ksd_itm_no": FUND_ISIN,
            "mtco_itm_no": "MANAGER-PRODUCT-001",
            "ofsfd_yn": "0",
            "ofwk_trus_rwrd_r": Decimal("0.01"),
            "or_attr_desc": "주식형",
            "or_co_rwrd_r": Decimal("0.2"),
            "or_co_xtn_itt_cd": "MANAGER-001",
            "ovrs_fd_desc": "해외투자",
            "pers_corp_desc": "개인",
            "pfiv_sale_cntl_tcd": "CONTROL-RAW",
            "prfd_attr_cds": "A, B, A",
            "prfd_attr_cnt": "2",
            "prfd_attr_search_text": "A B",
            "prvo_fd_desc": "일반",
            "prvo_pbff_desc": "공모",
            "rptt_ksd_itm_no": "KR0000000000",
            "sale_co_rwrd_r": Decimal("0.3"),
            "sale_yn": "판매중",
            "std_itm_no": "STANDARD-001",
            "thco_sale_yn": "Y",
            "trusc_rwrd_r": Decimal("0.02"),
            "trusc_xtn_itt_cd": "TRUSTEE-RAW",
            "zrin_attr_nms": "성장형, 대형주, 성장형",
            "zrin_btyp_cd": "TYPE-RAW",
            "zrin_btyp_nm": "주식형",
            "zrin_dmst_bd_cmst_rt": Decimal("0"),
            "zrin_dmst_stk_cmst_rt": Decimal("20"),
            "zrin_etc_ast_cmst_rt": Decimal("5"),
            "zrin_fd_cmst_rt": Decimal("10"),
            "zrin_fd_ivst_risk_gcd": "2",
            "zrin_fd_ivst_risk_grd_nm": "높은 위험",
            "zrin_liqt_cmst_rt": Decimal("5"),
            "zrin_ovrs_bd_cmst_rt": Decimal("10"),
            "zrin_ovrs_stk_cmst_rt": Decimal("50"),
            "zrin_pcd": "ZEROIN-RAW",
            "zrin_ptn_nm": "글로벌주식",
        }
    )
    return row


def _map(
    row: Mapping[str, object],
    *,
    rows: tuple[Mapping[str, object], ...] | None = None,
    extra_candidates: tuple[IdentifierCandidate, ...] = (),
):
    source_rows = rows or (row,)
    analysis = analyze_public_fund_rows(source_rows)
    candidates = collect_organizer_identifier_candidates(
        "PRFD01N001", source_rows
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


def observations(mapped, metric_suffix: str) -> tuple[Mapping[str, object], ...]:
    metric_id = f"organizer.prfd01n001.{metric_suffix}"
    return tuple(
        item
        for item in records(mapped, "observation.observation_record")
        if item["metric_id"] == metric_id
    )


def observation(mapped, metric_suffix: str) -> Mapping[str, object]:
    return observations(mapped, metric_suffix)[0]


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


def test_all_75_fields_are_handled_and_none_are_silently_ignored() -> None:
    assert len(SPEC.expected_columns) == 75
    assert HANDLED_COLUMNS == frozenset(SPEC.expected_columns)
    assert IGNORED_COLUMNS == {}
    assert EVIDENCE_ONLY_COLUMNS == {
        "bmrk_eng_nm",
        "fd_estb_ctry_cd",
        "fd_set_pcd",
        "kofia_fd_ccd",
        "pfiv_sale_cntl_tcd",
        "trusc_xtn_itt_cd",
        "zrin_btyp_cd",
        "zrin_fd_ivst_risk_gcd",
        "zrin_pcd",
    }


def test_one_row_product_identifiers_aliases_and_relations_are_bounded() -> None:
    mapped = _map(synthetic_public_fund_row())

    product = records(mapped, "catalog.product")[0]
    assert product["entity_id"] == stable_id(
        "product", "PRFD01N001", "SYN-FUND-001"
    )
    assert product["product_family"] == "public_fund"
    assert product["primary_currency"] == "KRW"
    assert {
        (item["scheme"], item["identifier_value"], item["is_primary"])
        for item in records(mapped, "catalog.identifier")
    } == {
        ("PRFD_ITM_NO", "SYN-FUND-001", True),
        ("FSS_FUND", "FSS-SYN-001", False),
        ("KSD_PRODUCT", FUND_ISIN, False),
        ("ISIN", FUND_ISIN, False),
        ("MANAGER_SCOPED_PRODUCT:MANAGER-001", "MANAGER-PRODUCT-001", False),
        ("PRFD_STANDARD_PRODUCT", "STANDARD-001", False),
    }
    assert {item["alias_text"] for item in records(mapped, "catalog.alias")} == {
        "클래스 A",
        "SYN 공모펀드",
        "SYN-PUBLIC-FUND",
        "Synthetic Public Fund Class A",
    }
    assert len(relations(mapped, "managedBy")) == 1
    assert len(relations(mapped, "tracksIndex")) == 1
    assert not relations(mapped, "hasShareClass")


def test_domestic_etf_overlap_reuses_owner_without_second_product_or_isin() -> None:
    row = synthetic_public_fund_row()
    etf_candidates = (
        IdentifierCandidate(
            source_code="PREF01N001",
            row_number=2,
            natural_key=FUND_ISIN,
            entity_role="DomesticETF",
            scheme="PREF01_PD_ITM_NO",
            value=FUND_ISIN,
        ),
        IdentifierCandidate(
            source_code="PREF01N001",
            row_number=2,
            natural_key=FUND_ISIN,
            entity_role="DomesticETF",
            scheme="ISIN",
            value=FUND_ISIN,
        ),
    )

    mapped = _map(row, extra_candidates=etf_candidates)

    assert not records(mapped, "catalog.product")
    assert not any(
        item["entity_type"] == "product"
        for item in records(mapped, "catalog.entity")
    )
    assert "ISIN" not in {
        item["scheme"] for item in records(mapped, "catalog.identifier")
    }
    assert observation(mapped, "net_assets")["entity_id"] == stable_id(
        "product", "PREF01N001", FUND_ISIN
    )
    assert {
        item["scheme"] for item in records(mapped, "catalog.identifier")
    } >= {"PRFD_ITM_NO", "KSD_PRODUCT"}


def test_ordered_lists_are_trimmed_deduplicated_and_keep_one_raw_evidence() -> None:
    mapped = _map(synthetic_public_fund_row())

    assert [item["text_value"] for item in observations(mapped, "attribute_code")] == [
        "A",
        "B",
    ]
    assert [
        item["text_value"] for item in observations(mapped, "zeroin_attribute_name")
    ] == ["성장형", "대형주"]
    assert observation(mapped, "attribute_codes_raw")["text_value"] == "A, B, A"
    assert len(
        [
            item
            for item in records(mapped, "evidence.evidence_record")
            if item["locator_column"] == "prfd_attr_cds"
        ]
    ) == 1
    raw_evidence_id = evidence(mapped, "prfd_attr_cds")["evidence_id"]
    linked_observation_ids = {
        item["observation_id"]
        for item in records(mapped, "evidence.evidence_observation_origin")
        if item["evidence_id"] == raw_evidence_id
    }
    assert len(linked_observation_ids) == 3


def test_declared_attribute_count_mismatch_is_limited_not_rewritten() -> None:
    mapped = _map(synthetic_public_fund_row() | {"prfd_attr_cnt": "3"})

    assert observation(mapped, "attribute_count")["numeric_value"] == 3
    assert [item["text_value"] for item in observations(mapped, "attribute_code")] == [
        "A",
        "B",
    ]
    assert "ATTRIBUTE_COUNT_MISMATCH" in {issue.code for issue in mapped.issues}


def test_representative_fund_relation_uses_canonical_target_and_sentinels_do_not() -> None:
    representative = synthetic_public_fund_row() | {
        "itm_no": "REP-FUND",
        "itm_nm": "대표 펀드",
        "ksd_itm_no": "KR7000880005",
        "fss_itm_no": "FSS-REP",
        "mtco_itm_no": "MANAGER-REP",
        "std_itm_no": "STANDARD-REP",
    }
    share_class = synthetic_public_fund_row() | {
        "rptt_ksd_itm_no": "KR7000880005"
    }
    mapped = _map(share_class, rows=(representative, share_class))

    relation = relations(mapped, "hasShareClass")[0]
    assert relation["subject_id"] == stable_id(
        "product", "PRFD01N001", "REP-FUND"
    )
    assert relation["object_id"] == stable_id(
        "product", "PRFD01N001", "SYN-FUND-001"
    )

    sentinel = _map(
        synthetic_public_fund_row() | {"rptt_ksd_itm_no": "000000000000"}
    )
    assert not relations(sentinel, "hasShareClass")
    assert observation(sentinel, "representative_fund_id_raw")[
        "value_status"
    ] == "placeholder"


def test_representative_self_reference_and_cycles_are_suppressed() -> None:
    self_row = synthetic_public_fund_row() | {"rptt_ksd_itm_no": FUND_ISIN}
    self_mapped = _map(self_row)
    assert not relations(self_mapped, "hasShareClass")
    assert "SELF_REFERENTIAL_SHARE_CLASS" in {
        issue.code for issue in self_mapped.issues
    }

    first = synthetic_public_fund_row() | {
        "itm_no": "CYCLE-A",
        "ksd_itm_no": FUND_ISIN,
        "rptt_ksd_itm_no": "KR7000880005",
    }
    second = synthetic_public_fund_row() | {
        "itm_no": "CYCLE-B",
        "itm_nm": "순환 펀드 B",
        "ksd_itm_no": "KR7000880005",
        "rptt_ksd_itm_no": FUND_ISIN,
        "fss_itm_no": "FSS-CYCLE-B",
        "mtco_itm_no": "MANAGER-CYCLE-B",
        "std_itm_no": "STANDARD-CYCLE-B",
    }
    cycle_mapped = _map(first, rows=(first, second))
    assert not relations(cycle_mapped, "hasShareClass")
    assert "SHARE_CLASS_CYCLE" in {issue.code for issue in cycle_mapped.issues}


def test_values_dates_zero_and_float_cells_are_preserved() -> None:
    row = synthetic_public_fund_row() | {
        "fd_nast_suma": 5e10,
        "zrin_dmst_bd_cmst_rt": 0.0,
    }
    mapped = _map(row)

    assert observation(mapped, "net_assets")["numeric_value"] == Decimal(
        "5E+10"
    )
    assert observation(mapped, "net_assets")["applicable_date"] == date(
        2026, 8, 22
    )
    assert observation(mapped, "cumulative_return_1y")["period_end"] == date(
        2026, 8, 22
    )
    assert observation(mapped, "domestic_bond_weight")["value_status"] == "zero"
    assert observation(mapped, "last_distribution_rate")["period_end"] == date(
        2026, 6, 30
    )


def test_duplicate_optional_identifiers_are_evidence_only() -> None:
    first = synthetic_public_fund_row()
    second = synthetic_public_fund_row() | {
        "itm_no": "SYN-FUND-002",
        "itm_nm": "합성 공모펀드 2",
        "ksd_itm_no": "KR7000880005",
    }

    mapped = _map(first, rows=(first, second))
    schemes = {item["scheme"] for item in records(mapped, "catalog.identifier")}

    assert "FSS_FUND" not in schemes
    assert "MANAGER_SCOPED_PRODUCT:MANAGER-001" not in schemes
    assert "PRFD_STANDARD_PRODUCT" not in schemes
    assert observation(mapped, "fss_product_id")["text_value"] == "FSS-SYN-001"
    assert sum(
        issue.code == "DUPLICATE_IDENTIFIER_NOT_PROMOTED"
        for issue in mapped.issues
    ) == 3


def test_all_fields_have_one_evidence_and_future_date_is_fatal() -> None:
    mapped = _map(synthetic_public_fund_row())
    evidence_rows = records(mapped, "evidence.evidence_record")

    assert len(evidence_rows) == 75
    assert {item["locator_column"] for item in evidence_rows} == set(
        SPEC.expected_columns
    )
    assert all(item["locator_sheet"] == "data" for item in evidence_rows)
    assert all(item["mapping_version"] == "2" for item in evidence_rows)
    assert all(item["vintage_date"] == date(2026, 8, 24) for item in evidence_rows)

    future = _map(synthetic_public_fund_row() | {"fd_daily_bas_dt": "20260825"})
    assert future.disposition == "quarantined"
    assert future.issues[0].column == "fd_daily_bas_dt"
    assert future.issues[0].code == "AFTER_CUTOFF_SOURCE_VALUE"
    assert future.issues[0].severity == "fatal"

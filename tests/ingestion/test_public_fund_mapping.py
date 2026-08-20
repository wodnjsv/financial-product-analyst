from collections.abc import Mapping
from decimal import Decimal

import pytest

from financial_agent.ingestion.mapping.public_fund import (
    HANDLED_COLUMNS,
    IGNORED_COLUMNS,
    SPEC,
    analyze_repeated_fund_rows,
    map_row,
)


EXPECTED_COLUMNS = (
    "bmrk_eng_nm",
    "bmrk_nm",
    "curr_cd",
    "exchdg_yn",
    "fd_estb_ctry_cd",
    "fd_ivst_rgn_desc",
    "fd_mm18_ern_r",
    "fd_mm1_ern_r",
    "fd_mm3_ern_r",
    "fd_mm6_ern_r",
    "fd_nast_suma",
    "fd_set_pcd",
    "fd_wk1_ern_r",
    "fd_yr1_ern_r",
    "fd_yr2_ern_r",
    "fd_yr3_ern_r",
    "fd_yr5_ern_r",
    "frc_bpr_itm_yn",
    "fss_itm_no",
    "hdge_fd_yn",
    "int_dvd_desc",
    "itm_abrv_nm",
    "itm_eabrv_nm",
    "itm_eng_nm",
    "itm_nm",
    "itm_no",
    "kofia_fd_ccd",
    "ksd_itm_no",
    "mtco_itm_no",
    "ofsfd_yn",
    "or_attr_desc",
    "or_co_xtn_itt_cd",
    "ovrs_fd_desc",
    "pers_corp_desc",
    "pfiv_sale_cntl_tcd",
    "prfd_attr_cd",
    "prvo_fd_desc",
    "prvo_pbff_desc",
    "rptt_ksd_itm_no",
    "sale_yn",
    "std_itm_no",
    "thco_sale_yn",
    "trusc_xtn_itt_cd",
    "zrin_fd_ivst_risk_gcd",
    "zrin_fd_ivst_risk_grd_nm",
)

EXPECTED_METRIC_IDS = {
    "bmrk_eng_nm": "organizer.prfd01n001.benchmark_english_raw",
    "bmrk_nm": "organizer.prfd01n001.benchmark_raw",
    "curr_cd": "organizer.prfd01n001.currency",
    "exchdg_yn": "organizer.prfd01n001.currency_hedged",
    "fd_estb_ctry_cd": (
        "organizer.prfd01n001.establishment_country_code_raw"
    ),
    "fd_ivst_rgn_desc": "organizer.prfd01n001.investment_region",
    "fd_mm18_ern_r": "organizer.prfd01n001.cumulative_return_18m",
    "fd_mm1_ern_r": "organizer.prfd01n001.cumulative_return_1m",
    "fd_mm3_ern_r": "organizer.prfd01n001.cumulative_return_3m",
    "fd_mm6_ern_r": "organizer.prfd01n001.cumulative_return_6m",
    "fd_nast_suma": "organizer.prfd01n001.net_assets",
    "fd_set_pcd": "organizer.prfd01n001.establishment_type_code_raw",
    "fd_wk1_ern_r": "organizer.prfd01n001.cumulative_return_1w",
    "fd_yr1_ern_r": "organizer.prfd01n001.cumulative_return_1y",
    "fd_yr2_ern_r": "organizer.prfd01n001.cumulative_return_2y",
    "fd_yr3_ern_r": "organizer.prfd01n001.cumulative_return_3y",
    "fd_yr5_ern_r": "organizer.prfd01n001.cumulative_return_5y",
    "frc_bpr_itm_yn": "organizer.prfd01n001.foreign_currency_base_price",
    "fss_itm_no": "organizer.prfd01n001.fss_product_id",
    "hdge_fd_yn": "organizer.prfd01n001.is_hedge_fund",
    "int_dvd_desc": "organizer.prfd01n001.interest_dividend_class",
    "itm_abrv_nm": "organizer.prfd01n001.short_name_ko",
    "itm_eabrv_nm": "organizer.prfd01n001.short_name_en",
    "itm_eng_nm": "organizer.prfd01n001.name_en_raw",
    "itm_nm": "organizer.prfd01n001.name",
    "itm_no": "organizer.prfd01n001.product_id",
    "kofia_fd_ccd": "organizer.prfd01n001.kofia_classification_code_raw",
    "ksd_itm_no": "organizer.prfd01n001.ksd_product_id",
    "mtco_itm_no": "organizer.prfd01n001.manager_product_id",
    "ofsfd_yn": "organizer.prfd01n001.is_offshore_fund",
    "or_attr_desc": "organizer.prfd01n001.management_attribute",
    "ovrs_fd_desc": "organizer.prfd01n001.overseas_fund_class",
    "pers_corp_desc": "organizer.prfd01n001.investor_type",
    "pfiv_sale_cntl_tcd": (
        "organizer.prfd01n001.professional_sale_control_code_raw"
    ),
    "prfd_attr_cd": "organizer.prfd01n001.attribute_row_code",
    "prvo_fd_desc": "organizer.prfd01n001.private_fund_detail",
    "prvo_pbff_desc": "organizer.prfd01n001.public_private_class",
    "sale_yn": "organizer.prfd01n001.sale_status",
    "std_itm_no": "organizer.prfd01n001.standard_product_id",
    "thco_sale_yn": "organizer.prfd01n001.sold_by_provider",
    "trusc_xtn_itt_cd": (
        "organizer.prfd01n001.trustee_institution_code_raw"
    ),
    "zrin_fd_ivst_risk_gcd": "organizer.prfd01n001.risk_grade_code",
    "zrin_fd_ivst_risk_grd_nm": "organizer.prfd01n001.risk_grade_name",
}


def synthetic_public_fund_row() -> dict[str, object]:
    return {
        "bmrk_eng_nm": "SYN BENCHMARK 100",
        "bmrk_nm": "Synthetic Benchmark 100",
        "curr_cd": "KRW",
        "exchdg_yn": "Y",
        "fd_estb_ctry_cd": "410",
        "fd_ivst_rgn_desc": "SYN-GLOBAL",
        "fd_mm18_ern_r": Decimal("18.10"),
        "fd_mm1_ern_r": Decimal("1.10"),
        "fd_mm3_ern_r": Decimal("3.10"),
        "fd_mm6_ern_r": Decimal("6.10"),
        "fd_nast_suma": Decimal("50000000000"),
        "fd_set_pcd": "SYN-SET-10",
        "fd_wk1_ern_r": Decimal("0.30"),
        "fd_yr1_ern_r": Decimal("12.00"),
        "fd_yr2_ern_r": Decimal("24.00"),
        "fd_yr3_ern_r": Decimal("36.00"),
        "fd_yr5_ern_r": Decimal("60.00"),
        "frc_bpr_itm_yn": "0",
        "fss_itm_no": "SYN-FSS-001",
        "hdge_fd_yn": "0",
        "int_dvd_desc": "SYN-DIVIDEND-CLASS",
        "itm_abrv_nm": "SYN 공모펀드",
        "itm_eabrv_nm": "SYN-PUBLIC-FUND",
        "itm_eng_nm": "Synthetic Public Fund Class A",
        "itm_nm": "  합성  공모펀드 클래스 A ",
        "itm_no": "SYN-FUND-001",
        "kofia_fd_ccd": "SYN-KOFIA-CODE",
        "ksd_itm_no": "SYN-KSD-001",
        "mtco_itm_no": "SYN-MANAGER-PRODUCT-001",
        "ofsfd_yn": "0",
        "or_attr_desc": "SYN-EQUITY",
        "or_co_xtn_itt_cd": "SYN-MANAGER-001",
        "ovrs_fd_desc": "SYN-OVERSEAS",
        "pers_corp_desc": "SYN-INDIVIDUAL",
        "pfiv_sale_cntl_tcd": "SYN-CONTROL-00",
        "prfd_attr_cd": "SYN-ATTR-A",
        "prvo_fd_desc": "SYN-NOT-PRIVATE",
        "prvo_pbff_desc": "SYN-PUBLIC",
        "rptt_ksd_itm_no": "SYN-REP-001",
        "sale_yn": "판매중",
        "std_itm_no": "SYN-STANDARD-001",
        "thco_sale_yn": "Y",
        "trusc_xtn_itt_cd": "SYN-TRUSTEE-001",
        "zrin_fd_ivst_risk_gcd": "2",
        "zrin_fd_ivst_risk_grd_nm": "SYN-RISK-GRADE-2",
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


def map_group(rows: list[Mapping[str, object]], start_row: int = 7):
    analysis = analyze_repeated_fund_rows(rows)
    return analysis, [
        map_row(start_row + offset, row, repeat_analysis=analysis)
        for offset, row in enumerate(rows)
    ]


def test_all_45_fields_are_handled_without_ignored_columns() -> None:
    assert SPEC.expected_columns == EXPECTED_COLUMNS
    assert SPEC.natural_key == (
        "itm_no",
        "prfd_attr_cd",
        "zrin_fd_ivst_risk_gcd",
    )
    assert HANDLED_COLUMNS == frozenset(EXPECTED_COLUMNS)
    assert IGNORED_COLUMNS == {}


def test_repeated_rows_emit_common_facts_once_and_each_attribute_once() -> None:
    first = synthetic_public_fund_row()
    second = first | {"prfd_attr_cd": "SYN-ATTR-B"}
    analysis, (mapped_first, mapped_second) = map_group([first, second])

    assert analysis.canonical_record_keys == {
        "SYN-FUND-001": "SYN-FUND-001|SYN-ATTR-A|2"
    }
    assert analysis.conflicting_columns == {}
    assert records(mapped_first, "catalog.product")
    assert not records(mapped_second, "catalog.product")
    first_aum = observation(mapped_first, "fd_nast_suma")
    assert first_aum["numeric_value"] == Decimal("50000000000")
    assert not any(
        item["metric_id"] == EXPECTED_METRIC_IDS["fd_nast_suma"]
        for item in records(mapped_second, "observation.observation_record")
    )
    first_attribute = observation(mapped_first, "prfd_attr_cd")
    second_attribute = observation(mapped_second, "prfd_attr_cd")
    assert first_attribute["text_value"] == "SYN-ATTR-A"
    assert second_attribute["text_value"] == "SYN-ATTR-B"
    assert first_attribute["observation_id"] != second_attribute["observation_id"]
    assert evidence(mapped_first, "fd_nast_suma")["locator_row"] == 7
    assert evidence(mapped_first, "prfd_attr_cd")["locator_row"] == 7
    assert evidence(mapped_second, "prfd_attr_cd")["locator_row"] == 8
    assert mapped_first.disposition == "accepted"
    assert mapped_second.disposition == "accepted"


def test_repeated_value_conflict_selects_no_value_and_preserves_all_locations() -> None:
    first = synthetic_public_fund_row()
    second = first | {
        "prfd_attr_cd": "SYN-ATTR-B",
        "fd_nast_suma": Decimal("53000000000"),
    }
    analysis, (mapped_first, mapped_second) = map_group([first, second], 20)

    assert analysis.conflicting_columns == {
        "SYN-FUND-001": frozenset({"fd_nast_suma"})
    }
    first_aum = observation(mapped_first, "fd_nast_suma")
    second_aum = observation(mapped_second, "fd_nast_suma")
    assert first_aum["observation_id"] == second_aum["observation_id"]
    assert first_aum["value_status"] == "unknown"
    assert second_aum["value_status"] == "unknown"
    assert first_aum["numeric_value"] is None
    assert second_aum["numeric_value"] is None
    first_evidence = evidence(mapped_first, "fd_nast_suma")
    second_evidence = evidence(mapped_second, "fd_nast_suma")
    assert first_evidence["evidence_id"] != second_evidence["evidence_id"]
    assert first_evidence["locator_row"] == 20
    assert second_evidence["locator_row"] == 21
    assert first_evidence["raw_value_repr"] == "50000000000"
    assert second_evidence["raw_value_repr"] == "53000000000"
    assert {
        (issue.column, issue.code)
        for mapped in (mapped_first, mapped_second)
        for issue in mapped.issues
    } >= {("fd_nast_suma", "SOURCE_VALUE_CONFLICT")}


def test_valid_representative_points_to_share_class_without_aum_aggregation() -> None:
    first = synthetic_public_fund_row()
    second = first | {
        "itm_no": "SYN-FUND-002",
        "itm_nm": "Synthetic Public Fund Class B",
        "prfd_attr_cd": "SYN-ATTR-B",
        "fd_nast_suma": Decimal("30000000000"),
        "fss_itm_no": "SYN-FSS-002",
        "ksd_itm_no": "SYN-KSD-002",
        "mtco_itm_no": "SYN-MANAGER-PRODUCT-002",
        "std_itm_no": "SYN-STANDARD-002",
    }
    _, mapped_rows = map_group([first, second])

    product_entities = [
        item
        for mapped in mapped_rows
        for item in records(mapped, "catalog.entity")
        if item["entity_type"] == "product"
    ]
    assert len(product_entities) == 4
    representative_relations = [
        relation(mapped, "hasShareClass") for mapped in mapped_rows
    ]
    representative_id = representative_relations[0]["subject_id"]
    assert {item["subject_id"] for item in representative_relations} == {
        representative_id
    }
    assert len({item["object_id"] for item in representative_relations}) == 2
    aum_observations = [
        observation(mapped, "fd_nast_suma") for mapped in mapped_rows
    ]
    assert {item["numeric_value"] for item in aum_observations} == {
        Decimal("50000000000"),
        Decimal("30000000000"),
    }
    assert all(item["entity_id"] != representative_id for item in aum_observations)
    assert not any(
        "representative" in str(item["metric_id"])
        and "aum" in str(item["metric_id"])
        for mapped in mapped_rows
        for item in records(mapped, "observation.observation_record")
    )


@pytest.mark.parametrize("sentinel", ["KR0000000000", "000000000000", None])
def test_representative_sentinel_creates_no_group(sentinel: object) -> None:
    _, (mapped,) = map_group(
        [synthetic_public_fund_row() | {"rptt_ksd_itm_no": sentinel}]
    )

    assert len(
        [
            item
            for item in records(mapped, "catalog.entity")
            if item["entity_type"] == "product"
        ]
    ) == 1
    assert not any(
        item["predicate_id"] == "hasShareClass"
        for item in records(mapped, "relation.relation_record")
    )


def test_identifiers_aliases_and_source_local_manager_are_bounded() -> None:
    _, (mapped,) = map_group([synthetic_public_fund_row()])

    assert [
        (item["scheme"], item["identifier_value"], item["is_primary"])
        for item in records(mapped, "catalog.identifier")
    ] == [
        ("PRFD_ITM_NO", "SYN-FUND-001", True),
        ("FSS_FUND", "SYN-FSS-001", False),
        ("KSD_PRODUCT", "SYN-KSD-001", False),
        (
            "MANAGER_SCOPED_PRODUCT:SYN-MANAGER-001",
            "SYN-MANAGER-PRODUCT-001",
            False,
        ),
        ("PRFD_STANDARD_PRODUCT", "SYN-STANDARD-001", False),
    ]
    assert {item["alias_text"] for item in records(mapped, "catalog.alias")} == {
        "SYN 공모펀드",
        "SYN-PUBLIC-FUND",
        "Synthetic Public Fund Class A",
    }
    manager = next(
        item
        for item in records(mapped, "catalog.entity")
        if item["entity_type"] == "institution"
    )
    assert manager["canonical_name"] == "SYN-MANAGER-001"
    assert relation(mapped, "managedBy")["object_id"] == manager["entity_id"]


def test_classification_sale_currency_risk_and_returns_are_preserved() -> None:
    _, (mapped,) = map_group([synthetic_public_fund_row()])

    assert records(mapped, "catalog.product")[0]["primary_currency"] == "KRW"
    assert observation(mapped, "prvo_pbff_desc")["text_value"] == "SYN-PUBLIC"
    assert observation(mapped, "sale_yn")["text_value"] == "판매중"
    assert observation(mapped, "or_attr_desc")["text_value"] == "SYN-EQUITY"
    assert observation(mapped, "fd_ivst_rgn_desc")["text_value"] == "SYN-GLOBAL"
    assert observation(mapped, "exchdg_yn")["boolean_value"] is True
    assert observation(mapped, "frc_bpr_itm_yn")["boolean_value"] is False
    assert observation(mapped, "zrin_fd_ivst_risk_gcd")["text_value"] == "2"
    return_columns = {
        "fd_wk1_ern_r",
        "fd_mm1_ern_r",
        "fd_mm3_ern_r",
        "fd_mm6_ern_r",
        "fd_mm18_ern_r",
        "fd_yr1_ern_r",
        "fd_yr2_ern_r",
        "fd_yr3_ern_r",
        "fd_yr5_ern_r",
    }
    assert all(
        observation(mapped, column)["numeric_value"] is not None
        for column in return_columns
    )
    assert all(
        observation(mapped, column)["period_end"] is None
        for column in return_columns
    )


def test_every_answerable_field_has_exact_evidence_and_one_origin() -> None:
    _, (mapped,) = map_group([synthetic_public_fund_row()], 30)

    evidence_rows = records(mapped, "evidence.evidence_record")
    observation_origins = records(mapped, "evidence.evidence_observation_origin")
    relation_origins = records(mapped, "evidence.evidence_relation_origin")
    assert {item["locator_column"] for item in evidence_rows} == HANDLED_COLUMNS
    assert len(evidence_rows) == 45
    assert len(observation_origins) == 43
    assert len(relation_origins) == 2
    assert {item["evidence_id"] for item in evidence_rows} == {
        item["evidence_id"] for item in observation_origins + relation_origins
    }
    assert len(records(mapped, "observation.metric_definition")) == 43
    aum = evidence(mapped, "fd_nast_suma")
    assert aum["normalized_value"] == {
        "type": "decimal",
        "value": "50000000000",
    }
    assert aum["currency"] == "KRW"
    assert aum["applicable_date"] is None
    assert aum["vintage_date"].isoformat() == "2026-07-11"
    assert aum["locator_record_key"] == "SYN-FUND-001|SYN-ATTR-A|2"
    assert aum["locator_row"] == 30


def test_benchmark_text_never_creates_index_relation() -> None:
    _, (mapped,) = map_group(
        [
            synthetic_public_fund_row()
            | {
                "bmrk_eng_nm": "123456",
                "bmrk_nm": "SYN INDEX A 60% + SYN INDEX B 40%",
            }
        ]
    )

    assert observation(mapped, "bmrk_eng_nm")["value_status"] == "unknown"
    assert observation(mapped, "bmrk_nm")["text_value"] == (
        "SYN INDEX A 60% + SYN INDEX B 40%"
    )
    assert not any(
        item["entity_type"] == "index"
        for item in records(mapped, "catalog.entity")
    )
    assert not any(
        item["predicate_id"] == "tracksIndex"
        for item in records(mapped, "relation.relation_record")
    )


def test_risk_null_unknown_attribute_and_missing_hedge_remain_limited() -> None:
    row = synthetic_public_fund_row() | {
        "exchdg_yn": None,
        "or_attr_desc": "06",
        "zrin_fd_ivst_risk_gcd": "NULL",
        "zrin_fd_ivst_risk_grd_nm": None,
    }
    _, (mapped,) = map_group([row])

    assert mapped.disposition == "limited"
    assert observation(mapped, "exchdg_yn")["value_status"] == "missing"
    assert observation(mapped, "or_attr_desc")["value_status"] == "unknown"
    assert observation(mapped, "zrin_fd_ivst_risk_gcd")["value_status"] == (
        "missing"
    )
    assert observation(mapped, "zrin_fd_ivst_risk_grd_nm")["value_status"] == (
        "missing"
    )


def test_return_outlier_is_not_corrected_but_raw_evidence_is_retained() -> None:
    _, (mapped,) = map_group(
        [synthetic_public_fund_row() | {"fd_yr3_ern_r": Decimal("1500.25")}]
    )

    result = observation(mapped, "fd_yr3_ern_r")
    assert result["value_status"] == "unknown"
    assert result["numeric_value"] is None
    outlier_evidence = evidence(mapped, "fd_yr3_ern_r")
    assert outlier_evidence["normalized_value"] == {"type": "null", "value": None}
    assert outlier_evidence["raw_value_repr"] == "1500.25"
    assert ("fd_yr3_ern_r", "RETURN_OUTLIER") in {
        (issue.column, issue.code) for issue in mapped.issues
    }


def test_optional_identifier_sentinels_and_duplicates_are_not_promoted() -> None:
    first = synthetic_public_fund_row() | {
        "fss_itm_no": "000000000000",
        "ksd_itm_no": "KR0000000000",
    }
    second = synthetic_public_fund_row() | {
        "itm_no": "SYN-FUND-002",
        "itm_nm": "Synthetic Public Fund Class B",
        "prfd_attr_cd": "SYN-ATTR-B",
        "fss_itm_no": "000000000000",
        "ksd_itm_no": "KR0000000000",
        "std_itm_no": "SYN-STANDARD-001",
    }
    _, mapped_rows = map_group([first, second])

    for mapped in mapped_rows:
        schemes = {item["scheme"] for item in records(mapped, "catalog.identifier")}
        assert "FSS_FUND" not in schemes
        assert "KSD_PRODUCT" not in schemes
        assert "PRFD_STANDARD_PRODUCT" not in schemes
        assert observation(mapped, "fss_itm_no")["value_status"] == "placeholder"


@pytest.mark.parametrize("column", ["itm_no", "prfd_attr_cd"])
def test_missing_required_raw_key_part_quarantines_without_records(column: str) -> None:
    row = synthetic_public_fund_row() | {column: " "}
    analysis = analyze_repeated_fund_rows([row])
    mapped = map_row(40, row, repeat_analysis=analysis)

    assert mapped.disposition == "quarantined"
    assert not any(mapped.records_by_table.values())
    assert mapped.issues[0].column == column
    assert mapped.issues[0].code == "MISSING_NATURAL_KEY"


def test_binary_float_failure_reports_column_without_value_leak() -> None:
    row = synthetic_public_fund_row() | {"fd_nast_suma": 3.141592}
    analysis = analyze_repeated_fund_rows([row])
    mapped = map_row(41, row, repeat_analysis=analysis)

    assert mapped.disposition == "quarantined"
    assert not any(mapped.records_by_table.values())
    assert mapped.issues[0].column == "fd_nast_suma"
    assert mapped.issues[0].code == "INVALID_SOURCE_VALUE"
    assert "3.141592" not in repr(mapped.issues)

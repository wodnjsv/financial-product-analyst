from collections.abc import Mapping
from datetime import date
from decimal import Decimal

import pytest

from financial_agent.ingestion.mapping.domestic_bond import (
    HANDLED_COLUMNS,
    IGNORED_COLUMNS,
    SPEC,
    map_row,
)


EXPECTED_COLUMNS = (
    "PD_NO",
    "PD_EXG_MKT",
    "PD_NM",
    "PD_ABRV_NM",
    "PD_ENG_NM",
    "PD_ABRV_ENG_NM",
    "PD_CTRY_CD",
    "PD_PBCM",
    "STD_PD_MCLS_NM",
    "STD_PD_SCLS_NM",
    "BD_KND",
    "CURR_CD",
    "ISU_BAL_AMT",
    "ISU_DT",
    "MAT_DT",
    "SRFC_IRT",
    "PD_EVCO_CRD_GRD",
    "PD_RISK_GCD",
    "PD_STD_INFO_UPDATE",
    "BUY_YIELD",
    "CORP_PRETAX_YIELD",
    "CORP_AFTER_TAX_YIELD",
    "AFTER_TAX_YIELD",
    "PREF_TAX_YIELD",
    "AVG_ANNUAL_TAX_YIELD",
    "DEPO_EQUIV_YIELD_154",
    "BUYABLE_QUANTITY",
    "REMAINING_DAYS",
    "DUR",
    "COV",
    "NDY_DUR",
    "NDY_COV",
    "EVAL_PRICE",
    "APPLIED_YIELD",
    "DIRTY",
    "NDY_EVAL_PRICE",
    "NDY_APPLIED_YIELD",
    "NDY_DIRTY",
    "CRD_GRD",
    "CRD_GRD_DT",
)

EXPECTED_METRIC_IDS = {
    "PD_NO": "organizer.prbd01n001.product_id",
    "PD_EXG_MKT": "organizer.prbd01n001.exchange_market_type",
    "PD_NM": "organizer.prbd01n001.name_ko",
    "PD_ABRV_NM": "organizer.prbd01n001.short_name_ko",
    "PD_ENG_NM": "organizer.prbd01n001.name_en",
    "PD_ABRV_ENG_NM": "organizer.prbd01n001.short_name_en",
    "PD_CTRY_CD": "organizer.prbd01n001.country_code_raw",
    "STD_PD_MCLS_NM": "organizer.prbd01n001.product_major_class",
    "STD_PD_SCLS_NM": "organizer.prbd01n001.product_subclass",
    "BD_KND": "organizer.prbd01n001.bond_kind",
    "CURR_CD": "organizer.prbd01n001.currency",
    "ISU_BAL_AMT": "organizer.prbd01n001.issue_balance",
    "ISU_DT": "organizer.prbd01n001.issue_date",
    "MAT_DT": "organizer.prbd01n001.maturity_date",
    "SRFC_IRT": "organizer.prbd01n001.coupon_rate",
    "PD_EVCO_CRD_GRD": "organizer.prbd01n001.credit_grade_raw",
    "PD_RISK_GCD": "organizer.prbd01n001.risk_grade_code",
    "PD_STD_INFO_UPDATE": (
        "organizer.prbd01n001.standard_info_updated_on"
    ),
    "BUY_YIELD": "organizer.prbd01n001.buy_yield",
    "CORP_PRETAX_YIELD": "organizer.prbd01n001.corporate_pretax_yield",
    "CORP_AFTER_TAX_YIELD": "organizer.prbd01n001.corporate_after_tax_yield",
    "AFTER_TAX_YIELD": "organizer.prbd01n001.after_tax_yield",
    "PREF_TAX_YIELD": "organizer.prbd01n001.preferential_tax_yield",
    "DEPO_EQUIV_YIELD_154": (
        "organizer.prbd01n001.deposit_equivalent_yield_154"
    ),
    "BUYABLE_QUANTITY": "organizer.prbd01n001.buyable_quantity",
    "DUR": "organizer.prbd01n001.duration_raw",
    "COV": "organizer.prbd01n001.convexity_raw",
    "NDY_DUR": "organizer.prbd01n001.next_business_day_duration_raw",
    "NDY_COV": "organizer.prbd01n001.next_business_day_convexity_raw",
    "EVAL_PRICE": "organizer.prbd01n001.evaluation_price_raw",
    "APPLIED_YIELD": "organizer.prbd01n001.applied_yield_raw",
    "DIRTY": "organizer.prbd01n001.dirty_price_raw",
    "NDY_EVAL_PRICE": (
        "organizer.prbd01n001.next_business_day_evaluation_price_raw"
    ),
    "NDY_APPLIED_YIELD": (
        "organizer.prbd01n001.next_business_day_applied_yield_raw"
    ),
    "NDY_DIRTY": "organizer.prbd01n001.next_business_day_dirty_price_raw",
    "CRD_GRD": "organizer.prbd01n001.credit_grade_representative",
    "CRD_GRD_DT": "organizer.prbd01n001.credit_grade_as_of",
}


def synthetic_bond_row() -> dict[str, object]:
    return {
        "PD_NO": "SYN-BOND-001",
        "PD_EXG_MKT": "SYN-MARKET",
        "PD_NM": "  합성\u3000채권 1 ",
        "PD_ABRV_NM": "합성채1",
        "PD_ENG_NM": "Synthetic Bond 1",
        "PD_ABRV_ENG_NM": "SYN BOND 1",
        "PD_CTRY_CD": "SYN",
        "PD_PBCM": "  합성\u3000발행기관 ",
        "STD_PD_MCLS_NM": "SYN-MAJOR",
        "STD_PD_SCLS_NM": "SYN-SUB",
        "BD_KND": "SYN-KIND",
        "CURR_CD": "KRW",
        "ISU_BAL_AMT": Decimal("1000000"),
        "ISU_DT": 20250115,
        "MAT_DT": 20300115,
        "SRFC_IRT": Decimal("3.25"),
        "PD_EVCO_CRD_GRD": "SYN-AA,SYN-AA",
        "PD_RISK_GCD": 2,
        "PD_STD_INFO_UPDATE": 20260601,
        "BUY_YIELD": Decimal("3.40"),
        "CORP_PRETAX_YIELD": Decimal("3.30"),
        "CORP_AFTER_TAX_YIELD": Decimal("2.80"),
        "AFTER_TAX_YIELD": Decimal("2.75"),
        "PREF_TAX_YIELD": Decimal("2.90"),
        "AVG_ANNUAL_TAX_YIELD": 0,
        "DEPO_EQUIV_YIELD_154": Decimal("3.25"),
        "BUYABLE_QUANTITY": Decimal("100"),
        "REMAINING_DAYS": 1300,
        "DUR": Decimal("2.10"),
        "COV": Decimal("0.30"),
        "NDY_DUR": Decimal("2.09"),
        "NDY_COV": Decimal("0.29"),
        "EVAL_PRICE": Decimal("10050"),
        "APPLIED_YIELD": Decimal("3.20"),
        "DIRTY": Decimal("10100"),
        "NDY_EVAL_PRICE": Decimal("10048"),
        "NDY_APPLIED_YIELD": Decimal("3.21"),
        "NDY_DIRTY": Decimal("10099"),
        "CRD_GRD": "SYN-AA",
        "CRD_GRD_DT": 20260531,
    }


def records(
    mapped,
    table: str,
) -> tuple[Mapping[str, object], ...]:
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


def test_all_40_fields_are_handled_or_ignored_exactly_once() -> None:
    expected = set(EXPECTED_COLUMNS)

    assert SPEC.expected_columns == EXPECTED_COLUMNS
    assert HANDLED_COLUMNS.isdisjoint(IGNORED_COLUMNS)
    assert HANDLED_COLUMNS | set(IGNORED_COLUMNS) == expected
    assert len(HANDLED_COLUMNS) == 38
    assert IGNORED_COLUMNS == {
        "AVG_ANNUAL_TAX_YIELD": "UNUSABLE_ALL_ZERO_SERIES",
        "REMAINING_DAYS": "NO_TRUSTED_TIME_BASIS",
    }


def test_valid_row_creates_product_security_identifier_and_local_issuer() -> None:
    mapped = map_row(7, synthetic_bond_row())

    assert mapped.disposition == "accepted"
    entities = records(mapped, "catalog.entity")
    assert len(entities) == 2
    product_entity = next(item for item in entities if item["entity_type"] == "product")
    issuer_entity = next(
        item for item in entities if item["entity_type"] == "institution"
    )
    assert product_entity["canonical_name"] == "합성 채권 1"
    assert issuer_entity["canonical_name"] == "합성 발행기관"

    assert records(mapped, "catalog.product") == (
        {
            "entity_id": product_entity["entity_id"],
            "product_family": "domestic_bond",
            "primary_currency": "KRW",
        },
    )
    assert records(mapped, "catalog.security") == (
        {
            "entity_id": product_entity["entity_id"],
            "security_kind": "bond",
            "ticker_display": None,
            "isin_display": None,
        },
    )
    assert records(mapped, "catalog.institution") == (
        {"entity_id": issuer_entity["entity_id"], "institution_kind": "issuer"},
    )

    identifier = records(mapped, "catalog.identifier")[0]
    assert identifier["entity_id"] == product_entity["entity_id"]
    assert identifier["scheme"] == "PRBD_PD_NO"
    assert identifier["identifier_value"] == "SYN-BOND-001"
    assert identifier["is_primary"] is True

    relation = records(mapped, "relation.relation_record")[0]
    assert relation["subject_id"] == product_entity["entity_id"]
    assert relation["predicate_id"] == "issuedBy"
    assert relation["object_id"] == issuer_entity["entity_id"]
    assert all(item["predicate_id"] != "availability" for item in records(
        mapped, "relation.relation_record"
    ))


def test_product_and_issuer_ids_are_stable_but_source_local() -> None:
    first = map_row(2, synthetic_bond_row())
    repeated = map_row(300, synthetic_bond_row())
    changed = map_row(3, synthetic_bond_row() | {"PD_NO": "SYN-BOND-002"})

    first_product = records(first, "catalog.product")[0]["entity_id"]
    repeated_product = records(repeated, "catalog.product")[0]["entity_id"]
    changed_product = records(changed, "catalog.product")[0]["entity_id"]
    assert first_product == repeated_product
    assert first_product != changed_product


def test_valid_row_maps_dates_numeric_text_and_limited_metrics() -> None:
    mapped = map_row(7, synthetic_bond_row())

    assert observation(mapped, "ISU_DT")["date_value"] == date(2025, 1, 15)
    assert observation(mapped, "MAT_DT")["date_value"] == date(2030, 1, 15)
    assert observation(mapped, "SRFC_IRT")["numeric_value"] == Decimal("3.25")
    assert observation(mapped, "BUY_YIELD")["numeric_value"] == Decimal("3.40")
    assert observation(mapped, "EVAL_PRICE")["numeric_value"] == Decimal(
        "10050"
    )
    assert observation(mapped, "DUR")["numeric_value"] == Decimal("2.10")
    assert observation(mapped, "CRD_GRD")["text_value"] == "SYN-AA"
    assert observation(mapped, "CRD_GRD")["applicable_date"] == date(
        2026, 5, 31
    )
    buyable = observation(mapped, "BUYABLE_QUANTITY")
    assert buyable["numeric_value"] == Decimal("100")
    assert buyable["unit"] == "source_defined_quantity"
    assert not any(
        item["metric_id"].endswith("remaining_days")
        for item in records(mapped, "observation.observation_record")
    )


def test_every_answerable_field_has_exact_evidence_and_one_origin() -> None:
    mapped = map_row(7, synthetic_bond_row())

    evidence_rows = records(mapped, "evidence.evidence_record")
    observation_origins = records(mapped, "evidence.evidence_observation_origin")
    relation_origins = records(mapped, "evidence.evidence_relation_origin")
    assert {item["locator_column"] for item in evidence_rows} == HANDLED_COLUMNS
    assert len(evidence_rows) == 38
    assert len(observation_origins) == 37
    assert len(relation_origins) == 1
    assert {item["evidence_id"] for item in evidence_rows} == {
        item["evidence_id"] for item in observation_origins + relation_origins
    }

    coupon = evidence(mapped, "SRFC_IRT")
    assert coupon["source_id"]
    assert coupon["predicate_id"] == "organizer.prbd01n001.coupon_rate"
    assert coupon["value_or_object_id"] == {"type": "decimal", "value": "3.25"}
    assert coupon["normalized_value"] == {"type": "decimal", "value": "3.25"}
    assert coupon["unit"] == "percentage_point"
    assert coupon["applicable_date"] is None
    assert coupon["vintage_date"] == date(2026, 7, 11)
    assert coupon["locator_type"] == "tabular"
    assert coupon["locator_uri_or_object_key"] == SPEC.data_file_name
    assert coupon["locator_record_key"] == "SYN-BOND-001"
    assert coupon["locator_sheet"] == "datarows"
    assert coupon["locator_row"] == 7
    assert coupon["locator_column"] == "SRFC_IRT"
    assert coupon["raw_value_repr"] == "3.25"
    assert coupon["parser_version"] == "1"
    assert coupon["mapping_version"] == "1"
    assert coupon["cutoff_status"] == "eligible"

    maturity = evidence(mapped, "MAT_DT")
    assert maturity["normalized_value"] == {
        "type": "date",
        "value": "2030-01-15",
    }
    assert maturity["applicable_date"] == date(2030, 1, 15)
    assert maturity["cutoff_status"] == "eligible"


def test_sentinels_remain_missing_placeholder_unknown_or_zero() -> None:
    source = synthetic_bond_row() | {
        "CURR_CD": "000",
        "ISU_DT": 0,
        "MAT_DT": "99991231",
        "PD_STD_INFO_UPDATE": 20190101,
        "BUY_YIELD": "NULL",
        "BUYABLE_QUANTITY": 0,
        "NDY_EVAL_PRICE": 0,
        "NDY_DIRTY": Decimal("0"),
        "CRD_GRD_DT": 0,
    }

    mapped = map_row(8, source)

    assert mapped.disposition == "limited"
    assert records(mapped, "catalog.product")[0]["primary_currency"] is None
    assert observation(mapped, "CURR_CD")["value_status"] == "unknown"
    assert observation(mapped, "ISU_DT")["value_status"] == "placeholder"
    assert observation(mapped, "MAT_DT")["value_status"] == "placeholder"
    assert observation(mapped, "BUY_YIELD")["value_status"] == "missing"
    assert observation(mapped, "BUYABLE_QUANTITY")["value_status"] == "zero"
    assert observation(mapped, "BUYABLE_QUANTITY")["numeric_value"] == 0
    assert observation(mapped, "NDY_EVAL_PRICE")["value_status"] == "unknown"
    assert observation(mapped, "NDY_DIRTY")["value_status"] == "unknown"
    assert observation(mapped, "PD_STD_INFO_UPDATE")["date_value"] == date(
        2019, 1, 1
    )
    assert evidence(mapped, "PD_STD_INFO_UPDATE")["cutoff_status"] == "eligible"
    assert evidence(mapped, "BUY_YIELD")["value_or_object_id"] == {
        "type": "null",
        "value": None,
    }
    assert evidence(mapped, "BUY_YIELD")["normalized_value"] == {
        "type": "null",
        "value": None,
    }
    assert evidence(mapped, "BUY_YIELD")["raw_value_repr"] == "NULL"
    assert evidence(mapped, "MAT_DT")["normalized_value"]["type"] == "null"
    assert all(
        issue.code
        in {
            "SOURCE_VALUE_MISSING",
            "SOURCE_VALUE_PLACEHOLDER",
            "SOURCE_ZERO_SEMANTICS_UNKNOWN",
            "UNDEFINED_CURRENCY_CODE",
        }
        for issue in mapped.issues
    )


def test_each_limited_field_is_counted_once() -> None:
    mapped = map_row(8, synthetic_bond_row() | {"CURR_CD": "000"})

    assert mapped.disposition == "limited"
    assert [(issue.column, issue.code) for issue in mapped.issues] == [
        ("CURR_CD", "UNDEFINED_CURRENCY_CODE")
    ]


def test_missing_natural_key_quarantines_the_row_without_records() -> None:
    mapped = map_row(9, synthetic_bond_row() | {"PD_NO": "  "})

    assert mapped.disposition == "quarantined"
    assert not any(mapped.records_by_table.values())
    assert len(mapped.issues) == 1
    assert mapped.issues[0].column == "PD_NO"
    assert mapped.issues[0].code == "MISSING_NATURAL_KEY"
    assert mapped.issues[0].severity == "quarantined"


def test_binary_float_parse_failure_quarantines_without_leaking_value() -> None:
    mapped = map_row(10, synthetic_bond_row() | {"SRFC_IRT": 3.141592})

    assert mapped.disposition == "quarantined"
    assert not any(mapped.records_by_table.values())
    assert len(mapped.issues) == 1
    assert mapped.issues[0].column == "SRFC_IRT"
    assert mapped.issues[0].code == "INVALID_SOURCE_VALUE"
    assert "3.141592" not in repr(mapped.issues)


def test_invalid_date_reports_the_exact_source_column() -> None:
    mapped = map_row(11, synthetic_bond_row() | {"MAT_DT": "2026-99-99"})

    assert mapped.disposition == "quarantined"
    assert not any(mapped.records_by_table.values())
    assert len(mapped.issues) == 1
    assert mapped.issues[0].column == "MAT_DT"
    assert mapped.issues[0].code == "INVALID_SOURCE_VALUE"
    assert "2026-99-99" not in repr(mapped.issues)


def test_after_cutoff_update_date_is_fatal_but_future_maturity_is_allowed() -> None:
    mapped = map_row(
        12,
        synthetic_bond_row()
        | {
            "MAT_DT": 20350101,
            "PD_STD_INFO_UPDATE": 20260712,
        },
    )

    assert mapped.disposition == "quarantined"
    assert not any(mapped.records_by_table.values())
    assert len(mapped.issues) == 1
    assert mapped.issues[0].column == "PD_STD_INFO_UPDATE"
    assert mapped.issues[0].code == "AFTER_CUTOFF_SOURCE_VALUE"
    assert mapped.issues[0].severity == "fatal"

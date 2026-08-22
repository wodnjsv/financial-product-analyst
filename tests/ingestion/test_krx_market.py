from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from financial_agent.ingestion.mapping.common import stable_id
from financial_agent.ingestion.official import (
    map_krx_etf_daily,
    parse_krx_etf_daily,
    select_latest_eligible_krx_date,
)
from financial_agent.ingestion.official.krx_holdings import KrxEtfProductBinding
from financial_agent.ingestion.sources import SourceVerificationError
from tests.fixtures.official_ingestion import (
    krx_etf_daily_payload,
    official_manifest,
)


def _payload_rows(payload: bytes | None = None) -> list[dict[str, str]]:
    decoded = json.loads((payload or krx_etf_daily_payload()).decode("utf-8"))
    return [dict(row) for row in decoded["OutBlock_1"]]


def _manifest(payload: bytes, *, applicable_date: date = date(2026, 7, 10)):
    return official_manifest(
        source_code="KRX_ETF_DAILY",
        object_name=f"etf-daily-{applicable_date:%Y%m%d}.json",
        payload=payload,
        applicable_date=applicable_date,
    )


def _binding(*, name_matches: bool = True) -> KrxEtfProductBinding:
    return KrxEtfProductBinding(
        product_entity_id=stable_id(
            "product", "PREF01N001", "KR7305080004"
        ),
        organizer_isin="KR7305080004",
        krx_short_code="305080",
        organizer_name="TIGER 미국채10년선물",
        krx_name=(
            "TIGER 미국채10년선물"
            if name_matches
            else "TIGER 미국채10년선물(공식명 변경)"
        ),
        name_matches=name_matches,
    )


def _records(mapped, table: str) -> tuple[dict[str, object], ...]:
    return tuple(
        dict(record)
        for row in mapped
        for record in row.records_by_table[table]
    )


def test_krx_etf_daily_parser_preserves_approved_numeric_text() -> None:
    rows = parse_krx_etf_daily(krx_etf_daily_payload())

    assert len(rows) == 1
    assert rows[0]["BAS_DD"] == "20260710"
    assert rows[0]["TDD_CLSPRC"] == "12345.50"
    assert rows[0]["NAV"] == "12340.25"
    assert type(rows[0]["TDD_CLSPRC"]) is str


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        (lambda rows: rows[0].pop("NAV"), "KRX_ETF_DAILY_SCHEMA_MISMATCH"),
        (
            lambda rows: rows[0].__setitem__("BAS_DD", "2026-07-10"),
            "KRX_ETF_DAILY_SCHEMA_MISMATCH",
        ),
        (
            lambda rows: rows[0].__setitem__("TDD_CLSPRC", "12,345.50"),
            "KRX_ETF_DAILY_VALUE_INVALID",
        ),
        (
            lambda rows: rows[0].__setitem__("NAV", "1e3"),
            "KRX_ETF_DAILY_VALUE_INVALID",
        ),
    ),
)
def test_krx_etf_daily_parser_rejects_schema_and_numeric_drift(
    mutation, code: str
) -> None:
    rows = _payload_rows()
    mutation(rows)

    with pytest.raises(SourceVerificationError) as captured:
        parse_krx_etf_daily(krx_etf_daily_payload(tuple(rows)))

    assert captured.value.code == code
    assert captured.value.__cause__ is None


def test_krx_etf_daily_parser_rejects_duplicate_product_dates() -> None:
    rows = _payload_rows()
    rows.append(dict(rows[0]))

    with pytest.raises(SourceVerificationError) as captured:
        parse_krx_etf_daily(krx_etf_daily_payload(tuple(rows)))

    assert captured.value.code == "KRX_ETF_DAILY_DUPLICATE_OBSERVATION"


def test_latest_eligible_krx_date_selects_friday_before_saturday_cutoff() -> None:
    assert select_latest_eligible_krx_date(
        (date(2026, 7, 13), date(2026, 7, 10)),
        date(2026, 7, 11),
    ) == date(2026, 7, 10)

    with pytest.raises(SourceVerificationError) as captured:
        select_latest_eligible_krx_date(
            (date(2026, 7, 13),), date(2026, 7, 11)
        )
    assert captured.value.code == "KRX_ETF_DAILY_NO_ELIGIBLE_DATE"


def test_krx_market_maps_close_and_nav_to_exact_bound_product() -> None:
    payload = krx_etf_daily_payload()

    mapped = map_krx_etf_daily(
        _manifest(payload),
        parse_krx_etf_daily(payload),
        bindings=(_binding(),),
    )

    assert len(mapped) == 1
    assert {row.disposition for row in mapped} == {"accepted"}
    observations = _records(mapped, "observation.observation_record")
    assert {
        row["metric_id"]: row["numeric_value"] for row in observations
    } == {
        "krx_etf_market_close_krw": Decimal("12345.50"),
        "krx_etf_nav_per_share_krw": Decimal("12340.25"),
    }
    assert {row["entity_id"] for row in observations} == {
        _binding().product_entity_id
    }
    assert {row["applicable_date"] for row in observations} == {
        date(2026, 7, 10)
    }
    assert {row["unit"] for row in observations} == {"KRW"}
    assert {row["currency"] for row in observations} == {"KRW"}
    assert {row["metric_definition_version"] for row in observations} == {
        "1"
    }

    evidence = _records(mapped, "evidence.evidence_record")
    observation_evidence = [
        row for row in evidence if row["evidence_kind"] == "observation"
    ]
    assert {row["locator_column"] for row in observation_evidence} == {
        "TDD_CLSPRC",
        "NAV",
    }
    assert {row["locator_record_key"] for row in observation_evidence} == {
        "305080:20260710"
    }


def test_krx_market_rejects_rows_from_another_date_in_the_same_object() -> None:
    rows = _payload_rows()
    rows.append(
        dict(rows[0])
        | {
            "BAS_DD": "20260713",
            "TDD_CLSPRC": "99999.99",
            "NAV": "99998.99",
        }
    )
    payload = krx_etf_daily_payload(tuple(rows))

    with pytest.raises(SourceVerificationError) as captured:
        map_krx_etf_daily(
            _manifest(payload),
            parse_krx_etf_daily(payload),
            bindings=(_binding(),),
        )

    assert captured.value.code == "KRX_ETF_DAILY_OBJECT_MISMATCH"


def test_krx_market_preserves_missing_nav_without_copying_close() -> None:
    rows = _payload_rows()
    rows[0]["NAV"] = ""
    payload = krx_etf_daily_payload(tuple(rows))

    mapped = map_krx_etf_daily(
        _manifest(payload),
        parse_krx_etf_daily(payload),
        bindings=(_binding(),),
    )
    observations = _records(mapped, "observation.observation_record")
    nav = next(
        row
        for row in observations
        if row["metric_id"] == "krx_etf_nav_per_share_krw"
    )

    assert nav["value_status"] == "unknown"
    assert nav["numeric_value"] is None
    assert nav["reason_code"] == "SOURCE_VALUE_MISSING"


def test_krx_market_keeps_unbound_rows_limited_without_product_facts() -> None:
    rows = _payload_rows()
    rows[0]["ISU_CD"] = "999999"
    rows[0]["ISU_NM"] = "미연결 ETF"
    payload = krx_etf_daily_payload(tuple(rows))

    mapped = map_krx_etf_daily(
        _manifest(payload),
        parse_krx_etf_daily(payload),
        bindings=(_binding(),),
    )

    assert len(mapped) == 1
    assert mapped[0].disposition == "limited"
    assert mapped[0].issues[0].code == "KRX_ETF_DAILY_LINK_BLOCKED"
    assert not _records(mapped, "observation.observation_record")


def test_krx_market_allows_binding_name_drift_as_audit_only() -> None:
    payload = krx_etf_daily_payload()

    mapped = map_krx_etf_daily(
        _manifest(payload),
        parse_krx_etf_daily(payload),
        bindings=(_binding(name_matches=False),),
    )

    assert mapped[0].disposition == "accepted"
    assert len(_records(mapped, "observation.observation_record")) == 2


def test_krx_market_rejects_manifest_date_different_from_selected_rows() -> None:
    payload = krx_etf_daily_payload()

    with pytest.raises(SourceVerificationError) as captured:
        map_krx_etf_daily(
            _manifest(payload, applicable_date=date(2026, 7, 9)),
            parse_krx_etf_daily(payload),
            bindings=(_binding(),),
        )

    assert captured.value.code == "KRX_ETF_DAILY_OBJECT_MISMATCH"

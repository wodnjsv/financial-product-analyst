from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from financial_agent.ingestion.mapping.common import stable_id
from financial_agent.ingestion.official.identity import (
    IdentityCandidate,
    OfficialIdentityIndex,
)
from financial_agent.ingestion.official.krx_holdings import (
    KrxEtfProductBinding,
    build_krx_etf_product_bindings,
    map_krx_holding_snapshot,
    parse_krx_etf_pdf_csv,
)
from financial_agent.ingestion.sources import SourceVerificationError
from tests.fixtures.official_ingestion import (
    krx_etf_pdf_payload,
    official_manifest,
)


def _manifest(payload: bytes):
    return official_manifest(
        source_code="KRX_ETF_PDF",
        object_name="305080_20260710.csv",
        payload=payload,
        applicable_date=date(2026, 7, 10),
        media_type="text/csv",
    )


def _binding() -> KrxEtfProductBinding:
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


def _security_index() -> OfficialIdentityIndex:
    return OfficialIdentityIndex(
        exact_entries=(
            (
                IdentityCandidate("KRX_SHORT_ISSUE_CODE", "005930"),
                "security-samsung",
            ),
        )
    )


def _records(mapped, table: str) -> tuple[dict[str, object], ...]:
    return tuple(dict(row) for row in mapped.records_by_table[table])


def test_krx_pdf_parser_preserves_signed_values_and_missing_markers() -> None:
    rows = parse_krx_etf_pdf_csv(krx_etf_pdf_payload())

    assert len(rows) == 4
    assert rows[2]["시가총액"] == "-100"
    assert rows[2]["시가총액 구성비중"] == "-1.00"
    assert rows[1]["시가총액"] == "-"


def test_krx_pdf_parser_rejects_header_drift() -> None:
    payload = krx_etf_pdf_payload().replace(
        "시가총액 구성비중".encode("cp949"), "비중".encode("cp949")
    )

    with pytest.raises(SourceVerificationError) as captured:
        parse_krx_etf_pdf_csv(payload)

    assert captured.value.code == "KRX_ETF_PDF_SCHEMA_MISMATCH"
    assert captured.value.__cause__ is None


def test_isin_derived_binding_uses_exact_historical_krx_code() -> None:
    result = build_krx_etf_product_bindings(
        organizer_rows=(
            {
                "pd_grp_no": "ETF",
                "pd_itm_no": "KR7305080004",
                "pd_abrv_nm": "TIGER 미국채10년선물",
            },
            {
                "pd_grp_no": "ETF",
                "pd_itm_no": "KR",
                "pd_abrv_nm": "malformed",
            },
            {
                "pd_grp_no": "ETF",
                "pd_itm_no": "KR7453540007",
                "pd_abrv_nm": "inactive",
            },
            {
                "pd_grp_no": "ETN",
                "pd_itm_no": "KRG760000148",
                "pd_abrv_nm": "excluded ETN",
            },
        ),
        daily_rows=(
            {
                "종목코드": "305080",
                "종목명": "TIGER 미국채10년선물",
            },
            {
                "종목코드": "0210A0",
                "종목명": "KRX only ETF",
            },
        ),
        applicable_date=date(2026, 7, 10),
    )

    assert result.organizer_etf_count == 3
    assert result.invalid_isin_count == 1
    assert result.unresolved_organizer_count == 2
    assert result.unmatched_krx_count == 1
    assert result.name_drift_count == 0
    assert result.bindings == (_binding(),)


def test_isin_derived_binding_allows_name_drift_only_as_audit() -> None:
    result = build_krx_etf_product_bindings(
        organizer_rows=(
            {
                "pd_grp_no": "ETF",
                "pd_itm_no": "KR7284430006",
                "pd_abrv_nm": "KODEX 200미국채혼합",
            },
        ),
        daily_rows=(
            {
                "종목코드": "284430",
                "종목명": "KODEX 200미국채혼합50",
            },
        ),
        applicable_date=date(2026, 7, 10),
    )

    assert len(result.bindings) == 1
    assert result.bindings[0].krx_short_code == "284430"
    assert result.bindings[0].name_matches is False
    assert result.name_drift_count == 1


def test_isin_derived_binding_rejects_a_different_historical_date() -> None:
    with pytest.raises(SourceVerificationError) as captured:
        build_krx_etf_product_bindings(
            organizer_rows=(),
            daily_rows=(),
            applicable_date=date(2026, 7, 11),
        )

    assert captured.value.code == "KRX_ETF_BINDING_DATE_MISMATCH"


@pytest.mark.parametrize("duplicate_side", ("organizer", "krx"))
def test_isin_derived_binding_rejects_duplicate_identity_axes(
    duplicate_side: str,
) -> None:
    organizer = [
        {
            "pd_grp_no": "ETF",
            "pd_itm_no": "KR7305080004",
            "pd_abrv_nm": "TIGER 미국채10년선물",
        }
    ]
    daily = [
        {
            "종목코드": "305080",
            "종목명": "TIGER 미국채10년선물",
        }
    ]
    (organizer if duplicate_side == "organizer" else daily).append(
        dict((organizer if duplicate_side == "organizer" else daily)[0])
    )

    with pytest.raises(SourceVerificationError) as captured:
        build_krx_etf_product_bindings(
            organizer_rows=organizer,
            daily_rows=daily,
            applicable_date=date(2026, 7, 10),
        )

    assert captured.value.code == "KRX_ETF_BINDING_CONFLICT"


def test_holdings_map_relations_values_summary_and_bounded_coverage() -> None:
    payload = krx_etf_pdf_payload()
    mapped = map_krx_holding_snapshot(
        _manifest(payload),
        parse_krx_etf_pdf_csv(payload),
        binding=_binding(),
        security_index=_security_index(),
    )

    relations = _records(mapped, "relation.relation_record")
    observations = _records(mapped, "observation.observation_record")
    evidence = _records(mapped, "evidence.evidence_record")

    assert mapped.disposition == "limited"
    assert len(relations) == 3
    assert {row["predicate_id"] for row in relations} == {"holdsSecurity"}
    assert "security-samsung" in {row["object_id"] for row in relations}
    assert not any(
        row["canonical_name"] == "설정현금액"
        for row in _records(mapped, "catalog.entity")
    )
    assert any(
        row["metric_id"] == "krx_etf_creation_cash_amount_krw"
        and row["numeric_value"] == Decimal("1400")
        and row["entity_id"] == _binding().product_entity_id
        for row in observations
    )
    assert any(
        row["metric_id"] == "krx_etf_holding_market_cap_krw"
        and row["numeric_value"] == Decimal("-100")
        for row in observations
    )
    assert any(
        row["metric_id"] == "krx_etf_holding_weight_pct"
        and row["numeric_value"] == Decimal("-1.00")
        for row in observations
    )
    scopes = [row for row in evidence if row["evidence_kind"] == "query_scope"]
    assert len(scopes) == 1
    assert scopes[0]["raw_value_repr"] == "PARTIALLY_COVERED"
    assert scopes[0]["scope_completeness"] == "bounded_unknown"


def test_holding_missing_numeric_values_stay_unknown_not_zero() -> None:
    payload = krx_etf_pdf_payload()
    mapped = map_krx_holding_snapshot(
        _manifest(payload),
        parse_krx_etf_pdf_csv(payload),
        binding=_binding(),
        security_index=_security_index(),
    )

    observations = _records(mapped, "observation.observation_record")
    future_market_cap = next(
        row
        for row in observations
        if row["metric_id"] == "krx_etf_holding_market_cap_krw"
        and row["relation_id"]
        == next(
            relation["relation_id"]
            for relation in _records(mapped, "relation.relation_record")
            if relation["object_id"] != "security-samsung"
            and any(
                entity["entity_id"] == relation["object_id"]
                and entity["canonical_name"].startswith("US 10YR")
                for entity in _records(mapped, "catalog.entity")
            )
        )
    )
    assert future_market_cap["value_status"] == "unknown"
    assert future_market_cap["numeric_value"] is None
    assert future_market_cap["reason_code"] == "SOURCE_VALUE_MISSING"


def test_repeated_source_lots_are_preserved_without_aggregation() -> None:
    repeated = {
        "종목코드": "TYU6",
        "구성종목명": "US 10YR NOTE FUT (CBOT) SEPT 2026",
        "주식수(계약수)": "1.00",
        "평가금액": "250",
        "시가총액": "250",
        "시가총액 구성비중": "5.00",
    }
    payload = krx_etf_pdf_payload((repeated, repeated))
    mapped = map_krx_holding_snapshot(
        _manifest(payload),
        parse_krx_etf_pdf_csv(payload),
        binding=_binding(),
        security_index=_security_index(),
    )

    relations = _records(mapped, "relation.relation_record")
    assert len(relations) == 2
    assert relations[0]["relation_id"] != relations[1]["relation_id"]
    assert relations[0]["object_id"] == relations[1]["object_id"]


def test_zero_holding_value_is_preserved_as_zero() -> None:
    payload = krx_etf_pdf_payload(
        (
            {
                "종목코드": "005930",
                "구성종목명": "삼성전자",
                "주식수(계약수)": "0",
                "평가금액": "0",
                "시가총액": "0",
                "시가총액 구성비중": "0",
            },
        )
    )
    mapped = map_krx_holding_snapshot(
        _manifest(payload),
        parse_krx_etf_pdf_csv(payload),
        binding=_binding(),
        security_index=_security_index(),
    )

    assert all(
        row["value_status"] == "zero" and row["numeric_value"] == 0
        for row in _records(mapped, "observation.observation_record")
    )


def test_conflicting_holding_identity_fails_closed() -> None:
    payload = krx_etf_pdf_payload()
    conflicting_index = OfficialIdentityIndex(
        exact_entries=(
            (
                IdentityCandidate("KRX_SHORT_ISSUE_CODE", "005930"),
                "security-a",
            ),
            (
                IdentityCandidate("KRX_SHORT_ISSUE_CODE", "005930"),
                "security-b",
            ),
        )
    )

    with pytest.raises(SourceVerificationError) as captured:
        map_krx_holding_snapshot(
            _manifest(payload),
            parse_krx_etf_pdf_csv(payload),
            binding=_binding(),
            security_index=conflicting_index,
        )

    assert captured.value.code == "KRX_ETF_HOLDING_IDENTITY_CONFLICT"
    assert captured.value.__cause__ is None


def test_empty_official_pdf_is_not_covered() -> None:
    payload = krx_etf_pdf_payload(())
    mapped = map_krx_holding_snapshot(
        _manifest(payload),
        parse_krx_etf_pdf_csv(payload),
        binding=_binding(),
        security_index=_security_index(),
    )

    assert mapped.disposition == "limited"
    assert not _records(mapped, "relation.relation_record")
    scope = next(
        row
        for row in _records(mapped, "evidence.evidence_record")
        if row["evidence_kind"] == "query_scope"
    )
    assert scope["raw_value_repr"] == "NOT_COVERED"
    assert scope["scope_completeness"] == "bounded_unknown"


def test_holdings_map_rejects_after_cutoff_and_wrong_product_object() -> None:
    payload = krx_etf_pdf_payload()
    manifest = _manifest(payload)

    with pytest.raises(SourceVerificationError) as cutoff_error:
        map_krx_holding_snapshot(
            replace(manifest, applicable_date=date(2026, 8, 25)),
            parse_krx_etf_pdf_csv(payload),
            binding=_binding(),
            security_index=_security_index(),
        )
    assert cutoff_error.value.code == "OFFICIAL_CUTOFF_VIOLATION"

    wrong_object = replace(
        manifest,
        objects=(
            replace(manifest.objects[0], object_name="999999_20260710.csv"),
        ),
    )
    with pytest.raises(SourceVerificationError) as object_error:
        map_krx_holding_snapshot(
            wrong_object,
            parse_krx_etf_pdf_csv(payload),
            binding=_binding(),
            security_index=_security_index(),
        )
    assert object_error.value.code == "KRX_ETF_PDF_OBJECT_MISMATCH"

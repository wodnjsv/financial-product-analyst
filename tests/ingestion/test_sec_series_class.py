from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from financial_agent.ingestion.official.identity import IdentityCandidate
from financial_agent.ingestion.official.sec_series_class import (
    build_sec_series_class_index,
    parse_sec_series_class,
)
from financial_agent.ingestion.sources import SourceVerificationError
from tests.fixtures.official_ingestion import (
    official_manifest,
    sec_series_class_payload,
)


def _manifest(payload: bytes):
    return official_manifest(
        source_code="SEC_SERIES_CLASS_20260601",
        object_name="series-class.csv",
        payload=payload,
        applicable_date=date(2026, 6, 1),
        published_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        available_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        media_type="text/csv",
    )


def test_sec_series_class_parser_preserves_the_six_approved_fields() -> None:
    payload = sec_series_class_payload()

    rows = parse_sec_series_class(payload)

    assert rows == (
        {
            "CIK": "0000123456",
            "Series ID": "S000000001",
            "Series Name": "Synthetic ETF Series",
            "Class ID": "C000000001",
            "Class Name": "Synthetic ETF Class",
            "Class Ticker": "SYNX",
        },
    )


def test_sec_series_class_parser_rejects_header_drift() -> None:
    payload = sec_series_class_payload().replace(b"Class Ticker", b"Ticker", 1)

    with pytest.raises(SourceVerificationError) as captured:
        parse_sec_series_class(payload)

    assert captured.value.code == "SEC_SERIES_CLASS_SCHEMA_MISMATCH"
    assert captured.value.__cause__ is None


def test_sec_series_class_parser_rejects_a_header_only_report() -> None:
    header_only = sec_series_class_payload(())

    with pytest.raises(SourceVerificationError) as captured:
        parse_sec_series_class(header_only)

    assert captured.value.code == "SEC_SERIES_CLASS_SCHEMA_MISMATCH"


def test_cik_and_ticker_resolve_to_the_same_series_as_official_ids() -> None:
    payload = sec_series_class_payload()
    index = build_sec_series_class_index(_manifest(payload), parse_sec_series_class(payload))

    compound = index.resolve_compound_product(
        "SEC_CIK_CLASS_TICKER", ("123456", "synx")
    )
    by_series = index.resolve_product(
        (IdentityCandidate("SEC_SERIES_ID", "S000000001"),)
    )
    by_class = index.resolve_product(
        (IdentityCandidate("SEC_CLASS_ID", "C000000001"),)
    )

    assert compound.status == by_series.status == by_class.status == "exact"
    assert compound.entity_id == by_series.entity_id == by_class.entity_id


def test_ticker_without_cik_never_resolves() -> None:
    payload = sec_series_class_payload()
    index = build_sec_series_class_index(_manifest(payload), parse_sec_series_class(payload))

    resolved = index.resolve_product((IdentityCandidate("TICKER", "SYNX"),))

    assert resolved.status == "unresolved"
    assert resolved.issue_code == "NO_EXACT_IDENTITY"


def test_duplicate_class_id_fails_the_whole_snapshot() -> None:
    payload = sec_series_class_payload(
        (
            {
                "CIK": "0000123456",
                "Series ID": "S000000001",
                "Series Name": "Synthetic Series One",
                "Class ID": "C000000001",
                "Class Name": "Synthetic Class One",
                "Class Ticker": "SYNX",
            },
            {
                "CIK": "0000654321",
                "Series ID": "S000000002",
                "Series Name": "Synthetic Series Two",
                "Class ID": "C000000001",
                "Class Name": "Synthetic Class Two",
                "Class Ticker": "SYNY",
            },
        )
    )

    with pytest.raises(SourceVerificationError) as captured:
        build_sec_series_class_index(_manifest(payload), parse_sec_series_class(payload))

    assert captured.value.code == "SEC_SERIES_CLASS_DUPLICATE_CLASS_ID"


def test_same_cik_ticker_for_two_series_is_a_resolution_conflict() -> None:
    payload = sec_series_class_payload(
        (
            {
                "CIK": "0000123456",
                "Series ID": "S000000001",
                "Series Name": "Synthetic Series One",
                "Class ID": "C000000001",
                "Class Name": "Synthetic Class One",
                "Class Ticker": "SYNX",
            },
            {
                "CIK": "0000123456",
                "Series ID": "S000000002",
                "Series Name": "Synthetic Series Two",
                "Class ID": "C000000002",
                "Class Name": "Synthetic Class Two",
                "Class Ticker": "SYNX",
            },
        )
    )
    index = build_sec_series_class_index(_manifest(payload), parse_sec_series_class(payload))

    resolved = index.resolve_compound_product(
        "SEC_CIK_CLASS_TICKER", ("123456", "SYNX")
    )

    assert resolved.status == "conflict"
    assert resolved.issue_code == "IDENTITY_KEY_CONFLICT"


def test_same_cik_ticker_for_two_classes_in_one_series_is_still_conflict() -> None:
    payload = sec_series_class_payload(
        (
            {
                "CIK": "0000123456",
                "Series ID": "S000000001",
                "Series Name": "Synthetic Series",
                "Class ID": "C000000001",
                "Class Name": "Synthetic Class One",
                "Class Ticker": "SYNX",
            },
            {
                "CIK": "0000123456",
                "Series ID": "S000000001",
                "Series Name": "Synthetic Series",
                "Class ID": "C000000002",
                "Class Name": "Synthetic Class Two",
                "Class Ticker": "SYNX",
            },
        )
    )
    index = build_sec_series_class_index(_manifest(payload), parse_sec_series_class(payload))

    resolved = index.resolve_compound_product(
        "SEC_CIK_CLASS_TICKER", ("123456", "SYNX")
    )

    assert resolved.status == "conflict"
    assert resolved.issue_code == "IDENTITY_KEY_CONFLICT"

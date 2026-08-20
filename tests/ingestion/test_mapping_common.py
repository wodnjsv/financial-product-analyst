from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from financial_agent.ingestion.mapping.common import (
    classify_value,
    make_record_hash,
    normalize_name,
    parse_decimal,
    parse_tristate,
    parse_yyyymmdd,
    stable_id,
)


def test_stable_id_uses_kind_source_and_natural_key_only() -> None:
    assert stable_id("product", "PRBD01N001", "SYN-BOND-001") == (
        "a0d3a713-47c9-5d65-b748-a5096aa30855"
    )


def test_source_local_institution_ids_do_not_merge_matching_names() -> None:
    normalized = normalize_name("한국\u3000 기관")

    assert stable_id("institution", "PRBD01N001", normalized) == (
        "5d127224-f3fb-5177-9aec-ae0ca7d53679"
    )
    assert stable_id("institution", "PREF01N001", normalized) == (
        "0520faf7-999b-5780-80b6-6d14cd9063a4"
    )


def test_normalize_name_applies_nfkc_and_collapses_whitespace() -> None:
    assert normalize_name("ＡＢＣ\u3000 삼성\n전자 ") == "ABC 삼성 전자"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("  ", None),
        (7, Decimal("7")),
        (" 1.2500 ", Decimal("1.2500")),
        (Decimal("1E+2"), Decimal("1E+2")),
    ],
)
def test_parse_decimal_preserves_decimal_arithmetic(
    raw: object,
    expected: Decimal | None,
) -> None:
    assert parse_decimal(raw) == expected


@pytest.mark.parametrize("raw", [1.25, True, "NaN", Decimal("Infinity")])
def test_parse_decimal_rejects_binary_float_boolean_and_non_finite_values(
    raw: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        parse_decimal(raw)


def test_parse_yyyymmdd_accepts_exact_calendar_dates() -> None:
    sentinels = frozenset({"0", "99991231", "NULL"})

    assert parse_yyyymmdd(" 20260711 ", sentinels=sentinels) == date(
        2026, 7, 11
    )
    assert parse_yyyymmdd(20260615, sentinels=sentinels) == date(2026, 6, 15)


@pytest.mark.parametrize("raw", [None, "", 0, "99991231", " NULL "])
def test_parse_yyyymmdd_does_not_turn_sentinels_into_dates(raw: object) -> None:
    assert parse_yyyymmdd(
        raw,
        sentinels=frozenset({"0", "99991231", "NULL"}),
    ) is None


@pytest.mark.parametrize("raw", [20260230, "2026-07-11", 20260711.0, True])
def test_parse_yyyymmdd_rejects_invalid_or_ambiguous_inputs(raw: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        parse_yyyymmdd(raw, sentinels=frozenset())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(" Ｙ ", True), ("N", False), (1, True), (0, False)],
)
def test_parse_tristate_uses_only_explicit_true_and_false_values(
    raw: object,
    expected: bool,
) -> None:
    assert parse_tristate(
        raw,
        true_values=frozenset({"Y", "1"}),
        false_values=frozenset({"N", "0"}),
    ) is expected


@pytest.mark.parametrize("raw", [None, "", "unknown"])
def test_parse_tristate_does_not_turn_missing_or_unknown_into_false(
    raw: object,
) -> None:
    assert parse_tristate(
        raw,
        true_values=frozenset({"Y", "1"}),
        false_values=frozenset({"N", "0"}),
    ) is None


@pytest.mark.parametrize("raw", [None, "", "  ", " NULL "])
def test_classify_value_keeps_missing_values_distinct_from_zero(
    raw: object,
) -> None:
    assert classify_value(
        raw,
        missing_values=frozenset({None, "", "NULL"}),
        placeholder_values=frozenset(),
        zero_is_value=True,
    ) == ("missing", None, "SOURCE_VALUE_MISSING")


def test_classify_value_marks_configured_text_as_placeholder() -> None:
    assert classify_value(
        "  지수\u3000정보 없음 ",
        missing_values=frozenset({None, "", "NULL"}),
        placeholder_values=frozenset({"지수 정보 없음"}),
        zero_is_value=True,
    ) == ("placeholder", None, "SOURCE_VALUE_PLACEHOLDER")


def test_classify_value_marks_meaningful_numeric_zero_explicitly() -> None:
    assert classify_value(
        0,
        missing_values=frozenset({None, "", "NULL"}),
        placeholder_values=frozenset(),
        zero_is_value=True,
    ) == ("zero", 0, None)


def test_classify_value_does_not_publish_zero_with_unknown_semantics() -> None:
    assert classify_value(
        Decimal("0"),
        missing_values=frozenset({None, "", "NULL"}),
        placeholder_values=frozenset(),
        zero_is_value=False,
    ) == ("unknown", None, "SOURCE_ZERO_SEMANTICS_UNKNOWN")


def test_classify_value_preserves_false_and_normalizes_present_text() -> None:
    common = {
        "missing_values": frozenset({None, "", "NULL"}),
        "placeholder_values": frozenset(),
        "zero_is_value": True,
    }

    assert classify_value(False, **common) == ("present", False, None)
    assert classify_value(" Ａ\u3000 상품 ", **common) == (
        "present",
        "A 상품",
        None,
    )


def test_make_record_hash_is_typed_canonical_and_excludes_created_at() -> None:
    payload = {
        "optional": None,
        "name": "상품 A",
        "as_of": date(2026, 7, 11),
        "amount": Decimal("1.00"),
        "created_at": datetime(2026, 8, 20, tzinfo=UTC),
    }

    assert make_record_hash(payload) == (
        "0b5ddf88bd5812baa037ed5d9f2586043c51d44e6e6eed50efbe13e70d285f01"
    )
    assert make_record_hash(payload) == make_record_hash(
        payload | {"created_at": datetime(2027, 1, 1, tzinfo=UTC)}
    )
    assert make_record_hash(payload) != make_record_hash(
        payload | {"amount": "1"}
    )

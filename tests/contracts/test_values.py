import json
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from financial_agent.contracts.values import (
    BooleanValue,
    ContractValue,
    DateTimeValue,
    DateValue,
    DecimalValue,
    IntegerValue,
    NullValue,
    StringValue,
    TupleValue,
    decode_contract_value,
    encode_contract_value,
)

CONTRACT_VALUE_ADAPTER = TypeAdapter(ContractValue)
DECIMAL_PATTERN = (
    r"^(?:0|-?[1-9][0-9]*|-?(?:0|[1-9][0-9]*)\.[0-9]*[1-9])$"
)


@pytest.mark.parametrize(
    ("native", "expected_type", "expected_wire"),
    [
        (None, NullValue, {"type": "null", "value": None}),
        (
            "2026-07-11",
            StringValue,
            {"type": "string", "value": "2026-07-11"},
        ),
        (5, IntegerValue, {"type": "integer", "value": 5}),
        (Decimal("1.00"), DecimalValue, {"type": "decimal", "value": "1"}),
        (False, BooleanValue, {"type": "boolean", "value": False}),
        (
            date(2026, 7, 11),
            DateValue,
            {"type": "date", "value": "2026-07-11"},
        ),
        (
            datetime(2026, 8, 17, tzinfo=UTC),
            DateTimeValue,
            {"type": "datetime", "value": "2026-08-17T00:00:00Z"},
        ),
    ],
)
def test_scalar_round_trip_preserves_native_type(
    native: object,
    expected_type: type[object],
    expected_wire: dict[str, object],
) -> None:
    encoded = encode_contract_value(native)  # type: ignore[arg-type]

    assert isinstance(encoded, expected_type)
    assert encoded.model_dump(mode="json") == expected_wire

    restored = CONTRACT_VALUE_ADAPTER.validate_json(encoded.model_dump_json())
    decoded = decode_contract_value(restored)
    assert type(decoded) is type(native)
    assert decoded == native


def test_boolean_is_not_encoded_as_integer() -> None:
    encoded = encode_contract_value(True)

    assert isinstance(encoded, BooleanValue)
    assert not isinstance(encoded, IntegerValue)


def test_datetime_is_not_encoded_as_date() -> None:
    encoded = encode_contract_value(datetime(2026, 8, 17, tzinfo=UTC))

    assert isinstance(encoded, DateTimeValue)
    assert not isinstance(encoded, DateValue)


def test_mixed_tuple_keeps_one_tag_per_item() -> None:
    native = (date(2026, 7, 11), "2026-07-11", Decimal("1.0"), "1.0")

    encoded = encode_contract_value(native)

    assert isinstance(encoded, TupleValue)
    assert [item.type for item in encoded.items] == [
        "date",
        "string",
        "decimal",
        "string",
    ]
    restored = CONTRACT_VALUE_ADAPTER.validate_json(encoded.model_dump_json())
    assert decode_contract_value(restored) == (
        date(2026, 7, 11),
        "2026-07-11",
        Decimal("1"),
        "1.0",
    )


@pytest.mark.parametrize(
    ("source", "canonical"),
    [
        ("0", "0"),
        ("-0", "0"),
        ("1.0", "1"),
        ("1.00", "1"),
        ("1E+0", "1"),
        ("1E+3", "1000"),
        ("0.00100", "0.001"),
        ("-123.4500", "-123.45"),
        ("12345678901234567890.1234500", "12345678901234567890.12345"),
    ],
)
def test_decimal_python_values_emit_one_canonical_string(
    source: str,
    canonical: str,
) -> None:
    encoded = encode_contract_value(Decimal(source))

    assert isinstance(encoded, DecimalValue)
    assert encoded.model_dump(mode="json") == {
        "type": "decimal",
        "value": canonical,
    }
    restored = CONTRACT_VALUE_ADAPTER.validate_json(encoded.model_dump_json())
    assert decode_contract_value(restored) == Decimal(canonical)


@pytest.mark.parametrize(
    "wire_value",
    ["-0", "00", "01", "1.0", "1.20", ".5", "1.", "1E+3", "NaN", "Infinity"],
)
def test_decimal_json_rejects_noncanonical_strings(wire_value: str) -> None:
    payload = {"type": "decimal", "value": wire_value}

    with pytest.raises(ValidationError):
        CONTRACT_VALUE_ADAPTER.validate_json(json.dumps(payload))


def test_decimal_json_rejects_numeric_payload() -> None:
    with pytest.raises(ValidationError):
        CONTRACT_VALUE_ADAPTER.validate_json(
            json.dumps({"type": "decimal", "value": 1})
        )


@pytest.mark.parametrize("source", ["NaN", "Infinity", "-Infinity"])
def test_decimal_python_rejects_nonfinite_values(source: str) -> None:
    with pytest.raises(ValueError):
        encode_contract_value(Decimal(source))


def test_decimal_schema_requires_canonical_string() -> None:
    value_schema = DecimalValue.model_json_schema(mode="validation")["properties"][
        "value"
    ]

    assert value_schema["type"] == "string"
    assert value_schema["pattern"] == DECIMAL_PATTERN


@pytest.mark.parametrize(
    "payload",
    [
        {"value": "missing-tag"},
        {"type": "unknown", "value": "x"},
        {"type": "string", "value": "x", "extra": True},
        {"type": "integer", "value": True},
        {"type": "boolean", "value": 1},
        {"type": "date", "value": "not-a-date"},
        {"type": "datetime", "value": "2026-08-17T09:00:00+09:00"},
    ],
)
def test_tag_and_value_type_must_agree(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CONTRACT_VALUE_ADAPTER.validate_json(json.dumps(payload))


def test_tuple_json_rejects_nested_tuple() -> None:
    payload = {
        "type": "tuple",
        "items": [
            {
                "type": "tuple",
                "items": [{"type": "string", "value": "nested"}],
            }
        ],
    }

    with pytest.raises(ValidationError):
        CONTRACT_VALUE_ADAPTER.validate_json(json.dumps(payload))


@pytest.mark.parametrize("value", [1.5, ["x"], {"value": "x"}])
def test_encoder_rejects_unsupported_native_values(value: object) -> None:
    with pytest.raises(TypeError):
        encode_contract_value(value)  # type: ignore[arg-type]


def test_encoder_rejects_nested_tuple() -> None:
    with pytest.raises(TypeError):
        encode_contract_value((("nested",),))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 8, 17),
        datetime(
            2026,
            8,
            17,
            tzinfo=timezone(timedelta(hours=9)),
        ),
    ],
)
def test_encoder_requires_utc_datetime(value: datetime) -> None:
    with pytest.raises(ValueError):
        encode_contract_value(value)


def test_decoder_rejects_unvalidated_object() -> None:
    with pytest.raises(TypeError):
        decode_contract_value(object())  # type: ignore[arg-type]

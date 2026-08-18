import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationInfo,
    WithJsonSchema,
)

from .base import ContractModel, UtcDateTime, require_utc

DECIMAL_PATTERN = (
    r"^(?:0|-?[1-9][0-9]*|-?(?:0|[1-9][0-9]*)\.[0-9]*[1-9])$"
)


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("decimal value must be finite")

    sign, digits, exponent = value.as_tuple()
    coefficient = list(digits)
    if not any(coefficient):
        return "0"

    while coefficient[-1] == 0:
        coefficient.pop()
        exponent += 1

    text = "".join(str(digit) for digit in coefficient)
    if exponent >= 0:
        text += "0" * exponent
    else:
        point = len(text) + exponent
        if point > 0:
            text = f"{text[:point]}.{text[point:]}"
        else:
            text = f"0.{('0' * -point)}{text}"

    return f"-{text}" if sign else text


def _validate_decimal(value: object, info: ValidationInfo) -> Decimal:
    if info.mode == "json":
        if not isinstance(value, str) or re.fullmatch(DECIMAL_PATTERN, value) is None:
            raise ValueError("decimal JSON value must be a canonical string")
        return Decimal(value)

    if not isinstance(value, Decimal):
        raise ValueError("decimal Python value must be Decimal")
    if not value.is_finite():
        raise ValueError("decimal value must be finite")
    return value


CanonicalDecimal = Annotated[
    Decimal,
    BeforeValidator(_validate_decimal),
    PlainSerializer(_canonical_decimal, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "pattern": DECIMAL_PATTERN},
        mode="validation",
    ),
]


class _TaggedValueModel(ContractModel):
    model_config = ConfigDict(strict=True)


class NullValue(_TaggedValueModel):
    type: Literal["null"]
    value: None


class StringValue(_TaggedValueModel):
    type: Literal["string"]
    value: str


class IntegerValue(_TaggedValueModel):
    type: Literal["integer"]
    value: int


class DecimalValue(_TaggedValueModel):
    type: Literal["decimal"]
    value: CanonicalDecimal


class BooleanValue(_TaggedValueModel):
    type: Literal["boolean"]
    value: bool


class DateValue(_TaggedValueModel):
    type: Literal["date"]
    value: date


class DateTimeValue(_TaggedValueModel):
    type: Literal["datetime"]
    value: UtcDateTime


ScalarValue: TypeAlias = Annotated[
    NullValue
    | StringValue
    | IntegerValue
    | DecimalValue
    | BooleanValue
    | DateValue
    | DateTimeValue,
    Field(discriminator="type"),
]


class TupleValue(_TaggedValueModel):
    type: Literal["tuple"]
    items: tuple[ScalarValue, ...]


ContractValue: TypeAlias = Annotated[
    ScalarValue | TupleValue,
    Field(discriminator="type"),
]
ScalarPrimitive: TypeAlias = str | int | Decimal | bool | date | UtcDateTime | None
ContractPrimitive: TypeAlias = ScalarPrimitive | tuple[ScalarPrimitive, ...]


def _encode_scalar(value: ScalarPrimitive) -> ScalarValue:
    if value is None:
        return NullValue(type="null", value=None)
    if isinstance(value, bool):
        return BooleanValue(type="boolean", value=value)
    if isinstance(value, int):
        return IntegerValue(type="integer", value=value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("decimal value must be finite")
        return DecimalValue(type="decimal", value=value)
    if isinstance(value, datetime):
        return DateTimeValue(type="datetime", value=require_utc(value))
    if isinstance(value, date):
        return DateValue(type="date", value=value)
    if isinstance(value, str):
        return StringValue(type="string", value=value)
    raise TypeError(f"unsupported contract scalar: {type(value).__name__}")


def encode_contract_value(value: ContractPrimitive) -> ContractValue:
    if isinstance(value, tuple):
        return TupleValue(
            type="tuple",
            items=tuple(_encode_scalar(item) for item in value),
        )
    return _encode_scalar(value)


def decode_contract_value(value: ContractValue) -> ContractPrimitive:
    if isinstance(value, NullValue):
        return None
    if isinstance(value, TupleValue):
        return tuple(decode_contract_value(item) for item in value.items)
    if isinstance(
        value,
        (
            StringValue,
            IntegerValue,
            DecimalValue,
            BooleanValue,
            DateValue,
            DateTimeValue,
        ),
    ):
        return value.value
    raise TypeError(f"unsupported tagged contract value: {type(value).__name__}")

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid5

from pydantic import BaseModel

from financial_agent.contracts import canonical_sha256, encode_contract_value


PROJECT_NAMESPACE = UUID("1a967c94-0c0d-53b7-b106-0488da25efa9")


def stable_id(kind: str, source_code: str, natural_key: str) -> str:
    return str(uuid5(PROJECT_NAMESPACE, f"{kind}:{source_code}:{natural_key}"))


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split())


def parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (bool, float)):
        raise TypeError("decimal source value must not be Boolean or binary float")

    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str):
        normalized = normalize_name(value)
        if not normalized:
            return None
        try:
            parsed = Decimal(normalized)
        except InvalidOperation:
            raise ValueError("source value is not a valid decimal") from None
    else:
        raise TypeError("decimal source value has an unsupported type")

    if not parsed.is_finite():
        raise ValueError("decimal source value must be finite")
    return parsed


def parse_yyyymmdd(
    value: object,
    *,
    sentinels: frozenset[str],
) -> date | None:
    if value is None:
        return None
    if isinstance(value, (bool, float)):
        raise TypeError("date source value must not be Boolean or binary float")

    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise ValueError("source value is not a valid YYYYMMDD date")
        normalized = format(value, "f").split(".", 1)[0]
    elif isinstance(value, int):
        normalized = str(value)
    elif isinstance(value, str):
        normalized = normalize_name(value)
    else:
        raise TypeError("date source value has an unsupported type")

    normalized_sentinels = frozenset(normalize_name(item) for item in sentinels)
    if not normalized or normalized in normalized_sentinels:
        return None
    if re.fullmatch(r"[0-9]{8}", normalized) is None:
        raise ValueError("source value is not a valid YYYYMMDD date")

    try:
        return date(
            int(normalized[0:4]),
            int(normalized[4:6]),
            int(normalized[6:8]),
        )
    except ValueError:
        raise ValueError("source value is not a valid YYYYMMDD date") from None


def parse_tristate(
    value: object,
    *,
    true_values: frozenset[str],
    false_values: frozenset[str],
) -> bool | None:
    if value is None:
        return None

    normalized = normalize_name(str(value))
    if not normalized:
        return None

    normalized_true = frozenset(normalize_name(item) for item in true_values)
    normalized_false = frozenset(normalize_name(item) for item in false_values)
    if normalized in normalized_true:
        return True
    if normalized in normalized_false:
        return False
    return None


def _normalized_source_value(value: object) -> object:
    return normalize_name(value) if isinstance(value, str) else value


def classify_value(
    raw: object,
    *,
    missing_values: frozenset[object],
    placeholder_values: frozenset[str],
    zero_is_value: bool,
) -> tuple[str, object | None, str | None]:
    normalized = _normalized_source_value(raw)
    normalized_missing = frozenset(
        _normalized_source_value(value) for value in missing_values
    )
    if normalized in normalized_missing:
        return "missing", None, "SOURCE_VALUE_MISSING"

    normalized_placeholders = frozenset(
        normalize_name(value) for value in placeholder_values
    )
    if isinstance(normalized, str) and normalized in normalized_placeholders:
        return "placeholder", None, "SOURCE_VALUE_PLACEHOLDER"
    if (
        not isinstance(normalized, bool)
        and isinstance(normalized, (int, Decimal))
        and normalized == 0
    ):
        if "0" in normalized_placeholders:
            return "placeholder", None, "SOURCE_VALUE_PLACEHOLDER"
        if zero_is_value:
            return "zero", normalized, None
        return "unknown", None, "SOURCE_ZERO_SEMANTICS_UNKNOWN"

    return "present", normalized, None


def _record_hash_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (Mapping, list)):
        return value
    return encode_contract_value(value).model_dump(mode="json")


def make_record_hash(payload: Mapping[str, object]) -> str:
    canonical_payload = {
        key: _record_hash_value(value)
        for key, value in payload.items()
        if key != "created_at"
    }
    return canonical_sha256(canonical_payload)

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum

import pytest

from financial_agent.contracts.canonical import (
    build_request_key,
    canonical_json_bytes,
    canonical_sha256,
    normalize_question,
)
from financial_agent.contracts.query import FilterSpec
from financial_agent.contracts.values import encode_contract_value


class ExampleStringEnum(str, Enum):
    VALUE = "value"


def test_normalize_question_is_unicode_and_whitespace_stable() -> None:
    assert normalize_question("  삼성전자\u3000ETF\n질문 ") == "삼성전자 ETF 질문"


def test_request_key_changes_with_dataset_version() -> None:
    first = build_request_key("Q-001", "삼성전자 ETF", "2026-07-11-v1", "1.0")
    second = build_request_key("Q-001", "삼성전자 ETF", "2026-07-11-v2", "1.0")
    assert first != second
    assert len(first) == 64


def test_canonical_hash_ignores_mapping_order() -> None:
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256({"a": 1, "b": 2})


def test_tagged_decimal_has_stable_identity_distinct_from_text() -> None:
    first = FilterSpec(
        subtask_id="q1",
        field_id="field-aum",
        operator_id="operator-eq",
        value=encode_contract_value(Decimal("1.00")),
    )
    second = FilterSpec(
        subtask_id="q1",
        field_id="field-aum",
        operator_id="operator-eq",
        value=encode_contract_value(Decimal("1E+0")),
    )
    text = FilterSpec(
        subtask_id="q1",
        field_id="field-aum",
        operator_id="operator-eq",
        value=encode_contract_value("1"),
    )

    assert canonical_sha256(first) == canonical_sha256(second)
    assert canonical_sha256(first) != canonical_sha256(text)
    assert canonical_json_bytes(first) == canonical_json_bytes(
        first.model_dump(mode="json")
    )


@pytest.mark.parametrize(
    "mapping",
    [
        {"value": Decimal("1")},
        {"value": date(2026, 7, 11)},
        {"value": datetime(2026, 8, 17, tzinfo=UTC)},
        {"value": ExampleStringEnum.VALUE},
        {"value": ("one", "two")},
        {"value": 1.5},
        {"value": {"one", "two"}},
        {"value": object()},
        {1: "non-string-key"},
    ],
)
def test_schema_less_mapping_rejects_non_json_native_values(mapping) -> None:
    with pytest.raises(TypeError):
        canonical_json_bytes(mapping)

from __future__ import annotations

import json
from collections.abc import Iterator

import psycopg
import pytest
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter, ValidationError

from financial_agent.contracts import (
    ContractValue,
    decode_contract_value,
    encode_contract_value,
)
from financial_agent.db.preflight import normalize_psycopg_url
from tests.fixtures.db.tagged_value_corpus import (
    INVALID_NATIVE_VALUES,
    INVALID_TAGGED_JSON,
    VALID_TAGGED_VALUES,
)


CONTRACT_VALUE_ADAPTER = TypeAdapter(ContractValue)
TAGGED_VALUE_CHECK = "ck_task6_tagged_value"


@pytest.fixture
def tagged_value_connection(
    migrated_database_url: str,
) -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as connection:
        connection.execute(
            f"""
            CREATE TEMP TABLE task6_tagged_value (
                ordinal integer PRIMARY KEY,
                value jsonb NOT NULL,
                CONSTRAINT {TAGGED_VALUE_CHECK}
                    CHECK (evidence.is_valid_tagged_value(value))
            ) ON COMMIT DROP
            """
        )
        yield connection


@pytest.mark.parametrize(("native", "expected_json"), VALID_TAGGED_VALUES)
def test_shared_corpus_matches_the_frozen_stage01_wire_contract(
    native: object,
    expected_json: dict[str, object],
) -> None:
    encoded = encode_contract_value(native)  # type: ignore[arg-type]

    assert encoded.model_dump(mode="json") == expected_json
    restored = CONTRACT_VALUE_ADAPTER.validate_json(json.dumps(expected_json))
    decoded = decode_contract_value(restored)
    assert type(decoded) is type(native)
    assert decoded == native


@pytest.mark.parametrize("invalid_json", INVALID_TAGGED_JSON)
def test_shared_invalid_json_is_never_a_stage01_json_mode_output(
    invalid_json: object,
) -> None:
    try:
        restored = CONTRACT_VALUE_ADAPTER.validate_json(json.dumps(invalid_json))
    except ValidationError:
        return

    assert restored.model_dump(mode="json") != invalid_json


@pytest.mark.parametrize("invalid_native", INVALID_NATIVE_VALUES)
def test_shared_invalid_native_values_are_rejected_by_the_stage01_encoder(
    invalid_native: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        encode_contract_value(invalid_native)  # type: ignore[arg-type]


@pytest.mark.postgres
def test_every_valid_stage01_shape_survives_the_named_postgresql_check(
    tagged_value_connection: psycopg.Connection,
) -> None:
    for ordinal, (_, expected_json) in enumerate(VALID_TAGGED_VALUES):
        tagged_value_connection.execute(
            "INSERT INTO task6_tagged_value (ordinal, value) VALUES (%s, %s)",
            (ordinal, Jsonb(expected_json)),
        )

    stored = tagged_value_connection.execute(
        "SELECT value FROM task6_tagged_value ORDER BY ordinal"
    ).fetchall()
    assert [row[0] for row in stored] == [
        expected_json for _, expected_json in VALID_TAGGED_VALUES
    ]


@pytest.mark.postgres
@pytest.mark.parametrize("invalid_json", INVALID_TAGGED_JSON)
def test_every_invalid_shape_fails_the_named_postgresql_check(
    tagged_value_connection: psycopg.Connection,
    invalid_json: object,
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation) as error:
        with tagged_value_connection.transaction():
            tagged_value_connection.execute(
                "INSERT INTO task6_tagged_value (ordinal, value) VALUES (1, %s)",
                (Jsonb(invalid_json),),
            )

    assert error.value.diag.constraint_name == TAGGED_VALUE_CHECK

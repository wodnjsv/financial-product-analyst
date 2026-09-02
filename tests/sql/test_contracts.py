from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from financial_agent.contracts.values import decode_contract_value, encode_contract_value
from financial_agent.intent.query_contracts import ProjectionSpecV2
from financial_agent.planning.logical_query import LogicalLookupOperationV2
from financial_agent.sql.compiler import SemanticSqlCompiler
from financial_agent.sql.lowering import ParameterBuilder
from financial_agent.sql.contracts import (
    CompiledSqlRequest,
    PhysicalLoweringRecord,
    SqlParameter,
    compiled_sql_request_id,
    physical_lowering_record_id,
    PhysicalLoweringKind,
)
from .helpers import ACTIVE_DATASET, BINDINGS, PLANNING, POLICIES, make_plan


COMPILER = SemanticSqlCompiler(BINDINGS, POLICIES, PLANNING, ACTIVE_DATASET)


def _request(**updates) -> CompiledSqlRequest:
    plan = make_plan(
        LogicalLookupOperationV2(
            projections=ProjectionSpecV2(field_concept_ids=("aum",))
        )
    )
    request = COMPILER.compile_task(plan, plan.tasks[0].task_id).request
    assert request is not None
    if not updates:
        return request
    payload = request.model_dump()
    payload.update(updates)
    return CompiledSqlRequest.model_validate(payload)


def test_compiled_request_is_strict_frozen_and_content_addressed() -> None:
    request = _request()

    assert request.compiled_request_id == compiled_sql_request_id(request)
    with pytest.raises(ValidationError):
        request.task_id = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="COMPILED_REQUEST_ID_MISMATCH"):
        CompiledSqlRequest.model_validate(
            {**request.model_dump(), "compiled_request_id": "compiled-sql-forged"}
        )


@pytest.mark.parametrize(
    ("statement", "reason"),
    [
        ("SELECT 1; SELECT 2", "SQL_MULTIPLE_STATEMENTS_FORBIDDEN"),
        ("DELETE FROM catalog.product", "SQL_READ_ONLY_STATEMENT_REQUIRED"),
        ("WITH changed AS (UPDATE x SET y=1 RETURNING *) SELECT * FROM changed", "SQL_MUTATION_FORBIDDEN"),
        ("SELECT catalog.product.entity_id INTO stolen FROM catalog.product", "SQL_MUTATION_FORBIDDEN"),
        ("SELECT catalog.product.entity_id FROM catalog.product FOR UPDATE", "SQL_MUTATION_FORBIDDEN"),
        ("COPY catalog.product TO STDOUT", "SQL_READ_ONLY_STATEMENT_REQUIRED"),
        ("SELECT 1 -- hidden", "SQL_COMMENTS_FORBIDDEN"),
        ("SELECT /* hidden */ 1", "SQL_COMMENTS_FORBIDDEN"),
    ],
)
def test_compiled_request_rejects_unsafe_statement(statement: str, reason: str) -> None:
    with pytest.raises(ValidationError, match=reason):
        _request(statement=statement, parameters=())


def test_compiled_request_requires_exact_named_placeholder_ownership() -> None:
    with pytest.raises(ValidationError, match="SQL_MANIFEST_PARAMETER_MISMATCH"):
        _request(parameters=())
    with pytest.raises(ValidationError, match="SQL_MANIFEST_PARAMETER_MISMATCH"):
        _request(
            parameters=(
                SqlParameter(
                    name="different",
                    value=encode_contract_value(Decimal("1")),
                    value_kind="decimal",
                ),
            )
        )


def test_parameter_kind_must_match_tagged_value() -> None:
    with pytest.raises(ValidationError, match="SQL_PARAMETER_VALUE_KIND_MISMATCH"):
        SqlParameter(
            name="value_0",
            value=encode_contract_value(Decimal("1")),
            value_kind="string",
        )


def test_injection_payload_is_data_not_sql() -> None:
    injection = "1); DROP TABLE catalog.product; --"
    parameters = ParameterBuilder()
    placeholder = parameters.bind(injection)

    assert injection not in str(placeholder)
    assert decode_contract_value(parameters.parameters[0].value) == injection


def test_evidence_and_lowering_kinds_are_closed() -> None:
    payload = _request().model_dump()
    payload["lowering_records"][0]["lowering_kind"] = "invented"
    with pytest.raises(ValidationError):
        CompiledSqlRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        CompiledSqlRequest.model_validate(
            {**_request().model_dump(), "evidence_projection_ids": ("invented",)}
        )
    with pytest.raises(ValidationError, match="SQL_MANIFEST_POLICY_OWNERSHIP_MISMATCH"):
        CompiledSqlRequest.model_validate(
            {**_request().model_dump(), "applied_policy_ids": ("invented.v1",)}
        )


def test_compiled_request_rejects_unregistered_physical_identifier() -> None:
    with pytest.raises(ValidationError, match="SQL_MANIFEST_STATEMENT_MISMATCH"):
        _request(statement="SELECT secret FROM private.user_table", parameters=())


@pytest.mark.parametrize(
    "statement",
    (
        'SELECT "private"."user_table"."secret" FROM "private"."user_table"',
        "SELECT catalog.product.invented_column FROM catalog.product",
        "SELECT pg_sleep(10) FROM catalog.product",
        "SELECT catalog.product.entity_id AS invented_alias FROM catalog.product",
        "SELECT catalog.product.entity_id FROM catalog.product WHERE catalog.product.entity_id = 1",
    ),
)
def test_restore_rejects_every_unregistered_identifier_shape(statement: str) -> None:
    with pytest.raises(ValidationError, match="SQL_MANIFEST_STATEMENT_MISMATCH"):
        _request(statement=statement, parameters=())


def test_restore_rejects_an_alternate_safe_looking_registered_cte() -> None:
    with pytest.raises(ValidationError, match="SQL_MANIFEST_STATEMENT_MISMATCH"):
        _request(
            statement=(
                'WITH "representative_product" AS '
                '(SELECT "product"."entity_id" FROM "catalog"."product" AS "product"), '
                '"distribution_values" AS '
                '(SELECT "representative_product"."entity_id" FROM "representative_product") '
                'SELECT "distribution_values"."entity_id" FROM "distribution_values"'
            ),
            parameters=(),
        )

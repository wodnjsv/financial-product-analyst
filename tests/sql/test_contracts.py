from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from financial_agent.contracts.values import decode_contract_value, encode_contract_value
from financial_agent.sql.contracts import (
    CompiledSqlRequest,
    PhysicalLoweringRecord,
    SqlParameter,
    compiled_sql_request_id,
    physical_lowering_record_id,
    PhysicalLoweringKind,
)
from financial_agent.planning.physical_bindings import EvidenceLocator


PIN = "a" * 64


def _request(**updates) -> CompiledSqlRequest:
    kwargs = dict(
        logical_plan_id="logical-query-plan-1",
        task_id="logical-task-1",
        statement=(
            "SELECT catalog.product.entity_id FROM catalog.product "
            "WHERE catalog.product.dataset_version = :dataset_version"
        ),
        parameters=(
            SqlParameter(
                name="dataset_version",
                value=encode_contract_value("dataset-v1"),
                value_kind="string",
            ),
        ),
        lowering_records=(),
        applied_policy_ids=(),
        evidence_projection_ids=(EvidenceLocator.SOURCE_RECORD,),
        compiler_version="semantic-sql-compiler.v1",
        binding_registry_version="semantic-sql-bindings.v1",
        binding_registry_hash=PIN,
        policy_registry_version="semantic-sql-policies.v1",
        policy_registry_hash=PIN,
        contract_registry_version="query-contract-registry.v2",
        contract_registry_hash=PIN,
        operator_registry_version="query-operator-registry.v1",
        operator_registry_hash=PIN,
        semantic_policy_registry_version="query-policy-registry.v1",
        semantic_policy_registry_hash=PIN,
        planning_registry_version="query-plan-registry.v1",
        planning_registry_hash=PIN,
        dataset_version="dataset-v1",
        dataset_pin=PIN,
        population_manifest_id=None,
        population_manifest_hash=None,
    )
    kwargs.update(updates)
    if "lowering_records" not in updates:
        lowering_draft = PhysicalLoweringRecord.model_construct(
            lowering_id="pending",
            semantic_path="scope.product_family_ids",
            binding_id="catalog-product-family.v1",
            lowering_kind=PhysicalLoweringKind.SCOPE,
            value_column=None,
            policy_ids=(),
        )
        kwargs["lowering_records"] = (
            PhysicalLoweringRecord(
                lowering_id=physical_lowering_record_id(lowering_draft),
                semantic_path="scope.product_family_ids",
                binding_id="catalog-product-family.v1",
                lowering_kind=PhysicalLoweringKind.SCOPE,
                value_column=None,
                policy_ids=(),
            ),
        )
    draft = CompiledSqlRequest.model_construct(compiled_request_id="pending", **kwargs)
    return CompiledSqlRequest(
        compiled_request_id=compiled_sql_request_id(draft),
        **kwargs,
    )


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
        ("SELECT 1 -- hidden", "SQL_COMMENTS_FORBIDDEN"),
        ("SELECT /* hidden */ 1", "SQL_COMMENTS_FORBIDDEN"),
    ],
)
def test_compiled_request_rejects_unsafe_statement(statement: str, reason: str) -> None:
    with pytest.raises(ValidationError, match=reason):
        _request(statement=statement, parameters=())


def test_compiled_request_requires_exact_named_placeholder_ownership() -> None:
    with pytest.raises(ValidationError, match="SQL_PARAMETER_MISMATCH"):
        _request(parameters=())
    with pytest.raises(ValidationError, match="SQL_PARAMETER_MISMATCH"):
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
    request = _request(
        statement="SELECT catalog.product.entity_id FROM catalog.product WHERE catalog.product.entity_id = :value_0",
        parameters=(
            SqlParameter(
                name="value_0",
                value=encode_contract_value(injection),
                value_kind="string",
            ),
        ),
    )

    assert injection not in request.statement
    assert decode_contract_value(request.parameters[0].value) == injection


def test_evidence_and_lowering_kinds_are_closed() -> None:
    payload = _request().model_dump()
    payload["lowering_records"][0]["lowering_kind"] = "invented"
    with pytest.raises(ValidationError):
        CompiledSqlRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        CompiledSqlRequest.model_validate(
            {**_request().model_dump(), "evidence_projection_ids": ("invented",)}
        )
    with pytest.raises(ValidationError, match="SQL_POLICY_NOT_REGISTERED"):
        CompiledSqlRequest.model_validate(
            {**_request().model_dump(), "applied_policy_ids": ("invented.v1",)}
        )


def test_compiled_request_rejects_unregistered_physical_identifier() -> None:
    with pytest.raises(ValidationError, match="SQL_IDENTIFIER_NOT_REGISTERED"):
        _request(statement="SELECT secret FROM private.user_table", parameters=())

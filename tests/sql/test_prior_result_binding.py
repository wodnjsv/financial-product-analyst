from __future__ import annotations

import pytest

from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import ResultType, ToolStatus
from financial_agent.contracts.execution import BindingValue, ToolResult
from financial_agent.contracts.values import decode_contract_value, encode_contract_value
from financial_agent.sql.compiler import SemanticSqlRuntimeBinder
from financial_agent.sql.contracts import (
    CompiledSqlRequest,
    DeferredSqlParameter,
    SqlParameter,
)
from financial_agent.sql.executor import ReadOnlySqlRunner, SqlExecutionError

from tests.orchestration.test_semantic_graph import (
    SQL_COMPILER,
    sql_dependency_compilation,
)
from tests.sql.test_executor import FakeEngine


def _dependency_result(plan, binding) -> ToolResult:
    provisional = ToolResult(
        request_key=plan.request_key,
        run_id=plan.run_id,
        dataset_version=plan.dataset_version,
        cutoff_date=plan.cutoff_date,
        producer="executor:rdb_lookup",
        created_at=plan.created_at,
        task_id=f"semantic-execution:{plan.tasks[0].task_id}",
        status=ToolStatus.SUCCESS,
        result_type=ResultType.ROW_SET,
        binding_values=(binding,),
        result_hash="0" * 64,
        latency_ms=1,
    )
    return provisional.model_copy(
        update={
            "result_hash": canonical_sha256(
                provisional, exclude_fields=("result_hash",)
            )
        }
    )


def test_prior_result_compiles_deferred_then_binds_canonical_entity_ids() -> None:
    compilation = sql_dependency_compilation()
    plan = compilation.logical_query_plan
    assert plan is not None
    consumer = plan.tasks[1]
    outcome = SQL_COMPILER.compile_task(plan, consumer.task_id)

    assert outcome.request is not None
    deferred = tuple(
        item
        for item in outcome.request.parameters
        if isinstance(item, DeferredSqlParameter)
    )
    assert len(deferred) == 1
    assert deferred[0].binding_id == "result-set-1"
    assert "product-2" not in outcome.request.statement
    restored = CompiledSqlRequest.model_validate_json(outcome.request.model_dump_json())
    assert restored == outcome.request

    binding = BindingValue(
        binding_name="result-set-1",
        value_type="semantic-result:many",
        value=encode_contract_value(("product-2", "product-1", "product-2")),
    )
    bound = SemanticSqlRuntimeBinder(SQL_COMPILER).bind(
        outcome.request,
        plan,
        (binding,),
        dependency_results=(_dependency_result(plan, binding),),
    )

    assert bound.compiled_request_id != outcome.request.compiled_request_id
    assert bound.render_manifest.manifest_id != outcome.request.render_manifest.manifest_id
    assert all(isinstance(item, SqlParameter) for item in bound.parameters)
    parameter = next(item for item in bound.parameters if item.name == deferred[0].name)
    assert decode_contract_value(parameter.value) == ("product-1", "product-2")
    assert "product-1" not in bound.statement
    assert "product-2" not in bound.statement
    SQL_COMPILER.validate_request_for_execution(bound, plan)


def test_prior_result_runtime_binder_rejects_wrong_cardinality_and_identifier() -> None:
    compilation = sql_dependency_compilation()
    plan = compilation.logical_query_plan
    assert plan is not None
    request = SQL_COMPILER.compile_task(plan, plan.tasks[1].task_id).request
    assert request is not None
    binder = SemanticSqlRuntimeBinder(SQL_COMPILER)

    for value in ("product-1", ("invalid identifier",)):
        binding = BindingValue(
            binding_name="result-set-1",
            value_type="semantic-result:many",
            value=encode_contract_value(value),
        )
        with pytest.raises(ValueError, match="PRIOR_RESULT_BINDING_INVALID"):
            binder.bind(
                request,
                plan,
                (binding,),
                dependency_results=(_dependency_result(plan, binding),),
            )


def test_runtime_binder_rejects_self_rehashed_foreign_dependency() -> None:
    compilation = sql_dependency_compilation()
    plan = compilation.logical_query_plan
    assert plan is not None
    request = SQL_COMPILER.compile_task(plan, plan.tasks[1].task_id).request
    assert request is not None
    binding = BindingValue(
        binding_name="result-set-1",
        value_type="semantic-result:many",
        value=encode_contract_value(("product-1",)),
    )
    forged = _dependency_result(plan, binding).model_copy(
        update={"producer": "executor:keyword_search"}
    )
    forged = forged.model_copy(
        update={
            "result_hash": canonical_sha256(
                forged, exclude_fields=("result_hash",)
            )
        }
    )

    with pytest.raises(ValueError, match="PRIOR_RESULT_DEPENDENCY_INVALID"):
        SemanticSqlRuntimeBinder(SQL_COMPILER).bind(
            request,
            plan,
            (binding,),
            dependency_results=(forged,),
        )


@pytest.mark.asyncio
async def test_runner_rejects_deferred_request_before_database_access() -> None:
    compilation = sql_dependency_compilation()
    plan = compilation.logical_query_plan
    assert plan is not None
    request = SQL_COMPILER.compile_task(plan, plan.tasks[1].task_id).request
    assert request is not None
    engine = FakeEngine([])

    with pytest.raises(SqlExecutionError, match="SQL_DEFERRED_PARAMETER_UNBOUND"):
        await ReadOnlySqlRunner(engine, SQL_COMPILER).execute(request, plan)
    assert engine.connect_count == 0

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import Cardinality, ResultType, ToolStatus
from financial_agent.contracts.execution import BindingValue, ToolResult
from financial_agent.contracts.values import decode_contract_value, encode_contract_value
from financial_agent.intent.query_contract_solver import QueryContractCandidate
from financial_agent.intent.query_contracts import (
    AxisReadiness,
    AxisReadinessRecordV2,
    ContractReadiness,
    ContractReadinessRecordV2,
)
from financial_agent.planning.contracts import CompilationRoute
from financial_agent.planning.semantic_compiler import (
    PriorResultOwnershipV2,
    SemanticPlanningCompiler,
)
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
from tests.planning.test_plan_readiness import (
    _ACTIVE_DATASET_PIN,
    _common,
    _public_fund_prior_aggregate,
    _public_fund_representative_count,
    _validate,
    _verified_population_facts,
)
from tests.planning.test_semantic_compiler import BINDINGS, PLANNING, POLICIES
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


def _public_prior_compilation(consumer_contract, *, facts=None):
    producer_payload = _common("lookup", "public_fund")
    producer_payload["qualifiers"]["as_of_date"] = "2026-08-24"
    producer_payload["projections"] = {
        "field_concept_ids": ["aum"],
        "default_profile_id": None,
    }
    producer = QueryContractCandidate(
        candidate_id="public-producer",
        contract=_validate(producer_payload),
    )
    consumer = QueryContractCandidate(
        candidate_id="public-consumer",
        contract=consumer_contract,
    )
    ownership = (
        PriorResultOwnershipV2(
            binding_id="result-set-1",
            producer_frame_id="frame-1",
            cardinality=Cardinality.MANY,
        ),
    )
    compiler = SemanticPlanningCompiler(BINDINGS, POLICIES, PLANNING)
    complete_axis = tuple(
        AxisReadinessRecordV2(
            readiness=AxisReadiness.COMPLETE,
            reason_codes=(),
        )
        for _ in range(2)
    )
    complete_contract = tuple(
        ContractReadinessRecordV2(
            readiness=ContractReadiness.COMPLETE,
            reason_codes=(),
        )
        for _ in range(2)
    )
    assessments = compiler.assess_in_dependency_order(
        selected_candidates=(producer, consumer),
        axis_readiness=complete_axis,
        contract_readiness=complete_contract,
        active_dataset_pin=_ACTIVE_DATASET_PIN,
        prior_result_ownership=ownership,
        facts=facts,
    )
    compilation = compiler.compile(
        request_key="e" * 64,
        run_id="run-1",
        dataset_version=_ACTIVE_DATASET_PIN.dataset_version,
        dataset_pin=_ACTIVE_DATASET_PIN.manifest_hash,
        cutoff_date=date(2026, 8, 24),
        producer="semantic-query-compiler.v2",
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
        resolution_id="resolution-1",
        selected_candidates=(producer, consumer),
        readiness_assessments=assessments,
        primitive_ids=("lookup-products", "aggregate-products"),
        prior_result_ownership=ownership,
    )
    return compilation, assessments


def test_prior_result_compiles_deferred_then_binds_canonical_entity_ids() -> None:
    compilation = sql_dependency_compilation()
    plan = compilation.logical_query_plan
    assert plan is not None
    consumer = plan.tasks[1]
    assert consumer.scope.product_family_ids == ()
    outcome = SQL_COMPILER.compile_task(plan, consumer.task_id)

    assert outcome.request is not None
    assert tuple(
        item.id for item in outcome.request.render_manifest.binding_definitions
    ) == ("domestic-etf-aum.v1",)
    assert tuple(
        item.value
        for item in outcome.request.render_manifest.effective_product_family_ids
    ) == ("domestic_etf",)
    assert "product_family =" not in outcome.request.statement
    assert "identity-unit.v1" in outcome.request.applied_policy_ids
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


def test_public_fund_prior_sum_requires_policy_then_compiles_representative_cte() -> None:
    unsafe, unsafe_assessments = _public_prior_compilation(
        _public_fund_prior_aggregate(representative=False),
        facts=_verified_population_facts(),
    )
    safe, safe_assessments = _public_prior_compilation(
        _public_fund_prior_aggregate(representative=True),
        facts=_verified_population_facts(),
    )

    assert unsafe_assessments[1].plan.readiness.value == "limited"
    assert unsafe.route is CompilationRoute.EXPLORE
    assert unsafe.logical_query_plan is None
    assert safe_assessments[1].plan.readiness.value == "executable"
    assert safe.logical_query_plan is not None
    compiler = type(SQL_COMPILER)(BINDINGS, POLICIES, PLANNING, _ACTIVE_DATASET_PIN)
    request = compiler.compile_task(
        safe.logical_query_plan,
        safe.logical_query_plan.tasks[1].task_id,
        readiness_facts=_verified_population_facts(),
    ).request

    assert request is not None
    assert request.render_manifest.effective_product_family_ids == ("public_fund",)
    assert "representative_product" in request.statement
    assert "product_family =" not in request.statement


def test_public_fund_prior_count_compiles_with_closed_manifest_lineage() -> None:
    consumer = _public_fund_representative_count().model_copy(
        update={
            "frame_id": "frame-2",
            "scope": _public_fund_representative_count().scope.model_copy(
                update={
                    "product_family_ids": (),
                    "prior_result_binding": "result-set-1",
                }
            ),
        }
    )
    compilation, assessments = _public_prior_compilation(
        consumer,
        facts=_verified_population_facts(),
    )

    assert assessments[1].plan.readiness.value == "executable"
    assert compilation.logical_query_plan is not None
    compiler = type(SQL_COMPILER)(BINDINGS, POLICIES, PLANNING, _ACTIVE_DATASET_PIN)
    request = compiler.compile_task(
        compilation.logical_query_plan,
        compilation.logical_query_plan.tasks[1].task_id,
        readiness_facts=_verified_population_facts(),
    ).request

    assert request is not None
    assert request.render_manifest.binding_definitions == ()
    assert request.render_manifest.count_lineage_metric_definition_refs == (
        "organizer.prfd01n001.net_assets:2",
    )
    assert "representative_product" in request.statement


@pytest.mark.parametrize(
    "entity_ids",
    (
        ("representative-a",),
        ("share-a",),
        ("share-a", "share-b"),
        ("representative-a", "share-a", "unrelated-product"),
    ),
)
def test_public_fund_prior_membership_is_applied_before_representative_collapse(
    entity_ids,
) -> None:
    compilation, assessments = _public_prior_compilation(
        _public_fund_prior_aggregate(representative=True),
        facts=_verified_population_facts(),
    )
    assert assessments[1].plan.readiness.value == "executable"
    plan = compilation.logical_query_plan
    assert plan is not None
    compiler = type(SQL_COMPILER)(
        BINDINGS, POLICIES, PLANNING, _ACTIVE_DATASET_PIN
    )
    request = compiler.compile_task(
        plan,
        plan.tasks[1].task_id,
        readiness_facts=_verified_population_facts(),
    ).request
    assert request is not None
    binding = BindingValue(
        binding_name="result-set-1",
        value_type="semantic-result:many",
        value=encode_contract_value(entity_ids),
    )

    bound = SemanticSqlRuntimeBinder(compiler).bind(
        request,
        plan,
        (binding,),
        dependency_results=(_dependency_result(plan, binding),),
    )

    assert "relation_record.subject_id = ANY" in bound.statement
    assert "relation_record.object_id = ANY" in bound.statement
    assert "product.entity_id = ANY" not in bound.statement
    prior_parameter = next(
        item
        for item in bound.parameters
        if isinstance(item, SqlParameter) and item.name.startswith("prior_result_")
    )
    assert bound.statement.count(prior_parameter.name) == 2
    assert decode_contract_value(prior_parameter.value) == tuple(
        sorted(set(entity_ids))
    )

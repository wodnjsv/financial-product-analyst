from __future__ import annotations

from datetime import date
from decimal import Decimal

from financial_agent.contracts.canonical import canonical_json_bytes
from financial_agent.contracts.enums import ProductFamily
from financial_agent.contracts.values import decode_contract_value
from financial_agent.intent.query_contracts import (
    AggregationSpecV2,
    AggregationFunction,
    ComparisonSpecV2,
    OrderingSpecV2,
    OrderingDirection,
    PredicateAllOfV2,
    PredicateAtomV2,
    PredicateNotV2,
    QueryQualifiersV2,
    QueryOperatorId,
    QueryResultShape,
    TypedSemanticValue,
)
from financial_agent.planning.logical_query import (
    LogicalAggregateOperationV2,
    LogicalCompareOperationV2,
    LogicalLookupOperationV2,
    LogicalRankOperationV2,
    LogicalScreenOperationV2,
)
from financial_agent.intent.query_contracts import ProjectionSpecV2
from financial_agent.sql.compiler import SemanticSqlCompiler

from .helpers import (
    ACTIVE_DATASET,
    BINDINGS,
    PLANNING,
    POLICIES,
    make_plan,
    verified_public_fund_facts,
)


COMPILER = SemanticSqlCompiler(BINDINGS, POLICIES, PLANNING, ACTIVE_DATASET)


def _aum_lookup():
    return make_plan(
        LogicalLookupOperationV2(
            projections=ProjectionSpecV2(field_concept_ids=("aum",))
        )
    )


def test_lookup_compilation_is_deterministic_parameterized_and_owned() -> None:
    plan = _aum_lookup()

    first = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    second = COMPILER.compile_task(plan, plan.tasks[0].task_id)

    assert first.rejection is None
    assert first.request is not None
    assert canonical_json_bytes(first.request) == canonical_json_bytes(second.request)
    assert first.request.logical_plan_id == plan.logical_plan_id
    assert first.request.task_id == plan.tasks[0].task_id
    assert first.request.binding_registry_hash == plan.binding_registry_hash
    assert "catalog.product" in first.request.statement
    assert "observation.observation_record" in first.request.statement
    assert "domestic_etf" not in first.request.statement
    assert "organizer.pref01n001.aum" not in first.request.statement
    assert {decode_contract_value(item.value) for item in first.request.parameters} >= {
        "synthetic-dataset-v1",
        "domestic_etf",
        "organizer.pref01n001.aum",
    }


def test_multiple_entity_scope_values_are_one_bound_membership_filter() -> None:
    plan = make_plan(
        LogicalLookupOperationV2(
            projections=ProjectionSpecV2(field_concept_ids=("aum",))
        ),
        entity_refs=("product-a", "product-b"),
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is not None
    assert "entity_id IN" in outcome.request.statement
    values = {decode_contract_value(item.value) for item in outcome.request.parameters}
    assert {"product-a", "product-b"} <= values


def test_compound_predicates_and_qualifiers_are_lowered() -> None:
    predicate = PredicateAllOfV2(
        children=(
            PredicateAtomV2(
                field_concept_id="aum",
                operator_id=QueryOperatorId.BETWEEN,
                values=(
                    TypedSemanticValue(kind="decimal", decimal="100"),
                    TypedSemanticValue(kind="decimal", decimal="200"),
                ),
                null_policy_id="exclude_missing.v1",
            ),
            PredicateNotV2(
                child=PredicateAtomV2(
                    field_concept_id="aum",
                    operator_id=QueryOperatorId.IS_MISSING,
                    null_policy_id="exclude_missing.v1",
                )
            ),
        )
    )
    plan = make_plan(
        LogicalScreenOperationV2(predicate=predicate),
        policy_ids=("exclude_missing.v1", "identity-unit.v1"),
        qualifiers=QueryQualifiersV2(
            currency_id="KRW", as_of_date=date(2026, 8, 24)
        ),
    )

    result = COMPILER.compile_task(plan, plan.tasks[0].task_id)

    assert result.request is not None
    sql = result.request.statement.upper()
    assert "BETWEEN" in sql and "NOT" in sql
    values = {decode_contract_value(item.value) for item in result.request.parameters}
    assert {Decimal("100"), Decimal("200"), "KRW", date(2026, 8, 24)} <= values


def test_percent_conversion_occurs_only_during_physical_compilation() -> None:
    literal = TypedSemanticValue(kind="decimal", decimal="1", unit_id="percent")
    predicate = PredicateAtomV2(
        field_concept_id="fee_rate",
        operator_id=QueryOperatorId.LTE,
        value=literal,
        null_policy_id="exclude_missing.v1",
    )
    plan = make_plan(
        LogicalScreenOperationV2(predicate=predicate),
        binding_ids=("domestic-etf-fee-rate.v1",),
        policy_ids=(
            "exclude_missing.v1",
            "semantic-percent-to-percentage-point.v1",
        ),
        qualifiers=QueryQualifiersV2(unit_id="percent"),
    )
    before = plan.model_dump_json()

    result = COMPILER.compile_task(plan, plan.tasks[0].task_id)

    assert result.request is not None
    assert Decimal("1") in {
        decode_contract_value(item.value) for item in result.request.parameters
    }
    assert plan.model_dump_json() == before


def test_rank_adds_stable_product_tie_break_and_bound_limit() -> None:
    plan = make_plan(
        LogicalRankOperationV2(
            ordering=(
                OrderingSpecV2(
                    field_concept_id="aum",
                    direction=OrderingDirection.DESC,
                    nulls_policy_id="exclude_missing.v1",
                    tie_break_policy_id="stable-product-id.v1",
                ),
            ),
            limit=5,
        ),
        policy_ids=("exclude_missing.v1", "stable-product-id.v1", "identity-unit.v1"),
    )

    result = COMPILER.compile_task(plan, plan.tasks[0].task_id)

    assert result.request is not None
    assert "ORDER BY" in result.request.statement
    assert "entity_id" in result.request.statement
    assert "LIMIT" in result.request.statement
    assert 5 in {decode_contract_value(item.value) for item in result.request.parameters}


def test_rank_missing_predicate_conflict_rejects_instead_of_empty_false_success() -> None:
    missing = PredicateAtomV2(
        field_concept_id="aum",
        operator_id=QueryOperatorId.IS_MISSING,
        null_policy_id="exclude_missing.v1",
    )
    plan = make_plan(
        LogicalRankOperationV2(
            ordering=(
                OrderingSpecV2(
                    field_concept_id="aum",
                    direction=OrderingDirection.DESC,
                    nulls_policy_id="exclude_missing.v1",
                    tie_break_policy_id="stable-product-id.v1",
                ),
            ),
            limit=5,
            predicate=missing,
        ),
        policy_ids=("exclude_missing.v1", "stable-product-id.v1", "identity-unit.v1"),
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.rejection.code == "ORDERING_MISSINGNESS_CONFLICT"


def test_scalar_aggregates_and_distinct_count_compile() -> None:
    for function_id in (
        AggregationFunction.SUM,
        AggregationFunction.AVG,
        AggregationFunction.MIN,
        AggregationFunction.MAX,
    ):
        aggregation = AggregationSpecV2(
            function_id=function_id,
            target_field_concept_id="aum",
            population_grain_id="source-product.v1",
            dedup_policy_id="no-dedup.v1",
        )
        plan = make_plan(
            LogicalAggregateOperationV2(aggregation=aggregation),
            policy_ids=("source-product.v1", "no-dedup.v1", "identity-unit.v1", "exclude_missing.v1"),
        )
        result = COMPILER.compile_task(plan, plan.tasks[0].task_id)
        assert result.request is not None, (function_id, result.rejection)


def test_count_grouping_and_comparison_lowerings() -> None:
    count_plan = make_plan(
        LogicalAggregateOperationV2(
            aggregation=AggregationSpecV2(
                function_id=AggregationFunction.COUNT,
                count_population_id="source-product.v1",
                population_grain_id="source-product.v1",
                dedup_policy_id="no-dedup.v1",
            )
        ),
        binding_ids=(),
        policy_ids=("source-product.v1", "no-dedup.v1"),
        qualifiers=QueryQualifiersV2(),
    )
    count = COMPILER.compile_task(count_plan, count_plan.tasks[0].task_id)
    assert count.request is not None
    assert "count(DISTINCT catalog.product.entity_id)" in count.request.statement

    grouped_plan = make_plan(
        LogicalAggregateOperationV2(
            aggregation=AggregationSpecV2(
                function_id=AggregationFunction.SUM,
                target_field_concept_id="aum",
                group_by_field_concept_ids=("aum",),
                population_grain_id="source-product.v1",
                dedup_policy_id="no-dedup.v1",
            )
        ),
        policy_ids=("source-product.v1", "no-dedup.v1", "identity-unit.v1", "exclude_missing.v1"),
        result_shape=QueryResultShape.GROUPED_TABLE,
    )
    grouped = COMPILER.compile_task(grouped_plan, grouped_plan.tasks[0].task_id)
    assert grouped.request is not None
    assert "GROUP BY" in grouped.request.statement

    comparison_plan = make_plan(
        LogicalCompareOperationV2(
            comparison=ComparisonSpecV2(
                subject_refs=("product-a", "product-b"),
                metric_concept_ids=("aum",),
                basis_policy_id="same-definition-period-unit.v1",
            )
        ),
        policy_ids=("same-definition-period-unit.v1", "identity-unit.v1", "exclude_missing.v1"),
    )
    comparison = COMPILER.compile_task(
        comparison_plan, comparison_plan.tasks[0].task_id
    )
    assert comparison.request is not None
    values = {decode_contract_value(item.value) for item in comparison.request.parameters}
    assert {"product-a", "product-b"} <= values


def test_missing_and_present_use_registered_statuses_without_sentinel_leakage() -> None:
    predicate = PredicateAtomV2(
        field_concept_id="aum",
        operator_id=QueryOperatorId.IS_MISSING,
        null_policy_id="exclude_missing.v1",
    )
    plan = make_plan(
        LogicalScreenOperationV2(predicate=predicate),
        policy_ids=("exclude_missing.v1", "identity-unit.v1"),
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is not None
    values = {decode_contract_value(item.value) for item in outcome.request.parameters}
    assert {"missing", "placeholder", "unavailable", "inapplicable", "unknown"} <= values
    assert "evidence_id_0" in outcome.request.statement


def test_unknown_task_and_registry_pin_drift_reject_stably() -> None:
    plan = _aum_lookup()
    missing = COMPILER.compile_task(plan, "logical-task-missing")
    assert missing.rejection.code == "SQL_TASK_NOT_FOUND"

    binding_drift = plan.model_copy(update={"binding_registry_hash": "f" * 64})
    assert (
        COMPILER.compile_task(binding_drift, plan.tasks[0].task_id).rejection.code
        == "BINDING_REGISTRY_PIN_MISMATCH"
    )
    planning_drift = plan.model_copy(update={"planning_registry_hash": "f" * 64})
    assert (
        COMPILER.compile_task(planning_drift, plan.tasks[0].task_id).rejection.code
        == "PLANNING_REGISTRY_PIN_MISMATCH"
    )
    dataset_drift = plan.model_copy(update={"dataset_pin": "f" * 64})
    assert (
        COMPILER.compile_task(dataset_drift, plan.tasks[0].task_id).rejection.code
        == "DATASET_PROVENANCE_MISMATCH"
    )


def test_public_fund_representative_aggregate_requires_verified_proof() -> None:
    aggregation = AggregationSpecV2(
        function_id=AggregationFunction.SUM,
        target_field_concept_id="aum",
        population_grain_id="representative-product.v1",
        dedup_policy_id="public-fund-representative-share.v1",
    )
    plan = make_plan(
        LogicalAggregateOperationV2(aggregation=aggregation),
        family=ProductFamily.PUBLIC_FUND,
        binding_ids=("public-fund-aum.v1",),
        policy_ids=(
            "representative-product.v1",
            "public-fund-representative-share.v1",
            "identity-unit.v1",
            "exclude_missing.v1",
        ),
        evidence=("metric_definition", "observation_record", "relation_record", "evidence_record", "source_record"),
        qualifiers=QueryQualifiersV2(as_of_date=date(2026, 8, 24)),
    )

    result = COMPILER.compile_task(plan, plan.tasks[0].task_id)

    assert result.request is None
    assert result.rejection.code == "PUBLIC_FUND_VERIFIED_PROOF_REQUIRED"

    compiled = COMPILER.compile_task(
        plan,
        plan.tasks[0].task_id,
        readiness_facts=verified_public_fund_facts(),
    )
    assert compiled.request is not None
    assert "WITH representative_product AS" in compiled.request.statement
    assert "hasShareClass" not in compiled.request.statement
    assert compiled.request.population_manifest_id == "synthetic-public-fund-complete.v1"
    assert compiled.request.population_manifest_hash == verified_public_fund_facts().public_fund_manifest_hash


def test_cross_currency_normalization_stays_fail_closed() -> None:
    plan = make_plan(
        LogicalLookupOperationV2(
            projections=ProjectionSpecV2(field_concept_ids=("aum",))
        ),
        family=ProductFamily.OVERSEAS_ETF,
        binding_ids=("overseas-etf-aum.v1",),
        qualifiers=QueryQualifiersV2(
            currency_id="USD", as_of_date=date(2026, 8, 24)
        ),
    )
    result = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert result.rejection.code == "CROSS_CURRENCY_NORMALIZATION_UNVERIFIED"

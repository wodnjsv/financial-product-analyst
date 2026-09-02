from __future__ import annotations

from datetime import date

import pytest

from financial_agent.contracts.enums import ProductFamily
from financial_agent.intent.query_contracts import (
    AggregationFunction,
    AggregationBucketPolicyId,
    AggregationSpecV2,
    OrderingDirection,
    OrderingSpecV2,
    PredicateAtomV2,
    PredicateAllOfV2,
    PredicateNotV2,
    QueryOperatorId,
    QueryQualifiersV2,
    QueryResultShape,
    TypedSemanticValue,
)
from financial_agent.planning.logical_query import (
    LogicalAggregateOperationV2,
    LogicalRankOperationV2,
    LogicalScreenOperationV2,
)
from financial_agent.planning.physical_bindings import PhysicalBindingAvailability
from financial_agent.sql.compiler import SemanticSqlCompiler

from .helpers import ACTIVE_DATASET, BINDINGS, PLANNING, POLICIES, make_plan


COMPILER = SemanticSqlCompiler(BINDINGS, POLICIES, PLANNING, ACTIVE_DATASET)


def _qualifiers(binding):
    return QueryQualifiersV2(
        unit_id="percent" if binding.semantic_concept_id == "fee_rate" else None,
        as_of_date=(
            date(2026, 8, 24)
            if binding.semantic_concept_id == "aum"
            else None
        ),
    )


def _value(operator: QueryOperatorId, *, wrong_kind: bool = False):
    if operator in {QueryOperatorId.IS_MISSING, QueryOperatorId.IS_PRESENT}:
        return {"value": None, "values": ()}
    if wrong_kind:
        item = TypedSemanticValue(kind="string", string="not-a-decimal")
    else:
        item = TypedSemanticValue(kind="decimal", decimal="1", unit_id="percent")
    if operator is QueryOperatorId.BETWEEN:
        return {"value": None, "values": (item, item)}
    if operator in {QueryOperatorId.IN, QueryOperatorId.NOT_IN}:
        return {"value": None, "values": (item,)}
    return {"value": item, "values": ()}


@pytest.mark.parametrize("binding_id", tuple(BINDINGS.bindings_by_id))
@pytest.mark.parametrize("operator", tuple(QueryOperatorId))
def test_family_field_operator_value_matrix_never_raises(binding_id, operator) -> None:
    binding = BINDINGS.bindings_by_id[binding_id]
    wrong_kind = operator is QueryOperatorId.CONTAINS
    values = _value(operator, wrong_kind=wrong_kind)
    predicate = PredicateAtomV2(
        field_concept_id=binding.semantic_concept_id,
        operator_id=operator,
        value=values["value"],
        values=values["values"],
        null_policy_id="exclude_missing.v1",
    )
    plan = make_plan(
        LogicalScreenOperationV2(predicate=predicate),
        family=binding.product_family_id,
        binding_ids=(binding.id,),
        policy_ids=tuple(
            dict.fromkeys(
                item
                for item in (
                    "exclude_missing.v1",
                    binding.unit_conversion_policy_id,
                )
                if item is not None
            )
        ),
        qualifiers=_qualifiers(binding),
    )

    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)

    assert (outcome.request is None) != (outcome.rejection is None)
    if binding.availability is PhysicalBindingAvailability.UNAVAILABLE:
        assert outcome.rejection.code == "PHYSICAL_BINDING_UNAVAILABLE"


@pytest.mark.parametrize("binding_id", tuple(BINDINGS.bindings_by_id))
def test_family_rank_matrix_is_request_or_one_rejection(binding_id) -> None:
    binding = BINDINGS.bindings_by_id[binding_id]
    plan = make_plan(
        LogicalRankOperationV2(
            ordering=(
                OrderingSpecV2(
                    field_concept_id=binding.semantic_concept_id,
                    direction=OrderingDirection.DESC,
                    nulls_policy_id="exclude_missing.v1",
                    tie_break_policy_id="stable-product-id.v1",
                ),
            ),
            limit=5,
        ),
        family=binding.product_family_id,
        binding_ids=(binding.id,),
        policy_ids=tuple(
            dict.fromkeys(
                item
                for item in (
                    "exclude_missing.v1",
                    "stable-product-id.v1",
                    binding.unit_conversion_policy_id,
                )
                if item is not None
            )
        ),
        qualifiers=_qualifiers(binding),
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert (outcome.request is None) != (outcome.rejection is None)


@pytest.mark.parametrize("binding_id", tuple(BINDINGS.bindings_by_id))
@pytest.mark.parametrize("function", tuple(AggregationFunction))
def test_family_aggregate_matrix_is_request_or_one_rejection(binding_id, function) -> None:
    binding = BINDINGS.bindings_by_id[binding_id]
    if function is AggregationFunction.COUNT:
        spec = AggregationSpecV2(
            function_id=function,
            count_population_id="source-product.v1",
            population_grain_id="source-product.v1",
            dedup_policy_id="no-dedup.v1",
        )
        binding_ids = ()
    else:
        spec = AggregationSpecV2(
            function_id=function,
            target_field_concept_id=binding.semantic_concept_id,
            bucket_policy_id=(AggregationBucketPolicyId.EQUAL_WIDTH_10 if function is AggregationFunction.DISTRIBUTION else None),
            population_grain_id="source-product.v1",
            dedup_policy_id="no-dedup.v1",
        )
        binding_ids = (binding.id,)
    shape = (
        QueryResultShape.DISTRIBUTION
        if function is AggregationFunction.DISTRIBUTION
        else QueryResultShape.SINGLE_VALUE
    )
    policies = ["source-product.v1", "no-dedup.v1"]
    if binding_ids:
        policies.append("exclude_missing.v1")
    if function is AggregationFunction.DISTRIBUTION:
        policies.append("equal-width-10.v1")
    if binding.unit_conversion_policy_id:
        policies.append(binding.unit_conversion_policy_id)
    plan = make_plan(
        LogicalAggregateOperationV2(aggregation=spec),
        family=binding.product_family_id,
        binding_ids=binding_ids,
        policy_ids=tuple(dict.fromkeys(policies)),
        qualifiers=_qualifiers(binding) if binding_ids else QueryQualifiersV2(),
        result_shape=shape,
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert (outcome.request is None) != (outcome.rejection is None)


@pytest.mark.parametrize("binding_id", tuple(BINDINGS.bindings_by_id))
def test_family_aggregate_predicate_matrix_is_lossless_or_one_rejection(binding_id) -> None:
    binding = BINDINGS.bindings_by_id[binding_id]
    value = TypedSemanticValue(
        kind=binding.semantic_value_kind,
        **(
            {"decimal": "1", "unit_id": "percent"}
            if binding.semantic_value_kind.value == "decimal"
            else {"string": "x"}
        ),
    )
    atom = PredicateAtomV2(
        field_concept_id=binding.semantic_concept_id,
        operator_id=QueryOperatorId.EQ,
        value=value,
        null_policy_id="exclude_missing.v1",
    )
    predicate = PredicateAllOfV2(children=(atom, PredicateNotV2(child=atom)))
    spec = AggregationSpecV2(
        function_id=AggregationFunction.SUM,
        target_field_concept_id=binding.semantic_concept_id,
        population_grain_id="source-product.v1",
        dedup_policy_id="no-dedup.v1",
    )
    policies = tuple(
        dict.fromkeys(
            item
            for item in (
                "source-product.v1",
                "no-dedup.v1",
                "exclude_missing.v1",
                binding.unit_conversion_policy_id,
            )
            if item is not None
        )
    )
    plan = make_plan(
        LogicalAggregateOperationV2(aggregation=spec, predicate=predicate),
        family=binding.product_family_id,
        binding_ids=(binding.id,),
        policy_ids=policies,
        qualifiers=_qualifiers(binding),
    )

    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)

    assert (outcome.request is None) != (outcome.rejection is None)
    if outcome.request is not None:
        assert any(
            item.semantic_path.startswith("operation.predicate.")
            for item in outcome.request.lowering_records
        )


@pytest.mark.parametrize(
    "qualifiers",
    (
        QueryQualifiersV2(period_id="one_year"),
        QueryQualifiersV2(currency_id="KRW"),
        QueryQualifiersV2(unit_id="percent"),
        QueryQualifiersV2(as_of_date=date(2026, 8, 24)),
    ),
)
def test_count_qualifier_matrix_is_one_stable_rejection(qualifiers) -> None:
    plan = make_plan(
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
        qualifiers=qualifiers,
    )

    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)

    assert outcome.request is None
    assert outcome.rejection.code == "COUNT_QUALIFIER_BINDING_REQUIRED"

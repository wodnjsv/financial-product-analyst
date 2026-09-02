from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from financial_agent.contracts.canonical import canonical_json_bytes
from financial_agent.intent.query_contracts import (
    AggregationFunction,
    AggregationSpecV2,
    OrderingDirection,
    OrderingSpecV2,
    ProjectionSpecV2,
    QueryQualifiersV2,
    QueryResultShape,
)
from financial_agent.planning.logical_query import (
    LogicalAggregateOperationV2,
    LogicalLookupOperationV2,
    LogicalRankOperationV2,
)
from financial_agent.sql.compiler import SemanticSqlCompiler
from financial_agent.sql.result_mapping import SqlResultMappingError, map_sql_rows

from .helpers import ACTIVE_DATASET, BINDINGS, PLANNING, POLICIES, make_plan


COMPILER = SemanticSqlCompiler(BINDINGS, POLICIES, PLANNING, ACTIVE_DATASET)


def _lookup_request():
    plan = make_plan(
        LogicalLookupOperationV2(
            projections=ProjectionSpecV2(field_concept_ids=("aum",))
        )
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is not None
    return outcome.request


def _lookup_row(
    value=Decimal("100"), *, include_lookup_status: bool = True
) -> dict[str, object]:
    row = {
        "product_id": "product-a",
        "product_name": "ETF A",
        "field_0": value,
        "value_status_0": "present" if value is not None else "missing",
        "reason_code_0": None if value is not None else "synthetic_missing",
        "observation_id_0": "observation-a",
        "metric_id_0": "organizer.pref01n001.aum",
        "metric_definition_version_0": "metric.v1",
        "unit_0": "source_defined_amount",
        "currency_0": "KRW",
        "applicable_date_0": date(2026, 8, 24),
        "evidence_id_0": ["evidence-a"],
        "source_id_0": ["source-a"],
    }
    if not include_lookup_status:
        del row["value_status_0"]
        del row["reason_code_0"]
    return row


def test_maps_business_value_and_flat_lineage_without_losing_zero() -> None:
    mapped = map_sql_rows(_lookup_request(), [_lookup_row(Decimal("0"))])

    assert mapped.result_rows[0].entity_ids == ("product-a",)
    aum = next(
        field for field in mapped.result_rows[0].fields if field.field_id == "aum"
    )
    assert aum.value.value == Decimal("0")
    assert aum.unit_id == "source_defined_amount"
    assert aum.currency == "KRW"
    assert aum.applicable_date == date(2026, 8, 24)
    assert mapped.evidence_refs == (
        "evidence:evidence-a",
        "observation:observation-a",
        "source:source-a",
    )
    assert mapped.exclusions == ()


def test_unordered_product_results_are_canonicalized_deterministically() -> None:
    first = _lookup_row(Decimal("100"))
    second = {
        **_lookup_row(Decimal("200")),
        "product_id": "product-b",
        "product_name": "ETF B",
        "observation_id_0": "observation-b",
        "evidence_id_0": ["evidence-b"],
        "source_id_0": ["source-b"],
    }
    left = map_sql_rows(_lookup_request(), [first, second])
    right = map_sql_rows(_lookup_request(), [second, first])
    assert canonical_json_bytes(left) == canonical_json_bytes(right)


def test_missing_and_sentinel_values_are_exclusions_not_zeroes() -> None:
    missing = map_sql_rows(_lookup_request(), [_lookup_row(None)])
    assert all(field.field_id != "aum" for field in missing.result_rows[0].fields)
    assert missing.exclusions[0].reason_code == "SOURCE_VALUE_MISSING"
    assert missing.warnings[0].warning_code == "MISSING_VALUE_EXCLUDED"


def test_unexpected_columns_wrong_types_and_duplicate_entities_fail_closed() -> None:
    request = _lookup_request()
    with pytest.raises(SqlResultMappingError, match="RETURNED_COLUMN_SET_MISMATCH"):
        map_sql_rows(request, [{**_lookup_row(), "injected": "value"}])
    with pytest.raises(SqlResultMappingError, match="RETURNED_VALUE_TYPE_MISMATCH"):
        map_sql_rows(request, [_lookup_row("100")])
    with pytest.raises(SqlResultMappingError, match="RETURNED_DUPLICATE_ROW"):
        map_sql_rows(request, [_lookup_row(), _lookup_row()])


def test_physical_metadata_and_lineage_must_match_the_compiler_binding() -> None:
    request = _lookup_request()
    with pytest.raises(SqlResultMappingError, match="RETURNED_METRIC_OWNERSHIP_MISMATCH"):
        map_sql_rows(
            request,
            [{**_lookup_row(), "metric_id_0": "invented.metric"}],
        )
    with pytest.raises(SqlResultMappingError, match="RETURNED_UNIT_OWNERSHIP_MISMATCH"):
        map_sql_rows(request, [{**_lookup_row(), "unit_0": "USD"}])
    with pytest.raises(SqlResultMappingError, match="RETURNED_UNIT_OWNERSHIP_MISMATCH"):
        map_sql_rows(request, [{**_lookup_row(), "unit_0": None}])
    with pytest.raises(SqlResultMappingError, match="RETURNED_DATE_OWNERSHIP_MISMATCH"):
        map_sql_rows(request, [{**_lookup_row(), "applicable_date_0": None}])
    with pytest.raises(SqlResultMappingError, match="RETURNED_EVIDENCE_IDS_MALFORMED"):
        map_sql_rows(request, [{**_lookup_row(), "evidence_id_0": [["nested"]]}])


def test_semantic_unit_conversion_is_labeled_with_exact_storage_unit() -> None:
    plan = make_plan(
        LogicalLookupOperationV2(
            projections=ProjectionSpecV2(field_concept_ids=("fee_rate",))
        ),
        binding_ids=("domestic-etf-fee-rate.v1",),
        policy_ids=(
            "exclude_missing.v1",
            "semantic-percent-to-percentage-point.v1",
        ),
        qualifiers=QueryQualifiersV2(unit_id="percent"),
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is not None
    row = {
        **_lookup_row(Decimal("0.5")),
        "metric_id_0": "organizer.pref01n001.total_fee_rate",
        "unit_0": "percentage_point",
        "currency_0": None,
    }

    mapped = map_sql_rows(outcome.request, [row])

    fee = next(field for field in mapped.result_rows[0].fields if field.field_id == "fee_rate")
    assert fee.unit_id == "percentage_point"
    with pytest.raises(SqlResultMappingError, match="RETURNED_UNIT_OWNERSHIP_MISMATCH"):
        map_sql_rows(outcome.request, [{**row, "unit_0": "percent"}])


def test_scalar_aggregate_preserves_flat_arrays_and_rejects_mixed_units() -> None:
    plan = make_plan(
        LogicalAggregateOperationV2(
            aggregation=AggregationSpecV2(
                function_id=AggregationFunction.SUM,
                target_field_concept_id="aum",
                population_grain_id="source-product.v1",
                dedup_policy_id="no-dedup.v1",
            )
        ),
        policy_ids=(
            "source-product.v1",
            "no-dedup.v1",
            "identity-unit.v1",
            "exclude_missing.v1",
        ),
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is not None
    row = {
        "aggregate_value": Decimal("300"),
        "observation_ids": ["observation-a", "observation-b"],
        "metric_ids": ["organizer.pref01n001.aum"],
        "metric_definition_versions": ["metric.v1"],
        "units": ["source_defined_amount"],
        "currencies": ["KRW"],
        "applicable_dates": [date(2026, 8, 24)],
        "evidence_ids": ["evidence-a", "evidence-b"],
        "source_ids": ["source-a"],
    }
    mapped = map_sql_rows(outcome.request, [row])
    assert mapped.result_rows[0].fields[0].field_id == "aum"
    assert mapped.evidence_refs == (
        "evidence:evidence-a",
        "evidence:evidence-b",
        "observation:observation-a",
        "observation:observation-b",
        "source:source-a",
    )

    with pytest.raises(SqlResultMappingError, match="RETURNED_AGGREGATE_UNIT_MISMATCH"):
        map_sql_rows(outcome.request, [{**row, "units": ["source_defined_amount", "USD"]}])
    with pytest.raises(SqlResultMappingError, match="RETURNED_AGGREGATE_UNIT_MISMATCH"):
        map_sql_rows(outcome.request, [{**row, "units": [None, "source_defined_amount"]}])
    with pytest.raises(SqlResultMappingError, match="RETURNED_AGGREGATE_CURRENCY_MISMATCH"):
        map_sql_rows(outcome.request, [{**row, "currencies": [None, "KRW"]}])
    with pytest.raises(SqlResultMappingError, match="RETURNED_AGGREGATE_DATE_MISMATCH"):
        map_sql_rows(
            outcome.request,
            [{**row, "applicable_dates": [None, date(2026, 8, 24)]}],
        )
    with pytest.raises(SqlResultMappingError, match="RETURNED_METRIC_OWNERSHIP_MISMATCH"):
        map_sql_rows(outcome.request, [{**row, "metric_ids": ["invented.metric"]}])


def test_count_cardinality_and_injection_shaped_names_remain_data() -> None:
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
        qualifiers=QueryQualifiersV2(),
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is not None
    mapped = map_sql_rows(
        outcome.request,
        [
            {
                "aggregate_value": 2,
                "product_ids": ["product-a", "product-b"],
                "observation_ids": ["observation-a", "observation-b"],
                "evidence_ids": ["evidence-a", "evidence-b"],
                "source_ids": ["source-a"],
            }
        ],
    )
    assert mapped.result_rows[0].fields[0].value.value == 2
    assert mapped.evidence_refs == (
        "evidence:evidence-a",
        "evidence:evidence-b",
        "observation:observation-a",
        "observation:observation-b",
        "source:source-a",
    )
    with pytest.raises(SqlResultMappingError, match="RETURNED_COUNT_CARDINALITY_MISMATCH"):
        map_sql_rows(
            outcome.request,
            [
                {
                    "aggregate_value": 1,
                    "product_ids": ["product-a", "product-b"],
                    "observation_ids": ["observation-a", "observation-b"],
                    "evidence_ids": ["evidence-a", "evidence-b"],
                    "source_ids": ["source-a"],
                }
            ],
        )

    empty = map_sql_rows(
        outcome.request,
        [
            {
                "aggregate_value": 0,
                "product_ids": None,
                "observation_ids": None,
                "evidence_ids": None,
                "source_ids": None,
            }
        ],
    )
    assert empty.result_rows[0].fields[0].value.value == 0
    assert empty.result_rows[0].entity_ids == ()
    with pytest.raises(SqlResultMappingError, match="RETURNED_PRODUCT_IDS_MALFORMED"):
        map_sql_rows(
            outcome.request,
            [
                {
                    "aggregate_value": 1,
                    "product_ids": None,
                    "observation_ids": ["observation-a"],
                    "evidence_ids": ["evidence-a"],
                    "source_ids": ["source-a"],
                }
            ],
        )
    with pytest.raises(SqlResultMappingError, match="RETURNED_COLUMN_SET_MISMATCH"):
        map_sql_rows(
            outcome.request,
            [
                {
                    "aggregate_value": 1,
                    "product_ids": ["product-a"],
                    "observation_ids": ["observation-a"],
                    "evidence_ids": ["evidence-a"],
                }
            ],
        )

    row = _lookup_row()
    row["product_name"] = "ETF'); DROP TABLE catalog.product; --"
    assert map_sql_rows(_lookup_request(), [row]).result_rows[0].fields[0].value.value == row["product_name"]


def test_rank_preserves_compiler_order_and_enforces_limit_with_ties() -> None:
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
            limit=2,
        ),
        policy_ids=("exclude_missing.v1", "stable-product-id.v1", "identity-unit.v1"),
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is not None
    first = {
        **_lookup_row(Decimal("200"), include_lookup_status=False),
        "product_id": "product-a",
    }
    second = {
        **_lookup_row(Decimal("200"), include_lookup_status=False),
        "product_id": "product-b",
        "observation_id_0": "observation-b",
        "evidence_id_0": ["evidence-b"],
        "source_id_0": ["source-b"],
    }
    mapped = map_sql_rows(outcome.request, [first, second])
    assert [row.entity_ids[0] for row in mapped.result_rows] == ["product-a", "product-b"]
    third = {
        **_lookup_row(Decimal("100"), include_lookup_status=False),
        "product_id": "product-c",
        "observation_id_0": "observation-c",
        "evidence_id_0": ["evidence-c"],
        "source_id_0": ["source-c"],
    }
    with pytest.raises(SqlResultMappingError, match="RETURNED_CARDINALITY_EXCEEDED"):
        map_sql_rows(outcome.request, [first, second, third])


def test_grouped_aggregate_maps_group_and_target_without_nested_evidence() -> None:
    plan = make_plan(
        LogicalAggregateOperationV2(
            aggregation=AggregationSpecV2(
                function_id=AggregationFunction.SUM,
                target_field_concept_id="aum",
                group_by_field_concept_ids=("aum",),
                population_grain_id="source-product.v1",
                dedup_policy_id="no-dedup.v1",
            )
        ),
        binding_ids=("domestic-etf-aum.v1",),
        policy_ids=(
            "source-product.v1",
            "no-dedup.v1",
            "identity-unit.v1",
            "exclude_missing.v1",
        ),
        qualifiers=QueryQualifiersV2(as_of_date=date(2026, 8, 24)),
        result_shape=QueryResultShape.GROUPED_TABLE,
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is not None
    mapped = map_sql_rows(
        outcome.request,
        [
            {
                "group_0": Decimal("100"),
                "aggregate_value": Decimal("100"),
                "observation_ids": ["observation-a"],
                "metric_ids": ["organizer.pref01n001.aum"],
                "metric_definition_versions": ["metric.v1"],
                "units": ["source_defined_amount"],
                "currencies": ["KRW"],
                "applicable_dates": [date(2026, 8, 24)],
                "evidence_ids": ["evidence-a"],
                "source_ids": ["source-a"],
            }
        ],
    )
    assert [field.field_id for field in mapped.result_rows[0].fields] == [
        "group:aum",
        "aum",
    ]
    assert mapped.result_rows[0].fields[0].unit_id == "source_defined_amount"
    assert mapped.result_rows[0].fields[0].applicable_date == date(2026, 8, 24)
    assert mapped.evidence_refs == (
        "evidence:evidence-a",
        "observation:observation-a",
        "source:source-a",
    )


def test_grouped_count_requires_flat_observation_evidence_and_source_lineage() -> None:
    plan = make_plan(
        LogicalAggregateOperationV2(
            aggregation=AggregationSpecV2(
                function_id=AggregationFunction.COUNT,
                count_population_id="source-product.v1",
                group_by_field_concept_ids=("aum",),
                population_grain_id="source-product.v1",
                dedup_policy_id="no-dedup.v1",
            )
        ),
        policy_ids=(
            "source-product.v1",
            "no-dedup.v1",
            "identity-unit.v1",
            "exclude_missing.v1",
        ),
        qualifiers=QueryQualifiersV2(as_of_date=date(2026, 8, 24)),
        result_shape=QueryResultShape.GROUPED_TABLE,
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is not None
    row = {
        "group_0": Decimal("100"),
        "aggregate_value": 1,
        "product_ids": ["product-a"],
        "observation_ids": ["observation-a"],
        "evidence_ids": ["evidence-a"],
        "source_ids": ["source-a"],
    }
    mapped = map_sql_rows(outcome.request, [row])
    assert mapped.evidence_refs == (
        "evidence:evidence-a",
        "observation:observation-a",
        "source:source-a",
    )
    with pytest.raises(SqlResultMappingError, match="RETURNED_COLUMN_SET_MISMATCH"):
        map_sql_rows(outcome.request, [{key: value for key, value in row.items() if key != "source_ids"}])

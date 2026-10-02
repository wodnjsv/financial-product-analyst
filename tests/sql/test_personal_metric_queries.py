from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from financial_agent.contracts.enums import ProductFamily
from financial_agent.contracts.values import decode_contract_value
from financial_agent.intent.query_contracts import (
    OrderingDirection, OrderingSpecV2, PredicateAtomV2, ProjectionSpecV2, QueryOperatorId, QueryQualifiersV2,
    TypedSemanticValue,
)
from financial_agent.planning.logical_query import (
    LogicalLookupOperationV2, LogicalRankOperationV2, LogicalScreenOperationV2,
)
from financial_agent.sql.compiler import SemanticSqlCompiler
from financial_agent.sql.result_mapping import SqlResultMappingError, map_sql_rows

from .helpers import ACTIVE_DATASET, BINDINGS, PLANNING, POLICIES, make_plan


COMPILER = SemanticSqlCompiler(BINDINGS, POLICIES, PLANNING, ACTIVE_DATASET)
RETURN_ID = 'trailing_1y_historical_cumulative_return'


def _lookup(field, binding_id, *, family=ProductFamily.DOMESTIC_ETF, qualifiers=None):
    binding = BINDINGS.bindings_by_id.get(binding_id)
    assert binding is not None, 'required source metric binding is missing'
    return make_plan(
        LogicalLookupOperationV2(projections=ProjectionSpecV2(field_concept_ids=(field,))),
        family=family, binding_ids=(binding_id,),
        policy_ids=(binding.unit_conversion_policy_id, 'exclude_missing.v1'),
        qualifiers=qualifiers or QueryQualifiersV2(),
    )


def _request(plan):
    result = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert result.request is not None, result.rejection
    return result.request


@pytest.mark.parametrize('family', [ProductFamily.DOMESTIC_ETF, ProductFamily.OVERSEAS_ETF])
def test_fee_lookup_and_rank_use_registered_storage_unit_without_global_default(family) -> None:
    binding_id = f'{family.value.replace("_", "-")}-fee-rate.v1'
    lookup = _lookup('fee_rate', binding_id, family=family)
    request = _request(lookup)
    assert request.render_manifest.logical_task.qualifiers.unit_id is None
    assert request.render_manifest.binding_definitions[0].storage_unit_id == 'percentage_point'
    rank = make_plan(
        LogicalRankOperationV2(ordering=(OrderingSpecV2(
            field_concept_id='fee_rate', direction=OrderingDirection.ASC,
            nulls_policy_id='exclude_missing.v1', tie_break_policy_id='stable-product-id.v1',
        ),), limit=5),
        family=family, binding_ids=(binding_id,),
        policy_ids=('semantic-percent-to-percentage-point.v1', 'exclude_missing.v1', 'stable-product-id.v1'),
        qualifiers=QueryQualifiersV2(),
    )
    assert 'ORDER BY' in _request(rank).statement


@pytest.mark.parametrize('unit, code', [
    (None, 'UNIT_CONVERSION_POLICY_MISMATCH'), ('KRW', 'SEMANTIC_UNIT_NOT_SUPPORTED'),
])
def test_fee_numeric_threshold_still_requires_explicit_percent(unit, code) -> None:
    plan = make_plan(
        LogicalScreenOperationV2(predicate=PredicateAtomV2(
            field_concept_id='fee_rate', operator_id=QueryOperatorId.LTE,
            value=TypedSemanticValue(kind='decimal', decimal='0.1', unit_id=unit),
            null_policy_id='exclude_missing.v1',
        )),
        binding_ids=('domestic-etf-fee-rate.v1',),
        policy_ids=('semantic-percent-to-percentage-point.v1', 'exclude_missing.v1'),
        qualifiers=QueryQualifiersV2(),
    )
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert outcome.request is None
    assert outcome.rejection.code == code


def test_domestic_one_year_return_consumes_only_p1y_without_inventing_period_start() -> None:
    plan = _lookup(RETURN_ID, 'domestic-etf-return-1y.v1', qualifiers=QueryQualifiersV2(period_id='P1Y'))
    request = _request(plan)
    values = {decode_contract_value(item.value) for item in request.parameters}
    assert 'organizer.pref01n001.cumulative_return_1y' in values
    assert '2' in values
    assert 'metric_definition_version =' in request.statement
    assert 'period_start' not in request.statement
    assert any(record.semantic_path == 'qualifiers.period' for record in request.lowering_records)
    for period, expected in ((None, 'PHYSICAL_REQUIRED_QUALIFIER_MISSING'), ('P6M', 'PERIOD_QUALIFIER_NOT_SUPPORTED')):
        wrong = _lookup(RETURN_ID, 'domestic-etf-return-1y.v1', qualifiers=QueryQualifiersV2(period_id=period))
        outcome = COMPILER.compile_task(wrong, wrong.tasks[0].task_id)
        assert outcome.request is None
        assert outcome.rejection.code == expected


def test_bond_maturity_compiles_date_value_and_preserves_no_unit() -> None:
    binding = BINDINGS.binding_for('domestic_bond', 'maturity_date')
    assert binding is not None
    assert binding.storage_unit_id is None
    plan = make_plan(
        LogicalScreenOperationV2(predicate=PredicateAtomV2(
            field_concept_id='maturity_date', operator_id=QueryOperatorId.LTE,
            value=TypedSemanticValue(kind='date', date=date(2030, 1, 15)),
            null_policy_id='exclude_missing.v1',
        )),
        family=ProductFamily.DOMESTIC_BOND, binding_ids=(binding.id,),
        qualifiers=QueryQualifiersV2(),
    )
    request = _request(plan)
    assert 'date_value' in request.statement
    assert date(2030, 1, 15) in {decode_contract_value(item.value) for item in request.parameters}
    assert 'applicable_date =' not in request.statement


def _row(metric_id, value, *, unit='percentage_point', applicable_date=date(2026, 8, 22)):
    return {
        'product_id': 'product-a', 'product_name': 'Synthetic product',
        'field_0': value, 'value_status_0': 'present', 'reason_code_0': None,
        'observation_id_0': 'observation-a', 'metric_id_0': metric_id,
        'metric_definition_version_0': '2', 'unit_0': unit, 'currency_0': None,
        'applicable_date_0': applicable_date,
        'evidence_id_0': ['evidence-a'], 'source_id_0': ['source-a'],
    }


def test_one_year_zero_missing_and_definition_version_are_preserved() -> None:
    request = _request(_lookup(RETURN_ID, 'domestic-etf-return-1y.v1', qualifiers=QueryQualifiersV2(period_id='P1Y')))
    row = _row('organizer.pref01n001.cumulative_return_1y', Decimal('0'))
    row['value_status_0'] = 'zero'
    mapped = map_sql_rows(request, [row])
    value = next(field for field in mapped.result_rows[0].fields if field.field_id == RETURN_ID)
    assert value.value.value == Decimal('0')
    assert value.applicable_date == date(2026, 8, 22)
    missing = {**row, 'field_0': None, 'value_status_0': 'missing', 'reason_code_0': 'SOURCE_NULL'}
    mapped_missing = map_sql_rows(request, [missing])
    assert all(field.field_id != RETURN_ID for field in mapped_missing.result_rows[0].fields)
    assert mapped_missing.exclusions[0].reason_code == 'SOURCE_VALUE_MISSING'
    with pytest.raises(SqlResultMappingError, match='RETURNED_METRIC_DEFINITION_OWNERSHIP_MISMATCH'):
        map_sql_rows(request, [{**row, 'metric_definition_version_0': 'invented-version'}])


def test_bond_maturity_result_keeps_future_date_value_and_source_metadata() -> None:
    request = _request(_lookup('maturity_date', 'domestic-bond-maturity-date.v1', family=ProductFamily.DOMESTIC_BOND))
    row = _row('organizer.prbd01n001.maturity_date', date(2030, 1, 15), unit=None, applicable_date=date(2030, 1, 15))
    result = next(field for field in map_sql_rows(request, [row]).result_rows[0].fields if field.field_id == 'maturity_date')
    assert result.value.value == date(2030, 1, 15)
    assert result.unit_id is None
    assert result.applicable_date == date(2030, 1, 15)
    with pytest.raises(SqlResultMappingError, match='RETURNED_UNIT_OWNERSHIP_MISMATCH'):
        map_sql_rows(request, [{**row, 'unit_0': 'iso_date'}])


@pytest.mark.parametrize(('family', 'concept', 'reason'), [
    ('overseas_etf', RETURN_ID, 'SOURCE_ONE_YEAR_RETURN_NOT_PROVIDED'),
    ('public_fund', 'fee_rate', 'PUBLIC_FUND_TOTAL_FEE_DEFINITION_UNVERIFIED'),
])
def test_unavailable_metrics_have_concrete_non_executable_reason(family, concept, reason) -> None:
    binding = BINDINGS.binding_for(family, concept)
    assert binding is not None
    assert binding.availability.value == 'unavailable'
    assert binding.unavailable_reason_code == reason
    assert binding.approved_metric_ids == ()


def test_evidence_lineage_groups_only_the_pinned_dataset_and_approved_metric_predicate() -> None:
    request = _request(_lookup('fee_rate', 'domestic-etf-fee-rate.v1'))
    statement = request.statement
    assert 'evidence_0.predicate_id IN (' in statement
    assert 'evidence_origin_0.dataset_version =' in statement
    assert 'JOIN LATERAL' in statement
    assert 'evidence_origin_0.observation_id = observation_0.observation_id' in statement
    assert 'evidence_0.subject_id = observation_0.entity_id' in statement
    parameters = {item.name: decode_contract_value(item.value) for item in request.parameters}
    predicate_names = tuple(name for name in parameters if name.startswith('lineage_metric_'))
    assert predicate_names
    assert {parameters[name] for name in predicate_names} == {'organizer.pref01n001.total_fee_rate'}
    assert parameters[next(name for name in parameters if name.startswith('lineage_dataset_'))] == ACTIVE_DATASET.dataset_version

from __future__ import annotations

import pytest

from financial_agent.intent.query_contracts import PlanReadiness
from financial_agent.planning.physical_bindings import (
    load_physical_binding_registry, load_semantic_sql_policy_registry,
)

from .test_plan_readiness import PROJECT_ROOT, _assess_plan_readiness, _common, _validate


def condition(field, kind=None, value=None, operator='eq'):
    return {'node_type': 'atom', 'field_concept_id': field, 'operator_id': operator,
            'value': {'kind': kind, kind: value} if kind else None,
            'values': [], 'null_policy_id': 'exclude_missing.v1'}


def assess(payload):
    return _assess_plan_readiness(_validate(payload), load_physical_binding_registry(PROJECT_ROOT),
                                 load_semantic_sql_policy_registry(PROJECT_ROOT))


def japan_equity_fee_presence(*, action='screen', as_of='2026-08-22'):
    payload = _common(action, 'overseas_etf')
    payload['qualifiers']['unit_id'] = 'percent'
    payload['qualifiers']['as_of_date'] = as_of
    fee = condition('fee_rate', 'decimal', '0.5', 'lte')
    fee['value']['unit_id'] = 'percent'
    payload['predicate'] = {'node_type': 'all_of', 'children': [
        condition('region', 'string', 'Japan'), condition('asset_class', 'string', 'Equity'),
        fee, condition('aum', operator='is_present'),
    ]}
    if action == 'rank':
        payload.update(ordering=[{'field_concept_id': 'fee_rate', 'direction': 'asc',
                                  'direction_policy_id': None, 'nulls_policy_id': 'exclude_missing.v1',
                                  'tie_break_policy_id': 'stable-product-id.v1'}],
                       limit=5, limit_policy_id=None)
    return payload


@pytest.mark.parametrize('action', ['screen', 'rank'])
def test_compound_unit_and_date_are_consumed_by_their_applicable_binding(action):
    result = assess(japan_equity_fee_presence(action=action))
    assert result.readiness is PlanReadiness.EXECUTABLE
    assert result.reason_codes == ()
    assert set(result.binding_ids) == {'overseas-etf-region.v1', 'overseas-etf-asset-class.v1',
                                       'overseas-etf-fee-rate.v1', 'overseas-etf-aum.v1'}


def test_presence_condition_still_requires_its_actual_as_of_date():
    result = assess(japan_equity_fee_presence(as_of=None))
    assert result.readiness is PlanReadiness.LIMITED
    assert 'PHYSICAL_REQUIRED_QUALIFIER_MISSING' in result.reason_codes


def test_quantitative_aum_predicate_still_requires_currency_normalization():
    payload = japan_equity_fee_presence(action='rank')
    payload['predicate']['children'][-1] = condition('aum', 'decimal', '10', 'gt')
    result = assess(payload)
    assert result.readiness is PlanReadiness.LIMITED
    assert 'CURRENCY_NORMALIZATION_POLICY_REQUIRED' in result.reason_codes


def test_unsupported_qualifier_and_unmatched_unit_remain_non_executable():
    payload = japan_equity_fee_presence()
    payload['qualifiers']['period_id'] = 'P1Y'
    result = assess(payload)
    assert result.readiness is PlanReadiness.LIMITED
    assert 'PHYSICAL_QUALIFIER_UNSUPPORTED' in result.reason_codes
    payload = japan_equity_fee_presence()
    payload['qualifiers']['unit_id'] = 'USD'
    result = assess(payload)
    assert result.readiness is PlanReadiness.BLOCKED
    assert 'SEMANTIC_UNIT_NOT_SUPPORTED' in result.reason_codes

from __future__ import annotations

from datetime import date
from decimal import Decimal

from financial_agent.contracts.enums import ProductFamily
from financial_agent.contracts.values import decode_contract_value
from financial_agent.intent.query_contracts import (
    PredicateAllOfV2, PredicateAtomV2, QueryOperatorId, QueryQualifiersV2,
    TypedSemanticValue,
)
from financial_agent.planning.logical_query import LogicalScreenOperationV2
from financial_agent.sql.compiler import SemanticSqlCompiler

from .helpers import ACTIVE_DATASET, BINDINGS, PLANNING, POLICIES, make_plan


COMPILER = SemanticSqlCompiler(BINDINGS, POLICIES, PLANNING, ACTIVE_DATASET)


def atom(field, value, operator=QueryOperatorId.EQ):
    return PredicateAtomV2(field_concept_id=field, operator_id=operator,
                         value=value, null_policy_id='exclude_missing.v1')


def request(predicate, binding_ids, family, qualifiers=None):
    plan = make_plan(LogicalScreenOperationV2(predicate=predicate), family=family,
                     binding_ids=binding_ids, qualifiers=qualifiers or QueryQualifiersV2())
    result = COMPILER.compile_task(plan, plan.tasks[0].task_id)
    assert result.request is not None, result.rejection
    return result.request


def test_japan_equity_conditions_lower_to_exact_registered_text_fields():
    compiled = request(PredicateAllOfV2(children=(
        atom('region', TypedSemanticValue(kind='string', string='Japan')),
        atom('asset_class', TypedSemanticValue(kind='string', string='Equity')),
    )), ('overseas-etf-region.v1', 'overseas-etf-asset-class.v1'), ProductFamily.OVERSEAS_ETF)
    values = tuple(decode_contract_value(item.value) for item in compiled.parameters)
    assert 'organizer.pref02n001.investment_region' in values
    assert 'organizer.pref02n001.investment_asset_type' in values
    assert 'Japan' in values and 'Equity' in values
    assert 'Japan' not in compiled.statement and 'Equity' not in compiled.statement
    assert 'text_value =' in compiled.statement
    assert 'value_status IN' in compiled.statement
    assert 'organizer.pref02n001.product_type' in values
    assert 'ETF' in values


def test_bond_currency_grade_and_unexpired_source_conditions_keep_exact_types():
    grade = PredicateAtomV2(field_concept_id='credit_grade', operator_id=QueryOperatorId.IN,
        values=tuple(TypedSemanticValue(kind='string', string=value)
                     for value in ('AAA', 'AA+', 'AA0', 'AA-')),
        null_policy_id='exclude_missing.v1')
    compiled = request(PredicateAllOfV2(children=(
        atom('currency', TypedSemanticValue(kind='string', string='KRW')),
        grade,
        atom('maturity_date', TypedSemanticValue(kind='date', date=date(2026, 8, 24)), QueryOperatorId.GT),
        atom('remaining_days', TypedSemanticValue(kind='decimal', decimal='0', unit_id='day'), QueryOperatorId.GT),
    )), ('domestic-bond-currency.v1', 'domestic-bond-credit-grade.v1',
         'domestic-bond-maturity-date.v1', 'domestic-bond-remaining-days.v1'),
         ProductFamily.DOMESTIC_BOND, QueryQualifiersV2(as_of_date=date(2026, 8, 22)))
    values = tuple(decode_contract_value(item.value) for item in compiled.parameters)
    assert 'organizer.prbd01n001.currency' in values
    assert 'organizer.prbd01n001.credit_grade_representative' in values
    assert 'organizer.prbd01n001.remaining_days' in values
    assert all(value in values for value in ('KRW', 'AAA', 'AA+', 'AA0', 'AA-'))
    assert Decimal('0') in values and date(2026, 8, 24) in values
    assert 'text_value >=' not in compiled.statement
    assert 'text_value IN' in compiled.statement
    assert 'numeric_value >' in compiled.statement


def test_actual_saleability_contract_preserves_day_unit_through_readiness_and_sql():
    from tests.intent.test_personal_condition_predicates import _solve
    from financial_agent.intent.query_contracts import PlanReadiness
    from financial_agent.planning.readiness import assess_plan_readiness

    solved = _solve('현재 판매 가능한 원화채권 중 AA- 이상 종목 알려줘.',
                    ProductFamily.DOMESTIC_BOND,
                    (('availability_status', '판매 가능한'), ('currency', '원화'), ('credit_grade', 'AA-')))
    assert len(solved.complete_candidates) == 1
    contract = solved.complete_candidates[0].contract
    days = next(item for item in contract.predicate.children if item.field_concept_id == 'remaining_days')
    assert days.value.unit_id == 'day'
    assert days.value.decimal == '0'
    # The runtime supplies its verified source date after solving the predicate.
    contract = contract.model_copy(update={'qualifiers': QueryQualifiersV2(as_of_date=date(2026, 8, 21))})
    readiness = assess_plan_readiness(contract, BINDINGS, POLICIES, active_dataset_pin=ACTIVE_DATASET)
    assert readiness.readiness is PlanReadiness.EXECUTABLE, readiness.reason_codes
    compiled = request(contract.predicate, readiness.binding_ids, ProductFamily.DOMESTIC_BOND,
                       contract.qualifiers)
    values = tuple(decode_contract_value(item.value) for item in compiled.parameters)
    lowered_days = next(item for item in compiled.render_manifest.logical_task.operation.predicate.children
                        if item.field_concept_id == 'remaining_days')
    assert lowered_days.value.unit_id == 'day'
    assert Decimal('0') in values
    assert 'numeric_value >' in compiled.statement

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from financial_agent.contracts.enums import ProductFamily
from financial_agent.contracts.execution import ResultField, ResultRow
from financial_agent.contracts.values import encode_contract_value
from financial_agent.intent.query_contracts import (
    ComparisonSpecV2, OrderingDirection, OrderingSpecV2, PredicateAllOfV2,
    PredicateAnyOfV2, PredicateAtomV2, PredicateNotV2, ProjectionSpecV2,
    QueryOperatorId, QueryQualifiersV2, TypedSemanticValue,
)
from financial_agent.planning.logical_query import (
    LogicalCompareOperationV2, LogicalLookupOperationV2,
    LogicalRankOperationV2, LogicalScreenOperationV2,
)
from financial_agent.release.local_semantic_contract import (
    LocalSemanticContractError, validate_semantic_task,
)
from financial_agent.release.local_semantic_results import VerifiedSemanticRow
from financial_agent.sql.compiler import SemanticSqlCompiler
from tests.sql.helpers import ACTIVE_DATASET, BINDINGS, PLANNING, POLICIES, make_plan


COMPILER = SemanticSqlCompiler(BINDINGS, POLICIES, PLANNING, ACTIVE_DATASET)
DATE = date(2026, 8, 24)
FEE = BINDINGS.bindings_by_id['domestic-etf-fee-rate.v1']


def atom(operator='lte', value='0.5', *, field='fee_rate', kind='decimal', values=()):
    scalar = None if value is None else TypedSemanticValue(
        kind=kind, **{kind: value}, unit_id='percent' if field == 'fee_rate' else None,
    )
    return PredicateAtomV2(field_concept_id=field, operator_id=QueryOperatorId(operator),
                           value=scalar, values=values, null_policy_id='exclude_missing.v1')


def request(operation=None, *, bindings=(FEE,), family=ProductFamily.DOMESTIC_ETF,
            qualifiers=None, entities=(), display=None):
    operation = operation or LogicalScreenOperationV2(predicate=atom())
    policy_ids = tuple(dict.fromkeys(
        [b.unit_conversion_policy_id for b in bindings] + ['exclude_missing.v1']
        + (['stable-product-id.v1'] if isinstance(operation, LogicalRankOperationV2) else [])
    ))
    plan = make_plan(operation, family=family, binding_ids=tuple(b.id for b in bindings),
                     policy_ids=policy_ids, qualifiers=qualifiers or QueryQualifiersV2(),
                     entity_refs=entities)
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id, screen_display_limit=display)
    assert outcome.request is not None, outcome.rejection
    return outcome.request


def row(value=Decimal('0.1'), *, product='product-1', binding=FEE, missing=False,
        family=None, actual_date=DATE, currency=None):
    fields = [ResultField(field_id='product_name', value=encode_contract_value('합성 상품'))]
    if not missing:
        fields.append(ResultField(field_id=binding.semantic_concept_id,
                                  value=encode_contract_value(value), unit_id=binding.storage_unit_id,
                                  currency=currency, applicable_date=actual_date))
    fact = {
        'subject_id': product, 'subject_product_family': family or binding.product_family_id.value,
        'metric_id': binding.approved_metric_ids[0], 'evidence_kind': 'observation',
        'observation_date': actual_date, 'observation_currency': currency,
        'observation_unit': binding.storage_unit_id, 'value_status': 'missing' if missing else ('zero' if value == 0 else 'present'),
        'period_end': actual_date, 'period_start': None,
    }
    return VerifiedSemanticRow(
        ResultRow(row_id=f'row-{product}', entity_ids=(product,), fields=tuple(fields)),
        (fact,), ((binding.semantic_concept_id, 'SOURCE_VALUE_MISSING'),) if missing else (),
    )


def check(req, rows, *, count=None, display=3):
    return validate_semantic_task(req, rows, total_count=len(rows) if count is None else count,
                                  display_limit=display)


def test_grounded_but_nonmatching_fee_is_rejected_by_task_contract():
    req = request()
    assert 'local-predicate.v1' in check(req, (row(),))
    with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_PREDICATE_MISMATCH'):
        check(req, (row(Decimal('0.8')),))


def test_every_and_condition_is_checked():
    predicate = PredicateAllOfV2(children=(atom('gte', '0.2'), atom('lte', '0.5')))
    req = request(LogicalScreenOperationV2(predicate=predicate))
    assert check(req, (row(Decimal('0.3')),))
    for value in ('0.1', '0.8'):
        with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_PREDICATE_MISMATCH'):
            check(req, (row(Decimal(value)),))


def test_wrong_subject_or_product_family_is_rejected():
    req = request(entities=('product-1',))
    for wrong in (row(product='product-2'), row(family='overseas_etf'), row(family='unknown')):
        with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_SCOPE_MISMATCH'):
            check(req, (wrong,))


def test_missing_does_not_satisfy_negated_comparison_but_zero_is_present():
    req = request(LogicalScreenOperationV2(predicate=PredicateNotV2(child=atom('gt', '0.5'))))
    assert check(req, (row(Decimal('0')),))
    with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_PREDICATE_MISMATCH'):
        check(req, (row(None, missing=True),))
    missing_req = request(LogicalScreenOperationV2(predicate=atom('is_missing', None)))
    assert check(missing_req, (row(None, missing=True),))


def test_not_or_preserves_sql_presence_guard_for_every_comparison():
    predicate = PredicateNotV2(child=PredicateAnyOfV2(children=(atom('gt', '0.5'), atom('lt', '0.1'))))
    assert check(request(LogicalScreenOperationV2(predicate=predicate)), (row(Decimal('0.3')),))


def test_aum_consumed_date_and_currency_must_match_requested_qualifiers():
    binding = BINDINGS.bindings_by_id['domestic-etf-aum.v1']
    operation = LogicalLookupOperationV2(projections=ProjectionSpecV2(field_concept_ids=('aum',)))
    req = request(operation, bindings=(binding,), qualifiers=QueryQualifiersV2(as_of_date=DATE, currency_id='KRW'))
    assert check(req, (row(Decimal('100'), binding=binding, currency='KRW'),))
    for wrong in (row(binding=binding, currency='USD'),
                  row(binding=binding, currency='KRW', actual_date=date(2026, 8, 23))):
        with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_QUALIFIER_MISMATCH'):
            check(req, (wrong,))


def test_future_maturity_is_a_value_not_an_as_of_constraint():
    binding = BINDINGS.bindings_by_id['domestic-bond-maturity-date.v1']
    operation = LogicalScreenOperationV2(predicate=atom('lte', date(2030, 1, 15), field='maturity_date', kind='date'))
    req = request(operation, bindings=(binding,), family=ProductFamily.DOMESTIC_BOND)
    assert check(req, (row(date(2029, 12, 1), binding=binding, actual_date=date(2029, 12, 1)),))


def ranked_request(limit=3, direction='desc'):
    operation = LogicalRankOperationV2(ordering=(OrderingSpecV2(
        field_concept_id='fee_rate', direction=OrderingDirection(direction),
        nulls_policy_id='exclude_missing.v1', tie_break_policy_id='stable-product-id.v1',
    ),), limit=limit)
    return request(operation)


def test_rank_order_tie_and_limit_are_checked_without_claiming_unseen_population():
    req = ranked_request()
    correct = (row(Decimal('0.5'), product='a'), row(Decimal('0.5'), product='b'), row(Decimal('0.1'), product='c'))
    assert 'local-rank-order.v1' in check(req, correct)
    for wrong in (tuple(reversed(correct)), (correct[1], correct[0], correct[2]),
                  (*correct, row(Decimal('0.01'), product='d')), (row(None, missing=True),)):
        with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_RANK_INVALID'):
            check(req, wrong)
    assert check(req, correct[:1])


@pytest.mark.parametrize('count,display', [(True, 3), (-1, 3), (2, 3), (1, 0), (1, 51)])
def test_invalid_count_or_display_is_rejected(count, display):
    with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_COUNT_INVALID'):
        check(request(), (row(),), count=count, display=display)


def test_bounded_screen_count_is_distinct_from_display_and_requires_complete_display():
    req = request(display=2)
    rows = (row(product='a'), row(product='b'))
    assert check(req, rows, count=10, display=2)
    with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_COUNT_INVALID'):
        check(req, rows[:1], count=10, display=2)
    with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_DUPLICATE_SUBJECT'):
        check(req, (rows[0], rows[0]), count=10, display=2)


@pytest.mark.parametrize('operator,threshold,accepted,rejected', [
    ('eq', '0.2', '0.2', '0.3'), ('neq', '0.2', '0.3', '0.2'),
    ('lt', '0.2', '0.1', '0.2'), ('lte', '0.2', '0.2', '0.3'),
    ('gt', '0.2', '0.3', '0.2'), ('gte', '0.2', '0.2', '0.1'),
    ('between', ('0.1', '0.3'), '0.2', '0.4'),
    ('in', ('0.1', '0.3'), '0.3', '0.2'),
    ('not_in', ('0.1', '0.3'), '0.2', '0.3'),
])
def test_registered_scalar_operators_are_independently_checked(operator, threshold, accepted, rejected):
    values = tuple(TypedSemanticValue(kind='decimal', decimal=value, unit_id='percent')
                   for value in threshold) if isinstance(threshold, tuple) else ()
    predicate = atom(operator, None if values else threshold, values=values)
    req = request(LogicalScreenOperationV2(predicate=predicate))
    assert check(req, (row(Decimal(accepted)),))
    with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_PREDICATE_MISMATCH'):
        check(req, (row(Decimal(rejected)),))


def merge_rows(*rows):
    first = rows[0]
    fields = (first.row.fields[0], *(field for part in rows for field in part.row.fields[1:]))
    return VerifiedSemanticRow(first.row.model_copy(update={'fields': fields}),
                               tuple(fact for part in rows for fact in part.facts),
                               tuple(missing for part in rows for missing in part.missing_fields))


def test_not_or_cannot_turn_a_missing_operand_into_a_match():
    aum = BINDINGS.bindings_by_id['domestic-etf-aum.v1']
    predicate = PredicateNotV2(child=PredicateAnyOfV2(children=(
        atom('gt', '0.5'), atom('lt', '100', field='aum'),
    )))
    req = request(LogicalScreenOperationV2(predicate=predicate), bindings=(FEE, aum),
                  qualifiers=QueryQualifiersV2(as_of_date=DATE))
    correct = merge_rows(row(Decimal('0.3')), row(Decimal('200'), binding=aum))
    assert check(req, (correct,))
    wrong = merge_rows(row(Decimal('0.3')), row(None, binding=aum, missing=True))
    with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_PREDICATE_MISMATCH'):
        check(req, (wrong,))


def test_any_of_preserves_sql_guarded_branch_semantics():
    aum = BINDINGS.bindings_by_id['domestic-etf-aum.v1']
    predicate = PredicateAnyOfV2(children=(atom('lte', '0.5'), atom('gt', '100', field='aum')))
    req = request(LogicalScreenOperationV2(predicate=predicate), bindings=(FEE, aum),
                  qualifiers=QueryQualifiersV2(as_of_date=DATE))
    matching = merge_rows(row(Decimal('0.3')), row(None, binding=aum, missing=True))
    assert check(req, (matching,))


def test_qualifier_unit_is_consumed_only_by_its_compatible_binding():
    aum = BINDINGS.bindings_by_id['domestic-etf-aum.v1']
    operation = LogicalLookupOperationV2(projections=ProjectionSpecV2(field_concept_ids=('fee_rate', 'aum')))
    req = request(operation, bindings=(FEE, aum),
                  qualifiers=QueryQualifiersV2(as_of_date=DATE, unit_id='percent'))
    correct = merge_rows(row(), row(Decimal('100'), binding=aum))
    assert check(req, (correct,))
    altered = replace(correct, facts=({**correct.facts[0], 'observation_unit': 'fraction'}, correct.facts[1]))
    with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_QUALIFIER_MISMATCH'):
        check(req, (altered,))


def test_return_p1y_does_not_require_synthesized_period_start():
    binding = BINDINGS.bindings_by_id['domestic-etf-return-1y.v1']
    operation = LogicalLookupOperationV2(projections=ProjectionSpecV2(
        field_concept_ids=('trailing_1y_historical_cumulative_return',)))
    req = request(operation, bindings=(binding,), qualifiers=QueryQualifiersV2(period_id='P1Y'))
    correct = row(Decimal('10'), binding=binding)
    assert check(req, (correct,))
    wrong = replace(correct, facts=({**correct.facts[0], 'period_end': date(2026, 8, 23)},))
    with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_QUALIFIER_MISMATCH'):
        check(req, (wrong,))


def test_lookup_projection_cannot_be_silently_omitted_or_added():
    operation = LogicalLookupOperationV2(projections=ProjectionSpecV2(field_concept_ids=('fee_rate',)))
    req = request(operation)
    assert check(req, (row(None, missing=True),))
    correct = row()
    wrong = replace(correct, row=correct.row.model_copy(update={'fields': correct.row.fields[:1]}))
    with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_FIELD_MISMATCH'):
        check(req, (wrong,))


def test_compare_returns_only_the_requested_subjects():
    operation = LogicalCompareOperationV2(comparison=ComparisonSpecV2(
        subject_refs=('a', 'b'), metric_concept_ids=('fee_rate',),
        basis_policy_id='same-definition-period-unit.v1',
    ))
    req = request(operation)
    assert check(req, (row(product='a'), row(product='b')))
    with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_SCOPE_MISMATCH'):
        check(req, (row(product='c'),))


def test_bound_prior_scope_is_checked_against_resolved_product_ids():
    from financial_agent.contracts.execution import BindingValue
    from financial_agent.sql.compiler import SemanticSqlRuntimeBinder
    from tests.orchestration.test_semantic_graph import SQL_COMPILER, sql_dependency_compilation
    from tests.sql.test_prior_result_binding import _dependency_result

    plan = sql_dependency_compilation().logical_query_plan
    deferred = SQL_COMPILER.compile_task(plan, plan.tasks[1].task_id).request
    binding = BindingValue(binding_name='result-set-1', value_type='semantic-result:many',
                           value=encode_contract_value(('product-1',)))
    bound = SemanticSqlRuntimeBinder(SQL_COMPILER).bind(
        deferred, plan, (binding,), dependency_results=(_dependency_result(plan, binding),))
    aum = BINDINGS.bindings_by_id['domestic-etf-aum.v1']
    assert check(bound, (row(Decimal('100'), binding=aum, currency='KRW'),))
    with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_SCOPE_MISMATCH'):
        check(bound, (row(Decimal('100'), product='other', binding=aum, currency='KRW'),))


def test_ascending_rank_and_second_ordering_field_are_checked():
    assert check(ranked_request(direction='asc'), (row(Decimal('0.1'), product='a'), row(Decimal('0.2'), product='b')))
    aum = BINDINGS.bindings_by_id['domestic-etf-aum.v1']
    operation = LogicalRankOperationV2(ordering=(
        OrderingSpecV2(field_concept_id='fee_rate', direction=OrderingDirection.ASC,
                       nulls_policy_id='exclude_missing.v1', tie_break_policy_id='stable-product-id.v1'),
        OrderingSpecV2(field_concept_id='aum', direction=OrderingDirection.DESC,
                       nulls_policy_id='exclude_missing.v1', tie_break_policy_id='stable-product-id.v1'),
    ), limit=3)
    req = request(operation, bindings=(FEE, aum), qualifiers=QueryQualifiersV2(as_of_date=DATE))
    rows = tuple(merge_rows(row(product=product), row(Decimal(value), product=product, binding=aum))
                 for product, value in (('b', '200'), ('a', '100')))
    assert check(req, rows)
    with pytest.raises(LocalSemanticContractError, match='LOCAL_RESULT_RANK_INVALID'):
        check(req, tuple(reversed(rows)))


def test_empty_verified_result_has_zero_count():
    assert check(request(), (), count=0)
    assert check(request(display=2), (), count=0, display=2)

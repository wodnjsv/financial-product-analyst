from __future__ import annotations

from datetime import date
from decimal import Decimal
import json

import pytest
from pydantic import ValidationError

from financial_agent.contracts.enums import ProductFamily
from financial_agent.contracts.values import decode_contract_value
from financial_agent.intent.query_contracts import (
    PredicateAllOfV2, PredicateAtomV2, ProjectionSpecV2, QueryOperatorId,
    QueryQualifiersV2, TypedSemanticValue,
)
from financial_agent.planning.logical_query import LogicalLookupOperationV2, LogicalScreenOperationV2
from financial_agent.sql.compiler import SemanticSqlCompiler
from financial_agent.sql.contracts import CompiledSqlRequest, PhysicalSqlRenderManifest
from financial_agent.sql.result_mapping import SqlResultMappingError, map_sql_rows

from .helpers import ACTIVE_DATASET, BINDINGS, PLANNING, POLICIES, make_plan


COMPILER = SemanticSqlCompiler(BINDINGS, POLICIES, PLANNING, ACTIVE_DATASET)


def region_plan():
    return make_plan(LogicalScreenOperationV2(predicate=PredicateAtomV2(
        field_concept_id='region', operator_id=QueryOperatorId.EQ,
        value=TypedSemanticValue(kind='string', string='Japan'), null_policy_id='exclude_missing.v1',
    )), family=ProductFamily.OVERSEAS_ETF, binding_ids=('overseas-etf-region.v1',),
        qualifiers=QueryQualifiersV2())


def request(*, limit=2, plan=None):
    plan = plan or region_plan()
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id, screen_display_limit=limit)
    assert outcome.request is not None, outcome.rejection
    return outcome.request


def row(index, total=3):
    return {'product_id': f'product-{index}', 'product_name': f'합성 ETF {index}',
            'field_0': 'Japan', 'observation_id_0': f'observation-{index}',
            'metric_id_0': 'organizer.pref02n001.investment_region',
            'metric_definition_version_0': '2', 'unit_0': None, 'currency_0': None,
            'applicable_date_0': date(2026, 7, 15), 'evidence_id_0': [f'evidence-{index}'],
            'source_id_0': ['source-1'], 'screen_population_count': total}


def test_full_count_is_distinct_and_limit_is_parameterized_manifest_owned():
    compiled = request()
    assert compiled.render_manifest.screen_display_limit == 2
    assert 'count(*) OVER ()' in compiled.statement
    assert 'screen_population' in compiled.statement and 'screen_display' in compiled.statement
    assert 'DISTINCT ON (catalog.product.entity_id)' in compiled.statement
    assert 'ORDER BY screen_population.product_id ASC' in compiled.statement
    parameters = {item.name: decode_contract_value(item.value) for item in compiled.parameters}
    limit = next(name for name in parameters if name.startswith('screen_display_limit_'))
    assert parameters[limit] == 2
    assert f'LIMIT :{limit}' in compiled.statement
    assert 'Japan' not in compiled.statement
    restored = CompiledSqlRequest.model_validate_json(compiled.model_dump_json())
    assert restored.statement == compiled.statement
    COMPILER.validate_request_for_execution(restored, region_plan())
    manifest = compiled.render_manifest.model_dump(mode='json')
    manifest['screen_display_limit'] = 3
    with pytest.raises(ValidationError, match='SQL_RENDER_MANIFEST_ID_MISMATCH'):
        PhysicalSqlRenderManifest.model_validate_json(json.dumps(manifest))


@pytest.mark.parametrize('limit', [0, 51, True, 1.5])
def test_display_limit_is_bounded_before_execution(limit):
    plan = region_plan()
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id, screen_display_limit=limit)
    assert outcome.request is None
    assert outcome.rejection.code == 'SQL_BOUNDED_SCREEN_LIMIT_INVALID'


def test_display_limit_is_rejected_for_non_screen_operation():
    plan = make_plan(LogicalLookupOperationV2(projections=ProjectionSpecV2(field_concept_ids=('region',))),
                     family=ProductFamily.OVERSEAS_ETF, binding_ids=('overseas-etf-region.v1',),
                     qualifiers=QueryQualifiersV2())
    outcome = COMPILER.compile_task(plan, plan.tasks[0].task_id, screen_display_limit=2)
    assert outcome.request is None
    assert outcome.rejection.code == 'SQL_BOUNDED_SCREEN_SCOPE_INVALID'


def test_bounded_display_materializes_population_count_before_evidence_hydration():
    assert 'screen_display AS MATERIALIZED' in request().statement
    assert 'screen_display AS MATERIALIZED' not in request(limit=None).statement


def test_bounded_rows_keep_total_and_only_displayed_lineage():
    mapped = map_sql_rows(request(), [row(2), row(1)])
    assert mapped.screen_population_count == 3
    assert len(mapped.result_rows) == 2
    assert tuple(item.entity_ids for item in mapped.result_rows) == (('product-1',), ('product-2',))
    assert 'evidence:evidence-1' in mapped.evidence_refs
    assert 'evidence:evidence-3' not in mapped.evidence_refs
    empty = map_sql_rows(request(), [])
    assert empty.screen_population_count == 0 and empty.result_rows == ()
    ordinary_row = row(1)
    ordinary_row.pop('screen_population_count')
    assert map_sql_rows(request(limit=None), [ordinary_row]).screen_population_count is None


@pytest.mark.parametrize('count', [None, False, 1.5, '3', [], -1, 1])
def test_invalid_or_underreported_count_is_rejected(count):
    with pytest.raises(SqlResultMappingError, match='SCREEN_POPULATION_COUNT_INVALID'):
        map_sql_rows(request(), [row(1, count), row(2, count)])


def test_inconsistent_count_missing_display_rows_and_duplicate_products_are_rejected():
    for rows, code in (([row(1, 3), row(2, 4)], 'SCREEN_POPULATION_COUNT_MISMATCH'),
                       ([row(1, 3)], 'SCREEN_DISPLAY_CARDINALITY_MISMATCH'),
                       ([row(1, 3), row(2, 3), row(3, 3)], 'SCREEN_DISPLAY_CARDINALITY_MISMATCH'),
                       ([row(1, 3), {**row(2, 3), 'product_id': 'product-1'}], 'RETURNED_DUPLICATE_ROW')):
        with pytest.raises(SqlResultMappingError, match=code):
            map_sql_rows(request(), rows)


def japan_equity_plan():
    def atom(field, value, operator=QueryOperatorId.EQ):
        return PredicateAtomV2(field_concept_id=field, operator_id=operator, value=value,
                               null_policy_id='exclude_missing.v1')
    return make_plan(LogicalScreenOperationV2(predicate=PredicateAllOfV2(children=(
        atom('region', TypedSemanticValue(kind='string', string='Japan')),
        atom('asset_class', TypedSemanticValue(kind='string', string='Equity')),
        atom('fee_rate', TypedSemanticValue(kind='decimal', decimal='0.5', unit_id='percent'), QueryOperatorId.LTE),
        atom('aum', None, QueryOperatorId.IS_PRESENT),
    ))), family=ProductFamily.OVERSEAS_ETF,
        binding_ids=('overseas-etf-region.v1', 'overseas-etf-asset-class.v1',
                     'overseas-etf-fee-rate.v1', 'overseas-etf-aum.v1'),
        policy_ids=('identity-unit.v1', 'semantic-percent-to-percentage-point.v1', 'exclude_missing.v1'),
        qualifiers=QueryQualifiersV2(unit_id='percent', as_of_date=date(2026, 8, 22)))


def test_original_japan_equity_fee_aum_presence_uses_metric_specific_unit_and_date():
    compiled = request(plan=japan_equity_plan())
    values = tuple(decode_contract_value(item.value) for item in compiled.parameters)
    assert 'percentage_point' in values
    assert 'amount' not in values
    field_units = {record.binding_id for record in compiled.lowering_records
                   if record.semantic_path == 'qualifiers.unit'}
    assert field_units == {'overseas-etf-fee-rate.v1'}
    raw = row(1, total=1)
    for index, (metric, value, unit, applicable_date) in enumerate((
        ('investment_asset_type', 'Equity', None, date(2026, 7, 15)),
        ('total_fee_rate', Decimal('0.5'), 'percentage_point', None),
        ('aum', Decimal('123'), 'amount', date(2026, 8, 22)),
    ), 1):
        raw.update({f'field_{index}': value, f'observation_id_{index}': f'observation-{index+1}',
                    f'metric_id_{index}': f'organizer.pref02n001.{metric}',
                    f'metric_definition_version_{index}': '2', f'unit_{index}': unit,
                    f'currency_{index}': 'USD' if metric == 'aum' else None,
                    f'applicable_date_{index}': applicable_date,
                    f'evidence_id_{index}': [f'evidence-{index+1}'], f'source_id_{index}': ['source-1']})
    mapped = map_sql_rows(compiled, [raw])
    assert len(mapped.result_rows) == 1
    with pytest.raises(SqlResultMappingError, match='RETURNED_DATE_OWNERSHIP_MISMATCH'):
        map_sql_rows(compiled, [{**raw, 'applicable_date_3': date(2026, 8, 21)}])

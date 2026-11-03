from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from financial_agent.contracts.execution import ResultField, ResultRow
from financial_agent.contracts.values import encode_contract_value
from financial_agent.intent.query_contracts import RelationConditionV2
from financial_agent.planning.physical_bindings import load_physical_binding_registry
from financial_agent.release.local_semantic_results import LocalSemanticResultError, validate_semantic_rows
from tests.intent.test_personal_search_results import (
    CUTOFF, DATASET, DATE, REFS, RELATION_REFS, fact, relation_fact, row, validate, validate_relation,
)


def test_duplicate_product_is_rejected_even_when_row_ids_differ():
    second = row().model_copy(update={'row_id': 'row-2'})
    with pytest.raises(LocalSemanticResultError):
        validate((row(), second), (fact(),))


def test_duplicate_row_id_is_rejected_even_when_products_differ():
    second = row().model_copy(update={'entity_ids': ('product-2',)})
    second_fact = fact(subject_id='product-2', entity_id='product-2',
                       evidence_id='evidence-2', observation_id='observation-2')
    refs = REFS + ('evidence:evidence-2', 'observation:observation-2')
    with pytest.raises(LocalSemanticResultError):
        validate((row(), second), (fact(), second_fact), refs)


def test_duplicate_field_id_is_rejected_before_fact_rendering():
    source = row()
    duplicate = source.model_copy(update={'fields': (*source.fields, source.fields[1])})
    with pytest.raises(LocalSemanticResultError):
        validate((duplicate,), (fact(),))


@pytest.mark.parametrize('field', ['published_at', 'available_at', 'vintage_date'])
def test_source_instant_on_next_seoul_day_is_after_cutoff(field):
    # 15:00 UTC is midnight on the next day in Seoul.
    with pytest.raises(LocalSemanticResultError):
        validate((row(),), (fact(**{field: datetime(2026, 8, 24, 15, tzinfo=UTC)}),))


@pytest.mark.parametrize('field', ['published_at', 'available_at', 'vintage_date'])
def test_last_instant_of_seoul_cutoff_day_remains_eligible(field):
    instant = datetime(2026, 8, 24, 14, 59, 59, tzinfo=UTC)
    assert len(validate((row(),), (fact(**{field: instant}),))) == 1


@pytest.mark.parametrize('field', ['published_at', 'available_at', 'vintage_date'])
def test_naive_source_datetime_is_not_assumed_to_be_seoul(field):
    with pytest.raises(LocalSemanticResultError):
        validate((row(),), (fact(**{field: datetime(2026, 8, 24, 12)}),))


@pytest.mark.parametrize('field', ['published_at', 'available_at', 'vintage_date', 'applicable_date'])
def test_relation_source_cutoff_uses_seoul_day(field):
    with pytest.raises(LocalSemanticResultError):
        validate_relation((relation_fact(**{field: datetime(2026, 8, 24, 15, tzinfo=UTC)}),))


@pytest.mark.parametrize('field', ['published_at', 'available_at', 'vintage_date', 'applicable_date'])
def test_relation_rejects_naive_source_datetime(field):
    with pytest.raises(LocalSemanticResultError):
        validate_relation((relation_fact(**{field: datetime(2026, 8, 24, 12)}),))


def test_source_cutoff_conversion_uses_offset_without_changing_original_fact():
    instant = datetime(2026, 8, 24, 23, 59, 59, tzinfo=timezone(timedelta(hours=9)))
    source = fact(published_at=instant)
    assert len(validate((row(),), (source,))) == 1
    assert source['published_at'] is instant


@pytest.mark.parametrize('changes', [
    {'publisher_type': 'organizer'}, {'source_type': 'web'},
    {'authority_tier': 'organizer'}, {'subject_product_family': 'public_fund'},
    {'subject_product_family': 'unknown'},
    {'subject_product_family': ['domestic_etf']},
])
def test_holding_relation_requires_the_approved_source_for_its_family(changes):
    with pytest.raises(LocalSemanticResultError):
        validate_relation((relation_fact(**changes),))


def test_overseas_holding_relation_accepts_regulator_dataset_authority():
    assert len(validate_relation((relation_fact(subject_product_family='overseas_etf',
                                              publisher='synthetic-sec', publisher_type='regulator'),))) == 1
    with pytest.raises(LocalSemanticResultError):
        validate_relation((relation_fact(subject_product_family='overseas_etf'),))


def managed_by_fact(**changes):
    return relation_fact(predicate_id='managedBy', relation_predicate_id='managedBy',
        relation_object_id='manager-1', relation_object_name='합성 운용사',
        value_or_object_id={'type': 'string', 'value': 'manager-1'},
        publisher='synthetic-organizer', publisher_type='organizer', authority_tier='organizer',
        source_locator_root='prfd01n001_data.xlsx', locator_uri_or_object_key='prfd01n001_data.xlsx',
        **changes)


def validate_managed_by(source):
    condition = RelationConditionV2(relation_id='managedBy', object_entity_id='manager-1',
                                    object_ontology_type_id='AssetManager')
    name_only = row().model_copy(update={'fields': row().fields[:1]})
    return validate_semantic_rows((name_only,), (source,), RELATION_REFS, (), DATASET, CUTOFF,
                                 relation_conditions=(condition,), as_of_date=DATE)


def test_managed_by_preserves_cross_role_organizer_workbook_origin():
    assert len(validate_managed_by(managed_by_fact())) == 1


@pytest.mark.parametrize('changes', [
    {'publisher_type': 'exchange'}, {'source_type': 'web'},
    {'authority_tier': 'official'}, {'subject_product_family': 'unknown'},
    {'subject_product_family': ['domestic_etf']},
])
def test_managed_by_requires_organizer_source_metadata(changes):
    source = managed_by_fact()
    source.update(changes)
    with pytest.raises(LocalSemanticResultError):
        validate_managed_by(source)


@pytest.mark.parametrize('changes', [
    {'publisher': None}, {'publisher': ' '},
    {'publisher_type': 'asset_manager'}, {'publisher_type': None},
    {'source_type': 'web'}, {'source_type': None},
    {'authority_tier': 'official'}, {'authority_tier': None},
    {'content_checksum': None}, {'content_checksum': 'not-a-checksum'},
    {'content_checksum': 'A' * 64}, {'content_checksum': 'a' * 63},
    {'subject_product_family': 'public_fund'},
    {'locator_column': 'du_last_aum'},
    {'source_locator_root': 'pref02n001_data.xlsx', 'locator_uri_or_object_key': 'pref02n001_data.xlsx'},
])
def test_organizer_metric_requires_its_registered_source_ownership(changes):
    with pytest.raises(LocalSemanticResultError):
        validate((row(),), (fact(**changes),))


def test_source_ownership_does_not_replace_null_or_zero():
    from tests.intent.test_personal_search_results import MISSING, missing_fact, name_only_row

    zero = validate((row(Decimal('0')),), (fact(numeric_value=Decimal('0'),
                    normalized_value={'type': 'decimal', 'value': '0'}, value_status='zero'),))
    assert zero[0].row.fields[1].value.value == 0
    absent = validate((name_only_row(),), (missing_fact(),), exclusions=(MISSING,))
    assert absent[0].missing_fields == (('fee_rate', 'SOURCE_VALUE_MISSING'),)


def test_future_maturity_is_a_value_not_an_after_cutoff_publication():
    binding = load_physical_binding_registry(Path(__file__).resolve().parents[2]).bindings_by_id['domestic-bond-maturity-date.v1']
    maturity = date(2045, 1, 1)
    metric = binding.approved_metric_ids[0]
    result = ResultRow(row_id='row-bond', entity_ids=('product-1',), fields=(
        ResultField(field_id='product_name', value=encode_contract_value('합성 ETF')),
        ResultField(field_id='maturity_date', value=encode_contract_value(maturity),
                    applicable_date=maturity),
    ))
    source = fact(predicate_id=metric, metric_id=metric,
        normalized_value={'type': 'date', 'value': maturity.isoformat()},
        numeric_value=None, date_value=maturity,
        unit=None, observation_unit=None,
        applicable_date=None, observation_date=maturity,
        source_locator_root='prbd01n001_data.xlsx',
        locator_uri_or_object_key='prbd01n001_data.xlsx',
        subject_product_family='domestic_bond', locator_column='mat_dt')
    refs = ('evidence:evidence-1', 'source:source-1', 'observation:observation-1',
            f'metric-definition:{metric}:2')
    verified = validate_semantic_rows((result,), (source,), refs, (binding,), DATASET, CUTOFF)
    assert verified[0].row.fields[1].value.value == maturity
    source['published_at'] = datetime(2026, 8, 24, 15, tzinfo=UTC)
    with pytest.raises(LocalSemanticResultError):
        validate_semantic_rows((result,), (source,), refs, (binding,), DATASET, CUTOFF)

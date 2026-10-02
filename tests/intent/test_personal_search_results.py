from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from financial_agent.contracts.execution import Exclusion, ResultField, ResultRow
from financial_agent.contracts.values import encode_contract_value
from financial_agent.planning.physical_bindings import load_physical_binding_registry
from financial_agent.intent.query_contracts import RelationConditionV2
from financial_agent.release.local_semantic_results import (
    LocalSemanticResultError, validate_semantic_rows, render_semantic_rows,
)


ROOT = Path(__file__).resolve().parents[2]
DATASET = 'dataset-v1'
CUTOFF = date(2026, 8, 24)
DATE = date(2026, 8, 22)
BINDING = load_physical_binding_registry(ROOT).bindings_by_id['domestic-etf-fee-rate.v1']


def row(value=Decimal('0.1')):
    return ResultRow(row_id='row-1', entity_ids=('product-1',), fields=(
        ResultField(field_id='product_name', value=encode_contract_value('합성 ETF')),
        ResultField(field_id='fee_rate', value=encode_contract_value(value),
                    unit_id='percentage_point', applicable_date=DATE),
    ))


def fact(**changes):
    return {
        'dataset_version': DATASET, 'evidence_id': 'evidence-1', 'source_id': 'source-1',
        'evidence_kind': 'observation', 'subject_id': 'product-1',
        'predicate_id': 'organizer.pref01n001.total_fee_rate',
        'normalized_value': {'type': 'decimal', 'value': '0.1'},
        'unit': 'percentage_point', 'currency': None, 'applicable_date': DATE,
        'vintage_date': DATE, 'published_at': None, 'available_at': None,
        'cutoff_status': 'eligible', 'eligible_for_claim': True,
        'source_title': '합성 상품 마스터', 'source_locator_root': 'synthetic.xlsx',
        'locator_uri_or_object_key': 'synthetic.xlsx', 'locator_sheet': 'ETF',
        'locator_row': 2, 'locator_column': 'cu_charge_rt',
        'canonical_name': '합성 ETF', 'observation_id': 'observation-1',
        'entity_id': 'product-1', 'metric_id': 'organizer.pref01n001.total_fee_rate',
        'metric_definition_version': '2', 'value_status': 'present',
        'numeric_value': Decimal('0.1'), 'date_value': None,
        'observation_unit': 'percentage_point', 'observation_currency': None,
        'observation_date': DATE, 'period_start': None, 'period_end': None,
        'relation_id': None, **changes,
    }


REFS = ('evidence:evidence-1', 'source:source-1', 'observation:observation-1',
        'metric-definition:organizer.pref01n001.total_fee_rate:2')


def validate(rows, facts, refs=REFS, *, exclusions=()):
    return validate_semantic_rows(rows, facts, refs, (BINDING,), DATASET, CUTOFF,
                                 exclusions=exclusions)


def test_verified_fee_preserves_percent_value_and_exact_source():
    verified = validate((row(),), (fact(),))
    text = render_semantic_rows(verified, total_count=1, display_limit=3, ranked=False)
    assert '전체 일치 1건 · 표시 1건' in text
    assert '0.1%' in text
    assert '2026-08-22' in text
    assert '시트=ETF · 행=2 · 열=cu_charge_rt' in text
    assert 'organizer.pref01n001.total_fee_rate:2' in text


@pytest.mark.parametrize('changes', [
    {'dataset_version': 'other'}, {'subject_id': 'other'}, {'entity_id': 'other'},
    {'metric_definition_version': '1'}, {'unit': 'fraction'},
    {'numeric_value': Decimal('0.001')},
    {'normalized_value': {'type': 'decimal', 'value': '0.001'}},
    {'observation_date': date(2026, 8, 21)}, {'cutoff_status': 'after_cutoff'},
    {'eligible_for_claim': False}, {'canonical_name': '다른 상품'},
    {'vintage_date': date(2026, 8, 25)}, {'locator_column': None},
    {'period_end': date(2027, 8, 22)}, {'source_title': None},
    {'locator_uri_or_object_key': 'other.xlsx'},
])
def test_tampered_evidence_never_releases_facts(changes):
    with pytest.raises(LocalSemanticResultError):
        validate((row(),), (fact(**changes),))


def test_evidence_from_other_returned_product_cannot_support_this_row():
    with pytest.raises(LocalSemanticResultError):
        validate((row(),), (fact(subject_id='product-2', entity_id='product-2'),))


def test_missing_lineage_is_rejected():
    with pytest.raises(LocalSemanticResultError):
        validate((row(),), (fact(),), refs=REFS[:2])


def test_zero_is_supported_and_not_replaced_with_missing():
    verified = validate((row(Decimal('0')),), (fact(
        normalized_value={'type': 'decimal', 'value': '0'},
        numeric_value=Decimal('0'), value_status='zero',
    ),))
    assert '0%' in render_semantic_rows(verified, total_count=1, display_limit=3, ranked=False)


@pytest.mark.parametrize('value,expected', [
    (Decimal('0E-12'), '0'),
    (Decimal('0.100000000000'), '0.1'),
    (Decimal('10.000000000000'), '10'),
    (Decimal('1E+12'), '1000000000000'),
    (Decimal('1.123456789012000'), '1.123456789012'),
])
def test_decimal_text_preserves_precision_without_exponents_or_fractional_zeroes(value, expected):
    verified = validate((row(value),), (fact(
        numeric_value=value, normalized_value={'type': 'decimal', 'value': expected},
        value_status='zero' if value == 0 else 'present',
    ),))
    text = render_semantic_rows(verified, total_count=1, display_limit=1, ranked=False)
    assert f'총보수: {expected}%' in text
    assert verified[0].row.fields[1].value.value == value


def test_display_cap_does_not_change_full_match_count():
    verified = validate((row(),), (fact(),))
    text = render_semantic_rows(verified * 3, total_count=3, display_limit=1, ranked=False)
    assert '전체 일치 3건 · 표시 1건' in text
    text = render_semantic_rows(verified * 3, total_count=3, display_limit=1, ranked=True)
    assert '상위 결과 3건 · 표시 1건' in text
    assert '전체 일치' not in text


def test_empty_screen_has_explicit_zero_count():
    assert validate((), ()) == ()
    assert '전체 일치 0건' in render_semantic_rows((), total_count=0, display_limit=3, ranked=False)


MISSING = Exclusion(subject_id='product-1', rule_id='exclude_missing.v1',
                    reason_code='SOURCE_VALUE_MISSING')


def missing_fact(**changes):
    return fact(value_status='missing', numeric_value=None,
                normalized_value={'type': 'null', 'value': None}, **changes)


def name_only_row():
    return row().model_copy(update={'fields': row().fields[:1]})


def test_verified_missing_lookup_preserves_name_source_and_missing_reason():
    verified = validate((name_only_row(),), (missing_fact(),), exclusions=(MISSING,))
    text = render_semantic_rows(verified, total_count=1, display_limit=3, ranked=False)
    assert '합성 ETF' in text
    assert '총보수: 미제공 (SOURCE_VALUE_MISSING)' in text
    assert 'synthetic.xlsx' in text
    assert '시트=ETF · 행=2 · 열=cu_charge_rt' in text
    assert '총보수: 0%' not in text
    assert 'None%' not in text


@pytest.mark.parametrize('changes', [
    {'metric_id': 'other-metric'}, {'metric_definition_version': '1'},
    {'numeric_value': Decimal('0')},
    {'normalized_value': {'type': 'decimal', 'value': '0'}},
    {'unit': 'fraction'}, {'cutoff_status': 'after_cutoff'},
])
def test_missing_exclusion_cannot_bypass_observation_validation(changes):
    item = missing_fact()
    item.update(changes)
    with pytest.raises(LocalSemanticResultError):
        validate((name_only_row(),), (item,), exclusions=(MISSING,))


def test_missing_lineage_needs_the_matching_exclusion():
    with pytest.raises(LocalSemanticResultError):
        validate((name_only_row(),), (missing_fact(),))
    other = MISSING.model_copy(update={'subject_id': 'product-2'})
    with pytest.raises(LocalSemanticResultError):
        validate((name_only_row(),), (missing_fact(),), exclusions=(other,))
    with pytest.raises(LocalSemanticResultError):
        validate((name_only_row(),), (missing_fact(),), refs=REFS[:2], exclusions=(MISSING,))


def test_bare_name_only_row_does_not_turn_present_or_absent_facts_into_missing():
    with pytest.raises(LocalSemanticResultError):
        validate((name_only_row(),), (fact(),), exclusions=(MISSING,))
    with pytest.raises(LocalSemanticResultError):
        validate((name_only_row(),), (), exclusions=(MISSING,))


def test_null_field_is_not_released_as_a_verified_numeric_field():
    null_field = row().fields[1].model_copy(update={'value': encode_contract_value(None)})
    null_row = row().model_copy(update={'fields': (row().fields[0], null_field)})
    with pytest.raises(LocalSemanticResultError):
        validate((null_row,), (missing_fact(),), exclusions=(MISSING,))


def test_missing_exclusion_cannot_release_an_unregistered_field():
    extra = ResultField(field_id='unverified', value=encode_contract_value(Decimal('1')))
    unverified = name_only_row().model_copy(update={'fields': (row().fields[0], extra)})
    with pytest.raises(LocalSemanticResultError):
        validate((unverified,), (missing_fact(),), exclusions=(MISSING,))


def test_partial_lookup_keeps_present_values_separate_from_missing_fields():
    aum = load_physical_binding_registry(ROOT).bindings_by_id['domestic-etf-aum.v1']
    metric = aum.approved_metric_ids[0]
    absent = missing_fact()
    absent.update(evidence_id='evidence-2', observation_id='observation-2',
                  metric_id=metric, predicate_id=metric,
                  unit=aum.storage_unit_id, observation_unit=aum.storage_unit_id)
    refs = REFS + ('evidence:evidence-2', 'observation:observation-2',
                   f'metric-definition:{metric}:2')
    verified = validate_semantic_rows((row(),), (fact(), absent), refs, (BINDING, aum),
                                     DATASET, CUTOFF, exclusions=(MISSING,))
    text = render_semantic_rows(verified, total_count=1, display_limit=1, ranked=False)
    assert '총보수: 0.1%' in text
    assert '순자산: 미제공 (SOURCE_VALUE_MISSING)' in text


RELATION = RelationConditionV2(relation_id='holdsSecurity', object_entity_id='security-1',
                               object_ontology_type_id='Security')
RELATION_REFS = ('evidence:evidence-1', 'source:source-1', 'relation:relation-1')


def relation_fact(**changes):
    payload = fact(evidence_kind='relation', predicate_id='holdsSecurity',
                value_or_object_id={'type': 'string', 'value': 'security-1'},
                normalized_value={'type': 'string', 'value': 'code=005930;name=합성 종목'},
                relation_id='relation-1', relation_subject_id='product-1',
                relation_predicate_id='holdsSecurity', relation_object_id='security-1',
                relation_object_name='합성 종목', relation_valid_from=DATE, relation_valid_to=DATE,
                metric_id=None)
    payload.update(changes)
    return payload


def validate_relation(facts, refs=RELATION_REFS, as_of=DATE):
    name_only = row().model_copy(update={'fields': row().fields[:1]})
    return validate_semantic_rows((name_only,), facts, refs, (), DATASET, CUTOFF,
                                 relation_conditions=(RELATION,), as_of_date=as_of)


def test_holding_relation_uses_object_id_and_not_description():
    verified = validate_relation((relation_fact(),))
    text = render_semantic_rows(verified, total_count=1, display_limit=3, ranked=False)
    assert '보유 종목: 합성 종목' in text
    assert '관계 출처: 합성 상품 마스터' in text
    assert 'None:None' not in text


@pytest.mark.parametrize('changes', [
    {'relation_subject_id': 'other'}, {'relation_object_id': 'other'},
    {'value_or_object_id': {'type': 'string', 'value': 'other'}},
    {'relation_valid_to': date(2026, 8, 21)},
    {'source_title': ''}, {'eligible_for_claim': False},
])
def test_invalid_relation_evidence_is_rejected(changes):
    with pytest.raises(LocalSemanticResultError):
        validate_relation((relation_fact(**changes),))


def test_holding_date_and_relation_lineage_are_required():
    with pytest.raises(LocalSemanticResultError):
        validate_relation((relation_fact(),), as_of=None)
    with pytest.raises(LocalSemanticResultError):
        validate_relation((relation_fact(),), refs=RELATION_REFS[:2])

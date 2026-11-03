from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

import pytest

from financial_agent.contracts.execution import ResultField, ResultRow
from financial_agent.contracts.values import encode_contract_value
from financial_agent.intent.query_contracts import SemanticValueKind
from financial_agent.planning.physical_bindings import (
    ObservationValueColumn, PhysicalBindingDefinition, load_physical_binding_registry,
)
from financial_agent.release.local_semantic_results import (
    LocalSemanticResultError, render_semantic_rows, validate_semantic_rows,
)

from .test_personal_search_results import CUTOFF, DATASET, DATE, fact


ROOT = Path(__file__).resolve().parents[2]


def fixture(binding, value, column, **changes):
    metric = binding.approved_metric_ids[0]
    row = ResultRow(row_id='row-1', entity_ids=('product-1',), fields=(
        ResultField(field_id='product_name', value=encode_contract_value('합성 ETF')),
        ResultField(field_id=binding.semantic_concept_id, value=encode_contract_value(value),
                    unit_id=binding.storage_unit_id, applicable_date=DATE),
    ))
    payload = fact(predicate_id=metric, metric_id=metric,
        normalized_value=encode_contract_value(value).model_dump(mode='json'),
        numeric_value=None, text_value=None, boolean_value=None,
        subject_product_family=binding.product_family_id.value,
        source_locator_root='pref02n001_data.xlsx',
        locator_uri_or_object_key='pref02n001_data.xlsx',
        unit=binding.storage_unit_id, observation_unit=binding.storage_unit_id,
        locator_column=column)
    storage = {'string': 'text_value', 'boolean': 'boolean_value', 'decimal': 'numeric_value'}[
        binding.semantic_value_kind.value]
    payload[storage] = value
    payload.update(changes)
    refs = ('evidence:evidence-1', 'source:source-1', 'observation:observation-1',
            f'metric-definition:{metric}:2')
    return row, payload, refs


def validate(binding, value, column, **changes):
    row, payload, refs = fixture(binding, value, column, **changes)
    return validate_semantic_rows((row,), (payload,), refs, (binding,), DATASET, CUTOFF)


def test_registered_region_text_is_verified_against_original_typed_observation():
    binding = load_physical_binding_registry(ROOT).bindings_by_id['overseas-etf-region.v1']
    verified = validate(binding, 'Japan', 'wu_inv_rgn')
    text = render_semantic_rows(verified, total_count=1, display_limit=5, ranked=False)
    assert '지역: Japan' in text
    assert '열=wu_inv_rgn' in text
    assert 'organizer.pref02n001.investment_region:2' in text
    assert '실제 기준일: 2026-08-22' in text


@pytest.mark.parametrize('changes', [
    {'text_value': 'US'}, {'text_value': True}, {'text_value': None},
    {'normalized_value': {'type': 'boolean', 'value': True}},
    {'numeric_value': Decimal('1')}, {'observation_unit': 'code'},
])
def test_region_evidence_type_or_value_tampering_is_rejected(changes):
    binding = load_physical_binding_registry(ROOT).bindings_by_id['overseas-etf-region.v1']
    with pytest.raises(LocalSemanticResultError):
        validate(binding, 'Japan', 'wu_inv_rgn', **changes)


def boolean_binding():
    payload = load_physical_binding_registry(ROOT).bindings_by_id['overseas-etf-region.v1'].model_dump(mode='json')
    payload.update(id='synthetic-boolean.v1', semantic_concept_id='synthetic_eligibility',
        approved_metric_ids=['synthetic.eligibility'], approved_metric_definition_refs=['synthetic.eligibility:2'],
        value_column=ObservationValueColumn.BOOLEAN.value, semantic_value_kind=SemanticValueKind.BOOLEAN.value)
    return PhysicalBindingDefinition.model_validate_json(json.dumps(payload))


def test_false_boolean_is_verified_as_present_false_and_never_a_numeric_zero():
    binding = boolean_binding()
    verified = validate(binding, False, 'synthetic_flag')
    assert len(verified) == 1
    for changes in ({'boolean_value': 0}, {'normalized_value': {'type': 'integer', 'value': 0}},
                    {'numeric_value': Decimal('0')}, {'value_status': 'zero'}):
        with pytest.raises(LocalSemanticResultError):
            validate(binding, False, 'synthetic_flag', **changes)

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from financial_agent.intent.catalog import load_catalog
from financial_agent.planning.physical_bindings import (
    PhysicalBindingDefinition, load_physical_binding_registry,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(('binding_id', 'metric', 'kind', 'unit'), [
    ('overseas-etf-region.v1', 'organizer.pref02n001.investment_region', 'string', None),
    ('overseas-etf-asset-class.v1', 'organizer.pref02n001.investment_asset_type', 'string', None),
    ('domestic-bond-credit-grade.v1', 'organizer.prbd01n001.credit_grade_representative', 'string', None),
    ('domestic-bond-currency.v1', 'organizer.prbd01n001.currency', 'string', None),
    ('domestic-bond-remaining-days.v1', 'organizer.prbd01n001.remaining_days', 'decimal', 'day'),
])
def test_condition_bindings_preserve_source_kind_version_and_unit(binding_id, metric, kind, unit):
    binding = load_physical_binding_registry(ROOT).bindings_by_id[binding_id]
    assert binding.approved_metric_ids == (metric,)
    assert binding.approved_metric_definition_refs == (f'{metric}:2',)
    assert binding.semantic_value_kind.value == kind
    assert binding.storage_unit_id == unit
    assert {item.value for item in binding.required_evidence_locators} == {
        'metric_definition', 'observation_record', 'evidence_record', 'source_record',
    }
    if kind == 'string':
        assert 'gte' not in {item.value for item in binding.supported_operator_ids}


def test_numeric_condition_still_requires_its_verified_day_unit():
    binding = load_physical_binding_registry(ROOT).bindings_by_id['domestic-bond-remaining-days.v1']
    assert binding.accepted_semantic_unit_ids == ('day',)
    payload = binding.model_dump(mode='json')
    payload['storage_unit_id'] = None
    with pytest.raises(ValidationError, match='verified binding requires unit policy'):
        PhysicalBindingDefinition.model_validate_json(json.dumps(payload))
    concept = load_catalog(ROOT).concepts_by_id['remaining_days']
    assert concept.value_kind == 'decimal'
    assert concept.normalization_rule == 'source_remaining_days'
    assert concept.required_qualifiers == ('as_of',)


def test_new_condition_definition_cannot_change_source_metric_or_unit(tmp_path):
    payload = json.loads((ROOT / 'config/planning/semantic-sql-bindings.v1.json').read_text())
    binding = next(item for item in payload['bindings'] if item['id'] == 'overseas-etf-region.v1')
    binding['approved_metric_ids'] = ['organizer.pref02n001.market_country_code_raw']
    binding['approved_metric_definition_refs'] = ['organizer.pref02n001.market_country_code_raw:2']
    path = tmp_path / 'bindings.json'
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='physical binding definition mismatch'):
        load_physical_binding_registry(ROOT, registry_path=path)

"""Empty comparison fields must remain a bounded contract rejection."""

import json

import pytest

from financial_agent.contracts.enums import IntentType
from financial_agent.intent.model import ModelInvocationResult
from financial_agent.intent.query_contract_solver import solve_query_contracts
from financial_agent.intent.query_contracts import ComparisonSpecV2, ContractReadiness

from .test_personal_intent import Adapter, service
from .test_query_contract_solver import HYBRID_CATALOG, REGISTRY, _entity_axis, _semantic_view


@pytest.mark.parametrize('field,expected_reason', [
    (None, 'REQUIRED_SEMANTIC_INPUT_MISSING'), ('aum', 'REQUIRED_QUALIFIER_MISSING'),
])
def test_compare_with_no_complete_fields_returns_existing_rejection(field, expected_reason):
    resolver_view = _semantic_view(*(() if field is None else (field,))).model_copy(
        update={'literal_candidates': ()},
    )
    if field:
        resolver_view = resolver_view.model_copy(update={'concept_definitions': tuple(
            item.model_copy(update={'required_qualifiers': HYBRID_CATALOG.concepts_by_id[field].required_qualifiers})
            if item.concept_id == field else item for item in resolver_view.concept_definitions
        )})
    result = solve_query_contracts(
        resolution=_entity_axis(action=IntentType.COMPARE, candidate_groups=(('a',), ('b',))),
        view=resolver_view, exact_locks=(), registry=REGISTRY,
    )
    assert result.frames[0].complete_candidates == ()
    assert result.frames[0].contract_readiness.readiness is ContractReadiness.BLOCKED
    assert expected_reason in result.frames[0].contract_readiness.reason_codes


def test_nonempty_comparison_metric_and_valid_profile_invariants_are_preserved():
    result = solve_query_contracts(
        resolution=_entity_axis(action=IntentType.COMPARE, candidate_groups=(('a',), ('b',))),
        view=_semantic_view('fee_rate'), exact_locks=(), registry=REGISTRY,
    )
    assert len(result.frames[0].complete_candidates) == 1
    assert result.frames[0].complete_candidates[0].contract.comparison.metric_concept_ids == ('fee_rate',)
    profile = ComparisonSpecV2(
        subject_refs=('a', 'b'), projection_profile_id='default-product-projection.v1',
        basis_policy_id='same-definition-period-unit.v1',
    )
    assert profile.metric_concept_ids == ()
    assert profile.projection_profile_id == 'default-product-projection.v1'


class ContextComparisonAdapter(Adapter):
    def __init__(self):
        super().__init__('overseas_etf', None, action='lookup', entity=False)

    async def invoke(self, envelope, timeout_seconds):
        result = await super().invoke(envelope, timeout_seconds)
        proposal = json.loads(result.content)
        view = json.loads(envelope.user_message)['view']
        region = next(m for m in view['mention_spans']['items'] if m['text'] == '지역')
        annual = next(item for item in view['exact_lock_projections']
                      if item['role'] == 'field'
                      and item['canonical_semantic_id'] == 'trailing_1y_historical_cumulative_return')
        first = proposal['frames'][0]
        first['entity_type_ids'] = []
        first['semantic_links'] = [{'mention_id': region['mention_id'], 'state': 'selected',
                                    'semantic_ids': ['region'], 'reason_code': 'explicit'}]
        second = {**first, 'action_choice': {'state': 'selected', 'selected_ids': ['compare'],
                                           'evidence_ids': [], 'reason_code': 'explicit'},
                  'semantic_links': [{'mention_id': annual['mention_id'], 'state': 'selected',
                                      'semantic_ids': ['trailing_1y_historical_cumulative_return'],
                                      'reason_code': 'explicit'}],
                  'produced_result_hints': ['comparison_decision']}
        proposal['frames'].append(second)
        reference_id = view['reference_candidates'][0]['reference_id']
        proposal['references'] = [{
            'reference_id': reference_id, 'producer_frame_ordinals': [0],
            'surface_presence': 'explicit', 'reference_form': 'demonstrative',
            'grammatical_number': 'unknown' if self.calls == 1 else ['singular'],
            'expected_target_kind': ['result_set'], 'expected_cardinality': ['many'],
            'status': 'resolved', 'reason_code': 'explicit',
        }]
        proposal['context_links'] = [{
            'reference_id': reference_id, 'link_type': 'consume_result_set', 'source_role': 'candidates',
            'selector': ['all'], 'selector_literal_candidate_id': [],
            'producer_frame_ordinal': 0, 'consumer_frame_ordinal': 1, 'target_slot_kind': ['filter_value'],
        }]
        return ModelInvocationResult(content=json.dumps(proposal), usage=result.usage)


@pytest.mark.asyncio
@pytest.mark.parametrize('period,complete', [('연간', False), ('1년', True)])
async def test_authored_context_compare_without_period_stays_incomplete_after_one_repair(period, complete):
    adapter = ContextComparisonAdapter()
    result = await service(adapter).resolve(f'해외ETF 지역 조회하고 그 지역별 {period} 수익률 비교')
    assert adapter.calls == 2
    assert result.attempt.resolution.repair_used
    consumer = result.attempt.candidates.frames[1]
    assert bool(consumer.complete_candidates) is complete
    if not complete:
        assert 'REQUIRED_QUALIFIER_MISSING' in consumer.contract_readiness.reason_codes
        assert result.compilation is None or result.compilation.logical_query_plan is None
    else:
        assert consumer.complete_candidates[0].contract.qualifiers.period_id == 'P1Y'

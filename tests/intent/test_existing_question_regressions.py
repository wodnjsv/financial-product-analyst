"""Source constraints found by the existing-question end-to-end audit."""

import json

import pytest

from financial_agent.intent.errors import ResolverContractError
from financial_agent.intent.hybrid_assembler import assemble_hybrid_proposal
from financial_agent.intent.service import build_hybrid_repair_envelope
from tests.intent.test_hybrid_assembler import _inputs, _proposal
from tests.intent.test_nvidia_repair_feedback import prepared_relation


def test_omitted_source_reference_cannot_become_a_family_wide_query():
    _, normalized, view, catalog, mention = _inputs('이 상품의 비용 부담이 작은 ETF')
    assert len(view.reference_candidates) == 1
    with pytest.raises(ResolverContractError) as caught:
        assemble_hybrid_proposal(_proposal(mention), normalized, view, catalog)
    assert caught.value.code == 'MODEL_INVALID_FRAME_REFERENCE'
    assert caught.value.validation_feedback == ({
        'path': 'references', 'rule': 'source_reference_missing',
        'required_reference_ids': [view.reference_candidates[0].reference_id],
    },)


@pytest.mark.asyncio
async def test_inapplicable_type_feedback_preserves_source_and_registered_domain():
    intent, prepared, proposal = await prepared_relation()
    proposal['frames'][0]['entity_type_ids'] = ['AssetManager']
    with pytest.raises(ResolverContractError) as caught:
        intent._resolver.validate_hybrid_response(prepared, json.dumps(proposal))
    assert caught.value.code == 'MODEL_INAPPLICABLE_CONCEPT'
    feedback = json.loads(build_hybrid_repair_envelope(prepared, caught.value).user_message)['validation_errors']
    assert feedback == [{
        'path': 'frames.0.entity_type_ids', 'rule': 'concept_subject_type_mismatch',
        'semantic_id': 'managedBy',
        'mention_id': proposal['frames'][0]['semantic_links'][0]['mention_id'],
        'allowed_entity_type_ids': ['FinancialProduct'],
    }]


@pytest.mark.asyncio
async def test_inapplicable_family_feedback_does_not_change_selected_family():
    intent, prepared, proposal = await prepared_relation()
    frame = proposal['frames'][0]
    frame['semantic_links'][0]['semantic_ids'] = ['credit_grade']
    frame['entity_hints'] = []
    with pytest.raises(ResolverContractError) as caught:
        intent._resolver.validate_hybrid_response(prepared, json.dumps(proposal))
    assert caught.value.code == 'MODEL_INAPPLICABLE_CONCEPT'
    feedback = json.loads(build_hybrid_repair_envelope(prepared, caught.value).user_message)['validation_errors']
    assert feedback[0]['rule'] == 'concept_product_family_mismatch'
    assert feedback[0]['semantic_id'] == 'credit_grade'
    assert feedback[0]['allowed_product_family_ids'] == ['domestic_bond']
    assert frame['product_family_choice']['selected_ids'] == ['domestic_etf']


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid_shape,expected_rule', [
    ('overlap', 'linked_and_unmapped_are_disjoint'),
    ('empty_partial', 'partial_or_unmapped_requires_reason_and_source_mention'),
    ('duplicate', 'semantic_mention_must_be_unique'),
])
async def test_model_invariant_feedback_is_specific_without_raw_response(invalid_shape, expected_rule):
    intent, prepared, proposal = await prepared_relation()
    frame = proposal['frames'][0]
    if invalid_shape == 'overlap':
        frame['unmapped_mention_ids'] = [frame['semantic_links'][0]['mention_id']]
        frame['semantic_coverage'] = {'state': 'partial', 'reason': 'missing_critical_semantic'}
    elif invalid_shape == 'empty_partial':
        frame['semantic_coverage'] = {'state': 'partial', 'reason': 'missing_critical_semantic'}
    else:
        frame['semantic_links'] *= 2
    with pytest.raises(ResolverContractError) as caught:
        intent._resolver.validate_hybrid_response(prepared, json.dumps(proposal))
    assert caught.value.code == 'MODEL_PROPOSAL_SCHEMA_INVALID'
    repair = json.loads(build_hybrid_repair_envelope(prepared, caught.value).user_message)
    assert repair['validation_errors'] == [{'path': 'frames.0', 'rule': expected_rule}]
    assert 'invalid_response' not in repair
    assert str(caught.value) == 'MODEL_PROPOSAL_SCHEMA_INVALID'

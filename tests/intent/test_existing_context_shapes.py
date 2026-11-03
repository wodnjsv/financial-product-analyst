"""Contract-shape regressions from the unchanged authored-question V7 rerun."""

import json

import httpx
import pytest

from financial_agent.contracts.enums import Cardinality, IntentType
from financial_agent.intent.context import _ROLE_SHAPES, _link_target, validate_context_graph
from financial_agent.intent.errors import ResolverContractError
from financial_agent.intent.nvidia import NvidiaStructuredOutputAdapter
from financial_agent.intent.types import ContextLinkType, ReferenceTargetKind, Selector, SlotKind, SourceRole

from .test_context import _frame, _link, _reference, _state
from .test_nvidia import Envelope, config, payload
from .test_personal_intent import Adapter, service


@pytest.mark.parametrize('link_type,role,allowed_roles', [
    (ContextLinkType.CONSUME_SINGLE_RESULT, SourceRole.SELECTED_PRODUCT, ['candidates', 'top_k_products']),
    (ContextLinkType.CONSUME_RESULT_SET, SourceRole.RELATION_TARGET, ['candidates', 'top_k_products']),
    (ContextLinkType.DERIVE_ENTITY, SourceRole.SELECTED_PRODUCT, ['relation_target']),
    (ContextLinkType.DERIVE_METRIC_VALUE, SourceRole.TOP_K_PRODUCTS, ['metric_value']),
    (ContextLinkType.INHERIT_SCOPE, SourceRole.RELATION_TARGET, ['candidates', 'selected_product', 'top_k_products']),
    (ContextLinkType.REFER_EXCLUSION_SET, SourceRole.CANDIDATES, ['excluded_products']),
    (ContextLinkType.REFER_EVIDENCE, SourceRole.METRIC_VALUE, ['evidence_records']),
])
def test_invalid_link_source_keeps_rejection_and_reports_registered_shapes(link_type, role, allowed_roles):
    hint = _link(link_type=link_type, role=role, selector=(), link_id='private-link-id')
    source = _ROLE_SHAPES[role]
    with pytest.raises(ResolverContractError, match='INVALID_CONTEXT_GRAPH') as caught:
        _link_target(hint, source)
    assert caught.value.validation_feedback == ({
        'path': 'context_links', 'rule': 'context_link_source_shape_mismatch',
        'link_type': link_type.value, 'source_role': role.value,
        'source_target_kind': source.target_kind.value, 'source_cardinality': source.cardinality.value,
        'allowed_source_roles': allowed_roles,
    },)
    assert 'private-link-id' not in str(caught.value.validation_feedback)


def test_recorded_singleton_consumer_shape_still_fails_in_full_context_validation():
    role = SourceRole.SELECTED_PRODUCT
    state = _state(
        frames=(_frame('f1', 0, roles=(role,)), _frame('f2', 1)),
        references=(_reference(number='singular', target_kind=ReferenceTargetKind.ENTITY,
                               cardinality=Cardinality.ONE),),
        links=(_link(link_type=ContextLinkType.CONSUME_SINGLE_RESULT, role=role, selector=()),),
    )
    with pytest.raises(ResolverContractError, match='INVALID_CONTEXT_GRAPH') as caught:
        validate_context_graph(state)
    assert caught.value.validation_feedback[0]['allowed_source_roles'] == ['candidates', 'top_k_products']


@pytest.mark.parametrize('kind,cardinality', [
    (ReferenceTargetKind.RESULT_SET, Cardinality.ONE),
    (ReferenceTargetKind.ENTITY, Cardinality.MANY),
])
def test_recorded_first_product_reference_requires_the_consumed_target_shape(kind, cardinality):
    # REL-MGR-001 repair selected a product but described its target as a result set.
    frames = (_frame('f1', 0, roles=(SourceRole.TOP_K_PRODUCTS,)),
              _frame('f2', 1, action=IntentType.SIMILAR))
    reference = _reference('private-reference-id', number='singular',
                           target_kind=kind, cardinality=cardinality)
    link = _link(reference_id=reference.reference_id, link_id='private-link-id',
                 link_type=ContextLinkType.CONSUME_SINGLE_RESULT, role=SourceRole.TOP_K_PRODUCTS,
                 selector=(Selector.FIRST,), target_slot=(SlotKind.SIMILARITY_ANCHOR,))
    with pytest.raises(ResolverContractError, match='INVALID_CONTEXT_GRAPH') as caught:
        validate_context_graph(_state(frames=frames, references=(reference,), links=(link,)))
    assert caught.value.validation_feedback == ({
        'path': 'context_links', 'rule': 'context_link_reference_target_shape_mismatch',
        'link_type': 'consume_single_result', 'source_role': 'top_k_products',
        'reference_expected_target_kind': [kind.value],
        'reference_expected_cardinality': [cardinality.value],
        'required_target_kind': ['entity'], 'required_cardinality': ['one'],
    },)
    assert 'private' not in str(caught.value.validation_feedback)
    assert reference.expected_target_kind == (kind,)
    assert reference.expected_cardinality == (cardinality,)
    corrected_reference = reference.model_copy(update={
        'expected_target_kind': (ReferenceTargetKind.ENTITY,),
        'expected_cardinality': (Cardinality.ONE,),
    })
    corrected = validate_context_graph(_state(frames=frames, references=(corrected_reference,), links=(link,)))
    assert len(corrected.context_links) == 1
    assert corrected.context_links[0].target_kind == (ReferenceTargetKind.ENTITY,)
    assert corrected.context_links[0].target_cardinality == (Cardinality.ONE,)


@pytest.mark.parametrize('role,target_slot,allowed_slots', [
    (SourceRole.SELECTED_PRODUCT, (), ['entity', 'similarity_anchor']),
    (SourceRole.METRIC_VALUE, (SlotKind.ENTITY,), ['metric']),
    (SourceRole.TOP_K_PRODUCTS, (SlotKind.ENTITY,), []),
])
def test_invalid_replacement_reports_registered_target_slots_without_source_ids(role, target_slot, allowed_slots):
    hint = _link(link_type=ContextLinkType.REPLACE_SLOT, role=role, target_slot=target_slot,
                 link_id='private-link-id', producer='private-frame-id')
    with pytest.raises(ResolverContractError, match='INVALID_CONTEXT_GRAPH') as caught:
        _link_target(hint, _ROLE_SHAPES[role])
    feedback = caught.value.validation_feedback[0]
    assert feedback['rule'] == 'context_link_source_or_target_slot_mismatch'
    assert feedback['allowed_target_slot_kinds'] == allowed_slots
    assert 'allowed_source_roles' not in feedback
    assert 'private' not in str(feedback)


@pytest.mark.parametrize('link_type,role,target_slot,kind,cardinality', [
    (ContextLinkType.CONSUME_SINGLE_RESULT, SourceRole.CANDIDATES, (), ReferenceTargetKind.ENTITY, Cardinality.ONE),
    (ContextLinkType.CONSUME_SINGLE_RESULT, SourceRole.TOP_K_PRODUCTS, (), ReferenceTargetKind.ENTITY, Cardinality.ONE),
    (ContextLinkType.CONSUME_RESULT_SET, SourceRole.CANDIDATES, (), ReferenceTargetKind.RESULT_SET, Cardinality.MANY),
    (ContextLinkType.CONSUME_RESULT_SET, SourceRole.TOP_K_PRODUCTS, (), ReferenceTargetKind.RESULT_SET, Cardinality.MANY),
    (ContextLinkType.DERIVE_ENTITY, SourceRole.RELATION_TARGET, (), ReferenceTargetKind.RELATED_ENTITY, Cardinality.ONE),
    (ContextLinkType.DERIVE_METRIC_VALUE, SourceRole.METRIC_VALUE, (), ReferenceTargetKind.METRIC_VALUE, Cardinality.ONE),
    (ContextLinkType.INHERIT_SCOPE, SourceRole.SELECTED_PRODUCT, (), ReferenceTargetKind.ENTITY, Cardinality.ONE),
    (ContextLinkType.INHERIT_SCOPE, SourceRole.CANDIDATES, (), ReferenceTargetKind.RESULT_SET, Cardinality.MANY),
    (ContextLinkType.INHERIT_SCOPE, SourceRole.TOP_K_PRODUCTS, (), ReferenceTargetKind.RESULT_SET, Cardinality.MANY),
    (ContextLinkType.REFER_EXCLUSION_SET, SourceRole.EXCLUDED_PRODUCTS, (), ReferenceTargetKind.EXCLUSION_SET, Cardinality.MANY),
    (ContextLinkType.REFER_EVIDENCE, SourceRole.EVIDENCE_RECORDS, (), ReferenceTargetKind.EVIDENCE_RECORDS, Cardinality.MANY),
    (ContextLinkType.REPLACE_SLOT, SourceRole.SELECTED_PRODUCT, (SlotKind.ENTITY,), ReferenceTargetKind.ENTITY, Cardinality.ONE),
    (ContextLinkType.REPLACE_SLOT, SourceRole.RELATION_TARGET, (SlotKind.ENTITY,), ReferenceTargetKind.RELATED_ENTITY, Cardinality.ONE),
    (ContextLinkType.REPLACE_SLOT, SourceRole.SELECTED_PRODUCT, (SlotKind.SIMILARITY_ANCHOR,), ReferenceTargetKind.ENTITY, Cardinality.ONE),
    (ContextLinkType.REPLACE_SLOT, SourceRole.RELATION_TARGET, (SlotKind.SIMILARITY_ANCHOR,), ReferenceTargetKind.RELATED_ENTITY, Cardinality.ONE),
    (ContextLinkType.REPLACE_SLOT, SourceRole.METRIC_VALUE, (SlotKind.METRIC,), ReferenceTargetKind.METRIC_VALUE, Cardinality.ONE),
])
def test_registered_valid_link_shapes_remain_unchanged(link_type, role, target_slot, kind, cardinality):
    assert _link_target(_link(link_type=link_type, role=role, target_slot=target_slot), _ROLE_SHAPES[role]) == (kind, cardinality)


@pytest.mark.asyncio
@pytest.mark.parametrize('field,scalar', [
    ('grammatical_number', 'singular'), ('grammatical_number', 'plural'),
    ('expected_target_kind', 'result_set'), ('expected_cardinality', 'many'),
])
async def test_repeated_reference_scalar_is_never_coerced_and_has_precise_feedback(field, scalar):
    calls = []
    adapter = Adapter('domestic_etf', 'fee_rate', action='lookup', entity=False)

    async def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        result = await adapter.invoke(Envelope(user_message=body['messages'][1]['content']), 1)
        proposal = json.loads(result.content)
        view = json.loads(body['messages'][1]['content'])['view']
        proposal['references'] = [{
            'reference_id': view['reference_candidates'][0]['reference_id'],
            'producer_frame_ordinals': [], 'surface_presence': 'explicit',
            'reference_form': 'demonstrative', 'grammatical_number': ['singular'],
            'expected_target_kind': ['entity'], 'expected_cardinality': ['one'],
            'status': 'unresolved', 'reason_code': 'implicit',
        }]
        proposal['references'][0][field] = scalar
        return httpx.Response(200, json=payload(json.dumps(proposal)))

    intent = service(NvidiaStructuredOutputAdapter(config(), transport=httpx.MockTransport(handler)))
    with pytest.raises(ResolverContractError, match='MODEL_PROPOSAL_SCHEMA_INVALID') as caught:
        await intent.resolve('이 국내 ETF의 총보수를 알려줘.')
    assert len(calls) == 2
    assert caught.value.validation_feedback == ({
        'path': f'references.0.{field}', 'rule': 'type', 'expected_type': 'array',
    },)
    repair = json.loads(json.loads(calls[1].content)['messages'][1]['content'])
    assert repair['validation_errors'] == list(caught.value.validation_feedback)
    for request in calls:
        guide = json.loads(request.content)['messages'][0]['content']
        assert 'grammatical_number=["plural"]' in guide
        assert 'expected_target_kind=["result_set"]' in guide
        assert 'expected_cardinality=["many"]' in guide
        assert 'optional single-item arrays' in guide
        assert 'selected_product uses inherit_scope' in guide
        assert 'relation_target uses derive_entity' in guide
        assert 'consume_single_result selects from candidates or top_k_products' in guide


@pytest.mark.asyncio
async def test_inapplicable_ambiguous_alternative_still_rejects_after_one_repair():
    calls = []
    adapter = Adapter('domestic_etf', None, action='lookup', entity=False)

    async def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        result = await adapter.invoke(Envelope(user_message=body['messages'][1]['content']), 1)
        proposal = json.loads(result.content)
        view = json.loads(body['messages'][1]['content'])['view']
        mention = next(m for m in view['mention_spans']['items'] if m['text'] == '위험등급')
        proposal['frames'][0]['semantic_links'] = [{
            'mention_id': mention['mention_id'], 'state': 'ambiguous',
            'semantic_ids': ['credit_grade', 'product_risk_grade'], 'reason_code': 'ambiguous',
        }]
        return httpx.Response(200, json=payload(json.dumps(proposal)))

    intent = service(NvidiaStructuredOutputAdapter(config(), transport=httpx.MockTransport(handler)))
    with pytest.raises(ResolverContractError, match='MODEL_INAPPLICABLE_CONCEPT') as caught:
        await intent.resolve('국내 ETF의 위험등급 알려줘.')
    assert len(calls) == 2
    assert caught.value.validation_feedback[0]['semantic_id'] == 'credit_grade'
    assert caught.value.validation_feedback[0]['allowed_product_family_ids'] == ['domestic_bond']
    for request in calls:
        guide = json.loads(request.content)['messages'][0]['content']
        assert 'Every semantic_id in a selected or ambiguous link must apply to all selected' in guide
        assert 'Do not include an inapplicable alternative in ambiguity' in guide
        assert 'Keep unresolved source meaning unmapped' in guide

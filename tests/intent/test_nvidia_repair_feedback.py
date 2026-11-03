from copy import deepcopy
import json
import logging

import httpx
import pytest

from financial_agent.contracts.request import RequestContext
from financial_agent.intent.errors import ResolverContractError, ModelInvocationError
from financial_agent.intent.model import ModelInvocationResult
from financial_agent.intent.nvidia import NvidiaStructuredOutputAdapter, _model_response_schema
from financial_agent.intent.service import build_hybrid_repair_envelope
from tests.intent.test_personal_intent import service
from tests.intent.test_personal_relations import _RelationAdapter, _RelationEntities
from tests.intent.test_nvidia import config, envelope


class Capture(Exception):
    pass


async def prepared_relation():
    class Capturing(_RelationAdapter):
        async def invoke(self, envelope, timeout_seconds):
            result = await super().invoke(envelope, timeout_seconds)
            self.envelope, self.proposal = envelope, json.loads(result.content)
            raise Capture()

    adapter = Capturing('managedBy')
    intent = service(adapter, name='삼성자산운용')
    intent._resolver._entity_repository = _RelationEntities('AssetManager')
    with pytest.raises(Capture):
        await intent.resolve('삼성자산운용이 운용하는 국내 ETF를 찾아줘.')
    context = RequestContext.model_validate_json(json.dumps(json.loads(adapter.envelope.user_message)['context']))
    prepared = await intent._resolver.prepare_hybrid(context)
    return intent, prepared, adapter.proposal


def add_family_hint(prepared, proposal):
    family = next(m for m in prepared.view.mention_spans.items if m.text == '국내 ETF')
    proposal['frames'][0]['entity_hints'].insert(0, {
        'semantic_role': 'frame_subject', 'relation_id': [],
        'expected_entity_type_ids': ['ETF'], 'mention_id': [family.mention_id],
        'candidate_entity_ids': [], 'selected_candidate_ids': [],
    })
    return family.mention_id


@pytest.mark.asyncio
async def test_model_schema_keeps_entity_mention_and_concept_namespaces():
    _, prepared, _ = await prepared_relation()
    original = deepcopy(prepared.prompt.response_schema)
    frame = _model_response_schema(original)['properties']['frames']['items']['properties']
    assert frame['entity_hints']['items']['properties']['mention_id']['items']['enum'] == [
        prepared.view.entity_candidates[0].mention_id,
    ]
    concepts = frame['semantic_links']['items']['oneOf'][0]['properties']['semantic_ids']['items']['enum']
    assert 'managedBy' in concepts and 'domestic_etf' not in concepts
    assert original == prepared.prompt.response_schema


@pytest.mark.asyncio
async def test_family_hint_error_reports_exact_path_and_allowed_named_span():
    intent, prepared, proposal = await prepared_relation()
    invalid_id = add_family_hint(prepared, proposal)
    with pytest.raises(ResolverContractError) as caught:
        intent._resolver.validate_hybrid_response(prepared, json.dumps(proposal))
    assert caught.value.code == 'MODEL_PROPOSAL_SCHEMA_INVALID'
    repair = build_hybrid_repair_envelope(prepared, caught.value)
    feedback = json.loads(repair.user_message)['validation_errors']
    issue = next(i for i in feedback if i['path'] == 'frames.0.entity_hints.0.mention_id.0')
    assert issue['rejected_id'] == invalid_id
    assert issue['allowed_values'] == [prepared.view.entity_candidates[0].mention_id]
    assert 'General product-family scope is not a named entity' in repair.system_message


@pytest.mark.asyncio
async def test_family_concept_error_uses_selected_branch_feedback():
    intent, prepared, proposal = await prepared_relation()
    proposal['frames'][0]['semantic_links'][0]['semantic_ids'] = ['domestic_etf']
    with pytest.raises(ResolverContractError) as caught:
        intent._resolver.validate_hybrid_response(prepared, json.dumps(proposal))
    feedback = json.loads(build_hybrid_repair_envelope(prepared, caught.value).user_message)['validation_errors']
    issue = next(i for i in feedback if i['path'] == 'frames.0.semantic_links.0.semantic_ids.0')
    assert issue['rejected_id'] == 'domestic_etf'
    assert 'managedBy' in issue['allowed_values']
    assert all(i.get('rejected_id') != 'selected' for i in feedback)


@pytest.mark.asyncio
async def test_schema_feedback_never_echoes_arbitrary_model_text():
    intent, prepared, proposal = await prepared_relation()
    proposal['frames'][0]['entity_hints'][0]['mention_id'] = ['secret-key hidden reasoning']
    with pytest.raises(ResolverContractError) as caught:
        intent._resolver.validate_hybrid_response(prepared, json.dumps(proposal))
    repair = build_hybrid_repair_envelope(prepared, caught.value)
    assert 'secret-key' not in repair.user_message
    assert 'hidden reasoning' not in repair.user_message
    assert json.loads(repair.user_message)['validation_errors']
    assert 'secret-key' not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,kind', [(503, 'http_status'), (429, 'http_status')])
async def test_provider_failure_log_has_status_category_elapsed_without_body(status, kind, caplog):
    async def handler(request):
        return httpx.Response(status, text='test-nvidia-key hidden reasoning')
    with caplog.at_level(logging.WARNING), pytest.raises(ModelInvocationError):
        await NvidiaStructuredOutputAdapter(config(), transport=httpx.MockTransport(handler)).invoke(envelope(), 1)
    assert f'http_status={status}' in caplog.text
    assert f'kind={kind}' in caplog.text and 'elapsed_ms=' in caplog.text
    assert 'test-nvidia-key' not in caplog.text and 'hidden reasoning' not in caplog.text


@pytest.mark.asyncio
async def test_transport_failure_log_distinguishes_read_timeout_without_payload(caplog):
    async def handler(request):
        raise httpx.ReadTimeout('test-nvidia-key hidden reasoning')
    with caplog.at_level(logging.WARNING), pytest.raises(ModelInvocationError):
        await NvidiaStructuredOutputAdapter(config(), transport=httpx.MockTransport(handler)).invoke(envelope(), 1)
    assert 'kind=read_timeout' in caplog.text and 'http_status=None' in caplog.text
    assert 'test-nvidia-key' not in caplog.text and 'hidden reasoning' not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize('relation,object_type,name,question', [
    ('managedBy', 'AssetManager', '삼성자산운용', '삼성자산운용이 운용하는 국내 ETF를 찾아줘.'),
    ('holdsSecurity', 'Security', '삼성전자', '2026-08-22 기준 삼성전자를 보유한 국내 ETF를 찾아줘.'),
])
async def test_one_targeted_repair_preserves_relation_object_and_query_scope(relation, object_type, name, question):
    class Repairing(_RelationAdapter):
        async def invoke(self, envelope, timeout_seconds):
            result = await super().invoke(envelope, timeout_seconds)
            payload = json.loads(result.content)
            if self.calls == 1:
                view = json.loads(envelope.user_message)['view']
                family = next(m for m in view['mention_spans']['items'] if m['text'] == '국내 ETF')
                payload['frames'][0]['entity_hints'].insert(0, {
                    'semantic_role': 'frame_subject', 'relation_id': [],
                    'expected_entity_type_ids': ['ETF'], 'mention_id': [family['mention_id']],
                    'candidate_entity_ids': [], 'selected_candidate_ids': [],
                })
                payload['frames'][0]['semantic_links'][0]['semantic_ids'] = ['domestic_etf']
            else:
                feedback = json.loads(envelope.user_message)['validation_errors']
                assert any('entity_hints' in i['path'] for i in feedback)
                assert any('semantic_ids' in i['path'] for i in feedback)
            return ModelInvocationResult(json.dumps(payload), result.usage)

    adapter = Repairing(relation)
    intent = service(adapter, name=name)
    intent._resolver._entity_repository = _RelationEntities(object_type)
    result = await intent.resolve(question)
    assert adapter.calls == 2
    assert result.attempt.resolution.repair_used
    assert result.issue_codes == ()
    contract = result.attempt.candidates.frames[0].complete_candidates[0].contract
    assert contract.scope.entity_refs == ()
    assert contract.scope.relation_conditions[0].relation_id == relation
    assert contract.scope.relation_conditions[0].object_entity_id == 'relation-object-1'
    assert result.compilation.logical_query_plan is not None


@pytest.mark.asyncio
async def test_repeated_illegal_id_still_fails_after_only_one_repair():
    class Invalid(_RelationAdapter):
        async def invoke(self, envelope, timeout_seconds):
            result = await super().invoke(envelope, timeout_seconds)
            payload = json.loads(result.content)
            payload['frames'][0]['entity_hints'][0]['mention_id'] = ['invented-id']
            return ModelInvocationResult(json.dumps(payload), result.usage)

    adapter = Invalid('managedBy')
    intent = service(adapter, name='삼성자산운용')
    intent._resolver._entity_repository = _RelationEntities('AssetManager')
    with pytest.raises(ResolverContractError, match='MODEL_PROPOSAL_SCHEMA_INVALID'):
        await intent.resolve('삼성자산운용이 운용하는 국내 ETF를 찾아줘.')
    assert adapter.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('relation,object_type,name,question', [
    ('managedBy', 'AssetManager', '삼성자산운용', '삼성자산운용이 운용하는 국내 ETF를 찾아줘.'),
    ('holdsSecurity', 'Security', '삼성전자', '2026-08-22 기준 삼성전자를 보유한 국내 ETF를 찾아줘.'),
])
async def test_missing_relation_semantic_link_gets_targeted_repair(relation, object_type, name, question):
    class MissingLink(_RelationAdapter):
        async def invoke(self, envelope, timeout_seconds):
            result = await super().invoke(envelope, timeout_seconds)
            proposal = json.loads(result.content)
            if self.calls == 1:
                proposal['frames'][0]['semantic_links'] = []
            else:
                repair = json.loads(envelope.user_message)
                assert repair['failure_code'] == 'MODEL_INVALID_RELATION'
                issue, = repair['validation_errors']
                assert issue['path'] == 'frames.0.semantic_links'
                assert issue['required_relation_ids'] == [relation]
                assert issue['object_mention_ids'] == proposal['frames'][0]['entity_hints'][0]['mention_id']
            return ModelInvocationResult(json.dumps(proposal), result.usage)

    adapter = MissingLink(relation)
    intent = service(adapter, name=name)
    intent._resolver._entity_repository = _RelationEntities(object_type)
    result = await intent.resolve(question)
    assert adapter.calls == 2 and result.issue_codes == ()
    condition, = result.compilation.logical_query_plan.tasks[0].scope.relation_conditions
    assert condition.relation_id == relation and condition.object_entity_id == 'relation-object-1'

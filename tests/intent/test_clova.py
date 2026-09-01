from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.clova import ClovaStructuredOutputAdapter
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.config import ClovaResolverConfig
from financial_agent.intent.errors import ModelInvocationError
from financial_agent.intent.prompt import build_prompt
from financial_agent.intent.resolution import ContractFileHash, ResolverBuildManifest
from financial_agent.intent.view import (
    ActiveDatasetPin,
    ResolverView,
    ResolverViewConcept,
    ResolverViewSemanticCandidate,
    ResolverViewSemanticCandidateGroup,
)

from .view_fixtures import complete_axis_definitions, complete_entity_type_ids


def valid_proposal_json() -> str:
    return json.dumps(
        {
            'proposal_schema_version': '2.0',
            'frames': [
                {
                    'segment_ids': ['s1'],
                    'action_choice': {
                        'state': 'selected',
                        'selected_ids': ['lookup'],
                        'evidence_ids': [],
                        'reason_code': 'explicit',
                    },
                    'product_family_choice': {
                        'state': 'selected',
                        'selected_ids': ['domestic_etf'],
                        'evidence_ids': [],
                        'reason_code': 'explicit',
                    },
                    'entity_type_ids': ['ETF'],
                    'semantic_coverage': {
                        'state': 'covered',
                        'reason': 'none',
                        'evidence_ids': [],
                    },
                    'slot_assignments': [],
                    'entity_hints': [],
                    'produced_result_hints': [],
                }
            ],
            'references': [],
            'context_links': [],
            'slot_mutations': [],
            'semantic_flag_hints': [],
            'frame_limit_exceeded': False,
        }
    )


def make_prompt():
    question = 'AUM을 알려줘'
    created_at = datetime(2026, 8, 31, tzinfo=timezone.utc)
    context = RequestContext(
        request_key=build_request_key('q-clova', question, 'dataset-v1', '1.0'),
        run_id='run-clova',
        dataset_version='dataset-v1',
        producer='test',
        created_at=created_at,
        question_id='q-clova',
        question=question,
        segments=(Segment(segment_id='s1', ordinal=0, text=question),),
        deadline_at=created_at + timedelta(seconds=10),
    )
    manifest = ResolverBuildManifest(
        catalog_version='catalog-v1',
        catalog_hash='a' * 64,
        ontology_hashes=(ContractFileHash(relative_path='ontology.ttl', sha256='b' * 64),),
        overlay_version='overlay-v1',
        overlay_hash='c' * 64,
        normalizer_version='normalizer-v1',
        candidate_policy_version='candidate-policy-v1',
        resolver_schema_version='1.0',
        prompt_version='prompt-v1',
        adapter_version='adapter-v1',
    )
    view = ResolverView(
        build_manifest=manifest,
        active_dataset_pin=ActiveDatasetPin(dataset_version='dataset-v1', manifest_hash='d' * 64),
        product_family_ids=('domestic_etf',),
        action_ids=('lookup',),
        entity_type_ids=complete_entity_type_ids(),
        semantic_candidates=(
            ResolverViewSemanticCandidateGroup(
                mention_id='mention-1',
                items=(ResolverViewSemanticCandidate(semantic_id='aum', match_kind='direct_alias', score=1_000_000),),
            ),
        ),
        concept_definitions=(
            ResolverViewConcept(
                concept_id='aum', kind='metric', definition_ko='운용자산 규모', value_kind='money',
                allowed_product_families=('domestic_etf',), allowed_ontology_types=('ETF',),
                required_qualifiers=(), allowed_operators=('greater_than',),
                missingness_sensitive=True, normalization_rule='none',
            ),
        ),
        relation_definitions=(), literal_candidates=(), entity_candidates=(),
        axis_definitions=complete_axis_definitions(),
        evidence_candidates=(),
        reference_candidates=(),
    )
    return build_prompt(context, view, load_catalog(Path(__file__).resolve().parents[2]))


def make_config() -> ClovaResolverConfig:
    return ClovaResolverConfig(
        api_key=SecretStr('test-api-key-not-a-secret'),
        base_url='https://clova.example.test',
        model_id='test/model',
    )


def test_clova_config_requires_https_and_redacts_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ModelInvocationError, match='MODEL_CONFIGURATION_INVALID'):
        ClovaResolverConfig(
            api_key=SecretStr('test-api-key-not-a-secret'),
            base_url='http://clova.example.test',
            model_id='test-model',
        )

    monkeypatch.setenv('FINANCIAL_AGENT_CLOVA_API_KEY', 'test-api-key-not-a-secret')
    monkeypatch.setenv('FINANCIAL_AGENT_CLOVA_BASE_URL', 'https://clova.example.test')
    monkeypatch.setenv('FINANCIAL_AGENT_INTENT_MODEL_ID', 'test-model')
    config = ClovaResolverConfig.from_env()

    assert 'test-api-key-not-a-secret' not in repr(config)


def provider_payload(content: str = valid_proposal_json()) -> dict[str, object]:
    return {
        'status': {'code': '20000', 'message': 'OK'},
        'result': {
            'message': {'role': 'assistant', 'content': content},
            'finishReason': 'stop',
            'created': 1,
            'seed': 1,
            'usage': {'promptTokens': 10, 'completionTokens': 20, 'totalTokens': 30},
        },
    }


def successful_transport(content: str = valid_proposal_json()):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=provider_payload(content), request=request)

    return httpx.MockTransport(handler), calls


@pytest.mark.asyncio
async def test_clova_adapter_sends_one_structured_request() -> None:
    transport, calls = successful_transport()
    adapter = ClovaStructuredOutputAdapter(make_config(), transport=transport)

    result = await adapter.invoke(make_prompt(), timeout_seconds=4.0)

    body = json.loads(calls[0].content)
    assert len(calls) == 1
    assert calls[0].url == 'https://clova.example.test/v3/chat-completions/test%2Fmodel'
    assert calls[0].headers['Authorization'] == 'Bearer test-api-key-not-a-secret'
    assert calls[0].headers['X-NCP-CLOVASTUDIO-REQUEST-ID']
    assert calls[0].headers['Content-Type'] == 'application/json'
    assert body['responseFormat']['type'] == 'json'
    assert body['topP'] == 0.1
    assert body['topK'] == 1
    assert body['maxCompletionTokens'] == 4096
    assert body['temperature'] == 0.0
    assert body['repetitionPenalty'] == 1.0
    assert body['thinking'] == {'effort': 'none'}
    assert body['seed'] == 42
    assert 'tools' not in body
    assert result.content == valid_proposal_json()
    assert result.usage == {'promptTokens': 10, 'completionTokens': 20, 'totalTokens': 30}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('status_code', 'expected_code'),
    [(401, 'MODEL_CONFIGURATION_INVALID'), (403, 'MODEL_CONFIGURATION_INVALID'), (429, 'MODEL_RATE_LIMITED'), (500, 'MODEL_PROVIDER_UNAVAILABLE')],
)
async def test_clova_adapter_maps_provider_status_without_retry(status_code: int, expected_code: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status_code, json={'status': {'message': 'failure'}}, request=request)

    adapter = ClovaStructuredOutputAdapter(make_config(), transport=httpx.MockTransport(handler))

    with pytest.raises(ModelInvocationError, match=expected_code) as failure:
        await adapter.invoke(make_prompt(), timeout_seconds=4.0)

    assert len(calls) == 1
    assert 'test-api-key-not-a-secret' not in repr(failure.value)
    assert 'test-api-key-not-a-secret' not in str(failure.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('exception', 'expected_code'),
    [(httpx.ConnectError('unavailable'), 'MODEL_PROVIDER_UNAVAILABLE'), (httpx.ReadTimeout('timeout'), 'MODEL_TIMEOUT')],
)
async def test_clova_adapter_maps_transport_failures_without_retry(exception: Exception, expected_code: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise exception

    adapter = ClovaStructuredOutputAdapter(make_config(), transport=httpx.MockTransport(handler))

    with pytest.raises(ModelInvocationError, match=expected_code):
        await adapter.invoke(make_prompt(), timeout_seconds=4.0)

    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'response',
    [
        httpx.Response(200, text='not-json'),
        httpx.Response(200, json={'status': {'code': '20000'}}),
    ],
)
async def test_clova_adapter_rejects_malformed_success_response(response: httpx.Response) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        response.request = request
        return response

    adapter = ClovaStructuredOutputAdapter(make_config(), transport=httpx.MockTransport(handler))

    with pytest.raises(ModelInvocationError, match='MODEL_SCHEMA_INVALID'):
        await adapter.invoke(make_prompt(), timeout_seconds=4.0)

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_clova_adapter_rejects_invalid_usage_counts() -> None:
    calls: list[httpx.Request] = []
    payload = provider_payload()
    result = payload['result']
    assert isinstance(result, dict)
    usage = result['usage']
    assert isinstance(usage, dict)
    usage['totalTokens'] = -1

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=payload, request=request)

    adapter = ClovaStructuredOutputAdapter(make_config(), transport=httpx.MockTransport(handler))

    with pytest.raises(ModelInvocationError, match='MODEL_SCHEMA_INVALID'):
        await adapter.invoke(make_prompt(), timeout_seconds=4.0)

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_clova_adapter_rejects_duplicate_provider_response_keys() -> None:
    calls: list[httpx.Request] = []
    payload = provider_payload()
    result = payload['result']
    assert isinstance(result, dict)
    raw_response = json.dumps({'result': result})[:-1] + f', "result": {json.dumps(result)}}}'

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=raw_response, request=request)

    adapter = ClovaStructuredOutputAdapter(make_config(), transport=httpx.MockTransport(handler))

    with pytest.raises(ModelInvocationError, match='MODEL_SCHEMA_INVALID') as failure:
        await adapter.invoke(make_prompt(), timeout_seconds=4.0)

    assert len(calls) == 1
    assert raw_response not in str(failure.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('model_content', ('not-json', '{"frames":[],"frames":[]}'))
async def test_clova_adapter_preserves_model_content_for_resolver_validation(
    model_content: str,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=provider_payload(model_content), request=request)

    adapter = ClovaStructuredOutputAdapter(make_config(), transport=httpx.MockTransport(handler))

    result = await adapter.invoke(make_prompt(), timeout_seconds=4.0)

    assert len(calls) == 1
    assert result.content == model_content
    assert result.usage == {
        'promptTokens': 10,
        'completionTokens': 20,
        'totalTokens': 30,
    }

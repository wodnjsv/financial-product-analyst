from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from financial_agent.intent.errors import ModelInvocationError
from financial_agent.intent.model import ModelInvocationResult
from financial_agent.intent.nvidia import NvidiaStructuredOutputAdapter
from financial_agent.intent.nvidia_config import NvidiaResolverConfig


@dataclass(frozen=True)
class Envelope:
    system_message: str = 'Resolve registered meanings only.'
    user_message: str = '{"question":"국내 ETF 수익률"}'
    response_schema: dict[str, object] | None = None


def envelope() -> Envelope:
    return Envelope(response_schema={
        'type': 'object',
        'properties': {'plan': {'type': 'string', 'enum': ['rank']}},
        'required': ['plan'],
        'additionalProperties': False,
    })


def config(**overrides) -> NvidiaResolverConfig:
    return NvidiaResolverConfig(api_key=SecretStr('test-nvidia-key'), **overrides)


def payload(content: object = '{"plan":"rank"}') -> dict[str, object]:
    return {
        'choices': [{
            'index': 0,
            'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': content,
                        'reasoning_content': 'hidden model reasoning'},
        }],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30},
    }


def transport_for(response: httpx.Response):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request):
        calls.append(request)
        response.request = request
        return response

    return httpx.MockTransport(handler), calls


def test_config_uses_nvidia_env_without_clova_credentials(monkeypatch) -> None:
    monkeypatch.setenv('NVIDIA_API_KEY', 'test-nvidia-key')
    monkeypatch.delenv('FINANCIAL_AGENT_INTENT_MODEL_ID', raising=False)
    actual = NvidiaResolverConfig.from_env()
    assert actual.model_id == 'z-ai/glm-5.3-flash'
    assert actual.base_url == 'https://integrate.api.nvidia.com/v1'
    assert 'test-nvidia-key' not in repr(actual)
    monkeypatch.setenv('FINANCIAL_AGENT_INTENT_MODEL_ID', 'meta/llama-3.3-70b-instruct')
    assert NvidiaResolverConfig.from_env().model_id == 'meta/llama-3.3-70b-instruct'


def test_config_rejects_missing_key_without_reading_files(monkeypatch) -> None:
    monkeypatch.delenv('NVIDIA_API_KEY', raising=False)
    with pytest.raises(ModelInvocationError, match='MODEL_CONFIGURATION_INVALID'):
        NvidiaResolverConfig.from_env()


@pytest.mark.parametrize('key', ['', '   ', 'test\nkey', '키', 'test\x00key'])
def test_config_rejects_invalid_bearer_keys(key) -> None:
    with pytest.raises(ModelInvocationError, match='MODEL_CONFIGURATION_INVALID'):
        NvidiaResolverConfig(api_key=SecretStr(key))


@pytest.mark.parametrize('base_url', [
    'http://integrate.api.nvidia.com/v1',
    'https://example.test/v1',
    'https://integrate.api.nvidia.com.example.test/v1',
    'https://user@integrate.api.nvidia.com/v1',
    'https://integrate.api.nvidia.com:444/v1',
    'https://integrate.api.nvidia.com/v1?route=other',
    'https://integrate.api.nvidia.com/v1#fragment',
    'https://integrate.api.nvidia.com/other',
])
def test_config_rejects_non_approved_key_destinations(base_url) -> None:
    with pytest.raises(ModelInvocationError, match='MODEL_CONFIGURATION_INVALID'):
        config(base_url=base_url)


@pytest.mark.parametrize('overrides', [
    {'model_id': ''}, {'model_id': ' vendor/model '},
    {'max_completion_tokens': 0}, {'max_completion_tokens': True},
    {'temperature': float('nan')}, {'temperature': 2.0},
])
def test_config_rejects_invalid_generation_settings(overrides) -> None:
    with pytest.raises(ModelInvocationError, match='MODEL_CONFIGURATION_INVALID'):
        config(**overrides)


@pytest.mark.asyncio
async def test_adapter_sends_one_json_request_with_explicit_schema() -> None:
    transport, calls = transport_for(httpx.Response(200, json=payload()))
    adapter = NvidiaStructuredOutputAdapter(config(), transport=transport)
    result = await adapter.invoke(envelope(), timeout_seconds=1)

    assert len(calls) == 1
    assert calls[0].url == 'https://integrate.api.nvidia.com/v1/chat/completions'
    assert calls[0].headers['Authorization'] == 'Bearer test-nvidia-key'
    body = json.loads(calls[0].content)
    assert body['model'] == 'z-ai/glm-5.3-flash'
    assert body['response_format'] == {'type': 'json_object'}
    assert body['stream'] is False
    assert body['temperature'] == 0.0
    assert body['max_tokens'] == 4096
    assert body['reasoning_effort'] == 'low'
    assert body['chat_template_kwargs'] == {'clear_thinking': True}
    assert 'tools' not in body
    assert body['messages'][1]['content'] == envelope().user_message
    assert json.dumps(envelope().response_schema, ensure_ascii=False, sort_keys=True, separators=(',', ':')) in body['messages'][0]['content']
    assert result == ModelInvocationResult(
        content='{"plan":"rank"}',
        usage={'promptTokens': 10, 'completionTokens': 20, 'totalTokens': 30},
    )
    assert 'hidden model reasoning' not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('version_schema', [
    {'type': 'string', 'enum': ['3.0']}, {'type': 'string', 'const': '3.0'},
])
async def test_v3_model_schema_omits_only_identifier_enums_without_mutating_original(version_schema) -> None:
    identifier_fields = (
        'mention_id', 'unmapped_mention_ids', 'evidence_ids', 'semantic_ids',
        'candidate_entity_ids', 'selected_candidate_ids', 'reference_id',
        'selector_literal_candidate_id',
    )
    identifier_array = {
        'type': 'array', 'items': {'type': 'string', 'enum': ['offered-id']},
        'minItems': 1, 'maxItems': 2, 'uniqueItems': True,
    }
    preserved_fields = {
        'state': {'type': 'string', 'enum': ['selected', 'ambiguous']},
        'semantic_role': {'type': 'string', 'enum': ['subject_product']},
        'reason_code': {'type': 'string', 'enum': ['explicit']},
        'selected_ids': {'type': 'array', 'items': {'type': 'string', 'enum': ['rank', 'domestic_etf']}},
        'relation_id': {'type': 'array', 'items': {'type': 'string', 'enum': ['held_by']}, 'maxItems': 1},
        'expected_entity_type_ids': {'type': 'array', 'items': {'type': 'string', 'enum': ['FinancialProduct']}},
    }
    frame = {
        'type': 'object',
        'properties': {field: deepcopy(identifier_array) for field in identifier_fields} | preserved_fields,
        'required': list(identifier_fields) + list(preserved_fields),
        'additionalProperties': False,
    }
    schema = {
        'type': 'object',
        'properties': {
            'proposal_schema_version': version_schema,
            'frames': {'type': 'array', 'items': {'oneOf': [frame]}, 'minItems': 1, 'maxItems': 16},
            'references': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'reference_id': {'type': 'string', 'enum': ['reference-1']},
            }}, 'maxItems': 0},
        },
        'required': ['proposal_schema_version', 'frames', 'references'],
        'additionalProperties': False,
    }
    original = deepcopy(schema)
    transport, calls = transport_for(httpx.Response(200, json=payload()))
    await NvidiaStructuredOutputAdapter(config(), transport=transport).invoke(
        Envelope(response_schema=schema), 1,
    )
    system = json.loads(calls[0].content)['messages'][0]['content']
    model_schema_text = system.split('JSON Schema:\n', 1)[1]
    model_schema = json.loads(model_schema_text)
    assert schema == original
    assert model_schema_text == json.dumps(model_schema, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    model_frames = model_schema['properties']['frames']
    assert model_frames['minItems'] == 1
    assert model_frames['maxItems'] == 16
    model_frame = model_frames['items']['oneOf'][0]
    assert model_frame['required'] == frame['required']
    assert model_frame['additionalProperties'] is False
    for field in identifier_fields:
        assert model_frame['properties'][field] == {
            'type': 'array', 'items': {'type': 'string'},
            'minItems': 1, 'maxItems': 2, 'uniqueItems': True,
        }
    for field, preserved in preserved_fields.items():
        assert model_frame['properties'][field] == preserved
    assert model_schema['properties']['proposal_schema_version'] == version_schema
    assert model_schema['properties']['references']['items']['properties']['reference_id'] == {'type': 'string'}
    assert model_schema['properties']['references']['maxItems'] == 0
    assert model_schema['required'] == schema['required']


@pytest.mark.asyncio
@pytest.mark.parametrize('version', [None, '2.0'])
async def test_non_v3_schemas_keep_identifier_enums(version) -> None:
    schema = {
        'type': 'object', 'properties': {'semantic_ids': {
            'type': 'array', 'items': {'type': 'string', 'enum': ['candidate-1']},
        }}, 'required': ['semantic_ids'], 'additionalProperties': False,
    }
    if version is not None:
        schema['properties']['proposal_schema_version'] = {'type': 'string', 'enum': [version]}
    transport, calls = transport_for(httpx.Response(200, json=payload()))
    await NvidiaStructuredOutputAdapter(config(), transport=transport).invoke(
        Envelope(response_schema=schema), 1,
    )
    system = json.loads(calls[0].content)['messages'][0]['content']
    assert system.split('JSON Schema:\n', 1)[1] == json.dumps(
        schema, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    )


@pytest.mark.asyncio
async def test_other_model_does_not_receive_glm_template_options() -> None:
    transport, calls = transport_for(httpx.Response(200, json=payload()))
    await NvidiaStructuredOutputAdapter(
        config(model_id='meta/llama-3.3-70b-instruct'), transport=transport,
    ).invoke(envelope(), timeout_seconds=1)
    body = json.loads(calls[0].content)
    assert 'reasoning_effort' not in body
    assert 'chat_template_kwargs' not in body


@pytest.mark.asyncio
@pytest.mark.parametrize(('status', 'code'), [
    (400, 'MODEL_CONFIGURATION_INVALID'), (401, 'MODEL_CONFIGURATION_INVALID'),
    (403, 'MODEL_CONFIGURATION_INVALID'), (402, 'MODEL_CONFIGURATION_INVALID'),
    (422, 'MODEL_CONFIGURATION_INVALID'), (429, 'MODEL_RATE_LIMITED'),
    (500, 'MODEL_PROVIDER_UNAVAILABLE'), (503, 'MODEL_PROVIDER_UNAVAILABLE'),
    (302, 'MODEL_PROVIDER_UNAVAILABLE'),
])
async def test_provider_failures_are_safe_and_never_retried(status, code) -> None:
    transport, calls = transport_for(httpx.Response(status, text='test-nvidia-key hidden reasoning'))
    with pytest.raises(ModelInvocationError, match=code) as failure:
        await NvidiaStructuredOutputAdapter(config(), transport=transport).invoke(
            envelope(), timeout_seconds=1,
        )
    assert len(calls) == 1
    assert 'test-nvidia-key' not in str(failure.value)
    assert 'hidden reasoning' not in repr(failure.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(('error', 'code'), [
    (httpx.ReadTimeout('key secret'), 'MODEL_TIMEOUT'),
    (httpx.ConnectError('key secret'), 'MODEL_PROVIDER_UNAVAILABLE'),
])
async def test_transport_failures_are_safe(error, code) -> None:
    def handler(request):
        raise error

    with pytest.raises(ModelInvocationError, match=code):
        await NvidiaStructuredOutputAdapter(config(), transport=httpx.MockTransport(handler)).invoke(
            envelope(), timeout_seconds=1,
        )


@pytest.mark.asyncio
async def test_total_wall_clock_timeout_even_if_transport_never_times_out() -> None:
    cancelled = False

    async def handler(request):
        nonlocal cancelled
        try:
            await asyncio.sleep(1)
            return httpx.Response(200, json=payload())
        finally:
            cancelled = True

    with pytest.raises(ModelInvocationError, match='MODEL_TIMEOUT'):
        await NvidiaStructuredOutputAdapter(config(), transport=httpx.MockTransport(handler)).invoke(
            envelope(), timeout_seconds=0.01,
        )
    assert cancelled


@pytest.mark.asyncio
@pytest.mark.parametrize('seconds', [0, -1, float('nan'), float('inf'), True])
async def test_invalid_time_budget_never_makes_a_request(seconds) -> None:
    transport, calls = transport_for(httpx.Response(200, json=payload()))
    with pytest.raises(ModelInvocationError, match='MODEL_CONFIGURATION_INVALID'):
        await NvidiaStructuredOutputAdapter(config(), transport=transport).invoke(envelope(), seconds)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('content', ['', '  ', None, {'plan': 'rank'}])
async def test_empty_or_non_text_content_is_rejected(content) -> None:
    transport, _ = transport_for(httpx.Response(200, json=payload(content)))
    with pytest.raises(ModelInvocationError, match='MODEL_SCHEMA_INVALID'):
        await NvidiaStructuredOutputAdapter(config(), transport=transport).invoke(envelope(), 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('finish_reason', ['length', 'content_filter', 'tool_calls', None])
async def test_truncated_or_non_answer_finish_is_rejected(finish_reason) -> None:
    response = payload()
    response['choices'][0]['finish_reason'] = finish_reason
    transport, _ = transport_for(httpx.Response(200, json=response))
    with pytest.raises(ModelInvocationError, match='MODEL_SCHEMA_INVALID'):
        await NvidiaStructuredOutputAdapter(config(), transport=transport).invoke(envelope(), 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('field_value', [
    ('refusal', 'Cannot comply'), ('tool_calls', [{'id': 'call-1'}]),
    ('role', 'user'),
])
async def test_refusals_and_tool_calls_are_not_intent_proposals(field_value) -> None:
    response = payload()
    response['choices'][0]['message'][field_value[0]] = field_value[1]
    transport, _ = transport_for(httpx.Response(200, json=response))
    with pytest.raises(ModelInvocationError, match='MODEL_SCHEMA_INVALID'):
        await NvidiaStructuredOutputAdapter(config(), transport=transport).invoke(envelope(), 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('usage', [
    None, {}, {'prompt_tokens': True, 'completion_tokens': 20, 'total_tokens': 21},
    {'prompt_tokens': -1, 'completion_tokens': 20, 'total_tokens': 19},
    {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 31},
    {'prompt_tokens': 10.0, 'completion_tokens': 20, 'total_tokens': 30},
])
async def test_usage_must_be_complete_nonnegative_integers(usage) -> None:
    response = payload()
    response['usage'] = usage
    transport, _ = transport_for(httpx.Response(200, json=response))
    with pytest.raises(ModelInvocationError, match='MODEL_SCHEMA_INVALID'):
        await NvidiaStructuredOutputAdapter(config(), transport=transport).invoke(envelope(), 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    httpx.Response(200, text='not-json'),
    httpx.Response(200, json=[]),
    httpx.Response(200, json={'choices': []}),
    httpx.Response(200, text='{"choices":[],"choices":[],"usage":{}}'),
])
async def test_malformed_or_duplicate_provider_payload_is_rejected(response) -> None:
    transport, _ = transport_for(response)
    with pytest.raises(ModelInvocationError, match='MODEL_SCHEMA_INVALID'):
        await NvidiaStructuredOutputAdapter(config(), transport=transport).invoke(envelope(), 1)


@pytest.mark.asyncio
async def test_model_proposal_is_left_for_existing_strict_validation_and_repair() -> None:
    transport, _ = transport_for(httpx.Response(200, json=payload('invalid proposal JSON')))
    result = await NvidiaStructuredOutputAdapter(config(), transport=transport).invoke(envelope(), 1)
    assert result.content == 'invalid proposal JSON'


def hybrid_inputs():
    from financial_agent.contracts.canonical import build_request_key
    from financial_agent.contracts.request import RequestContext, Segment
    from financial_agent.intent.catalog import load_hybrid_catalog
    from financial_agent.intent.view import ActiveDatasetPin, build_hybrid_manifest
    from .view_fixtures import hybrid_manifest_versions

    root = Path(__file__).resolve().parents[2]
    catalog = load_hybrid_catalog(root)
    now = datetime(2026, 10, 2, tzinfo=UTC)
    question = '비용 부담이 작은 ETF 다섯 개'
    context = RequestContext(
        request_key=build_request_key('nvidia-pins', question, 'dataset-v1', '1.0'),
        run_id='run-nvidia-pins', dataset_version='dataset-v1', producer='test',
        created_at=now, question_id='nvidia-pins', question=question,
        segments=(Segment(segment_id='s1', ordinal=0, text=question),),
        deadline_at=now + timedelta(seconds=55),
    )
    versions = hybrid_manifest_versions() | {'adapter_version': 'nvidia-chat-json-proposal-v4'}
    return {
        'catalog': catalog, 'context': context,
        'manifest': build_hybrid_manifest(catalog, versions),
        'active_dataset_pin': ActiveDatasetPin(dataset_version='dataset-v1', manifest_hash='a' * 64),
    }


@pytest.mark.asyncio
async def test_nvidia_provenance_reaches_hybrid_preparation_validation_and_solver() -> None:
    from financial_agent.intent.query_contract_registry import load_query_contract_registry
    from financial_agent.intent.query_contract_solver import solve_query_contracts
    from financial_agent.intent.service import IntentResolverService, build_hybrid_repair_envelope
    from financial_agent.intent.view import NVIDIA_HYBRID_ADAPTER_VERSION

    class EmptyRepository:
        async def search_batch(self, dataset_version, mentions):
            return {}

    inputs = hybrid_inputs()
    transport, calls = transport_for(httpx.Response(200, json=payload()))
    service = IntentResolverService(
        adapter=NvidiaStructuredOutputAdapter(config(), transport=transport),
        entity_repository=EmptyRepository(),
        catalog=inputs['catalog'], manifest=inputs['manifest'],
        active_dataset_pin=inputs['active_dataset_pin'],
    )
    prepared = await service.prepare_hybrid(inputs['context'])
    mention = next(item for item in prepared.view.mention_spans.items if item.text == '비용 부담')
    proposal = {
        'proposal_schema_version': '3.0',
        'frames': [{
            'segment_ids': ['s1'],
            'action_choice': {'state': 'selected', 'selected_ids': ['rank'], 'evidence_ids': [], 'reason_code': 'explicit'},
            'product_family_choice': {'state': 'selected', 'selected_ids': ['domestic_etf'], 'evidence_ids': [], 'reason_code': 'implicit'},
            'entity_type_ids': ['FinancialProduct'],
            'semantic_links': [{'mention_id': mention.mention_id, 'state': 'selected', 'semantic_ids': ['fee_rate'], 'reason_code': 'implicit'}],
            'unmapped_mention_ids': [], 'semantic_coverage': {'state': 'covered', 'reason': 'none'},
            'entity_hints': [], 'produced_result_hints': ['candidates'],
        }],
        'references': [], 'context_links': [], 'slot_mutations': [],
        'semantic_flag_hints': [], 'frame_limit_exceeded': False,
    }
    resolution = service.validate_hybrid_response(prepared, json.dumps(proposal))
    candidates = solve_query_contracts(
        resolution=resolution, view=prepared.view,
        exact_locks=prepared.view.exact_semantic_locks,
        registry=load_query_contract_registry(Path(__file__).resolve().parents[2]),
        semantic_catalog=inputs['catalog'],
    )
    assert prepared.view.build_manifest.adapter_version == NVIDIA_HYBRID_ADAPTER_VERSION
    assert resolution.build_manifest.adapter_version == NVIDIA_HYBRID_ADAPTER_VERSION
    assert candidates.frames[0].complete_candidates
    assert candidates.frames[0].complete_candidates[0].contract.ordering[0].field_concept_id == 'fee_rate'
    assert calls == []

    from financial_agent.intent.errors import ResolverContractError

    original_schema = deepcopy(prepared.prompt.response_schema)
    await service._adapter.invoke(prepared.prompt, 1)
    repair = build_hybrid_repair_envelope(
        prepared, ResolverContractError('MODEL_PROPOSAL_SCHEMA_INVALID'),
    )
    await service._adapter.invoke(repair, 1)
    model_schemas = [json.loads(call.content)['messages'][0]['content'].split('JSON Schema:\n', 1)[1] for call in calls]
    assert model_schemas[0] == model_schemas[1]
    model_schema = json.loads(model_schemas[0])
    model_link = model_schema['properties']['frames']['items']['properties']['semantic_links']['items']['oneOf'][0]
    assert model_link['properties']['semantic_ids']['items'] == {'type': 'string'}
    assert prepared.prompt.response_schema == original_schema
    assert repair.response_schema == original_schema
    proposal['frames'][0]['semantic_links'][0]['semantic_ids'] = ['domestic_etf']
    with pytest.raises(ResolverContractError, match='MODEL_PROPOSAL_SCHEMA_INVALID'):
        service.validate_hybrid_response(prepared, json.dumps(proposal))


def test_hybrid_manifest_rejects_unknown_adapter_and_extra_version_fields() -> None:
    from financial_agent.intent.catalog import load_hybrid_catalog
    from financial_agent.intent.view import ResolverInvariantError, build_hybrid_manifest
    from .view_fixtures import hybrid_manifest_versions

    catalog = load_hybrid_catalog(Path(__file__).resolve().parents[2])
    for versions in (
        hybrid_manifest_versions() | {'adapter_version': 'unregistered-provider'},
        hybrid_manifest_versions() | {'unregistered_component': 'v1'},
    ):
        with pytest.raises(ResolverInvariantError, match='CATALOG_VERSION_MISMATCH'):
            build_hybrid_manifest(catalog, versions)


@pytest.mark.asyncio
async def test_hybrid_preparation_rejects_forged_adapter_pin() -> None:
    from financial_agent.intent.service import IntentResolverService
    from financial_agent.intent.view import ResolverInvariantError

    class UnusedRepository:
        async def search_batch(self, dataset_version, mentions):
            pytest.fail('pin rejection must happen before entity search')

    inputs = hybrid_inputs()
    forged = inputs['manifest'].model_copy(update={'adapter_version': 'unregistered-provider'})
    service = IntentResolverService(
        adapter=NvidiaStructuredOutputAdapter(config()), entity_repository=UnusedRepository(),
        catalog=inputs['catalog'], manifest=forged, active_dataset_pin=inputs['active_dataset_pin'],
    )
    with pytest.raises(ResolverInvariantError, match='CATALOG_VERSION_MISMATCH'):
        await service.prepare_hybrid(inputs['context'])

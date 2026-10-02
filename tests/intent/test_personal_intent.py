from datetime import UTC, date, datetime
import json
from pathlib import Path

import pytest

from financial_agent.contracts.request import NamedEntityMention
from financial_agent.intent.candidates import EntityCandidate
from financial_agent.intent.catalog import load_hybrid_catalog
from financial_agent.intent.model import ModelInvocationResult
from financial_agent.intent.personal import PersonalIntentService
from financial_agent.intent.query_contract_registry import load_query_contract_registry
from financial_agent.intent.service import IntentResolverService
from financial_agent.intent.view import (
    ActiveDatasetPin, HYBRID_CANDIDATE_POLICY_VERSION, HYBRID_PROMPT_VERSION,
    HYBRID_RESOLVER_SCHEMA_VERSION, NORMALIZER_VERSION,
    NVIDIA_HYBRID_ADAPTER_VERSION, build_hybrid_manifest,
)
from financial_agent.planning.physical_bindings import (
    load_physical_binding_registry, load_semantic_sql_policy_registry,
)
from financial_agent.planning.registry import load_planning_registry
from financial_agent.planning.semantic_compiler import SemanticPlanningCompiler


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 2, tzinfo=UTC)
PIN = ActiveDatasetPin(dataset_version='dataset-v1', manifest_hash='a' * 64)


class Discovery:
    def __init__(self, name=None):
        self.name = name

    async def discover(self, context):
        if not self.name:
            return ()
        start = context.question.index(self.name)
        return (NamedEntityMention(
            mention_id=f'mention-s1-{start}-{start + len(self.name)}', segment_id='s1',
            text=self.name, expected_entity_types=(), start_char=start,
            end_char=start + len(self.name),
        ),)


class Entities:
    def __init__(self, family='domestic_etf'):
        self.family = family

    async def search_batch(self, dataset_version, mentions):
        return {mention.mention_id: (EntityCandidate(
            entity_id='product-1', canonical_name=mention.text,
            ontology_type_ids=('ETF', 'FinancialProduct'), product_family=self.family,
            match_kind='exact_name', score=1_000_000, source_id='source-1',
        ),) for mention in mentions}


class Adapter:
    def __init__(self, family, field, *, action='rank', entity=True, policy=False):
        self.family, self.field, self.action = family, field, action
        self.entity, self.policy = entity, policy
        self.calls = 0

    async def invoke(self, envelope, timeout_seconds):
        self.calls += 1
        view = json.loads(envelope.user_message)['view']
        links = []
        if self.field:
            card = next(card for card in view['compact_semantic_catalog']['concepts']
                        if card['semantic_id'] == self.field)
            mention = next((m for m in view['mention_spans']['items']
                            if m['text'] == card['preferred_label_ko']), None)
            if mention is None:
                surface = {'fee_rate': '총보수', 'maturity_date': '만기일',
                           'trailing_1y_historical_cumulative_return': '수익률'}[self.field]
                mention = next(m for m in view['mention_spans']['items'] if m['text'] == surface)
            links = [{'mention_id': mention['mention_id'], 'state': 'selected',
                      'semantic_ids': [self.field], 'reason_code': 'explicit'}]
        hints = []
        if self.entity:
            for group in view['entity_candidates']:
                ids = [item['entity_id'] for item in group['items']]
                hints.append({'semantic_role': 'frame_subject', 'relation_id': [],
                              'expected_entity_type_ids': ['FinancialProduct'],
                              'mention_id': [group['mention_id']],
                              'candidate_entity_ids': ids, 'selected_candidate_ids': ids[:1]})
        flags = []
        if self.policy:
            evidence = next(e for e in view['evidence_candidates'] if '내년' in e['text'])
            flags = [{'semantic_tag': 'FUTURE_FORECAST',
                      'evidence_ids': [evidence['evidence_id']], 'reason_code': 'implicit'}]
        payload = {
            'proposal_schema_version': '3.0',
            'frames': [{'segment_ids': ['s1'],
                        'action_choice': {'state': 'selected', 'selected_ids': [self.action],
                                          'evidence_ids': [], 'reason_code': 'explicit'},
                        'product_family_choice': {'state': 'selected', 'selected_ids': [self.family],
                                                  'evidence_ids': [], 'reason_code': 'explicit'},
                        'entity_type_ids': ['FinancialProduct'], 'semantic_links': links,
                        'unmapped_mention_ids': [],
                        'semantic_coverage': {'state': 'covered', 'reason': 'none'},
                        'entity_hints': hints, 'produced_result_hints': ['candidates']}],
            'references': [], 'context_links': [], 'slot_mutations': [],
            'semantic_flag_hints': flags, 'frame_limit_exceeded': False,
        }
        return ModelInvocationResult(content=json.dumps(payload),
                                     usage={'promptTokens': 1, 'completionTokens': 1, 'totalTokens': 2})


def service(adapter, *, name=None, actual_family='domestic_etf'):
    catalog = load_hybrid_catalog(ROOT)
    manifest = build_hybrid_manifest(catalog, {
        'normalizer_version': NORMALIZER_VERSION,
        'candidate_policy_version': HYBRID_CANDIDATE_POLICY_VERSION,
        'resolver_schema_version': HYBRID_RESOLVER_SCHEMA_VERSION,
        'prompt_version': HYBRID_PROMPT_VERSION,
        'adapter_version': NVIDIA_HYBRID_ADAPTER_VERSION,
    })
    resolver = IntentResolverService(
        adapter=adapter, entity_repository=Entities(actual_family), catalog=catalog,
        manifest=manifest, active_dataset_pin=PIN,
        query_contract_registry=load_query_contract_registry(ROOT), utcnow=lambda: NOW,
    )
    return PersonalIntentService(
        resolver=resolver, discovery=Discovery(name),
        compiler=SemanticPlanningCompiler(load_physical_binding_registry(ROOT),
                                         load_semantic_sql_policy_registry(ROOT),
                                         load_planning_registry(ROOT)),
        pin=PIN, cutoff_date=date(2026, 8, 24), model_id='test/model', utcnow=lambda: NOW,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('family,label', [
    ('domestic_etf', '국내 ETF'), ('overseas_etf', '해외 ETF'),
    ('public_fund', '공모펀드'),
])
async def test_raw_question_preserves_product_family_and_ordering(family, label):
    adapter = Adapter(family, 'fee_rate')
    result = await service(adapter).resolve(f'{label} 중 총보수가 낮은 5개')
    output = result.to_dict()
    assert output['interpreted_product_families'] == [family]
    assert output['frames'][0]['candidate_contract']['ordering'][0]['direction'] == 'asc'
    assert output['frames'][0]['candidate_contract']['limit'] == 5
    if family == 'public_fund':
        assert output['target_product_families'] == []
        assert output['frames'][0]['selected_contract'] is None
        assert 'PUBLIC_FUND_TOTAL_FEE_DEFINITION_UNVERIFIED' in output['issue_codes']
    else:
        assert output['target_product_families'] == [family]
        assert output['frames'][0]['selected_contract'] is not None
        assert output['issue_codes'] == []
        assert output['route'] == 'compose'
    assert output['execution_performed'] is False
    assert adapter.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('family,label,threshold', [
    ('domestic_etf', '국내 ETF', '0.1'), ('overseas_etf', '해외 ETF', '0.1'),
    ('public_fund', '공모펀드', '0.3'),
])
async def test_decimal_fee_screen_preserves_family_predicate_and_planning_boundary(
    family, label, threshold
):
    adapter = Adapter(family, 'fee_rate', action='screen')
    result = await service(adapter).resolve(f'{label} 중 총보수 {threshold}% 이하인 상품 찾아줘')
    output = result.to_dict()
    frame = output['frames'][0]
    contract = frame['candidate_contract']
    assert output['interpreted_product_families'] == [family]
    assert contract['action_id'] == 'screen'
    assert contract['scope']['product_family_ids'] == [family]
    assert contract['predicate']['field_concept_id'] == 'fee_rate'
    assert contract['predicate']['operator_id'] == 'lte'
    assert contract['predicate']['value']['kind'] == 'decimal'
    assert contract['predicate']['value']['decimal'] == threshold
    assert contract['predicate']['value']['unit_id'] == 'percent'
    if family == 'public_fund':
        assert output['route'] == 'explore'
        assert 'PUBLIC_FUND_TOTAL_FEE_DEFINITION_UNVERIFIED' in output['issue_codes']
        assert output['target_product_families'] == []
        assert frame['selected_contract'] is None
        assert output['logical_query_plan'] is None
    else:
        assert output['route'] == 'compose'
        assert output['issue_codes'] == []
        assert output['target_product_families'] == [family]
        assert frame['selected_contract'] == contract
        assert output['logical_query_plan'] is not None
    assert output['execution_performed'] is False
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_bond_maturity_uses_registered_date_binding():
    result = await service(Adapter('domestic_bond', 'maturity_date', action='lookup')).resolve(
        '국내채권 만기일 알려줘')
    output = result.to_dict()
    assert output['interpreted_product_families'] == ['domestic_bond']
    assert output['target_product_families'] == ['domestic_bond']
    assert output['frames'][0]['selected_contract'] is not None
    assert output['frames'][0]['candidate_contract'] is not None
    assert output['route'] == 'compose'
    assert output['issue_codes'] == []


@pytest.mark.asyncio
async def test_discovered_product_is_bound_to_scope_and_provenance():
    result = await service(Adapter('domestic_etf', 'fee_rate', action='lookup'),
                           name='TIGER 미국S&P500').resolve('TIGER 미국S&P500의 총보수 알려줘')
    output = result.to_dict()
    assert output['frames'][0]['candidate_contract']['scope']['entity_refs'] == ['product-1']
    assert output['frames'][0]['selected_contract'] is not None
    assert output['discovered_entities'][0]['text'] == 'TIGER 미국S&P500'
    assert output['adapter_version'] == NVIDIA_HYBRID_ADAPTER_VERSION


@pytest.mark.asyncio
async def test_ignored_named_product_cannot_broaden_to_whole_family():
    result = await service(Adapter('domestic_etf', 'fee_rate', action='lookup', entity=False),
                           name='TIGER 미국S&P500').resolve('TIGER 미국S&P500의 총보수 알려줘')
    output = result.to_dict()
    assert output['route'] == 'abstain'
    assert 'ENTITY_SCOPE_UNRESOLVED' in output['issue_codes']
    assert output['logical_query_plan'] is None


@pytest.mark.asyncio
async def test_product_family_conflict_cannot_become_executable():
    result = await service(Adapter('overseas_etf', 'fee_rate', action='lookup'),
                           name='TIGER 미국S&P500').resolve('TIGER 미국S&P500의 총보수 알려줘')
    output = result.to_dict()
    assert output['route'] == 'abstain'
    assert 'ENTITY_PRODUCT_FAMILY_MISMATCH' in output['issue_codes']


@pytest.mark.asyncio
@pytest.mark.parametrize('family', ['domestic_etf', 'overseas_etf'])
async def test_named_etn_cannot_execute_in_an_etf_product_family(family):
    class EtnEntities(Entities):
        async def search_batch(self, dataset_version, mentions):
            candidates = await super().search_batch(dataset_version, mentions)
            return {mention_id: tuple(candidate.model_copy(update={
                'ontology_type_ids': ('ETN', 'FinancialProduct'),
            }) for candidate in items) for mention_id, items in candidates.items()}

    adapter = Adapter(family, 'fee_rate', action='lookup')
    resolver = service(adapter, name='합성 ETN', actual_family=family)
    resolver._resolver._entity_repository = EtnEntities(family)
    result = await resolver.resolve('합성 ETN의 총보수 알려줘')
    output = result.to_dict()

    assert output['route'] == 'explore'
    assert output['disposition'] == 'limitation'
    assert output['issue_codes'] == ['PRODUCT_SUBTYPE_NOT_SUPPORTED']
    assert output['frames'][0]['candidate_contract']['scope']['entity_refs'] == ['product-1']
    assert output['frames'][0]['selected_contract'] is None
    assert output['target_product_families'] == []
    assert output['logical_query_plan'] is None
    assert output['execution_performed'] is False
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_model_grounded_forecast_flag_blocks_a_complete_contract():
    result = await service(Adapter('domestic_etf', 'fee_rate', policy=True)).resolve(
        '내년에 가장 많이 오를 국내 ETF 중 총보수가 낮은 5개')
    output = result.to_dict()
    assert output['route'] == 'abstain'
    assert 'POLICY_BLOCKED' in output['issue_codes']


@pytest.mark.asyncio
async def test_past_return_does_not_invent_an_omitted_period():
    adapter = Adapter('domestic_etf', None)
    # The explicit metric mention is intentionally period-free; the model must
    # select the registered concept, but may not invent a period qualifier.
    adapter.field = 'trailing_1y_historical_cumulative_return'
    result = await service(adapter).resolve('국내 ETF 수익률 높은 5개')
    output = result.to_dict()
    assert output['frames'][0]['selected_contract'] is None
    assert 'REQUIRED_QUALIFIER_MISSING' in output['issue_codes']
    assert output['logical_query_plan'] is None


@pytest.mark.asyncio
async def test_explicit_past_return_period_survives_without_execution_fallback():
    result = await service(Adapter('overseas_etf', 'trailing_1y_historical_cumulative_return')).resolve(
        '해외 ETF 최근 1년 수익률 높은 5개')
    output = result.to_dict()
    assert output['frames'][0]['candidate_contract']['qualifiers']['period_id'] == 'P1Y'
    assert output['frames'][0]['selected_contract'] is None
    assert output['target_product_families'] == []
    assert output['route'] == 'explore'
    assert 'SOURCE_ONE_YEAR_RETURN_NOT_PROVIDED' in output['issue_codes']


@pytest.mark.asyncio
async def test_request_after_dataset_cutoff_cannot_approve_a_plan():
    result = await service(Adapter('domestic_etf', 'fee_rate')).resolve(
        '2026-09-01 기준 국내 ETF 중 총보수가 낮은 5개')
    output = result.to_dict()
    assert output['route'] == 'explore'
    assert output['issue_codes'] == ['REQUEST_AFTER_DATASET_CUTOFF']
    assert output['target_product_families'] == []
    assert output['frames'][0]['selected_contract'] is None
    assert output['logical_query_plan'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('question', ['', ' ', '가' * 4097])
async def test_bad_question_is_rejected_before_model_call(question):
    adapter = Adapter('domestic_etf', 'fee_rate')
    with pytest.raises(ValueError, match='QUESTION_INVALID'):
        await service(adapter).resolve(question)
    assert adapter.calls == 0


@pytest.mark.asyncio
async def test_explicit_domestic_one_year_rank_produces_registered_logical_plan():
    result = await service(Adapter('domestic_etf', 'trailing_1y_historical_cumulative_return')).resolve(
        '국내 ETF 최근 1년 수익률 높은 5개')
    output = result.to_dict()
    assert output['route'] == 'compose'
    assert output['issue_codes'] == []
    assert output['target_product_families'] == ['domestic_etf']
    assert output['frames'][0]['selected_contract']['qualifiers']['period_id'] == 'P1Y'
    assert output['logical_query_plan']['tasks'][0]['binding_ids'] == ['domestic-etf-return-1y.v1']


@pytest.mark.asyncio
async def test_bond_maturity_threshold_is_date_predicate_and_not_as_of_date():
    result = await service(Adapter('domestic_bond', 'maturity_date', action='screen')).resolve(
        '국내채권 만기일 2030-01-15 이하인 상품 찾아줘')
    output = result.to_dict()
    assert output['route'] == 'compose'
    assert output['issue_codes'] == []
    contract = output['frames'][0]['selected_contract']
    assert contract['predicate']['value']['kind'] == 'date'
    assert contract['predicate']['value']['date'] == '2030-01-15'
    assert contract['predicate']['value']['unit_id'] is None
    assert contract['qualifiers']['as_of_date'] is None

"""Source-owned categorical predicates must survive through contract solving."""

from datetime import date
import json

import pytest

from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.contracts.request import NamedEntityMention
from financial_agent.intent.axis_locks import build_exact_semantic_locks
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.condition_normalization import POLICY_PATH, load_personal_condition_policy
from financial_agent.intent.literals import extract_literals
from financial_agent.intent.normalization import normalize_request
from financial_agent.intent.operators import extract_operator_candidates
from financial_agent.intent.query_contract_solver import solve_query_contracts
from financial_agent.intent.query_contracts import QueryOperatorId

from .test_literals import normalized_request
from .test_query_contract_solver import PROJECT_ROOT, REGISTRY, _axis, _candidate_pipeline
from .test_personal_intent import Adapter
from financial_agent.intent.model import ModelInvocationResult


@pytest.mark.parametrize('question', [
    '일본 주식형 해외 ETF', '일본주식형 해외 ETF',
])
def test_region_and_asset_class_keep_distinct_values_and_original_offsets(question):
    request = normalized_request(question)
    literals = extract_literals(request)
    assert [(item.kind, item.canonical_value) for item in literals] == [
        ('region', 'Japan'), ('asset_class', 'Equity'),
    ]
    assert [question[item.start_char:item.end_char] for item in literals] == ['일본', '주식형']
    operators = extract_operator_candidates(request, literals)
    assert [(item.operator_id.value, item.compatible_value_candidate_ids) for item in operators] == [
        ('eq', (literals[0].literal_id,)), ('eq', (literals[1].literal_id,)),
    ]


def test_credit_threshold_is_source_owned_and_does_not_enable_ordered_strings():
    request = normalized_request('신용등급 ＡＡ－ 이상')
    literals = extract_literals(request)
    assert [(item.kind, item.original_text, item.canonical_value) for item in literals] == [
        ('credit_grade', 'ＡＡ－', 'AA-'),
    ]
    operators = extract_operator_candidates(request, literals)
    assert [(item.operator_id.value, item.compatible_value_candidate_ids) for item in operators] == [
        ('gte', (literals[0].literal_id,)),
    ]
    assert extract_operator_candidates(normalized_request('USD 이하'), extract_literals(normalized_request('USD 이하'))) == ()


def test_explicit_aum_presence_emits_zero_arity_operator():
    request = normalized_request('해외 ETF 중 AUM이 있는 상품')
    operators = extract_operator_candidates(request, extract_literals(request))
    assert [(item.operator_id.value, item.arity.value, item.compatible_value_candidate_ids) for item in operators] == [
        ('is_present', 'zero', ()),
    ]


def test_operator_literal_association_is_preserved_in_exact_locks():
    request = normalized_request('일본 주식형 해외 ETF 중 총보수 0.5% 이하')
    literals = extract_literals(request)
    operators = extract_operator_candidates(request, literals)
    locks = build_exact_semantic_locks(request, load_catalog(PROJECT_ROOT), literals=literals)
    by_id = {item.canonical_id: item for item in locks if item.role == 'literal'}
    assert by_id
    assert sorted((lock.canonical_id, lock.compatible_value_candidate_ids) for lock in locks if lock.role == 'operator') == sorted(
        (operator.operator_id.value, operator.compatible_value_candidate_ids) for operator in operators
    )


def test_condition_words_inside_an_explicit_product_name_are_masked():
    question = '일본주식형 AA- 판매가능 ETF의 총보수 0.5% 이하'
    request = normalized_request(question)
    name = '일본주식형 AA- 판매가능 ETF'
    context = request.context.model_copy(update={'named_entities': (NamedEntityMention(
        mention_id='entity-1', segment_id='s1', text=name,
        expected_entity_types=('FinancialProduct',), start_char=0, end_char=len(name),
    ),)})
    request = normalize_request(context)
    assert [(item.kind, item.canonical_value) for item in extract_literals(request)] == [('percentage', '0.5')]
    assert [item.operator_id.value for item in extract_operator_candidates(request, extract_literals(request))] == ['lte']


@pytest.mark.parametrize('question', ['일본전자 주식형태 AAAB', '판매가능성 알려줘'])
def test_substrings_are_not_conditions(question):
    assert extract_literals(normalized_request(question)) == ()


def _v2_inputs(question, family, fields):
    view, locks = _candidate_pipeline(question)
    definitions = {item.concept_id: item for item in view.concept_definitions}
    catalog = load_catalog(PROJECT_ROOT)
    from financial_agent.intent.view import ResolverViewConcept, ResolverViewSemanticCandidate, ResolverViewSemanticCandidateGroup
    groups = []
    definition_ids = tuple(item[0] for item in fields) + (
        ('maturity_date', 'remaining_days') if any(item[0] == 'availability_status' for item in fields) else ()
    )
    for concept_id in definition_ids:
        concept = catalog.concepts_by_id[concept_id]
        definitions[concept_id] = ResolverViewConcept(
            concept_id=concept.id, kind=concept.kind, definition_ko=concept.definition_ko,
            value_kind=concept.value_kind, allowed_product_families=concept.allowed_product_families,
            allowed_ontology_types=concept.allowed_ontology_types, required_qualifiers=(),
            allowed_operators=concept.allowed_operators, missingness_sensitive=concept.missingness_sensitive,
            normalization_rule=concept.normalization_rule,
        )
    for concept_id, surface in fields:
        start = question.index(surface)
        groups.append(ResolverViewSemanticCandidateGroup(
            mention_id=f'mention-s1-{start}-{start + len(surface)}',
            items=(ResolverViewSemanticCandidate(semantic_id=concept_id, match_kind='group_alias', score=1_000_000),),
        ))
    view = view.model_copy(update={'concept_definitions': tuple(definitions.values()), 'semantic_candidates': tuple(groups)})
    return _axis(IntentType.SCREEN, family=family), view, locks


def _solve(question, family, fields):
    resolution, view, locks = _v2_inputs(question, family, fields)
    return solve_query_contracts(resolution=resolution, view=view, exact_locks=locks, registry=REGISTRY)


class ConditionAdapter(Adapter):
    """Metadata-only proposal fixture for actual local DB contract verification."""

    def __init__(self, family, *, missing=()):
        super().__init__(family, None, action='screen', entity=False)
        self.missing = frozenset(missing)

    async def invoke(self, envelope, timeout_seconds):
        result = await super().invoke(envelope, timeout_seconds)
        proposal = json.loads(result.content)
        view = json.loads(envelope.user_message)['view']
        links = []
        for literal in view['literal_candidates']:
            field_id = literal['kind']
            if field_id not in {'region', 'asset_class', 'credit_grade', 'availability_status', 'currency'} or field_id in self.missing:
                continue
            mention_id = f"mention-{literal['segment_id']}-{literal['start_char']}-{literal['end_char']}"
            links.append({'mention_id': mention_id, 'state': 'selected',
                          'semantic_ids': [field_id], 'reason_code': 'explicit'})
        for lock in view['exact_lock_projections']:
            if lock['role'] == 'field' and lock['canonical_semantic_id'] not in self.missing:
                links.append({'mention_id': lock['mention_id'], 'state': 'selected',
                              'semantic_ids': [lock['canonical_semantic_id']], 'reason_code': 'explicit'})
        proposal['frames'][0]['semantic_links'] = links
        return ModelInvocationResult(content=json.dumps(proposal), usage=result.usage)


def test_japan_equity_and_numeric_fee_predicates_are_all_preserved():
    result = _solve('일본 주식형 해외 ETF 중 총보수 0.5% 이하', ProductFamily.OVERSEAS_ETF,
                    (('region', '일본'), ('asset_class', '주식형'), ('fee_rate', '총보수')))
    assert len(result.complete_candidates) == 1
    atoms = result.complete_candidates[0].contract.predicate.children
    assert {(item.field_concept_id, item.operator_id.value, item.value.string or item.value.decimal) for item in atoms} == {
        ('region', 'eq', 'Japan'), ('asset_class', 'eq', 'Equity'), ('fee_rate', 'lte', '0.5'),
    }
    contract = result.complete_candidates[0].contract
    _, _, locks = _v2_inputs('일본 주식형 해외 ETF 중 총보수 0.5% 이하', ProductFamily.OVERSEAS_ETF,
                             (('region', '일본'), ('asset_class', '주식형'), ('fee_rate', '총보수')))
    eq_locks = {lock.compatible_value_candidate_ids[0]: lock.lock_id for lock in locks
                if lock.role == 'operator' and lock.canonical_id == 'eq'}
    for index, atom in enumerate(atoms):
        if atom.operator_id is not QueryOperatorId.EQ:
            continue
        refs = {item.source_ref for item in contract.provenance
                if item.semantic_input_id.split('.source.')[0] == f'predicate.children.{index}.operator_id'}
        literal = next(item for item in extract_literals(normalized_request('일본 주식형 해외 ETF 중 총보수 0.5% 이하'))
                       if item.canonical_value == atom.value.string)
        assert refs == {eq_locks[literal.literal_id]}


@pytest.mark.parametrize('missing', ['region', 'asset_class'])
def test_missing_categorical_meaning_cannot_drop_one_condition(missing):
    fields = tuple(item for item in (('region', '일본'), ('asset_class', '주식형'), ('fee_rate', '총보수')) if item[0] != missing)
    result = _solve('일본 주식형 해외 ETF 중 총보수 0.5% 이하', ProductFamily.OVERSEAS_ETF, fields)
    assert result.complete_candidates == ()


def test_credit_gte_is_normalized_to_closed_ordered_grade_membership():
    result = _solve('국내채권 중 신용등급 AA- 이상', ProductFamily.DOMESTIC_BOND, (('credit_grade', '신용등급'),))
    assert len(result.complete_candidates) == 1
    contract = result.complete_candidates[0].contract
    assert contract.predicate.operator_id is QueryOperatorId.IN
    assert tuple(item.string for item in contract.predicate.values) == ('AAA', 'AA+', 'AA0', 'AA-')
    assert any(item.source_ref == 'personal-credit-grade-aa-minus.v1' for item in contract.provenance)
    assert any('gte' in item.source_ref for item in contract.provenance)
    assert any('credit_grade' in item.source_ref for item in contract.provenance)


def test_bond_saleability_expansion_keeps_currency_and_credit_conditions():
    question = '현재 판매 가능한 원화채권 중 AA- 이상 종목 알려줘.'
    result = _solve(question, ProductFamily.DOMESTIC_BOND,
                    (('availability_status', '판매 가능한'), ('currency', '원화'), ('credit_grade', 'AA-')))
    assert len(result.complete_candidates) == 1
    contract = result.complete_candidates[0].contract
    atoms = contract.predicate.children
    assert {item.field_concept_id for item in atoms} == {'maturity_date', 'remaining_days', 'currency', 'credit_grade'}
    maturity = next(item for item in atoms if item.field_concept_id == 'maturity_date')
    assert maturity.operator_id is QueryOperatorId.GT
    assert maturity.value.date == date(2026, 8, 24)
    days = next(item for item in atoms if item.field_concept_id == 'remaining_days')
    assert days.operator_id is QueryOperatorId.GT
    assert days.value.decimal == '0'
    assert contract.qualifiers.currency_id is None
    assert next(item for item in atoms if item.field_concept_id == 'currency').value.unit_id is None
    assert any(item.source_ref == 'personal-organizer-bond-saleability.v1' for item in contract.provenance)


@pytest.mark.parametrize('question', [
    '국내채권 중 판매 가능하지 않은 종목', '국내채권 중 판매 가능한 종목 제외',
])
def test_saleability_negation_does_not_become_positive_availability(question):
    result = _solve(question, ProductFamily.DOMESTIC_BOND, (('availability_status', '판매 가능'),))
    assert result.complete_candidates == ()


def test_aum_presence_does_not_borrow_a_fee_field_when_model_omits_aum():
    result = _solve('일본 주식형 해외 ETF 중 총보수 0.5% 이하이고 AUM이 있는 상품', ProductFamily.OVERSEAS_ETF,
                    (('region', '일본'), ('asset_class', '주식형'), ('fee_rate', '총보수')))
    assert result.complete_candidates == ()


@pytest.mark.parametrize('missing', ['availability_status', 'currency', 'credit_grade'])
def test_any_missing_bond_filter_prevents_broader_execution(missing):
    question = '현재 판매 가능한 원화채권 중 AA- 이상 종목 알려줘.'
    fields = tuple(item for item in (('availability_status', '판매 가능한'), ('currency', '원화'), ('credit_grade', 'AA-'))
                   if item[0] != missing)
    assert _solve(question, ProductFamily.DOMESTIC_BOND, fields).complete_candidates == ()


def test_saleability_cannot_expand_for_another_family():
    assert _solve('해외 ETF 중 판매 가능한 상품', ProductFamily.OVERSEAS_ETF,
                  (('availability_status', '판매 가능한'),)).complete_candidates == ()


def test_unapproved_grade_threshold_and_arbitrary_grade_are_not_guessed():
    assert _solve('국내채권 중 신용등급 AA+ 이상', ProductFamily.DOMESTIC_BOND,
                  (('credit_grade', '신용등급'),)).complete_candidates == ()
    assert _solve('국내채권 중 신용등급 AAAA 이상', ProductFamily.DOMESTIC_BOND,
                  (('credit_grade', '신용등급'),)).complete_candidates == ()


@pytest.mark.parametrize('suffix', [' 상품 제외', '상품은 제외', ' 종목 아닌'])
def test_aum_presence_negation_stays_nonexecutable(suffix):
    result = _solve(f'해외 ETF 중 AUM이 있는{suffix}', ProductFamily.OVERSEAS_ETF, (('aum', 'AUM'),))
    assert result.complete_candidates == ()
    assert 'SOURCE_CONDITION_NEGATION_UNSUPPORTED' in result.frames[0].contract_readiness.reason_codes


@pytest.mark.parametrize('field,value', [
    ('credit_threshold_values', ['AAA', 'AA-', 'AA+', 'AA0']),
    ('credit_threshold', 'AA+'), ('bond_saleability_remaining_days_value', '-1'),
    ('bond_saleability_cutoff_source', 'today'), ('region_japan', 'USA'),
])
def test_condition_policy_rejects_changed_values_or_order(tmp_path, field, value):
    payload = json.loads((PROJECT_ROOT / POLICY_PATH).read_text())
    payload[field] = value
    target = tmp_path / POLICY_PATH
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_personal_condition_policy(tmp_path)


@pytest.mark.parametrize('surface', ['원화채권', '원화 채권', '원화채권을', '원화채권 중'])
def test_registered_krw_bond_scope_keeps_a_source_owned_family_lock(surface):
    request = normalized_request(f'{surface} 알려줘')
    locks = build_exact_semantic_locks(request, load_catalog(PROJECT_ROOT))
    family = tuple(item for item in locks if item.role == 'product_family')
    assert len(family) == 1
    assert family[0].canonical_id == 'domestic_bond'
    assert family[0].evidence_span_ids[0].startswith('mention-s1-0-')


@pytest.mark.parametrize('surface', [
    '원화채권형 ETF', '외국원화채권', '해외 채권형 ETF', '원화채권ETF',
])
def test_krw_bond_scope_does_not_expand_a_different_product_expression(surface):
    locks = build_exact_semantic_locks(normalized_request(f'{surface} 알려줘'), load_catalog(PROJECT_ROOT))
    assert not any(item.role == 'product_family' and item.canonical_id == 'domestic_bond' for item in locks)


def test_krw_bond_scope_inside_a_named_etf_does_not_change_the_family():
    name = 'TIGER 원화채권'
    request = normalized_request(f'{name}의 총보수 알려줘')
    context = request.context.model_copy(update={'named_entities': (NamedEntityMention(
        mention_id='entity-1', segment_id='s1', text=name,
        expected_entity_types=('FinancialProduct',), start_char=0, end_char=len(name),
    ),)})
    locks = build_exact_semantic_locks(normalize_request(context), load_catalog(PROJECT_ROOT))
    assert not any(item.role == 'product_family' for item in locks)

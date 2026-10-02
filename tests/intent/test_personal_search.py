from datetime import date, timedelta

import pytest

from financial_agent.intent.personal_search import PersonalSemanticSearch, PersonalSearchError
from financial_agent.sql.result_mapping import MappedSqlResult
from financial_agent.sql.executor import SqlExecutionError
from tests.intent.test_personal_intent import Adapter, NOW, ROOT, service
from tests.intent.test_personal_search_results import REFS, fact, row


class Runner:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = (row(),) if rows is None else rows

    async def execute(self, request, plan, **kwargs):
        self.calls.append((request, plan))
        return MappedSqlResult(result_rows=self.rows, evidence_refs=REFS if self.rows else (),
                               exclusions=(), warnings=())


class Repository:
    async def load(self, dataset, refs):
        return (fact(),) if refs else ()


def searcher(adapter, runner, *, clock=lambda: NOW):
    return PersonalSemanticSearch(service(adapter), project_root=ROOT,
                                  runner_factory=lambda compiler: runner,
                                  repository=Repository(), utcnow=clock)


@pytest.mark.asyncio
async def test_only_approved_plan_executes_and_renders_verified_facts():
    runner = Runner()
    result = await searcher(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False), runner).search(
        '국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘', display_limit=3,
    )
    assert len(runner.calls) == 1
    request, plan = runner.calls[0]
    assert request.render_manifest.logical_plan_id == plan.logical_plan_id
    assert result.execution_performed is True
    assert '0.1%' in result.text
    assert '전체 일치 1건' in result.text
    assert '출처:' in result.text


@pytest.mark.asyncio
async def test_unavailable_intent_never_calls_sql():
    runner = Runner()
    result = await searcher(Adapter('public_fund', 'fee_rate', action='screen', entity=False), runner).search(
        '공모펀드 중 총보수가 0.3% 이하인 상품을 찾아줘',
    )
    assert runner.calls == []
    assert result.execution_performed is False
    assert 'PUBLIC_FUND_TOTAL_FEE_DEFINITION_UNVERIFIED' in result.text


@pytest.mark.asyncio
async def test_expired_shared_deadline_never_calls_sql():
    runner = Runner()
    with pytest.raises(PersonalSearchError, match='PERSONAL_SEARCH_DEADLINE_EXCEEDED'):
        await searcher(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False), runner,
                       clock=lambda: NOW + timedelta(seconds=56)).search(
            '국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘',
        )
    assert runner.calls == []


@pytest.mark.asyncio
async def test_empty_query_is_explicit_and_not_an_execution_failure():
    runner = Runner(())
    result = await searcher(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False), runner).search(
        '국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘',
    )
    assert result.execution_performed
    assert '전체 일치 0건' in result.text


@pytest.mark.asyncio
async def test_display_limit_is_not_a_sql_limit():
    runner = Runner()
    result = await searcher(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False), runner).search(
        '국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘', display_limit=1,
    )
    assert 'LIMIT' not in runner.calls[0][0].statement
    assert '표시 1건' in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize(('failure', 'code'), [
    (SqlExecutionError('SQL_RESULT_ROW_LIMIT_EXCEEDED'), 'SQL_RESULT_ROW_LIMIT_EXCEEDED'),
    (TimeoutError(), 'PERSONAL_SQL_TIMEOUT'),
    (SqlExecutionError('secret-bearing-driver-message'), 'PERSONAL_SQL_EXECUTION_FAILED'),
])
async def test_sql_failure_retains_only_safe_limit_reason(failure, code):
    class FailedRunner:
        async def execute(self, request, plan, **kwargs):
            raise failure

    with pytest.raises(PersonalSearchError, match=f'^{code}$'):
        await searcher(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False),
                       FailedRunner()).search('국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘')


@pytest.mark.asyncio
async def test_empty_screen_benignly_skips_dependent_rank_and_returns_text():
    from types import SimpleNamespace

    from financial_agent.intent.query_contract_solver import QueryContractCandidate
    from financial_agent.intent.query_contracts import QueryQualifiersV2
    from financial_agent.planning.semantic_compiler import PriorResultOwnershipV2
    from tests.planning.test_semantic_compiler import (
        _actual_assessments, _compile, _rank, _semantic_contract,
    )

    first = QueryContractCandidate(
        candidate_id='first',
        contract=_semantic_contract('screen').model_copy(update={'frame_id': 'frame-1'}),
    )
    ranked = _rank('frame-2', 'result-set-1')
    second = QueryContractCandidate(
        candidate_id=ranked.candidate_id,
        contract=ranked.contract.model_copy(update={
            'qualifiers': QueryQualifiersV2(as_of_date=date(2026, 8, 24)),
        }),
    )
    ownership = (PriorResultOwnershipV2(
        binding_id='result-set-1', producer_frame_id='frame-1', cardinality='many',
    ),)
    compilation = _compile(
        (first, second), _actual_assessments((first, second), prior_result_ownership=ownership),
        prior_result_ownership=ownership,
        primitive_ids=('lookup-products', 'screen-products', 'rank-products'),
    )
    plan = compilation.logical_query_plan
    assert plan is not None and len(plan.tasks) == 2
    assert plan.dependencies[0].upstream_task_id == plan.tasks[0].task_id
    assert plan.dependencies[0].downstream_task_id == plan.tasks[1].task_id

    class Intent:
        async def resolve(self, question, question_id):
            return SimpleNamespace(
                compilation=compilation, model_id='synthetic',
                context=SimpleNamespace(question=question, dataset_version=plan.dataset_version,
                                        deadline_at=NOW + timedelta(seconds=55)),
                to_dict=lambda: {'route': compilation.route.value,
                                 'disposition': compilation.recommended_answer_disposition.value,
                                 'frames': []},
            )

    runner = Runner(())
    search = PersonalSemanticSearch(
        Intent(), project_root=ROOT, runner_factory=lambda compiler: runner,
        repository=Repository(), utcnow=lambda: NOW,
    )
    result = await search.search('국내 ETF를 조건으로 찾고 그중 순자산 상위 상품을 보여줘')

    assert result.execution_performed is True
    assert len(runner.calls) == 1
    assert runner.calls[0][0].task_id == plan.tasks[0].task_id
    assert '전체 일치 0건 · 표시 0건' in result.text
    assert 'frame-2: 선행 조회 결과 0건으로 후속 조회를 생략했습니다.' in result.text
    assert '상위 결과' not in result.text

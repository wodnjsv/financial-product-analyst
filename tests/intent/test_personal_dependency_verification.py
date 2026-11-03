import asyncio
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from financial_agent.intent import personal_search as module
from financial_agent.intent.personal_search import PersonalSearchError, PersonalSemanticSearch
from financial_agent.intent.query_contract_solver import QueryContractCandidate
from financial_agent.intent.query_contracts import QueryQualifiersV2
from financial_agent.planning.semantic_compiler import PriorResultOwnershipV2
from tests.intent.test_personal_intent import Adapter, NOW, ROOT
from tests.intent.test_personal_search import Runner, searcher
from tests.intent.test_personal_search_results import fact, row
from tests.planning.test_semantic_compiler import (
    _actual_assessments, _compile, _rank, _semantic_contract,
)


def dependent_search(runner, repository):
    first = QueryContractCandidate(candidate_id='first', contract=_semantic_contract('screen').model_copy(
        update={'frame_id': 'frame-1'},
    ))
    ranked = _rank('frame-2', 'result-set-1')
    second = QueryContractCandidate(candidate_id=ranked.candidate_id, contract=ranked.contract.model_copy(
        update={'qualifiers': QueryQualifiersV2(as_of_date=date(2026, 8, 24))},
    ))
    ownership = (PriorResultOwnershipV2(binding_id='result-set-1', producer_frame_id='frame-1', cardinality='many'),)
    compilation = _compile(
        (first, second), _actual_assessments((first, second), prior_result_ownership=ownership),
        prior_result_ownership=ownership,
        primitive_ids=('lookup-products', 'screen-products', 'rank-products'),
    )
    plan = compilation.logical_query_plan
    assert len(plan.tasks) == 2 and len(plan.dependencies) == 1

    class Intent:
        async def resolve(self, question, question_id):
            return SimpleNamespace(
                compilation=compilation, model_id='synthetic',
                attempt=SimpleNamespace(view=SimpleNamespace(active_dataset_pin=SimpleNamespace(
                    dataset_version=plan.dataset_version, manifest_hash=plan.dataset_pin)),
                    candidates=SimpleNamespace(frames=(
                        SimpleNamespace(frame_id='frame-1', complete_candidates=(first,)),
                        SimpleNamespace(frame_id='frame-2', complete_candidates=(second,)),
                    ))),
                context=SimpleNamespace(question=question, dataset_version=plan.dataset_version,
                                        request_key=plan.request_key, run_id=plan.run_id,
                                        cutoff_date=plan.cutoff_date, deadline_at=NOW + timedelta(seconds=55)),
                to_dict=lambda: {'route': compilation.route.value,
                                 'disposition': compilation.recommended_answer_disposition.value,
                                 'frames': []},
            )

    return PersonalSemanticSearch(Intent(), project_root=ROOT, runner_factory=lambda compiler: runner,
                                  repository=repository, utcnow=lambda: NOW), plan


@pytest.mark.asyncio
@pytest.mark.parametrize('failure_stage,source_changes,value,expected_code', [
    ('result_contract', {}, Decimal('1.5'), 'LOCAL_RESULT_PREDICATE_MISMATCH'),
    ('evidence', {'publisher_type': 'asset_manager', 'authority_tier': 'other'},
     Decimal('0.1'), 'LOCAL_RESULT_EVIDENCE_INVALID'),
])
async def test_upstream_verification_failure_blocks_dependent_query_and_final_render(
    monkeypatch, failure_stage, source_changes, value, expected_code,
):
    class Repository:
        async def load(self, dataset, refs, **kwargs):
            return (fact(numeric_value=value, normalized_value={'type': 'decimal', 'value': str(value)},
                         **source_changes),)

    runner = Runner((row(value),))
    search, plan = dependent_search(runner, Repository())
    renders = []
    monkeypatch.setattr(module, 'render_semantic_rows', lambda *args, **kwargs: renders.append('row'))
    monkeypatch.setattr(module, '_render_final_text', lambda *args, **kwargs: renders.append('final'))
    with pytest.raises(PersonalSearchError) as caught:
        await search.search('국내 ETF를 조건으로 찾고 그중 순자산 상위 상품을 보여줘')
    assert [request.task_id for request, _ in runner.calls] == [plan.tasks[0].task_id]
    assert renders == []
    report = caught.value.verification_report
    assert report.outcome == 'failed' and report.output_hash is None
    blocked = [check for check in report.checks if check.stage == failure_stage
               and check.task_id == plan.tasks[0].task_id]
    assert len(blocked) == 1 and blocked[0].status == 'fail' and blocked[0].reason_code == expected_code
    assert next(check for check in report.checks if check.stage == 'execution'
                and check.task_id == plan.tasks[0].task_id).status == 'pass'
    assert next(check for check in report.checks if check.stage == 'query'
                and check.task_id == plan.tasks[1].task_id).status == 'not_run'
    assert next(check for check in report.checks if check.stage == 'final').status == 'not_run'


@pytest.mark.asyncio
async def test_real_wait_for_cancellation_retains_failed_attempt_before_retry_success():
    class OnceCancelledRunner(Runner):
        cancelled = False

        async def execute(self, request, plan, **kwargs):
            if not self.calls:
                self.calls.append((request, plan))
                try:
                    # Orchestrator's real registered task deadline cancels this await.
                    await asyncio.Future()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            return await super().execute(request, plan, **kwargs)

    runner = OnceCancelledRunner()
    result = await searcher(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False), runner).search(
        '국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘',
    )
    assert runner.cancelled and len(runner.calls) == 2
    assert runner.calls[0][0] == runner.calls[1][0]
    assert result.verification_report.outcome == 'verified'
    executions = [check for check in result.verification_report.checks if check.stage == 'execution']
    assert [(check.attempt, check.status) for check in executions] == [(1, 'fail'), (2, 'pass')]
    assert executions[0].reason_code
    assert [check.status for check in result.verification_report.checks if check.stage == 'evidence'] == ['pass']


@pytest.mark.asyncio
async def test_real_evidence_loading_cancellation_retains_correct_phase_before_retry_success():
    from tests.intent.test_personal_intent import service

    class OnceCancelledRepository:
        def __init__(self):
            self.calls = []
            self.cancelled = False

        async def load(self, dataset, refs, **kwargs):
            self.calls.append((dataset, refs, kwargs))
            if len(self.calls) == 1:
                try:
                    # The registered task budget cancels hydration after SQL returned.
                    await asyncio.Future()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            return (fact(),)

    runner, repository = Runner(), OnceCancelledRepository()
    search = PersonalSemanticSearch(
        service(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False)),
        project_root=ROOT, runner_factory=lambda compiler: runner,
        repository=repository, utcnow=lambda: NOW,
    )
    result = await search.search('국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘')

    assert repository.cancelled and len(repository.calls) == len(runner.calls) == 2
    assert runner.calls[0][0] == runner.calls[1][0]
    assert repository.calls[0] == repository.calls[1]
    assert result.verification_report.outcome == 'verified'
    queries = [check for check in result.verification_report.checks if check.stage == 'query']
    executions = [check for check in result.verification_report.checks if check.stage == 'execution']
    loading = [check for check in result.verification_report.checks if check.stage == 'evidence_loading']
    assert [(check.attempt, check.status) for check in queries] == [(1, 'pass'), (2, 'pass')]
    assert [(check.attempt, check.status) for check in executions] == [(1, 'pass'), (2, 'pass')]
    assert [(check.attempt, check.status) for check in loading] == [(1, 'fail'), (2, 'pass')]
    assert loading[0].reason_code == 'EVIDENCE_LOADING_CANCELLED'
    assert loading[1].reason_code is None
    assert [(check.attempt, check.status) for check in result.verification_report.checks
            if check.stage == 'evidence'] == [(2, 'pass')]

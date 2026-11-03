from dataclasses import replace
from decimal import Decimal

import pytest

from financial_agent.intent import personal_search as module
from financial_agent.intent.personal_search import PersonalSearchError
from tests.intent.test_personal_intent import Adapter
from tests.intent.test_personal_search import Runner, searcher
from tests.intent.test_personal_search_results import fact, row


QUESTION = '국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘'


def check(report, stage):
    return [item for item in report.checks if item.stage == stage]


@pytest.mark.asyncio
async def test_complete_question_reports_only_checks_that_really_ran():
    result = await searcher(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False), Runner()).search(QUESTION)
    report = result.verification_report
    assert report.outcome == 'verified'
    for stage in ('plan', 'query', 'execution', 'evidence', 'result_contract', 'final'):
        assert check(report, stage)[0].status == 'pass'
        assert check(report, stage)[0].artifact_hash
    assert check(report, 'graph_projection')[0].status == 'not_applicable'
    assert check(report, 'production_claim_gate')[0].status == 'not_applicable'
    assert report.output_hash


@pytest.mark.asyncio
async def test_legitimate_source_value_that_breaks_predicate_cannot_reach_renderer(monkeypatch):
    renderer_calls = []
    monkeypatch.setattr(module, 'render_semantic_rows', lambda *a, **k: renderer_calls.append(True))
    search = searcher(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False), Runner((row(Decimal('0.2')),)))

    class Repository:
        async def load(self, dataset, refs, **kwargs):
            return (fact(numeric_value=Decimal('0.2'), normalized_value={'type': 'decimal', 'value': '0.2'}),)

    search._repository = Repository()
    with pytest.raises(PersonalSearchError, match='LOCAL_RESULT_PREDICATE_MISMATCH') as caught:
        await search.search(QUESTION)
    report = caught.value.verification_report
    assert check(report, 'evidence')[0].status == 'pass'
    assert check(report, 'result_contract')[0].status == 'fail'
    assert check(report, 'final')[0].status == 'not_run'
    assert renderer_calls == []


@pytest.mark.asyncio
async def test_wrong_source_authority_stops_result_and_final_checks(monkeypatch):
    search = searcher(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False), Runner())

    class Repository:
        async def load(self, dataset, refs, **kwargs):
            return (fact(publisher_type='asset_manager', authority_tier='other'),)

    search._repository = Repository()
    rendered = []
    monkeypatch.setattr(module, 'render_semantic_rows', lambda *a, **k: rendered.append(True))
    with pytest.raises(PersonalSearchError, match='LOCAL_RESULT_EVIDENCE_INVALID') as caught:
        await search.search(QUESTION)
    report = caught.value.verification_report
    assert check(report, 'evidence')[0].status == 'fail'
    assert check(report, 'result_contract')[0].status == 'not_run'
    assert report.output_hash is None and rendered == []


@pytest.mark.asyncio
async def test_tampered_plan_never_calls_database():
    runner = Runner()
    search = searcher(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False), runner)
    resolve = search._intent.resolve

    async def changed(question, question_id):
        intent = await resolve(question, question_id)
        plan = intent.compilation.logical_query_plan.model_copy(update={'dataset_pin': 'f' * 64})
        return replace(intent, compilation=intent.compilation.model_copy(update={'logical_query_plan': plan}))

    search._intent.resolve = changed
    with pytest.raises(PersonalSearchError, match='PLAN_CONTRACT_INVALID') as caught:
        await search.search(QUESTION)
    assert runner.calls == []
    assert check(caught.value.verification_report, 'plan')[0].status == 'fail'
    assert check(caught.value.verification_report, 'query')[0].status == 'not_run'


@pytest.mark.asyncio
@pytest.mark.parametrize('target', ['final_join', 'result_renderer'])
async def test_added_numbers_or_prose_are_blocked_at_final_boundary(monkeypatch, target):
    if target == 'final_join':
        monkeypatch.setattr(module, '_render_final_text', lambda lines: '\n'.join(lines) + '\n예상 수익률 10%')
    else:
        original = module.render_semantic_rows
        monkeypatch.setattr(module, 'render_semantic_rows', lambda *a, **k: original(*a, **k).replace('0.1%', '0.2%'))
    with pytest.raises(PersonalSearchError, match='FINAL_RESPONSE_MISMATCH') as caught:
        await searcher(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False), Runner()).search(QUESTION)
    report = caught.value.verification_report
    assert check(report, 'result_contract')[0].status == 'pass'
    assert check(report, 'final')[0].status == 'fail'
    assert report.output_hash is None


@pytest.mark.asyncio
async def test_intent_limitation_is_not_factual_verification_success():
    runner = Runner()
    result = await searcher(Adapter('public_fund', 'fee_rate', action='screen', entity=False), runner).search(
        '공모펀드 중 총보수가 0.3% 이하인 상품을 찾아줘',
    )
    assert result.verification_report.outcome == 'limited'
    assert check(result.verification_report, 'query')[0].status == 'not_run'
    assert check(result.verification_report, 'final')[0].status == 'pass'
    assert runner.calls == []


@pytest.mark.asyncio
async def test_approved_sql_retry_preserves_failed_attempt_and_success():
    class OnceTimeout(Runner):
        async def execute(self, request, plan, **kwargs):
            if not self.calls:
                self.calls.append((request, plan))
                raise TimeoutError()
            return await super().execute(request, plan, **kwargs)

    runner = OnceTimeout()
    result = await searcher(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False), runner).search(QUESTION)
    assert len(runner.calls) == 2
    assert result.verification_report.outcome == 'verified'
    assert [(item.attempt, item.status) for item in check(result.verification_report, 'execution')] == [(1, 'fail'), (2, 'pass')]


@pytest.mark.asyncio
async def test_query_tampering_stops_before_runner_and_hydration():
    from financial_agent.release.personal_verification import VerificationHarness
    from financial_agent.sql.executor import SqlExecutionError
    from tests.sql.test_bounded_personal_screen import COMPILER, region_plan, request

    plan, compiled = region_plan(), request()
    checks = VerificationHarness(plan.dataset_version, plan.dataset_pin, plan.request_key,
                                 plan.cutoff_date, task_ids=(compiled.task_id,))
    runner = Runner()
    repository_calls = []

    class Repository:
        async def load(self, *args, **kwargs):
            repository_calls.append(True)

    wrapper = module._PersonalSqlRunner(runner, COMPILER, checks, {}, Repository(), 2)
    with pytest.raises(SqlExecutionError, match='EXECUTION_REQUEST_REJECTED'):
        await wrapper.execute(compiled.model_copy(update={'statement': 'SELECT 42'}), plan)
    assert runner.calls == [] and repository_calls == []
    assert check(checks.finish('failed'), 'query')[0].status == 'fail'


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', [False, True])
async def test_evidence_loading_checks_live_pin_even_for_empty_result(changed):
    from datetime import date

    from financial_agent.sql.dataset_pin import DatasetPinChanged
    from tests.sql.helpers import ACTIVE_DATASET
    from tests.sql.test_executor import FakeConnection, FakeEngine

    class RepositoryConnection(FakeConnection):
        async def execute(self, statement, parameters=None):
            return await super().execute(statement, parameters or {})

    engine = FakeEngine([])
    engine.connection = RepositoryConnection([], pin_rows=[{
        'dataset_version': ACTIVE_DATASET.dataset_version,
        'manifest_hash': 'f' * 64 if changed else ACTIVE_DATASET.manifest_hash,
        'cutoff_date': date(2026, 8, 24),
    }])
    repository = module.SemanticResultRepository(engine)
    operation = repository.load(ACTIVE_DATASET.dataset_version, (),
                                expected_pin=ACTIVE_DATASET.manifest_hash, cutoff_date=date(2026, 8, 24))
    if changed:
        with pytest.raises(DatasetPinChanged):
            await operation
    else:
        assert await operation == ()
    statements = [statement for statement, _, _ in engine.connection.executions]
    assert statements[0] == 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'
    assert any('FROM operations.dataset_version' in statement for statement in statements)
    assert not any('FROM evidence.evidence_record' in statement for statement in statements)

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.release import personal_verification as module
from financial_agent.release.personal_verification import (
    PersonalVerificationCheck, PersonalVerificationReport, VerificationHarness, seal_answer_section,
    validate_final_text,
)
from tests.intent.test_personal_search_results import fact, row, validate


def harness():
    return VerificationHarness('dataset-1', 'a' * 64, 'b' * 64, date(2026, 8, 24), task_ids=('task-1',))


def test_failed_stage_does_not_certify_unrun_or_unused_checks():
    checks = harness()
    checks.passed('plan', {'plan': 'approved'}, rule_ids=('registered-plan.v1',))
    checks.failed('query', 'EXECUTION_REQUEST_REJECTED', task_id='task-1')
    report = checks.finish('failed')
    assert next(c for c in report.checks if c.stage == 'query').status == 'fail'
    assert next(c for c in report.checks if c.stage == 'evidence').status == 'not_run'
    assert next(c for c in report.checks if c.stage == 'graph_projection').status == 'not_applicable'
    restored = PersonalVerificationReport.model_validate_json(report.model_dump_json())
    assert restored == report
    with pytest.raises(ValidationError, match='VERIFICATION_REPORT_HASH_MISMATCH'):
        PersonalVerificationReport.model_validate_json(report.model_dump_json().replace('EXECUTION_REQUEST_REJECTED', 'FAKE_APPROVED'))


def test_verified_report_requires_all_executed_local_stages():
    with pytest.raises(ValueError, match='VERIFICATION_STAGES_INCOMPLETE'):
        harness().finish('verified', text='unknown answer')


@pytest.mark.parametrize('changed', [
    '상품A: 0.2% · 2026-08-22 · 출처 [E1]',
    '상품B: 0.1% · 2026-08-22 · 출처 [E1]',
    '상품A: 0.1% · 2026-08-23 · 출처 [E1]',
    '상품A: 0.1% · 2026-08-22',
    '상품A: 0.1% · 2026-08-22 · 출처 [E2]',
    '상품A: 0.1% · 2026-08-22 · 출처 [E1]\n향후 수익률은 10%입니다.',
])
def test_final_output_is_bound_to_approved_text_not_numeric_membership(changed):
    section = seal_answer_section('task-1', '상품A: 0.1% · 2026-08-22 · 출처 [E1]')
    with pytest.raises(ValueError, match='FINAL_RESPONSE_MISMATCH'):
        validate_final_text((section,), changed)


def test_names_dates_source_rows_and_literal_quote_numbers_are_preserved():
    text = 'ETF 200 · 날짜 2026-08-22 · 원본 행=42\n원문: [D9] 비중 25.11%'
    section = seal_answer_section('task-1', text)
    assert validate_final_text((section,), text)


def test_error_reason_cannot_contain_provider_payload():
    with pytest.raises(ValueError, match='UNSAFE_VERIFICATION_REASON'):
        harness().failed('query', 'secret-bearing driver message')


def test_one_completed_task_does_not_certify_a_second_unrun_task():
    checks = VerificationHarness('dataset-1', 'a' * 64, 'b' * 64, date(2026, 8, 24),
                                 task_ids=('task-1', 'task-2'))
    for stage in ('plan', 'final'):
        checks.passed(stage, {'approved': True}, rule_ids=('check.v1',))
    for stage in ('query', 'execution', 'evidence', 'result_contract'):
        checks.passed(stage, {'approved': True}, task_id='task-1', rule_ids=('check.v1',))
    with pytest.raises(ValueError, match='VERIFICATION_STAGES_INCOMPLETE'):
        checks.finish('verified', text='answer')


def complete_report():
    checks = harness()
    checks.passed('plan', {'approved': True}, rule_ids=('check.v1',))
    for stage in ('query', 'execution', 'evidence_loading', 'evidence', 'result_contract'):
        checks.passed(stage, {'approved': True}, task_id='task-1', rule_ids=('check.v1',))
    checks.passed('final', {'output_hash': canonical_sha256({'text': 'answer'})}, rule_ids=('check.v1',))
    return checks.finish('verified', text='answer')


def revalidate(report, checks):
    draft = report.model_copy(update={'checks': tuple(checks)})
    draft = draft.model_copy(update={
        'report_hash': canonical_sha256(draft, exclude_fields=('report_hash',)),
    })
    return PersonalVerificationReport.model_validate_json(draft.model_dump_json())


@pytest.mark.parametrize('changes', [
    {'artifact_hash': None}, {'rule_ids': ()}, {'rule_ids': ('check.v1', 'check.v1')},
    {'reason_code': 'FAKE_REASON'},
])
def test_self_consistent_report_cannot_certify_unbound_pass(changes):
    report = complete_report()
    checks = [item.model_copy(update=changes) if item.stage == 'evidence' else item
              for item in report.checks]
    with pytest.raises(ValueError, match='VERIFICATION_PASS_INVALID'):
        revalidate(report, checks)


@pytest.mark.parametrize('status', ['fail', 'not_run', 'not_applicable'])
@pytest.mark.parametrize('changes', [
    {'reason_code': None}, {'reason_code': 'secret-provider-payload'},
    {'artifact_hash': 'a' * 64}, {'rule_ids': ('check.v1',)},
])
def test_non_pass_checks_require_safe_reason_and_no_success_artifact(status, changes):
    payload = dict(stage='evidence', status=status, reason_code='NO_STAGE_RESULT')
    if status == 'not_applicable':
        payload.update(stage='graph_projection', reason_code='GRAPH_NOT_USED')
    with pytest.raises(ValueError, match='VERIFICATION_NON_PASS_INVALID'):
        PersonalVerificationCheck(**(payload | changes))


@pytest.mark.parametrize('payload', [
    {'stage': 'unregistered', 'status': 'not_run', 'reason_code': 'NO_STAGE_RESULT'},
    {'stage': 'evidence', 'status': 'not_applicable', 'reason_code': 'NOT_USED'},
    {'stage': 'graph_projection', 'status': 'pass', 'artifact_hash': 'a' * 64,
     'rule_ids': ('check.v1',)},
    {'stage': 'graph_projection', 'status': 'not_applicable', 'reason_code': 'FAKE_REASON'},
])
def test_check_stage_and_unused_scope_are_fixed(payload):
    with pytest.raises(ValueError, match='VERIFICATION_STAGE_INVALID'):
        PersonalVerificationCheck(**payload)


@pytest.mark.parametrize('stage', ['plan', 'query', 'evidence', 'result_contract', 'final'])
def test_hard_failure_cannot_be_overridden_by_later_pass(stage):
    report = complete_report()
    checks = []
    for item in report.checks:
        if item.stage == stage:
            checks.append(PersonalVerificationCheck(
                stage=stage, task_id=item.task_id, attempt=1,
                status='fail', reason_code='HARD_CHECK_FAILED',
            ))
            item = item.model_copy(update={'attempt': 2})
        checks.append(item)
    with pytest.raises(ValueError, match='VERIFICATION_HARD_FAILURE_OVERRIDDEN'):
        revalidate(report, checks)


@pytest.mark.parametrize('stage', ['execution', 'evidence_loading'])
def test_transient_failure_and_success_keep_both_attempts(stage):
    report = complete_report()
    checks = []
    for item in report.checks:
        if item.stage == stage:
            checks.append(PersonalVerificationCheck(
                stage=stage, task_id=item.task_id, attempt=1,
                status='fail', reason_code='TRANSIENT_CHECK_FAILED',
            ))
        if item.task_id == 'task-1':
            item = item.model_copy(update={'attempt': 2})
        checks.append(item)
    restored = revalidate(report, checks)
    assert [(item.attempt, item.status) for item in restored.checks if item.stage == stage] == [
        (1, 'fail'), (2, 'pass'),
    ]


def test_report_order_cannot_hide_later_failed_attempt():
    report = complete_report()
    checks = list(report.checks)
    execution = next(item for item in checks if item.stage == 'execution')
    checks.insert(checks.index(execution), PersonalVerificationCheck(
        stage='execution', task_id='task-1', attempt=2,
        status='fail', reason_code='SQL_EXECUTION_FAILED',
    ))
    with pytest.raises(ValueError, match='VERIFICATION_ATTEMPT_ORDER_INVALID'):
        revalidate(report, checks)


def test_old_evidence_attempt_cannot_certify_retried_execution():
    report = complete_report()
    checks = [item.model_copy(update={'attempt': 2})
              if item.stage in ('query', 'execution', 'evidence_loading') else item
              for item in report.checks]
    with pytest.raises(ValueError, match='VERIFICATION_STAGES_INCOMPLETE'):
        revalidate(report, checks)


def test_unused_or_unrun_checks_cannot_disappear_from_report():
    report = harness().finish('failed')
    for stage in ('graph_projection', 'evidence_loading'):
        with pytest.raises(ValueError, match='VERIFICATION_CHECK_COVERAGE_INVALID'):
            revalidate(report, [item for item in report.checks if item.stage != stage])


def test_output_hash_cannot_be_replaced_without_final_verification_binding():
    report = complete_report().model_copy(update={'output_hash': 'f' * 64})
    with pytest.raises(ValueError, match='VERIFICATION_FINAL_HASH_MISMATCH'):
        revalidate(report, report.checks)


def test_evidence_fingerprint_contains_full_validated_metadata():
    instant = datetime(2026, 8, 22, 1, 2, tzinfo=UTC)
    source = fact(published_at=instant)
    artifact = module.evidence_artifact(validate((row(),), (source,)))
    assert artifact['rows'] == [row().model_dump(mode='json')]
    assert artifact['facts'][0].keys() == source.keys()
    assert artifact['facts'][0]['numeric_value'] == '0.1'
    assert artifact['facts'][0]['vintage_date'] == '2026-08-22'
    assert artifact['facts'][0]['published_at'] == instant.isoformat()
    changed = module.evidence_artifact(validate((row(),), (fact(
        published_at=instant, content_checksum='b' * 64,
    ),)))
    assert canonical_sha256(artifact) != canonical_sha256(changed)


def test_evidence_fingerprint_sorts_facts_without_changing_result_order():
    from dataclasses import replace

    verified = validate((row(),), (fact(),))[0]
    changed_fact = dict(verified.facts[0]) | {'source_id': 'source-2'}
    left = replace(verified, facts=(verified.facts[0], changed_fact))
    right = replace(verified, facts=(changed_fact, verified.facts[0]))
    assert module.evidence_artifact((left,)) == module.evidence_artifact((right,))


@pytest.mark.parametrize('unsupported', [object(), Decimal('NaN'), float('inf')])
def test_evidence_fingerprint_rejects_unsupported_metadata(unsupported):
    from dataclasses import replace

    verified = validate((row(),), (fact(),))[0]
    altered = replace(verified, facts=(dict(verified.facts[0]) | {'unexpected': unsupported},))
    with pytest.raises((TypeError, ValueError)):
        module.evidence_artifact((altered,))

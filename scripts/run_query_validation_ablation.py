"""질의 명세 검증 전후 비교 실험: 잘못된 조회가 SQL 실행(DB)까지 가는지 측정한다.

모델 제안을 기존 테스트의 가짜 어댑터로 고정하고, 서버 검증만 켜고 끈다.
- ON : 저장소의 현재 경로 그대로
- OFF: 아래 네 검증만 통과 처리
  1) 질문에 명시된 상품군 고정(exact lock): 모델이 다른 상품군을 골라도 통과
  2) 상품군 모호성 검사: 질문에 상품군 근거가 없어도 모델 선택을 그대로 사용
  3) '또는' 조건 검사: OR 조건을 AND 조건 SQL로 실행
  4) 실행 직전 SQL·인자 재컴파일 대조: 컴파일 뒤 바뀐 SQL·인자를 그대로 실행
가짜 DB 러너는 받은 SQL을 기록만 하고 실행을 멈추므로, 지표는 'DB에 도달한 SQL'이다.
외부 API·DB를 호출하지 않는다. 저장소 루트에서 실행한다.

    PYTHONPATH=.:src python scripts/run_query_validation_ablation.py > ablation.json

결과 해석과 한계는 docs/planning/reports/2026-11-16-query-validation-ablation.md 참고.
"""

import asyncio
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from unittest import mock

from financial_agent.contracts.values import DecimalValue, IntegerValue, StringValue
from financial_agent.intent import personal as personal_module
from financial_agent.intent import personal_search as search_module
from financial_agent.intent import service as resolver_module
from financial_agent.intent.personal_search import PersonalSearchError, PersonalSemanticSearch
from financial_agent.sql.compiler import SemanticSqlCompiler
from tests.intent.test_personal_intent import Adapter, NOW, ROOT, service


@dataclass
class Case:
    case_id: str
    category: str
    question: str
    model_family: str      # 가짜 모델이 고르는 상품군
    field: str
    action: str
    expected_family: str   # 질문이 실제로 가리키는 상품군 (모호하면 None)
    tamper: str | None = None

    @property
    def is_error(self):
        return self.category != 'clean'


class StopAfterSql(Exception):
    pass


class Runner:
    """DB 대신 받은 SQL을 기록하고 멈춘다."""

    def __init__(self):
        self.requests = []

    async def execute(self, request, plan, **kwargs):
        self.requests.append(request)
        raise StopAfterSql


class Repository:
    async def load(self, *args, **kwargs):
        return ()


def build_cases():
    cases = []
    fee = 'fee_rate'
    ret = 'trailing_1y_historical_cumulative_return'
    # 정상: 상품군이 명시되고 단일 조건인 질문 20건
    clean = []
    for family, label in (('domestic_etf', '국내 ETF'), ('overseas_etf', '해외 ETF')):
        for value in ('0.05', '0.1', '0.2', '0.3', '0.5'):
            clean.append((f'{label} 중 총보수가 {value}% 이하인 상품을 찾아줘', family, fee, 'screen'))
        for n in (3, 5, 10):
            clean.append((f'{label} 중 총보수가 낮은 {n}개', family, fee, 'rank'))
    clean.append(('국내 ETF 최근 1년 수익률 높은 5개', 'domestic_etf', ret, 'rank'))
    clean.append(('국내 ETF 최근 1년 수익률 높은 10개', 'domestic_etf', ret, 'rank'))
    clean.append(('국내채권 만기일 2030-01-15 이하인 상품 찾아줘', 'domestic_bond', 'maturity_date', 'screen'))
    clean.append(('국내채권 만기일 2028-06-30 이하인 상품 찾아줘', 'domestic_bond', 'maturity_date', 'screen'))
    for k, (q, family, field, action) in enumerate(clean, 1):
        cases.append(Case(f'clean-{k}', 'clean', q, family, field, action, family))
    # E1 상품군 오지정: 질문은 상품군을 명시했는데 모델이 다른 상품군을 고름
    wrong = [
        ('국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘', 'domestic_etf', 'overseas_etf', 'screen'),
        ('국내 ETF 중 총보수가 0.3% 이하인 상품을 찾아줘', 'domestic_etf', 'overseas_etf', 'screen'),
        ('해외 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘', 'overseas_etf', 'domestic_etf', 'screen'),
        ('해외 ETF 중 총보수가 0.5% 이하인 상품을 찾아줘', 'overseas_etf', 'domestic_etf', 'screen'),
        ('국내 ETF 중 총보수가 낮은 5개', 'domestic_etf', 'overseas_etf', 'rank'),
        ('해외 ETF 중 총보수가 낮은 5개', 'overseas_etf', 'domestic_etf', 'rank'),
    ]
    for k, (q, truth, chosen, action) in enumerate(wrong, 1):
        cases.append(Case(f'family-wrong-{k}', '상품군 오지정(질문과 다른 상품군)', q, chosen, fee, action, truth))
    # E2 상품군 모호: 질문에 국내/해외 근거가 없는데 모델이 하나를 골라 확정
    vague = [
        ('ETF 중 총보수가 0.1% 이하인 상품을 찾아줘', 'domestic_etf', 'screen'),
        ('ETF 중 총보수가 0.1% 이하인 상품을 찾아줘', 'overseas_etf', 'screen'),
        ('ETF 중 총보수가 낮은 5개', 'domestic_etf', 'rank'),
        ('ETF 중 총보수가 낮은 5개', 'overseas_etf', 'rank'),
        ('미국에 투자하는 ETF 중 총보수가 낮은 5개', 'overseas_etf', 'rank'),
        ('미국에 투자하는 ETF 중 총보수가 0.2% 이하인 상품을 찾아줘', 'domestic_etf', 'screen'),
    ]
    for k, (q, chosen, action) in enumerate(vague, 1):
        cases.append(Case(f'family-vague-{k}', '상품군 모호(질문에 근거 없음)', q, chosen, fee, action, None))
    # E3 '또는' 조건: OR 조건을 AND로 실행하면 조건을 만족하는 상품이 빠짐
    disjunction = [
        '국내 ETF 중 총보수가 0.1% 이하이거나 0.5% 이상인 상품을 찾아줘',
        '국내 ETF 중 총보수가 0.1% 이하 또는 0.8% 이상인 상품을 찾아줘',
        '해외 ETF 중 총보수가 0.2% 이하 혹은 1% 이상인 상품을 찾아줘',
        '해외 ETF 중 총보수가 0.1% 이하이거나 0.3% 이상인 상품을 찾아줘',
        '국내 ETF 중 총보수가 0.05% 이하 OR 0.7% 이상인 상품을 찾아줘',
    ]
    for k, q in enumerate(disjunction, 1):
        family = 'domestic_etf' if q.startswith('국내') else 'overseas_etf'
        cases.append(Case(f'or-{k}', "'또는' 조건(OR을 AND로 실행)", q, family, fee, 'screen', family))
    # E4 실행 직전 SQL·인자 변조: 컴파일은 정상, 실행 요청만 바뀜
    for k, tamper in enumerate(['threshold', 'family', 'limit', 'statement_or', 'metric', 'dataset'], 1):
        cases.append(Case(f'tamper-{k}', '실행 직전 SQL·인자 변조', '국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘',
                          'domestic_etf', fee, 'screen', 'domestic_etf', tamper=tamper))
    return cases


def tamper_request(request, kind):
    def replace(name_prefix, value):
        return tuple(p.model_copy(update={'value': value}) if p.name.startswith(name_prefix) else p
                     for p in request.parameters)
    if kind == 'threshold':
        return request.model_copy(update={'parameters': replace('value_', DecimalValue(type='decimal', value=Decimal('1.0')))})
    if kind == 'family':
        return request.model_copy(update={'parameters': replace('family_', StringValue(type='string', value='overseas_etf'))})
    if kind == 'limit':
        return request.model_copy(update={'parameters': replace('screen_display_limit_', IntegerValue(type='integer', value=50))})
    if kind == 'statement_or':
        return request.model_copy(update={'statement': request.statement.replace('WHERE', 'WHERE TRUE OR', 1)})
    if kind == 'metric':
        return request.model_copy(update={'parameters': replace(
            'metric_9', StringValue(type='string', value='organizer.pref01n001.product_type'))})
    if kind == 'dataset':
        return request.model_copy(update={'parameters': replace('dataset_0', StringValue(type='string', value='dataset-v0'))})
    raise ValueError(kind)


def tamper_patches(kind):
    if kind is None:
        return []
    original = search_module._PersonalSqlRunner.execute

    async def execute(self, request, logical_plan, **kwargs):
        return await original(self, tamper_request(request, kind), logical_plan, **kwargs)
    return [mock.patch.object(search_module._PersonalSqlRunner, 'execute', execute)]


def verification_off_patches():
    original_locks = resolver_module.build_exact_semantic_locks

    def locks_without_family(*args, **kwargs):
        return tuple(item for item in original_locks(*args, **kwargs) if item.role != 'product_family')
    return [
        mock.patch.object(resolver_module, 'build_exact_semantic_locks', locks_without_family),
        mock.patch.object(personal_module, 'ambiguous_product_family_frames', lambda *a, **k: ()),
        mock.patch.object(personal_module, 'unsupported_boolean_frames', lambda *a, **k: ()),
        mock.patch.object(SemanticSqlCompiler, 'validate_request_for_execution', lambda *a, **k: None),
    ]


def describe(request):
    params = {p.name: getattr(p.value, 'value', None) for p in request.parameters}
    family = next((v for k, v in params.items() if k.startswith('family_')), None)
    thresholds = [str(v) for k, v in params.items() if k.startswith('value_')]
    return {'family': family, 'thresholds': thresholds}


async def run_case(case, verification_on):
    runner = Runner()
    intent_service = service(Adapter(case.model_family, case.field, action=case.action, entity=False))
    resolve, issue_codes = intent_service.resolve, []

    async def resolve_and_record(*args, **kwargs):
        result = await resolve(*args, **kwargs)
        issue_codes.extend(result.issue_codes)
        return result
    intent_service.resolve = resolve_and_record
    search = PersonalSemanticSearch(
        intent_service, project_root=ROOT,
        runner_factory=lambda compiler: runner, repository=Repository(), utcnow=lambda: NOW)
    patches = tamper_patches(case.tamper) + ([] if verification_on else verification_off_patches())
    for p in patches:
        p.start()
    outcome = None
    try:
        await search.search(case.question)
        outcome = 'answered_without_sql:' + ','.join(issue_codes)   # 확인 요청·제한 안내로 응답
    except PersonalSearchError as error:
        report = error.verification_report
        failed = next((c.reason_code for c in report.checks if c.status == 'fail'), None) if report else None
        outcome = failed or error.code
    except Exception as error:  # 모델 제안 검증 실패(ResolverContractError 등)
        outcome = getattr(error, 'code', None) or (error.args[0] if error.args else type(error).__name__)
    finally:
        for p in reversed(patches):
            p.stop()
    executed = [describe(r) for r in runner.requests]
    return {'sql_reached_db': bool(runner.requests), 'sql': executed, 'outcome': outcome}


async def main():
    rows = []
    for case in build_cases():
        off = await run_case(case, verification_on=False)
        on = await run_case(case, verification_on=True)
        rows.append({'case_id': case.case_id, 'category': case.category, 'question': case.question,
                     'model_family': case.model_family, 'expected_family': case.expected_family,
                     'is_error': case.is_error, 'off': off, 'on': on})
    summary = {}
    for row in rows:
        item = summary.setdefault(row['category'], {'cases': 0, 'off_sql_reached_db': 0, 'on_sql_reached_db': 0})
        item['cases'] += 1
        item['off_sql_reached_db'] += row['off']['sql_reached_db']
        item['on_sql_reached_db'] += row['on']['sql_reached_db']
    json.dump({'summary': summary, 'cases': rows}, sys.stdout, ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    asyncio.run(main())

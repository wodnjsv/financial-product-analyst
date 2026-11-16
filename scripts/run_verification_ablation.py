"""검증 전후 비교 실험: 오류를 주입한 조회 결과가 최종 답변까지 가는지 측정한다.

질문: '국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘' (기존 테스트와 같은 가짜 LLM·가짜 DB 사용)
- ON : 저장소의 현재 파이프라인 그대로 (근거 검증 → 조건 검증 → 최종 문구 검증)
- OFF: 같은 파이프라인에서 세 검증 함수만 통과 처리
가짜 LLM·가짜 DB만 쓰므로 외부 API·DB를 호출하지 않는다. 저장소 루트에서 실행한다.

    PYTHONPATH=.:src python scripts/run_verification_ablation.py > ablation.json

결과 해석과 한계는 docs/planning/reports/2026-11-16-verification-ablation.md 참고.
"""

import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from unittest import mock

from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.execution import ResultField, ResultRow
from financial_agent.contracts.values import encode_contract_value
from financial_agent.intent import personal_search as module
from financial_agent.intent.personal_search import PersonalSearchError, PersonalSemanticSearch
from financial_agent.release.local_semantic_results import VerifiedSemanticRow
from financial_agent.sql.result_mapping import MappedSqlResult
from tests.intent.test_personal_intent import Adapter, NOW, ROOT, service
from tests.intent.test_personal_search_results import fact as base_fact

QUESTION = '국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘'
DATE = date(2026, 8, 22)
METRIC_REF = 'metric-definition:organizer.pref01n001.total_fee_rate:2'


def make_row(i, value, name=None):
    return ResultRow(row_id=f'row-{i}', entity_ids=(f'product-{i}',), fields=(
        ResultField(field_id='product_name', value=encode_contract_value(name or f'합성 ETF {i}')),
        ResultField(field_id='fee_rate', value=encode_contract_value(Decimal(value)),
                    unit_id='percentage_point', applicable_date=DATE),
    ))


def make_fact(i, value, **changes):
    fields = dict(evidence_id=f'evidence-{i}', subject_id=f'product-{i}', entity_id=f'product-{i}',
                  observation_id=f'observation-{i}', canonical_name=f'합성 ETF {i}',
                  numeric_value=Decimal(value), locator_row=i + 1,
                  normalized_value={'type': 'decimal', 'value': value})
    return base_fact(**(fields | changes))


def refs(n):
    out = ['source:source-1', METRIC_REF]
    for i in range(1, n + 1):
        out += [f'evidence:evidence-{i}', f'observation:observation-{i}']
    return tuple(out)


@dataclass
class Case:
    case_id: str
    category: str
    rows: tuple
    facts: tuple
    tamper: str | None = None          # 최종 문구 변조 방식
    wrong_marker: str | None = None    # OFF에서 답변에 실제로 들어간 오답 표시(검산용)

    @property
    def is_error(self):
        return self.category != 'clean'


class Runner:
    def __init__(self, rows, n):
        self.rows, self.n = rows, n

    async def execute(self, request, plan, **kwargs):
        return MappedSqlResult(result_rows=self.rows, evidence_refs=refs(self.n), exclusions=(), warnings=(),
                               screen_population_count=len(self.rows)
                               if request.render_manifest.screen_display_limit is not None else None)


class Repository:
    def __init__(self, facts):
        self.facts = facts

    async def load(self, dataset, evidence_refs, **kwargs):
        return self.facts


def build_cases():
    cases = []
    good = ['0.1', '0.09', '0.08', '0.07', '0.06', '0.05', '0.04', '0.03', '0.02', '0.01']
    # 정상: 단일 상품 10건 + 여러 상품 10건
    for k, v in enumerate(good, 1):
        cases.append(Case(f'clean-single-{k}', 'clean', (make_row(1, v),), (make_fact(1, v),)))
    for k in range(10):
        n = 3 if k < 6 else 5
        values = [good[(k + j) % len(good)] for j in range(n)]
        cases.append(Case(f'clean-multi-{k + 1}', 'clean',
                          tuple(make_row(i, v) for i, v in enumerate(values, 1)),
                          tuple(make_fact(i, v) for i, v in enumerate(values, 1))))
    # E1 조건 위반: 원천에 실제로 있는 값이지만 0.1% 초과 (단일 6 + 정상 2개 사이에 섞인 1개 4)
    for k, v in enumerate(['0.11', '0.15', '0.2', '0.25', '0.3', '0.5'], 1):
        cases.append(Case(f'cond-single-{k}', '조건 위반(원천에 있는 값)',
                          (make_row(1, v),), (make_fact(1, v),), wrong_marker=f'{v}%'))
    for k, v in enumerate(['0.12', '0.2', '0.35', '0.8'], 1):
        values = ['0.05', v, '0.08']
        cases.append(Case(f'cond-mixed-{k}', '조건 위반(원천에 있는 값)',
                          tuple(make_row(i, x) for i, x in enumerate(values, 1)),
                          tuple(make_fact(i, x) for i, x in enumerate(values, 1)), wrong_marker=f'{v}%'))
    # E2 값 불일치: 답변에는 0.1% 이하로 나오지만 원천 값은 다름
    for k, (shown, truth) in enumerate([('0.1', '0.3'), ('0.1', '0.2'), ('0.05', '0.15'),
                                        ('0.08', '0.5'), ('0.1', '1.0')], 1):
        cases.append(Case(f'value-{k}', '값 불일치(원천과 다른 수치)',
                          (make_row(1, shown),), (make_fact(1, truth),), wrong_marker=f'{shown}%'))
    # E3 단위·기준일·정의 불일치
    for k, ch in enumerate([{'unit': 'fraction'}, {'observation_date': date(2026, 8, 21)},
                            {'metric_definition_version': '1'}, {'period_end': date(2027, 8, 22)}], 1):
        cases.append(Case(f'meta-{k}', '단위·기준일·지표 정의 불일치',
                          (make_row(1, '0.1'),), (make_fact(1, '0.1', **ch),)))
    # E4 출처 자격 문제
    for k, ch in enumerate([{'cutoff_status': 'after_cutoff'}, {'eligible_for_claim': False},
                            {'publisher_type': 'asset_manager', 'authority_tier': 'other'},
                            {'vintage_date': date(2026, 8, 25)}], 1):
        cases.append(Case(f'source-{k}', '출처 자격 문제(기준일 이후·인용 불가)',
                          (make_row(1, '0.1'),), (make_fact(1, '0.1', **ch),)))
    # E5 상품 불일치
    cases.append(Case('product-1', '상품 불일치', (make_row(1, '0.1', name='다른 ETF'),), (make_fact(1, '0.1'),),
                      wrong_marker='다른 ETF'))
    cases.append(Case('product-2', '상품 불일치', (make_row(1, '0.1'),),
                      (make_fact(1, '0.1', subject_id='product-2', entity_id='product-2'),)))
    cases.append(Case('product-3', '상품 불일치', (make_row(1, '0.1'),),
                      (make_fact(1, '0.1', subject_product_family='overseas_etf'),)))
    # E6 최종 문구 변조: 검증 뒤 렌더링·문장 조립 단계에서 수치나 문장이 바뀜
    for k, t in enumerate(['number', 'forecast', 'recommend', 'drop_source'], 1):
        cases.append(Case(f'final-{k}', '최종 문구 변조(수치 변경·문장 추가)',
                          (make_row(1, '0.1'),), (make_fact(1, '0.1'),), tamper=t,
                          wrong_marker={'number': '0.01%', 'forecast': '예상 수익률',
                                        'recommend': '매수를 추천', 'drop_source': None}[t]))
    return cases


def tamper_patches(kind):
    if kind is None:
        return []
    original_render = module.render_semantic_rows
    if kind == 'number':
        return [mock.patch.object(module, 'render_semantic_rows',
                                  lambda *a, **k: original_render(*a, **k).replace('0.1%', '0.01%'))]
    if kind == 'drop_source':
        return [mock.patch.object(module, 'render_semantic_rows',
                                  lambda *a, **k: '\n'.join(line for line in original_render(*a, **k).splitlines()
                                                           if '출처' not in line))]
    extra = {'forecast': '\n예상 수익률 10%', 'recommend': '\n이 상품의 매수를 추천합니다.'}[kind]
    return [mock.patch.object(module, '_render_final_text', lambda lines: '\n'.join(lines) + extra)]


def verification_off_patches():
    def rows_unchecked(rows, facts, *a, **k):
        by_product = {}
        for item in facts:
            by_product.setdefault(item['subject_id'], []).append(item)
        return tuple(VerifiedSemanticRow(row, tuple(by_product.get(row.entity_ids[0], facts))) for row in rows)
    return [
        mock.patch.object(module, 'validate_semantic_rows', rows_unchecked),
        mock.patch.object(module, 'validate_semantic_task', lambda *a, **k: ('verification-disabled',)),
        mock.patch.object(module, 'validate_final_text', lambda sections, text: canonical_sha256({'text': text})),
    ]


async def run_case(case, verification_on):
    search = PersonalSemanticSearch(
        service(Adapter('domestic_etf', 'fee_rate', action='screen', entity=False)), project_root=ROOT,
        runner_factory=lambda compiler: Runner(case.rows, len(case.rows)),
        repository=Repository(case.facts), utcnow=lambda: NOW)
    patches = tamper_patches(case.tamper) + ([] if verification_on else verification_off_patches())
    for p in patches:
        p.start()
    try:
        result = await search.search(QUESTION)
        return {'delivered': True, 'text': result.text, 'code': None, 'stage': None}
    except PersonalSearchError as error:
        stage = None
        if error.verification_report is not None:
            stage = next((c.stage for c in error.verification_report.checks if c.status == 'fail'), None)
        return {'delivered': False, 'text': None, 'code': error.code, 'stage': stage}
    finally:
        for p in reversed(patches):
            p.stop()


async def main():
    cases = build_cases()
    rows = []
    for case in cases:
        off = await run_case(case, verification_on=False)
        on = await run_case(case, verification_on=True)
        marker_seen = (case.wrong_marker in off['text']) if (off['delivered'] and case.wrong_marker) else None
        rows.append({'case_id': case.case_id, 'category': case.category, 'is_error': case.is_error,
                     'off_delivered': off['delivered'], 'off_code': off['code'], 'off_marker_in_answer': marker_seen,
                     'on_delivered': on['delivered'], 'on_code': on['code'], 'on_failed_stage': on['stage']})
    summary = {}
    for row in rows:
        item = summary.setdefault(row['category'], {'cases': 0, 'off_delivered': 0, 'on_delivered': 0})
        item['cases'] += 1
        item['off_delivered'] += row['off_delivered']
        item['on_delivered'] += row['on_delivered']
    json.dump({'summary': summary, 'cases': rows}, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    asyncio.run(main())

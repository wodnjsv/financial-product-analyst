# 검증 Harness 전후 비교 실험

**Date:** 2026-11-16

## 결과

오류를 일부러 넣은 30건에서, 검증을 끄면 30건(100%)이 최종 답변까지 나갔고 검증을 켜면 0건이 나갔습니다.
정상 20건은 두 조건 모두 그대로 응답했습니다(잘못 막은 것 0건).

| 오류 유형 | 사례 | 검증 끔: 답변 전달 | 검증 켬: 답변 전달 | 막은 단계 (오류 코드) |
| --- | --- | --- | --- | --- |
| 조건 위반 (원천에 있는 0.11~0.8% 값) | 10 | 10 | 0 | `result_contract` (`LOCAL_RESULT_PREDICATE_MISMATCH`) |
| 값 불일치 (답변 값 ≠ 원천 값) | 5 | 5 | 0 | `evidence` (`LOCAL_RESULT_EVIDENCE_INVALID`) |
| 단위·기준일·지표 정의 불일치 | 4 | 4 | 0 | `evidence` (`LOCAL_RESULT_EVIDENCE_INVALID`) |
| 출처 자격 (cutoff 이후, 인용 불가, 권한 등급) | 4 | 4 | 0 | `evidence` (`LOCAL_RESULT_EVIDENCE_INVALID`) |
| 상품 불일치 (상품명·ID·상품군) | 3 | 3 | 0 | `evidence` (`LOCAL_RESULT_EVIDENCE_INVALID`) |
| 최종 문구 변조 (수치 변경, 예측·추천 문장 추가, 출처 삭제) | 4 | 4 | 0 | `final` (`FINAL_RESPONSE_MISMATCH`) |
| **오류 합계** | **30** | **30 (100%)** | **0 (0%)** | |
| 정상 (단일 10, 상품 3~5개 10) | 20 | 20 | 20 | |

검증을 끈 조건에서는 오답 표시를 정의한 사례(19건) 모두에서 그 오답(예: `0.2%`, `예상 수익률`, `매수를 추천`)이 실제 답변 문장에 들어 있었습니다.

## 실험 방법

- 질문: `국내 ETF 중 총보수가 0.1% 이하인 상품을 찾아줘`
- `tests/intent/test_personal_intent.py`의 가짜 의도 어댑터와 `tests/intent/test_personal_search_results.py`의 근거 fixture를 재사용했습니다. NVIDIA, PostgreSQL, 원천 데이터는 호출하지 않습니다.
- 검증 켬: `PersonalSemanticSearch`의 현재 경로 그대로입니다.
- 검증 끔: 같은 경로에서 `validate_semantic_rows`, `validate_semantic_task`, `validate_final_text` 세 함수만 무조건 통과하도록 바꿨습니다. 계획·SQL 소유권 검증 등 나머지 단계는 두 조건이 같습니다.
- 오류 주입 위치: 조회 결과 행(조건 위반·값·상품명), 근거 fact(단위·기준일·정의·출처·상품 ID·상품군), 렌더링 함수(최종 문구).

재현:

```bash
PYTHONPATH=.:src python scripts/run_verification_ablation.py > ablation.json
```

출력의 `summary`가 위 표의 숫자이고, `cases`에 사례별 차단 단계와 오류 코드가 있습니다.

## 한계

- 사례는 검증기가 겨냥한 오류 유형에 맞춰 직접 만든 합성 사례입니다. 이 숫자는 이 유형들을 빠짐없이 막는다는 근거이지, 실제 질문 분포에서의 정확도가 아닙니다.
- 가짜 LLM·가짜 DB 경로입니다. 실제 NVIDIA 응답과 로컬 PostgreSQL 조회는 포함하지 않습니다.
- 차단은 답변 단위입니다. 정상 상품 2개 사이에 조건 위반 1개를 섞은 4건에서는 정상 상품도 함께 내보내지 않았습니다. 틀린 답변 대신 답변 보류를 택한 기존 설계([ADR-0057](../decisions/ADR-0057-personal-verification-harness.md))를 따른 결과입니다.
- 검증에 드는 시간이나 비용은 측정하지 않았습니다.

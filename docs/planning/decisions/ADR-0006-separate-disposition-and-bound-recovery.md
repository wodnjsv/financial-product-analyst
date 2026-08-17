# ADR-0006: Separate Answer Disposition from Execution Failure and Bound Recovery

**Date:** 2026-08-17

**Status:** Accepted

**Related:** [ADR-0005](ADR-0005-bounded-llm-typed-capability-execution.md)

## Context

초기 `VerificationReport.disposition`은 `pass`, `partial`, `limitation`, `abstain`, `repairable_failure`, `internal_failure`를 하나의 Enum으로 두었다. 이 구조는 검증 통과 여부, 사용자 답변의 완성도, 실행 장애를 섞는다. 예를 들어 존재하지 않는 상품은 정상적인 답변 자제 사유지만, DB 타임아웃은 시스템 실패다.

대회 API는 답변 불가 질문도 `200 OK`와 같은 다섯 문자열 필드로 반환하도록 요구한다. 반면 타임아웃과 5xx는 주최측이 최대 두 번 재시도한다. 정상적인 금융·데이터 경계를 5xx로 보내면 무의미한 재시도가 발생하고, 시스템 장애를 `abstain`으로 보내면 복구 기회를 잃는다.

또한 응답 속도가 중요하지만 실제 HyperCLOVA X와 NCP 저장소 지연은 구현 후에만 정확히 알 수 있다. 초기 마감을 두되 실측 결과로 조정할 절차가 필요하다.

## Decision

### Separate three state axes

다음 세 축을 독립적으로 저장한다.

- `ExecutionOutcome`: `completed`, `completed_with_failures`, `failed`
- `VerificationStatus`: `pass`, `fail`
- `AnswerDisposition`: `answer`, `partial`, `limitation`, `abstain`

`AnswerDisposition`은 시스템 장애를 표현하지 않는다. 중심 실행이 완료되지 않아 검증할 수 없으면 답변 판정 없이 5xx를 반환한다.

### Classify subtask importance

`QueryPlan.subtask`는 `critical`, `required_independent`, `optional`을 갖는다. 모든 `critical`이 검증되어야 `answer` 또는 `partial`이 가능하다. `partial`은 중심 결론을 왜곡하지 않는 독립 요청 누락에만 사용한다.

### Map semantic boundaries to HTTP 200

- 완전한 답변: `200 + answer`
- 중심 결론은 검증되었지만 독립 요청 일부 누락: `200 + partial`
- 유효한 질문의 데이터·관계·비교 한계: `200 + limitation`
- 무효한 전제·엔티티 부재·금지 요청: `200 + abstain`

조건에 맞는 결과가 0개라도 조회가 완전히 실행·검증됐으면 `answer`다.

### Map execution failures to 5xx

- 일시적 의존성 실패: 내부 재시도 후 `503`
- 55초 내부 하드 마감 초과: `504`
- 계약·데이터 버전·근거 불변식 반복 훼손: `500`

5xx는 필요한 경우 공식 5필드 JSON 형태를 유지하지만 완성된 `ReleasedAnswer`로 캐시하지 않는다.

### Bound recovery

- 요청 전체 LLM 보정권: 1회
- 요청 전체 일시적 재시도: 2회
- 동일 작업 일시적 재시도: 1회
- 근거 원장 결정론적 재구성: 1회
- 원시 Chain-of-Thought을 재시도 입력으로 저장하지 않음

### Use an initial 55-second internal hard deadline

초기 종료 시각은 요청 시작 기준 20초 질문 해석, 40초 Capability 실행, 45초 검증, 50초 답변·Claim Gate, 55초 응답 전송이다. 마지막 5초는 응답 안전 예산으로 보존한다.

단순, 단일 상품군, 복합·교차 질문의 초기 p95 목표는 각각 4초, 7초, 10초다. 이 값과 55초 마감은 실제 NCP 환경의 냉간·온간 벤치마크로 재평가한다. 구조 최적화를 먼저 수행하고, 측정된 p99와 정확도 영향을 근거로 시간 예산을 조정한다.

55초 안에서의 단계별 재배분은 벤치마크 보고서와 정책 문서에 기록한다. 55초 하드 마감, 판정 순서, HTTP 의미, 재시도 횟수를 바꾸려면 새 승인과 ADR이 필요하다.

## Reasons

- 금융적으로 답할 수 없는 상황과 시스템 장애가 평가·로그·재시도에서 섞이지 않는다.
- `partial`을 중심 결론 누락의 우회로 사용하는 것을 막는다.
- 주최측의 5xx 재시도를 실제로 복구 가능한 장애에만 사용한다.
- 요청별 공유 예산은 재시도 루프와 최악의 모델 호출 수를 제한한다.
- 실측 후 시간을 조정할 수 있지만, 근거 검증을 포기하는 방향으로 최적화하지 않는다.

## Rejected Alternatives

### One mixed disposition enum

검증, 답변 완성도, 실행 장애를 하나의 값으로 두면 같은 `abstain`이 질문 문제인지 서버 문제인지 알 수 없다.

### Always return HTTP 200

일시적 시스템 장애에도 주최측 재시도를 받지 못하고 장애가 답변 자제로 기록된다.

### Return 5xx for every unanswered request

데이터 부재, 존재하지 않는 상품, 금지된 예측 질문도 반복 실행되어 공식 답변 불가 평가를 충족하지 못한다.

### Permit one LLM repair per stage

Intent Resolver와 Answer Composer가 각각 보정하면 실패 경로의 모델 호출 수와 지연이 늘어난다. 요청 전체 한 번으로 제한한다.

### Use the organizer's full 300-second timeout

정상 질문의 응답 속도가 느려지고 실패 감지와 외부 재시도가 지연된다.

## Consequences

### Positive

- 답변 정확도, 데이터 커버리지, 시스템 가용성을 서로 다른 지표로 측정할 수 있다.
- 0건 결과, 부분 결과, 제한, 자제의 의미가 테스트 가능하게 고정된다.
- 실패가 반복되어도 호출 횟수와 최종 종료 시각이 유한하다.
- Composer 장애를 검증된 템플릿으로 후퇴할 수 있다.

### Costs and risks

- 하위 작업의 중요도와 의존성을 `QueryPlan`과 Orchestrator가 일관되게 검증해야 한다.
- 오류 코드, 재시도 예산, 남은 시간을 실행 상태에 저장해야 한다.
- 55초와 단계별 시간은 초기 설계값이므로 실제 인프라 벤치마크가 필수다.
- 5xx 응답은 평가 시스템의 재시도 행동과 함께 통합 테스트해야 한다.

## Preserved Decisions

- 정상 경로의 LLM 호출은 Intent Resolver와 Answer Composer 두 번을 넘지 않는다.
- 결정론적 Orchestrator만 재시도·마감·판정을 제어한다.
- 결정론적 검증 실패를 LLM이 덮어쓸 수 없다.
- 의미적 답변 불가 질문도 사용자에게 재질문하지 않고 한 번의 200 응답으로 끝낸다.

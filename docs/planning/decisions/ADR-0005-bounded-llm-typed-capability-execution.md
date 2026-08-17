# ADR-0005: Use Bounded LLM Roles and Typed Capability Execution

**Date:** 2026-08-17

**Status:** Accepted

**Supersedes:** ADR-0004의 Product Specialist Agent 필수 호출, LLM Verifier 기본 호출, Agent 역할 구성 부분

## Context

ADR-0004는 조건부 병렬 멀티 에이전트 그래프를 선택하면서 Intent Planner, 네 개 Product Specialist, Evidence and Policy Verifier, Answer Synthesizer를 Agent 역할로 정의했다. 그러나 평가 요청은 외부에서 순차로 들어오고 응답 속도가 중요하다. 상품군별 LLM을 항상 추가하면 같은 모델 가족의 오류를 복제하고 지연만 늘릴 수 있다.

이 과제의 차별점은 Agent 수 자체보다 온톨로지, 정확한 관계 탐색, 결정론적 계산, 근거 검증이다. 질문 의도를 여러 하위 작업으로 나누는 능력은 유지하되, 연산·저장소 선택·실행·검증을 LLM 자율성에 맡기지 않는 구조가 더 적합하다.

## Decision

기본 오케스트레이션을 **두 개의 제한된 LLM 역할 + 결정론적 Orchestrator + 타입화된 Capability Executors**로 구성한다.

### LLM 역할

1. **Intent Resolver:** 질문 원문을 스키마로 검증되는 `QueryPlan`으로 변환한다.
2. **Answer Composer:** 검증된 `EvidenceBundle`과 `VerificationReport`만 사용해 답변 초안을 만든다.

정상 기본 경로의 LLM 호출은 최대 두 번이다. 허용된 한 번의 수정은 스키마 오류나 근거 바인딩 실패가 있을 때만 사용하며, 정상 경로의 일부로 간주하지 않는다.

### 결정론적 제어와 실행

- Orchestrator만 작업 그래프, 병렬성, 마감, 재시도, 최종 판정을 제어한다.
- Product Specialist는 기본 LLM Agent가 아니라 상품군별 필드·규칙·온톨로지를 소유한 Capability Module이다.
- Capability Executor는 RDB, Graph, Keyword, Vector, 계산, 순위, 유사도, 비교를 허용된 작업으로 수행한다.
- 독립적인 Capability 작업은 하나의 요청 안에서 병렬로 실행한다.
- 수치, 식별자, 계산, 환산, 비교 가능성, 컷오프, 근거 완전성 검증은 규칙 엔진이 권위를 갖는다.
- 답변 초안은 결정론적 Claim Gate를 통과해야 공개할 수 있다.

### 실행 계약

컴포넌트 간 전달은 [Runtime Contracts](../architecture/RUNTIME_CONTRACTS.md)의 7개 계약 그룹을 사용한다.

1. `RequestContext`
2. `QueryPlan`
3. `ExecutionGraph`
4. `ToolResult`
5. `EvidenceBundle`
6. `VerificationReport`
7. `AnswerDraft` 및 `ReleasedAnswer`

계약은 버전이 있고 알 수 없는 필드를 거부하며, 생성 후 수정하지 않는다. LLM 자유 문장은 실행 필터나 계산식이 될 수 없다.

### 향후 Product Specialist LLM 도입 조건

Product Specialist LLM은 기본안에 포함하지 않는다. 다음 조건을 모두 충족하고 새 ADR을 승인한 경우에만 추가한다.

- 현재 Intent Resolver + 결정론적 Executor가 실패하는 상품군별 골드 사례가 반복적으로 존재한다.
- 추가 LLM이 정확도나 답변 가능률을 측정 가능하게 개선한다.
- 추가 지연과 비용이 실행 시간 목표 안에 있다.
- 같은 모델 가족의 오류를 복제하지 않도록 결정론적 검증이 유지된다.

## Reasons

- 에이전트 수가 아니라 온톨로지·근거·계산 정확도에 지연 예산을 사용한다.
- 자유도가 큰 LLM 중간 결과가 실행 로직으로 전파되는 것을 막는다.
- 구조화된 작업 DAG는 여러 정보를 엮은 질문과 중간 결과 지시어를 유지한다.
- 상품군별 규칙을 모듈로 분리하면 LLM 호출 없이도 책임 경계와 테스트 격리를 유지할 수 있다.
- 평가 질문이 순차적이어도 요청 내부의 독립 작업은 병렬로 실행할 수 있다.

## Rejected Alternatives

### Always invoke four Product Specialist Agents

질문과 관계없는 Agent 호출, 같은 모델 가족의 오류 복제, 지연 증가 때문에 기본안으로 사용하지 않는다.

### One unrestricted general-purpose Agent

질문 해석, 스키마 선택, 도구 실행, 계산, 답변 작성을 하나의 자유 프롬프트에 맡기면 실패 범위가 너무 크고 재현하기 어렵다.

### Event bus and asynchronous Agent messaging

주최측이 질문을 순차로 보내는 초기 범위에서는 메시지 브로커, 분산 상태, 중복 이벤트 처리가 불필요한 운영 복잡도를 만든다.

## Consequences

### Positive

- 정상 경로의 모델 지연과 토큰 사용량을 예측하기 쉽다.
- 실행, 계산, 근거 검증을 정확한 테스트 대상으로 만들 수 있다.
- 하위 작업과 지시어 바인딩을 구조화해 복합 질문을 재현할 수 있다.
- 나중에 특정 Specialist가 필요해도 Capability 계약을 바꾸지 않고 내부 구현만 교체할 수 있다.

### Costs and risks

- `QueryPlan`을 실행 가능한 DAG로 변환하는 컴파일러와 작업 등록부를 구현해야 한다.
- 상품군별 필드·지표·결측·비교 규칙을 코드와 설정으로 명확히 관리해야 한다.
- Intent Resolver가 정확한 구조화 계획을 만들지 못하면 실행 전에 제한 또는 답변 불가로 전환될 수 있다.
- 계약 버전과 생산자·소비자 호환성 테스트를 유지해야 한다.

## Preserved Decisions

- ADR-0004의 결정론적 Orchestrator, 조건부 라우팅, 요청 내부 병렬성, 타입 계약, 재시도 상한, 근거 기반 출력은 유지한다.
- 결정론적 데이터 엔진이 필터, 정렬, 순위, 집계, 계산을 수행한다.
- 검증되지 않은 주장은 Claim Gate를 통과할 수 없다.
- 개인화 투자자문, 주문 실행, 근거 없는 예측은 범위 밖이다.

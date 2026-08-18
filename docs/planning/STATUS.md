# Financial Product Agent 계획·구현 현황

**Updated:** 2026-08-18

이 문서는 어떤 결정과 계획이 Git에 저장되어 있는지, 현재 무엇을 구현 중인지, 다음 단계가 무엇인지를 한 곳에서 추적한다. 설계 권위는 각 연결 문서와 ADR이 가지며, 이 문서는 상태 색인이다.

## 1. 상위 상태

| 구분 | 현재 상태 | 기준 문서 |
| --- | --- | --- |
| Task 1 요구사항·평가 질문·추가 데이터 | 완료; 52개 질문 유형과 공식 데이터 공백 기록 | [Core Evaluation Set](specs/core-evaluation-set.md), [Authoritative Data Requirements](specs/authoritative-data-requirements.md), [Official API Source Matrix](specs/official-api-source-matrix.md) |
| Task 2 상위 아키텍처 | 확정; 2개 제한 LLM 역할 + 결정론적 Orchestrator·Capability·Verifier | [Planning Harness](HARNESS.md), [ADR-0005](decisions/ADR-0005-bounded-llm-typed-capability-execution.md) |
| 실패·판정·시간 예산 | 확정 기본안; 55초 내부 마감은 NCP 벤치마크 후 단계별 재배분 가능 | [Failure and Disposition Policy](architecture/FAILURE_AND_DISPOSITION_POLICY.md), [ADR-0006](decisions/ADR-0006-separate-disposition-and-bound-recovery.md) |
| 근거·Claim·AnswerPlan·Renderer | 확정 기본안; Claim Gate Registry 호환성 검사는 후속 구현 필수 | [Evidence, Verification, and Rendering](architecture/EVIDENCE_VERIFICATION_AND_RENDERING.md), [ADR-0007](decisions/ADR-0007-normalized-evidence-ledger-structured-answer-plan.md) |
| 3개 물리 저장소·5개 논리 계층·NCP 사양 | 확정 기본안; 실제 부하 테스트 후 사양 재검증 | [NCP Deployment Architecture](architecture/NCP_DEPLOYMENT_ARCHITECTURE.md) |
| 온톨로지 논리 구조 | 최소 클래스와 13개 핵심 관계를 현재 기본안으로 기록; TTL·SHACL 필드 매핑은 후속 계획 필요 | [Financial Ontology Architecture](architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md) |
| 공식 평가 API | 규격 기록 완료; 서버 구현은 후속 Stage | [Official Evaluation API](../reference/official-evaluation-api.md) |

## 2. 구현 Stage

### Stage 01 런타임 계약

**상태: 구현·검증 완료, Stage 02 인계용 동결**

- 기본 계약과 JSON Schema는 커밋 `c5d387d`∼`36ffa82`에 구현되었다.
- AnswerPlan의 구조적 경계는 `4dc6c30`에 잠겼다.
- 의존성 lock과 `.dockerignore` 보강은 `69998f5`, 컨테이너 검증 입력 누락 수정은 `822fbf0`에 들어갔다.
- 종료 보강은 `57ce82e`∼`b5f42e7`의 5개 독립 커밋으로 구현했다.
- 호스트에서 224개 contract test, Schema 바이트 최신성, Python 컴파일, diff 검사가 모두 통과했다.
- NCP Ubuntu/Linux-amd64에서 커밋 `b5f42e777d7edb13f980a19bc531a360a3209b85`를 당겨 잠금 이미지를 무캐시 빌드했고, `docker run` 종료 코드 0을 확인했다.
- 개발 Mac에는 Docker 실행 환경이 없어 로컬 중복 컨테이너 검증을 실행하지 못했다. 2026-08-18 사용자 승인에 따라 NCP의 동일 Linux/amd64 무캐시 빌드·실행을 완료 대체 근거로 채택했다.
- 10개 다형 값 필드의 태그 wire shape과 14개 생성 Schema는 Stage 02가 그대로 사용할 동결 입력이다. Stage 02는 두 번째 Python 코덱을 만들지 않는다.
- Claim Gate Registry 등록·호환성 검사는 Stage 01에서 구현하지 않았으며 후속 단계의 필수 구현 항목으로 유지한다.

기준 계획:

- [Stage 01 Runtime Contracts](tasks/2026-08-17-stage-01-runtime-contracts-implementation-plan.md)
- [Stage 01 Execution Contract Hardening](tasks/2026-08-18-stage-01-execution-contract-hardening-plan.md)
- [Stage 01 Closure Hardening Design](specs/2026-08-18-stage-01-closure-hardening-design.md)
- [Stage 01 Closure Hardening Implementation Plan](tasks/2026-08-18-stage-01-closure-hardening-implementation-plan.md)

### Stage 02 PostgreSQL 저장 계층

**상태: Stage 01 인계 조건 충족; 최종 계획 재리뷰·승인 대기**

- 상세 계획과 차단급 리뷰 보강은 작성되어 있다.
- Stage 01 태그 값 API와 생성 Schema를 변경 없이 저장 계약의 입력으로 사용한다.
- 작성된 Stage 02 계획을 동결 계약 기준으로 한 번 더 리뷰하고 명시적 구현 승인을 받는다.

기준 계획: [Stage 02 PostgreSQL Storage](tasks/2026-08-17-stage-02-postgresql-storage-implementation-plan.md)

## 3. 현재 실행하면 안 되는 계획

[2026-08-10 Core Implementation Plan](tasks/2026-08-10-financial-agent-core-implementation-plan.md)은 질문·데이터·온톨로지 요구사항의 역사적 출처로만 유지한다. DuckDB, 로컬 인덱스, 옛 ADR 번호, 이전 에이전트 역할을 포함한 실행 순서는 현재 아키텍처와 맞지 않으므로 그대로 구현하지 않는다.

[Multi-Agent Architecture](architecture/MULTI_AGENT_ARCHITECTURE.md)의 Specialist Agent·LLM Verifier 기본 호출 부분은 역사적 설명이다. 현재 런타임은 ADR-0005∼0007과 Runtime Contracts를 따른다.

## 4. 기록되었지만 아직 새 구현 계획이 필요한 단계

아래 항목은 방향과 제약은 문서화되었지만, 현재 NCP·PostgreSQL·런타임 계약에 맞춘 실행 계획은 아직 없다.

1. 주최 측 4개 마스터 적재·표준화·품질 검증
2. 공식 추가 데이터 원천 승인과 2026-07-11 스냅샷 수집
3. TTL·SHACL 온톨로지와 PostgreSQL→Fuseki ABox 투영
4. SQL·Graph·Keyword·Vector 통합 검색과 상품군별 계산·유사도
5. Intent Resolver·Orchestrator·Capability Executor·Verifier 연결
6. Claim Gate Registry, Renderer, 검증된 응답 캐시
7. `GET /answer`, NCP API 이중화, Load Balancer, 모니터링·부하 테스트

각 단계는 직전 Stage의 실측 결과와 동결된 계약을 입력으로 받아 별도 계획으로 작성한다.

## 5. 다음 순서

1. Stage 02 계획을 Stage 01 동결 계약 기준으로 최종 재리뷰
2. PostgreSQL DDL·Alembic·리포지터리·JSONB 경계의 구현 범위 승인
3. 승인된 Stage 02 계획을 순차적으로 구현·검증

이 순서를 바꾸거나 상위 아키텍처를 바꾸는 경우 사전 승인과 해당 ADR 또는 설계 문서 갱신이 필요하다.

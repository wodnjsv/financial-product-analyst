# Financial Product Agent 계획·구현 현황

**Updated:** 2026-08-19

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

**상태: Stage 02A 핵심 저장 구현·검증 완료; Stage 02B 이식성 증명 대기**

- 상세 계획은 2026-08-18 최종 재리뷰에서 승인된 1A~18A 결정을 반영해 Stage 02A 핵심 저장과 Stage 02B NCP·이식성 증명으로 나뉘었다.
- 사용자가 PostgreSQL DDL·Alembic·리포지터리·JSONB 구현 범위를 승인했으며, `codex/stage-02-storage` 격리 브랜치에서 Task 1 데이터베이스 하니스부터 Task 7 `0005` 불변 request artifact·request lifecycle 저장까지 Stage 02A 범위를 구현했다.
- 비운영 NCP PostgreSQL 15.17을 승인된 4 vCPU/16 GB·Private Subnet 구성으로 생성했고, 콘솔 관리 `pgvector`와 `pg_stat_statements`, 애플리케이션 서버 ACG 한정 5432 접근, 자동 백업 7일을 확인했다.
- 실제 capability probe는 `direct_users`를 선택했다. NCP USER_ID 제한에 맞춘 `fa_migration`, `fa_build`, `fa_runtime`과 직접 최소 권한 방식을 [ADR-0010](decisions/ADR-0010-use-ncp-direct-database-users.md)에 기록했다. 세 사용자 생성, `direct_users` preflight, 최소 DB `CREATE` 부여 후 migration-user capability probe까지 완료했다.
- Rocky Linux 8.10 기반 신규 Cloud DB가 선택형 스토리지 암호화를 지원하지 않는 실제 제약은 [ADR-0009](decisions/ADR-0009-ncp-postgresql-storage-encryption-boundary.md)에 기록했으며, 암호화 적용을 주장하지 않고 Private Subnet·ACG·최소 권한·Credential 비저장·백업을 보상 통제로 사용한다.
- Stage 01 태그 값 API와 생성 Schema를 변경 없이 저장 계약의 입력으로 사용한다.
- 검증된 답변 캐시는 Claim Gate Registry 단계로 미뤘으며, Stage 02는 저장된 `ReleasedAnswer`에 공개 권한을 부여하지 않는다.
- NCP 서버의 폐기 가능한 PostgreSQL 15.18 컨테이너를 SSH 터널로 연결해 `0001` 업·다운그레이드, 7개 스키마, 데이터셋 전이·동시 활성화·동시 요청 멱등성·FailureEvent 불변성·별도 로그인 역할 ACL을 검증했다.
- Task 3은 `catalog.entity`, `product`, `security`, `institution`, `identifier`, `alias`의 버전 결합 키·FK, 상품군과 엔티티 유형 제약, 지연 subtype 검증, 식별자·별칭 인덱스, building 상태 변경 제한과 역할별 ACL을 `0002`에 구현했다. 독립 검토에서 수정 사항 없이 승인됐고, 폐기 가능한 PostgreSQL 15에서 `0002 → 0001 → 0002`, `alembic check`, DB 테스트 93개와 Stage 01 계약 포함 317개가 통과했다.
- Task 4는 버전 결합 관계, 명시적 zero·missingness를 가진 typed 관측값, 불변 metric/model registry, Stage 01 Source, 문서·부모 청크, `cdb_admin.vector` 임베딩 저장을 `0003`에 구현했다. Source→문서 FK 생성 순서, exact chunk hash·model version·vector dimension 검증, building 상태 변경 제한과 역할별 ACL을 PostgreSQL이 강제한다. 독립 검토에서 수정 사항 없이 승인됐고, 폐기 가능한 PostgreSQL 15에서 `0003 → 0002 → 0003`, `alembic check`, Task 4 집중 테스트 53개와 Stage 01 계약 포함 전체 370개가 통과했다.
- Task 5는 Source·Evidence·Calculation·AtomicClaim·ClaimSupport를 정규화한 불변 원장, Stage 01 태그 값·UTC 시각 형식, 컷오프, 단일 origin, Calculation DAG, Claim 지원, 버전 직접 FK와 최소 권한을 `0004`에 구현했다. 동시 의존성 쓰기 편향·비표준 datetime·전이적 dataset FK를 보강한 후 독립 재검토에서 세 지적 모두 해소를 확인했다. 폐기 가능한 PostgreSQL 15에서 `0004 → 0003 → 0004`, `alembic check`, Task 5 집중 테스트 98개와 Stage 01 계약 포함 전체 468개가 통과했다.
- Task 6는 Stage 01 태그 값의 JSONB parity, Source·Evidence·Calculation·AtomicClaim·ClaimSupport의 완전한 왕복, 전체 payload 기반 멱등성, 두 독립 연결의 Source/Evidence 동시 재시도를 SQLAlchemy Core 비동기 리포지터리에 구현했다. Claim과 최초 Support는 `0004` 불변식을 지키기 위해 한 트랜잭션으로 저장하고 후속 Support만 별도 추가한다. Claim 재시도에서 저장된 Support 전체 목록을 비교하도록 보강한 뒤 독립 재검토에서 지적 해소를 확인했다. 폐기 가능한 PostgreSQL 15에서 Task 6 집중 테스트 91개, Stage 01 계약 포함 전체 559개, `alembic check`가 통과했다.
- Task 7은 8개 Stage 01 런타임 산출물의 canonical JSON 원문·DB 파생 JSONB/SHA-256, 정규화된 Evidence·Calculation·Claim 참조, request subtask, FailureEvent, 단방향 실행 종료 상태와 최소권한 보호 함수를 `0005`에 구현했다. 저장된 VerificationReport·AnswerPlan·ReleasedAnswer에는 출시 권한이나 캐시 의미를 부여하지 않는다. 비계산 CheckResult target의 Calculation 오연결을 수정한 뒤 독립 재검토에서 지적 해소를 확인했다. 폐기 가능한 PostgreSQL 15에서 Task 7 집중 테스트 34개, Stage 01 계약 포함 전체 583개, `0005 → 0004 → 0005`, `alembic check`가 통과했다.
- 다음 구현 게이트는 Stage 02B Task 8 마이그레이션 이식성·DB 객체 manifest·Linux/amd64·비운영 NCP 증명이며, 실제 NCP Cloud DB Alembic 적용은 그 명시적 승인 단계까지 보류한다.

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

1. ~~Stage 02 계획을 Stage 01 동결 계약 기준으로 최종 재리뷰~~ — 2026-08-18 완료
2. ~~PostgreSQL DDL·Alembic·리포지터리·JSONB 경계의 구현 범위 승인~~ — 2026-08-18 완료
3. ~~Stage 02A Task 1의 실제 PostgreSQL·NCP capability 검증~~ — 2026-08-18 완료
4. ~~Stage 02A Task 2 database foundation 구현·검증~~ — 2026-08-18 완료
5. ~~Stage 02A Task 3 버전화 상품 카탈로그 구현·검증~~ — 2026-08-18 완료
6. ~~Stage 02A Task 4 관계·관측·문서·검색 저장 구현·검증~~ — 2026-08-18 완료
7. ~~Stage 02A Task 5 정규화 Evidence 원장 구현·검증~~ — 2026-08-18 완료
8. ~~Stage 02A Task 6 손실 없는 Evidence 리포지터리 구현·검증~~ — 2026-08-18 완료
9. ~~Stage 02A Task 7 불변 request artifact·request lifecycle 저장 구현·검증~~ — 2026-08-19 완료
10. Stage 02B NCP·이식성 증명 수행

이 순서를 바꾸거나 상위 아키텍처를 바꾸는 경우 사전 승인과 해당 ADR 또는 설계 문서 갱신이 필요하다.

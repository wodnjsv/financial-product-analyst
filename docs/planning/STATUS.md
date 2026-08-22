# Financial Product Agent 계획·구현 현황

**Updated:** 2026-08-23

이 문서는 어떤 결정과 계획이 Git에 저장되어 있는지, 현재 무엇을 구현 중인지, 다음 단계가 무엇인지를 한 곳에서 추적한다. 설계 권위는 각 연결 문서와 ADR이 가지며, 이 문서는 상태 색인이다.

## 1. 상위 상태

| 구분 | 현재 상태 | 기준 문서 |
| --- | --- | --- |
| 전체 대회 Stage 로드맵 | Stage 01~09 확정; 종점은 제출과 공식 평가 운영 기간 종료 | [Competition Stage Roadmap](ROADMAP.md), [ADR-0012](decisions/ADR-0012-use-nine-stage-competition-delivery-roadmap.md) |
| Task 1 요구사항·평가 질문·추가 데이터 | 완료; 52개 질문 유형과 공식 데이터 공백 기록 | [Core Evaluation Set](specs/core-evaluation-set.md), [Authoritative Data Requirements](specs/authoritative-data-requirements.md), [Official API Source Matrix](specs/official-api-source-matrix.md) |
| Task 2 상위 아키텍처 | 확정; 2개 제한 LLM 역할 + 결정론적 Orchestrator·Capability·Verifier | [Planning Harness](HARNESS.md), [ADR-0005](decisions/ADR-0005-bounded-llm-typed-capability-execution.md) |
| 실패·판정·시간 예산 | 확정 기본안; 55초 내부 마감은 NCP 벤치마크 후 단계별 재배분 가능 | [Failure and Disposition Policy](architecture/FAILURE_AND_DISPOSITION_POLICY.md), [ADR-0006](decisions/ADR-0006-separate-disposition-and-bound-recovery.md) |
| 근거·Claim·AnswerPlan·Renderer | 확정 기본안; Claim Gate Registry 호환성 검사는 후속 구현 필수 | [Evidence, Verification, and Rendering](architecture/EVIDENCE_VERIFICATION_AND_RENDERING.md), [ADR-0007](decisions/ADR-0007-normalized-evidence-ledger-structured-answer-plan.md) |
| 3개 물리 저장소·5개 논리 계층·NCP 사양 | 저장 기본안 확정; PostgreSQL 비운영 NCP 부하·권한 검증 완료, 최종 HA·운영 부하는 배포 단계 | [NCP Deployment Architecture](architecture/NCP_DEPLOYMENT_ARCHITECTURE.md) |
| 온톨로지 논리 구조 | 최소 클래스와 13개 핵심 관계를 현재 기본안으로 기록; TTL·SHACL 필드 매핑은 후속 계획 필요 | [Financial Ontology Architecture](architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md) |
| 공식 평가 API | 규격 기록 완료; 서버 구현은 후속 Stage | [Official Evaluation API](../reference/official-evaluation-api.md) |
| Stage 03B 공식 외부 정형 데이터 | Task 1~7 mapper 완료; ADR-0015의 valid organizer ISIN에서 2026-07-10 KRX ETF 1,133개를 exact binding하고 KRX PDF bounded holdings와 같은 날짜의 KRX 종가·NAV를 보존한다. 로컬 holdings capture inventory는 1,133개 모두 공식 원천으로 채웠고 Task 8 결합 파이프라인이 후속 | [Stage 03B Field Matrix](specs/stage-03b-official-source-field-matrix.md), [Stage 03B Implementation Plan](tasks/2026-08-22-stage-03b-official-structured-data-implementation-plan.md), [ADR-0014](decisions/ADR-0014-use-bounded-official-source-snapshots.md), [ADR-0015](decisions/ADR-0015-use-isin-derived-krx-etf-bindings.md) |

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

**상태: Stage 02A 핵심 저장 및 Stage 02B NCP·이식성 증명 완료**

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
- Task 8은 Linux/amd64 검증 이미지, `0001 → 0005 → base → 0005` 폐기 가능 DB 순환, 함수·뷰·트리거·CHECK·ACL 객체 manifest, 권한·확장·역할 postflight, 합성 규모·인덱스·동시성 검증을 구현했다. 최종 로컬 회귀는 `663 passed, 5 deselected`였고 객체 manifest와 마이그레이션 검증이 통과했다.
- 2026-08-20 승인된 비운영 NCP 실행에서 `0001`부터 `0005`까지 적용하고 `direct_users` postflight, `fa_runtime` 읽기/보호 DML 차단, 역할 분리 합성 적재와 `ANALYZE`, 여섯 코어 SQL의 p95 500ms 미만 gate, 30회의 4동시 읽기, 사후 postflight와 객체 manifest를 모두 통과했다. NCP 관리형 `pg_read_all_stats` 관계의 정확한 허용 경계는 [ADR-0011](decisions/ADR-0011-allow-ncp-managed-statistics-membership.md)에 기록했다. 개별 지연시간은 quiet 출력에 보존되지 않아 임의 수치로 기록하지 않는다.
- Stage 02 이후 구현 게이트는 실제 주최측·공식 추가 데이터의 적재·표준화 계획이다. 최종 평가용 HA, 백업·복원, API 부하, 장애 복구와 공개 endpoint 운영 검증은 데이터·API 구현 이후의 배포 단계로 유지한다.

기준 계획: [Stage 02 PostgreSQL Storage](tasks/2026-08-17-stage-02-postgresql-storage-implementation-plan.md)

### Stage 03A 주최 측 마스터 적재

**상태: 완료 — 로컬 실데이터·private Object Storage·Linux/amd64 검증 통과**

- 207개 원천 필드를 승인된 분류와 Stage 02 저장 경계에 매핑하고, 네 소스별 결정론적 매퍼와 하나의 FK 순서 보장 배치 writer를 구현했다.
- Task 9는 8개 워크북 전체의 체크섬·헤더·행 수·중복 구조를 먼저 검증한 뒤에만 `building` 데이터셋을 만들며, 네 소스를 1,000행 배치로 순차 적재한다. 해외 ETP 중복 식별자는 자동 병합하지 않고, 공모펀드 반복행은 공통값 일치 검증 후 대표 원본 위치만 Evidence locator로 사용한다.
- openpyxl 읽기 전용 모드가 실제 워크북 행 끝의 빈 셀을 생략하는 동작을 재현 테스트로 고정했다. 생략된 끝 셀은 `None`으로 복원하고 스키마보다 넓은 행은 안정 오류로 거부한다.
- 2026-08-22 로컬 PostgreSQL 15 폐기 가능 클러스터에서 실제 `42,394 + 1,734 + 5,646 + 95,619 = 145,393`행을 검증된 임시 스냅샷으로 재적재했다. 실제 데이터 게이트는 `2 passed in 1511.29s`였고, 결과 데이터셋 상태는 `building`, `active_dataset`은 0개였다.
- 빠른 source·pipeline·외부 게이트 경계 검증은 36개, 비NCP ingestion 회귀는 `136 passed, 2 skipped, 2 deselected`였다. 깨끗한 기준 DB의 계약·DB·ingestion 전체 회귀는 `799 passed, 2 skipped, 7 deselected`였으며 계약 Schema, DB 객체 manifest, Python 컴파일, 의존성, diff 검사가 통과했다.
- 2026-08-22 NCP Ubuntu에서 수정된 ingestion 검증 이미지를 Linux/amd64로 무캐시 빌드하고 실행해 모두 종료 코드 0을 확인했다. 이미지 내부 synthetic contract·ingestion 검증은 통과했고 organizer 원본은 이미지 계층에 포함하지 않았다.
- VPC 접근 제어가 적용된 private Object Storage는 NCP 사설 S3 endpoint를 사용해 서버 원본 8개와 저장 객체 8개의 SHA-256 동일성을 검증했으며, 전용 gate는 `1 passed in 62.54s`였다. 공개 endpoint의 403은 권한 추가가 아니라 사설 endpoint 사용으로 해소했다.
- NCP DB에는 03A 부분 데이터셋을 만들지 않았다. 로컬 폐기 가능 PostgreSQL에서 manifest·SourceRecord 계보를 이미 검증했으며, NCP DB의 결합 계보 검사는 03A·03B·03C 원천 manifest가 모두 동결된 뒤 03C 최종 `building` 재현에서 수행한다.
- 이 단계의 데이터셋은 검증용 비활성 `building` 버전이다. 03B 공식 외부 정형 데이터와 03C 공식 문서·최종 품질 게이트가 끝난 뒤 NCP에서 최종 버전을 재현하므로 Stage 03 전체는 아직 진행 중이다.

기준 계획: [Stage 03A Organizer Master Ingestion](tasks/2026-08-20-stage-03a-organizer-master-ingestion-plan.md)

### Stage 03B 공식 외부 정형 데이터

**상태: 소스별 mapper 완료 — Task 8 결합 적재 대기**

- SEC N-PORT Task 7은 공식 5개 TSV만 안전 추출하고, 컷오프 이하 최신 report·amendment를 선택하며, 주최 측 해외 ETF를 명시적 `product_entity_id + CIK + Class Ticker` binding으로 Series와 대조한다. Series ID를 주최 측 상품의 고유 식별자로 승격하지 않고 새 테이블·DDL·온톨로지 관계도 추가하지 않았다.
- 보유종목은 고유하고 유효한 ISIN, 그다음 CUSIP만 승격한다. 중복·미해소 식별자는 snapshot-local Security로 보존하고 `PARTIALLY_COVERED/bounded_unknown`으로 제한하며, ticker는 별칭으로만 사용한다. 동일 원본 lot은 합산하지 않고 별도 `holdsSecurity` 관계로 유지한다.
- 일반 테스트는 합성 N-PORT 파일만 사용한다. SEC 2026 Q2 실제 ZIP 다운로드·Object Storage 업로드·실제 coverage 집계·NCP PostgreSQL 결합 적재는 아직 실행하지 않았으며 Task 8~9 게이트에 남아 있다.
- 국내 ETF holdings 로컬 inventory는 KRX CSV 1,129개와 운용사 공식 fallback 4개로 exact binding 1,133개를 모두 채웠다. 이 파일들은 비추적 원본이며 Task 8에서 manifest·coverage·결합 재현을 검증한다.
- Task 5는 KRX 2026-07-10 ETF 일별 응답의 1,141행을 검증하고, exact binding 1,133개에 대해서만 종가와 NAV를 별도 Decimal Observation·Evidence로 매핑한다. KRX-only 8개와 주최 측 미연결 69개에는 상품 가격 사실을 만들지 않으며, 이름 차이는 식별키로 사용하지 않는다.

## 3. 현재 실행하면 안 되는 계획

[2026-08-10 Core Implementation Plan](tasks/2026-08-10-financial-agent-core-implementation-plan.md)은 질문·데이터·온톨로지 요구사항의 역사적 출처로만 유지한다. DuckDB, 로컬 인덱스, 옛 ADR 번호, 이전 에이전트 역할을 포함한 실행 순서는 현재 아키텍처와 맞지 않으므로 그대로 구현하지 않는다.

[Multi-Agent Architecture](architecture/MULTI_AGENT_ARCHITECTURE.md)의 Specialist Agent·LLM Verifier 기본 호출 부분은 역사적 설명이다. 현재 런타임은 ADR-0005∼0007과 Runtime Contracts를 따른다.

## 4. 확정된 후속 Stage

[Competition Stage Roadmap](ROADMAP.md)은 대회 제출과 평가 운영 기간 종료를 종점으로 하는 현재 권위 있는 전체 순서를 정의한다.

| Stage | 범위 | 상태 |
| --- | --- | --- |
| 03 | 주최 측·공식 추가 데이터 수집, 표준화, 계보와 컷오프 검증 | 03A 완료; 03B Task 1~7 mapper 완료·Task 8 결합 대기; 03C 대기 |
| 04 | TTL·SHACL, PostgreSQL→Fuseki ABox, Keyword·Vector 투영과 데이터 버전 활성화 | 대기 |
| 05 | SQL·Graph·Keyword·Vector 통합 검색과 결정론적 금융 계산·유사도 | 대기 |
| 06 | Intent Resolver, RequestContext·QueryPlan·ExecutionGraph, Orchestrator·Capability 실행 | 대기 |
| 07 | Verifier, Claim Gate Registry, Answer Composer, Renderer와 검증된 응답 캐시 | 대기 |
| 08 | 공식 `GET /answer`, NCP 이중화·Load Balancer·모니터링·복구 | 대기 |
| 09 | 52개 종합 평가, 제출 동결, 공식 평가 운영과 종료 기록 | 대기 |

각 Stage는 직전 Stage의 실측 결과와 동결된 계약을 입력으로 받아 별도 구현 계획과 사용자 승인을 거친다. 병렬 준비가 허용된 작업도 로드맵의 완료 게이트를 건너뛸 수 없다.

Stage 03은 [경량 데이터 수집·표준화 설계](specs/2026-08-20-stage-03-lean-data-ingestion-design.md)와 [ADR-0013](decisions/ADR-0013-use-lean-source-specific-ingestion.md)에 따라 03A 주최 측 마스터, 03B 승인된 공식 외부 정형 데이터, 03C 공식 문서·최종 품질 게이트로 나뉜다. 03A의 실행 순서는 [주최 측 마스터 적재 계획](tasks/2026-08-20-stage-03a-organizer-master-ingestion-plan.md)이 관리한다.

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
10. ~~Stage 02B NCP·이식성 증명 수행~~ — 2026-08-20 완료
11. ~~대회 제출·평가 운영 종료까지 Stage 01~09 전체 로드맵 확정~~ — 2026-08-20 완료
12. ~~Stage 03을 03A 주최 측 마스터·03B 공식 외부 정형 데이터·03C 공식 문서와 최종 품질 게이트로 분리~~ — 2026-08-20 완료
13. ~~Stage 03의 과도한 범용 추상화를 제거하고 소스별 경량 파이프라인으로 확정~~ — 2026-08-20 완료
14. ~~Stage 03A 주최 측 4개 마스터 구현계획 최종 검토와 승인~~ — 2026-08-20 완료
15. ~~Stage 03A Task 1의 207개 필드 매핑 matrix 작성·검토·승인~~ — 2026-08-20 완료
16. ~~Stage 03A Task 2~9 로컬 구현과 실제 145,393행 적재 검증~~ — 2026-08-22 완료
17. ~~Stage 03A private Object Storage checksum과 Linux/amd64 런타임 검증~~ — 2026-08-22 완료
18. ~~Stage 03B 첫 공식 외부 정형 데이터 범위와 설계 승인~~ — 2026-08-22 완료
19. ~~Stage 03B 설계를 단계별 실행 계획과 57개 공식 필드 매트릭스로 확정~~ — 2026-08-22 완료
20. ~~Stage 03B Task 2 불변 공식 스냅샷 캡처·검증 구현~~ — 2026-08-22 완료
21. ~~Stage 03B Task 3 공식 식별자 정확 해소 구현~~ — 2026-08-22 완료
22. ~~Stage 03B Task 6 ECOS 승인 환율 4종 구현~~ — 2026-08-22 완료
23. ~~Stage 03B Task 4~5 차단을 유지하고 Task 7 SEC N-PORT bounded parser·mapper 구현~~ — 2026-08-22 완료
24. ~~Stage 03B Task 4의 KRX ETF별 2026-07-10 PDF bounded holdings mapper 구현·대표 원본 검증~~ — 2026-08-22 완료
25. ~~Stage 03B Task 4의 1,133개 연결 ETF PDF full capture inventory 생성·검증~~ — 2026-08-23 완료
26. ~~Stage 03B Task 5 KRX ETF 종가·NAV 구현~~ — 2026-08-23 완료
27. Stage 03B Task 8의 Stage 03A+03B 결합 파이프라인 구현계획 재리뷰·승인

이 순서를 바꾸거나 상위 아키텍처를 바꾸는 경우 사전 승인과 해당 ADR 또는 설계 문서 갱신이 필요하다.

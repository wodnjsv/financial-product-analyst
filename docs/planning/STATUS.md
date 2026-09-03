# Financial Product Agent 계획·구현 현황

**Updated:** 2026-09-04

이 문서는 어떤 결정과 계획이 Git에 저장되어 있는지, 현재 무엇을 구현 중인지, 다음 단계가 무엇인지를 한 곳에서 추적한다. 설계 권위는 각 연결 문서와 ADR이 가지며, 이 문서는 상태 색인이다.

## 1. 상위 상태

| 구분 | 현재 상태 | 기준 문서 |
| --- | --- | --- |
| 전체 대회 Stage 로드맵 | Stage 01~09 확정; 종점은 제출과 공식 평가 운영 기간 종료 | [Competition Stage Roadmap](ROADMAP.md), [ADR-0012](decisions/ADR-0012-use-nine-stage-competition-delivery-roadmap.md) |
| Task 1 요구사항·평가 질문·추가 데이터 | 내부 52개 회귀 질문의 지원 상태를 유지하고 schema `1.3` 여섯 요구사항 그룹·명시적 Capability route로 정규화 완료; 실제 DB 실행 검증은 `not_run`으로 분리 | [Core Evaluation Set](specs/core-evaluation-set.md), [Question Contract Normalization](specs/2026-08-29-question-capability-contract-normalization-design.md) |
| Task 2 상위 아키텍처 | 확정; 2개 제한 LLM 역할 + 결정론적 Orchestrator·Capability·Verifier | [Planning Harness](HARNESS.md), [ADR-0005](decisions/ADR-0005-bounded-llm-typed-capability-execution.md) |
| 실패·판정·시간 예산 | 확정 기본안; 55초 내부 마감은 NCP 벤치마크 후 단계별 재배분 가능 | [Failure and Disposition Policy](architecture/FAILURE_AND_DISPOSITION_POLICY.md), [ADR-0006](decisions/ADR-0006-separate-disposition-and-bound-recovery.md) |
| 근거·Claim·AnswerPlan·Renderer | 확정 기본안; Claim Gate Registry 호환성 검사는 후속 구현 필수 | [Evidence, Verification, and Rendering](architecture/EVIDENCE_VERIFICATION_AND_RENDERING.md), [ADR-0007](decisions/ADR-0007-normalized-evidence-ledger-structured-answer-plan.md) |
| 3개 물리 저장소·5개 논리 계층·NCP 사양 | 저장 기본안 확정; PostgreSQL 비운영 NCP 부하·권한 검증 완료, 최종 HA·운영 부하는 배포 단계 | [NCP Deployment Architecture](architecture/NCP_DEPLOYMENT_ARCHITECTURE.md) |
| 온톨로지 논리 구조 | 13개 관계 유지, `ProductRiskGrade`·`CreditGrade` 분리, `PolicyProgram`, controlled attribute·문서 provenance 경계 승인; 실제 PostgreSQL 관계의 결정론적 Evidence-bound ABox·읽기 전용 Fuseki와 Vector Evidence 승격 경로를 로컬 검증, Stage 04는 미완료 | [Financial Ontology Architecture](architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md), [ADR-0018](decisions/ADR-0018-keep-minimal-ontology-with-canonical-multi-role-products.md), [ADR-0021](decisions/ADR-0021-amend-minimal-ontology-for-question-contract-semantics.md) |
| 통합 마이그레이션 기준 | 문서 `0008`·`0009`, Intent `0010`·`0011`, 검증 응답 캐시 `0012`를 연결한 단일 head; 기존 문서 코퍼스 재적재 불필요 | [ADR-0046](decisions/ADR-0046-linearize-document-and-intent-migrations.md), [Stage 05–07 검증 기록](verification/2026-09-04-stage05-stage07-local-vertical-slice-verification.md) |
| Intent Resolver·QueryPlan·Orchestrator | Phase 1~3와 SQL 의미 계약 V2 경로를 로컬 구현·검증했다. V2는 요청별 제한 후보 구조를 유지하면서 한국어 V4 오버레이를 공유한다. full-catalog hybrid V3도 구현·검증했지만 HCX-007 정확도와 provider 성공률이 승격 기준에 크게 미달해 `implemented, shadow-only`; V2가 기본이며 promotion은 fail-closed `deferred`다. PostgreSQL conformance는 미측정이다. | [Hybrid V3 Verification](verification/2026-09-03-hybrid-full-catalog-semantic-linking-verification.md), [ADR-0030](decisions/ADR-0030-use-hybrid-full-catalog-semantic-linking.md), [ADR-0031](decisions/ADR-0031-share-korean-nlu-overlay-v4-with-v2.md) |
| 공식 평가 API | 규격 기록 완료; 서버 구현은 후속 Stage | [Official Evaluation API](../reference/official-evaluation-api.md) |
| Stage 03 organizer·외부 정형 데이터 | 최신 주최 측 8개 workbook·8월 24일 cutoff·280필드·전역 identity 재베이스와 organizer 로컬 결정성 검증 완료; 8월 22일 KRX ETF 구성종목 1,161개의 로컬 PostgreSQL 통합·재현·대표 질의 검증 완료; 새 NCP acceptance는 Stage 08로 이연 | [ADR-0016](decisions/ADR-0016-use-2026-08-24-organizer-baseline.md), [ADR-0019](decisions/ADR-0019-defer-ncp-acceptance-until-local-end-to-end.md), [Local KRX Plan](tasks/2026-08-26-local-krx-holdings-integration-plan.md) |

## 2. 구현 Stage

### Stage 01 런타임 계약

**상태: JSON shape 구현·검증 완료; current cutoff `2026-08-24` 계약 보강 완료**

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

**상태: 정규화 저장구조와 NCP·이식성 증명 완료; legacy 보존형 cutoff migration `0006` 구현·검증 완료**

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

**상태: 최신 주최 측 배포본 기준 로컬 재베이스·결정성 검증 완료; 외부 데이터 로컬 통합 진행 중; NCP acceptance는 Stage 08로 이연**

- 2026-08-24 공지로 교체된 8개 workbook을 유일한 current organizer 기준으로 사용한다. 실제 원본의 적용일은 행·필드별 2026-08-20∼2026-08-24 값을 보존하며, 옛 2026-07-11 배포본은 역사적 검증 자료로만 남긴다.
- 4개 master의 280개 필드와 53,375행을 새 source 계약과 전역 identity pre-scan으로 재구현했다. 국내 ETF·공모펀드 exact overlap 217개는 하나의 canonical product로 재사용하고, 해외 ISIN·Lipper 모호 그룹 63쌍은 식별자로 승격하거나 자동 병합하지 않는다.
- 두 개의 깨끗한 로컬 PostgreSQL 15 DB에 각각 전량 적재했다. 두 실행 모두 `building`, active 0, manifest 동일이었고 데이터셋 ID·생성시각을 제외한 모든 catalog·observation·relation·Evidence 행이 전수 일치했다.
- 저장되지 않는 매핑 품질 집계도 두 번 독립 순회해 완전히 일치했다. 53,375행은 모두 원본 결측·코드 미정의·모호성을 제한정보로 보존한 `limited`이며 fatal·quarantined는 0이다.
- 최신 focused PostgreSQL·mapper 테스트 68개, 비DB ingestion 회귀 313개, 계약·DB·ingestion 전체 비-live 회귀 997개가 통과했다. 최종 NCP `building` 적재와 `fa_runtime` 비활성·읽기 전용 확인은 ADR-0019에 따라 Stage 08에서 반복한다.

아래 7월 배포본 기록은 역사적 검증 이력이다.

- 207개 원천 필드를 승인된 분류와 Stage 02 저장 경계에 매핑하고, 네 소스별 결정론적 매퍼와 하나의 FK 순서 보장 배치 writer를 구현했다.
- Task 9는 8개 워크북 전체의 체크섬·헤더·행 수·중복 구조를 먼저 검증한 뒤에만 `building` 데이터셋을 만들며, 네 소스를 1,000행 배치로 순차 적재한다. 해외 ETP 중복 식별자는 자동 병합하지 않고, 공모펀드 반복행은 공통값 일치 검증 후 대표 원본 위치만 Evidence locator로 사용한다.
- openpyxl 읽기 전용 모드가 실제 워크북 행 끝의 빈 셀을 생략하는 동작을 재현 테스트로 고정했다. 생략된 끝 셀은 `None`으로 복원하고 스키마보다 넓은 행은 안정 오류로 거부한다.
- 2026-08-22 로컬 PostgreSQL 15 폐기 가능 클러스터에서 실제 `42,394 + 1,734 + 5,646 + 95,619 = 145,393`행을 검증된 임시 스냅샷으로 재적재했다. 실제 데이터 게이트는 `2 passed in 1511.29s`였고, 결과 데이터셋 상태는 `building`, `active_dataset`은 0개였다.
- 빠른 source·pipeline·외부 게이트 경계 검증은 36개, 비NCP ingestion 회귀는 `136 passed, 2 skipped, 2 deselected`였다. 깨끗한 기준 DB의 계약·DB·ingestion 전체 회귀는 `799 passed, 2 skipped, 7 deselected`였으며 계약 Schema, DB 객체 manifest, Python 컴파일, 의존성, diff 검사가 통과했다.
- 2026-08-22 NCP Ubuntu에서 수정된 ingestion 검증 이미지를 Linux/amd64로 무캐시 빌드하고 실행해 모두 종료 코드 0을 확인했다. 이미지 내부 synthetic contract·ingestion 검증은 통과했고 organizer 원본은 이미지 계층에 포함하지 않았다.
- VPC 접근 제어가 적용된 private Object Storage는 NCP 사설 S3 endpoint를 사용해 서버 원본 8개와 저장 객체 8개의 SHA-256 동일성을 검증했으며, 전용 gate는 `1 passed in 62.54s`였다. 공개 endpoint의 403은 권한 추가가 아니라 사설 endpoint 사용으로 해소했다.
- NCP DB에는 03A 부분 데이터셋을 만들지 않았다. 로컬 폐기 가능 PostgreSQL에서 manifest·SourceRecord 계보를 이미 검증했으며, NCP DB의 결합 계보 검사는 03A·03B·03C 원천과 Stage 04~07 서비스 경계가 모두 동결된 뒤 Stage 08 최종 `building` 재현에서 수행한다.
- 이 단계의 데이터셋은 검증용 비활성 `building` 버전이다. 03B 공식 외부 정형 데이터와 03C 공식 문서·최종 품질 게이트를 로컬에서 먼저 완료하고 Stage 08에서 NCP 최종 버전을 재현하므로 Stage 03 전체는 아직 진행 중이다.

기준 계획: [Stage 03A Organizer Master Ingestion](tasks/2026-08-20-stage-03a-organizer-master-ingestion-plan.md)

### Stage 03B 공식 외부 정형 데이터

**상태: current cutoff 재바인딩·8월 22일 KRX holdings 로컬 PostgreSQL 결합·재현·대표 질의 검증 완료; 주최 측 결측 권위 정책·나머지 공식 source 로컬 완료 계획 승인, 순차 구현 중; 새 NCP acceptance는 최종 배포 단계로 이연**

- [ADR-0020](decisions/ADR-0020-treat-organizer-missingness-as-authoritative.md)에 따라 organizer 스키마가 정의한 상품 사실은 공란·`NULL`·placeholder여도 권위 있는 결측으로 유지한다. 동일 의미의 외부 값을 답변 사실로 적재하지 않고, 원문·manifest 감사 경계만 보존한다. 주최 측에 없는 구성종목 관계·증권 식별자·ECOS 환율·coverage 계보만 명시적 allowlist로 보완한다.
- current cutoff 코드·테스트와 KRX ETF PDF의 `2026-08-22` 로컬 캡처는 구현·검증됐다. ECOS·SEC·운용사 객체는 국내 영업일 `2026-08-22`, 해외 한국시간 `2026-08-23`, 최종 가용성 cutoff `2026-08-24` 경계를 source별로 지켜 로컬에서 추가 동결한다. NCP 결합 적재는 Stage 08까지 수행하지 않는다.
- SEC Series/Class와 2026 Q2 N-PORT 원본 448,751,052 byte는 재다운로드 없이 SHA-256을 재검증해 current cutoff manifest로 재승인했다. 최신 주최 측 해외상품 6,037개 전체 측정은 `COVERED=6`, `PARTIALLY_COVERED=4,247`, `NOT_COVERED=1,781`, 구성종목 식별 충돌 3개다. 이 결과는 SEC가 포괄하지 못한 상품을 구성종목 없음으로 단정하지 않고 bounded coverage로 보존한다. 결정론적 10개 상품 실데이터 gate는 `1 passed in 230.78s`였다.
- 공모펀드 구성종목은 KOFIA 비교공시·자산운용보고서·Fund One-Click, OpenDART, 운용사 문서를 공식성·날짜·exact share-class binding·종목 의미·전수 coverage·원문 보존 기준으로 검토했으나 모든 gate를 통과한 source가 없었다. Stage 03 결정은 `requires_data`이며, ETF-only 결과를 전체 결과로 표현하거나 공모펀드의 보유 없음을 추론하지 않는다.
- 나머지 source 동결, 질문 coverage 확정, 두 로컬 PostgreSQL 최종 재현은 [Stage 03 Local Completion Plan](tasks/2026-08-27-stage-03-local-completion-plan.md)을 따른다. 주최 측에 종가·NAV 필드가 이미 있으므로 current KRX ETF daily 값은 답변 보강 source에서 제외한다.

아래 7월 cutoff 캡처 기록은 역사적 검증 이력이다.

- SEC N-PORT Task 7은 공식 5개 TSV만 안전 추출하고, 컷오프 이하 최신 report·amendment를 선택하며, 주최 측 해외 ETF를 명시적 `product_entity_id + CIK + Class Ticker` binding으로 Series와 대조한다. Series ID를 주최 측 상품의 고유 식별자로 승격하지 않고 새 테이블·DDL·온톨로지 관계도 추가하지 않았다.
- 보유종목은 고유하고 유효한 ISIN, 그다음 CUSIP만 승격한다. 중복·미해소 식별자는 snapshot-local Security로 보존하고 `PARTIALLY_COVERED/bounded_unknown`으로 제한하며, ticker는 별칭으로만 사용한다. 동일 원본 lot은 합산하지 않고 별도 `holdsSecurity` 관계로 유지한다.
- 일반 테스트는 합성 N-PORT 파일만 사용한다. SEC 2026 Q2 실제 ZIP 다운로드·Object Storage 업로드·실제 coverage 집계·NCP PostgreSQL 결합 적재는 아직 실행하지 않았으며 Task 9 게이트에 남아 있다.
- 2026-07-11 구기준 국내 ETF holdings inventory는 KRX CSV 1,129개와 운용사 공식 fallback 4개로 exact binding 1,133개를 채운 역사적 결과다. 최종 입력에는 재사용하지 않는다.
- current 국내 ETF holdings 원본은 실제 기준일 `2026-08-22` KRX CSV 1,161개다. 최신 주최 측의 ETF·유효 `pd_ticker`·상장종료 조건으로 계산한 모집단과 파일명이 1,161 대 1,161로 일치하고 `MISSING=0`, `EXTRA=0`, `FILE_FAILURES=0`이다. 전수 로컬 변환은 구성종목 75,216개를 `holdsSecurity` 75,216건, Observation 301,517건, Evidence 377,894건으로 재현했고 gated 검증 `1 passed in 72.26s`를 통과했다.
- 두 개의 깨끗한 로컬 PostgreSQL 15 DB에 최신 organizer 4개 master와 KRX holdings를 독립 적재했다. 두 실행의 manifest·재현성·PostgreSQL·Evidence 해시와 Samsung Electronics AUM 상위 5개 결과가 완전히 일치했다. 각 DB는 entity 77,832개, product 58,651개, relation 152,555건, Observation 3,859,702건, Evidence 4,042,495건이었다. KRX 보유 기준일 `2026-08-22`, 주최 측 ETF AUM 기준일 `2026-08-21`, 양쪽 Evidence locator, `building`·current active 0을 확인했고 `group_roles` postflight와 DB 객체 manifest 검사가 통과했다. 이 결과는 로컬 데이터 경계의 근거이며 NCP 준비 완료를 의미하지 않는다.
- Task 5는 KRX 2026-07-10 ETF 일별 응답의 1,141행을 검증하고, exact binding 1,133개에 대해서만 종가와 NAV를 별도 Decimal Observation·Evidence로 매핑한다. KRX-only 8개와 주최 측 미연결 69개에는 상품 가격 사실을 만들지 않으며, 이름 차이는 식별키로 사용하지 않는다.
- Task 8은 Stage 03A organizer 입력과 승인 공식 manifest를 모두 검증한 뒤 한 canonical manifest와 하나의 `building` 데이터셋에 순차 결합한다. NCP Ubuntu에서 Linux/amd64 이미지 `266 passed, 13 deselected`, PostgreSQL ingestion `9 passed, 270 deselected`, 전체 비-live 회귀 `938 passed, 9 deselected`를 확인했다. 최종 NCP PostgreSQL 데이터셋은 아직 적재하거나 활성화하지 않았다.
- Task 9 로컬 캡처는 7개 공식 소스의 1,135개 객체, 약 454 MB를 컷오프 이하 불변 manifest로 고정했다. SEC N-PORT의 게시일은 2026-06-30, 공식 데이터 라이브러리 available date는 2026-07-09로 분리했다. 실제 SEC Series/Class 43,121행, N-PORT 공식 5개 TSV와 주최 측 해외 ETF 5,646개 binding을 전부 검증했다.
- 첫 전체 N-PORT 측정은 Python 내 연결표가 약 4.6 GB를 사용해 중단했다. 선택 행을 폐기 가능한 SQLite keyed join으로 spill하고 250 holdings·10만 생성 레코드 상한을 적용한 뒤, 9,672개 출력 묶음에서 구성종목 1,299,751개와 관측값 7,798,506개를 약 33분 42초·최대 0.26 GB로 처리했다. 공식 `N/A`·공란 파생상품 817행은 추가 검증 후 관계를 보존하고 `unknown` Observation으로 정규화했다.
- Task 9 일반 계약·ingestion 회귀는 `511 passed, 15 deselected`, 로컬 공식 캡처 재검증은 `1 passed`였다. NCP Object Storage 왕복, Linux/amd64 이미지, 실제 PostgreSQL 결합 재현은 로컬에 자격증명·Docker·DB URL이 없어 실행하지 않았다. 예상 N-PORT 논리 payload와 인덱스·두 재현 빌드를 고려하면 현재 10 GB NCP DB는 부족하므로 실제 적재 전에 최소 50 GB, 권장 100 GB로 확장해야 한다.

### Stage 03C 공식 문서 Phase 0

**상태: DART 공식 문서·실제 임베딩 적재와 선택 청크 Evidence 승격 경로의 로컬 통합 검증 완료; 최종 공식 정형 source 결합은 대기**

- `organizer-dart-2026-08-24-v2` 데이터셋에 DART 공식 문서 2,214건을 연결하고 40,149개 청크를 생성했다. 동일한 40,149개 청크에 `ncp-clova-bge-m3` / `embedding-v2-dart-search-text-v1` 임베딩을 생성해 로컬 PostgreSQL에 저장했다.
- 검색 후보는 상품·문서·출처·페이지·섹션·원문 범위·버전 메타데이터를 유지한다. 원본 PDF는 청크 적재 후 누적 보관하지 않고, 원본 파일 식별과 검증에 필요한 provenance만 보존한다.
- Vector 검색 결과는 후보로만 취급하고 모든 청크를 Evidence로 일괄 승격하지 않는다. 답변에 실제로 채택된 청크만 PostgreSQL 권위 메타데이터를 다시 확인한 뒤 `document_span` Evidence와 정확한 문서 청크 origin으로 승격한다. 국내 ETF·공모펀드 실제 canary가 이 왕복과 원문 범위를 통과했다.
- 이 데이터셋은 `building`이며 활성 데이터셋은 없다. 현재 결과는 로컬 검색 기반을 완성한 것이고 최종 Stage 04 readiness·activation 또는 NCP 운영 준비 완료를 뜻하지 않는다.

| 질문 | 상태 | current_db_execution |
| --- | --- | --- |
| `DOC-FUND-001` | `requires_additional_data` | `not_run` |
| `REL-THEME-001` | `requires_additional_data` | `not_run` |
| `REL-CORP-001` | `requires_additional_data` | `not_run` |

### Stage 04 Graph·Vector 투영과 데이터셋 활성화

**상태: 실제 PostgreSQL·Graph·Vector·Evidence 통합 기반 로컬 검증 완료; 최종 공식 정형 source·readiness·activation이 남아 Stage 04 미완료**

- 13개 승인 predicate의 TBox·SHACL, 명시적 문서·위험요인 provenance, 날짜별 holding-weight observation, PostgreSQL 반복 가능 읽기 전용 투영, 결정론적 N-Quads·검증 산출물에 결합된 Graph component manifest, Evidence-bound SPARQL 읽기 경로와 읽기 전용 Fuseki 적합성 게이트를 구현했다. 실제 문서 ABox는 만들지 않고 합성 fixture만 사용했다.
- 2026-08-30 최종 로컬 검증은 외부 서비스 없는 Graph gate `197 passed, 13 deselected in 21.26s`, 기존 non-live 회귀 `896 passed, 361 deselected in 22.60s`, 전용 폐기 가능 PostgreSQL `15.19` 투영 gate `12 passed in 0.45s`, Apache Jena/Fuseki `6.0.0`·Java `24` exact-runtime gate `13 passed in 21.78s`를 모두 통과했다. PostgreSQL gate는 두 연결 사이 커밋을 사용해 relation/Evidence를 섞어 읽지 않는 단일 `REPEATABLE READ, READ ONLY` snapshot도 검증했다.
- Graph 모듈은 `record_dataset_readiness`, `activate_dataset`, `active_dataset` 또는 SQL 변경 경로를 두지 않는다. 정적 스캔의 유일한 `INSERT` 문구는 없는 `/update` endpoint가 HTTP 404/405로 거부함을 검증하는 음성 probe이다.
- 관리형 sandbox에서 PostgreSQL shared memory와 임시 loopback port bind는 승인된 로컬 실행을 필요로 했다. 모든 gate는 완료됐고 PostgreSQL 클러스터, Fuseki JVM, TDB2·N-Quads·검증 임시 디렉터리는 종료·삭제했다. 체크섬을 검증한 Jena/Fuseki 외부 binary home은 저장소 밖에만 유지한다.
- 2026-09-04 실제 통합 검증은 64,019개 entity, 78,532개 relation, 81,063개 relation Evidence binding을 두 번 byte-identical Graph로 생성했다. Jena/Fuseki 6.0.0의 읽기 전용 질의·차단 surface와 국내 ETF·공모펀드 Vector→Evidence canary를 통과했고, 임베딩은 40,149개 exact·이상 0건을 유지했다. 전체 회귀는 `2069 passed, 15 skipped`였다.
- 현재 DB에는 organizer 4개 source와 DART filing 2,214개만 있고, 별도 검증된 KRX·ECOS·SEC 정형 source 1,166개 객체는 아직 결합하지 않았다. DB는 `6779 MB`, 로컬 여유 공간은 `8.9 GiB`였으며, 최종 결합 DB는 약 `26–30 GB`로 추정한다. 한 번의 안전한 빌드는 최소 50 GB, 두 번의 재현 빌드와 운영 여유를 포함한 NCP는 100 GB를 유지한다.
- 이 결과는 Stage 04 완료를 의미하지 않는다. 최종 공식 정형 source 결합, component manifest 동일성, readiness·activation, NCP 배포, Graph 경로가 필요한 23개 질문의 dataset-relative 커버리지는 후속 계획과 최종 Stage 작업으로 남아 있다.

기준 계획: [Stage 04 Graph Phase 1](tasks/2026-08-30-stage-04-graph-phase-1-implementation-plan.md)

### Stage 05 Graph·문서 실행과 계산 경계

**상태: Graph·공식 문서 검색 executor와 PostgreSQL SQL 경로 로컬 구현·검증; 계산·유사도 production route는 fail-closed, Stage 05 전체 미완료**

- 승인된 관계만 고정 SPARQL로 조회하는 Graph executor와 상품·문서 유형·컷오프를 제한한 Keyword/Vector 결합 문서 executor를 구현했다. 두 경로 모두 후보 결과만으로는 답변 근거가 되지 않으며, 관계 Evidence ID 또는 승격된 문서 Evidence가 있어야 `ToolResult`를 발행한다.
- 새 executor는 기존 bounded Orchestrator의 `ExecutorRegistry`를 통해 실행되며, 별도 자유 질의나 새 스케줄러를 추가하지 않았다.
- 기존 SQL 의미 경로는 실제 PostgreSQL 15 통합 테스트에서 혼합 qualifier, 배열 binding, metric lineage 타입 문제를 보정했다.
- 현재 V2 계산 피연산자는 권위 있는 typed literal 값을 executor까지 전달하지 않는다. 따라서 일반 계산 evaluator를 추가하지 않았고, 유사도 결과도 승인 정책이 활성화되기 전에는 Verifier가 거부한다. provenance가 완전한 외부 `CalculationRecord`의 변환 등만 Stage 07에서 검증·출력할 수 있다.

기준 설계·계획: [Stage 05–07 Local Vertical Slice](specs/2026-09-04-stage05-stage07-local-vertical-slice-design.md), [Implementation Plan](tasks/2026-09-04-stage05-stage07-local-vertical-slice-plan.md)

### Stage 07 근거 검증·답변 출시 경로

**상태: bounded local vertical slice 구현·검증; 최종 데이터 활성화·52문항·NCP/API acceptance 대기**

- `ToolResult`의 개별 필드를 정확한 Evidence 또는 Calculation과 결합해 `AtomicClaim`, `ClaimSupport`, `EvidenceBundle`을 결정론적으로 생성한다. 검색 결과가 비었을 때 closed-world 범위 근거가 없으면 “없음”이 아니라 제한 답변으로 처리한다.
- Verifier는 계약·해시, 출처 권위, 서울 기준 컷오프, 온톨로지 결합, 계산 지원, coverage 순서로 검사한다. Claim Gate는 서버 등록 template과 검증 통과 Claim만 허용하고, Renderer는 원장 값과 출처 locator만으로 대회 응답 문자열을 만든다.
- 마이그레이션 `0012`는 검증 보고서·승인된 AnswerPlan·ReleasedAnswer가 정확히 일치할 때만 불변 캐시에 저장한다. 저장 payload 위조, 다른 dataset/version 혼합, 미검증 Claim 캐시는 거부한다.
- 이는 로컬 실행 경계의 구현 완료를 뜻하며 Stage 07 전체 완료 선언은 아니다. 최종 활성 데이터셋, 52문항 종합 평가, NCP 권한·성능, 공식 API 검증은 Stage 08~09 입력으로 남는다.

기준 검증: [Stage 05–07 Verification](verification/2026-09-04-stage05-stage07-local-vertical-slice-verification.md)

### Stage 06 Intent Resolver·QueryPlan·Orchestrator

**상태: Phase 1-3 및 SQL 의미 계약 V2→결정론적 RDB 실행·저장 로컬 구현 완료; hybrid V3는 implemented, shadow-only; promotion은 fail-closed deferred**

- 2026-09-03 [ADR-0030](decisions/ADR-0030-use-hybrid-full-catalog-semantic-linking.md)으로 request-local 후보를 HCX의 전체 선택지로 사용하던 경계를 폐기하고, 전체 compact semantic catalog와 의미 중립 mention span을 제공하는 hybrid semantic linking 방향을 승인했다. deterministic candidate는 exact lock 또는 advisory hint로 유지한다. hybrid V3 구현과 로컬 검증은 완료했지만 V2는 계속 기본값이며, 모든 gate 통과와 별도 사용자 승인 전까지 V3는 shadow-only다.
- 2026-09-04 hybrid V3 초기 shadow 검증은 narrow `139 passed`, Intent Resolver·evaluation `806 passed`, Jena 환경 의존 suite를 명시적으로 제외한 broad offline `2419 passed, 13 skipped, 451 deselected`다. 계획의 원래 broad 명령에서는 `RUN_JENA_INTEGRATION != 1`이어서 Jena 전용 13건이 모두 opt-in precondition에서 중단됐다. Jena/Fuseki runtime 변수도 설정되지 않아 실제 binary 존재 여부와 버전은 평가하지 않았다. compileall과 V2/V3 schema freshness도 통과했다.
- 2026-09-04 final-review hardening commit `1dbae14`에서 V3 request별 JSON Schema runtime 검증, authoritative compact-catalog canonical content 비교와 case-normalized physical-token 차단, solver manifest·dataset·catalog pin 검증, 미지원 schema-version 명시적 거부를 추가했다. 최종 회귀는 narrow `166 passed`, Intent Resolver·evaluation·planning `1031 passed`, broad offline `2459 passed, 13 skipped, 451 deselected`이며 compileall과 V1/V2/V3 schema freshness도 통과했다. live HCX는 재호출하지 않았고 V2 default, V3 shadow-only, promotion `deferred` 상태는 유지한다.
- 2026-09-04 [ADR-0031](decisions/ADR-0031-share-korean-nlu-overlay-v4-with-v2.md)로 V2의 요청별 제한 후보·HCX 선택 구조는 유지하되 한국어 오버레이를 V4로 통일했다. V4의 고유 preferred label은 exact lock이 아닌 요청별 advisory 후보로 제공한다. held-out 후보 recall@5는 `123/196`에서 `134/196`으로 올랐지만 `>=99%` gate는 여전히 실패하며, 이 변경은 V3 승격을 의미하지 않는다.
- 승인된 HCX-007 V3 shadow 21-case는 first-pass validity `5/21`, repair validity `0/16`, Action/ProductFamily exact 각각 `3/21`, semantic-link exact `0/5`, complete-contract exact `0/5`, provider success `19/21`이었다. OOD false-fast는 `0/1`이지만 완전 분모가 아니며 PostgreSQL도 미측정이다. offline/live report hash는 각각 `620f1ca0…9353a`, `4796116b…eccc`이고, 실측 결과는 승격 기준에 크게 미달하므로 promotion은 fail-closed `deferred`다.

- 온톨로지 기반 semantic catalog, 한국어 정규화·literal·candidate·bounded view,
  strict HCX adapter, semantic/context validator, one-call service, 불변
  `intent_resolution` 저장, 160-case held-out evaluation과 fail-closed promotion
  판정 경계를 구현했다.
- action별 `ResolvedQueryContractV2`, bounded candidate solver, 별도 contract
  readiness, `LogicalQueryPlanV2`, 폐쇄형 semantic-to-SQL compiler, 읽기 전용
  PostgreSQL runner, 기존 bounded Orchestrator 통합, `query_contract` 및
  `logical_query_plan` 불변 저장을 당시 통합 마이그레이션 head `0011`까지 구현했다. 이 Phase 1~3 범위에는 Graph·Search·Calculation production executor가 포함되지 않았으며, 이후 Stage 05–07 local vertical slice에서 Graph·공식 문서 executor만 추가했다.
- 2026-09-03 최종 V2 검증은 focused `660 passed`, broad offline `2281 passed,
  1 expected skip, 463 deselected`다. 지원 프레임 구조 표현력은 `199/199`,
  미지원 reason coverage는 `10/10`, false-complete는 `0/10`이다. 그러나 계약
  role gold는 194개 필요 분모 중 43개만 측정 가능하고 151개가 불완전하므로,
  measured subset의 recall/exact `43/43`을 승격 근거로 사용하지 않는다.
- 2026-09-01 entity-role final hardening의 fresh intent/evaluation suite는
   `369 passed`; v1·v2 schema freshness check와 v1 no-drift check도 통과했다.
   외부 marker를 제외한 broad offline suite는 `1301 passed, 1 skipped,
   378 deselected`였다. 명시적 PostgreSQL evidence는 이 final fix에서는 실행하지
  않았고, URL 미설정으로 계속 `unmeasured`다.
- resolver view의 exact catalog entity-type registry는 prior fresh `155/155`
  reachability (unreachable case `0`)를 유지한다. 새 결정론적 평가는 candidate
  reproducibility `155/155`, recall@5 `123/196` (`62.76%`)로 승인된 `>=99%`
  gate에 미달한다.
- 승인된 HCX-007 16-case smoke에서 production one-axis provider success는 `16/16`,
  structured/semantic validity `11/16`, action exact `10/16`, family exact `11/16`,
  complete contract `4/16`이지만, action·family와 predicate typed value, COUNT/SUM,
  grouping, ordering, prior-result binding을 함께 고정한 대표 의미 계약은 `0/5`로
  승격 gate에 실패했다. 25개 호출은 primary `16`, repair 시도 `8`, judge `1`이며
  모든 성공·실패 호출을 직접 계측한다. 세 축 병렬 challenger는 48호출 중 성공
  `40`, rate limit `8`, structured `11/16`, action exact `2/16`, family exact
  `6/16`으로 더 낮아 운영
  기본값을 변경하지 않는다. complete-population first-pass/frame/context/OOD
  metric은 여전히 미측정이고 default promotion은 fail-closed/deferred 상태다.
  exact-lock precision·compile success·byte equivalence는 권위 있는 완전 분모가
  정의되지 않아 양의 부분집합 결과와 무관하게 `unmeasured`다. Promotion evidence는
  frozen v3 SHA와 정확히 다섯 prior-failure 계약 SHA `16e3097e…f66f38`,
  action별 supported/unsupported population SHA `b592ab53…140c8` /
  `b3acfa3f…1d323`에 결합된다. role-required frame evidence가 비어 있거나
  부분 denominator/coverage이면 `unmeasured`이며, action 간 분모 이동도
  aggregate 합계가 같더라도 거부한다.
  `model_copy`·`model_construct`로 우회 생성된 기존 증거도 exact type·stored field
  keys·strict JSON 재검증을 통과하지 못하면 판정 전에 예외로 차단한다.
- 이 호스트에는 Docker 계열 runtime이 없어 Linux/amd64 build/run/Compose는
  실행하지 않았다. 이번 검증의 외부 호출은 승인된 HCX smoke뿐이며 NCP 데이터베이스,
  organizer/official source, Object Storage, Jena는 호출하지 않았다.
- Phase 2는 검증된 resolution과 exact ResolverView를 versioned registry에 따라
  `fast`, `compose`, `explore`, `abstain`으로 라우팅하고 기존 QueryPlan 계약으로
  손실 없이 내리는 compiler를 구현했다. 교차 상품군 순위에는 comparability와
  normalization이 순위보다 앞서며, rank/screen/similarity에는 versioned
  coverage·missingness policy ID가 전달된다.
- Phase 3는 QueryPlanCompilation을 ExecutionGraph로 결정론적으로 확장하고,
  typed executor registry, 직접 선행 결과와 context binding 전달, 최대 55초
  deadline, bounded concurrency, 요청 전체 transient retry 2회, 결과 hash·pin·
  evidence 검증, terminal outcome 분류를 구현했다.
- 한 요청 안의 `ETF 상위 5개 → 그 상품 중 수익률 1위`는 첫 결과 binding을
  두 번째 subtask로 전달하며 전체 상품군 조회를 반복하지 않는다.
- 실제 SQL executor는 합성·로컬 경계까지 구현됐지만 승인된 PostgreSQL URL이 없어
  migration/SQL conformance는 `unmeasured`다. `public_fund.fee_rate`와 대표 상품
  grain도 production 정의 검증 전까지 `LIMITED`다. Graph·Keyword·Vector·금융
  계산 production executor와 답변 생성은 후속 범위다. 상세 근거는
  [Semantic Query Verification](verification/2026-09-02-semantic-query-contracts-and-sql-compilation-verification.md)에 있다.
- Task 1 audit-only fixture는 core 52개(`03de130a…3618a2`)와 held-out 160 case의
  action-bearing 209 frame(`bd40481c…f4c7de`)을 SHA-256으로 pin했다. V1
  representability는 94/209로 고정했고, generated requirement snapshot은 52개
  core question과 209개 frame의 semantic requirement 또는 명시적 unsupported
  reason을 담는다. 평가 fixture만 변경했으며 resolver·planner 런타임은 변경하지
  않았다.

기준 보고서: [Hybrid V3 Verification](verification/2026-09-03-hybrid-full-catalog-semantic-linking-verification.md), [Intent Resolver Phase 1 Verification](reports/2026-08-31-intent-resolver-phase1-verification.md), [QueryPlan and Orchestrator Verification](reports/2026-09-02-query-plan-orchestrator-verification.md)

## 3. 현재 실행하면 안 되는 계획

[2026-08-10 Core Implementation Plan](tasks/2026-08-10-financial-agent-core-implementation-plan.md)은 질문·데이터·온톨로지 요구사항의 역사적 출처로만 유지한다. DuckDB, 로컬 인덱스, 옛 ADR 번호, 이전 에이전트 역할을 포함한 실행 순서는 현재 아키텍처와 맞지 않으므로 그대로 구현하지 않는다.

[Multi-Agent Architecture](architecture/MULTI_AGENT_ARCHITECTURE.md)의 Specialist Agent·LLM Verifier 기본 호출 부분은 역사적 설명이다. 현재 런타임은 ADR-0005∼0007과 Runtime Contracts를 따른다.

## 4. 확정된 후속 Stage

[Competition Stage Roadmap](ROADMAP.md)은 대회 제출과 평가 운영 기간 종료를 종점으로 하는 현재 권위 있는 전체 순서를 정의한다.

| Stage | 범위 | 상태 |
| --- | --- | --- |
| 03 | 주최 측·공식 추가 데이터 수집, 표준화, 계보와 컷오프 검증 | current organizer 로컬 결정성 검증 완료; current KRX holdings 로컬 통합과 나머지 공식 source 동결 대기; NCP acceptance는 Stage 08로 이연 |
| 04 | TTL·SHACL, PostgreSQL→Fuseki ABox, Keyword·Vector 투영과 데이터 버전 활성화 | 실제 PostgreSQL·Graph·Vector·Evidence 통합 기반 검증 완료; 최종 공식 정형 source·manifest 동일성·readiness/activation·NCP·23질문 커버리지 대기, Stage 04 미완료 |
| 05 | SQL·Graph·Keyword·Vector 통합 검색과 결정론적 금융 계산·유사도 | SQL PostgreSQL 15 경로와 evidence-bound Graph·공식 문서 hybrid executor 로컬 구현·검증; public-fund 물리 gate는 `LIMITED`, typed 계산 입력·승인 recipe·유사도 정책은 fail-closed로 남아 Stage 05 미완료 |
| 06 | Intent Resolver, RequestContext·QueryPlan·ExecutionGraph, Orchestrator·Capability 실행 | Phase 1~3와 SQL 의미 계약 V2 통합·artifact persistence 로컬 구현 완료; hybrid V3도 구현됐으나 HCX-007 V3 shadow 정확도·provider gate 실패와 미측정 PostgreSQL 때문에 `shadow-only`, production promotion은 `deferred` |
| 07 | Verifier, Claim Gate Registry, Answer Composer, Renderer와 검증된 응답 캐시 | 근거 조립→검증→Claim Gate→결정론적 Renderer→불변 캐시 local vertical slice 구현·검증; 최종 활성 데이터·52문항·NCP/API acceptance 대기 |
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
27. ~~Stage 03B Task 8의 Stage 03A+03B 결합 파이프라인 구현·Linux/amd64·폐기 가능 PostgreSQL 검증~~ — 2026-08-23 완료
28. ~~옛 Stage 03B Task 9 NCP acceptance~~ — 공식 2026-08-24 재배포로 실행 중단; 역사적 산출물만 보존
29. ~~새 8개 workbook 전수 분석과 280필드 매핑·identity·cutoff 보강안 승인~~ — 2026-08-25 완료
30. ~~승인안 기준 DB·온톨로지 rebaseline 상세 구현계획 작성~~ — 2026-08-25 완료
31. ~~Alembic `0006`과 2026-08-24 current cutoff 계약 구현~~ — 2026-08-25 완료
32. ~~organizer identity pre-scan과 네 source mapper 재구현~~ — 2026-08-25 완료
33. ~~공식 외부 source current cutoff 재바인딩 구현~~ — 2026-08-25 완료
34. ~~두 로컬 PostgreSQL에서 current organizer 비활성 결정성 검증~~ — 2026-08-26 완료
35. ~~current KRX ETF holdings 1,161개 exact binding·로컬 비활성 적재·대표 질의 검증~~ — 2026-08-27 완료
36. 나머지 current 공식 외부 source 동결과 Stage 03 로컬 완료 게이트 — [구현 계획](tasks/2026-08-27-stage-03-local-completion-plan.md) 승인, Task 1~6 완료; 52개 질문 커버리지를 `supported` 16, `limited` 18, `requires_additional_data` 11, `unsupported` 7로 동결
37. ~~52개 질문 계약 schema `1.3` 정규화와 온톨로지 논리 보정 승인~~ — 2026-08-30 완료; 지원 상태 수량 유지, 실제 DB 실행은 전건 `not_run`
38. Stage 04 실제 PostgreSQL·Graph·Vector·Evidence 통합 기반 로컬 검증 완료; 최종 공식 정형 source 결합·manifest 동일성·readiness/activation을 완료한 뒤 로컬 평가 API까지 Stage 04~07 순차 구현
39. Stage 08에서 최종 NCP 비활성 적재·Graph/Vector·권한·성능·복구·공개 API acceptance
40. ~~Stage 06 Phase 1 Intent Resolver의 온톨로지 기반 분류·한국어 문맥 해소·OOD·검증·평가 설계 승인~~ — 2026-08-31 완료; 상세 구현 계획과 런타임 변경은 별도 승인 대기
41. ~~Stage 06 Phase 1 Intent Resolver 상세 구현·로컬 비라이브·PostgreSQL 검증~~ — 2026-09-01 완료; Linux/amd64 container 미실행, candidate recall 실패와 live 미측정 gate로 승격 차단
42. ~~Stage 06 Phase 2 QueryPlan compiler·4경로 router와 Phase 3 bounded Orchestrator 로컬 구현·통합 검증~~ — 2026-09-02 완료; production executor와 답변 생성은 포함하지 않음
43. ~~Stage 06 live HCX-007 16-case production/challenger benchmark~~ — 2026-09-03 완료; production provider `16/16`, complete contract `4/16`, representative exact `0/5`, challenger rate limit `8/48`, 승격 보류
44. ~~SQL 의미 계약 V2·결정론적 SQL compiler·RDB executor·artifact persistence 구현~~ — 2026-09-03 로컬 완료; 불완전 gold·PostgreSQL·public-fund physical gate는 보류
45. ~~hybrid full-catalog semantic linking V3 구현·로컬/HCX shadow 검증~~ — 2026-09-04 `implemented, shadow-only`; V2 기본 유지, 낮은 V3 정확도·provider 성공률과 미측정 PostgreSQL 때문에 promotion은 fail-closed `deferred`
46. ~~V2 요청별 제한 후보 구조에 한국어 V4 오버레이 공유~~ — 2026-09-04 로컬 구현·검증, `main` 병합과 GitHub push 완료; V3 promotion 상태는 변경 없음
47. ~~Stage 05 Graph·공식 문서 executor와 Stage 07 근거 검증·답변 출시 local vertical slice 구현~~ — 2026-09-04 로컬 구현·검증; 계산·유사도 production route와 최종 데이터·NCP/API acceptance는 후속 gate로 유지

이 순서를 바꾸거나 상위 아키텍처를 바꾸는 경우 사전 승인과 해당 ADR 또는 설계 문서 갱신이 필요하다.

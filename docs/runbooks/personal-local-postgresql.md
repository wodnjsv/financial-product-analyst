# 개인용 로컬 PostgreSQL

승인: 2026-09-18, ADR-0050. 대회 제출용 활성화와 분리된 로컬 SQL 테스트 구성.

## 적재·검증 결과 (2026-09-18)

- 마스터 원본 53,375행: 국내 채권 21,882, 국내 ETP 1,780,
  해외 ETP 6,037, 공모펀드 23,676. 원본 건수 대조 통과.
- 국내 ETF 50개 / 보유 관계 2,925건, 해외 ETF 50개 / 보유 관계 11,424건.
- DART 문서 100건, 청크와 기존 1,024차원 임베딩 각각 1,552개.
  복원 벡터는 백업과 동일하며 API 호출은 0회.
- 관측값 3,649,906건, 근거 3,782,563건, 전체 관계 92,881건.
  관측값·보유 관계의 근거 누락 및 벡터 검증 오류 0건.
- DB와 인덱스 약 **6.72 GB**, 잔여 디스크 **33.95 GiB**.
  작업 전 저장한 기준 대비 디스크 사용 증가 약 9.79 GB이며, 이 값에는
  작업 중 다른 시스템 활동도 포함된다. 적재용 임시 파일·스키마는 정리했다.
- PostgreSQL 17 스키마·권한 검사와 아래 읽기 전용 조회 예제 모두 통과.

원본 행 수와 정규화된 `catalog.product`의 58,646개 엔터티 수는 서로 다른
지표다. 원본 행 수 검증은 `structured-report.json`의 `source_counts`,
실제 조회 대상 수는 `acceptance.json`의 `family_counts`에서 확인한다.

보고서는 원본 작업 폴더의 `data/personal-local/`에 보관한다.
`structured-report.json`은 문서 복원 전 정형 데이터 보고서이며,
최종 상태는 `document-report.json`과 `acceptance.json`을 함께 확인한다.

## 접속

```bash
psql -h localhost -p 5432 -d financial_agent_local
```

GUI 클라이언트도 Host `localhost`, Port `5432`, Database
`financial_agent_local`을 사용한다. 사용자명은 이 Mac의 PostgreSQL 로그인
사용자를 사용한다. 비밀번호/인증 정책은 기존 서버 설정을 바꾸지 않았다.

프로젝트 루트(이 worktree)에서 다음 예제를 실행한다.

```bash
psql -X -h localhost -d financial_agent_local -f scripts/personal_queries.sql
```

예제는 `fa_runtime` 역할과 읽기 전용 트랜잭션으로 상품명 검색, 상품군별
건수, 구성종목 관계, 관측값의 출처, 문서 키워드 검색, 저장 벡터 간
유사도 검색을 수행한다. 새로운 임베딩 API 호출은 없다.

## 데이터 범위

- 데이터셋 ID: `personal-2026-08-24-v1`.
- 기본 사실은 보존된 2026-08-24 워크북 스냅샷이다. 현재 시세가 아니다.
- 국내 ETF 구성종목 50개와 SEC에 연결된 해외 상품 50개를 식별자 해시
  순으로 선정한다. 선정 상품의 원본 구성종목은 행 단위로 자르지 않는다.
- 공식 문서는 기존 내보내기에서 현재 상품과 연결되는 최대 100건만 이관한다.
- 표본 외 상품의 구성종목·문서 coverage는 미확인이다. 빈 검색 결과로
  보유종목이나 위험이 없다고 결론 내릴 수 없다.
- 원본의 결측·충돌·식별자 제한을 보존했다. KRX 표본 50개와 SEC 표본
  49개는 `PARTIALLY_COVERED`, SEC 1개는 `COVERED`다. 원본 구성종목을
  전부 보존한 것과 모든 구성종목의 공식 식별이 완료된 것은 다르다.
- 문서는 보유종목 표본에 연결된 문서를 우선한 뒤 문서 ID 순으로 골랐다.
  오래된 투자설명서도 포함되므로 최신 상품 설명으로 일반화하지 않는다.
- `building`은 전체 대회 Graph/Vector release gate를 통과한 버전이
  아니라는 뜻이다. 로컬에서는 위 ID로 직접 조회하며 active 포인터는 만들지 않는다.
- 자연어 질의에 대한 API나 LLM 정확도 개선은 이번 적재 범위가 아니다.

## 재현과 용량

`.venv`는 Python 3.12 환경이다. `FINANCIAL_AGENT_LOCAL_DEVELOPMENT=1`은
loopback의 `financial_agent_local` 또는 `financial_agent_local_test`에서만
허용된다. PostgreSQL 17에서 통계 확장 shared preload를 강제하지 않지만
pgvector, 테이블/함수/권한 검증은 유지한다.

새 환경을 만들 때는 `requirements/personal-local.lock`의 검증된 패키지를
설치한 다음 프로젝트를 editable 설치한다. **DB가 아직 없을 때만** 다음
초기화를 수행한다. 기존 DB를 삭제하는 명령은 포함하지 않는다.

```bash
createdb -h localhost financial_agent_local
psql -X -h localhost -d financial_agent_local -v ON_ERROR_STOP=1 -f docker/initdb/001-ncp-extension-layout.sql
FINANCIAL_AGENT_LOCAL_DEVELOPMENT=1 FINANCIAL_AGENT_DATABASE_URL=postgresql://localhost/financial_agent_local .venv/bin/python -m alembic upgrade head
```

원본이 들어 있는 상위 작업 폴더를 인자로 준다.

```bash
.venv/bin/python scripts/build_personal_dataset.py --workspace-root /path/to/original-workspace
.venv/bin/python scripts/restore_personal_documents.py --workspace-root /path/to/original-workspace
.venv/bin/python scripts/verify_personal_dataset.py --workspace-root /path/to/original-workspace
```

빌드 manifest, 원본 체크섬, 표본 목록과 결과는 상위 작업 폴더의
`data/personal-local/`에 저장한다. 같은 manifest의 부분 적재는 기존 writer의
값 비교와 멱등성 검사를 통해 재개한다. 다른 데이터셋을 덮어쓰지 않는다.
문서 복원은 임시 unlogged schema에서 이관 후 임시 schema를 제거한다.

DB+인덱스 목표 상한 18 GB, 전체 추가 사용량 30 GB, 최소 잔여 10 GiB를
적재 배치 사이에서 검사하며 다음 배치를 위해 2 GB 여유를 남긴다.
이는 PostgreSQL 서버 자체의 디스크 quota가 아니므로 수동 SQL이나 다른
프로세스가 쓰는 공간까지 물리적으로 제한하지는 않는다.

NCP, 전체 Fuseki/RDF 복제, 재임베딩, 기존 다른 DB 변경은 수행하지 않는다.

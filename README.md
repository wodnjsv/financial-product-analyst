# Financial Product Agent

국내 채권·국내 ETF·해외 ETF·공모펀드 데이터를 조회하고, 결과의 값·기준일·출처·원문을 함께 확인하는 금융상품 분석 프로젝트입니다. 필터링·정렬·계산과 사실 출력은 서버가 수행하고, 모델이 임의의 수치나 근거를 작성하지 않도록 설계했습니다.

대회 종료 후에는 **개인용 로컬 PostgreSQL 검색·검증**을 중심으로 개발하고 있습니다. 전체 데이터를 다시 적재하는 대신, 추가 디스크 사용량 30 GB 이내에서 구성종목과 문서를 표본으로 보존합니다. 데이터는 과거 스냅샷이며 현재 시세나 투자 권고가 아닙니다.

## 현재 사용할 수 있는 범위

| 구분 | 구현·검증 상태 |
| --- | --- |
| 개인용 DB | PostgreSQL 17의 별도 `financial_agent_local`, 데이터셋 `personal-2026-08-24-v1` |
| 상품·관측·근거 | 네 상품군 마스터, 버전별 상품 식별자·관계·관측값·원본 근거 적재 |
| 구성종목 | 국내 ETF 50개와 해외 ETF 50개의 선택된 원본 구성종목 보존 |
| 문서 | DART 문서 100건, 청크와 기존 1,024차원 임베딩 복원 |
| 개인용 검색 | 수익률 순위·정확 종목명 보유 ETF 조회·위험 문서 키워드 조회의 세 계획을 CLI로 실행 |
| 출력·검증 | 검색 일치/표시 건수, 누락 상태, 출처와 전체 조회 발췌를 서버에서 출력·검증 |
| 별도 비중 | 다섯 운용사에서 확인한 삼성전자 보통주 비중 9건을 원본 KRX 값과 분리하여 적재 |
| NVIDIA 의도 분석 | `z-ai/glm-5.3-flash` adapter와 자연어 CLI 구현. 기존 V3 의미 계약·검증·라우팅 사용 |
| 자연어 실행 범위 | 상품군·엔터티·조건·기간·계획을 JSON으로 출력. 상품 조회 실행과 HTTP API는 별도 연결 필요 |

`search_personal_dataset.py`는 사용자가 지정한 `plan`, `keyword`, `limit`로 실제 검색합니다. 새 `resolve_personal_intent.py`는 NVIDIA로 자연어를 분석하고 기존 컴파일러로 라우팅·실행 가능성을 검사합니다. 두 CLI는 아직 자동 연결되지 않았으며, 의도 분석 출력의 `execution_performed`는 항상 `false`입니다.

## 실행 흐름

현재 제공되는 로컬 경로는 다음과 같습니다.

```text
등록된 조회 계획 + 검색어 + 개수
  → 계획·검색어·개수 검증
  → fa_runtime / 읽기 전용 PostgreSQL 조회
  → 원본 근거·관계 근거·선택적 운용사 보조 비중 조회
  → 문서 청크 해시 확인 및 발췌
  → 서버가 값·날짜·출처·건수·원문 출력
  → 출력 계약 및 원문 일치 검증
```

새 의도 분석 경로는 다음과 같습니다.

```text
자연어 질문 + 실제 데이터셋 pin
  → 읽기 전용 DB에서 이름·별칭·식별자와 원문 위치 탐색
  → 의미 목록·상품 후보·명시적 상품군 잠금 구성
  → NVIDIA가 등록된 ID로 의미·엔터티 역할 제안
  → JSON 스키마·근거 ID·상품군 잠금·질의 계약 검증
  → 결정론적 계획 컴파일 및 fast / compose / explore / abstain 판정
  → 해석·후보 계약·승인된 계획·제한 사유 JSON 출력
```

모델이 SQL을 작성하거나 비중·수익률을 계산하지 않습니다. 검색 CLI의 문서 계약은 `{"citations": ["D1", "D2", "D3"]}`처럼 조회된 문서 ID만 허용합니다. CLI는 조회 ID를 직접 사용하므로 모델 호출 없이 서버 출력 경로를 실행합니다.

## 프로젝트 구조

대회 개발 중 구축한 전체 기반과 현재 개인용 경로를 함께 보존합니다. 아래 모듈의 존재가 모든 경로의 운영 서비스 통합 완료를 의미하지는 않습니다.

| 경로 | 역할 |
| --- | --- |
| `src/financial_agent/contracts/` | Pydantic 런타임 계약, 타입·버전·JSON 경계 |
| `src/financial_agent/db/`, `alembic/` | PostgreSQL 스키마, 마이그레이션, 최소 권한, 불변 원장·요청 산출물 저장 |
| `src/financial_agent/ingestion/` | 주최 측 마스터·공식 소스 정규화, 식별자 연결, 누락·출처 보존, 로컬 용량 검사 |
| `src/financial_agent/documents/`, `embeddings/` | PDF 추출·문서 구역·청크·원문 해시·임베딩 계약 및 저장 |
| `src/financial_agent/intent/` | NVIDIA adapter·원문 엔터티 탐색·기존 V3 의미 해소·검증·개인용 라우팅. HCX adapter는 과거 검증용으로 보존 |
| `src/financial_agent/planning/`, `orchestration/` | 타입이 정해진 계획·실행 그래프, 조건부 라우팅, 제한된 동시 실행·재시도 |
| `src/financial_agent/sql/`, `graph/`, `retrieval/` | 결정론적 SQL 컴파일·조회, RDF/SHACL·Graph 투영, 문서 검색과 근거 연결 |
| `src/financial_agent/release/` | 근거 검증·Claim Gate·Renderer·검증 응답 캐시와 개인용 출력 계약 |
| `scripts/` | 개인용 적재·복원·검색·자연어 의도 분석·감사·재검증 CLI |
| `schemas/`, `ontology/`, `tests/` | 계약 산출물, 온톨로지, 합성 데이터 기반 회귀·선택적 통합 검사 |
| `docs/planning/`, `docs/runbooks/` | 승인된 설계·결정·작업 계획·검증 이력·운영 방법 |

전체 기반은 PostgreSQL을 기준 근거 원장으로 두고 Graph·Keyword·Vector 검색 결과를 검증 가능한 근거에 연결한 뒤 Claim과 정해진 레이아웃으로 출력하는 구조입니다. 개인용 세 계획은 이와 구분되는 제한된 로컬 실행 경로이며, 전체 운영 Evidence 출시 게이트를 통과했다고 주장하지 않습니다. 기존 대회 HCX 의존 경로는 현재 개인 사용 방법에 포함하지 않습니다.

## 데이터 범위와 용량

2026-09-18 적재·검증 이력 기준입니다. 설치 환경이나 이후 작업에 따른 현재 DB 크기·디스크 여유는 별도로 확인해야 합니다.

| 항목 | 적재 이력 |
| --- | ---: |
| 마스터 원본 행 | 53,375 |
| 국내 채권 / 국내 ETP | 21,882 / 1,780 |
| 해외 ETP / 공모펀드 | 6,037 / 23,676 |
| 국내 ETF 구성종목 관계 | 50개 상품 / 2,925건 |
| 해외 ETF 구성종목 관계 | 50개 상품 / 11,424건 |
| DART 문서 / 청크·임베딩 | 100건 / 각각 1,552개 |
| 관측값 / 근거 | 3,649,906 / 3,782,563건 |
| DB·인덱스 | 약 6.72 GB |

마스터 원본 행 수는 정규화된 상품 엔터티 수와 다릅니다. 국내·해외 구성종목은 식별자 해시 기준으로 상품을 선정하고, 선택된 원본의 행을 임의로 잘라내지 않습니다. 표본 밖의 보유종목·문서 coverage는 미확인입니다. 조회 결과가 없다고 전체 시장에 해당 상품·보유종목·위험이 없다는 뜻은 아닙니다.

용량 기준은 **DB·인덱스 초기 목표 상한 18 GB, 전체 추가 디스크 사용량 30 GB 이내, 최소 잔여 10 GiB**입니다. 적재 배치 사이에 다음 배치를 위한 2 GB 여유까지 검사합니다. 30 GB를 채우는 것이 목표는 아니며, 이 검사는 PostgreSQL 서버의 물리 quota가 아닙니다. 다른 프로세스나 수동 SQL의 디스크 사용은 따로 관리해야 합니다.

데이터셋은 `building` 상태와 명시적 ID로 조회합니다. 대회용 active 포인터를 만들거나 전체 RDF/Fuseki 복제·재임베딩을 요구하지 않습니다.

## 설치

필요한 환경은 Python **3.12**, PostgreSQL **17**, `psql`·`createdb`, PostgreSQL용 `pgvector`와 프로젝트 초기화 SQL에 쓰이는 확장입니다. 확장 설치·역할 생성 권한이 있는 로컬 DB 관리 계정이 필요하며, 실행 계정은 `fa_migration`, `fa_build`, `fa_runtime` 역할을 사용할 수 있어야 합니다.

저장소 루트에서 실행합니다.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements/personal-local.lock
.venv/bin/python -m pip install --no-deps -e .
```

`requirements/personal-local.lock`은 2026-09-18 개인용 환경에서 검증한 패키지 버전입니다. 검색·문서 복원에는 LLM API 키가 필요하지 않습니다. 자연어 의도 분석에는 NVIDIA API 키가 필요합니다.

## 로컬 DB 재현

**Git clone만으로 원본 데이터와 DB는 복원되지 않습니다.** 원본 워크북·공식 캡처·DART 내보내기는 Git에 포함하지 않습니다. 적재 스크립트는 새로 전체 데이터를 수집하는 도구가 아니라, 보존한 자료를 검사하여 제한된 DB를 만드는 도구입니다.

`--workspace-root`에 전달할 원본 작업 폴더에는 다음 자료가 필요합니다.

- 네 상품군의 data/schema 워크북 8개가 있는 하위 폴더. 빌더는 `prbd01n001_data.xlsx`가 있는 폴더가 정확히 하나인지 확인합니다.
- `data/generated/stage03b/`의 `current-krx-holdings-capture`, `current-krx-identity-capture`, `current-ecos-capture`, `current-sec-capture` 디렉터리와 각 `manifests/`, `objects/`.
- `data/generated/local-postgres/dart-source-export/`의 기존 문서·청크·임베딩 등 binary 내보내기 파일. 문서 복원은 이 파일의 체크섬과 저장 벡터를 검사하며 새 임베딩 API를 호출하지 않습니다.

원본이 없는 경우 아래 적재는 실패합니다. 자료를 별도로 확보해야 하며, 빈 값이나 합성 데이터로 실제 상품 사실을 대신 생성하지 않습니다.

**DB가 아직 없을 때만** 초기화를 실행합니다. 기존 DB를 삭제하는 명령은 포함하지 않습니다.

```sh
createdb -h localhost financial_agent_local
psql -X -h localhost -d financial_agent_local -v ON_ERROR_STOP=1 \
  -f docker/initdb/001-ncp-extension-layout.sql
FINANCIAL_AGENT_LOCAL_DEVELOPMENT=1 \
FINANCIAL_AGENT_DATABASE_URL=postgresql://localhost/financial_agent_local \
  .venv/bin/python -m alembic upgrade head
```

로컬 개발 프로필은 loopback의 `financial_agent_local` 또는 `financial_agent_local_test`에서만 허용됩니다. PostgreSQL 17에서는 서버 재시작이 필요한 통계 확장 shared preload를 마이그레이션 전제조건으로 강제하지 않으며, pgvector·스키마·권한 검사 등은 유지합니다. 인증은 기존 로컬 서버 정책을 사용합니다.

원본 경로를 실제 경로로 바꾼 뒤 순서대로 실행합니다.

```sh
.venv/bin/python scripts/build_personal_dataset.py --workspace-root /path/to/original-workspace
.venv/bin/python scripts/restore_personal_documents.py --workspace-root /path/to/original-workspace
.venv/bin/python scripts/verify_personal_dataset.py --workspace-root /path/to/original-workspace
```

manifest·체크섬·표본 목록·용량 기준·검증 결과는 원본 작업 폴더의 `data/personal-local/`에 저장합니다. 같은 manifest의 부분 적재는 기존 값 비교와 멱등성 검사를 거쳐 재개하며, 다른 데이터셋을 덮어쓰지 않습니다. 상세 절차는 [개인용 PostgreSQL runbook](docs/runbooks/personal-local-postgresql.md)을 따릅니다.

## 세 검색 예제

```sh
# TIGER를 이름에 포함한 국내 ETF: 2026-08-21 기준 1년 누적수익률 상위 5개
.venv/bin/python scripts/search_personal_dataset.py --plan rank_return --keyword TIGER --limit 5

# 구성종목을 적재한 국내 ETF 중 삼성전자 보통주를 보유한 상품 최대 5개
.venv/bin/python scripts/search_personal_dataset.py --plan holding_weight --keyword 삼성전자보통주 --limit 5

# 위험 구역에서 환율을 언급한 문서 최대 3개
.venv/bin/python scripts/search_personal_dataset.py --plan document_risk --keyword 환율 --limit 3
```

`rank_return`은 상품명 포함 검색 후 저장된 1년 수익률을 내림차순 정렬합니다. `holding_weight`는 공백을 제외한 정확 보유종목명으로 검색합니다. 원본 비중이 누락되어 전체 순위를 확정할 수 없으면 순위 불가를 명시하고, 누락을 0%로 바꾸지 않습니다. `document_risk`는 100개 표본 문서의 `risk_factor` 청크에서 키워드를 찾고, 문서별 첫 일치 청크를 공시일 내림차순으로 반환합니다. 이 CLI의 문서 경로는 벡터 검색을 수행하지 않습니다.

검색어는 1~40자이며 `%`, `_`, `\`를 허용하지 않습니다. 반환 개수는 SQL 계획에서 1~5개, 문서 계획에서 1~3개입니다. CLI는 `localhost/financial_agent_local`과 위 데이터셋 ID에 고정되어 있습니다.

2026-10-02 수정 후 실DB 검증에서는 세 예제의 일치/표시 건수가 각각 **210/5, 9/5, 58/3**이었습니다. 이는 저장된 표본의 검증 이력으로, 새로운 수집이나 다른 데이터셋의 결과를 보장하지 않습니다.

## NVIDIA 자연어 의도 분석

키는 환경의 `NVIDIA_API_KEY` 또는 명시한 로컬 `api.txt`의 `Nvidia API = 값`에서 읽습니다. 파일은 Git에 포함하지 않습니다. 모델은 `FINANCIAL_AGENT_INTENT_MODEL_ID`로 변경할 수 있으며 기본값은 `z-ai/glm-5.3-flash`입니다.

```sh
.venv/bin/python scripts/resolve_personal_intent.py \
  --question '국내 ETF 중 총보수가 0.1% 이하인 상품을 보수가 낮은 순으로 5개 보여줘' \
  --api-key-file /path/to/original-workspace/api.txt
```

이 호출은 질문, 등록된 의미 목록, DB에서 매칭한 후보의 이름·타입·상품군·내부 ID를 NVIDIA로 전송합니다. 원본 워크북·문서 본문·상품 관측값 전체를 전송하는 경로는 아닙니다. 모델의 숨겨진 추론과 키는 출력하지 않습니다.

`interpreted_product_families`는 검증된 해석, `target_product_families`와 `selected_contract`는 컴파일된 계획의 범위입니다. `discovered_entities`, `frames`, `issue_codes`, `route`, `disposition`, `logical_query_plan`으로 해석과 제한을 확인할 수 있습니다. 상품군 오변경·불완전한 기간·엔터티 미해소는 승인된 조회 계획으로 진행하지 않습니다. 물리 매핑이 없는 지표와 아직 내릴 수 없는 관계 조건은 제한 사유를 출력합니다. `explore` 판정이 추가 탐색 실행을 뜻하지는 않습니다.

개선 사항과 지원 경계는 [NVIDIA 의도 분석 runbook](docs/runbooks/personal-nvidia-intent.md)에 있습니다. 메타데이터 전송 승인 후 정식 V3 경로에서 여섯 질문의 실제 NVIDIA 응답을 검증했습니다. 모델 호출은 각각 1회였고, 조건·상품군·기간·정렬·건수·상품 ID와 제한 판정이 일치했습니다. 이 검증에서 상품 SQL은 실행하지 않았습니다.

## 답변·누락·출처 정책

- 수치·기준일·원본 파일·시트·행·열과 관계 근거는 조회 결과에서 서버가 출력합니다. 검색 일치 건수와 실제 표시 건수를 구분합니다.
- 원본의 `present`, `zero`, `unknown`과 누락 이유를 보존합니다. 수량이나 평가금액으로 누락 비중을 임의 계산하지 않습니다.
- 문서 ID는 조회된 ID를 모두 정확히 한 번씩 선택해야 합니다. 모델이 쓴 요약·인용문·구간·위치와 미등록·중복·누락 ID는 거부합니다.
- 서버는 조회 시 만든 발췌 **전체**를 그대로 출력합니다. 원문 속 `[D9]` 같은 문자열은 애플리케이션 출처 번호로 취급하지 않습니다. 바뀌거나 자유롭게 작성된 최종 문서 본문은 거부합니다.
- 문서의 공시·첨부 링크, 구역, 저장 청크 페이지 범위를 표시합니다. 발췌와의 일치를 검증한 것이며, 정확한 인용 페이지·PDF 추출 품질·문서 전체 문맥까지 검증한 것은 아닙니다.
- 과거 자유 요약 답변은 현재 계약에서 실패한 상태로 보존합니다. 명시적 재생성 결과는 별도 파생 결과로 기록하며 원래 실패를 성공으로 바꾸지 않습니다.

## 별도 운용사 비중

운용사 보조 비중은 `personal_local.holding_weight_supplement`에 저장하는 선택적 로컬 자료입니다. KRX 원본 관측값·기본 manifest·운영 출시 원장과 분리합니다. 삼성 3건, TIGER 3건, PLUS·HANARO·WON 각 1건으로 삼성전자 보통주 보유 ETF 9개를 보완했습니다.

요청 기준일은 2026-08-22이고 실제 보조 자료 기준일은 **2026-08-21**입니다. 삼성 비중은 현금성 자산·예금을 제외한 기준이며 다른 운용사의 현금 포함 분모는 확인되지 않았습니다. 운용사별 지표를 유지하고 **보조 비중을 KRX 값에 합치거나 서로 다른 기준으로 순위를 만들지 않습니다.** 9건이 모두 있어도 비교 가능성이 입증된 것은 아닙니다.

아래 명령은 공개 공식 엔드포인트를 호출하고 자료를 보관·적재합니다. 이미 적재한 DB를 검색하는 데 다시 실행할 필요는 없습니다. 지원 범위는 코드에서 검증한 상품·과거 날짜로 제한됩니다.

```sh
.venv/bin/python scripts/import_personal_manager_weights.py --publisher samsung --workspace-root /path/to/original-workspace
.venv/bin/python scripts/import_personal_manager_weights.py --publisher tiger --workspace-root /path/to/original-workspace
.venv/bin/python scripts/import_personal_manager_weights.py --publisher plus --workspace-root /path/to/original-workspace
.venv/bin/python scripts/import_personal_manager_weights.py --publisher hanaro --workspace-root /path/to/original-workspace
.venv/bin/python scripts/import_personal_manager_weights.py --publisher won --workspace-root /path/to/original-workspace
```

상품·종목·실제 날짜·비중·출처 체크섬과 위치를 검사하고, 동일 재적재는 중복을 만들지 않으며 충돌 값은 트랜잭션을 중단합니다. 런타임에는 조회 권한만 제공합니다. 상세 검증 기준은 [검색·보조 비중 runbook](docs/runbooks/personal-local-search.md)과 [ADR-0051](docs/planning/decisions/ADR-0051-local-manager-weight-supplements.md)에 있습니다.

## 검증

외부 API·DB·원본 없이 실행하는 관련 회귀 검사:

```sh
.venv/bin/python -m pytest tests/retrieval/test_personal_search.py tests/release \
  tests/contracts/test_answer.py tests/ingestion/test_manager_weights.py \
  tests/ingestion/test_personal_holdings_audit.py tests/ingestion/test_krx_holdings.py -q
```

전체 offline 검사:

```sh
.venv/bin/python -m pytest -q \
  -m 'not postgres and not ncp_integration and not performance and not object_storage and not official_data and not jena_integration and not clova_integration'
```

별도 원본·DB가 준비된 경우 원본 KRX 보존 감사와 읽기 전용 조회 예제:

```sh
.venv/bin/python scripts/audit_personal_holdings.py --workspace-root /path/to/original-workspace
psql -X -h localhost -d financial_agent_local -f scripts/personal_queries.sql
```

2026-10-02 수정 검증 이력은 관련 검사 **186 passed**, 전체 offline **3,192 passed, 4 skipped, 516 deselected**입니다. 건너뛰거나 제외한 외부 통합·성능 검사는 통과했다고 취급하지 않습니다. 실DB에서는 세 검색·빈 결과·개수 제한·우선주 조건, 원문 인용 3/3과 운용사 원본/상품 식별 자료 체크섬 18/18을 확인했습니다. 원본 KRX 감사는 불일치 0건이었습니다. NVIDIA 임시 harness의 질문 분석 3회와 문서 ID 선택 1회도 HTTP 200과 출력 계약을 확인했습니다.

검증 이력과 수정 근거는 [검색 수정 기록](docs/planning/tasks/2026-10-02-local-search-grounding-fixes.md)과 [NVIDIA 의도 분석 작업 기록](docs/planning/tasks/2026-10-02-nvidia-intent-routing.md)을 참조합니다. 생성한 실제 데이터 로그는 저장소에서 제외합니다.

읽기 전용 DB에서 상품·종목·운용사 타입과 반복된 이름 위치를 확인했습니다. 정식 V3 경로의 실제 NVIDIA 검증은 **6/6**이며, 마지막 실행에서 각 질문의 전체 처리 시간은 **22.2~36.7초**였습니다. 초기 스키마 오류와 시간 초과는 작업 기록에 보존하고, 필수 구간 ID·의미 ID 역할 지침과 중복 스키마 안내를 보완한 뒤 재검증했습니다. 제공된 여섯 예제의 성공이 모든 질문이나 이후 API 응답 시간을 보장하지는 않습니다.

이후 수정까지 포함한 최종 offline 결과는 **3,365 passed, 4 skipped, 516 deselected**입니다. 제외한 외부 통합·성능 검사를 통과로 취급하지 않습니다.

## 남은 작업

- 지원이 확인된 자연어 계획을 실제 조회·출력 경로와 연결하기.
- 관계 조건을 타입에 맞게 컴파일하고, 미등록 지표의 물리 매핑을 보완하기. 일반 자연어 HTTP API는 별도 작업입니다.
- 현재 세 계획 밖의 상품군·조건·비교·금융 계산·유사도 경로를 승인된 정책과 실제 데이터로 연결하기.
- 표본 밖 coverage와 추가 공식 데이터의 출처·날짜·비교 가능성을 확인하기.
- 개인용 검색을 전체 Evidence/Claim 출시 경로와 연결하려면 해당 근거 게이트를 별도로 검증하기.
- 자유로운 문서 요약을 다시 제공하려면 원문 충실성을 넘어 주장 내용의 근거를 검증하는 별도 설계가 필요합니다. 현재는 원문 근거만 출력합니다.

전체 서비스 배포·대회용 공개 API·NCP 운영 acceptance는 완료되지 않았습니다. 로컬 DB와 세 검색·출력·검증 경로, 새 자연어 분석·라우팅의 여섯 예제는 검증했습니다. 두 경로를 하나의 자연어 조회·답변 서비스로 연결하는 작업은 남아 있습니다.

## 데이터와 보안

원본 워크북·대회 PDF·DB·Parquet·벡터·모델 캐시·실행 로그·API 키·`.env`·`api.txt`·계정 식별 설정은 커밋하지 않습니다. `data/`는 전체 제외하며, 저장소에는 재현용 코드·스키마·합성 테스트·승인된 문서만 포함합니다. NVIDIA adapter는 키와 숨겨진 모델 추론을 실행 로그에 남기지 않습니다.

## 설계·사용 문서

- [개인용 PostgreSQL 설치·재현](docs/runbooks/personal-local-postgresql.md)
- [개인용 검색·원문 출력·운용사 비중](docs/runbooks/personal-local-search.md)
- [NVIDIA 자연어 의도 분석·라우팅](docs/runbooks/personal-nvidia-intent.md)
- [현재 및 과거 구현 현황](docs/planning/STATUS.md)
- [계획·구현 기준](docs/planning/HARNESS.md)
- [개인용 표본·용량 결정: ADR-0050](docs/planning/decisions/ADR-0050-personal-local-subset.md)
- [원본 기반 문서 답변 결정: ADR-0052](docs/planning/decisions/ADR-0052-source-owned-local-document-answers.md)
- [NVIDIA 의도 분석 결정: ADR-0053](docs/planning/decisions/ADR-0053-nvidia-personal-intent-routing.md)
- [전체 근거·검증·응답 구조](docs/planning/architecture/EVIDENCE_VERIFICATION_AND_RENDERING.md)
- [온톨로지 구조](docs/planning/architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md)

대회 관련 계획은 과거 설계·검증 기록입니다. 현재 개인용 범위는 최신 사용자 승인과 ADR-0050~0053을 따릅니다.

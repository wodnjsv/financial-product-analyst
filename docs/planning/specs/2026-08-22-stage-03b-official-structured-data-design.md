# Stage 03B 공식 외부 정형 데이터 설계

**Date:** 2026-08-22

**Status:** Approved design

**Cutoff:** 2026-07-11

**Scope:** ETF 구성종목·공식 식별자·국내 ETF 동일일 가격/NAV·ECOS 환율의 수집, 표준화, 커버리지와 Evidence 검증

**Related:** [Stage 03 Lean Data Ingestion Design](2026-08-20-stage-03-lean-data-ingestion-design.md), [Official API Source Matrix](official-api-source-matrix.md), [Authoritative Data Requirements](authoritative-data-requirements.md), [ADR-0014](../decisions/ADR-0014-use-bounded-official-source-snapshots.md)

## 1. 목적과 결정 요약

Stage 03B는 API 수를 늘리거나 범용 금융 데이터 플랫폼을 만드는 단계가 아니다. 52개 평가 질문에서 실제로 확인된 공백을 `2026-07-11` 당시 이용 가능했던 공식 정형 데이터로 보완하는 단계다.

첫 구현 범위와 순서는 다음과 같다.

1. 상품·증권·기업·운용사의 공식 식별자와 별칭
2. 국내 ETF 구성종목·편입비중과 같은 기준일의 KRX 가격·NAV
3. ECOS `731Y001`의 교차통화 비교용 공식 환율
4. SEC N-PORT와 승인된 운용사 공식 자료로 확보 가능한 해외 ETF 구성종목
5. 예상 질문 기반 통합 검증과 커버리지 보고

공식 원본은 NCP Private Object Storage에 불변 보존한다. 정규화 결과는 폐기 가능한 PostgreSQL `building` 버전에서 검증하며, 최종 NCP PostgreSQL 데이터셋은 Stage 03C에서 주최 측·외부 정형 데이터·공식 문서 manifest를 모두 동결한 뒤 처음부터 재현한다.

## 2. 범위와 비범위

### 2.1 이번 범위

| 데이터 | 승인된 1차 원천 | 목표 |
| --- | --- | --- |
| 국내 ETF·주식·지수 식별자 | KRX 공식 정보 | 주최 측 상품과 구성증권의 안정적 ID 연결 |
| 국내 ETF 가격·NAV | KRX ETF 일별매매정보 | 호환 가능한 동일 기준일 가격·NAV 확보 |
| 국내 ETF 구성종목·편입비중 | KRX 공식 파일 또는 운용사 공식 파일 | 공식 적격 스냅샷이 있는 국내 ETF의 최대 전수 연결 |
| KRW 환산 환율 | ECOS `731Y001` | USD, 100 JPY, EUR, CNY의 승인된 원화 환율 |
| 해외 ETF 구성종목 | SEC N-PORT 또는 승인된 운용사 공식 파일 | 공식적으로 확보 가능한 범위의 보유종목 연결 |
| 기업·기관 식별자 | 거래소·규제기관·공식 등록기관 | 이름만으로 합치지 않는 기업·운용사 해소 |

### 2.2 이번 비범위

- FRED 거시 시계열과 개별 ETF 사실
- 일반 뉴스, 검색 결과 요약, 비공식 집계 사이트
- 공식 문서 parsing·chunking과 위험요인 추출
- 기업 지배·상장 관계와 테마 이력의 본 수집; 식별 기반만 준비하고 별도 소스 승인을 거친다
- 모든 해외 ETF에 대한 구성종목 전수 보장
- 수익률·환율 환산·순위·유사도 계산 실행
- Graph·Keyword·Vector 투영과 데이터셋 활성화
- 최종 NCP PostgreSQL 데이터셋의 부분 변경
- Alembic `0006` 또는 새 물리 테이블

## 3. 커버리지 정책

### 3.1 국내와 해외의 비대칭 목표

- 국내 ETF는 주최 측 국내 ETF 모집단을 기준으로 적격 공식 구성종목 스냅샷을 최대한 전수 연결한다.
- 해외 ETF는 SEC N-PORT 등 대량 수집 가능한 공식 신고자료와 승인된 운용사 공식 파일로 확보된 범위만 지원한다.
- 해외 ETF의 미확보 상태를 구성종목 부재로 해석하지 않는다.
- 공식 범위 밖의 상품을 포함해 “이 조건을 만족하는 해외 ETF는 이것이 전부”라는 폐쇄세계 Claim을 만들지 않는다.

### 3.2 커버리지 상태

BuildReport는 상품·소스별로 다음 상태를 집계한다.

| 상태 | 의미 | Evidence 범위 |
| --- | --- | --- |
| `COVERED` | 공식 게시자가 선언한 전체 보유내역을 적격 스냅샷으로 확보하고 모든 필수 행을 해소 | `closed_world` 가능 |
| `PARTIALLY_COVERED` | 상위 종목만 공개됐거나 일부 증권 ID가 미해소 | `bounded_unknown` |
| `NOT_COVERED` | 컷오프를 만족하는 공식 스냅샷을 확보하지 못함 | `bounded_unknown` |
| `CONFLICT` | 같은 사실에 해결되지 않은 공식 출처 충돌이 있음 | 해당 값 출시 제한 |

`COVERED`는 행 수가 많다는 뜻이 아니라 게시자가 정의한 스냅샷 모집단이 완결됐고 파싱·식별·컷오프 검증을 모두 통과했다는 뜻이다.

## 4. 컷오프와 스냅샷 선택

### 4.1 공통 적격 조건

사용 가능한 사실은 가능한 범위에서 다음을 모두 만족해야 한다.

```text
applicable_date <= 2026-07-11
published_at <= 2026-07-11
available_at <= 2026-07-11
vintage_date <= 2026-07-11  # 원천이 빈티지를 제공하는 경우
```

수집 실행일이 컷오프 이후인 것은 허용하지만, 실행일을 공식 공개일이나 이용 가능일로 대체하지 않는다. 공개·이용 가능 시점을 공식적으로 검증할 수 없는 자료는 제한 상태로 보존하며 엄격한 과거시점 Claim에 사용하지 않는다.

### 4.2 최신 적격값 선택

- 일별 가격·NAV·환율은 컷오프 당일 적격값이 없으면 컷오프 이전 최신 공식 관측값을 사용한다.
- `2026-07-11`은 토요일이므로 국내 일별 시장 데이터는 일반적으로 `2026-07-10` 값이 선택되지만, 실제 관측일을 바꾸어 표시하지 않는다.
- 구성종목은 `applicable_date`만 오래됐다고 배제하지 않고 `published_at`과 `available_at`까지 함께 검사한다.
- SEC N-PORT의 보유기준일이 컷오프 이전이어도 신고·공개가 컷오프 이후라면 사용하지 않는다.
- 가격과 NAV를 함께 계산할 때는 같은 상품, 같은 통화, 같은 기준일과 호환 가능한 정의를 요구한다.

최종 답변과 Evidence에는 실제 관측일, 공개일, 출처와 적용된 fallback을 표시한다.

## 5. 지표별 출처 권위와 충돌

모든 사실에 하나의 전역 출처 순위를 적용하지 않는다. 사실을 직접 관리하는 기관을 지표별 권위로 지정한다.

| 사실 | 우선 출처 | 보완 출처 |
| --- | --- | --- |
| 주최 측 제공 필드 | 주최 측 원본 | 외부 원천은 검증·보완만 수행 |
| 국내 ETF 가격·NAV·상장정보 | KRX | 운용사 공식 자료는 원천 공백 설명에 사용 |
| 국내 ETF 구성종목 | KRX 공식 자료 | 운용사 공식 자료 |
| 해외 ETF 구성종목 | 관할 규제기관 공시 | 운용사 공식 자료 |
| 증권·기업·기관 식별자 | 거래소·규제기관·공식 등록기관 | 발행사·운용사 공식 자료 |
| 원화 환율 | ECOS `731Y001` | FRED와 다른 환율 정의를 혼합하지 않음 |

- 외부 데이터는 같은 평가 필드의 주최 측 값을 덮어쓰지 않는다.
- 같은 사실의 값이 다르면 기준일·공개일·관할·지표 정의를 비교한다.
- 해결되지 않은 값은 `source_value_conflict`로 격리하고 양쪽 Source와 Evidence를 보존한다.
- 충돌값을 평균하거나 최신 수치 하나로 자동 대체하지 않는다.

## 6. 원본 보존형 수집 흐름

```text
공식 API·파일
  → 응답 바이트·요청 명세 보존
  → NCP Private Object Storage
  → SHA-256·스키마·날짜·공개시점 검증
  → 소스별 명시적 mapper
  → Stage 02 catalog/relation/observation/evidence payload
  → 폐기 가능한 PostgreSQL building 재현
  → BuildReport·component hash·커버리지 보고
```

Object Storage key의 기본형은 다음과 같다.

```text
external/2026-07-11/{source_code}/{snapshot_id}/{object_name}
```

- API가 pagination을 사용하면 페이지별 원본 응답과 요청 파라미터를 보존하고 하나의 snapshot manifest로 묶는다.
- 인증 키·쿠키·서명·계정·bucket 이름은 object key, manifest, 로그와 Git에 기록하지 않는다.
- ETag를 SHA-256으로 간주하지 않는다.
- 원본 파일이나 API 응답을 Git fixture로 복제하지 않는다.
- 합성 fixture만 일반 테스트에 포함하고 실제 수집 검증은 명시적 marker와 환경변수로 실행한다.

Stage 03A처럼 YAML 규칙 DSL, 범용 plugin framework, 데이터 레이크를 새로 만들지 않는다. 공유 검증은 작은 helper로 유지하고 KRX, ECOS, N-PORT, 운용사 파일은 각각 명시적인 source adapter와 mapper를 가진다.

## 7. Stage 02 저장 구조 재사용

새 테이블 없이 다음과 같이 저장한다.

| 외부 사실 | Stage 02 저장 구조 |
| --- | --- |
| ETF·증권·기업·운용사 | `catalog.entity`와 해당 subtype |
| ISIN·티커·CIK 등 공식 ID | `catalog.identifier` |
| 공식 명칭·과거 표기 | `catalog.alias` |
| ETF 구성종목 | `relation.relation_record(predicate_id='holdsSecurity')` |
| 구성종목 편입비중·수량 | 위 관계를 대상으로 한 `observation.observation_record` |
| 증권과 기업 연결 | `securityOfCompany` 관계 |
| 국내 ETF 가격·NAV | ETF 엔티티 대상 Observation |
| ECOS 환율 | 한국은행 기관 엔티티 대상의 통화쌍·환율종류별 고정 Metric Observation |
| 원본과 컷오프 | `evidence.source_record`, `evidence.evidence_record`와 origin |
| 검색 범위 완전성 | `evidence_kind='query_scope'`, `scope_completeness` |

### 7.1 구성종목

```text
ETF --holdsSecurity--> Security
  └─ relation observation: holding_weight, quantity, holding_value
  └─ relation evidence: 원본 object key·record key·기준일·공개일
```

동일 증권이 원본에서 여러 행으로 표현될 때는 원천 정의가 같은 lot 또는 share class를 합산하도록 명시한 경우에만 결정론적으로 집계한다. 이름만 같은 행을 합치지 않는다. 비중 합계는 진단값으로 보고하며 파생상품·현금·공매도 등 원천 구조를 고려하지 않은 일률적 100% 강제 규칙은 두지 않는다.

### 7.2 환율

예를 들어 원/미국달러 매매기준율은 통화쌍과 공식 환율 종류가 포함된 고정 Metric ID를 사용한다. `numeric_value`, `unit`, `currency`, `applicable_date`는 Observation에 저장하고, `base_currency`, `quote_currency`, `rate_type`, ECOS 통계표·항목 코드는 Metric 정의와 Evidence의 정규값에 고정한다. 자유 문자열을 해석해 통화 방향을 추측하지 않는다.

### 7.3 Graph 경계

Stage 03B는 PostgreSQL 관계와 Evidence ID까지만 만든다. `holdsSecurity`, `securityOfCompany` 등의 RDF ABox 투영과 SHACL 검증은 Stage 04에서 수행하며 PostgreSQL 원장을 권위로 유지한다.

## 8. 검증과 실패 정책

### 8.1 소스 스냅샷 원자성

다음 문제는 해당 스냅샷 전체를 실패시킨다.

- 원본 checksum 불일치
- 승인되지 않은 endpoint·파일·게시기관
- 응답 스키마나 필수 필드의 예기치 않은 변경
- pagination 누락 또는 중복
- 컷오프 이후 자료의 적격값 승격
- 모집단 수와 행 회계 불일치
- snapshot manifest와 parser·mapping 버전 불일치

실패한 스냅샷의 정규화 결과를 BuildReport의 성공 건수에 포함하지 않는다.

### 8.2 개별 사실 격리

다음 문제는 가능한 범위에서 해당 상품·관계·관측값만 격리한다.

- 공식 식별자 충돌 또는 미해소
- 같은 상품·기준일·지표의 상이한 공식값
- 파싱 가능한 원본 안의 비정상 단위·비중·통화
- 공식 파일이 일부 보유종목만 제공하는 경우

격리 건은 원본 위치, 오류 코드, source ID와 함께 집계한다. 정상 레코드는 계속 검증할 수 있지만 구조 오류나 컷오프 위반을 조용히 건너뛰는 best-effort 적재는 금지한다.

## 9. 구현 순서

1. 공식 식별자·별칭 mapper와 source manifest
2. 국내 ETF 구성종목·비중 adapter와 mapper
3. KRX 동일일 가격·NAV adapter와 mapper
4. ECOS 환율 adapter와 mapper
5. SEC N-PORT adapter와 해외 ETF bounded coverage
6. 필요한 운용사 공식 파일의 소스별 승인과 보완 mapper
7. 통합 BuildReport, 커버리지, 예상 질문 데이터 게이트

식별자를 먼저 처리해 구성종목을 이름 문자열로 연결하지 않는다. 국내 경로로 holdings 구조를 검증한 뒤 범위와 공개시점이 더 복잡한 해외 경로를 추가한다.

## 10. Stage 03B 완료 게이트

1. 승인된 모든 공식 원본이 Private Object Storage에 보존되고 SHA-256 manifest와 일치한다.
2. 모든 적격 사실이 `applicable_date`, `published_at`, `available_at` 컷오프를 통과한다.
3. 같은 원본·parser·mapping으로 처음부터 재실행하면 같은 ID, payload hash, component hash와 건수가 생성된다.
4. 상품군·소스별 `COVERED`, `PARTIALLY_COVERED`, `NOT_COVERED`, `CONFLICT` 수가 BuildReport에 포함된다.
5. 미해소 식별자, 중복, 비중 진단, 출처 충돌과 격리 건이 안정적인 오류 코드로 집계된다.
6. `holdsSecurity`, `securityOfCompany`, 가격·NAV, 환율이 Source·Evidence 원본까지 역추적된다.
7. 핵심 데이터 질문인 삼성전자 편입 ETF, 구성종목 중첩, 동일일 가격·NAV, 교차통화 AUM 입력이 결정론적 데이터 fixture에서 검증된다.
8. 합성, 폐기 가능한 PostgreSQL, 명시적 실데이터·Object Storage 게이트가 각각 통과한다.
9. 일반 테스트와 로그에 원본 금융 데이터, 인증정보, bucket·계정·서버 식별자가 포함되지 않는다.
10. 최종 NCP PostgreSQL은 변경하지 않고 Stage 03C가 사용할 동결 후보 manifest와 재현 명령만 인계한다.

## 11. Stage 03C 인계

Stage 03B 완료는 데이터셋 활성화를 뜻하지 않는다. Stage 03C는 다음을 받아 공식 문서와 함께 최종 manifest를 만든다.

- Stage 03A 주최 측 8개 원본 object hash
- Stage 03B 승인 외부 source snapshot manifest
- parser·mapping·metric·predicate 버전
- 정규화 component hash와 커버리지 보고
- 격리·충돌·미지원 목록

모든 manifest가 동결된 후에만 NCP PostgreSQL에 새 최종 `building` 데이터셋을 처음부터 재현한다. Stage 04의 PostgreSQL·Graph·Vector·Evidence readiness를 모두 통과하기 전에는 활성화하지 않는다.

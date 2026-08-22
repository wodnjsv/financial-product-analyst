# Stage 03B 공식 구조화 데이터 필드 매트릭스

**Date:** 2026-08-22

**Status:** Approved - Task 1 boundary frozen on 2026-08-22

**Cutoff:** 2026-07-11
**Scope:** KRX 공식 종목·ETF 시장정보, ECOS `731Y001`, SEC Series/Class Report 및 Form N-PORT 2026 Q2

## 1. 결론

이번 매트릭스는 답변에 실제로 사용할 최소 공식 필드만 승인 후보로 고정한다. API 키, 인증 URL, 계정·버킷·오브젝트 키, 원시 응답값은 기록하지 않는다.

사용자는 2026-08-22에 A안을 승인했다. 접근과 강한 연결키가 확인된 원천은 순차 구현하고, `KRX_ETF_DAILY`의 상품 관측값 매핑과 `KRX_ETF_PDF` holdings 매핑은 각각 공식 ETF crosswalk와 재현 가능한 과거 holdings export가 추가 승인될 때까지 차단한다.

| 원천 | 접근·스키마 확인 | 컷오프 후보 | 연결 상태 | Task 1 판정 |
| --- | --- | --- | --- | --- |
| `KRX_KOSPI_BASIC` | 실응답 945행, 공식 필드 확인 | 요청 기준일 `20260710` | 구성종목 Security 식별용 | `ACCESS_CONFIRMED` |
| `KRX_KOSDAQ_BASIC` | 실응답 1,820행, 공식 필드 확인 | 요청 기준일 `20260710` | 구성종목 Security 식별용 | `ACCESS_CONFIRMED` |
| `KRX_ETF_DAILY` | 실응답 1,141행, `BAS_DD=20260710` | 2026-07-10 | 주최 측 국내 ETF와 강한 crosswalk 없음 | `ACCESS_CONFIRMED_LINK_BLOCKED` |
| `ECOS_731Y001` | 승인 4개 항목 각 1행, 공식 필드·단위 확인 | 2026-07-10 | 항목코드 고정 | `ACCESS_CONFIRMED` |
| `KRX_ETF_PDF` | 공식 화면과 PDF 정의만 확인 | 과거 export 미확인 | ETF·보유종목 crosswalk 및 헤더 미확인 | `ACCESS_NOT_CONFIRMED` |
| `KRX_ETF_BASIC_EXPORT` | 필요성만 확인 | 과거 export 미확인 | 주최 측 ETF와 KRX ETF 코드 crosswalk에 필요 | `ACCESS_NOT_CONFIRMED` |
| `SEC_SERIES_CLASS_20260601` | 공식 CSV 필드·게시일 확인 | 2026-06-01 공개본 | `(CIK, Class Ticker) -> Series ID` | `DOCS_CONFIRMED_CAPTURE_DEFERRED` |
| `SEC_NPORT_2026Q2` | 공식 ZIP·Readme·필드 확인 | 2026-06-30 공개본 | `Series ID` 및 holding strong ID | `DOCS_CONFIRMED_CAPTURE_DEFERRED` |

KRX Open API와 ECOS 실호출에서는 응답 스키마·행 수·날짜·단위만 확인했고 원시 값은 보존하지 않았다. SEC는 공식 문서와 컷오프 이전 공개 패키지만 고정했으며, 사용자 식별 가능한 User-Agent를 준비할 때까지 실제 ZIP 캡처는 수행하지 않는다.

## 2. Task 1에서 발견한 필수 계획 수정

### 2.1 국내 ETF 연결키

기존 계획은 `pd_itm_no`를 KRX 단축코드와 직접 비교해 식별자 유형을 잘못 해석했다. [ADR-0015](../decisions/ADR-0015-use-isin-derived-krx-etf-bindings.md)가 이를 대체한다.

- 주최 측 국내 ETF 1,202개 중 checksum-valid ISIN: **1,201건**
- 공식 KRX 기본정보의 `표준코드[3:9] == 단축코드`: **1,161/1,161건**
- valid organizer ISIN에서 파생한 단축코드와 `2026-07-10` KRX ETF 코드의 unique exact 일치: **1,133건**
- 위 1,133건 중 이름 audit 일치: **1,132건**, 이름 변경: **1건**
- 미해소 organizer ETF: **69건**, organizer에 없는 KRX ETF: **8건**

승인된 crosswalk는 다음 조건을 모두 만족해야 한다.

```text
organizer pd_itm_no is a checksum-valid ISIN
derived KRX short code == unique KRX ETF code on 2026-07-10
one organizer ETF == one KRX ETF code
one KRX ETF code == one organizer ETF
```

이름과 상장일은 audit에 사용하되 identity binding을 만들지 않는다. 현재 KRX 기본정보 export는 identifier 구조 검증에만 사용하고 답변 사실에는 사용하지 않는다.

### 2.2 해외 ETF와 N-PORT 연결키

N-PORT의 필수 5개 파일에는 펀드 자체 ticker가 없다. 따라서 기존 `(CIK, ticker)` 규칙은 N-PORT 파일만으로 구현할 수 없다. 컷오프 전에 공개된 SEC `Investment Company Series and Class Report` 2026-06-01 CSV를 최소 보조 원천으로 추가한다.

```text
organizer overseas ETF
  -- unique exact (CIK, normalized ticker) --> SEC class
  -- CLASS_ID belongs to --> SERIES_ID
  -- exact SERIES_ID --> N-PORT FUND_REPORTED_INFO
```

- ticker 단독, 상품명 단독, issuer명 단독, 임베딩 유사도는 금지한다.
- `company_tickers_mf.json` 현재본은 컷오프 당시 버전을 입증하지 못하므로 사용하지 않는다.
- Series/Class Report가 포괄하지 않는 closed-end fund·UIT와 ticker 미제공 class는 `NOT_COVERED`다.

## 3. 공통 규칙

아래 필드표에서 `same`은 같은 표의 첫 행에 적은 source-level 값과 동일하다는 뜻이다. `source_code`는 모든 소비 필드 행에 반복해서 명시한다.

### 3.1 분류

| `classification` | 의미 |
| --- | --- |
| `identifier` | pre-scan 고유성 검증 후에만 `catalog.identifier`로 승격 |
| `catalog` | canonical name 또는 alias; companion text Observation과 Evidence 필수 |
| `relation` | 승인된 ontology relation의 endpoint 또는 구조 필드 |
| `observation` | 타입·단위·날짜가 고정된 값 |
| `evidence_only` | 구조 검증·locator·제한 설명에만 사용 |

### 3.2 날짜와 권위

- 모든 원천은 `applicable_date <= 2026-07-11`을 만족해야 한다.
- KRX·ECOS 일별 응답은 공식 response에 게시시각과 과거 vintage가 없으므로 `published_at`은 비워 둔다. `2026-07-10` 일별 관측은 컷오프보다 하루 이전인 경우에만 day-level `available_at` 적격으로 인정한다. 캡처 시각은 별도 `vintage_date`로 보존한다.
- KRX 종목기본정보의 기준일은 response field가 아니라 서명된 snapshot request `basDd`에서 가져온다.
- SEC N-PORT는 `REPORT_DATE`, `FILING_DATE`, package 공개일이 모두 컷오프 이하여야 한다. 동일 `(CIK, SERIES_ID, REPORT_DATE)`는 컷오프 이하 최신 amendment만 선택한다.
- 같은 평가 필드가 주최 측 원천에도 있으면 주최 측 값이 우선한다. KRX 가격·NAV, ECOS 환율, SEC holdings처럼 별도로 승인한 사실만 공식 원천이 권위 원천이다.

### 3.3 Evidence와 충돌

- locator는 `source_code/object_name/row key/field`까지 재현 가능해야 한다.
- 구조키 중복, 필수행 누락, schema drift, 날짜 위반은 snapshot 전체 실패다.
- identifier 중복이나 crosswalk 다중 후보는 해당 entity만 `source_value_conflict`로 격리한다. 첫 행을 선택하지 않는다.
- holdings의 반복 lot은 strong security ID, 통화, payoff profile, 단위가 모두 같고 공식 정의가 합산 가능하다고 명시한 경우에만 합산한다.
- `NOT_COVERED`는 보유종목 없음이 아니다. 음의 `holdsSecurity` 사실을 만들지 않는다.

## 4. KRX 종목기본정보 필드

두 시장은 같은 필드 계약을 사용한다. `object_name`만 `KOSPI issue basic information` 또는 `KOSDAQ issue basic information`으로 달라진다.

| source_code | publisher | access_method | object_name | source_field | source_type | source_grain | classification | target | identifier_or_metric | unit | currency | applicable_date_rule | published_at_rule | available_at_rule | vintage_date_rule | coverage_rule | conflict_rule | evidence_locator | usage_note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `KRX_KOSPI_BASIC / KRX_KOSDAQ_BASIC` | KRX | Open API GET; `AUTH_KEY` header | market issue basic information | `REQUEST.basDd` | `YYYYMMDD` | snapshot | evidence_only | snapshot manifest | `krx_requested_date` | date | - | exact request date | null | `basDd < cutoff`이면 day-level 적격 | capture timestamp | API가 반환한 전체 row accounting | 요청일 불일치면 snapshot 실패 | request manifest | response에는 `BAS_DD`가 없음 |
| `KRX_KOSPI_BASIC / KRX_KOSDAQ_BASIC` | KRX | same | same | `ISU_CD` | text | security | identifier | Security identifier + companion observation | `KRX_STANDARD_ISSUE_CODE` | code | - | request `basDd` | null | request-date rule | capture timestamp | KOSPI/KOSDAQ 응답 universe | snapshot 내 중복이면 해당 code conflict | `OutBlock_1[row]/ISU_CD` | 12자리 표준 종목코드로 관측됨 |
| `KRX_KOSPI_BASIC / KRX_KOSDAQ_BASIC` | KRX | same | same | `ISU_SRT_CD` | text | security | identifier | Security identifier + companion observation | `KRX_SHORT_ISSUE_CODE` | code | - | request `basDd` | null | request-date rule | capture timestamp | same | snapshot 내 중복 또는 standard-code 다중 매핑이면 conflict | `OutBlock_1[row]/ISU_SRT_CD` | 6자리 단축코드 |
| `KRX_KOSPI_BASIC / KRX_KOSDAQ_BASIC` | KRX | same | same | `ISU_NM` | text | security | catalog | canonical name + companion observation | `official_security_name_ko` | - | - | request `basDd` | null | request-date rule | capture timestamp | same | identifier가 해결된 row에서만 사용 | `OutBlock_1[row]/ISU_NM` | 이름은 식별키가 아님 |
| `KRX_KOSPI_BASIC / KRX_KOSDAQ_BASIC` | KRX | same | same | `ISU_ABBRV` | text | security | catalog | alias + companion observation | `official_security_short_name_ko` | - | - | request `basDd` | null | request-date rule | capture timestamp | same | identifier가 해결된 row에서만 사용 | `OutBlock_1[row]/ISU_ABBRV` | 검색 alias |
| `KRX_KOSPI_BASIC / KRX_KOSDAQ_BASIC` | KRX | same | same | `ISU_ENG_NM` | text | security | catalog | alias + companion observation | `official_security_name_en` | - | - | request `basDd` | null | request-date rule | capture timestamp | same | identifier가 해결된 row에서만 사용 | `OutBlock_1[row]/ISU_ENG_NM` | 영문 검색 alias |

`LIST_DD`, `MKT_TP_NM`, `SECUGRP_NM`, `SECT_TP_NM`, `KIND_STKCERT_TP_NM`, `PARVAL`, `LIST_SHRS`는 이번 mapper에서 제외한다. ETF 상품 crosswalk용 필드로 재해석하지 않는다.

## 5. KRX ETF 일별매매정보 필드

| source_code | publisher | access_method | object_name | source_field | source_type | source_grain | classification | target | identifier_or_metric | unit | currency | applicable_date_rule | published_at_rule | available_at_rule | vintage_date_rule | coverage_rule | conflict_rule | evidence_locator | usage_note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `KRX_ETF_DAILY` | KRX | Open API GET; `AUTH_KEY` header | ETF daily trading information | `BAS_DD` | `YYYYMMDD` | ETF/date | evidence_only | Observation date | `krx_etf_observation_date` | date | - | exact field date | null | `BAS_DD < cutoff`이면 day-level 적격 | capture timestamp | 해당 일자 응답 전체 row accounting | 요청일과 다르면 snapshot 실패 | `OutBlock_1[row]/BAS_DD` | 2026-07-10 실응답 확인 |
| `KRX_ETF_DAILY` | KRX | same | same | `ISU_CD` | text | ETF/date | identifier | ETF crosswalk key + companion observation | `KRX_ETF_ISSUE_CODE` | code | - | `BAS_DD` | null | same | capture timestamp | crosswalk 승인된 organizer ETF만 answerable | ETF 기본정보 crosswalk가 없으면 unresolved | `OutBlock_1[row]/ISU_CD` | `pd_itm_no`와 직접 매칭 금지 |
| `KRX_ETF_DAILY` | KRX | same | same | `ISU_NM` | text | ETF/date | catalog | alias candidate + companion observation | `official_etf_name_ko` | - | - | `BAS_DD` | null | same | capture timestamp | same | 이름 단독 연결 금지 | `OutBlock_1[row]/ISU_NM` | crosswalk 검증 보조값 |
| `KRX_ETF_DAILY` | KRX | same | same | `TDD_CLSPRC` | numeric text | ETF/date | observation | product Observation | `krx_etf_market_close_krw@1` | price per share | KRW | `BAS_DD` | null | same | capture timestamp | matched ETF only | 중복 `(ISU_CD,BAS_DD)` 또는 malformed Decimal이면 snapshot 실패 | `OutBlock_1[row]/TDD_CLSPRC` | organizer AUM·return을 대체하지 않음 |
| `KRX_ETF_DAILY` | KRX | same | same | `NAV` | numeric text | ETF/date | observation | product Observation | `krx_etf_nav_per_share_krw@1` | NAV per share | KRW | `BAS_DD` | null | same | capture timestamp | matched ETF only | close와 같은 날짜가 아니면 비교 금지; missing은 missing | `OutBlock_1[row]/NAV` | price와 별도 Evidence |

그 밖의 가격, 거래량, 거래대금, 시가총액, 순자산총액, 상장좌수, 지수 필드는 raw snapshot에는 남지만 이번 답변용 mapper에서는 사용하지 않는다. 특히 `INVSTASST_NETASST_TOTAMT`로 주최 측 AUM을 덮어쓰지 않는다.

## 6. ECOS `731Y001` 필드

허용 item은 `0000001` 원/미국달러, `0000002` 원/100엔, `0000003` 원/유로, `0000053` 원/위안뿐이다.

| source_code | publisher | access_method | object_name | source_field | source_type | source_grain | classification | target | identifier_or_metric | unit | currency | applicable_date_rule | published_at_rule | available_at_rule | vintage_date_rule | coverage_rule | conflict_rule | evidence_locator | usage_note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ECOS_731Y001` | Bank of Korea | ECOS `StatisticSearch` HTTPS | `731Y001`, daily | `STAT_CODE` | text | item/date | evidence_only | snapshot validation | `731Y001` | code | - | `TIME` | null | `TIME < cutoff`이면 day-level 적격 | capture timestamp | exactly four allowlisted items | 다른 통계표면 snapshot 실패 | `StatisticSearch.row[row]/STAT_CODE` | 고정값 검증 |
| `ECOS_731Y001` | Bank of Korea | same | same | `ITEM_CODE1` | text | item/date | identifier | metric selector + Evidence | fixed ECOS item code | code | - | `TIME` | null | same | capture timestamp | exactly four allowlisted items | unknown·duplicate item이면 snapshot 실패 | `StatisticSearch.row[row]/ITEM_CODE1` | 방향을 질문에서 추론하지 않음 |
| `ECOS_731Y001` | Bank of Korea | same | same | `ITEM_NAME1` | text | item/date | evidence_only | metric definition description | official item name | - | - | `TIME` | null | same | capture timestamp | same | item code와 공식명 불일치면 snapshot 실패 | `StatisticSearch.row[row]/ITEM_NAME1` | 표시·정의 검증 |
| `ECOS_731Y001` | Bank of Korea | same | same | `UNIT_NAME` | text | item/date | evidence_only | unit validation | `KRW` | KRW | KRW | `TIME` | null | same | capture timestamp | same | 공식 unit이 원이 아니면 snapshot 실패 | `StatisticSearch.row[row]/UNIT_NAME` | JPY 항목의 100엔 denominator는 metric 정의에 고정 |
| `ECOS_731Y001` | Bank of Korea | same | same | `TIME` | `YYYYMMDD` | item/date | evidence_only | Observation date | `ecos_observation_date` | date | - | exact field date | null | `TIME < cutoff`이면 day-level 적격 | capture timestamp | 각 item별 latest eligible 1행 | cutoff 이후 row는 제외 | `StatisticSearch.row[row]/TIME` | 2026-07-10 실응답 확인 |
| `ECOS_731Y001` | Bank of Korea | same | same | `DATA_VALUE` | numeric text | item/date | observation | FX Observation | item별 `ecos_731y001_*@1` | KRW per source unit | KRW | `TIME` | null | same | capture timestamp | four item 모두 있어야 snapshot answerable | float 변환 금지; malformed·duplicate latest면 snapshot 실패 | `StatisticSearch.row[row]/DATA_VALUE` | Decimal; `0000002`는 KRW per 100 JPY |

`ITEM_CODE2-4`, `ITEM_NAME2-4`, `WGT`는 이번 통계표에서 직접 사용하지 않는다.

## 7. SEC Series/Class Report 필드

| source_code | publisher | access_method | object_name | source_field | source_type | source_grain | classification | target | identifier_or_metric | unit | currency | applicable_date_rule | published_at_rule | available_at_rule | vintage_date_rule | coverage_rule | conflict_rule | evidence_locator | usage_note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `SEC_SERIES_CLASS_20260601` | SEC | official CSV download | Investment Company Series and Class Report | `CIK` | text | class | identifier | Institution identifier + companion observation | `SEC_CIK` | code | - | static report snapshot | 2026-06-01 | 2026-06-01 | report version date | report-defined active series/class scope | invalid or multi-registrant mapping이면 conflict | CSV row/`CIK` | leading zeros normalized only by SEC rule |
| `SEC_SERIES_CLASS_20260601` | SEC | same | same | `Series ID` | text | series | identifier | Product identifier + companion observation | `SEC_SERIES_ID` | code | - | same | 2026-06-01 | 2026-06-01 | same | same | one class가 multiple series이면 conflict | CSV row/`Series ID` | N-PORT join key |
| `SEC_SERIES_CLASS_20260601` | SEC | same | same | `Series Name` | text | series | catalog | Product alias + companion observation | `official_series_name` | - | - | same | 2026-06-01 | 2026-06-01 | same | same | identifier가 해결된 row에서만 사용 | CSV row/`Series Name` | 이름 단독 연결 금지 |
| `SEC_SERIES_CLASS_20260601` | SEC | same | same | `Class ID` | text | class | identifier | Product identifier + companion observation | `SEC_CLASS_ID` | code | - | same | 2026-06-01 | 2026-06-01 | same | same | duplicate class ID면 snapshot 실패 | CSV row/`Class ID` | organizer ETF는 ticker가 속한 class에 연결 |
| `SEC_SERIES_CLASS_20260601` | SEC | same | same | `Class Name` | text | class | catalog | Product alias + companion observation | `official_class_name` | - | - | same | 2026-06-01 | 2026-06-01 | same | same | identifier가 해결된 row에서만 사용 | CSV row/`Class Name` | 표시 보조값 |
| `SEC_SERIES_CLASS_20260601` | SEC | same | same | `Class Ticker` | text | class | evidence_only | compound crosswalk component | `SEC_CLASS_TICKER` | code | - | same | 2026-06-01 | 2026-06-01 | same | ticker가 있는 report scope만 | `(CIK, normalized ticker)`가 1개 class가 아니면 unresolved/conflict | CSV row/`Class Ticker` | ticker 단독 identifier 금지 |

## 8. SEC Form N-PORT 필드

공통 access는 SEC 2026 Q2 공식 ZIP의 UTF-8 tab-delimited 파일이다. package 공개일·available date는 2026-06-30으로 고정한다. 모든 locator는 `package/file/primary key/field`를 포함한다.

| source_code | publisher | access_method | object_name | source_field | source_type | source_grain | classification | target | identifier_or_metric | unit | currency | applicable_date_rule | published_at_rule | available_at_rule | vintage_date_rule | coverage_rule | conflict_rule | evidence_locator | usage_note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `SEC_NPORT_2026Q2` | SEC | official quarterly ZIP | `SUBMISSION.tsv` | `ACCESSION_NUMBER` | text | submission | evidence_only | submission key | `SEC_ACCESSION_NUMBER` | code | - | `REPORT_DATE` | `FILING_DATE` | max(package date, filing date) | 2026 Q2 package | public disseminated filings only | duplicate key면 snapshot 실패 | file/accession/field | 모든 downstream join과 Evidence root |
| `SEC_NPORT_2026Q2` | SEC | same | `SUBMISSION.tsv` | `FILING_DATE` | date | submission | evidence_only | Evidence publication date | `sec_filing_date` | date | - | `REPORT_DATE` | exact field | max(package date, filing date) | same | filing date <= cutoff | after-cutoff amendment 제외 | file/accession/field | amendment 선택축 |
| `SEC_NPORT_2026Q2` | SEC | same | `SUBMISSION.tsv` | `SUB_TYPE` | text | submission | evidence_only | filing type | `sec_nport_submission_type` | code | - | `REPORT_DATE` | `FILING_DATE` | same | same | `NPORT-P`, `NPORT-P/A`만 | unsupported type 제외 | file/accession/field | original/amendment 구분 |
| `SEC_NPORT_2026Q2` | SEC | same | `SUBMISSION.tsv` | `REPORT_DATE` | date | submission | evidence_only | portfolio applicable date | `sec_nport_report_date` | date | - | exact field | `FILING_DATE` | same | same | report date <= cutoff | invalid date면 accession 격리 | file/accession/field | holdings snapshot date |
| `SEC_NPORT_2026Q2` | SEC | same | `REGISTRANT.tsv` | `ACCESSION_NUMBER` | text | registrant/submission | relation | registrant-to-submission join | `SEC_ACCESSION_NUMBER` | code | - | submission `REPORT_DATE` | submission `FILING_DATE` | same | same | selected accession only | orphan key면 snapshot 실패 | file/accession/field | 구조키 |
| `SEC_NPORT_2026Q2` | SEC | same | `REGISTRANT.tsv` | `CIK` | text | registrant | identifier | Institution identifier + companion observation | `SEC_CIK` | code | - | selected report date | filing date | same | same | selected registrant scope | CIK mismatch with Series/Class crosswalk이면 conflict | file/accession/field | organizer compound crosswalk component |
| `SEC_NPORT_2026Q2` | SEC | same | `REGISTRANT.tsv` | `REGISTRANT_NAME` | text | registrant | catalog | Institution name + companion observation | `official_registrant_name` | - | - | selected report date | filing date | same | same | same | CIK 해결 후에만 사용 | file/accession/field | 이름 단독 병합 금지 |
| `SEC_NPORT_2026Q2` | SEC | same | `REGISTRANT.tsv` | `LEI` | text | registrant | identifier | Institution identifier + companion observation | `LEI` | code | - | selected report date | filing date | same | same | non-empty valid LEI only | 중복·invalid LEI는 Evidence only conflict | file/accession/field | strong identifier 후보 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_INFO.tsv` | `ACCESSION_NUMBER` | text | fund/submission | relation | fund-to-submission join | `SEC_ACCESSION_NUMBER` | code | - | submission `REPORT_DATE` | submission `FILING_DATE` | same | same | selected accession only | orphan key면 snapshot 실패 | file/accession/field | 구조키 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_INFO.tsv` | `SERIES_ID` | text | fund series | identifier | Product identifier + companion observation | `SEC_SERIES_ID` | code | - | report date | filing date | same | same | Series/Class crosswalk로 연결된 series | crosswalk 불일치·다중 후보면 conflict | file/accession/field | organizer product-to-holdings join |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_INFO.tsv` | `SERIES_NAME` | text | fund series | catalog | Product alias + companion observation | `official_series_name` | - | - | report date | filing date | same | same | matched series only | SERIES_ID 해결 후에만 사용 | file/accession/field | 이름 단독 연결 금지 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_INFO.tsv` | `SERIES_LEI` | text | fund series | identifier | Product identifier + companion observation | `LEI` | code | - | report date | filing date | same | same | valid non-empty LEI | 중복·invalid LEI는 Evidence only conflict | file/accession/field | 보조 strong identifier |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `ACCESSION_NUMBER` | text | holding/submission | relation | holding-to-submission join | `SEC_ACCESSION_NUMBER` | code | - | report date | filing date | same | same | selected accession의 전체 row accounting | orphan key면 snapshot 실패 | file/accession+holding/field | 구조키 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `HOLDING_ID` | integer | holding | evidence_only | source-local Security key | `SEC_NPORT_HOLDING_ID` | code | - | report date | filing date | same | same | selected accession의 전체 row accounting | duplicate `(accession,holding)`이면 snapshot 실패 | file/accession+holding/field | global identifier로 승격 금지 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `ISSUER_NAME` | text | holding | catalog | Security/issuer display observation | `official_holding_issuer_name` | - | - | report date | filing date | same | same | accounted holding rows | strong ID 해결 후 alias; 아니면 source-local 표시 | file/accession+holding/field | 이름 병합 금지 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `ISSUER_TITLE` | text | holding | catalog | Security alias observation | `official_holding_title` | - | - | report date | filing date | same | same | accounted holding rows | strong ID 해결 후 alias | file/accession+holding/field | 종목 표시명 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `ISSUER_CUSIP` | text | holding | identifier | Security identifier + companion observation | `CUSIP` | code | - | report date | filing date | same | same | valid unique CUSIP only | duplicate·invalid이면 identifier 미생성 | file/accession+holding/field | ISIN 다음 resolution 우선순위 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `BALANCE` | decimal | holding | observation | `holdsSecurity` relation Observation | `official_holding_balance@1` | `UNIT` | `CURRENCY_CODE` when monetary | report date | filing date | same | same | accounted holding rows | unit 없는 balance는 limited | file/accession+holding/field | float 변환 금지 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `UNIT` | text | holding | evidence_only | balance unit | `official_holding_balance_unit` | source enum | - | report date | filing date | same | same | accounted holding rows | unknown enum이면 row limited | file/accession+holding/field | shares/principal/other 구분 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `OTHER_UNIT_DESC` | text | holding | evidence_only | balance unit description | `official_holding_other_unit` | - | - | report date | filing date | same | same | `UNIT=other` row | unit과 불일치면 limited | file/accession+holding/field | 임의 단위 정규화 금지 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `CURRENCY_CODE` | text | holding | observation | holding currency Observation | `official_holding_currency@1` | ISO 4217 code | source currency | report date | filing date | same | same | valid currency rows | invalid code는 row limited | file/accession+holding/field | fund base currency로 대체 금지 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `CURRENCY_VALUE` | decimal | holding | observation | `holdsSecurity` relation Observation | `official_holding_currency_value@1` | amount | `CURRENCY_CODE` | report date | filing date | same | same | accounted holding rows | missing currency와 함께 있으면 limited | file/accession+holding/field | organizer AUM이 아님 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `PERCENTAGE` | decimal | holding | observation | `holdsSecurity` relation Observation | `official_holding_weight_pct@1` | percentage point | - | report date | filing date | same | same | accounted holding rows | fraction으로 나누지 않음; malformed면 row conflict | file/accession+holding/field | net assets 대비 비율 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `PAYOFF_PROFILE` | text | holding | evidence_only | holding structure qualifier | `official_holding_payoff_profile` | enum | - | report date | filing date | same | same | accounted holding rows | 반복 lot 합산 조건에 포함 | file/accession+holding/field | long/short/N/A |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `ASSET_CAT` | text | holding | observation | Security classification Observation | `official_holding_asset_category@1` | enum | - | report date | filing date | same | same | accounted holding rows | unknown enum은 raw evidence | file/accession+holding/field | similarity 보조값 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `OTHER_ASSET` | text | holding | evidence_only | asset category description | `official_holding_other_asset` | - | - | report date | filing date | same | same | `ASSET_CAT=other` row | category와 불일치면 limited | file/accession+holding/field | 텍스트로 임의 분류 금지 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `INVESTMENT_COUNTRY` | text | holding | observation | Security country Observation | `official_holding_investment_country@1` | country code | - | report date | filing date | same | same | valid code rows | issuer 국적 외 의미로 확장 금지 | file/accession+holding/field | SEC 정의 그대로 사용 |
| `SEC_NPORT_2026Q2` | SEC | same | `FUND_REPORTED_HOLDING.tsv` | `DERIVATIVE_CAT` | text | holding | evidence_only | derivative qualifier | `official_holding_derivative_category` | enum | - | report date | filing date | same | same | derivative rows | unsupported derivative는 source-local Security | file/accession+holding/field | 일반 주식으로 오분류 금지 |
| `SEC_NPORT_2026Q2` | SEC | same | `IDENTIFIERS.tsv` | `HOLDING_ID` | integer | holding identifier | relation | identifier-to-holding join | `SEC_NPORT_HOLDING_ID` | code | - | report date | filing date | same | same | selected holding rows | orphan key면 snapshot 실패 | file/holding+identifier/field | 구조키 |
| `SEC_NPORT_2026Q2` | SEC | same | `IDENTIFIERS.tsv` | `IDENTIFIERS_ID` | integer | holding identifier | evidence_only | source row key | `SEC_NPORT_IDENTIFIERS_ID` | code | - | report date | filing date | same | same | identifier row accounting | duplicate compound key면 snapshot 실패 | file/holding+identifier/field | global identifier 아님 |
| `SEC_NPORT_2026Q2` | SEC | same | `IDENTIFIERS.tsv` | `IDENTIFIER_ISIN` | text | holding identifier | identifier | Security identifier + companion observation | `ISIN` | code | - | report date | filing date | same | same | valid unique ISIN only | snapshot pre-scan 중복·invalid이면 identifier 미생성 | file/holding+identifier/field | holding resolution 1순위 |
| `SEC_NPORT_2026Q2` | SEC | same | `IDENTIFIERS.tsv` | `IDENTIFIER_TICKER` | text | holding identifier | catalog | Security alias observation | `official_holding_ticker` | code | - | report date | filing date | same | same | non-empty rows | ticker 단독 identifier 금지 | file/holding+identifier/field | 검색 표시 보조값 |
| `SEC_NPORT_2026Q2` | SEC | same | `IDENTIFIERS.tsv` | `OTHER_IDENTIFIER` | text | holding identifier | evidence_only | raw identifier observation | `official_holding_other_identifier` | source-defined | - | report date | filing date | same | same | non-empty rows | type가 명확하지 않으면 승격 금지 | file/holding+identifier/field | 원문 보존 |
| `SEC_NPORT_2026Q2` | SEC | same | `IDENTIFIERS.tsv` | `OTHER_IDENTIFIER_DESC` | text | holding identifier | evidence_only | raw identifier type | `official_holding_other_identifier_type` | - | - | report date | filing date | same | same | other identifier rows | allowlist 없는 type은 Evidence only | file/holding+identifier/field | 식별자 의미 보조 |

N-PORT의 `NET_ASSETS`, 수익률, VaR, 금리위험, 대차, 담보 및 상세 파생 테이블은 이번 범위에서 사용하지 않는다. `FUND_REPORTED_INFO.NET_ASSETS`로 주최 측 AUM을 대체하지 않는다.

## 9. KRX ETF PDF 및 coverage 판정

KRX는 PDF를 ETF 설정·환매에 필요한 현물 바스켓으로 설명한다. 이것만으로 모든 ETF의 전체 경제적 보유내역을 publisher-complete portfolio라고 단정할 수 없다. 따라서 정확한 export를 확보하더라도 다음을 먼저 검증한다.

1. 과거 기준일 조회가 재현되는가.
2. 파일이 한 ETF인지 전체 ETF인지, pagination/file boundary가 무엇인가.
3. ETF 코드, holding 코드, 수량, 평가금액, 통화, 비중의 exact header와 단위가 무엇인가.
4. 현금·파생·해외자산·합성 ETF 표현을 포함하는가.
5. KRX가 해당 파일을 complete portfolio로 정의하는가, creation basket으로만 정의하는가.

2026-07-10 과거 조회와 ETF별 CSV export가 재현되었고 exact header는 다음과 같다.

```text
종목코드
구성종목명
주식수(계약수)
평가금액
시가총액
시가총액 구성비중
```

파일은 ETF 한 종목·조회일 한 날짜 단위다. 주식 외에 선물, 외화예금, 원화현금, 설정현금액이 함께 나타나며 `-`는 0이 아니라 미제공 값이다. 실제 원화현금에서 음수 시가총액과 음수 비중이 관찰되므로 signed Decimal을 보존한다. `CASH00000001/설정현금액`은 holding security가 아니라 설정용 요약값으로 분리한다.

KRX는 PDF를 설정·환매용 바스켓으로 설명하므로 `COVERED/closed_world`를 사용하지 않는다. 성공한 ETF 파일도 `PARTIALLY_COVERED/bounded_unknown`으로 저장한다. Task 4는 이 제한된 의미로 진행할 수 있다.

## 10. 승인 시 구현 경계

승인 후에도 바로 구현 가능한 범위와 차단 범위는 분리한다.

| 상태 | 구현 범위 |
| --- | --- |
| 진행 가능 | immutable snapshot capture, KRX KOSPI/KOSDAQ Security identity, ECOS 4개 환율, SEC Series/Class + N-PORT bounded parser, KRX ETF PDF bounded holdings mapper, KRX ETF daily price/NAV mapping |
| 추가 source capture 후 가능 | KRX ETF별 PDF 전수 coverage 확정 |
| 계속 차단 | KRX PDF를 complete economic portfolio 또는 `closed_world`로 해석하는 것 |

Task 3과 Task 7의 해외 crosswalk는 `SEC_SERIES_CLASS_20260601`을 사용한다. Task 4와 Task 5는 ADR-0015의 exact domestic ETF binding만 사용한다.

## 11. 공식 문서

- [KRX Open API 서비스 이용](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp)
- [KRX Open API 서비스 목록](https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd)
- [KRX Data Marketplace](https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd)
- [KRX ETF information disclosure](https://global.krx.co.kr/contents/GLB/06/0605/0605010101/GLB0605010101T2.jsp)
- [Bank of Korea ECOS Open API](https://ecos.bok.or.kr/api/)
- [SEC Form N-PORT Data Sets](https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets)
- [SEC Form N-PORT Readme](https://www.sec.gov/files/nport_readme.pdf)
- [SEC Investment Company Series and Class Information](https://www.sec.gov/data-research/sec-markets-data/investment-company-series-class-information)

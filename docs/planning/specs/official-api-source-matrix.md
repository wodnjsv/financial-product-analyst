# 금융상품 Agent 필요 기반 공식 데이터·API 소스 매트릭스

**Date:** 2026-08-10

**Status:** Approved conditional-source policy; first Stage 03B source boundary activated by [ADR-0014](../decisions/ADR-0014-use-bounded-official-source-snapshots.md)

**Evaluation snapshot cutoff:** Superseded by `2026-08-24` under [ADR-0016](../decisions/ADR-0016-use-2026-08-24-organizer-baseline.md). The old source observations remain historical probes and require recapture or explicit reapproval.

## 1. 목적

공식 예상 질문을 반영한 52개 핵심 평가 질문을 기준으로, 주최 측 마스터에 없는 데이터를 어떤 공식 API와 공시에서 확보할지 정한다. 출발점은 API 목록이 아니라 질문의 필수 사실과 관계다. 한국거래소 KRX OPEN API, 한국은행 ECOS Open API, Federal Reserve Bank of St. Louis FRED API는 사용할 수 있는 공식 후보이며, 세 곳을 모두 연결하는 것은 요구사항이 아니다.

### 1.1 Current public-fund holdings decision

The `2026-08-24` cutoff review found no source that simultaneously provides
publisher-official security-level holdings, verifiable portfolio and
publication dates, exact organizer share-class binding, measurable population
coverage, and preservable raw evidence. The result is `requires_data`, not an
empty holdings set. See
[Public-Fund Holdings Source Decision](public-fund-holdings-source-decision-2026-08-24.md).

KOFIA performance-comparison disclosure provides asset-class proportions, not
security-level constituents. KOFIA asset-management report documents may
contain holdings, but a complete exact identifier crosswalk and uniform
machine-readable population have not been established. OpenDART and manager
sites likewise fail at least one exact-binding or measurable-coverage gate.

주최측이 명시한 RDB·Vector·Graph 결합과 공식 예상 질문은 [공식 과제·기술 요구사항](../../reference/official-competition-requirements.md)을 기준으로 한다. 공식 질문은 API만으로 충족되지 않으므로 법정 공시, 거래소·운용사 파일, 공식 상품·정책 문서도 동등한 소스 후보 레지스트리에서 관리한다.

소스 선택 순서는 다음과 같다.

```text
평가 질문
→ 필요한 사실·관계·계산 입력
→ 주최 측 데이터의 존재성·정의·기준일 검증
→ 공백이 답변에 실제로 필요한 경우에만 공식 외부 원천 선택
→ 2026-07-11 관측·공개 컷오프 검증
→ 해당 질문을 지원하는 최소 데이터만 적재
```

따라서 주최 측 데이터만으로 정확히 답할 수 있으면 외부 API를 호출하지 않는다. 공식 API가 제공한다는 이유만으로 금리·물가·시장지표를 미리 수집하거나 답변에 붙이지 않는다.

세 API는 역할이 다르다.

- KRX: 국내 상장 ETF·지수·주식·채권의 시장·기본정보
- ECOS: 원화 환율, 한국은행 기준금리, 국내 시장금리와 한국 거시지표
- FRED: 미국·글로벌 금리·환율·변동성·거시지표와 과거 빈티지

FRED·ECOS는 개별 금융상품의 AUM, NAV, 보수, 구성종목을 제공하는 원천으로 사용하지 않는다. KRX OPEN API 서비스 목록에도 ETF 구성종목 PDF가 별도 API로 명시돼 있지 않으므로, ETF 편입종목은 KRX Data Marketplace 또는 자산운용사 공식 공시 파일을 별도 수집해야 한다. 현재 52개 질문 중 ECOS가 직접 필요한 것은 교차통화 AUM 비교의 환율이며, FRED 시계열을 필수로 요구하는 질문은 없다.

## 2. 2026-07-11 컷오프의 정확한 의미

단순히 데이터 행의 날짜만 검사하면 사후 수정치나 뒤늦게 발표된 월·분기 값을 섞을 수 있다. 평가 스냅샷에 들어가는 레코드는 가능한 범위에서 다음 조건을 모두 만족해야 한다.

```text
applicable_date <= 2026-07-11
available_at <= 2026-07-11
published_at <= 2026-07-11
vintage_date <= 2026-07-11
```

해당 원천이 `available_at`, `published_at`, `vintage_date`를 제공하지 않으면 그 사실을 `availability_status`에 기록한다. 컷오프 이후 조회한 최신 수정치만 확보되는 경우에는 `latest_revised_after_cutoff`로 분류하고 엄격한 과거시점 답변에 사용하지 않는다.

### 2.1 주기별 선택 규칙

- 일별 시장·환율: 컷오프 당일 값이 있으면 사용하고, 없으면 컷오프 이전 최신 공식 관측값을 사용한다.
- 상태·효력 데이터: 컷오프 당일 유효한 레코드를 사용하고 `valid_from`, `valid_to`를 보존한다.
- 월·분기·연간 통계: 기간명이 컷오프 이전이라는 이유만으로 사용하지 않는다. 실제 발표일이 컷오프 이전인지 확인한다.
- 가격과 NAV, 수익률 입력: 같은 상품·같은 기간·호환 가능한 기준일끼리만 계산한다.
- 개정 가능한 거시통계: 과거 빈티지를 제공하면 컷오프 시점 빈티지를 사용한다.

2026-07-11은 토요일이다. 공식 API를 직접 확인한 결과, ECOS 환율 `731Y001`과 시장금리 `817Y002`의 최신 적격 관측일은 2026-07-10이고, 효력 상태를 일별로 제공하는 한국은행 기준금리 `722Y001`에는 2026-07-11 레코드가 존재한다. 따라서 모든 시계열을 임의로 7월 10일이나 7월 11일로 통일하지 않는다.

## 3. 조건부 공식 API 후보 레지스트리

이 절은 연결 대상을 확정하는 목록이 아니다. 각 API는 아래의 `연결 조건`이 실제 평가 질문에서 발생하고, 같은 사실을 주최 측 데이터로 충족하지 못할 때만 구현 후보가 된다.

### 3.1 KRX OPEN API

- 게시기관: 한국거래소
- 공식 서비스 목록: <https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd>
- 이용 절차: <https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp>
- 인증: 회원가입, 인증키 신청, API별 활용 신청과 승인 필요
- 제공기간: 공식 서비스 목록상 2010년 이후가 기본
- 연결 조건: 국내 ETF의 같은 날 가격·NAV, 국내 상장증권 식별자, 국내 지수-ETF 관계가 필요한데 주최 측 값이 없거나 정의·기준일 검증에 실패한 경우
- 현재 판단: 일부 질문에 조건부 사용. 주최 측 AUM·상품정보를 단순히 최신 KRX 값으로 교체하기 위한 연결은 하지 않음

관련 API 후보:

| API | 활용 데이터 | 연결 질문 |
| --- | --- | --- |
| ETF 일별매매정보 | 종가, NAV, 거래량·거래대금, 시가총액, 순자산총액, 상장좌수, 기초지수명·지수값 | `CALC-DETF-001`의 동일일 가격·NAV, 필요 시 지수 관계 검증 |
| KRX·KOSPI·KOSDAQ 지수 일별시세 | 지수 수준과 일별 변동 | 현재 세트에서는 필수 아님; 향후 지수 자체 성과 질문이 추가될 때만 사용 |
| 유가증권·코스닥 종목기본정보와 일별매매정보 | 종목 ID, 종목명, 시장, 가격, 시가총액·거래 | ETF 편입종목 식별, 구성종목 설명, 유동성 보조 |
| 국채전문·일반채권·소액채권시장 일별매매정보 | 국내 상장채권 거래·시장 데이터 | 채권 거래현황, 시장수익률 보조, 현행성 확인 |

ETF 일별매매정보의 검증된 주요 출력 필드는 `BAS_DD`, `ISU_CD`, `ISU_NM`, `TDD_CLSPRC`, `NAV`, `ACC_TRDVOL`, `ACC_TRDVAL`, `MKTCAP`, `INVSTASST_NETASST_TOTAMT`, `LIST_SHRS`, `IDX_IND_NM`, `OBJ_STKPRC_IDX`다. API 응답 원문과 명세 버전을 보존한다.

**중요한 공백:** KRX는 ETF 시장 투명성을 위해 Portfolio Deposit File, NAV, 지수 구성내역 등이 KRX와 집합투자업자 웹사이트 등에 게시된다고 안내하지만, 현재 확인한 KRX OPEN API 서비스 목록에는 ETF PDF 구성내역 API가 별도 항목으로 없다. 따라서 구성종목은 KRX Data Marketplace 또는 운용사 공식 파일을 승인된 파일 원천으로 등록한다.

### 3.2 ECOS Open API

- 게시기관: 한국은행
- 공식 서비스: <https://ecos.bok.or.kr/api/>
- 조회 서비스: `StatisticTableList`, `StatisticItemList`, `StatisticSearch`
- 인증: 개발용 `sample`은 10건 제한, 실제 수집은 개인 인증키 필요
- 연결 조건: 서로 다른 통화의 AUM 또는 금액을 KRW로 환산해야 하는 질문
- 현재 판단: `CMP-AUM-001`, `AMB-AUM-001`의 `official_fx_snapshot`에만 우선 사용. 기준금리·시장금리·거시지표는 현재 52개 질문의 필수 입력이 아니므로 보류

관련 통계표와 항목 후보:

| 통계표 | 주기·항목 | 활용 데이터 |
| --- | --- | --- |
| `731Y001` 주요국 통화의 대원화환율 | 일별 `0000001` 원/미국달러 매매기준율, `0000002` 원/100엔, `0000003` 원/유로, `0000053` 원/위안 매매기준율 | 해외상품 AUM·수익률의 KRW 환산 |
| `722Y001` 한국은행 기준금리 및 여수신금리 | 일별 `0101000` 한국은행 기준금리 | 현재 보류; 질문이 기준금리를 명시할 때만 사용 |
| `817Y002` 시장금리(일별) | 국고채 1·5·10·20년, 콜금리, KORIBOR 등 | 현재 보류; 질문이 금리곡선·스프레드를 명시할 때만 사용 |
| `901Y009` 소비자물가지수 | 월별 총지수 `0` 등 | 현재 보류; 질문이 물가·실질금리를 명시할 때만 사용 |
| `200Y104` 경제활동별 GDP 및 GNI | 분기별 산업 항목 | 현재 보류; 질문이 공식 경기·산업 통계를 명시할 때만 사용 |

ECOS `StatisticSearch`의 검증 응답은 `STAT_CODE`, `STAT_NAME`, 항목 코드·명, `UNIT_NAME`, `TIME`, `DATA_VALUE`를 제공한다. 그러나 확인한 응답에는 FRED와 같은 과거 빈티지 구간이 포함되지 않는다. 수정 가능한 월·분기 통계는 공식 발표일 또는 당시 보관 파일을 추가로 확보하지 못하면 엄격한 `as known on 2026-07-11` 사실로 사용하지 않는다.

환율 우선순위는 ECOS를 1차 원천으로 한다. FRED `DEXKOUS`는 뉴욕시장 정오 매입률이므로 한국은행 매매기준율과 같은 지표가 아니다. 두 값을 평균내지 않고 차이가 있으면 정의 차이를 기록한다.

### 3.3 FRED API

- 게시기관: Federal Reserve Bank of St. Louis
- 공식 API 문서: <https://fred.stlouisfed.org/docs/api/fred/series_observations.html>
- 과거 빈티지 설명: <https://fred.stlouisfed.org/docs/api/fred/realtime_period.html>
- 인증: 등록 API 키 필요
- 연결 조건: 질문이 미국·글로벌 거시 시계열을 명시하고, 그 시계열이 상품 사실이나 주최 측 필드로 대체될 수 없는 경우
- 현재 판단: 52개 질문에는 직접 필요한 FRED 시계열이 없으므로 커넥터 구현과 수집을 보류

관련 시계열 후보:

| Series ID | 활용 데이터 |
| --- | --- |
| `EFFR` | 미국 연방기금 실효금리 |
| `DGS2`, `DGS10` | 미국 2년·10년 국채 상수만기 금리 |
| `DEXKOUS` | 원/미국달러 뉴욕시장 정오 환율의 교차검증 |
| `VIXCLS` | 미국 주식시장 단기 기대변동성 문맥; 원천 사용조건 확인 필요 |
| `CPIAUCSL` | 미국 소비자물가 문맥 |

FRED API의 기본 실시간 기간은 현재 날짜이므로 그대로 호출하면 안 된다. 컷오프 스냅샷은 최소한 다음 매개변수를 강제한다.

```text
observation_end=2026-07-11
realtime_start=2026-07-11
realtime_end=2026-07-11
```

이 설정은 컷오프 당시에 알려진 빈티지를 선택하기 위한 것이다. `series_id`, 원출처, 단위, 빈도, 계절조정, 관측일, 실시간 구간과 API 응답 체크섬을 보존한다.

FRED는 거시·시장 문맥용이다. 개별 해외 ETF의 보유종목, AUM, NAV, 보수, 분배금, 상품상태를 FRED에서 가져오지 않는다. 현재 질문 세트에서는 `DEXKOUS`도 필수 교차검증으로 수집하지 않는다. KRW 환산 질문에는 정의가 직접 맞는 ECOS 매매기준율을 사용하고, 별도 검증 목적이 승인될 때만 FRED 값을 추가한다.

### 3.4 API 밖의 공식 파일·문서 원천

공식 예상 질문 다수는 KRX·ECOS·FRED API만으로 답할 수 없다. 다음은 모든 후보를 자동 수집하는 목록이 아니다. Stage 03B 첫 범위는 ADR-0014에서 원문 위치, 과거 스냅샷, 이용조건과 bounded coverage를 검증하도록 승인했으며, 그 밖의 후보는 별도 승인을 유지한다.

| 후보 게시기관·원천 | 필요한 데이터 | 연결 질문 | 필수 검증 |
| --- | --- | --- | --- |
| 거래소·자산운용사 공식 구성파일 | 국내·해외 ETF 구성종목과 편입비중 | `REL-HOLD-*`, `REL-OETF-001`, `REL-CORP-001` | 상품·증권 ID, 적용일, 비중 합계, 파일 체크섬 |
| 법정 기업공시와 거래소 상장정보 | 모회사·자회사 관계, 상장 여부, 공식 기업명·식별자 | `REL-CORP-001` | 관계와 상장상태의 별도 기준일, 원문 위치 |
| 지수 제공기관·운용사 방법론과 공시 | 산업·테마 분류, 관계 이력, 지수·상품 연결 | `REL-THEME-001`, `REL-OETF-001`, `REL-IDX-001` | 분류 정의, 유효기간, 게시일, 개정 이력 |
| 감독기관·정책 시행기관·공식 운용주체 문서 | 국민성장펀드 구조·전략·동향 | `DOC-FUND-001` | 정확한 대상 식별, 게시일, 페이지·절, 컷오프 당시 공개 여부 |
| 운용사 투자설명서·상품 문서 | 상품 구조, 비용, 전략, 위험요인 | `DOC-FUND-001`, `REL-CORP-001`, 설명형 질문 | 문서 버전, 효력일, 상품 ID, 근거 구절 |

일반 뉴스와 검색 결과 요약은 원문 탐색에만 사용할 수 있다. 최종 Graph edge나 서술형 답변 주장은 위 공식 원문 중 하나에 연결돼야 한다.

## 4. 52개 질문에서 도출한 추가 데이터 우선순위

### P0: 없으면 핵심 질문을 풀 수 없는 데이터

| 데이터 | 1차 원천 | 현재 판정 | 사용 질문 |
| --- | --- | --- | --- |
| 국내 ETF 일별 가격·NAV | KRX ETF 일별매매정보 | API 제공 확인, 해당 질문에만 조건부 사용 | `CALC-DETF-001` |
| 국내 ETF 구성종목·편입비중 | KRX Data Marketplace 또는 운용사 PDF | OPEN API 공백, 공식 파일 필요 | 삼성전자 편입 ETF, 업종 비중, 포트폴리오 중첩 |
| 공모펀드 보유종목·편입비중 | 금융투자협회 자산운용보고서 또는 운용사 공식 | `requires_data`: 보고서 문서는 존재하나 exact share-class crosswalk·전수 coverage·통일 종목 스키마 미확정 | 국내·해외 ETF와 공모펀드의 특정 종목 보유 교차 질문 |
| 국내 주식·ETF·지수 식별자 | KRX 종목기본정보와 지수정보 | API 제공 확인 | 종목명·코드 해소, 지수 추종 관계 |
| KRW 환산 환율 | ECOS `731Y001` | API 제공과 컷오프 조회 확인, 교차통화 질문에만 사용 | `CMP-AUM-001`, `AMB-AUM-001` |
| 해외 ETF 동일기간 가격/NAV·분배금 | 해외 거래소·운용사 공식 원천 | KRX·ECOS·FRED로 미충족 | 해외 ETF 1년 성과, 동일일 괴리율 |
| 해외 ETF 구성종목과 기업·증권 별칭 | 해외 거래소·운용사 구성파일, 공식 식별 원천 | 세 API로 미충족 | `REL-OETF-001` 캠브리콘 편입 ETF |
| 기업 지배·종속 관계와 상장 상태 | 법정 기업공시와 거래소 상장정보 | 세 API로 미충족 | `REL-CORP-001` 에코프로 자회사 경로 |
| 시간 이력이 있는 테마·산업 관계 | 지수 제공기관·운용사 공식 방법론·공시 | 세 API로 미충족 | `REL-THEME-001` 최근 6개월 관계 |
| 공식 상품·정책 문서와 위험 근거 | 감독기관·정책기관·운용사 문서 | 세 API로 미충족 | `DOC-FUND-001`, `REL-CORP-001` |

### P1: 비교와 설명 정확도를 크게 높이는 데이터

| 데이터 | 1차 원천 | 사용 질문 |
| --- | --- | --- |
| 국내 지수-상품 매핑·구성종목 | KRX 지수정보·Data Marketplace, 공식 지수 제공기관 | `REL-IDX-001`; 지수 시계열 자체는 불필요 |
| ETF 비용·분배금·복제·환헤지 | KRX 상세정보 또는 운용사 공시 | 총보수, 분배정책, 유사상품 구조 비교 |
| 공모펀드 성과 기준일·클래스·전략 | 공식 펀드 공시·협회·운용사 원문 | `RANK-FUND-001`, `MIS-FUND-001`, `REL-SIM-FUND-001`, `REL-FUND-001` |
| 채권 등급·약정조건 기준일 | 공식 신용평가사·법정 공시 | `REL-SIM-BOND-001`, `MIS-BOND-001` |

### 보류: 새 질문이 생길 때만 검토하는 데이터

| 데이터 | 후보 원천 | 현재 보류 이유 |
| --- | --- | --- |
| 국내 기준금리·국고채 금리곡선 | ECOS `722Y001`, `817Y002` | 현재 질문은 상품 마스터의 채권 조건·수익률을 사용하며 거시금리를 요구하지 않음 |
| 미국 정책금리·국채곡선 | FRED `EFFR`, `DGS2`, `DGS10` | 현재 질문에 미국 금리 시계열 조건이 없음 |
| 한국·미국 물가와 GDP | ECOS, FRED | 현재 질문에 공식 거시통계 조건이 없음 |
| 국내채권 시장 일별 거래 | KRX 채권 일별 API | 현재 질문의 매수가능 여부는 주최 측 `BUYABLE_QUANTITY`를 기준으로 판정 |

### 별도 승인 필요: 세 API만으로 해결되지 않는 공식 데이터

| 데이터 공백 | 필요한 공식 원천 유형 |
| --- | --- |
| 공모펀드 운용사명, 대표펀드·클래스, 보수, 판매상태, 성과 기준일 | 감독기관·금융투자협회·예탁결제원·운용사 공식 공시 |
| 국내채권 신용등급과 등급 기준일 | 공식 신용평가사 또는 법정 공시 |
| 기업 지배·종속·자회사 관계 | 법정 기업공시 원문 |
| 해외 ETF 구성종목·NAV·보수·분배금 | 해당 거래소·운용사·감독기관 공식 원천 |
| 운용사·발행사 통합 기관 ID | 감독기관·거래소·법정 공시 기관 마스터 |
| 상품·정책 구조와 동향 | 감독기관·정책 시행기관·공식 운용주체 문서 |
| ETF 위험요인 | 운용사 투자설명서·상품 문서 |
| 기간이 있는 테마·산업 관계 | 지수 제공기관·운용사 방법론·공시 |

이 분류는 필요성이 낮다는 뜻이 아니다. 공식 예상 질문을 지원하는 P0 데이터도 포함되며, 세 API만으로 자동 연결할 수 없으므로 별도 출처 승인과 수집방식 검토가 필요하다는 뜻이다.

## 5. 기존 평가 요구사항과의 연결

| 요구사항 이름 | 우선 원천 | 상태 |
| --- | --- | --- |
| `official_fx_snapshot` | ECOS `731Y001` | 교차통화 질문에서만 ECOS API로 충족; FRED 교차검증은 기본 수집하지 않음 |
| `official_same_date_price_nav` | 국내 ETF는 KRX ETF 일별매매정보, 해외 ETF는 공식 거래소·운용사 | 국내 가능, 해외 공백 |
| `official_index_product_mapping` | KRX 지수·ETF 정보, 비KRX 지수는 공식 지수 제공기관 | 부분 충족 |
| `official_security_master` | KRX 종목기본정보 | 국내 상장증권 중심 충족 |
| `official_security_sector_classification` | KRX 공식 분류 또는 승인된 공식 지수·산업분류 | 분류체계 확정 필요 |
| `official_etf_holdings_snapshot` | KRX Data Marketplace 또는 운용사 공식 PDF·CSV | OPEN API가 아닌 공식 파일 수집 필요 |
| `official_etf_fee_snapshot` | KRX 상세정보 또는 운용사 공시 | OPEN API 제공필드 재검증 필요 |
| `official_return_methodology_and_dates` | KRX·운용사 방법론, 가격/NAV·분배 입력 | 상품군별 별도 확보 |
| `official_fund_performance_snapshot` | 공식 펀드 공시 | 세 API로 미충족 |
| `official_fund_class_master` | 공식 펀드 공시 | 세 API로 미충족 |
| `official_public_fund_strategy_and_benchmark_snapshot` | 공식 펀드 공시·운용사 투자설명서 | 세 API로 미충족 |
| `official_credit_rating_snapshot` | 공식 신용평가사·법정 공시 | 세 API로 미충족 |
| `official_bond_rating_and_terms_snapshot` | 공식 신용평가사·채권 발행 공시 | 세 API로 미충족 |
| `official_institution_master` | KRX와 감독기관·법정 공시 | 부분 충족 |
| `official_institution_and_performance_snapshots` | 기관 마스터와 상품군별 공식 성과 공시를 별도 결합 | 단일 API로 충족되지 않음 |
| `official_product_document_corpus` | 감독기관·정책기관·운용사·거래소 공식 문서 | 공식 예시 지원을 위해 필수, 원문 위치 확정 필요 |
| `official_temporal_theme_relation_snapshot` | 지수 제공기관·운용사 공식 방법론·공시 | 최근 6개월 관계 질문에 필수 |
| `official_corporate_control_and_listing_snapshot` | 법정 기업공시와 거래소 상장정보 | 자회사→편입 ETF 경로에 필수 |

## 6. 공통 적재 스키마

```text
source_id
publisher
api_or_document_name
endpoint_or_document_id
series_or_api_id
subject_id
metric_or_relation
raw_value
normalized_value
unit
currency
frequency
applicable_date
period_start
period_end
published_at
available_at
vintage_date
retrieved_at
snapshot_cutoff
selection_method
availability_status
content_checksum
parser_version
mapping_version
license_or_usage_note
```

API 키는 환경변수나 비밀 저장소에만 두며 URL, 로그, 문서, 테스트 fixture에 기록하지 않는다.

## 7. 연결·수집 결정 게이트

다음 조건을 모두 만족한 소스만 연결한다.

1. 하나 이상의 승인된 질문 ID가 해당 데이터 없이는 정확히 답할 수 없다.
2. 주최 측 마스터의 필드가 없거나, 결측·정의·기준일 문제로 사용할 수 없다는 근거가 있다.
3. 후보 원천이 필요한 금융적 정의와 식별자를 실제로 제공한다.
4. 2026-07-11 이후 관측값뿐 아니라 이후에 처음 공개된 정보도 차단할 수 있다.
5. 사용조건, 저장범위, 인증방식과 비용이 승인된다.
6. 예상 지원 질문 수와 구현비용을 비교해 우선순위가 승인된다.

이 게이트를 통과하지 못한 API는 커넥터, 주기 수집, 스키마를 미리 만들지 않는다.

## 8. 구현 전 검증 항목

- 연결이 승인된 모든 API 요청은 종료일 또는 관측일을 `2026-07-11` 이하로 강제한다.
- FRED 요청은 현재 빈티지 기본값을 사용하지 않는다.
- KRX 휴장일에는 컷오프 이전 최신 거래일을 선택하고 실제 `BAS_DD`를 표시한다.
- ECOS는 통계표·항목·주기·단위를 allowlist로 고정한다.
- 월·분기 값은 발표일 검증 없이 기간명만 보고 사용하지 않는다.
- 같은 통계의 다른 정의나 원천을 평균내지 않는다.
- API 응답이 컷오프 이후 레코드를 포함하면 적재 단계에서 거절한다.
- 공식 파일 원천은 적용일, 게시일, 체크섬과 상품 식별자 연결률을 검증한다.
- 원시 API 응답과 파생 DB는 Git에 넣지 않는다.

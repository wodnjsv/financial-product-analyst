# 금융상품 Agent 공식 추가 데이터 요구사항

**Date:** 2026-08-10

**Status:** Approved Task 1 requirements; concrete source activation deferred to ADR-0008

**Snapshot cutoff:** Superseded by `2026-08-24` under [ADR-0016](../decisions/ADR-0016-use-2026-08-24-organizer-baseline.md). Older literal dates below remain historical requirement text until the source recapture plan is approved.

## 1. 기준

이 문서는 주최 측 제공 마스터만으로 답할 수 없는 평가 질문과 이를 보완할 공식 데이터 요구사항을 연결한다. 주최 측 마스터의 필드 의미와 한계는 다음 네 문서를 기준으로 판정한다.

- [국내채권 마스터](../../reference/domestic-bond-master.md)
- [국내 ETF 마스터](../../reference/domestic-etf-master.md)
- [해외 ETF 마스터](../../reference/overseas-etf-master.md)
- [공모펀드 마스터](../../reference/public-fund-master.md)

외부 데이터는 주최 측 데이터에 없는 관계나 필드를 채우기 위한 것이다. 같은 필드가 충돌할 때 외부 값으로 주최 측 값을 조용히 덮어쓰지 않는다.

구체적인 공식 소스 후보와 연결 여부는 [필요 기반 공식 데이터·API 소스 매트릭스](official-api-source-matrix.md)에 기록한다. KRX·ECOS·FRED는 필수 연결 목록이 아니라 질문별 데이터 공백을 충족할 때만 선택하는 후보군이다.

주최측 과제설명·기술세션에서 추가로 확인된 비정형 문서, 지식 그래프, 답변 불가 판정 요구는 [공식 과제·기술 요구사항](../../reference/official-competition-requirements.md)을 기준으로 한다.

## 2. 공식성 수용 기준

최종 답변의 금융 사실을 뒷받침하는 외부 출처는 다음 중 하나여야 한다.

1. 금융 감독기관, 거래소, 법정 공시 시스템
2. 상품 발행사 또는 자산운용사가 직접 공개한 공식 파일·공시·상품 문서
3. 지수 제공기관이 직접 공개한 공식 지수 문서나 구성내역
4. 신용평가사가 직접 공개한 공식 등급 정보
5. 중앙은행 또는 공공기관이 직접 공개한 공식 환율·시장 통계

뉴스, 블로그, 검색 결과 요약, 생성형 AI 답변, 출처가 불명확한 재가공 데이터는 원문 탐색 보조로만 사용하고 증거 원장에는 넣지 않는다.

## 3. 2026-07-11 스냅샷 규칙

- 평가용 데이터셋은 `2026-07-11` 시점에서 동결한다.
- 원천 레코드의 실제 `applicable_date` 또는 `as_of`는 반드시 별도로 저장한다.
- 기준일에 공식 파일이 없으면 `2026-07-11` 이전의 최신 공식 레코드를 선택한다.
- 가능한 경우 `available_at`, `published_at`, `vintage_date`도 모두 `2026-07-11` 이하여야 한다.
- 선택한 값이 언제 측정된 것인지 답변과 증거에 표시한다.
- `2026-07-11` 이후 게시·정정된 데이터는 평가 스냅샷에 섞지 않는다.
- 월·분기·연간 값은 표시 기간이 컷오프 이전이어도 실제 발표일이 컷오프 이후라면 사용하지 않는다.
- 과거 시점 빈티지를 재현할 수 없고 현재 수정치만 조회되는 값은 `latest_revised_after_cutoff`로 표시하고 엄격한 과거시점 답변에서 제외한다.
- 원천 파일, 수집 응답, 파생 DB, 로그는 Git에 넣지 않는다.

## 4. 공통 계보 스키마

모든 외부 데이터 레코드는 다음 메타데이터를 가진다.

```text
source_id
publisher
publisher_type
source_title
source_url_or_document_id
published_at
available_at
applicable_date
vintage_date
retrieved_at
content_checksum
parser_version
mapping_version
license_or_usage_note
snapshot_cutoff
availability_status
selection_method
```

금융 사실에는 추가로 `subject_id`, `predicate`, `value_or_object_id`, `unit`, `currency`, `source_locator`를 연결한다. `source_locator`는 파일의 시트·행·열, 문서 페이지·표, 또는 API 레코드 키처럼 원문 위치를 재현할 수 있어야 한다.

## 5. 추가 데이터 우선순위

### P0: ETF 구성종목과 편입비중

**필수 질문 예시**

- 삼성전자가 편입된 국내 ETF를 AUM 순으로 5개
- 특정 산업 비중이 높은 ETF
- 특정 종목과 그 자회사를 함께 편입한 ETF
- 기준 ETF와 구성종목이 유사한 ETF

**현재 마스터 상태**

- 국내·해외 ETF의 상품 ID, 운용사, AUM, 자산군·지역은 일부 존재한다.
- ETF 구성종목, 종목별 편입비중, 구성 기준일은 없다.

**필수 스키마**

```text
etf_product_id
constituent_security_id
constituent_name
weight_pct_or_quantity
holding_value
holding_currency
applicable_date
source_id
source_locator
```

**수용 가능한 게시기관 유형**

- 거래소
- ETF 자산운용사
- 해당 ETF의 법정 공시 시스템

**연결 규칙**

- 국내 ETF는 `pd_itm_no`를 우선 연결키로 사용한다.
- 해외 ETF는 `pd_itm_no`를 내부 대표키로 유지하고 유효한 ISIN·티커를 보조 연결키로 사용한다.
- 종목명만으로 자동 결합하지 않고 표준 종목 ID를 우선한다.
- 편입비중 합계와 기준일을 검증하며 현금·파생·기타 항목을 일반 주식과 구분한다.

### P0: 증권·기업·기관 식별자 마스터

**필수 질문 예시**

- 특정 기업이 들어간 ETF
- 특정 운용사의 상품
- 특정 기업의 자회사를 편입한 ETF
- 동일 발행사 채권과 관련 ETF 비교

**현재 마스터 상태**

- 상품마다 자체 식별자는 있으나 상품군 간 공통 기업·기관 ID가 없다.
- 공모펀드는 운용사 코드가 있지만 현재 운용사 명칭 매핑이 없다.

**필수 스키마**

```text
entity_id
entity_type
official_name
aliases
registration_or_market_ids
valid_from
valid_to
source_id
```

**수용 가능한 게시기관 유형**

- 감독기관·거래소·법정 공시 시스템
- 상품 발행사·자산운용사의 공식 회사 정보

### P0: 동일 기준일 가격·NAV·성과 입력

**필수 질문 예시**

- ETF 괴리율 계산
- 기간수익률 비교
- 해외 ETF와 국내 ETF의 동일 기간 성과 비교
- 수익률 상위 상품과 유사상품 탐색

**현재 마스터 상태**

- 국내 ETF는 기간수익률이 있으나 정의 확인이 필요하고 `-100` 센티널 후보가 있다.
- 해외 ETF는 유효한 1년 수익률이 없고 종가·NAV 기준일이 다르다.
- 공모펀드는 1년 수익률이 있지만 성과 기준일이 없다.

**필수 스키마**

```text
product_id
metric_type
metric_value
unit
currency
price_or_nav_basis
distribution_treatment
applicable_date
source_id
```

**수용 가능한 게시기관 유형**

- 거래소·감독기관
- 상품 발행사·자산운용사
- 공식 기준가·공시 시스템

**수익률 정규화에 필요한 의미 정보**

- 별도 정의가 없는 `연간수익률`의 기본 지표는 최근 1년 역사적 누적수익률이다.
- 공식 가격·NAV·분배금 입력으로 같은 기간 값을 재현할 때는 시작·종료일, 분배금 처리, 세전·세후 기준, 통화, 계산식을 함께 저장한다.
- 여러 해의 누적수익률을 CAGR로 바꿀 때는 완전한 기간 길이와 누적수익률 원천이 있어야 한다.
- 채권 YTM, 표면금리, 현재수익률 같은 기대·조건부 연율은 `historical_return`과 다른 `metric_family`로 저장한다.
- 서로 다른 `metric_family`를 하나의 동질적인 순위로 위장하지 않고, 분리 비교 또는 명시적 제한을 적용한다.

### P0: 공식 상품·정책 문서와 위험 근거

**필수 질문 예시**

- 국민성장펀드의 구조·투자전략·동향
- 에코프로 자회사를 편입한 ETF 중 AUM이 큰 상품의 위험요인
- 상품 전략과 보수·추적오차 위험을 함께 설명

**현재 마스터 상태**

- 상품 설명, 정책 구조, 투자전략 동향과 위험요인을 완결된 문장 근거로 제공하지 않는다.
- 상품명·전략·보수·위험 내용이 서로 다른 PDF 페이지나 표에 있을 수 있다.
- 기존 P2 보조자료가 아니라 공식 예상 질문을 직접 지원하는 필수 데이터다.

**필수 스키마**

```text
document_id
publisher
document_type
title
subject_product_or_entity_id
published_at
available_at
effective_date
source_id
content_checksum
page_or_section_map
chunk_id
parent_chunk_id
preceding_context
evidence_span
parser_version
```

**수용 가능한 게시기관 유형**

- 감독기관·법정 공시 시스템·정책 시행기관
- 상품 발행사·자산운용사의 공식 투자설명서와 상품 문서
- 거래소·지수 제공기관의 공식 방법론·공시

문서 청크에는 반드시 부모 상품 또는 엔티티 ID와 페이지·절을 연결한다. `본 펀드`, `이 상품` 같은 표현을 독립 청크의 단독 엔티티로 해석하지 않는다. Vector 검색은 후보 문서를 찾는 데 사용하고 최종 주장은 정확한 문서 위치와 날짜로 검증한다.

### P0: 시간 이력이 있는 테마·산업·상품 관계

**필수 질문 예시**

- 최근 6개월 동안 우주항공 테마와 연결 이력이 있는 ETF
- 특정 기간에 테마·지수·전략 변경 이력이 있는 상품

**현재 마스터 상태**

- 현재 분류값 일부만 있고 관계가 언제 생성·변경·종료됐는지 알 수 없다.
- `최근 6개월` 같은 시간 조건을 검증할 공식 관계 이력과 근거 문서가 없다.

**필수 스키마**

```text
relation_assertion_id
subject_entity_id
relation_type
object_entity_id
valid_from
valid_to
announced_at
published_at
available_at
source_id
source_locator
extraction_method
ontology_mapping_version
```

관계는 이름이나 문서 임베딩의 유사성만으로 확정하지 않는다. 공식 지수 방법론, 상품 공시, 운용사 문서처럼 관계를 명시하거나 재현 가능한 분류를 제공하는 원문이 필요하다. 기간의 시작과 끝은 평가 컷오프 `2026-07-11`을 넘을 수 없다.

### P0: 기업 지배·종속·상장·산업 관계

**필수 질문 예시**

- 에코프로의 상장 자회사를 편입한 ETF
- 동일 그룹 계열사 노출이 큰 상품
- 특정 산업 공급망 기업을 편입한 상품

**현재 마스터 상태**

- 기업 관계와 산업 관계가 없다.

**필수 스키마**

```text
parent_entity_id
relation_type
child_entity_id
valid_from
valid_to
listing_status
listing_market
relation_assertion_id
source_id
source_locator
```

관계는 공시상 지배·종속, 공식 상장정보 또는 공식 분류처럼 재현 가능한 정의만 사용한다. 모회사·자회사 관계와 상장 여부는 같은 사실이 아니므로 각각의 기준일과 원천을 보존한다. `성장기업`, `핵심기업` 같은 판단적 표현은 별도 공식 분류나 명시된 규칙이 없으면 사실 관계로 저장하지 않는다.

### P1: ETF·펀드 비용과 분배 정책

**필수 질문 예시**

- 총보수가 낮은 유사 ETF
- 분배주기가 같은 상품 비교
- 공모펀드 클래스별 비용 비교

**현재 마스터 상태**

- 국내 ETF 총보수는 저충족이며 단위·비용범위 확인이 필요하다.
- 공모펀드는 총보수·판매수수료·환매수수료를 정확히 답할 수 없다.
- 국내 ETF 분배금·분배주기 필드는 사용할 수 없다.

**필수 스키마**

```text
product_or_share_class_id
fee_type
fee_value
unit
distribution_frequency
distribution_policy
applicable_date
source_id
```

### P1: 기초지수와 지수 구성정보

**필수 질문 예시**

- 같은 지수를 추종하는 ETF
- 특정 지수에 포함된 기업과 이를 추종하는 ETF
- 지수·ETF·편입종목을 잇는 다단계 질문

**현재 마스터 상태**

- 국내 ETF 기초지수는 대부분 결측이다.
- 해외 ETF 기초지수에는 문장형 결측이 대량 포함돼 있다.

**필수 스키마**

```text
index_id
index_name
index_provider
constituent_security_id
constituent_weight
effective_date
linked_product_id
source_id
```

### P1: 공식 환율

**필수 질문 예시**

- 원화와 달러 AUM을 동일 통화로 환산해 순위 비교
- 외화채권과 원화상품 규모 비교

**현재 마스터 상태**

- 상품통화는 있으나 승인된 환율 원천과 환산 기준일이 없다.

**필수 스키마**

```text
base_currency
quote_currency
rate
rate_type
applicable_date
source_id
```

**고정 적용 규칙**

- 기본 비교·표시 통화는 KRW다.
- 평가 환율 컷오프는 2026-07-11이다.
- 당일 승인된 공식 관측값이 없으면 그 이전의 최신 공식 관측값만 사용한다.
- 실제 관측일을 2026-07-11로 바꾸어 표기하지 않는다.
- 환산 증거에는 `base_currency`, `quote_currency`, `rate`, `rate_type`, `applicable_date`, 공식 게시기관, 원문 식별자, 수집 체크섬, 환산 공식을 포함한다.
- 서로 다른 공식 환율 종류가 존재하면 ADR-0008의 승인된 종류만 사용하며 임의 평균을 만들지 않는다.

환율 원천이 승인되기 전에는 통화가 다른 AUM을 직접 합산하거나 순위화하지 않는다. 승인 후에는 위 규칙으로 KRW 환산한 값을 사용하고 실제 환율 관측일과 출처를 답변에 표시한다.

### P1: 공모펀드 기관·클래스·판매정보

**필수 질문 예시**

- 특정 운용사의 1년 수익률 상위 공모펀드
- 동일 대표펀드의 클래스별 비용·판매채널 비교
- 현재 판매 가능한 대표 클래스만 표시

**현재 마스터 상태**

- 운용사 코드와 대표펀드 연결키는 있으나 운용사 이름, 클래스 의미, 비용 정의가 부족하다.

**필수 스키마**

```text
manager_id
manager_name
representative_fund_id
share_class_id
share_class_type
fee_schedule
sale_channel
sale_status
applicable_date
source_id
```

### P1: 채권 발행·등급·현행성 보완

**필수 질문 예시**

- 특정 발행사의 매수 가능 채권 중 수익률 상위
- 신용등급과 잔존만기가 비슷한 채권
- 동일 그룹 발행사 채권 비교

**현재 마스터 상태**

- 신용등급과 매수수익률의 결측이 크고 대표등급 선정 규칙과 판매 현행성 정의가 부족하다.

**필수 스키마**

```text
bond_product_id
issuer_id
rating_agency
rating
rating_date
issue_terms
availability_status
applicable_date
source_id
```

## 6. 질문-데이터 연결 원칙

각 평가 질문에는 다음 판정을 기록한다.

```text
available_from_organizer
available_from_approved_external_source
missing_but_mandatory
unsupported_by_design
```

`missing_but_mandatory` 질문은 최종 제출 전에 공식 소스를 확보해야 한다. `unsupported_by_design`은 예측, 개인화 추천, 공식 근거가 없는 분류처럼 데이터를 더 넣어도 제공하지 않을 기능이다.

외부 원천은 아래 순서로 선택한다.

1. 질문 ID와 필요한 사실·관계·계산 입력을 확정한다.
2. 주최 측 필드의 존재, 유효값 충족률, 정의, 기준일을 확인한다.
3. 부족한 항목만 공식 원천 후보에 매핑한다.
4. 컷오프 당시 공개된 값임을 검증할 수 있는 최소 원천을 선택한다.
5. 어떤 승인 질문에도 연결되지 않는 API나 데이터는 수집하지 않는다.

공식 예상 질문을 반영한 현재 52개 질문과 세 API 후보·공식 파일 원천의 직접 연결은 다음과 같다.

| 질문·요구사항 | 필요한 추가 데이터 | 조건부 후보 | 판단 |
| --- | --- | --- | --- |
| `REL-HOLD-001`~`004`, `REL-MGR-001` | ETF 구성종목·편입비중 | KRX Data Marketplace 또는 운용사 공식 파일 | 필수 공백이지만 KRX OPEN API·ECOS·FRED로는 충족되지 않음 |
| `REL-OETF-001` | 캠브리콘 공식 기업·증권 ID, 중국·반도체 분류, 해외 ETF 구성종목 | 해외 거래소·운용사 구성파일, 공식 증권·기업 식별 원천 | 세 API만으로 충족되지 않음 |
| `REL-THEME-001` | 최근 6개월의 우주항공 테마 관계 이력 | 운용사·지수 제공기관의 공식 방법론·공시 | 관계 유효일과 문서 근거가 필요 |
| `REL-CORP-001` | 에코프로 자회사·상장 관계, ETF 구성종목, 위험 문서 | 법정 기업공시·거래소·운용사 문서 | Graph·RDB·Vector 결합 필요 |
| `DOC-FUND-001` | 국민성장펀드 구조·전략·동향 공식 문서 | 감독기관·정책 시행기관·공식 운용주체 문서 | 문서 게시일과 페이지·절 근거 필요 |
| `CALC-DETF-001` | 국내 ETF 동일일 종가·NAV | KRX ETF 일별매매정보 | 주최 측 값의 동일일 사용 가능성이 입증되지 않을 때만 연결 |
| `CMP-AUM-001`, `AMB-AUM-001` | KRW 환산 환율 | ECOS `731Y001` | 교차통화 순위를 실제 수행할 때만 연결 |
| `REL-IDX-001` | 지수-상품 매핑 | KRX 지수·ETF 정보와 공식 지수 제공기관 | 국내 상장 부분에 조건부 사용 |
| 공모펀드 성과·클래스·전략 질문 | 성과 기준일, 클래스 의미, 벤치마크 | 공식 펀드 공시·협회·운용사 | 세 API로 충족되지 않음 |
| 채권 유사도·결측등급 질문 | 등급·조건·기준일 | 공식 신용평가사·법정 공시 | 세 API로 충족되지 않음 |
| 현재 52개 질문 전체 | 미국 금리·물가·경기 시계열 | FRED | 직접 요구 질문이 없어 보류 |
| 현재 52개 질문 전체 | 한국 기준금리·금리곡선·GDP | ECOS | 직접 요구 질문이 없어 보류 |
| `UNS-GRADE-001`, `UNS-ENTITY-001`, `UNS-PRODUCT-001` | 추가 사실이 아니라 답변 불가 판정 규칙 | 온톨로지 허용값·기준일 엔티티 인덱스·근거 관계 검사 | 외부 일반검색으로 억지 보완하지 않음 |

유사상품 질문은 적용한 `similarity_policy_id`와 각 점수축의 원천을 함께 기록한다. 한 축에 필요한 값이 주최 측과 승인된 공식 외부 데이터 어디에도 없으면 그 축을 일치로 처리하거나 텍스트 임베딩으로 대체하지 않는다. 계산 가능한 가중치 비율인 `score_coverage`가 60% 미만이면 숫자 순위를 만들지 않는다.

특히 ETF 구성종목 중첩은 같은 공식 증권 식별자로 연결된 편입비중만 사용하고, 두 상품의 정규화 편입비중 중 작은 값의 합으로 계산한다. 공모펀드 전략·벤치마크와 채권 발행주체·등급·잔존만기·금리구조·수익률도 각 원천의 실제 적용일과 정의를 보존해야 한다.

## 7. 구현 전 승인 게이트

각 외부 데이터셋을 실제로 수집하기 전에 다음을 사용자와 확정한다.

1. 공식 게시기관과 원문 위치
2. 2026-07-11 컷오프에 맞는 스냅샷 확보 가능성
3. 상품·증권·기관 식별자 연결률
4. 사용 조건과 저장 가능 범위
5. 주최 측 값과 충돌할 때의 처리
6. 해당 데이터가 지원할 질문 유형과 평가 가치
7. 외부 원천 없이 주최 측 데이터만으로 답할 수 없는 이유

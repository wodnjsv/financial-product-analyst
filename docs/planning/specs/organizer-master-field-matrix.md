# 주최 측 4개 마스터 필드 매핑 매트릭스

**Date:** 2026-08-20

**Status:** Superseded historical matrix — use [2026-08-24 280-field matrix](organizer-master-field-matrix-2026-08-24.md)

**Cutoff:** 2026-07-11
**Scope:** `PRBD01N001`, `PREF01N001`, `PREF02N001`, `PRFD01N001`의 실제 데이터 컬럼 207개

## 1. 검증 결과

원본은 로컬의 무시된 `data/` 디렉터리에서 읽기 전용 `openpyxl` 모드로 확인했다. 행 값은 출력하거나 저장소에 복사하지 않았다. 네 데이터 워크북의 첫 행과 대응 스키마 워크북 `Sheet1_Schema`의 필드 순서를 비교한 결과는 다음과 같다.

| 소스 | 데이터 헤더 | 스키마 필드 | 순서까지 일치 |
| --- | ---: | ---: | --- |
| `PRBD01N001` 국내채권 | 40 | 40 | 예 |
| `PREF01N001` 국내 ETF·ETN | 73 | 73 | 예 |
| `PREF02N001` 해외 ETF·ETN | 49 | 49 | 예 |
| `PRFD01N001` 공모펀드 | 45 | 45 | 예 |
| **합계** | **207** | **207** | **예** |

따라서 **207개는 네 데이터 마스터의 실제 컬럼 수를 모두 합한 값**이다. 네 스키마 워크북은 별도 데이터 컬럼을 추가하는 파일이 아니라 이 207개 컬럼의 이름·타입·설명을 정의한다.

## 2. 읽는 법과 공통 규칙

분류는 아래 여섯 값만 사용한다.

| 분류 | 의미 |
| --- | --- |
| `identifier` | 상품 또는 기관을 찾는 원천 식별자 |
| `catalog` | 이름·별칭·상품군·기준통화 같은 카탈로그 사실 |
| `relation` | 승인된 온톨로지 predicate로 표현할 수 있는 관계 |
| `observation` | 타입·단위·기준일이 명시된 관측값 |
| `evidence_only` | 원본 근거는 보존하지만 직접 검색·순위·비교에는 출시하지 않는 값 |
| `ignored` | 현재 스냅샷에서 답변에 쓰지 않는 값 |

표기 규칙은 다음과 같다.

- `obs:<metric>@1[<kind>]`는 Stage 02 `metric_definition`의 `definition_version=1`과 `numeric|text|boolean|date|timestamp` 값 종류를 뜻한다.
- `catalog`와 `identifier` 중 답변 근거가 되는 값은 Stage 02 Evidence origin 제약 때문에 같은 값을 담은 companion text observation도 만든다.
- 근거 `Y`는 정규화 사실과 정확한 workbook·sheet·row·column locator를 Evidence로 만든다는 뜻이다. `L`은 Evidence는 만들지만 직접 검색·순위·비교에 출시하지 않는다는 뜻이고, `N`은 만들지 않는다는 뜻이다.
- `vintage=2026-07-11`은 파일 추출 컷오프일 뿐 값의 측정일을 뜻하지 않는다. 필드별 기준일이 없으면 `applicable_date`는 비워 둔다.
- 빈 Boolean은 `False`가 아니다. 명시된 `Y/N`, `1/0`만 변환하고 나머지는 `missing` 또는 `unknown`이다.
- 이름만 같은 기관을 소스 간 병합하지 않는다. 03A의 기관은 source-local entity이며, 03B에서 공식 식별자가 확인될 때만 통합한다.
- `listedOn`은 현재 Stage 02 catalog가 `Market` entity type을 지원하지 않으므로 만들지 않는다. 거래소·시장 값은 text observation으로 보존한다.
- 원본 단위가 확인되지 않은 숫자는 임의 환산하지 않고 원단위와 제한 사유를 함께 보존한다.

## 3. 국내채권 `PRBD01N001` — 40개

| 원천 필드 | 원천 타입 | 분류 | 저장 대상 | 값 상태 규칙 | 날짜·기간 | 단위 | 통화 | 근거 | 판단·주의 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `PD_NO` | text | identifier | `catalog.identifier(PRBD_PD_NO)` + `obs:organizer.prbd01n001.product_id@1[text]` | trim 후 빈칸은 행 격리 | 정적; vintage만 기록 | — | — | Y | 전 행 고유·비결측인 자연키 |
| `PD_EXG_MKT` | text | observation | `obs:organizer.prbd01n001.exchange_market_type@1[text]` | 빈칸→missing | applicable 없음 | — | — | Y | 장내·장외 구분이며 발행시장으로 해석하지 않음 |
| `PD_NM` | text | catalog | `catalog.entity.canonical_name` + `obs:organizer.prbd01n001.name_ko@1[text]` | trim; 빈칸은 행 격리 | 정적 | — | — | Y | 검색·표시 이름, 식별키 아님 |
| `PD_ABRV_NM` | text | catalog | `catalog.alias` + `obs:organizer.prbd01n001.short_name_ko@1[text]` | trim; 빈칸→missing | 정적 | — | — | Y | 단축 한글명 |
| `PD_ENG_NM` | text | catalog | `catalog.alias` + `obs:organizer.prbd01n001.name_en@1[text]` | trim; 빈칸→missing | 정적 | — | — | Y | 영문 표시 보조값 |
| `PD_ABRV_ENG_NM` | text | catalog | `catalog.alias` + `obs:organizer.prbd01n001.short_name_en@1[text]` | trim; 빈칸→missing | 정적 | — | — | Y | 영문 단축명 |
| `PD_CTRY_CD` | text | evidence_only | `obs:organizer.prbd01n001.country_code_raw@1[text]` | 빈칸→missing | applicable 없음 | — | — | L | 발행국·등록국 중 의미가 확인되지 않음 (`UNDEFINED_SOURCE_SEMANTICS`) |
| `PD_PBCM` | text | relation | source-local institution + `issuedBy` | trim; 빈칸이면 관계 없음 | applicable 없음 | — | — | Y | 발행주체 관계. 소스 간 동명이인 병합 금지 |
| `STD_PD_MCLS_NM` | text | observation | `obs:organizer.prbd01n001.product_major_class@1[text]` | 빈칸→missing | applicable 없음 | — | — | Y | 주최 측 대분류 그대로 보존 |
| `STD_PD_SCLS_NM` | text | observation | `obs:organizer.prbd01n001.product_subclass@1[text]` | 빈칸→missing | applicable 없음 | — | — | Y | 주최 측 소분류 그대로 보존 |
| `BD_KND` | text | observation | `obs:organizer.prbd01n001.bond_kind@1[text]` | 빈칸→missing | applicable 없음 | — | — | Y | 구체 채권 종류; 임의 재분류 금지 |
| `CURR_CD` | text | catalog | `catalog.product.primary_currency` + `obs:organizer.prbd01n001.currency@1[text]` | `000`→unknown; 빈칸→missing | applicable 없음 | — | ISO 4217 원문 | Y | `000`을 통화로 사용하지 않음 |
| `ISU_BAL_AMT` | double precision | observation | `obs:organizer.prbd01n001.issue_balance@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음 | 원천 발행잔액 단위 | `CURR_CD` | Y | 금액 배율이 확인되기 전 임의 환산 금지 |
| `ISU_DT` | double precision | observation | `obs:organizer.prbd01n001.issue_date@1[date]` | `YYYYMMDD`만 present; 0→placeholder; 빈칸→missing | 값 자체가 날짜 | — | — | Y | 유효 날짜만 변환 |
| `MAT_DT` | double precision | observation | `obs:organizer.prbd01n001.maturity_date@1[date]` | `YYYYMMDD`만 present; 0·`99991231`→placeholder | 값 자체가 날짜 | — | — | Y | 센티널을 실제 만기일로 만들지 않음 |
| `SRFC_IRT` | double precision | observation | `obs:organizer.prbd01n001.coupon_rate@1[numeric]` | 빈칸→missing; 0→zero | 계약 조건; applicable 없음 | percentage point | — | Y | 거래수익률과 구분 |
| `PD_EVCO_CRD_GRD` | text | observation | `obs:organizer.prbd01n001.credit_grade_raw@1[text]` | trim; 빈칸→missing | applicable 없음 | — | — | Y | 평가사별 결합 문자열을 분해·대표화하지 않음 |
| `PD_RISK_GCD` | bigint | observation | `obs:organizer.prbd01n001.risk_grade_code@1[text]` | 0 포함 원코드를 text로 보존; 빈칸→missing | applicable 없음 | code | — | Y | 신용등급과 다른 상품 위험코드 |
| `PD_STD_INFO_UPDATE` | double precision | observation | `obs:organizer.prbd01n001.standard_info_updated_on@1[date]` | `YYYYMMDD`만 present; 0→placeholder; 빈칸→missing | 값 자체가 갱신일 | — | — | Y | 모든 시장지표의 기준일로 전파하지 않음 |
| `BUY_YIELD` | double precision | observation | `obs:organizer.prbd01n001.buy_yield@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음; vintage만 기록 | percentage point | — | Y | 주체 정의 불명확, 881행 한정 |
| `CORP_PRETAX_YIELD` | double precision | observation | `obs:organizer.prbd01n001.corporate_pretax_yield@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음; vintage만 기록 | percentage point | — | Y | 법인 기준 정의 확인 전 제한 표시 |
| `CORP_AFTER_TAX_YIELD` | double precision | observation | `obs:organizer.prbd01n001.corporate_after_tax_yield@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음; vintage만 기록 | percentage point | — | Y | 적용 세율·과세방식 미확인 |
| `AFTER_TAX_YIELD` | double precision | observation | `obs:organizer.prbd01n001.after_tax_yield@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음; vintage만 기록 | percentage point | — | Y | 투자자 유형 미확인 |
| `PREF_TAX_YIELD` | double precision | observation | `obs:organizer.prbd01n001.preferential_tax_yield@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음; vintage만 기록 | percentage point | — | Y | 우대세율·대상 미확인 |
| `AVG_ANNUAL_TAX_YIELD` | double precision | ignored | — | 채워진 값 전부 0→unavailable | — | — | — | N | `UNUSABLE_ALL_ZERO_SERIES` |
| `DEPO_EQUIV_YIELD_154` | double precision | observation | `obs:organizer.prbd01n001.deposit_equivalent_yield_154@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음; vintage만 기록 | percentage point | — | Y | 15.4% 세율 기준 원천값 그대로 사용 |
| `BUYABLE_QUANTITY` | double precision | observation | `obs:organizer.prbd01n001.buyable_quantity@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음; vintage만 기록 | 원천 수량/액면 단위 | — | Y | 현재 매수 가능 확정값으로 표현하지 않음 |
| `REMAINING_DAYS` | double precision | ignored | — | 원천값 미사용 | — | — | — | N | `NO_TRUSTED_TIME_BASIS`; 유효 만기일과 질의 기준일로 재계산 |
| `DUR` | double precision | evidence_only | `obs:organizer.prbd01n001.duration_raw@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음 | source-defined | — | L | 수정·맥컬리 정의와 기준일 불명확 |
| `COV` | double precision | evidence_only | `obs:organizer.prbd01n001.convexity_raw@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음 | source-defined | — | L | 산식·단위·기준일 불명확 |
| `NDY_DUR` | double precision | evidence_only | `obs:organizer.prbd01n001.next_business_day_duration_raw@1[numeric]` | 빈칸→missing; 0→zero | 다음 영업일로 표시; 실제 날짜 없음 | source-defined | — | L | 전망치로 표현 금지 |
| `NDY_COV` | double precision | evidence_only | `obs:organizer.prbd01n001.next_business_day_convexity_raw@1[numeric]` | 빈칸→missing; 0→zero | 다음 영업일로 표시; 실제 날짜 없음 | source-defined | — | L | 예측값으로 표현 금지 |
| `EVAL_PRICE` | double precision | evidence_only | `obs:organizer.prbd01n001.evaluation_price_raw@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음 | source-defined price | `CURR_CD` | L | 액면 기준·단위·기준일 불명확 |
| `APPLIED_YIELD` | double precision | evidence_only | `obs:organizer.prbd01n001.applied_yield_raw@1[numeric]` | 빈칸→missing; 0→zero; 범위이상→unknown | applicable 없음 | source-defined | — | L | 산출 정의와 이상값 검증 필요 |
| `DIRTY` | double precision | evidence_only | `obs:organizer.prbd01n001.dirty_price_raw@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음 | source-defined price | `CURR_CD` | L | 필드 정의·단위 불명확 |
| `NDY_EVAL_PRICE` | double precision | evidence_only | `obs:organizer.prbd01n001.next_business_day_evaluation_price_raw@1[numeric]` | 빈칸→missing; 0→unknown 가능성 플래그 | 다음 영업일; 실제 날짜 없음 | source-defined price | `CURR_CD` | L | 미산출 0과 실제 0을 구분할 근거 없음 |
| `NDY_APPLIED_YIELD` | double precision | evidence_only | `obs:organizer.prbd01n001.next_business_day_applied_yield_raw@1[numeric]` | 빈칸→missing; 0→zero; 범위이상→unknown | 다음 영업일; 실제 날짜 없음 | source-defined | — | L | 전망수익률이 아닌 다음 날 산출 기준값 |
| `NDY_DIRTY` | double precision | evidence_only | `obs:organizer.prbd01n001.next_business_day_dirty_price_raw@1[numeric]` | 빈칸→missing; 0→unknown 가능성 플래그 | 다음 영업일; 실제 날짜 없음 | source-defined price | `CURR_CD` | L | 현재 더티가격과 단위 동일성 미확인 |
| `CRD_GRD` | text | observation | `obs:organizer.prbd01n001.credit_grade_representative@1[text]` | trim; 빈칸→missing | `CRD_GRD_DT`가 유효할 때 적용 | — | — | Y | 원천 대표등급 그대로 사용 |
| `CRD_GRD_DT` | double precision | observation | `obs:organizer.prbd01n001.credit_grade_as_of@1[date]` | `YYYYMMDD`만 present; 0→placeholder; 빈칸→missing | 값 자체가 기준일 | — | — | Y | `CRD_GRD`의 기준일 |

## 4. 국내 ETF·ETN `PREF01N001` — 73개

| 원천 필드 | 원천 타입 | 분류 | 저장 대상 | 값 상태 규칙 | 날짜·기간 | 단위 | 통화 | 근거 | 판단·주의 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `cu_base_index` | text | relation | source-local index + `tracksIndex` | trim; 빈칸→missing; 명확한 지수명만 관계 생성 | `cu_upt_dt` | — | — | Y | 58행 한정. 문장·미제공 문구로 Index를 만들지 않음 |
| `cu_charge_etc_rt` | text | ignored | — | 채워진 값 전부 0→unavailable | — | — | — | N | `UNUSABLE_ALL_ZERO_SERIES` |
| `cu_charge_rt` | text | observation | `obs:organizer.pref01n001.total_fee_rate@1[numeric]` | 숫자 text 변환; 빈칸→missing; 0→zero | `cu_upt_dt` | percentage point | — | Y | 217행만 존재하여 비용 순위는 제한 |
| `cu_fund_mgmt_co` | text | relation | ETF→`managedBy`; ETN→`issuedBy`; source-local institution | trim; 빈칸이면 관계 없음 | `cu_upt_dt` | — | — | Y | 같은 필드는 상품군에 따라 역할이 다름 |
| `cu_lev_fector` | text | observation | `obs:organizer.pref01n001.leverage_factor@1[numeric]` | 숫자 text 변환; 빈칸→missing; 0→zero | `cu_upt_dt` | multiple | — | Y | 원본 철자 유지; 1·음수·소수 포함 |
| `cu_strtegy` | text | observation | `obs:organizer.pref01n001.strategy_raw@1[text]` | 빈칸→missing; 코드 `C`→unknown | `cu_upt_dt` | — | — | Y | `C`를 임의 전략명으로 번역하지 않음 |
| `cu_upt_dt` | text | observation | `obs:organizer.pref01n001.structure_updated_on@1[date]` | 유효 `YYYYMMDD`만 present; 빈칸→missing | 값 자체가 구조 기준일 | — | — | Y | `cu_*`에만 적용 |
| `du_bpr` | numeric | observation | `obs:organizer.pref01n001.base_price@1[numeric]` | 빈칸→missing; 0→zero | `du_upt_dt` | price per share | KRW | Y | 펀드 기준가와 동일 개념으로 단정하지 않음 |
| `du_chas_errt` | numeric | ignored | — | 채워진 값 전부 0→unavailable | — | — | — | N | `UNUSABLE_ALL_ZERO_SERIES` |
| `du_clpr` | numeric | observation | `obs:organizer.pref01n001.close_price@1[numeric]` | 빈칸→missing; 0→zero | `du_upt_dt` | price per share | KRW | Y | 일간 시장 종가 |
| `du_diff_rt` | numeric | ignored | — | 채워진 값 전부 0→unavailable | — | — | — | N | `UNUSABLE_ALL_ZERO_SERIES`; 필요 시 동일 기준일 가격·NAV로 재계산 |
| `du_er_1d` | numeric | observation | `obs:organizer.pref01n001.cumulative_return_1d@1[numeric]` | 빈칸→missing; 0→zero; `-100` 후보→placeholder | 종료=`du_upt_dt`; 1일 | percentage point | — | Y | 가격·총수익 중 원천 정의 미확인 표시 |
| `du_er_1m` | numeric | observation | `obs:organizer.pref01n001.cumulative_return_1m@1[numeric]` | 빈칸→missing; 0→zero; `-100`→placeholder | 종료=`du_upt_dt`; 1개월 | percentage point | — | Y | source-defined 누적수익률 |
| `du_er_1y` | numeric | observation | `obs:organizer.pref01n001.cumulative_return_1y@1[numeric]` | 빈칸→missing; 0→zero; `-100`→placeholder | 종료=`du_upt_dt`; 1년 | percentage point | — | Y | “연간수익률” 기본 비교 후보, 정의 제한 표시 |
| `du_er_3m` | numeric | observation | `obs:organizer.pref01n001.cumulative_return_3m@1[numeric]` | 빈칸→missing; 0→zero; `-100`→placeholder | 종료=`du_upt_dt`; 3개월 | percentage point | — | Y | source-defined 누적수익률 |
| `du_er_6m` | numeric | observation | `obs:organizer.pref01n001.cumulative_return_6m@1[numeric]` | 빈칸→missing; 0→zero; `-100`→placeholder | 종료=`du_upt_dt`; 6개월 | percentage point | — | Y | source-defined 누적수익률 |
| `du_er_ytd` | numeric | observation | `obs:organizer.pref01n001.cumulative_return_ytd@1[numeric]` | 빈칸→missing; 0→zero; `-100`→placeholder | 종료=`du_upt_dt`; YTD | percentage point | — | Y | 시작일은 해당 연도 첫 거래일로 후속 계산 |
| `du_hpr` | numeric | observation | `obs:organizer.pref01n001.high_price@1[numeric]` | 빈칸→missing; 0→zero | `du_upt_dt` | price per share | KRW | Y | 일간 고가 |
| `du_last_aum` | numeric | observation | `obs:organizer.pref01n001.aum@1[numeric]` | 빈칸→missing; 0→zero; ETN→inapplicable 가능성 | `du_upt_dt` | source-defined amount | KRW | Y | ETF 중심 지표; ETN과 섞은 순위 금지 |
| `du_last_nav` | numeric | observation | `obs:organizer.pref01n001.nav_per_share@1[numeric]` | 빈칸→missing; 0→zero | `du_upt_dt` | NAV per share | KRW | Y | ETF NAV·ETN 지표가치 차이 표시 |
| `du_lpr` | numeric | evidence_only | `obs:organizer.pref01n001.lpr_raw@1[numeric]` | 빈칸→missing; 0→zero | `du_upt_dt` | source-defined price | KRW | L | 한글명은 시가, 필드쌍은 저가를 암시 (`CONFLICTING_SOURCE_DEFINITION`) |
| `du_nav_rnf_amt` | numeric | ignored | — | 원천값 미사용 | — | — | — | N | `FAILED_DERIVATION_CHECK`; NAV 차이 산식 불일치 |
| `du_nav_yday` | numeric | observation | `obs:organizer.pref01n001.previous_nav_per_share@1[numeric]` | 빈칸→missing; 0→zero | `du_upt_dt` 직전 기준 | NAV per share | KRW | Y | 전일 NAV |
| `du_upt_dt` | timestamp without time zone | observation | `obs:organizer.pref01n001.daily_updated_at@1[timestamp]` | 빈칸→missing; 타임존 없는 날짜는 KST 일자로 해석 후 UTC 경계 명시 | 일간 필드 기준시각 | — | — | Y | 현재 파일은 2026-06-15, 파일명 날짜와 분리 |
| `du_val_1d` | numeric | observation | `obs:organizer.pref01n001.trading_value_1d@1[numeric]` | 빈칸→missing; 0→zero | `du_upt_dt`; 1거래일 | amount | KRW | Y | 거래대금 |
| `du_val_1m` | numeric | observation | `obs:organizer.pref01n001.average_trading_value_1m@1[numeric]` | 빈칸→missing; 0→zero | 종료=`du_upt_dt`; 1개월 평균 | amount | KRW | Y | 평균 산식의 거래일 수는 원천 정의 |
| `du_val_5d` | numeric | observation | `obs:organizer.pref01n001.average_trading_value_5d@1[numeric]` | 빈칸→missing; 0→zero | 종료=`du_upt_dt`; 5거래일 평균 | amount | KRW | Y | 유동성 비교 후보 |
| `du_vol_1d` | numeric | observation | `obs:organizer.pref01n001.trading_volume_1d@1[numeric]` | 빈칸→missing; 0→zero | `du_upt_dt`; 1거래일 | shares/notes | — | Y | 상품군별 단위 표시 |
| `du_vol_avg_1m` | numeric | observation | `obs:organizer.pref01n001.average_trading_volume_1m@1[numeric]` | 빈칸→missing; 0→zero | 종료=`du_upt_dt`; 1개월 평균 | shares/notes | — | Y | 평균 거래량 |
| `du_vol_avg_5d` | numeric | observation | `obs:organizer.pref01n001.average_trading_volume_5d@1[numeric]` | 빈칸→missing; 0→zero | 종료=`du_upt_dt`; 5거래일 평균 | shares/notes | — | Y | 평균 거래량 |
| `nru_mkt_diff_rt` | numeric | ignored | — | 전 행 NULL→unavailable | — | — | — | N | `NOT_AVAILABLE_CURRENT_SNAPSHOT` |
| `nru_mkt_inav` | numeric | ignored | — | 전 행 NULL→unavailable | — | — | — | N | `NOT_AVAILABLE_CURRENT_SNAPSHOT` |
| `pd_abrv_nm` | text | catalog | `catalog.alias`·`security.ticker_display` + `obs:organizer.pref01n001.short_name@1[text]` | trim; 빈칸→missing | 정적 | — | — | Y | 표시·검색 별칭 |
| `pd_circ_net_tamt` | numeric | observation | `obs:organizer.pref01n001.circulating_net_assets@1[numeric]` | 빈칸→missing; 0→zero; ETN→inapplicable 가능성 | `du_upt_dt` | amount | KRW | Y | ETF/ETN 의미 차이 표시 |
| `pd_circ_stk_cnt` | numeric | observation | `obs:organizer.pref01n001.circulating_security_count@1[numeric]` | 빈칸→missing; 0→zero | `du_upt_dt` | shares/notes | — | Y | 다른 두 주식수와 합치지 않음 |
| `pd_curr_cd` | text | catalog | `catalog.product.primary_currency` + `obs:organizer.pref01n001.product_currency@1[text]` | 유효 코드→present; 해당없음→inapplicable; 빈칸→missing | 정적 | — | ISO 4217 원문 | Y | 투자대상 통화와 다름 |
| `pd_curr_nm` | text | observation | `obs:organizer.pref01n001.product_currency_name@1[text]` | 빈칸→missing | 정적 | — | — | Y | 코드 표시 보조값 |
| `pd_divd_amt_pshr` | numeric | ignored | — | 채워진 값 전부 0→unavailable | — | — | — | N | `UNUSABLE_ALL_ZERO_SERIES`; 실제 분배금으로 사용 금지 |
| `pd_dvid_cycl` | text | ignored | — | 전 행 NULL→unavailable | — | — | — | N | `NOT_AVAILABLE_CURRENT_SNAPSHOT` |
| `pd_dvid_yield` | numeric | ignored | — | 채워진 값 전부 0→unavailable | — | — | — | N | `UNUSABLE_ALL_ZERO_SERIES` |
| `pd_exg_mkt_cd` | text | observation | `obs:organizer.pref01n001.exchange_code@1[text]` | 빈칸→missing | 정적 | code | — | Y | 상품 식별자가 아니라 거래소 코드; `listedOn` 미생성 |
| `pd_exg_mkt_nm` | text | observation | `obs:organizer.pref01n001.exchange_name@1[text]` | 빈칸→missing | 정적 | — | — | Y | Market entity 미지원으로 text 보존 |
| `pd_grp_no` | text | catalog | `catalog.security.security_kind` + `obs:organizer.pref01n001.product_type@1[text]` | ETF·ETN만 present; 기타→unknown | 정적 | — | — | Y | ETF 1,202·ETN 532 |
| `pd_itm_no` | text | identifier | `catalog.identifier(PREF01_PD_ITM_NO, primary)` + `obs:organizer.pref01n001.product_id@1[text]` | trim 후 빈칸은 행 격리 | 정적 | — | — | Y | 조회 대표키, 전 행 고유 |
| `pd_itm_no_ma` | text | identifier | `catalog.identifier(PREF01_PD_ITM_NO_MA)` + `obs:organizer.pref01n001.internal_product_id@1[text]` | trim 후 빈칸은 행 격리 | 정적 | — | — | Y | 보조·내부 식별자 |
| `pd_lst_price` | numeric | ignored | — | 전 행 0→unavailable | — | — | — | N | `UNUSABLE_ALL_ZERO_SERIES` |
| `pd_lst_stk_cnt` | numeric | observation | `obs:organizer.pref01n001.listed_security_count@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음 | shares/notes | — | Y | 공식 상장수량으로 보이지만 기준일 미제공 |
| `pd_lste_dt` | text | observation | `obs:organizer.pref01n001.trading_end_date@1[date]` | 유효 `YYYYMMDD`→present; `99991231`→placeholder; 빈칸→missing | 값 자체가 날짜 | — | — | Y | 센티널을 실제 종료일로 저장하지 않음 |
| `pd_lstg_dt` | text | observation | `obs:organizer.pref01n001.listing_date@1[date]` | 유효 `YYYYMMDD`만 present; 빈칸→missing | 값 자체가 날짜 | — | — | Y | 상장·거래개시일 |
| `pd_mkt_id` | text | observation | `obs:organizer.pref01n001.market_code@1[text]` | 빈칸→missing | 정적 | code | — | Y | Market entity 미지원 |
| `pd_mkt_nm` | text | observation | `obs:organizer.pref01n001.market_name@1[text]` | 빈칸→missing | 정적 | — | — | Y | 거래시장 표시값 |
| `pd_nav_pshr` | numeric | observation | `obs:organizer.pref01n001.net_asset_value_per_share@1[numeric]` | 빈칸→missing; 0→zero | `du_upt_dt` | NAV per share | KRW | Y | `du_last_nav`과 중복 여부는 원천별로 검증 |
| `pd_net_ast_pshr` | numeric | ignored | — | 채워진 값 전부 0→unavailable | — | — | — | N | `UNUSABLE_ALL_ZERO_SERIES` |
| `pd_net_prft_pshr` | numeric | ignored | — | 채워진 값 전부 0→unavailable | — | — | — | N | `UNUSABLE_ALL_ZERO_SERIES` |
| `pd_net_rt_ast_pshr` | numeric | ignored | — | 채워진 값 전부 0→unavailable | — | — | — | N | `UNUSABLE_ALL_ZERO_SERIES` |
| `pd_net_tamt` | numeric | observation | `obs:organizer.pref01n001.net_assets@1[numeric]` | 빈칸→missing; 0→zero; ETN 의미 제한 | `du_upt_dt` | amount | KRW | Y | AUM과 같은 필드로 자동 통합하지 않음 |
| `pd_nm` | text | catalog | `catalog.entity.canonical_name` + `obs:organizer.pref01n001.name@1[text]` | trim; 빈칸은 행 격리 | 정적 | — | — | Y | ETF 펀드명·ETN 증권명 |
| `pd_pen_risk_nm` | text | observation | `obs:organizer.pref01n001.pension_risk_class@1[text]` | `N`→inapplicable; 빈칸→missing; 그 외 present | applicable 없음 | — | — | Y | `N`을 위험등급으로 저장하지 않음 |
| `pd_pen_tr_yn` | text | observation | `obs:organizer.pref01n001.pension_trade_eligible@1[boolean]` | Y→true; N→false; 빈칸→missing; 기타→unknown | applicable 없음 | — | — | Y | 명시값만 Boolean 변환 |
| `pd_risk_cd` | text | observation | `obs:organizer.pref01n001.risk_grade_code@1[text]` | 빈칸→missing | applicable 없음 | code | — | Y | 명칭과 함께 검증 |
| `pd_risk_nm` | text | observation | `obs:organizer.pref01n001.risk_grade_name@1[text]` | 빈칸→missing | applicable 없음 | — | — | Y | 1~6등급 명칭 |
| `pd_sale_yn` | text | observation | `obs:organizer.pref01n001.saleable_in_master@1[boolean]` | 1→true; 0→false; 빈칸→missing; 기타→unknown | applicable 없음 | — | — | Y | 현재 실제 주문 가능성 전체를 보장하지 않음 |
| `pd_sect_cd` | text | evidence_only | `obs:organizer.pref01n001.sector_code_raw@1[text]` | 빈칸→missing | applicable 없음 | code | — | L | 코드북 부재 (`UNDEFINED_SOURCE_CODE`) |
| `pd_sect_nm` | text | ignored | — | 전 행 NULL→unavailable | — | — | — | N | `NOT_AVAILABLE_CURRENT_SNAPSHOT` |
| `pd_spac_yn` | text | ignored | — | 현재 ETP 질문에 사용하지 않음 | — | — | — | N | `NOT_ANSWERABLE`; 대부분 N인 비관련 주식 필드 |
| `pd_stk_cnt` | numeric | evidence_only | `obs:organizer.pref01n001.stock_count_raw@1[numeric]` | 빈칸→missing; 0→zero | `du_upt_dt` 추정 | shares/notes | — | L | 상장·유통수량과 의미가 겹치며 정의 불명확 |
| `pd_tr_yn` | text | observation | `obs:organizer.pref01n001.trading_suspended@1[boolean]` | 1→true; 0→false; 빈칸→missing; 기타→unknown | applicable 없음 | — | — | Y | 1은 거래정지 |
| `ru_mkt_price` | numeric | ignored | — | 전 행 NULL→unavailable | — | — | — | N | `NOT_AVAILABLE_CURRENT_SNAPSHOT`; 실시간값 아님 |
| `ru_mkt_volume` | numeric | ignored | — | 전 행 NULL→unavailable | — | — | — | N | `NOT_AVAILABLE_CURRENT_SNAPSHOT` |
| `wu_core_yn` | text | evidence_only | `obs:organizer.pref01n001.internal_core_flag@1[boolean]` | Y→true; N→false; 빈칸→missing; 기타→unknown | `wu_upt_dt` | — | — | L | 내부 핵심상품 분류를 추천 근거로 사용하지 않음 |
| `wu_inv_ast_type` | text | observation | `obs:organizer.pref01n001.investment_asset_type@1[text]` | 빈칸→missing | `wu_upt_dt` | — | — | Y | 자산군 검색 우선 필드 |
| `wu_inv_rgn` | text | observation | `obs:organizer.pref01n001.investment_region@1[text]` | 빈칸→missing | `wu_upt_dt` | — | — | Y | 투자지역 검색 우선 필드 |
| `wu_upt_dt` | text | observation | `obs:organizer.pref01n001.classification_updated_on@1[date]` | 유효 `YYYYMMDD`만 present; 빈칸→missing | 값 자체가 분류 기준일 | — | — | Y | `wu_*`에만 적용 |

## 5. 해외 ETF·ETN `PREF02N001` — 49개

| 원천 필드 | 원천 타입 | 분류 | 저장 대상 | 값 상태 규칙 | 날짜·기간 | 단위 | 통화 | 근거 | 판단·주의 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `cu_base_index` | text | relation | source-local index + `tracksIndex` | 명확한 지수명만 present·관계 생성; 문장형 미제공값→placeholder | `cu_upt_dt` | — | — | Y | 2,705개 문장형 placeholder로 Index 생성 금지 |
| `cu_charge_rt` | numeric | observation | `obs:organizer.pref02n001.total_fee_rate@1[numeric]` | 빈칸→missing; 0→zero | `cu_upt_dt` | percentage point 추정 | — | Y | 공식 단위 확인 전 source-defined 표시 |
| `cu_etn_yn` | text | observation | `obs:organizer.pref02n001.is_etn@1[boolean]` | Y→true; 빈칸→missing; 기타→unknown | `cu_upt_dt` | — | — | Y | ETF의 빈칸을 false로 바꾸지 않음; `pd_grp_no`가 구조 권위 |
| `cu_fund_mgmt_co` | text | relation | ETF→`managedBy`; ETN→`obs:organizer.pref02n001.provider_name_raw@1[text]` | trim; 빈칸→missing | `cu_upt_dt` | — | — | Y | ETN 발행기관 의미가 확정되지 않아 `issuedBy`를 추론하지 않음 |
| `cu_index_repl_mthd` | text | observation | `obs:organizer.pref02n001.index_replication_method@1[text]` | 빈칸→missing | `cu_upt_dt` | — | — | Y | Optimized·Swap·Full·Other 원문 유지 |
| `cu_index_tracking_yn` | text | observation | `obs:organizer.pref02n001.index_tracking_flag@1[boolean]` | Y→true; 빈칸→missing; 기타→unknown | `cu_upt_dt` | — | — | Y | 빈칸은 N이 아님 |
| `cu_inverse_short_yn` | text | observation | `obs:organizer.pref02n001.inverse_short_flag@1[boolean]` | Y→true; 빈칸→missing; 기타→unknown | `cu_upt_dt` | — | — | Y | 빈칸을 일반형으로 확정하지 않음 |
| `cu_lev_fector` | numeric | ignored | — | 전 행 NULL→unavailable | — | — | — | N | `NOT_AVAILABLE_CURRENT_SNAPSHOT` |
| `cu_strtegy` | text | observation | `obs:organizer.pref02n001.strategy_description@1[text]` | trim; 빈칸→missing | `cu_upt_dt` | — | — | Y | 긴 영문 설명; 구조화 분류는 별도 파생 사실로 구분 |
| `cu_upt_dt` | text | observation | `obs:organizer.pref02n001.structure_updated_on@1[date]` | 유효 `YYYYMMDD`만 present; 빈칸→missing | 값 자체가 구조 기준일 | — | — | Y | `cu_*`에만 적용 |
| `du_base_dt_match_yn` | text | observation | `obs:organizer.pref02n001.price_nav_date_match@1[boolean]` | Y→true; N→false; 빈칸→missing; 기타→unknown | `du_upt_dt` | — | — | Y | 가격·NAV 비교 가능성 판단용 |
| `du_bpr` | numeric | evidence_only | `obs:organizer.pref02n001.base_price_raw@1[numeric]` | 빈칸→missing; 0→zero | `du_upt_dt` | source-defined price | `pd_curr_cd` | L | NAV와 동일 개념인지 불명확 |
| `du_clpr` | numeric | observation | `obs:organizer.pref02n001.close_price@1[numeric]` | 빈칸→missing; 0→zero | `du_clpr_base_dt` | price per share | `pd_trd_ccy` | Y | 종가 기준일을 별도 사용 |
| `du_clpr_base_dt` | text | observation | `obs:organizer.pref02n001.close_price_date@1[date]` | 유효 `YYYYMMDD`만 present; 빈칸→missing | 값 자체가 기준일 | — | — | Y | 종가의 실제 적용일 |
| `du_clpr_src` | text | evidence_only | `obs:organizer.pref02n001.close_price_source_raw@1[text]` | trim; 빈칸→missing | `du_clpr_base_dt` | — | — | L | 내부 출처 문자열이며 source authority로 승격하지 않음 |
| `du_diff_rt` | numeric | ignored | — | 3개만 존재하고 극단값 포함→unavailable | — | — | — | N | `UNTRUSTED_SPARSE_SERIES`; 동일 기준일 가격·NAV로 재계산 |
| `du_er_1d` | numeric | ignored | — | 존재값 전부 0→unavailable | — | — | — | N | `UNUSABLE_ALL_ZERO_SERIES`; 가격 시계열로 재계산 |
| `du_hpr` | numeric | observation | `obs:organizer.pref02n001.high_price@1[numeric]` | 빈칸→missing; 0→zero | `du_clpr_base_dt` | price per share | `pd_trd_ccy` | Y | 일간 고가 |
| `du_last_aum` | numeric | observation | `obs:organizer.pref02n001.aum@1[numeric]` | 빈칸→missing; 0→zero; ETN→inapplicable 가능성 | `du_upt_dt` | source-defined amount | `pd_curr_cd` | Y | ETF 중심 지표; ETN 의미 제한 |
| `du_last_nav` | numeric | observation | `obs:organizer.pref02n001.nav_per_share@1[numeric]` | 빈칸→missing; 0→zero | `du_nav_base_dt`가 있고 값도 있을 때만 present | NAV per share | `pd_curr_cd` | Y | 날짜만 있고 NAV가 없는 행은 missing 유지 |
| `du_lpr` | numeric | observation | `obs:organizer.pref02n001.low_price@1[numeric]` | 빈칸→missing; 0→zero | `du_clpr_base_dt` | price per share | `pd_trd_ccy` | Y | `du_opr`과 구분되는 저가 |
| `du_nav_base_dt` | timestamp without time zone | observation | `obs:organizer.pref02n001.nav_date@1[date]` | 날짜 부분만 사용; 빈칸→missing | 값 자체가 NAV 기준일 | — | — | Y | NAV 값 결측 여부를 별도 검사 |
| `du_opr` | numeric | observation | `obs:organizer.pref02n001.open_price@1[numeric]` | 빈칸→missing; 0→zero | `du_clpr_base_dt` | price per share | `pd_trd_ccy` | Y | 일간 시가 |
| `du_upt_dt` | text | observation | `obs:organizer.pref02n001.daily_updated_on@1[date]` | 유효 `YYYYMMDD`만 present; 빈칸→missing | 값 자체가 적재·갱신일 | — | — | Y | 거래일과 분리 |
| `du_val_1d` | numeric | observation | `obs:organizer.pref02n001.trading_value_1d@1[numeric]` | 빈칸→missing; 0→zero | `du_clpr_base_dt`; 1거래일 | amount | `pd_trd_ccy` | Y | 일간 거래대금 |
| `du_vol_1d` | numeric | observation | `obs:organizer.pref02n001.trading_volume_1d@1[numeric]` | 빈칸→missing; 0→zero | `du_clpr_base_dt`; 1거래일 | shares/notes | — | Y | `ru_mkt_volume`과 중복 합산 금지 |
| `pd_abrv_nm` | text | catalog | `catalog.alias`·`security.ticker_display` + `obs:organizer.pref02n001.ticker@1[text]` | trim; 빈칸→missing | 정적 | — | — | Y | 표시 티커, 자연키 아님 |
| `pd_curr_cd` | text | catalog | `catalog.product.primary_currency` + `obs:organizer.pref02n001.product_currency@1[text]` | 유효 코드→present; 빈칸→missing | 정적 | — | ISO 4217 원문 | Y | 거래통화와 구분 |
| `pd_exg_mkt_cd` | text | observation | `obs:organizer.pref02n001.exchange_code@1[text]` | 빈칸→missing | 정적 | code | — | Y | 코드북 없이 Market entity·`listedOn` 미생성 |
| `pd_grp_no` | text | catalog | `catalog.security.security_kind` + `obs:organizer.pref02n001.product_type@1[text]` | ETF·ETN만 present; 기타→unknown | 정적 | — | — | Y | ETF 5,587·ETN 59 |
| `pd_isin_cd` | text | identifier | `catalog.identifier(ISIN)` + `obs:organizer.pref02n001.isin@1[text]` | 빈칸→missing; 동일 ISIN 다중 상품이면 limited·identifier 미생성 | 정적 | — | — | Y | 중복 50행이라 단독 자연키 금지 |
| `pd_itm_no` | text | identifier | `catalog.identifier(PREF02_PD_ITM_NO, primary)` + `obs:organizer.pref02n001.product_id@1[text]` | trim 후 빈칸은 행 격리 | 정적 | — | — | Y | 전 행 고유 대표키 |
| `pd_itm_no_ma` | text | identifier | `catalog.identifier(PREF02_PD_ITM_NO_MA)` + `obs:organizer.pref02n001.internal_product_id@1[text]` | trim 후 빈칸은 행 격리 | 정적 | — | — | Y | 보조 식별자 |
| `pd_lipper_id` | text | identifier | `catalog.identifier(LIPPER)` + `obs:organizer.pref02n001.lipper_id@1[text]` | 빈칸→missing; 동일 ID 다중 상품이면 limited·identifier 미생성 | 정적 | — | — | Y | 중복 50행, 단독키 금지 |
| `pd_lstg_dt` | text | observation | `obs:organizer.pref02n001.listing_date@1[date]` | 유효 `YYYYMMDD`만 present; 0·해석불가→placeholder | 값 자체가 날짜 | — | — | Y | 상장일 |
| `pd_lst_price` | numeric | ignored | — | 거의 전부 0→unavailable | — | — | — | N | `UNUSABLE_ALL_ZERO_SERIES`; 시장가격·투자금액으로 사용 금지 |
| `pd_lst_stk_cnt` | numeric | observation | `obs:organizer.pref02n001.listed_security_count@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음 | shares/notes | — | Y | ETF·ETN 단위 차이 표시 |
| `pd_mkt_id` | text | observation | `obs:organizer.pref02n001.market_country_id@1[text]` | 빈칸→missing | 정적 | code | — | Y | 전 행 US이나 투자지역을 뜻하지 않음 |
| `pd_nm` | text | catalog | `catalog.entity.canonical_name` + `obs:organizer.pref02n001.name@1[text]` | trim; 빈칸은 행 격리 | 정적 | — | — | Y | 상품 정식명 |
| `pd_sale_yn` | text | observation | `obs:organizer.pref02n001.saleable_in_master@1[boolean]` | 1→true; 빈칸→missing; 기타는 공식 코드 확인 전 unknown | applicable 없음 | — | — | Y | 0/1 정의가 완전히 확인되지 않아 보수적 변환 |
| `pd_trd_ccy` | text | observation | `obs:organizer.pref02n001.trading_currency@1[text]` | 유효 코드→present; 빈칸→missing | 정적 | — | ISO 4217 원문 | Y | 실제 거래통화 |
| `pd_tr_yn` | text | evidence_only | `obs:organizer.pref02n001.trading_status_code_raw@1[text]` | 빈칸→missing; 0 포함 원코드 보존 | applicable 없음 | code | — | L | 국내 동명 필드와 의미가 같다는 공식 확인 전 Boolean 금지 |
| `pd_us_cik` | text | evidence_only | `obs:organizer.pref02n001.us_cik_raw@1[text]` | 빈칸→missing | 정적 | identifier text | — | L | 상품 ID가 아닌 신고주체 ID 가능성; 03B에서 기관 연결 검증 |
| `ru_mkt_price` | numeric | ignored | — | 기준시각 없음; 종가와 불일치 가능 | — | — | — | N | `DUPLICATE_RUNTIME_VALUE_WITHOUT_TIME_BASIS` |
| `ru_mkt_volume` | numeric | ignored | — | `du_vol_1d`과 동일한 복제값 | — | — | — | N | `DUPLICATE_RUNTIME_VALUE` |
| `wu_core_yn` | text | ignored | — | Y가 없고 대부분 결측 | — | — | — | N | `NOT_ANSWERABLE`; 추천·핵심 판단 금지 |
| `wu_inv_ast_type` | text | observation | `obs:organizer.pref02n001.investment_asset_type@1[text]` | 빈칸→missing | `wu_upt_dt` | — | — | Y | 자산군 검색 우선 필드 |
| `wu_inv_rgn` | text | observation | `obs:organizer.pref02n001.investment_region@1[text]` | 빈칸→missing | `wu_upt_dt` | — | — | Y | 투자지역 검색 우선 필드 |
| `wu_upt_dt` | text | observation | `obs:organizer.pref02n001.classification_updated_on@1[date]` | 유효 `YYYYMMDD`만 present; 빈칸→missing | 값 자체가 분류 기준일 | — | — | Y | `wu_*`에만 적용 |

## 6. 공모펀드 `PRFD01N001` — 45개

| 원천 필드 | 원천 타입 | 분류 | 저장 대상 | 값 상태 규칙 | 날짜·기간 | 단위 | 통화 | 근거 | 판단·주의 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `bmrk_eng_nm` | text | evidence_only | `obs:organizer.prfd01n001.benchmark_english_raw@1[text]` | trim; 빈칸→missing; 숫자성 이상값→unknown | applicable 없음; vintage만 기록 | — | — | L | 혼합 문구를 Index entity로 만들지 않음 |
| `bmrk_nm` | text | evidence_only | `obs:organizer.prfd01n001.benchmark_raw@1[text]` | trim; 빈칸→missing | applicable 없음; vintage만 기록 | — | — | L | 여러 지수·비중이 섞인 문자열, `tracksIndex` 미생성 |
| `curr_cd` | text | catalog | `catalog.product.primary_currency` + `obs:organizer.prfd01n001.currency@1[text]` | 유효 코드→present; 빈칸→missing | applicable 없음 | — | ISO 4217 원문 | Y | 기준가 표시통화로 해석 |
| `exchdg_yn` | text | observation | `obs:organizer.prfd01n001.currency_hedged@1[boolean]` | Y→true; N→false; 빈칸→missing; 기타→unknown | applicable 없음; vintage만 기록 | — | — | Y | 결측을 false로 만들지 않음 |
| `fd_estb_ctry_cd` | text | evidence_only | `obs:organizer.prfd01n001.establishment_country_code_raw@1[text]` | `000`→unknown; 빈칸→missing | applicable 없음 | code | — | L | 공식 국가 코드 체계·`000` 의미 미확인 |
| `fd_ivst_rgn_desc` | text | observation | `obs:organizer.prfd01n001.investment_region@1[text]` | trim; 빈칸→missing | applicable 없음; vintage만 기록 | — | — | Y | 제공 분류 그대로 사용 |
| `fd_mm18_ern_r` | numeric | observation | `obs:organizer.prfd01n001.cumulative_return_18m@1[numeric]` | 빈칸→missing; 0→zero; `<-100`·극단치→unknown | applicable 없음; 18개월; vintage만 기록 | percentage point | — | Y | 파일 날짜를 수익률 종료일로 확정하지 않음 |
| `fd_mm1_ern_r` | numeric | observation | `obs:organizer.prfd01n001.cumulative_return_1m@1[numeric]` | 빈칸→missing; 0→zero; 범위이상→unknown | applicable 없음; 1개월; vintage만 기록 | percentage point | — | Y | source-defined 누적수익률 |
| `fd_mm3_ern_r` | numeric | observation | `obs:organizer.prfd01n001.cumulative_return_3m@1[numeric]` | 빈칸→missing; 0→zero; 범위이상→unknown | applicable 없음; 3개월; vintage만 기록 | percentage point | — | Y | source-defined 누적수익률 |
| `fd_mm6_ern_r` | numeric | observation | `obs:organizer.prfd01n001.cumulative_return_6m@1[numeric]` | 빈칸→missing; 0→zero; 범위이상→unknown | applicable 없음; 6개월; vintage만 기록 | percentage point | — | Y | source-defined 누적수익률 |
| `fd_nast_suma` | numeric | observation | `obs:organizer.prfd01n001.net_assets@1[numeric]` | 빈칸→missing; 0→zero | applicable 없음; vintage만 기록 | source-defined amount | `curr_cd` | Y | 반복 속성행에서 동일 `itm_no` 값은 정확 일치할 때만 축약 |
| `fd_set_pcd` | text | evidence_only | `obs:organizer.prfd01n001.establishment_type_code_raw@1[text]` | 빈칸→missing; 원코드 보존 | applicable 없음 | code | — | L | 코드북 부재 (`UNDEFINED_SOURCE_CODE`) |
| `fd_wk1_ern_r` | numeric | observation | `obs:organizer.prfd01n001.cumulative_return_1w@1[numeric]` | 빈칸→missing; 0→zero; 범위이상→unknown | applicable 없음; 1주; vintage만 기록 | percentage point | — | Y | source-defined 누적수익률 |
| `fd_yr1_ern_r` | numeric | observation | `obs:organizer.prfd01n001.cumulative_return_1y@1[numeric]` | 빈칸→missing; 0→zero; 범위이상→unknown | applicable 없음; 1년; vintage만 기록 | percentage point | — | Y | “연간수익률” 비교 후보이나 측정일 제한 필수 |
| `fd_yr2_ern_r` | numeric | observation | `obs:organizer.prfd01n001.cumulative_return_2y@1[numeric]` | 빈칸→missing; 0→zero; `<-100`·극단치→unknown | applicable 없음; 2년; vintage만 기록 | percentage point | — | Y | 누적수익률, 연환산값 아님 |
| `fd_yr3_ern_r` | numeric | observation | `obs:organizer.prfd01n001.cumulative_return_3y@1[numeric]` | 빈칸→missing; 0→zero; `<-100`·극단치→unknown | applicable 없음; 3년; vintage만 기록 | percentage point | — | Y | 누적수익률, 연환산값 아님 |
| `fd_yr5_ern_r` | numeric | observation | `obs:organizer.prfd01n001.cumulative_return_5y@1[numeric]` | 빈칸→missing; 0→zero; `<-100`·극단치→unknown | applicable 없음; 5년; vintage만 기록 | percentage point | — | Y | 누적수익률, 연환산값 아님 |
| `frc_bpr_itm_yn` | text | observation | `obs:organizer.prfd01n001.foreign_currency_base_price@1[boolean]` | 1→true; 0→false; 빈칸→missing; 기타→unknown | applicable 없음 | — | — | Y | `curr_cd`와 교차검증 |
| `fss_itm_no` | text | identifier | `catalog.identifier(FSS_FUND)` + `obs:organizer.prfd01n001.fss_product_id@1[text]` | `000000000000`→placeholder; 빈칸→missing; 유효값만 identifier | 정적 | — | — | Y | 센티널이 많아 단독키 금지 |
| `hdge_fd_yn` | text | observation | `obs:organizer.prfd01n001.is_hedge_fund@1[boolean]` | 1→true; 0→false; 빈칸→missing; 기타→unknown | applicable 없음 | — | — | Y | 환헤지와 다른 헤지펀드 여부 |
| `int_dvd_desc` | text | observation | `obs:organizer.prfd01n001.interest_dividend_class@1[text]` | trim; 빈칸→missing | applicable 없음 | — | — | Y | 세무·소득 구분으로 보되 원문 명칭 유지 |
| `itm_abrv_nm` | text | catalog | `catalog.alias` + `obs:organizer.prfd01n001.short_name_ko@1[text]` | trim; 빈칸→missing | 정적 | — | — | Y | 클래스 표기 포함 가능 |
| `itm_eabrv_nm` | text | catalog | `catalog.alias` + `obs:organizer.prfd01n001.short_name_en@1[text]` | trim; 빈칸→missing | 정적 | — | — | Y | 충족률이 낮아 표시 보조값 |
| `itm_eng_nm` | text | catalog | `catalog.alias` + `obs:organizer.prfd01n001.name_en_raw@1[text]` | trim; 빈칸·`0`·비명칭 문구→unknown | 정적 | — | — | Y | 대부분 한글이며 이상문구 존재; canonical name 금지 |
| `itm_nm` | text | catalog | `catalog.entity.canonical_name` + `obs:organizer.prfd01n001.name@1[text]` | trim; 빈칸은 행 격리 | 정적 | — | — | Y | 사용자 표시·검색 우선 이름 |
| `itm_no` | text | identifier | `catalog.identifier(PRFD_ITM_NO, primary)` + `obs:organizer.prfd01n001.product_id@1[text]` | trim 후 빈칸은 행 격리 | 정적 | — | — | Y | 11,139개 share-class 상품 ID |
| `kofia_fd_ccd` | text | evidence_only | `obs:organizer.prfd01n001.kofia_classification_code_raw@1[text]` | 20자리 0→placeholder; 빈칸→missing | applicable 없음 | code | — | L | 자리별 공식 코드표 부재 |
| `ksd_itm_no` | text | identifier | `catalog.identifier(KSD_PRODUCT)` + `obs:organizer.prfd01n001.ksd_product_id@1[text]` | 센티널·빈칸→missing; 유효값만 identifier | 정적 | — | — | Y | 클래스 연결 보조키 |
| `mtco_itm_no` | text | identifier | `catalog.identifier(MANAGER_SCOPED_PRODUCT)` + `obs:organizer.prfd01n001.manager_product_id@1[text]` | 빈칸→missing; `or_co_xtn_itt_cd`가 있을 때만 identifier | 정적 | — | — | Y | 운용사 코드와 함께 namespace 구성 |
| `ofsfd_yn` | text | observation | `obs:organizer.prfd01n001.is_offshore_fund@1[boolean]` | 1→true; 0→false; 빈칸→missing; 기타→unknown | applicable 없음 | — | — | Y | 해외투자 여부와 다름 |
| `or_attr_desc` | text | observation | `obs:organizer.prfd01n001.management_attribute@1[text]` | trim; `06`→unknown; 빈칸→missing | applicable 없음 | — | — | Y | 주식형·채권형 등 원천 분류; 미정규 코드 분리 |
| `or_co_xtn_itt_cd` | text | relation | source-local institution + `managedBy` | trim; 빈칸이면 관계 없음 | applicable 없음 | — | — | Y | 공식 설명상 운용회사 코드; 이름·외부 ID 통합은 03B |
| `ovrs_fd_desc` | text | observation | `obs:organizer.prfd01n001.overseas_fund_class@1[text]` | trim; 빈칸→missing | applicable 없음 | — | — | Y | 국내·해외·국내외혼합 원문 분류 |
| `pers_corp_desc` | text | observation | `obs:organizer.prfd01n001.investor_type@1[text]` | trim; 빈칸→missing | applicable 없음 | — | — | Y | 개인·법인·해당없음 구분 |
| `pfiv_sale_cntl_tcd` | text | evidence_only | `obs:organizer.prfd01n001.professional_sale_control_code_raw@1[text]` | 빈칸→missing; 원코드 보존 | applicable 없음 | code | — | L | 코드별 판매제약 정의 부재 |
| `prfd_attr_cd` | text | evidence_only | `obs:organizer.prfd01n001.attribute_row_code@1[text]` | 빈칸은 행 격리; 원코드 보존 | 정적 원본 행 grain | code | — | L | 상품 속성이 아니라 95,619행 반복 grain의 PK 일부; 별도 상품 미생성 |
| `prvo_fd_desc` | text | observation | `obs:organizer.prfd01n001.private_fund_detail@1[text]` | trim; 빈칸→missing | applicable 없음 | — | — | Y | 공모 마스터 안의 사모행 식별 보조값 |
| `prvo_pbff_desc` | text | observation | `obs:organizer.prfd01n001.public_private_class@1[text]` | trim; 빈칸→missing | applicable 없음 | — | — | Y | 공모 필터의 우선 필드 |
| `rptt_ksd_itm_no` | text | relation | source-local representative fund + `hasShareClass` | `KR0000000000`·`000000000000`·빈칸→placeholder; 유효값만 관계 | 정적 | — | — | Y | 센티널 그룹 생성 금지; 유효 대표그룹 2,626개 |
| `sale_yn` | text | observation | `obs:organizer.prfd01n001.sale_status@1[text]` | 판매중·판매완료→present; 빈칸→missing; 기타→unknown | applicable 없음; vintage만 기록 | — | — | Y | 신규매수 가능성의 우선 필드이나 실시간 주문 가능 보장 아님 |
| `std_itm_no` | text | identifier | `catalog.identifier(PRFD_STANDARD_PRODUCT)` + `obs:organizer.prfd01n001.standard_product_id@1[text]` | 빈칸→missing; 유효값만 identifier | 정적 | — | — | Y | 표준 보조 식별자 |
| `thco_sale_yn` | text | observation | `obs:organizer.prfd01n001.sold_by_provider@1[boolean]` | Y→true; 빈칸→missing; 기타→unknown·행 품질 플래그 | applicable 없음; vintage만 기록 | — | — | Y | 비정상 식별자 문자열 1행은 격리 판단 |
| `trusc_xtn_itt_cd` | text | evidence_only | `obs:organizer.prfd01n001.trustee_institution_code_raw@1[text]` | trim; 빈칸→missing | applicable 없음 | code | — | L | 승인된 13개 관계에 수탁관계가 없어 relation 미생성 |
| `zrin_fd_ivst_risk_gcd` | text | observation | `obs:organizer.prfd01n001.risk_grade_code@1[text]` | 문자열 `NULL`·빈칸→missing; 1~6→present; 기타→unknown | applicable 없음; vintage만 기록 | code | — | Y | 원본 행 grain PK 일부이지만 상품 위험등급 관측으로도 보존 |
| `zrin_fd_ivst_risk_grd_nm` | text | observation | `obs:organizer.prfd01n001.risk_grade_name@1[text]` | trim; 빈칸→missing; 코드와 불일치→unknown | applicable 없음; vintage만 기록 | — | — | Y | 코드와 이름을 함께 검증 |

## 7. 원천 grain과 식별자 불변식

| 소스 | 반드시 유지할 불변식 |
| --- | --- |
| `PRBD01N001` | `PD_NO`가 42,394행 전체에서 고유하고 비어 있지 않다. |
| `PREF01N001` | 1,202 ETF + 532 ETN이며, 조회 대표 identity는 `pd_itm_no`다. 스키마의 복합 PK 표시는 원천 레코드 검증에도 보존한다. |
| `PREF02N001` | 5,587 ETF + 59 ETN이며, identity는 `pd_itm_no`다. ISIN은 중복되므로 단독키가 아니다. |
| `PRFD01N001` | 95,619 attribute rows, 11,139 `itm_no`, 2,626 valid representative groups다. 상품·속성행·대표그룹의 세 grain을 섞지 않는다. |

네 소스의 원본 행 합계는 `42,394 + 1,734 + 5,646 + 95,619 = 145,393`이다.

## 8. 분류 집계

| 소스 | identifier | catalog | relation | observation | evidence_only | ignored | 합계 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `PRBD01N001` | 1 | 5 | 1 | 20 | 11 | 2 | 40 |
| `PREF01N001` | 2 | 4 | 2 | 44 | 4 | 17 | 73 |
| `PREF02N001` | 4 | 4 | 2 | 28 | 4 | 7 | 49 |
| `PRFD01N001` | 5 | 5 | 2 | 25 | 8 | 0 | 45 |
| **합계** | **12** | **18** | **7** | **117** | **27** | **26** | **207** |

`relation` 7개는 원천 필드의 종류 수다. 실제 관계 레코드 수는 유효값과 상품 유형에 따라 달라진다.

## 9. 출시 전 보수적 해석 점검

- [x] missing Boolean을 false로 매핑하지 않았다.
- [x] 문장형 placeholder 지수명으로 Index entity를 만들지 않는다.
- [x] 해외 ETF의 전부 0인 1일 수익률을 사용 가능한 수익률로 표시하지 않았다.
- [x] 공모펀드 대표번호 센티널로 representative fund를 만들지 않는다.
- [x] source-local 기관 이름·코드를 cross-source canonical organization으로 표시하지 않았다.
- [x] 파일 추출일 `2026-07-11`을 필드별 applicable date로 대체하지 않았다.
- [x] 현재 Stage 02에 없는 `Market` entity를 억지로 다른 타입으로 저장하지 않았다.
- [x] 혼합 벤치마크 문자열을 하나의 `tracksIndex` 관계로 단순화하지 않았다.

## 10. 승인 필요한 핵심 판단

구현 전 다음 결정을 함께 확정해야 한다.

1. 국내 ETF·ETN의 `cu_fund_mgmt_co`는 상품군별로 ETF `managedBy`, ETN `issuedBy`로 사용한다.
2. 해외 `cu_fund_mgmt_co`는 ETF의 `managedBy`만 확정하고, ETN은 제공기관 text Evidence로 제한한다.
3. 유효한 `cu_base_index`만 source-local Index와 `tracksIndex`를 만들며 placeholder·혼합 문구는 만들지 않는다.
4. 공모펀드 `or_co_xtn_itt_cd`는 이름 없는 source-local 기관 코드로 `managedBy`를 만들고, 공식 기관 통합은 03B로 미룬다.
5. 공모펀드 `rptt_ksd_itm_no`는 유효값에 한해 representative fund–share class `hasShareClass`를 만든다.
6. 거래소·시장은 text observation으로 유지하고 `listedOn`은 Stage 03A에서 만들지 않는다.
7. 정의·기준일·단위가 확인되지 않은 27개 `evidence_only` 필드와 현재 사용할 수 없는 26개 `ignored` 필드는 정규 검색·순위 입력에서 제외한다.

이 매트릭스가 승인되기 전에는 mapper, reader, writer, 테스트 구현으로 넘어가지 않는다.

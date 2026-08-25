# 주최 측 4개 마스터 280필드 매핑 매트릭스

**Date:** 2026-08-24

**Status:** Approved for mapper implementation

**Decision:** [ADR-0016](../decisions/ADR-0016-use-2026-08-24-organizer-baseline.md)

**Scope:** 새로 배포된 `PRBD01N001`, `PREF01N001`, `PREF02N001`, `PRFD01N001` 데이터 280개 필드

## 1. 검증된 원천 경계

| 소스 | 데이터 행 | 필드 | 원천 레코드 grain |
| --- | ---: | ---: | --- |
| `PRBD01N001` 국내채권 | 21,882 | 58 | `(pd_no, pd_exg_mkt, info_base_dt, info_seq)` |
| `PREF01N001` 국내 ETF·ETN | 1,780 | 98 | `pd_itm_no` |
| `PREF02N001` 해외 ETF·ETN | 6,037 | 49 | `pd_itm_no` |
| `PRFD01N001` 공모펀드 | 23,676 | 75 | `itm_no` |
| **합계** | **53,375** | **280** | — |

각 데이터 워크북의 `data` 헤더와 대응 스키마 워크북의 `schema` 필드는 이름과 순서가 정확히 일치하며 중복 헤더가 없다. 원본 값은 수정하지 않고 Git과 Docker context 밖에 둔다.

## 2. 공통 규칙

| 표기 | 의미 |
| --- | --- |
| `identifier` | 검증된 상품·기관 식별자. 문법·체크섬·유일성 검사를 통과한 값만 승격한다. |
| `catalog` | 이름·별칭·상품군·기준통화 같은 카탈로그 사실 |
| `relation` | 승인된 13개 온톨로지 관계 중 하나. 관계와 Evidence를 함께 만든다. |
| `observation` | 타입·단위·시점이 정해진 관측값 |
| `evidence_only` | 원문과 locator는 보존하지만 검색·순위·계산에는 출시하지 않는 값 |
| `ignored` | 공식 공지나 검증 결과에 따라 사실로 만들지 않는 값 |

- 모든 필드는 아래 표에 정확히 한 번만 등장한다.
- `obs:<name>[type]`은 `metric_definition`과 tagged Observation을 뜻한다. 기존과 의미가 같은 metric은 version 1을 재사용하고, 의미가 달라진 경우에만 별도 version을 승인한다.
- 기본 숫자 규칙은 `blank → missing`, 명시적 `0 → zero`다. 두 상태를 합치거나 이웃 행으로 보간하지 않는다.
- 기본 text 규칙은 trim 후 빈 문자열을 `missing`으로 둔다. 코드표가 없는 코드는 번역하지 않고 원문만 보존한다.
- Boolean은 표에 적힌 명시적 `Y/N` 또는 `1/0`만 변환한다. 빈 값은 `false`가 아니다.
- 날짜는 유효한 `YYYYMMDD`만 변환한다. 파일 배포일이나 외부 cutoff를 실제 관측일로 덮어쓰지 않는다.
- `Y`는 정규화 사실과 원본 workbook/sheet/row/column Evidence를 만들고, `L`은 제한 Evidence만 만들며, `N`은 사실과 Evidence를 만들지 않는다는 뜻이다. 모든 source record 자체의 해시·locator 원장은 별도로 보존한다.
- 금액의 배율이 스키마에 없으면 원단위를 보존하고 임의 환산하지 않는다. 환산에는 같은 기준일 또는 정책상 허용된 공식 환율과 계산 Evidence가 필요하다.
- `2026-08-24T23:59:59+09:00`은 외부 공식 자료의 **가용성 cutoff**다. organizer 관측값은 각 필드의 실제 기준일을 유지한다.

## 3. 국내채권 `PRBD01N001` — 58개

상품 정적 사실은 동일 `pd_no` 안에서 일치해야 한다. 판매·가격·수익률 사실은 복합 source key별로 보존하며, 서로 다른 `info_seq`를 별도 상품으로 만들지 않는다.

| 원천 필드 | 원천 타입 | 분류 | 저장 대상 | 날짜·기간 | 단위·통화 | 상태·제약 | 근거 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `after_tax_yield` | double precision | observation | `obs:organizer.prbd01n001.after_tax_yield[numeric]` | `sale_yield_base_dt` 또는 `info_base_dt` | percentage point | 개인 세후 원천값; 세율 임의 추론 금지 | Y |
| `applied_yield` | double precision | observation | `obs:organizer.prbd01n001.applied_yield[numeric]` | `pd_std_info_update` 또는 `info_base_dt` | percentage point | 민평 수익률 원문 | Y |
| `avg_annual_tax_yield` | double precision | observation | `obs:organizer.prbd01n001.average_annual_after_tax_yield[numeric]` | `sale_yield_base_dt` 또는 `info_base_dt` | percentage point | 0도 그대로 보존; 다른 세후 지표와 대체 금지 | Y |
| `bdbns_abl_chnl_nm` | text | observation | `obs:organizer.prbd01n001.tradable_channel_name[text]` | `info_base_dt` | — | 명시된 채널명만 사용 | Y |
| `bdbns_abl_chnl_tcd` | text | evidence_only | `obs:organizer.prbd01n001.tradable_channel_code_raw[text]` | `info_base_dt` | code | 코드표 부재; `0`을 임의 채널로 번역 금지 | L |
| `bd_inrt_tcd` | text | observation | `obs:organizer.prbd01n001.interest_rate_type[text]` | 계약 조건 | — | 제공된 명칭을 그대로 사용 | Y |
| `bd_intp_tcd` | text | observation | `obs:organizer.prbd01n001.interest_payment_type[text]` | 계약 조건 | — | 제공된 명칭을 그대로 사용 | Y |
| `bd_knd` | text | observation | `obs:organizer.prbd01n001.bond_kind[text]` | 정적 | — | 예탁원 기준 명칭; 임의 재분류 금지 | Y |
| `bd_ofr_tcd` | text | observation | `obs:organizer.prbd01n001.offering_type[text]` | 정적 | — | 제공된 공모·사모 명칭만 사용 | Y |
| `bd_tisu_a` | numeric(26,8) | observation | `obs:organizer.prbd01n001.total_issuance_amount[numeric]` | 정적 | source amount / `curr_cd` | 배율 확인 전 환산 금지 | Y |
| `buyable_quantity` | double precision | ignored | — | — | — | 공식 공지상 값 무효; 구매가능 필터·답변·계산에 사용 금지 | N |
| `buy_yield` | double precision | observation | `obs:organizer.prbd01n001.buy_yield[numeric]` | `sale_yield_base_dt` 또는 `info_base_dt`; LOT | percentage point | source record별 보존 | Y |
| `corp_after_tax_yield` | double precision | observation | `obs:organizer.prbd01n001.corporate_after_tax_yield[numeric]` | `sale_yield_base_dt` 또는 `info_base_dt`; LOT | percentage point | 적용 과세방식은 원문 범위로 제한 | Y |
| `corp_pretax_yield` | double precision | observation | `obs:organizer.prbd01n001.corporate_pretax_yield[numeric]` | `sale_yield_base_dt` 또는 `info_base_dt`; LOT | percentage point | source record별 보존 | Y |
| `cov` | double precision | observation | `obs:organizer.prbd01n001.convexity[numeric]` | `pd_std_info_update` 또는 `info_base_dt` | source-defined | 산식·단위 제한을 Evidence에 표시 | Y |
| `crd_grd` | text | observation | `obs:organizer.prbd01n001.credit_grade_representative[text]` | `crd_grd_dt` | — | 원천 대표등급 그대로 사용 | Y |
| `crd_grd_dt` | text | observation | `obs:organizer.prbd01n001.credit_grade_as_of[date]` | 값 자체 | — | 유효 날짜만 변환 | Y |
| `curr_cd` | text | catalog | `catalog.product.primary_currency` + companion observation | 정적 | ISO 4217 원문 | 미확인 코드와 빈값은 unknown/missing | Y |
| `depo_equiv_yield_154` | double precision | observation | `obs:organizer.prbd01n001.deposit_equivalent_yield_154[numeric]` | `sale_yield_base_dt` 또는 `info_base_dt` | percentage point | 세율 15.4 기준 원천값 | Y |
| `depo_equiv_yield_495` | double precision | observation | `obs:organizer.prbd01n001.deposit_equivalent_yield_495[numeric]` | `sale_yield_base_dt` 또는 `info_base_dt` | percentage point | 세율 49.5 기준 원천값 | Y |
| `dirty` | double precision | observation | `obs:organizer.prbd01n001.dirty_price[numeric]` | `pd_std_info_update` 또는 `info_base_dt` | source price / `curr_cd` | 액면 기준은 원천 정의로 제한 | Y |
| `dur` | double precision | observation | `obs:organizer.prbd01n001.duration[numeric]` | `pd_std_info_update` 또는 `info_base_dt` | source-defined | 수정·맥컬리 여부를 추론하지 않음 | Y |
| `eval_price` | double precision | observation | `obs:organizer.prbd01n001.evaluation_price[numeric]` | `pd_std_info_update` 또는 `info_base_dt` | source price / `curr_cd` | Clean Price 성격의 원천값 | Y |
| `exg_close_price` | double precision | observation | `obs:organizer.prbd01n001.exchange_close_price[numeric]` | `exg_close_price_base_dt` | source price / `curr_cd` | 기준일이 없으면 limited | Y |
| `exg_close_price_base_dt` | text | observation | `obs:organizer.prbd01n001.exchange_close_as_of[date]` | 값 자체 | — | 종가·종가수익률에만 적용 | Y |
| `exg_close_yield` | double precision | observation | `obs:organizer.prbd01n001.exchange_close_yield[numeric]` | `exg_close_price_base_dt` | percentage point | 기준일이 없으면 limited | Y |
| `exrt_grte_ern_r` | numeric(20,12) | observation | `obs:organizer.prbd01n001.maturity_guaranteed_yield[numeric]` | 계약 조건 | percentage point | 구분코드 원문과 함께 사용 | Y |
| `exrt_grte_ern_r_tcd` | text | evidence_only | `obs:organizer.prbd01n001.maturity_guaranteed_yield_type_raw[text]` | 계약 조건 | code | 코드표 부재; 숫자코드 번역 금지 | L |
| `exrt_rpy_r` | numeric(20,12) | observation | `obs:organizer.prbd01n001.maturity_redemption_rate[numeric]` | 계약 조건 | percentage point | 원천 상환율 | Y |
| `info_base_dt` | text | observation | `obs:organizer.prbd01n001.information_as_of[date]` | 값 자체 | — | 복합 source key와 판매·민평 기본 기준일 | Y |
| `info_seq` | bigint | evidence_only | source-record locator component | `info_base_dt`; LOT | sequence | 상품 식별자가 아니며 외부 답변에 노출하지 않음 | L |
| `isu_bal_amt` | double precision | observation | `obs:organizer.prbd01n001.issue_balance[numeric]` | `pd_std_info_update` 또는 `info_base_dt` | source amount / `curr_cd` | 배율 확인 전 환산 금지 | Y |
| `isu_dt` | text | observation | `obs:organizer.prbd01n001.issue_date[date]` | 값 자체 | — | 유효 날짜만 변환 | Y |
| `mat_dt` | text | observation | `obs:organizer.prbd01n001.maturity_date[date]` | 값 자체 | — | 영구채 1차 콜일 의미를 함께 표시 | Y |
| `ndy_applied_yield` | double precision | observation | `obs:organizer.prbd01n001.next_day_applied_yield[numeric]` | `info_base_dt`; 다음 영업일 horizon | percentage point | 실제 달력일을 추측하지 않음 | Y |
| `ndy_cov` | double precision | observation | `obs:organizer.prbd01n001.next_day_convexity[numeric]` | `info_base_dt`; 다음 영업일 horizon | source-defined | 실제 달력일을 추측하지 않음 | Y |
| `ndy_dirty` | double precision | observation | `obs:organizer.prbd01n001.next_day_dirty_price[numeric]` | `info_base_dt`; 다음 영업일 horizon | source price / `curr_cd` | 실제 달력일을 추측하지 않음 | Y |
| `ndy_dur` | double precision | observation | `obs:organizer.prbd01n001.next_day_duration[numeric]` | `info_base_dt`; 다음 영업일 horizon | source-defined | 실제 달력일을 추측하지 않음 | Y |
| `ndy_eval_price` | double precision | observation | `obs:organizer.prbd01n001.next_day_evaluation_price[numeric]` | `info_base_dt`; 다음 영업일 horizon | source price / `curr_cd` | 실제 달력일을 추측하지 않음 | Y |
| `pd_abrv_eng_nm` | text | catalog | `catalog.alias` + companion observation | 정적 | — | 영문 약어 | Y |
| `pd_abrv_nm` | text | catalog | `catalog.alias` + companion observation | 정적 | — | 한글 약어 | Y |
| `pd_ctry_cd` | text | evidence_only | `obs:organizer.prbd01n001.country_code_raw[text]` | 정적 | code | 발행국·등록국 의미 미확정 | L |
| `pd_eng_nm` | text | catalog | `catalog.alias` + companion observation | 정적 | — | 영문 상품명 | Y |
| `pd_exg_mkt` | text | observation | `obs:organizer.prbd01n001.exchange_market_type[text]` | `info_base_dt`; source grain | — | 장내·장외 구분; 발행시장으로 해석 금지 | Y |
| `pd_nm` | text | catalog | `catalog.entity.canonical_name` + companion observation | 정적 | — | 빈 이름은 source record 격리 | Y |
| `pd_no` | text | identifier | `catalog.identifier(PRBD_PD_NO)` + companion observation | 정적 | — | 반복 가능 product key; 복합 source key와 구분 | Y |
| `pd_pbcm` | text | relation | source-local institution + `issuedBy` | 정적 | — | 동명이인 cross-source 병합 금지 | Y |
| `pd_pen_tr_yn` | text | observation | `obs:organizer.prbd01n001.pension_eligible[boolean]` | `info_base_dt` | — | Y/N만 변환 | Y |
| `pd_risk_gcd` | text | evidence_only | `obs:organizer.prbd01n001.risk_grade_code_raw[text]` | `info_base_dt` | code | 내부 코드표 부재; 이름과 연결해 번역하지 않음 | L |
| `pd_risk_nm` | text | observation | `obs:organizer.prbd01n001.risk_grade_name[text]` | `info_base_dt` | — | 제공된 등급명만 사용 | Y |
| `pd_std_info_update` | text | observation | `obs:organizer.prbd01n001.standard_info_updated_on[date]` | 값 자체 | — | 민평 계열에만 적용 | Y |
| `pref_tax_yield` | double precision | observation | `obs:organizer.prbd01n001.preferential_tax_yield[numeric]` | `sale_yield_base_dt` 또는 `info_base_dt` | percentage point | 우대세율 대상 임의 추론 금지 | Y |
| `remaining_days` | double precision | observation | `obs:organizer.prbd01n001.remaining_days[numeric]` | `info_base_dt` | day | 만기일 재계산값과 혼합하지 않음 | Y |
| `sale_yield_base_dt` | text | observation | `obs:organizer.prbd01n001.sale_yield_as_of[date]` | 값 자체 | — | 판매 수익률·가격 LOT 계열에 적용 | Y |
| `srfc_irt` | double precision | observation | `obs:organizer.prbd01n001.coupon_rate[numeric]` | 계약 조건 | percentage point | 거래수익률과 구분 | Y |
| `std_pd_mcls_nm` | text | observation | `obs:organizer.prbd01n001.product_major_class[text]` | 정적 | — | 원천 분류명 그대로 사용 | Y |
| `std_pd_scls_nm` | text | observation | `obs:organizer.prbd01n001.product_subclass[text]` | 정적 | — | 원천 분류명 그대로 사용 | Y |
| `trade_price` | double precision | observation | `obs:organizer.prbd01n001.trade_price[numeric]` | `sale_yield_base_dt` 또는 `info_base_dt`; LOT | source price / `curr_cd` | 서로 다른 LOT 값을 합치지 않음 | Y |

## 4. 국내 ETF·ETN `PREF01N001` — 98개

`pd_itm_no` 1,780개는 모두 고유하다. 유효한 `pd_isin_cd`는 checksum과 유일성을 확인하고 `pd_itm_no`와의 일치도 검증한다. 공모펀드의 유효 `ksd_itm_no`와 정확히 겹치는 217개는 ETF를 기준 상품 identity로 재사용하고 두 상품으로 집계하지 않는다.

| 원천 필드 | 원천 타입 | 분류 | 저장 대상 | 날짜·기간 | 단위·통화 | 상태·제약 | 근거 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cu_base_index` | text | relation | source-local Index + `tracksIndex` | `cu_upt_dt` | — | 명확한 단일 지수명만 관계 생성; 문장·placeholder 제외 | Y |
| `cu_charge_etc_rt` | text | observation | `obs:organizer.pref01n001.other_expense_rate[numeric]` | `cu_upt_dt` | percentage point | 숫자 text만 변환; 0 보존 | Y |
| `cu_charge_rt` | text | observation | `obs:organizer.pref01n001.total_fee_rate[numeric]` | `cu_upt_dt` | percentage point | 숫자 text만 변환 | Y |
| `cu_fund_mgmt_co` | text | relation | ETF→`managedBy`; ETN→`issuedBy`; source-local institution | `cu_upt_dt` | — | 동명이인 cross-source 병합 금지 | Y |
| `cu_lev_fector` | text | observation | `obs:organizer.pref01n001.leverage_factor[numeric]` | `cu_upt_dt` | multiple | 숫자 text만 변환 | Y |
| `cu_strtegy` | text | observation | `obs:organizer.pref01n001.strategy_raw[text]` | `cu_upt_dt` | — | 코드성 단일문자는 번역하지 않음 | Y |
| `cu_upt_dt` | text | observation | `obs:organizer.pref01n001.structure_updated_on[date]` | 값 자체 | — | `cu_*`에만 적용 | Y |
| `du_bpr` | numeric(28,2) | observation | `obs:organizer.pref01n001.base_price[numeric]` | `du_nav_base_dt` 또는 `du_upt_dt` | price per share / KRW | 펀드 기준가와 동일 개념으로 단정하지 않음 | Y |
| `du_chas_errt` | numeric(28,2) | observation | `obs:organizer.pref01n001.tracking_error[numeric]` | `du_chas_errt_base_dt` | percentage point | 새 스냅샷의 비영(非零) 값 포함 | Y |
| `du_chas_errt_base_dt` | text | observation | `obs:organizer.pref01n001.tracking_error_as_of[date]` | 값 자체 | — | 추적오차에만 적용 | Y |
| `du_clpr` | numeric(28,2) | observation | `obs:organizer.pref01n001.close_price[numeric]` | `du_upt_dt` | price per share / KRW | 일간 종가 | Y |
| `du_diff_rt` | numeric(28,2) | observation | `obs:organizer.pref01n001.premium_discount_rate[numeric]` | `du_diff_rt_base_dt` | percentage point | 새 스냅샷 원천값; NAV로 재계산한 값과 구분 | Y |
| `du_diff_rt_base_dt` | text | observation | `obs:organizer.pref01n001.premium_discount_as_of[date]` | 값 자체 | — | 괴리율에만 적용 | Y |
| `du_er_1d` | numeric(28,2) | observation | `obs:organizer.pref01n001.cumulative_return_1d[numeric]` | 종료=`du_upt_dt`; 1일 | percentage point | source-defined 누적수익률 | Y |
| `du_er_1m` | numeric(28,2) | observation | `obs:organizer.pref01n001.cumulative_return_1m[numeric]` | 종료=`du_upt_dt`; 1개월 | percentage point | source-defined 누적수익률 | Y |
| `du_er_1y` | numeric(28,2) | observation | `obs:organizer.pref01n001.cumulative_return_1y[numeric]` | 종료=`du_upt_dt`; 1년 | percentage point | 기본 연간수익률 비교 후보 | Y |
| `du_er_3m` | numeric(28,2) | observation | `obs:organizer.pref01n001.cumulative_return_3m[numeric]` | 종료=`du_upt_dt`; 3개월 | percentage point | source-defined 누적수익률 | Y |
| `du_er_6m` | numeric(28,2) | observation | `obs:organizer.pref01n001.cumulative_return_6m[numeric]` | 종료=`du_upt_dt`; 6개월 | percentage point | source-defined 누적수익률 | Y |
| `du_er_ytd` | numeric(28,2) | observation | `obs:organizer.pref01n001.cumulative_return_ytd[numeric]` | 종료=`du_upt_dt`; YTD | percentage point | 해당 연도 수익률 | Y |
| `du_hpr` | numeric(28,2) | observation | `obs:organizer.pref01n001.high_price[numeric]` | `du_upt_dt` | price per share / KRW | 일간 고가 | Y |
| `du_last_aum` | numeric(28,2) | observation | `obs:organizer.pref01n001.aum[numeric]` | `du_upt_dt` | source amount / KRW | ETF 중심; ETN과 무조건 합산 순위 금지 | Y |
| `du_last_nav` | numeric(28,2) | observation | `obs:organizer.pref01n001.nav_per_share[numeric]` | `du_nav_base_dt` | NAV per share / KRW | ETN 지표가치와 의미 차이를 표시 | Y |
| `du_lpr` | numeric(28,2) | evidence_only | `obs:organizer.pref01n001.lpr_raw[numeric]` | `du_upt_dt` | source price / KRW | 필드명과 코멘트만으로 시가·저가 확정 불가 | L |
| `du_nav_base_dt` | text | observation | `obs:organizer.pref01n001.nav_as_of[date]` | 값 자체 | — | NAV 계열에 적용 | Y |
| `du_nav_rnf_amt` | numeric(28,2) | observation | `obs:organizer.pref01n001.nav_change_amount[numeric]` | `du_nav_base_dt` | amount per share / KRW | 원천값으로 저장; 별도 산식 결과와 구분 | Y |
| `du_nav_yday` | numeric(28,2) | observation | `obs:organizer.pref01n001.previous_nav_per_share[numeric]` | `du_nav_base_dt` 직전 | NAV per share / KRW | 전일 NAV | Y |
| `du_upt_dt` | text | observation | `obs:organizer.pref01n001.daily_updated_on[date]` | 값 자체 | — | 일간 시장·수익률 기본 기준일 | Y |
| `du_val_1d` | numeric(28,2) | observation | `obs:organizer.pref01n001.trading_value_1d[numeric]` | `du_upt_dt`; 1거래일 | amount / KRW | 일거래대금 | Y |
| `du_val_1m` | numeric(28,2) | observation | `obs:organizer.pref01n001.average_trading_value_1m[numeric]` | 종료=`du_upt_dt`; 1개월 평균 | amount / KRW | 원천 평균기간 정의 유지 | Y |
| `du_val_5d` | numeric(28,2) | observation | `obs:organizer.pref01n001.average_trading_value_5d[numeric]` | 종료=`du_upt_dt`; 5거래일 평균 | amount / KRW | 유동성 비교 후보 | Y |
| `du_vlty_1m` | numeric(28,8) | observation | `obs:organizer.pref01n001.annualized_volatility_1m[numeric]` | `du_vlty_base_dt`; 20거래일 | percentage point annualized | 기간 수익률과 구분 | Y |
| `du_vlty_1y` | numeric(28,8) | observation | `obs:organizer.pref01n001.annualized_volatility_1y[numeric]` | `du_vlty_base_dt`; 252거래일 | percentage point annualized | 기간 수익률과 구분 | Y |
| `du_vlty_3m` | numeric(28,8) | observation | `obs:organizer.pref01n001.annualized_volatility_3m[numeric]` | `du_vlty_base_dt`; 60거래일 | percentage point annualized | 기간 수익률과 구분 | Y |
| `du_vlty_6m` | numeric(28,8) | observation | `obs:organizer.pref01n001.annualized_volatility_6m[numeric]` | `du_vlty_base_dt`; 120거래일 | percentage point annualized | 기간 수익률과 구분 | Y |
| `du_vlty_base_dt` | text | observation | `obs:organizer.pref01n001.volatility_as_of[date]` | 값 자체 | — | 변동성 4개에만 적용 | Y |
| `du_vol_1d` | numeric(28,2) | observation | `obs:organizer.pref01n001.trading_volume_1d[numeric]` | `du_upt_dt`; 1거래일 | shares/notes | ETF·ETN 단위 구분 | Y |
| `du_vol_avg_1m` | numeric(28,2) | observation | `obs:organizer.pref01n001.average_trading_volume_1m[numeric]` | 종료=`du_upt_dt`; 1개월 평균 | shares/notes | 평균 거래량 | Y |
| `du_vol_avg_5d` | numeric(28,2) | observation | `obs:organizer.pref01n001.average_trading_volume_5d[numeric]` | 종료=`du_upt_dt`; 5거래일 평균 | shares/notes | 평균 거래량 | Y |
| `fn_average_coupon` | numeric(28,8) | observation | `obs:organizer.pref01n001.portfolio_average_coupon[numeric]` | `fn_base_dt` 또는 `fn_portfolio_dt` | percentage point | 채권 포트폴리오에만 적용 | Y |
| `fn_average_maturity` | numeric(28,8) | observation | `obs:organizer.pref01n001.portfolio_average_maturity[numeric]` | `fn_base_dt` 또는 `fn_portfolio_dt` | year, source-defined | 채권 포트폴리오에만 적용 | Y |
| `fn_average_quality` | text | evidence_only | `obs:organizer.pref01n001.portfolio_average_quality_raw[text]` | `fn_base_dt` 또는 `fn_portfolio_dt` | source scale | 공식 등급척도 부재·형식 이상값 존재; 순위 금지 | L |
| `fn_base_dt` | text | observation | `obs:organizer.pref01n001.fundamentals_as_of[date]` | 값 자체 | — | `fn_*` 기본 기준일 | Y |
| `fn_effective_duration` | numeric(28,8) | observation | `obs:organizer.pref01n001.effective_duration[numeric]` | `fn_base_dt` 또는 `fn_portfolio_dt` | year, source-defined | 채권 포트폴리오에만 적용 | Y |
| `fn_effective_maturity` | numeric(28,8) | observation | `obs:organizer.pref01n001.effective_maturity[numeric]` | `fn_base_dt` 또는 `fn_portfolio_dt` | year, source-defined | 채권 포트폴리오에만 적용 | Y |
| `fn_modified_duration` | numeric(28,8) | observation | `obs:organizer.pref01n001.modified_duration[numeric]` | `fn_base_dt` 또는 `fn_portfolio_dt` | year, source-defined | 채권 포트폴리오에만 적용 | Y |
| `fn_nominal_maturity` | numeric(28,8) | observation | `obs:organizer.pref01n001.nominal_maturity[numeric]` | `fn_base_dt` 또는 `fn_portfolio_dt` | year, source-defined | 채권 포트폴리오에만 적용 | Y |
| `fn_portfolio_dt` | text | observation | `obs:organizer.pref01n001.portfolio_as_of[date]` | 값 자체 | — | 포트폴리오 기초지표에 적용 | Y |
| `pd_abrv_nm` | text | catalog | `catalog.alias` + companion observation | 정적 | — | 표시·검색 별칭 | Y |
| `pd_circ_net_tamt` | numeric(28,2) | observation | `obs:organizer.pref01n001.circulating_net_assets[numeric]` | `du_upt_dt` | source amount / `pd_curr_cd` | `pd_net_tamt`와 중복 합산 금지 | Y |
| `pd_circ_stk_cnt` | numeric(28,2) | observation | `obs:organizer.pref01n001.circulating_security_count[numeric]` | `du_upt_dt` | shares/notes | 상장주식수와 의미 구분 | Y |
| `pd_curr_cd` | text | catalog | `catalog.product.primary_currency` + companion observation | 정적 | ISO 4217 원문 | 유효 코드만 승격 | Y |
| `pd_curr_nm` | text | observation | `obs:organizer.pref01n001.product_currency_name[text]` | 정적 | — | 코드와 교차검증 | Y |
| `pd_divd_amt_ann` | numeric(28,8) | observation | `obs:organizer.pref01n001.estimated_annual_distribution[numeric]` | `pd_dvid_base_dt` | amount per share / `pd_curr_cd` | 추정값임을 답변에 표시 | Y |
| `pd_divd_amt_pshr` | numeric(28,8) | observation | `obs:organizer.pref01n001.distribution_per_share[numeric]` | `pd_dvid_base_dt` | amount per share / `pd_curr_cd` | 원천 우선·없으면 회당 추정이라는 정의 보존 | Y |
| `pd_dvid_base_dt` | text | observation | `obs:organizer.pref01n001.distribution_as_of[date]` | 값 자체 | — | 분배 계열 기본 기준일 | Y |
| `pd_dvid_cycl` | text | observation | `obs:organizer.pref01n001.distribution_cycle[text]` | `pd_dvid_base_dt` | enum A/Q/M/S | 명시된 코드만 제어어휘로 사용 | Y |
| `pd_dvid_inc_dist` | numeric(28,8) | observation | `obs:organizer.pref01n001.source_distribution_amount[numeric]` | `pd_dvid_base_dt` | source amount / `pd_curr_cd` | 성과배분·분배금 원천값 | Y |
| `pd_dvid_nav` | numeric(28,8) | observation | `obs:organizer.pref01n001.distribution_calculation_nav[numeric]` | `pd_dvid_prc_base_dt` | NAV per share / `pd_curr_cd` | 계산 기준 NAV | Y |
| `pd_dvid_pay_cnt` | numeric(28,0) | observation | `obs:organizer.pref01n001.annual_distribution_count[numeric]` | `pd_dvid_base_dt`; 연간 | count | 정수만 허용 | Y |
| `pd_dvid_pay_months` | text | observation | `obs:organizer.pref01n001.distribution_payment_months[text]` | `pd_dvid_base_dt`; 연간 | month list | 순서·원문 보존; 유효 월만 검색 | Y |
| `pd_dvid_prc_base_dt` | text | observation | `obs:organizer.pref01n001.distribution_nav_as_of[date]` | 값 자체 | — | 분배금 계산 NAV에만 적용 | Y |
| `pd_dvid_tax_basis` | text | observation | `obs:organizer.pref01n001.distribution_tax_basis[text]` | `pd_dvid_base_dt` | — | 원천 과세기준 명칭만 사용 | Y |
| `pd_dvid_yield` | numeric(28,8) | observation | `obs:organizer.pref01n001.annualized_distribution_yield[numeric]` | `pd_dvid_base_dt`; 연환산 | percentage point annualized | 과거 총수익률과 비교 금지 | Y |
| `pd_exg_mkt_cd` | text | observation | `obs:organizer.pref01n001.exchange_code[text]` | 정적 | code | 코드표 없이 `Market` 병합 금지 | Y |
| `pd_exg_mkt_nm` | text | observation | `obs:organizer.pref01n001.exchange_name[text]` | 정적 | — | 시장 표시·필터용 원문 | Y |
| `pd_grp_no` | text | catalog | `catalog.security.security_kind` + companion observation | 정적 | ETF/ETN | 명시된 두 값만 사용 | Y |
| `pd_isin_cd` | text | identifier | `catalog.identifier(ISIN)` + companion observation | 정적 | — | checksum-valid·unique만 승격; `pd_itm_no`와 일치 검증 | Y |
| `pd_itm_no` | text | identifier | `catalog.identifier(PREF01_PD_ITM_NO, primary)` + checksum-valid `catalog.identifier(ISIN)` + companion observation | 정적 | — | 1,780개 고유; explicit `pd_isin_cd`가 있으면 일치 필수 | Y |
| `pd_itm_no_ma` | text | identifier | `catalog.identifier(PREF01_PD_ITM_NO_MA)` + companion observation | 정적 | — | source-scoped 유일성 검사 | Y |
| `pd_lst_stk_cnt` | numeric(28,2) | observation | `obs:organizer.pref01n001.listed_security_count[numeric]` | `du_upt_dt` | shares/notes | `pd_stk_cnt`와 중복 합산 금지 | Y |
| `pd_lste_dt` | text | observation | `obs:organizer.pref01n001.trading_end_date[date]` | 값 자체 | — | 명시된 종료일만 사용 | Y |
| `pd_lstg_dt` | text | observation | `obs:organizer.pref01n001.listing_date[date]` | 값 자체 | — | 상장일 | Y |
| `pd_mkt_id` | text | evidence_only | `obs:organizer.pref01n001.market_code_raw[text]` | 정적 | code | 코드표 부재 | L |
| `pd_mkt_nm` | text | observation | `obs:organizer.pref01n001.market_name[text]` | 정적 | — | 원천 시장명 | Y |
| `pd_net_tamt` | numeric(28,2) | observation | `obs:organizer.pref01n001.net_assets[numeric]` | `du_upt_dt` | source amount / `pd_curr_cd` | AUM 계열과 정의를 표시 | Y |
| `pd_nm` | text | catalog | `catalog.entity.canonical_name` + companion observation | 정적 | — | 빈 이름은 source record 격리 | Y |
| `pd_pen_risk_nm` | text | observation | `obs:organizer.pref01n001.pension_risk_class[text]` | `du_upt_dt` | — | 원천 명칭만 사용 | Y |
| `pd_pen_tr_yn` | text | observation | `obs:organizer.pref01n001.pension_trade_eligible[boolean]` | `du_upt_dt` | — | Y/N만 변환 | Y |
| `pd_ric` | text | identifier | `catalog.identifier(REFINITIV_RIC)` + companion observation | 정적 | — | 유효·unique만 승격 | Y |
| `pd_risk_cd` | text | evidence_only | `obs:organizer.pref01n001.risk_grade_code_raw[text]` | `du_upt_dt` | code | 내부 코드표 부재 | L |
| `pd_risk_nm` | text | observation | `obs:organizer.pref01n001.risk_grade_name[text]` | `du_upt_dt` | — | 제공된 등급명만 사용 | Y |
| `pd_sale_yn` | text | observation | `obs:organizer.pref01n001.saleable_in_master[boolean]` | `du_upt_dt` | — | 1/0만 변환; 주문 가능 보장은 아님 | Y |
| `pd_sect_cd` | text | evidence_only | `obs:organizer.pref01n001.sector_code_raw[text]` | `wu_upt_dt` | code | 코드표 부재; 섹터명 추론 금지 | L |
| `pd_spac_yn` | text | observation | `obs:organizer.pref01n001.is_spac[boolean]` | `du_upt_dt` | — | Y/N만 변환; missing은 false 아님 | Y |
| `pd_stk_cnt` | numeric(28,2) | observation | `obs:organizer.pref01n001.security_count[numeric]` | `du_upt_dt` | shares/notes | `pd_lst_stk_cnt`와 별도 원천값 | Y |
| `pd_ticker` | text | catalog | `catalog.alias` + `obs:organizer.pref01n001.refinitiv_ticker[text]` | 정적 | — | 단독 글로벌 identifier로 사용하지 않음 | Y |
| `pd_tr_yn` | text | observation | `obs:organizer.pref01n001.trading_suspended[boolean]` | `du_upt_dt` | — | 1/0만 변환 | Y |
| `ref_ast_type` | text | observation | `obs:organizer.pref01n001.refinitiv_asset_type[text]` | `ref_base_dt` | — | 공급자 분류 원문 | Y |
| `ref_base_dt` | text | observation | `obs:organizer.pref01n001.refinitiv_as_of[date]` | 값 자체 | — | `ref_*`에만 적용 | Y |
| `ref_base_index` | text | relation | source-local Index + `tracksIndex` | `ref_base_dt` | — | 명확한 단일 지수명만 관계; 기존 관계와 충돌 시 제한 | Y |
| `ref_fund_mgmt_co` | text | relation | source-local institution + ETF `managedBy` | `ref_base_dt` | — | organizer 운용사 관계와 충돌 시 자동 선택 금지 | Y |
| `ref_geo_focus` | text | observation | `obs:organizer.pref01n001.refinitiv_geographic_focus[text]` | `ref_base_dt` | — | 공급자 지역분류 원문 | Y |
| `ru_mkt_price` | numeric(28,2) | evidence_only | `obs:organizer.pref01n001.runtime_market_price_raw[numeric]` | 기준시각 없음 | price / KRW | 종가 대체·순위 입력 금지 | L |
| `ru_mkt_volume` | numeric(28,2) | evidence_only | `obs:organizer.pref01n001.runtime_market_volume_raw[numeric]` | 기준시각 없음 | shares/notes | 일거래량과 중복 합산 금지 | L |
| `wu_core_yn` | text | observation | `obs:organizer.pref01n001.internal_core_flag[boolean]` | `wu_upt_dt` | — | Y/N만 변환; 추천 판단으로 확대 금지 | Y |
| `wu_inv_ast_type` | text | observation | `obs:organizer.pref01n001.investment_asset_type[text]` | `wu_upt_dt` | — | 자산군 필터 원문 | Y |
| `wu_inv_rgn` | text | observation | `obs:organizer.pref01n001.investment_region[text]` | `wu_upt_dt` | — | 투자지역 필터 원문 | Y |
| `wu_upt_dt` | text | observation | `obs:organizer.pref01n001.classification_updated_on[date]` | 값 자체 | — | `wu_*`에만 적용 | Y |

## 5. 해외 ETF·ETN `PREF02N001` — 49개

`pd_itm_no` 6,037개는 고유하다. ISIN과 Lipper ID는 각각 63개 중복 그룹이며, 두 중복쌍은 정확히 일치한다. 중복 외부 ID는 `catalog.identifier`로 승격하지 않고 모든 source record의 Evidence에 남긴다.

| 원천 필드 | 원천 타입 | 분류 | 저장 대상 | 날짜·기간 | 단위·통화 | 상태·제약 | 근거 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cu_base_index` | text | relation | source-local Index + `tracksIndex` | `cu_upt_dt` | — | 명확한 단일 지수명만 관계 생성 | Y |
| `cu_charge_rt` | numeric(18,6) | observation | `obs:organizer.pref02n001.total_fee_rate[numeric]` | `cu_upt_dt` | percentage point | 연간 보수율 | Y |
| `cu_etn_yn` | text | observation | `obs:organizer.pref02n001.is_etn[boolean]` | `cu_upt_dt` | — | Y만 true; missing은 false 아님 | Y |
| `cu_fund_mgmt_co` | text | relation | ETF→source-local institution + `managedBy`; ETN→provider text observation | `cu_upt_dt` | — | ETN 발행기관이라고 추론하지 않음 | Y |
| `cu_index_repl_mthd` | text | observation | `obs:organizer.pref02n001.index_replication_method[text]` | `cu_upt_dt` | — | 공급자 원문 분류 | Y |
| `cu_index_tracking_yn` | text | observation | `obs:organizer.pref02n001.index_tracking_flag[boolean]` | `cu_upt_dt` | — | Y만 true; missing은 false 아님 | Y |
| `cu_inverse_short_yn` | text | observation | `obs:organizer.pref02n001.inverse_short_flag[boolean]` | `cu_upt_dt` | — | Y만 true; missing은 false 아님 | Y |
| `cu_lev_fector` | numeric(18,6) | observation | `obs:organizer.pref02n001.leverage_factor[numeric]` | `cu_upt_dt` | multiple | 0도 원문 상태로 보존; 일반형 1로 보간 금지 | Y |
| `cu_strtegy` | text | observation | `obs:organizer.pref02n001.strategy_description[text]` | `cu_upt_dt` | — | 공식 원문 | Y |
| `cu_upt_dt` | text | observation | `obs:organizer.pref02n001.structure_updated_on[date]` | 값 자체 | — | `cu_*`에만 적용 | Y |
| `du_base_dt_match_yn` | text | observation | `obs:organizer.pref02n001.price_nav_date_match[boolean]` | `du_upt_dt` | — | Y/N만 변환; 불일치 시 교차가격 계산 제한 | Y |
| `du_bpr` | numeric(28,8) | observation | `obs:organizer.pref02n001.base_price[numeric]` | `du_nav_base_dt` 또는 `du_upt_dt` | price per share / `pd_curr_cd` | 원천 기준가 | Y |
| `du_clpr` | numeric(28,8) | observation | `obs:organizer.pref02n001.close_price[numeric]` | `du_clpr_base_dt` | price per share / `pd_trd_ccy` | 선택된 종가 원천과 함께 사용 | Y |
| `du_clpr_base_dt` | text | observation | `obs:organizer.pref02n001.close_price_as_of[date]` | 값 자체 | — | OHLC·거래 계열에 적용 | Y |
| `du_clpr_src` | text | evidence_only | `obs:organizer.pref02n001.close_price_source_raw[text]` | `du_clpr_base_dt` | source column | 내부 원천 컬럼명; 사용자 순위 입력 금지 | L |
| `du_diff_rt` | numeric(28,6) | observation | `obs:organizer.pref02n001.premium_discount_rate[numeric]` | 종가=`du_clpr_base_dt`; NAV=`du_nav_base_dt` | percentage point | 날짜 불일치면 limited 표시 | Y |
| `du_er_1d` | numeric(28,6) | observation | `obs:organizer.pref02n001.cumulative_return_1d[numeric]` | 종료=`du_clpr_base_dt`; 1일 | percentage point | 0을 missing으로 바꾸지 않음 | Y |
| `du_hpr` | numeric(28,8) | observation | `obs:organizer.pref02n001.high_price[numeric]` | `du_clpr_base_dt` | price per share / `pd_trd_ccy` | 일간 고가 | Y |
| `du_last_aum` | numeric(28,2) | observation | `obs:organizer.pref02n001.aum[numeric]` | `du_nav_base_dt` | amount / `pd_curr_cd` | 원화 순위에는 공식 환율 Evidence 필요 | Y |
| `du_last_nav` | numeric(28,6) | observation | `obs:organizer.pref02n001.nav_per_share[numeric]` | `du_nav_base_dt` | NAV per share / `pd_curr_cd` | 추정 NAV임을 표시 | Y |
| `du_lpr` | numeric(28,8) | observation | `obs:organizer.pref02n001.low_price[numeric]` | `du_clpr_base_dt` | price per share / `pd_trd_ccy` | 일간 저가 | Y |
| `du_nav_base_dt` | text | observation | `obs:organizer.pref02n001.nav_as_of[date]` | 값 자체 | — | NAV·AUM 계열에 적용 | Y |
| `du_opr` | numeric(28,8) | observation | `obs:organizer.pref02n001.open_price[numeric]` | `du_clpr_base_dt` | price per share / `pd_trd_ccy` | 일간 시가 | Y |
| `du_upt_dt` | text | observation | `obs:organizer.pref02n001.daily_updated_on[date]` | 값 자체 | — | 적재·갱신일; 거래일과 구분 | Y |
| `du_val_1d` | numeric(28,8) | observation | `obs:organizer.pref02n001.trading_value_1d[numeric]` | `du_clpr_base_dt`; 1거래일 | amount / `pd_trd_ccy` | 외화 거래대금 | Y |
| `du_vol_1d` | numeric(28,8) | observation | `obs:organizer.pref02n001.trading_volume_1d[numeric]` | `du_clpr_base_dt`; 1거래일 | shares/notes | runtime 거래량과 중복 합산 금지 | Y |
| `pd_abrv_nm` | text | catalog | `catalog.alias` + ticker display + companion observation | 정적 | — | 표시 티커; 단독 글로벌 identity 아님 | Y |
| `pd_curr_cd` | text | catalog | `catalog.product.primary_currency` + companion observation | 정적 | ISO 4217 원문 | 펀드 기준통화 | Y |
| `pd_exg_mkt_cd` | text | evidence_only | `obs:organizer.pref02n001.exchange_code_raw[text]` | 정적 | code | 코드표 없이 Market 통합 금지 | L |
| `pd_grp_no` | text | catalog | `catalog.security.security_kind` + companion observation | 정적 | ETF/ETN | 명시된 두 값만 사용 | Y |
| `pd_isin_cd` | text | identifier | `catalog.identifier(ISIN)` + companion observation | 정적 | — | valid·unique만 승격; 63개 중복 그룹은 Evidence only | Y |
| `pd_itm_no` | text | identifier | `catalog.identifier(PREF02_PD_ITM_NO, primary)` + companion observation | 정적 | RIC-like source key | 6,037개 고유 organizer identity | Y |
| `pd_itm_no_ma` | text | identifier | `catalog.identifier(PREF02_PD_ITM_NO_MA)` + companion observation | 정적 | — | 유효·source-scoped unique만 승격 | Y |
| `pd_lipper_id` | text | identifier | `catalog.identifier(LIPPER)` + companion observation | 정적 | — | valid·unique만 승격; 63개 중복 그룹은 Evidence only | Y |
| `pd_lstg_dt` | text | observation | `obs:organizer.pref02n001.listing_date[date]` | 값 자체 | — | 설정·상장일 원천 의미 유지 | Y |
| `pd_lst_price` | numeric(28,8) | observation | `obs:organizer.pref02n001.face_value[numeric]` | 정적 | amount / `pd_curr_cd` | 0도 보존; 시장가격으로 사용 금지 | Y |
| `pd_lst_stk_cnt` | numeric(28,2) | observation | `obs:organizer.pref02n001.listed_security_count[numeric]` | `du_upt_dt` | shares/notes | ETF·ETN 단위 구분 | Y |
| `pd_mkt_id` | text | evidence_only | `obs:organizer.pref02n001.market_country_code_raw[text]` | 정적 | code | 투자지역을 뜻하지 않음 | L |
| `pd_nm` | text | catalog | `catalog.entity.canonical_name` + companion observation | 정적 | — | 빈 이름은 source record 격리 | Y |
| `pd_sale_yn` | text | observation | `obs:organizer.pref02n001.saleable_in_master[boolean]` | `du_upt_dt` | — | 1/0만 변환; missing은 false 아님 | Y |
| `pd_trd_ccy` | text | observation | `obs:organizer.pref02n001.trading_currency[text]` | 정적 | ISO 4217 원문 | 실제 거래통화 | Y |
| `pd_tr_yn` | text | observation | `obs:organizer.pref02n001.trading_suspended[boolean]` | `du_upt_dt` | — | 1/0만 변환; missing은 false 아님 | Y |
| `pd_us_cik` | text | evidence_only | `obs:organizer.pref02n001.us_cik_raw[text]` | 정적 | registrant identifier | 상품 identifier로 승격하지 않음 | L |
| `ru_mkt_price` | numeric(28,8) | evidence_only | `obs:organizer.pref02n001.runtime_market_price_raw[numeric]` | 기준시각 없음 | price / `pd_trd_ccy` | 종가 대체·순위 입력 금지 | L |
| `ru_mkt_volume` | numeric(28,8) | evidence_only | `obs:organizer.pref02n001.runtime_market_volume_raw[numeric]` | 기준시각 없음 | shares/notes | 일거래량과 중복 합산 금지 | L |
| `wu_core_yn` | text | observation | `obs:organizer.pref02n001.internal_core_flag[boolean]` | `wu_upt_dt` | — | Y/N만 변환; 추천 의미로 확대 금지 | Y |
| `wu_inv_ast_type` | text | observation | `obs:organizer.pref02n001.investment_asset_type[text]` | `wu_upt_dt` | — | 자산군 필터 원문 | Y |
| `wu_inv_rgn` | text | observation | `obs:organizer.pref02n001.investment_region[text]` | `wu_upt_dt` | — | 투자지역 필터 원문 | Y |
| `wu_upt_dt` | text | observation | `obs:organizer.pref02n001.classification_updated_on[date]` | 값 자체 | — | `wu_*`에만 적용 | Y |

## 6. 공모펀드 `PRFD01N001` — 75개

모든 `itm_no`가 고유하므로 대표 원본 행 선택 로직을 사용하지 않는다. `prfd_attr_cds`와 `zrin_attr_nms`는 원문 목록을 Evidence에 보존하고, 공백 제거·원래 순서 유지·중복 제거 후 반복 observation으로 펼친다.

| 원천 필드 | 원천 타입 | 분류 | 저장 대상 | 날짜·기간 | 단위·통화 | 상태·제약 | 근거 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `bmrk_eng_nm` | text | evidence_only | `obs:organizer.prfd01n001.benchmark_english_raw[text]` | 정적 | — | 숫자성·혼합 문구를 Index alias로 만들지 않음 | L |
| `bmrk_nm` | text | relation | 명확한 단일 benchmark→source-local Index + `tracksIndex`; otherwise raw observation | 정적 | — | 복수 지수·비중·설명문은 관계로 단순화하지 않음 | Y |
| `bns_bpr` | numeric(38,15) | observation | `obs:organizer.prfd01n001.trading_base_price[numeric]` | `fd_price_bas_dt` | price per unit / `curr_cd` | 기준가 계열 원천값 | Y |
| `curr_cd` | text | catalog | `catalog.product.primary_currency` + companion observation | 정적 | ISO 4217 원문 | 유효 코드만 승격 | Y |
| `exchdg_yn` | text | observation | `obs:organizer.prfd01n001.currency_hedged[boolean]` | `fd_daily_bas_dt` | — | Y/N만 변환; missing은 false 아님 | Y |
| `fd_daily_bas_dt` | text | observation | `obs:organizer.prfd01n001.daily_information_as_of[date]` | 값 자체 | — | 일간·자산 계열 기본 기준일 | Y |
| `fd_estb_ctry_cd` | text | evidence_only | `obs:organizer.prfd01n001.establishment_country_code_raw[text]` | 정적 | code | 공식 코드체계 부재; `000` 번역 금지 | L |
| `fd_ivst_rgn_desc` | text | observation | `obs:organizer.prfd01n001.investment_region[text]` | `fd_daily_bas_dt` | — | 제공된 설명명만 사용 | Y |
| `fd_last_dstb_actg_bss_dt` | text | observation | `obs:organizer.prfd01n001.last_distribution_accounting_start[date]` | 값 자체 | — | 최근 분배 회계기간 시작 | Y |
| `fd_last_dstb_actg_eot_dt` | text | observation | `obs:organizer.prfd01n001.last_distribution_accounting_end[date]` | 값 자체 | — | 최근 분배 회계기간 종료 | Y |
| `fd_last_dstb_r` | numeric(20,12) | observation | `obs:organizer.prfd01n001.last_distribution_rate[numeric]` | 종료=`fd_last_dstb_actg_eot_dt` | percentage point, source-defined | 총수익률과 비교 금지 | Y |
| `fd_mm18_ern_r` | numeric(30,2) | observation | `obs:organizer.prfd01n001.cumulative_return_18m[numeric]` | 종료=`fd_price_bas_dt`; 18개월 | percentage point | 누적수익률 | Y |
| `fd_mm1_ern_r` | numeric(30,2) | observation | `obs:organizer.prfd01n001.cumulative_return_1m[numeric]` | 종료=`fd_price_bas_dt`; 1개월 | percentage point | 누적수익률 | Y |
| `fd_mm3_ern_r` | numeric(30,2) | observation | `obs:organizer.prfd01n001.cumulative_return_3m[numeric]` | 종료=`fd_price_bas_dt`; 3개월 | percentage point | 누적수익률 | Y |
| `fd_mm6_ern_r` | numeric(30,2) | observation | `obs:organizer.prfd01n001.cumulative_return_6m[numeric]` | 종료=`fd_price_bas_dt`; 6개월 | percentage point | 누적수익률 | Y |
| `fd_nast_suma` | numeric(22,4) | observation | `obs:organizer.prfd01n001.net_assets[numeric]` | `fd_daily_bas_dt` | source amount / `curr_cd` | AUM 비교 시 원단위·환율 Evidence 필요 | Y |
| `fd_price_bas_dt` | text | observation | `obs:organizer.prfd01n001.price_return_as_of[date]` | 값 자체 | — | 기준가·수익률에 적용 | Y |
| `fd_prsv_r` | numeric(20,12) | observation | `obs:organizer.prfd01n001.preservation_rate[numeric]` | `fd_daily_bas_dt` | percentage point, source-defined | 보전 대상·산식 확대해석 금지 | Y |
| `fd_sbpr` | numeric(30,12) | observation | `obs:organizer.prfd01n001.market_valuation_amount[numeric]` | `fd_price_bas_dt` | amount / `curr_cd` | 순자산과 중복 합산 금지 | Y |
| `fd_set_pcd` | text | evidence_only | `obs:organizer.prfd01n001.establishment_type_code_raw[text]` | 정적 | code | 코드표 부재 | L |
| `fd_wk1_ern_r` | numeric(30,2) | observation | `obs:organizer.prfd01n001.cumulative_return_1w[numeric]` | 종료=`fd_price_bas_dt`; 1주 | percentage point | 누적수익률 | Y |
| `fd_yr1_ern_r` | numeric(30,2) | observation | `obs:organizer.prfd01n001.cumulative_return_1y[numeric]` | 종료=`fd_price_bas_dt`; 1년 | percentage point | 기본 연간수익률 비교 후보 | Y |
| `fd_yr2_ern_r` | numeric(30,2) | observation | `obs:organizer.prfd01n001.cumulative_return_2y[numeric]` | 종료=`fd_price_bas_dt`; 2년 | percentage point | 누적수익률; 연환산 아님 | Y |
| `fd_yr3_ern_r` | numeric(30,2) | observation | `obs:organizer.prfd01n001.cumulative_return_3y[numeric]` | 종료=`fd_price_bas_dt`; 3년 | percentage point | 누적수익률; 연환산 아님 | Y |
| `fd_yr5_ern_r` | numeric(30,2) | observation | `obs:organizer.prfd01n001.cumulative_return_5y[numeric]` | 종료=`fd_price_bas_dt`; 5년 | percentage point | 누적수익률; 연환산 아님 | Y |
| `frc_bpr_itm_yn` | text | observation | `obs:organizer.prfd01n001.foreign_currency_base_price[boolean]` | `fd_price_bas_dt` | — | 1/0만 변환 | Y |
| `fss_itm_no` | text | identifier | `catalog.identifier(FSS_FUND)` + companion observation | 정적 | — | 센티널·invalid·duplicate 제외 | Y |
| `han_clas_fee_type` | text | observation | `obs:organizer.prfd01n001.share_class_fee_type[text]` | 정적 | — | 제공된 수수료 유형명만 사용 | Y |
| `han_clas_nm` | text | catalog | `catalog.alias` + `obs:organizer.prfd01n001.share_class_name[text]` | 정적 | — | 클래스 표시·검색명 | Y |
| `han_clas_policies` | text | observation | `obs:organizer.prfd01n001.share_class_policies[text]` | 정적 | — | 원문 정책 목록; 규정 효과 추론 금지 | Y |
| `han_clas_sales_channel` | text | observation | `obs:organizer.prfd01n001.share_class_sales_channel[text]` | `fd_daily_bas_dt` | — | 판매채널 원문 | Y |
| `hdge_fd_yn` | text | observation | `obs:organizer.prfd01n001.is_hedge_fund[boolean]` | `fd_daily_bas_dt` | — | 1/0만 변환; 환헤지 여부와 구분 | Y |
| `int_dvd_desc` | text | observation | `obs:organizer.prfd01n001.interest_dividend_class[text]` | `fd_daily_bas_dt` | — | 제공된 설명명만 사용 | Y |
| `itm_abrv_nm` | text | catalog | `catalog.alias` + companion observation | 정적 | — | 한글 약어 | Y |
| `itm_eabrv_nm` | text | catalog | `catalog.alias` + companion observation | 정적 | — | 영문 약어 | Y |
| `itm_eng_nm` | text | catalog | `catalog.alias` + companion observation | 정적 | — | 이상문구는 alias로 승격하지 않음 | Y |
| `itm_nm` | text | catalog | `catalog.entity.canonical_name` + companion observation | 정적 | — | 사용자 표시 우선 이름 | Y |
| `itm_no` | text | identifier | `catalog.identifier(PRFD_ITM_NO, primary)` + companion observation | 정적 | — | 23,676개 고유 source identity | Y |
| `kofia_fd_ccd` | text | evidence_only | `obs:organizer.prfd01n001.kofia_classification_code_raw[text]` | 정적 | code | 공식 코드표 부재 | L |
| `ksd_itm_no` | text | identifier | `catalog.identifier(KSD_PRODUCT)` + checksum-valid `catalog.identifier(ISIN)` + companion observation | 정적 | ISIN | valid·unique만 승격; 국내 ETF 217개 exact match는 entity 재사용 | Y |
| `mtco_itm_no` | text | identifier | `catalog.identifier(MANAGER_SCOPED_PRODUCT)` + companion observation | 정적 | — | `or_co_xtn_itt_cd` namespace 안에서만 유일성 검사 | Y |
| `ofsfd_yn` | text | observation | `obs:organizer.prfd01n001.is_offshore_fund[boolean]` | `fd_daily_bas_dt` | — | 1/0만 변환; 해외투자 여부와 구분 | Y |
| `ofwk_trus_rwrd_r` | numeric(20,12) | observation | `obs:organizer.prfd01n001.administration_fee_rate[numeric]` | `fd_daily_bas_dt` | source rate | 단위 스케일 검증 전 cross-source 환산 금지 | Y |
| `or_attr_desc` | text | observation | `obs:organizer.prfd01n001.management_attribute[text]` | `fd_daily_bas_dt` | — | 원천 분류 설명 | Y |
| `or_co_rwrd_r` | numeric(20,12) | observation | `obs:organizer.prfd01n001.manager_fee_rate[numeric]` | `fd_daily_bas_dt` | source rate | 단위 스케일 검증 전 cross-source 환산 금지 | Y |
| `or_co_xtn_itt_cd` | text | relation | source-local institution + `managedBy` | `fd_daily_bas_dt` | institution code | 코드 namespace 내부에서만 기관 identity 생성 | Y |
| `ovrs_fd_desc` | text | observation | `obs:organizer.prfd01n001.overseas_fund_class[text]` | `fd_daily_bas_dt` | — | 국내·해외·혼합 원문 분류 | Y |
| `pers_corp_desc` | text | observation | `obs:organizer.prfd01n001.investor_type[text]` | `fd_daily_bas_dt` | — | 제공된 설명명만 사용 | Y |
| `pfiv_sale_cntl_tcd` | text | evidence_only | `obs:organizer.prfd01n001.professional_sale_control_code_raw[text]` | `fd_daily_bas_dt` | code | 코드표 부재; 판매제약 추론 금지 | L |
| `prfd_attr_cds` | text | observation | ordered repeated `obs:organizer.prfd01n001.attribute_code[text]` + raw Evidence | 정적 | code list | split·trim·stable de-dup; 코드 의미 번역 금지 | Y |
| `prfd_attr_cnt` | text | observation | `obs:organizer.prfd01n001.attribute_count[numeric]` | 정적 | count | 정수 변환 후 파싱 목록 길이와 일치해야 함 | Y |
| `prfd_attr_search_text` | text | observation | `obs:organizer.prfd01n001.attribute_search_text[text]` | 정적 | — | 검색 보조 원문; 독립 사실·관계로 과대해석 금지 | Y |
| `prvo_fd_desc` | text | observation | `obs:organizer.prfd01n001.private_fund_detail[text]` | `fd_daily_bas_dt` | — | 제공된 설명명만 사용 | Y |
| `prvo_pbff_desc` | text | observation | `obs:organizer.prfd01n001.public_private_class[text]` | `fd_daily_bas_dt` | — | 공모·사모 필터 우선 필드 | Y |
| `rptt_ksd_itm_no` | text | relation | source-local representative fund + `hasShareClass` | 정적 | identifier | 센티널·invalid 제외; 자기참조·cycle 방지 | Y |
| `sale_co_rwrd_r` | numeric(20,12) | observation | `obs:organizer.prfd01n001.sales_fee_rate[numeric]` | `fd_daily_bas_dt` | source rate | 단위 스케일 검증 전 cross-source 환산 금지 | Y |
| `sale_yn` | text | observation | `obs:organizer.prfd01n001.sale_status[text]` | `fd_daily_bas_dt` | — | 판매중·판매완료 원문; 실시간 주문 가능 보장 아님 | Y |
| `std_itm_no` | text | identifier | `catalog.identifier(PRFD_STANDARD_PRODUCT)` + companion observation | 정적 | — | 유효·unique만 승격 | Y |
| `thco_sale_yn` | text | observation | `obs:organizer.prfd01n001.sold_by_provider[boolean]` | `fd_daily_bas_dt` | — | Y만 true; missing은 false 아님 | Y |
| `trusc_rwrd_r` | numeric(20,12) | observation | `obs:organizer.prfd01n001.trustee_fee_rate[numeric]` | `fd_daily_bas_dt` | source rate | 단위 스케일 검증 전 cross-source 환산 금지 | Y |
| `trusc_xtn_itt_cd` | text | evidence_only | `obs:organizer.prfd01n001.trustee_institution_code_raw[text]` | `fd_daily_bas_dt` | code | 승인된 관계에 수탁관계가 없어 edge 미생성 | L |
| `zrin_attr_nms` | text | observation | ordered repeated `obs:organizer.prfd01n001.zeroin_attribute_name[text]` + raw Evidence | `fd_daily_bas_dt` | name list | split·trim·stable de-dup | Y |
| `zrin_btyp_cd` | text | evidence_only | `obs:organizer.prfd01n001.zeroin_major_type_code_raw[text]` | `fd_daily_bas_dt` | code | 코드표 부재 | L |
| `zrin_btyp_nm` | text | observation | `obs:organizer.prfd01n001.zeroin_major_type_name[text]` | `fd_daily_bas_dt` | — | 공급자 분류명 | Y |
| `zrin_dmst_bd_cmst_rt` | numeric(26,12) | observation | `obs:organizer.prfd01n001.domestic_bond_weight[numeric]` | `fd_daily_bas_dt` | percentage point | broad asset composition; 개별 보유종목 증거 아님 | Y |
| `zrin_dmst_stk_cmst_rt` | numeric(26,12) | observation | `obs:organizer.prfd01n001.domestic_equity_weight[numeric]` | `fd_daily_bas_dt` | percentage point | broad asset composition; 개별 보유종목 증거 아님 | Y |
| `zrin_etc_ast_cmst_rt` | numeric(26,12) | observation | `obs:organizer.prfd01n001.other_asset_weight[numeric]` | `fd_daily_bas_dt` | percentage point | 구성비 합계 검증; 임의 잔차 보정 금지 | Y |
| `zrin_fd_cmst_rt` | numeric(26,12) | observation | `obs:organizer.prfd01n001.fund_weight[numeric]` | `fd_daily_bas_dt` | percentage point | broad asset composition | Y |
| `zrin_fd_ivst_risk_gcd` | text | evidence_only | `obs:organizer.prfd01n001.risk_grade_code_raw[text]` | `fd_daily_bas_dt` | code | 내부 코드표 부재; 이름을 통한 역번역 금지 | L |
| `zrin_fd_ivst_risk_grd_nm` | text | observation | `obs:organizer.prfd01n001.risk_grade_name[text]` | `fd_daily_bas_dt` | — | 제공된 위험등급명만 사용 | Y |
| `zrin_liqt_cmst_rt` | numeric(26,12) | observation | `obs:organizer.prfd01n001.liquidity_weight[numeric]` | `fd_daily_bas_dt` | percentage point | 구성비 합계 검증; 임의 잔차 보정 금지 | Y |
| `zrin_ovrs_bd_cmst_rt` | numeric(26,12) | observation | `obs:organizer.prfd01n001.overseas_bond_weight[numeric]` | `fd_daily_bas_dt` | percentage point | broad asset composition; 개별 보유종목 증거 아님 | Y |
| `zrin_ovrs_stk_cmst_rt` | numeric(26,12) | observation | `obs:organizer.prfd01n001.overseas_equity_weight[numeric]` | `fd_daily_bas_dt` | percentage point | broad asset composition; 개별 보유종목 증거 아님 | Y |
| `zrin_pcd` | text | evidence_only | `obs:organizer.prfd01n001.zeroin_type_code_raw[text]` | `fd_daily_bas_dt` | code | 코드표 부재 | L |
| `zrin_ptn_nm` | text | observation | `obs:organizer.prfd01n001.zeroin_type_name[text]` | `fd_daily_bas_dt` | — | 공급자 분류명 | Y |

## 7. 전수 대조 결과

| 소스 | identifier | catalog | relation | observation | evidence_only | ignored | 합계 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `PRBD01N001` | 1 | 5 | 1 | 45 | 5 | 1 | 58 |
| `PREF01N001` | 4 | 5 | 4 | 78 | 7 | 0 | 98 |
| `PREF02N001` | 4 | 4 | 2 | 33 | 6 | 0 | 49 |
| `PRFD01N001` | 5 | 6 | 3 | 52 | 9 | 0 | 75 |
| **합계** | **14** | **20** | **10** | **208** | **27** | **1** | **280** |

스키마 워크북과 이 문서를 기계적으로 대조한 결과, 네 섹션 모두 필드 수·이름·순서·원천 타입이 정확히 일치하고 누락·중복·추가 필드가 없다. `relation` 수는 관계를 만드는 원천 필드 종류 수이며 실제 relation record 수와 다르다.

## 8. identity·중복·공백 정책

1. normalized entity를 쓰기 전에 네 organizer source의 identifier를 전수 pre-scan하고 canonical organizer entity ID를 결정한다.
2. 그 결과를 외부 source보다 먼저 `AuthoritativeIdentityIndex`로 동결한다.
3. key는 `(identifier_scheme, normalized_value)`이며 결과는 `MATCHED`, `NOT_FOUND`, `AMBIGUOUS` 셋뿐이다.
4. 같은 entity의 같은 `(scheme, value)`를 여러 organizer 필드가 입증하면 identifier record는 하나만 만들고 Evidence origin만 모두 연결한다.
5. `MATCHED`면 organizer entity를 재사용하고 외부 관측·관계·Evidence만 추가한다.
6. `NOT_FOUND`일 때만 승인된 외부 mapper가 source-specific entity를 만든다.
7. `AMBIGUOUS`면 자동 병합도 새 canonical identifier 생성도 하지 않는다. 원문 후보와 coverage limitation만 남긴다.
8. 모든 blank는 `missing`이며, 명시적 zero와 다르다. 둘 다 행 제거 사유가 아니다.
9. 코드표가 없는 내부 코드는 Evidence 또는 raw observation으로 남기되 사용자에게 코드 의미를 답하지 않는다.
10. `BUYABLE_QUANTITY`는 저장된 사실이 아니다. 명시적 상장폐지·listing 종료가 없는 채권은 공지의 가정에 따라 구매 가능 후보로 취급한다.

## 9. 구현 승인 시 고정되는 핵심 판단

1. 새 8개 workbook만 authoritative organizer baseline으로 사용한다.
2. 기존 207필드 mapper와 old public-fund canonical-row 알고리즘은 호환 overlay 없이 교체한다.
3. `PRBD01N001`은 product와 sale LOT grain을 분리한다.
4. 국내 ETF·공모펀드 exact 217건은 organizer ETF entity를 재사용하고 이중 집계하지 않는다.
5. 해외 ETF의 중복 ISIN·Lipper 63쌍은 유일 identifier로 승격하지 않는다.
6. N-PORT 등 외부 보유종목은 동일 `AuthoritativeIdentityIndex`를 사용한다.
7. 공모펀드 asset composition은 개별 `holdsSecurity` 근거가 아니므로, 구성종목 교차질의에는 별도의 승인된 공식 holdings source가 필요하다.
8. 사실·관계·Evidence 물리 구조는 유지하되, 고정 cutoff 충돌을 해소하는 ADR-0017의 최소 Alembic `0006`은 mapper보다 먼저 구현한다.

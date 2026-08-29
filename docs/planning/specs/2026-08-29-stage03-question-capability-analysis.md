# Stage 03 질문 → Capability → 저장소 분석

**기준일:** 2026-08-24

**분석 대상:** 내부 회귀 질문 52개와 공개된 공식 35문항 질문 가족

**기계가독 기준:** `tests/gold/core_questions.json` schema 1.2

**문서 성격:** 기계가독 기준을 사람이 검토할 수 있게 정규화한 분석 투영본

## 1. 판정 원칙

- 질문을 DB에 직접 고정하지 않고 `질문 → 요구사항 → Capability → 저장소 역할 → Evidence → Disposition`으로 처리한다.
- PostgreSQL은 수치·상태·계산·Evidence의 권위 원장이고 Graph는 승인 관계의 투영본이다.
- Vector와 Keyword는 공식 문서 후보를 찾을 뿐, 원문 span이 Evidence로 변환되기 전에는 Claim을 지지하지 않는다.
- 주최 측 필드의 NULL·빈 값·검토된 placeholder는 같은 의미의 외부값으로 채우지 않는다.
- 아래 `지원 상태`는 2026-08-27에 동결된 설계상 데이터 커버리지다. 52개 질문의 현재 DB 종단간 실행 검증은 아직 `not_run`이다.
- `requires_data=true`는 `support_level=requires_additional_data`와 동일하다. `unsupported`는 데이터 추가 대상이 아니라 정책·범위·근거 제약에 따른 제한이다.

### 지원 상태 분포

|supported|limited|requires_additional_data|unsupported|
|---:|---:|---:|---:|
|16|18|11|7|

## 2. 52개 질문별 상세 분석

### 01. `LKP-DETF-001`

**질문 원문:** 이 국내 ETF의 운용사, 위험등급, 연금거래 가능 여부와 데이터 기준일을 알려줘.

- 질문 유형: `exact_lookup` / `domestic_etf_exact_fact_lookup`
- Entity: `AssetManager`, `DomesticETF`
- Metric·구조화 사실: `pension_eligibility`, `risk_grade`
- 원천 필드: `pd_itm_no`, `pd_nm`, `pd_grp_no`, `cu_fund_mgmt_co`, `pd_risk_nm`, `pd_pen_tr_yn`, `du_upt_dt`
- 승인 Relation: `managedBy`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `EXACT_PRODUCT_IDENTITY`, `ETF_ONLY`, `DISCLOSE_APPLICABLE_DATE`, `closed_world_coverage`
- Capability: `resolve_product`, `lookup_facts`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `resolve_product→keyword`, `lookup_facts→rdb`
- 결정론적 연산: 없음
- Evidence 요구사항: `table`, `product_id`, `field`, `value`, `as_of`
- 데이터 요구사항: `domestic_etf_master(available)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: 연금거래 가능 여부를 개인별 적합성으로 확대 해석하지 않는다.

### 02. `LKP-OETF-001`

**질문 원문:** 티커가 ABCD인 해외 ETF의 정식명, 운용사, 투자지역, 기초지수와 거래통화를 알려줘.

- 질문 유형: `exact_lookup` / `overseas_etf_ticker_lookup`
- Entity: `AssetManager`, `Index`, `OverseasETF`
- Metric·구조화 사실: `investment_region`, `trading_currency`
- 원천 필드: `pd_abrv_nm`, `pd_itm_no`, `pd_nm`, `pd_grp_no`, `cu_fund_mgmt_co`, `wu_inv_rgn`, `cu_base_index`, `pd_trd_ccy`
- 승인 Relation: `managedBy`, `tracksIndex`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ETF_ONLY`, `TICKER_IS_NOT_PRIMARY_KEY`, `PLACEHOLDER_INDEX_IS_MISSING`, `closed_world_coverage`
- Capability: `resolve_ticker`, `lookup_facts`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `resolve_ticker→keyword`, `lookup_facts→rdb`
- 결정론적 연산: 없음
- Evidence 요구사항: `table`, `product_id`, `field`, `value`, `as_of`, `missing_reason`
- 데이터 요구사항: `overseas_etf_master(available)`
- 지원 상태: `limited`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 기초지수 등 주최 측 결측은 외부값으로 보충하지 않고 해당 필드를 확인 불가로 반환한다.
- 위험·표현 주의: 문장형 기초지수 결측을 실제 지수명으로 표시하지 않는다.

### 03. `LKP-BOND-001`

**질문 원문:** 한빛전자 회사채를 찾아서 발행일, 만기일, 표면금리와 신용등급을 알려줘.

- 질문 유형: `exact_lookup` / `bond_name_disambiguated_lookup`
- Entity: `DomesticBond`, `Issuer`
- Metric·구조화 사실: `credit_grade`
- 원천 필드: `PD_NO`, `PD_NM`, `PD_PBCM`, `ISU_DT`, `MAT_DT`, `SRFC_IRT`, `CRD_GRD`, `CRD_GRD_DT`
- 승인 Relation: `issuedBy`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `DO_NOT_MERGE_DISTINCT_ISSUES`, `DISCLOSE_MISSING_CREDIT_GRADE`, `closed_world_coverage`
- Capability: `search_by_name`, `disambiguate_issues`, `lookup_facts`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `search_by_name→keyword`, `disambiguate_issues→rdb`, `lookup_facts→rdb`
- 결정론적 연산: 없음
- Evidence 요구사항: `table`, `product_id`, `field`, `value`, `as_of`
- 데이터 요구사항: `domestic_bond_master(available)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: 같은 발행사 채권이라도 발행일과 만기가 다르면 별도 종목이다.

### 04. `LKP-FUND-001`

**질문 원문:** 새봄글로벌주식형 펀드의 판매 클래스별 상품번호, 판매상태와 위험등급을 보여줘.

- 질문 유형: `exact_lookup` / `public_fund_share_class_lookup`
- Entity: `FundShareClass`, `PublicFund`, `RepresentativeFund`
- Metric·구조화 사실: `risk_grade`, `sale_status`
- 원천 필드: `itm_no`, `itm_nm`, `rptt_ksd_itm_no`, `sale_yn`, `zrin_fd_ivst_risk_gcd`
- 승인 Relation: `hasShareClass` (hasShareClass 역방향)
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `DEDUP_BY_ITM_NO`, `INVALID_REPRESENTATIVE_SENTINEL_IS_MISSING`, `closed_world_coverage`
- Capability: `resolve_fund_group`, `list_unique_share_classes`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `resolve_fund_group→keyword`, `list_unique_share_classes→rdb`
- 결정론적 연산: 없음
- Evidence 요구사항: `table`, `product_id`, `field`, `value`, `exclusion_reason`
- 데이터 요구사항: `public_fund_master(available)`
- 지원 상태: `limited`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 주최 측 식별자로 확인되는 판매 클래스만 그룹화하며 불명한 대표펀드 연결은 하지 않는다.
- 위험·표현 주의: 원본 속성행을 판매 클래스 수로 세지 않는다.

### 05. `FLT-DETF-001`

**질문 원문:** 미국 주식에 투자하면서 연금거래가 가능하고 판매중이며 거래정지가 아닌 국내 ETF만 보여줘.

- 질문 유형: `compound_filter` / `domestic_etf_operational_multi_filter`
- Entity: `DomesticETF`
- Metric·구조화 사실: `asset_class`, `investment_region`, `pension_eligibility`, `sale_status`
- 원천 필드: `pd_grp_no`, `wu_inv_ast_type`, `wu_inv_rgn`, `pd_pen_tr_yn`, `pd_sale_yn`, `pd_tr_yn`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ETF_ONLY`, `SALEABLE_EQUALS_1`, `TRADING_SUSPENDED_EQUALS_1`, `PENSION_ELIGIBLE_EQUALS_Y`
- Capability: `apply_product_type_filter`, `apply_classification_filters`, `apply_operational_filters`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `apply_product_type_filter→rdb`, `apply_classification_filters→rdb`, `apply_operational_filters→rdb`
- 결정론적 연산: `apply_product_type_filter`, `apply_classification_filters`, `apply_operational_filters`
- Evidence 요구사항: `table`, `product_id`, `filters`, `field`, `value`, `as_of`
- 데이터 요구사항: `domestic_etf_master(available)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: 판매와 거래정지, 연금 가능 상태를 서로 다른 조건으로 적용한다.

### 06. `FLT-OETF-001`

**질문 원문:** 일본 주식형 해외 ETF 중 총보수 0.5% 이하이고 AUM이 있는 상품만 찾아줘.

- 질문 유형: `compound_filter` / `overseas_etf_region_fee_aum_filter`
- Entity: `OverseasETF`
- Metric·구조화 사실: `asset_class`, `aum`, `fee`, `investment_region`
- 원천 필드: `pd_grp_no`, `wu_inv_rgn`, `wu_inv_ast_type`, `cu_charge_rt`, `du_last_aum`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ETF_ONLY`, `NON_MISSING_FEE`, `NON_MISSING_AUM`, `DISCLOSE_FEE_DEFINITION_LIMITATION`
- Capability: `filter_product_type`, `filter_region_and_asset`, `filter_fee`, `require_aum`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `filter_product_type→rdb`, `filter_region_and_asset→rdb`, `filter_fee→rdb`, `require_aum→rdb`
- 결정론적 연산: `filter_product_type`, `filter_region_and_asset`, `filter_fee`
- Evidence 요구사항: `table`, `product_id`, `filters`, `field`, `unit`, `as_of`
- 데이터 요구사항: `overseas_etf_master(available)`
- 지원 상태: `limited`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 보수 필드의 포함 범위와 결측 범위가 완전히 확정되지 않아 주최 측에 있는 동일 정의 값만 필터한다.
- 위험·표현 주의: 보수 단위와 포함 범위가 공식 확인 전임을 표시한다.

### 07. `FLT-BOND-001`

**질문 원문:** 현재 판매 가능한 원화채권 중 AA- 이상 종목 알려줘.

- 질문 유형: `compound_filter` / `official_saleable_krw_bond_credit_threshold`
- Entity: `DomesticBond`
- Metric·구조화 사실: `availability_status`, `credit_grade`, `currency`, `maturity`
- 원천 필드: `STD_PD_MCLS_NM`, `CRD_GRD`, `MAT_DT`, `BUYABLE_QUANTITY`, `REMAINING_DAYS`, `CURR_CD`, `PD_STD_INFO_UPDATE`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `KRW_ONLY`, `CREDIT_GRADE_ORDER_AAA_AA_PLUS_AA_ZERO_AA_MINUS`, `CREDIT_GRADE_AT_LEAST_AA_MINUS`, `BUYABLE_QUANTITY_INVALID_IGNORE`, `EXCLUDE_DELISTED_OR_LISTING_ENDED`, `OTHERWISE_ASSUME_PURCHASABLE`, `MATURITY_AFTER_CUTOFF`, `REMAINING_DAYS_POSITIVE`, `VALID_CREDIT_GRADE`, `CREDIT_GRADE_ORDER`, `BOND_HAS_CURRENCY`, `AVAILABILITY_IS_TIME_SCOPED`
- Capability: `filter_currency`, `validate_credit_grade_vocabulary`, `filter_credit_threshold`, `filter_not_matured`, `filter_current_saleability`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `filter_currency→rdb`, `validate_credit_grade_vocabulary→ontology`, `filter_credit_threshold→rdb`, `filter_not_matured→rdb`, `filter_current_saleability→rdb`
- 결정론적 연산: `filter_currency`, `filter_credit_threshold`, `filter_not_matured`, `filter_current_saleability`
- Evidence 요구사항: `table`, `product_id`, `currency`, `credit_grade`, `credit_grade_date`, `saleability_status`, `availability_as_of`, `filters`, `exclusion_reason`
- 데이터 요구사항: `domestic_bond_master(available_with_announced_saleability_rule)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- Answerability 근거: 주최 측 공지에 따라 BUYABLE_QUANTITY는 사용하지 않고 상장폐지·리스팅 종료 종목만 제외한 나머지를 구매 가능으로 간주한다.
- 위험·표현 주의: BUYABLE_QUANTITY를 사용하지 않으며 신용등급 결측을 우량등급으로 추정하지 않는다.

### 08. `FLT-FUND-001`

**질문 원문:** 공모펀드 중 판매중이고 당사판매가 가능하며 해외 주식에 투자하고 환헤지를 하는 상품을 찾아줘.

- 질문 유형: `compound_filter` / `public_fund_sale_region_hedge_filter`
- Entity: `PublicFund`
- Metric·구조화 사실: `hedge_policy`, `investment_region`, `offering_type`, `sale_status`
- 원천 필드: `prvo_pbff_desc`, `sale_yn`, `thco_sale_yn`, `ovrs_fd_desc`, `or_attr_desc`, `exchdg_yn`, `itm_no`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `PUBLIC_OFFERING_ONLY`, `SALE_STATUS_ACTIVE`, `DEDUP_BY_ITM_NO`, `MISSING_HEDGE_IS_UNKNOWN`
- Capability: `filter_public_offering`, `filter_sale_status`, `filter_region_and_type`, `filter_currency_hedge`, `deduplicate_classes`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `filter_public_offering→rdb`, `filter_sale_status→rdb`, `filter_region_and_type→rdb`, `filter_currency_hedge→rdb`, `deduplicate_classes→rdb`
- 결정론적 연산: `filter_public_offering`, `filter_sale_status`, `filter_region_and_type`, `filter_currency_hedge`, `deduplicate_classes`
- Evidence 요구사항: `table`, `product_id`, `filters`, `field`, `value`, `exclusion_reason`
- 데이터 요구사항: `public_fund_master(available)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: 환헤지 결측을 비헤지로 바꾸지 않는다.

### 09. `RANK-DETF-001`

**질문 원문:** 가람자산운용이 운용하는 국내 ETF를 AUM이 큰 순서로 5개 알려줘.

- 질문 유형: `ranking` / `provider_domestic_etf_aum_top5`
- Entity: `AssetManager`, `DomesticETF`
- Metric·구조화 사실: `aum`
- 원천 필드: `cu_fund_mgmt_co`, `pd_grp_no`, `du_last_aum`, `du_upt_dt`, `pd_itm_no`
- 승인 Relation: `managedBy`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ETF_ONLY`, `NON_MISSING_AUM`, `STABLE_DESCENDING_SORT`, `TOP_K_5`, `closed_world_coverage`
- Capability: `resolve_provider`, `filter_provider_and_type`, `rank_aum`, `take_top5`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `resolve_provider→keyword`, `filter_provider_and_type→rdb`, `rank_aum→rdb`, `take_top5→rdb`
- 결정론적 연산: `filter_provider_and_type`, `rank_aum`, `take_top5`
- Evidence 요구사항: `table`, `product_id`, `field`, `unit`, `as_of`, `sort_order`
- 데이터 요구사항: `domestic_etf_master(available)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: AUM을 유동성과 동일하게 설명하지 않는다.

### 10. `RANK-OETF-001`

**질문 원문:** 글로벌 채권형 해외 ETF 중 AUM 상위 5개를 알려줘.

- 질문 유형: `ranking` / `overseas_etf_region_aum_top5`
- Entity: `OverseasETF`
- Metric·구조화 사실: `asset_class`, `aum`, `currency`, `investment_region`
- 원천 필드: `pd_grp_no`, `wu_inv_rgn`, `wu_inv_ast_type`, `du_last_aum`, `pd_curr_cd`, `du_upt_dt`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ETF_ONLY`, `NON_MISSING_AUM`, `SAME_CURRENCY`, `TOP_K_5`
- Capability: `filter_type_region_asset`, `rank_aum`, `take_top5`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `filter_type_region_asset→rdb`, `rank_aum→rdb`, `take_top5→rdb`
- 결정론적 연산: `filter_type_region_asset`, `rank_aum`, `take_top5`
- Evidence 요구사항: `table`, `product_id`, `field`, `currency`, `as_of`, `sort_order`
- 데이터 요구사항: `overseas_etf_master(available)`
- 지원 상태: `limited`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 해외 ETF AUM은 통화별로만 완전한 순위를 보장하며, 환율 지원 범위 밖 통화는 분리하거나 제외한다.
- 위험·표현 주의: 해외 ETF의 AUM 통화 단위가 공식 확인 전임을 표시한다.

### 11. `RANK-BOND-001`

**질문 원문:** 데이터상 매수 가능한 원화 회사채 중 매수수익률이 높은 5개를 알려줘.

- 질문 유형: `ranking` / `buyable_bond_yield_top5`
- Entity: `DomesticBond`
- Metric·구조화 사실: `availability_status`, `maturity`, `yield`
- 원천 필드: `STD_PD_MCLS_NM`, `CURR_CD`, `BUYABLE_QUANTITY`, `BUY_YIELD`, `MAT_DT`, `REMAINING_DAYS`, `PD_STD_INFO_UPDATE`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `DO_NOT_MIX_YIELD_TYPES`, `BUYABLE_QUANTITY_INVALID_IGNORE`, `EXCLUDE_DELISTED_OR_LISTING_ENDED`, `OTHERWISE_ASSUME_PURCHASABLE`, `NON_MISSING_BUY_YIELD`, `TOP_K_5`
- Capability: `filter_buyable_bonds`, `validate_yield`, `rank_buy_yield`, `take_top5`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `filter_buyable_bonds→rdb`, `validate_yield→rdb`, `rank_buy_yield→rdb`, `take_top5→rdb`
- 결정론적 연산: `filter_buyable_bonds`, `rank_buy_yield`, `take_top5`
- Evidence 요구사항: `table`, `product_id`, `field`, `unit`, `as_of`, `exclusion_reason`
- 데이터 요구사항: `domestic_bond_master(available)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: 매수수익률과 평가수익률·세후수익률을 섞지 않는다.

### 12. `RANK-FUND-001`

**질문 원문:** 판매중인 공모 주식형 펀드 중 1년 수익률 상위 5개를 알려줘.

- 질문 유형: `ranking` / `public_fund_1y_return_top5`
- Entity: `PublicFund`
- Metric·구조화 사실: `offering_type`, `return_metric`, `sale_status`
- 원천 필드: `prvo_pbff_desc`, `sale_yn`, `or_attr_desc`, `itm_no`, `fd_yr1_ern_r`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `DEDUP_BY_ITM_NO`, `NON_MISSING_RETURN`, `REJECT_RETURN_BELOW_MINUS_100`, `DISCLOSE_MISSING_RETURN_DATE`
- Capability: `filter_public_active_equity_funds`, `deduplicate_by_itm_no`, `validate_1y_return`, `rank_top5`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `filter_public_active_equity_funds→rdb`, `deduplicate_by_itm_no→rdb`, `validate_1y_return→rdb`, `rank_top5→rdb`
- 결정론적 연산: `filter_public_active_equity_funds`, `deduplicate_by_itm_no`, `rank_top5`
- Evidence 요구사항: `table`, `product_id`, `field`, `unit`, `as_of`, `exclusion_reason`
- 데이터 요구사항: `public_fund_master(available)`, `official_fund_performance_snapshot(required_for_exact_as_of)`
- 지원 상태: `limited`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 1년 수익률 값은 주최 측 값을 사용하되 개별 값의 정확한 성과 기준일이 없으면 파일 내 제공값으로 제한해 표시한다.
- 위험·표현 주의: 기준일을 확보하기 전에는 파일 내 제공 1년 수익률이라고 제한한다.

### 13. `CALC-DETF-001`

**질문 원문:** 이 국내 ETF의 종가와 NAV로 괴리율을 다시 계산하고 원본 괴리율과 비교해줘.

- 질문 유형: `calculation` / `domestic_etf_premium_discount_recalculation`
- Entity: `DomesticETF`
- Metric·구조화 사실: `market_price`, `nav`, `premium_discount`
- 원천 필드: `du_clpr`, `du_last_nav`, `du_diff_rt`, `du_upt_dt`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `SAME_DATE_REQUIRED`, `DETERMINISTIC_FORMULA`, `ORGANIZER_NULL_REMAINS_UNAVAILABLE`, `ZERO_IS_NOT_MISSING`
- Capability: `resolve_product`, `validate_price_nav_dates`, `calculate_premium_discount`, `compare_source_metric`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `resolve_product→keyword`, `validate_price_nav_dates→rdb`, `calculate_premium_discount→rdb`, `compare_source_metric→rdb`
- 결정론적 연산: `calculate_premium_discount`, `compare_source_metric`
- Evidence 요구사항: `product_id`, `price`, `nav`, `formula`, `unit`, `as_of`, `source`
- 데이터 요구사항: `domestic_etf_master(available_with_authoritative_missingness)`
- 지원 상태: `limited`
- 목표 상태: `limited`
- requires_data: `false`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 주최 측 종가와 NAV가 모두 있고 기준일이 호환되는 상품만 계산하며 결측값은 외부 시세로 보충하지 않는다.
- 위험·표현 주의: 가격과 NAV의 기준일이 다르면 계산하지 않는다.

### 14. `CALC-BOND-001`

**질문 원문:** 기준일 2026년 7월 11일로 이 채권들의 잔존일수를 다시 계산하고 원본 값과 다른 항목을 알려줘.

- 질문 유형: `calculation` / `bond_remaining_days_recalculation`
- Entity: `DomesticBond`
- Metric·구조화 사실: `maturity`, `remaining_days`
- 원천 필드: `PD_NO`, `MAT_DT`, `REMAINING_DAYS`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `FIXED_CUTOFF_DATE`, `VALID_DATE_REQUIRED`, `DETERMINISTIC_DATE_ARITHMETIC`
- Capability: `resolve_products`, `parse_maturity_dates`, `calculate_remaining_days`, `compare_source_values`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `resolve_products→keyword`, `parse_maturity_dates→rdb`, `calculate_remaining_days→rdb`, `compare_source_values→rdb`
- 결정론적 연산: `calculate_remaining_days`, `compare_source_values`
- Evidence 요구사항: `product_id`, `maturity_date`, `cutoff_date`, `formula`, `source_value`, `calculated_value`
- 데이터 요구사항: `domestic_bond_master(available)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: 만기일 0 또는 센티널은 계산에서 제외한다.

### 15. `CALC-FUND-001`

**질문 원문:** 이 데이터의 공모펀드 수를 원본 행, 고유 판매클래스, 대표펀드군 기준으로 각각 알려줘.

- 질문 유형: `calculation` / `public_fund_count_by_analysis_unit`
- Entity: `FundShareClass`, `PublicFund`, `RepresentativeFund`
- Metric·구조화 사실: 없음
- 원천 필드: `prvo_pbff_desc`, `itm_no`, `rptt_ksd_itm_no`, `prfd_attr_cd`, `zrin_fd_ivst_risk_gcd`
- 승인 Relation: `hasShareClass` (hasShareClass 역방향)
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `REPORT_ANALYSIS_UNIT`, `INVALID_REPRESENTATIVE_SENTINEL_IS_MISSING`, `DISTINCT_COUNTS`, `closed_world_coverage`
- Capability: `filter_public_offering`, `count_raw_rows`, `count_distinct_itm_no`, `count_valid_representative_groups`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `filter_public_offering→rdb`, `count_raw_rows→rdb`, `count_distinct_itm_no→rdb`, `count_valid_representative_groups→rdb`
- 결정론적 연산: `filter_public_offering`, `count_raw_rows`, `count_distinct_itm_no`, `count_valid_representative_groups`
- Evidence 요구사항: `table`, `field`, `filter`, `aggregation_unit`, `count`, `data_version`
- 데이터 요구사항: `public_fund_master(available)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: 95,619개 원본 행을 펀드 개수로 단독 제시하지 않는다.

### 16. `CALC-CROSS-001`

**질문 원문:** 가람자산운용이 운용하는 상품 수를 국내 ETF, 해외 ETF, 공모펀드로 나눠 알려줘.

- 질문 유형: `calculation` / `product_count_by_provider_and_family`
- Entity: `AssetManager`, `DomesticETF`, `OverseasETF`, `PublicFund`
- Metric·구조화 사실: `product_family`
- 원천 필드: `cu_fund_mgmt_co`, `pd_grp_no`, `or_co_xtn_itt_cd`, `itm_no`
- 승인 Relation: `managedBy`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ETF_ONLY_WITHIN_ETF_MASTERS`, `PUBLIC_FUND_DEDUP_BY_ITM_NO`, `SEPARATE_COUNTS_BY_FAMILY`, `closed_world_coverage`
- Capability: `resolve_provider_identity`, `count_domestic_etf`, `count_overseas_etf`, `count_public_fund`, `merge_separate_counts`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `resolve_provider_identity→keyword`, `count_domestic_etf→rdb`, `count_overseas_etf→rdb`, `count_public_fund→rdb`, `merge_separate_counts→rdb`
- 결정론적 연산: `count_domestic_etf`, `count_overseas_etf`, `count_public_fund`, `merge_separate_counts`
- Evidence 요구사항: `provider_id`, `family`, `count`, `identity_unit`, `source`, `data_version`
- 데이터 요구사항: `domestic_and_overseas_etf_masters(available)`, `official_institution_master(required_for_public_fund_name_mapping)`
- 지원 상태: `requires_additional_data`
- 목표 상태: `supported`
- requires_data: `true`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 운용사명과 기관코드를 근거 없이 문자열 유사도로 결합하지 않는다.
- 위험·표현 주의: 운용사명과 기관코드를 근거 없이 문자열 유사도로 결합하지 않는다.

### 17. `CMP-RET-001`

**질문 원문:** 국내 ETF와 공모펀드의 1년 수익률 상위 상품을 한 표에서 비교해줘.

- 질문 유형: `cross_family` / `cross_family_1y_return_comparison`
- Entity: `DomesticETF`, `PublicFund`
- Metric·구조화 사실: `return_metric`
- 원천 필드: `du_er_1y`, `du_upt_dt`, `fd_yr1_ern_r`, `itm_no`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `SAME_PERIOD`, `SAME_RETURN_DEFINITION`, `SAME_DISTRIBUTION_TREATMENT`, `SEPARATE_IF_INCOMPATIBLE`
- Capability: `rank_domestic_etf_1y`, `rank_public_fund_1y`, `check_metric_compatibility`, `compose_or_separate`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `rank_domestic_etf_1y→rdb`, `rank_public_fund_1y→rdb`, `check_metric_compatibility→rdb`, `compose_or_separate→rdb`
- 결정론적 연산: `rank_domestic_etf_1y`, `rank_public_fund_1y`
- Evidence 요구사항: `product_id`, `family`, `return_field`, `return_definition`, `unit`, `as_of`
- 데이터 요구사항: `domestic_etf_and_public_fund_masters(partially_available)`, `official_return_methodology_and_dates(required)`
- 지원 상태: `requires_additional_data`
- 목표 상태: `limited`
- requires_data: `true`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 같은 1년 표기만으로 수익률 정의가 동일하다고 가정하지 않는다.
- 위험·표현 주의: 같은 1년 표기만으로 수익률 정의가 동일하다고 가정하지 않는다.

### 18. `CMP-AUM-001`

**질문 원문:** 국내 ETF와 해외 ETF를 합쳐 AUM이 큰 순서로 10개 알려줘.

- 질문 유형: `cross_family` / `cross_currency_aum_ranking`
- Entity: `DomesticETF`, `OverseasETF`
- Metric·구조화 사실: `aum`, `currency`
- 원천 필드: `du_last_aum`, `pd_curr_cd`, `du_upt_dt`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `CONVERT_TO_KRW_USING_OFFICIAL_FX`, `USE_LATEST_OFFICIAL_RATE_ON_OR_BEFORE_CUTOFF`, `DISCLOSE_FX_ACTUAL_DATE_AND_SOURCE`, `TOP_K_10`
- Capability: `retrieve_domestic_aum`, `retrieve_overseas_aum`, `resolve_currency_basis`, `normalize_if_approved`, `rank_top10`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `retrieve_domestic_aum→rdb`, `retrieve_overseas_aum→rdb`, `resolve_currency_basis→keyword`, `normalize_if_approved→rdb`, `rank_top10→rdb`
- 결정론적 연산: `normalize_if_approved`, `rank_top10`
- Evidence 요구사항: `product_id`, `aum`, `source_currency`, `fx_rate`, `target_currency`, `as_of`, `formula`
- 데이터 요구사항: `domestic_and_overseas_etf_masters(available_but_incompatible)`, `official_fx_snapshot(approved_four_currency_scope)`
- 지원 상태: `limited`
- 목표 상태: `limited`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: KRW 환산은 승인된 ECOS 4개 통화 범위로 한정하며 다른 통화는 임의 환율로 보충하지 않는다.
- 위험·표현 주의: KRW 환산 순위이며 실제 적용 환율의 종류·관측일·출처를 함께 공개한다.

### 19. `CMP-RISK-001`

**질문 원문:** 국내 ETF와 회사채 중 위험등급이 가장 낮은 상품을 같이 순위로 보여줘.

- 질문 유형: `cross_family` / `cross_family_risk_grade_comparison`
- Entity: `DomesticBond`, `DomesticETF`
- Metric·구조화 사실: `credit_grade`, `product_risk_grade`
- 원천 필드: `pd_risk_cd`, `pd_risk_nm`, `PD_RISK_GCD`, `CRD_GRD`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `CREDIT_GRADE_IS_NOT_PRODUCT_RISK`, `FAMILY_SPECIFIC_RISK_SCALE`, `NO_UNAPPROVED_NORMALIZATION`, `RETURN_SEPARATE_FAMILY_SECTIONS`
- Capability: `retrieve_etf_risk`, `retrieve_bond_risk`, `check_risk_scale_compatibility`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `retrieve_etf_risk→rdb`, `retrieve_bond_risk→rdb`, `check_risk_scale_compatibility→rdb`
- 결정론적 연산: 없음
- Evidence 요구사항: `product_id`, `family`, `risk_field`, `risk_definition`, `as_of`
- 데이터 요구사항: `domestic_etf_and_bond_masters(available_but_semantically_incompatible)`
- 지원 상태: `limited`
- 목표 상태: `limited`
- requires_data: `false`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: ETF 위험등급과 채권 신용등급은 동일 척도가 아니므로 상품군별 결과로만 제한해 비교한다.
- 위험·표현 주의: 서로 다른 위험 척도를 하나의 숫자 순위로 만들지 않는다.

### 20. `CMP-FEE-001`

**질문 원문:** 국내 ETF와 해외 ETF 중 총보수가 낮은 상품을 같은 기준으로 비교해줘.

- 질문 유형: `cross_family` / `domestic_overseas_etf_fee_comparison`
- Entity: `DomesticETF`, `OverseasETF`
- Metric·구조화 사실: `fee`
- 원천 필드: `cu_charge_rt`, `cu_charge_etc_rt`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `SAME_FEE_SCOPE`, `SAME_UNIT`, `NON_MISSING_FEE`, `SEPARATE_IF_INCOMPATIBLE`
- Capability: `retrieve_domestic_fees`, `retrieve_overseas_fees`, `validate_fee_definitions`, `rank_if_compatible`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `retrieve_domestic_fees→rdb`, `retrieve_overseas_fees→rdb`, `validate_fee_definitions→rdb`, `rank_if_compatible→rdb`
- 결정론적 연산: `rank_if_compatible`
- Evidence 요구사항: `product_id`, `fee_type`, `fee_value`, `unit`, `as_of`, `source`
- 데이터 요구사항: `domestic_and_overseas_etf_masters(low_coverage_or_unconfirmed_definition)`, `official_etf_fee_snapshot(required)`
- 지원 상태: `requires_additional_data`
- 목표 상태: `supported`
- requires_data: `true`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 이름이 총보수여도 포함 비용 범위가 같은지 확인한다.
- 위험·표현 주의: 이름이 총보수여도 포함 비용 범위가 같은지 확인한다.

### 21. `REL-HOLD-001`

**질문 원문:** 삼성전자를 보유한 국내·해외 ETF와 공모펀드를 1년 수익률 기준 TOP 10으로 알려줘.

- 질문 유형: `multi_hop` / `cross_family_holding_filter_then_1y_return_rank`
- Entity: `DomesticETF`, `OverseasETF`, `PublicFund`, `Security`
- Metric·구조화 사실: `return_metric`
- 원천 필드: `pd_itm_no`, `pd_isin_cd`, `du_er_1y`, `fd_yr1_ern_r`
- 승인 Relation: `holdsSecurity`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `NO_HOLDING_INFERENCE_FROM_NAME`, `VERIFIED_SECURITY_ID_JOIN`, `SAME_1Y_RETURN_DEFINITION`, `ORGANIZER_MISSING_VALUE_REMAINS_UNAVAILABLE`, `NO_FALSE_EMPTY_FOR_UNCOVERED_FAMILY`, `TOP_K_10`, `closed_world_coverage`
- Capability: `resolve_security`, `find_holding_products_by_family`, `validate_family_coverage`, `join_1y_return`, `validate_return_compatibility`, `rank_top10`
- Retrieval: `structured_graph` / 역할 `keyword`, `graph`, `rdb`
- Subtask route: `resolve_security→graph`, `find_holding_products_by_family→graph`, `validate_family_coverage→rdb`, `join_1y_return→rdb`, `validate_return_compatibility→rdb`, `rank_top10→rdb`
- 결정론적 연산: `rank_top10`
- Evidence 요구사항: `product_id`, `family`, `constituent_security_id`, `holding_as_of`, `return_metric`, `return_as_of`, `family_coverage`, `source`
- 데이터 요구사항: `organizer_product_masters(return_fields_present_with_authoritative_missingness)`, `official_etf_holdings_snapshot(available_with_bounded_overseas_coverage)`, `official_public_fund_holdings_snapshot(requires_additional_data)`, `official_security_master(available_with_source_specific_coverage)`
- 지원 상태: `requires_additional_data`
- 목표 상태: `requires_additional_data`
- requires_data: `true`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 공모펀드 구성종목 원천이 승인되지 않았으므로 ETF 결과만을 전체 결과로 표현하거나 공모펀드는 보유하지 않는다고 단정하지 않는다.
- 위험·표현 주의: 공모펀드 구성종목 원천이 승인되지 않았으므로 ETF 결과만을 전체 결과로 표현하거나 공모펀드는 보유하지 않는다고 단정하지 않는다.

### 22. `REL-HOLD-002`

**질문 원문:** 이 ETF의 구성종목을 편입비중이 높은 순서로 10개 보여주고 각 비중의 기준일도 알려줘.

- 질문 유형: `multi_hop` / `etf_top_constituents_by_weight`
- Entity: `DomesticETF`, `OverseasETF`, `Security`
- Metric·구조화 사실: `holding_weight_assertion_attribute`
- 원천 필드: `pd_itm_no`, `pd_isin_cd`, `pd_nm`
- 승인 Relation: `holdsSecurity`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `USE_SINGLE_HOLDINGS_SNAPSHOT`, `PRESERVE_CASH_AND_DERIVATIVE_TYPES`, `VALIDATE_WEIGHT_UNIT`, `TOP_K_10`, `closed_world_coverage`
- Capability: `resolve_etf`, `retrieve_constituent_snapshot`, `validate_weights`, `rank_top10`
- Retrieval: `structured_graph` / 역할 `keyword`, `graph`, `rdb`
- Subtask route: `resolve_etf→keyword`, `retrieve_constituent_snapshot→rdb`, `validate_weights→rdb`, `rank_top10→rdb`
- 결정론적 연산: `validate_weights`, `rank_top10`
- Evidence 요구사항: `etf_product_id`, `constituent_security_id`, `constituent_name`, `weight`, `weight_unit`, `as_of`, `source`
- 데이터 요구사항: `organizer_etf_masters(product_identity_available)`, `official_etf_holdings_snapshot(available_with_source_specific_coverage)`, `official_security_master(available_with_source_specific_coverage)`
- 지원 상태: `limited`
- 목표 상태: `limited`
- requires_data: `false`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 국내 KRX와 해외 SEC에서 해당 상품의 기준일 구성종목이 확인된 경우에만 답하며 SEC 미커버 상품은 확인 불가로 표시한다.
- 위험·표현 주의: 서로 다른 기준일의 편입비중을 한 구성표에 섞지 않는다.

### 23. `REL-HOLD-003`

**질문 원문:** A ETF와 구성종목이 가장 많이 겹치는 ETF 5개를 찾아서 겹치는 종목과 비중도 설명해줘.

- 질문 유형: `multi_hop` / `etf_weighted_holdings_overlap_similarity`
- Entity: `DomesticETF`, `OverseasETF`, `Security`
- Metric·구조화 사실: `holding_weight_assertion_attribute`
- 원천 필드: `pd_itm_no`, `pd_isin_cd`, `pd_grp_no`, `pd_curr_cd`
- 승인 Relation: `holdsSecurity`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ETF_ONLY`, `EXCLUDE_ANCHOR`, `SAME_OR_DISCLOSED_HOLDINGS_DATE`, `DETERMINISTIC_OVERLAP_FORMULA`, `TOP_K_5`, `closed_world_coverage`
- Capability: `resolve_anchor_etf`, `retrieve_same_date_holdings`, `calculate_overlap`, `rank_top5`, `explain_overlap`
- Retrieval: `structured_graph` / 역할 `keyword`, `graph`, `rdb`
- Subtask route: `resolve_anchor_etf→keyword`, `retrieve_same_date_holdings→graph`, `calculate_overlap→rdb`, `rank_top5→rdb`, `explain_overlap→rdb`
- 결정론적 연산: `calculate_overlap`, `rank_top5`
- Evidence 요구사항: `anchor_product_id`, `candidate_product_id`, `overlap_formula`, `overlap_score`, `shared_constituents`, `as_of`, `source`
- 데이터 요구사항: `organizer_etf_masters(product_identity_available)`, `official_etf_holdings_snapshot(available_with_source_specific_coverage)`, `official_security_master(available_with_source_specific_coverage)`
- 지원 상태: `limited`
- 목표 상태: `limited`
- requires_data: `false`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 구성종목 유사도는 동일하거나 명시된 기준일의 커버된 ETF 후보 내에서만 계산한다.
- 위험·표현 주의: 유사도 산식과 구성 기준일을 공개하고 임베딩 점수로 대체하지 않는다.

### 24. `REL-HOLD-004`

**질문 원문:** 반도체 업종 편입비중이 30% 이상인 ETF를 찾아서 AUM 순으로 보여줘.

- 질문 유형: `multi_hop` / `etf_sector_exposure_from_constituents`
- Entity: `DomesticETF`, `Industry`, `OverseasETF`, `Security`
- Metric·구조화 사실: `aum`, `holding_weight_assertion_attribute`
- 원천 필드: `pd_itm_no`, `pd_isin_cd`, `du_last_aum`, `pd_curr_cd`, `du_upt_dt`
- 승인 Relation: `classifiedAsIndustry`, `holdsSecurity`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `DETERMINISTIC_WEIGHT_AGGREGATION`, `SECTOR_CLASSIFICATION_VERSION_REQUIRED`, `THRESHOLD_GTE_30_PCT`, `SAME_CURRENCY_OR_SEPARATE_RANKING`, `closed_world_coverage`
- Capability: `resolve_sector`, `retrieve_holdings`, `join_security_sector`, `aggregate_sector_weight`, `filter_threshold`, `join_and_rank_aum`
- Retrieval: `structured_graph` / 역할 `keyword`, `graph`, `rdb`
- Subtask route: `resolve_sector→keyword`, `retrieve_holdings→graph`, `join_security_sector→graph`, `aggregate_sector_weight→rdb`, `filter_threshold→rdb`, `join_and_rank_aum→rdb`
- 결정론적 연산: `aggregate_sector_weight`, `filter_threshold`, `join_and_rank_aum`
- Evidence 요구사항: `etf_product_id`, `sector_id`, `constituent_ids`, `aggregated_weight`, `weight_as_of`, `aum`, `aum_as_of`, `source`
- 데이터 요구사항: `organizer_etf_masters(aum_available)`, `official_etf_holdings_snapshot(mandatory)`, `official_security_sector_classification(mandatory)`
- 지원 상태: `requires_additional_data`
- 목표 상태: `supported`
- requires_data: `true`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 업종 분류 체계와 기준일이 다른 데이터를 섞어 비중을 계산하지 않는다.
- 위험·표현 주의: 업종 분류 체계와 기준일이 다른 데이터를 섞어 비중을 계산하지 않는다.

### 25. `REL-MGR-001`

**질문 원문:** 가람자산운용이 운용 중인 국내 ETF 중에서 1년 수익률이 가장 높은 상품을 알려주고, 그거랑 비슷한 상품들도 알려줘.

- 질문 유형: `multi_hop` / `provider_top_return_then_similarity`
- Entity: `AssetManager`, `DomesticETF`, `Index`
- Metric·구조화 사실: `asset_class`, `investment_region`, `return_metric`, `strategy_structured_fact`
- 원천 필드: `cu_fund_mgmt_co`, `pd_grp_no`, `pd_sale_yn`, `pd_tr_yn`, `du_er_1y`, `du_upt_dt`, `wu_inv_ast_type`, `wu_inv_rgn`, `cu_strtegy`, `cu_lev_fector`, `cu_base_index`
- 승인 Relation: `managedBy`, `tracksIndex`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ETF_ONLY`, `ACTIVE_CANDIDATES_ONLY`, `NON_MISSING_RETURN`, `EXCLUDE_RETURN_SENTINEL`, `FAMILY_SPECIFIC_HARD_FILTERS`, `MIN_SCORE_COVERAGE_60_PCT`, `DISCLOSE_SIMILARITY_BASIS`, `closed_world_coverage`
- Capability: `resolve_provider`, `filter_active_etfs`, `rank_1y_return`, `bind_top_product`, `find_similar_etfs`
- Retrieval: `structured_graph` / 역할 `keyword`, `graph`, `rdb`
- Subtask route: `resolve_provider→keyword`, `filter_active_etfs→rdb`, `rank_1y_return→rdb`, `bind_top_product→rdb`, `find_similar_etfs→rdb`
- 결정론적 연산: `filter_active_etfs`, `rank_1y_return`
- Evidence 요구사항: `product_id`, `provider`, `return_field`, `return_value`, `as_of`, `similarity_policy_id`, `similarity_score`, `score_coverage`, `similarity_dimensions`, `exclusions`
- 데이터 요구사항: `domestic_etf_master(available_with_similarity_gaps)`, `official_etf_holdings_snapshot(mandatory_for_full_similarity)`
- 지원 상태: `limited`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 유사성 계산은 주최 측 속성과 커버된 구성종목 축만 사용하므로 미커버 구성종목은 유사하다고 가정하지 않는다.
- 위험·표현 주의: 과거 수익률 1위와 유사성 결과를 투자 추천으로 표현하지 않는다.

### 26. `REL-SIM-FUND-001`

**질문 원문:** A 공모 주식형 펀드와 비슷한 공모펀드 5개를 찾고 어떤 점이 비슷하고 다른지도 알려줘.

- 질문 유형: `multi_hop` / `public_fund_family_specific_similarity`
- Entity: `FundShareClass`, `PublicFund`, `RepresentativeFund`
- Metric·구조화 사실: `asset_class`, `benchmark`, `hedge_policy`, `investment_region`, `risk_grade`
- 원천 필드: `itm_no`, `rptt_ksd_itm_no`, `or_attr_desc`, `fd_ivst_rgn_desc`, `bmrk_nm`, `zrin_fd_ivst_risk_gcd`, `exchdg_yn`, `fd_set_pcd`
- 승인 Relation: `hasShareClass` (hasShareClass 역방향)
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `PUBLIC_FUND_ONLY`, `DEDUPLICATE_BY_ITM_NO`, `FAMILY_SPECIFIC_HARD_FILTERS`, `MIN_SCORE_COVERAGE_60_PCT`, `MISSING_DIMENSION_IS_NOT_MATCH`, `TOP_K_5`, `DISCLOSE_DIMENSION_EVIDENCE`, `closed_world_coverage`
- Capability: `resolve_anchor_fund`, `deduplicate_share_class_rows`, `select_public_fund_similarity_policy`, `apply_hard_filters`, `score_candidates`, `rank_top5`, `explain_dimensions`
- Retrieval: `structured_graph` / 역할 `keyword`, `graph`, `rdb`
- Subtask route: `resolve_anchor_fund→keyword`, `deduplicate_share_class_rows→rdb`, `select_public_fund_similarity_policy→rdb`, `apply_hard_filters→rdb`, `score_candidates→rdb`, `rank_top5→rdb`, `explain_dimensions→rdb`
- 결정론적 연산: `deduplicate_share_class_rows`, `apply_hard_filters`, `score_candidates`, `rank_top5`
- Evidence 요구사항: `anchor_product_id`, `candidate_product_id`, `similarity_policy_id`, `similarity_score`, `score_coverage`, `dimension_scores`, `field_sources`, `as_of`, `exclusions`
- 데이터 요구사항: `public_fund_master(available_with_strategy_and_missingness_gaps)`, `official_public_fund_strategy_and_benchmark_snapshot(required_for_full_similarity)`
- 지원 상태: `limited`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 전략·벤치마크 결측 축은 일치로 계산하지 않아 유사도 점수 커버리지가 상품별로 다를 수 있다.
- 위험·표현 주의: 대표펀드군과 판매 클래스를 혼동하지 않고 결측 축을 일치로 계산하지 않는다.

### 27. `REL-SIM-BOND-001`

**질문 원문:** A 회사채와 비슷한 회사채 5개를 찾고 발행주체, 신용등급, 잔존만기, 금리구조, 통화와 수익률 차이를 설명해줘.

- 질문 유형: `multi_hop` / `domestic_bond_family_specific_similarity`
- Entity: `DomesticBond`, `Issuer`
- Metric·구조화 사실: `credit_grade`, `currency`, `rate_structure`, `remaining_maturity`, `yield_metric`
- 원천 필드: `PD_NO`, `PD_PBCM`, `STD_PD_MCLS_NM`, `BD_KND`, `CRD_GRD`, `CRD_GRD_DT`, `REMAINING_DAYS`, `SRFC_IRT`, `CURR_CD`, `BUY_YIELD`, `PD_STD_INFO_UPDATE`
- 승인 Relation: `issuedBy`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `DOMESTIC_BOND_ONLY`, `SAME_BROAD_BOND_TYPE`, `FAMILY_SPECIFIC_HARD_FILTERS`, `SAME_YIELD_DEFINITION_ONLY`, `MIN_SCORE_COVERAGE_60_PCT`, `MISSING_DIMENSION_IS_NOT_MATCH`, `TOP_K_5`, `DISCLOSE_DIMENSION_EVIDENCE`, `closed_world_coverage`
- Capability: `resolve_anchor_bond`, `select_domestic_bond_similarity_policy`, `apply_hard_filters`, `validate_rating_and_yield_definitions`, `score_candidates`, `rank_top5`, `explain_dimensions`
- Retrieval: `structured_graph` / 역할 `keyword`, `graph`, `rdb`
- Subtask route: `resolve_anchor_bond→keyword`, `select_domestic_bond_similarity_policy→rdb`, `apply_hard_filters→rdb`, `validate_rating_and_yield_definitions→rdb`, `score_candidates→rdb`, `rank_top5→rdb`, `explain_dimensions→rdb`
- 결정론적 연산: `apply_hard_filters`, `score_candidates`, `rank_top5`
- Evidence 요구사항: `anchor_product_id`, `candidate_product_id`, `similarity_policy_id`, `similarity_score`, `score_coverage`, `dimension_scores`, `rating_date`, `yield_definition`, `as_of`, `exclusions`
- 데이터 요구사항: `domestic_bond_master(available_with_material_rating_yield_and_date_gaps)`, `official_bond_rating_and_terms_snapshot(required_for_missing_dimensions)`
- 지원 상태: `limited`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 신용등급·수익률·잔존만기 결측 축은 일치로 가정하지 않아 후보별 점수 커버리지를 함께 보여준다.
- 위험·표현 주의: 등급·수익률 결측을 추정하지 않고 서로 다른 수익률 정의를 같은 점수축에 섞지 않는다.

### 28. `REL-IDX-001`

**질문 원문:** S&P 500 지수를 추종하는 국내 ETF와 해외 ETF를 찾아서 운용사와 보수를 알려줘.

- 질문 유형: `multi_hop` / `same_index_products_across_markets`
- Entity: `AssetManager`, `DomesticETF`, `Index`, `OverseasETF`
- Metric·구조화 사실: `fee`
- 원천 필드: `cu_base_index`, `cu_fund_mgmt_co`, `cu_charge_rt`, `pd_itm_no`
- 승인 Relation: `managedBy`, `tracksIndex`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ETF_ONLY`, `NORMALIZE_INDEX_IDENTITY`, `PLACEHOLDER_INDEX_IS_MISSING`, `DISCLOSE_FEE_SCOPE`, `closed_world_coverage`
- Capability: `resolve_index`, `find_linked_etfs`, `lookup_provider_and_fee`, `validate_fee_compatibility`
- Retrieval: `structured_graph` / 역할 `keyword`, `graph`, `rdb`
- Subtask route: `resolve_index→keyword`, `find_linked_etfs→graph`, `lookup_provider_and_fee→rdb`, `validate_fee_compatibility→rdb`
- 결정론적 연산: 없음
- Evidence 요구사항: `index_id`, `product_id`, `provider`, `fee_type`, `fee_value`, `as_of`, `source`
- 데이터 요구사항: `domestic_and_overseas_etf_masters(index_coverage_incomplete)`, `official_index_product_mapping(required)`, `official_etf_fee_snapshot(required)`
- 지원 상태: `requires_additional_data`
- 목표 상태: `supported`
- requires_data: `true`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 지수명 문자열 일부 일치만으로 동일 지수라고 단정하지 않는다.
- 위험·표현 주의: 지수명 문자열 일부 일치만으로 동일 지수라고 단정하지 않는다.

### 29. `REL-FUND-001`

**질문 원문:** 새봄글로벌주식 대표펀드군에서 1년 수익률이 가장 높은 판매 클래스를 찾고 같은 대표펀드의 다른 클래스도 보여줘.

- 질문 유형: `multi_hop` / `representative_fund_best_class_then_siblings`
- Entity: `FundShareClass`, `PublicFund`, `RepresentativeFund`
- Metric·구조화 사실: `return_metric`, `sale_status`
- 원천 필드: `rptt_ksd_itm_no`, `itm_no`, `itm_nm`, `sale_yn`, `fd_yr1_ern_r`
- 승인 Relation: `hasShareClass` (hasShareClass 역방향)
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `VALID_REPRESENTATIVE_ID`, `DEDUP_BY_ITM_NO`, `NON_MISSING_RETURN`, `DO_NOT_SUM_CLASS_AUM`, `closed_world_coverage`
- Capability: `resolve_representative_fund`, `list_unique_share_classes`, `rank_valid_1y_return`, `expand_sibling_classes`
- Retrieval: `structured_graph` / 역할 `keyword`, `graph`, `rdb`
- Subtask route: `resolve_representative_fund→keyword`, `list_unique_share_classes→rdb`, `rank_valid_1y_return→rdb`, `expand_sibling_classes→rdb`
- 결정론적 연산: `rank_valid_1y_return`
- Evidence 요구사항: `representative_fund_id`, `share_class_id`, `return_field`, `return_value`, `sale_status`, `source`
- 데이터 요구사항: `public_fund_master(available_with_class_definition_gap)`, `official_fund_class_master(required_for_class_meaning)`
- 지원 상태: `limited`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 대표펀드와 판매 클래스는 주최 측 식별자로 연결된 범위만 보여주고 클래스 문자의 의미는 추정하지 않는다.
- 위험·표현 주의: 클래스별 비용·채널 의미는 공식 클래스 마스터 없이 추정하지 않는다.

### 30. `CTX-DETF-001`

**질문 원문:** 가람자산운용 ETF 중 AUM이 가장 큰 상품을 알려줘. 이 상품의 1년 수익률과 위험등급도 보여줘.

- 질문 유형: `context_resolution` / `top_product_followup_details`
- Entity: `AssetManager`, `DomesticETF`
- Metric·구조화 사실: `aum`, `return_metric`, `risk_grade`
- 원천 필드: `cu_fund_mgmt_co`, `du_last_aum`, `du_er_1y`, `pd_risk_nm`, `du_upt_dt`
- 승인 Relation: `managedBy`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `EXECUTE_DEPENDENCIES_IN_ORDER`, `UNIQUE_RESULT_BINDING`, `DISCLOSE_METRIC_DATE`, `closed_world_coverage`
- Capability: `rank_provider_aum`, `bind_top_product`, `lookup_followup_metrics`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `rank_provider_aum→rdb`, `bind_top_product→rdb`, `lookup_followup_metrics→rdb`
- 결정론적 연산: `rank_provider_aum`
- Evidence 요구사항: `product_id`, `binding_source`, `field`, `value`, `unit`, `as_of`
- 데이터 요구사항: `domestic_etf_master(available)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: 두 번째 문장을 독립 청크로 검색하지 않는다.

### 31. `CTX-DETF-002`

**질문 원문:** 연금거래가 가능한 국내 ETF 10개를 AUM 순으로 보여줘. 이 상품들 중 위험등급이 낮은 것만 다시 추려줘.

- 질문 유형: `context_resolution` / `plural_result_reference_filter`
- Entity: `DomesticETF`
- Metric·구조화 사실: `aum`, `pension_eligibility`, `risk_grade`
- 원천 필드: `pd_pen_tr_yn`, `du_last_aum`, `pd_risk_cd`, `pd_risk_nm`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `BOUND_SET_ONLY`, `FAMILY_SPECIFIC_RISK_ORDER`, `DO_NOT_REQUERY_ALL_PRODUCTS`
- Capability: `filter_pension_etfs`, `rank_aum_top10`, `bind_product_set`, `filter_bound_set_by_risk`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `filter_pension_etfs→rdb`, `rank_aum_top10→rdb`, `bind_product_set→rdb`, `filter_bound_set_by_risk→rdb`
- 결정론적 연산: `filter_pension_etfs`, `rank_aum_top10`, `filter_bound_set_by_risk`
- Evidence 요구사항: `product_id`, `binding_source`, `rank`, `risk_field`, `risk_value`
- 데이터 요구사항: `domestic_etf_master(available)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: ‘낮은’ 위험의 등급 방향을 국내 ETF 코드 기준으로 해석한다.

### 32. `CTX-AMB-001`

**질문 원문:** A ETF와 B ETF의 AUM과 1년 수익률을 비교해줘. 이 상품의 위험등급도 알려줘.

- 질문 유형: `context_resolution` / `ambiguous_singular_reference_after_comparison`
- Entity: `DomesticETF`
- Metric·구조화 사실: `aum`, `return_metric`, `risk_grade`
- 원천 필드: `pd_itm_no`, `du_last_aum`, `du_er_1y`, `pd_risk_nm`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `DO_NOT_GUESS_AMBIGUOUS_REFERENCE`, `RETURN_ALL_COMPATIBLE_CANDIDATES`, `SINGLE_TURN_NO_FOLLOWUP`
- Capability: `compare_two_products`, `resolve_followup_reference`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `compare_two_products→rdb`, `resolve_followup_reference→keyword`
- 결정론적 연산: `compare_two_products`
- Evidence 요구사항: `candidate_product_ids`, `ambiguous_mention`, `source_segments`, `risk_grade_for_each_candidate`
- 데이터 요구사항: `domestic_etf_master(available)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: 직전 표의 첫 행을 임의 선택하지 않고 A와 B 모두의 위험등급을 보여준다.

### 33. `CTX-CROSS-001`

**질문 원문:** 가람자산운용 국내 ETF 중 AUM 1위를 알려줘. 그 운용사가 운용하는 해외 ETF도 AUM 순으로 보여줘.

- 질문 유형: `context_resolution` / `provider_reference_cross_family_followup`
- Entity: `AssetManager`, `DomesticETF`, `OverseasETF`
- Metric·구조화 사실: `aum`
- 원천 필드: `cu_fund_mgmt_co`, `pd_grp_no`, `du_last_aum`, `pd_curr_cd`
- 승인 Relation: `managedBy`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `BIND_PROVIDER_NOT_TOP_PRODUCT`, `NORMALIZE_PROVIDER_IDENTITY`, `SEPARATE_CURRENCY_DISCLOSURE`, `closed_world_coverage`
- Capability: `resolve_provider`, `rank_domestic_etf`, `bind_provider`, `rank_overseas_etf_for_same_provider`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `resolve_provider→keyword`, `rank_domestic_etf→rdb`, `bind_provider→rdb`, `rank_overseas_etf_for_same_provider→rdb`
- 결정론적 연산: `rank_domestic_etf`, `rank_overseas_etf_for_same_provider`
- Evidence 요구사항: `provider_id`, `provider_alias`, `product_id`, `aum`, `currency`, `as_of`
- 데이터 요구사항: `domestic_and_overseas_etf_masters(available_with_provider_name_variants)`, `official_institution_master(required_for_robust_identity)`
- 지원 상태: `limited`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 국내·해외 운용사 문자열이 공식 기관 식별자로 완전히 정규화되지 않은 경우 확정 연결을 하지 않는다.
- 위험·표현 주의: ‘그 운용사’를 첫 문장 결과 상품이 아니라 운용사 엔티티에 연결한다.

### 34. `MIS-OETF-001`

**질문 원문:** 이 해외 ETF의 현재 괴리율을 종가와 NAV로 계산해줘.

- 질문 유형: `missing_incompatible` / `overseas_etf_nav_price_date_mismatch`
- Entity: `OverseasETF`
- Metric·구조화 사실: `market_price`, `nav`
- 원천 필드: `du_clpr`, `du_clpr_base_dt`, `du_last_nav`, `du_nav_base_dt`, `du_base_dt_match_yn`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `SAME_DATE_REQUIRED`, `DO_NOT_CALL_STALE_VALUE_CURRENT`, `ORGANIZER_NULL_REMAINS_UNAVAILABLE`, `ABSTAIN_FROM_INVALID_CALCULATION`
- Capability: `resolve_product`, `retrieve_price_and_nav`, `validate_dates`, `calculate_if_compatible`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `resolve_product→keyword`, `retrieve_price_and_nav→rdb`, `validate_dates→rdb`, `calculate_if_compatible→rdb`
- 결정론적 연산: `calculate_if_compatible`
- Evidence 요구사항: `product_id`, `price`, `price_date`, `nav`, `nav_date`, `missing_requirement`
- 데이터 요구사항: `overseas_etf_master(available_with_date_match_and_authoritative_missingness)`
- 지원 상태: `limited`
- 목표 상태: `limited`
- requires_data: `false`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 주최 측 종가와 NAV가 모두 있고 기준일이 같은 경우에만 계산하며 하나라도 비어 있으면 확인 불가로 반환한다.
- 위험·표현 주의: 기준일이 다른 가격과 NAV로 괴리율을 만들지 않는다.

### 35. `MIS-DETF-001`

**질문 원문:** 국내 ETF의 1년 수익률 하위 10개를 알려줘.

- 질문 유형: `missing_incompatible` / `domestic_etf_return_sentinel_exclusion`
- Entity: `DomesticETF`
- Metric·구조화 사실: `return_metric`
- 원천 필드: `pd_grp_no`, `du_er_1y`, `pd_lstg_dt`, `du_clpr`, `du_upt_dt`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ETF_ONLY`, `VALIDATE_MINUS_100`, `NON_MISSING_RETURN`, `BOTTOM_K_10`, `RECORD_EXCLUSIONS`
- Capability: `filter_etf`, `classify_return_values`, `exclude_sentinel_candidates`, `rank_bottom10`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `filter_etf→rdb`, `classify_return_values→rdb`, `exclude_sentinel_candidates→rdb`, `rank_bottom10→rdb`
- 결정론적 연산: `filter_etf`, `rank_bottom10`
- Evidence 요구사항: `product_id`, `return_value`, `return_field`, `as_of`, `exclusion_reason`
- 데이터 요구사항: `domestic_etf_master(available_with_sentinel_candidates)`
- 지원 상태: `limited`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: -100 등 센티넬 의심값은 정상 하위 수익률로 즉시 사용하지 않아 유효 결과가 10개보다 적을 수 있다.
- 위험·표현 주의: -100을 자동으로 최하위 정상 수익률로 정렬하지 않는다.

### 36. `MIS-BOND-001`

**질문 원문:** 이 채권의 신용등급을 알려주고 비슷한 등급의 채권도 찾아줘.

- 질문 유형: `missing_incompatible` / `bond_missing_credit_grade`
- Entity: `DomesticBond`
- Metric·구조화 사실: `credit_grade`
- 원천 필드: `PD_NO`, `CRD_GRD`, `CRD_GRD_DT`, `PD_EVCO_CRD_GRD`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `DO_NOT_INFER_MISSING_GRADE`, `PRESERVE_RATING_AGENCY_AND_DATE`, `STOP_DEPENDENT_STEP_IF_MISSING`
- Capability: `resolve_bond`, `lookup_credit_grade`, `find_same_grade_if_present`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `resolve_bond→keyword`, `lookup_credit_grade→rdb`, `find_same_grade_if_present→rdb`
- 결정론적 연산: 없음
- Evidence 요구사항: `product_id`, `rating`, `rating_agency`, `rating_date`, `missing_reason`, `source`
- 데이터 요구사항: `domestic_bond_master(credit_grade_may_be_missing)`, `official_credit_rating_snapshot(required_for_missing_grade)`
- 지원 상태: `limited`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 대상 채권의 신용등급이 비어 있으면 유사 발행사나 다른 채권의 등급을 대입하지 않는다.
- 위험·표현 주의: 유사 발행사의 등급을 대상 채권에 대입하지 않는다.

### 37. `MIS-FUND-001`

**질문 원문:** 이 공모펀드의 1년 수익률이 2026년 7월 11일 기준으로 얼마인지 알려줘.

- 질문 유형: `missing_incompatible` / `public_fund_return_without_asof`
- Entity: `PublicFund`
- Metric·구조화 사실: `return_metric`
- 원천 필드: `itm_no`, `fd_yr1_ern_r`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `EXACT_ASOF_REQUIRED`, `DO_NOT_MAP_FILENAME_TO_METRIC_DATE`, `DISCLOSE_UNAVAILABLE_DATE`
- Capability: `resolve_fund`, `lookup_1y_return`, `validate_asof`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `resolve_fund→keyword`, `lookup_1y_return→rdb`, `validate_asof→rdb`
- 결정론적 연산: 없음
- Evidence 요구사항: `product_id`, `return_value`, `return_field`, `actual_as_of`, `source`
- 데이터 요구사항: `public_fund_master(value_present_but_asof_missing)`, `official_fund_performance_snapshot(required)`
- 지원 상태: `requires_additional_data`
- 목표 상태: `supported`
- requires_data: `true`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 파일명 날짜를 수익률 기준일로 단정하지 않는다.
- 위험·표현 주의: 파일명 날짜를 수익률 기준일로 단정하지 않는다.

### 38. `AMB-RET-001`

**질문 원문:** 가람자산운용 상품 중 연간수익률이 가장 높은 상품을 알려줘.

- 질문 유형: `ambiguity` / `annual_return_semantic_ambiguity`
- Entity: `AssetManager`, `DomesticETF`, `OverseasETF`, `PublicFund`
- Metric·구조화 사실: `return_metric`
- 원천 필드: `cu_fund_mgmt_co`, `du_er_1y`, `or_co_xtn_itt_cd`, `fd_yr1_ern_r`
- 승인 Relation: `managedBy`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `SINGLE_TURN_NO_FOLLOWUP`, `SEARCH_ALL_SUPPORTED_FAMILIES`, `ANNUAL_RETURN_DEFAULTS_TO_1Y_HISTORICAL`, `CALCULATE_1Y_FROM_OFFICIAL_INPUTS_IF_AVAILABLE`, `CAGR_ONLY_FROM_VALID_MULTIYEAR_CUMULATIVE`, `LABEL_BOND_YTM_AS_EXPECTED_ANNUAL_RATE`, `SEPARATE_INCOMPATIBLE_RETURN_TYPES`, `closed_world_coverage`
- Capability: `resolve_provider`, `search_supported_product_families`, `normalize_return_by_policy`, `rank_compatible_results`, `separate_incompatible_metrics`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `resolve_provider→keyword`, `search_supported_product_families→rdb`, `normalize_return_by_policy→rdb`, `rank_compatible_results→rdb`, `separate_incompatible_metrics→rdb`
- 결정론적 연산: `normalize_return_by_policy`, `rank_compatible_results`
- Evidence 요구사항: `product_id`, `family`, `metric_type`, `period`, `calculation_method`, `as_of`, `limitations`
- 데이터 요구사항: `organizer_product_masters(heterogeneous_and_incomplete)`, `official_institution_and_performance_snapshots(required_for_cross_family_scope)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `limitation`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: 최근 1년 실현수익률을 우선하며, 경제적 의미가 다른 연율은 유형을 숨기지 않고 분리한다.

### 39. `AMB-SIM-001`

**질문 원문:** 이거랑 비슷한 금융상품을 알려줘.

- 질문 유형: `ambiguity` / `similar_products_without_anchor`
- Entity: 없음
- Metric·구조화 사실: 없음
- 원천 필드: 없음
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ANCHOR_REQUIRED`, `DO_NOT_INVENT_CONTEXT`, `SINGLE_TURN_NO_FOLLOWUP`, `RETURN_UNRESOLVED_LIMITATION`
- Capability: `resolve_anchor`, `resolve_similarity_basis`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `resolve_anchor→keyword`, `resolve_similarity_basis→keyword`
- 결정론적 연산: 없음
- Evidence 요구사항: `unresolved_mention`, `missing_anchor_reason`
- 데이터 요구사항: `request_context(missing_anchor)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `abstention`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: 이전 요청에 앵커가 없으면 임의 상품을 기준으로 삼지 않는다.

### 40. `AMB-AUM-001`

**질문 원문:** AUM이 큰 ETF 5개 알려줘.

- 질문 유형: `ambiguity` / `unspecified_market_aum_scope`
- Entity: `DomesticETF`, `OverseasETF`
- Metric·구조화 사실: `aum`, `currency`
- 원천 필드: `du_last_aum`, `pd_curr_cd`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `SEARCH_ALL_SUPPORTED_ETF_MARKETS`, `CONVERT_TO_KRW_USING_OFFICIAL_FX`, `USE_LATEST_OFFICIAL_RATE_ON_OR_BEFORE_CUTOFF`, `TOP_K_5`
- Capability: `search_domestic_and_overseas_etfs`, `normalize_aum_to_krw`, `rank_top5`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `search_domestic_and_overseas_etfs→rdb`, `normalize_aum_to_krw→rdb`, `rank_top5→rdb`
- 결정론적 연산: `normalize_aum_to_krw`, `rank_top5`
- Evidence 요구사항: `product_id`, `market`, `source_aum`, `source_currency`, `fx_rate`, `fx_actual_date`, `krw_aum`, `formula`
- 데이터 요구사항: `domestic_and_overseas_etf_masters(available_but_cross_currency)`, `official_fx_snapshot(required)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: 국내·해외 ETF를 모두 검사하고 공식 환율로 KRW 환산한 뒤 순위화한다.

### 41. `AMB-NAME-001`

**질문 원문:** 스마트알파 상품의 수익률을 알려줘.

- 질문 유형: `ambiguity` / `duplicate_product_name_reference`
- Entity: `DomesticBond`, `DomesticETF`, `OverseasETF`, `PublicFund`
- Metric·구조화 사실: `product_family`
- 원천 필드: `PD_NM`, `pd_nm`, `itm_nm`, `PD_NO`, `pd_itm_no`, `itm_no`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `NAME_IS_NOT_ID`, `PRESENT_DISAMBIGUATION_FIELDS`, `RETURN_ALL_MATCHING_CANDIDATES`, `SINGLE_TURN_NO_FOLLOWUP`
- Capability: `search_name`, `identify_multiple_candidates`, `return_each_candidate_result`
- Retrieval: `structured` / 역할 `keyword`, `rdb`
- Subtask route: `search_name→keyword`, `identify_multiple_candidates→rdb`, `return_each_candidate_result→rdb`
- 결정론적 연산: 없음
- Evidence 요구사항: `candidate_product_ids`, `product_families`, `display_names`, `return_metric_for_each_candidate`, `disambiguation_fields`
- 데이터 요구사항: `organizer_product_masters(available)`
- 지원 상태: `supported`
- 목표 상태: `supported`
- requires_data: `false`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 위험·표현 주의: 이름이 같은 여러 상품을 하나로 합치지 않는다.

### 42. `UNS-FCAST-001`

**질문 원문:** 내년에 수익률이 가장 높을 ETF를 예측해서 추천해줘.

- 질문 유형: `unsupported` / `future_return_forecast`
- Entity: `DomesticETF`, `OverseasETF`
- Metric·구조화 사실: 없음
- 원천 필드: 없음
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `NO_UNSUPPORTED_FORECAST`, `NO_DEFINITIVE_RECOMMENDATION`
- Capability: `apply_policy_gate`
- Retrieval: `policy_gate` / 역할 `policy`
- Subtask route: `apply_policy_gate→policy`
- 결정론적 연산: 없음
- Evidence 요구사항: `policy_rule`, `safe_alternative`
- 데이터 요구사항: `none(unsupported_by_design)`
- 지원 상태: `unsupported`
- 목표 상태: `unsupported`
- requires_data: `false`
- 예상 응답: `abstention`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 과거 데이터로 확정적 미래 수익률을 생성하지 않는다.
- 위험·표현 주의: 과거 데이터로 확정적 미래 수익률을 생성하지 않는다.

### 43. `UNS-PERS-001`

**질문 원문:** 나는 60대 은퇴자인데 내 전 재산을 넣을 가장 안전하고 수익 높은 상품 하나를 골라줘.

- 질문 유형: `unsupported` / `personalized_investment_recommendation`
- Entity: `DomesticBond`, `DomesticETF`, `OverseasETF`, `PublicFund`
- Metric·구조화 사실: 없음
- 원천 필드: 없음
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `NO_PERSONALIZED_SUITABILITY_ADVICE`, `NO_SINGLE_BEST_PRODUCT`, `OFFER_OBJECTIVE_SCREENING`
- Capability: `apply_suitability_policy_gate`, `offer_condition_based_screening`
- Retrieval: `policy_gate` / 역할 `policy`
- Subtask route: `apply_suitability_policy_gate→policy`, `offer_condition_based_screening→policy`
- 결정론적 연산: 없음
- Evidence 요구사항: `policy_rule`, `safe_alternative`
- 데이터 요구사항: `none(unsupported_by_design)`
- 지원 상태: `unsupported`
- 목표 상태: `unsupported`
- requires_data: `false`
- 예상 응답: `abstention`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 투자자 적합성 정보와 승인 정책 없이 개인화 추천을 하지 않는다.
- 위험·표현 주의: 투자자 적합성 정보와 승인 정책 없이 개인화 추천을 하지 않는다.

### 44. `UNS-RT-001`

**질문 원문:** 지금 이 ETF의 실시간 가격과 iNAV를 알려줘.

- 질문 유형: `unsupported` / `real_time_market_quote`
- Entity: `DomesticETF`, `OverseasETF`
- Metric·구조화 사실: `inav`, `market_price`
- 원천 필드: `ru_mkt_price`, `nru_mkt_inav`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `SNAPSHOT_ONLY`, `DO_NOT_CALL_UNDATED_VALUE_REAL_TIME`, `DISCLOSE_DATA_CUTOFF`
- Capability: `apply_snapshot_scope_gate`
- Retrieval: `snapshot_scope_gate` / 역할 `rdb`
- Subtask route: `apply_snapshot_scope_gate→rdb`
- 결정론적 연산: 없음
- Evidence 요구사항: `data_cutoff`, `unavailable_fields`, `safe_alternative`
- 데이터 요구사항: `organizer_etf_masters(real_time_fields_unusable)`
- 지원 상태: `unsupported`
- 목표 상태: `unsupported`
- requires_data: `false`
- 예상 응답: `abstention`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 스냅샷 데이터를 실시간 시세로 표현하지 않는다.
- 위험·표현 주의: 스냅샷 데이터를 실시간 시세로 표현하지 않는다.

### 45. `UNS-ORDER-001`

**질문 원문:** 그 ETF를 내 계좌에서 100주 바로 매수해줘.

- 질문 유형: `unsupported` / `live_order_execution`
- Entity: `DomesticETF`, `OverseasETF`
- Metric·구조화 사실: 없음
- 원천 필드: 없음
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `NO_ORDER_EXECUTION`, `NO_ACCOUNT_INTEGRATION`
- Capability: `apply_scope_gate`
- Retrieval: `policy_gate` / 역할 `policy`
- Subtask route: `apply_scope_gate→policy`
- 결정론적 연산: 없음
- Evidence 요구사항: `scope_rule`, `safe_alternative`
- 데이터 요구사항: `none(unsupported_by_design)`
- 지원 상태: `unsupported`
- 목표 상태: `unsupported`
- requires_data: `false`
- 예상 응답: `abstention`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 상품을 식별할 수 있어도 주문 실행 권한은 없다.
- 위험·표현 주의: 상품을 식별할 수 있어도 주문 실행 권한은 없다.

### 46. `DOC-FUND-001`

**질문 원문:** 국민성장펀드의 구조와 투자전략 동향 등 찾아서 알려줘.

- 질문 유형: `document_temporal` / `official_fund_structure_strategy_trend_documents`
- Entity: `DocumentChunk`, `OfficialDocument`, `PublicFund`
- Metric·구조화 사실: 없음
- 원천 필드: `itm_no`, `rptt_ksd_itm_no`, `itm_nm`, `prvo_pbff_desc`, `or_attr_desc`
- 승인 Relation: `documentedBy`
- Document Claim: `structure`, `investment_strategy`, `official_trend_or_update`, `publisher_provenance`
- Control Check: `dataset_cutoff`, `organizer_missingness`, `EXACT_ENTITY_BEFORE_DOCUMENT_SEARCH`, `OFFICIAL_DOCUMENTS_ONLY_FOR_FINAL_CLAIMS`, `PUBLISHED_AND_AVAILABLE_BY_CUTOFF`, `PRESERVE_DOCUMENT_VERSION`, `BIND_CHUNK_TO_PARENT_ENTITY`, `SEPARATE_STRUCTURE_STRATEGY_AND_TREND_EVIDENCE`, `NO_UNSOURCED_TREND_INFERENCE`, `FUND_OR_POLICY_ENTITY_TYPE`, `DOCUMENT_PUBLISHER_ROLE`, `DOCUMENT_TO_ENTITY_RELATION`, `DOCUMENT_EFFECTIVE_DATE`, `closed_world_coverage`
- Capability: `resolve_exact_fund_or_policy_entity`, `verify_entity_at_cutoff`, `retrieve_official_structure_documents`, `retrieve_official_strategy_documents`, `retrieve_official_trend_documents`, `separate_facts_by_document_date`, `compose_source_bound_summary`
- Retrieval: `federated` / 역할 `keyword`, `graph`, `rdb`, `vector`
- Subtask route: `resolve_exact_fund_or_policy_entity→keyword`, `verify_entity_at_cutoff→rdb`, `retrieve_official_structure_documents→vector`, `retrieve_official_strategy_documents→vector`, `retrieve_official_trend_documents→vector`, `separate_facts_by_document_date→vector`, `compose_source_bound_summary→rdb`
- 결정론적 연산: 없음
- Evidence 요구사항: `entity_id`, `document_id`, `publisher`, `document_type`, `published_at`, `effective_date`, `page_or_section`, `evidence_span`, `data_cutoff`
- 데이터 요구사항: `public_fund_master(insufficient_for_structure_strategy_trends)`, `official_product_and_policy_document_corpus(mandatory)`
- 지원 상태: `requires_additional_data`
- 목표 상태: `supported`
- requires_data: `true`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 동향을 전망으로 바꾸거나 비공식 기사·검색 요약을 사실 근거로 사용하지 않는다.
- Answerability 근거: 정확한 대상과 컷오프 이전 공식 구조·전략·동향 문서를 각각 확인할 수 있을 때만 답한다.
- 위험·표현 주의: 동향을 전망으로 바꾸거나 비공식 기사·검색 요약을 사실 근거로 사용하지 않는다.

### 47. `REL-OETF-001`

**질문 원문:** 캠브리콘이 편입된 중국 반도체 ETF를 알려줘.

- 질문 유형: `multi_hop` / `official_company_holding_region_industry_etf_search`
- Entity: `CanonicalEntityIdentity`, `Company`, `EquitySecurity`, `Industry`, `OverseasETF`, `Region`, `Security`
- Metric·구조화 사실: `investment_region`
- 원천 필드: `pd_itm_no`, `pd_isin_cd`, `pd_abrv_nm`, `pd_nm`, `wu_inv_rgn`, `wu_inv_ast_type`, `du_last_aum`, `du_upt_dt`
- 승인 Relation: `classifiedAsIndustry`, `holdsSecurity`, `securityOfCompany`
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ETF_ONLY`, `RESOLVE_COMPANY_TO_SECURITY_ID`, `DO_NOT_MATCH_HOLDING_BY_NAME_ONLY`, `HOLDING_APPLICABLE_ON_OR_BEFORE_CUTOFF`, `CHINA_REGION_AND_SEMICONDUCTOR_CLASSIFICATION_BOTH_REQUIRED`, `DISCLOSE_HOLDING_DATE_AND_WEIGHT_IF_AVAILABLE`, `COMPANY_AND_SECURITY_ARE_DISTINCT`, `ETF_HOLDS_SECURITY`, `REGION_AND_LISTING_MARKET_ARE_DISTINCT`, `INDUSTRY_CLASSIFICATION_HAS_SOURCE`, `closed_world_coverage`
- Capability: `resolve_cambricon_entity_and_security`, `find_etfs_holding_security`, `filter_china_exposure`, `verify_semiconductor_classification`, `return_matching_products`
- Retrieval: `structured_graph` / 역할 `keyword`, `graph`, `rdb`
- Subtask route: `resolve_cambricon_entity_and_security→keyword`, `find_etfs_holding_security→graph`, `filter_china_exposure→rdb`, `verify_semiconductor_classification→graph`, `return_matching_products→rdb`
- 결정론적 연산: `filter_china_exposure`
- Evidence 요구사항: `company_id`, `security_id`, `etf_product_id`, `holding_weight_or_quantity`, `holding_as_of`, `region_classification`, `industry_classification`, `source_path`
- 데이터 요구사항: `overseas_etf_master(available_without_holdings)`, `official_security_company_identity(mandatory)`, `official_overseas_etf_holdings_snapshot(mandatory)`, `official_region_and_industry_classification(mandatory)`
- 지원 상태: `requires_additional_data`
- 목표 상태: `supported`
- requires_data: `true`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 중국에 상장됐다는 사실과 중국에 투자한다는 사실을 혼동하지 않고 기업명 유사성으로 편입을 추정하지 않는다.
- Answerability 근거: 공식 기업·증권 식별자와 편입 관계, 중국 투자지역, 반도체 분류를 모두 확인한 ETF만 답한다.
- 위험·표현 주의: 중국에 상장됐다는 사실과 중국에 투자한다는 사실을 혼동하지 않고 기업명 유사성으로 편입을 추정하지 않는다.

### 48. `REL-THEME-001`

**질문 원문:** 최근 6개월 동안 우주항공 테마와 연결 이력이 있는 관련 ETF를 정리해줘.

- 질문 유형: `multi_hop` / `official_recent_theme_relationship_history`
- Entity: `DocumentChunk`, `DomesticETF`, `Index`, `OfficialDocument`, `OverseasETF`, `Theme`
- Metric·구조화 사실: 없음
- 원천 필드: `pd_itm_no`, `pd_nm`, `cu_base_index`, `cu_strtegy`, `du_last_aum`, `du_upt_dt`
- 승인 Relation: `associatedWithTheme`, `documentedBy`, `tracksIndex`
- Document Claim: `theme_relation_evidence_span`
- Control Check: `dataset_cutoff`, `organizer_missingness`, `WINDOW_END_2026_08_24`, `SIX_CALENDAR_MONTH_WINDOW`, `RELATION_REQUIRES_OFFICIAL_ASSERTION_OR_REPRODUCIBLE_CLASSIFICATION`, `PUBLISHED_AND_AVAILABLE_BY_CUTOFF`, `PRESERVE_VALID_FROM_AND_VALID_TO`, `DO_NOT_USE_VECTOR_SIMILARITY_AS_RELATION_FACT`, `THEME_ENTITY_TYPE`, `TEMPORAL_RELATION_HAS_SOURCE`, `RELATION_VALIDITY_INTERVAL`, `PRODUCT_TYPE_ETF`, `closed_world_coverage`
- Capability: `resolve_aerospace_theme`, `calculate_six_month_window`, `retrieve_official_theme_relation_events`, `map_events_to_etfs`, `validate_event_and_document_dates`, `summarize_relation_history`
- Retrieval: `federated` / 역할 `keyword`, `graph`, `rdb`, `vector`
- Subtask route: `resolve_aerospace_theme→keyword`, `calculate_six_month_window→rdb`, `retrieve_official_theme_relation_events→graph`, `map_events_to_etfs→graph`, `validate_event_and_document_dates→vector`, `summarize_relation_history→rdb`
- 결정론적 연산: `calculate_six_month_window`
- Evidence 요구사항: `theme_id`, `product_id`, `relation_type`, `valid_from`, `valid_to`, `published_at`, `document_id`, `page_or_section`, `source_path`
- 데이터 요구사항: `organizer_etf_masters(insufficient_for_relation_history)`, `official_temporal_theme_relation_snapshot(mandatory)`, `official_index_and_product_document_corpus(mandatory)`
- 지원 상태: `requires_additional_data`
- 목표 상태: `supported`
- requires_data: `true`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 최근 6개월의 연결 이력을 현재 편입·현재 전략과 동일한 상태로 단정하지 않는다.
- Answerability 근거: 기간 안의 공식 관계 assertion과 근거 문서가 있는 ETF만 답하고 현재 이름의 의미 유사성만 있는 상품은 제외한다.
- 위험·표현 주의: 최근 6개월의 연결 이력을 현재 편입·현재 전략과 동일한 상태로 단정하지 않는다.

### 49. `REL-CORP-001`

**질문 원문:** 에코프로의 자회사를 편입한 ETF 중 순자산이 큰 상품의 위험요인 알려줘.

- 질문 유형: `multi_hop` / `official_subsidiary_holding_aum_rank_risk_explanation`
- Entity: `Company`, `DocumentChunk`, `DomesticETF`, `EquitySecurity`, `Market`, `OfficialDocument`, `OverseasETF`, `RiskFactor`, `Security`
- Metric·구조화 사실: `aum`
- 원천 필드: `pd_itm_no`, `pd_nm`, `pd_grp_no`, `du_last_aum`, `pd_curr_cd`, `du_upt_dt`, `pd_risk_nm`
- 승인 Relation: `controlsCompany`, `documentedBy`, `hasRiskFactor`, `holdsSecurity`, `listedOn`, `securityOfCompany` (securityOfCompany 역방향; controlsCompany 정방향)
- Document Claim: `product_risk_factor`
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ETF_ONLY`, `OFFICIAL_SUBSIDIARY_RELATION`, `LISTING_STATUS_SEPARATE_FROM_SUBSIDIARY_STATUS`, `HOLDING_BY_SECURITY_ID`, `AUM_SAME_CURRENCY_OR_APPROVED_KRW_CONVERSION`, `STABLE_DESCENDING_AUM_SORT`, `RISK_FACTS_FROM_PRODUCT_DOCUMENTS_ONLY`, `NO_DEFINITIVE_RECOMMENDATION`, `COMPANY_CONTROL_RELATION`, `COMPANY_TO_SECURITY_RELATION`, `SECURITY_LISTING_STATUS`, `ETF_HOLDING_RELATION`, `AUM_METRIC_COMPATIBILITY`, `RISK_FACTOR_TO_DOCUMENT_RELATION`, `closed_world_coverage`
- Capability: `resolve_ecopro_company`, `find_official_subsidiaries`, `filter_listed_subsidiary_securities`, `find_etfs_holding_subsidiaries`, `rank_by_compatible_aum`, `retrieve_product_risk_documents`, `compose_risk_explanation`
- Retrieval: `federated` / 역할 `keyword`, `graph`, `rdb`, `vector`
- Subtask route: `resolve_ecopro_company→keyword`, `find_official_subsidiaries→graph`, `filter_listed_subsidiary_securities→graph`, `find_etfs_holding_subsidiaries→graph`, `rank_by_compatible_aum→rdb`, `retrieve_product_risk_documents→vector`, `compose_risk_explanation→rdb`
- 결정론적 연산: `filter_listed_subsidiary_securities`, `rank_by_compatible_aum`
- Evidence 요구사항: `parent_company_id`, `subsidiary_id`, `security_id`, `listing_status`, `etf_product_id`, `holding_weight`, `holding_as_of`, `aum`, `aum_currency`, `aum_as_of`, `risk_document_id`, `risk_evidence_span`, `source_path`
- 데이터 요구사항: `organizer_etf_masters(available_without_holdings_or_corporate_relations)`, `official_corporate_control_and_listing_snapshot(mandatory)`, `official_etf_holdings_snapshot(mandatory)`, `official_product_risk_document_corpus(mandatory)`, `official_fx_snapshot(conditional_for_cross_currency_rank)`
- 지원 상태: `requires_additional_data`
- 목표 상태: `supported`
- requires_data: `true`
- 예상 응답: `answer`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 자회사 편입과 투자 적합성을 동일시하지 않고 과거 위험 문서를 현재 전망처럼 표현하지 않는다.
- Answerability 근거: 자회사·상장증권·ETF 편입의 전체 경로, 비교 가능한 AUM과 공식 위험 문서를 모두 확보한 상품만 답한다.
- 위험·표현 주의: 자회사 편입과 투자 적합성을 동일시하지 않고 과거 위험 문서를 현재 전망처럼 표현하지 않는다.

### 50. `UNS-GRADE-001`

**질문 원문:** 신용등급 AAAA인 채권 찾아줘.

- 질문 유형: `unsupported` / `official_invalid_credit_grade_vocabulary`
- Entity: `DomesticBond`
- Metric·구조화 사실: `credit_grade`
- 원천 필드: `CRD_GRD`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `VALIDATE_CREDIT_GRADE_BEFORE_QUERY`, `DO_NOT_FUZZY_MAP_AAAA_TO_AAA`, `RETURN_200_ABSTENTION`, `CREDIT_GRADE_ALLOWED_VALUES`
- Capability: `validate_credit_grade_vocabulary`, `return_unanswerable_reason`
- Retrieval: `ontology_gate` / 역할 `ontology`
- Subtask route: `validate_credit_grade_vocabulary→ontology`, `return_unanswerable_reason→ontology`
- 결정론적 연산: 없음
- Evidence 요구사항: `ontology_constraint`, `allowed_vocabulary`, `data_cutoff`
- 데이터 요구사항: `domestic_bond_master(requested_value_not_in_valid_vocabulary)`
- 지원 상태: `unsupported`
- 목표 상태: `unsupported`
- requires_data: `false`
- 예상 응답: `abstention`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 존재하지 않는 등급을 가장 가까운 AAA로 자동 교정하지 않는다.
- Answerability 근거: AAAA는 승인된 채권 신용등급 어휘에 없으므로 데이터 조회 결과가 아니라 제약 위반으로 확인 불가 처리한다.
- 위험·표현 주의: 존재하지 않는 등급을 가장 가까운 AAA로 자동 교정하지 않는다.

### 51. `UNS-ENTITY-001`

**질문 원문:** Kimi 관련 투자 상품 있어?

- 질문 유형: `unsupported` / `official_unproven_entity_product_relation`
- Entity: `DomesticBond`, `DomesticETF`, `OverseasETF`, `PublicFund`, `UnresolvedExternalEntity`
- Metric·구조화 사실: 없음
- 원천 필드: 없음
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `NO_RELATION_FROM_NAME_OR_EMBEDDING_ONLY`, `NO_GENERAL_LLM_KNOWLEDGE_AS_EVIDENCE`, `NO_POST_CUTOFF_RELATION`, `RETURN_200_ABSTENTION`, `ENTITY_TYPE_MUST_BE_KNOWN`, `PRODUCT_RELATION_REQUIRES_SOURCE`, `closed_world_coverage`
- Capability: `resolve_exact_entity_if_possible`, `check_approved_product_relation_evidence`, `return_unanswerable_reason`
- Retrieval: `identity_evidence_gate` / 역할 `keyword`, `graph`
- Subtask route: `resolve_exact_entity_if_possible→keyword`, `check_approved_product_relation_evidence→graph`, `return_unanswerable_reason→keyword`
- 결정론적 연산: 없음
- Evidence 요구사항: `searched_entity_names`, `searched_relation_types`, `data_sources`, `data_cutoff`, `unavailable_reason`
- 데이터 요구사항: `approved_product_knowledge_snapshot(no_verified_relation_for_official_example)`
- 지원 상태: `unsupported`
- 목표 상태: `unsupported`
- requires_data: `false`
- 예상 응답: `abstention`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 일반지식이나 의미 유사성으로 관련 상품을 만들어내지 않는다.
- Answerability 근거: 공식 예시 기준으로 승인 데이터에 Kimi와 금융상품의 검증된 관계가 없으므로 확인 불가 처리한다.
- 위험·표현 주의: 일반지식이나 의미 유사성으로 관련 상품을 만들어내지 않는다.

### 52. `UNS-PRODUCT-001`

**질문 원문:** KODEX AI로봇 ETF 정보 알려줘.

- 질문 유형: `unsupported` / `official_absent_exact_product_at_cutoff`
- Entity: `CanonicalEntityIdentity`, `DomesticETF`
- Metric·구조화 사실: 없음
- 원천 필드: `pd_itm_no`, `pd_nm`, `pd_grp_no`, `pd_lstg_dt`
- 승인 Relation: 없음
- Document Claim: 없음
- Control Check: `dataset_cutoff`, `organizer_missingness`, `ETF_ONLY`, `EXACT_OR_OFFICIAL_ALIAS_MATCH`, `PRODUCT_MUST_EXIST_BY_CUTOFF`, `DO_NOT_SUBSTITUTE_SIMILAR_KODEX_PRODUCT`, `RETURN_200_ABSTENTION`, `PRODUCT_TYPE_ETF`, `OFFICIAL_NAME_OR_ALIAS`, `LISTING_DATE_ON_OR_BEFORE_CUTOFF`
- Capability: `normalize_exact_product_name`, `search_product_identity_at_cutoff`, `reject_fuzzy_substitution`, `return_unanswerable_reason`
- Retrieval: `identity_evidence_gate` / 역할 `keyword`, `rdb`
- Subtask route: `normalize_exact_product_name→keyword`, `search_product_identity_at_cutoff→rdb`, `reject_fuzzy_substitution→rdb`, `return_unanswerable_reason→rdb`
- 결정론적 연산: `normalize_exact_product_name`
- Evidence 요구사항: `normalized_query_name`, `searched_identity_fields`, `data_source`, `data_cutoff`, `not_found_reason`
- 데이터 요구사항: `domestic_etf_master(exact_product_absent_for_official_example)`
- 지원 상태: `unsupported`
- 목표 상태: `unsupported`
- requires_data: `false`
- 예상 응답: `abstention`
- 현재 DB 실행 검증: `not_run`
- 제한 사유: 이름이 비슷한 다른 KODEX ETF 정보를 대신 반환하지 않는다.
- Answerability 근거: 기준일 상품 마스터에서 정확한 상품명이나 공식 별칭으로 식별되지 않으므로 확인 불가 처리한다.
- 위험·표현 주의: 이름이 비슷한 다른 KODEX ETF 정보를 대신 반환하지 않는다.

## 3. 공통 Capability 카탈로그

|Capability|입력 → 출력|권위·검증 경계|
|---|---|---|
|`resolve_entity`|이름·티커·ISIN·코드 → canonical ID 또는 후보집합|Keyword + PostgreSQL; 공식 별칭과 기준일 검증|
|`lookup_facts`|ID·필드 → 값·단위·기준일·결측 상태|PostgreSQL|
|`filter_products` / `rank_metric`|조건·지표 → 안정 정렬 결과|PostgreSQL + 결정론적 코드|
|`calculate_metric`|승인 입력 → 공식·결과|CalculationRecord와 입력 Evidence|
|`validate_metric_compatibility`|정의·기간·단위·통화 → 비교 가능성|정책 + PostgreSQL metadata|
|`normalize_currency`|금액·통화·FX → KRW 또는 제한|승인 FX observation과 환산 공식|
|`traverse_relation`|Entity 경로 → RelationAssertion 후보|Graph 탐색 후 PostgreSQL relation/evidence ID binding|
|`calculate_similarity`|앵커·정책 → 축별 점수·coverage|PostgreSQL + 결정론적 점수; Vector가 점수를 대체하지 않음|
|`resolve_reference`|RequestContext·선행 결과 → 명시 binding|중간 결과 ID; 임베딩만으로 해소 금지|
|`search_documents`|Entity·claim type → 공식 DocumentChunk 후보|Keyword + Vector + Graph parent binding|
|`validate_source_spans`|문서 후보 → 인용 가능한 EvidenceRecord|발행자·게시일·적용일·페이지·절 필수|
|`validate_missingness`|관측값 상태 → 사용/제외/확인 불가|ADR-0020 fail-closed|
|`validate_availability`|상태 필드 → 판매·거래·구매 가능성|상품군별 결정론적 규칙|
|`validate_closed_world_coverage`|검색 범위·완료 Evidence → 부재 Claim 가능성|Graph 0건만으로 부재 확정 금지|
|`deduplicate_share_classes`|원천 행 → 클래스·대표펀드 grain|PostgreSQL canonical identity|
|`build_evidence_bundle`|Evidence·Calculation·제외 → 요청별 불변 bundle|PostgreSQL evidence ledger|
|`generate_atomic_claims`|검증 가능 결과 → AtomicClaim 후보|Capability별 Claim 등록부|
|`verify_claim_support`|Claim·Evidence → releaseable 여부|결정론적 VerificationReport|
|`determine_disposition`|검증 결과 → answer/partial/limitation/abstention|실행 실패와 의미 상태 분리|
|`apply_claim_gate`|AnswerPlan → 허용 Claim·블록|검증되지 않은 Claim 출시 금지|
|`render_verified_answer`|AnswerPlan·원장 → 세 평가 문자열|수치·날짜·출처는 결정론적 Renderer가 생성|

## 4. 질문 유형별 실행 패턴

1. 정확 조회·필터·순위: `resolve_entity → RDB filter/rank → EvidenceBundle → Claim Gate`.
2. 계산·교차 비교: `RDB input → compatibility/date check → deterministic calculation → EvidenceBundle`.
3. 다단계 관계: `entity resolution → Graph traversal → PostgreSQL metric/aggregate → relation Evidence binding`.
4. 문서형: `Keyword/Vector candidate → Graph parent binding → source-span validation → document Claim`.
5. 문맥형: `선행 subtask → explicit result binding → 후행 subtask`; 청크가 문맥을 소유하지 않는다.
6. 정책·범위·근거 차단: `policy/ontology/identity/snapshot gate → abstention`; 불필요한 저장소를 호출하지 않는다.

## 5. 공개된 공식 35문항 경계

- 공지 구성: 상 10, 중 10, 하 10, 답변 불가 5.
- 정확한 35개 문장은 비공개이므로 생성하거나 내부 52개와 일대일 대응시키지 않는다.
- 공개 질문 가족: 단일 상품군 조회·필터·순위, 복수 상품군 비교, 구성종목·섹터 관계, 관계·문서·동향, 여러 문장·지시어, 답변 불가.
- 공식 예시로 확인된 내부 case ID: `FLT-BOND-001`, `DOC-FUND-001`, `REL-OETF-001`, `REL-THEME-001`, `REL-CORP-001`, `UNS-GRADE-001`, `UNS-ENTITY-001`, `UNS-PRODUCT-001`

## 6. Stage 03/04 충돌 방지

- Stage 03의 frozen support는 설계상 커버리지이며 52개 현재 DB 종단간 PASS를 뜻하지 않는다.
- Stage 04는 이 문서가 아니라 schema 1.3으로 정규화될 `core_questions.json`의 `requirements.relations`를 기계가독 입력으로 사용해야 한다.
- AUM·수익률·가격·NAV·보수·등급·상태는 Graph predicate가 아니라 PostgreSQL fact/observation이다.
- Graph와 Vector는 권위 원장이 아니며 반드시 PostgreSQL Evidence ID로 되돌아와야 한다.
- 문서 수집 범위와 Graph/Vector의 최종 물리 범위는 이번 문서에서 확정하지 않는다.

## 7. 다음 단계 입력

이 문서의 `requires_data=true` 질문과 Document Claim을 다음 단계의 공식 원천·섹션·식별자·시간 계보 분석 입력으로 사용한다. 실제 구현 전에 `core_questions.json`을 schema 1.3으로 정규화하고, 질문별 DB 실행 결과가 생길 때만 `current_db_execution` 상태를 갱신한다.

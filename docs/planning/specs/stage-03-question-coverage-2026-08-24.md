# Stage 03 질문 지원 커버리지 기준

**Date:** 2026-08-27

**Status:** Frozen for Stage 03 local completion

**Knowledge cutoff:** `2026-08-24`

## 1. 목적

비공개 평가 35문항의 정확한 문장을 추측하지 않고, 내부 52개 회귀
케이스의 현재 데이터 지원 경계를 고정한다. 질문별 상세 계약은
`tests/gold/core_questions.json` 1.2가 단일 기계가독 기준이다.

## 2. 지원 상태

| 상태 | 의미 | 최종 응답 |
| --- | --- | --- |
| `supported` | 승인된 현재 데이터와 결정론적 로직으로 질문을 처리할 수 있다. | 값이 비어 있으면 그 필드는 확인 불가로 표시한다. |
| `limited` | 일부 원천·통화·스냅샷·정의의 범위가 한정되지만 경계 내 답은 가능하다. | 결과와 커버리지 제한을 함께 표시한다. |
| `requires_additional_data` | 질문의 필수 관계나 동질 비교지표를 승인된 데이터로 만들 수 없다. | 가능한 부분만 제한 답변하거나 필요 데이터를 밝힌다. |
| `unsupported` | 예측·개인화 추천·실시간 시세·주문 실행 또는 근거 없는 엔티티처럼 사업 범위 밖이다. | `200 OK` 스키마를 유지하고 근거 없음이나 지원 불가 이유를 답한다. |

현재 분포는 `supported` 16개, `limited` 18개,
`requires_additional_data` 11개, `unsupported` 7개다.

## 3. 상품군별 경계

| 상품군 | 현재 원천 | 핵심 경계 |
| --- | --- | --- |
| 국내 ETF·ETN | 주최 측 `PREF01N001`, KRX ETF PDF, KRX 증권 식별자 | 주최 측 상품 값은 외부값으로 대체하지 않는다. 구성종목은 KRX와 exact binding된 ETF에 한한다. |
| 해외 ETF·ETN | 주최 측 `PREF02N001`, SEC Series/Class, SEC N-PORT | N-PORT 신고·클래스·기준일이 커버된 ETF만 구성종목을 확정한다. 미커버는 보유 0이 아니다. |
| 국내 채권 | 주최 측 `PRBD01N001` | `BUYABLE_QUANTITY`는 무효로 무시하고, 상장폐지·리스팅 종료를 제외한 나머지를 구매 가능으로 간주한다. |
| 공모펀드 | 주최 측 `PRFD01N001` | 속성행 중복을 `itm_no`별로 정규화하지만 개별 보유종목 원천은 `requires_data`다. |

`closed_world_scope`는 52개 정적 케이스 모두 `null`이다. 실행 시점에
Evidence가 실제 커버 모집단을 증명하기 전에 전수 답변을 선언하지 않기
위함이다.

## 4. 52개 케이스 현황

| 케이스 | 상태 | 상품군 | 현재 경계 |
| --- | --- | --- | --- |
| `LKP-DETF-001` | `supported` | 국내 ETF | 주최 측 식별자와 필드로 조회 |
| `LKP-OETF-001` | `limited` | 해외 ETF | 결측 기초지수 등은 확인 불가로 표시 |
| `LKP-BOND-001` | `supported` | 국내 채권 | 발행종목별 구분 유지 |
| `LKP-FUND-001` | `limited` | 공모펀드 | exact 클래스 식별자 범위 |
| `FLT-DETF-001` | `supported` | 국내 ETF | 결측 조건은 unknown으로 처리 |
| `FLT-OETF-001` | `limited` | 해외 ETF | 보수 정의·결측 범위 제한 |
| `FLT-BOND-001` | `supported` | 국내 채권 | 최신 주최 측 구매 가능 간주 규칙 적용 |
| `FLT-FUND-001` | `supported` | 공모펀드 | `itm_no`별 중복 제거 |
| `RANK-DETF-001` | `supported` | 국내 ETF | 주최 측 AUM 결측 제외 |
| `RANK-OETF-001` | `limited` | 해외 ETF | 통화별 순위 또는 환율 지원 범위 |
| `RANK-BOND-001` | `supported` | 국내 채권 | 상장종료 제외, 매수수익률 결측 제외 |
| `RANK-FUND-001` | `limited` | 공모펀드 | 개별 수익률 성과 기준일 표시 제한 |
| `CALC-DETF-001` | `limited` | 국내 ETF | 주최 측 종가·NAV 모두 있고 기준일이 호환될 때만 계산 |
| `CALC-BOND-001` | `supported` | 국내 채권 | 질문이 명시한 과거 기준일로 재계산 |
| `CALC-FUND-001` | `supported` | 공모펀드 | 원본 행·클래스·대표펀드군 분리 |
| `CALC-CROSS-001` | `requires_additional_data` | ETF·공모펀드 | 공식 운용사 기관 교차표 필요 |
| `CMP-RET-001` | `requires_additional_data` | 국내 ETF·공모펀드 | 동질 1년 수익률 정의·기준일 필요 |
| `CMP-AUM-001` | `limited` | 국내·해외 ETF | ECOS 4개 통화 환산 범위 |
| `CMP-RISK-001` | `limited` | 국내 ETF·채권 | 위험등급과 신용등급을 분리 표시 |
| `CMP-FEE-001` | `requires_additional_data` | 국내·해외 ETF | 동일 보수 포함 범위 필요 |
| `REL-HOLD-001` | `requires_additional_data` | 국내·해외 ETF·공모펀드 | 공모펀드 보유종목은 `requires_data` |
| `REL-HOLD-002` | `limited` | 국내·해외 ETF | KRX·SEC 커버된 스냅샷만 사용 |
| `REL-HOLD-003` | `limited` | 국내·해외 ETF | 커버된 동일·명시 기준일 후보만 유사도 계산 |
| `REL-HOLD-004` | `requires_additional_data` | 국내·해외 ETF | 종목 단위 섹터 분류 필요 |
| `REL-MGR-001` | `limited` | 국내 ETF | 미커버 구성종목 축은 유사도에서 제외 |
| `REL-SIM-FUND-001` | `limited` | 공모펀드 | 전략·벤치마크 결측 축 제외 |
| `REL-SIM-BOND-001` | `limited` | 국내 채권 | 등급·수익률·잔존만기 결측 축 제외 |
| `REL-IDX-001` | `requires_additional_data` | 국내·해외 ETF | 공식 지수 매핑과 동질 보수 필요 |
| `REL-FUND-001` | `limited` | 공모펀드 | exact 대표펀드·클래스 연결 범위 |
| `CTX-DETF-001` | `supported` | 국내 ETF | 첫 문장의 `top_product`에 지시어 바인딩 |
| `CTX-DETF-002` | `supported` | 국내 ETF | 앞 결과 목록을 다음 필터에 전달 |
| `CTX-AMB-001` | `supported` | 국내 ETF | 복수 후보를 임의로 하나 선택하지 않음 |
| `CTX-CROSS-001` | `limited` | 국내·해외 ETF | 운용사 명칭 정규화 범위 |
| `MIS-OETF-001` | `limited` | 해외 ETF | 종가·NAV 동시 존재·동일 기준일일 때만 계산 |
| `MIS-DETF-001` | `limited` | 국내 ETF | 센티넬 의심값 제외로 10개보다 적을 수 있음 |
| `MIS-BOND-001` | `limited` | 국내 채권 | 결측 등급을 다른 채권에서 대입하지 않음 |
| `MIS-FUND-001` | `requires_additional_data` | 공모펀드 | 2026-07-11 수익률 성과 기준일 필요 |
| `AMB-RET-001` | `supported` | ETF·공모펀드 | 상품군별 동질 지표만 분리 비교 |
| `AMB-SIM-001` | `supported` | 상품 미지정 | 앵커가 없으면 추측 대신 제한 응답 |
| `AMB-AUM-001` | `supported` | 국내·해외 ETF | 통화 정보에 따라 환산 또는 분리 |
| `AMB-NAME-001` | `supported` | 전체 상품군 | 동명 후보를 모두 표시 |
| `UNS-FCAST-001` | `unsupported` | ETF | 미래 확정 수익률 예측 금지 |
| `UNS-PERS-001` | `unsupported` | 전체 상품군 | 개인화 전재산 투자 추천 금지 |
| `UNS-RT-001` | `unsupported` | ETF | 실시간 시세 미제공 |
| `UNS-ORDER-001` | `unsupported` | ETF | 주문 실행 권한 없음 |
| `DOC-FUND-001` | `requires_additional_data` | 공모펀드 | 기준일 이하 공식 문서 코퍼스 필요 |
| `REL-OETF-001` | `requires_additional_data` | 해외 ETF | 기업·증권 식별자와 산업·지역 분류 필요 |
| `REL-THEME-001` | `requires_additional_data` | 국내·해외 ETF | 6개월 관계 이력과 게시일 필요 |
| `REL-CORP-001` | `requires_additional_data` | 국내·해외 ETF | 자회사·상장·구성종목·위험문서 결합 필요 |
| `UNS-GRADE-001` | `unsupported` | 국내 채권 | 온톨로지 등급 어휘 위반 |
| `UNS-ENTITY-001` | `unsupported` | 전체 상품군 | 검증된 관계 없음 |
| `UNS-PRODUCT-001` | `unsupported` | 국내 ETF | 기준일 정확 상품 부재 |

## 5. 비공개 35문항 질문 가족 매핑

| 발표된 질문 가족 | 처리 원칙 | 회귀 대표 |
| --- | --- | --- |
| 단일 상품군 조회·필터·순위 | 주최 측 필드만 사용하고 결측은 unknown으로 제외·표시 | `LKP-*`, `FLT-*`, `RANK-*` |
| 여러 상품군 교차·비교 | 동질 지표·단위·기준일일 때만 합산·순위화 | `CALC-CROSS-*`, `CMP-*` |
| 구성종목 → 상품 | KRX는 연결 범위, SEC는 bounded scope, 공모펀드는 `requires_data` | `REL-HOLD-*`, `REL-OETF-001` |
| 섹터 → 상품 | 종목 단위 공식 섹터 분류가 없으면 추정하지 않음 | `REL-HOLD-004` |
| 관계·문서·동향 | 기관·기업·테마 관계와 공식 문서 스팬을 분리 검증 | `DOC-FUND-001`, `REL-THEME-001`, `REL-CORP-001` |
| 여러 문장·지시어 | 전체 요청이 문맥을 소유하고 중간 결과 ID를 후행 문장에 바인딩 | `CTX-*`, `REL-MGR-001` |
| 답변 불가 | 유효한 어휘·기준일 엔티티·근거 관계를 확인하고 없으면 제한·거절 | `UNS-*` |

주최 측의 답변 불가 5문항의 정확한 문장은 비공개이므로, 상기 표는
문장 예측이 아니라 판정 유형을 검증한다. 내부 `unsupported` 7개는 공식 5개와
개수를 맞추기 위한 목록이 아니다.

## 6. 주최 측 결측값 절대 우선

`aum`, `return`, `price`, `nav`, `risk`의 주최 측 값이 `null`이거나 빈 문자열이면,
같은 상품의 외부 값이 있어도 해당 상품 사실을 채우지 않는다. 필터·순위에서
제외하거나 확인 불가로 표시한다. 숫자 `0`은 결측이 아니며 해당 지표에서
유효한 값일 수 있으므로 별도 규칙으로 검증한다.

## 7. 변경 통제

- 상태 변경은 승인 원천·식별자 교차표·커버리지 수치가 변했을 때만 한다.
- 부분 원천을 추가했다고 `closed_world_scope`를 선언하지 않는다.
- 주최 측 결측값을 외부값으로 보완하는 정책 변경은 별도 ADR과 사용자 승인 없이 허용하지 않는다.

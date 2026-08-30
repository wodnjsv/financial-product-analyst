# VectorDB 공식 문서 코퍼스 최소 범위 설계

**Date:** 2026-08-29

**Status:** Approved; Phase 0 foundation implemented; official-file manifest pending

**Related:** [Financial Product Analyst Planning Harness](../HARNESS.md), [Question Capability Contract Normalization](2026-08-29-question-capability-contract-normalization-design.md), [Stage 03 Question Capability Analysis](2026-08-29-stage03-question-capability-analysis.md), [ADR-0014](../decisions/ADR-0014-use-bounded-official-source-snapshots.md), [ADR-0018](../decisions/ADR-0018-keep-minimal-ontology-with-canonical-multi-role-products.md), [ADR-0020](../decisions/ADR-0020-treat-organizer-missingness-as-authoritative.md), [ADR-0021](../decisions/ADR-0021-use-three-tier-official-document-sources.md)

## 1. 결정 요약

VectorDB는 공식 문서에서 질문에 필요한 근거 문단을 찾는 후보 검색 인덱스로 사용한다. 상품 사실, 관계, 계산, 기준일 판정의 권위 원장으로 사용하지 않는다.

초기 코퍼스는 다음 원칙을 따른다.

1. 주최 측 마스터의 전체 상품을 문서 커버리지 원장에서 추적한다.
2. 실제 Vector 색인은 문서형 Claim이 필요한 국내 ETF, 해외 ETF, 공모펀드와 승인된 정책형 펀드·지수 문서에 한정한다.
3. 문서 전체가 아니라 Claim별 승인 섹션만 색인한다.
4. 상품별 활성 상품 문서는 원칙적으로 하나만 선택하고, 지수 방법론은 상품이 아닌 고유 지수 단위로 하나만 선택한다.
5. 구조화 수치, 보유종목, 관계, 현재 상태는 PostgreSQL 또는 Graph에 남긴다.
6. 검색 결과는 원문 위치와 PostgreSQL EvidenceRecord에 결합되기 전에는 답변 Claim을 지지하지 않는다.
7. 원천은 감독기관 공시, 지수사업자·정부·공공기관 원문, 거래소·협회 공식 자료의 세 권위 등급으로 제한한다.
8. 변경 공시는 식별·처리 이력을 원장에 남기되, 승인 Claim을 실제로 변경한 최소 구절만 Vector 색인한다.

이 설계는 평가 질문 직결 문서를 필수로 넣고 같은 문서의 필요한 핵심 섹션만 얇게 확장하는 방향이다. 문서 종류와 섹션을 나중의 가능성만으로 넓히지 않는다.

## 2. 문제와 목표

### 2.1 문제

52개 질문 중 Vector 검색이 직접 필요한 현재 사례는 다음 세 가지다.

| Case | 필요한 문서 Claim |
| --- | --- |
| DOC-FUND-001 | 펀드·정책기구의 구조, 투자전략, 공식 동향·변경 |
| REL-THEME-001 | 테마 정의, 지수 방법론, 기간이 있는 상품·테마 연결 근거 |
| REL-CORP-001 | 선택된 ETF의 상품별 공식 위험요인 |

문서 전체를 무차별 색인하면 반복 법률 문구, 수치표, 부록, 다른 상품의 유사 문장이 검색 결과를 오염시킨다. 반대로 알려진 세 질문에 등장하는 상품만 수집하면 비공개 평가 질문의 상품을 놓칠 수 있다.

### 2.2 목표

- 전체 상품에 대해 문서 지원 가능 여부를 명시적으로 관리한다.
- 필요한 공식 문서와 섹션만 색인해 검색 정밀도와 증거 재현성을 높인다.
- 같은 상품, 올바른 문서 버전, 컷오프 이전 공식 원문을 우선한다.
- Vector 후보가 Graph 관계나 문서 Claim으로 잘못 승격되지 않게 한다.
- 문서·청크 수가 질문 요구사항 없이 계속 증가하지 않게 한다.

### 2.3 비목표

- VectorDB를 상품 마스터나 Evidence 원장으로 사용하는 것
- 문서에서 AUM, NAV, 가격, 수익률, 보수율을 추출해 주최 측 값을 대체하는 것
- ETF 보유종목과 비중을 문서 의미 검색으로 판정하는 것
- 기업 지배관계, 상품-지수 관계, 테마 관계를 임베딩 유사도로 생성하는 것
- 뉴스, 블로그, 검색 결과 요약, LLM 요약·번역을 Claim 근거로 사용하는 것
- 이번 설계에서 Vector 제품, 임베딩 모델, OCR 엔진을 확정하는 것
- 국내채권 약정·상환 문서 코퍼스를 선제 구축하는 것

## 3. 가정, 제약과 성공 조건

### 3.1 가정

- 평가 데이터 컷오프는 2026-08-24다.
- 비공개 35문항의 정확한 문장은 알 수 없으므로 알려진 상품명에 과적합하지 않는다.
- 주최 측 마스터에 있는 상품 식별자가 외부 공식 문서 결합의 출발점이다.
- 원본 공식 파일은 객체 저장소에 불변 보존할 수 있고, PostgreSQL이 문서·근거 계보를 보유한다.
- Graph와 Vector는 같은 dataset_version의 PostgreSQL 원장으로 되돌아올 수 있다.

### 3.2 하드 제약

- published_at, available_at, effective date가 컷오프 조건을 통과하지 못한 문서는 경쟁 평가 Claim에 사용할 수 없다.
- 주최 측 결측이나 placeholder를 외부 문서 값으로 덮어쓰지 않는다.
- 정확한 상품·지수·정책 Entity 결합 전에는 문서 검색 결과를 Claim 후보로 만들지 않는다.
- 검색용 접두 문맥이나 번역문은 Evidence 원문이 아니다.
- 필수 원문 span을 찾지 못하면 partial, limitation 또는 abstention으로 판정한다.
- 임베딩 사용은 Harness의 선택적 모델 제한을 따르며 별도 벤치마크와 ADR 없이 모델을 확정하지 않는다.

### 3.3 검증 가능한 성공 조건

1. 주최 측 마스터의 모든 상품에 문서 커버리지 상태가 하나 이상 존재한다.
2. 알려진 세 문서형 질문의 gold 근거 span이 Claim별 Top 5 후보 안에 들어간다.
3. 컷오프 이후 문서, 비공식 문서, 다른 상품 문서가 releaseable Evidence가 되는 사례가 0건이다.
4. 의미 유사성만으로 associatedWithTheme 또는 hasRiskFactor 관계를 생성하는 사례가 0건이다.
5. 선택된 모든 청크가 document_id, entity_id, 문서 버전, 원문 위치와 체크섬으로 재현된다.
6. 상품별 청크 예산 초과가 자동 절단이나 무제한 적재로 이어지지 않고 검토 상태로 전환된다.
7. 초기 색인에 정량 시계열, 보유종목 전체표, 일반 뉴스, LLM 생성 요약이 포함되지 않는다.

## 4. 검토한 접근과 선택

### 4.1 문서 전체 색인

구축은 단순하지만 반복 문구와 수치표가 검색을 오염시키고 상품별 청크 수를 통제하기 어렵다. 선택하지 않는다.

### 4.2 Claim 중심 섹션 색인

질문이 요구하는 Claim 유형으로 문서와 섹션을 제한한다. 검색 정확도, 범위 통제, Evidence 재현성이 가장 좋다. 이 방식을 선택한다.

### 4.3 핵심·보조 이중 인덱스

회수율을 높일 수 있지만 현재 세 문서형 질문에 비해 운영 복잡도가 크다. 단일 최소 인덱스의 평가 실패가 확인될 때만 새 설계로 검토한다.

### 4.4 모든 공식 변경 공시 색인

변경 이력 누락은 줄지만 주소·판매사·보수·세무·운용인력과 같은 비대상 변경이 반복 유입돼 코퍼스와 검색 잡음을 함께 키운다. 변경 공시의 식별·처리 이력은 보존하되 승인 Claim에 영향을 주는 본문만 색인하는 방식을 선택한다.

### 4.5 현재 대표 문서만 색인

가장 작지만 기간이 있는 테마·정책 변경 질문을 재현할 수 없다. 대표 문서에 더해 질문 기간에 적용된 Claim 영향 변경 공시만 추가한다.

## 5. 전체 상품 커버리지와 실제 색인 범위

전체 상품 범위는 모든 상품의 모든 문서를 색인한다는 뜻이 아니다. 전체 상품은 PostgreSQL 커버리지 원장에서 추적하고, Vector 적재는 아래 범위만 허용한다.

| 대상 | 커버리지 원장 | 초기 Vector 적재 |
| --- | --- | --- |
| 국내 ETF 전체 | 필수 | 승인 상품 문서의 필수 섹션, 필요한 고유 지수 방법론 |
| 해외 ETF 전체 | 필수 | 승인 상품 문서의 필수 섹션, 필요한 고유 지수 방법론 |
| 공모펀드 전체 | 필수 | 승인 상품 문서의 구조·전략·주요 위험 섹션 |
| 국내채권 전체 | 필수 | 없음; not_applicable_current_scope |
| 승인 정책형 펀드·정책기구 | 필수 | 구조·전략 문서와 질문 기간에 필요한 공식 변경·현황 문서 |
| 지수 | 연결된 상품 기준 | 고유 index_id당 유효 방법론 하나와 필요한 기간의 변경 공지 |

상품과 지수가 다대일이면 지수 방법론을 상품별로 복제하지 않는다. PostgreSQL과 Graph가 여러 상품을 같은 index_id와 document_id에 연결한다.

## 6. Claim별 필수 문서와 섹션

### 6.1 펀드·정책기구 구조와 전략

| Claim | 필수 내용 |
| --- | --- |
| structure | 법적·운용 구조, 재원과 투자기구 구성, 운용 주체, 하위 기구·클래스 |
| investment_strategy | 투자목적, 주요 투자대상, 자산배분, 선정 기준, 운용 방식 |
| official_trend_or_update | 출시·조성 현황, 공식 일정, 전략·구조 변경과 적용일 |
| publisher_provenance | 발행기관, 기관 역할, 게시일, 문서 버전 |

공모펀드는 감독기관 공시시스템에서 확인한 최신 유효 집합투자증권 투자설명서를 사용한다. 공시 안의 간이·요약 영역이 필요한 구조·전략·위험 Claim을 충족하면 그 영역을 우선하고, 부족한 Claim만 같은 유효 공시의 전체 영역에서 보충한다. 요약본과 전체본을 중복 색인하지 않는다.

정책형 펀드는 공식 기본계획 하나를 기준 문서로 선택한다. 동향 질문에 필요한 기간의 공식 변경·현황 문서만 추가한다. 일반 뉴스와 전망 보고서는 제외한다.

### 6.2 테마와 지수 방법론

| Claim | 필수 내용 |
| --- | --- |
| theme_definition | 테마의 공식 정의, 포함 산업·기술·사업 기준 |
| selection_rules | 유니버스, 편입·제외 조건 |
| weighting_and_rebalancing | 가중 방식, 리밸런싱 주기와 적용일 |
| relation_history | 방법론·상품 전략의 공식 변경, valid_from과 valid_to |

상품명이나 문서 문장의 의미 유사성만으로 테마 관계를 만들지 않는다. 상품-지수 식별 관계와 지수 방법론의 공식 테마 정의가 모두 검증돼야 한다.

최근 6개월은 평가 컷오프 2026-08-24를 기준으로 2026-02-24부터 2026-08-24까지의 달력 기간으로 계산한다. 기존 질문 분석 문서 REL-THEME-001의 WINDOW_END_2026_07_11 표기는 현재 컷오프와 충돌하는 과거 literal이므로 구현 전에 2026-08-24 기준 규칙으로 정정해야 한다.

### 6.3 상품별 위험요인

| Claim | 필수 내용 |
| --- | --- |
| product_risk_factor | Principal 또는 주요 투자위험 |
| concentration_risk | 산업·테마·국가·종목 집중위험 |
| market_and_liquidity_risk | 시장가격·유동성·거래 위험 |
| tracking_and_index_risk | 추적오차, 지수 산출·변경 위험 |
| currency_risk | 환율 변동과 환헤지 한계 |
| derivatives_and_counterparty_risk | 파생상품, 레버리지, 거래상대방 위험 |

일반적인 투자 위험 안내보다 해당 상품 문서의 주요 위험 섹션을 우선한다. 선택된 ETF의 정확한 product_id와 유효 문서 버전에 결합되지 않은 위험 문단은 사용하지 않는다.

## 7. 문서 원천 우선순위

원천은 다음 세 권위 등급으로 제한한다. 등급 밖 자료는 탐색 힌트로도 자동 수집하지 않으며, 승인 원천에서 문서를 찾지 못하면 하위 권위 자료로 대체하지 않고 커버리지 제한을 기록한다.

| 등급 | 허용 원천 | 소유 Claim과 사용 원칙 |
| --- | --- | --- |
| 1순위 | 감독기관·감독당국의 법정 공시시스템 | 제출·접수된 상품 구조, 투자목적·전략, 주요 위험과 유효 정정·보충 문서 |
| 2순위 | 지수사업자, 주무부처, 정책 시행 공공기관의 공식 원문 | 지수 방법론과 변경, 정책형 펀드의 구조·재원·운영·공식 현황 |
| 3순위 | 거래소·금융투자협회 등 공식 협회 공시 | 거래소·협회가 소유하는 상장·식별·상품 변경 사실, 문서 발견과 교차검증 |

운용사·발행사 홈페이지, 판매사 자료, 뉴스, 블로그, 검색 결과·요약, 자동 생성 요약·번역은 색인과 Evidence 대상이 아니다. 발행사가 제출한 문서라도 감독기관 공시시스템에서 수집·보존하면 1순위 공시로 취급한다.

### 7.1 상품군별 대표 문서

| 대상 | 필수 대표 문서 | 조건부 추가 | Vector 적재 범위 |
| --- | --- | --- | --- |
| 국내 ETF | 감독기관 공시시스템의 최신 유효 집합투자증권 투자설명서 | 거래소의 Claim 영향 상품 변경 공시 | 투자목적·전략, 추종지수, 주요 위험, 필요한 환헤지·파생상품 구절 |
| 해외 ETF | 관할 감독기관의 최신 유효 Summary Prospectus 또는 동등 문서; 미국은 원칙적으로 SEC 497K | 유효 보충 공시, 부족한 Claim의 감독기관 제출 Full Prospectus | 투자목적·주요 전략, 추종지수, Principal Risks |
| 공모펀드 | 감독기관 공시시스템의 최신 유효 집합투자증권 투자설명서 | 같은 공식 공시체계의 유효 정정·보충 문서 | 구조, 투자목적·전략, 주요 투자대상, 주요 위험 |
| 지수 | 지수사업자 공식 Methodology | 질문 기간에 적용된 공식 방법론 변경 공지 | 테마 정의, 유니버스, 편입·제외, 가중, 리밸런싱 |
| 정책형 펀드·정책기구 | 주무부처·시행 공공기관의 공식 기본계획 | 질문 기간의 공식 변경계획·현황자료 | 법적·운용 구조, 재원, 전략, Claim 영향 현황·변경 |
| 국내채권 | 없음 | 없음 | 적재하지 않고 `not_applicable_current_scope` 기록 |

3순위 원천은 1·2순위가 소유한 Claim을 덮어쓰지 않는다. 거래소·협회의 공식 정보는 그 기관이 소유하는 사실 또는 상위 원천 문서의 발견·식별 검증에만 사용한다.

## 8. 문서 승인 게이트와 커버리지 상태

### 8.1 승인 게이트

문서는 다음 조건을 모두 통과해야 Vector 후보가 될 수 있다.

1. 주최 측 product_id, 승인 entity_id 또는 index_id와 정확히 결합된다.
2. 발행자가 Claim 유형에 승인된 공식 역할을 가진다.
3. published_at과 available_at이 컷오프를 통과한다.
4. effective date와 문서 버전을 확인하거나 제한 상태를 명시할 수 있다.
5. 개정본과 구버전 관계를 보존할 수 있다.
6. 페이지·절·원문 offset을 재현할 수 있다.
7. 원본 객체 체크섬과 추출 텍스트 체크섬을 보존한다.
8. 원문 추출 결과가 인용에 충분하다.

텍스트 레이어가 없는 스캔 문서는 OCR 결과만으로 Claim eligible이 되지 않는다. 공식 HTML·텍스트본 또는 원본 대조를 통해 span을 재현할 수 없으면 unreadable_document로 처리한다. OCR 엔진별 신뢰도 숫자를 공통 사실처럼 비교하지 않는다.

### 8.2 커버리지 상태

모든 대상 상품·지수·정책 Entity는 required_document_role별로 다음 상태 중 하나를 가진다.

| 상태 | 의미 |
| --- | --- |
| indexed | 승인 문서와 필수 섹션이 색인됨 |
| document_not_found | 승인 원천에서 문서를 찾지 못함 |
| ambiguous_entity_binding | 상품·지수·정책 Entity 결합이 유일하지 않음 |
| after_cutoff_only | 확인된 문서가 컷오프 이후에만 공개됨 |
| version_unknown | 적용 버전이나 효력 시점을 검증할 수 없음 |
| unreadable_document | 원문 span을 재현할 수 없음 |
| publisher_not_approved | 공식 역할을 입증하지 못함 |
| section_missing | 문서는 있으나 필수 Claim 섹션이 없음 |
| not_applicable_current_scope | 현재 질문 세트에서 문서 Claim이 필요하지 않음 |
| review_required_chunk_budget | 필수 후보가 상품별 청크 예산을 넘어 검토 필요 |

빈 검색 결과를 문서 부재나 Claim 부재로 바로 해석하지 않는다. 커버리지 상태와 완료된 원천 범위가 있어야 부재 제한을 만들 수 있다.

## 9. 섹션 허용 목록과 제외 목록

### 9.1 초기 필수

- legal_structure
- investment_objective
- investment_strategy
- index_methodology
- theme_definition
- selection_rules
- rebalancing
- risk_factor
- official_update
- change_history

### 9.2 조건부

- currency_hedge: 전략 또는 위험 Claim에 필요한 경우
- derivatives_leverage: 전략 또는 위험 Claim에 필요한 경우
- governance: 정책형 펀드 구조 Claim에 필요한 경우

`official_update`와 `change_history`는 공시 문서라는 이유만으로 허용하지 않는다. 상품·지수 식별, 투자목적·전략·주요 투자대상, 추종지수·테마·선정·가중·리밸런싱, 주요 위험·환헤지·파생상품, 법적·운용 구조, 정책형 펀드의 재원·운영·공식 현황 중 하나를 실제로 변경한 경우에만 허용한다.

### 9.3 초기 제외

- fees_policy
- distribution_redemption
- taxation
- accounting_policy
- general_legal_notice
- full_holdings_table
- historical_performance_table
- 전체 재무제표와 부록
- 일반 시장전망과 운용자 코멘터리
- 주소·연락처·판매사·운용인력만의 변경
- 보수·세무·회계·분배·환매만의 변경
- AUM·NAV·가격·수익률·일반 보유종목 변동
- 오탈자 정정과 최신 대표 문서에 완전히 반영된 중복 변경문구

제외 영역이 새 질문에 필요해지면 먼저 Document Claim, Evidence 요구사항과 question family를 추가해야 한다. 문서가 이미 존재한다는 이유만으로 허용 목록을 넓히지 않는다.

## 10. 문서와 청크 예산

### 10.1 상품별 문서 예산

- 활성 상품설명 문서: 원칙적으로 하나
- 지수 방법론: 고유 index_id당 하나
- 과거 문서·변경 공지: 질문의 명시 기간에 필요한 것만
- 간이·요약본이 Claim을 충족하면 일반·전체 문서를 추가하지 않음
- 같은 유효 공시의 HTML·PDF·첨부본처럼 내용이 같은 표현 형식을 중복 색인하지 않음

### 10.2 변경 공시 예산

- 승인 원천에서 대상 Entity의 변경 공시 후보를 발견하면 document_id, source, published_at, effective date, 영향 Entity와 색인·제외 disposition을 manifest 또는 커버리지 원장에 기록
- 승인 Claim에 영향이 없는 변경 공시는 원장 이력만 남기고 Vector에 적재하지 않음
- 적재 대상 변경 공시도 전체 문서가 아니라 변경 Claim, 변경 전·후 내용, 효력일, 적용 대상과 해석에 필요한 최소 사유 구절만 청킹
- 현재 대표 문서에 동일 내용이 완전히 반영됐더라도 질문의 명시 기간에 변경 사건 자체가 필요하면 change_history 청크를 유지
- 기간 질문과 연결되지 않는 과거 변경 공지를 보존 가능성만으로 일괄 적재하지 않음

### 10.3 청크 예산

- 상품별 목표: 8~15개
- 상품별 소프트 한도: 20개
- 한도를 넘으면 자동 절단하지 않고 review_required_chunk_budget으로 전환
- 지수 방법론은 index_id 기준으로 별도 계산
- 필수 위험요인을 단순 개수 제한으로 삭제하지 않음
- 같은 문서 안의 완전 중복 문단은 체크섬으로 제거
- 상품 간 같은 문구는 product_id별 Evidence 결합을 보존하기 위해 임의 병합하지 않음

청크 예산은 범위 경보이지 Evidence 삭제 규칙이 아니다. 반복 상용문구를 제거하고도 필수 섹션이 한도를 넘는 상품은 수동 또는 규칙 검토를 거쳐 허용 범위를 명시한다.

## 11. 청킹 규칙

문서 구조를 먼저 보존한 뒤 섹션 단위로 나눈다.

1. 문서 버전과 페이지 순서를 고정한다.
2. 장·절 제목과 제목 계층을 인식한다.
3. 섹션 유형을 허용 목록으로 분류한다.
4. 문단, 목록, 표의 의미 경계를 보존한다.
5. 긴 섹션만 같은 절 안에서 재분할한다.
6. 원문 locator와 체크섬을 붙인다.

기본 목표는 300~800 토큰이다. 겹침은 같은 절 안에서만 50~100 토큰을 허용한다. 다른 상품, 다른 문서 버전, 다른 섹션 유형을 하나의 청크에 섞지 않는다.

위험요인 목록은 가능한 한 위험 항목별로 나눈다. 표는 제목과 열 이름을 함께 보존할 수 있고 Claim에 필요한 서술형 규칙이 있을 때만 색인한다. 정량표는 PostgreSQL 대상으로 분리한다.

검색용 embedding text는 canonical entity name, document type, section path, original text를 결합할 수 있다. Evidence text는 original text와 원문 locator만 사용하며 검색용 접두 문맥을 인용하지 않는다.

## 12. 필수 메타데이터

권위 메타데이터는 PostgreSQL에 저장하고 VectorDB에는 필터에 필요한 복사본만 둔다.

| 영역 | 필수 필드 |
| --- | --- |
| 식별 | chunk_id, document_id, source_object_id |
| 대상 | product_id, entity_id, index_id |
| 분류 | document_type, section_type, claim_types |
| 출처 | publisher_id, publisher_role, jurisdiction, source_locator |
| 시간 | published_at, available_at, effective_from, effective_to |
| 버전 | document_version, amends_document_id, dataset_version, cutoff_date |
| 위치 | page_start, page_end, section_path, character_start, character_end |
| 원문 | original_language, original_text_hash, content_checksum |
| 품질 | extraction_method, cutoff_eligible, coverage_status |

Vector metadata는 authoritative fact가 아니다. Vector 레코드가 삭제·재생성돼도 PostgreSQL document_id와 chunk_id로 동일한 Evidence 후보를 재구축할 수 있어야 한다.

## 13. 검색과 Evidence 승격 흐름

1. Keyword와 PostgreSQL로 상품·지수·정책 Entity를 먼저 식별한다.
2. QueryPlan의 Document Claim 유형을 승인 section_type과 document_type으로 컴파일한다.
3. entity_id, dataset_version, cutoff, publisher_role, section_type으로 후보를 제한한다.
4. 제한된 집합에서 Keyword와 Vector 검색을 병행한다.
5. 공식성, 동일 Entity, 버전, 적용일, section_type을 결정론적으로 재정렬한다.
6. 원본 객체에서 page, section, character span과 텍스트 체크섬을 다시 확인한다.
7. 검증된 span만 PostgreSQL EvidenceRecord와 ClaimSupport 후보로 만든다.
8. 관계 Claim이면 승인 predicate와 유효기간을 검증한 뒤 Graph projection을 만든다.
9. Verifier와 Claim Gate를 통과한 Claim만 Renderer에 전달한다.

Vector 검색의 Top K는 최종 답변 수가 아니라 근거 후보 수다. 후보가 많아도 동일 Entity·공식성·시간 검사를 통과하지 못하면 사용하지 않는다.

## 14. 저장소 책임 경계

| 정보 | 권위 저장소 |
| --- | --- |
| 원본 문서 객체와 체크섬 | Object Storage |
| 문서 ID, 버전, 날짜, 발행자, 커버리지 | PostgreSQL |
| Evidence span, ClaimSupport, 검증 결과 | PostgreSQL |
| 상품·지수·기업·테마 관계 | PostgreSQL 원장 + Graph projection |
| 문서 청크 후보 검색 | VectorDB + Keyword index |
| AUM, NAV, 가격, 수익률, 보수, 상태 | PostgreSQL |
| 보유종목과 비중 | PostgreSQL + 필요한 Graph projection |

VectorDB 장애나 인덱스 재구축 중에는 구조화 질문을 계속 처리한다. 문서 Claim이 필요한 질문만 limitation 또는 abstention으로 축소한다.

## 15. 실패와 안전 처리

- 문서 없음: document_not_found 근거와 검색 범위를 반환
- 상품 결합 모호: ambiguous_entity_binding으로 중단
- 컷오프 이후 문서만 존재: after_cutoff_only로 제한
- 버전 불명: 현재 사실로 표현하지 않음
- 필수 섹션 없음: section_missing으로 Claim 제외
- OCR 재현 실패: unreadable_document로 Claim 제외
- Vector 후보 없음: Keyword 후보와 커버리지 상태를 확인한 뒤 limitation
- Vector 후보가 다른 상품: 즉시 제외하고 자동 상품 치환 금지
- Graph 관계 근거 부족: 관계를 생성하지 않고 해당 하위 질문 abstain
- 검색 지연: 문서 하위 질문만 실패 처리하고 구조화 결과를 보존

## 16. 수집·색인 단계

### Phase 0: 소규모 검증

DOC-FUND-001, REL-THEME-001, REL-CORP-001의 정확한 Entity와 공식 문서로 문서 선택, 섹션 분류, 청킹, 검색, Evidence 승격을 종단간 검증한다.

### Phase 1: 국내 ETF

국내 ETF 전체에 감독기관 공시 대표 문서 정책을 적용한다. 거래소 변경 공시는 Claim 영향 규칙을 통과한 최소 구절만 추가하고, 고유 지수별 방법론은 한 번만 수집한다.

### Phase 2: 공모펀드

공모펀드 전체에 감독기관 공시의 간이·요약 영역 우선 정책을 적용하고, 필수 Claim이 부족할 때만 같은 유효 공시의 전체 영역에서 보충한다.

### Phase 3: 해외 ETF

해외 ETF 전체에 관할 감독기관의 Summary Prospectus 우선 정책을 적용한다. 관할별 감독기관 원천과 상품 ID 결합이 검증되지 않으면 운용사 홈페이지로 대체하지 않는다.

### Phase 4: 갭 보충

검색 평가에서 실패한 Claim만 추가 문서 또는 섹션으로 보충한다. 새 문서 유형을 일괄 추가하지 않는다.

## 17. 검색 품질 평가

### 17.1 양성 사례

- 정확한 정책형 펀드의 구조·전략·공식 동향 span
- 정확한 지수의 테마 정의와 기간 내 변경 span
- Graph로 선택된 정확한 ETF의 상품별 위험요인 span

### 17.2 음성 사례

- 이름이 비슷한 다른 상품
- 같은 운용사의 다른 상품 위험 문단
- 상품명에 테마 단어만 포함된 경우
- 컷오프 이후 문서
- 과거 구버전
- 비공식 기사·검색 요약
- 일반적인 투자위험 문단
- LLM 생성 요약·번역문

### 17.3 합격 기준

| 검사 | 기준 |
| --- | --- |
| Known gold span recall | Claim별 Top 5 안에 정답 span |
| Entity purity | releaseable Evidence의 entity_id 불일치 0건 |
| Source purity | 비공식 출처 release 0건 |
| Temporal purity | 컷오프·효력 위반 release 0건 |
| Version purity | 구버전을 현재 문서로 release 0건 |
| Relation safety | 의미 유사성만으로 관계 생성 0건 |
| Reproducibility | 모든 releaseable span의 원문 round-trip 성공 |
| Coverage accounting | 대상 상품·지수의 상태 누락 0건 |
| Scope budget | 초과 상품이 자동 무제한 적재되지 않음 |

Top 5 recall은 초기 최소 기준이다. 실제 문서 평가셋의 크기와 난이도가 확보되면 precision, recall, latency 기준을 별도 벤치마크 ADR에서 확정한다.

## 18. 새 문서·섹션 추가 조건

다음 네 조건을 모두 만족해야 범위를 넓힐 수 있다.

1. 지원할 question family가 등록돼 있다.
2. 필요한 Document Claim과 Evidence 필드가 정의돼 있다.
3. 현재 승인 코퍼스로 Claim을 지원할 수 없다는 평가 실패가 있다.
4. 새 문서의 공식 출처, Entity 결합, 시간 계보를 검증할 수 있다.

나중에 유용할 가능성, 문서의 존재, 검색 결과 수 확대, 다른 프로젝트의 관행은 추가 사유가 아니다. 범위 변경은 이 설계를 조용히 수정하지 않고 새 ADR 또는 후속 설계에 기록한다.

## 19. 기존 Stage 03/04 설계와의 정합성

- PostgreSQL은 상품 사실과 Evidence의 권위 원장이다.
- Graph는 승인된 관계만 투영한다.
- Vector는 공식 문서 후보를 찾고 원문 span 검증 전에는 Claim을 지지하지 않는다.
- organizer missingness는 외부 문서로 덮어쓰지 않는다.
- dataset_version은 PostgreSQL, Graph, Vector에서 같아야 한다.
- 문서 수집은 immutable source snapshot과 cutoff 검사를 따른다.
- current DB execution이 not_run인 질문을 문서 적재만으로 supported로 바꾸지 않는다.

확인된 충돌은 REL-THEME-001에 남은 2026-07-11 기간 종료 literal이다. 현재 승인 컷오프 2026-08-24와 일치하도록 질문 계약 정규화 단계에서 수정해야 한다.

## 20. 구현 전 남은 승인 경계

이 문서 승인만으로 다음 선택은 확정되지 않는다.

- VectorDB 제품과 물리 인덱스 구조
- 한국어·영어 임베딩 모델
- Hybrid search와 재정렬 알고리즘
- OCR 엔진과 문서 파서
- 승인 원천별 실제 상품·지수 문서 manifest와 수집 방식·이용조건
- 상품별 예외 한도 승인 절차

각 선택은 Phase 0 평가셋으로 최소 두 대안을 비교하고 비용, 검색 정확도, 지연시간, 컷오프 재현성을 근거로 결정한다. 구현은 별도 계획과 사용자 승인을 받은 뒤 시작한다.

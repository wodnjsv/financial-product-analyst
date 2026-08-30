# 온톨로지 기반 Intent Resolver 설계

**Date:** 2026-08-31

**Status:** Approved design; implementation not started

**Scope:** Stage 06 Phase 1 Intent Resolution

**Decision:** [ADR-0022](../decisions/ADR-0022-use-ontology-grounded-intent-resolution.md)

**Related:** [Planning Harness](../HARNESS.md),
[Runtime Contracts](../architecture/RUNTIME_CONTRACTS.md),
[Financial Ontology Architecture](../architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md),
[Failure and Disposition Policy](../architecture/FAILURE_AND_DISPOSITION_POLICY.md),
[Question Capability Contract Normalization](2026-08-29-question-capability-contract-normalization-design.md),
[Core Evaluation Set](core-evaluation-set.md)

## 1. 결정 요약

Intent Resolver의 목적은 질문에 가장 그럴듯한 라벨을 붙이는 것이 아니다.
질문을 잘못 해석해 다른 데이터·관계·계산·근거·정책 경로를 선택하는 것을
실행 전에 차단하는 것이다.

정상 경로는 다음과 같다.

    RequestContext
      -> 결정론적 정규화·리터럴 추출
      -> SemanticQueryCatalog 기반 후보 생성
      -> 요청별 ResolverView
      -> HyperCLOVA X 구조화 호출 1회
      -> IntentResolutionDraft
      -> 결정론적 스키마·온톨로지·문맥 검증
      -> ValidatedIntentResolution
      -> Phase 2 QueryPlan Compiler
      -> 기존 QueryPlan

이 설계는 기존 QueryPlan과 downstream 계약을 변경하지 않는다. 모델의 역할만
QueryPlan 직접 생성에서 제한된 의미 프레임 추출로 좁힌다.

## 2. 목표, 비목표, 제약

### 2.1 목표

1. 국내채권, 국내 ETF, 해외 ETF, 공모펀드 질문의 상품군과 경제적 타입을
   분리해 해석한다.
2. lookup, screen, rank, compare, aggregate, calculate, similar, explain의
   여덟 액션만 사용한다.
3. 한국어 복합 문장, 생략, 지시어, 교정, 복수 참조를 타입화된 프레임과
   문맥 링크로 표현한다.
4. 속성·지표·관계·문서 주제를 기존 온톨로지와 의미 계약의 등록 ID로
   grounding한다.
5. 미등록 ID, 잘못된 관계 타입, 잘못된 카디널리티, 순환 의존성을 실행 전에
   거부한다.
6. 조합 OOD, 어휘 OOD, 도메인 OOD, 문맥 OOD를 구분한다.
7. 후보 생성, 모델 추론, 검증, 이후 QueryPlan 컴파일 정확도를 각각 측정한다.
8. 같은 입력·카탈로그·데이터 버전에 대해 후보 생성과 검증 결과를 재현한다.

### 2.2 비목표

- QueryPlan 아키타입, 실행 프리미티브, Capability route 확정
- QueryPlan Compiler 구현
- Orchestrator와 ExecutionGraph 구현
- SQL, SPARQL, 함수 또는 DB 컬럼 생성
- 필터·순위·집계·계산 실행
- 답변 생성과 AnswerDisposition 최종 판정
- 요청 간 대화 기억
- 자유형 Agent planning
- 개인화 투자자문, 주문 실행, 미래 수익률 예측 지원

### 2.3 고정 제약

- 평가 경로의 의도 분석은 HyperCLOVA X를 사용한다.
- 정상 Intent Resolver 모델 호출은 한 번이다.
- 요청 전체 LLM 보정권은 Intent Resolver와 Answer Composer를 합쳐 한 번이다.
- 모델의 숫자형 confidence는 라우팅 근거가 될 수 없다.
- 모델이 생성한 자유 문장, SQL, 수식, 필드명은 실행 입력이 될 수 없다.
- 모든 요청은 stateless이며 한 question 내부 문맥만 사용한다.
- 알 수 없는 JSON 필드와 등록되지 않은 ID를 거부한다.
- QueryPlan의 현재 Pydantic·JSON shape는 유지한다.

## 3. 전제와 성공 조건

### 3.1 전제

- RequestContext는 유효한 question, 순서가 있는 surface segment,
  named-entity mention 후보, 명시적 reference mention 후보를 제공한다.
- active dataset과 ontology projection은 같은 dataset version과 cutoff를
  사용한다.
- SemanticQueryCatalog는 서비스 시작 전에 빌드·검증된다.
- 실제 canonical entity 확정은 후속 Entity Resolution 실행의 책임이다.
- Phase 1은 의미 적용 가능성을 판정하지만 실제 데이터 coverage를 확정하지
  않는다.

### 3.2 완료 기준

- unknown ID와 잘못된 context graph가 검증을 통과하지 않는다.
- 골드 질문 파일을 삭제하거나 위치를 바꿔도 production catalog build가
  동일하게 성공한다.
- 한 surface segment에서 여러 atomic frame을 표현할 수 있다.
- ETF와 ETN, ProductRiskGrade와 CreditGrade, product family와 ontology type을
  혼동하지 않는다.
- explicit, ellipsis, plural result set, ambiguous singular reference를
  구별한다.
- 조합 OOD는 valid frame으로 보존하고, 어휘·도메인·문맥 OOD는 안정된
  reason code를 가진다.
- 모든 결과가 catalog, ontology, NLU overlay, prompt, model, dataset 버전으로
  재현 가능하다.
- 실행에 필요한 context link, selector, slot mutation, frame dependency가 기존
  QueryPlan에 손실 없이 내려갈 수 있음을 Phase 2 contract test로 증명한다.
- 16절의 promotion gate를 모두 통과해야 기본 경로로 승격된다.

## 4. 검토한 대안

| 접근 | 작업량 | 위험 | 결론 |
| --- | ---: | ---: | --- |
| 모델이 QueryPlan 직접 생성 | S | High | 실행 선택지가 너무 크고 오류가 바로 하방 전파되므로 기각 |
| Resolver 전용 어휘 파일 수작업 | M | Medium-High | 기존 온톨로지·계약과 중복되어 기각 |
| 공통 SemanticQueryCatalog와 생성 ResolverView | M-L | Medium | 선택; 정확성과 재사용의 균형이 가장 좋음 |
| Domain·Action·Tag 세 모델 호출 | M | Medium | context 일관성과 지연 문제로 기본안에서 제외; benchmark challenger만 유지 |

## 5. 의미 권위와 의존 방향

### 5.1 권위 매트릭스

| 의미 | 단일 권위 | Resolver 사용 방식 |
| --- | --- | --- |
| Product family | contracts ProductFamily enum | 네 ID 전체를 작은 선택지로 제공 |
| Action | contracts IntentType enum | 여덟 ID 전체를 제공; frame당 하나 |
| Entity type·상하위·disjointness | ontology TBox·SHACL | expected type와 관계 domain/range 검증 |
| Domain relation | 승인 13개 ontology predicate | predicate와 방향 후보·타입 검증 |
| Abstract metric·attribute·document topic | SemanticQueryCatalog | 질문 의미 ID와 applicability 제공 |
| Source metric definition | PostgreSQL metric_definition | Phase 2 binding·단위·정의 검증에 사용 |
| Entity name·ticker·identifier alias | dataset-versioned catalog | 요청별 canonical entity 후보 생성 |
| 한국어 query 표현 | Korean NLU Overlay | semantic ID 후보 retrieval |
| 회귀 질문·아키타입 | tests/gold/core_questions.json | production catalog의 소비자이자 평가셋 |

gold question catalog은 production build 입력이 아니다. 초기 개념 목록을
감사하는 자료로는 사용할 수 있지만 런타임 dependency, prompt lookup,
archetype-only classifier로 사용할 수 없다.

### 5.2 의존 방향

    Runtime Enum ──────────────┐
    Ontology TBox·SHACL ───────┤
    SemanticQueryCatalog ──────┼─> Catalog Compiler
    Korean NLU Overlay ────────┘         |
                                        v
                                 ResolverBuildManifest
                                        |
                                        v
                                   ResolverView

    tests/gold/core_questions.json
                |
                └──── validates against production catalog

역방향 의존은 금지한다.

## 6. SemanticQueryCatalog

### 6.1 역할

SemanticQueryCatalog는 Resolver와 Phase 2 QueryPlan Compiler가 공유하는
추상 query 의미 계층이다. DB 스키마, 원천 컬럼, SQL 표현을 포함하지 않는다.

초기 논리 구조는 다음과 같다.

    SemanticQueryCatalog
    ├─ catalog_version
    ├─ product_family_references
    ├─ action_references
    ├─ entity_type_references
    ├─ concepts
    │  ├─ attributes
    │  ├─ metrics
    │  ├─ relations
    │  └─ document_topics
    ├─ operators
    ├─ selectors
    ├─ source_roles
    ├─ applicability_rules
    ├─ semantic_flag_rules
    └─ compatibility_metadata

각 concept은 최소한 다음을 가진다.

- stable concept ID
- kind
- 짧은 한국어 정의
- value kind
- 허용 product family
- 허용 ontology entity type
- 필요한 qualifier
- 허용 operator
- missingness sensitivity
- normalization requirement 조건
- ontology 또는 승인 계약 reference

예시 concept ID는 aum, trailing_1y_historical_cumulative_return,
product_risk_grade, credit_grade, managedBy다. 원천별 metric ID나 컬럼명은
Phase 2 compiler binding으로 남긴다.

### 6.2 Product family와 entity type 분리

product_family_scope는 다음 네 값만 사용한다.

- domestic_bond
- domestic_etf
- overseas_etf
- public_fund

entity_type_constraints는 ontology class ID를 사용한다. 예를 들어 일반
ETF 질문은 ETF type을 요구하면서 domestic_etf와 overseas_etf scope를 가질
수 있다. ETF-only 질문은 ETN을 제외한다.

하나의 canonical product가 DomesticETF와 FundShareClass 역할을 함께 가지는
기존 온톨로지 결정을 유지한다. Resolver는 multi-role을 오류로 만들지 않는다.

### 6.3 적용 가능성과 coverage 분리

Applicability는 concept이 특정 family 또는 entity type에 의미상 적용 가능한지
나타낸다. Coverage는 활성 데이터에 답변에 필요한 값과 근거가 실제 존재하는지
나타낸다.

Phase 1은 applicability만 검사한다. Coverage, 비교 가능성, 환율 존재,
결측률, closed-world completeness는 Phase 2 이후의 deterministic gate가
판정한다.

## 7. Korean NLU Overlay

Korean NLU Overlay는 SemanticQueryCatalog ID를 가리키는 언어 계층이다.
다음 정보를 가진다.

- preferred Korean label
- 동의어·약어·구어체
- 띄어쓰기 변형
- 조사 결합 허용 형태
- 숫자·기간·순위 표현 패턴
- direct alias, group alias, ambiguous alias 구분
- negative example 또는 충돌하는 concept

예:

- AUM, 순자산, 순자산총액 -> aum
- 수익률, 성과, 얼마나 올랐는지 -> return concept 후보
- ETF -> ETF type + 국내·해외 ETF group scope
- 위험등급 -> product family와 entity type에 따라 ProductRiskGrade 또는
  CreditGrade 후보

NLU overlay는 상품명, 운용사명, 기업명 alias를 저장하지 않는다. 그 값은
기존 dataset-versioned catalog alias를 사용한다.

## 8. ResolverBuildManifest와 ResolverView

ResolverBuildManifest는 다음 해시와 버전을 고정한다.

- semantic catalog version과 hash
- ontology IRI와 TBox·SHACL aggregate hash
- Korean NLU overlay version과 hash
- normalizer version
- candidate policy version
- resolver schema version
- prompt version
- model adapter version

요청 시 dataset version과 active dataset manifest hash를 추가로 결합한다.

ResolverView는 요청별 bounded projection이다.

    ResolverView
    ├─ four product families
    ├─ eight actions
    ├─ matched semantic concept candidates
    ├─ relation candidates and type constraints
    ├─ deterministic literal candidates
    ├─ dataset-pinned entity candidates
    └─ short definitions and allowed choices

초기 제한은 다음과 같다.

- question: 최대 4,096 Unicode code point
- RequestContext surface segment: 최대 16개
- intent frame: 최대 16개
- semantic candidate: mention당 최대 5개
- entity candidate: mention당 최대 5개
- 전체 semantic candidate: 최대 80개

입력 길이 초과는 모델 호출 전에 REQUEST_CONTRACT_INVALID로 거부한다.
frame 상한을 초과하는 유효 복합 질문은 FRAME_LIMIT_EXCEEDED라는 semantic
limitation 신호로 남긴다.

## 9. 입력 정규화와 후보 생성

### 9.1 정규화

정규화기는 다음을 수행한다.

- Unicode와 공백의 승인된 정규화
- 원문과 정규문 사이의 reversible span map 생성
- 숫자, 한국어 수사, 비율, 금액, 통화, 날짜, 기간, 개수, 순위 추출
- ISIN, ticker, 상품번호처럼 형식 검증 가능한 identifier 표시
- 명시적 지시어 후보 표시

정규화된 문자열 인덱스를 원문 인덱스로 직접 사용하지 않는다. 모든 model
evidence span은 RequestContext segment 내부의 원문 Unicode code-point
start/end와 원문 text를 함께 가진다.

### 9.2 후보 retrieval

Semantic candidate는 exact canonical ID, normalized alias, group alias,
bounded lexical similarity 순으로 합친다. Entity candidate는 기존 exact
identifier, exact normalized name, approved alias, bounded trigram candidate
순으로 만든다.

Fuzzy candidate는 resolved entity가 아니다. 모델도 canonical entity를
확정할 수 없다. 모델은 mention span, expected ontology type, candidate set과
selection hint만 제공하며 실제 cutoff-valid entity resolution은 후속
Capability가 수행한다.

후보가 없다는 사실은 두 가지로 분리한다.

- 정상 검색 결과가 없음: semantic unmapped 후보
- catalog 또는 alias index를 읽지 못함: system failure

## 10. Surface Segment와 Intent Frame

RequestContext segment는 원문 순서와 pseudo-turn을 보존한다. 구두점이 없거나
하나의 문장에 여러 요청이 있더라도 segment를 억지로 실행 단위로 만들지 않는다.

Intent frame은 하나의 atomic action을 가진다.

    IntentFrame
    ├─ frame_id
    ├─ ordinal
    ├─ segment_id
    ├─ evidence_spans
    ├─ normalized_intent_argument
    ├─ action_choice
    ├─ product_family_scope
    ├─ entity_type_constraints
    ├─ entity_hints
    ├─ slot_assignments
    ├─ produced_result_hints
    └─ frame_status

한 segment가 compare와 rank를 함께 요청하면 두 frame을 만들 수 있다. 두
frame은 같은 evidence span을 공유할 수 있으며 frame ordinal과 typed
dependency로 순서를 표현한다.

normalized_intent_argument는 오류 분석과 평가용 진단 문자열이다. 실행 필터,
수식, QueryPlan ID 생성에 사용할 수 없다.

## 11. IntentResolutionDraft

### 11.1 모델 출력 경계

모델에는 질문 전체, RequestContext segment, ResolverView를 한 번에 제공한다.
모델은 다음의 schema-valid draft만 반환한다.

    IntentResolutionDraft
    ├─ surface_segment_refs
    ├─ intent_frames
    ├─ reference_hints
    ├─ context_link_hints
    ├─ slot_mutations
    └─ semantic_flag_hints

서버가 catalog·prompt·model·dataset metadata를 붙인다. 모델이 metadata를
echo하거나 version을 선택하지 않는다.

### 11.2 Axis choice

product family, action, concept 선택은 다음 상태만 허용한다.

- selected
- ambiguous
- unmapped

수치형 confidence와 자유형 rationale은 받지 않는다. evidence span과 안정된
reason code만 허용한다.

### 11.3 Slot assignment

초기 slot kind는 다음과 같다.

- entity
- metric
- filter_value
- filter_operator
- period
- unit
- currency
- sort_key
- sort_direction
- result_limit
- date_scope
- relation
- comparison_basis
- similarity_anchor
- document_topic

숫자, 날짜, 통화, 기간, result limit은 정규화기가 만든 literal candidate ID를
참조한다. 모델이 새 값을 작성할 수 없다. Qualitative 표현은 등록 operator와
concept을 선택하고 evidence span을 남긴다.

### 11.4 Semantic flag hint와 최종 tag

모델은 semantic flag hint만 제공한다. 최종 tag는 validator가 구조와 catalog
규칙으로 생성한다.

초기 tag vocabulary는 다음과 같다.

- CROSS_FAMILY
- MULTI_STEP
- CONTEXT_DEPENDENT
- RELATIONSHIP_REQUIRED
- DOCUMENT_GROUNDED
- TEMPORAL
- NORMALIZATION_REQUIRED
- MISSINGNESS_SENSITIVE
- OPERATIONAL_STATUS
- FUTURE_FORECAST
- PERSONALIZED_ADVICE
- ORDER_EXECUTION
- REALTIME_REQUIRED

구조적으로 유도 가능한 tag는 model hint보다 rule 결과가 우선한다. 정책성
flag는 원문 evidence와 허용 reason code가 있어야 최종 tag가 된다.

## 12. 문맥 해소

### 12.1 ReferenceHint

ReferenceHint는 원문 표현과 후보 antecedent를 기록한다.

필수 의미는 다음과 같다.

- reference ID
- segment ID와 evidence span
- surface presence: explicit 또는 ellipsis
- reference form: demonstrative, zero_anaphora, lexical_anaphor, bridging,
  discourse_deixis
- grammatical number: singular, plural, unknown
- expected target type
- expected cardinality
- candidate target frame 또는 mention ID
- status: resolved, ambiguous, unresolved
- reason code

reference target kind는 entity, result_set, metric_value, related_entity,
prior_operation, evidence_records, exclusion_set을 허용한다.

### 12.2 ContextLink

ContextLink는 ReferenceHint를 실행 전 typed dependency로 바꾼 내부 의미
링크다.

허용 link type은 다음과 같다.

- consume_single_result
- consume_result_set
- derive_entity
- derive_metric_value
- inherit_scope
- replace_slot
- refer_exclusion_set
- refer_evidence

허용 source role은 candidates, selected_product, top_k_products,
excluded_products, metric_value, relation_target, comparison_decision,
evidence_records다.

selector는 all, first, last, rank_position, top_n, former, latter, each,
remaining 중 등록된 값만 사용한다.

producer_frame_id는 consumer_frame_id보다 앞서야 한다. 링크는 acyclic이어야
하며 type·cardinality가 맞아야 한다. many를 one으로 소비하려면 명시 selector가
필요하다. 실제 product ID나 result row는 ContextLink에 들어가지 않는다.

### 12.3 SlotMutation과 우선순위

허용 mutation은 CARRYOVER, UPDATE, DELETE, DONTCARE다.

REPLACE라는 별도 mutation은 두지 않고 같은 slot의 UPDATE로 표현한다.
Carryover는 명시된 source frame과 허용 slot에만 적용한다.

해석 우선순위는 다음과 같다.

1. 현재 frame의 명시적 원문 evidence
2. 유효한 typed ContextLink
3. 명시적으로 허용된 CARRYOVER
4. Phase 2에서 적용할 승인된 default

서로 충돌하면 선택하지 않고 ambiguity issue를 만든다.

### 12.4 경계

- 요청 간 문맥을 사용하지 않는다.
- 단수 이거를 복수 antecedent 중 하나로 추측하지 않는다.
- 비교 기준 없는 더 좋은 상품을 임의 지표로 해석하지 않는다.
- anchor 없는 similarity를 실행 가능으로 표시하지 않는다.
- forward reference를 지원하지 않는다.
- upstream result가 empty여도 downstream 성공을 가정하지 않는다.

## 13. 결정론적 검증과 ValidatedIntentResolution

검증 순서는 고정한다.

1. strict JSON Schema와 unknown-field 검사
2. offered candidate·registered ID 검사
3. source segment와 evidence span 일치 검사
4. ProductFamily·entity type·concept applicability 검사
5. ontology relation domain·range·direction 검사
6. literal candidate와 slot value kind 검사
7. frame ordinal·producer role·context link type·cardinality·acyclic 검사
8. SlotMutation target과 우선순위 검사
9. deterministic final tag 생성
10. semantic resolution status와 issue code 생성

Validator는 ordering canonicalization, exact duplicate 제거, tag derivation처럼
의미를 바꾸지 않는 정규화만 수행한다. unknown ID 교체, 누락 critical slot
추론, antecedent 임의 선택은 하지 않는다.

ValidatedIntentResolution은 draft, canonical frames, validated context links,
final tags, resolution issues, validation events와 모든 version pin을 가진다.

이 내부 계약이 QueryPlan보다 풍부하다는 이유로 실행 의미를 버리면 안 된다.
Phase 2 compiler는 context link, selector, slot mutation, frame dependency를
현재 `resolved_references`, `binding_specs`, `dependency_edges`, 등록 operation
parameter로 손실 없이 내리는 compatibility test를 가져야 한다. 표현할 수 없는
구성이 발견되면 compile을 fail closed하고 별도 contract-change ADR을 요구한다.

semantic resolution status는 다음 네 값을 사용한다.

- resolved
- ambiguous
- unmapped
- context_unresolved

정책 tag는 resolution status가 아니다. FUTURE_FORECAST가 정확히 탐지된
질문은 semantic parsing 관점에서 resolved일 수 있으며, 후속 policy gate가
abstain을 결정한다.

## 14. OOD 분리

| OOD 유형 | 예 | Phase 1 결과 |
| --- | --- | --- |
| 조합 OOD | 유효한 family·action·concept의 새 조합 | resolved frame; Phase 2 compose 후보 |
| 어휘 OOD | 등록되지 않은 ESG 등급 concept | unmapped + lexical evidence |
| 도메인 OOD | 금융상품 분석 범위를 벗어난 질문 | unmapped + domain reason |
| 문맥 OOD | antecedent 없는 이거·그 상품 | context_unresolved |

Phase 1은 Fast, Compose, Explore, Abstain 실행 경로를 확정하지 않는다. 그 경로는
Phase 2가 archetype match, concept coverage, policy와 함께 결정한다.

## 15. 오류와 복구

| Code | 발생 조건 | 복구 | 최종 분류 |
| --- | --- | --- | --- |
| RESOLVER_CATALOG_UNAVAILABLE | catalog snapshot 없음 | 호출 전 중단 | internal invariant, 500 |
| CATALOG_VERSION_MISMATCH | catalog·ontology·dataset pin 불일치 | request 시작 전 reload만 허용 | internal invariant, 500 |
| MODEL_TIMEOUT | provider timeout | transient budget 안에서 1회 | 소진 시 503 |
| MODEL_RATE_LIMITED | provider rate limit | transient budget 안에서 1회 | 소진 시 503 |
| MODEL_PROVIDER_UNAVAILABLE | connection failure 또는 provider 5xx | transient budget 안에서 1회 | 소진 시 503 |
| MODEL_CONFIGURATION_INVALID | 인증·권한·지원하지 않는 model/요청 설정 | 재시도 금지 | internal invariant, 500 |
| MODEL_SCHEMA_INVALID | JSON Schema 위반 | shared LLM repair 1회 가능 | 실패 시 planner contract, 503 |
| MODEL_UNKNOWN_ID | 제공하지 않은 ID 생성 | shared LLM repair 1회 가능 | 실패 시 planner contract, 503 |
| LITERAL_SPAN_MISMATCH | literal·evidence 원문 불일치 | shared LLM repair 1회 가능 | 실패 시 planner contract, 503 |
| INVALID_CONTEXT_GRAPH | cycle·forward·cardinality 위반 | shared LLM repair 1회 가능 | 실패 시 planner contract, 503 |
| SEMANTIC_CONCEPT_UNMAPPED | catalog에 concept 없음 | 재호출 금지 | semantic unmapped |
| REFERENCE_UNRESOLVED | 안전한 antecedent 없음 | 재호출 금지 | context_unresolved |
| REFERENCE_AMBIGUOUS | 복수 antecedent가 유효 | 재호출 금지 | ambiguous |
| FRAME_LIMIT_EXCEEDED | bounded frame 상한 초과 | 재호출 금지 | semantic limitation signal |

model failure를 abstain으로 위장하지 않는다. semantic ambiguity를 provider
failure로 처리하지 않는다. 모든 repair와 retry는 ADR-0006의 request-wide
budget과 deadline을 공유한다.

## 16. 평가

### 16.1 평가 계층

1. Candidate evaluation: gold concept이 top-k 후보에 포함되는가
2. Decoupled frame evaluation: gold candidate를 주었을 때 model이 frame을
   맞히는가
3. Full resolver evaluation: raw Korean question부터 validated frame까지
4. Context evaluation: reference, link, selector, cardinality, mutation
5. OOD evaluation: combination, vocabulary, domain, context 구분
6. Phase 2 evaluation: gold ValidatedIntentResolution을 주입한 QueryPlan
   compiler와 full end-to-end 비교

분류 오류와 compiler·execution 오류를 하나의 점수로 합치지 않는다.

### 16.2 데이터 경계

- 기존 52개 질문은 regression set으로 유지한다.
- production catalog build는 이 파일을 읽지 않는다.
- 한국어 paraphrase, spacing, particle, no-punctuation, correction, ellipsis,
  plural/singular, negative pairs를 별도 held-out set으로 만든다.
- 외부 한국어 dialogue dataset은 패턴과 보조 benchmark로만 사용하며 product
  training set에 직접 혼합하지 않는다.
- model·prompt·alias 변경 후 held-out set을 다시 tuning input으로 사용하지
  않는다. 필요한 경우 새 blind split을 만든다.

### 16.3 Promotion gate

| 지표 | 초기 기준 |
| --- | ---: |
| Unknown ID acceptance | 0 |
| Invalid context graph acceptance | 0 |
| Candidate reproducibility | 100% |
| Candidate recall@5 | 99% 이상 |
| First-pass schema validity | 99% 이상 |
| Held-out joint frame exact match | 90% 이상 |
| Held-out context-link exact match | 95% 이상 |
| OOD false-fast rate | 2% 이하 |

여기서 Phase 1의 false-fast는 어휘·도메인·문맥 OOD가 blocking issue 없이
`resolved`로 남아 후속 Fast route 자격을 얻게 되는 경우다. Phase 2에서는 실제
Fast·Compose·Explore·Abstain route confusion을 별도로 측정한다.

추가로 action, product family, entity type, slot, reference form, mutation별
정확도와 confusion matrix를 기록한다. Fast path 비율 자체는 목표 지표가
아니다.

### 16.4 Model adapter 선택

모든 HyperCLOVA X adapter는 같은 input envelope과 output contract를 사용한다.
Native structured-output adapter와 prompt-constrained JSON adapter가 있다면
다음 지표로 비교한다.

- joint frame exact match
- context-link exact match
- invalid output와 repair rate
- OOD false-fast rate
- p50·p95 latency
- input·output token
- request cost

특정 모델 이름이나 API 기능을 설계 계약에 영구 고정하지 않는다. promotion
report가 선택한 model ID와 adapter version을 고정한다.

## 17. 보안과 프롬프트 경계

- question, alias, label, description은 모두 untrusted data field로 직렬화한다.
- 사용자 문장이나 alias 안의 지시를 system instruction으로 취급하지 않는다.
- full DB row, source locator, secret, credential, raw document body를 prompt에
  넣지 않는다.
- model output에는 SQL, SPARQL, Python, formula, table name, column name 필드가
  없다.
- allowed ID와 enum은 server-side validator가 다시 검사한다.
- prompt와 telemetry에 raw chain of thought을 요청하거나 저장하지 않는다.
- invalid raw output은 valid artifact로 저장하지 않는다.
- operational metrics에는 raw question을 복사하지 않고 request key와 reason
  code를 사용한다.
- prompt-injection, oversized input, Unicode confusable, duplicate-key JSON,
  unknown-field payload를 negative test로 유지한다.

## 18. 저장과 관측성

### 18.1 저장

Stage 06 구현 시 operations.request_artifact에 intent_resolution artifact
type을 하나 추가한다. 별도 domain table이나 두 번째 alias store는 만들지
않는다.

한 intent_resolution artifact는 다음을 묶는다.

- schema-valid IntentResolutionDraft
- ValidatedIntentResolution
- validation event 목록
- original invalid-attempt hash와 repair 사용 여부
- ResolverBuildManifest reference
- dataset version과 active manifest hash
- model ID와 prompt version
- canonical payload hash

QueryPlan artifact는 deterministic compiler output으로 기록한다. model ID와
prompt version은 intent_resolution artifact에 귀속한다. 이 변경은 별도 Stage
06 migration plan과 contract compatibility test가 승인된 뒤 구현한다.

### 18.2 지표

요청별로 다음을 기록한다.

- normalization, candidate generation, model, validation latency
- semantic·entity candidate 수와 candidate source
- frame 수와 context link 수
- resolution status와 issue code
- final tag
- schema violation과 unknown-ID attempt
- repair·retry 사용 여부
- model token과 provider error
- catalog·ontology·NLU·prompt·model·dataset version

offline dashboard는 candidate recall, joint frame exact match, context accuracy,
OOD false-fast와 path confusion을 표시한다. production dashboard는 schema
validity, ambiguous·unmapped·context rate, repair rate와 p95 latency의 변화를
표시한다.

## 19. 성능, 배포, rollback

- ResolverBuildManifest와 static ResolverView 자료는 startup에 검증하고
  memory에 cache한다.
- entity alias 후보는 mention별 N+1 query가 아니라 한 요청에서 batch 조회한다.
- prompt에는 요청 관련 top-k 후보만 넣는다.
- normal path에서 ontology 전체를 parse하거나 Graph query를 실행하지 않는다.
- 3개 axis model call은 production 기본 경로가 아니다.
- Intent Resolution은 기존 20초 질문 해석 상한 안에서 동작하며 실제 p95로
  더 좁은 stage budget을 정한다.

새 catalog, overlay, prompt, model은 shadow benchmark를 먼저 통과한다. 승격은
manifest 단위로 atomic하게 수행한다. rollback은 이전 검증 manifest로
되돌린다. validation을 우회하거나 unconstrained direct QueryPlan generation으로
후퇴하지 않는다.

## 20. Worked example

질문:

    AUM 상위 5개 ETF 알려줘. 그 상품 중 1년 수익률 1위는?

RequestContext surface segment:

    s1: AUM 상위 5개 ETF 알려줘.
    s2: 그 상품 중 1년 수익률 1위는?

Intent frame:

    f1
      segment: s1
      action: rank
      product_family_scope: domestic_etf, overseas_etf
      entity_type_constraint: ETF
      sort concept: aum
      result limit: literal 5
      produces: top_k_products, cardinality many

    f2
      segment: s2
      action: rank
      sort concept: trailing_1y_historical_cumulative_return
      period: 1y
      result limit: literal 1
      consumes: f1.top_k_products

Reference and mutation:

    그 상품
      form: demonstrative
      grammatical number: unknown
      target: f1.top_k_products
      link: consume_result_set
      selector: all

    mutations
      UPDATE sort_key aum -> trailing_1y_historical_cumulative_return
      UPDATE result_limit 5 -> 1

Validator result:

- generic ETF는 ETF type과 국내·해외 ETF scope로 확장한다.
- f2는 f1의 result set을 사용하므로 CONTEXT_DEPENDENT다.
- 두 family를 포함하므로 CROSS_FAMILY다.
- 두 frame이므로 MULTI_STEP다.
- period가 있으므로 TEMPORAL이다.
- cross-family AUM은 Phase 2에서 NORMALIZATION_REQUIRED 가능성을 검사한다.
- 실제 top-five product ID는 모델이 생성하지 않는다.

## 21. Phase handoff

### Phase 1 산출물

- SemanticQueryCatalog 설계와 integrity rules
- Korean NLU Overlay
- ResolverBuildManifest와 bounded ResolverView
- IntentResolutionDraft
- ValidatedIntentResolution
- deterministic validators와 tag rules
- candidate, frame, context, OOD evaluation harness
- intent_resolution artifact storage amendment

### Phase 2 입력

Phase 2 QueryPlan 설계는 다음만 입력으로 받는다.

- ValidatedIntentResolution
- SemanticQueryCatalog의 동일 concept IDs
- archetype catalog
- primitive operation registry
- applicability·coverage·compatibility policies

Phase 2가 Fast, Compose, Explore, Abstain route, required slot, default,
Capability request와 기존 QueryPlan을 결정한다.

Phase 2의 선행 완료 조건은 ValidatedIntentResolution의 실행 의미를 기존
QueryPlan shape에 손실 없이 내리는 compiler compatibility matrix와 contract
test다. 기존 shape로 표현할 수 없는 의미가 발견되면 필드를 조용히 버리지 않고
compile을 차단한 뒤 별도 ADR로 계약 변경을 검토한다.

### Phase 3 입력

Phase 3 Orchestrator는 검증된 QueryPlan과 compiler provenance만 입력으로 받아
ExecutionGraph, 병렬 실행, retry, deadline, failure state를 설계한다. LLM이
Orchestrator를 재귀 호출하지 않는다.

## 22. 구현 경계

이번 문서 승인으로 다음은 아직 수행하지 않는다.

- Pydantic contract 추가
- JSON Schema 생성
- PostgreSQL migration
- HyperCLOVA X 호출
- NLU alias 작성
- gold·held-out 평가셋 변경
- QueryPlan compiler
- Orchestrator

구현 전에는 이 문서를 입력으로 별도 Stage 06 Phase 1 구현 계획을 작성하고,
계약·DB 변경 범위, 테스트 순서, model benchmark와 rollback checkpoint를 다시
승인받아야 한다.

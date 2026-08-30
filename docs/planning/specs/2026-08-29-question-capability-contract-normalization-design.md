# 질문·Capability 계약 정규화 설계

**Date:** 2026-08-29

**Status:** Approved 2026-08-30

**Scope:** 내부 52개 회귀 질문의 요구사항 분류, 검색 역할, 데이터 지원 상태,
실행 검증 상태와 Stage 04 온톨로지 입력 계약

**Related:** [Planning Harness](../HARNESS.md),
[Core Evaluation Set](core-evaluation-set.md),
[Stage 03 Question Coverage](stage-03-question-coverage-2026-08-24.md),
[Financial Ontology Architecture](../architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md),
[ADR-0005](../decisions/ADR-0005-bounded-llm-typed-capability-execution.md),
[ADR-0007](../decisions/ADR-0007-normalized-evidence-ledger-structured-answer-plan.md),
[ADR-0018](../decisions/ADR-0018-keep-minimal-ontology-with-canonical-multi-role-products.md),
[ADR-0021](../decisions/ADR-0021-amend-minimal-ontology-for-question-contract-semantics.md),
[ADR-0020](../decisions/ADR-0020-treat-organizer-missingness-as-authoritative.md)

## 1. 문제

현재 `tests/gold/core_questions.json`의 `required_relations`에는 서로 다른
종류의 요구사항이 섞여 있다.

- 승인된 Graph 관계: `managedBy`, `holdsSecurity`, `tracksIndex`
- PostgreSQL Observation 또는 상품 속성: `hasAUM`, `hasReturnMetric`,
  `hasFee`, `hasNAV`, `hasRiskGrade`
- 제어·검증 조건: `hasAvailability`, `hasSaleStatus`
- 승인 온톨로지 관계의 과거·비정규 명칭: `hasSubsidiary`,
  `representedBySecurity`, `describedByDocument`

이 상태에서 질문별 `required_relations`를 Stage 04 Graph 범위로 사용하면
PostgreSQL에 남아야 하는 수치·상태를 Graph predicate로 승격하거나, 같은 관계를
여러 이름으로 구현할 위험이 있다.

또한 현재 질문 계약은 데이터 지원 상태와 최종 응답 동작을 별도 필드로
갖고 있지만, 요약 문서에서는 이를 `지원(거절)` 또는 `불가`로 합쳐 표현하기
쉽다. 이 표현은 `requires_additional_data`와 영구적인 `unsupported`, 그리고
정확한 `abstention` 동작을 구별하지 못한다.

마지막으로 검색 프로필은 44개 질문에서 카테고리 기본값으로만 결정된다.
이 기본값은 다단계 관계 질문에는 유용하지만, 모든 `unsupported` 질문에
Keyword·RDB·Graph를 지정하여 정책만으로 차단 가능한 예측·개인화·주문
질문에도 불필요한 검색을 실행할 수 있다.

## 2. 목표와 비목표

### 목표

1. 52개 질문의 요구사항을 Entity, Attribute, Metric, Relation,
   Document Claim, Control Check로 분리한다.
2. Graph 관계는 ADR-0018의 13개 predicate만 사용한다.
3. 질문마다 최종 해석된 검색 역할과 Capability별 route를 명시한다.
4. 데이터 지원 상태, 추가 데이터 필요 여부, 예상 응답 동작과 실제 실행
   검증 상태를 분리한다.
5. 질문 원문, Evidence 요구사항, 제한 이유와 기준일을 손실 없이 유지한다.
6. 문서 검색 이후 EvidenceBundle·Claim Gate·Renderer까지 공통 Capability
   카탈로그에 포함한다.

### 비목표

- 공식 문서 수집 범위 확정
- Graph와 Vector의 물리 용량 또는 최종 배포 사양 변경
- Stage 03 정형 데이터 재적재
- 52개 질문의 지원 상태 수량 변경
- 공식 35문항의 비공개 문장 추측
- 새로운 온톨로지 관계 추가
- TTL·SHACL·ABox·Fuseki 구현
- PostgreSQL 스키마 또는 Stage 03 적재 변경

## 3. 결정

### 3.1 단일 기계가독 기준 유지

`tests/gold/core_questions.json`을 질문 계약의 단일 기계가독 기준으로 유지하고
스키마 버전을 `1.3`으로 올린다. 별도 상세 매트릭스 JSON을 만들지 않는다.
질문 계약을 두 파일에 복제하면 상태·라우팅·Evidence가 서로 달라질 수 있기
때문이다.

기존 Markdown 문서는 JSON 계약의 의미와 집계 결과를 설명한다. 52개 질문
원문과 모든 필드를 Markdown에 다시 복사하지 않는다.

### 3.2 요구사항 분류

각 질문은 다음 구조를 갖는다.

```json
{
  "requirements": {
    "entities": [
      {"type": "DomesticETF", "role": "candidate_product"}
    ],
    "attributes": [
      {
        "id": "product_risk_grade",
        "role": "output",
        "authority": "organizer_product_field",
        "controlled_vocabulary": "product_risk_grade_v1"
      }
    ],
    "metrics": [
      {
        "id": "aum",
        "role": "rank_key",
        "authority": "organizer_observation",
        "required_dimensions": ["value", "currency", "applicable_date"]
      }
    ],
    "relations": [
      {
        "predicate": "managedBy",
        "direction": "product_to_manager",
        "required_assertion_fields": [
          "relation_assertion_id",
          "evidence_id",
          "dataset_version"
        ]
      }
    ],
    "document_claims": [],
    "control_checks": [
      "organizer_missingness",
      "stable_sort",
      "dataset_cutoff"
    ]
  }
}
```

분류 규칙은 다음과 같다.

| 분류 | 포함 | 저장·검증 권위 |
| --- | --- | --- |
| `entities` | 상품, 정책 프로그램, 기업, 증권, 운용사, 지수, 테마, 문서의 타입과 역할 | PostgreSQL canonical ID + 온톨로지 타입 제약 |
| `attributes` | 투자지역, 자산군, 상품 위험등급, 채권 신용등급, 통화, 판매·가용 상태, 환헤지, 금리구조 | 구조화 상품 필드 또는 제어 어휘; 온톨로지·SHACL 허용값 검증 |
| `metrics` | AUM, 수익률, 가격, NAV, 보수, 만기·잔존일, 편입비중 등 수치 관측값 | PostgreSQL Observation 또는 RelationAssertion 속성 |
| `relations` | 승인된 엔티티 간 의미 관계 | PostgreSQL RelationAssertion; Graph는 투영본 |
| `document_claims` | 구조, 전략, 위험, 동향 등 공식 문서 구절로 입증할 주장 | DocumentChunk → EvidenceRecord → AtomicClaim |
| `control_checks` | 결측, 비교 가능성, 커버리지, 중복, 컷오프, 정책 | 결정론적 규칙과 VerificationReport |

`required_fields`는 원천 필드 의존성을 추적하므로 유지한다.
`required_relations`는 제거하고 `requirements.relations`로 대체한다. 저장소 내부
소비 코드가 없고 테스트가 해당 필드 존재를 계약으로 강제하지 않으므로, 같은
의미를 두 필드에 중복 보관하는 호환 계층은 만들지 않는다.

`attributes`와 `metrics`는 Graph domain predicate가 아니다. `Region`,
`AssetClass`, 등급, 통화, 상태처럼 허용 어휘와 출처를 검증해야 하지만 다단계
탐색이 필요하지 않은 의미는 controlled attribute로 둔다. 수치·시계열·순위
입력은 metric으로 둔다. 두 분류 모두 PostgreSQL이 권위를 가지며, 온톨로지는
허용 타입·어휘·스킴 버전만 검증한다.

### 3.3 관계 이름 정규화

Graph로 투영 가능한 관계는 다음 13개뿐이다.

```text
managedBy
issuedBy
tracksIndex
holdsSecurity
containsSecurity
securityOfCompany
controlsCompany
listedOn
classifiedAsIndustry
associatedWithTheme
hasShareClass
documentedBy
hasRiskFactor
```

기존 명칭은 다음처럼 이동하거나 정규화한다.

| 기존 명칭 | 새 위치 또는 관계 |
| --- | --- |
| `hasAUM`, `hasReturnMetric`, `hasFee`, `hasNAV`, `hasYieldMetric`, `hasMarketPrice`, `hasINAV`, `hasPremiumDiscount`, `hasMaturity`, `hasRemainingDays`, `hasRemainingMaturity`, `hasYield` | `requirements.metrics` |
| `hasRiskGrade`, `hasProductRiskGrade` | `requirements.attributes.product_risk_grade` + 필요 시 `control_checks` |
| `hasCreditGrade` | `requirements.attributes.credit_grade` + 등급 스킴·순서 `control_checks` |
| `investsInRegion`, `investsInAssetClass`, `hasCurrency`, `tradesInCurrency`, `hasSaleStatus`, `hasAvailability`, `hasPensionEligibility`, `hasOfferingType`, `hasHedgePolicy`, `hasRateStructure` | `requirements.attributes` + 필요 시 `control_checks` |
| `hasHoldingWeight` | 보유 relation assertion의 필수 속성 |
| `hasSubsidiary` | `controlsCompany` |
| `representedBySecurity`, `issuedByCompany` | `securityOfCompany`의 질의 방향 또는 `issuedBy` |
| `classifiedInSector`, `classifiedInIndustry` | `classifiedAsIndustry` |
| `belongsToRepresentativeFund` | `hasShareClass`의 역방향 질의 |
| `describedByDocument` | `documentedBy` |
| `hasStructure`, `hasStrategy`, `hasOfficialUpdate` | `document_claims.claim_type` |
| `publishedBy` | `document_claims.provenance.publisher_organization_id` |
| `hasRelationEvent` | `associatedWithTheme` RelationAssertion의 시간 속성 |
| `hasAlias`, `hasOfficialName` | Entity resolution용 식별·별칭 속성 |
| `hasProductFamily` | `requirements.entities[].type` |
| `hasBenchmark` | `tracksIndex` |
| `relatedToEntity` | 승인 predicate가 아님; Evidence 부재를 검사하는 control check |

관계의 역방향 질의는 새 predicate를 만들지 않는다. `query_direction` 또는
Capability 입력으로 표현한다.

### 3.3.1 최소 온톨로지 보정

52개 질문 감사 결과 Graph 경로가 필요한 질문은 23개이며, 별칭을 정규화하면
13개 승인 predicate 중 12개로 모두 표현된다. `containsSecurity`는 현재 52개
질문에서 직접 사용되지 않지만 지수 구성종목 경로를 위해 유지한다. 새 domain
predicate는 추가하지 않는다.

대신 다음 의미 경계를 명시한다.

- `ProductRiskGrade`와 `CreditGrade`를 분리한다. 각 값은 스킴 ID, 스킴 버전,
  공식 출처, 적용일을 가지며 신용등급만 승인된 스킴 안에서 순서를 비교한다.
- `PolicyProgram`을 문서 주제 엔티티로 추가한다. `FinancialProduct`로 입증되지
  않은 정책형 대상을 상품으로 강제하지 않는다.
- `documentedBy`의 주체는 `FinancialProduct`, `Organization`, `PolicyProgram`을
  허용한다.
- `publisher_organization_id`, `published_at`, `effective_from`, `effective_to`,
  `available_at`, `document_version`, `source_object_id`는 문서 provenance다.
  `publishedBy`를 14번째 domain predicate로 만들지 않는다.
- `RiskFactor` Claim은 `DocumentChunk`의 페이지·절·원문 span Evidence로
  역추적되어야 한다.
- `Region`, `AssetClass`, 등급, 통화, 상태는 controlled attribute이며 13개
  Graph domain predicate에 포함되지 않는다.

### 3.4 검색 역할과 Capability route

각 질문은 `retrieval` 객체에 최종 해석된 역할을 명시한다.

```json
{
  "retrieval": {
    "profile": "structured",
    "roles": ["keyword", "rdb"],
    "subtask_routes": [
      {
        "subtask": "resolve_provider",
        "capability": "resolve_entity",
        "role": "keyword",
        "required": true
      },
      {
        "subtask": "rank_aum",
        "capability": "rank_metric",
        "role": "rdb",
        "required": true
      }
    ]
  }
}
```

최상위 역할만으로 실제 실행 순서를 추측하지 않는다. 모든 `subtasks`는 정확히
한 route를 가지며, 하나의 subtask가 여러 저장소를 결합하면 route의
`role`을 배열로 기록한다.

프로필은 다음 의미를 갖는다.

| 프로필 | 기본 역할 | 사용 범위 |
| --- | --- | --- |
| `structured` | Keyword + RDB | 정확 조회, 필터, 순위, 계산, 문맥 binding |
| `structured_graph` | Keyword + Graph + RDB | 보유·기업·지수 등 관계 경로 후 수치 조회 |
| `document_grounded` | Keyword + Vector + Graph + RDB | 문서 후보, 부모 entity binding, Evidence 검증 |
| `federated` | Keyword + Graph + RDB + Vector | 관계·수치·문서가 모두 필요한 복합 질문 |
| `ontology_gate` | Ontology | 허용 어휘 검증만으로 끝나는 질문 |
| `identity_evidence_gate` | Keyword + 필요 시 RDB/Graph | 기준일 entity 또는 관계 근거 부재 확인 |
| `policy_gate` | Policy | 예측·개인화 추천·주문 등 검색 없는 즉시 차단 |
| `snapshot_scope_gate` | RDB dataset metadata | 실시간 데이터 요청의 컷오프 확인 |

`unsupported`는 검색 프로필이 아니다. 지원 상태가 같아도 차단 이유에 따라
`policy_gate`, `snapshot_scope_gate`, `ontology_gate`,
`identity_evidence_gate` 중 하나를 선택한다.

### 3.5 지원 상태와 실행 검증 상태

각 질문의 기존 `support_level`, `target_support_level`,
`expected_disposition`은 유지하고 다음 필드를 추가한다.

```json
{
  "requires_data": false,
  "verification": {
    "coverage_assessment": "frozen_design_2026-08-27",
    "current_db_execution": "not_run",
    "verified_dataset_version": null,
    "verified_at": null,
    "result_artifact": null
  }
}
```

`requires_data`는 `support_level == requires_additional_data`일 때만 `true`다.
영구 범위 밖인 `unsupported`는 새 데이터를 수집해 답하도록 유도하지 않으므로
`false`다.

`current_db_execution`은 다음 값만 허용한다.

```text
not_run
passed
failed
not_applicable
```

정책·온톨로지 차단 질문도 실제 end-to-end 평가를 실행하기 전에는 `not_run`이다.
Stage 03 커버리지 분류가 존재한다는 이유로 `passed`를 기록하지 않는다.

### 3.6 Evidence와 출시 Capability

공통 Capability 카탈로그는 검색과 계산에서 끝나지 않고 다음 출시 경로를
포함한다.

```text
resolve_entity
lookup_facts
filter_products
rank_metric
calculate_metric
validate_metric_compatibility
normalize_currency
traverse_relation
calculate_similarity
resolve_reference
search_documents
validate_source_spans
validate_missingness
validate_availability
validate_closed_world_coverage
deduplicate_share_classes
build_evidence_bundle
generate_atomic_claims
verify_claim_support
determine_disposition
apply_claim_gate
render_verified_answer
```

각 Capability는 입력·출력 계약, 실행 역할, 필수 Evidence, 실패 시 의미적
Disposition을 설계 문서에 기록한다. 이번 정규화에서는 목록과 질문별 사용
관계만 확정하고 구현 코드는 Stage 04~07 계획에서 작성한다.

### 3.7 공식 35문항 표현

35문항의 정확한 문장은 비공개이므로 질문을 생성하지 않는다. 다음만 기록한다.

- 난이도 상·중·하 각 10문항
- 답변 불가 5문항
- 공개된 질문 가족
- 공식 예시로 확인된 8개 내부 case ID와 출처 페이지

내부 `unsupported` 7개를 공식 답변 불가 5개에 일대일 대응시키지 않는다.

## 4. 데이터 흐름

```text
Question
  → RequestContext
  → QueryPlan
  → requirements grounding
  → explicit Capability routes
  → RDB / Graph / Keyword / Vector candidates
  → EvidenceRecord / CalculationRecord
  → EvidenceBundle
  → AtomicClaim + ClaimSupport
  → VerificationReport
  → AnswerDisposition
  → AnswerPlan
  → Claim Gate
  → deterministic Renderer
```

Graph와 Vector 결과는 직접 Claim을 지지하지 않는다. 반드시 PostgreSQL의
RelationAssertion 또는 DocumentChunk Evidence로 binding되어야 한다.

## 5. 오류와 제한 처리

- 주최 측 필드가 missing이면 같은 의미의 외부값으로 보충하지 않는다.
- Graph 0건은 `closed_world_scope`와 완료 검색 Evidence가 없으면 관계 부재가
  아니다.
- 필요한 route가 성공하지 못하면 남은 부분의 Evidence를 검사해 `partial`,
  `limitation`, `abstention`을 결정한다.
- 서로 다른 지표는 승인된 정의·단위·기간·통화 변환이 없으면 분리하거나
  제한한다.
- 문서 검색 결과에 원문 span, 발행자, 게시일, 적용일이 없으면 Claim을 만들지
  않는다.
- 정책 차단 질문은 검색 실패가 아니라 의미적 `abstention`으로 처리한다.

## 6. 수정 대상

승인 후 다음 파일만 수정한다.

1. `tests/gold/core_questions.json`
2. `tests/ingestion/test_official_question_gates.py`
3. `docs/planning/specs/core-evaluation-set.md`
4. `docs/planning/specs/stage-03-question-coverage-2026-08-24.md`
5. `docs/planning/architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md`

현재 수정 중인 Stage 03 ingestion 구현 파일과
`docs/planning/tasks/2026-08-27-stage-03-local-completion-plan.md`는 건드리지 않는다.

## 7. 검증 기준

1. 질문 case가 정확히 52개이고 ID·원문·상태 분포가 변하지 않는다.
2. 모든 case에 여섯 요구사항 분류와 `retrieval`, `requires_data`,
   `verification`이 존재한다.
3. 모든 `subtasks`가 최소 한 개 route를 가지며 route의 subtask 이름은 실제
   `subtasks`에 존재한다.
4. `requirements.relations[].predicate`는 승인된 13개 중 하나다.
5. `requirements.attributes`와 `requirements.metrics`의 ID가 Graph predicate로
   중복되지 않는다.
6. `requires_data`와 `support_level`의 관계가 모든 case에서 일치한다.
7. 52개 모두 `current_db_execution=not_run`으로 시작한다.
8. 정책 차단 질문은 `policy_gate`이고 저장소 역할이 없다.
9. 문서형·Federated 질문만 Vector 역할을 사용한다.
10. `python -m json.tool`, 질문 계약 테스트, 관련 ingestion 회귀가 통과한다.
11. 최종 diff에 구현 코드, 원본 데이터, 비밀정보, 생성 산출물이 포함되지 않는다.
12. `ProductRiskGrade`와 `CreditGrade`가 다른 제어 어휘로 매핑되고, 신용등급
    순서 검증은 승인된 스킴에만 적용된다.
13. `DOC-FUND-001`은 상품 또는 `PolicyProgram`을 구분하고 문서 발행기관·게시일·
    적용일·가용일을 provenance 요구사항으로 가진다.

## 8. 대안과 기각 이유

### 별도 질문-저장소 매트릭스 JSON 추가

기각한다. 질문 계약과 매트릭스가 서로 다른 상태·라우팅을 갖게 될 수 있고,
질문을 DB에 직접 고정하는 인상을 준다.

### 기존 `required_relations`를 유지하고 별도 분류 필드도 추가

기각한다. 같은 요구사항이 두 위치에 남아 향후 Stage 04가 과거 혼합 필드를
다시 Graph 범위로 사용할 위험이 있다.

### Region·AssetClass·등급·상태를 Graph 관계로 추가

기각한다. 52개 질문에서 이 값들은 구조화 필터, 비교 가능성 검증, 유사도 점수
입력으로 사용되며 다단계 관계 탐색을 요구하지 않는다. PostgreSQL 권위 필드와
제어 어휘를 SHACL로 검증하는 편이 작은 온톨로지 원칙과 일치한다.

### `publishedBy`를 14번째 핵심 관계로 추가

기각한다. 발행기관은 문서 Claim의 공식성과 시간 적격성을 검증하는 provenance
필드다. Graph 경로 확장 없이 문서·Evidence 계약에서 강제할 수 있다.

### 카테고리 기본 검색 프로필만 유지

기각한다. 같은 `unsupported` 카테고리 안에서도 정책, 실시간 범위, 온톨로지
어휘, entity 부재의 실행 경로가 다르다. 최종 route를 질문별로 명시해야
불필요한 Capability 호출을 막을 수 있다.

## 9. 영향

이 변경은 기존 지원 상태나 데이터 범위를 늘리지 않는다. Stage 04는 정규화된
`requirements.relations`만 Graph competency 입력으로 사용하고,
`requirements.attributes`와 `requirements.metrics`는 PostgreSQL 구조화 조회·
검증·계산 입력으로 사용한다.
Stage 05~07은 질문별 Capability route와 Evidence·Claim 출시 Capability를 구현
계획의 기준으로 사용한다.

# Intent Resolver v2 계약 보완 설계

**Date:** 2026-09-01

**Status:** Accepted

**Scope:** Stage 06 Phase 1 contract hardening only

**Decision:** [ADR-0023](../decisions/ADR-0023-use-server-owned-intent-identities-and-explicit-semantic-coverage.md)

## 1. 목적

현재 Phase 1 구조와 단일 HCX 호출은 유지하면서, 실호출에서 확인된 상품군
오분류, 자유 생성 ID 불일치, evidence offset 오류, OOD false-fast를 계약으로
차단한다. QueryPlan compiler와 Orchestrator는 이번 범위에 포함하지 않는다.

## 2. 측정된 기준선

HCX 요청에 `thinking.effort=none`을 추가하고 slot별 ID 제한과 근거 offset의
유일 일치 보정을 적용한 12건 preflight에서 다음을 확인했다.

- provider 성공: 12/12
- strict validation 통과: 10/12
- 보수적 기대 의미 일치: 6/12
- 주요 잔여 오류: context ID 불일치, 복합 frame 누락, product family 오분류,
  vocabulary OOD false-fast와 policy tag 누락

후속 장문 system prompt 실험은 validation을 8/12로 낮춰 폐기했다. 이 수치는
promotion 근거가 아니라 v2 변경의 회귀 기준선이다.

## 3. 변경 후 데이터 흐름

```text
RequestContext
  → normalization/literal/reference extraction
  → semantic/entity/policy/evidence candidates
  → ResolverViewV2
  → HCX Structured Outputs 1회
  → IntentResolutionProposalV2
  → deterministic proposal assembler
  → IntentResolutionDraft
  → semantic/context validation
  → ValidatedIntentResolution
```

HCX는 의미 선택만 담당한다. 서버는 ID, 원문 위치, 교차 참조의 정합성을
담당한다.

## 4. ResolverViewV2

### 4.1 AxisDefinition

ProductFamily와 IntentType 각각에 다음 projection을 제공한다.

```text
AxisDefinition
  axis_kind: product_family | action
  axis_id: registered enum ID
  preferred_label_ko: bounded text
  definition_ko: bounded text
  surface_forms: bounded Korean NLU overlay values
```

- `axis_id` 집합은 runtime enum과 정확히 같아야 한다.
- label·surface form은 Korean NLU overlay에서 생성한다.
- gold 질문이나 런타임별 예시를 정의에 넣지 않는다.
- 전체 axis projection은 작으므로 모든 요청에 제공한다.

### 4.2 EvidenceCandidate

```text
EvidenceCandidate
  evidence_id
  segment_id
  start_char
  end_char
  text
  source_kind: semantic | literal | reference | entity | policy | surface
  offered_semantic_ids
```

ID는 `segment_id`, 원문 좌표, source kind의 canonical hash 또는 안정된 조합으로
생성한다. 같은 원문 범위는 source가 여러 개여도 하나의 evidence record로
합치고 offered semantic IDs만 병합한다. 중복 문자열이 있어도 좌표가 다르면
서로 다른 후보다.

`surface` 후보는 OOD 근거 선택을 위해 필요하지만 전체 문장을 임의 n-gram으로
폭발시키지 않는다. semantic/literal/reference/entity/policy 후보가 덮지 못한
bounded token span만 생성한다.

### 4.3 기존 후보

concept, relation, literal, entity 후보와 applicability는 유지한다. Slot kind별
허용 ID 집합은 현재 동적 response schema 제한을 그대로 유지한다.

## 5. IntentResolutionProposalV2

모델 출력에는 다음 ID를 두지 않는다.

- frame ID
- slot assignment ID
- entity hint ID
- context link ID
- slot mutation ID
- 모델 생성 evidence span ID·offset·text

대신 배열 순서와 server-offered ID를 사용한다.

```text
IntentResolutionProposalV2
  frames[]
    segment_ids[]
    action_choice
    product_family_choice
    semantic_coverage
    slot_assignments[]
      slot_kind
      value_ids[]
      evidence_ids[]
    entity_hints[]
      mention_id
      candidate_entity_ids[]
    produced_result_hints[]
  references[]
    reference_id                 # server-offered normalizer ID
    producer_frame_ordinals[]
    expected target/cardinality
  context_links[]
    reference_id
    producer_frame_ordinal
    consumer_frame_ordinal
    link type/source role/selector
  slot_mutations[]
    source_frame_ordinal?
    consumer_frame_ordinal
    slot kind/mutation kind
  semantic_flag_hints[]
  frame_limit_exceeded
```

Frame ordinal은 배열 위치로 결정하며 모델이 별도 ordinal을 쓰지 않는다.
`producer_frame_ordinal < consumer_frame_ordinal`은 assembler 진입 전에 검사한다.

## 6. Deterministic Proposal Assembler

Assembler는 다음 순서로 동작한다.

1. strict proposal schema와 unknown field 검사
2. offered axis·concept·literal·entity·evidence·reference ID 검사
3. frame ordinal과 backward dependency 검사
4. semantic coverage invariant 검사
5. canonical ID 생성
6. ordinal reference를 canonical ID로 치환
7. ID-rich `IntentResolutionDraft` 생성

Canonical ID 예시는 `frame-0000`, `slot-0000-0001`, `link-0000`처럼 요청 내부에서
결정론적인 형식을 사용한다. 외부 실행 ID나 product ID 의미를 담지 않는다.

Assembler가 할 수 없는 일:

- 누락 frame 생성
- action·family·concept 교체
- 복수 antecedent 중 하나 선택
- partial/unmapped를 covered로 승격
- 없는 evidence 생성

## 7. Semantic coverage와 OOD

```text
FrameSemanticCoverage
  state: covered | partial | unmapped
  reason: none | lexical_ood | domain_ood |
          unsupported_operation | missing_critical_semantic
  evidence_ids[]
```

Invariant:

- `covered`는 reason과 OOD evidence가 없어야 한다.
- `partial`과 `unmapped`는 reason과 최소 1개 evidence가 필요하다.
- `partial`과 `unmapped`는 blocking resolution issue를 만든다.
- registered family/action/concept의 새 조합은 `covered`이며 조합 OOD다.
- unresolved reference는 coverage가 아니라 `context_unresolved`로 남긴다.
- 정책 tag는 coverage가 아니며 후속 policy gate 입력으로 남긴다.

Deterministic guard:

- semantic slot의 value ID는 해당 evidence candidate가 제공한 ID여야 한다.
- ambiguous alias 또는 trigram만으로 선택된 concept은 family/type 적용 규칙으로
  단일 후보가 되지 않으면 `covered`를 허용하지 않는다.
- 미등록 surface를 유사 concept으로 조용히 치환하면 validation이 실패한다.

Issue mapping:

| Coverage | Reason | Issue/status |
| --- | --- | --- |
| partial | lexical_ood | `SEMANTIC_CONCEPT_UNMAPPED` / `unmapped` |
| unmapped | lexical_ood | `SEMANTIC_CONCEPT_UNMAPPED` / `unmapped` |
| unmapped | domain_ood | `SEMANTIC_DOMAIN_UNMAPPED` / `unmapped` |
| unmapped | unsupported_operation | `SEMANTIC_OPERATION_UNSUPPORTED` / `unmapped` |
| partial | missing_critical_semantic | `SEMANTIC_CRITICAL_SLOT_MISSING` / `unmapped` |

## 8. 문맥 해소

Normalizer가 `그 상품`, `각각`, `이거`에 reference ID를 먼저 부여한다. HCX는
그 ID와 producer/consumer frame ordinal만 선택한다. Assembler가 모든 link와
mutation ID를 생성하므로 서로 다른 자유형 ID를 쓸 수 없다.

기존 규칙은 유지한다.

- backward, acyclic link만 허용
- source role은 producer가 실제 제공해야 함
- many-to-one은 selector 필수
- explicit current-frame evidence가 link와 carryover보다 우선
- 안전한 antecedent가 없으면 `context_unresolved`

## 9. 정책 신호

`PERSONALIZED_ADVICE`, `ORDER_EXECUTION`, `FUTURE_FORECAST`,
`REALTIME_REQUIRED`의 명시적 Korean cue를 NLU overlay의 policy cue 영역에 둔다.
Exact cue hit는 deterministic tag enrichment가 보존하며, 모델 hint는 추가 근거일
뿐 exact hit를 제거할 수 없다. 정책 tag는 Phase 2/후속 policy gate가 사용할
뿐 Phase 1이 주문이나 자문을 지원하는 것으로 해석하지 않는다.

일반적인 “추천해줘”만으로 `PERSONALIZED_ADVICE`를 만들지 않는다. 기존 Harness의
safe default대로 조건 기반 후보 검색으로 해석하고, 투자자 개인 정보에 맞춘
선정이나 실제 주문을 명시한 bounded cue가 있을 때만 해당 정책 tag를 만든다.

## 10. 버전과 호환성

- proposal schema: `2.0`
- prompt, candidate policy, normalizer, adapter version을 변경 영향에 맞게 갱신
- `IntentResolutionDraft`와 `ValidatedIntentResolution`은 assembler 출력으로
  유지하되 semantic coverage를 손실 없이 포함하도록 내부 schema를 갱신
- RequestContext, QueryPlan, public `GET /answer`는 변경하지 않음
- v1 artifact는 기존 schema/version으로 계속 읽을 수 있어야 함

저장소 migration 필요 여부는 구현 계획에서 artifact JSON 저장과 schema
constraint를 확인한 뒤 결정한다. 추측으로 migration을 추가하지 않는다.

## 11. 오류 처리

새 failure code:

- `MODEL_PROPOSAL_SCHEMA_INVALID`
- `MODEL_UNKNOWN_EVIDENCE_ID`
- `MODEL_INVALID_FRAME_REFERENCE`
- `MODEL_INVALID_SEMANTIC_COVERAGE`

이 오류는 planner contract failure이며 ADR-0006의 shared repair budget만 사용할
수 있다. `partial`, `unmapped`, `context_unresolved`는 semantic result이므로 모델
재호출 사유가 아니다.

## 12. 테스트와 평가

### Contract/assembler

- 같은 proposal에서 canonical ID와 assembled draft가 byte-stable
- unknown evidence와 out-of-range ordinal 거부
- 자유형 ID 필드가 proposal schema에 존재하지 않음
- duplicate surface text가 정확한 evidence ID로 구별됨
- assembler가 semantic choice를 변경하지 않음

### Context

- 2-frame result-set consume 성공
- forward/cyclic/missing producer 거부
- plural/singular selector와 cardinality 검증
- reference ID는 normalizer 제공값만 허용

### OOD/policy

- ESG ETF: `partial` 또는 `unmapped`, false-fast 금지
- 시장 일반 질문: domain `unmapped`
- 개인화 추천·주문: policy tag 보존, 지원 액션으로 변환 금지
- 새 유효 family/action/concept 조합: `covered`

### Live evaluation

- resolver 자체 retry는 추가하지 않는다.
- benchmark runner만 provider rate limit을 피하도록 요청 간격을 둔다.
- fixed seed와 동일 manifest로 simple/compound/context/OOD를 분리 집계한다.
- raw 질문별 모델 출력과 credential은 저장하지 않는다.

ADR-0022의 promotion gate를 완화하지 않는다. 12건 smoke는 연결 회귀일 뿐
promotion 근거가 아니며, held-out set에서 schema validity, joint frame,
context-link, OOD false-fast를 판정한다.

## 13. 구현 범위와 비범위

구현 범위:

- catalog/NLU overlay axis·policy projection
- ResolverViewV2 evidence/axis fields
- proposal v2 contract와 HCX response schema
- deterministic assembler
- semantic coverage validation과 issue mapping
- 관련 schema export, evaluation projection, unit/integration test

비범위:

- QueryPlan compiler·archetype·Fast/Compose/Explore/Abstain route
- QueryPlan 계약 변경
- Orchestrator·ExecutionGraph
- SQL·SPARQL·retrieval·calculation
- Answer Composer와 최종 disposition
- model promotion, deployment, push 또는 merge

## 14. 완료 조건

- 모델이 생성하는 실행용 내부 ID와 evidence offset이 0개다.
- unknown ID/evidence와 invalid graph acceptance가 0이다.
- lexical/domain/context OOD가 blocking issue 없이 `resolved`가 되지 않는다.
- 기존 v1 artifact와 public/downstream 계약 호환성이 검증된다.
- 관련 unit·contract·offline suite가 모두 통과한다.
- rate-limit과 모델 정확도를 분리한 live report가 생성된다.
- ADR-0022 promotion gate를 모두 통과하기 전에는 기본 resolver로 승격하지 않는다.

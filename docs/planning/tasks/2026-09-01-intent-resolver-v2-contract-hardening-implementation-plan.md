# Intent Resolver v2 Contract Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** HCX-007이 한국어 금융상품 질문의 의미만 선택하게 하고, 서버가 모든
evidence와 내부 ID를 결정론적으로 조립하며 lexical/domain OOD를 명시적으로
차단하는 Intent Resolver v2를 완성한다.

**Architecture:** 기존 단일 HCX Structured Outputs 호출과 외부
`RequestContext → Intent Resolver → QueryPlan` 경계는 유지한다. 요청별
`ResolverViewV2`가 축 정의와 서버 소유 evidence 후보를 제공하고, HCX의
`IntentResolutionProposalV2`를 deterministic assembler가 기존 ID-rich draft로
변환한 뒤 semantic/context validator가 최종 resolution을 만든다.

**Tech Stack:** Python 3.12, Pydantic 2, JSON Schema 2020-12, HTTPX 0.28+,
pytest 8, HyperCLOVA X Chat Completions v3 Structured Outputs, SHA-256

**Spec:**
`docs/planning/specs/2026-09-01-intent-resolver-contract-hardening-design.md`

**Decisions:**
`docs/planning/decisions/ADR-0022-use-ontology-grounded-intent-resolution.md`,
`docs/planning/decisions/ADR-0023-use-server-owned-intent-identities-and-explicit-semantic-coverage.md`

## Global Constraints

- 작업 시작 시 Harness, ADR-0022, ADR-0023, v1 설계, v2 설계를 다시 읽는다.
- 현재 `codex/intent-resolver-phase1` worktree의 승인되지 않은 HCX preflight 변경은
  먼저 diff를 검토하고, 이 계획과 일치하는 부분만 각 Task에 흡수한다.
- 정상 resolver 경로의 HCX 호출은 정확히 한 번이며 resolver 자체 retry와 자동
  repair를 추가하지 않는다.
- HCX는 frame·slot·entity hint·context link·mutation·evidence ID 또는 원문 offset을
  생성하지 않는다.
- 서버가 제공하지 않은 axis·semantic·literal·entity·evidence·reference ID와
  유효하지 않은 frame ordinal은 fail closed 한다.
- ProductFamily 네 값과 IntentType 여덟 값은
  `financial_agent.contracts.enums`를 단일 권위로 유지한다.
- 한국어 축 정의·surface form·policy cue는 NLU overlay가 단일 권위이며 gold
  질문과 런타임별 예시를 production prompt 입력으로 사용하지 않는다.
- 일반적인 “추천해줘”는 조건 기반 screen이다. 개인 정보 기반 선정 또는 실제
  주문의 명시적 cue에만 `PERSONALIZED_ADVICE` 또는 `ORDER_EXECUTION`을 붙인다.
- registered family/action/concept의 새 조합은 `covered`다. lexical/domain OOD와
  unresolved context는 각각 별도 typed 상태로 유지한다.
- `RequestContext`, `QueryPlan`, public `GET /answer`, SQL/retrieval/calculation,
  QueryPlan route, Orchestrator는 수정하지 않는다.
- 기존 v1 artifact JSON은 계속 읽을 수 있어야 한다. 새 model-facing proposal과
  schema bundle만 `2.0`으로 버전한다.
- `operations.request_artifact`는 JSONB payload와 기존 공통 key만 제약하므로 이번
  변경에는 Alembic migration을 추가하지 않는다.
- raw 질문별 HCX 출력, credential, `api.txt`, `.env`, benchmark artifact는 Git에
  넣지 않는다.
- 각 Task는 RED → 최소 구현 → GREEN → 관련 회귀 → diff 검토 → 독립 커밋 순서로
  진행한다.

## 구현 파일 지도

| 경로 | 단일 책임 |
| --- | --- |
| `config/intent/korean-nlu-overlay.v2.json` | 한국어 axis 정의·alias·bounded policy cue |
| `src/financial_agent/intent/catalog.py` | v2 overlay 검증·불변 snapshot 생성 |
| `src/financial_agent/intent/evidence.py` | 원문 좌표 기반 evidence 후보 생성·병합 |
| `src/financial_agent/intent/view.py` | axis/evidence/reference를 포함한 bounded ResolverViewV2 |
| `src/financial_agent/intent/proposal.py` | HCX model-facing strict proposal v2 계약 |
| `src/financial_agent/intent/assembler.py` | ordinal/선택값을 canonical ID-rich draft로 변환 |
| `src/financial_agent/intent/prompt.py` | v2 view 직렬화와 동적 HCX response schema |
| `src/financial_agent/intent/draft.py` | 기존 draft 호환성과 frame semantic coverage 보존 |
| `src/financial_agent/intent/resolution.py` | validated frame coverage 보존 |
| `src/financial_agent/intent/validation.py` | coverage invariant·OOD issue mapping·policy enrichment |
| `src/financial_agent/intent/context.py` | assembled canonical link의 기존 graph 검증 |
| `src/financial_agent/intent/service.py` | prepare→invoke once→proposal parse→assemble→validate 조합 |
| `src/financial_agent/intent/errors.py` | v2 proposal/assembler stable failure code |
| `src/financial_agent/intent/schema_export.py` | v2 proposal·draft·resolution schema freshness |
| `schemas/intent/v2/` | 커밋되는 v2 내부 JSON Schema |
| `src/financial_agent/intent/evaluation.py` | coverage·false-fast·provider 분리 metric |
| `scripts/evaluate_intent_resolver.py` | 요청 간격을 둔 live evaluator와 sanitized report |
| `tests/intent/` | contract, view, assembler, validation, service 회귀 |

---

### Task 1: v2 한국어 axis와 policy ontology projection을 잠근다

**Files:**

- Create: `config/intent/korean-nlu-overlay.v2.json`
- Modify: `src/financial_agent/intent/catalog.py`
- Modify: `tests/intent/test_catalog.py`

**Interfaces:**

- Consumes: 기존 runtime `ProductFamily`, `IntentType`, catalog concept IDs
- Produces: `AxisLanguageDefinition`, `PolicyCue`,
  `SemanticCatalogSnapshot.axis_definitions`, `SemanticCatalogSnapshot.policy_cues`

- [ ] **Step 1: strict overlay 계약의 실패 테스트를 쓴다**

```python
def test_v2_overlay_covers_every_runtime_axis_once() -> None:
    snapshot = load_catalog(PROJECT_ROOT)
    assert tuple(snapshot.axis_definitions) == tuple(sorted(
        [item.value for item in ProductFamily] + [item.value for item in IntentType]
    ))


def test_generic_recommendation_is_not_a_personalized_policy_cue() -> None:
    snapshot = load_catalog(PROJECT_ROOT)
    surfaces = {cue.surface for cue in snapshot.policy_cues}
    assert "추천해줘" not in surfaces
    assert {"내 투자성향에 맞춰", "매수해줘"} <= surfaces
```

- [ ] **Step 2: RED를 확인한다**

Run: `python3.12 -m pytest tests/intent/test_catalog.py -q`

Expected: `axis_definitions` 또는 `policy_cues`가 없어 실패한다.

- [ ] **Step 3: v2 overlay strict model과 snapshot 필드를 구현한다**

```python
class AxisLanguageDefinition(_StrictModel):
    axis_kind: Literal["product_family", "action"]
    axis_id: str = Field(min_length=1)
    preferred_label_ko: str = Field(min_length=1)
    definition_ko: str = Field(min_length=1)
    surface_forms: tuple[str, ...]


class PolicyCue(_StrictModel):
    semantic_tag: Literal[
        "PERSONALIZED_ADVICE", "ORDER_EXECUTION",
        "FUTURE_FORECAST", "REALTIME_REQUIRED",
    ]
    surface: str = Field(min_length=1)
```

`_OverlayPayload`에 `axis_definitions`와 `policy_cues`를 required로 추가하고,
axis ID 집합이 runtime enum 합집합과 정확히 같으며 cue가 중복되지 않는지
검사한다. `_OVERLAY_PATH`는 v2 파일을 가리키고 v1 파일은 삭제하지 않는다.

- [ ] **Step 4: 열두 axis 정의와 bounded policy cue를 기록한다**

다음 값을 그대로 기록한다. surface form은 의미 중복을 피하기 위해 이 표의 값만
초기 v2에 넣고 held-out 결과 없이 확장하지 않는다.

| kind | ID | label | definition | surface forms |
| --- | --- | --- | --- | --- |
| product_family | `domestic_bond` | 국내채권 | 국내에서 발행·유통되는 채권 상품 범위 | 국내채권, 채권 |
| product_family | `domestic_etf` | 국내ETF | 국내 거래소에 상장된 ETF 상품 범위 | 국내 ETF, 국내 상장 ETF |
| product_family | `overseas_etf` | 해외ETF | 해외 거래소에 상장된 ETF 상품 범위 | 해외 ETF, 미국 ETF |
| product_family | `public_fund` | 공모펀드 | 일반 투자자에게 공개 모집되는 비상장 공모펀드 범위 | 공모펀드, 펀드 |
| action | `lookup` | 조회 | 특정 상품이나 속성의 값을 확인하는 질문 | 알려줘, 조회, 얼마 |
| action | `screen` | 조건검색 | 명시한 조건을 만족하는 후보를 찾는 질문 | 찾아줘, 골라줘, 추천해줘 |
| action | `rank` | 순위 | 정렬 기준에 따라 상위·하위 상품을 구하는 질문 | 상위, 하위, 순위, 1위 |
| action | `compare` | 비교 | 둘 이상의 상품·집단의 차이를 대조하는 질문 | 비교, 더 높은, 차이 |
| action | `aggregate` | 집계 | 상품 집합을 세거나 그룹별 통계를 구하는 질문 | 몇 개, 분포, 평균, 합계 |
| action | `calculate` | 계산 | 제공된 값과 등록된 산식으로 파생값을 구하는 질문 | 계산, 환산 |
| action | `similar` | 유사상품 | 기준 상품과 등록된 축에서 유사한 후보를 찾는 질문 | 비슷한, 유사한 |
| action | `explain` | 설명 | 상품·속성·관계의 의미나 근거를 설명하는 질문 | 설명, 의미, 왜 |

policy cue에는 다음 명시적 표현만 포함한다.

```json
[
  {"semantic_tag":"PERSONALIZED_ADVICE","surface":"내 투자성향에 맞춰"},
  {"semantic_tag":"PERSONALIZED_ADVICE","surface":"내 상황에 맞는 상품"},
  {"semantic_tag":"ORDER_EXECUTION","surface":"매수해줘"},
  {"semantic_tag":"ORDER_EXECUTION","surface":"주문해줘"},
  {"semantic_tag":"FUTURE_FORECAST","surface":"앞으로 오를"},
  {"semantic_tag":"REALTIME_REQUIRED","surface":"지금 가격"}
]
```

- [ ] **Step 5: GREEN과 catalog 회귀를 확인한다**

Run: `python3.12 -m pytest tests/intent/test_catalog.py tests/intent/test_candidates.py -q`

Expected: 모두 통과하고 동일 입력의 catalog hash가 byte-stable이다.

- [ ] **Step 6: 변경 범위를 검토하고 커밋한다**

```bash
git add config/intent/korean-nlu-overlay.v2.json src/financial_agent/intent/catalog.py tests/intent/test_catalog.py
git diff --cached --check
git commit -m "feat: add Korean intent axis definitions"
```

---

### Task 2: 서버 소유 evidence 후보와 ResolverViewV2를 만든다

**Files:**

- Create: `src/financial_agent/intent/evidence.py`
- Modify: `src/financial_agent/intent/view.py`
- Create: `tests/intent/test_evidence.py`
- Modify: `tests/intent/test_view.py`

**Interfaces:**

- Consumes: `NormalizedRequest`, literals, references, semantic/entity candidates,
  Task 1의 axis/policy projection
- Produces: `EvidenceCandidate`, `AxisDefinition`, v2 `ResolverView`

- [ ] **Step 1: 좌표·중복 문자열·병합 규칙의 실패 테스트를 쓴다**

```python
def test_duplicate_surface_text_keeps_distinct_evidence_ids() -> None:
    evidence = build_evidence_candidates(inputs_for("ETF와 ETF를 비교해줘"))
    etf = [item for item in evidence if item.text == "ETF"]
    assert len(etf) == 2
    assert etf[0].evidence_id != etf[1].evidence_id


def test_same_span_merges_offered_semantic_ids() -> None:
    evidence = build_evidence_candidates(inputs_for("위험등급"))
    item = next(value for value in evidence if value.text == "위험등급")
    assert item.offered_semantic_ids == ("credit_grade", "product_risk_grade")
```

- [ ] **Step 2: RED를 확인한다**

Run: `python3.12 -m pytest tests/intent/test_evidence.py tests/intent/test_view.py -q`

Expected: `financial_agent.intent.evidence` import가 실패한다.

- [ ] **Step 3: evidence value object와 canonical ID를 구현한다**

```python
class EvidenceSourceKind(str, Enum):
    SEMANTIC = "semantic"
    LITERAL = "literal"
    REFERENCE = "reference"
    ENTITY = "entity"
    POLICY = "policy"
    SURFACE = "surface"


class EvidenceCandidate(ContractModel):
    evidence_id: Identifier
    segment_id: Identifier
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    text: str = Field(min_length=1)
    source_kinds: tuple[EvidenceSourceKind, ...]
    offered_semantic_ids: tuple[Identifier, ...]
```

`evidence_id`는 canonical JSON의
`(segment_id,start_char,end_char,text)`를 SHA-256으로 해시해
`evidence-<64 hex>`로 만든다. 같은 좌표와 text는 하나로 합치고 source kind와
semantic ID를 정렬·중복 제거한다. uncovered `surface`는 문장 전체 n-gram이
아니라 공백·구두점으로 경계가 정해진 최대 32 code point token span만 만든다.

- [ ] **Step 4: axis/evidence/reference projection을 view에 추가한다**

```python
class AxisDefinition(ContractModel):
    axis_kind: Literal["product_family", "action"]
    axis_id: Identifier
    preferred_label_ko: str
    definition_ko: str
    surface_forms: tuple[str, ...]


class ResolverView(ContractModel):
    # 기존 pin/candidate/definition 필드 유지
    axis_definitions: tuple[AxisDefinition, ...]
    evidence_candidates: tuple[EvidenceCandidate, ...]
    reference_candidates: tuple[ResolverViewReferenceCandidate, ...]
```

view는 axis를 `(axis_kind, axis_id)`, evidence를 원문 segment ordinal과 좌표,
reference를 normalizer 순서로 고정한다. version 상수는
`intent-candidate-v2`, `2.0`, `intent-resolver-ko-v3`,
`clova-chat-v3-proposal-v2`로 함께 갱신한다.

- [ ] **Step 5: GREEN과 bounded view 회귀를 확인한다**

Run: `python3.12 -m pytest tests/intent/test_evidence.py tests/intent/test_view.py -q`

Expected: 모두 통과하고 view 두 번 생성 결과가 byte-identical이다.

- [ ] **Step 6: 변경 범위를 검토하고 커밋한다**

```bash
git add src/financial_agent/intent/evidence.py src/financial_agent/intent/view.py tests/intent/test_evidence.py tests/intent/test_view.py
git diff --cached --check
git commit -m "feat: build server-owned resolver evidence"
```

---

### Task 3: model-facing ProposalV2와 HCX schema를 잠근다

**Files:**

- Create: `src/financial_agent/intent/proposal.py`
- Modify: `src/financial_agent/intent/types.py`
- Modify: `src/financial_agent/intent/prompt.py`
- Modify: `src/financial_agent/intent/schema_export.py`
- Create: `schemas/intent/v2/intent-resolution-proposal.schema.json`
- Create: `tests/intent/test_proposal.py`
- Modify: `tests/intent/test_prompt.py`
- Modify: `tests/intent/test_schema_export.py`

**Interfaces:**

- Consumes: v2 `ResolverView`
- Produces: `IntentResolutionProposalV2.model_validate_json`,
  `build_clova_response_schema(view)` 제한 schema

- [ ] **Step 1: 자유형 ID·offset 부재와 coverage invariant 실패 테스트를 쓴다**

```python
def test_proposal_schema_has_no_model_owned_artifact_ids_or_offsets() -> None:
    schema = IntentResolutionProposalV2.model_json_schema()
    rendered = json.dumps(schema, sort_keys=True)
    for forbidden in ("frame_id", "slot_assignment_id", "context_link_id",
                      "start_char", "end_char", "span_id"):
        assert forbidden not in rendered


def test_covered_frame_rejects_ood_reason_and_evidence() -> None:
    payload = valid_proposal_payload()
    payload["frames"][0]["semantic_coverage"] = {
        "state": "covered", "reason": "lexical_ood", "evidence_ids": ["e1"]
    }
    with pytest.raises(ValidationError):
        IntentResolutionProposalV2.model_validate(payload)
```

- [ ] **Step 2: RED를 확인한다**

Run: `python3.12 -m pytest tests/intent/test_proposal.py tests/intent/test_prompt.py -q`

Expected: proposal module이 없어 실패한다.

- [ ] **Step 3: coverage와 proposal strict model을 구현한다**

```python
class SemanticCoverageState(str, Enum):
    COVERED = "covered"
    PARTIAL = "partial"
    UNMAPPED = "unmapped"


class SemanticCoverageReason(str, Enum):
    NONE = "none"
    LEXICAL_OOD = "lexical_ood"
    DOMAIN_OOD = "domain_ood"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    MISSING_CRITICAL_SEMANTIC = "missing_critical_semantic"


class FrameSemanticCoverage(ContractModel):
    state: SemanticCoverageState
    reason: SemanticCoverageReason
    evidence_ids: tuple[Identifier, ...]


class IntentResolutionProposalV2(ContractModel):
    proposal_schema_version: Literal["2.0"] = "2.0"
    frames: Annotated[tuple[ProposedIntentFrame, ...], Field(max_length=16)]
    references: tuple[ProposedReference, ...]
    context_links: tuple[ProposedContextLink, ...]
    slot_mutations: tuple[ProposedSlotMutation, ...]
    semantic_flag_hints: tuple[ProposedSemanticFlag, ...]
    frame_limit_exceeded: bool
```

각 nested model은 server-offered ID와 frame ordinal만 받는다. Frame ordinal은
별도 필드 없이 `frames` 배열 위치이며 consumer/producer만 정수 ordinal을 쓴다.
`covered`는 `reason=none`과 빈 OOD evidence, 나머지는 non-none reason과 최소
1개 evidence를 요구한다.

- [ ] **Step 4: 동적 HCX schema를 proposal 전용으로 교체한다**

`build_clova_response_schema`가 evidence/reference/axis/candidate enum을 view에서
만들고, context ordinal에는 `minimum=0`, `maximum=len(frames)-1` 대신 HCX schema
생성 시 frame 수를 알 수 없으므로 `minimum=0`, `maximum=15`를 사용한다.
최종 실제 범위는 assembler가 검사한다. system message에는 “정의와 원문을 보고
offered ID/ordinal만 선택하라”는 한정된 규칙만 두고 예시 질문은 넣지 않는다.

- [ ] **Step 5: v2 schema export를 추가하고 v1 파일을 보존한다**

`schema_export.py`는 v1 디렉터리를 수정하지 않고 v2 디렉터리에 proposal,
resolver manifest, assembled draft, validated resolution 네 파일을 생성·검사한다.
기존 v1 JSON을 fixture로 읽는 회귀도 추가한다.

- [ ] **Step 6: GREEN과 schema subset 회귀를 확인한다**

Run: `python3.12 -m pytest tests/intent/test_proposal.py tests/intent/test_prompt.py tests/intent/test_schema_export.py -q`

Expected: 모두 통과하고 response schema에는 offered ID만 존재한다.

- [ ] **Step 7: 변경 범위를 검토하고 커밋한다**

```bash
git add src/financial_agent/intent/proposal.py src/financial_agent/intent/types.py src/financial_agent/intent/prompt.py src/financial_agent/intent/schema_export.py schemas/intent/v2 tests/intent/test_proposal.py tests/intent/test_prompt.py tests/intent/test_schema_export.py
git diff --cached --check
git commit -m "feat: define bounded intent proposal v2"
```

---

### Task 4: deterministic proposal assembler를 구현한다

**Files:**

- Create: `src/financial_agent/intent/assembler.py`
- Modify: `src/financial_agent/intent/draft.py`
- Modify: `src/financial_agent/intent/errors.py`
- Create: `tests/intent/test_assembler.py`
- Modify: `tests/intent/test_contracts.py`

**Interfaces:**

- Consumes: `IntentResolutionProposalV2`, `NormalizedRequest`, `ResolverView`
- Produces: `assemble_proposal(proposal, normalized, view) -> IntentResolutionDraft`

- [ ] **Step 1: canonical assembly와 fail-closed 경계의 실패 테스트를 쓴다**

```python
def test_assembly_is_byte_stable_and_server_assigns_ids() -> None:
    first = assemble_proposal(proposal(), normalized(), view())
    second = assemble_proposal(proposal(), normalized(), view())
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert first.intent_frames[0].frame_id == "frame-0000"
    assert first.intent_frames[0].slot_assignments[0].slot_assignment_id == "slot-0000-0000"


@pytest.mark.parametrize("mutation", [unknown_evidence, forward_link, bad_ordinal])
def test_assembler_rejects_unoffered_or_invalid_references(mutation) -> None:
    with pytest.raises(ResolverContractError):
        assemble_proposal(mutation(proposal()), normalized(), view())
```

- [ ] **Step 2: RED를 확인한다**

Run: `python3.12 -m pytest tests/intent/test_assembler.py -q`

Expected: assembler module이 없어 실패한다.

- [ ] **Step 3: stable failure code를 추가한다**

```python
MODEL_PROPOSAL_SCHEMA_INVALID = "MODEL_PROPOSAL_SCHEMA_INVALID"
MODEL_UNKNOWN_EVIDENCE_ID = "MODEL_UNKNOWN_EVIDENCE_ID"
MODEL_INVALID_FRAME_REFERENCE = "MODEL_INVALID_FRAME_REFERENCE"
MODEL_INVALID_SEMANTIC_COVERAGE = "MODEL_INVALID_SEMANTIC_COVERAGE"
```

- [ ] **Step 4: coverage를 draft에 호환 가능하게 보존한다**

`IntentFrameDraft`에 다음 필드를 추가한다. 기본 빈 tuple은 과거 v1 JSON을 읽기
위한 호환 경로이며, v2 assembler 출력에는 정확히 하나가 들어가야 한다.

```python
semantic_coverage: Annotated[tuple[FrameSemanticCoverage, ...], Field(max_length=1)] = ()
```

- [ ] **Step 5: assembler를 최소 구현한다**

```python
def assemble_proposal(
    proposal: IntentResolutionProposalV2,
    normalized: NormalizedRequest,
    view: ResolverView,
) -> IntentResolutionDraft:
    _validate_offered_ids(proposal, view)
    _validate_ordinals(proposal)
    frames = tuple(_assemble_frame(index, item, view) for index, item in enumerate(proposal.frames))
    return IntentResolutionDraft(
        evidence_spans=_selected_evidence_spans(proposal, view),
        intent_frames=frames,
        entity_hints=_assemble_entity_hints(proposal, frames),
        reference_hints=_assemble_references(proposal, normalized, frames),
        context_link_hints=_assemble_links(proposal, frames),
        slot_mutations=_assemble_mutations(proposal, frames),
        semantic_flag_hints=_assemble_flags(proposal),
        frame_limit_exceeded=proposal.frame_limit_exceeded,
    )
```

ID 형식은 `frame-%04d`, `slot-%04d-%04d`, `entity-hint-%04d-%04d`,
`link-%04d`, `mutation-%04d`로 고정한다. evidence span ID는 view의 evidence ID를
그대로 사용하며 text와 offset은 view에서 복사한다. assembler는 의미 선택이나
antecedent를 새로 만들지 않는다.

- [ ] **Step 6: GREEN과 기존 draft parsing 회귀를 확인한다**

Run: `python3.12 -m pytest tests/intent/test_assembler.py tests/intent/test_contracts.py -q`

Expected: 모두 통과하고 기존 v1 draft fixture가 semantic coverage 빈 tuple로
읽힌다.

- [ ] **Step 7: 변경 범위를 검토하고 커밋한다**

```bash
git add src/financial_agent/intent/assembler.py src/financial_agent/intent/draft.py src/financial_agent/intent/errors.py tests/intent/test_assembler.py tests/intent/test_contracts.py
git diff --cached --check
git commit -m "feat: assemble intent proposals deterministically"
```

---

### Task 5: semantic coverage와 deterministic policy enrichment를 검증한다

**Files:**

- Modify: `src/financial_agent/intent/resolution.py`
- Modify: `src/financial_agent/intent/validation.py`
- Modify: `src/financial_agent/intent/context.py`
- Modify: `tests/intent/test_validation.py`
- Modify: `tests/intent/test_context.py`
- Modify: `tests/intent/test_contracts.py`

**Interfaces:**

- Consumes: assembler가 채운 frame coverage와 server evidence
- Produces: blocking `ResolutionIssue`, coverage를 보존한
  `ValidatedIntentFrame`, deterministic policy tags

- [ ] **Step 1: OOD·조합·policy 경계의 실패 테스트를 쓴다**

```python
def test_esg_lexical_ood_cannot_finish_resolved(inputs) -> None:
    state = validate_semantics(draft_with_coverage("partial", "lexical_ood"), *inputs)
    assert state.resolution_status is ResolutionStatus.UNMAPPED
    assert [issue.code for issue in state.issues] == ["SEMANTIC_CONCEPT_UNMAPPED"]


def test_registered_new_combination_remains_covered(inputs) -> None:
    state = validate_semantics(covered_cross_family_aggregate(), *inputs)
    assert state.resolution_status is ResolutionStatus.RESOLVED


def test_exact_order_cue_survives_missing_model_hint(inputs) -> None:
    state = validate_semantics(draft_without_flags("매수해줘"), *inputs)
    assert SemanticTag.ORDER_EXECUTION in state.final_tags
```

- [ ] **Step 2: RED를 확인한다**

Run: `python3.12 -m pytest tests/intent/test_validation.py tests/intent/test_context.py -q`

Expected: coverage issue mapping 또는 deterministic policy enrichment가 없어
실패한다.

- [ ] **Step 3: validated frame에 coverage를 보존한다**

```python
class ValidatedIntentFrame(ContractModel):
    # 기존 필드 유지
    semantic_coverage: Annotated[
        tuple[FrameSemanticCoverage, ...], Field(max_length=1)
    ] = ()
```

v2 build manifest에서는 frame마다 coverage가 정확히 하나여야 하고, 과거 v1
artifact는 빈 tuple을 허용한다.

- [ ] **Step 4: coverage invariant와 issue mapping을 구현한다**

```python
_COVERAGE_ISSUE = {
    SemanticCoverageReason.LEXICAL_OOD: "SEMANTIC_CONCEPT_UNMAPPED",
    SemanticCoverageReason.DOMAIN_OOD: "SEMANTIC_DOMAIN_UNMAPPED",
    SemanticCoverageReason.UNSUPPORTED_OPERATION: "SEMANTIC_OPERATION_UNSUPPORTED",
    SemanticCoverageReason.MISSING_CRITICAL_SEMANTIC: "SEMANTIC_CRITICAL_SLOT_MISSING",
}
```

`partial`과 `unmapped`는 evidence를 가진 blocking issue를 만들고 resolution을
`unmapped`로 만든다. `covered`는 선택한 semantic value가 해당 evidence의
`offered_semantic_ids`에 포함되고 applicability가 단일하게 성립할 때만 허용한다.
context reference 실패는 이 mapping에 넣지 않는다.

- [ ] **Step 5: exact policy cue enrichment를 구현한다**

정규화된 segment에서 Task 1의 bounded cue를 code-point exact match하고,
해당 원문 evidence가 view에 존재할 때 tag를 합집합에 추가한다. 모델은 tag를
추가 제안할 수 있지만 exact cue tag를 제거할 수 없다. “추천해줘” 단독 문장은
`PERSONALIZED_ADVICE`를 만들지 않는다.

- [ ] **Step 6: context graph 회귀를 확인한다**

Run: `python3.12 -m pytest tests/intent/test_validation.py tests/intent/test_context.py tests/intent/test_contracts.py -q`

Expected: 2-frame result-set consume는 통과하고 forward/cycle/cardinality/reference
오류는 계속 fail closed 한다.

- [ ] **Step 7: 변경 범위를 검토하고 커밋한다**

```bash
git add src/financial_agent/intent/resolution.py src/financial_agent/intent/validation.py src/financial_agent/intent/context.py tests/intent/test_validation.py tests/intent/test_context.py tests/intent/test_contracts.py
git diff --cached --check
git commit -m "feat: validate intent semantic coverage"
```

---

### Task 6: service와 HCX adapter를 ProposalV2 경로로 연결한다

**Files:**

- Modify: `src/financial_agent/intent/service.py`
- Modify: `src/financial_agent/intent/clova.py`
- Modify: `tests/intent/test_service.py`
- Modify: `tests/intent/test_clova.py`

**Interfaces:**

- Consumes: Task 3 proposal schema, Task 4 assembler, 기존 HCX adapter
- Produces: 한 번의 호출로 생성되는 `ValidatedIntentResolution`

- [ ] **Step 1: service one-call과 proposal parsing 실패 테스트를 쓴다**

```python
async def test_resolve_once_parses_proposal_then_assembles_once(service_fixture) -> None:
    attempt = await service_fixture.service.resolve_once(service_fixture.context)
    assert service_fixture.adapter.calls == 1
    assert attempt.resolution.canonical_frames[0].frame_id == "frame-0000"


async def test_unknown_evidence_does_not_retry(service_fixture) -> None:
    service_fixture.adapter.content = proposal_with_unknown_evidence()
    with pytest.raises(ResolverContractError, match="MODEL_UNKNOWN_EVIDENCE_ID"):
        await service_fixture.service.resolve_once(service_fixture.context)
    assert service_fixture.adapter.calls == 1
```

- [ ] **Step 2: RED를 확인한다**

Run: `python3.12 -m pytest tests/intent/test_service.py tests/intent/test_clova.py -q`

Expected: service가 proposal이 아니라 draft를 직접 parse해 실패한다.

- [ ] **Step 3: response validation 경로를 교체한다**

```python
proposal = IntentResolutionProposalV2.model_validate_json(content)
draft = assemble_proposal(proposal, prepared.normalized, prepared.view)
semantic_state = validate_semantics(
    draft, prepared.context, prepared.normalized, prepared.view, self._catalog
)
context_state = validate_context_graph(semantic_state)
```

기존 `_normalize_unique_evidence_offsets`는 삭제한다. 이제 offset은 model output에
없으므로 보정할 대상이 없다. strict JSON duplicate-key 검사, timeout,
`thinking.effort=none`, temperature 0, topP 0.1, topK 1, seed 42,
`maxCompletionTokens=4096`은 유지한다.

- [ ] **Step 4: repair envelope 허용 코드를 v2에 맞춘다**

기존 외부 shared repair budget 입력 형식은 유지하되, resolver 내부에서는 호출하지
않는다. envelope은 새 네 failure code에 대해 “offered ID와 유효 ordinal만
선택하라”는 bounded correction만 만든다.

- [ ] **Step 5: GREEN과 전체 intent 회귀를 확인한다**

Run: `python3.12 -m pytest tests/intent -q`

Expected: intent suite 전체가 통과하고 adapter call count는 항상 0 또는 1이다.

- [ ] **Step 6: 변경 범위를 검토하고 커밋한다**

```bash
git add src/financial_agent/intent/service.py src/financial_agent/intent/clova.py tests/intent/test_service.py tests/intent/test_clova.py
git diff --cached --check
git commit -m "feat: connect HCX intent proposal v2"
```

---

### Task 7: v1 호환성·schema·저장소 경계를 검증한다

**Files:**

- Modify: `src/financial_agent/intent/schema_export.py`
- Modify: `tests/intent/test_schema_export.py`
- Modify: `tests/intent/test_contracts.py`
- Modify: `tests/db/test_artifact_repository.py`

**Interfaces:**

- Consumes: v2 draft/resolution의 additive coverage 필드
- Produces: v1 JSON read compatibility와 변경 없는 request artifact 저장 API

- [ ] **Step 1: 과거 v1 JSON과 v2 round-trip 실패 테스트를 쓴다**

```python
def test_v1_validated_resolution_still_parses() -> None:
    artifact = ValidatedIntentResolution.model_validate_json(V1_RESOLUTION_JSON)
    assert artifact.canonical_frames[0].semantic_coverage == ()


async def test_repository_round_trips_v2_resolution(repository) -> None:
    saved = await repository.save("intent_resolution", v2_resolution())
    loaded = await repository.get(saved.artifact_id)
    assert loaded == v2_resolution()
```

- [ ] **Step 2: RED를 확인한다**

Run: `python3.12 -m pytest tests/intent/test_schema_export.py tests/intent/test_contracts.py tests/db/test_artifact_repository.py -q`

Expected: v2 schema bundle 또는 coverage round-trip이 없어 실패한다.

- [ ] **Step 3: repository가 additive field를 손실 없이 읽는지 확인한다**

별도 table·column·migration은 만들지 않는다. 현재 repository가
`artifact_type="intent_resolution"` payload를 `ValidatedIntentResolution`으로
검증한 뒤 JSONB에 그대로 저장하므로 production repository 수정 없이 위
round-trip 테스트를 통과해야 한다. 실패하면 Task 7을 중단하고 승인된 설계와
실제 저장 계약의 충돌로 보고한다.

- [ ] **Step 4: v1 immutable/v2 freshness 검사를 구현한다**

`schemas/intent/v1/`의 기존 세 파일 hash가 변경되지 않았음을 검사하고,
`schemas/intent/v2/`는 현재 모델에서 재생성한 결과와 byte equality를 검사한다.

- [ ] **Step 5: GREEN과 migration-free 저장소 회귀를 확인한다**

Run: `python3.12 -m pytest tests/intent/test_schema_export.py tests/intent/test_contracts.py tests/db/test_artifact_repository.py -q`

Expected: 모두 통과하고 `alembic/versions/` diff가 없다.

- [ ] **Step 6: 변경 범위를 검토하고 커밋한다**

```bash
git add src/financial_agent/intent/schema_export.py schemas/intent/v2 tests/intent/test_schema_export.py tests/intent/test_contracts.py tests/db/test_artifact_repository.py
git diff --cached --check
git commit -m "test: verify intent v2 artifact compatibility"
```

---

### Task 8: OOD·context·provider 평가를 분리하고 live preflight를 실행한다

**Files:**

- Modify: `src/financial_agent/intent/evaluation.py`
- Modify: `scripts/evaluate_intent_resolver.py`
- Modify: `tests/evaluation/intent/intent_resolution_heldout_ko_v3.json`
- Modify: `tests/evaluation/test_intent_evaluation.py`
- Create: `docs/planning/reports/2026-09-01-intent-resolver-v2-verification.md`

**Interfaces:**

- Consumes: validated v2 resolution과 기존 blind Korean held-out labels
- Produces: provider success, schema validity, joint frame, context-link,
  coverage/OOD false-fast를 분리한 sanitized report

- [ ] **Step 1: metric 분리의 실패 테스트를 쓴다**

```python
def test_provider_failure_is_not_counted_as_semantic_miss() -> None:
    report = evaluate_predictions(dataset_with(rate_limited_case(), lexical_ood_case()))
    assert report.runtime.provider_success.total == 2
    assert report.runtime.provider_success.matched == 1
    assert report.ood.false_fast.total == 1


def test_combination_ood_is_not_false_fast() -> None:
    report = evaluate_predictions(dataset_with(covered_new_combination()))
    assert report.ood.false_fast.matched == 0
```

- [ ] **Step 2: RED를 확인한다**

Run: `python3.12 -m pytest tests/evaluation/test_intent_evaluation.py -q`

Expected: provider와 semantic coverage 집계가 분리되지 않아 실패한다.

- [ ] **Step 3: coverage evaluation projection과 metric을 구현한다**

prediction에 frame별 expected/actual coverage state·reason을 추가하고,
`lexical_ood`, `domain_ood`, `combination_ood`, `context_unresolved`, policy tag를
서로 다른 축으로 집계한다. provider 실패는 semantic metric denominator에서
제외하되 provider success denominator에는 남긴다.

- [ ] **Step 4: live runner에 evaluator pacing만 추가한다**

CLI에 `--request-interval-seconds`를 추가하고 기본값을 `1.0`으로 둔다. 각 live
case 사이에만 대기하며 resolver service에는 retry/sleep을 넣지 않는다. 보고서에는
질문 원문, raw model content, API key를 쓰지 않고 case ID와 집계만 기록한다.

- [ ] **Step 5: offline 전체 검증을 실행한다**

Run:

```bash
python3.12 -m pytest tests/intent tests/evaluation/test_intent_evaluation.py -q
python3.12 scripts/export_intent_schemas.py --check
python3.12 -m pytest -m "not clova_integration and not database_integration" -q
```

Expected: 관련 suite와 broader offline suite가 모두 통과한다.

- [ ] **Step 6: 승인된 credential로 12건 smoke를 실행한다**

Run:

```bash
python3.12 scripts/evaluate_intent_resolver.py live \
  --model HCX-007 \
  --request-interval-seconds 1.0 \
  --case-limit 12 \
  --report-path /private/tmp/intent-resolver-v2-live-report.json
```

Expected: provider success/schema validity/joint frame/context/OOD가 분리되어 출력된다.
12건 결과는 연결 회귀로만 해석하고 promotion 판정에 사용하지 않는다.

- [ ] **Step 7: verification report에 수치와 미통과 gate를 기록한다**

보고서는 baseline `12/12 provider`, `10/12 strict validation`, `6/12 conservative
semantic match`와 v2 결과를 같은 표에서 비교한다. ADR-0022 held-out promotion
gate를 모두 충족하지 못하면 기본 resolver 승격 상태를 명시적으로 `보류`로 둔다.

- [ ] **Step 8: 최종 diff와 secret 범위를 검토하고 커밋한다**

```bash
git status --short
git diff --check
git diff --stat main...HEAD
git add src/financial_agent/intent/evaluation.py scripts/evaluate_intent_resolver.py tests/evaluation/intent/intent_resolution_heldout_ko_v3.json tests/evaluation/test_intent_evaluation.py docs/planning/reports/2026-09-01-intent-resolver-v2-verification.md
git diff --cached --check
git commit -m "test: evaluate intent resolver v2"
```

`api.txt`, `.env`, raw live output, organizer data가 staged되지 않았음을 마지막으로
확인한다. push, merge, model promotion은 별도 사용자 승인 전에는 수행하지 않는다.

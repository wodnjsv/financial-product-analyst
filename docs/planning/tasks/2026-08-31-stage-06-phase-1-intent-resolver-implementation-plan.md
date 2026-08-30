# Stage 06 Phase 1 Intent Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** 구현 가능한 온톨로지 기반 Intent Resolver Phase 1을 완성해,
`RequestContext`와 제한된 의미 후보를 HyperCLOVA X 구조화 호출 한 번으로
`IntentResolutionDraft`로 만들고 결정론적으로 검증된
`ValidatedIntentResolution`까지 생성·저장·평가한다.

**Architecture:** 기존 외부 흐름인
`RequestContext → Intent Resolver component → QueryPlan`은 유지한다. 이번
Phase는 공통 `SemanticQueryCatalog`, 한국어 NLU overlay, 결정론적 정규화·후보
생성, 요청별 `ResolverView`, HCX 구조화 출력 adapter, 의미·문맥 validator,
감사 artifact와 평가 harness까지만 구현한다. 모델은 `QueryPlan`을 직접 만들지
않으며 Phase 2 compiler와 Phase 3 Orchestrator는 별도 설계·계획으로 남긴다.

**Tech Stack:** Python 3.12, Pydantic 2, JSON Schema 2020-12, SQLAlchemy 2
async Core, PostgreSQL 15, pg_trgm, RDFLib 7.6, HTTPX 0.28+, pytest 8,
HyperCLOVA X Chat Completions v3 Structured Outputs, SHA-256

**Spec:**
`docs/planning/specs/2026-08-31-intent-resolver-design.md`

**Decision:**
`docs/planning/decisions/ADR-0022-use-ontology-grounded-intent-resolution.md`

## Global Constraints

- 실행 시작 시 `superpowers:using-git-worktrees`로 승인된
  `codex/intent-resolver-design` HEAD에서 별도
  `codex/intent-resolver-phase1` worktree를 만든다. 현재 설계 worktree에서
  구현하지 않는다.
- Task 1 전에 새 worktree에서 `docs/planning/HARNESS.md`, ADR-0022, 위 Spec,
  `docs/planning/architecture/RUNTIME_CONTRACTS.md`,
  `docs/planning/architecture/FAILURE_AND_DISPOSITION_POLICY.md`를 다시 읽는다.
- Python은 `>=3.12,<3.13`을 유지한다. 기존 `requirements/contracts.lock`,
  `requirements/storage.lock`, `requirements/ingestion.lock`은 수정하지 않는다.
- 평가 경로 Intent 분석은 HyperCLOVA X를 사용한다. 현재 Naver Cloud 공식
  Structured Outputs 경로는 `POST /v3/chat-completions/{modelName}`이며,
  구현 시점 공식 문서가 명시한 지원 모델을 live preflight에서 다시 확인한다.
- 정상 resolver 모델 호출은 정확히 한 번이다. adapter와 service는 자동 retry
  또는 자동 repair를 하지 않고, 후속 Orchestrator가 사용할 typed failure와
  repair envelope만 반환한다.
- 요청 전체 LLM repair budget 1회와 transient retry budget은 ADR-0006의
  권위다. Phase 1 unit test가 별도 budget을 발명하지 않는다.
- 모델 숫자 confidence, 자유형 rationale, SQL, SPARQL, Python, 수식, 테이블명,
  컬럼명은 출력 계약과 실행 입력에 넣지 않는다.
- `tests/gold/core_questions.json`은 production catalog·prompt·runtime build의
  입력이 아니다. 테스트와 offline 평가만 이 파일을 읽을 수 있다.
- ProductFamily 네 값과 IntentType 여덟 값은 기존
  `financial_agent.contracts.enums`를 단일 권위로 사용한다. 같은 enum을 새로
  선언하지 않는다.
- ontology class와 13개 relation predicate는 기존 TBox·SHACL을 단일 권위로
  사용한다. 한국어 표현은 TBox가 아니라 NLU overlay에 둔다.
- entity 이름·ticker·identifier alias는 기존 dataset-versioned
  `catalog.entity`, `catalog.identifier`, `catalog.alias`만 조회한다. 두 번째
  entity alias store를 만들지 않는다.
- question은 최대 4,096 Unicode code point, surface segment와 intent frame은
  각각 최대 16개, semantic·entity candidate는 mention당 최대 5개, 전체
  semantic candidate는 최대 80개다.
- unknown JSON field, 제공하지 않은 candidate ID, 잘못된 원문 span, ontology
  domain/range 위반, forward/cyclic context link, cardinality 위반은 fail closed
  한다.
- 모든 정렬·tie break·hash·candidate 결과는 같은 입력과 version pin에서
  결정론적이어야 한다.
- 기존 `RequestContext`와 `QueryPlan` Pydantic·JSON Schema shape를 변경하지
  않는다. 내부 계약은 `schemas/intent/v1/`에 별도로 둔다.
- QueryPlan compiler, archetype, Fast/Compose/Explore/Abstain routing,
  Capability route, ExecutionGraph, Orchestrator, Answer Composer는 비범위다.
- raw organizer workbook, 공식 원문 payload, 자격증명, `.env`, model raw 응답,
  live question별 출력, benchmark build artifact를 Git에 넣지 않는다.
- 각 Task는 RED → 최소 구현 → GREEN → 관련 회귀 → diff 검토 → 독립 커밋
  순서를 지킨다.
- code block에 쓰인 test helper와 fixture는 해당 test file에 함께 정의한다.
  production interface로 승격하거나 task 사이의 숨은 전역 fixture로 만들지 않는다.

## 구현 파일 지도

| 경로 | 단일 책임 |
| --- | --- |
| `src/financial_agent/intent/types.py` | Phase 1 내부 enum과 작은 공통 value object |
| `src/financial_agent/intent/draft.py` | model-facing `IntentResolutionDraft` strict 계약 |
| `src/financial_agent/intent/resolution.py` | `ResolverBuildManifest`와 `ValidatedIntentResolution` |
| `src/financial_agent/intent/catalog.py` | semantic catalog·NLU overlay load, 무결성 검사, snapshot hash |
| `config/intent/*.json` | 언어 독립 query concept과 한국어 표현 overlay |
| `src/financial_agent/intent/normalization.py` | 원문 보존 Unicode·공백 정규화와 span map |
| `src/financial_agent/intent/literals.py` | 숫자·금액·통화·날짜·기간·순위·개수 literal 추출 |
| `src/financial_agent/intent/candidates.py` | semantic candidate retrieval·정렬·상한 |
| `src/financial_agent/intent/entity_repository.py` | dataset-pinned entity candidate batch 조회 |
| `src/financial_agent/intent/view.py` | 요청별 bounded `ResolverView`와 build manifest 결합 |
| `src/financial_agent/intent/prompt.py` | untrusted-data prompt envelope와 요청별 HCX schema |
| `src/financial_agent/intent/clova.py` | 한 번의 Chat Completions v3 structured call adapter |
| `src/financial_agent/intent/validation.py` | ID·span·applicability·ontology·literal·tag 검증 |
| `src/financial_agent/intent/context.py` | reference·ContextLink·selector·mutation 검증 |
| `src/financial_agent/intent/service.py` | prepare·invoke-once·validate 단계 조합, retry 없음 |
| `src/financial_agent/intent/evaluation.py` | 단계별 offline metric 계산 |
| `alembic/versions/0007_intent_resolution_artifact.py` | 내부 artifact provenance와 invalid-attempt 감사 보강 |
| `scripts/export_intent_schemas.py` | 내부 Schema 생성·freshness 검사 |
| `scripts/evaluate_intent_resolver.py` | deterministic·decoupled·live 평가 CLI |
| `tests/intent/` | catalog, 계약, 정규화, 후보, adapter, validator, service unit test |
| `tests/evaluation/intent/` | regression label과 blind Korean held-out fixture |

---

### Task 1: 내부 Draft·Validated 계약과 Schema를 잠근다

**Files:**

- Modify: `pyproject.toml`
- Create: `requirements/resolver.lock`
- Create: `src/financial_agent/intent/__init__.py`
- Create: `src/financial_agent/intent/types.py`
- Create: `src/financial_agent/intent/draft.py`
- Create: `src/financial_agent/intent/resolution.py`
- Create: `src/financial_agent/intent/schema_export.py`
- Create: `scripts/export_intent_schemas.py`
- Create: `schemas/intent/v1/intent-resolution-draft.schema.json`
- Create: `schemas/intent/v1/resolver-build-manifest.schema.json`
- Create: `schemas/intent/v1/validated-intent-resolution.schema.json`
- Create: `tests/intent/__init__.py`
- Create: `tests/intent/test_contracts.py`
- Create: `tests/intent/test_schema_export.py`

**Interfaces:**

- `IntentResolutionDraft.model_validate_json(payload: str)`는 unknown field를
  거부하고 model-facing 필드만 받는다.
- `ResolverBuildManifest`는 catalog·ontology·overlay·normalizer·candidate
  policy·schema·prompt·adapter version/hash를 고정한다.
- `ValidatedIntentResolution(RuntimeArtifact)`는 `resolution_id`, draft hash,
  canonical frames, validated context links, final tags, issues, validation
  events, build manifest, active dataset manifest hash, repair metadata를 가진다.
- internal schema version은 `1.0`이며 기존 `CONTRACT_SCHEMA_VERSION`과 독립적으로
  같은 초기 문자열을 사용한다.

- [ ] **Step 1: resolver dependency profile과 marker의 실패 테스트를 쓴다**

`tests/intent/test_contracts.py`에 다음 경계를 먼저 추가한다.

```python
from pydantic import ValidationError

from financial_agent.intent.draft import IntentResolutionDraft


def test_draft_rejects_unknown_fields(valid_draft_payload: dict[str, object]) -> None:
    valid_draft_payload["sql"] = "SELECT * FROM product"
    with pytest.raises(ValidationError):
        IntentResolutionDraft.model_validate(valid_draft_payload)


def test_one_surface_segment_can_produce_two_frames(
    valid_draft_payload: dict[str, object],
) -> None:
    valid_draft_payload["intent_frames"] = [
        frame("f1", 0, "compare"),
        frame("f2", 1, "rank"),
    ]
    draft = IntentResolutionDraft.model_validate(valid_draft_payload)
    assert [item.frame_id for item in draft.intent_frames] == ["f1", "f2"]
    assert {item.segment_ids for item in draft.intent_frames} == {("s1",)}
```

fixture는 `tests/intent/conftest.py`가 아니라 이 파일의 작은 helper로 유지해
Task 간 숨은 fixture 의존을 만들지 않는다.

- [ ] **Step 2: RED를 확인한다**

Run:

```bash
python3.12 -m pytest tests/intent/test_contracts.py -q
```

Expected: `financial_agent.intent`가 없어 collection이 실패한다.

- [ ] **Step 3: dependency와 정확한 내부 enum을 추가한다**

`pyproject.toml`에 기존 group을 바꾸지 않고 다음만 추가한다.

```toml
resolver = [
  "httpx>=0.28,<1",
]
```

pytest marker에 다음을 추가한다.

```toml
"clova_integration: requires explicit HyperCLOVA X credentials and live-cost authorization",
```

`requirements/resolver.lock`은 CPython 3.12에서 base, dev, storage, graph,
resolver extras의 정확한 transitive pin으로 생성한다. 기존 세 lock은 byte
단위로 보존한다.

`types.py`에는 다음 값만 선언한다. ProductFamily와 IntentType은 import한다.

```python
class ChoiceState(str, Enum):
    SELECTED = "selected"
    AMBIGUOUS = "ambiguous"
    UNMAPPED = "unmapped"


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNMAPPED = "unmapped"
    CONTEXT_UNRESOLVED = "context_unresolved"


class ReferenceForm(str, Enum):
    DEMONSTRATIVE = "demonstrative"
    ZERO_ANAPHORA = "zero_anaphora"
    LEXICAL_ANAPHOR = "lexical_anaphor"
    BRIDGING = "bridging"
    DISCOURSE_DEIXIS = "discourse_deixis"


class ContextLinkType(str, Enum):
    CONSUME_SINGLE_RESULT = "consume_single_result"
    CONSUME_RESULT_SET = "consume_result_set"
    DERIVE_ENTITY = "derive_entity"
    DERIVE_METRIC_VALUE = "derive_metric_value"
    INHERIT_SCOPE = "inherit_scope"
    REPLACE_SLOT = "replace_slot"
    REFER_EXCLUSION_SET = "refer_exclusion_set"
    REFER_EVIDENCE = "refer_evidence"
```

같은 방식으로 Spec의 `ReferenceTargetKind`, `SourceRole`, `Selector`,
`SlotMutationKind`, 15개 `SlotKind`, 13개 `SemanticTag`를 정확히 선언한다.

- [ ] **Step 4: Draft 계약을 최소 구현한다**

`draft.py`의 public model은 다음 이름과 shape를 사용한다.

```python
class EvidenceSpan(ContractModel):
    span_id: Identifier
    segment_id: Identifier
    start_char: int
    end_char: int
    text: str


class AxisChoice(ContractModel):
    state: ChoiceState
    selected_ids: tuple[Identifier, ...]
    evidence_span_ids: tuple[Identifier, ...]
    reason_code: Identifier


class IntentFrameDraft(ContractModel):
    frame_id: Identifier
    ordinal: int
    segment_ids: tuple[Identifier, ...]
    evidence_span_ids: tuple[Identifier, ...]
    normalized_intent_argument: str
    action_choice: AxisChoice
    product_family_choice: AxisChoice
    entity_type_ids: tuple[Identifier, ...]
    entity_hint_ids: tuple[Identifier, ...]
    slot_assignments: tuple[SlotAssignment, ...]
    produced_result_hints: tuple[SourceRole, ...]


class IntentResolutionDraft(ContractModel):
    evidence_spans: tuple[EvidenceSpan, ...]
    intent_frames: tuple[IntentFrameDraft, ...]
    entity_hints: tuple[EntityHint, ...]
    reference_hints: tuple[ReferenceHint, ...]
    context_link_hints: tuple[ContextLinkHint, ...]
    slot_mutations: tuple[SlotMutation, ...]
    semantic_flag_hints: tuple[SemanticFlagHint, ...]
    frame_limit_exceeded: bool
```

선택 가능한 optional 의미는 JSON `null` 대신 최대 길이 1인 tuple로
표현한다. 이 결정은 HCX가 지원하는 제한된 JSON Schema type 안에서 모든
필드를 required로 유지하기 위함이다. cross-field 의미 검증은 Task 7·8이
담당하고, 이 Task는 shape·고유 ID·ordinal·16 frame 상한만 검증한다.

- [ ] **Step 5: Validated 계약과 Schema exporter를 구현한다**

`resolution.py`에는 다음 entry point를 둔다.

```python
class ResolverBuildManifest(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    catalog_version: Identifier
    catalog_hash: Sha256Hex
    ontology_hashes: tuple[ContractFileHash, ...]
    overlay_version: Identifier
    overlay_hash: Sha256Hex
    normalizer_version: Identifier
    candidate_policy_version: Identifier
    resolver_schema_version: Identifier
    prompt_version: Identifier
    adapter_version: Identifier


class ValidatedIntentResolution(RuntimeArtifact):
    resolution_id: Identifier
    draft_hash: Sha256Hex
    canonical_frames: tuple[ValidatedIntentFrame, ...]
    context_links: tuple[ValidatedContextLink, ...]
    final_tags: tuple[SemanticTag, ...]
    resolution_status: ResolutionStatus
    issues: tuple[ResolutionIssue, ...]
    validation_events: tuple[ValidationEvent, ...]
    build_manifest: ResolverBuildManifest
    active_dataset_manifest_hash: Sha256Hex
    repair_used: bool
    invalid_attempt_hashes: tuple[Sha256Hex, ...]
```

`ContractFileHash`는 nested mutable mapping을 피하기 위해 다음 immutable
value object로 정의하고 `relative_path` 순으로 정렬한다.

```python
class ContractFileHash(ContractModel):
    relative_path: str
    sha256: Sha256Hex
```

`schema_export.py`는 세 model만 `schemas/intent/v1/`에 canonical JSON으로
생성하고 `--check`에서 extra·missing·byte drift를 모두 실패시킨다.

- [ ] **Step 6: Schema와 계약 GREEN을 확인한다**

Run:

```bash
python3.12 scripts/export_intent_schemas.py
python3.12 -m pytest tests/intent/test_contracts.py tests/intent/test_schema_export.py -q
python3.12 scripts/export_intent_schemas.py --check
python3.12 -m pytest tests/contracts -q
```

Expected: 새 내부 Schema 3개와 기존 외부 contract 전부 PASS.

- [ ] **Step 7: Task 1을 커밋한다**

```bash
git add pyproject.toml requirements/resolver.lock src/financial_agent/intent \
  scripts/export_intent_schemas.py schemas/intent tests/intent
git diff --cached --check
git diff --cached
git commit -m "feat: add intent resolution contracts"
```

---

### Task 2: SemanticQueryCatalog와 Korean NLU Overlay를 생성한다

**Files:**

- Create: `config/intent/semantic-query-catalog.v1.json`
- Create: `config/intent/korean-nlu-overlay.v1.json`
- Create: `src/financial_agent/intent/catalog.py`
- Create: `tests/intent/test_catalog.py`

**Interfaces:**

- `load_catalog(project_root: Path) -> SemanticCatalogSnapshot`
- `SemanticCatalogSnapshot.catalog_hash`와 `overlay_hash`는 canonical JSON
  SHA-256이다.
- `SemanticCatalogSnapshot.concepts_by_id`는 immutable mapping이다.
- build는 runtime enum, TBox·SHACL, 두 config JSON만 읽는다.

- [ ] **Step 1: production/gold 의존 차단 테스트를 쓴다**

```python
def test_catalog_build_does_not_read_gold(tmp_path: Path) -> None:
    project = copy_catalog_and_ontology_without_tests(tmp_path)
    first = load_catalog(project)
    second = load_catalog(project)
    assert first.catalog_hash == second.catalog_hash
    assert first.overlay_hash == second.overlay_hash


def test_catalog_uses_frozen_runtime_axes(project_root: Path) -> None:
    snapshot = load_catalog(project_root)
    assert set(snapshot.product_family_ids) == {item.value for item in ProductFamily}
    assert set(snapshot.action_ids) == {item.value for item in IntentType}
```

gold coverage 검사는 별도 test 함수에서만 `tests/gold/core_questions.json`을
읽고, production loader import graph에는 포함하지 않는다.

- [ ] **Step 2: RED를 확인한다**

```bash
python3.12 -m pytest tests/intent/test_catalog.py -q
```

Expected: 두 config와 loader가 없어 FAIL.

- [ ] **Step 3: 언어 독립 catalog의 완전한 초기 ID 집합을 작성한다**

catalog concept은 아래 ID를 빠짐없이 포함한다.

```text
attributes:
  asset_class, availability_status, credit_grade, currency, hedge_policy,
  offering_type, official_product_name, pension_eligibility, product_alias,
  product_risk_grade, rate_structure, region, sale_status

metrics:
  aum, fee_rate, intraday_indicative_nav, market_price, maturity_date, nav,
  premium_discount_rate, remaining_days, remaining_maturity,
  trailing_1y_historical_cumulative_return, yield_rate

relations:
  managedBy, issuedBy, tracksIndex, holdsSecurity, containsSecurity,
  securityOfCompany, controlsCompany, listedOn, classifiedAsIndustry,
  associatedWithTheme, hasShareClass, documentedBy, hasRiskFactor

document_topics:
  investment_strategy, official_update, product_structure, risk_factor,
  supporting_document
```

각 object는 `id`, `kind`, 짧은 한국어 정의, `value_kind`, 허용 family,
허용 ontology type, required qualifier, 허용 operator,
`missingness_sensitive`, `normalization_rule`, authority reference를 모두 가진다.
원천 컬럼, SQL, source-specific metric ID는 넣지 않는다.

초기 family applicability는 아래에서 넓히거나 추측하지 않는다.

| Concept | Allowed ProductFamily |
| --- | --- |
| `asset_class`, `currency`, `official_product_name`, `product_alias`, `region` | 네 family 전체 |
| `availability_status`, `credit_grade`, `rate_structure` | `domestic_bond` |
| `hedge_policy` | `domestic_etf`, `overseas_etf`, `public_fund` |
| `offering_type`, `sale_status` | `public_fund` |
| `pension_eligibility` | `domestic_etf`, `public_fund` |
| `product_risk_grade` | `domestic_etf`, `overseas_etf`, `public_fund` |
| `aum`, `fee_rate`, `nav`, `trailing_1y_historical_cumulative_return` | `domestic_etf`, `overseas_etf`, `public_fund` |
| `intraday_indicative_nav` | `domestic_etf` |
| `market_price`, `premium_discount_rate` | `domestic_etf`, `overseas_etf` |
| `maturity_date`, `remaining_days`, `remaining_maturity`, `yield_rate` | `domestic_bond` |

ETF/ETN, RepresentativeFund/FundShareClass, ProductRiskGrade/CreditGrade의 더
세밀한 허용 여부는 family 표가 아니라 TBox class constraint로 검사한다.

- [ ] **Step 4: overlay를 작성하고 alias 충돌 정책을 고정한다**

overlay entry는 `semantic_id`, `preferred_label`, `aliases`, `alias_kind`,
`negative_semantic_ids`만 가진다. 최소한 다음 표현을 포함한다.

```json
{
  "AUM": "aum",
  "순자산": "aum",
  "순자산총액": "aum",
  "1년 수익률": "trailing_1y_historical_cumulative_return",
  "연간 수익률": "trailing_1y_historical_cumulative_return",
  "위험등급": ["product_risk_grade", "credit_grade"],
  "운용사": "managedBy",
  "발행사": "issuedBy",
  "구성종목": ["holdsSecurity", "containsSecurity"],
  "비슷한": "similar"
}
```

위 JSON은 설명용 map이며 실제 file은 entry array다. `ETF`는 concept alias가
아니라 `ETF` entity type과 국내·해외 ETF group scope를 가리키는 group alias로
기록한다. 상품명·운용사명·회사명은 넣지 않는다.

- [ ] **Step 5: strict compiler를 구현한다**

`catalog.py`는 Pydantic strict model로 두 JSON을 읽고 다음을 검사한다.

```python
def compile_catalog(
    catalog_payload: bytes,
    overlay_payload: bytes,
    *,
    ontology_paths: tuple[Path, ...],
    shacl_paths: tuple[Path, ...],
) -> SemanticCatalogSnapshot:
    ...
```

- ProductFamily·IntentType set exact match
- concept ID, alias, preferred label uniqueness
- overlay의 모든 semantic ID가 catalog 또는 runtime axis에 존재
- ambiguous alias는 후보가 2개 이상이고 direct alias는 정확히 1개
- relation 13개가 TBox의 approved predicate와 exact match
- 모든 entity type reference가 TBox class로 존재
- SHACL·TBox path와 hash가 기존 Graph contract set과 exact match
- canonical sort 후 hash 생성

- [ ] **Step 6: gold가 consumer일 뿐임을 검증하고 GREEN을 만든다**

```bash
python3.12 -m pytest tests/intent/test_catalog.py \
  tests/graph/test_ontology_contract.py -q
```

gold coverage test는 위 attribute·metric·relation·document topic ID가 모두
catalog에 존재한다고 확인하되, gold 파일을 임시로 제거한 build test도 반드시
PASS해야 한다.

- [ ] **Step 7: Task 2를 커밋한다**

```bash
git add config/intent src/financial_agent/intent/catalog.py \
  tests/intent/test_catalog.py
git diff --cached --check
git diff --cached
git commit -m "feat: add semantic query catalog"
```

---

### Task 3: 한국어 정규화·원문 Span·Literal 추출을 구현한다

**Files:**

- Create: `src/financial_agent/intent/normalization.py`
- Create: `src/financial_agent/intent/literals.py`
- Create: `tests/intent/test_normalization.py`
- Create: `tests/intent/test_literals.py`

**Interfaces:**

- `normalize_request(context: RequestContext) -> NormalizedRequest`
- `NormalizedSegment.to_original_span(start: int, end: int) -> tuple[int, int]`
- `NormalizedSegment.find_normalized(text: str) -> tuple[int, int]`
- `extract_literals(request: NormalizedRequest) -> tuple[LiteralCandidate, ...]`
- literal kind: `number`, `percentage`, `money`, `currency`, `date`, `period`,
  `result_limit`, `rank_position`, `sort_direction`

- [ ] **Step 1: 원문 보존과 경계 실패 테스트를 쓴다**

```python
def test_nfkc_and_whitespace_mapping_returns_exact_original_slice() -> None:
    segment = normalize_segment("s1", "ＡＵＭ   상위 ５개")
    start, end = segment.find_normalized("AUM 상위 5개")
    original_start, original_end = segment.to_original_span(start, end)
    assert segment.original_text[original_start:original_end] == "ＡＵＭ   상위 ５개"


def test_request_rejects_more_than_4096_code_points(context_factory) -> None:
    context = context_factory(question="가" * 4097)
    with pytest.raises(RequestNormalizationError, match="REQUEST_CONTRACT_INVALID"):
        normalize_request(context)


def test_request_rejects_more_than_16_segments(context_factory) -> None:
    with pytest.raises(RequestNormalizationError, match="REQUEST_CONTRACT_INVALID"):
        normalize_request(context_factory(segment_count=17))
```

- [ ] **Step 2: RED를 확인한다**

```bash
python3.12 -m pytest tests/intent/test_normalization.py \
  tests/intent/test_literals.py -q
```

- [ ] **Step 3: code-point origin map을 구현한다**

각 원문 code point를 NFKC 변환할 때 생성된 normalized code point에 동일한
`original_start`, `original_end`를 붙인다. 연속 whitespace는 normalized 공백
하나로 만들고 그 공백이 원문 whitespace run 전체를 가리키게 한다.

```python
@dataclass(frozen=True, slots=True)
class NormalizedSegment:
    segment_id: str
    original_text: str
    normalized_text: str
    origin_spans: tuple[tuple[int, int], ...]

    def to_original_span(self, start: int, end: int) -> tuple[int, int]:
        if not 0 <= start < end <= len(self.origin_spans):
            raise ValueError("normalized span is out of range")
        return self.origin_spans[start][0], self.origin_spans[end - 1][1]
```

정규 문자열 offset을 원문 offset으로 직접 재사용하지 않는다. confusable을
ASCII로 임의 치환하지 않고 NFKC와 whitespace 외 의미 변환을 하지 않는다.

- [ ] **Step 4: deterministic literal parser를 구현한다**

다음 표현군을 원문 span과 canonical value로 추출한다.

```text
5, 5개, 상위 5개, 1위, 30%, 3.5%, 330만원, 3,300,000원,
KRW, 원화, USD, 달러, 2026-08-24, 2026년 8월 24일,
1년, 6개월, 오름차순, 내림차순, 높은, 낮은
```

money는 `Decimal` 문자열과 currency를 분리하고 `만원` multiplier를
결정론적으로 적용한다. `1년 수익률`은 period literal만 추출하며 어떤 return
concept인지는 catalog candidate가 결정한다. 각 ID는
`lit-{segment_id}-{start}-{end}-{kind}`로 만든다.

- [ ] **Step 5: 명시적 한국어 reference mention 후보를 표시한다**

`normalize_request`는 `이 상품`, `그 상품`, `그 상품들`, `위 상품들`,
`해당 상품`, `전자`, `후자`, `나머지`, `각각`의 원문 span을 표시한다.
zero anaphora는 문자열 후보를 만들지 않고 model/validator의 ellipsis 경계로
남긴다.

- [ ] **Step 6: GREEN과 기존 request contract 회귀를 확인한다**

```bash
python3.12 -m pytest tests/intent/test_normalization.py \
  tests/intent/test_literals.py tests/contracts/test_request.py -q
```

- [ ] **Step 7: Task 3을 커밋한다**

```bash
git add src/financial_agent/intent/normalization.py \
  src/financial_agent/intent/literals.py tests/intent/test_normalization.py \
  tests/intent/test_literals.py
git diff --cached --check
git diff --cached
git commit -m "feat: normalize Korean intent input"
```

---

### Task 4: Semantic·Entity Candidate를 결정론적으로 생성한다

**Files:**

- Create: `src/financial_agent/intent/candidates.py`
- Create: `src/financial_agent/intent/entity_repository.py`
- Create: `tests/intent/test_candidates.py`
- Create: `tests/db/test_intent_entity_repository.py`

**Interfaces:**

- `generate_semantic_candidates(normalized, catalog) -> SemanticCandidateSet`
- `EntityCandidateRepository.search_batch(dataset_version, mentions) -> Mapping[str, tuple[EntityCandidate, ...]]`
- candidate는 resolved entity가 아니며 `match_kind`, deterministic score,
  source ID를 가진다.

- [ ] **Step 1: candidate 순서·상한·무결성 테스트를 쓴다**

```python
def test_semantic_candidates_are_stable_and_bounded(snapshot, normalized) -> None:
    first = generate_semantic_candidates(normalized, snapshot)
    second = generate_semantic_candidates(normalized, snapshot)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert all(len(group.items) <= 5 for group in first.by_mention)
    assert first.total_count <= 80


def test_risk_grade_keeps_both_semantic_candidates(snapshot) -> None:
    result = candidates_for("위험등급", snapshot)
    assert [item.semantic_id for item in result] == [
        "credit_grade",
        "product_risk_grade",
    ]
```

- [ ] **Step 2: batch entity query의 RED test를 쓴다**

합성 PostgreSQL fixture에 exact identifier, exact name, alias, trigram 후보를
넣고 한 batch 호출이 모든 mention을 반환하는지 검사한다. 같은 score는
`entity_id ASC`로 정렬하고 cutoff 밖 alias는 제외한다.

```python
@pytest.mark.postgres
async def test_entity_search_batches_mentions_and_pins_dataset(
    migrated_engine, seeded_entities,
) -> None:
    result = await EntityCandidateRepository(migrated_engine).search_batch(
        seeded_entities.dataset_version,
        (mention("m1", "005930"), mention("m2", "삼성전자")),
    )
    assert result["m1"][0].match_kind == "exact_identifier"
    assert result["m2"][0].entity_id == seeded_entities.samsung_id
    assert all(len(items) <= 5 for items in result.values())
```

- [ ] **Step 3: RED를 확인한다**

```bash
python3.12 -m pytest tests/intent/test_candidates.py -q
python3.12 -m pytest tests/db/test_intent_entity_repository.py -q
```

두 번째 명령은 명시적 test PostgreSQL이 없으면 skip, 있으면 RED여야 한다.

- [ ] **Step 4: semantic retrieval을 최소 구현한다**

우선순위와 tie break는 다음으로 고정한다.

```python
MATCH_PRIORITY = {
    "canonical_id": 0,
    "direct_alias": 1,
    "group_alias": 2,
    "ambiguous_alias": 3,
    "trigram": 4,
}
```

trigram score는 lowercase normalized code-point trigram Jaccard를 사용한다.
threshold는 `candidate_policy_version`에 포함하고 resolve 판정에는 사용하지
않는다. exact와 fuzzy 중복은 semantic ID 기준으로 가장 높은 우선순위만
보존한다.

- [ ] **Step 5: dataset-pinned entity batch repository를 구현한다**

한 transaction과 bounded query set 안에서 다음 순서로 합친다.

1. `catalog.identifier` exact value
2. `catalog.entity.normalized_name` exact
3. `catalog.alias.normalized_alias_text` exact and cutoff-valid
4. pg_trgm similarity candidate and cutoff-valid

`catalog.product`는 product family hint만 붙인다. model은 candidate ID를
selection hint로만 반환하고 canonical resolution status를 바꾸지 못한다.
DB 오류는 빈 결과가 아니라 `RESOLVER_CATALOG_UNAVAILABLE`을 발생시킨다.

- [ ] **Step 6: unit·PostgreSQL GREEN을 확인한다**

```bash
python3.12 -m pytest tests/intent/test_candidates.py -q
python3.12 -m pytest tests/db/test_intent_entity_repository.py -q
```

- [ ] **Step 7: Task 4를 커밋한다**

```bash
git add src/financial_agent/intent/candidates.py \
  src/financial_agent/intent/entity_repository.py \
  tests/intent/test_candidates.py tests/db/test_intent_entity_repository.py
git diff --cached --check
git diff --cached
git commit -m "feat: generate bounded intent candidates"
```

---

### Task 5: ResolverBuildManifest와 요청별 ResolverView를 만든다

**Files:**

- Create: `src/financial_agent/intent/view.py`
- Create: `tests/intent/test_view.py`

**Interfaces:**

- `build_manifest(snapshot, versions) -> ResolverBuildManifest`
- `build_resolver_view(context, normalized, literals, semantic_candidates, entity_candidates, manifest, active_dataset_pin) -> ResolverView`
- ResolverView는 four families, eight actions, relevant concepts, relation type
  constraints, literals, entity candidates, 짧은 정의만 포함한다.

`view.py`는 다음 immutable runtime pin을 함께 정의한다.

```python
class ActiveDatasetPin(ContractModel):
    dataset_version: Identifier
    manifest_hash: Sha256Hex
```

- [ ] **Step 1: manifest mismatch와 deterministic view 테스트를 쓴다**

```python
def test_view_is_byte_reproducible(resolver_inputs) -> None:
    first = build_resolver_view(**resolver_inputs)
    second = build_resolver_view(**resolver_inputs)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_view_rejects_dataset_manifest_mismatch(resolver_inputs) -> None:
    resolver_inputs["active_dataset_pin"] = ActiveDatasetPin(
        dataset_version="different-version",
        manifest_hash="f" * 64,
    )
    with pytest.raises(ResolverInvariantError, match="CATALOG_VERSION_MISMATCH"):
        build_resolver_view(**resolver_inputs)
```

- [ ] **Step 2: RED를 확인한다**

```bash
python3.12 -m pytest tests/intent/test_view.py -q
```

- [ ] **Step 3: manifest build와 pin 검증을 구현한다**

manifest는 config bytes, TBox·SHACL aggregate hashes, code version constants를
받아 만든다. `ActiveDatasetPin(dataset_version, manifest_hash)`은 호출자가
제공하며 RequestContext의 dataset version과 다르거나 값이 비어 있으면 model
호출 전 실패시킨다.

```python
NORMALIZER_VERSION = "intent-normalizer-v1"
CANDIDATE_POLICY_VERSION = "intent-candidate-v1"
RESOLVER_SCHEMA_VERSION = "1.0"
PROMPT_VERSION = "intent-resolver-ko-v1"
ADAPTER_VERSION = "clova-chat-v3-structured-v1"
```

- [ ] **Step 4: bounded view build를 구현한다**

모든 collection은 stable ID로 정렬한다. mention당 5, semantic 전체 80을
넘으면 우선순위가 낮은 fuzzy candidate부터 제거하며 exact candidate를 제거해
상한을 맞추지 않는다. exact만으로 상한을 넘으면
`RESOLVER_VIEW_LIMIT_EXCEEDED` internal invariant로 실패한다.

- [ ] **Step 5: prompt에 ontology 전체가 들어가지 않음을 검사한다**

test는 `ResolverView` serialized bytes에 TBox 원문, SHACL 원문, DB column,
source locator가 없고 요청에 무관한 concept ID가 없는지 확인한다.

- [ ] **Step 6: GREEN을 확인하고 커밋한다**

```bash
python3.12 -m pytest tests/intent/test_view.py \
  tests/intent/test_catalog.py tests/intent/test_candidates.py -q
git add src/financial_agent/intent/view.py tests/intent/test_view.py
git diff --cached --check
git diff --cached
git commit -m "feat: build bounded resolver views"
```

---

### Task 6: HCX Structured Output Prompt와 1회 호출 Adapter를 구현한다

**Files:**

- Create: `src/financial_agent/intent/config.py`
- Create: `src/financial_agent/intent/errors.py`
- Create: `src/financial_agent/intent/prompt.py`
- Create: `src/financial_agent/intent/clova.py`
- Create: `tests/intent/test_prompt.py`
- Create: `tests/intent/test_clova.py`

**Interfaces:**

- `build_prompt(context, view) -> ResolverPromptEnvelope`
- `build_clova_response_schema(view) -> dict[str, object]`
- `ClovaStructuredOutputAdapter.invoke(envelope, timeout_seconds) -> ModelInvocationResult`
- adapter는 retry하지 않고 `MODEL_TIMEOUT`, `MODEL_RATE_LIMITED`,
  `MODEL_PROVIDER_UNAVAILABLE`, `MODEL_CONFIGURATION_INVALID`,
  `MODEL_SCHEMA_INVALID`만 typed error로 반환한다.

구현 시점 API 사실은 Naver Cloud 공식
[Structured Outputs](https://api.ncloud-docs.com/docs/en/clovastudio-chatcompletionsv3-so)
문서로 다시 확인한다. 현재 문서는 v3 POST endpoint, JSON Schema 기반
`responseFormat`, structured output과 thinking/function calling의 동시 사용
금지를 명시한다.

- [ ] **Step 1: 요청 body·보안·호출 횟수 테스트를 쓴다**

HTTPX `MockTransport`로 request를 캡처한다.

```python
@pytest.mark.asyncio
async def test_clova_adapter_sends_one_structured_request(prompt, config) -> None:
    transport, calls = successful_transport(valid_draft_json())
    adapter = ClovaStructuredOutputAdapter(config, transport=transport)
    result = await adapter.invoke(prompt, timeout_seconds=4.0)

    assert len(calls) == 1
    body = json.loads(calls[0].content)
    assert body["responseFormat"]["type"] == "json"
    assert "thinking" not in body
    assert "tools" not in body
    assert result.content == valid_draft_json()
```

API key가 exception, repr, captured telemetry에 나오지 않는 test와 401/403,
429, provider 5xx, connection error, timeout, non-JSON response test도 먼저 쓴다.

- [ ] **Step 2: dynamic schema가 offered ID만 허용하는 RED test를 쓴다**

```python
def test_response_schema_enums_only_offered_semantic_ids(view) -> None:
    schema = build_clova_response_schema(view)
    enums = collect_enums(schema)
    assert "aum" in enums
    assert "invented_metric" not in enums
    assert_no_keywords(schema, {"pattern", "$ref", "$defs", "additionalProperties"})
```

- [ ] **Step 3: RED를 확인한다**

```bash
python3.12 -m pytest tests/intent/test_prompt.py tests/intent/test_clova.py -q
```

- [ ] **Step 4: prompt와 HCX-compatible schema를 구현한다**

system message는 역할, 허용 출력, 금지된 추측, 원문 evidence 의무만 가진다.
question, segment, alias, label은 하나의 JSON data envelope로 user message에
직렬화한다. 사용자 문자열을 system prompt에 interpolation하지 않는다.

요청별 schema는 HCX 공식 지원 범위인 `type`, `properties`, `required`,
`items`, `minItems`, `maxItems`, `minimum`, `maximum`, `enum`, `anyOf`,
`format`만 사용한다. 모든 object field는 required이고 local Pydantic validation이
unknown field를 다시 막는다.

- [ ] **Step 5: 환경 설정과 async adapter를 구현한다**

```python
@dataclass(frozen=True, slots=True)
class ClovaResolverConfig:
    api_key: SecretStr
    base_url: str
    model_id: str
    max_completion_tokens: int = 4096
    temperature: float = 0.0
    top_p: float = 0.1
    top_k: int = 1
    repetition_penalty: float = 1.0
```

환경 변수는 `FINANCIAL_AGENT_CLOVA_API_KEY`,
`FINANCIAL_AGENT_CLOVA_BASE_URL`, `FINANCIAL_AGENT_INTENT_MODEL_ID`다. API key와
model ID는 code·fixture에 실제 값으로 저장하지 않는다. URL은 HTTPS만 허용한다.

request는 `Authorization: Bearer ...`,
`X-NCP-CLOVASTUDIO-REQUEST-ID`, `Content-Type: application/json`을 사용하고
`/v3/chat-completions/{quoted_model_id}`로 보낸다. response의
`result.message.content`와 usage만 추출한다. `thinking`과 function calling을
동시에 보내지 않는다.

401/403과 지원하지 않는 model·request 설정은
`MODEL_CONFIGURATION_INVALID`, 429는 `MODEL_RATE_LIMITED`, connection error와
provider 5xx는 `MODEL_PROVIDER_UNAVAILABLE`, timeout은 `MODEL_TIMEOUT`, 성공
응답의 content shape·JSON 오류는 `MODEL_SCHEMA_INVALID`로만 매핑한다.

- [ ] **Step 6: adapter GREEN을 확인한다**

```bash
python3.12 -m pytest tests/intent/test_prompt.py tests/intent/test_clova.py -q
```

live API는 이 Task에서 호출하지 않는다.

- [ ] **Step 7: Task 6을 커밋한다**

```bash
git add src/financial_agent/intent/config.py \
  src/financial_agent/intent/errors.py src/financial_agent/intent/prompt.py \
  src/financial_agent/intent/clova.py tests/intent/test_prompt.py \
  tests/intent/test_clova.py
git diff --cached --check
git diff --cached
git commit -m "feat: add clova intent adapter"
```

---

### Task 7: 의미 ID·Span·Applicability·Tag Validator를 구현한다

**Files:**

- Create: `src/financial_agent/intent/validation.py`
- Create: `tests/intent/test_validation.py`

**Interfaces:**

- `validate_semantics(draft, context, normalized, view, catalog) -> SemanticValidationState`
- planner contract 위반은 `ResolverContractError`를 raise한다.
- valid OOD·ambiguity는 exception이 아니라 typed `ResolutionIssue`다.

- [ ] **Step 1: unknown ID와 원문 span 음성 test를 쓴다**

```python
def test_unknown_id_is_contract_failure(validation_inputs) -> None:
    draft = replace_metric(validation_inputs.draft, "invented_metric")
    with pytest.raises(ResolverContractError, match="MODEL_UNKNOWN_ID"):
        validate_semantics(draft=draft, **validation_inputs.rest)


def test_span_text_must_match_original_segment(validation_inputs) -> None:
    draft = replace_span_text(validation_inputs.draft, "다른 문장")
    with pytest.raises(ResolverContractError, match="LITERAL_SPAN_MISMATCH"):
        validate_semantics(draft=draft, **validation_inputs.rest)
```

- [ ] **Step 2: applicability·relation·tag test를 쓴다**

ETF 질문에서 `credit_grade`를 확정하거나 `managedBy` 방향을 뒤집은 draft는
contract failure여야 한다. multi-frame, two-family, context link, period가 있는
valid draft의 final tag는 stable sort로 다음을 포함해야 한다.

```python
assert {
    SemanticTag.CROSS_FAMILY,
    SemanticTag.MULTI_STEP,
    SemanticTag.CONTEXT_DEPENDENT,
    SemanticTag.TEMPORAL,
} <= set(state.final_tags)
assert state.final_tags == tuple(sorted(state.final_tags, key=lambda item: item.value))
```

- [ ] **Step 3: RED를 확인한다**

```bash
python3.12 -m pytest tests/intent/test_validation.py -q
```

- [ ] **Step 4: 고정 순서 validator를 구현한다**

다음 순서를 코드의 named stage로 유지한다.

```python
VALIDATION_STAGES = (
    "schema",
    "offered_ids",
    "evidence_spans",
    "applicability",
    "ontology_relations",
    "literal_types",
    "frame_order",
    "slot_mutations",
    "tag_derivation",
    "resolution_status",
)
```

이 Task는 앞의 여섯 단계와 deterministic tag derivation을 구현한다. ordering
canonicalization과 exact duplicate 제거만 허용하고 unknown ID 교체, critical
slot 추론, antecedent 선택은 금지한다.

- [ ] **Step 5: semantic resolution precedence를 고정한다**

contract-valid issue가 여러 개면 top-level status는 다음 우선순위다.

```python
STATUS_PRECEDENCE = (
    ResolutionStatus.UNMAPPED,
    ResolutionStatus.CONTEXT_UNRESOLVED,
    ResolutionStatus.AMBIGUOUS,
    ResolutionStatus.RESOLVED,
)
```

policy tag는 status를 바꾸지 않는다. `FUTURE_FORECAST`를 정확히 탐지한 질문은
Phase 1에서 `resolved`일 수 있다.

- [ ] **Step 6: GREEN을 확인하고 커밋한다**

```bash
python3.12 -m pytest tests/intent/test_validation.py \
  tests/intent/test_contracts.py tests/intent/test_catalog.py -q
git add src/financial_agent/intent/validation.py \
  tests/intent/test_validation.py
git diff --cached --check
git diff --cached
git commit -m "feat: validate intent semantics"
```

---

### Task 8: 한국어 Reference·ContextLink·SlotMutation을 fail-closed로 검증한다

**Files:**

- Create: `src/financial_agent/intent/context.py`
- Create: `tests/intent/test_context.py`

**Interfaces:**

- `validate_context_graph(state: SemanticValidationState) -> ContextValidationState`
- `finalize_resolution(context_state, metadata) -> ValidatedIntentResolution`
- v1은 backward acyclic link만 허용한다.

- [ ] **Step 1: 대표 follow-up context test를 쓴다**

```python
def test_plural_followup_consumes_prior_top_k(context_inputs) -> None:
    resolution = validate_and_finalize(
        "AUM 상위 5개 ETF 알려줘. 그 상품 중 1년 수익률 1위는?",
        draft_for_top5_then_return_rank(),
        context_inputs,
    )
    link = resolution.context_links[0]
    assert link.link_type is ContextLinkType.CONSUME_RESULT_SET
    assert link.source_role is SourceRole.TOP_K_PRODUCTS
    assert link.selector is Selector.ALL
    assert link.producer_frame_id == "f1"
    assert link.consumer_frame_id == "f2"
```

- [ ] **Step 2: 잘못된 문맥 graph 음성 test를 쓴다**

다음을 각각 독립 test로 만든다.

- forward link
- f1 ↔ f2 cycle
- many source를 selector 없이 single target으로 소비
- 존재하지 않는 producer role
- 단수 `이거`가 두 후보 중 하나를 근거 없이 선택
- anchor 없는 similarity
- 서로 충돌하는 explicit slot과 carryover

모두 `INVALID_CONTEXT_GRAPH` contract error 또는
`REFERENCE_AMBIGUOUS`/`REFERENCE_UNRESOLVED` semantic issue 중 설계된 한
종류로만 귀결되어야 한다.

- [ ] **Step 3: RED를 확인한다**

```bash
python3.12 -m pytest tests/intent/test_context.py -q
```

- [ ] **Step 4: type·cardinality·selector 검증을 구현한다**

`producer.ordinal < consumer.ordinal`, DAG acyclic, source role의 target kind와
cardinality, selector compatibility를 모두 검사한다. `rank_position`과 `top_n`은
정규화기가 제공한 literal ID를 요구한다. 실제 product ID나 result row는
ContextLink에 넣지 않는다.

- [ ] **Step 5: mutation과 precedence를 구현한다**

허용 mutation은 `CARRYOVER`, `UPDATE`, `DELETE`, `DONTCARE`뿐이다. 해석
우선순위는 아래 exact order다.

```python
SLOT_PRECEDENCE = (
    "explicit_current_evidence",
    "validated_context_link",
    "explicit_carryover",
    "phase2_default",
)
```

Phase 1은 마지막 default를 적용하지 않고 자리만 남긴다. 충돌은 임의 선택하지
않고 issue를 만든다.

- [ ] **Step 6: zero anaphora·bridging·former/latter case를 GREEN으로 만든다**

최소 다음 표현을 test한다.

```text
연간수익률은? / 위험등급도 보여줘 / 그 운용사는? / 전자는? / 후자는? /
나머지 상품은? / 각 상품의 수익률은? / 그 결과의 근거는?
```

- [ ] **Step 7: 전체 validator 회귀 후 커밋한다**

```bash
python3.12 -m pytest tests/intent/test_context.py \
  tests/intent/test_validation.py -q
git add src/financial_agent/intent/context.py tests/intent/test_context.py
git diff --cached --check
git diff --cached
git commit -m "feat: validate typed intent context"
```

---

### Task 9: 한 번의 모델 호출로 Phase 1 Pipeline을 조합한다

**Files:**

- Create: `src/financial_agent/intent/service.py`
- Create: `tests/intent/test_service.py`

**Interfaces:**

- `IntentResolverService.prepare(context) -> PreparedResolutionRequest`
- `IntentResolverService.resolve_once(context) -> ResolutionAttempt`
- `IntentResolverService.validate_response(prepared, content) -> ValidatedIntentResolution`
- `build_repair_envelope(prepared, failure) -> ResolverPromptEnvelope`
- service는 repair envelope를 만들 수 있지만 두 번째 call을 실행하지 않는다.

- [ ] **Step 1: one-call·no-retry integration test를 쓴다**

```python
@pytest.mark.asyncio
async def test_resolve_once_calls_model_exactly_once(service_fixture) -> None:
    result = await service_fixture.service.resolve_once(service_fixture.context)
    assert service_fixture.adapter.call_count == 1
    assert result.resolution.resolution_status is ResolutionStatus.RESOLVED


@pytest.mark.asyncio
async def test_schema_failure_does_not_retry_inside_service(service_fixture) -> None:
    service_fixture.adapter.content = "{}"
    with pytest.raises(ResolverContractError, match="MODEL_SCHEMA_INVALID"):
        await service_fixture.service.resolve_once(service_fixture.context)
    assert service_fixture.adapter.call_count == 1
```

- [ ] **Step 2: 단계별 latency와 raw-output 비노출 test를 쓴다**

`ResolutionAttempt.telemetry`는 normalization, candidate, model, validation
milliseconds, candidate/frame/link counts, usage, stable code만 가진다. raw
question과 raw model content가 telemetry `repr`과 mapping에 없어야 한다.

- [ ] **Step 3: RED를 확인한다**

```bash
python3.12 -m pytest tests/intent/test_service.py -q
```

- [ ] **Step 4: prepare·invoke·validate를 명시적으로 분리해 구현한다**

```python
class IntentResolverService:
    async def prepare(self, context: RequestContext) -> PreparedResolutionRequest:
        ...

    async def resolve_once(self, context: RequestContext) -> ResolutionAttempt:
        prepared = await self.prepare(context)
        model_result = await self._adapter.invoke(
            prepared.prompt,
            timeout_seconds=self._remaining_model_seconds(context),
        )
        resolution = self.validate_response(prepared, model_result.content)
        return ResolutionAttempt(resolution, model_result.usage, prepared.telemetry)
```

`prepare`는 active dataset/catalog pin mismatch와 입력 상한을 model 전에
실패시킨다. provider timeout/rate limit을 semantic OOD로 변환하지 않는다.

- [ ] **Step 5: repair envelope 경계를 구현한다**

repair 입력은 original prompt hash, stable failure code, local validator가
허용한 짧은 correction instruction, 같은 ResolverView와 같은 response schema만
포함한다. invalid raw content 전체를 prompt에 다시 넣지 않는다. 실제 재호출은
Phase 3 Orchestrator 책임이다.

- [ ] **Step 6: service와 전체 unit GREEN을 확인한다**

```bash
python3.12 -m pytest tests/intent -m "not clova_integration" -q
python3.12 scripts/export_intent_schemas.py --check
```

- [ ] **Step 7: Task 9를 커밋한다**

```bash
git add src/financial_agent/intent/service.py tests/intent/test_service.py
git diff --cached --check
git diff --cached
git commit -m "feat: assemble intent resolver pipeline"
```

---

### Task 10: intent_resolution 감사 Artifact와 Provenance Migration을 구현한다

**Files:**

- Create: `alembic/versions/0007_intent_resolution_artifact.py`
- Modify: `scripts/verify_database_migrations.py`
- Modify: `src/financial_agent/db/schema/operations.py`
- Modify: `src/financial_agent/db/repositories/artifacts.py`
- Modify: `src/financial_agent/db/repositories/operations.py`
- Modify: `tests/db/test_artifact_repository.py`
- Modify: `tests/db/test_migration_cycle.py`
- Modify: `tests/db/test_foundation_migration.py`
- Modify: `tests/db/test_ncp_preflight.py`
- Modify: `schemas/postgresql/v1/database-objects.json`

**Interfaces:**

- `ArtifactType`에 `intent_resolution` 한 값만 추가한다.
- `intent_resolution`은 model_id·prompt_version pair가 필수다.
- `query_plan`은 Phase 2 compiler output이므로 model metadata가 금지된다.
- invalid raw output은 valid artifact가 아니며 FailureEvent optional hash·size에만
  기록한다.

- [ ] **Step 1: 새 artifact provenance RED test를 쓴다**

```python
@pytest.mark.postgres
async def test_intent_resolution_requires_model_provenance(
    artifact_repository, validated_resolution,
) -> None:
    with pytest.raises(ArtifactValidationError, match="MODEL_METADATA_REQUIRED"):
        await artifact_repository.append(
            "intent_resolution", validated_resolution
        )

    artifact_id = await artifact_repository.append(
        "intent_resolution",
        validated_resolution,
        model_id="synthetic-model",
        prompt_version="intent-resolver-ko-v1",
    )
    assert await artifact_repository.get(validated_resolution.run_id, artifact_id) \
        == validated_resolution
```

QueryPlan에 model metadata를 주면 `MODEL_METADATA_FORBIDDEN`, 주지 않으면
성공해야 한다.

- [ ] **Step 2: invalid-attempt 감사 RED test를 쓴다**

`FailureEventRecord`에 optional `payload_hash`, `payload_size_bytes`를 추가하고
hash 형식과 nonnegative size를 DB에서 검사한다. raw payload column은 만들지
않는다.

- [ ] **Step 3: RED를 확인한다**

```bash
python3.12 -m pytest tests/db/test_artifact_repository.py \
  tests/db/test_migration_cycle.py -q
```

- [ ] **Step 4: migration 0007을 구현한다**

upgrade는 다음 변경만 수행한다.

1. artifact type check에 `intent_resolution` 추가
2. model metadata check를 아래 의미로 교체
3. `derive_request_artifact`가 resolution_id를 contract_object_id로 파생
4. failure_event에 optional hash·size와 check 추가
5. append function의 existing-conflict 검사는 provenance까지 동일해야 idempotent

```sql
(model_id IS NULL) = (prompt_version IS NULL)
AND (
  artifact_type = 'intent_resolution' AND model_id IS NOT NULL
  OR artifact_type = 'answer_plan'
  OR artifact_type NOT IN ('intent_resolution', 'answer_plan')
     AND model_id IS NULL
)
```

downgrade는 intent_resolution row와 payload audit column 값이 존재하면 데이터
손실을 감추지 않고 stable error로 차단한다.

- [ ] **Step 5: SQLAlchemy model과 repository를 동기화한다**

`ARTIFACT_MODELS["intent_resolution"] = ValidatedIntentResolution`을 추가하고
metadata rule을 migration과 byte-for-byte 같은 의미로 구현한다. QueryPlan
기존 fixture/test 호출은 model metadata 없이 저장하도록 고친다.

- [ ] **Step 6: migration cycle·manifest·권한을 검증한다**

```bash
python3.12 scripts/verify_database_migrations.py
python3.12 -m pytest tests/db/test_artifact_repository.py \
  tests/db/test_migration_cycle.py tests/db/test_database_permissions.py -q
python3.12 scripts/export_database_objects.py \
  --database-url-env FINANCIAL_AGENT_TEST_DATABASE_URL
python3.12 scripts/export_database_objects.py --check \
  --database-url-env FINANCIAL_AGENT_TEST_DATABASE_URL
```

Expected: Alembic head `0007`, runtime은 artifact append와 failure event insert만
허용하며 UPDATE/DELETE 불변 trigger는 유지된다.

- [ ] **Step 7: Task 10을 커밋한다**

```bash
git add alembic/versions/0007_intent_resolution_artifact.py \
  scripts/verify_database_migrations.py \
  src/financial_agent/db/schema/operations.py \
  src/financial_agent/db/repositories/artifacts.py \
  src/financial_agent/db/repositories/operations.py tests/db \
  schemas/postgresql/v1/database-objects.json
git diff --cached --check
git diff --cached
git commit -m "feat: persist validated intent resolutions"
```

---

### Task 11: 단계 분리 Evaluation Harness와 Korean Held-out Set을 만든다

**Files:**

- Create: `src/financial_agent/intent/evaluation.py`
- Create: `scripts/evaluate_intent_resolver.py`
- Create: `tests/evaluation/__init__.py`
- Create: `tests/evaluation/intent/__init__.py`
- Create: `tests/evaluation/intent/intent_resolution_regression.json`
- Create: `tests/evaluation/intent/intent_resolution_heldout_ko.json`
- Create: `tests/evaluation/intent/test_intent_evaluation.py`
- Modify: `.gitignore`

**Interfaces:**

- `evaluate_candidates(cases, predictions) -> CandidateMetrics`
- `evaluate_frames(cases, predictions) -> FrameMetrics`
- `evaluate_context(cases, predictions) -> ContextMetrics`
- `evaluate_ood(cases, predictions) -> OodMetrics`
- CLI mode: `deterministic`, `decoupled`, `full`, `live`

- [ ] **Step 1: metric 공식의 RED unit test를 쓴다**

```python
def test_metrics_separate_candidate_frame_context_and_ood() -> None:
    report = evaluate_predictions(synthetic_cases(), synthetic_predictions())
    assert report.candidate_recall_at_5 == Decimal("0.99")
    assert report.joint_frame_exact_match == Decimal("0.90")
    assert report.context_link_exact_match == Decimal("0.95")
    assert report.ood_false_fast_rate == Decimal("0.02")
```

test data는 정확한 분모가 나오도록 100개 synthetic label을 code에서 생성한다.
float 대신 integer numerator/denominator와 Decimal을 사용한다.

- [ ] **Step 2: fixture leakage·분포 gate의 RED test를 쓴다**

regression file은 기존 52 case ID와 expected axes/context label만 가진다. 질문
원문은 gold에서 offline loader가 읽어도 되지만 production `src/.../intent`
module은 이 loader를 import하지 않는다.

blind Korean held-out file은 최소 160개 새 질문을 아래 고정 분포로 가진다.

```text
40 paraphrase·spacing·particle
30 compound·no-punctuation·correction
40 demonstrative·ellipsis·plural/singular·former/latter·bridging
30 OOD: vocabulary 10, domain 10, context 10
20 policy·prompt-injection·Unicode·oversized-boundary negative
```

각 case는 `case_id`, `question`, `segments`, expected frames, expected context
links, expected resolution status, expected tags를 가진다. 실제 상품·고객정보나
organizer row를 포함하지 않는다.

- [ ] **Step 3: RED를 확인한다**

```bash
python3.12 -m pytest tests/evaluation/intent/test_intent_evaluation.py -q
```

- [ ] **Step 4: evaluator와 CLI를 구현한다**

`deterministic`은 catalog·normalizer·candidate만, `decoupled`는 gold candidate
view를 주입한 draft 평가, `full`은 저장된 prediction file, `live`는 HCX adapter를
사용한다. 어떤 mode도 QueryPlan·SQL execution 점수를 섞지 않는다.

report에는 아래를 포함한다.

```text
candidate recall@1/@3/@5, joint frame EM, action/family/entity-type/slot F1,
reference/link/selector/cardinality/mutation EM, OOD confusion,
unknown-ID acceptance, invalid-graph acceptance, schema validity, repair rate,
p50/p95 latency, prompt/completion tokens, stable error counts
```

- [ ] **Step 5: blind fixture를 동결한다**

두 fixture 작성 후 아래 명령의 실제 SHA-256을
`test_intent_evaluation.py`의 상수로 기록한다.

```bash
shasum -a 256 tests/evaluation/intent/intent_resolution_regression.json \
  tests/evaluation/intent/intent_resolution_heldout_ko.json
```

prompt/model tuning 후 같은 fixture label을 수정하지 않는다. 변경 필요 시 새
version file을 만들고 이전 file을 보존한다.

- [ ] **Step 6: deterministic evaluation GREEN을 확인한다**

```bash
python3.12 -m pytest tests/evaluation/intent/test_intent_evaluation.py -q
python3.12 scripts/evaluate_intent_resolver.py \
  --mode deterministic \
  --output build/reports/intent-resolver-deterministic.json
```

`build/reports/`는 `.gitignore`에 추가하고 report에 raw model response나 key가
없음을 검사한다.

- [ ] **Step 7: Task 11을 커밋한다**

```bash
git add src/financial_agent/intent/evaluation.py \
  scripts/evaluate_intent_resolver.py tests/evaluation .gitignore
git diff --cached --check
git diff --cached
git commit -m "test: add intent resolver evaluation harness"
```

---

### Task 12: Linux·PostgreSQL·Live HCX Gate를 실행하고 승격 여부를 기록한다

**Files:**

- Create: `docker/resolver-check.Dockerfile`
- Modify: `docker/postgres.compose.yml`
- Modify: `.dockerignore`
- Create: `tests/intent/test_container_verification.py`
- Create after measured run: `docs/planning/reports/2026-08-31-intent-resolver-phase1-verification.md`
- Modify after measured run: `docs/planning/STATUS.md`

**Interfaces:**

- non-live gate는 자격증명 없이 재현 가능하다.
- live gate는 명시적 환경변수와 비용 승인 없이는 skip한다.
- 승격은 8개 promotion gate를 모두 만족할 때만 가능하다.

- [ ] **Step 1: container boundary RED test를 추가한다**

`tests/intent/test_container_verification.py`를 만들어 Dockerfile이
`requirements/resolver.lock`, `config/intent`, `ontology`, `schemas`, `src`,
`tests`, internal schema check를 포함하는지 검사한다. `.env`, `data/`, build
report, raw response는 copy 대상이 아니어야 한다.

- [ ] **Step 2: resolver verification image를 구현한다**

```dockerfile
FROM --platform=linux/amd64 python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_CONSTRAINT=/app/requirements/resolver.lock \
    FINANCIAL_AGENT_PROJECT_ROOT=/app

WORKDIR /app
COPY pyproject.toml ./
COPY alembic.ini ./
COPY requirements/ ./requirements/
COPY alembic/ ./alembic/
COPY config/intent/ ./config/intent/
COPY docker/ ./docker/
COPY ontology/ ./ontology/
COPY schemas/ ./schemas/
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
RUN python -m pip install ".[dev,storage,graph,resolver]"
CMD ["sh", "-c", "python scripts/export_intent_schemas.py --check && python -m pytest tests/intent tests/evaluation/intent -m 'not postgres and not clova_integration' -q && if [ -n \"$FINANCIAL_AGENT_TEST_DATABASE_URL\" ]; then python scripts/verify_database_migrations.py && python -m pytest tests/db/test_intent_entity_repository.py tests/db/test_artifact_repository.py -q; fi"]
```

Compose의 `resolver-check` service는 위 image에 disposable PostgreSQL URL만
주입한다. live CLOVA key와 model ID는 image build·Compose environment에 넣지
않는다.

`docker/postgres.compose.yml`에는 기존 postgres와 db-check를 보존하고 다음
service만 추가한다.

```yaml
  resolver-check:
    platform: linux/amd64
    build:
      context: ..
      dockerfile: docker/resolver-check.Dockerfile
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      FINANCIAL_AGENT_TEST_DATABASE_URL: postgresql+psycopg://financial_agent_test:financial_agent_test@postgres:5432/financial_agent_test
```

- [ ] **Step 3: narrow-to-broad local gate를 실행한다**

```bash
python3.12 -m pytest tests/intent -m "not clova_integration" -q
python3.12 -m pytest tests/evaluation/intent -q
python3.12 -m pytest tests/contracts -q
python3.12 scripts/export_contract_schemas.py --check
python3.12 scripts/export_intent_schemas.py --check
python3.12 -m pytest tests/db \
  -m "not performance and not ncp_integration" -q
python3.12 -m pytest \
  -m "not postgres and not organizer_data and not object_storage and not official_data and not ncp_integration and not jena_integration and not clova_integration" -q
```

PostgreSQL test는 disposable DB만 사용한다. 기존 organizer/official data live
test는 이 Phase의 완료 근거로 실행하지 않는다.

- [ ] **Step 4: Linux/amd64 image와 migration cycle을 검증한다**

```bash
docker build --platform linux/amd64 \
  -f docker/resolver-check.Dockerfile -t financial-agent-resolver-check .
docker run --rm financial-agent-resolver-check
docker compose -f docker/postgres.compose.yml up \
  --build --abort-on-container-exit --exit-code-from resolver-check resolver-check
```

이미지·container·volume은 검증 후 제거하되 광범위한 prune은 하지 않는다.

- [ ] **Step 5: live HCX 실행 전 사용자 checkpoint를 지킨다**

다음 세 조건이 모두 충족되기 전에는 live call을 실행하지 않는다.

1. 사용자가 live API 비용과 호출을 명시적으로 승인
2. `FINANCIAL_AGENT_CLOVA_API_KEY`가 Git 밖 runtime environment에 존재
3. 공식 문서 preflight에서 configured model의 Structured Outputs 지원 확인

실행 명령은 다음 하나다.

```bash
python3.12 scripts/evaluate_intent_resolver.py \
  --mode live \
  --dataset tests/evaluation/intent/intent_resolution_heldout_ko.json \
  --output build/reports/intent-resolver-live.json
```

각 case는 normal path 한 번만 호출한다. repair benchmark는 별도 `--repair`
실행으로 구분하고 request-wide 최대 1회를 넘지 않는다.

- [ ] **Step 6: promotion gate를 자동 판정한다**

report validator는 아래 exact gate를 검사한다.

```text
unknown registered-ID acceptance = 0
invalid context-graph acceptance = 0
deterministic candidate reproducibility = 100%
candidate recall@5 >= 99%
first-pass structured-output validity >= 99%
held-out joint frame exact match >= 90%
held-out context-link exact match >= 95%
OOD false-fast rate <= 2%
```

하나라도 실패하면 default 승격을 기록하지 않는다. threshold·validator·gold
label을 완화하지 않고 confusion과 다음 실험만 기록한다.

- [ ] **Step 7: 측정 사실만 verification report와 STATUS에 기록한다**

report에는 commit, catalog/ontology/overlay/prompt/adapter/model/dataset hash,
실행 명령, pass/fail/skip, 지표, latency·token 집계, repair 수, known limitation을
쓴다. API key, raw response, raw chain of thought, request별 model output은 쓰지
않는다.

`docs/planning/STATUS.md`는 다음 중 실제 결과 하나만 기록한다.

- `Phase 1 implemented; promotion gates passed; Phase 2 design pending`
- `Phase 1 implemented; promotion blocked by <stable metric names>`
- `Phase 1 non-live verified; live benchmark not run`

- [ ] **Step 8: 최종 diff·secret·data gate를 실행한다**

```bash
git status --short
git diff --check
git diff --stat
git grep -n -E 'Authorization: Bearer [A-Za-z0-9]|BEGIN .*PRIVATE KEY|sk-[A-Za-z0-9]'
git diff --name-only --cached
```

`data/`, organizer PDF/workbook, `.env`, live report, cache, DB, N-Quads,
embedding, credential이 staged되지 않았는지 직접 확인한다.

- [ ] **Step 9: Task 12를 커밋한다**

```bash
git add docker/resolver-check.Dockerfile docker/postgres.compose.yml \
  .dockerignore tests/intent/test_container_verification.py \
  docs/planning/reports/2026-08-31-intent-resolver-phase1-verification.md \
  docs/planning/STATUS.md
git diff --cached --check
git diff --cached
git status --short
git commit -m "docs: record intent resolver verification"
```

live benchmark가 실행되지 않았다면 존재하지 않는 report path를 `git add`하지
말고 STATUS에 `live benchmark not run`만 기록한다.

---

## Phase 1 완료 정의

Phase 1 구현은 다음이 모두 참일 때만 완료다.

1. production catalog build가 gold 질문 파일 없이 동일 hash로 성공한다.
2. model-facing Draft와 persisted Validated 계약이 strict Schema로 잠긴다.
3. 입력 정규화·literal·candidate·view가 결정론적으로 재현된다.
4. 정상 service가 model adapter를 정확히 한 번만 호출한다.
5. unknown ID·span·ontology·context graph 위반이 실행 전에 차단된다.
6. ambiguous·unmapped·context_unresolved가 provider failure와 구분된다.
7. intent_resolution artifact가 model/prompt/catalog/ontology provenance와 함께
   불변 저장되고 QueryPlan은 direct-model provenance를 갖지 않는다.
8. candidate, frame, context, OOD metric이 분리 측정된다.
9. non-live full gate가 통과하고 live 미실행 또는 실패 상태가 명시된다.
10. QueryPlan compiler와 Orchestrator 구현은 시작되지 않는다.

## Phase 2 진입 Gate

Phase 2 QueryPlan compiler 설계를 시작하기 전에 다음을 별도로 승인받는다.

- ValidatedIntentResolution의 context link, selector, slot mutation, frame
  dependency를 기존 `resolved_references`, `binding_specs`,
  `dependency_edges`, registered operation parameter로 내리는 compatibility
  matrix
- 표현 불가능한 의미가 있을 때 fail-closed할지 QueryPlan contract를 새 ADR로
  개정할지에 대한 결정
- archetype catalog, primitive registry, Fast/Compose/Explore/Abstain route와
  required-slot/default 정책

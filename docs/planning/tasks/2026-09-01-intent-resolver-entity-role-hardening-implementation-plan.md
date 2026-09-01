# Intent Resolver Entity Role Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all registered frame entity types reachable by HCX and validate relation subjects and objects against their correct ontology endpoints.

**Architecture:** ResolverView exposes the complete, sorted 20-type catalog registry while request-local candidates continue to bound entity identities. ProposalV2 and v2 artifacts carry explicit `frame_subject` or `relation_object` entity-hint roles; the deterministic assembler copies them and validation checks relation domain and range independently.

**Tech Stack:** Python 3.12, Pydantic strict contracts, pytest, generated JSON Schema, HyperCLOVA X HCX-007 Structured Outputs

**Spec:** `docs/planning/specs/2026-09-01-intent-resolver-entity-role-hardening-design.md`

## Global Constraints

- Preserve one normal-path HCX call and the existing request-wide repair budget.
- HCX may emit only server-offered type, relation, mention, entity, evidence, and reference IDs.
- Preserve v1 schemas and canonical serialization byte-for-byte.
- ProposalV2 is still unpromoted and undeployed, so harden the existing internal `2.0` contract in place; do not add a compatibility layer for the defective branch-only v2 shape.
- Bump `PROMPT_VERSION` from `intent-resolver-ko-v3` to `intent-resolver-ko-v4`; keep `ADAPTER_VERSION` unchanged because the HTTP envelope does not change.
- Do not change QueryPlan, the public API, database DDL, Alembic migrations, candidate scoring, or Orchestrator code.
- Do not add ontology classes or relations; the semantic catalog's current 20 entity types are authoritative.
- Do not read, print, stage, or commit credentials, `api.txt`, raw live output, organizer data, or generated runtime logs.
- Run the live 12-case HCX smoke only after every offline gate passes. Keep one-second pacing and write only a sanitized report under `/private/tmp`.

---

### Task 1: Expose the Complete Bounded Entity-Type Registry

**Files:**
- Modify: `src/financial_agent/intent/view.py`
- Modify: `src/financial_agent/intent/prompt.py`
- Modify: `tests/intent/test_view.py`
- Modify: `tests/intent/test_prompt.py`
- Modify: `tests/intent/view_fixtures.py`
- Modify: `tests/intent/test_assembler.py`
- Modify: `tests/intent/test_clova.py`
- Modify: `tests/intent/test_context.py`
- Modify: `tests/intent/test_validation.py`
- Modify: `tests/evaluation/intent/test_intent_evaluation.py`

**Interfaces:**
- Consumes: `SemanticCatalogSnapshot.entity_type_ids: tuple[str, ...]`
- Produces: `ResolverView.entity_type_ids: tuple[Identifier, ...]`
- Produces: `offered_entity_type_ids(view: ResolverView) -> tuple[str, ...]`
- Produces: HCX frame and hint type enums containing exactly the view's registered types

- [ ] **Step 1: Add failing ResolverView registry tests**

Add tests that assert the production builder projects the complete catalog and
that malformed direct construction fails:

```python
def test_resolver_view_offers_complete_sorted_catalog_entity_types(
    request_context, normalized_request, resolver_inputs, catalog, manifest, dataset_pin
) -> None:
    view = build_resolver_view(
        request_context,
        normalized_request,
        resolver_inputs.literals,
        resolver_inputs.semantic_candidates,
        resolver_inputs.entity_candidates,
        manifest,
        dataset_pin,
        catalog,
    )
    assert view.entity_type_ids == tuple(sorted(catalog.entity_type_ids))
    assert len(view.entity_type_ids) == 20
    assert offered_entity_type_ids(view) == view.entity_type_ids


def test_resolver_view_rejects_unsorted_or_duplicate_entity_type_registry(
    resolver_view: ResolverView,
) -> None:
    with pytest.raises(ValidationError, match="entity type IDs must be unique and sorted"):
        ResolverView.model_validate(
            resolver_view.model_dump(mode="json")
            | {"entity_type_ids": ["ETF", "AssetManager", "ETF"]}
        )
```

- [ ] **Step 2: Run the focused view tests and confirm RED**

Run:

```bash
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -m pytest \
  tests/intent/test_view.py -q
```

Expected: the new tests fail because `ResolverView` has no explicit registry and
`offered_entity_type_ids` still derives a request-local union.

- [ ] **Step 3: Implement the explicit registry projection**

Add the required field and invariant:

```python
class ResolverView(ContractModel):
    build_manifest: ResolverBuildManifest
    active_dataset_pin: ActiveDatasetPin
    product_family_ids: tuple[Identifier, ...]
    action_ids: tuple[Identifier, ...]
    entity_type_ids: tuple[Identifier, ...]
    # existing fields remain unchanged

    @model_validator(mode="after")
    def validate_entity_candidate_bounds(self) -> "ResolverView":
        if (
            not self.entity_type_ids
            or self.entity_type_ids != tuple(sorted(set(self.entity_type_ids)))
            or not set(self.entity_type_ids) <= APPROVED_RDF_TYPES
        ):
            raise ValueError("entity type IDs must be unique and sorted")
        # preserve the existing entity and axis checks
        return self


def offered_entity_type_ids(view: ResolverView) -> tuple[str, ...]:
    return view.entity_type_ids
```

Populate it only from the catalog:

```python
return ResolverView(
    build_manifest=manifest,
    active_dataset_pin=active_dataset_pin,
    product_family_ids=tuple(sorted(item.value for item in ProductFamily)),
    action_ids=tuple(sorted(item.value for item in IntentType)),
    entity_type_ids=tuple(sorted(catalog.entity_type_ids)),
    # existing projections
)
```

Update every direct `ResolverView` fixture with the exact sorted catalog tuple.
Do not compute the field from semantic or entity candidates.

- [ ] **Step 4: Add failing prompt-schema reachability tests**

```python
def test_prompt_offers_all_registered_frame_and_hint_types(
    resolver_view: ResolverView,
) -> None:
    envelope = build_prompt(request_context_for("ETF를 운용하는 회사"), resolver_view)
    frame = envelope.response_schema["properties"]["frames"]["items"]
    assert frame["properties"]["entity_type_ids"]["items"]["enum"] == list(
        resolver_view.entity_type_ids
    )
    hint = frame["properties"]["entity_hints"]["items"]
    assert hint["properties"]["expected_entity_type_ids"]["items"]["enum"] == list(
        resolver_view.entity_type_ids
    )
```

- [ ] **Step 5: Make the generated schema consume only the explicit registry**

Change all model-facing entity-type enum construction to use
`view.entity_type_ids`. Do not narrow it with a request-local candidate set.
Update `PROMPT_VERSION` to `intent-resolver-ko-v4` and update manifest assertions.

- [ ] **Step 6: Run Task 1 tests**

```bash
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -m pytest \
  tests/intent/test_view.py tests/intent/test_prompt.py \
  tests/intent/test_container_verification.py -q
```

Expected: PASS, and no response-schema entity-type enum is empty for a valid
catalog-backed view.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/financial_agent/intent/view.py src/financial_agent/intent/prompt.py \
  tests/intent/test_view.py tests/intent/test_prompt.py \
  tests/intent/view_fixtures.py tests/intent/test_container_verification.py \
  tests/intent/test_assembler.py tests/intent/test_clova.py \
  tests/intent/test_context.py tests/intent/test_validation.py \
  tests/evaluation/intent/test_intent_evaluation.py
git diff --cached --check
git commit -m "fix: expose bounded intent entity types"
```

---

### Task 2: Add Role-Aware Entity Hints to V2 Contracts

**Files:**
- Modify: `src/financial_agent/intent/types.py`
- Modify: `src/financial_agent/intent/proposal.py`
- Modify: `src/financial_agent/intent/draft.py`
- Modify: `src/financial_agent/intent/resolution.py`
- Modify: `src/financial_agent/intent/context.py`
- Modify: `tests/intent/test_proposal.py`
- Modify: `tests/intent/test_contracts.py`
- Modify: `tests/intent/test_context.py`

**Interfaces:**
- Produces: `EntitySemanticRole.FRAME_SUBJECT` and `EntitySemanticRole.RELATION_OBJECT`
- Produces: `ProposedEntityHint.semantic_role`, `.relation_id`, and `.expected_entity_type_ids`
- Produces: `EntityHintV2` with the same role fields plus canonical `entity_hint_id`
- Produces: `ValidatedIntentResolutionV2.entity_hints: tuple[EntityHintV2, ...]`
- Preserves: existing v1 `EntityHint`, `IntentResolutionDraft`, and `ValidatedIntentResolution`

- [ ] **Step 1: Add RED tests for the proposal role shape**

```python
def test_relation_object_requires_one_relation_and_expected_type() -> None:
    with pytest.raises(ValidationError):
        ProposedEntityHint(
            semantic_role="relation_object",
            relation_id=(),
            expected_entity_type_ids=("AssetManager",),
            mention_id=("mention-manager",),
            candidate_entity_ids=("manager-1",),
            selected_candidate_ids=("manager-1",),
        )


def test_frame_subject_rejects_relation_id() -> None:
    with pytest.raises(ValidationError):
        ProposedEntityHint(
            semantic_role="frame_subject",
            relation_id=("managedBy",),
            expected_entity_type_ids=("ETF",),
            mention_id=("mention-etf",),
            candidate_entity_ids=("etf-1",),
            selected_candidate_ids=("etf-1",),
        )
```

- [ ] **Step 2: Confirm the contract tests fail**

```bash
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -m pytest \
  tests/intent/test_proposal.py tests/intent/test_contracts.py -q
```

Expected: the new fields and enum do not exist.

- [ ] **Step 3: Define the role enum and strict proposal contract**

```python
class EntitySemanticRole(str, Enum):
    FRAME_SUBJECT = "frame_subject"
    RELATION_OBJECT = "relation_object"
```

```python
class ProposedEntityHint(ContractModel):
    semantic_role: EntitySemanticRole
    relation_id: OptionalIdentifier
    expected_entity_type_ids: Annotated[
        tuple[Identifier, ...], Field(min_length=1)
    ]
    mention_id: OptionalIdentifier
    candidate_entity_ids: tuple[Identifier, ...]
    selected_candidate_ids: OptionalIdentifier

    @model_validator(mode="after")
    def validate_role_shape(self) -> "ProposedEntityHint":
        if self.semantic_role is EntitySemanticRole.FRAME_SUBJECT and self.relation_id:
            raise ValueError("frame subject cannot carry a relation ID")
        if (
            self.semantic_role is EntitySemanticRole.RELATION_OBJECT
            and len(self.relation_id) != 1
        ):
            raise ValueError("relation object requires exactly one relation ID")
        if not set(self.selected_candidate_ids) <= set(self.candidate_entity_ids):
            raise ValueError("selected entity candidates must be proposed candidates")
        return self
```

- [ ] **Step 4: Add a v2-only draft entity hint without changing v1**

```python
class EntityHintV2(EntityHint):
    semantic_role: EntitySemanticRole
    relation_id: OptionalIdentifier


class IntentResolutionDraftV2(IntentResolutionDraft):
    intent_frames: Annotated[
        tuple[IntentFrameDraftV2, ...], Field(min_length=1, max_length=16)
    ]
    entity_hints: tuple[EntityHintV2, ...]
```

Do not add fields or defaults to the v1 `EntityHint`.

- [ ] **Step 5: Preserve role-aware hints in the validated v2 artifact**

```python
class ValidatedIntentResolutionV2(ValidatedIntentResolution):
    canonical_frames: Annotated[
        tuple[ValidatedIntentFrameV2, ...], Field(min_length=1, max_length=16)
    ]
    entity_hints: tuple[EntityHintV2, ...]
```

In `finalize_resolution`, pass the draft's v2 hints only when constructing the
v2 resolution. Keep the v1 constructor payload unchanged. Build a small payload
dictionary branch instead of adding `entity_hints` to the shared base class.

- [ ] **Step 6: Add byte-compatibility and v2 round-trip tests**

```python
def test_v1_entity_hint_schema_and_canonical_bytes_remain_frozen() -> None:
    assert "semantic_role" not in EntityHint.model_fields
    assert "relation_id" not in EntityHint.model_fields
    assert "expected_entity_type_ids" in EntityHint.model_fields


def test_v2_resolution_preserves_relation_object_role(v2_resolution_fixture) -> None:
    restored = ValidatedIntentResolutionV2.model_validate_json(
        v2_resolution_fixture.model_dump_json()
    )
    hint = restored.entity_hints[0]
    assert hint.semantic_role is EntitySemanticRole.RELATION_OBJECT
    assert hint.relation_id == ("managedBy",)
    assert hint.expected_entity_type_ids == ("AssetManager",)
```

- [ ] **Step 7: Run Task 2 tests**

```bash
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -m pytest \
  tests/intent/test_proposal.py tests/intent/test_contracts.py \
  tests/intent/test_context.py -q
```

Expected: PASS with unchanged v1 schema fixtures and role-preserving v2 JSON.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/financial_agent/intent/types.py src/financial_agent/intent/proposal.py \
  src/financial_agent/intent/draft.py src/financial_agent/intent/resolution.py \
  src/financial_agent/intent/context.py tests/intent/test_proposal.py \
  tests/intent/test_contracts.py tests/intent/test_context.py
git diff --cached --check
git commit -m "feat: preserve intent entity roles"
```

---

### Task 3: Assemble and Validate Relation Endpoints Independently

**Files:**
- Modify: `src/financial_agent/intent/prompt.py`
- Modify: `src/financial_agent/intent/assembler.py`
- Modify: `src/financial_agent/intent/validation.py`
- Modify: `tests/intent/test_prompt.py`
- Modify: `tests/intent/test_assembler.py`
- Modify: `tests/intent/test_validation.py`
- Modify: `tests/intent/test_service.py`

**Interfaces:**
- Consumes: role-aware `ProposedEntityHint` from Task 2
- Produces: `EntityHintV2` copied without semantic inference
- Enforces: frame subject → relation domain; relation object → relation range
- Error codes: `MODEL_UNKNOWN_ID`, `MODEL_SCHEMA_INVALID`, `MODEL_INVALID_ENTITY_TYPE`, `MODEL_INVALID_RELATION`

- [ ] **Step 1: Add a real ProposalV2 managedBy GREEN-target test and negative tests**

Construct the proposal from a ResolverView that offers an ETF entity and an
AssetManager entity with `managedBy`:

```python
def test_managed_by_accepts_asset_manager_as_relation_object(inputs) -> None:
    proposal = proposal_for_managed_by(
        frame_types=("ETF",),
        role="relation_object",
        relation_id=("managedBy",),
        expected_types=("AssetManager",),
        selected_entity_id="manager-samsung",
    )
    draft = assemble_proposal(proposal, inputs.normalized, inputs.view)
    state = validate_semantics(
        draft, inputs.context, inputs.normalized, inputs.view, inputs.catalog
    )
    assert state.resolution_status is ResolutionStatus.RESOLVED
    assert draft.entity_hints[0].semantic_role is EntitySemanticRole.RELATION_OBJECT


@pytest.mark.parametrize(
    ("role", "frame_types", "expected_types", "entity_id", "code"),
    [
        ("frame_subject", ("ETF",), ("AssetManager",), "manager-samsung", "MODEL_INVALID_ENTITY_TYPE"),
        ("relation_object", ("ETF",), ("ETF",), "etf-kodex200", "MODEL_INVALID_RELATION"),
    ],
)
def test_managed_by_rejects_endpoint_reversal(
    inputs, role, frame_types, expected_types, entity_id, code
) -> None:
    proposal = proposal_for_managed_by(
        frame_types=frame_types,
        role=role,
        relation_id=("managedBy",) if role == "relation_object" else (),
        expected_types=expected_types,
        selected_entity_id=entity_id,
    )
    draft = assemble_proposal(proposal, inputs.normalized, inputs.view)
    with pytest.raises(ResolverContractError, match=code):
        validate_semantics(
            draft, inputs.context, inputs.normalized, inputs.view, inputs.catalog
        )
```

- [ ] **Step 2: Confirm the managedBy positive case fails before implementation**

```bash
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -m pytest \
  tests/intent/test_assembler.py tests/intent/test_validation.py \
  -k "managed_by or endpoint" -q
```

Expected: the positive relation-object case fails because the assembler still
assigns frame types to every hint or the validator applies frame subject types to
the object.

- [ ] **Step 3: Bound every proposed role field in the assembler**

For each frame:

```python
_require_subset(hint.expected_entity_type_ids, view.entity_type_ids)
if hint.semantic_role is EntitySemanticRole.RELATION_OBJECT:
    _require_subset(hint.relation_id, relation_ids)
    if hint.relation_id[0] not in {
        relation_id
        for assignment in frame.slot_assignments
        if assignment.slot_kind is SlotKind.RELATION
        for relation_id in assignment.value_ids
    }:
        _schema_invalid()
```

Copy, do not derive:

```python
EntityHintV2(
    entity_hint_id=f"entity-hint-{frame_index:04d}-{hint_index:04d}",
    semantic_role=hint.semantic_role,
    relation_id=hint.relation_id,
    mention_id=hint.mention_id,
    evidence_span_ids=(),
    expected_entity_type_ids=hint.expected_entity_type_ids,
    candidate_entity_ids=hint.candidate_entity_ids,
    selected_candidate_ids=hint.selected_candidate_ids,
    reason_code="implicit",
)
```

- [ ] **Step 4: Replace the cross-endpoint validation with role-specific checks**

Split the checks into named functions:

```python
def _validate_frame_subject_hint(
    frame: IntentFrameDraftV2,
    hint: EntityHintV2,
    catalog: SemanticCatalogSnapshot,
) -> None:
    if not all(
        _type_is_compatible(expected, set(frame.entity_type_ids), catalog)
        for expected in hint.expected_entity_type_ids
    ):
        raise ResolverContractError("MODEL_INVALID_ENTITY_TYPE")


def _validate_relation_object_hint(
    frame: IntentFrameDraftV2,
    hint: EntityHintV2,
    catalog: SemanticCatalogSnapshot,
) -> None:
    relation = catalog.concepts_by_id.get(hint.relation_id[0])
    if relation is None or relation.kind != "relation":
        raise ResolverContractError("MODEL_INVALID_RELATION")
    allowed = set(relation.object_ontology_types)
    if not all(
        _type_is_compatible(expected, allowed, catalog)
        for expected in hint.expected_entity_type_ids
    ):
        raise ResolverContractError("MODEL_INVALID_RELATION")
```

Retain the existing relation-domain check for `frame.entity_type_ids`. In
`_validate_selected_entity_types`, validate candidates against
`hint.expected_entity_type_ids` only; remove the second check that forces every
candidate to match every referencing frame's subject type.

- [ ] **Step 5: Update the structured-output instructions**

The prompt must state these bounded rules in Korean:

```text
frame.entity_type_ids는 분석 대상 또는 관계 주체의 타입이다.
entity_hints.semantic_role=relation_object이면 relation_id를 하나 선택하고,
expected_entity_type_ids에는 그 관계의 객체 타입을 선택한다.
```

The schema must require `semantic_role`, `relation_id`, and
`expected_entity_type_ids`; role values and relation values remain enums.

- [ ] **Step 6: Exercise the entire one-call service parse path**

```python
async def test_service_preserves_managed_by_object_role(service_fixture) -> None:
    service_fixture.adapter.content = managed_by_proposal_json()
    attempt = await service_fixture.service.resolve_once(service_fixture.context)
    hint = attempt.resolution.entity_hints[0]
    assert hint.semantic_role is EntitySemanticRole.RELATION_OBJECT
    assert hint.relation_id == ("managedBy",)
    assert hint.expected_entity_type_ids == ("AssetManager",)
```

- [ ] **Step 7: Run Task 3 tests**

```bash
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -m pytest \
  tests/intent/test_prompt.py tests/intent/test_assembler.py \
  tests/intent/test_validation.py tests/intent/test_service.py -q
```

Expected: the valid managedBy object passes and endpoint reversals fail with the
specified stable error codes.

- [ ] **Step 8: Commit Task 3**

```bash
git add src/financial_agent/intent/prompt.py \
  src/financial_agent/intent/assembler.py \
  src/financial_agent/intent/validation.py tests/intent/test_prompt.py \
  tests/intent/test_assembler.py tests/intent/test_validation.py \
  tests/intent/test_service.py
git diff --cached --check
git commit -m "fix: validate intent relation endpoints"
```

---

### Task 4: Add End-to-End Type Reachability and Artifact Evaluation

**Files:**
- Modify: `src/financial_agent/intent/evaluation.py`
- Modify: `scripts/evaluate_intent_resolver.py`
- Modify: `tests/evaluation/intent/test_intent_evaluation.py`
- Modify: generated v2 schemas under `schemas/intent/v2/`

**Interfaces:**
- Consumes: frozen 160-case held-out dataset and the 155 semantic-executable population
- Produces: `EntityTypeReachabilityEvidence(total, reachable, unreachable_case_ids)`
- Produces: sanitized evaluation output without question text or raw HCX content
- Preserves: existing ADR-0022 promotion percentages and provider/schema separation

- [ ] **Step 1: Add the failing 155/155 reachability test**

Build the real catalog, normalize every executable request, generate candidates,
build the real ResolverView, then inspect the generated schema:

```python
def case_request_context(case: EvaluationCase) -> RequestContext:
    created_at = datetime(2026, 8, 31, tzinfo=UTC)
    dataset_version = "intent-heldout-ko-v3"
    return RequestContext(
        request_key=build_request_key(
            case.case_id, case.question, dataset_version, "1.0"
        ),
        run_id=f"reachability-{case.case_id}",
        dataset_version=dataset_version,
        producer="intent-reachability-test",
        created_at=created_at,
        question_id=case.case_id,
        question=case.question,
        segments=tuple(
            Segment(segment_id=item.segment_id, ordinal=item.ordinal, text=item.text)
            for item in case.segments
        ),
        deadline_at=created_at + timedelta(seconds=55),
    )


def build_real_view_for_evaluation_case(
    case: EvaluationCase,
    catalog: SemanticCatalogSnapshot,
) -> ResolverView:
    context = case_request_context(case)
    normalized = normalize_request(context)
    manifest = build_manifest(
        catalog,
        {
            "normalizer_version": NORMALIZER_VERSION,
            "candidate_policy_version": CANDIDATE_POLICY_VERSION,
            "resolver_schema_version": RESOLVER_SCHEMA_VERSION,
            "prompt_version": PROMPT_VERSION,
            "adapter_version": ADAPTER_VERSION,
        },
    )
    return build_resolver_view(
        context=context,
        normalized=normalized,
        literals=extract_literals(normalized),
        semantic_candidates=generate_semantic_candidates(normalized, catalog),
        entity_candidates={},
        manifest=manifest,
        active_dataset_pin=ActiveDatasetPin(
            dataset_version=context.dataset_version,
            manifest_hash="d" * 64,
        ),
        catalog=catalog,
    )


def test_all_semantic_cases_can_express_expected_frame_types() -> None:
    dataset = parse_strict_json(HELDOUT_PATH.read_bytes(), EvaluationDataset)
    catalog = load_catalog(PROJECT_ROOT)
    checked = 0
    for case in dataset.cases:
        if case.expected_pipeline_outcome == "pre_model_rejected":
            continue
        view = build_real_view_for_evaluation_case(case, catalog)
        schema = build_prompt(case_request_context(case), view).response_schema
        offered = set(
            schema["properties"]["frames"]["items"]["properties"]
            ["entity_type_ids"]["items"]["enum"]
        )
        assert all(set(frame.entity_type_ids) <= offered for frame in case.expected_frames), (
            case.case_id,
            frame.entity_type_ids,
        )
        checked += 1
    assert checked == 155
```

`build_real_view_for_evaluation_case` must call the same normalizer, literal
extractor, semantic candidate generator, entity candidate input boundary, and
`build_resolver_view` used by the service. It must not assign expected types to
the view.

- [ ] **Step 2: Reproduce the old failure before changing evaluation helpers**

Run the new test against commit `5827fdf` behavior before completing Task 1's
projection or by temporarily asserting the prior request-local union in the RED
test record.

Expected baseline: only 14 of 155 cases are reachable, with 141 unreachable.
Record the RED evidence in the task report; do not commit a temporary revert.

- [ ] **Step 3: Add a typed reachability metric**

```python
class EntityTypeReachabilityEvidence(ContractModel):
    total: int = Field(ge=0)
    reachable: int = Field(ge=0)
    unreachable_case_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_counts(self) -> "EntityTypeReachabilityEvidence":
        if self.reachable + len(self.unreachable_case_ids) != self.total:
            raise ValueError("entity-type reachability counts must cover population")
        return self
```

Include only stable case IDs in stored reports. Do not include question text,
prompt text, entity names, model content, or credentials.

- [ ] **Step 4: Replace the gold-only conformance proof with layered evidence**

Keep the existing perfect-prediction arithmetic test for metric math, but rename
it so it does not claim contract reachability. Add separate assertions that:

1. all 155 expected frame types occur in real schemas;
2. a real managedBy ProposalV2 traverses assembler and validation; and
3. its role-aware DraftV2 and ValidatedV2 JSON round-trip through stored bundle
   dispatch.

```python
def test_managed_by_proposal_crosses_full_v2_evaluation_boundary(
    stored_managed_by_inputs,
) -> None:
    draft, resolution = resolve_gold_equivalent_managed_by(stored_managed_by_inputs)
    draft_bundle = IntentDraftBundleV2(
        dataset_id="entity-role-v2",
        cases=(IntentDraftCaseArtifactV2(case_id="managed-by", artifact=draft),),
    )
    resolution_bundle = ValidatedResolutionBundleV2(
        dataset_id="entity-role-v2",
        cases=(
            ValidatedResolutionCaseArtifactV2(
                case_id="managed-by", artifact=resolution
            ),
        ),
    )
    assert draft_bundle.cases[0].artifact.entity_hints[0].semantic_role.value == "relation_object"
    assert resolution_bundle.cases[0].artifact.entity_hints[0].relation_id == ("managedBy",)
```

- [ ] **Step 5: Run evaluator and contract suites**

```bash
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -m pytest \
  tests/evaluation/intent/test_intent_evaluation.py \
  tests/intent/test_contracts.py tests/intent/test_schema_export.py -q
```

Expected: reachability `155/155`, real role-aware artifact round-trip PASS, and
promotion arithmetic still uses the 155 semantic-executable denominator.

- [ ] **Step 6: Regenerate and freshness-check only v2 schemas**

```bash
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -c \
  'from pathlib import Path; from financial_agent.intent.schema_export import export_schemas; export_schemas(Path("schemas/intent/v2"), schema_version="2.0")'
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python \
  scripts/export_intent_schemas.py --check
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -c \
  'from pathlib import Path; from financial_agent.intent.schema_export import check_schemas; check_schemas(Path("schemas/intent/v2"), schema_version="2.0")'
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -m pytest \
  tests/intent/test_schema_export.py tests/intent/test_contracts.py -q
```

Inspect the diff and verify that no v1 schema file changed.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/financial_agent/intent/evaluation.py \
  scripts/evaluate_intent_resolver.py tests/evaluation/intent/test_intent_evaluation.py \
  schemas/intent/v2 tests/intent/test_schema_export.py tests/intent/test_contracts.py
git diff --cached --check
git diff --cached --name-only
git commit -m "test: prove intent entity type reachability"
```

Expected staged paths must not include `schemas/intent/v1/`.

---

### Task 5: Run Offline Gates and the Authorized HCX Smoke

**Files:**
- Modify: `docs/planning/reports/2026-09-01-intent-resolver-v2-verification.md`
- No implementation files unless a failing gate produces a separately reviewed fix

**Interfaces:**
- Consumes: Tasks 1–4 and the existing `NCP_CLOVA_STUDIO_API` value stored outside Git
- Produces: fresh offline counts and sanitized 12-case HCX smoke metrics
- Produces: explicit promotion status; no automatic model promotion

- [ ] **Step 1: Run the focused intent and evaluation suite**

```bash
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -m pytest \
  tests/intent tests/evaluation/intent -q
```

Expected: zero failures, exact count recorded in the verification report.

- [ ] **Step 2: Run schema and diff gates**

```bash
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python \
  scripts/export_intent_schemas.py --check
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -c \
  'from pathlib import Path; from financial_agent.intent.schema_export import check_schemas; check_schemas(Path("schemas/intent/v2"), schema_version="2.0")'
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 3: Run the broad offline suite**

```bash
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python -m pytest -q \
  -m "not postgres and not ncp_integration and not performance and not organizer_data and not object_storage and not official_data and not jena_integration and not clova_integration"
```

Expected: zero failures. The explicit PostgreSQL test may remain skipped when
`FINANCIAL_AGENT_TEST_DATABASE_URL` is absent; record it as unmeasured external
evidence rather than a pass.

- [ ] **Step 4: Audit scope and secrets before any live call**

```bash
git diff 5827fdf..HEAD --name-only
git diff 5827fdf..HEAD --check
git status --short
```

Confirm that no path under `data/`, no organizer PDF/workbook, `api.txt`, `.env`,
raw report, migration, QueryPlan, Orchestrator, or public API file appears.

- [ ] **Step 5: Run the authorized 12-case HCX smoke at one-second pacing**

Load the local credential without printing it, then execute:

```bash
set -a
source "/Users/kimjaewon/금융상품 agent/api.txt"
set +a
PYTHONPATH=src /private/tmp/financial-agent-resolver-verify/bin/python \
  scripts/evaluate_intent_resolver.py live \
  --model HCX-007 \
  --request-interval-seconds 1 \
  --report-path /private/tmp/intent-resolver-entity-role-live-report.json
```

Do not display or commit the raw report. Read only its sanitized aggregate and
case IDs. If provider success is `0/12`, stop semantic interpretation and record
the provider gate as unavailable. Do not retry beyond this authorized 12-case
run.

- [ ] **Step 6: Update the verification report**

Record:

- type reachability before/after: `14/155 → 155/155` if verified;
- focused and broad offline test counts;
- v1 schema no-drift and v2 schema freshness;
- provider success, schema validity, joint frame, context, OOD, latency, and
  token fields as separate values;
- PostgreSQL evidence status;
- each ADR-0022 gate with `pass`, `fail`, or `unmeasured`;
- model promotion as `deferred` unless every gate passes.

Do not claim that the 12-case smoke is promotion evidence.

- [ ] **Step 7: Commit the verified report**

```bash
git add docs/planning/reports/2026-09-01-intent-resolver-v2-verification.md
git diff --cached --check
git diff --cached
git commit -m "docs: report intent entity role verification"
```

- [ ] **Step 8: Final branch verification**

```bash
git status --short
git log --oneline 5827fdf..HEAD
git diff --check 5827fdf..HEAD
```

Expected: clean worktree, only scoped commits, no push, merge, deployment, or
model promotion.

---

## Completion Conditions

Implementation is ready for final review only when:

1. all five tasks have independent GREEN evidence and commits;
2. expected entity-type reachability is `155/155`;
3. the managedBy relation-object positive and endpoint-reversal negative tests
   pass through the real ProposalV2 boundary;
4. v1 artifacts are byte-stable and v2 artifacts preserve roles;
5. focused, schema, and broad offline gates have zero failures;
6. live-provider failure, if any, is reported separately and does not become a
   semantic result; and
7. promotion remains deferred unless every ADR-0022 gate passes.

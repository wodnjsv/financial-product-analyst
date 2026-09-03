# Hybrid Full-Catalog Semantic Linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Implemented, shadow-only; promotion deferred

**Goal:** Implement a shadow V3 Intent Resolver that lets HCX link bounded source spans to every registered semantic concept while preserving deterministic exact locks, validation, QueryContract solving, and physical-schema isolation.

**Architecture:** V3 adds meaning-neutral mention spans and a generated full `CompactSemanticCatalogV1` to a request-specific `ResolverViewV3`. One HCX call returns Action, ProductFamily, semantic links, explicit unmapped evidence, and only the entity/context branches supported by request evidence; deterministic code validates the result, reconciles exact locks, solves registered QueryContracts, and optionally applies an explicitly injected snapshot-date policy. V2 remains the default until the complete V3 offline and live promotion gates pass and a separate promotion decision is approved.

**Tech Stack:** Python 3.12, Pydantic v2 strict frozen contracts, JSON registries with canonical SHA-256 pins, pytest, HyperCLOVA X HCX-007 Structured Outputs, existing deterministic QueryContract solver and PostgreSQL artifact repository.

**Spec:** [Hybrid Full-Catalog Semantic Linking Design](../specs/2026-09-03-hybrid-full-catalog-semantic-linking-design.md)

## Assumptions and Approved Trade-offs

- The authoritative semantic catalog currently contains 42 concepts and the
  held-out semantic denominator contains 196 expected concept occurrences.
- HCX-007 Structured Outputs can enumerate 42 compact IDs plus bounded mention
  IDs within the provider's accepted JSON Schema size; the payload-size test
  must prove this before any live call.
- A single joint HCX call is preferred because Action, ProductFamily, frame
  boundaries, and semantic links share sentence-level meaning. Three independent
  axis calls are rejected for V3 because they lose that joint context and triple
  provider traffic; they may be reconsidered only with comparative evidence.
- Full compact-catalog exposure is preferred over making the Korean candidate
  generator closed-world. The trade-off is a larger prompt and a greater
  nearest-concept risk, controlled by explicit `unmapped`/`ambiguous` output,
  contrastive cards, strict validation, and OOD tests.
- New Korean aliases remain useful for exact locks and ranking hints, but adding
  aliases is not the primary correctness mechanism for unseen paraphrases.

## Non-goals

- Do not promote V3 to the default resolver in this change.
- Do not change the public answer API, Orchestrator routing, physical planner,
  SQL/Graph/Search/Calculation executors, or answer narration.
- Do not expose physical schema, permit free-form semantic IDs, or let HCX
  author QueryContracts.
- Do not add PostgreSQL DDL unless a separately approved follow-up is required
  by an observed compatibility failure.

## Global Constraints

- Keep one HCX resolver call on the normal V3 path; retain the mutually exclusive repair-or-candidate-judge allowance.
- Keep V2 behavior, schemas, stored artifacts, and public `GET /answer` contract readable and unchanged.
- HCX may select only server-owned Action, ProductFamily, semantic, entity, reference, and mention IDs.
- HCX never receives or emits SQL, table names, column names, joins, formulas, physical metric IDs, arbitrary defaults, or contract bodies.
- Canonical IDs, unique direct aliases, literals, operators, and exact family anchors remain deterministic locks.
- Group, ambiguous, trigram, and model semantic links never become deterministic locks.
- Filtering, ranking, comparison, aggregation, de-duplication, calculations, physical planning, and execution remain deterministic.
- An absent hint must not make a registered concept unselectable.
- Unknown or incompatible semantics fail closed into Explore, Limitation, or Abstain; validation is not relaxed to raise coverage.
- No default `as_of` date is inferred from the competition cutoff. A default is eligible only when a caller supplies a dataset-pinned verified observation date.
- V3 remains shadow-only until all complete-denominator promotion gates pass and a separate explicit promotion decision is approved.
- Use tests first for every behavior change. Run the narrowest test after each edit and the broad offline suite before any live HCX call.
- Do not commit credentials, raw HCX payloads, organizer workbooks, database dumps, or generated live logs.

## File Structure

New focused modules:

- `src/financial_agent/intent/mention_spans.py` — source-preserving, meaning-neutral span generation and bounds.
- `src/financial_agent/intent/compact_catalog.py` — generated model-facing semantic cards and catalog hash.
- `src/financial_agent/intent/hybrid_proposal.py` — strict ProposalV3 semantic-link contracts.
- `src/financial_agent/intent/hybrid_prompt.py` — V3 payload and request-specific HCX response schema.
- `src/financial_agent/intent/hybrid_assembler.py` — server-owned IDs and ProposalV3-to-DraftV3 assembly.
- `src/financial_agent/intent/semantic_defaults.py` — dataset-pinned semantic default policy inputs.

Existing modules retain their current responsibility:

- `catalog.py` compiles catalog, overlay, and ontology authorities.
- `view.py` owns versioned request projections and build manifests.
- `draft.py`, `resolution.py`, and `validation.py` own canonical internal contracts and semantic validation.
- `service.py` schedules preparation, the one HCX call, repair, validation, solving, and judging.
- `query_contract_solver.py` enumerates only complete registered contracts.
- `db/repositories/artifacts.py` validates stored resolver versions.
- evaluation scripts report V2 and V3 separately.

---

### Task 1: Generate the complete compact semantic catalog

**Files:**
- Create: `src/financial_agent/intent/compact_catalog.py`
- Create: `tests/intent/test_compact_catalog.py`
- Create: `config/intent/korean-nlu-overlay.v4.json`
- Modify: `src/financial_agent/intent/catalog.py`

**Interfaces:**
- Consumes: `SemanticCatalogSnapshot`, `SemanticConcept`, and `KoreanNluEntry` from `catalog.py`.
- Produces: `load_hybrid_catalog(project_root) -> SemanticCatalogSnapshot`,
  `CompactSemanticConceptV1`, `CompactSemanticCatalogV1`, and
  `build_compact_semantic_catalog(snapshot: SemanticCatalogSnapshot) -> CompactSemanticCatalogV1`.

- [x] **Step 1: Write failing full-selectability and no-physical-schema tests**

```python
def test_compact_catalog_contains_every_registered_concept(project_root: Path) -> None:
    snapshot = load_hybrid_catalog(project_root)
    compact = build_compact_semantic_catalog(snapshot)
    assert {item.semantic_id for item in compact.concepts} == set(snapshot.concepts_by_id)
    assert len(compact.concepts) == 42


def test_compact_catalog_contains_no_physical_schema_tokens(project_root: Path) -> None:
    payload = canonical_json_bytes(
        build_compact_semantic_catalog(load_hybrid_catalog(project_root))
    ).decode("utf-8")
    for forbidden in ("SELECT ", "FROM ", "catalog.observation", "metric_id", "column_name"):
        assert forbidden not in payload
```

- [x] **Step 2: Run the focused tests and verify they fail because the compact catalog module does not exist**

Run: `.venv/bin/pytest tests/intent/test_compact_catalog.py -q`

Expected: collection failure naming `financial_agent.intent.compact_catalog`.

- [x] **Step 3: Add strict compact-card contracts and deterministic construction**

```python
class CompactSemanticConceptV1(ContractModel):
    semantic_id: Identifier
    preferred_label_ko: str = Field(min_length=1)
    definition_ko: str = Field(min_length=1)
    concept_kind: Literal["attribute", "metric", "relation", "document_topic"]
    value_kind: str = Field(min_length=1)
    applicable_family_ids: tuple[Identifier, ...]
    required_qualifier_ids: tuple[Identifier, ...]
    disambiguation_ko: str | None = None


class CompactSemanticCatalogV1(ContractModel):
    projection_version: Literal["compact-semantic-catalog.v1"]
    source_catalog_hash: Sha256Hex
    source_overlay_hash: Sha256Hex
    concepts: tuple[CompactSemanticConceptV1, ...] = Field(min_length=1)


def build_compact_semantic_catalog(
    snapshot: SemanticCatalogSnapshot,
) -> CompactSemanticCatalogV1:
    ...
```

Construction uses the V4 overlay preferred label when present and otherwise
uses the catalog's non-empty Korean definition as the label. Concepts are
sorted by `(concept_kind, semantic_id)`. The constructor rejects duplicate IDs,
missing cards, unknown families, empty definitions, and any physical-schema
field.

- [x] **Step 4: Correct preferred-label indexing without changing lock authority**

Copy V3 overlay content into the separately versioned V4 overlay, extend the
strict overlay entry with optional `disambiguation_ko`, and add catalog mappings
separate from `alias_candidates`:

```python
preferred_labels_by_semantic_id: Mapping[str, str]
disambiguation_by_semantic_id: Mapping[str, str]
```

Do not automatically place `preferred_label` into `alias_candidates`. Exact-lock
authority continues to require an explicit unique `direct` alias. Add concise
disambiguation only for the reviewed pairs `credit_grade/product_risk_grade`,
`aum/nav`, `yield_rate/trailing_1y_historical_cumulative_return`, and
`remaining_days/remaining_maturity`.

Add `_HYBRID_OVERLAY_PATH` and `load_hybrid_catalog()`. Keep `_OVERLAY_PATH`,
`load_catalog()`, and the V2 overlay bytes unchanged. Add a regression assertion
that the V2 catalog and overlay hashes are identical before and after this task.

- [x] **Step 5: Run catalog tests**

Run: `.venv/bin/pytest tests/intent/test_catalog.py tests/intent/test_compact_catalog.py -q`

Expected: all tests pass and the compact catalog contains exactly the same 42
semantic IDs as the authoritative catalog.

- [x] **Step 6: Commit the independently useful catalog projection**

```bash
git add config/intent/korean-nlu-overlay.v4.json src/financial_agent/intent/catalog.py src/financial_agent/intent/compact_catalog.py tests/intent/test_catalog.py tests/intent/test_compact_catalog.py
git commit -m "feat: add compact semantic catalog"
```

### Task 2: Generate bounded meaning-neutral mention spans

**Files:**
- Create: `src/financial_agent/intent/mention_spans.py`
- Create: `tests/intent/test_mention_spans.py`
- Modify: `src/financial_agent/intent/normalization.py`

**Interfaces:**
- Consumes: `NormalizedRequest`, exact candidate mentions, literals, named-entity mentions, and reference mentions.
- Produces: `MentionSpanV1`, `MentionSpanSetV1`, `MentionSpanLimitError`, and `generate_mention_spans(...) -> MentionSpanSetV1`.

- [x] **Step 1: Write failing tests for unseen paraphrases and source preservation**

```python
def test_phrase_spans_preserve_unseen_fee_paraphrase(request_context) -> None:
    normalized = normalize_request(request_context("비용 부담이 작은 ETF를 알려줘"))
    spans = generate_mention_spans(normalized, (), (), (), ())
    assert any(item.text == "비용 부담" for item in spans.items)
    assert all(
        normalized.context.segments[0].text[item.start_char:item.end_char] == item.text
        for item in spans.items
    )


def test_required_spans_are_never_silently_truncated(long_request) -> None:
    with pytest.raises(MentionSpanLimitError, match="MENTION_SPAN_LIMIT_EXCEEDED"):
        generate_mention_spans(long_request, required_exact_spans, (), (), ())
```

- [x] **Step 2: Run the tests and verify the missing module failure**

Run: `.venv/bin/pytest tests/intent/test_mention_spans.py -q`

Expected: collection failure naming `financial_agent.intent.mention_spans`.

- [x] **Step 3: Implement strict span types and the deterministic policy**

```python
MAX_PHRASE_TOKENS = 4
MAX_MENTION_SPANS = 96
MENTION_SPAN_POLICY_VERSION = "meaning-neutral-spans-v1-4x96"

class MentionSpanV1(ContractModel):
    mention_id: Identifier
    segment_id: Identifier
    text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    source_kinds: tuple[Literal[
        "exact_anchor", "literal_context", "reference", "entity", "phrase"
    ], ...]

class MentionSpanSetV1(ContractModel):
    policy_version: Literal["meaning-neutral-spans-v1-4x96"]
    items: tuple[MentionSpanV1, ...] = Field(max_length=MAX_MENTION_SPANS)
```

Generate all normalized contiguous one-to-four-token phrase spans plus every
full segment span. Merge exact, literal, reference, and entity ranges into the
same range record. Sort by segment ordinal, source start, source end, and ID. If
the de-duplicated set exceeds 96, raise `MentionSpanLimitError`; do not truncate.

- [x] **Step 4: Add Korean punctuation and particle boundary regression tests**

Cover `수수료율은`, `신용 등급`, `만기까지 며칠 남았는지`, Unicode composition,
comma-separated predicates, and a two-frame prior-result question. Verify exact
source offsets after normalization.

- [x] **Step 5: Run normalization and mention-span tests**

Run: `.venv/bin/pytest tests/intent/test_normalization.py tests/intent/test_mention_spans.py -q`

Expected: all tests pass, outputs are byte-reproducible, and the 96-span overflow
is the only accepted bound failure.

- [x] **Step 6: Commit mention-span generation**

```bash
git add src/financial_agent/intent/normalization.py src/financial_agent/intent/mention_spans.py tests/intent/test_mention_spans.py
git commit -m "feat: generate semantic mention spans"
```

### Task 3: Add a versioned full-catalog ResolverViewV3

**Files:**
- Modify: `src/financial_agent/intent/view.py`
- Modify: `src/financial_agent/intent/service.py`
- Modify: `tests/intent/test_view.py`
- Modify: `tests/intent/view_fixtures.py`

**Interfaces:**
- Consumes: `MentionSpanSetV1`, `CompactSemanticCatalogV1`, existing semantic candidates, exact locks, literals, entities, references, and manifest pins.
- Produces: `ResolverViewV3`, `build_hybrid_manifest(...)`,
  `build_resolver_view_v3(...) -> ResolverViewV3`, and hybrid version constants.

- [x] **Step 1: Write failing tests proving hints do not limit concept selectability**

```python
def test_v3_view_offers_full_catalog_when_no_alias_matches(v3_inputs) -> None:
    view = build_resolver_view_v3(**v3_inputs(question="비용 부담이 작은 ETF"))
    assert not any(
        item.semantic_id == "fee_rate"
        for group in view.semantic_candidates
        for item in group.items
    )
    assert "fee_rate" in {
        item.semantic_id for item in view.compact_semantic_catalog.concepts
    }


def test_v3_non_entity_request_disables_entity_output(v3_inputs) -> None:
    view = build_resolver_view_v3(**v3_inputs(question="ETF 순위를 알려줘"))
    assert view.entity_output_enabled is False
```

- [x] **Step 2: Run the focused view tests and verify they fail**

Run: `.venv/bin/pytest tests/intent/test_view.py -q`

Expected: failures naming `ResolverViewV3` and `build_resolver_view_v3`.

- [x] **Step 3: Add V3 contracts and version pins without modifying V2 constants**

```python
HYBRID_RESOLVER_SCHEMA_VERSION = "3.0"
HYBRID_CANDIDATE_POLICY_VERSION = "intent-hints-v3"
HYBRID_PROMPT_VERSION = "intent-resolver-ko-v6-full-catalog"
HYBRID_ADAPTER_VERSION = "clova-chat-v3-proposal-v3"

class ResolverViewV3(ResolverView):
    mention_spans: MentionSpanSetV1
    compact_semantic_catalog: CompactSemanticCatalogV1
    entity_output_enabled: bool
    reference_output_enabled: bool
```

`build_resolver_view_v3` includes every compact concept, keeps V2 candidate
groups as advisory hints, and sets output capability flags only from actual
request evidence. `build_hybrid_manifest` accepts only the V3 version map and
the V4 overlay hash. V2 `build_manifest`, `build_resolver_view`, version
constants, fixture payloads, and hashes remain byte-stable.

- [x] **Step 4: Add model-safe exact-lock projections**

Expose only lock ID, mention ID, canonical semantic ID, and role. Exclude physical
or literal implementation details. Assert that the model-safe V3 payload cannot
contain an exact lock whose source range is absent from `mention_spans`.

- [x] **Step 5: Run V2 and V3 view tests**

Run: `.venv/bin/pytest tests/intent/test_view.py tests/intent/test_axis_locks.py -q`

Expected: all tests pass and existing V2 fixture hashes do not change.

- [x] **Step 6: Commit the shadow V3 view**

```bash
git add src/financial_agent/intent/view.py src/financial_agent/intent/service.py tests/intent/test_view.py tests/intent/view_fixtures.py
git commit -m "feat: add full catalog resolver view"
```

### Task 4: Define ProposalV3 and the adaptive HCX schema

**Files:**
- Create: `src/financial_agent/intent/hybrid_proposal.py`
- Create: `src/financial_agent/intent/hybrid_prompt.py`
- Create: `tests/intent/test_hybrid_proposal.py`
- Create: `tests/intent/test_hybrid_prompt.py`
- Modify: `src/financial_agent/intent/clova.py`

**Interfaces:**
- Consumes: `RequestContext`, `ResolverViewV3`, `SemanticCatalogSnapshot`.
- Produces: `FrameSemanticCoverageV3`, `ProposedSemanticLinkV3`,
  `ProposedIntentFrameV3`, `IntentResolutionProposalV3`,
  `build_hybrid_prompt(...) -> ResolverPromptEnvelope`, and
  `build_hybrid_response_schema(...) -> dict[str, object]`.

- [x] **Step 1: Write failing ProposalV3 invariant tests**

```python
def test_selected_semantic_link_requires_one_catalog_id() -> None:
    with pytest.raises(ValidationError):
        ProposedSemanticLinkV3(
            mention_id="mention-1",
            state="selected",
            semantic_ids=("fee_rate", "aum"),
            reason_code="explicit",
        )


def test_ambiguous_semantic_link_requires_multiple_catalog_ids() -> None:
    with pytest.raises(ValidationError):
        ProposedSemanticLinkV3(
            mention_id="mention-1",
            state="ambiguous",
            semantic_ids=("fee_rate",),
            reason_code="ambiguous",
        )
```

- [x] **Step 2: Write failing request-specific schema tests**

```python
def test_simple_question_schema_forbids_entity_and_context_arrays(simple_v3_view) -> None:
    schema = build_hybrid_response_schema(simple_v3_view)
    frame = schema["properties"]["frames"]["items"]
    assert frame["properties"]["entity_hints"]["maxItems"] == 0
    assert schema["properties"]["context_links"]["maxItems"] == 0


def test_semantic_link_enum_contains_unhinted_catalog_id(simple_v3_view) -> None:
    schema = build_hybrid_response_schema(simple_v3_view)
    assert "fee_rate" in semantic_id_enum(schema)
```

- [x] **Step 3: Run the new tests and verify missing-type failures**

Run: `.venv/bin/pytest tests/intent/test_hybrid_proposal.py tests/intent/test_hybrid_prompt.py -q`

Expected: collection failures for the new V3 modules.

- [x] **Step 4: Implement the strict ProposalV3 shape**

```python
class ProposedSemanticLinkV3(ContractModel):
    mention_id: Identifier
    state: Literal["selected", "ambiguous"]
    semantic_ids: tuple[Identifier, ...] = Field(min_length=1)
    reason_code: Literal["explicit", "implicit", "ambiguous"]

class FrameSemanticCoverageV3(ContractModel):
    state: SemanticCoverageState
    reason: SemanticCoverageReason

class ProposedIntentFrameV3(ContractModel):
    segment_ids: tuple[Identifier, ...] = Field(min_length=1)
    action_choice: ProposedAxisChoice
    product_family_choice: ProposedAxisChoice
    entity_type_ids: tuple[Identifier, ...]
    semantic_links: tuple[ProposedSemanticLinkV3, ...]
    unmapped_mention_ids: tuple[Identifier, ...]
    semantic_coverage: FrameSemanticCoverageV3
    entity_hints: tuple[ProposedEntityHint, ...]
    produced_result_hints: tuple[SourceRole, ...]

class IntentResolutionProposalV3(ContractModel):
    proposal_schema_version: Literal["3.0"] = "3.0"
    frames: tuple[ProposedIntentFrameV3, ...] = Field(min_length=1, max_length=16)
    references: tuple[ProposedReference, ...]
    context_links: tuple[ProposedContextLink, ...]
    slot_mutations: tuple[ProposedSlotMutation, ...]
    semantic_flag_hints: tuple[ProposedSemanticFlag, ...]
    frame_limit_exceeded: bool
```

Selected links require exactly one semantic ID; ambiguous links require at least
two distinct IDs. A mention cannot appear in both `semantic_links` and
`unmapped_mention_ids`. Covered frames require reason `none` and no unmapped
mention IDs. Uncovered frames require a non-`none` reason and at least one
unmapped mention ID. This avoids making HCX repeat the same IDs inside the
coverage object.

- [x] **Step 5: Implement the compact prompt and adaptive JSON Schema**

The system message tells HCX to map offered source mentions to registered
semantic IDs, use `unmapped_mention_ids` rather than nearest-concept coercion,
and leave entity/context arrays empty when disabled. The schema enumerates every
compact semantic ID and mention ID. It sets entity and reference branch limits
from `ResolverViewV3` flags.

- [x] **Step 6: Add payload scans and exact HCX adapter compatibility tests**

Assert no prompt or schema contains physical tokens, raw TBox text, SQL, or
arbitrary IDs. Reuse the existing HCX-007 Structured Outputs transport without
another provider client or model call.

- [x] **Step 7: Run proposal, prompt, and adapter tests**

Run: `.venv/bin/pytest tests/intent/test_hybrid_proposal.py tests/intent/test_hybrid_prompt.py tests/intent/test_clova.py -q`

Expected: all tests pass; V2 prompt snapshots remain unchanged.

- [x] **Step 8: Commit ProposalV3 and prompt shaping**

```bash
git add src/financial_agent/intent/hybrid_proposal.py src/financial_agent/intent/hybrid_prompt.py src/financial_agent/intent/clova.py tests/intent/test_hybrid_proposal.py tests/intent/test_hybrid_prompt.py tests/intent/test_clova.py
git commit -m "feat: add hybrid semantic prompt"
```

### Task 5: Assemble and validate semantic links with server-owned IDs

**Files:**
- Create: `src/financial_agent/intent/hybrid_assembler.py`
- Create: `tests/intent/test_hybrid_assembler.py`
- Modify: `src/financial_agent/intent/draft.py`
- Modify: `src/financial_agent/intent/resolution.py`
- Modify: `src/financial_agent/intent/validation.py`
- Modify: `src/financial_agent/intent/context.py`
- Modify: `tests/intent/test_validation.py`
- Modify: `tests/intent/test_context.py`

**Interfaces:**
- Consumes: `IntentResolutionProposalV3`, `NormalizedRequest`, `ResolverViewV3`, and `SemanticCatalogSnapshot`.
- Produces: `SemanticLinkDraftV3`, `IntentResolutionDraftV3`, `ValidatedSemanticLinkV3`, `ValidatedIntentResolutionV3`, and `assemble_hybrid_proposal(...) -> IntentResolutionDraftV3`.

- [x] **Step 1: Write failing assembly tests for unhinted valid concepts**

```python
def test_assembler_accepts_registered_unhinted_semantic_link(v3_fixture) -> None:
    proposal = v3_fixture.proposal(
        question="비용 부담이 작은 ETF",
        semantic_id="fee_rate",
        omit_hint=True,
    )
    draft = assemble_hybrid_proposal(
        proposal, v3_fixture.normalized, v3_fixture.view, v3_fixture.catalog
    )
    assert draft.semantic_links[0].semantic_id == "fee_rate"
```

- [x] **Step 2: Write failing validation tests for unsafe selections**

Cover unknown semantic IDs, unknown mentions, exact-lock contradiction,
family-incompatible concepts, relation endpoint mismatch, a mention selected and
unmapped simultaneously, covered frames with unmapped evidence, and model
entity output when `entity_output_enabled` is false.

- [x] **Step 3: Run focused tests and verify V3 types are missing**

Run: `.venv/bin/pytest tests/intent/test_hybrid_assembler.py tests/intent/test_validation.py -q`

Expected: failures naming the V3 draft and validation contracts.

- [x] **Step 4: Add immutable V3 canonical contracts**

```python
class SemanticLinkDraftV3(ContractModel):
    semantic_link_id: Identifier
    frame_id: Identifier
    mention_id: Identifier
    semantic_ids: tuple[Identifier, ...] = Field(min_length=1)
    state: Literal["selected", "ambiguous"]
    evidence_span_ids: tuple[Identifier, ...] = Field(min_length=1)
    reason_code: Identifier

class IntentResolutionDraftV3(IntentResolutionDraftV2):
    semantic_links: tuple[SemanticLinkDraftV3, ...]

class ValidatedIntentResolutionV3(ValidatedIntentResolutionV2):
    semantic_links: tuple[ValidatedSemanticLinkV3, ...]
```

Frame ownership and ID uniqueness are validated in the contracts. V3 extends V2
so downstream readers can continue to consume common frame/context fields while
V3-aware consumers retain semantic-link provenance.

- [x] **Step 5: Implement deterministic assembly and validation order**

Use server-owned IDs derived from frame ordinal, mention ID, semantic IDs, and
proposal hash. Validate offered IDs before assembly, exact locks before semantic
coverage, applicability before contract solving, and relation endpoints before
entity projection. The validator may restore an omitted exact lock but may not
replace a model-selected concept.

- [x] **Step 6: Extend context validation without changing V2 behavior**

V3 reference graphs use the existing backward, acyclic, cardinality-safe rules.
When reference output is disabled, V3 rejects any reference, link, or mutation.
Run the existing prior-result and correction cases against both V2 and V3.

- [x] **Step 7: Run assembler, validation, and context tests**

Run: `.venv/bin/pytest tests/intent/test_hybrid_assembler.py tests/intent/test_assembler.py tests/intent/test_validation.py tests/intent/test_context.py -q`

Expected: all V2 and V3 tests pass with zero unknown-ID acceptance.

- [x] **Step 8: Commit V3 assembly and validation**

```bash
git add src/financial_agent/intent/hybrid_assembler.py src/financial_agent/intent/draft.py src/financial_agent/intent/resolution.py src/financial_agent/intent/validation.py src/financial_agent/intent/context.py tests/intent/test_hybrid_assembler.py tests/intent/test_validation.py tests/intent/test_context.py
git commit -m "feat: validate semantic links"
```

### Task 6: Integrate validated links with QueryContract solving

**Files:**
- Modify: `src/financial_agent/intent/query_contracts.py`
- Modify: `src/financial_agent/intent/query_contract_solver.py`
- Modify: `src/financial_agent/intent/service.py`
- Modify: `tests/intent/test_query_contract_solver.py`
- Modify: `tests/intent/test_query_contract_service.py`

**Interfaces:**
- Consumes: `ValidatedIntentResolutionV3`, `ResolverViewV3`, exact locks, literals, and `QueryContractRegistry`.
- Produces: V3-aware `_FieldOffer` inputs,
  `ProvenanceSourceKind.MODEL_SEMANTIC_LINK`,
  `QueryContractResolutionAttemptV3`, and
  `IntentResolverService.resolve_hybrid_query_contract_candidates(...)`.

- [x] **Step 1: Write failing solver tests for model-only field offers**

```python
def test_model_semantic_link_can_complete_fee_rank(v3_solver_inputs) -> None:
    result = solve_query_contracts(**v3_solver_inputs(
        question="비용 부담이 작은 ETF 다섯 개",
        action="rank",
        semantic_link="fee_rate",
    ))
    assert result.frames[0].complete_candidates
    contract = result.frames[0].complete_candidates[0].contract
    assert contract.ordering[0].field_concept_id == "fee_rate"
    assert any(
        item.source_kind is ProvenanceSourceKind.MODEL_SEMANTIC_LINK
        for item in contract.provenance
    )
```

- [x] **Step 2: Write failing negative tests**

Assert that an ambiguous link cannot form one complete candidate without a
deterministic disambiguator, an unmapped mention creates no contract, an
incompatible family creates a stable rejection, and a model link never outranks
a conflicting exact lock.

- [x] **Step 3: Run solver tests and verify model links are ignored by V2 code**

Run: `.venv/bin/pytest tests/intent/test_query_contract_solver.py -q`

Expected: the new V3 completion test fails with no complete candidate.

- [x] **Step 4: Add model-link field offers and provenance**

```python
class ProvenanceSourceKind(str, Enum):
    EXACT_LOCK = "exact_lock"
    MODEL_SEMANTIC_LINK = "model_semantic_link"
    AXIS_RESOLUTION = "axis_resolution"
    REGISTRY_DEFAULT = "registry_default"
    PRIOR_RESULT = "prior_result"
```

Merge selected V3 semantic links into coalesced field groups after exact locks
and before advisory hints. Keep ambiguous links as multiple bounded offers.
Attach mention and semantic-link IDs to provenance. Preserve the V2 path exactly.

- [x] **Step 5: Add the shadow V3 service entry point**

```python
async def resolve_hybrid_query_contract_candidates(
    self, context: RequestContext
) -> QueryContractResolutionAttemptV3:
    prepared = await self.prepare_hybrid(context)
    # one HCX call, optional shared repair, V3 validation, deterministic solve,
    # optional mutually exclusive offered-ID judge
```

`QueryContractResolutionAttemptV3` is a frozen dataclass with
`resolution: ValidatedIntentResolutionV3`,
`candidates: QueryContractCandidateSet`, and
`telemetry: QueryContractResolutionTelemetry`. `prepare_hybrid()` uses the V3
catalog, manifest, view, prompt, and proposal contracts; it does not reuse a V2
prompt through type coercion.

Do not switch `resolve_query_contract_candidates` to V3. Record preparation,
model, repair, validation, solve, and judge telemetry separately.

- [x] **Step 6: Run service and solver tests**

Run: `.venv/bin/pytest tests/intent/test_query_contract_solver.py tests/intent/test_query_contract_service.py tests/intent/test_service.py -q`

Expected: all V2 tests remain green; V3 uses one primary call and at most one
repair or judge.

- [x] **Step 7: Commit solver and service integration**

```bash
git add src/financial_agent/intent/query_contracts.py src/financial_agent/intent/query_contract_solver.py src/financial_agent/intent/service.py tests/intent/test_query_contract_solver.py tests/intent/test_query_contract_service.py
git commit -m "feat: solve contracts from semantic links"
```

### Task 7: Export and persist V3 artifacts without a lossy downgrade

**Files:**
- Modify: `src/financial_agent/intent/schema_export.py`
- Modify: `scripts/export_intent_schemas.py`
- Create: `schemas/intent/v3/intent-resolution-proposal.schema.json`
- Create: `schemas/intent/v3/resolver-build-manifest.schema.json`
- Create: `schemas/intent/v3/intent-resolution-draft.schema.json`
- Create: `schemas/intent/v3/validated-intent-resolution.schema.json`
- Modify: `src/financial_agent/db/repositories/artifacts.py`
- Modify: `tests/intent/test_schema_export.py`
- Modify: `tests/db/test_artifact_repository.py`

**Interfaces:**
- Consumes: ProposalV3, DraftV3, and ValidatedIntentResolutionV3.
- Produces: deterministic V3 JSON Schemas and schema-version dispatch for persisted `intent_resolution` artifacts.

- [x] **Step 1: Write failing schema export and persistence tests**

```python
def test_v3_intent_schemas_are_fresh(project_root: Path) -> None:
    check_schemas(project_root / "schemas/intent/v3", schema_version="3.0")


def test_intent_resolution_dispatch_restores_v3(v3_resolution_json: bytes) -> None:
    assert _artifact_model("intent_resolution", v3_resolution_json) is ValidatedIntentResolutionV3
```

Also assert that removing `semantic_links` from a V3 artifact fails rather than
dispatching it as V2.

- [x] **Step 2: Run schema and repository tests and verify failure**

Run: `.venv/bin/pytest tests/intent/test_schema_export.py tests/db/test_artifact_repository.py -q`

Expected: V3 is rejected as an unknown resolver schema version.

- [x] **Step 3: Add explicit V3 schema registry and artifact dispatch**

Extend accepted schema-version literals to `"1.0" | "2.0" | "3.0"`. Dispatch
only exact `3.0` manifests to `ValidatedIntentResolutionV3`. Do not add a fallback
for unknown versions.

Extend `scripts/export_intent_schemas.py` with strict `--schema-version` choices
`1.0`, `2.0`, and `3.0`, plus an explicit `--output-dir`. Preserve the current
no-argument V1 behavior.

- [x] **Step 4: Export committed V3 schemas using the repository script**

Run: `.venv/bin/python scripts/export_intent_schemas.py --schema-version 3.0 --output-dir schemas/intent/v3`

Expected: exactly four V3 schema files are generated deterministically.

- [x] **Step 5: Verify repository round-trip and database contract compatibility**

Run: `.venv/bin/pytest tests/db/test_artifact_repository.py tests/db/test_migration_cycle.py -q`

Expected: V1, V2, and V3 artifacts round-trip through the existing immutable
JSON boundary. This task adds no migration; a failing database-contract test
blocks completion and requires a separately reviewed migration plan.

- [x] **Step 6: Commit schema and persistence support**

```bash
git add src/financial_agent/intent/schema_export.py scripts/export_intent_schemas.py schemas/intent/v3 src/financial_agent/db/repositories/artifacts.py tests/intent/test_schema_export.py tests/db/test_artifact_repository.py
git commit -m "feat: persist hybrid intent artifacts"
```

### Task 8: Add an explicitly injected active-snapshot qualifier policy

**Files:**
- Create: `src/financial_agent/intent/semantic_defaults.py`
- Create: `config/intent/semantic-default-policy-registry.v1.json`
- Create: `tests/intent/test_semantic_defaults.py`
- Modify: `src/financial_agent/intent/query_contract_solver.py`
- Modify: `src/financial_agent/intent/service.py`
- Modify: `tests/intent/test_query_contract_solver.py`

**Interfaces:**
- Consumes: a dataset-version and manifest-hash pinned `DatasetSemanticDefaultsV1` supplied by the service caller.
- Produces: `SemanticDefaultPolicyRegistry`, `load_semantic_default_policy_registry(project_root)`, and eligible `as_of` qualifier offers with registry provenance.

- [x] **Step 1: Write failing positive and negative default tests**

```python
def test_verified_dataset_date_completes_aum_rank(v3_solver_inputs) -> None:
    defaults = DatasetSemanticDefaultsV1(
        dataset_version="dataset-v1",
        manifest_hash="0" * 64,
        defaults=(SemanticAsOfDefaultV1(
            default_record_id="dataset-v1-overseas-etf-aum",
            product_family_id="overseas_etf",
            semantic_id="aum",
            as_of_date=date(2026, 8, 21),
        ),),
    )
    result = solve_query_contracts(**v3_solver_inputs(
        action="rank", semantic_link="aum", defaults=defaults
    ))
    contract = result.frames[0].complete_candidates[0].contract
    assert contract.qualifiers.as_of_date == date(2026, 8, 21)


def test_cutoff_date_is_not_used_as_an_observation_default(v3_solver_inputs) -> None:
    result = solve_query_contracts(**v3_solver_inputs(
        action="rank", semantic_link="aum", defaults=None
    ))
    assert not result.frames[0].complete_candidates
    assert "REQUIRED_QUALIFIER_MISSING" in result.frames[0].contract_readiness.reason_codes
```

- [x] **Step 2: Run the tests and verify AUM remains incomplete**

Run: `.venv/bin/pytest tests/intent/test_semantic_defaults.py tests/intent/test_query_contract_solver.py -q`

Expected: the positive test fails because no default registry is connected.

- [x] **Step 3: Implement the pinned input and registry**

```python
class SemanticAsOfDefaultV1(ContractModel):
    default_record_id: Identifier
    product_family_id: Identifier
    semantic_id: Identifier
    as_of_date: date

class DatasetSemanticDefaultsV1(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_version: Identifier
    manifest_hash: Sha256Hex
    defaults: tuple[SemanticAsOfDefaultV1, ...]
```

The JSON registry contains only `active-dataset-as-of.v1`, kind `default`, the
eligible snapshot concepts, and applicable families. Runtime dates never live
in the tracked registry; callers supply them from verified dataset metadata.

- [x] **Step 4: Apply defaults only after pin and conflict validation**

Reject dataset or manifest mismatch, multiple dates, a date after the request
cutoff, an ineligible concept/family, and conflict with an explicit date. Add
`REGISTRY_DEFAULT` provenance containing the policy ID and the supplied default
record ID.

- [x] **Step 5: Run default and solver tests**

Run: `.venv/bin/pytest tests/intent/test_semantic_defaults.py tests/intent/test_query_contract_solver.py tests/intent/test_query_contract_service.py -q`

Expected: AUM completes only with an eligible pinned date; no existing fixture
uses the cutoff date as a substitute observation date.

- [x] **Step 6: Commit registered semantic defaults**

```bash
git add config/intent/semantic-default-policy-registry.v1.json src/financial_agent/intent/semantic_defaults.py src/financial_agent/intent/query_contract_solver.py src/financial_agent/intent/service.py tests/intent/test_semantic_defaults.py tests/intent/test_query_contract_solver.py tests/intent/test_query_contract_service.py
git commit -m "feat: add pinned semantic defaults"
```

### Task 9: Add V3 stage-specific evaluation and corrected representative scoring

**Files:**
- Modify: `src/financial_agent/intent/evaluation.py`
- Modify: `scripts/evaluate_intent_resolver.py`
- Modify: `scripts/run_semantic_query_benchmark.py`
- Modify: `tests/evaluation/intent/test_intent_evaluation.py`
- Modify: `tests/evaluation/query_contract/test_end_to_end_metrics.py`
- Modify: `tests/evaluation/query_contract/test_decoupled_resolution.py`
- Create: `tests/evaluation/intent/hybrid_semantic_link_cases.v1.json`

**Interfaces:**
- Consumes: existing 160-case held-out gold, V3 span/link predictions, representative contract expectations, and V2/V3 runtime evidence.
- Produces: separate mention-span, hint, selectability, structured, semantic-link, frame, OOD, contract, and planning metrics.

- [x] **Step 1: Write failing metric-separation tests**

```python
def test_missing_hint_does_not_fail_catalog_selectability() -> None:
    metrics = evaluate_hybrid_prediction(case_without_fee_hint, prediction_with_fee_link)
    assert metrics.hint_recall_at_5 == Decimal("0")
    assert metrics.catalog_selectability == Decimal("1")
    assert metrics.semantic_link_recall == Decimal("1")


def test_representative_cases_score_independently() -> None:
    observations = four_exact_observations_and_one_missing()
    metric = evaluate_representative_contracts(observations)
    assert metric.successes == 4
    assert metric.total == 5
```

- [x] **Step 2: Add focused unseen-paraphrase and contrastive OOD fixtures**

The new fixture contains, at minimum:

```json
[
  {"question":"비용 부담이 작은 ETF 다섯 개","semantic_ids":["fee_rate"],"ood":false},
  {"question":"신용 상태가 우수한 국내 채권","semantic_ids":["credit_grade"],"ood":false},
  {"question":"만기까지 얼마 안 남은 채권","semantic_ids":["remaining_days"],"ood":false},
  {"question":"성과가 괜찮은 해외 ETF","semantic_ids":["trailing_1y_historical_cumulative_return"],"ood":false},
  {"question":"ESG 등급이 높은 ETF","semantic_ids":[],"ood":true}
]
```

Define a strict `HybridSemanticLinkCase` with `case_id`, `question`,
`expected_action_ids`, `expected_product_family_ids`, `expected_span_texts`,
`expected_semantic_ids`, `expected_coverage_state`, and `expected_ood`. Populate
all eight fields for each of the five records; fixture loading rejects missing
or extra fields.

- [x] **Step 3: Run evaluation tests and verify missing V3 metrics**

Run: `.venv/bin/pytest tests/evaluation/intent/test_intent_evaluation.py tests/evaluation/query_contract/test_end_to_end_metrics.py -q`

Expected: failures naming hybrid metrics and independent representative scoring.

- [x] **Step 4: Implement complete-denominator V3 metrics**

Keep V2 report fields unchanged. Add V3 fields for required span preservation,
hint recall, exact-lock precision, compact-catalog selectability, first-pass and
repaired validity, Action/Family/semantic-link/frame/context exactness, OOD
false-fast, complete-contract exactness, and provider telemetry. A missing
denominator is `unmeasured`, never pass.

Add `hybrid-deterministic` to the strict resolver-evaluation mode choices. Add
`--offline` and `--include-hybrid-v3` to the semantic benchmark CLI; `--offline`
must prohibit provider calls even when credentials are present, while
`--include-hybrid-v3` reports V2 and V3 under separate path IDs.

- [x] **Step 5: Normalize only registered semantic equivalence before contract comparison**

Normalize explicit descending and `default-direction-descending.v1` only when
the registry proves equivalence. Keep predicate value units separate from query
qualifiers so a duplicated unit representation is not labeled an intent error.
Do not normalize differing filters, fields, dates, periods, grains, de-duplication,
or comparison bases.

- [x] **Step 6: Run deterministic V2 and V3 reports**

Run: `.venv/bin/python scripts/evaluate_intent_resolver.py deterministic --output build/reports/intent-resolver-v2-deterministic.json`

Run: `.venv/bin/python scripts/evaluate_intent_resolver.py hybrid-deterministic --output build/reports/intent-resolver-v3-deterministic.json`

Expected: V2 remains `123/196`; V3 catalog selectability is `196/196` held-out
expected concept occurrences from 42 registered concepts; hint recall is
reported diagnostically; the V3-path diagnostics report exact locks `140/140`
and required spans `253/253`. The authoritative top-level exact-lock promotion
gate remains `unmeasured` until its complete population is defined.

- [x] **Step 7: Run query-contract evaluation tests**

Run: `.venv/bin/pytest tests/evaluation/query_contract/test_decoupled_resolution.py tests/evaluation/query_contract/test_end_to_end_metrics.py -q`

Expected: representative cases score independently and incomplete contract gold
remains `unmeasured` rather than passing on 43 measured frames.

- [x] **Step 8: Commit V3 evaluation**

```bash
git add src/financial_agent/intent/evaluation.py scripts/evaluate_intent_resolver.py scripts/run_semantic_query_benchmark.py tests/evaluation/intent/test_intent_evaluation.py tests/evaluation/intent/hybrid_semantic_link_cases.v1.json tests/evaluation/query_contract/test_end_to_end_metrics.py tests/evaluation/query_contract/test_decoupled_resolution.py
git commit -m "test: measure hybrid intent resolution"
```

### Task 10: Verify the shadow V3 resolver and record promotion status

**Files:**
- Create: `docs/planning/verification/2026-09-03-hybrid-full-catalog-semantic-linking-verification.md`
- Modify: `docs/planning/STATUS.md`
- Modify: `docs/planning/tasks/2026-09-03-hybrid-full-catalog-semantic-linking-implementation-plan.md`

**Interfaces:**
- Consumes: every V3 implementation task, deterministic reports, optional PostgreSQL evidence, and authorized HCX-007 credentials.
- Produces: one reproducible verification record and a fail-closed promotion status.

- [x] **Step 1: Run the narrow V3 suite**

Run: `.venv/bin/pytest tests/intent/test_compact_catalog.py tests/intent/test_mention_spans.py tests/intent/test_hybrid_proposal.py tests/intent/test_hybrid_prompt.py tests/intent/test_hybrid_assembler.py tests/intent/test_query_contract_solver.py tests/intent/test_query_contract_service.py -q`

Expected: zero failures.

- [x] **Step 2: Run all Intent Resolver and evaluation tests**

Run: `.venv/bin/pytest tests/intent tests/evaluation/intent tests/evaluation/query_contract -q`

Expected: zero failures, with provider and PostgreSQL markers deselected unless
their explicit environments are configured.

- [x] **Step 3: Run the broad offline suite**

Run: `.venv/bin/pytest -m "not ncp and not live and not postgres" -q`

Expected: zero failures; only documented environment-dependent skips or
deselections are accepted.

- [x] **Step 4: Verify schemas, compilation, dependencies, and diff scope**

Run: `.venv/bin/python -m compileall -q src scripts tests`

Run: `.venv/bin/python scripts/export_intent_schemas.py --check --schema-version 2.0 --output-dir schemas/intent/v2`

Run: `.venv/bin/python scripts/export_intent_schemas.py --check --schema-version 3.0 --output-dir schemas/intent/v3`

Run: `git diff --check`

Expected: every command exits zero and no secret-bearing or organizer source file
is staged.

- [x] **Step 5: Produce the offline promotion report**

Run: `.venv/bin/python scripts/run_semantic_query_benchmark.py --offline --include-hybrid-v3 --sanitized-report /private/tmp/hybrid-semantic-query-offline.json`

Expected: every available offline gate is explicitly `pass`, `fail`, or
`unmeasured`; V3 remains non-default if any required gate is fail or unmeasured.

- [x] **Step 6: Inspect and integrity-verify the already-authorized HCX-007 shadow comparison**

Inspect the existing sanitized report at
`/private/tmp/hybrid-semantic-query-live-verified.json`, revalidate its exact
fields, and recompute its embedded canonical report hash. Do not repeat provider
calls and do not read, copy, hash, or stage the protected raw-response file.

Expected: V2 and V3 paths are reported separately with primary, repair, judge,
provider, token, p50, p95, schema, semantic, contract, and OOD metrics. Raw
responses remain mode `0600` under `/private/tmp` and are never staged.

- [x] **Step 7: Record exact evidence and keep promotion fail closed**

The new verification document records commit SHA, source/config hashes, exact
commands, counts, gate results, unavailable denominators, live-call totals, and
remaining limitations. Update `STATUS.md` to `implemented, shadow-only` only when
the code and offline suite pass. It explicitly accounts for every design/ADR V3
promotion gate; missing or partial denominators remain `unmeasured`. Do not state
that V3 is promoted unless every gate passes and the user separately approves
promotion.

- [x] **Step 8: Inspect and commit only verified task paths**

Run: `git status --short`

Run: `git diff --cached --check`

Run: `git diff --cached`

Commit:

```bash
git commit -m "docs: verify hybrid intent resolution"
```

Expected: the branch is clean, V2 remains the default, and the verification
document states the measured promotion status without inference.

## Completion Definition

This implementation plan is complete only when all ten tasks are implemented,
their focused tests and the broad offline suite pass, generated V3 schemas are
fresh, stored V3 artifacts round-trip without loss, and the verification report
records every required gate. HCX live evidence may remain unavailable when no
authorized credential or offline qualification exists, but that leaves V3
promotion deferred; it does not block completion of the shadow implementation.

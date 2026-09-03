# Hybrid Full-Catalog Semantic Linking Design

**Date:** 2026-09-03

**Status:** Approved

**Decision:** [ADR-0030](../decisions/ADR-0030-use-hybrid-full-catalog-semantic-linking.md)

## 1. Outcome

Convert a Korean financial-product question into validated atomic frames and
semantic query inputs without making deterministic Korean candidate recall a
hard ceiling and without allowing HCX to create executable identifiers.

```text
RequestContext
  -> deterministic normalization and literals
  -> meaning-neutral mention spans
  -> exact locks + advisory semantic hints
  -> full CompactSemanticCatalog
  -> one HCX frame/axis/semantic-link call
  -> strict server validation and exact-lock reconciliation
  -> deterministic QueryContract candidate solving
  -> Fast / Compose / Explore / Abstain
```

The public API, deterministic Orchestrator, QueryContract grammar, physical SQL
compiler, and executor boundaries do not change.

## 2. Problem Being Corrected

The current flow offers every registered Action, ProductFamily, and entity type,
but offers only request-local semantic concepts reached by alias or trigram
candidate generation. A missing candidate therefore has two effects:

1. its concept definition is absent from `ResolverView`; and
2. strict validation prevents HCX from selecting it even if HCX understands the
   Korean phrase.

The candidate generator currently indexes overlay aliases and canonical IDs,
not model-facing preferred labels or semantic definitions. It produces fuzzy
mentions only from a full segment and whitespace-separated tokens. This makes
the system deterministic but leaves compound Korean paraphrases outside the
selectable vocabulary.

The latest evidence separates this retrieval defect from the HCX defect:

| Boundary | Evidence | Interpretation |
| --- | ---: | --- |
| deterministic candidate recall@5 | 123/196 | 73 gold concepts never offered |
| registered entity-type reachability | 155/155 | prior type-choice defect fixed |
| live provider success | 16/16 | transport is healthy |
| live strict resolution validity | 11/16 | response structure remains fragile |
| family exact among valid responses | 11/11 | HCX family interpretation is strong when valid |
| action exact among valid responses | 10/11 | HCX action interpretation is mostly correct when valid |
| live complete contracts | 4/16 | semantic and qualifier completion remains downstream work |

The new design removes the first hard ceiling and narrows the second response
surface.

## 3. Design Principles

1. **Full registered selectability:** every cataloged semantic concept is
   selectable without an alias hit.
2. **Closed vocabulary:** HCX selects only server-owned IDs.
3. **Exact facts remain deterministic:** unique exact expressions, literals,
   operators, and family anchors remain locks.
4. **Language understanding belongs to HCX:** unseen Korean paraphrases are
   linked from source spans to catalog meanings by HCX.
5. **Execution meaning remains deterministic:** HCX does not select SQL,
   physical bindings, formulas, policies, or arbitrary contract bodies.
6. **Smallest request schema:** impossible entity and context branches are not
   offered.
7. **Unknown is a valid semantic result:** the model may explicitly return
   unmapped or ambiguous evidence instead of forcing a nearest concept.
8. **Stage-specific evaluation:** retrieval, semantic linking, validation,
   contract solving, and physical readiness are measured separately.

## 4. Responsibility Matrix

| Concern | Owner |
| --- | --- |
| Unicode, spacing, segment and source preservation | deterministic normalizer |
| numbers, percentages, dates, periods, limits, operators | deterministic literal extraction |
| meaning-neutral source spans | deterministic mention-span generator |
| canonical/direct aliases and exact locks | Korean overlay + deterministic lock builder |
| advisory candidate hints | deterministic lexical candidate generator |
| Action, ProductFamily, frame split, source-span semantic linking | one HCX call |
| explicit unmapped and ambiguity reporting | HCX proposal + server validator |
| registered-ID, applicability, relation endpoint, exact-lock validation | deterministic validator |
| contract variant, field role, default, policy, and candidate enumeration | deterministic QueryContract solver |
| SQL/Graph/Search/Calculation routing and execution | deterministic planner/orchestrator/executors |

## 5. Model-Facing Inputs

### 5.1 Meaning-neutral mention spans

`MentionSpanSetV1` is generated before any semantic concept is selected. A span
contains:

```text
mention_id
segment_id
text
normalized_text
start_char
end_char
source_kind
```

`source_kind` is one of `exact_anchor`, `literal_context`, `reference`,
`entity`, or `phrase`. Phrase spans are normalized contiguous source spans,
not inferred meanings.

Span generation follows these priorities:

1. preserve all exact lock, literal, reference, and named-entity ranges;
2. add their smallest surrounding phrase when needed for interpretation;
3. add bounded contiguous phrase spans for remaining text;
4. de-duplicate identical normalized ranges; and
5. fail closed if required preserved spans alone exceed the bound.

The implementation plan must choose and benchmark the phrase-window and total
span bounds. No test may depend on silently dropping a required range.

### 5.2 Compact semantic concept cards

`CompactSemanticCatalogV1` is deterministically generated and build-pinned. A
concept card contains:

```json
{
  "semantic_id": "fee_rate",
  "preferred_label_ko": "총보수 및 비용률",
  "definition_ko": "상품을 보유하는 동안 부담하는 보수 또는 비용 비율",
  "concept_kind": "metric",
  "value_kind": "decimal",
  "applicable_family_ids": [
    "domestic_etf",
    "overseas_etf",
    "public_fund"
  ],
  "required_qualifier_ids": [],
  "disambiguation_ko": "채권의 수익률을 뜻하는 yield_rate와 구분"
}
```

The card is a projection, not a separately authored ontology. Canonical IDs,
kind, value kind, applicability, and qualifiers come from the semantic catalog
and ontology. The Korean overlay may own the preferred model-facing label and a
bounded disambiguation sentence. Compilation fails if any registered concept
lacks a valid compact card.

Raw TBox, SHACL, physical bindings, source fields, SQL identifiers, and formulas
are excluded.

### 5.3 Exact locks and advisory hints

The model-facing view distinguishes:

- `exact_semantic_locks`: canonical or unique direct-alias facts reconciled by
  the server after inference; and
- `semantic_candidate_hints`: ranked group, ambiguous, or fuzzy suggestions.

Hints may order or emphasize concept cards but cannot remove cards. HCX may
select a catalog ID that has no hint. HCX may not contradict an exact lock.

The current `preferred_label` indexing defect is corrected, but a preferred
label becomes an exact lock only if the overlay declares it a unique direct
alias. Merely showing a label to HCX must not silently raise its deterministic
authority.

## 6. Model-Facing Output

### 6.1 Minimal frame

The normal simple-query response contains:

```json
{
  "proposal_schema_version": "3.0",
  "frames": [
    {
      "segment_ids": ["segment-0"],
      "action_choice": {
        "state": "selected",
        "selected_ids": ["rank"]
      },
      "product_family_choice": {
        "state": "selected",
        "selected_ids": ["domestic_etf", "overseas_etf"]
      },
      "semantic_links": [
        {
          "mention_id": "mention-cost-burden",
          "semantic_id": "fee_rate",
          "state": "selected"
        }
      ],
      "unmapped_mention_ids": [],
      "semantic_coverage": "covered"
    }
  ]
}
```

`semantic_links` express source meaning, not executable slot placement. The
contract solver determines whether a linked concept can serve as a predicate
field, ordering field, aggregate target, projection, relation, or explanation
topic under the selected action and other source evidence.

### 6.2 Ambiguous and unmapped meanings

An ambiguous link selects two or more registered candidate IDs for one offered
mention and uses `state="ambiguous"`. A model may not label a one-ID selection
ambiguous.

An intent-bearing mention that cannot be grounded appears in
`unmapped_mention_ids`. Covered frames must have no unmapped intent-bearing
mentions. Partial and unmapped frames cannot enter Fast or Compose.

No numeric confidence is accepted or used for routing.

### 6.3 Conditional entity and context branches

`entity_hints` are available only when deterministic preparation produced at
least one named-entity mention. A relation concept can still be selected in
`semantic_links`; relation endpoint identity grounding is requested only when
an entity mention exists.

Reference, context-link, and slot-mutation structures are available only when
the request includes a server-owned reference candidate. The existing backward,
acyclic, cardinality-safe context rules remain unchanged.

For a request without entity or reference evidence, those arrays are absent or
schema-bounded to zero. This prevents simple aggregate and rank questions from
creating invalid relation-object hints.

## 7. Validation and Reconciliation

Validation runs in this order:

1. parse one strict JSON object and validate the request-specific schema;
2. replace frame ordinals with server-owned IDs;
3. validate every segment, mention, Action, ProductFamily, and semantic ID;
4. validate semantic-link state and uniqueness;
5. reconcile exact locks and reject contradictions;
6. validate concept applicability across selected ProductFamily values;
7. validate relation domain/range and named-entity endpoint types;
8. validate coverage against selected, ambiguous, and unmapped mentions;
9. validate the existing reference graph when present; and
10. emit a versioned validated resolution or one stable failure code.

The validator may add an omitted exact lock and canonicalize representation. It
may not choose between ambiguous model selections, replace an incompatible
concept, or turn unmapped evidence into covered evidence.

One request-wide repair remains available for schema and bounded contract
violations. Semantic ambiguity and OOD do not trigger repair.

## 8. QueryContract Integration

Each validated semantic link becomes a source-bound `_FieldOffer` or relation
offer. The existing exact locks remain higher-authority offers. The solver:

1. selects registered variants for the validated Action;
2. applies exact scope and literal constraints;
3. enumerates compatible roles for validated semantic links;
4. rejects family, value-kind, operator, qualifier, relation, and policy
   incompatibility;
5. emits only complete registered contracts; and
6. uses the existing deterministic tie-break or one offered-ID-only judge.

HCX never directly returns `filter_field`, `sort_key`, aggregation function,
population grain, de-duplication policy, physical binding, or SQL. These remain
derived from the selected action, linked meanings, literals, exact language
cues, registered defaults, and bounded candidate solving.

The implementation must preserve all source spans and distinguish deterministic
locks from model semantic links in provenance.

## 9. Registered Defaults

Defaults are separate from language interpretation. A missing qualifier is not
implicitly filled because HCX selected a concept.

The first implementation should add a registry-owned active-snapshot policy for
metrics whose semantic meaning requires `as_of` but whose ordinary question
omits a date. The policy is eligible only when:

- the active dataset has one verified applicable observation date;
- the concept and family permit the policy;
- no explicit or context-linked date conflicts;
- the contract records the policy ID and resolved date; and
- the evidence and answer disclose the effective date.

Otherwise the contract remains incomplete. Period, currency, unit, aggregation
grain, and de-duplication continue to require explicit evidence or their own
approved registered policies.

## 10. OOD and Failure Behavior

| Situation | Result |
| --- | --- |
| registered concept expressed by unseen Korean paraphrase | HCX semantic link, then validation |
| multiple registered meanings remain plausible | ambiguous link, no Fast route |
| requested property is absent from the compact catalog | unmapped, then Explore/Limitation |
| registered concept is incompatible with selected family | deterministic rejection |
| registered concept lacks physical binding | PlanReadiness limited; no executable SQL |
| model creates an ID or mention | strict failure, optional shared repair |
| span bound would remove required evidence | fail closed before model call |

The full catalog increases the risk of nearest-concept coercion. Evaluation must
therefore include contrastive negatives such as ESG versus product risk grade,
credit grade versus product risk grade, NAV versus AUM, return versus yield, and
remaining days versus remaining maturity.

## 11. Versioning and Persistence

The implementation requires coordinated new versions for:

- mention-span policy;
- CompactSemanticCatalog projection;
- ResolverView;
- prompt;
- Proposal and validated resolution;
- adapter schema identifier;
- persisted intent-resolution artifact payload; and
- evaluation report.

Historical V2 artifacts remain readable and immutable. V3 output must not be
flattened into V2 if semantic links or unmapped mention evidence would be lost.
No PostgreSQL DDL change is assumed; persistence tests determine whether the
existing immutable JSON artifact boundary can store the new version safely.

## 12. Evaluation

### 12.1 Required stage metrics

The report keeps distinct denominators for:

1. mention-span source coverage;
2. deterministic hint recall and exact-lock precision;
3. compact-catalog selectability;
4. first-pass and repaired schema validity;
5. Action, ProductFamily, semantic-link, frame, and context exactness;
6. OOD false-fast behavior;
7. complete-contract candidate recall and exactness;
8. PlanReadiness and deterministic compilation; and
9. provider calls, repair/judge use, tokens, latency, and rate limits.

Candidate recall at five remains visible but is not treated as semantic
selectability.

### 12.2 Representative regression cases

At minimum, live and deterministic fixtures cover:

- exact fee screen: `공모펀드 중 총보수가 1% 이하인 상품`;
- unseen fee paraphrase: `비용 부담이 작은 ETF`;
- public-fund AUM sum with registered snapshot default;
- overseas-ETF AUM rank with a result limit;
- domestic-ETF one-year return rank;
- domestic-bond credit-grade screen;
- grouped aggregate without entity hints;
- two-frame prior-result reference;
- vocabulary OOD such as ESG; and
- domain OOD such as a general market-outlook question.

The five representative contract cases are scored independently. Semantic
equivalence owned by registered policies is normalized before exact comparison;
schema validity, semantic exactness, contract completeness, and representation
canonicalization remain separate metrics.

### 12.3 Promotion gates

| Gate | Required value |
| --- | ---: |
| registered compact-catalog selectability | 100% |
| preserved required mention spans | 100% |
| exact-lock precision | 100% |
| requested semantic-link recall | at least 99% |
| first-pass structured validity | at least 99% |
| held-out joint frame exact | at least 90% |
| held-out context-link exact | at least 95% |
| supported complete-contract exact | at least 95% on complete gold denominator |
| OOD false-fast | at most 2% |
| unknown-ID acceptance | 0 |
| physical-schema tokens in HCX prompts or outputs | 0 |

Missing or partial denominators remain `unmeasured`; they do not pass by
substituting a smaller positive subset.

## 13. Rollout

1. Generate and validate compact catalog cards and meaning-neutral spans.
2. Add V3 contracts and validators behind a non-default path.
3. Integrate semantic links with exact-lock reconciliation and contract solving.
4. Add snapshot qualifier policy as a separately pinned registry rule.
5. Run deterministic held-out and adversarial OOD evaluation.
6. Run paced HCX-007 shadow evaluation against the V2 baseline.
7. Review tokens, latency, repair rate, and every promotion gate.
8. Promote only through a separate explicit decision after complete evidence.

V2 remains the default until V3 passes the approved gates. No deployment,
dataset activation, public API change, or executor expansion is part of this
design.

## 14. Success Criteria

The design is correctly implemented when:

1. removing an advisory alias does not make its registered concept impossible
   for HCX to select;
2. exact direct aliases remain deterministic and unchangeable by HCX;
3. an unseen Korean paraphrase can link to a registered meaning with exact
   source provenance;
4. an unknown property can remain explicitly unmapped instead of being forced
   to the nearest catalog concept;
5. simple questions cannot emit entity or reference structures without offered
   evidence;
6. no model-facing payload contains physical schema or executable SQL choices;
7. validated links can produce complete registered QueryContracts without
   model-authored slot or contract bodies;
8. omitted snapshot dates use only the registered and disclosed active-snapshot
   policy;
9. historical V2 behavior and artifacts remain readable; and
10. all promotion gates are measured on their complete authoritative
    denominators before V3 becomes the default.

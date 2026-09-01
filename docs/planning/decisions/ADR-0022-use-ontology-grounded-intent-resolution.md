# ADR-0022: Use Ontology-Grounded Intent Resolution Before QueryPlan Compilation

**Date:** 2026-08-31

**Status:** Accepted

**Approved:** 2026-08-31 — the user approved the ontology-grounded design,
requested a hold-scope critical review, and authorized moving to formal design
documentation.

**Amends:** [ADR-0005](ADR-0005-bounded-llm-typed-capability-execution.md)
only where it describes the LLM itself as the direct QueryPlan producer.

**Related:** [Planning Harness](../HARNESS.md),
[Runtime Contracts](../architecture/RUNTIME_CONTRACTS.md),
[Financial Ontology Architecture](../architecture/FINANCIAL_ONTOLOGY_ARCHITECTURE.md),
[ADR-0006](ADR-0006-separate-disposition-and-bound-recovery.md),
[ADR-0018](ADR-0018-keep-minimal-ontology-with-canonical-multi-role-products.md),
[ADR-0021](ADR-0021-amend-minimal-ontology-for-question-contract-semantics.md),
[Intent Resolver Design](../specs/2026-08-31-intent-resolver-design.md)

## Context

ADR-0005 correctly limits the normal path to one Intent Resolver LLM and one
Answer Composer LLM, but its initial contract description assumes that the
Intent Resolver model directly emits QueryPlan. That places product-family
scope, executable operations, bindings, dependencies, capabilities,
answerability, and ambiguity policy in one model output.

The project now has stronger deterministic semantic assets:

- the four frozen ProductFamily values and eight IntentType values;
- a minimal financial ontology with explicit classes, disjointness,
  multi-role products, and 13 approved relationship predicates;
- PostgreSQL entity aliases and versioned metric definitions;
- a normalized six-group question requirement model; and
- 52 regression questions containing Korean compound, contextual, ambiguous,
  unsupported, and relationship-driven cases.

Direct model-to-QueryPlan generation would fail to use these assets as hard
constraints. A separate hand-maintained resolver vocabulary would instead
duplicate them and create another source of truth. The model also needs to
recognize Korean paraphrases, ellipsis, demonstratives, corrections, and
multi-intent utterances without being allowed to invent executable IDs.

## Decision

### Keep the external architecture and narrow the internal LLM role

The external Intent Resolver component still accepts RequestContext and, after
Phase 2 compilation, produces the existing QueryPlan consumed by the
Orchestrator.

Internally, the component is split into:

1. deterministic normalization and literal extraction;
2. bounded candidate generation from a generated ResolverView;
3. one HyperCLOVA X structured inference call;
4. strict draft validation and deterministic tag enrichment;
5. a validated internal intent-resolution artifact; and
6. a deterministic QueryPlan compiler designed and implemented in Phase 2.

The LLM emits IntentResolutionDraft, not QueryPlan. The compiler may use only a
ValidatedIntentResolution and registered catalog IDs. QueryPlan remains
unchanged.

Phase 2 must prove that every context link, selector, slot mutation, and frame
dependency used for execution can be lowered without semantic loss into the
current QueryPlan fields: resolved_references, binding_specs,
dependency_edges, and registered operation parameters. If a construct cannot
be represented, compilation must fail closed and a separate contract-change
ADR is required. The compiler must never silently discard internal semantics
to preserve the old shape.

### Use a shared semantic catalog, not a resolver-only ontology

Create a versioned SemanticQueryCatalog that owns the abstract query concepts
shared by Intent Resolution and the later QueryPlan compiler. It references
rather than duplicates:

- ProductFamily and IntentType from the frozen runtime enums;
- entity types, class constraints, and relations from the TBox and SHACL;
- controlled attribute and abstract metric concepts approved for query use;
- required qualifiers, value kinds, and applicability constraints; and
- registered selectors, operators, source roles, and semantic flags.

A separate Korean NLU overlay maps Korean labels, synonyms, spacing variants,
and common paraphrases to catalog IDs. Entity names remain in the existing
dataset-versioned catalog.alias store. The NLU overlay does not become a
second entity-alias database.

ResolverView is a bounded, generated, read-only projection of the catalog and
NLU overlay. Runtime requests do not load the entire ontology into the prompt.

### Keep evaluation data out of the production dependency graph

tests/gold/core_questions.json is a regression consumer of the production
semantic catalog. It must validate that its semantic IDs exist, but production
catalog compilation and request serving must never read the gold question
file. Existing cases may inform the initial catalog audit but cannot become a
runtime lookup table or an archetype-only classifier.

### Separate surface segmentation from executable frames

RequestContext segments preserve ordered surface or pseudo-turn units. An
IntentResolutionDraft contains one or more atomic intent frames that reference
those segments. One segment may produce multiple frames, and multiple frames
may share evidence spans. Each frame has exactly one action from the frozen
eight-value IntentType vocabulary.

This prevents punctuation or conjunction boundaries from deciding executable
subtasks and supports compound requests such as compare-and-rank without
inventing composite runtime intent labels.

### Separate product-family scope from ontology type constraints

The four ProductFamily values identify storage and capability scope.
Ontology entity types express economic type constraints such as ETF versus ETN,
RepresentativeFund versus FundShareClass, and ProductRiskGrade versus
CreditGrade. The resolver preserves both. It must not force all ontology types
into ProductFamily or assume product families are mutually exclusive.

### Make context links typed and fail closed

References may target an entity, result set, metric value, related entity,
prior operation, evidence records, or an exclusion set. The draft records
reference form, expected type, cardinality, selector, producer frame, and
consumer frame.

Only backward, acyclic links are permitted in the first version. A many-valued
source cannot become one value without an explicit selector. Explicit evidence
in the current frame overrides a valid context link, which overrides an
explicitly permitted carryover, which overrides an approved default. Conflicts
remain visible.

Slot mutations use CARRYOVER, UPDATE, DELETE, and DONTCARE. Carryover is
opt-in, not the default.

### Preserve one normal-path model call and bounded recovery

The normal resolver path uses one structured model call containing the full
request context and bounded candidate set. Per-axis parallel calls remain an
offline benchmark challenger only.

Schema, unknown-ID, evidence-span, and context-graph violations are planner
contract failures. They may consume the one request-wide LLM repair allowance.
Semantic ambiguity, vocabulary OOD, and unresolved context do not trigger a
second model call. Transient provider failures follow ADR-0006 retry limits.

No numeric model confidence controls routing.

### Add internal provenance without changing the public API

Stage 06 implementation will add one internal intent_resolution artifact type
to the existing request-artifact ledger. It will bind the schema-valid model
draft, validated resolution, validation events, catalog and ontology hashes,
candidate-policy version, model ID, and prompt version.

Invalid raw model output is not stored as a valid artifact. Its hash, byte
length, and stable failure code may be recorded in FailureEvent. QueryPlan is
stored as deterministic compiler output and no longer carries direct-model
producer semantics.

This decision does not change GET /answer, RequestContext, or QueryPlan.

## Promotion Gates

Before the new resolver can become the default:

- unknown registered-ID acceptance must be zero;
- invalid context-graph acceptance must be zero;
- deterministic candidate generation must be 100 percent reproducible;
- semantic candidate recall at five must be at least 99 percent;
- first-pass structured-output validity must be at least 99 percent;
- held-out joint frame exact match must be at least 90 percent;
- held-out context-link exact match must be at least 95 percent; and
- OOD false-fast rate must be at most 2 percent.

For this Phase 1 gate, false-fast means a vocabulary, domain, or context OOD
case incorrectly leaves validation as resolved with no blocking issue, which
would make it eligible for a later Fast route. Phase 2 adds its own actual
route-confusion measurement.

Model adapters are compared on those correctness measures plus repair rate,
p95 latency, token use, and cost. Failing a gate blocks promotion; validation
is not loosened to raise coverage.

## Rejected Alternatives

### Continue direct LLM-to-QueryPlan generation

Rejected because it exposes too many executable choices at once, makes Korean
context errors propagate directly into routing, and weakens deterministic
ontology and catalog validation.

### Maintain a separate IntentVocabularyBundle by hand

Rejected because product families, entity types, relations, metrics, aliases,
and applicability would drift from their existing authorities.

### Put Korean aliases and all query semantics into the TBox

Rejected because the minimal TBox is an execution-semantic and validation
boundary, not a language-specific prompt corpus. Korean NLU expressions change
more frequently and include discourse phenomena that are not domain ontology
facts.

### Use the 52 gold archetypes as the runtime intent catalog

Rejected because the catalog would overfit known wording, make novel valid
combinations look unsupported, and create a production dependency on
evaluation fixtures.

### Use three independent model calls for product family, action, and tags

Rejected as the default because independent calls can disagree on a shared
reference or frame, consume more recovery budget, and increase cost. It remains
eligible for offline comparison.

## Consequences

### Positive

- The model solves bounded semantic selection instead of executable planning.
- The ontology and runtime contracts become hard validators rather than prompt
  prose.
- Korean multi-intent and contextual questions retain typed dependencies.
- QueryPlan and all downstream consumers remain stable.
- Candidate generation, model inference, validation, and compilation can be
  evaluated independently.
- New valid axis combinations can reach Phase 2 composition without requiring
  a predeclared archetype.

### Costs and risks

- Stage 06 must implement two new internal strict contracts and one generated
  semantic catalog view.
- The request-artifact type and model-provenance constraint require a bounded
  PostgreSQL migration.
- A Korean NLU overlay needs measured maintenance and held-out tests.
- The QueryPlan compiler becomes an explicit Phase 2 deliverable.
- Phase 2 must include a lossless-lowering compatibility proof against the
  frozen QueryPlan contract.
- Catalog, ontology, prompt, model, and dataset versions must be pinned
  together for reproducibility.

## Preserved Decisions

- Normal execution still has at most one Intent Resolver LLM and one Answer
  Composer LLM.
- Only the deterministic Orchestrator schedules calls, retries, and deadlines.
- Filtering, sorting, ranking, aggregation, calculations, and verification
  remain deterministic.
- The request-wide LLM repair budget remains one.
- Semantic boundaries remain distinct from execution failures.
- No unsupported forecast, personalized suitability advice, order execution,
  or cross-request conversational memory is added.

## Non-Approval

This ADR approves the design direction only. It does not approve runtime code,
a PostgreSQL migration, QueryPlan compiler implementation, model promotion,
NCP changes, dataset activation, or changes to the official API.

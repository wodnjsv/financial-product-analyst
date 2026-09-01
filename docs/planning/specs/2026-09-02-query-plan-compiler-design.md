# QueryPlan Compiler and Four-Path Router Design

**Status:** Approved for implementation on 2026-09-02

## Goal

Convert a pinned Phase 1 resolution into the existing QueryPlan contract without
semantic loss, while classifying it as Fast, Compose, Explore, or Abstain.

## Inputs and outputs

`CompilerInput` contains a `ValidatedIntentResolutionV2` and the exact
`ResolverView` used to validate it. Manifest and active-dataset hashes must
match. The semantic catalog supplies applicability; a versioned planning
registry supplies archetypes, primitives, policies, defaults, required slots,
result shapes, and evidence requirements.

`QueryPlanCompilation` is an internal RuntimeArtifact. It records the route,
optional QueryPlan, selected archetype, primitive IDs, applied defaults, one
lowering record for every execution-relevant frame/link/mutation, blocking issue
codes, input hashes, and a compiler manifest. Fast and Compose require a valid
QueryPlan. Explore may produce a bounded catalog/document exploration plan.
Abstain must not produce a QueryPlan.

## Route rules

1. Validate pins, registry integrity, and input hashes.
2. Policy tags `PERSONALIZED_ADVICE`, `ORDER_EXECUTION`, `FUTURE_FORECAST`, or
   `REALTIME_REQUIRED` route to Abstain.
3. Ambiguous or context-unresolved resolutions route to Abstain.
4. Domain OOD and unsupported operations route to Abstain.
5. Partial lexical or missing-semantic coverage with a grounded family/action
   routes to Explore using only `explore_catalog` and `search_documents`.
6. Fully covered resolutions match an archetype by exact action, family count,
   context requirement, and semantic tags. All archetype preconditions must
   pass for Fast.
7. A fully covered non-Fast input composes registered primitives. A missing
   primitive, slot collision, unpaired filter, invalid applicability, or
   unrepresentable link routes to Abstain with a stable compiler issue.

No numeric confidence influences a route. Fast rate is not a target.

## Lowering

- Intent frame -> Subtask and OperationSpec.
- Product family choices -> QueryPlan product families.
- Concept slots -> MetricSpec or registered operation parameter.
- Filter concept/operator/literal assignments sharing an evidence group ->
  FilterSpec. Ambiguous grouping is rejected.
- Selected entity -> ResolvedReference; unresolved mention ->
  EntityResolutionRequest.
- Produced role -> BindingSpec.
- Context link -> ResolvedReference to a binding, BindingSpec, DependencyEdge,
  and selector/link parameter IDs.
- Slot mutations are applied in ordinal order. Delete and dontcare remove the
  slot; update replaces it; carryover requires an explicit source frame.
- Semantic flags -> ambiguity/policy decisions and route preconditions.

Literal values are decoded only from ResolverView candidates and encoded with
the frozen tagged ContractValue representation. The compiler cannot interpret
arbitrary text.

## Initial registry

Archetypes cover exact lookup, single-family screen/rank/aggregate, explicit
compare/calculate, anchored similarity, document explanation, cross-family
rank, and context re-rank. Registered primitives cover RDB lookup, Graph
traversal, document search, comparability, normalization, ranking, aggregation,
calculation, similarity, and bounded catalog exploration. Entity resolution
requests and selected entities are immutable operation inputs. Missingness and
coverage rules are versioned policy inputs on screen, rank, and similarity
operations rather than model-authored plan text.

## Errors and promotion

Configuration or pin corruption raises a compiler invariant error. User
semantics produce an Abstain compilation with stable issues. Phase 2 promotion
requires deterministic output 100%, invalid-plan acceptance 0, unknown registry
ID acceptance 0, lossless-lowering coverage 100% for supported cases, and OOD
false-fast at most 2%. Decoupled and full-pipeline metrics remain separate.

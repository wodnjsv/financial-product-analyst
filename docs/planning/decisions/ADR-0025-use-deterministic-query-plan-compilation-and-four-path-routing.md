# ADR-0025: Use Deterministic QueryPlan Compilation and Four-Path Routing

**Date:** 2026-09-02

**Status:** Accepted

**Approved:** 2026-09-02 — the user approved the Phase 2 design and authorized
implementation without another approval checkpoint.

**Related:** ADR-0005, ADR-0006, ADR-0022, ADR-0023, ADR-0024

## Context

Phase 1 produces a validated, ontology-grounded intent artifact rather than an
executable plan. The frozen QueryPlan contract must remain the Orchestrator
boundary, but a compiler must preserve frame dependencies, context links,
selectors, slot mutations, semantic coverage, and policy signals. Frequently
used combinations should be predictable without making the archetype catalog
the set of all supported questions.

Literal and selected-entity values are server-owned request candidates in the
ResolverView; the validated resolution intentionally retains their IDs. A
compiler therefore needs the pinned ResolverView together with the validated
resolution. Both must carry the same build and dataset pins.

## Decision

- Compile QueryPlan deterministically from `ValidatedIntentResolutionV2`, its
  exact `ResolverView`, the semantic catalog, and versioned compiler registries.
- Keep the public QueryPlan contract unchanged.
- Return an internal immutable `QueryPlanCompilation` containing the route,
  optional QueryPlan, lowering provenance, selected archetype and primitives,
  blocking issues, input hashes, and compiler manifest.
- Use four routes: `fast`, `compose`, `explore`, and `abstain`.
- Treat archetypes as exact, common-plan templates. A miss proceeds to registered
  primitive composition; it is not automatically unsupported.
- Allow only registered operations, parameters, capabilities, selectors,
  policies, and defaults. Never generate SQL, SPARQL, column names, or formulas.
- Apply slot precedence exactly as explicit value, typed context link, approved
  carryover, then approved default. Preserve every executable input in lowering
  records and fail closed if a construct cannot be represented.
- Route policy-prohibited, domain-OOD, unresolved-context, and lossful inputs to
  abstain. Route bounded lexical coverage gaps to explore. Fast requires exact
  archetype and complete preconditions; all other fully grounded combinations
  use compose.
- Keep Phase 1 promotion gates in force. Phase 2 may be evaluated with injected
  validated resolutions but may not activate the live default while Phase 1 is
  unpromoted.

## Consequences

The same input and registry versions produce byte-equivalent plans and route
decisions. Novel valid combinations remain executable through composition.
Compiler input now explicitly includes the pinned ResolverView; this amends the
Phase 2 input list in ADR-0022 without changing the model-facing or QueryPlan
contracts. Phase 3 consumes the compilation result and never repeats semantic
interpretation.

## Rejected Alternatives

- Direct conditional code per gold question: overfits evaluation fixtures.
- A second planning LLM: violates bounded model roles and makes execution IDs
  model-owned again.
- Permissive best-effort lowering: silently loses financial and context meaning.

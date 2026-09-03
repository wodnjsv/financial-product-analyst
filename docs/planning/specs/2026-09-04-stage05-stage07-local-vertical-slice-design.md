# Stage 05–07 Local Vertical Slice Design

**Date:** 2026-09-04

**Status:** Approved for local implementation
**Scope:** Missing Stage 05 executors and the deterministic Stage 07 release path

## 1. Assumptions and constraints

- The integrated `main` commit `fce4e31` is the implementation baseline.
- PostgreSQL remains the authority store. Graph and Vector results are candidates
  until they are joined to immutable Evidence.
- Stage 06 Intent Resolver, semantic plan compiler, SQL executor, and bounded
  Orchestrator remain unchanged except for registering the missing executors.
- The current local corpus may be used for conformance tests, but incomplete KRX,
  ECOS, SEC, or document coverage must not be presented as complete.
- NCP deployment, live HCX calls, public evaluation API, and final dataset
  activation remain Stage 08 work.
- Organizer source files, local databases, embeddings, credentials, and generated
  corpora remain untracked.

## 2. Intended outcome

Complete one deterministic local path:

```text
validated logical task
  -> SQL / Graph / Document executor
  -> approved, reproducible CalculationRecord when applicable
  -> evidence-bound ToolResult
  -> AtomicClaim + ClaimSupport + EvidenceBundle
  -> deterministic Verifier
  -> server-owned AnswerPlan validation (Claim Gate)
  -> deterministic Renderer
  -> ReleasedAnswer
```

Every released value, date, unit, relation, and source must be recoverable from
the ledger. An empty candidate result is not converted into a factual absence
unless closed-world scope evidence exists.

## 3. Minimal implementation choices

### 3.1 Graph executor

- Accept only `SemanticToolTaskExecutionInput` owned by the active planning
  registry.
- Derive the one approved predicate from the server-owned logical operation.
- Generate SPARQL only through `build_relation_query`.
- Filter returned bindings by the task's explicit entity scope or typed prior
  result binding.
- Reject dataset-version drift, malformed bindings, missing relation IDs, and
  missing Evidence IDs.
- Return deterministic rows and Evidence references. Zero rows remain `EMPTY`.

### 3.2 Document executor

- Map registered document topics to a fixed claim type, section set, and Korean
  query label.
- Search only the task's explicit product scope or prior-result scope.
- Run keyword search and, only when a query embedding provider is configured,
  vector search; combine them with deterministic reciprocal-rank fusion.
- Revalidate and promote selected chunks with `DocumentEvidencePromoter` before
  they may appear in a successful `ToolResult`.
- Preserve document, chunk, page/section locator, and Evidence IDs in the result.

### 3.3 Calculation boundary

- Verify and render only `CalculationRecord` values whose formula, version, input
  Evidence, units, and recomputed result satisfy a closed server-owned recipe.
- Keep the V2 `calculate` and `similar` production routes fail-closed in this
  slice. The current semantic contract preserves operand `value_ref` IDs but
  does not carry their typed values into `SemanticToolTaskExecutionInput`, and
  the active policy registry intentionally marks similarity unverified.
- Do not invent a generic evaluator or infer formula semantics from the model.
  The later calculation implementation must first add approved recipes and an
  authoritative typed-value handoff, then record exact Evidence inputs,
  parameters, population, rounding, and tie-breaking metadata.
- The initial registry contains only a one-input identity/unit-preserving recipe;
  it recomputes exact value, unit, and currency equality. Reject every unregistered
  formula and all similarity results until typed calculation inputs and the
  similarity policy are activated. The eventual similarity policy must require at
  least 60% evidence coverage.

### 3.4 Evidence, verification, and release

- Claim generation is registry-based and deterministic. A claim is created only
  when its exact Evidence or Calculation support is known.
- Verification order is fixed: contract/version, source/authority, cutoff,
  ontology, calculation/comparability, coverage/policy.
- Passing verification lists the only releaseable claim IDs.
- Claim Gate accepts only registered renderer profiles, templates, columns,
  blocks, and slots; every referenced claim must be releaseable.
- Renderer reads claim values and provenance from the ledger. `AnswerPlan` may
  select and arrange IDs but cannot introduce factual text.
- A release cache may store only a Claim-Gate-authorized `ReleasedAnswer`, keyed
  by request identity and dataset version.

## 4. Non-goals

- No free-form SPARQL, SQL, formulas, or renderer templates.
- No text-derived `hasRiskFactor` Graph assertion.
- No speculative source collection or new Vector corpus expansion.
- No LLM verifier, free-form answer writer, web service, deployment, or cloud
  infrastructure.
- No claim that Stages 03–05 are complete while their final data activation and
  coverage gates remain open.

## 5. Verifiable success criteria

1. Graph and Document executors reject foreign plans, unapproved predicates or
   topics, version drift, and unbound evidence.
2. Repeated execution over the same pinned inputs produces byte-identical rows,
   ordering, Evidence references, claims, reports, plans, and released answers.
3. Candidate-only Graph/Vector results cannot become claims.
4. Direct, relation, approved recomputable calculation, and limitation cases have
   explicit positive and negative tests. Closed-world/no-match release remains
   fail-closed until a query-scope executor produces exact scope Evidence.
5. Claim Gate rejects unknown layout IDs, non-releaseable claims, duplicate or
   incompatible slots, and factual literals supplied by the plan.
6. Renderer output is derived entirely from verified ledger records and maps
   losslessly to the five evaluation API strings.
7. Narrow tests pass first; the broad non-live suite and PostgreSQL 15 migration
   cycle pass before completion is reported.

## 6. Known deferred gates

- Final official structured-source integration and Stage 04 atomic activation.
- Live Fuseki/pgvector latency against the final NCP dataset.
- Complete 52-question numeric and coverage acceptance.
- Approved calculation recipes, typed literal-value handoff, calculation and
  similarity production executors, and closed-world scope Evidence production.
- HCX intent promotion and Answer Composer live quality.
- Stage 08 API, container, NCP permissions, observability, and recovery.

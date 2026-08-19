# ADR-0012: Use a Nine-Stage Competition Delivery Roadmap

**Date:** 2026-08-20

**Status:** Accepted

**Related:** [Competition Stage Roadmap](../ROADMAP.md), [Planning and Implementation Status](../STATUS.md), [Planning Harness](../HARNESS.md)

## Context

Stage 01 runtime contracts and Stage 02 PostgreSQL storage have been implemented and verified, but the current architecture did not yet have one accepted Stage roadmap from data ingestion through the end of the competition evaluation period. The superseded 2026-08-10 plan contains useful historical requirements, but its DuckDB, local-index, and earlier Agent assumptions conflict with the accepted PostgreSQL, Fuseki, pgvector, bounded-LLM, normalized-Evidence, and NCP decisions.

The remaining work has seven distinct responsibility boundaries: data, ontology and projections, deterministic retrieval and finance, question orchestration, verified answer release, public deployment, and submission operations. These boundaries need explicit completion gates so that a partially loaded or unverified system cannot be treated as ready for evaluation.

## Decision

- Use nine total implementation Stages, including completed Stage 01 and Stage 02.
- Define the remaining sequence as:
  1. Stage 03 — data collection and normalization;
  2. Stage 04 — ontology, Graph, Keyword, and Vector projections;
  3. Stage 05 — federated retrieval and deterministic financial computation;
  4. Stage 06 — intent resolution and typed orchestration;
  5. Stage 07 — verification, Claim Gate, rendering, and verified answer release;
  6. Stage 08 — official evaluation API and NCP operational deployment;
  7. Stage 09 — end-to-end evaluation, submission freeze, and evaluation-period operations.
- Keep Stage 05 separate from Stage 06. Search, ranking, comparison, and calculation must be testable without an LLM before natural-language planning and orchestration are connected.
- Keep organizer masters and approved external sources in one Stage 03 data lifecycle, but require a separate approval gate for each external source.
- Permit preparatory work to overlap only where the roadmap documents it. A later Stage cannot be marked complete before its predecessor's completion gate passes.
- Treat the official evaluation-period end, not code completion or submission day, as the roadmap terminal condition.
- Require a separately approved, dated implementation plan before each incomplete Stage begins.

## Rejected Alternatives

### Eight Stages by combining retrieval and orchestration

Rejected because it would combine deterministic finance, four retrieval modes, entity resolution, LLM intent resolution, dependency bindings, concurrency, and deadline policy in one Stage. That boundary would make failures harder to isolate and would allow an apparently successful LLM path to hide defects in deterministic retrieval or calculation.

### Ten Stages by separating organizer and external data

Rejected because both source categories must obey the same cutoff, lineage, identifier, missingness, and dataset-activation rules. Separate Stages would delay the first complete data snapshot and duplicate lifecycle gates. External sources remain individually approved within Stage 03 instead.

### Retain only an unordered backlog after Stage 02

Rejected because Graph and Vector projections depend on normalized identifiers, orchestration depends on deterministic capabilities, Claim release depends on verified Evidence, and deployment depends on the release path. An unordered list does not protect these dependencies.

## Consequences

### Positive

- Every remaining responsibility has a bounded scope and measurable completion gate.
- Deterministic financial correctness is verified before LLM integration.
- The mandatory ontology and Evidence requirements are on the critical path rather than deferred to submission cleanup.
- Public deployment and competition operations remain explicit deliverables.

### Costs and risks

- Every Stage requires its own planning and approval checkpoint.
- Some implementation work may be prepared in parallel but cannot receive final completion credit early.
- Missing P0 official sources discovered in Stage 03 can block later supported-question coverage instead of being hidden by orchestration or answer generation.

## Preserved Decisions

- The organizer snapshot remains authoritative and the financial cutoff remains `2026-07-11`.
- Stage 01 contracts and Stage 02 storage boundaries remain frozen inputs.
- Normal execution continues to use only one Intent Resolver and one Answer Composer.
- PostgreSQL remains the authoritative structured and Evidence ledger, with Fuseki and pgvector as bounded projections or retrieval candidates.
- Deterministic code retains ownership of filtering, ranking, aggregation, financial calculations, comparability, and similarity.
- Claim Gate Registry validation remains mandatory before a stored or composed answer can be released.

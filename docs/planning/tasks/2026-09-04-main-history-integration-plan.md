# Main History Integration Plan

**Date:** 2026-09-04

**Status:** Completed

## Outcome

Combine the approved document, Graph, Vector, and intent-planning histories into
one verified `main` baseline before Stage 05 and Stage 07 implementation begins.

## Constraints and Non-goals

- Preserve organizer-provided raw data and local databases unchanged.
- Do not call DART, NCP embedding, or HyperCLOVA services.
- Do not promote hybrid V3 or mark Stage 04–07 complete.
- Preserve PostgreSQL as authority and Graph/Vector as evidence-bound
  projections.

## Steps and Success Criteria

1. Resolve migration, ADR-number, ontology, and shared-fixture conflicts.
   Verify one Alembic head and no conflict markers.
2. Reconcile ETF/ETN `tracksIndex` semantics across ontology, Graph projection,
   and the intent catalog. Verify focused contract tests.
3. Run the broad non-live test suite.
4. Run migration-cycle and core repository tests against isolated PostgreSQL
   15 and regenerate the reviewed object manifest from the migrated database.
5. Inspect staged paths for raw data, secrets, conflict markers, and unrelated
   files before committing and pushing `main`.

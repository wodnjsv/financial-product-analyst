# Main History Integration Verification

**Date:** 2026-09-04

## Verified Baseline

- Alembic has one linear head: `0011`.
- The document source/building-dataset migrations remain `0008` and `0009`;
  intent artifacts follow as `0010` and `0011`.
- The reviewed database-object manifest matches a clean PostgreSQL 15 database
  migrated through `0011`.
- `tracksIndex` consistently accepts `ExchangeTradedProduct | PublicFund` in
  TBox, SHACL, Graph projection, and the intent semantic catalog.

## Results

- Focused catalog, type-projection, and migration checks: passed.
- Broad local non-live suite: `2984 passed, 1 skipped, 502 deselected`.
- Isolated PostgreSQL 15 migration-cycle and core repository suite:
  `155 passed`.
- The skipped broad-suite test requires an explicitly configured PostgreSQL;
  its PostgreSQL path is covered by the isolated suite above.

## Exclusions

- No organizer raw data, retained corpus database, DART API, NCP service,
  HyperCLOVA service, or production Fuseki endpoint was used.
- This verifies the merged local baseline; it does not complete the remaining
  Stage 04 activation, Stage 05 executors, Stage 07 answer pipeline, or Stage 08
  NCP acceptance.

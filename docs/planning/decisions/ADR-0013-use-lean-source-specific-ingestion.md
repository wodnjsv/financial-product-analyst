# ADR-0013: Use a Lean Source-Specific Ingestion Pipeline

**Date:** 2026-08-20

**Status:** Accepted

**Related:** [Stage 03 Lean Data Ingestion Design](../specs/2026-08-20-stage-03-lean-data-ingestion-design.md), [ADR-0002](ADR-0002-repository-data-policy.md), [ADR-0007](ADR-0007-normalized-evidence-ledger-structured-answer-plan.md), [ADR-0012](ADR-0012-use-nine-stage-competition-delivery-roadmap.md)

## Context

Stage 03 must normalize four organizer workbooks with 145,393 raw rows and 207 source fields, preserve official lineage, enforce a fixed cutoff, and later incorporate approved external structured data and documents. The first design introduced several generic contracts, repository methods, manifests, and test layers before one real source had been loaded.

The correctness requirements are justified, but a generic ingestion framework would make the competition project slower to implement and harder to debug. Stage 02 already supplies the authoritative PostgreSQL schemas, dataset lifecycle, Evidence ledger, permissions, exact retry semantics, and NCP verification boundary.

## Decision

- Keep the strict data requirements: immutable raw sources, SHA-256 verification, `2026-07-11` cutoff, complete row accounting, deterministic IDs, missingness and sentinel handling, Source/Evidence lineage, `building` lifecycle, and exact retry conflicts.
- Implement Stage 03A as one typed flow with:
  - one small `SourceSpec`;
  - read-only local/Object Storage source access;
  - one XLSX streaming reader;
  - four explicit source-specific pure mapping modules;
  - one `DatasetBuildWriter` over the Stage 02 schema; and
  - one canonical `BuildReport`.
- Do not implement a YAML mapping DSL, generic field-rule engine, plugin framework, class hierarchy for row decisions, multiple overlapping manifests, or four independent ingestion applications.
- Create Evidence only for normalized facts that can support answers or deterministic verification, not for every raw cell.
- Use four test boundaries: mapping, synthetic workbook, PostgreSQL, and gated real-data/NCP acceptance.
- Split Stage 03 into 03A organizer masters, 03B approved external structured data, and 03C official documents plus the final data-quality gate.
- Because `dataset_version.manifest_hash` is immutable, use disposable non-production `building` versions in 03A and 03B. Reproduce one final NCP `building` version in 03C after all approved source manifests are frozen.
- Require a field-level mapping matrix and explicit approval before mapper implementation. Do not add Alembic `0006` unless tests prove a mandatory fact cannot be represented by Stage 02 and the user separately approves the DDL change.

## Rejected Alternatives

### Generic field-rule or YAML DSL

Rejected because there are only four known organizer schemas, financial interpretation still requires source-specific code review, and a DSL would add a second validation and debugging system.

### One bespoke script per workbook

Rejected because source verification, hashing, row accounting, transaction handling, Evidence construction, and reporting would be duplicated and drift between product families.

### One large universal mapper

Rejected because bond, ETF·ETN, and public-fund row grains and missingness rules differ materially. Explicit source modules keep those differences visible without introducing runtime plugins.

### Incrementally mutate the final NCP dataset during 03A·03B·03C

Rejected because the Stage 02 dataset manifest is immutable and external sources are approved later. A partial manifest cannot honestly identify the final dataset.

### Create Evidence for every workbook cell

Rejected because it would multiply storage and processing without improving answer support. The immutable raw workbook remains the full source; Evidence covers normalized answerable facts and their exact locators.

## Consequences

### Positive

- Stage 03 code stays close to the four real source schemas.
- Stage 02 storage, permissions, lineage, and idempotency work is reused instead of reimplemented.
- Source-specific financial edge cases remain reviewable in ordinary Python.
- The first production path can be completed before investing in abstractions whose reuse has not been demonstrated.

### Costs and risks

- Shared behavior must remain in small helper functions rather than drifting across four mapper modules.
- A fifth materially different source may require a new explicit mapper before a common pattern is promoted.
- 03C must rerun the deterministic organizer and external mappings to create the final NCP dataset.
- The field-level mapping matrix is a real approval gate and can expose unresolved source semantics before coding proceeds.

## Preserved Decisions

- Organizer data remains outside Git and wins when the same evaluation field conflicts with an external source.
- PostgreSQL remains the structured and Evidence authority.
- Graph and Vector remain projections that must bind back to the PostgreSQL ledger.
- Deterministic code owns normalization, filtering, ranking, aggregation, comparison, and financial calculation.
- No data version is activated before PostgreSQL, Graph, Vector, and Evidence readiness all pass.

# ADR-0056: Add two local indexes for exact condition counts

- Date: 2026-10-11
- Status: Accepted
- Approval: The user explicitly approved two local PostgreSQL indexes and retesting.
- Related: ADR-0050, ADR-0054, ADR-0055.

## Decision

Add only the two reviewed nonunique B-tree indexes to `financial_agent_local`:

1. A partial observation index on dataset, metric, definition version and entity,
   covering the nine definition-version-2 source metrics used by the Japanese
   equity ETF and domestic-bond condition questions.
2. A reverse observation-origin index on dataset, observation ID and evidence ID.

This approval narrowly supersedes the condition task's prohibition on database
writes for these two indexes. It does not authorize changes to source rows,
constraints, application privileges, ingestion or other indexes. The application
remains read-only, with its existing SQL 5-second/service 55-second budgets.
Run each concurrent index build outside a transaction using a maintenance
connection; preserve the existing indexes. Rollback drops only the two new names.

## Alternatives and reasons

- Increase the SQL timeout: rejected because it conceals the population-count
  bottleneck and changes the approved runtime budget.
- Return a sampled count: rejected because it misrepresents the complete matching
  population. Hydration of five products already succeeds in about 0.04 seconds.
- Rewrite evidence predicates as scalar lookups: diagnostic variants still
  exceeded five seconds. Keep source eligibility and exact counts intact.
- Index all metrics: unnecessary for these questions. Restrict the observation
  index to the nine verified metrics; the origin index supports their proof joins.

The pre-build database is 6.715 decimal GB. Estimated permanent additions are
0.5–0.8 GB; build temporary space and WAL are additional. Check the approved
capacity limits and at least 10 GiB free between builds. Estimates are not an
assertion of measured size or performance.

## Verification

Check exact index definitions and validity, measured sizes, unchanged runtime
permissions and dataset pin. Replay all four condition questions using the
actual parameterized compiler/runner, including repeated execution on reused
connections. Compare complete counts and displayed product/evidence IDs with
independent source expectations. Inspect actual query plans for index use and
generic prepared-plan behavior. Keep provider failures separate from local DB
verification; index creation alone is not successful query acceptance.

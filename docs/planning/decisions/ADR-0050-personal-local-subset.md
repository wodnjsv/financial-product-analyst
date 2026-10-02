# ADR-0050: Personal local subset after the competition

- Date: 2026-09-18
- Status: Accepted
- Approval: User approved the proposed local database, size budget, and subset.

## Decision

Use a separate `financial_agent_local` database on the user's existing local
PostgreSQL 17. Keep the original four workbook masters where measured size
permits. Bound additional holdings to 50 domestic and 50 overseas ETFs and
official documents to 100. Select whole products and preserve all holdings
within each selected source snapshot; outside-sample coverage is unknown.

Target database plus indexes below 18 decimal GB initially. Total additional
disk consumption must remain below 30 decimal GB, with at least 10 GiB free.
Check capacity between small committed batches with headroom for the next
batch; never fill the budget merely to reach a size target.

Use PostgreSQL relations for local exploration. Do not require a duplicate
RDF/Fuseki build, NCP acceptance, public evaluation API, or competition release
activation for direct local SQL tests. The dataset remains explicitly pinned
and `building`; do not fabricate Graph/Vector readiness. This supersedes the
competition-only completion sequencing in HARNESS and ADR-0047 through 0049
for this personal profile only. Historical snapshots retain their real dates,
source lineage, missingness rules, and repository exclusion policy.

An explicit local-development profile may accept PostgreSQL 17 and omit usable
pg_stat_statements as a migration prerequisite, since enabling shared preload
would restart the user's shared server. It must still require pgvector,
permissions, source checks, and schema validation. The competition profile
retains its existing PostgreSQL 15 and extension requirements.

No existing database is deleted or modified. Missing external sources are
reported instead of synthesized. Paid document embeddings require a concrete
cost confirmation before execution. No remote push or deployment is included.

## Alternatives

- Full rebuild: rejected because prior Graph and holdings growth exceeded this
  local use case and requires extra temporary working storage.
- Arbitrary row truncation: rejected because it misrepresents holdings coverage.
- New server cluster: rejected because the existing local server is available.

## Verification

Validate schema on PostgreSQL 17; test capacity-stop behavior and local target
restriction; reconcile all four master counts and FK/evidence origins; run
read-only lookup/filter/relation queries and preserve measured capacity and
source coverage in a local report. Missing external data is not completion.

# Personal local dataset

Date: 2026-09-18. Direction approved by user; see ADR-0050.

Assumptions: the retained August 24 workbooks are the initial facts; the user's
localhost:5432 PostgreSQL 17 is the target. Initial inspection missed ignored
`data/`: subsequent full inspection found 761 MB of official captures and a
DART binary export, including embeddings. Reuse these with checksum and
repository validation. A 30 GB budget is an upper bound, not a target to fill.

Outcome: a reproducible, separately named local SQL dataset for individual
testing, with sources and measured storage. No cloud deployment, full Graph
projection, paid embeddings, unrelated DB changes, or remote publication.

1. [x] Recover latest code from origin/main plus existing finalization history.
2. [x] Implement and test explicit local PostgreSQL preflight and disk guards.
3. [x] Create isolated DB, migrate, verify PostgreSQL 17 and role boundaries.
4. [x] Validate source files; load masters in measured bounded batches.
5. [x] Reuse retained official sources; select <=50 ETFs per region and
   <=100 documents; preserve provenance and complete per-product scope.
6. [x] Verify counts, evidence linkage, SQL queries, and disk limits; document
   source limitations and provide local connection/query instructions.

Checks: database plus indexes <18 GB target, total disk growth <30 GB,
remaining space >=10 GiB, all four workbook source counts reconcile, no orphan
evidence, repeatable selection and truthful subset coverage. Keep untracked
reports/raw data under `data/`. Do not mark omitted dependencies complete.

## Verified result

- All 53,375 organizer rows reconciled: bonds 21,882, domestic ETPs 1,780,
  overseas ETPs 6,037, public funds 23,676. No fatal or quarantined rows.
- Holdings: 50 domestic ETFs / 2,925 relations; 50 overseas ETFs / 11,424
  relations. Existing partial-coverage and missing-value flags were preserved.
- Reused 100 DART documents, 1,552 chunks and 1,552 existing 1,024-dimensional
  embeddings. Compared restored vector values with the binary backup exactly;
  no embedding API calls. The temporary restore schema was removed.
- Final acceptance: 3,649,906 observations, 3,782,563 evidence records and
  92,881 relations; no observations or holdings without evidence origins,
  and no vector dimension/hash/coverage anomalies.
- DB including indexes: 6,715,264,147 bytes (6.72 GB); free disk:
  36,456,382,464 bytes (33.95 GiB). Observed disk growth from the saved baseline:
  9,786,535,936 bytes. Free-space changes also include other system activity.
- PostgreSQL 17 postflight passed with group roles. All six read-only example
  queries passed, including document keywords and stored-vector similarity.
- Offline ingestion/document/embedding checks: 991 passed, 38 deselected.
  PostgreSQL ingestion/carry-forward checks: 10 passed. PostgreSQL document/
  embedding checks: 34 passed, 42 deselected. Focused preflight/budget/selection
  checks: 60 passed, 23 deselected. Compilation and diff whitespace checks passed.
- The acceptance script initially counted the migration's empty singleton
  pointer as active. Corrected it to check non-NULL activation fields; the
  actual dataset remains `building` with no active pointer.

Untracked reports are in the original workspace's `data/personal-local/`:
`manifest.json`, `structured-report.json` (before document restoration),
`document-report.json`, and `acceptance.json`. SQL output is in
`data/personal-query-results.log`. No remote publication was performed.

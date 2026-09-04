# Stage 03/04 Final Assembly Design

## Outcome

Produce and activate `competition-2026-08-24-final-v1`, containing the
2026-08-24 organizer baseline, approved KRX/ECOS/SEC snapshots, the existing
DART document corpus and embeddings, and a deterministic Graph projection.

## Inputs

- Organizer workbooks and schemas for all eight approved tables.
- 1,166 official snapshot manifests: 1,161 KRX ETF holdings plus one each for
  KRX KOSPI, KRX KOSDAQ, ECOS 731Y001, SEC series/class, and SEC N-PORT.
- DART source dataset `organizer-dart-2026-08-24-v2`:
  - 2,214 documents and source artifacts
  - 7,267 document coverage rows
  - 40,149 chunks
  - 40,149 `ncp-clova-bge-m3` vectors of dimension 1,024

## Assembly Boundary

PostgreSQL remains authoritative. The Graph store is rebuilt from approved
PostgreSQL relations. Vector rows remain PostgreSQL `pgvector` rows and are
carried forward without recomputing vector values. Document candidates become
Evidence only when the existing deterministic promotion path revalidates the
selected span.

No DART PDF download, PDF extraction, chunk selection, embedding API call,
organizer-file modification, or NCP database write is part of this run.

## Execution Sequence

1. Record disk, database, migration, source-manifest, and source-dataset
   baselines.
2. Verify migration `0009 -> 0012` on a disposable PostgreSQL 15 database, then
   migrate the local integration database.
3. Apply the previously discovered SEC N-PORT product-scoped identity fix and
   accept multiple verified official capture roots.
4. Build organizer plus official structured rows under the final version.
5. Check that every DART-bound entity and publisher exists in the target.
6. Carry forward document metadata, coverage, chunks, source artifacts, and
   embeddings. Regenerate every hash or ID whose contract contains
   `dataset_version`.
7. Reconcile vector coverage and verify zero missing, duplicate, stale, orphan,
   and wrong-dimension rows.
8. Build Graph artifacts twice and require byte-identical data, evidence, and
   manifest hashes. Run SHACL and the configured Jena/Fuseki gate.
9. Create one validation run, write the four component readiness records,
   finish validation, and atomically activate the final version.
10. Run read-only post-activation smoke checks. Keep the source dataset.

## Failure and Recovery

- Every mutating phase targets only a `building` dataset.
- A failed build is never activated.
- An interrupted carry-forward is idempotent: identical rows converge and a
  payload conflict fails closed.
- If disk falls below the phase-specific reserve, stop before the next phase.
- The old dataset and captured source files are not deleted by this task.

## Acceptance Criteria

- Cutoff date is exactly `2026-08-24` and no eligible source is after cutoff.
- All 1,166 official manifests and objects pass size and SHA-256 validation.
- DART target counts are exactly 2,214 documents, 7,267 coverages, 40,149
  chunks, and 40,149 embeddings after carry-forward.
- Vector reconciliation reports zero anomalies and dimension 1,024.
- All deferred foreign keys validate and no bound entity is missing.
- Two Graph builds are byte-identical and all Graph validation gates pass.
- Readiness has exactly one passing row for each of `postgres`, `graph`,
  `vector`, and `evidence`, all bound to the final dataset manifest.
- `operations.active_dataset` points to
  `competition-2026-08-24-final-v1` only after all prior checks pass.

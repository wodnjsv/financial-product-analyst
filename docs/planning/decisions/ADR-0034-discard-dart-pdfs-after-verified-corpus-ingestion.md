# ADR-0034: Discard DART PDFs After Verified Corpus Ingestion

**Date:** 2026-08-31

**Status:** Accepted

**Approved:** 2026-08-31 — the user approved retaining DART source-file
identity, locators, checksums, and extracted Claims in PostgreSQL while deleting
each local PDF after the committed corpus is read back and verified.

**Supersedes:** Only the DART prospectus clauses in
[ADR-0009](ADR-0009-ncp-postgresql-storage-encryption-boundary.md),
[ADR-0014](ADR-0014-use-bounded-official-source-snapshots.md), and
[ADR-0033](ADR-0033-use-claim-based-vector-corpus-budgets.md) that require an
immutable PDF copy in Object Storage before local cleanup. Organizer workbooks
and other approved structured sources retain their existing preservation rules.

**Related:** [ADR-0007](ADR-0007-normalized-evidence-ledger-structured-answer-plan.md),
[ADR-0032](ADR-0032-use-three-tier-official-document-sources.md),
[DART Streaming Corpus Ingestion Design](../specs/2026-08-31-dart-streaming-corpus-ingestion-design.md)

## Context

The document corpus may include approximately 1,780 domestic ETF products and
6,885 representative public-fund identifiers before exact document
deduplication. Accumulating every prospectus locally would consume several
gigabytes and is unnecessary for normal retrieval after exact Claim spans and
their provenance are stored in PostgreSQL.

The approved trade-off is deliberate: a checksum proves the bytes processed,
but it cannot reconstruct those bytes if DART later removes or changes the
download. The system must therefore describe retained DART sources as
`metadata_only_deleted`, never as an available immutable object.

## Decision

- Derive the only permitted target universe from the organizer's authoritative
  `2026-08-24` domestic ETF and public-fund data. A DART filing cannot create a
  new product Entity, expand the target population, or replace an organizer
  identifier.
- Require an exact organizer Entity and identifier binding before download.
  Product-name normalization is a secondary equality check within the already
  verified publisher context; substring, fuzzy, or Vector similarity cannot
  establish eligibility.
- Download at most one bounded DART prospectus at a time to an ignored local
  temporary path.
- Verify the official DART binding, cutoff, media type, byte count, PDF SHA-256,
  page count, and extracted-text SHA-256 before corpus construction.
- Persist the document, all entity bindings, selected chunks, coverage, and
  source-file provenance in one PostgreSQL transaction.
- Store at least the DART receipt number, original attachment name, official
  filing locator, exact attachment locator, publisher, document type and
  version, publication/availability/effective dates, media type, byte count,
  source checksum, text checksum, page count, extraction version, retention
  disposition, and processing timestamps.
- Read the committed record back and verify document identity, entity bindings,
  chunk identities, content hashes, counts, and source-file provenance before
  deleting the local PDF.
- Delete only the verified local PDF. Never use a broad directory, unresolved
  path, glob, or unverified manifest field as a deletion target.
- On download, extraction, selection, budget, database, or read-back failure,
  do not mark the item indexed and do not execute the success cleanup path.
  Move or retain only the exact bounded temporary file for controlled retry,
  subject to a configured quarantine limit.
- Deduplicate by verified document identity and PDF SHA-256. Multiple product or
  share-class bindings reuse one document and one chunk set.
- A later rerun may re-download the same official attachment and must require
  checksum equality before treating it as the same source. A mismatch creates a
  new review disposition; it never overwrites the recorded source identity.

## Rejected Alternatives

### Retain every PDF locally

Rejected by the user because the complete source corpus would consume limited
local storage after the searchable Claims are already committed.

### Upload every PDF to Object Storage before cleanup

Rejected for this DART corpus run by the user's explicit metadata-only
retention decision. This remains the safer reconstruction option and may be
restored by a later ADR.

### Delete immediately after chunk construction

Rejected because an in-memory result is not durable. Cleanup is allowed only
after the PostgreSQL transaction commits and an independent read-back validates
the stored corpus and provenance.

## Consequences

- Persistent PDF storage remains bounded near zero during the run.
- PostgreSQL can identify exactly which official file supported each chunk.
- The corpus cannot reproduce the original PDF bytes from PostgreSQL alone.
  If the official attachment later disappears or changes, the stored checksum
  can detect the loss or mismatch but cannot recover the file.
- Operations and user-facing evidence must not claim that the deleted PDF is
  retained in Object Storage or locally available.
- The final dataset remains inactive until the existing PostgreSQL, Evidence,
  retrieval, Graph, and Vector readiness gates pass.
- DART-only products and unmatched filings remain outside the competition
  corpus even when their documents are otherwise official and readable.

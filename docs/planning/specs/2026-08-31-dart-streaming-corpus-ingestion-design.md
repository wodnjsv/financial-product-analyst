# DART Streaming Corpus Ingestion Design

**Date:** 2026-08-31

**Status:** Approved direction; implementation plan pending review

**Decisions:** [ADR-0034](../decisions/ADR-0034-discard-dart-pdfs-after-verified-corpus-ingestion.md),
[ADR-0035](../decisions/ADR-0035-correct-organizer-dart-target-inventory.md)

## 1. Outcome

Process every DART-eligible domestic ETF and public-fund target against the
`2026-08-24` cutoff, store Claim-selected chunks and exact source-file
provenance in PostgreSQL, and delete each local PDF only after committed data is
read back and verified. The run is resumable, document-deduplicated, bounded in
temporary storage, and produces complete coverage and failure accounting.

## 2. Scope

### Organizer-authoritative target gate

The organizer's `2026-08-24` product data is the sole source of the target
population. Build and freeze an input inventory from its domestic ETF and
public-fund rows before any DART request. Every download request must carry an
existing organizer `entity_id`, the relevant organizer product identifier, the
canonical organizer name, and an exact verified publisher binding.

DART is a document source for those products, not a product-discovery source.
A filing found only in DART cannot add a product, create an Entity, or enter the
competition corpus. A name-only, substring, fuzzy, or Vector match cannot make
a filing eligible. The batch report must reconcile its indexed, failed, and
not-applicable counts back to the frozen organizer target inventory with no
unaccounted target and no extra DART product.

### Included

- All 1,780 domestic ETP rows in the current organizer workbook: 1,235 ETF and
  545 ETN. DART applicability is resolved later without removing them from the
  organizer inventory.
- Public funds grouped only by the 6,878 valid representative KSD identifiers.
  The 120 blank rows and 6,962 sentinel rows remain explicit targets requiring
  exact alternate binding or a bounded failure disposition.
- The 217 exact domestic-ETP/public-fund overlaps follow canonical ETP
  ownership and cannot create duplicate downloads. The reconciled inventory is
  25,239 canonical products and 15,569 targets: 1,780 domestic ETP and 13,789
  public fund.
- DART tier-1 full prospectuses effective and available no later than
  `2026-08-24`.
- The approved Claim selection and KODEX 200 PDF extraction behavior.
- PostgreSQL document, binding, chunk, coverage, source, Evidence-readiness, and
  source-file provenance records.

### Excluded

- Overseas ETFs, which require their jurisdictional regulator rather than DART.
- Domestic bonds, which remain `not_applicable_current_scope` for Vector
  documents.
- Index-provider methodologies, policy documents, and tier-3 change notices.
- Embedding generation, pgvector population, Graph projection, dataset
  activation, and NCP deployment.
- PDF, extracted full text, real-data reports, credentials, or database dumps in
  Git.

## 3. Key Design Choices

### 3.1 Discover by publisher, bind by exact product identity

Download the OpenDART corporation-code file once, normalize reviewed publisher
names, and resolve each manager to one DART publisher code. Group product
targets by that verified publisher and retrieve eligible filing windows once
per publisher instead of once per product. Match filings to products only with
the frozen organizer target key, stable organizer identifiers, and the existing
exact normalized identity rules. Ambiguous or missing bindings fail closed.
Unmatched filings are counted only as rejected discovery results and are never
downloaded.

This avoids thousands of duplicate API requests while preserving the source
authority and product-binding rules in ADR-0021.

### 3.2 Select one canonical effective filing

For each exact product identity, choose the latest effective full prospectus
whose publication and availability do not exceed `2026-08-24`. Resolve DART
correction state before selection. Share classes or products bound to the same
receipt and verified PDF share one document record and one chunk set.

### 3.3 Stream one document through a transactional gate

For each unique selected receipt:

1. create a uniquely named temporary directory;
2. capture the exact official attachment atomically with a byte limit;
3. validate PDF magic, checksum, file size, page count, target identity, and
   cutoff metadata;
4. extract sections, select approved Claims, and chunk them;
5. enforce the 20-chunk and 8,000-selected-token review gates without
   truncation;
6. append source, document, bindings, chunks, coverage, and provenance in one
   PostgreSQL transaction;
7. read the complete persisted corpus and provenance back through the
   repository;
8. compare the expected and persisted canonical hashes; and
9. delete only the exact verified temporary PDF and directory.

An indexed status is impossible until step 6 commits. Success cleanup is
impossible until step 8 passes.

### 3.4 Persist physical-file provenance explicitly

Add a one-to-one `document.source_artifact` record keyed by
`(dataset_version, document_id)`. It records:

| Field | Meaning |
| --- | --- |
| `source_artifact_id` | deterministic retained provenance identity |
| `source_id`, `document_id` | source and logical document linkage |
| `receipt_id` | DART receipt number |
| `original_filename` | attachment name returned by DART |
| `filing_locator` | public DART filing page |
| `attachment_locator` | exact official PDF download locator |
| `media_type`, `byte_count` | captured file format and size |
| `source_checksum` | SHA-256 of the deleted PDF bytes |
| `text_checksum`, `page_count` | extracted canonical text identity |
| `extraction_version` | parser behavior identity |
| `downloaded_at`, `persisted_at`, `verified_at`, `discarded_at` | processing chronology |
| `retention_disposition` | always `metadata_only_deleted` after success |
| `record_hash` | canonical hash of the provenance row |

The existing `document_record.object_key` remains a stable logical source-file
key for compatibility, such as
`documents/dart/<receipt_id>/full-prospectus.pdf`. It does not assert that an
object currently exists. Retrieval and operations must consult
`retention_disposition` before describing source availability.

Each chunk continues to store document, section, page, character range,
`content_hash`, and `dataset_version`. Evidence promotion later joins the chunk
to the `source_id` and source artifact; it does not recreate the discarded PDF.

## 4. Failure and Resume Semantics

- Discovery failures create deterministic coverage rows and never download a
  lower-authority fallback.
- Temporary network failures retry with bounded backoff. DART rate limiting
  stops the run cleanly and preserves the last committed cursor.
- A corrupt, ambiguous, unreadable, or over-budget PDF is not persisted as an
  indexed corpus.
- A database retry is idempotent only when canonical corpus and provenance bytes
  are identical. Different bytes for the same identity produce a conflict.
- The durable run ledger records target status, selected receipt, attempt count,
  stable reason code, and last successful stage without storing credentials or
  source prose.
- Resume skips a document only after repository read-back proves that its
  complete expected corpus and provenance are already committed.
- Quarantine is bounded by file count and bytes. Exceeding either limit stops
  the run for review rather than consuming the remaining disk.

## 5. Data Safety

- Read `api.txt` without logging its value and expose the key only to the DART
  request context.
- Never include the key in URLs written to PostgreSQL, reports, exceptions, or
  logs.
- Temporary paths are generated locally and are never derived directly from an
  attachment filename.
- Cleanup receives a validated absolute file path under the configured run
  directory and refuses symlinks, directories, parents, globs, or paths outside
  that boundary.
- PostgreSQL 15 remains authoritative. Real data is loaded only into an approved
  inactive `building` dataset.

## 6. Verification

### Synthetic and repository tests

- a DART filing absent from the organizer target inventory is rejected before
  attachment download and cannot create a product Entity;
- every frozen organizer target receives exactly one final disposition and the
  report rejects any extra target or missing target;
- publisher-batched discovery returns the same exact candidate as the current
  per-target selector while reducing duplicate requests;
- correction, cutoff, identity mismatch, ambiguity, pagination, rate limit,
  and malformed-response cases fail with stable codes;
- one receipt bound to multiple products creates one source artifact and chunk
  set with multiple entity bindings;
- source artifact and corpus append in one transaction;
- changed PDF checksum, text checksum, receipt, filename, locator, or chunk
  identity causes a conflict;
- a committed corpus is read back and compared before cleanup is authorized;
- every pre-commit and read-back failure leaves success cleanup unauthorized;
- cleanup cannot remove a file outside the exact temporary run directory;
- reports and logs contain no API key or chunk prose.

### Real-data gates

1. Re-run KODEX 200 through PostgreSQL and prove the six accepted chunks, source
   provenance, read-back hash, and exact-file cleanup.
2. Run one additional ETF from another manager.
3. Run one public fund with multiple share-class bindings.
4. Run a 100-document capacity batch and report aggregate success, failure,
   deduplication, request, byte, chunk, token, database, and cleanup counts.
5. Continue the full universe only when the sample has no source-binding,
   deletion-safety, transaction, or disk-budget blocker.

## 7. Success Criteria

- Every in-scope target has exactly one indexed or bounded-failure coverage
  disposition.
- Every indexed chunk resolves to one document, source, exact official file
  identity, PDF checksum, text checksum, page and section locator, and bound
  product Entity.
- Every successful document has `metadata_only_deleted` provenance and no local
  PDF remaining.
- No cleanup occurs for an uncommitted or unverified corpus.
- Duplicate documents are not re-downloaded, re-chunked, or stored twice after
  their committed identity is verified.
- Full processing can stop and resume without changing committed results.
- Raw PDF bytes, source prose outside approved chunks, API credentials, and
  generated real-data reports remain outside Git.

## 8. Accepted Limitation

PostgreSQL retains proof of which bytes were processed but not the bytes
themselves. If DART later removes the attachment or serves different bytes, the
system can detect non-reproducibility through the recorded locator and
checksums, but it cannot reconstruct the deleted PDF. This limitation is part
of the approved storage trade-off and must be disclosed in corpus operations
documentation.

# DART Streaming Corpus Ingestion Implementation Plan

> **For agentic workers:** Execute this plan inline in the current session. Do
> not delegate tasks. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest Claim-selected chunks for every DART-eligible product in the
organizer's `2026-08-24` domestic ETF and public-fund universe, retain exact
source-file provenance in PostgreSQL, and delete each temporary PDF only after
the committed corpus is read back and verified.

**Architecture:** Freeze the target inventory from the organizer-backed
PostgreSQL dataset, reconcile only exact publisher bindings, discover filings
once per publisher, and stream each unique official PDF through capture,
extraction, Claim selection, atomic persistence, read-back verification, and
path-safe cleanup. DART never expands the organizer universe.

**Tech Stack:** Python 3.12, PostgreSQL 15, SQLAlchemy 2 async Core, Alembic,
pdfplumber, standard-library urllib/XML/ZIP/hashlib/tempfile, pytest 8.

**Spec:** `docs/planning/specs/2026-08-31-dart-streaming-corpus-ingestion-design.md`

## Global Constraints

- The organizer `2026-08-24` domestic ETF and public-fund population is the
  only permitted target universe.
- DART-only products, fuzzy matches, substring matches, and Vector-similarity
  matches cannot create a target or Entity.
- Only tier-1 DART filings available no later than `2026-08-24` are eligible.
- Keep the approved Claim selector, 300–800-token quality range, 20-chunk soft
  maximum, and 8,000-selected-token soft maximum. Do not truncate.
- Use one logical document and chunk set for duplicate receipts or PDF hashes.
- Do not retain PDF bytes locally or in Object Storage after success.
- PostgreSQL 15 is authoritative. Write only to an inactive `building` dataset.
- Never print or persist the DART API key. Ignore repository-root `api.txt`
  before any live run.
- Do not generate embeddings, populate pgvector, project Graph data, or activate
  a dataset in this plan.
- Raw workbooks, PDFs, full extracted text, real reports, databases, and
  credentials remain outside Git.

---

### Task 1: Add Source-Artifact Provenance and Retention State

**Files:**
- Create: `alembic/versions/0008_document_source_artifact.py`
- Modify: `src/financial_agent/db/schema/document.py`
- Modify: `src/financial_agent/db/repositories/documents.py`
- Modify: `tests/db/test_fact_document_search_schema.py`
- Modify: `tests/db/test_migration_cycle.py`
- Modify: `tests/db/test_document_repository.py`

**Interfaces:**
- Produces `DocumentSourceArtifactRecord` and table
  `document.document_source_artifact`.
- States are exactly `pending_delete`, `delete_authorized`,
  `metadata_only_deleted`, and `quarantined`.

- [ ] **Step 1: Write failing schema and repository contract tests**

Define this public record shape in the test:

~~~python
DocumentSourceArtifactRecord(
    dataset_version="documents-2026-08-24-building-v1",
    source_artifact_id="artifact:dart:20260716000161",
    source_id="source:dart:20260716000161",
    document_id="dart:20260716000161:full-prospectus",
    receipt_id="20260716000161",
    original_filename="KODEX 200 투자설명서.pdf",
    filing_locator="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260716000161",
    attachment_locator="https://dart.fss.or.kr/pdf/download/file.do?rcp_no=20260716000161&dcm_no=1&fl_nm=1",
    media_type="application/pdf",
    byte_count=918714,
    source_checksum="c" * 64,
    text_checksum="b" * 64,
    page_count=68,
    extraction_version="pdfplumber-layout-v1",
    retention_disposition="pending_delete",
    downloaded_at=datetime(2026, 8, 31, tzinfo=UTC),
    persisted_at=datetime(2026, 8, 31, tzinfo=UTC),
    verified_at=None,
    discarded_at=None,
    record_hash=artifact_hash,
)
~~~

Assert DART host, receipt, checksums, positive counts, aware timestamps,
immutable identity, and legal state transitions. `metadata_only_deleted`
requires both `verified_at` and `discarded_at`.

- [ ] **Step 2: Run focused tests and verify RED**

~~~bash
.venv/bin/python -m pytest \
  tests/db/test_fact_document_search_schema.py \
  tests/db/test_document_repository.py \
  -k 'source_artifact or retention' -q
~~~

Expected: failure because the table and record do not exist.

- [ ] **Step 3: Implement migration `0008` and the frozen record**

Create a one-to-one table keyed by `(dataset_version, document_id)` with a
unique `(dataset_version, source_artifact_id)` key and foreign keys to
`document_record` and `source_record`. Add exact state, timestamp, approved-host,
checksum, count, and receipt checks.

Keep `document_record.object_key` as the logical key
`documents/dart/<receipt>/full-prospectus.pdf`. Availability is determined only
from `retention_disposition`.

- [ ] **Step 4: Verify migration and repository tests**

~~~bash
.venv/bin/python -m pytest \
  tests/db/test_migration_cycle.py \
  tests/db/test_fact_document_search_schema.py \
  tests/db/test_document_repository.py -q
~~~

Require `0007 → 0008 → 0007 → 0008` and legacy-row preservation.

- [ ] **Step 5: Commit Task 1**

~~~bash
git add alembic/versions/0008_document_source_artifact.py \
  src/financial_agent/db/schema/document.py \
  src/financial_agent/db/repositories/documents.py \
  tests/db/test_fact_document_search_schema.py \
  tests/db/test_migration_cycle.py tests/db/test_document_repository.py
git diff --cached --check
git commit -m "feat: track discarded DART source files"
~~~

---

### Task 2: Persist and Read Back One Complete Captured Corpus Atomically

**Files:**
- Modify: `src/financial_agent/db/repositories/documents.py`
- Modify: `src/financial_agent/ingestion/document_sources/dart_pipeline.py`
- Modify: `tests/db/test_document_repository.py`
- Modify: `tests/ingestion/document_sources/test_dart_pipeline.py`

**Interfaces:**
- Produces `CapturedDocumentCorpus(source, corpus, source_artifact,
  additional_coverages)`.
- Produces `append_captured_corpus(...)`, `get_captured_corpus(...)`, and
  `transition_source_retention(...)`.

- [ ] **Step 1: Write failing atomicity and read-back tests**

Use one document bound to two organizer products. Assert one source, document,
artifact, and chunk set with two bindings and two coverage rows. Inject a
failure after each insert group and assert zero partial rows.

An identical retry is a no-op. Any changed receipt, filename, locator, source or
text checksum, page count, binding, chunk, or coverage must raise
`DOCUMENT_CORPUS_CONFLICT`.

- [ ] **Step 2: Run focused tests and verify RED**

~~~bash
.venv/bin/python -m pytest \
  tests/db/test_document_repository.py \
  tests/ingestion/document_sources/test_dart_pipeline.py \
  -k 'captured or source_artifact or multiple_binding' -q
~~~

- [ ] **Step 3: Implement the minimal transaction**

Insert the `SourceRecord`, document, profile, exact entity bindings, chunks,
coverages, and source artifact through one SQLAlchemy connection and
transaction. Return the same aggregate from `get_captured_corpus` and compare
canonical bytes.

Allow only:

~~~text
pending_delete -> delete_authorized
pending_delete -> quarantined
delete_authorized -> metadata_only_deleted
delete_authorized -> quarantined
~~~

- [ ] **Step 4: Run focused tests and commit**

~~~bash
.venv/bin/python -m pytest \
  tests/db/test_document_repository.py \
  tests/ingestion/document_sources/test_dart_pipeline.py -q
git add src/financial_agent/db/repositories/documents.py \
  src/financial_agent/ingestion/document_sources/dart_pipeline.py \
  tests/db/test_document_repository.py \
  tests/ingestion/document_sources/test_dart_pipeline.py
git diff --cached --check
git commit -m "feat: atomically persist captured document corpora"
~~~

---

### Task 3: Freeze the Organizer-Authoritative DART Target Inventory

**Files:**
- Modify: `src/financial_agent/db/repositories/document_targets.py`
- Create: `src/financial_agent/ingestion/document_sources/dart_targets.py`
- Create: `tests/ingestion/document_sources/test_dart_targets.py`
- Modify: `tests/db/test_document_target_repository.py`

**Interfaces:**
- Produces `OrganizerDartTarget`, `OrganizerDartInventory`, and
  `build_organizer_dart_inventory(...)`.
- Inventory includes only existing `domestic_etf` and `public_fund` entities
  and records its canonical SHA-256.

- [ ] **Step 1: Write failing inventory tests**

Prove that the inventory excludes bonds, overseas ETFs, indexes, and DART-only
candidates; carries organizer entity, family, name, identifiers,
representative-fund relation, and `managedBy` institution; groups share classes
only through an exact organizer relation; rejects duplicates and unaccounted
keys; and hashes identically across database row order.

- [ ] **Step 2: Run tests and verify RED**

~~~bash
.venv/bin/python -m pytest \
  tests/db/test_document_target_repository.py \
  tests/ingestion/document_sources/test_dart_targets.py -q
~~~

- [ ] **Step 3: Add a DART-only target query**

Join organizer-created products to exact identifiers, `managedBy`, manager
institution, and representative share-class relation. Return no target lacking
an organizer product row. Keep the general source-audit query unchanged.

- [ ] **Step 4: Reconcile the real organizer inventory read-only**

Against a disposable PostgreSQL 15 `building` dataset, require:

~~~text
domestic ETF rows: 1,780
nonblank public-fund representative identifiers: 6,885 unique
public-fund rows without representative identifier: 120
~~~

A lower database count is permitted only through documented exact overlap or
invalid-identifier dispositions. Store only aggregate counts and inventory hash
outside Git.

- [ ] **Step 5: Commit Task 3**

~~~bash
git add src/financial_agent/db/repositories/document_targets.py \
  src/financial_agent/ingestion/document_sources/dart_targets.py \
  tests/db/test_document_target_repository.py \
  tests/ingestion/document_sources/test_dart_targets.py
git diff --cached --check
git commit -m "feat: freeze organizer DART target inventory"
~~~

---

### Task 4: Reconcile Official Publisher Codes and Discover by Publisher

**Files:**
- Create: `src/financial_agent/ingestion/document_sources/dart_publishers.py`
- Create: `src/financial_agent/ingestion/document_sources/dart_batch.py`
- Modify: `src/financial_agent/ingestion/document_sources/dart.py`
- Create: `tests/ingestion/document_sources/test_dart_publishers.py`
- Create: `tests/ingestion/document_sources/test_dart_batch.py`

**Interfaces:**
- Produces `DartPublisherBinding`, `DartPublisherReconciliation`, and
  `discover_dart_candidates_by_publisher(...)`.

- [ ] **Step 1: Write failing corporation-code reconciliation tests**

Use synthetic `corpCode.xml` ZIP data. Accept only exact organizer institution
identifier equality, exact normalized official company-name equality, or an
explicit reviewed alias from an ignored local mapping. Reject one-to-many
names, guessed abbreviations, malformed ZIP/XML, and aliases not anchored to an
organizer manager key.

The public-fund `or_co_xtn_itt_cd` values are organizer external-institution
codes, not DART corporation codes. They must pass an explicit official or
reviewed mapping; equal length is not evidence of identity.

- [ ] **Step 2: Write failing publisher-batch discovery tests**

One publisher filing page must be fetched once for many products. Reuse current
correction and cutoff rules. Reject unmatched filings before attachment access.
Require:

~~~python
set(indexed_ids) | set(failed_ids) == set(inventory.target_ids)
set(indexed_ids) & set(failed_ids) == set()
set(downloaded_ids) <= set(inventory.target_ids)
~~~

- [ ] **Step 3: Run tests and verify RED**

~~~bash
.venv/bin/python -m pytest \
  tests/ingestion/document_sources/test_dart_publishers.py \
  tests/ingestion/document_sources/test_dart_batch.py -q
~~~

- [ ] **Step 4: Implement bounded publisher discovery**

Fetch `corpCode.xml` once, validate its official host and bounded ZIP/XML shape,
then create exact publisher groups. Reuse the existing filing decoder and
selector. Unmatched filings become rejected discovery results and are never
downloaded. Reports contain identifiers and reason codes but no source prose or
key.

- [ ] **Step 5: Run all DART tests and commit**

~~~bash
.venv/bin/python -m pytest \
  tests/ingestion/document_sources/test_dart.py \
  tests/ingestion/document_sources/test_dart_publishers.py \
  tests/ingestion/document_sources/test_dart_batch.py -q
git add src/financial_agent/ingestion/document_sources/dart.py \
  src/financial_agent/ingestion/document_sources/dart_publishers.py \
  src/financial_agent/ingestion/document_sources/dart_batch.py \
  tests/ingestion/document_sources/test_dart_publishers.py \
  tests/ingestion/document_sources/test_dart_batch.py
git diff --cached --check
git commit -m "feat: discover organizer DART filings by publisher"
~~~

---

### Task 5: Stream Capture, Read-Back Verification, and Safe Cleanup

**Files:**
- Modify: `src/financial_agent/ingestion/document_sources/dart_capture.py`
- Create: `src/financial_agent/ingestion/document_sources/dart_ingestion.py`
- Create: `tests/ingestion/document_sources/test_dart_ingestion.py`
- Modify: `tests/ingestion/document_sources/test_dart_capture.py`

**Interfaces:**
- Produces `DartCorpusIngestionRequest`, `DartCorpusIngestionResult`,
  `ingest_one_dart_document(...)`, and `safe_discard_verified_pdf(...)`.
- Capture returns official original filename and sanitized attachment locator.

- [ ] **Step 1: Write failing cleanup-authorization tests**

Deny cleanup when the transaction did not commit, read-back differs, retention
is not `delete_authorized`, path is a symlink/directory/outside run root, or the
immediate pre-delete checksum differs. The success case deletes exactly one PDF
and transitions to `metadata_only_deleted` after deletion.

- [ ] **Step 2: Run tests and verify RED**

~~~bash
.venv/bin/python -m pytest \
  tests/ingestion/document_sources/test_dart_capture.py \
  tests/ingestion/document_sources/test_dart_ingestion.py -q
~~~

- [ ] **Step 3: Implement the one-document state machine**

Use a generated temporary directory under one run root. Capture, extract,
select, chunk, append the captured corpus, read it back, compare canonical
hashes, authorize deletion, recheck file hash, delete the exact file, and mark
the artifact deleted.

Keep at most five quarantined PDFs or 100 MiB, whichever comes first. Stop for
review before exceeding either bound.

- [ ] **Step 4: Verify crash and resume boundaries**

Simulate crashes after commit, read-back, authorization, and deletion. Resume
must converge to one corpus and `metadata_only_deleted` without deleting an
unrelated file.

- [ ] **Step 5: Commit Task 5**

~~~bash
git add src/financial_agent/ingestion/document_sources/dart_capture.py \
  src/financial_agent/ingestion/document_sources/dart_ingestion.py \
  tests/ingestion/document_sources/test_dart_capture.py \
  tests/ingestion/document_sources/test_dart_ingestion.py
git diff --cached --check
git commit -m "feat: stream DART PDFs into PostgreSQL"
~~~

---

### Task 6: Add a Resumable Batch CLI and Sanitized Report

**Files:**
- Modify: `.gitignore`
- Modify: `src/financial_agent/ingestion/cli.py`
- Create: `tests/ingestion/test_dart_corpus_cli.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Adds `ingest-dart-corpus`.
- Reads `FINANCIAL_AGENT_DART_API_KEY_FILE`,
  `FINANCIAL_AGENT_BUILD_DATABASE_URL`, dataset version, temp root, reviewed
  publisher mapping, output path, and optional `--limit`.
- Writes counts, IDs, hashes, reason codes, bytes, chunks, provisional tokens,
  and cleanup counts, but no source prose or credential.

- [ ] **Step 1: Write failing CLI and secrecy tests**

Require repository-root `api.txt` to be ignored. Validate one nonblank key,
PostgreSQL 15, an inactive `building` dataset, and paths outside tracked source.
Reject unknown fields, invalid limits, wrong cutoff/database state, unsafe temp
root, and output under Git. Scan stdout, stderr, report, errors, and logs for a
synthetic key and chunk prose.

- [ ] **Step 2: Run tests and verify RED**

~~~bash
.venv/bin/python -m pytest tests/ingestion/test_dart_corpus_cli.py -q
~~~

- [ ] **Step 3: Implement bounded execution**

~~~text
load and hash organizer target inventory
-> reconcile publishers
-> discover filings by publisher
-> deduplicate selected receipts
-> process unique documents sequentially
-> reconcile every target disposition
-> atomically write sanitized report
~~~

Stop cleanly on DART rate limit, database loss, quarantine limit, inventory
drift, or unsafe cleanup. Resume only from committed PostgreSQL state.

- [ ] **Step 4: Run non-network tests and commit**

~~~bash
.venv/bin/python -m pytest \
  tests/ingestion/test_dart_corpus_cli.py \
  tests/ingestion/document_sources tests/documents \
  -m 'not postgres and not official_data and not document_data' -q
git add .gitignore src/financial_agent/ingestion/cli.py \
  tests/ingestion/test_dart_corpus_cli.py pyproject.toml
git diff --cached --check
git commit -m "feat: add resumable DART corpus command"
~~~

---

### Task 7: Verify PostgreSQL 15 and Run the Organizer Corpus

**Files:**
- Create: `tests/ingestion/document_sources/test_real_dart_corpus_ingestion.py`
- Modify: `docs/planning/STATUS.md`
- Modify: `docs/planning/tasks/2026-08-31-dart-streaming-corpus-ingestion-plan.md`

**Interfaces:**
- Real tests require explicit `RUN_DOCUMENT_DATA_TESTS=1` and environment paths.
  Missing configuration after opt-in is a hard failure.

- [ ] **Step 1: Run KODEX 200 through PostgreSQL 15**

Require 68 text pages, one strategy chunk, five separate risk chunks, complete
artifact metadata, identical read-back hash, and no PDF after success.

- [ ] **Step 2: Run another-manager ETF and a multi-class public fund**

The ETF must use an independently resolved publisher. The fund must bind
multiple organizer Entities to one document and one chunk set. Neither may use
fuzzy identity.

- [ ] **Step 3: Run the 100-unique-document capacity gate**

Report only aggregate inventory, publisher, receipt, request, byte, extraction,
chunk, provisional-token, PostgreSQL-growth, cleanup, quarantine, and failure
counts. Continue only with no extra DART product, unsafe deletion, partial
transaction, unexpected remaining PDF, or disk blocker.

- [ ] **Step 4: Run the remaining organizer universe**

Process unique documents sequentially and resume across rate-limit windows. Do
not weaken source or identity rules to increase coverage. Record every
unresolved publisher, document, section, budget, and download failure.

- [ ] **Step 5: Reconcile final coverage**

Require:

~~~text
indexed organizer target IDs
+ bounded-failure organizer target IDs
= frozen organizer DART target IDs
~~~

Require zero downloaded DART-only products, zero successful local PDFs, one
artifact row per indexed document, and sampled source/chunk hash read-back from
every publisher.

- [ ] **Step 6: Run focused and broad verification**

~~~bash
.venv/bin/python -m pytest \
  tests/documents tests/ingestion/document_sources \
  tests/db/test_document_repository.py \
  tests/db/test_fact_document_search_schema.py \
  tests/db/test_migration_cycle.py -q

.venv/bin/python -m pytest \
  -m 'not ncp_integration and not official_data and not object_storage and not organizer_data and not document_data' -q
~~~

Inspect status, diff, ignored real-data paths, and staged content. No file under
`data/`, PDF, key, real report, or database may be staged.

- [ ] **Step 7: Update status and commit verification code**

Record exact tests and aggregate real-run results. State that PDF bytes were
deleted and cannot be reconstructed from PostgreSQL.

~~~bash
git add tests/ingestion/document_sources/test_real_dart_corpus_ingestion.py \
  docs/planning/STATUS.md \
  docs/planning/tasks/2026-08-31-dart-streaming-corpus-ingestion-plan.md
git diff --cached --check
git commit -m "test: verify organizer DART corpus ingestion"
~~~

## Completion Gate

- [ ] Target inventory comes only from the organizer `2026-08-24` dataset.
- [ ] Every download belongs to one exact organizer Entity and publisher.
- [ ] PostgreSQL 15 stores complete provenance, chunks, bindings, coverage, and
  retention state.
- [ ] Cleanup requires commit, canonical read-back, authorization, and immediate
  checksum verification.
- [ ] Every successful artifact is `metadata_only_deleted` and its PDF is absent.
- [ ] Every organizer target has one indexed or bounded-failure disposition;
  DART-only products have none.
- [ ] Key, workbooks, PDFs, database, reports, and generated corpus stay outside
  Git.
- [ ] Embeddings, VectorDB, Graph, activation, and NCP deployment stay unstarted.

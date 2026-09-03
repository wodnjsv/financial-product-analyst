# DART Recovery, Ingestion, and Delta Embedding Completion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the full-suite regressions, recover every exactly supportable missing DART prospectus for the organizer-bound ETF and public-fund scope, and store embeddings for every newly committed chunk without changing the existing 37,629 vectors.

**Architecture:** Keep `organizer-dart-2026-08-24-v2` and its 2026-08-24 cutoff as the authority boundary. Improve only deterministic manager, product-name, document-lineage, attachment, extraction, and Claim-section gates, then run the existing streaming DART ingestion and resumable NCP BGE-M3 delta builder. Unresolved or genuinely unavailable official documents remain explicit failures; coverage is never increased through fuzzy or inferred identity.

**Tech Stack:** Python 3.12, PostgreSQL 15, SQLAlchemy 2, Alembic, pgvector, pdfplumber, OpenDART, NCP CLOVA Studio BGE-M3, pytest.

**Spec:** `docs/planning/specs/2026-09-03-dart-missing-embedding-recovery-design.md`

## Global Constraints

- Dataset version remains `organizer-dart-2026-08-24-v2`; cutoff remains `2026-08-24`.
- The existing 37,629 exact embeddings for `ncp-clova-bge-m3` / `embedding-v2-dart-search-text-v1` / dimension `1024` are immutable.
- ETN targets and private-fund members remain outside this fund-prospectus recovery run.
- Organizer raw data, API credentials, downloaded PDFs, local diagnostic artifacts, and embedding reports remain untracked.
- Manager identity requires official fund-manager evidence plus an exact OpenDART legal-entity match.
- Product identity may normalize only Unicode, whitespace, balanced wrappers, reviewed report boilerplate, and explicit share-class markers within one verified publisher.
- Substring, edit-distance, fuzzy, Vector, and cross-publisher identity matching remain prohibited.
- A PDF is processed one at a time and deleted after verified commit/read-back, or after its sanitized failure receipt is recorded.
- Only public DART chunk text is sent to NCP; vectors are stored only in local PostgreSQL.
- Completion means every selected applicable target is either newly covered or assigned a precise unresolved reason. It does not mean forcing all 5,117 targets to match.

## Verified Starting Point

- 1,959 organizer targets already embedded.
- 5,117 applicable targets remain: 275 domestic ETF and 4,842 public-fund targets.
- 545 ETN targets, 7,950 private-fund targets, and 3 private members in mixed groups are excluded.
- Previous residual reasons: 3,080 name mismatch, 1,058 metadata ambiguity, 597 manager binding missing, 153 approved section missing, 105 correction lineage unresolved, 92 attachment missing, 27 text-layer missing, 3 unusable representative identifiers, 1 invalid PDF, and 1 ambiguous attachment.
- The 597 manager-unbound targets contain 1,556 public-fund members and 32 distinct organizer manager codes.

---

### Task 1: Restore deterministic full-suite isolation and migration verification

**Files:**
- Modify: `tests/db/test_document_target_repository.py`
- Modify: `tests/db/test_foundation_migration.py`
- Modify: `tests/db/test_migration_cycle.py`
- Modify: `tests/db/test_ncp_preflight.py`
- Modify: `scripts/verify_database_migrations.py`
- Modify: `schemas/postgresql/v1/database-objects.json`

**Interfaces:**
- Consumes: Alembic head `0009`, the `document.document_source_artifact` foreign key, and `EmbeddingModelContract`.
- Produces: a clean canonical `financial_agent_test` full-suite run with no cross-test model or dataset state.

- [ ] **Step 1: Add or adjust tests so the known regressions fail independently**

Use a test-only model contract in the recovery repository fixture rather than the production model identity:

```python
RECOVERY_TEST_MODEL = replace(
    APPROVED_MODEL,
    model_id="test-dart-recovery-model",
    model_version="1",
    approval_record_id="test-dart-recovery-approval",
    model_hash="d" * 64,
)
```

Make the foundation cleanup exercise deletion when a source-artifact row exists. Current-head assertions must derive or expect `0009`; explicit historical migration tests that intentionally upgrade or downgrade to `0008` remain unchanged.

- [ ] **Step 2: Verify the isolated failures**

Run the affected tests against a freshly initialized canonical database. Expected before the fix: model contract mismatch, source-artifact FK truncation failure, and `0008`/manifest drift failures.

- [ ] **Step 3: Apply the minimal isolation and current-head corrections**

Add `document.document_source_artifact` before its referenced document rows in `_truncate_foundation_tables`. Replace only current-head literals with `0009` or `_expected_alembic_head()` as appropriate. Change `MigrationVerificationReport.alembic_head` to the actual head. Regenerate the reviewed database-object manifest from a clean `0009` database using `scripts/export_database_objects.py`; do not hand-edit generated object definitions.

- [ ] **Step 4: Run migration, repository, and full-suite verification**

Expected final result on a fresh `financial_agent_test`: all local tests pass except explicitly gated NCP/object-storage/real-source tests, which remain skipped.

- [ ] **Step 5: Commit the verified regression repair**

```text
fix: restore database test isolation at migration 0009
```

---

### Task 2: Produce an exact missing-target diagnostic inventory

**Files:**
- Modify: `src/financial_agent/ingestion/cli.py`
- Test: `tests/ingestion/test_dart_corpus_cli.py`
- Local only: `/private/tmp/financial-agent-dart-recovery-diagnostics.json`

**Interfaces:**
- Consumes: `DartRecoverySelection` and the existing full-run failure report.
- Produces: sanitized aggregate reason/family counts plus a local-only review inventory for exact manager and name analysis.

- [ ] **Step 1: Write a failing report test**

Assert that a missing-only report accounts for the full actionable population before `--limit` is applied:

```python
assert report.actionable_target_family_counts == (
    ("domestic_etf", 275),
    ("public_fund", 4842),
)
assert report.selected_target_count == len(report.indexed_target_ids) + len(report.failed_targets)
```

- [ ] **Step 2: Verify the test fails for any unaccounted disposition**

Mutation check: removing a failure or counting a completed/non-applicable target as actionable must fail the test.

- [ ] **Step 3: Add only aggregate production reporting**

Keep names, organizer codes, candidate filings, and local paths out of the persisted run report. Generate any detailed target/candidate inspection as an ignored local artifact under `/private/tmp` using existing public DART and organizer identities.

- [ ] **Step 4: Reconcile the local diagnostic against the verified baseline**

Require exactly 5,117 actionable targets and the ten residual reason groups recorded in this plan before changing matching behavior.

- [ ] **Step 5: Commit only reusable report/test changes**

```text
test: close DART recovery disposition accounting
```

---

### Task 3: Recover exact manager bindings for the 32 residual codes

**Files:**
- Modify: `src/financial_agent/ingestion/mapping/asset_managers.py`
- Modify: `tests/ingestion/test_asset_managers.py`
- Modify: `tests/ingestion/test_public_fund_mapping.py`
- Modify only if the organizer-derived mapping changes: dataset build configuration/documentation; never organizer raw files.

**Interfaces:**
- Consumes: 32 exact `or_co_xtn_itt_cd` values, official KOFIA manager identity, and exact OpenDART corporation identity.
- Produces: reviewed `PublicFundManagerBinding` entries or explicit unresolved-code dispositions.

- [ ] **Step 1: Classify all 32 codes using official evidence**

For each code, record one of: exact manager and DART corporation match; official manager without DART corporation; missing/placeholder (`99999999` included); conflicting managers; or no official evidence. Do not infer from a fund name.

- [ ] **Step 2: Write failing literal mapping tests for confirmed codes only**

```python
binding = public_fund_manager_binding("<confirmed-code>")
assert binding is not None
assert binding.identity.canonical_name == "<official-legal-name>"
assert binding.identity.dart_corp_code == "<exact-eight-digit-code>"
```

Add negative tests proving placeholders and ambiguous codes remain unresolved.

- [ ] **Step 3: Add the reviewed registry deltas**

Use the existing immutable `_public_fund_binding(...)` pattern and retain official evidence references. If a representative group contains incompatible confirmed managers, keep it ambiguous instead of selecting one.

- [ ] **Step 4: Rebuild only if mapping records changed**

Rebuild the organizer-derived dataset reproducibly; do not patch active rows. Reconcile product and target counts to 25,239 and 15,571 and re-check the 37,629 protected embeddings before continuing.

- [ ] **Step 5: Commit confirmed mappings and tests**

```text
feat: add reviewed residual public-fund managers
```

---

### Task 4: Recover deterministic product names and correction lineages

**Files:**
- Modify: `src/financial_agent/ingestion/document_sources/dart.py`
- Test: `tests/ingestion/document_sources/test_dart.py`

**Interfaces:**
- Consumes: one verified publisher, organizer canonical/member names, DART `report_nm`, receipt date/number, and correction markers.
- Produces: one exact current cutoff-eligible filing lineage or a precise ambiguity reason.

- [ ] **Step 1: Derive literal fixtures from real residual variants**

Choose the smallest representative fixtures for Unicode/whitespace, balanced wrapper, reviewed report boilerplate, and explicit share-class differences. Each fixture must preserve the full DART response shape used by the adapter.

- [ ] **Step 2: Write failing normalization and negative tests**

Assert accepted variants resolve only within one publisher. Add negative tests for substring-only, edit-distance-only, cross-publisher, two normalized names, and unrecognized suffixes.

- [ ] **Step 3: Implement one conservative identity function**

Extend `_normalize_product_identity` only with transformations approved by ADR-0033. Keep `_matches_all_share_classes` explicit and bounded; do not add a similarity score.

- [ ] **Step 4: Write failing correction-lineage tests**

Cover latest valid correction before cutoff, withdrawn latest filing, competing report identities, after-cutoff correction, and unresolved correction order.

- [ ] **Step 5: Select a filing only when one lineage is deterministic**

Group by normalized product identity and document type, then apply cutoff and correction state. Preserve `dart_product_metadata_ambiguous` or `dart_correction_state_unresolved` whenever more than one valid current lineage remains.

- [ ] **Step 6: Run the DART adapter and batch suites and commit**

```text
fix: resolve exact DART product and correction identities
```

---

### Task 5: Recover attachments, Claim sections, and text-layer failures narrowly

**Files:**
- Modify: `src/financial_agent/ingestion/document_sources/dart_capture.py`
- Modify: `src/financial_agent/documents/pdf_extraction.py`
- Modify: `src/financial_agent/documents/section_selection.py`
- Modify: `src/financial_agent/ingestion/document_sources/dart_pipeline.py`
- Test: corresponding files under `tests/ingestion/document_sources/` and `tests/documents/`.

**Interfaces:**
- Consumes: an exact filing and attachment, verified PDF bytes, requested Claim section types.
- Produces: selected exact-text chunks with page/span provenance or a specific bounded failure.

- [ ] **Step 1: Write failing attachment tests from the 94 residual cases**

Accept only the unique full-prospectus PDF belonging to the exact receipt and canonical product. Alternate filenames or table labels may normalize presentation, but multiple eligible PDFs remain ambiguous.

- [ ] **Step 2: Implement minimal attachment label handling and verify**

Do not broaden host, path, receipt, media-type, or product-identity checks.

- [ ] **Step 3: Write failing heading tests from the 153 section misses**

Add only observed numbering/punctuation/table-heading variants that map to the existing approved Claim types. Assert unrelated marketing, performance, and legal boilerplate remains excluded.

- [ ] **Step 4: Implement minimal deterministic heading normalization and verify**

Preserve exact text and original heading path in stored chunks; normalization is selection-only.

- [ ] **Step 5: Gate OCR to verified text-layer failures**

Before adding an OCR dependency or remote OCR provider, verify an approved local OCR runtime exists. If none exists, keep `PDF_TEXT_LAYER_MISSING` explicit and stop this subtask for a separate provider approval; do not upload PDF images under the embedding-only NCP authorization. OCR-derived text must carry a distinct extraction version and pass the same Claim selection, checksum, page, and read-back gates.

- [ ] **Step 6: Run extraction/pipeline suites and commit**

```text
fix: recover bounded DART attachment and section variants
```

---

### Task 6: Run canaries and the complete missing-only DART ingestion

**Files:**
- Local only: DART reports and temporary directories under `/private/tmp`.
- Modify: this plan only with sanitized aggregate results.

**Interfaces:**
- Consumes: the corrected full suite, reviewed mappings, deterministic filing rules, DART API key, and publisher aliases.
- Produces: newly committed documents/chunks plus an accounted unresolved residual.

- [ ] **Step 1: Reconcile the protected baseline**

Require `eligible=37629`, `exact=37629`, and zero missing, duplicate, stale, orphan, or wrong-dimension embeddings.

- [ ] **Step 2: Run one ETF, one public-fund, and one recovered-content canary**

Each canary must account for its target, persist/read back any successful corpus, delete the exact PDF, and leave all protected vectors unchanged.

- [ ] **Step 3: Check capacity and start the full missing-only run**

Require adequate free disk for PostgreSQL growth while keeping PDF accumulation near zero. Run only the 5,117 applicable missing targets; ETNs, private funds, and completed products must issue no requests.

- [ ] **Step 4: Resume safely across DART quota boundaries**

Reruns must skip newly completed targets. Never restart the original full 15,571-target corpus.

- [ ] **Step 5: Reconcile every target and PDF**

Require `selected = indexed + failed`, zero unaccounted targets, and no retained temporary PDFs. Record aggregate counts only in tracked documentation.

---

### Task 7: Embed only new chunks and complete reconciliation

**Files:**
- Local only: NCP embedding and reconciliation reports under `/private/tmp`.
- Modify: this plan with final sanitized counts.

**Interfaces:**
- Consumes: newly committed public DART chunks with no exact current-model embedding.
- Produces: one finite 1,024-dimensional local PostgreSQL vector per new chunk hash.

- [ ] **Step 1: Run embedding preflight**

Record exact old, new eligible, and missing counts. Any stale, orphan, duplicate, or wrong-dimension row stops the build.

- [ ] **Step 2: Run one new-chunk NCP canary**

Verify model identity, input template, token count, 1,024 dimensions, and local persistence without changing an old row.

- [ ] **Step 3: Run the resumable full delta build**

Use ADR-0032 backoff. Re-read missing hashes after every pause and commit completed batches idempotently.

- [ ] **Step 4: Run final reconciliation and retrieval samples**

Require exact embeddings equal eligible chunks, with zero missing, duplicate, stale, orphan, or wrong dimension. Run bounded real Top-5 retrieval samples across newly covered ETF and public-fund products.

- [ ] **Step 5: Inspect, document, and commit results**

Verify no file under `data/`, no organizer workbook/PDF, no credential, local report, embedding, or database file is staged. Record only aggregate coverage and unresolved reasons.

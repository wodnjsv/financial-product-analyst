# Stage 03/04 Final Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, validate, and activate one final Stage 03/04 dataset without
re-downloading DART PDFs or recomputing embeddings.

**Architecture:** Build organizer and official facts under a new immutable
dataset version, then carry forward the verified DART corpus with regenerated
dataset-scoped identities. Rebuild Graph from PostgreSQL and activate only
after all four readiness components pass.

**Tech Stack:** Python 3.12, PostgreSQL 15, SQLAlchemy 2 async Core, Alembic,
pgvector, RDFLib, pySHACL, Apache Jena/Fuseki 6.0.0, pytest 8.

**Spec:**
`docs/planning/specs/2026-09-04-stage03-stage04-final-assembly-design.md`

## Global Constraints

- Final dataset version: `competition-2026-08-24-final-v1`.
- Cutoff date: `2026-08-24`.
- Source DART dataset: `organizer-dart-2026-08-24-v2`.
- Preserve 2,214 documents, 7,267 coverages, 40,149 chunks, and 40,149
  dimension-1,024 vectors.
- Do not call DART or NCP embedding APIs.
- Do not delete the source dataset or any raw source input.
- Do not commit raw inputs, databases, vectors, graph output, logs, or secrets.

---

### Task 1: Lock the migration and source preflight

**Files:**
- Modify: `src/financial_agent/ingestion/official/sec_nport.py`
- Modify: `src/financial_agent/ingestion/official_pipeline.py`
- Test: `tests/ingestion/test_sec_nport.py`
- Test: `tests/ingestion/test_official_pipeline.py`

**Interfaces:**
- Consumes: multiple `Path` capture roots and N-PORT product bindings.
- Produces: unambiguous official object resolution and product-scoped N-PORT
  observation/evidence identities.

- [x] Add a failing test proving identical N-PORT holding keys for two products
  produce different observation and Evidence IDs.
- [x] Run the focused test and require the expected duplicate-ID failure.
- [x] Add product ID to the four affected N-PORT stable-ID inputs.
- [x] Run the focused test and require a pass.
- [x] Add failing tests for one object found in exactly one of multiple roots,
  a missing object, and an object duplicated across roots.
- [x] Implement `Path | Sequence[Path]` root resolution with missing and
  ambiguous failures.
- [x] Run both focused test files.

### Task 2: Add deterministic DART corpus carry-forward

**Files:**
- Create: `src/financial_agent/documents/carry_forward.py`
- Modify: `src/financial_agent/documents/__init__.py`
- Modify: `src/financial_agent/ingestion/cli.py`
- Test: `tests/documents/test_carry_forward.py`
- Test: `tests/ingestion/test_dart_corpus_cli.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class CorpusCarryForwardReport:
    source_dataset: str
    target_dataset: str
    document_count: int
    coverage_count: int
    chunk_count: int
    embedding_count: int

async def carry_forward_dart_corpus(
    engine: AsyncEngine,
    *,
    source_dataset: str,
    target_dataset: str,
) -> CorpusCarryForwardReport: ...
```

- [x] Write a failing PostgreSQL test with one indexed document, one additional
  coverage, one documentless negative coverage, and one embedding.
- [x] Require failure because `carry_forward_dart_corpus` does not exist.
- [x] Rebuild target document records with the target dataset version and
  canonical record hashes; preserve all non-version fields exactly.
- [x] Recompute target embedding IDs with `embedding_id(APPROVED_MODEL, chunk)`
  while copying the vector value unchanged.
- [x] Make identical reruns converge and conflicting target rows fail closed.
- [x] Add CLI configuration requiring explicit source and target versions.
- [x] Run the carry-forward and CLI tests.

### Task 3: Add final release validation

**Files:**
- Create: `src/financial_agent/ingestion/final_release.py`
- Modify: `src/financial_agent/ingestion/cli.py`
- Test: `tests/ingestion/test_final_release.py`

**Interfaces:**
- Consumes: expected source counts, Graph manifest hashes, and vector
  reconciliation.
- Produces one validation run and four readiness records, then optionally calls
  `operations.activate_dataset`.

- [x] Write failing tests proving missing entities, count drift, vector anomaly,
  graph mismatch, or absent readiness prevents activation.
- [x] Implement read-only checks and canonical component-manifest hashes.
- [x] Implement validation-run and readiness writes through existing operations
  functions; keep activation a separate final call.
- [x] Run the focused validation tests.

### Task 4: Verify code before touching the critical database

**Files:**
- Update: this plan's checkboxes only.

- [x] Run non-integration ingestion, document, embedding, retrieval, and Graph
  tests excluding Jena.
- [x] Create a disposable PostgreSQL 15 database and run migrations through
  `0012`.
- [x] Run the new PostgreSQL carry-forward and release-validation tests.
- [x] Inspect the diff and confirm no raw data, generated output, or secrets are
  present.

### Task 5: Build the final PostgreSQL dataset

**Files:**
- Runtime outputs only; nothing under `data/` is staged.

- [x] Record free space, current DB size, source counts, and active pointer.
- [x] Migrate the critical local database from `0009` to `0012`.
- [x] Verify all official manifests and objects across the four capture roots.
- [x] Run the organizer plus official build for
  `competition-2026-08-24-final-v1`.
- [x] Require the build report to pass before continuing.
- [x] Run DART carry-forward and require the exact approved counts.
- [x] Run vector reconciliation and require all anomaly counts to be zero.

## Runtime status — 2026-09-04

- PostgreSQL target remains `building` and inactive.
- Organizer, KRX, ECOS, and SEC Series/Class structured data are loaded.
- SEC N-PORT is not loaded because the sole 2026 Q2 ZIP is absent locally and
  SEC returned HTTP 403 when the official download was retried.
- DART carry-forward completed at 2,214 documents, 7,267 coverages, 40,149
  chunks, and 40,149 embeddings.
- Graph projection now omits official holdings whose weight is explicitly
  unknown. Full-data SHACL validation remained CPU-active for 50 minutes and
  was stopped; activation remains prohibited until this performance gate and
  the missing N-PORT input are resolved.

### Task 6: Build Graph and activate

**Files:**
- Runtime Graph outputs under `/private/tmp`; nothing is staged.

- [ ] Build Graph run A and require projection and SHACL success.
- [ ] Build Graph run B and require byte-identical artifacts and manifest.
- [ ] Run the configured Jena/Fuseki read-only acceptance gate.
- [ ] Record the four component readiness hashes and finish validation.
- [ ] Activate `competition-2026-08-24-final-v1` atomically.
- [ ] Run post-activation SQL, Graph, Vector, and Evidence smoke checks.
- [ ] Commit only source, tests, ADR, spec, plan, and sanitized status updates.

## Runtime status — 2026-09-05

- The complete structured build including SEC N-PORT 2026 Q2 passed. The
  target contains 58,646 canonical products and remains `building` and
  inactive.
- DART carry-forward again matched the approved counts: 2,214 documents,
  7,267 coverages, 40,149 chunks, and 40,149 embeddings.
- Vector reconciliation reported 40,149 eligible and exact rows with zero
  anomalies across missing, duplicate, stale, orphan, and dimension checks.
- Full Graph A/B plus Jena is blocked only by local working space. The current
  9.6 GiB free space is below the estimated 15–20 GiB safe requirement, so no
  partial Graph output or readiness record was created and activation remains
  prohibited.

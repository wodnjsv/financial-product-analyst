# Cross-store Integration Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the verified Graph Phase 1 core with the current
PostgreSQL and DART Vector branch, correct current organizer ETP typing, and
promote selected document candidates into immutable Evidence before they may
support a Claim.

**Architecture:** PostgreSQL remains the authority, Fuseki is a deterministic
read-only relation projection, and pgvector returns document candidates only.
Graph results retain PostgreSQL relation and Evidence IDs; selected Vector hits
are revalidated and promoted to `document_span` Evidence with an exact chunk
origin. Existing embeddings are immutable and the dataset remains inactive.

**Tech Stack:** Python 3.12, PostgreSQL 15, SQLAlchemy 2 async Core, pgvector,
RDFLib 7.6, pySHACL 0.40, Apache Jena/Fuseki 6.0.0, pytest 8.

**Spec:**
`docs/planning/specs/2026-09-03-cross-store-integration-foundation-design.md`

## Global Constraints

- Use `codex/vector-corpus-source-policy` as the integration base.
- Preserve dataset `organizer-dart-2026-08-24-v2` and cutoff `2026-08-24`.
- Preserve all 40,149 exact `ncp-clova-bge-m3` /
  `embedding-v2-dart-search-text-v1` embeddings without update or deletion.
- Preserve organizer files, official raw files, DART PDFs, generated N-Quads,
  TDB2 data, local reports, databases, and credentials outside Git.
- Keep PostgreSQL relation, document, source, and Evidence rows authoritative.
- Keep exactly 13 approved Graph predicates.
- Permit `tracksIndex` for ETF, ETN, and PublicFund under ADR-0034 while
  retaining ETF/ETN disjointness.
- Do not infer product type from names, tickers, indexes, or relationships.
- Do not pre-create Evidence for all document chunks; promote only selected
  and revalidated retrieval hits.
- Do not add real `hasRiskFactor` coverage without a normalized risk identity.
- Do not activate the dataset or write NCP PostgreSQL, Object Storage, or
  Fuseki in this plan.

---

### Task 1: Integrate the Graph Phase 1 branch

**Files:**
- Merge source: `codex/graph-phase1-core`
- Resolve: `pyproject.toml`
- Resolve: `docs/planning/STATUS.md`
- Resolve: `tests/gold/core_questions.json`
- Resolve: `tests/ingestion/test_official_question_gates.py`
- Add: Graph files under `ontology/`, `config/fuseki/`,
  `src/financial_agent/graph/`, `scripts/graph/`, and `tests/graph/`

**Interfaces:**
- Consumes: current migration `0009`, document/embedding modules, and the
  complete Graph Phase 1 commit history ending at `631191e`.
- Produces: one branch containing both current Vector and Graph public APIs.

- [x] **Step 1: Record pre-merge baselines**

Run the current full suite and Vector reconciliation. Require `1820 passed,
15 skipped`, `eligible=40149`, `exact=40149`, and all anomaly counts zero.

- [x] **Step 2: Merge without committing automatically**

```bash
git merge --no-ff --no-commit codex/graph-phase1-core
```

Expected conflicts are limited to the four reviewed shared files above.

- [x] **Step 3: Resolve shared files semantically**

Keep current source/cutoff/Vector changes and add Graph dependencies and the
normalized question-contract changes. Do not choose either complete file
wholesale. Validate `tests/gold/core_questions.json` as JSON after resolution.

- [x] **Step 4: Run the merged non-integration suites**

```bash
.venv/bin/pytest -q tests/graph -m 'not jena_integration'
.venv/bin/pytest -q tests/contracts tests/db tests/ingestion tests/documents \
  tests/retrieval tests/embeddings -m 'not postgres and not jena_integration'
```

- [x] **Step 5: Commit the integration merge**

```text
merge: integrate graph phase one with vector corpus
```

---

### Task 2: Align ETP typing and `tracksIndex` semantics

**Files:**
- Modify: `src/financial_agent/graph/repository.py`
- Modify: `src/financial_agent/graph/contract.py`
- Modify: `ontology/common.ttl`
- Modify: `ontology/shapes/domain.shacl.ttl`
- Test: `tests/db/test_graph_projection_repository.py`
- Test: `tests/graph/test_ontology_contract.py`
- Test: `tests/graph/test_shacl_validation.py`

**Interfaces:**
- Consumes: source-qualified organizer metrics
  `organizer.pref01n001.product_type`,
  `organizer.pref02n001.product_type`, and
  `organizer.pref02n001.is_etn`.
- Produces: `GraphProjectionRepository.load(dataset_version)` that types each
  current ETP exactly once and accepts an ETN `tracksIndex` assertion.

- [x] **Step 1: Add failing current-metric repository tests**

Create fixtures with domestic ETF, domestic ETN, overseas ETF, and overseas
ETN observations using the exact source-qualified metric IDs. Assert their RDF
types and assert failures for missing type, conflicting type, and overseas
`is_etn` disagreement.

- [x] **Step 2: Add failing ETN ontology and SHACL tests**

Assert that ETN `tracksIndex` conforms, ETF+ETN dual typing does not conform,
and a non-ETP/non-public-fund subject still fails.

- [x] **Step 3: Implement the minimal current-metric mapping**

Replace the obsolete generic metric lookup with the two exact product-type
metric IDs and one overseas consistency metric. Extend only the `tracksIndex`
domain to `ExchangeTradedProduct | PublicFund` in the repository, TBox, and
SHACL.

- [x] **Step 4: Run focused tests and a real read-only load**

```bash
.venv/bin/pytest -q tests/db/test_graph_projection_repository.py \
  tests/graph/test_ontology_contract.py tests/graph/test_shacl_validation.py
```

Then load `organizer-dart-2026-08-24-v2` from the current local PostgreSQL and
require zero type, relation, Evidence, source, date, and metric errors.

- [x] **Step 5: Commit ETP compatibility**

```text
fix: align graph ETP types with organizer metrics
```

---

### Task 3: Promote selected document hits to Evidence

**Files:**
- Create: `src/financial_agent/retrieval/document_evidence.py`
- Modify: `src/financial_agent/retrieval/__init__.py`
- Test: `tests/retrieval/test_document_evidence.py`
- Modify if a single transaction is required: `src/financial_agent/db/repositories/evidence.py`

**Interfaces:**
- Consumes: `DocumentCandidateHit`, an approved `claim_type`, and the current
  PostgreSQL document/source metadata.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class PromotedDocumentEvidence:
    candidate: DocumentCandidateHit
    evidence: EvidenceRecord

class DocumentEvidencePromoter:
    async def promote(
        self,
        candidate: DocumentCandidateHit,
        *,
        claim_type: str,
    ) -> PromotedDocumentEvidence: ...
```

- [x] **Step 1: Write failing happy-path and round-trip tests**

Persist a synthetic product, DART source, document profile, subject binding,
source-artifact receipt, chunk, and candidate. Assert the promoted Evidence
contains the exact dataset, entity, document/chunk origin, source, page,
section, sentence range, publication/availability/effective dates, and a
deterministic ID/hash.

- [x] **Step 2: Write failing rejection tests**

Cover a wrong entity binding, changed chunk hash, ineligible publisher,
after-cutoff document, missing source-artifact metadata, invalid retention
state, unsupported claim type, and a candidate whose stored metadata differs
from PostgreSQL. A valid `metadata_only_deleted` artifact must be accepted.

- [x] **Step 3: Implement authoritative re-read and Evidence construction**

Use one read transaction to join the exact candidate identity to
`document_entity_binding`, `document_record`, `document_profile`,
`document_chunk`, `source_record`, and `document_source_artifact`. Construct an
`EvidenceRecord(evidence_kind=document_span)` and append it with
`OriginReference(origin_kind="document_chunk")` through the existing Evidence
ledger repository.

- [x] **Step 4: Make repeated promotion idempotent**

Promoting the same tuple returns the same Evidence. A stored row with the same
ID and different canonical payload raises `EVIDENCE_LEDGER_CONFLICT`.

- [x] **Step 5: Run retrieval, Evidence, and migration tests**

```bash
.venv/bin/pytest -q tests/retrieval/test_document_evidence.py \
  tests/retrieval/test_document_search.py tests/db/test_evidence_repository.py
```

- [x] **Step 6: Commit Evidence promotion**

```text
feat: promote document candidates to evidence
```

---

### Task 4: Add a repeatable real Graph build command

**Files:**
- Create: `src/financial_agent/graph/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/graph/test_graph_cli.py`
- Update: `docs/planning/runbooks/GRAPH_LOCAL_VERIFICATION.md`

**Interfaces:**
- Consumes: explicit database URL, dataset version, output directory outside
  the repository, and tracked ontology/SHACL files.
- Produces: `data.nq`, `evidence.nq`, `manifest.json`, and a sanitized aggregate
  report only after repository load, deterministic export, and SHACL success.

- [ ] **Step 1: Write failing configuration and safety tests**

Reject a missing dataset, output inside the repository, symlink output,
nonempty output, and a report containing entity IDs, source locators, or raw
values.

- [ ] **Step 2: Write a failing deterministic build test**

Build twice from the same synthetic PostgreSQL dataset into separate temporary
directories and require byte-identical N-Quads and manifest hashes.

- [ ] **Step 3: Implement the thin command**

Compose only the existing repository, exporter, validator, and manifest APIs.
Use atomic file replacement and remove partial output on failure. Do not add a
second exporter or validation path.

- [ ] **Step 4: Run CLI and Graph suites**

```bash
.venv/bin/pytest -q tests/graph/test_graph_cli.py tests/graph \
  -m 'not jena_integration'
```

- [ ] **Step 5: Commit the build command**

```text
feat: build deterministic graph artifacts
```

---

### Task 5: Verify the integrated real-data path

**Files:**
- Local only: Graph artifacts and reports under `/private/tmp`
- Modify: `docs/planning/STATUS.md`
- Modify: this plan with aggregate results

**Interfaces:**
- Consumes: current PostgreSQL dataset, exact current vectors, and integrated
  Graph build and Evidence promotion paths.
- Produces: a local cross-store verification record without activating data.

- [ ] **Step 1: Build the real Graph twice**

Require byte-identical data/evidence N-Quads and manifests, then run RDFLib and
pySHACL validation.

- [ ] **Step 2: Run Jena/TDB2/Fuseki verification**

Use the existing pinned 6.0.0 verifier and temporary read-only Fuseki. Require
parse, SHACL, TDB2 load/query, Fuseki query, blocked update surfaces, process
termination, and temporary-state cleanup.

- [ ] **Step 3: Run real retrieval canaries**

For one domestic ETF and one public fund, run Vector Top-5 retrieval, promote
one selected hit to Evidence, read it back, and verify the exact source span.
For one real structured relationship, require Graph results to return the
original PostgreSQL `relation_id` and `evidence_id`.

- [ ] **Step 4: Reconcile protected state**

Require 40,149 exact embeddings with all anomaly counts zero. Confirm the
Graph build did not modify PostgreSQL relation/observation counts and that only
the two canary document Evidence records and origins were appended.

- [ ] **Step 5: Run the complete suite**

```bash
FINANCIAL_AGENT_TEST_DATABASE_URL="$FINANCIAL_AGENT_TEST_DATABASE_URL" \
  .venv/bin/pytest -q
```

All ordinary tests must pass; externally gated tests may skip only for their
documented environment gates.

- [ ] **Step 6: Record accurate phase status**

Record aggregate Graph entity/relation/Evidence/triple counts, deterministic
hash equality, two Evidence promotion canaries, Vector reconciliation, and
test counts. Keep official structured-source integration, readiness,
activation, and NCP deployment explicitly incomplete.

- [ ] **Step 7: Commit verification evidence**

```text
docs: record cross-store integration verification
```

---

### Task 6: Inspect and hand off the official-source workstream

**Files:**
- Modify: this plan only if final aggregate results change
- Create a separately dated official-source final-dataset design only after a
  fresh planning gate.

**Interfaces:**
- Consumes: the verified integrated foundation and existing KRX, SEC, and ECOS
  source implementations and manifests.
- Produces: exact input inventory, disk requirement, and completion boundary
  for the separate final-dataset build.

- [ ] **Step 1: Reconcile branch and source inventories read-only**

Identify the exact verified KRX/SEC/ECOS commits and local raw manifests that
are absent from the current database. Do not copy or reload them in this task.

- [ ] **Step 2: Measure final local/NCP storage requirement**

Use current PostgreSQL table sizes and the approved source manifests. Do not
assume the earlier 12.5 GB local free-space observation is still current.

- [ ] **Step 3: Report the next planning gate**

State which official sources can be integrated locally and which require NCP
storage expansion. Do not activate the current dataset or represent this
foundation as final competition readiness.

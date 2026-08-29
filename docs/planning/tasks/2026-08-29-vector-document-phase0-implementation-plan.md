# Vector Document Corpus Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Build the deterministic Phase 0 foundation that admits, classifies, chunks, persists, and safely retrieves the minimum official document corpus required by the three current Vector-routed question families.

**Architecture:** Extend the existing PostgreSQL document and pgvector schemas instead of adding another Vector product. Keep official source objects immutable, store document authority and coverage in PostgreSQL, select only approved Claim sections, and expose keyword and vector candidate lists through a typed retrieval boundary; real embedding-model selection and product-wide source connectors remain follow-up decisions.

**Tech Stack:** Python 3.12, standard-library dataclasses and enums, SQLAlchemy 2, Alembic, PostgreSQL 15, pg_trgm, pgvector, psycopg 3, pytest, pytest-asyncio.

**Spec:** [VectorDB Official Document Corpus Minimum Scope Design](../specs/2026-08-29-vector-document-corpus-design.md)

## Global Constraints

- Execute this plan only after the current dirty Stage 03 local-completion work has been committed or moved aside, from a fresh codex/vector-document-phase0 worktree based on the pushed spec-and-plan tip of origin/codex/stage03-local-completion.
- The evaluation cutoff is 2026-08-24. Preserve actual applicable, publication, availability, and effective dates.
- Track every organizer-master product in the coverage ledger, but index document chunks only for approved domestic ETF, overseas ETF, public-fund, policy-fund, and index document roles.
- Use one canonical active product document per product role and one methodology per unique index. Do not index both summary and full documents when the summary satisfies the required Claims.
- Keep organizer and official raw files, generated captures, embeddings, local databases, and real retrieval reports outside Git.
- PostgreSQL remains the document, coverage, Evidence, and model-approval authority. pgvector is a bounded candidate index.
- Do not use document text to overwrite organizer AUM, NAV, price, return, fee, risk-grade, sale-status, or other organizer fields.
- Do not infer theme, product-index, holding, company-control, or risk relations from Vector similarity.
- Only original source text with a round-trippable locator can become document-span Evidence. Search prefixes, translations, and summaries are not Evidence.
- Phase 0 uses synthetic committed fixtures and optionally configured ignored official files. It does not scrape or commit real official documents.
- Phase 0 does not select a production embedding model. Tests inject deterministic embeddings through the exact provider interface that a later benchmark will implement.
- Use TDD for every behavior change. Run the narrow test first, then the relevant PostgreSQL tests, then the ordinary non-live suite.
- Do not activate a dataset or write NCP PostgreSQL, Object Storage, Fuseki, or production Vector state.

## Scope Decomposition

This plan implements one independently testable foundation:

1. correct the stale theme-window rule;
2. extend document storage with profile, entity-binding, coverage, and section-locator metadata;
3. implement document admission and canonical selection;
4. implement Claim-driven section classification and bounded chunking;
5. persist the corpus idempotently;
6. retrieve metadata-filtered keyword and Vector candidates;
7. verify the three document question families with synthetic positive and negative cases.

The following require separate plans after this one passes:

- official source connector selection and terms-of-use review;
- actual PDF/HTML parsers and OCR;
- embedding-model benchmark and approval ADR;
- domestic ETF, public-fund, and overseas ETF full-population builds;
- runtime QueryPlan-to-document-search orchestration.

## File Structure

| Path | Responsibility |
| --- | --- |
| src/financial_agent/documents/models.py | Typed document roles, section types, coverage states, candidates, chunks, and search hits |
| src/financial_agent/documents/policy.py | Cutoff, publisher, exact binding, canonical-document, and chunk-budget rules |
| src/financial_agent/documents/chunking.py | Heading classification, allowed-section filtering, deterministic bounded chunking |
| src/financial_agent/db/schema/document.py | Document profile, entity binding, coverage, and exact span-location tables/columns |
| src/financial_agent/db/repositories/documents.py | Immutable and idempotent document-corpus persistence |
| src/financial_agent/retrieval/documents.py | Metadata-filtered keyword and pgvector candidate retrieval plus evaluation-only rank fusion |
| alembic/versions/0007_document_corpus_metadata.py | Reversible database migration for the Phase 0 document model |
| tests/fixtures/document_corpus.py | Synthetic official-like documents, sections, bindings, and deterministic vectors |
| tests/gold/document_retrieval_cases.json | Three positive families and required negative retrieval cases |
| scripts/verify_document_retrieval_pipeline.py | Offline Phase 0 safety and Top-5 report over configured synthetic or ignored inputs |

---

### Task 1: Align the Theme Window Contract With the Current Cutoff

**Files:**
- Modify: tests/gold/core_questions.json
- Modify: tests/ingestion/test_official_question_gates.py
- Modify: docs/planning/specs/2026-08-29-stage03-question-capability-analysis.md

**Interfaces:**
- Consumes: REL-THEME-001 temporal_scope and business_rules.
- Produces: one consistent inclusive window from 2026-02-24 through 2026-08-24 and the rule ID WINDOW_END_2026_08_24.
- Does not change: the question text, support level, required sources, retrieval profile, or expected Evidence.

- [ ] **Step 1: Write the failing temporal-contract test**

Add this focused assertion to tests/ingestion/test_official_question_gates.py:

```python
def test_theme_relation_window_uses_current_dataset_cutoff() -> None:
    catalog = json.loads(
        (Path(__file__).parents[1] / "gold" / "core_questions.json").read_text(
            "utf-8"
        )
    )
    case = next(item for item in catalog["cases"] if item["id"] == "REL-THEME-001")

    assert case["temporal_scope"] == {
        "window_start": "2026-02-24",
        "window_end": "2026-08-24",
        "boundary": "inclusive",
        "publication_cutoff": "2026-08-24",
    }
    assert "WINDOW_END_2026_08_24" in case["business_rules"]
    assert "WINDOW_END_2026_07_11" not in case["business_rules"]
```

- [ ] **Step 2: Run the narrow test and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/ingestion/test_official_question_gates.py::test_theme_relation_window_uses_current_dataset_cutoff -q
```

Expected: FAIL because the business rule still contains WINDOW_END_2026_07_11.

- [ ] **Step 3: Replace only the stale rule and its human-readable projection**

Change the REL-THEME-001 business rule to WINDOW_END_2026_08_24. In the analysis document, change the Control Check entry from WINDOW_END_2026_07_11 to WINDOW_END_2026_08_24. Preserve the already-correct temporal_scope dates.

- [ ] **Step 4: Run the temporal and question-catalog tests**

Run:

```bash
.venv/bin/python -m pytest tests/ingestion/test_official_question_gates.py -q
```

Expected: PASS, with all 52 question cases retained.

- [ ] **Step 5: Commit the corrected contract**

```bash
git add tests/gold/core_questions.json tests/ingestion/test_official_question_gates.py docs/planning/specs/2026-08-29-stage03-question-capability-analysis.md
git diff --cached --check
git commit -m "fix: align theme window with current cutoff"
```

---

### Task 2: Add the Minimal Document Corpus Storage Contract

**Files:**
- Create: alembic/versions/0007_document_corpus_metadata.py
- Modify: src/financial_agent/db/schema/document.py
- Modify: src/financial_agent/db/schema/__init__.py
- Modify: schemas/postgresql/v1/database-objects.json
- Modify: tests/db/test_fact_document_search_schema.py
- Modify: tests/db/test_foundation_migration.py
- Modify: tests/db/test_migration_cycle.py

**Interfaces:**
- Consumes: existing document.document_record, document.document_chunk, search.document_embedding, catalog.entity, evidence.evidence_record, and operations.dataset_version.
- Produces:
  - document.document_profile, one row per document_record;
  - document.document_entity_binding, one or more exact Entity bindings per document;
  - document.document_coverage, one status per Entity and required document role;
  - document.document_chunk.section_type, section_path, character_start, character_end.
- Preserves: current document_record and document_embedding primary keys and the pgvector placement in PostgreSQL.

- [ ] **Step 1: Write failing schema metadata tests**

Add schema assertions:

```python
def test_document_corpus_metadata_is_registered() -> None:
    from financial_agent.db.schema.document import (
        document_coverage,
        document_entity_binding,
        document_profile,
        document_chunk,
    )

    assert {
        "dataset_version",
        "document_id",
        "document_version",
        "publisher_role",
        "jurisdiction",
        "original_language",
        "effective_from",
        "effective_to",
        "amends_document_id",
        "extraction_method",
        "cutoff_eligible",
        "record_hash",
        "created_at",
    } == set(document_profile.c.keys())
    assert {"document_id", "entity_id", "binding_role"} <= set(
        document_entity_binding.c.keys()
    )
    assert {
        "coverage_id",
        "entity_id",
        "required_document_role",
        "coverage_status",
        "document_id",
        "scope_evidence_id",
        "reason_code",
        "record_hash",
        "created_at",
    } <= set(document_coverage.c.keys())
    assert {
        "section_type",
        "section_path",
        "character_start",
        "character_end",
    } <= set(document_chunk.c.keys())
```

Add PostgreSQL tests proving:

- an indexed coverage row requires a document_id and no reason_code;
- a non-indexed coverage row requires no document_id and a non-empty reason_code;
- effective_to cannot precede effective_from;
- a document binding cannot reference an Entity from another dataset_version;
- character_end cannot precede character_start;
- every new table rejects mutation after its dataset leaves building.

- [ ] **Step 2: Run the focused schema tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/db/test_fact_document_search_schema.py -q
```

Expected: FAIL because the new tables and chunk columns do not exist.

- [ ] **Step 3: Define the SQLAlchemy tables and migration**

Implement the new tables with these stable vocabularies:

```python
DOCUMENT_ROLES = (
    "product_summary",
    "product_full",
    "index_methodology",
    "official_update",
    "policy_base",
)

COVERAGE_STATUSES = (
    "indexed",
    "document_not_found",
    "ambiguous_entity_binding",
    "after_cutoff_only",
    "version_unknown",
    "unreadable_document",
    "publisher_not_approved",
    "section_missing",
    "not_applicable_current_scope",
    "review_required_chunk_budget",
)

BINDING_ROLES = ("subject_product", "subject_index", "subject_policy")
```

Use these exact table shapes:

- document_profile: dataset_version, document_id, document_version,
  publisher_role, jurisdiction, original_language, effective_from,
  effective_to, amends_document_id, extraction_method, cutoff_eligible,
  record_hash, created_at;
- document_entity_binding: dataset_version, binding_id, document_id, entity_id,
  binding_role, record_hash, created_at;
- document_coverage: dataset_version, coverage_id, entity_id,
  required_document_role, coverage_status, document_id, scope_evidence_id,
  reason_code, record_hash, created_at.

Use composite foreign keys that include dataset_version. A non-indexed
coverage row must reference a query-scope or policy EvidenceRecord through
scope_evidence_id; an indexed row must reference document_id and leave
scope_evidence_id and reason_code null. Add the existing
reject_nonbuilding_dataset_mutation trigger to all three new tables. Backfill
legacy chunk rows deterministically before setting the four new columns
non-null:

- section_type = legacy_unclassified;
- section_path = COALESCE(section, document_title);
- character_start = 0;
- character_end = length(exact_text).

The migration downgrade removes the new tables first and then the four columns. It must not delete document_record, document_chunk, or document_embedding.

- [ ] **Step 4: Run migration and schema tests**

Run:

```bash
.venv/bin/python -m pytest tests/db/test_fact_document_search_schema.py tests/db/test_foundation_migration.py tests/db/test_migration_cycle.py -q
```

Expected: PASS, including upgrade-to-head, downgrade-to-base, and re-upgrade.

- [ ] **Step 5: Refresh and verify the database object manifest**

Run:

```bash
.venv/bin/python scripts/export_database_objects.py
.venv/bin/python scripts/export_database_objects.py --check
```

Expected: the manifest includes new checks, triggers, owners, and grants, and the check is byte-deterministic.

- [ ] **Step 6: Commit the storage contract**

```bash
git add alembic/versions/0007_document_corpus_metadata.py src/financial_agent/db/schema/document.py src/financial_agent/db/schema/__init__.py schemas/postgresql/v1/database-objects.json tests/db/test_fact_document_search_schema.py tests/db/test_foundation_migration.py tests/db/test_migration_cycle.py
git diff --cached --check
git commit -m "feat: add document corpus metadata"
```

---

### Task 3: Implement Document Admission and Canonical Selection

**Files:**
- Create: src/financial_agent/documents/__init__.py
- Create: src/financial_agent/documents/models.py
- Create: src/financial_agent/documents/policy.py
- Create: tests/documents/__init__.py
- Create: tests/documents/test_policy.py

**Interfaces:**
- Consumes: typed DocumentCandidate rows derived from an exact Entity binding and official source manifest.
- Produces:
  - AdmissionDecision;
  - CanonicalDocumentSelection;
  - DocumentCoverageDraft;
  - stable enums DocumentRole, CoverageStatus, SectionType, PublisherRole.
- Public signatures:

```python
def admit_document(
    candidate: DocumentCandidate,
    *,
    cutoff_date: date,
) -> AdmissionDecision: ...

def select_canonical_document(
    candidates: tuple[DocumentCandidate, ...],
    *,
    required_role: DocumentRole,
    cutoff_date: date,
) -> CanonicalDocumentSelection: ...
```

- [ ] **Step 1: Write failing policy tests**

Cover these exact cases:

```python
def test_summary_wins_when_it_covers_all_required_claims() -> None:
    selected = select_canonical_document(
        (
            candidate("summary", document_type="summary_prospectus",
                      claim_types={"investment_strategy", "risk_factor"}),
            candidate("full", document_type="full_prospectus",
                      claim_types={"investment_strategy", "risk_factor"}),
        ),
        required_role=DocumentRole.PRODUCT_SUMMARY,
        cutoff_date=date(2026, 8, 24),
    )
    assert selected.document_id == "summary"
    assert selected.coverage_status is CoverageStatus.INDEXED


def test_after_cutoff_document_is_not_selected() -> None:
    selected = select_canonical_document(
        (candidate("late", available_at=datetime(2026, 8, 25, tzinfo=UTC)),),
        required_role=DocumentRole.PRODUCT_SUMMARY,
        cutoff_date=date(2026, 8, 24),
    )
    assert selected.document_id is None
    assert selected.coverage_status is CoverageStatus.AFTER_CUTOFF_ONLY


def test_ambiguous_entity_binding_fails_closed() -> None:
    decision = admit_document(
        candidate("ambiguous", bound_entity_ids=("product-a", "product-b")),
        cutoff_date=date(2026, 8, 24),
    )
    assert decision.coverage_status is CoverageStatus.AMBIGUOUS_ENTITY_BINDING
```

Also test publisher rejection, unknown version, unreadable text, exact duplicate documents, and summary fallback to full prospectus when required Claims are missing.

- [ ] **Step 2: Run the policy tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/documents/test_policy.py -q
```

Expected: FAIL because the documents package does not exist.

- [ ] **Step 3: Implement immutable models and allowlists**

Use frozen dataclasses and string enums. DocumentCandidate must contain:

- document_id, document_type, document_version;
- source_id, publisher_role, jurisdiction, original_language;
- published_at, available_at, effective_from, effective_to;
- bound_entity_ids and binding_role;
- claim_types, content_checksum, extraction_method;
- exact_text_available and source_locator.

AdmissionDecision must contain accepted, coverage_status, reason_code, and candidate. CanonicalDocumentSelection must contain document_id, coverage_status, reason_code, and rejected_document_ids.

Use these exact publisher-role values:

- regulator_disclosure;
- asset_manager;
- issuer;
- index_provider;
- policy_authority;
- policy_operator.

Define DocumentCoverageDraft with coverage_id, dataset_version, entity_id,
required_document_role, coverage_status, document_id, scope_evidence_id,
reason_code, and record_hash. Define DocumentChunkDraft with dataset_version,
chunk_id, document_id, ordinal, page_start, page_end, section_type,
section_path, character_start, character_end, exact_text,
normalized_search_text, embedding_text, content_hash, and record_hash.

- [ ] **Step 4: Implement fail-closed selection**

Selection order is:

1. exact one-Entity binding;
2. approved publisher role;
3. publication and availability on or before cutoff;
4. known document version and effective interval;
5. round-trippable original text;
6. required Claim coverage;
7. summary document before full document;
8. stable tie-break by effective_from descending, published_at descending, document_id ascending.

Do not use document title or Vector similarity to resolve a binding.

- [ ] **Step 5: Run policy tests**

Run:

```bash
.venv/bin/python -m pytest tests/documents/test_policy.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the admission boundary**

```bash
git add src/financial_agent/documents tests/documents
git diff --cached --check
git commit -m "feat: enforce document admission policy"
```

---

### Task 4: Implement Claim-Driven Section Selection and Bounded Chunking

**Files:**
- Create: src/financial_agent/documents/chunking.py
- Create: tests/documents/test_chunking.py

**Interfaces:**
- Consumes:
  - ExtractedSection with heading_path, exact_text, page range, character range;
  - DocumentChunkContext with document_id, canonical_entity_name, document_type, original_language;
  - TokenCounter protocol.
- Produces: tuple[DocumentChunkDraft, ...].
- Public signatures:

```python
class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...

def classify_section(section: ExtractedSection) -> SectionType | None: ...

def chunk_document_sections(
    context: DocumentChunkContext,
    sections: tuple[ExtractedSection, ...],
    *,
    counter: TokenCounter,
    target_min: int = 300,
    target_max: int = 800,
    overlap: int = 75,
    soft_limit: int = 20,
) -> ChunkingResult: ...
```

- [ ] **Step 1: Write failing classification and chunking tests**

Use Korean and English headings:

```python
@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        (("투자목적 및 투자전략",), SectionType.INVESTMENT_STRATEGY),
        (("투자위험", "환율변동위험"), SectionType.RISK_FACTOR),
        (("Principal Investment Strategies",), SectionType.INVESTMENT_STRATEGY),
        (("Principal Risks", "Index-Related Risk"), SectionType.RISK_FACTOR),
        (("Index Methodology", "Rebalancing"), SectionType.REBALANCING),
    ],
)
def test_classifies_only_approved_sections(heading, expected):
    assert classify_section(section(heading)) is expected


def test_excludes_performance_and_holdings_tables() -> None:
    result = chunk_document_sections(
        context(),
        (
            section(("Principal Risks",), "risk text"),
            section(("Historical Performance",), "performance text"),
            section(("Portfolio Holdings",), "holding rows"),
        ),
        counter=WhitespaceTokenCounter(),
    )
    assert {chunk.section_type for chunk in result.chunks} == {
        SectionType.RISK_FACTOR
    }
```

Also prove:

- exact_text remains unchanged;
- embedding_text contains Entity name, document type, section path, and exact_text;
- overlap never crosses a section boundary;
- a risk bullet remains intact;
- duplicate paragraphs inside one document are removed by content hash;
- 21 required chunks return REVIEW_REQUIRED_CHUNK_BUDGET without truncating the 21st chunk;
- different products are never mixed.

- [ ] **Step 2: Run the chunking tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/documents/test_chunking.py -q
```

Expected: FAIL because chunking.py does not exist.

- [ ] **Step 3: Implement the explicit section registry**

Map only the approved section types from the spec:

- legal_structure;
- investment_objective;
- investment_strategy;
- index_methodology;
- theme_definition;
- selection_rules;
- rebalancing;
- risk_factor;
- official_update;
- change_history;
- conditional currency_hedge, derivatives_leverage, governance.

Explicitly reject fees, distribution, taxation, accounting, legal boilerplate, full holdings, performance tables, financial statements, and market commentary.

- [ ] **Step 4: Implement deterministic chunk assembly**

Split on paragraph and list boundaries. Use the injected counter for budgets. Build:

```python
embedding_text = "\n".join(
    (
        context.canonical_entity_name,
        context.document_type,
        " > ".join(section.heading_path),
        exact_text,
    )
)
```

Store exact_text separately. Hash exact_text, not embedding_text, for Evidence identity. Return a ChunkingResult containing chunks, coverage_status, reason_code, and observed_chunk_count.

- [ ] **Step 5: Run document unit tests**

Run:

```bash
.venv/bin/python -m pytest tests/documents -q
```

Expected: PASS.

- [ ] **Step 6: Commit the bounded chunker**

```bash
git add src/financial_agent/documents/chunking.py tests/documents/test_chunking.py
git diff --cached --check
git commit -m "feat: chunk approved document sections"
```

---

### Task 5: Persist Document Corpus Records Idempotently

**Files:**
- Create: src/financial_agent/db/repositories/documents.py
- Modify: src/financial_agent/db/repositories/__init__.py
- Create: tests/db/test_document_repository.py
- Modify: tests/fixtures/db/synthetic_dataset.py

**Interfaces:**
- Consumes: DocumentCorpusRecord containing one document profile, one or more exact Entity bindings, approved chunks, and coverage updates.
- Produces: immutable rows in document_record, document_profile, document_entity_binding, document_chunk, and document_coverage.
- Public API:

```python
class DocumentCorpusRepository:
    async def append_corpus(self, corpus: DocumentCorpusRecord) -> None: ...
    async def get_coverage(
        self,
        dataset_version: str,
        entity_id: str,
        required_document_role: DocumentRole,
    ) -> DocumentCoverageDraft: ...
    async def list_chunks(
        self,
        dataset_version: str,
        document_id: str,
    ) -> tuple[DocumentChunkDraft, ...]: ...
```

DocumentCorpusRecord contains dataset_version, document_id, source_id,
document_title, document_type, object_key, content_checksum, published_at,
available_at, profile, entity_bindings, chunks, required_document_role, and
coverage. Its profile and every child record must carry the same
dataset_version and document_id.

- [ ] **Step 1: Write failing repository tests**

Prove:

```python
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_document_corpus_round_trips_idempotently(
    repository_engine,
    document_corpus_record,
) -> None:
    repository = DocumentCorpusRepository(repository_engine)

    await repository.append_corpus(document_corpus_record)
    await repository.append_corpus(document_corpus_record)

    coverage = await repository.get_coverage(
        document_corpus_record.dataset_version,
        document_corpus_record.entity_bindings[0].entity_id,
        document_corpus_record.required_document_role,
    )
    assert coverage.coverage_status is CoverageStatus.INDEXED
    assert await repository.list_chunks(
        document_corpus_record.dataset_version,
        document_corpus_record.document_id,
    ) == document_corpus_record.chunks
```

Also test:

- same ID with changed bytes raises DocumentCorpusConflict;
- chunk content_hash must match exact_text;
- indexed coverage must point to the same document and Entity binding;
- negative coverage persists with scope Evidence and no document;
- another dataset_version cannot reuse foreign Entity, document, or Evidence rows;
- a validated or active dataset rejects insert/update/delete.

- [ ] **Step 2: Run the repository tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/db/test_document_repository.py -q
```

Expected: FAIL because DocumentCorpusRepository does not exist.

- [ ] **Step 3: Implement one-transaction append**

Within one transaction:

1. verify dataset status is building;
2. insert document_record and document_profile;
3. insert exact Entity bindings;
4. insert chunks in ordinal order;
5. insert coverage;
6. force deferred constraints before commit.

On unique violations, load the stored aggregate and compare canonical bytes. Return on exact identity; raise DocumentCorpusConflict otherwise. Never update an existing row to make it match.

- [ ] **Step 4: Run focused PostgreSQL tests**

Run:

```bash
.venv/bin/python -m pytest tests/db/test_document_repository.py tests/db/test_evidence_repository.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit repository support**

```bash
git add src/financial_agent/db/repositories/documents.py src/financial_agent/db/repositories/__init__.py tests/db/test_document_repository.py tests/fixtures/db/synthetic_dataset.py
git diff --cached --check
git commit -m "feat: persist document corpus records"
```

---

### Task 6: Add Safe Keyword and Vector Candidate Retrieval

**Files:**
- Create: src/financial_agent/retrieval/__init__.py
- Create: src/financial_agent/retrieval/documents.py
- Create: tests/retrieval/__init__.py
- Create: tests/retrieval/test_document_search.py
- Create: tests/fixtures/document_corpus.py

**Interfaces:**
- Consumes:
  - DocumentSearchRequest;
  - query text;
  - optional externally supplied query embedding;
  - approved model_id and model_version when Vector search is requested.
- Produces separate keyword_hits, vector_hits, and evaluation-only fused_hits.
- Public API:

```python
@dataclass(frozen=True, slots=True)
class DocumentSearchRequest:
    dataset_version: str
    entity_ids: tuple[str, ...]
    claim_type: str
    section_types: tuple[SectionType, ...]
    cutoff_date: date
    top_k: int = 5
    query_embedding: tuple[float, ...] | None = None
    model_id: str | None = None
    model_version: str | None = None

class DocumentCandidateRepository:
    async def search_keyword(
        self, request: DocumentSearchRequest, query_text: str
    ) -> tuple[DocumentCandidateHit, ...]: ...

    async def search_vector(
        self, request: DocumentSearchRequest
    ) -> tuple[DocumentCandidateHit, ...]: ...

def reciprocal_rank_fusion(
    keyword_hits: tuple[DocumentCandidateHit, ...],
    vector_hits: tuple[DocumentCandidateHit, ...],
    *,
    rrf_k: int = 60,
    top_k: int = 5,
) -> tuple[DocumentCandidateHit, ...]: ...
```

DocumentCandidateHit contains dataset_version, entity_id, document_id,
chunk_id, section_type, exact_text, source_id, source_locator,
published_at, available_at, effective_from, effective_to, document_version,
cutoff_eligible, publisher_approved, keyword_rank, vector_rank, fused_score,
and evidence_id. evidence_id is always null at candidate-search time.

- [ ] **Step 1: Write failing retrieval-safety tests**

Create synthetic product, index, policy, late-document, wrong-product, and unofficial-source fixtures. Prove:

```python
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_vector_search_filters_before_distance_ranking(
    candidate_repository,
    risk_request,
) -> None:
    hits = await candidate_repository.search_vector(risk_request)

    assert hits
    assert {hit.entity_id for hit in hits} == {"selected-etf"}
    assert all(hit.section_type is SectionType.RISK_FACTOR for hit in hits)
    assert all(hit.cutoff_eligible for hit in hits)
    assert all(hit.publisher_approved for hit in hits)


def test_rrf_is_stable_and_does_not_create_claims() -> None:
    fused = reciprocal_rank_fusion(keyword_hits(), vector_hits(), top_k=5)
    assert [hit.chunk_id for hit in fused] == [
        "risk-specific",
        "risk-index",
        "risk-currency",
    ]
    assert all(hit.evidence_id is None for hit in fused)
```

Also prove:

- request without model metadata cannot run Vector search;
- model dimension mismatch remains a database error;
- after-cutoff and wrong-Entity chunks are filtered before similarity;
- section_type filtering excludes performance and holdings;
- identical rank inputs produce stable document_id/chunk_id tie-breaks;
- candidate hits contain source locator fields but are not EvidenceRecord objects.

- [ ] **Step 2: Run retrieval tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/retrieval/test_document_search.py -q
```

Expected: FAIL because the retrieval package does not exist.

- [ ] **Step 3: Implement metadata-first SQL**

Join document_embedding to document_chunk, document_profile, document_entity_binding, document_record, source_record, and dataset_version. Apply dataset, Entity, section, source eligibility, cutoff, effective interval, model, and exact chunk hash predicates before ordering by distance.

Keyword search uses the existing normalized_search_text trigram index and the same metadata predicates. Do not query across all documents and filter in Python.

- [ ] **Step 4: Implement deterministic evaluation fusion**

Use reciprocal rank fusion only to compare retrieval modes in Phase 0. The function returns candidate hits and never creates Evidence, relation, or Claim rows. Tie-break equal fused scores by document_id then chunk_id.

- [ ] **Step 5: Run retrieval and existing pgvector tests**

Run:

```bash
.venv/bin/python -m pytest tests/retrieval/test_document_search.py tests/db/test_fact_document_search_schema.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit candidate retrieval**

```bash
git add src/financial_agent/retrieval tests/retrieval tests/fixtures/document_corpus.py
git diff --cached --check
git commit -m "feat: retrieve bounded document candidates"
```

---

### Task 7: Build the Phase 0 Retrieval Safety Evaluation

**Files:**
- Create: tests/gold/document_retrieval_cases.json
- Create: tests/retrieval/test_document_retrieval_eval.py
- Create: scripts/verify_document_retrieval_pipeline.py
- Modify: docs/planning/STATUS.md

**Interfaces:**
- Consumes: committed synthetic corpus fixtures, deterministic query vectors, and DocumentCandidateRepository.
- Produces: a JSON report with case_id, mode, top_5_chunk_ids, gold_rank, Entity/source/time/version violations, and corpus coverage counts.
- Does not produce: production embeddings, official-document snapshots, activation records, or supported status for the three real questions.

- [ ] **Step 1: Define the exact synthetic gold cases**

Create these cases:

```json
{
  "schema_version": 1,
  "cases": [
    {
      "id": "DOC-FUND-001-structure",
      "entity_ids": ["policy-fund-one"],
      "claim_type": "structure",
      "section_types": ["legal_structure"],
      "gold_chunk_ids": ["policy-structure"]
    },
    {
      "id": "REL-THEME-001-history",
      "entity_ids": ["aerospace-index-one"],
      "claim_type": "theme_relation_evidence_span",
      "section_types": ["theme_definition", "change_history"],
      "gold_chunk_ids": ["aerospace-change"]
    },
    {
      "id": "REL-CORP-001-risk",
      "entity_ids": ["selected-etf"],
      "claim_type": "product_risk_factor",
      "section_types": ["risk_factor"],
      "gold_chunk_ids": ["selected-etf-risk"]
    }
  ]
}
```

Add negative fixtures for wrong product, unofficial publisher, after-cutoff document, stale version, name-only theme match, generic market commentary, performance table, and generated summary.

- [ ] **Step 2: Write the failing evaluation test**

```python
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_phase0_document_cases_pass_top5_and_safety_gates(
    loaded_document_corpus,
) -> None:
    report = await evaluate_cases(loaded_document_corpus)

    assert report.case_count == 3
    assert report.gold_in_top5_count == 3
    assert report.entity_violation_count == 0
    assert report.source_violation_count == 0
    assert report.temporal_violation_count == 0
    assert report.version_violation_count == 0
    assert report.relationships_created == 0
```

- [ ] **Step 3: Run the evaluation test and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/retrieval/test_document_retrieval_eval.py -q
```

Expected: FAIL because the evaluator and gold catalog do not exist.

- [ ] **Step 4: Implement the offline verifier**

The CLI accepts:

```text
--database-url
--gold tests/gold/document_retrieval_cases.json
--output tmp/document-retrieval-report.json
```

It refuses an output path tracked by Git, sorts report rows by case_id and mode, and exits non-zero when any gold span is outside Top 5 or any safety violation is non-zero. It records that deterministic fixture vectors validate pipeline behavior, not embedding-model quality.

- [ ] **Step 5: Run the Phase 0 verifier**

Run:

```bash
.venv/bin/python -m pytest tests/retrieval/test_document_retrieval_eval.py -q
.venv/bin/python scripts/verify_document_retrieval_pipeline.py --database-url "$TEST_DATABASE_URL" --gold tests/gold/document_retrieval_cases.json --output tmp/document-retrieval-report.json
```

Expected: 3/3 gold cases in Top 5, zero safety violations, and the report remains untracked.

- [ ] **Step 6: Update status without overstating support**

Record in docs/planning/STATUS.md:

- Phase 0 synthetic corpus and retrieval safety pipeline passed;
- no production embedding model is approved;
- no official document population is complete;
- DOC-FUND-001, REL-THEME-001, and REL-CORP-001 remain requires_additional_data and current_db_execution=not_run;
- the next required decision is an official-source and embedding benchmark plan.

- [ ] **Step 7: Commit the Phase 0 verification gate**

```bash
git add tests/gold/document_retrieval_cases.json tests/retrieval/test_document_retrieval_eval.py scripts/verify_document_retrieval_pipeline.py docs/planning/STATUS.md
git diff --cached --check
git commit -m "test: verify document retrieval safety"
```

---

### Task 8: Run the Phase 0 Completion Gate

**Files:**
- Modify only if a verified status correction is required: docs/planning/STATUS.md
- Do not add generated reports, official files, embeddings, or databases.

**Interfaces:**
- Consumes: all commits from Tasks 1 through 7.
- Produces: a reviewable branch with no staged or untracked generated data and a recorded list of deferred production decisions.

- [ ] **Step 1: Run focused tests**

```bash
.venv/bin/python -m pytest tests/documents tests/retrieval tests/db/test_document_repository.py tests/db/test_fact_document_search_schema.py tests/ingestion/test_official_question_gates.py -q
```

Expected: PASS.

- [ ] **Step 2: Run ordinary non-live regression**

```bash
.venv/bin/python -m pytest -m "not organizer_data and not object_storage and not ncp_integration and not official_data and not performance" -q
```

Expected: PASS.

- [ ] **Step 3: Verify migrations and generated contracts**

```bash
.venv/bin/python scripts/verify_database_migrations.py
.venv/bin/python scripts/export_database_objects.py --check
.venv/bin/python scripts/export_contract_schemas.py --check
```

Expected: all checks pass.

- [ ] **Step 4: Audit forbidden files and secrets**

Run:

```bash
git diff --check
git status --short
git diff --name-only origin/codex/stage03-local-completion...HEAD
```

Confirm manually that no path under data, no organizer workbook, competition PDF, official raw capture, generated embedding, database, environment file, credential, or retrieval output is staged.

- [ ] **Step 5: Inspect the complete branch diff**

Run:

```bash
git diff origin/codex/stage03-local-completion...HEAD
```

Verify every changed line traces to the approved Phase 0 corpus foundation. Do not include unrelated Stage 03 local-completion edits.

- [ ] **Step 6: Record completion without activating data**

If and only if every required check passes, mark the Phase 0 foundation complete in docs/planning/STATUS.md. Keep the production document corpus, embedding model, official source coverage, and real question execution explicitly incomplete.

- [ ] **Step 7: Commit a status-only correction if Step 6 changed it**

```bash
git add docs/planning/STATUS.md
git diff --cached --check
git commit -m "docs: record document corpus phase zero"
```

Skip this commit when STATUS.md already contains the exact verified state.

## Plan Completion Gate

The plan is complete only when:

1. the stale REL-THEME-001 rule is corrected without changing its question text;
2. migration 0007 upgrades, downgrades, and re-upgrades cleanly;
3. document profiles, exact Entity bindings, coverage states, and exact section locators are immutable and dataset-version scoped;
4. only approved Claim sections are chunked and soft-limit overflow fails into review rather than truncation;
5. document corpus writes are idempotent and conflict-detecting;
6. keyword and Vector candidates are metadata-filtered before ranking;
7. all three synthetic document families place the gold span in Top 5 with zero Entity, source, time, version, or relation-safety violations;
8. the ordinary non-live suite and artifact checks pass;
9. no raw official data, organizer file, PDF, embedding, database, secret, or generated report is committed;
10. real question support remains unchanged until official source and embedding benchmarks pass.

## Follow-Up Plans

After this plan passes, create separate approved plans in this order:

1. official source and usage-condition feasibility for the three Claim families;
2. multilingual embedding benchmark and model approval ADR;
3. domestic ETF minimal-corpus population;
4. public-fund minimal-corpus population;
5. overseas ETF minimal-corpus population;
6. runtime document-search and Evidence-span promotion.

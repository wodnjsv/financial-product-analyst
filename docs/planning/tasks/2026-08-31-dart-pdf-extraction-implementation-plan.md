# DART PDF Extraction and KODEX 200 Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deterministically extract page- and section-located text from the captured KODEX 200 DART prospectus, pass only approved concise-first sections to the existing chunker, and prove each chunk can be traced through product, document, source, version, Vector identity, and Evidence origin metadata.

**Architecture:** Add one `pdfplumber` adapter that converts a text-layer PDF into immutable page lines and table cells, one pure section assembly and concise-first selection layer, and one DART coordinator that produces an existing `DocumentCorpusRecord` plus a canonical quality report without writing a database. Reuse the existing chunker, PostgreSQL document schema, synthetic Vector fixtures, metadata-filtered retrieval, and Evidence foreign keys rather than creating parallel storage models.

**Tech Stack:** Python 3.12, `pdfplumber` 0.11.x, dataclasses, pytest 8, existing SQLAlchemy/PostgreSQL/pgvector repositories, Poppler rendering for manual PDF verification.

**Spec:** [DART PDF Section Extraction Design](../specs/2026-08-31-dart-pdf-section-extraction-design.md)

## Global Constraints

- Keep the KODEX 200 PDF, extracted text, generated report, embeddings, and local database outside Git.
- Do not read or expose `api.txt`; the captured PDF already exists and this task performs no live download.
- Do not use OCR, LLM extraction, semantic heading inference, or manager/issuer fallback sources.
- Do not activate a dataset or write NCP, Object Storage, Fuseki, Graph, or production Vector state.
- Keep PostgreSQL authoritative; Vector and Graph remain projections.
- Preserve the `2026-08-24` cutoff and the exact pre-bound KODEX 200 entity `domestic-etf:KR7069500007`.
- Prefer the concise `요약정보` area and use full-document sections only for missing approved Claim types.
- Preserve source page, section path, character span, exact text, and checksum for every selected section and chunk.
- Keep the existing 300-800 token target, same-section 75-token overlap, 8-15 target chunks, and 20-chunk soft limit.
- Vector similarity must create zero Evidence records, Claims, or Graph relations by itself.
- Use tests first and observe the expected failure before each production change.
- No product-wide download is part of this plan.

---

### Task 1: Add the PDF dependency and immutable extraction contracts

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements/ingestion.lock`
- Create: `src/financial_agent/documents/pdf_extraction.py`
- Modify: `src/financial_agent/documents/__init__.py`
- Create: `tests/documents/test_pdf_extraction.py`

**Interfaces:**
- Consumes: local PDF bytes and page-layout values supplied by the later `pdfplumber` adapter.
- Produces: `PdfTextLine`, `PdfTableRow`, `PdfPageLayout`, `ExtractedPdfDocument`, `PdfExtractionError`, and `assemble_pdf_sections(pages, *, source_checksum, extraction_version)`.

- [ ] **Step 1: Add failing contract tests**

Add tests that construct page layouts directly, without mocking `pdfplumber`:

```python
def test_assembled_sections_round_trip_to_canonical_document_text() -> None:
    pages = (
        PdfPageLayout(
            page_number=1,
            lines=(
                PdfTextLine("[요약정보]", 10.0, 16.0, True),
                PdfTextLine("투자목적 및 투자전략", 30.0, 12.0, True),
                PdfTextLine("KOSPI200을 추종합니다.", 50.0, 10.0, False),
            ),
            table_rows=(),
        ),
    )

    result = assemble_pdf_sections(
        pages,
        source_checksum="a" * 64,
        extraction_version="pdfplumber-layout-v1",
    )

    assert result.page_count == 1
    assert result.text_checksum == sha256(result.canonical_text.encode()).hexdigest()
    for section in result.sections:
        assert result.canonical_text[
            section.character_start : section.character_end
        ] == section.exact_text
```

Also test rejection of duplicate/out-of-order page numbers, blank extraction
version, malformed SHA-256, empty required page text, and invalid character
ranges. The production change that makes these tests pass is the new immutable
contract and its validation.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/documents/test_pdf_extraction.py -q
```

Expected: collection fails because `financial_agent.documents.pdf_extraction`
does not exist.

- [ ] **Step 3: Add the bounded dependency**

Add this optional ingestion dependency:

```toml
"pdfplumber>=0.11.9,<0.12",
```

Add this synthetic-PDF-only development dependency:

```toml
"reportlab>=4.4,<5",
```

Resolve and pin `pdfplumber`, `reportlab`, and only their required transitive
dependencies in `requirements/ingestion.lock`. Install the updated ingestion
and development extras into the existing worktree environment. Do not add OCR
packages.

- [ ] **Step 4: Implement the immutable contracts and pure assembler skeleton**

Create frozen dataclasses with these exact fields:

```python
@dataclass(frozen=True, slots=True)
class PdfTextLine:
    text: str
    top: float
    dominant_size: float
    emphasized: bool


@dataclass(frozen=True, slots=True)
class PdfTableRow:
    cells: tuple[str | None, ...]
    top: float
    bottom: float


@dataclass(frozen=True, slots=True)
class PdfPageLayout:
    page_number: int
    lines: tuple[PdfTextLine, ...]
    table_rows: tuple[PdfTableRow, ...]


@dataclass(frozen=True, slots=True)
class ExtractedPdfDocument:
    canonical_text: str
    page_count: int
    text_page_count: int
    sections: tuple[ExtractedSection, ...]
    source_checksum: str
    text_checksum: str
    extraction_method: str
    extraction_version: str
    issues: tuple[str, ...]
```

Use `PdfExtractionError(code, detail)` with stable codes. The first minimal
assembler may recognize only the test headings and must build offsets from the
canonical text it returns.

- [ ] **Step 5: Run contracts and existing chunking tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/documents/test_pdf_extraction.py \
  tests/documents/test_chunking.py -q
```

Expected: all pass, including the existing 63 chunking tests.

- [ ] **Step 6: Commit Task 1**

Stage only the five Task 1 paths, inspect the cached diff, and commit:

```text
feat: add PDF extraction contracts
```

---

### Task 2: Implement deterministic `pdfplumber` page, line, and table extraction

**Files:**
- Modify: `src/financial_agent/documents/pdf_extraction.py`
- Modify: `tests/documents/test_pdf_extraction.py`

**Interfaces:**
- Consumes: `Path` to a verified text-layer PDF.
- Produces: `read_pdf_layout(pdf_path) -> tuple[PdfPageLayout, ...]` and `extract_pdf_sections(pdf_path, *, extraction_version) -> ExtractedPdfDocument`.

- [ ] **Step 1: Add failing adapter tests**

Test the public API against a small synthetic PDF generated under `tmp_path`
with `reportlab` only as a test dependency. The fixture must contain:

- a title and numbered Korean headings;
- a two-column `요약정보` row for `투자목적 및 투자전략`;
- a `주요투자위험` table with two named risk rows; and
- an excluded fee and historical-performance row.

Representative assertions:

```python
result = extract_pdf_sections(
    synthetic_prospectus,
    extraction_version="pdfplumber-layout-v1",
)

assert result.page_count == 2
assert result.text_page_count == 2
assert {section.heading_path[-1] for section in result.sections} >= {
    "투자목적 및 투자전략",
    "주요투자위험",
}
assert all(section.page_start and section.page_start >= 1 for section in result.sections)
```

Add failure tests for a non-PDF file, encrypted/unreadable input, a page with no
usable text, and a table row whose cell geometry cannot be reproduced.

- [ ] **Step 2: Run adapter tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/documents/test_pdf_extraction.py -k 'adapter or table or invalid_pdf' -q
```

Expected: failures because the public file adapter and table reconstruction do
not exist.

- [ ] **Step 3: Implement the `pdfplumber` adapter**

Use `page.extract_text_lines(return_chars=True, strip=True)` for line text and
character font evidence. Use `page.find_tables()` and table bounding boxes to
extract cell rows in stable top-to-bottom, left-to-right order. Convert only
plain Python values into `PdfPageLayout`; close the PDF before section assembly.

Reject:

- zero pages;
- a required page with no usable line or table-cell text;
- non-finite geometry;
- a page-number discontinuity; and
- a source whose bytes change while being read.

Never call OCR. Set `extraction_method="pdf_text_layer"`.

- [ ] **Step 4: Implement DART heading and table-section assembly**

Recognize only deterministic structural labels:

```text
제N부
N.
가.
[요약정보]
투자목적 및 투자전략
집합투자기구의 투자목적
집합투자기구의 투자전략
주요투자위험
집합투자기구의 투자위험
```

For a concise two-column row, use the first nonblank cell as the heading and
the next nonblank cell as exact section text. For a principal-risk table,
preserve each risk label and body cell in source row order and join only with
newlines; do not add summary prose. Ignore table rows whose headings are not in
the approved or explicitly excluded vocabulary.

Build one canonical text stream from the emitted page blocks and calculate all
section offsets from that exact stream. Require a substring round trip before
returning.

- [ ] **Step 5: Run focused and document tests**

Run:

```bash
.venv/bin/python -m pytest tests/documents/test_pdf_extraction.py tests/documents -q
```

Expected: all pass with no warning or skipped extraction test.

- [ ] **Step 6: Commit Task 2**

Commit only the extractor and its tests:

```text
feat: extract structured DART PDF sections
```

---

### Task 3: Add concise-first section selection and connect the existing chunker

**Files:**
- Create: `src/financial_agent/documents/section_selection.py`
- Modify: `src/financial_agent/documents/chunking.py`
- Modify: `src/financial_agent/documents/__init__.py`
- Create: `tests/documents/test_section_selection.py`
- Modify: `tests/documents/test_chunking.py`

**Interfaces:**
- Consumes: extracted DART sections and requested `SectionType` values.
- Produces: `SectionSelectionResult` and `select_canonical_claim_sections(sections, *, requested_section_types)`.

- [ ] **Step 1: Add failing concise-first tests**

Use extracted-section fixtures with both summary and full-document copies:

```python
result = select_canonical_claim_sections(
    (
        extracted(("요약정보", "투자목적 및 투자전략"), "summary strategy"),
        extracted(("제2부", "집합투자기구의 투자전략"), "full strategy"),
        extracted(("제2부", "집합투자기구의 투자위험"), "full risk"),
    ),
    requested_section_types=frozenset(
        {SectionType.INVESTMENT_STRATEGY, SectionType.RISK_FACTOR}
    ),
)

assert [item.exact_text for item in result.selected_sections] == [
    "summary strategy",
    "full risk",
]
assert result.missing_section_types == frozenset()
```

Add tests proving that:

- exact duplicate paragraphs are selected once;
- a summary section never fills an unrelated Claim;
- full text fills only a missing Claim type;
- fees, performance, manager biography, general notices, holdings, financial
  statements, and appendices are excluded;
- selection is deterministic under reversed input order; and
- missing requested types return stable reason codes.

- [ ] **Step 2: Run selection tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/documents/test_section_selection.py -q
```

Expected: collection fails because the selection module does not exist.

- [ ] **Step 3: Extend exact DART heading aliases**

Update only the exact alias normalization needed by the sample. Strip known
structural numbering before exact comparison; do not add fuzzy or substring
classification. Add explicit aliases for the four observed DART headings from
the design.

- [ ] **Step 4: Implement selection**

Create:

```python
@dataclass(frozen=True, slots=True)
class SectionSelectionResult:
    selected_sections: tuple[ExtractedSection, ...]
    excluded_section_keys: tuple[str, ...]
    missing_section_types: frozenset[SectionType]
    reason_codes: tuple[str, ...]
```

Use `classify_section` as the sole section-type authority. Treat a heading path
containing normalized `요약정보` or `간이투자설명서` as concise. Select concise
sections first, then full sections only for missing types. Preserve source order
within each section type and exact text without rewriting.

- [ ] **Step 5: Verify selection and chunking together**

Add an integration test that passes the selected tuple to
`chunk_document_sections` and asserts:

- every chunk carries `dataset_version`, `document_id`, page range, section
  path, character range, exact text, and content hash;
- no chunk crosses a section; and
- excluded prose produces zero chunks.

Run:

```bash
.venv/bin/python -m pytest \
  tests/documents/test_section_selection.py \
  tests/documents/test_chunking.py \
  tests/documents/test_pdf_extraction.py -q
```

- [ ] **Step 6: Commit Task 3**

Commit:

```text
feat: select concise DART claim sections
```

---

### Task 4: Build an evidence-ready DART corpus and lineage quality report

**Files:**
- Create: `src/financial_agent/ingestion/document_sources/dart_pipeline.py`
- Modify: `src/financial_agent/ingestion/document_sources/__init__.py`
- Create: `tests/ingestion/document_sources/test_dart_pipeline.py`
- Modify: `tests/fixtures/document_corpus.py`
- Modify: `tests/retrieval/test_document_search.py`
- Modify: `tests/db/test_document_repository.py`
- Modify: `tests/db/test_evidence_repository.py`

**Interfaces:**
- Consumes: verified PDF, bound document/source/product metadata, requested Claim sections, and an injected token counter.
- Produces: `DartProspectusContext`, `DartProspectusQualityReport`, `DartProspectusProcessingResult`, and `process_dart_prospectus(...)` with an existing `DocumentCorpusRecord` ready for later persistence.

- [ ] **Step 1: Add failing coordinator and metadata-envelope tests**

Define the wished-for context in tests:

```python
context = DartProspectusContext(
    dataset_version="documents-kodex200-v1",
    entity_id="domestic-etf:KR7069500007",
    canonical_entity_name="삼성 KODEX 200증권상장지수투자신탁[주식]",
    document_id="dart:20260716000161:full-prospectus",
    document_type="full_prospectus",
    document_version="2026-07-03",
    source_id="source:dart:20260716000161",
    source_object_key="documents/dart/20260716000161/full-prospectus.pdf",
    source_content_checksum="c08febdb9c2d7d9a5bf19d674d356c4da4a46b80ebfc3071331b6e073d1e07c7",
    publisher_id="institution:dart",
    publisher_role=PublisherRole.REGULATOR_DISCLOSURE,
    published_at=datetime(2026, 7, 16, tzinfo=UTC),
    available_at=datetime(2026, 7, 16, tzinfo=UTC),
    effective_from=date(2026, 7, 16),
    effective_to=None,
    original_language="ko",
    required_document_role=DocumentRole.PRODUCT_FULL,
    budget_scope_id="domestic-etf:KR7069500007",
)
```

Assert that `result.corpus` contains the same dataset, entity binding,
document, source, object key, version, publisher role, dates, coverage role,
and chunks; that every chunk has a complete locator and content hash; and that
`evidence_id` is absent before Evidence promotion.

- [ ] **Step 2: Run coordinator tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/ingestion/document_sources/test_dart_pipeline.py -q
```

Expected: collection fails because `dart_pipeline` does not exist.

- [ ] **Step 3: Implement the coordinator and canonical report**

`process_dart_prospectus` must:

1. verify the PDF checksum against the bound object metadata;
2. extract sections;
3. select concise-first approved sections;
4. call the existing chunker;
5. construct stable document profile, entity binding, coverage, and record
   hashes using existing repository payload semantics; and
6. return a report with no source prose or embedding values.

The report contains only identifiers, counts, section types, page ranges,
hashes, pass/fail booleans, and stable reason codes. It must expose individual
gates for extraction, locator round trip, required Claim coverage, excluded
section leakage, chunk budget, metadata completeness, exact Vector identity,
Evidence readiness, and deterministic rerun.

- [ ] **Step 4: Add KODEX-shaped cross-store lineage tests**

Extend the existing synthetic corpus fixture with a KODEX-shaped product,
document, source, publisher, chunk, and deterministic three-dimensional
embedding. Test these invariants against a disposable PostgreSQL database:

```text
dataset_version + document_id + chunk_id + content_hash
```

- exact tuple inserts and retrieves;
- changing any one field rejects the embedding foreign key;
- metadata-filtered risk retrieval returns the KODEX chunk;
- a closer wrong-product, wrong-document, wrong-version, wrong-source,
  wrong-effective-time, or wrong-dataset chunk is excluded; and
- the candidate hit still carries `evidence_id=None`.

Create a document-span Evidence record through the existing Evidence
repository and assert that `evidence_document_origin` maps its `evidence_id` to
the exact KODEX `chunk_id`, page, section, source, and dataset. This is an
integration assertion, not a new Vector column.

- [ ] **Step 5: Verify non-DB and PostgreSQL lineage tests**

Run the non-DB coordinator test first:

```bash
.venv/bin/python -m pytest \
  tests/ingestion/document_sources/test_dart_pipeline.py \
  tests/retrieval/test_document_search.py -m 'not postgres' -q
```

Then run the named PostgreSQL lineage tests against a fresh disposable local
PostgreSQL 15 cluster. The cluster may live under `/private/tmp`; it must not be
created under tracked `data/` and must be stopped and removed after the test.

- [ ] **Step 6: Commit Task 4**

Commit only coordinator, fixtures, and focused lineage tests:

```text
feat: build traceable DART document corpus
```

---

### Task 5: Add the gated real KODEX 200 verifier and run visual acceptance

**Files:**
- Create: `scripts/verify_dart_pdf_pipeline.py`
- Create: `tests/ingestion/document_sources/test_real_dart_pdf_pipeline.py`
- Modify: `pyproject.toml`
- Modify: `docs/planning/STATUS.md`

**Interfaces:**
- Consumes: `--pdf`, `--context`, and `--output` local paths.
- Produces: one canonical JSON report written atomically outside Git; exit `0` only when all KODEX gates pass.

- [ ] **Step 1: Add failing CLI and gated-real tests**

The CLI test uses a synthetic PDF and context JSON. Assert:

- unknown context fields fail;
- missing required metadata fails;
- output cannot overwrite the input or be placed under a tracked source path;
- report JSON is deterministic and contains no `chunk_text`, PDF prose,
  embedding vector, API key, or raw hidden reasoning; and
- a failed gate exits nonzero while still writing an inspectable report.

Register a `document_data` pytest marker. The real test skips only when
`RUN_DOCUMENT_DATA_TESTS != "1"`; once enabled, a missing PDF or context is a
hard configuration failure.

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/ingestion/document_sources/test_real_dart_pdf_pipeline.py \
  -m 'not document_data' -q
```

Expected: failure because the verifier script and marker do not exist.

- [ ] **Step 3: Implement the verifier**

Use strict JSON parsing into `DartProspectusContext`. Write with a temporary
file in the output directory, `fsync`, and atomic replace. Never print context
contents, source text, or credentials. Print only report path, counts, hashes,
and pass/fail reason codes.

- [ ] **Step 4: Run KODEX 200 twice and compare determinism**

Create an ignored local context for:

```text
PDF: /private/tmp/dart-spike/second-document/kodex-200.pdf
entity_id: domestic-etf:KR7069500007
receipt: 20260716000161
object_key: documents/dart/20260716000161/full-prospectus.pdf
cutoff: 2026-08-24
```

Run the verifier twice to separate ignored output paths and compare their
canonical hashes and all section/chunk identities. Require:

- 68 of 68 text pages;
- investment objective, strategy, tracked-index content, and product-specific
  risk coverage;
- no excluded-section leakage;
- zero locator round-trip failures;
- 8-15 chunks, or an explicit review result no higher than the 20-chunk soft
  limit; and
- complete metadata gates.

- [ ] **Step 5: Visually verify representative source spans**

Render the source pages containing the selected objective/strategy and
principal-risk chunks with the bundled Poppler runtime. Compare at least one
objective/strategy span and three risk spans against the JSON page ranges and
hashes. Record only page numbers, section types, counts, and pass/fail in the
report; do not copy official prose into Git.

If any span is reordered, incomplete, or mixed with excluded material, write a
failing regression test first, fix the smallest parser rule, and rerun the full
KODEX gate twice.

- [ ] **Step 6: Run focused and broad verification**

Run, in order:

```bash
.venv/bin/python -m pytest tests/documents tests/ingestion/document_sources tests/retrieval -q
.venv/bin/python -m pytest -m 'not postgres and not ncp_integration and not official_data and not object_storage and not organizer_data and not document_data' -q
```

Run the focused PostgreSQL document, retrieval, embedding, and Evidence tests
against the disposable local cluster. Do not claim the broader PostgreSQL suite
passed if no database was configured.

- [ ] **Step 7: Update status without overstating scope**

Record the KODEX sample page count, selected section types, chunk count, report
hash, visual review outcome, and exact test results. State explicitly that:

- only one real DART document was evaluated;
- OCR, production embeddings, product-wide corpus capture, Graph projection,
  and dataset activation remain incomplete; and
- passing this gate authorizes a separate product-wide download decision but
  does not perform it.

- [ ] **Step 8: Inspect and commit Task 5**

Verify no `data/`, PDF, context JSON, report JSON, embedding, database, log,
`api.txt`, or secret is staged. Commit:

```text
feat: verify KODEX 200 document extraction
```

---

## Final completion gate

- [ ] All new production functions were introduced by a failing test.
- [ ] The exact KODEX 200 PDF passes twice with identical extraction, section,
  chunk, and report identities.
- [ ] Representative PDF pages visually match selected source spans.
- [ ] Every chunk is traceable to the exact entity, document, source, object,
  publisher, version, dates, and dataset.
- [ ] Deterministic test embeddings reject every mismatched chunk identity.
- [ ] Evidence round-trips from `evidence_id` to the exact chunk and source
  locator; Vector candidates never carry Evidence prematurely.
- [ ] Vector similarity creates zero Graph relations or Claims.
- [ ] Existing 63 chunking tests and all focused document tests pass.
- [ ] PostgreSQL test claims include an explicitly configured disposable DB.
- [ ] Raw official data and secrets remain untracked and unstaged.
- [ ] No product-wide download has started.

---

## 2026-08-31 KODEX 200 risk-table correction

**Approved correction:** Replace the aggregate principal-risk chunks produced
from pages 9–10 with one evidence span per risk row. A risk chunk contains only
its risk label and body. Repeated table headers, page numbers, continuation
markers, and merged-cell numerals are excluded. The KODEX 200 sample is expected
to produce one strategy chunk and five risk chunks. The accepted Claim-based
budget in ADR-0022 replaces every 8–15 target above; there is no minimum chunk
count.

- [x] Add a failing KODEX-shaped table regression test.
- [x] Split risk rows without rewriting official prose.
- [x] Verify six clean KODEX 200 chunks twice with identical identities.
- [x] Visually compare the selected strategy and risk pages and run focused plus
  broad regression tests.

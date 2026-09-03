# DART PDF Section Extraction Design

**Date:** 2026-08-31

**Status:** Approved direction; implementation pending
**Related:** [Vector document corpus design](2026-08-29-vector-document-corpus-design.md), [ADR-0032](../decisions/ADR-0032-use-three-tier-official-document-sources.md), [official document preflight plan](../tasks/2026-08-30-official-document-manifest-preflight-implementation-plan.md)

## 1. Goal

Add the smallest deterministic extraction stage needed to turn an already
captured DART prospectus PDF into page-located `ExtractedSection` values and
pass them to the implemented document chunker. Prove the flow against the
captured KODEX 200 prospectus before using it for any product-wide capture.

The first retained end-to-end flow is:

```text
verified DART PDF
  -> page text and layout extraction
  -> heading hierarchy and section spans
  -> ExtractedSection values
  -> approved-section classification and chunking
  -> deterministic KODEX 200 quality report
```

## 2. Assumptions and observed sample

- The sample is the captured DART full prospectus for KODEX 200 with receipt
  number `20260716000161` and cutoff-eligible source metadata already resolved
  by the document-source flow.
- It is a 68-page PDF with a usable text layer on all 68 pages. A read-only
  `pdfplumber` probe extracted 73,476 characters.
- Its concise `요약정보` area contains the product identity, investment
  objective and strategy, and product-specific principal risks. Full-document
  sections remain available only to fill approved Claims missing from that
  concise area.
- The raw PDF and generated extraction report remain ignored local data. Tests
  use synthetic PDF fixtures or sanitized expected spans, never the official
  source bytes.

## 3. Intended outcome

One command or callable coordinator accepts a verified local DART PDF plus its
already-bound document context and returns:

1. a canonical page-ordered text representation;
2. deterministic page and character locators;
3. hierarchical `ExtractedSection` values;
4. the existing `ChunkingResult`; and
5. a canonical quality report stating whether the sample is eligible for
   product-wide rollout.

The implementation does not download additional products. Product-wide
capture begins only after the KODEX 200 report passes and is reviewed.

## 4. Non-goals

- OCR, scanned-document recovery, generated summaries, or LLM section parsing;
- SEC HTML, 497K, index-methodology, or policy-document parsing;
- production embeddings, real-corpus pgvector population, retrieval quality
  benchmarking, Graph projection, request-time Evidence promotion, or dataset
  activation; deterministic synthetic linkage tests remain in scope;
- extracting fees, AUM, NAV, returns, complete holdings, financial statements,
  or other quantitative tables into Vector chunks;
- inferring product identity from PDF text; or
- downloading every DART document before the sample gate passes.

## 5. Chosen approach

### 5.1 Text-layer extraction with `pdfplumber`

Use a pinned `pdfplumber` dependency because the required output depends on
page geometry, font size, font name, and exact text order. A plain `pypdf`
text call does not expose enough layout evidence for deterministic heading
reconstruction. A general document-AI or OCR stack is unnecessary for the
current sample and would add model variance and storage cost.

The extractor fails closed when a page has no usable text layer, contains
invalid character geometry, or cannot reproduce its extracted span. It emits
`unreadable_document`; it does not silently invoke OCR.

### 5.2 Canonical text and locators

Process pages strictly in PDF order. Reconstruct page lines from characters
using stable vertical and horizontal ordering and normalized layout tolerances.
Preserve the extracted characters; normalize only line joining and recognized
hyphenation needed to reconstruct a word split at a visual line boundary.

The document text joins pages with one explicit page separator. Each section
records:

- `page_start` and `page_end` as one-based PDF pages;
- `character_start` and `character_end` in the canonical document text;
- `exact_text` equal to that canonical span; and
- a heading path built only from recognized headings in the same document.

The extractor must prove
`document_text[character_start:character_end] == exact_text` for every section.

### 5.3 Heading recognition

Recognize a heading only through deterministic document evidence:

- numbered Korean structure such as `제2부`, `7.`, `가.`, and bracketed labels;
- font size or font emphasis distinct from adjacent body text;
- short standalone lines matching an explicit DART prospectus heading
  vocabulary; or
- table labels that are visually isolated and match an approved Claim heading.

Do not use semantic similarity or free-form fuzzy matching. Strip only known
structural numbering before classification. Extend the current exact alias
table only for observed DART variants such as:

- `집합투자기구의 투자목적`;
- `집합투자기구의 투자전략`;
- `투자목적 및 투자전략`; and
- `주요투자위험` or `주요 투자위험`.

Unrecognized headings may remain in the hierarchy but cannot create an
approved `SectionType`.

### 5.4 Concise-section preference and deduplication

Extraction preserves every detected section. A separate deterministic
selection step applies the accepted corpus policy:

1. select approved Claims from the current filing's concise or summary area;
2. calculate which approved Claim section types remain missing;
3. admit full-document sections only for those missing types; and
4. remove exact duplicate paragraphs with the existing content hashes.

This prevents the KODEX 200 summary objective, strategy, and risks from being
indexed again from the full prospectus. It also prevents a general investor
warning from displacing product-specific principal risks.

### 5.5 Existing chunker remains authoritative

Pass the selected `ExtractedSection` tuple to `chunk_document_sections` without
adding a second chunking implementation. Keep the accepted defaults:

- target 300-800 tokens;
- 75-token overlap, restricted to the same section;
- target 8-15 chunks per product scope; and
- soft limit 20, producing `review_required_chunk_budget` rather than silent
  truncation.

The production caller must inject the tokenizer used by the later approved
embedding benchmark. The extraction test may use the existing deterministic
whitespace counter only where exact model-token counts are not asserted.

## 6. Components and interfaces

### `financial_agent.documents.pdf_extraction`

Owns DART PDF text-layer extraction and structure recovery.

```python
extract_pdf_sections(
    pdf_path: Path,
    *,
    extraction_version: str,
) -> ExtractedPdfDocument
```

`ExtractedPdfDocument` contains the canonical text, page count, immutable
section tuple, extraction method/version, source byte checksum, text checksum,
and extraction issues. It validates page and character round trips at
construction time.

### `financial_agent.documents.section_selection`

Owns concise-first selection without changing extracted text.

```python
select_canonical_claim_sections(
    sections: tuple[ExtractedSection, ...],
    *,
    requested_section_types: frozenset[SectionType],
) -> SectionSelectionResult
```

The result records selected sections, missing requested types, excluded section
identities, and stable reason codes.

### `financial_agent.documents.quality`

Owns a canonical, data-free report shape for the KODEX 200 gate. It records
counts, hashes, required heading hits, selected section types, chunk counts,
locator round-trip failures, excluded-section leaks, coverage status, and an
overall pass boolean. The generated real report stays outside Git.

The existing `chunking.py` continues to own classification and chunk assembly;
the DART capture module continues to own only official-object capture.

### 6.1 Cross-store traceability contract

The Vector projection does not need to duplicate every authoritative field in
one physical row. It must carry enough exact keys to reconstruct and verify the
complete record through deterministic PostgreSQL joins.

| Required concept | Authoritative representation |
| --- | --- |
| searchable text | `document.document_chunk.exact_text` and `normalized_search_text` |
| embedding | `search.document_embedding.embedding` |
| product identity | `document_entity_binding.entity_id`; current catalog uses the product's canonical `entity_id` rather than a second `product_id` |
| external product identifiers | `catalog.identifier`, joined through the same `entity_id` and `dataset_version` |
| document identity and type | `document_record.document_id` and `document_type` |
| document version and validity | `document_profile.document_version`, `effective_from`, and `effective_to` |
| chunk identity and order | `document_chunk.chunk_id` and `ordinal` |
| source span | `page_start`, `page_end`, `section_path`, `character_start`, and `character_end` |
| publisher | `source_record.publisher` plus `document_profile.publisher_role` |
| source identity | `document_record.source_id` |
| source object identity | `document_record.object_key` plus `content_checksum`; this is the current equivalent of a conceptual `source_object_id` |
| publication and availability | `document_record.published_at` and `available_at` |
| content version guard | `document_chunk.content_hash` plus `dataset_version` |
| Evidence identity | created during verified Evidence promotion, then linked by `evidence_document_origin.evidence_id -> chunk_id` |

The exact Vector identity is therefore:

```text
dataset_version
document_id
chunk_id
chunk_content_hash
model_id
model_version
```

The five cross-store identities important to the answer path remain
`entity_id`, `document_id`, `chunk_id`, `evidence_id`, and `dataset_version`,
but they do not all exist at the same lifecycle stage. `entity_id`,
`document_id`, `chunk_id`, and `dataset_version` exist before indexing;
`evidence_id` is added only after a retrieved source span passes authority,
entity, time, version, and locator verification.

### 6.2 Metadata envelope and lineage tests

The KODEX 200 gate must test the following stages independently and then as one
lineage chain:

1. **Extraction:** every section and chunk has exact text, page range, section
   path, character range, content hash, document ID, and dataset version.
2. **Document binding:** the document joins to exactly one approved KODEX 200
   entity binding and one approved source record. No title or Vector similarity
   may establish this binding.
3. **Document metadata:** document type, document version, publisher ID and
   role, source ID, object key, published/available time, effective range, and
   cutoff eligibility are all recoverable for every chunk.
4. **Vector projection:** a deterministic test embedding row references the
   exact `(dataset_version, document_id, chunk_id, content_hash)` and fails on
   any mismatched field. This proves metadata linkage only; it does not approve
   an embedding model or claim real semantic-search quality.
5. **Filtered retrieval:** a KODEX 200 risk query is restricted by entity,
   document, dataset, publisher, effective time, and `risk_factor` before
   ranking. A nearer chunk from another product, version, authority, or dataset
   must be rejected.
6. **Evidence promotion:** each accepted hit creates one document-span
   `evidence_id` whose `evidence_document_origin` points to the exact chunk and
   whose locator reproduces the source page, section, and span.
7. **Graph projection boundary:** any later `hasRiskFactor` or `documentedBy`
   edge must reference the same entity, document or chunk, Evidence, and
   dataset identities. Vector similarity alone must create zero Graph edges.

The lineage assertion is:

```text
source object
  -> source_id
  -> document_id
  -> entity_id
  -> chunk_id + content_hash
  -> deterministic test embedding
  -> verified evidence_id
```

Every arrow must be enforced by an existing foreign key or by a focused
validation test. The quality report records a boolean and stable failure reason
for each stage rather than one undifferentiated pass flag.

### 6.3 Correct question execution order

For “KODEX 200의 주요 위험요인을 알려줘”, the safe path is:

1. PostgreSQL exact identity, optionally aided by an already-approved Graph
   product relation, resolves KODEX 200 and its eligible current document.
2. The query fixes `entity_id`, `document_id`, `dataset_version`, publisher,
   effective-time, and `risk_factor` filters.
3. Keyword and Vector retrieval rank chunks only inside that bounded set.
4. The returned chunk and content hash are checked against the PostgreSQL
   document ledger and original source span.
5. Verified document-span Evidence is created and connected to the chunk.
6. Only an approved predicate backed by that Evidence may later be projected
   as a Graph risk relation and supplied to the answer Claim.

Graph may narrow a search using relations already proven from the PostgreSQL
ledger. It must not assert a risk factor first and then use its own unverified
assertion to validate the Vector result.

## 7. Failure handling

| Condition | Result |
| --- | --- |
| File is not a valid PDF | stable extraction error; no sections or chunks |
| Any required page lacks usable text | `unreadable_document`; no OCR fallback |
| Heading hierarchy is inconsistent | stable extraction issue and failed quality gate |
| Required Claim heading is absent | `section_missing` for that Claim |
| Locator round trip fails | hard extraction failure |
| Excluded content enters a chunk | failed quality gate |
| More than 20 product chunks are required | `review_required_chunk_budget` |
| Source checksum or bound context changes | new extraction identity; never overwrite prior result |

Failures do not downgrade source authority, guess headings, or expand the
corpus automatically.

## 8. KODEX 200 acceptance gate

The sample passes only when all of the following are true:

1. all 68 pages yield usable text in stable order;
2. every selected section and every produced chunk round-trips to its exact
   page and character span;
3. the product identity remains the already-bound KODEX 200 entity;
4. investment objective, investment strategy, tracked-index content, and
   product-specific principal risks are selected;
5. the concise area supplies Claims first and duplicate full-document text is
   not selected for the same Claim;
6. fees, historical performance, manager biography, general notices, holdings,
   financial statements, and appendices produce zero chunks;
7. chunks stay within one document, one product, and one section type;
8. normal chunks stay within the injected 300-800 token target, except an
   explicitly reported indivisible unit;
9. total selected chunks are within the 8-15 target, or the report explains why
   the accepted evidence requires up to the soft limit of 20; and
10. rerunning from identical PDF bytes and extraction version produces the same
    canonical text hash, section identities, chunk identities, and report;
11. every chunk reconstructs its entity, document, source, publisher, version,
    validity, object key, and dataset metadata through the approved joins;
12. a deterministic test embedding accepts only the exact chunk identity and
    content hash;
13. accepted document-span Evidence round-trips from `evidence_id` to the exact
    KODEX 200 chunk and source locator; and
14. wrong-product, wrong-document, wrong-version, wrong-source,
    wrong-effective-time, wrong-dataset, and wrong-content-hash candidates are
    all rejected before answer release.

The quality report is necessary but not sufficient: representative objective,
strategy, and risk chunks must also be visually compared with their source PDF
pages before rollout approval.

## 9. Verification strategy

- Unit-test line ordering, heading detection, hierarchy nesting, page spans,
  section selection, duplicate handling, and failure reason codes with small
  generated PDFs.
- Keep a sanitized KODEX 200 expectation fixture containing only headings,
  page numbers, hashes, and counts. Do not commit source prose or PDF bytes.
- Run the existing 63 chunking tests unchanged, then add focused extraction and
  coordinator tests.
- Reuse the existing PostgreSQL document, embedding, and Evidence foreign-key
  tests, adding one KODEX-shaped synthetic lineage case and one mismatch case
  for each identity boundary.
- Run the real KODEX 200 gate only behind an explicit local-data marker and
  ignored PDF path.
- Render and visually inspect the pages supporting representative selected
  spans.

## 10. Product-wide rollout boundary

After the user reviews a passing KODEX 200 report, reuse the same extraction
and chunking path for eligible products in bounded phases:

1. domestic ETFs from DART;
2. public funds from DART;
3. overseas ETFs through a separately approved SEC parser; and
4. official index and policy documents through source-specific parsers.

Coverage is tracked for every organizer product, but only roles allowed by
ADR-0021 are downloaded and indexed. Domestic bonds remain
`not_applicable_current_scope`. Batch capture must be restartable, checksum-
deduplicated, bounded by an explicit disk budget, and must not retain duplicate
representations of the same effective filing.

No product-wide capture is authorized by this design alone. It requires the
sample gate, a measured storage estimate from the resulting canonical objects,
and a separate execution approval.

## 11. Alternatives considered

### OCR-first universal parser

Rejected for the first implementation. The sample already has a complete text
layer, while OCR would add nondeterminism and still require exact source-span
verification.

### Plain text extraction without layout evidence

Rejected because it cannot reliably recover DART heading hierarchy, table risk
labels, or reproducible section boundaries.

### Download all products before implementing extraction

Rejected because it would repeat an unverified document choice and parsing
strategy at corpus scale and consume disk before per-product document and chunk
sizes are measured.

### LLM-based heading and section classification

Rejected because section admission, offsets, and repeatability are deterministic
Evidence boundaries. The LLM must not decide what source text becomes eligible.

## 12. Compatibility with accepted design

This design fills the parser boundary deliberately left open by the Vector
document Phase 0 plan. It preserves the three-tier source policy, one canonical
current document per role, concise-first selection, the 2026-08-24 cutoff,
PostgreSQL Evidence authority, inactive local development, and untracked raw
objects. No Stage 03 or Stage 04 conflict is introduced.
